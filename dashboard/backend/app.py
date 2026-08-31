"""
app.py — Backend FastAPI del dashboard (Fase 4).

Propósito
---------
Expone localmente los datos que ya producen las Fases 0-3 (reutiliza las
mismas estructuras de datos; no duplica lógica de negocio):
  - GET /api/estado               → hay datos? timestamps (para estados vacío/carga)
  - GET /api/resumen              → KPIs y distribución por lote
  - GET /api/pruebas              → listado filtrable (q, estado, limit/offset)
  - GET /api/pruebas/{nombre}     → detalle (tokens OCR etiqueta vs referencia)
  - GET /api/imagen?ruta=...      → imagen original (restringida a la raíz del lote)
  - GET /api/config               → colores del semáforo + reglas (paleta unificada)
  - GET /                         → frontend estático (dashboard/frontend)

El semáforo se evalúa con el MISMO motor de reglas que el Excel
(configuracion.clasificar sobre reglas_cumplimiento.yaml): la paleta vive en
config.yaml → colores y el frontend la consume vía /api/config, así el hex es
idéntico en Excel y dashboard.

Ejecución:
    python dashboard/backend/app.py          (desde la raíz del proyecto)
    → http://127.0.0.1:8000
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path, PureWindowsPath
from urllib.parse import quote, unquote

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ_PROYECTO))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from configuracion import cargar_config, cargar_reglas, clasificar  # noqa: E402
from aprendizaje import GestorAprendizaje, hash_archivo, normalizar_codigo  # noqa: E402

CONFIG = cargar_config()
REGLAS = cargar_reglas()
RUTA_VALIDACION = RAIZ_PROYECTO / "validacion_resultados.json"
RUTA_ESTRUCTURA = RAIZ_PROYECTO / CONFIG.get("fase0", {}).get(
    "archivo_salida", "estructura_detectada.json")
DIR_FRONTEND = RAIZ_PROYECTO / "dashboard" / "frontend"

app = FastAPI(title="Dashboard de validación de pruebas (OCR)", version="1.0")


class SolicitudPipeline(BaseModel):
    ruta: str = Field(min_length=1, max_length=4096)


class SolicitudCorreccion(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    campo: str = Field(default="etiqueta", pattern="^(etiqueta|referencia)$")
    imagen_id: str | None = Field(default=None, max_length=128)
    texto_ocr: str = Field(min_length=1, max_length=4096)
    texto_correcto: str = Field(min_length=1, max_length=4096)


class SolicitudAnotacionRegion(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    imagen_id: str = Field(min_length=1, max_length=128)
    bbox: list[int] = Field(min_length=4, max_length=4)
    texto_correcto: str = Field(min_length=1, max_length=8192)


class SolicitudRevision(BaseModel):
    tipo: str = Field(pattern="^(carpeta|externa)$")
    item_id: str = Field(min_length=1, max_length=128)
    estado: str | None = Field(default=None, pattern="^(por_revisar|completada)$")
    oculto: bool | None = None


class SolicitudRollback(BaseModel):
    version: str | None = Field(default=None, max_length=128)


class SolicitudCorreccionExterna(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    texto_ocr: str = Field(min_length=1, max_length=4096)
    texto_correcto: str = Field(min_length=1, max_length=4096)


_pipeline_lock = threading.Lock()
_externas_lock = threading.Lock()
_pipeline_estado: dict = {
    "estado": "inactivo", "fase": None, "mensaje": None, "ruta": None,
    "iniciado_en": None, "finalizado_en": None, "error": None, "resumen": None,
    "bitacora": None, "porcentaje": 0, "procesadas": 0, "total": 0,
    "restantes": 0, "eta_segundos": None, "transcurrido_segundos": 0,
    "resultados_parciales": [], "imagenes_procesadas": 0, "imagenes_total": 0,
    "imagenes_restantes": 0, "imagen_actual": None, "actualizado_en": None,
}

# ---------------------------------------------------------------------------
# Carga de datos con caché por mtime (refresco automático tras cada pipeline)
# ---------------------------------------------------------------------------

_cache: dict = {"mtime": None, "datos": None}


def _cargar_datos() -> dict | None:
    if not RUTA_VALIDACION.exists():
        return None
    mtime = RUTA_VALIDACION.stat().st_mtime
    if _cache["datos"] is None or mtime != _cache["mtime"]:
        try:
            with open(RUTA_VALIDACION, "r", encoding="utf-8") as f:
                cargados = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(503, f"No se pudieron leer los resultados: {exc}") from exc
        if not isinstance(cargados, dict) or not isinstance(cargados.get("resultados", []), list):
            raise HTTPException(503, "validacion_resultados.json no tiene el formato esperado.")
        _cache["datos"] = cargados
        _cache["mtime"] = mtime
    return _cache["datos"]


def _id_fila(fila: dict) -> str:
    """Id corto y estable; evita colisiones cuando distintos lotes repiten nombre."""
    clave = str(fila.get("ruta") or fila.get("nombre") or "")
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()[:16]


def _partes_portables(ruta: str) -> tuple[str, ...]:
    """Separa rutas POSIX o Windows aunque el servidor corra en otro sistema."""
    if "\\" in ruta:
        return PureWindowsPath(ruta).parts
    return Path(ruta).parts


def _resolver_raiz_datos(datos: dict) -> Path | None:
    """Resuelve la raíz original y, si el proyecto se movió, la reubica localmente."""
    configurada = CONFIG.get("dashboard", {}).get("raiz_datos_permitida")
    declarada = str(configurada or datos.get("raiz") or "")
    if not declarada:
        return None
    directa = Path(declarada).expanduser().resolve()
    if directa.is_dir():
        return directa

    partes = _partes_portables(declarada)
    # Los artefactos de prueba pueden haberse generado en otro SO. Solo se
    # reubican bajo el proyecto actual, nunca fuera de él.
    for marcador in ("datos_prueba",):
        if marcador in partes:
            candidata = RAIZ_PROYECTO.joinpath(*partes[partes.index(marcador):]).resolve()
            if candidata.is_dir() and candidata.is_relative_to(RAIZ_PROYECTO):
                return candidata
    return None


def _reubicar_ruta(ruta: str, datos: dict, raiz: Path) -> Path | None:
    """Reubica una ruta registrada bajo la raíz local equivalente."""
    directa = Path(ruta).expanduser().resolve()
    if directa.exists():
        return directa

    partes_ruta = _partes_portables(ruta)
    partes_raiz_original = _partes_portables(str(datos.get("raiz") or ""))
    n = len(partes_raiz_original)
    if n and tuple(partes_ruta[:n]) == tuple(partes_raiz_original):
        candidata = raiz.joinpath(*partes_ruta[n:]).resolve()
        if candidata.exists() and candidata.is_relative_to(raiz):
            return candidata
    return None


def _resolver_imagen(ruta: str, datos: dict, raiz: Path) -> Path:
    """Convierte una ruta registrada (incluso de otro SO) a su archivo local."""
    registradas = set()
    for fila in datos.get("resultados", []):
        items = list(fila.get("imagenes") or [])
        items.extend(item for item in (fila.get("etiqueta"), fila.get("referencia")) if item)
        registradas.update(str(item["ruta"]) for item in items if item.get("ruta"))
    if ruta not in registradas:
        raise HTTPException(403, "La imagen no forma parte de los resultados procesados.")

    candidata = _reubicar_ruta(ruta, datos, raiz)
    if candidata and candidata.is_file():
        return candidata
    raise HTTPException(404, "Archivo no encontrado; vuelve a ejecutar el pipeline en este equipo.")


def _raiz_publica(datos: dict) -> str | None:
    """Ruta efectiva del equipo actual; nunca muestra como vigente una ruta obsoleta."""
    resuelta = _resolver_raiz_datos(datos)
    return str(resuelta) if resuelta else None


def _capacidad_pipeline() -> dict:
    """Comprueba dependencias sin importar/arrancar los motores pesados."""
    modulos = {
        "OpenCV (cv2)": "cv2",
        "NumPy": "numpy",
        "openpyxl": "openpyxl",
        "PyYAML": "yaml",
    }
    faltantes = [etiqueta for etiqueta, modulo in modulos.items()
                 if importlib.util.find_spec(modulo) is None]
    motores = {
        "paddle": importlib.util.find_spec("paddleocr") is not None,
        "easyocr": importlib.util.find_spec("easyocr") is not None,
    }
    if not any(motores.values()):
        faltantes.append("PaddleOCR o EasyOCR")
    return {"listo": not faltantes, "faltantes": faltantes, "motores": motores}


def _actualizar_pipeline(**cambios) -> None:
    with _pipeline_lock:
        _pipeline_estado.update(cambios)


def _registrar_error_pipeline(ruta: Path, exc: Exception) -> Path:
    """Cumple la bitácora obligatoria del Documento Maestro ante un fallo."""
    ahora = datetime.now()
    archivo = RAIZ_PROYECTO / "errores" / f"{ahora:%Y-%m-%d_%H%M%S}_dashboard_pipeline.md"
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(
        "# Error al ejecutar el pipeline desde el dashboard\n\n"
        f"- Fecha: {ahora.isoformat(timespec='seconds')}\n"
        f"- Carpeta solicitada: `{ruta}`\n"
        f"- Error: `{type(exc).__name__}: {exc}`\n\n"
        "## Qué se intentó\n\nEjecutar las Fases 0–3 desde la vista de carga.\n\n"
        "## Nuevo enfoque\n\nCorregir la causa indicada y reintentar desde el dashboard.\n\n"
        "## Traza técnica\n\n```text\n" + traceback.format_exc() + "\n```\n",
        encoding="utf-8",
    )
    return archivo


def _ejecutar_pipeline_fondo(ruta: Path) -> None:
    inicio = time.monotonic()

    def progreso(fase: str, mensaje: str, detalle: dict | None = None) -> None:
        detalle = dict(detalle or {})
        fila = detalle.pop("resultado", None)
        with _pipeline_lock:
            _pipeline_estado.update(
                fase=fase, mensaje=mensaje,
                transcurrido_segundos=round(time.monotonic() - inicio, 1),
                actualizado_en=datetime.now().isoformat(timespec="milliseconds"),
                **detalle,
            )
            if fila is not None:
                _pipeline_estado["resultados_parciales"].append(_fila_publica(fila))

    try:
        from pipeline import ejecutar_pipeline
        resumen = ejecutar_pipeline(ruta, al_progreso=progreso)
        _cache.update({"mtime": None, "datos": None})
        _actualizar_pipeline(
            estado="completado", fase="completado", mensaje="Procesamiento terminado",
            finalizado_en=datetime.now().isoformat(timespec="seconds"), resumen=resumen,
            porcentaje=100, restantes=0, eta_segundos=0,
            transcurrido_segundos=round(time.monotonic() - inicio, 1),
        )
    except Exception as exc:  # el error se expone y también queda en errores/
        bitacora = _registrar_error_pipeline(ruta, exc)
        _actualizar_pipeline(
            estado="error", mensaje="El procesamiento no pudo completarse",
            finalizado_en=datetime.now().isoformat(timespec="seconds"),
            error=f"{type(exc).__name__}: {exc}", bitacora=str(bitacora),
            eta_segundos=None,
            transcurrido_segundos=round(time.monotonic() - inicio, 1),
        )


def _lote_de(fila: dict) -> str:
    """Nombre de la carpeta contenedora inmediata (el 'lote')."""
    partes = _partes_portables(str(fila["ruta"]))
    return partes[-2] if len(partes) >= 2 else "Sin lote"


def _fila_publica(fila: dict, revisiones: dict | None = None) -> dict:
    """Fila para listado/tabla: ligera + semáforo evaluado con el motor de reglas."""
    clasif = clasificar(fila.get("confianza_ocr_pct"),
                        fila["comparacion"]["resultado"], REGLAS)
    item_id = _id_fila(fila)
    inicial = "completada" if clasif.get("semaforo_global") == "verde" else "por_revisar"
    revision = (revisiones or {}).get(("carpeta", item_id)) or {
        "tipo": "carpeta", "item_id": item_id, "estado": inicial,
        "oculto": False, "actualizado_en": None}
    return {
        "id": item_id,
        "nombre": fila["nombre"],
        "identificador": fila.get("identificador"),
        "nomenclatura": fila.get("nomenclatura"),
        "variante": fila.get("variante"),
        "lote": _lote_de(fila),
        "resultado": fila["comparacion"]["resultado"],
        "confianza_ocr_pct": fila.get("confianza_ocr_pct"),
        "qr_detectado": fila.get("qr_detectado", False),
        "conforme": fila.get("es_conforme"),
        "observaciones": fila.get("observaciones", []),
        "semaforo": clasif.get("semaforo_global"),
        "semaforo_confianza": clasif.get("confianza_ocr"),
        "semaforo_coincidencia": clasif.get("coincidencia_texto"),
        "origen": "carpeta",
        "enlace": f"#/detalle/{item_id}",
        "revision": revision,
    }


def _fila_externa_publica(fila: dict) -> dict:
    completa = (bool(fila.get("coincidencia_exacta")) if fila.get("tipo") == "codigo"
                else float(fila.get("cobertura") or 0) >= 1.0)
    revision = fila.get("revision") or {
        "tipo": "externa", "item_id": fila["id"],
        "estado": "completada" if completa else "por_revisar",
        "oculto": False, "actualizado_en": None}
    if fila.get("tipo") == "codigo":
        resultado = "Código exacto" if fila.get("coincidencia_exacta") else "Código por corregir"
        identificador = fila.get("esperado") or fila.get("imagen")
    else:
        encontrados, esperados = len(fila.get("encontrados", [])), len(fila.get("esperados", []))
        resultado = f"Texto {encontrados}/{esperados} fragmentos"
        identificador = fila.get("imagen")
    return {
        "id": fila["id"], "nombre": fila.get("imagen"),
        "identificador": identificador, "nomenclatura": None, "variante": None,
        "lote": "Pruebas complejas", "resultado": resultado,
        "confianza_ocr_pct": None, "qr_detectado": False, "conforme": completa,
        "observaciones": [], "semaforo": "verde" if completa else "rojo",
        "origen": "externa", "enlace": "#/externas", "revision": revision,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/estado")
def estado():
    datos = _cargar_datos()
    return {
        "hay_datos": datos is not None and len(datos.get("resultados", [])) > 0,
        "total": len(datos.get("resultados", [])) if datos else 0,
        "generado_en": datos.get("generado_en") if datos else None,
        "raiz": _raiz_publica(datos) if datos else None,
        "raiz_origen": datos.get("raiz") if datos else None,
    }


@app.get("/api/config")
def config_dashboard():
    return {
        "colores": CONFIG.get("colores", {}),
        "reglas": REGLAS.get("criterios", {}),
    }


@app.get("/api/pipeline/capacidad")
def capacidad_pipeline():
    return _capacidad_pipeline()


@app.get("/api/pipeline/estado")
def estado_pipeline():
    with _pipeline_lock:
        estado = dict(_pipeline_estado)
        estado["resultados_parciales"] = list(_pipeline_estado["resultados_parciales"])
        if estado["estado"] == "procesando" and estado.get("iniciado_en"):
            inicio = datetime.fromisoformat(estado["iniciado_en"])
            estado["transcurrido_segundos"] = round(
                (datetime.now() - inicio).total_seconds(), 1)
        return estado


@app.get("/api/aprendizaje")
def estado_aprendizaje():
    return GestorAprendizaje(CONFIG).estado()


@app.post("/api/aprendizaje/correcciones")
def corregir_lectura(solicitud: SolicitudCorreccion):
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    fila = next((f for f in datos["resultados"] if _id_fila(f) == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "La prueba indicada no existe.")
    if solicitud.imagen_id:
        item = next((imagen for imagen in fila.get("imagenes", [])
                     if imagen.get("id") == solicitud.imagen_id), None)
    else:
        item = fila.get(solicitud.campo)
    if not item or not item.get("resultado_ocr"):
        raise HTTPException(400, f"La prueba no tiene imagen de {solicitud.campo}.")
    ocr = item["resultado_ocr"]
    unidades = list(ocr.get("tokens", [])) + list(ocr.get("lineas_texto", []))
    if ocr.get("texto_completo"):
        unidades.append({"texto": ocr["texto_completo"], "bbox": None})
    buscado = normalizar_codigo(solicitud.texto_ocr)
    token = next((t for t in unidades if normalizar_codigo(
        t.get("texto_original") or t.get("texto", "")) == buscado), None)
    if token is None:
        raise HTTPException(400, "La lectura OCR ya no coincide con los tokens de la prueba.")
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "La raíz de imágenes no está disponible en este equipo.")
    ruta_local = _resolver_imagen(str(item["ruta"]), datos, raiz)
    try:
        resultado = GestorAprendizaje(CONFIG).registrar_correccion(
            solicitud.texto_ocr, solicitud.texto_correcto,
            ruta_imagen=str(ruta_local), bbox=token.get("bbox"), fuente="dashboard")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    resultado["estado"] = GestorAprendizaje(CONFIG).estado()
    return resultado


@app.post("/api/aprendizaje/regiones")
def anotar_region_no_detectada(solicitud: SolicitudAnotacionRegion):
    """Registra verdad humana localizada sin exigir una lectura OCR previa."""
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    fila = next((f for f in datos["resultados"] if _id_fila(f) == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "La carpeta indicada no existe.")
    item = next((imagen for imagen in fila.get("imagenes", [])
                 if imagen.get("id") == solicitud.imagen_id), None)
    if item is None:
        raise HTTPException(404, "La imagen indicada no pertenece a la carpeta.")
    dimensiones = (item.get("resultado_ocr") or {}).get("dimensiones") or []
    if len(dimensiones) != 2:
        raise HTTPException(400, "No están disponibles las dimensiones de la imagen.")
    ancho_imagen, alto_imagen = (int(dimensiones[0]), int(dimensiones[1]))
    x, y, ancho, alto = solicitud.bbox
    if (x < 0 or y < 0 or ancho < 2 or alto < 2 or
            x + ancho > ancho_imagen or y + alto > alto_imagen):
        raise HTTPException(400, "La región seleccionada queda fuera de la imagen.")
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "La raíz de imágenes no está disponible en este equipo.")
    ruta_local = _resolver_imagen(str(item["ruta"]), datos, raiz)
    gestor = GestorAprendizaje(CONFIG)
    try:
        resultado = gestor.registrar_region(
            solicitud.texto_correcto, solicitud.bbox,
            ruta_imagen=str(ruta_local), carpeta_id=_id_fila(fila),
            carpeta_nombre=fila.get("nombre"),
            imagen_nombre=item.get("nombre") or ruta_local.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        from generar_excel import generar_excel
        resultado["excel_actualizado"] = str(generar_excel())
    except Exception as exc:  # la anotación queda guardada aunque falle el artefacto
        resultado["advertencia_excel"] = str(exc)
    resultado["estado"] = gestor.estado()
    return resultado


@app.post("/api/aprendizaje/rollback")
def rollback_aprendizaje(solicitud: SolicitudRollback):
    try:
        return GestorAprendizaje(CONFIG).rollback(solicitud.version)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _externas_publicas(incluir_ocultos: bool = False) -> dict:
    from pruebas_externas import cargar
    documento = cargar(CONFIG)
    publico = dict(documento)
    publico["resultados"] = []
    revisiones = GestorAprendizaje(CONFIG).listar_revisiones()
    for fila in documento.get("resultados", []):
        item = {k: v for k, v in fila.items() if k != "ruta"}
        completa = (bool(fila.get("coincidencia_exacta")) if fila.get("tipo") == "codigo"
                    else float(fila.get("cobertura") or 0) >= 1.0)
        item["revision"] = revisiones.get(("externa", fila["id"])) or {
            "tipo": "externa", "item_id": fila["id"],
            "estado": "completada" if completa else "por_revisar",
            "oculto": False, "actualizado_en": None}
        if item["revision"]["oculto"] and not incluir_ocultos:
            continue
        item["ruta_api"] = f"/api/externas/imagen/{quote(str(fila['imagen']), safe='')}"
        publico["resultados"].append(item)
    publico["visibles"] = len(publico["resultados"])
    return publico


@app.get("/api/externas")
def pruebas_externas(incluir_ocultos: bool = False):
    return _externas_publicas(incluir_ocultos)


@app.post("/api/externas/evaluar")
def evaluar_pruebas_externas():
    from pruebas_externas import evaluar
    with _pipeline_lock:
        if _pipeline_estado["estado"] == "procesando":
            raise HTTPException(409, "Espera a que termine el lote antes de evaluar el banco externo.")
    if not _externas_lock.acquire(blocking=False):
        raise HTTPException(409, "El banco externo ya se está evaluando.")
    try:
        try:
            evaluar(CONFIG)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
    finally:
        _externas_lock.release()
    return _externas_publicas()


@app.post("/api/revisiones")
def actualizar_revision(solicitud: SolicitudRevision):
    gestor = GestorAprendizaje(CONFIG)
    estado_inicial = "por_revisar"
    if solicitud.tipo == "carpeta":
        datos = _cargar_datos()
        fila = next((f for f in (datos or {}).get("resultados", [])
                     if _id_fila(f) == solicitud.item_id), None)
        if fila is None:
            raise HTTPException(404, "La carpeta indicada no existe.")
        estado_inicial = ("completada" if _fila_publica(fila)["semaforo"] == "verde"
                          else "por_revisar")
    else:
        from pruebas_externas import cargar
        fila = next((f for f in cargar(CONFIG).get("resultados", [])
                     if f.get("id") == solicitud.item_id), None)
        if fila is None:
            raise HTTPException(404, "La prueba compleja indicada no existe.")
        completa = (bool(fila.get("coincidencia_exacta")) if fila.get("tipo") == "codigo"
                    else float(fila.get("cobertura") or 0) >= 1.0)
        estado_inicial = "completada" if completa else "por_revisar"
    try:
        resultado = gestor.actualizar_revision(
            solicitud.tipo, solicitud.item_id, solicitud.estado,
            solicitud.oculto, estado_inicial)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        from generar_excel import generar_excel
        resultado["excel_actualizado"] = str(generar_excel())
    except Exception as exc:
        resultado["advertencia_excel"] = str(exc)
    return resultado


@app.get("/api/externas/imagen/{nombre}")
def imagen_externa(nombre: str):
    from pruebas_externas import CASOS, rutas
    nombre = unquote(nombre)
    if nombre not in CASOS:
        raise HTTPException(403, "La imagen no forma parte del banco externo permitido.")
    directorio, _ = rutas(CONFIG)
    objetivo = (directorio / nombre).resolve()
    if not objetivo.is_relative_to(directorio) or not objetivo.is_file():
        raise HTTPException(404, "La imagen externa no está disponible localmente.")
    return FileResponse(objetivo)


@app.post("/api/externas/correcciones")
def corregir_prueba_externa(solicitud: SolicitudCorreccionExterna):
    from pruebas_externas import cargar
    documento = cargar(CONFIG)
    fila = next((item for item in documento.get("resultados", [])
                 if item.get("id") == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "La prueba externa indicada no existe o aún no fue evaluada.")
    buscado = normalizar_codigo(solicitud.texto_ocr)
    unidades = list(fila.get("tokens", [])) + list(fila.get("lineas_texto", []))
    if fila.get("texto_completo"):
        unidades.append({"texto": fila["texto_completo"], "bbox": None})
    token = next((t for t in unidades if normalizar_codigo(
        t.get("texto_original") or t.get("texto", "")) == buscado), None)
    if token is None:
        raise HTTPException(400, "La lectura OCR no coincide con los tokens guardados.")
    try:
        resultado = GestorAprendizaje(CONFIG).registrar_correccion(
            solicitud.texto_ocr, solicitud.texto_correcto,
            ruta_imagen=fila["ruta"], bbox=token.get("bbox"), fuente="dashboard_externo")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    resultado["estado"] = GestorAprendizaje(CONFIG).estado()
    return resultado


@app.post("/api/pipeline", status_code=202)
def iniciar_pipeline(solicitud: SolicitudPipeline):
    ruta = Path(solicitud.ruta).expanduser()
    if not ruta.is_absolute():
        ruta = (RAIZ_PROYECTO / ruta).resolve()
    else:
        ruta = ruta.resolve()
    if not ruta.is_dir():
        raise HTTPException(400, "La ruta no existe o no es una carpeta accesible.")
    if ruta == Path(ruta.anchor):
        raise HTTPException(400, "No se permite procesar la raíz completa del sistema.")

    capacidad = _capacidad_pipeline()
    if not capacidad["listo"]:
        raise HTTPException(503, {"mensaje": "El entorno OCR no está listo.", **capacidad})

    with _pipeline_lock:
        if _pipeline_estado["estado"] == "procesando":
            raise HTTPException(409, "Ya hay una carpeta en procesamiento.")
        _pipeline_estado.update({
            "estado": "procesando", "fase": "preparando",
            "mensaje": "Preparando el pipeline", "ruta": str(ruta),
            "iniciado_en": datetime.now().isoformat(timespec="seconds"),
            "finalizado_en": None, "error": None, "resumen": None, "bitacora": None,
            "porcentaje": 0, "procesadas": 0, "total": 0, "restantes": 0,
            "eta_segundos": None, "transcurrido_segundos": 0,
            "resultados_parciales": [], "imagenes_procesadas": 0,
            "imagenes_total": 0, "imagenes_restantes": 0,
            "imagen_actual": None,
            "actualizado_en": datetime.now().isoformat(timespec="milliseconds"),
        })

    hilo = threading.Thread(target=_ejecutar_pipeline_fondo, args=(ruta,), daemon=True)
    hilo.start()
    return {"aceptado": True, "ruta": str(ruta), "estado": "procesando"}


@app.get("/api/resumen")
def resumen():
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados. Ejecuta primero el pipeline.")
    filas = [_fila_publica(f) for f in datos["resultados"]]
    procesadas = [f for f in filas if f["resultado"] != "sin_procesar"]
    n = len(procesadas)
    total = len(filas)
    conteo = {"verde": 0, "amarillo": 0, "rojo": 0, "sin_clasificar": 0}
    confianzas = []
    por_lote: dict[str, dict] = {}
    for f in filas:
        clave = f["semaforo"] or "sin_clasificar"
        conteo[clave] = conteo.get(clave, 0) + 1
        bucket = por_lote.setdefault(f["lote"], {"verde": 0, "amarillo": 0, "rojo": 0,
                                                 "sin_clasificar": 0, "total": 0})
        bucket[clave] += 1
        bucket["total"] += 1
        if f["confianza_ocr_pct"] is not None:
            confianzas.append(f["confianza_ocr_pct"])
    return {
        "total_carpetas": len(filas),
        "total_procesadas": n,
        "semaforo": conteo,
        "pct": {k: round(100 * v / total, 1) for k, v in conteo.items()} if total else {},
        "confianza_promedio": round(sum(confianzas) / len(confianzas), 1) if confianzas else None,
        "distribucion_por_lote": por_lote,
        "generado_en": datos.get("generado_en"),
        "raiz": _raiz_publica(datos),
        "raiz_origen": datos.get("raiz"),
    }


@app.get("/api/pruebas")
def pruebas(q: str = "", estado: str = "", limit: int = Query(200, ge=1, le=1000),
            offset: int = Query(0, ge=0), incluir_ocultos: bool = False):
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    revisiones = GestorAprendizaje(CONFIG).listar_revisiones()
    filas = [_fila_publica(f, revisiones) for f in datos["resultados"]]
    externas = _externas_publicas(incluir_ocultos=True)
    filas.extend(_fila_externa_publica(f) for f in externas.get("resultados", []))
    q_norm = unquote(q).strip().lower()
    filtradas = []
    for f in filas:
        if f["revision"].get("oculto") and not incluir_ocultos:
            continue
        if estado in {"por_revisar", "completada"} and f["revision"]["estado"] != estado:
            continue
        if (estado and estado not in {"por_revisar", "completada"} and
                (f["semaforo"] or "sin_clasificar") != estado and f["resultado"] != estado):
            continue
        texto_busqueda = " ".join(str(f.get(k) or "")
                                   for k in ("nombre", "identificador", "nomenclatura",
                                             "variante", "lote", "origen", "resultado"))
        if q_norm and q_norm not in texto_busqueda.lower():
            continue
        filtradas.append(f)
    return {"total": len(filtradas), "items": filtradas[offset:offset + limit],
            "incluye_externas": True}


@app.get("/api/pruebas/{clave}")
def detalle(clave: str):
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    buscada = unquote(clave)
    fila = next((f for f in datos["resultados"] if _id_fila(f) == buscada), None)
    if fila is None:
        por_nombre = [f for f in datos["resultados"] if f["nombre"] == buscada]
        if len(por_nombre) > 1:
            raise HTTPException(409, "El nombre se repite; usa el id estable de la fila.")
        fila = por_nombre[0] if por_nombre else None
    if fila is None:
        raise HTTPException(404, f"No existe la carpeta: {clave}")
    detalle_json = dict(fila)
    detalle_json["id"] = _id_fila(fila)
    detalle_json["lote"] = _lote_de(fila)
    detalle_json["semaforo"] = _fila_publica(fila)["semaforo"]
    detalle_json["revision"] = GestorAprendizaje(CONFIG).estado_revision(
        "carpeta", _id_fila(fila),
        "completada" if detalle_json["semaforo"] == "verde" else "por_revisar")
    raiz_local = _resolver_raiz_datos(datos)
    ruta_local = _reubicar_ruta(str(fila["ruta"]), datos, raiz_local) if raiz_local else None
    detalle_json["ruta_mostrada"] = str(ruta_local) if ruta_local else str(fila["ruta"])
    for campo in ("etiqueta", "referencia"):
        if fila.get(campo):
            detalle_json[campo] = dict(fila[campo])
            detalle_json[campo]["ruta_api"] = f"/api/imagen?ruta={quote(str(fila[campo]['ruta']), safe='')}"
    detalle_json["imagenes"] = []
    gestor = GestorAprendizaje(CONFIG)
    rutas_locales = []
    if raiz_local:
        for item in fila.get("imagenes", []):
            try:
                rutas_locales.append(_resolver_imagen(str(item["ruta"]), datos, raiz_local))
            except HTTPException:
                continue
    anotaciones = gestor.listar_anotaciones(rutas_locales, carpeta_id=_id_fila(fila))
    por_hash: dict[str, list[dict]] = {}
    for anotacion in anotaciones:
        por_hash.setdefault(anotacion["imagen_hash"], []).append(anotacion)
    for item in fila.get("imagenes", []):
        publico = dict(item)
        publico["ruta_api"] = f"/api/imagen?ruta={quote(str(item['ruta']), safe='')}"
        publico["anotaciones"] = []
        if raiz_local:
            try:
                ruta_item = _resolver_imagen(str(item["ruta"]), datos, raiz_local)
                publico["anotaciones"] = por_hash.get(hash_archivo(ruta_item), [])
            except (HTTPException, OSError):
                pass
        detalle_json["imagenes"].append(publico)
    return detalle_json


@app.get("/api/imagen")
def imagen(ruta: str):
    """Sirve imágenes originales SOLO si están dentro de la raíz del lote procesado."""
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    permitida = _resolver_raiz_datos(datos)
    if permitida is None:
        raise HTTPException(503, "La raíz de imágenes no está disponible en este equipo.")
    objetivo = _resolver_imagen(unquote(ruta), datos, permitida)
    if not objetivo.is_relative_to(permitida):
        raise HTTPException(403, "Ruta fuera de la raíz de datos permitida.")
    if not objetivo.is_file():
        raise HTTPException(404, "Archivo no encontrado.")
    return FileResponse(objetivo)


# Frontend estático: se monta al final para no tapar los endpoints /api.
app.mount("/", StaticFiles(directory=str(DIR_FRONTEND), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    puerto = int(CONFIG.get("dashboard", {}).get("puerto", 8000))
    print(f"Dashboard: http://127.0.0.1:{puerto}")
    uvicorn.run(app, host="127.0.0.1", port=puerto, log_level="warning")
