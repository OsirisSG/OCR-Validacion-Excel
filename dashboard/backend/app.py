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
from copy import deepcopy
from datetime import datetime
from pathlib import Path, PureWindowsPath
from urllib.parse import quote, unquote

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ_PROYECTO))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from configuracion import cargar_config, cargar_reglas, clasificar  # noqa: E402
from aprendizaje import (GestorAprendizaje, hash_archivo, normalizar_codigo,
                         rotar_bbox)  # noqa: E402
from recursos import detectar_recursos  # noqa: E402
from flujo_empresarial import BaseConocimiento, CLAVES_PLANTILLA  # noqa: E402

CONFIG = cargar_config()
REGLAS = cargar_reglas()
RUTA_VALIDACION = RAIZ_PROYECTO / "validacion_resultados.json"
RUTA_ESTRUCTURA = RAIZ_PROYECTO / CONFIG.get("fase0", {}).get(
    "archivo_salida", "estructura_detectada.json")
DIR_FRONTEND = RAIZ_PROYECTO / "dashboard" / "frontend"

app = FastAPI(title="Dashboard de validación de pruebas (OCR)", version="1.0")


@app.middleware("http")
async def evitar_frontend_obsoleto(request, call_next):
    """El dashboard local cambia con frecuencia; evita reutilizar JS/HTML antiguos."""
    respuesta = await call_next(request)
    ruta = request.url.path
    if ruta == "/" or ruta.endswith((".js", ".css", ".html")):
        respuesta.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        respuesta.headers["Pragma"] = "no-cache"
        respuesta.headers["Expires"] = "0"
    return respuesta


class SolicitudPipeline(BaseModel):
    ruta: str = Field(min_length=1, max_length=4096)
    nombre_excel: str | None = Field(default=None, max_length=128)
    sobrescribir_excel: bool = False
    tipo_st: str | None = Field(default=None, pattern="^(1ST|2ST|LEGACY)$")
    ruta_plantilla: str | None = Field(default=None, max_length=4096)
    modo_ejecucion: str = Field(default="completo", pattern="^(completo|inventario|reanudar)$")
    ruta_inventario: str | None = Field(default=None, max_length=4096)


class SolicitudRegla(BaseModel):
    estado: str = Field(pattern="^(confirmada|rechazada|desactivada)$")
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


class SolicitudReproceso(BaseModel):
    solo_errores: bool = False
    imagenes: list[str] = Field(default_factory=list, max_length=1000)
    modo_recorte: str | None = Field(default=None, pattern="^(auto|manual|completo)$")
    roi_manual: dict[str, float] | None = None
    zoom_forzado: float | None = Field(default=None, ge=1.0, le=4.0)
    roi_alcance: str = Field(default="etiqueta", pattern="^(proyecto|fase|etiqueta)$")


class SolicitudCampoManual(BaseModel):
    valor: str = Field(min_length=1, max_length=8192)
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


class SolicitudCorreccion(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    campo: str = Field(default="etiqueta", pattern="^(etiqueta|referencia)$")
    imagen_id: str | None = Field(default=None, max_length=128)
    texto_ocr: str = Field(min_length=1, max_length=4096)
    texto_correcto: str = Field(default="", max_length=4096)
    bbox: list[int] | None = Field(default=None, min_length=4, max_length=4)
    accion: str = Field(default="confirmar_entrenar", pattern=(
        "^(aceptar|corregir|ilegible|no_es_campo|guardar_sin_entrenar|confirmar_entrenar)$"))


class SolicitudAnotacionRegion(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    imagen_id: str = Field(min_length=1, max_length=128)
    bbox: list[int] = Field(min_length=4, max_length=4)
    texto_correcto: str = Field(min_length=1, max_length=8192)


class SolicitudRevision(BaseModel):
    tipo: str = Field(pattern="^(carpeta|externa)$")
    item_id: str = Field(min_length=1, max_length=128)
    estado: str | None = Field(
        default=None, pattern="^(por_revisar|parcial|casi_listo|completada)$")
    oculto: bool | None = None


class SolicitudAlerta(BaseModel):
    tipo: str = Field(pattern="^(carpeta|externa)$")
    item_id: str = Field(min_length=1, max_length=128)
    alerta_id: str = Field(min_length=8, max_length=64)


class SolicitudRollback(BaseModel):
    version: str | None = Field(default=None, max_length=128)


class SolicitudRotacion(BaseModel):
    tipo: str = Field(pattern="^(carpeta|externa)$")
    prueba_id: str = Field(min_length=1, max_length=128)
    imagen_id: str | None = Field(default=None, max_length=128)
    grados: int = Field(ge=0, le=270)


class SolicitudCorreccionExterna(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    texto_ocr: str = Field(min_length=1, max_length=4096)
    texto_correcto: str = Field(default="", max_length=4096)
    bbox: list[int] | None = Field(default=None, min_length=4, max_length=4)
    accion: str = Field(default="confirmar_entrenar", pattern=(
        "^(aceptar|corregir|ilegible|no_es_campo|guardar_sin_entrenar|confirmar_entrenar)$"))


class SolicitudRegionExterna(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    bbox: list[int] = Field(min_length=4, max_length=4)
    texto_correcto: str = Field(min_length=1, max_length=8192)


_pipeline_lock = threading.Lock()
_pipeline_continuar = threading.Event()
_pipeline_continuar.set()
_pipeline_cancelar = threading.Event()
_externas_lock = threading.Lock()
_entrenamiento_lock = threading.Lock()
_entrenamiento_estado = {"estado": "inactivo", "resultado": None, "error": None}
_pipeline_estado: dict = {
    "estado": "inactivo", "fase": None, "mensaje": None, "ruta": None,
    "iniciado_en": None, "finalizado_en": None, "error": None, "resumen": None,
    "bitacora": None, "porcentaje": 0, "procesadas": 0, "total": 0,
    "restantes": 0, "eta_segundos": None, "transcurrido_segundos": 0,
    "resultados_parciales": [], "imagenes_procesadas": 0, "imagenes_total": 0,
    "imagenes_restantes": 0, "imagen_actual": None, "actualizado_en": None,
    "recursos": None, "nombre_excel": None,
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
    clave = str(fila.get("case_key") or fila.get("ruta") or fila.get("nombre") or "")
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


def _bbox_igual(primera: list | None, segunda: list | None) -> bool:
    """Compara cajas OCR sin confundir textos repetidos en posiciones distintas."""
    if primera is None or segunda is None:
        return primera is None and segunda is None
    return [int(v) for v in primera] == [int(v) for v in segunda]


def _alerta_id(alerta: dict) -> str:
    firma = "|".join(str(alerta.get(k) or "")
                     for k in ("codigo", "imagen", "mensaje"))
    return hashlib.sha256(firma.encode("utf-8")).hexdigest()[:16]


def _alertas_pendientes(tipo: str, item_id: str, alertas: list[dict],
                        atendidas: set[tuple[str, str, str]] | None = None) -> list[dict]:
    atendidas = atendidas if atendidas is not None else GestorAprendizaje(
        CONFIG).listar_alertas_atendidas()
    salida = []
    for alerta in alertas or []:
        identificador = _alerta_id(alerta)
        if (tipo, item_id, identificador) not in atendidas:
            salida.append({**alerta, "id": identificador, "atendida": False})
    return salida


def _imagen_transformada(ruta: Path, rotacion: int = 0,
                         ajuste: float = 0.0) -> Response:
    """Entrega una vista orientada igual que la usada por el OCR."""
    import cv2
    import numpy as np

    datos = np.fromfile(str(ruta), dtype=np.uint8)
    imagen = cv2.imdecode(datos, cv2.IMREAD_COLOR)
    if imagen is None:
        raise HTTPException(422, "La imagen está corrupta o no se puede decodificar.")
    rotacion = int(rotacion) % 360
    if rotacion == 90:
        imagen = cv2.rotate(imagen, cv2.ROTATE_90_CLOCKWISE)
    elif rotacion == 180:
        imagen = cv2.rotate(imagen, cv2.ROTATE_180)
    elif rotacion == 270:
        imagen = cv2.rotate(imagen, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif rotacion != 0:
        raise HTTPException(400, "La rotación debe ser 0°, 90°, 180° o 270°.")
    if abs(float(ajuste)) >= 0.05:
        alto, ancho = imagen.shape[:2]
        matriz = cv2.getRotationMatrix2D((ancho / 2, alto / 2), float(ajuste), 1.0)
        imagen = cv2.warpAffine(
            imagen, matriz, (ancho, alto), flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE)
    ok, codificada = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise HTTPException(500, "No fue posible preparar la vista orientada.")
    return Response(content=codificada.tobytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


def _dimensiones_ocr_desde_archivo(ruta: Path, ocr: dict) -> tuple[int, int]:
    """Obtiene el lienzo OCR actual aun cuando un JSON antiguo no lo guardó."""
    import cv2
    import numpy as np

    datos = np.fromfile(str(ruta), dtype=np.uint8)
    imagen = cv2.imdecode(datos, cv2.IMREAD_COLOR)
    if imagen is None:
        raise ValueError("La imagen está corrupta o no se puede decodificar.")
    alto_original, ancho_original = imagen.shape[:2]
    manual = int(ocr.get("rotacion_manual_aplicada_grados") or 0) % 360
    orientacion = (_orientacion_base_publica(ocr) + manual) % 360
    if orientacion in {90, 270}:
        return alto_original, ancho_original
    return ancho_original, alto_original


def _rotar_resultado_existente(
        ocr: dict, grados_nuevos: int,
        dimensiones_respaldo: tuple[int, int] | None = None) -> dict:
    """Gira cajas OCR ya calculadas para que la corrección visual sea inmediata."""
    dimensiones = ocr.get("dimensiones") or []
    if len(dimensiones) == 2:
        ancho, alto = int(dimensiones[0]), int(dimensiones[1])
    elif dimensiones_respaldo:
        ancho, alto = dimensiones_respaldo
        ocr["dimensiones"] = [ancho, alto]
    else:
        raise ValueError("No fue posible obtener las dimensiones de la imagen para girarla.")
    aplicados = int(ocr.get("rotacion_manual_aplicada_grados") or 0) % 360
    delta = (int(grados_nuevos) - aplicados) % 360
    if delta == 0:
        ocr["rotacion_manual_aplicada_grados"] = int(grados_nuevos)
        return {"delta": 0, "dimensiones_anteriores": (ancho, alto)}
    for clave in ("tokens", "lineas_texto"):
        for unidad in ocr.get(clave) or []:
            if unidad.get("bbox") is not None:
                unidad["bbox"] = rotar_bbox(unidad["bbox"], delta, ancho, alto)
    for clave in ("qr_bbox", "roi_usado"):
        if ocr.get(clave) is not None:
            ocr[clave] = rotar_bbox(ocr[clave], delta, ancho, alto)
    if delta in {90, 270}:
        ocr["dimensiones"] = [alto, ancho]
    for clave in ("orientacion_corregida_grados", "orientacion_texto_grados",
                  "orientacion_grados"):
        if ocr.get(clave) is not None:
            ocr[clave] = (float(ocr[clave]) + delta) % 360
    ocr["rotacion_manual_aplicada_grados"] = int(grados_nuevos)
    return {"delta": delta, "dimensiones_anteriores": (ancho, alto)}


def _orientacion_base_publica(ocr: dict) -> int:
    """Recupera el giro recto también desde resultados JSON de versiones anteriores."""
    for clave in ("orientacion_texto_base_grados", "orientacion_base_grados"):
        if ocr.get(clave) is not None:
            return int(round(float(ocr[clave]) / 90.0) * 90) % 360
    total = ocr.get("orientacion_texto_grados")
    if total is None:
        total = ocr.get("orientacion_corregida_grados", 0)
    manual = float(ocr.get("rotacion_manual_aplicada_grados") or 0)
    return int(round((float(total or 0) - manual) / 90.0) * 90) % 360


def _guardar_json_atomico(ruta: Path, documento: dict) -> None:
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(json.dumps(documento, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(ruta)


def _buscar_unidad_ocr(unidades: list[dict], texto: str,
                       bbox: list[int] | None = None) -> dict | None:
    buscado = normalizar_codigo(texto)
    candidatas = [unidad for unidad in unidades if normalizar_codigo(
        unidad.get("texto_original") or unidad.get("texto", "")) == buscado]
    if bbox is not None:
        return next((unidad for unidad in candidatas
                     if _bbox_igual(unidad.get("bbox"), bbox)), None)
    sin_caja = [unidad for unidad in candidatas if unidad.get("bbox") is None]
    if len(sin_caja) == 1:
        return sin_caja[0]
    return candidatas[0] if len(candidatas) == 1 else None


def _aplicar_correcciones_publicas(ocr: dict, correcciones: list[dict]) -> dict:
    """Refleja en la respuesta el texto humano sin alterar el OCR bruto guardado."""
    salida = dict(ocr)
    for clave in ("tokens", "lineas_texto"):
        unidades = [dict(unidad) for unidad in ocr.get(clave, [])]
        for unidad in unidades:
            original = str(unidad.get("texto_original") or unidad.get("texto") or "")
            coincidencias = [c for c in correcciones
                             if str(c.get("texto_ocr") or "") == original and
                             _bbox_igual(c.get("bbox"), unidad.get("bbox"))]
            if coincidencias:
                unidad.setdefault("texto_original", original)
                unidad["texto"] = coincidencias[-1]["texto_correcto"]
                unidad["confirmado_manualmente"] = True
        salida[clave] = unidades
    lineas = salida.get("lineas_texto") or []
    if lineas and any(linea.get("confirmado_manualmente") for linea in lineas):
        salida["texto_completo"] = "\n".join(str(linea.get("texto") or "") for linea in lineas)
    return salida


def _regenerar_excel(resultado: dict) -> None:
    """Actualiza el artefacto sin perder una corrección si Excel falla."""
    try:
        from generar_excel import generar_excel
        resultado["excel_actualizado"] = str(generar_excel())
    except Exception as exc:
        resultado["advertencia_excel"] = str(exc)


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
    recursos = detectar_recursos(CONFIG.get("fase1", {}).get("dispositivo", "auto"))
    return {"listo": not faltantes, "faltantes": faltantes,
            "motores": motores, "recursos": recursos}


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


def _esperar_continuacion() -> None:
    """Pausa cooperativa: nunca interrumpe una inferencia a la mitad."""
    if _pipeline_cancelar.is_set():
        raise PipelineCancelado("Procesamiento cancelado por el usuario.")
    while not _pipeline_continuar.wait(timeout=0.25):
        if _pipeline_cancelar.is_set():
            raise PipelineCancelado("Procesamiento cancelado por el usuario.")


class PipelineCancelado(RuntimeError):
    pass


def _ejecutar_pipeline_fondo(ruta: Path, nombre_excel: str | None = None,
                             sobrescribir_excel: bool = False,
                             tipo_st: str | None = None,
                             ruta_plantilla: str | None = None,
                             casos_filtrados: set[str] | None = None,
                             imagenes_filtradas: set[str] | None = None,
                             solo_errores: bool = False,
                             modo_recorte: str | None = None,
                             roi_manual: dict[str, float] | None = None,
                             modo_ejecucion: str = "completo",
                             ruta_inventario: str | None = None,
                             zoom_forzado: float | None = None) -> None:
    inicio = time.monotonic()

    def progreso(fase: str, mensaje: str, detalle: dict | None = None) -> None:
        detalle = dict(detalle or {})
        fila = detalle.pop("resultado", None)
        caso = detalle.pop("caso_detectado", None)
        caso_actualizado = detalle.pop("caso_actualizado", None)
        with _pipeline_lock:
            _pipeline_estado.update(
                fase=fase, mensaje=mensaje,
                transcurrido_segundos=round(time.monotonic() - inicio, 1),
                actualizado_en=datetime.now().isoformat(timespec="milliseconds"),
                **detalle,
            )
            if fila is not None:
                publica = _fila_publica(fila)
                _pipeline_estado["resultados_parciales"] = [
                    f for f in _pipeline_estado["resultados_parciales"] if f["id"] != publica["id"]]
                _pipeline_estado["resultados_parciales"].append(publica)
                _cache.update({"mtime": None, "datos": None})
            elif caso is not None:
                publica = _fila_publica(caso)
                if not any(f["id"] == publica["id"] for f in _pipeline_estado["resultados_parciales"]):
                    _pipeline_estado["resultados_parciales"].append(publica)
            elif caso_actualizado is not None:
                publica = _fila_publica(caso_actualizado)
                _pipeline_estado["resultados_parciales"] = [
                    f for f in _pipeline_estado["resultados_parciales"] if f["id"] != publica["id"]]
                _pipeline_estado["resultados_parciales"].append(publica)

    try:
        from pipeline import ejecutar_pipeline
        resumen = ejecutar_pipeline(
            ruta, al_progreso=progreso, nombre_excel=nombre_excel,
            sobrescribir_excel=sobrescribir_excel,
            control=_esperar_continuacion, tipo_st=tipo_st,
            ruta_plantilla=ruta_plantilla, casos_filtrados=casos_filtrados,
            imagenes_filtradas=imagenes_filtradas, solo_errores=solo_errores,
            modo_recorte=modo_recorte, roi_manual=roi_manual,
            modo_ejecucion=modo_ejecucion, ruta_inventario=ruta_inventario,
            zoom_forzado=zoom_forzado)
        _cache.update({"mtime": None, "datos": None})
        _actualizar_pipeline(
            estado="completado", fase="completado", mensaje="Procesamiento terminado",
            finalizado_en=datetime.now().isoformat(timespec="seconds"), resumen=resumen,
            porcentaje=100, restantes=0, eta_segundos=0,
            transcurrido_segundos=round(time.monotonic() - inicio, 1),
        )
    except PipelineCancelado:
        with _pipeline_lock:
            for parcial in _pipeline_estado.get("resultados_parciales", []):
                if parcial.get("estado") == "procesando":
                    parcial["estado"] = "cancelada"
        _actualizar_pipeline(
            estado="cancelada", fase="cancelada", mensaje="Procesamiento detenido por el usuario",
            finalizado_en=datetime.now().isoformat(timespec="seconds"), error=None,
            eta_segundos=None,
            transcurrido_segundos=round(time.monotonic() - inicio, 1))
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


def _fila_publica(fila: dict, revisiones: dict | None = None,
                  alertas_atendidas: set | None = None) -> dict:
    """Fila para listado/tabla: ligera + semáforo evaluado con el motor de reglas."""
    comparacion = fila.get("comparacion", {}).get("resultado", "sin_procesar")
    clasif = clasificar(fila.get("confianza_ocr_pct"), comparacion, REGLAS)
    item_id = _id_fila(fila)
    if comparacion == "sin_procesar":
        inicial = "por_revisar"
    elif clasif.get("semaforo_global") == "verde":
        inicial = "casi_listo"
    else:
        inicial = "parcial"
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
        "resultado": comparacion,
        "confianza_ocr_pct": fila.get("confianza_ocr_pct"),
        "qr_detectado": fila.get("qr_detectado", False),
        "conforme": fila.get("es_conforme"),
        "observaciones": fila.get("observaciones", []),
        "alertas": _alertas_pendientes(
            "carpeta", item_id, fila.get("alertas", []), alertas_atendidas),
        "semaforo": clasif.get("semaforo_global"),
        "semaforo_confianza": clasif.get("confianza_ocr"),
        "semaforo_coincidencia": clasif.get("coincidencia_texto"),
        "origen": "carpeta",
        "enlace": f"#/detalle/{item_id}",
        "revision": revision,
        "case_key": fila.get("case_key"), "perfil": fila.get("perfil"),
        "tipo_st": fila.get("tipo_st"),
        "temperature_condition": fila.get("temperature_condition") or
                                 fila.get("metadata_ruta", {}).get("temperature_condition"),
        "module_version": fila.get("module_version") or
                          fila.get("metadata_ruta", {}).get("module_version"),
        "inflator_type": fila.get("inflator_type") or
                         fila.get("metadata_ruta", {}).get("inflator_type"),
        "ruta": fila.get("ruta"), "ruta_relativa": fila.get("ruta_relativa"),
        "estructura_valida": fila.get("estructura_valida"),
        "estado": fila.get("estado", "detectada"), "progreso": fila.get("progreso", {}),
        "total_imagenes": fila.get("total_imagenes", 0),
        "imagenes_nach": fila.get("imagenes_nach", 0),
        "imagenes_vor": fila.get("imagenes_vor", 0),
        "carpetas_tor": fila.get("carpetas_tor", []),
        "estado_deteccion": fila.get("estado_deteccion") or
                            ("estructura_valida" if fila.get("estructura_valida") else
                             "estructura_incompleta" if fila.get("estructura_valida") is False else None),
        "campos_encontrados": sum(
            dato.get("valor") not in {None, ""} for dato in fila.get("campos", {}).values()),
        "campos_faltantes": len(fila.get("campos_faltantes", [])),
        "conflictos": len(fila.get("conflictos", [])),
        "requiere_revision": fila.get("requiere_revision", comparacion != "coincidencia_total"),
        "ultima_ejecucion": fila.get("ultima_ejecucion"),
    }


def _fila_externa_publica(fila: dict) -> dict:
    completa = (bool(fila.get("coincidencia_exacta")) if fila.get("tipo") == "codigo"
                else float(fila.get("cobertura") or 0) >= 1.0)
    revision = fila.get("revision") or {
        "tipo": "externa", "item_id": fila["id"],
        "estado": ("casi_listo" if completa else
                   "parcial" if fila.get("tokens") or fila.get("lineas_texto") else "por_revisar"),
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
        "origen": "externa", "enlace": f"#/externas/{fila['id']}", "revision": revision,
        "alertas": fila.get("alertas", []),
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
    return {**GestorAprendizaje(CONFIG).estado(),
            "entrenamiento_visual": dict(_entrenamiento_estado)}


@app.post("/api/aprendizaje/entrenar-visual", status_code=202)
def iniciar_entrenamiento_visual():
    if not _entrenamiento_lock.acquire(blocking=False):
        raise HTTPException(409, "Ya existe un entrenamiento visual activo.")
    _entrenamiento_estado.update({"estado": "entrenando", "resultado": None, "error": None,
                                  "iniciado_en": datetime.now().isoformat(timespec="seconds")})

    def trabajo():
        try:
            from entrenamiento_easyocr import entrenar_lote
            try:
                resultado = entrenar_lote(CONFIG)
            except RuntimeError as exc:
                if "out of memory" not in str(exc).lower():
                    raise
                config_cpu = deepcopy(CONFIG)
                config_cpu.setdefault("fase1", {})["dispositivo"] = "cpu"
                resultado = entrenar_lote(config_cpu)
                resultado["advertencia"] = (
                    "La GPU se quedó sin memoria; el lote se reintentó automáticamente en CPU.")
            _entrenamiento_estado.update({"estado": resultado.get("estado", "terminado"),
                                          "resultado": resultado, "error": None})
            from ocr_engine import _MOTORES
            _MOTORES.clear()
        except Exception as exc:
            _entrenamiento_estado.update({"estado": "error", "resultado": None,
                                          "error": f"{type(exc).__name__}: {exc}"})
        finally:
            _entrenamiento_estado["finalizado_en"] = datetime.now().isoformat(timespec="seconds")
            _entrenamiento_lock.release()

    threading.Thread(target=trabajo, daemon=True).start()
    return {"aceptado": True, "estado": "entrenando"}


@app.post("/api/aprendizaje/modelos-visuales/{version}/activar")
def activar_modelo_visual(version: str):
    try:
        resultado = GestorAprendizaje(CONFIG).activar_modelo_visual(version)
        from ocr_engine import _MOTORES
        _MOTORES.clear()
        return resultado
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/aprendizaje/rollback-visual")
def rollback_modelo_visual(solicitud: SolicitudRollback):
    try:
        resultado = GestorAprendizaje(CONFIG).rollback_modelo_visual(solicitud.version)
        from ocr_engine import _MOTORES
        _MOTORES.clear()
        return resultado
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/aprendizaje/correcciones")
def corregir_lectura(solicitud: SolicitudCorreccion):
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    fila = next((f for f in datos["resultados"] if _id_fila(f) == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "La prueba indicada no existe.")
    gestor = GestorAprendizaje(CONFIG)
    revision = gestor.estado_revision(
        "carpeta", solicitud.prueba_id, _fila_publica(fila)["revision"]["estado"])
    if revision["estado"] == "completada":
        raise HTTPException(409, "La revisión está completada. Reábrela antes de editar.")
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
    token = _buscar_unidad_ocr(unidades, solicitud.texto_ocr, solicitud.bbox)
    if token is None:
        raise HTTPException(
            400, "La lectura OCR no coincide de forma única; vuelve a seleccionarla en la imagen.")
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "La raíz de imágenes no está disponible en este equipo.")
    ruta_local = _resolver_imagen(str(item["ruta"]), datos, raiz)
    try:
        correcto = (solicitud.texto_ocr if solicitud.accion == "aceptar"
                    else solicitud.texto_correcto)
        if solicitud.accion in {"aceptar", "ilegible", "no_es_campo", "guardar_sin_entrenar"}:
            muestra = gestor.registrar_muestra_visual(
                ruta_local, solicitud.prueba_id, solicitud.texto_ocr, correcto,
                token.get("bbox"), accion=solicitud.accion, entrenable=False,
                campo=solicitud.campo, fase=item.get("fase"), tor=item.get("tor"),
                confianza=token.get("confianza"), modelo_origen=ocr.get("modelo_visual_version")
                or ocr.get("motor"), metadatos={k: fila.get(k) for k in
                ("tipo_st", "module_version", "temperature_condition", "inflator_type")})
            resultado = {"registrada": True, "tipo": "supervision_visual",
                         "muestra_visual": muestra, "entrenamiento": None}
        else:
            if not correcto.strip():
                raise ValueError("Escribe el texto correcto antes de confirmar.")
            resultado = gestor.registrar_correccion(
                solicitud.texto_ocr, correcto, ruta_imagen=str(ruta_local),
                bbox=token.get("bbox"), fuente="dashboard", caso_id=solicitud.prueba_id,
                accion=solicitud.accion,
                entrenar_visual=solicitud.accion == "confirmar_entrenar",
                campo=solicitud.campo, fase=item.get("fase"), tor=item.get("tor"),
                confianza=token.get("confianza"), modelo_origen=ocr.get("modelo_visual_version")
                or ocr.get("motor"), metadatos={k: fila.get(k) for k in
                ("tipo_st", "module_version", "temperature_condition", "inflator_type")})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    gestor.actualizar_revision("carpeta", solicitud.prueba_id, estado="parcial")
    _regenerar_excel(resultado)
    resultado["estado"] = gestor.estado()
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
    gestor = GestorAprendizaje(CONFIG)
    revision = gestor.estado_revision(
        "carpeta", solicitud.prueba_id, _fila_publica(fila)["revision"]["estado"])
    if revision["estado"] == "completada":
        raise HTTPException(409, "La revisión está completada. Reábrela antes de editar.")
    item = next((imagen for imagen in fila.get("imagenes", [])
                 if imagen.get("id") == solicitud.imagen_id), None)
    if item is None:
        raise HTTPException(404, "La imagen indicada no pertenece a la carpeta.")
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "La raíz de imágenes no está disponible en este equipo.")
    ruta_local = _resolver_imagen(str(item["ruta"]), datos, raiz)
    dimensiones = (item.get("resultado_ocr") or {}).get("dimensiones") or []
    try:
        ancho_imagen, alto_imagen = (
            (int(dimensiones[0]), int(dimensiones[1]))
            if len(dimensiones) == 2 else
            _dimensiones_ocr_desde_archivo(ruta_local, item.get("resultado_ocr") or {}))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    x, y, ancho, alto = solicitud.bbox
    if (x < 0 or y < 0 or ancho < 2 or alto < 2 or
            x + ancho > ancho_imagen or y + alto > alto_imagen):
        raise HTTPException(400, "La región seleccionada queda fuera de la imagen.")
    try:
        resultado = gestor.registrar_region(
            solicitud.texto_correcto, solicitud.bbox,
            ruta_imagen=str(ruta_local), carpeta_id=_id_fila(fila),
            carpeta_nombre=fila.get("nombre"),
            imagen_nombre=item.get("nombre") or ruta_local.name,
            fase=item.get("fase"), tor=item.get("tor"),
            modelo_origen=(item.get("resultado_ocr") or {}).get("modelo_visual_version")
            or (item.get("resultado_ocr") or {}).get("motor"),
            metadatos={k: fila.get(k) for k in
                       ("tipo_st", "module_version", "temperature_condition", "inflator_type")})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    gestor.actualizar_revision("carpeta", solicitud.prueba_id, estado="parcial")
    _regenerar_excel(resultado)
    resultado["estado"] = gestor.estado()
    return resultado


@app.post("/api/aprendizaje/rollback")
def rollback_aprendizaje(solicitud: SolicitudRollback):
    try:
        return GestorAprendizaje(CONFIG).rollback(solicitud.version)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/aprendizaje/rotaciones")
def guardar_rotacion(solicitud: SolicitudRotacion):
    """Memoriza la orientación humana; el siguiente OCR la usa como punto de partida."""
    if solicitud.grados not in {0, 90, 180, 270}:
        raise HTTPException(400, "La rotación debe ser 0°, 90°, 180° o 270°.")
    gestor = GestorAprendizaje(CONFIG)
    ocr_objetivo = None
    documento_externo = None
    salida_externa = None
    if solicitud.tipo == "carpeta":
        datos = _cargar_datos()
        fila = next((f for f in (datos or {}).get("resultados", [])
                     if _id_fila(f) == solicitud.prueba_id), None)
        if fila is None:
            raise HTTPException(404, "La carpeta indicada no existe.")
        inicial = _fila_publica(fila)["revision"]["estado"]
        if gestor.estado_revision("carpeta", solicitud.prueba_id, inicial)["estado"] == "completada":
            raise HTTPException(409, "La revisión está completada. Reábrela antes de rotar.")
        item = next((imagen for imagen in fila.get("imagenes", [])
                     if imagen.get("id") == solicitud.imagen_id), None)
        if item is None:
            raise HTTPException(404, "La imagen indicada no pertenece a la carpeta.")
        ocr_objetivo = item.get("resultado_ocr") or {}
        raiz = _resolver_raiz_datos(datos)
        if raiz is None:
            raise HTTPException(503, "La raíz de imágenes no está disponible en este equipo.")
        ruta = _resolver_imagen(str(item["ruta"]), datos, raiz)
    else:
        from pruebas_externas import cargar, rutas
        documento_externo = cargar(CONFIG)
        fila = next((f for f in documento_externo.get("resultados", [])
                     if f.get("id") == solicitud.prueba_id), None)
        if fila is None:
            raise HTTPException(404, "La prueba compleja indicada no existe.")
        completa = (bool(fila.get("coincidencia_exacta")) if fila.get("tipo") == "codigo"
                    else float(fila.get("cobertura") or 0) >= 1.0)
        inicial = ("casi_listo" if completa else
                   "parcial" if fila.get("tokens") or fila.get("lineas_texto")
                   else "por_revisar")
        if gestor.estado_revision("externa", solicitud.prueba_id, inicial)["estado"] == "completada":
            raise HTTPException(409, "La revisión está completada. Reábrela antes de rotar.")
        ruta = Path(str(fila.get("ruta") or "")).resolve()
        if not ruta.is_file():
            raise HTTPException(404, "La imagen compleja ya no está disponible.")
        ocr_objetivo = fila
        _, salida_externa = rutas(CONFIG)
    try:
        dimensiones_respaldo = _dimensiones_ocr_desde_archivo(ruta, ocr_objetivo)
        giro = _rotar_resultado_existente(
            ocr_objetivo, solicitud.grados, dimensiones_respaldo)
        resultado = gestor.actualizar_rotacion(ruta, solicitud.grados)
        resultado.update(gestor.rotar_evidencias_imagen(
            ruta, giro["delta"], giro["dimensiones_anteriores"]))
        if solicitud.tipo == "carpeta":
            # Etiqueta/referencia son vistas resumidas de las mismas imágenes.
            for campo in ("etiqueta", "referencia"):
                copia = fila.get(campo)
                if (copia and str(copia.get("ruta")) == str(item.get("ruta")) and
                        copia.get("resultado_ocr") is not ocr_objetivo):
                    ocr_copia = copia.get("resultado_ocr") or {}
                    _rotar_resultado_existente(
                        ocr_copia, solicitud.grados,
                        _dimensiones_ocr_desde_archivo(ruta, ocr_copia))
            _guardar_json_atomico(RUTA_VALIDACION, datos)
            _cache.update({"mtime": None, "datos": None})
        else:
            _guardar_json_atomico(salida_externa, documento_externo)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    gestor.actualizar_revision(solicitud.tipo, solicitud.prueba_id, estado="parcial")
    resultado["mensaje"] = (
        "Imagen rotada ahora. También se ajustaron sus cajas y regiones; "
        "el próximo OCR conservará esta orientación.")
    return resultado


def _externas_publicas(incluir_ocultos: bool = False) -> dict:
    from pruebas_externas import cargar, rutas
    documento = cargar(CONFIG)
    publico = dict(documento)
    publico["resultados"] = []
    gestor = GestorAprendizaje(CONFIG)
    revisiones = gestor.listar_revisiones()
    alertas_atendidas = gestor.listar_alertas_atendidas()
    directorio, _ = rutas(CONFIG)
    rutas_disponibles = [(directorio / fila["imagen"]).resolve()
                         for fila in documento.get("resultados", [])
                         if (directorio / fila["imagen"]).is_file()]
    correcciones_por_hash: dict[str, list[dict]] = {}
    for correccion in gestor.listar_correcciones_texto(rutas_disponibles):
        correcciones_por_hash.setdefault(correccion["imagen_hash"], []).append(correccion)
    anotaciones_por_hash: dict[str, list[dict]] = {}
    for anotacion in gestor.listar_anotaciones(rutas_disponibles):
        anotaciones_por_hash.setdefault(anotacion["imagen_hash"], []).append(anotacion)
    rotaciones = gestor.listar_rotaciones(rutas_disponibles)
    for fila in documento.get("resultados", []):
        item = {k: v for k, v in fila.items() if k != "ruta"}
        completa = (bool(fila.get("coincidencia_exacta")) if fila.get("tipo") == "codigo"
                    else float(fila.get("cobertura") or 0) >= 1.0)
        item["revision"] = revisiones.get(("externa", fila["id"])) or {
            "tipo": "externa", "item_id": fila["id"],
            "estado": ("casi_listo" if completa else
                       "parcial" if fila.get("tokens") or fila.get("lineas_texto") else "por_revisar"),
            "oculto": False, "actualizado_en": None}
        if item["revision"]["oculto"] and not incluir_ocultos:
            continue
        item["ruta_api"] = f"/api/externas/imagen/{quote(str(fila['imagen']), safe='')}"
        ruta_imagen = (directorio / fila["imagen"]).resolve()
        imagen_hash = hash_archivo(ruta_imagen) if ruta_imagen.is_file() else None
        preferida = int((rotaciones.get(imagen_hash) or {}).get("grados", 0))
        aplicada = int(fila.get("rotacion_manual_aplicada_grados") or 0)
        base = _orientacion_base_publica(fila)
        ajuste = float(fila.get("deskew_texto_aplicado_grados") or
                       fila.get("deskew_aplicado_grados") or 0)
        item["rotacion_manual_preferida_grados"] = preferida
        item["orientacion_texto_base_grados"] = base
        item["rotacion_pendiente"] = preferida != aplicada
        item["ruta_api_visual"] = (
            f"/api/externas/imagen-orientada/{quote(str(fila['imagen']), safe='')}"
            f"?rotacion={(preferida + base) % 360}&ajuste={ajuste}")
        item["ruta_api_orientada"] = (
            f"/api/externas/imagen-orientada/{quote(str(fila['imagen']), safe='')}"
            f"?rotacion={(aplicada + base) % 360}&ajuste={ajuste}")
        item["correcciones"] = (correcciones_por_hash.get(hash_archivo(ruta_imagen), [])
                                if ruta_imagen.is_file() else [])
        item["anotaciones"] = (anotaciones_por_hash.get(hash_archivo(ruta_imagen), [])
                               if ruta_imagen.is_file() else [])
        item = _aplicar_correcciones_publicas(item, item["correcciones"])
        item["alertas"] = _alertas_pendientes(
            "externa", fila["id"], fila.get("alertas", []), alertas_atendidas)
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
        estado_inicial = _fila_publica(fila)["revision"]["estado"]
    else:
        from pruebas_externas import cargar
        fila = next((f for f in cargar(CONFIG).get("resultados", [])
                     if f.get("id") == solicitud.item_id), None)
        if fila is None:
            raise HTTPException(404, "La prueba compleja indicada no existe.")
        completa = (bool(fila.get("coincidencia_exacta")) if fila.get("tipo") == "codigo"
                    else float(fila.get("cobertura") or 0) >= 1.0)
        estado_inicial = ("casi_listo" if completa else
                          "parcial" if fila.get("tokens") or fila.get("lineas_texto")
                          else "por_revisar")
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


@app.post("/api/alertas/atender")
def atender_alerta(solicitud: SolicitudAlerta):
    gestor = GestorAprendizaje(CONFIG)
    return gestor.atender_alerta(
        solicitud.tipo, solicitud.item_id, solicitud.alerta_id)


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


@app.get("/api/externas/imagen-orientada/{nombre}")
def imagen_externa_orientada(nombre: str, rotacion: int = 0, ajuste: float = 0.0):
    from pruebas_externas import CASOS, rutas
    nombre = unquote(nombre)
    if nombre not in CASOS:
        raise HTTPException(403, "La imagen no forma parte del banco externo permitido.")
    directorio, _ = rutas(CONFIG)
    objetivo = (directorio / nombre).resolve()
    if not objetivo.is_relative_to(directorio) or not objetivo.is_file():
        raise HTTPException(404, "La imagen externa no está disponible localmente.")
    return _imagen_transformada(objetivo, rotacion, ajuste)


@app.post("/api/externas/correcciones")
def corregir_prueba_externa(solicitud: SolicitudCorreccionExterna):
    from pruebas_externas import cargar
    documento = cargar(CONFIG)
    fila = next((item for item in documento.get("resultados", [])
                 if item.get("id") == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "La prueba externa indicada no existe o aún no fue evaluada.")
    gestor = GestorAprendizaje(CONFIG)
    completa = (bool(fila.get("coincidencia_exacta")) if fila.get("tipo") == "codigo"
                else float(fila.get("cobertura") or 0) >= 1.0)
    inicial = ("casi_listo" if completa else
               "parcial" if fila.get("tokens") or fila.get("lineas_texto") else "por_revisar")
    if gestor.estado_revision("externa", solicitud.prueba_id, inicial)["estado"] == "completada":
        raise HTTPException(409, "La revisión está completada. Reábrela antes de editar.")
    unidades = list(fila.get("tokens", [])) + list(fila.get("lineas_texto", []))
    if fila.get("texto_completo"):
        unidades.append({"texto": fila["texto_completo"], "bbox": None})
    token = _buscar_unidad_ocr(unidades, solicitud.texto_ocr, solicitud.bbox)
    if token is None:
        raise HTTPException(
            400, "La lectura OCR no coincide de forma única; vuelve a seleccionarla.")
    try:
        correcto = (solicitud.texto_ocr if solicitud.accion == "aceptar"
                    else solicitud.texto_correcto)
        if solicitud.accion in {"aceptar", "ilegible", "no_es_campo", "guardar_sin_entrenar"}:
            muestra = gestor.registrar_muestra_visual(
                fila["ruta"], solicitud.prueba_id, solicitud.texto_ocr, correcto,
                token.get("bbox"), accion=solicitud.accion, entrenable=False,
                confianza=token.get("confianza"), modelo_origen=fila.get("modelo_visual_version")
                or fila.get("motor"), metadatos={"origen": "externa"})
            resultado = {"registrada": True, "tipo": "supervision_visual",
                         "muestra_visual": muestra, "entrenamiento": None}
        else:
            if not correcto.strip():
                raise ValueError("Escribe el texto correcto antes de confirmar.")
            resultado = gestor.registrar_correccion(
                solicitud.texto_ocr, correcto, ruta_imagen=fila["ruta"],
                bbox=token.get("bbox"), fuente="dashboard_externo",
                caso_id=solicitud.prueba_id, accion=solicitud.accion,
                entrenar_visual=solicitud.accion == "confirmar_entrenar",
                confianza=token.get("confianza"), modelo_origen=fila.get("modelo_visual_version")
                or fila.get("motor"), metadatos={"origen": "externa"})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    gestor.actualizar_revision("externa", solicitud.prueba_id, estado="parcial")
    _regenerar_excel(resultado)
    resultado["estado"] = gestor.estado()
    return resultado


@app.post("/api/externas/regiones")
def anotar_region_externa(solicitud: SolicitudRegionExterna):
    """Guarda texto omitido en una prueba compleja con el mismo contrato normal."""
    from pruebas_externas import cargar, rutas

    documento = cargar(CONFIG)
    fila = next((item for item in documento.get("resultados", [])
                 if item.get("id") == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "La prueba externa indicada no existe o aún no fue evaluada.")
    gestor = GestorAprendizaje(CONFIG)
    completa = (bool(fila.get("coincidencia_exacta")) if fila.get("tipo") == "codigo"
                else float(fila.get("cobertura") or 0) >= 1.0)
    inicial = ("casi_listo" if completa else
               "parcial" if fila.get("tokens") or fila.get("lineas_texto") else "por_revisar")
    if gestor.estado_revision("externa", solicitud.prueba_id, inicial)["estado"] == "completada":
        raise HTTPException(409, "La revisión está completada. Reábrela antes de editar.")

    directorio, _ = rutas(CONFIG)
    ruta = (directorio / str(fila.get("imagen") or "")).resolve()
    if not ruta.is_relative_to(directorio) or not ruta.is_file():
        raise HTTPException(404, "La imagen compleja ya no está disponible.")
    dimensiones = fila.get("dimensiones") or []
    try:
        ancho_imagen, alto_imagen = (
            (int(dimensiones[0]), int(dimensiones[1]))
            if len(dimensiones) == 2 else _dimensiones_ocr_desde_archivo(ruta, fila))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    x, y, ancho, alto = solicitud.bbox
    if (x < 0 or y < 0 or ancho < 2 or alto < 2 or
            x + ancho > ancho_imagen or y + alto > alto_imagen):
        raise HTTPException(400, "La región seleccionada queda fuera de la imagen.")
    try:
        resultado = gestor.registrar_region(
            solicitud.texto_correcto, solicitud.bbox, ruta_imagen=str(ruta),
            carpeta_id=solicitud.prueba_id, carpeta_nombre="Pruebas complejas",
            imagen_nombre=fila.get("imagen"), fuente="dashboard_externo",
            modelo_origen=fila.get("modelo_visual_version") or fila.get("motor"),
            metadatos={"origen": "externa"})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    gestor.actualizar_revision("externa", solicitud.prueba_id, estado="parcial")
    _regenerar_excel(resultado)
    resultado["estado"] = gestor.estado()
    return resultado


@app.post("/api/pipeline", status_code=202)
def iniciar_pipeline(solicitud: SolicitudPipeline):
    ruta_cruda = solicitud.ruta.strip()
    if len(ruta_cruda) >= 2 and ruta_cruda[0] == ruta_cruda[-1] and ruta_cruda[0] in {'"', "'"}:
        ruta_cruda = ruta_cruda[1:-1].strip()
    ruta = Path(ruta_cruda).expanduser()
    if not ruta.is_absolute():
        ruta = (RAIZ_PROYECTO / ruta).resolve()
    else:
        ruta = ruta.resolve()
    if not ruta.is_dir():
        raise HTTPException(400, "La ruta no existe o no es una carpeta accesible.")
    if ruta == Path(ruta.anchor):
        raise HTTPException(400, "No se permite procesar la raíz completa del sistema.")
    nombre_excel = (solicitud.nombre_excel or "").strip() or None
    if nombre_excel:
        if Path(nombre_excel).name != nombre_excel or nombre_excel in {".", ".."}:
            raise HTTPException(400, "Escribe solamente el nombre del Excel, sin carpetas.")
        if not nombre_excel.lower().endswith(".xlsx"):
            nombre_excel = (Path(nombre_excel).with_suffix(".xlsx").name
                            if Path(nombre_excel).suffix else nombre_excel + ".xlsx")
    ruta_plantilla = (solicitud.ruta_plantilla or "").strip().strip('"\'') or None
    if ruta_plantilla:
        plantilla = Path(ruta_plantilla).expanduser()
        plantilla = ((RAIZ_PROYECTO / plantilla).resolve() if not plantilla.is_absolute()
                     else plantilla.resolve())
        if not plantilla.is_file() or plantilla.suffix.lower() != ".xlsx":
            raise HTTPException(400, "La plantilla debe ser un archivo .xlsx accesible.")
        ruta_plantilla = str(plantilla)
    ruta_inventario = (solicitud.ruta_inventario or "").strip().strip('"\'') or None
    if ruta_inventario:
        inventario = Path(ruta_inventario).expanduser()
        inventario = ((RAIZ_PROYECTO / inventario).resolve() if not inventario.is_absolute()
                      else inventario.resolve())
        if solicitud.modo_ejecucion == "reanudar" and not inventario.is_file():
            raise HTTPException(400, "El inventario indicado no existe.")
        ruta_inventario = str(inventario)

    capacidad = _capacidad_pipeline()
    if not capacidad["listo"]:
        raise HTTPException(503, {"mensaje": "El entorno OCR no está listo.", **capacidad})

    with _pipeline_lock:
        if _pipeline_estado["estado"] in {"procesando", "pausado"}:
            raise HTTPException(409, "Ya hay una carpeta en procesamiento.")
        _pipeline_continuar.set()
        _pipeline_cancelar.clear()
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
            "recursos": capacidad.get("recursos"), "nombre_excel": nombre_excel,
            "tipo_st": solicitud.tipo_st, "ruta_plantilla": ruta_plantilla,
            "modo_ejecucion": solicitud.modo_ejecucion,
            "ruta_inventario": ruta_inventario,
            "actualizado_en": datetime.now().isoformat(timespec="milliseconds"),
        })

    hilo = threading.Thread(target=_ejecutar_pipeline_fondo, kwargs={
        "ruta": ruta, "nombre_excel": nombre_excel,
        "sobrescribir_excel": solicitud.sobrescribir_excel,
        "tipo_st": solicitud.tipo_st, "ruta_plantilla": ruta_plantilla,
        "modo_ejecucion": solicitud.modo_ejecucion,
        "ruta_inventario": ruta_inventario,
    }, daemon=True)
    hilo.start()
    return {"aceptado": True, "ruta": str(ruta), "estado": "procesando"}


@app.post("/api/pipeline/pausar")
def pausar_pipeline():
    with _pipeline_lock:
        if _pipeline_estado["estado"] != "procesando":
            raise HTTPException(409, "No hay un procesamiento activo que se pueda pausar.")
        _pipeline_continuar.clear()
        _pipeline_estado.update(
            estado="pausado", mensaje="Pausa solicitada; se detendrá al terminar la imagen actual",
            eta_segundos=None, actualizado_en=datetime.now().isoformat(timespec="milliseconds"))
    return {"estado": "pausado", "seguro": True}


@app.post("/api/pipeline/reanudar")
def reanudar_pipeline():
    with _pipeline_lock:
        if _pipeline_estado["estado"] != "pausado":
            raise HTTPException(409, "El procesamiento no está pausado.")
        _pipeline_continuar.set()
        _pipeline_estado.update(
            estado="procesando", mensaje="Procesamiento reanudado",
            actualizado_en=datetime.now().isoformat(timespec="milliseconds"))
    return {"estado": "procesando"}


@app.post("/api/pipeline/cancelar")
def cancelar_pipeline():
    with _pipeline_lock:
        if _pipeline_estado["estado"] not in {"procesando", "pausado"}:
            raise HTTPException(409, "No hay un procesamiento activo que detener.")
        _pipeline_cancelar.set()
        _pipeline_continuar.set()
        _pipeline_estado.update(
            mensaje="Detención solicitada; se cerrará al terminar la imagen actual",
            actualizado_en=datetime.now().isoformat(timespec="milliseconds"))
    return {"estado": "cancelando", "seguro": True}


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
    with _pipeline_lock:
        parciales = [dict(f) for f in _pipeline_estado.get("resultados_parciales", [])]
    if not datos and not parciales:
        raise HTTPException(404, "Sin datos procesados.")
    revisiones = GestorAprendizaje(CONFIG).listar_revisiones()
    atendidas = GestorAprendizaje(CONFIG).listar_alertas_atendidas()
    filas = [_fila_publica(f, revisiones, atendidas) for f in (datos or {}).get("resultados", [])]
    por_id = {f["id"]: f for f in filas}
    for parcial in parciales:
        if parcial.get("origen") == "carpeta":
            por_id[parcial["id"]] = parcial
    filas = list(por_id.values())
    externas = _externas_publicas(incluir_ocultos=True)
    filas.extend(_fila_externa_publica(f) for f in externas.get("resultados", []))
    q_norm = unquote(q).strip().lower()
    filtradas = []
    for f in filas:
        if f["revision"].get("oculto") and not incluir_ocultos:
            continue
        estados_revision = {"por_revisar", "parcial", "casi_listo", "completada"}
        if estado in estados_revision and f["revision"]["estado"] != estado:
            continue
        if (estado and estado not in estados_revision and
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


@app.get("/api/proyectos")
def proyectos():
    datos = _cargar_datos() or {}
    with _pipeline_lock:
        estado_actual = dict(_pipeline_estado)
    raiz = datos.get("raiz") or estado_actual.get("ruta")
    return {"proyectos": ([{"id": hashlib.sha256(str(raiz).encode()).hexdigest()[:16],
                             "nombre": Path(raiz).name, "ruta": raiz,
                             "perfil": datos.get("perfil", "pendiente"),
                             "tipos_st": datos.get("tipos_st", []),
                             "estado": estado_actual.get("estado")}]
                           if raiz else [])}


@app.get("/api/resultados/excel")
def descargar_excel():
    datos = _cargar_datos() or {}
    ruta = datos.get("archivo_excel")
    if not ruta:
        raise HTTPException(404, "Esta ejecución no registró un Excel asociado.")
    archivo = Path(ruta).resolve()
    if not archivo.is_file() or archivo.suffix.lower() != ".xlsx":
        raise HTTPException(404, "El Excel asociado ya no está disponible.")
    return FileResponse(archivo, filename=archivo.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/casos")
def casos(q: str = "", estado: str = "", limit: int = Query(500, ge=1, le=1000),
          offset: int = Query(0, ge=0)):
    respuesta = pruebas(q=q, estado=estado, limit=1000, offset=0)
    items = [item for item in respuesta["items"] if item.get("origen") == "carpeta"]
    return {"total": len(items), "items": items[offset:offset + limit]}


@app.get("/api/casos/{clave}/progreso")
def progreso_caso(clave: str):
    respuesta = casos(limit=1000)
    item = next((f for f in respuesta["items"] if f["id"] == clave), None)
    if not item:
        raise HTTPException(404, "No existe el caso solicitado.")
    return {"id": item["id"], "case_key": item.get("case_key"),
            "estado": item.get("estado"), "progreso": item.get("progreso", {}),
            "campos_faltantes": item.get("campos_faltantes", 0),
            "conflictos": item.get("conflictos", 0)}


@app.get("/api/casos/{clave}/historial")
def historial_caso(clave: str):
    datos = _cargar_datos() or {}
    fila = next((f for f in datos.get("resultados", []) if _id_fila(f) == clave), None)
    if not fila:
        raise HTTPException(404, "No existe el caso solicitado.")
    return {"id": clave, "case_key": fila.get("case_key"),
            "ejecuciones": fila.get("historial_ejecuciones", []),
            "acciones": fila.get("historial_acciones", [])}


@app.post("/api/casos/{clave}/campos/{campo}")
def corregir_campo_caso(clave: str, campo: str, solicitud: SolicitudCampoManual):
    """Confirma un valor de las 36 claves sin alterar archivos originales."""
    if campo not in CLAVES_PLANTILLA:
        raise HTTPException(400, "La clave no pertenece al contrato de 36 campos.")
    datos = _cargar_datos()
    fila = next((f for f in (datos or {}).get("resultados", []) if _id_fila(f) == clave), None)
    if not fila or fila.get("perfil") != "empresarial":
        raise HTTPException(404, "No existe el caso empresarial solicitado.")
    gestor = GestorAprendizaje(CONFIG)
    inicial = _fila_publica(fila)["revision"]["estado"]
    if gestor.estado_revision("carpeta", clave, inicial)["estado"] == "completada":
        raise HTTPException(409, "La revisión está completada. Reábrela antes de editar.")
    valor = solicitud.valor.strip()
    ahora_iso = datetime.now().isoformat(timespec="seconds")
    correccion = {"valor": valor, "corregido_en": ahora_iso,
                  "corregido_por": solicitud.usuario}
    fila.setdefault("correcciones_manual_campos", {})[campo] = correccion
    original_ruta = fila.get(campo) if campo in {
        "test_number", "module_version", "inflator_type", "temperature_condition"} else None
    conflicto_ruta = original_ruta not in {None, "", valor}
    dato = {"valor": valor, "valor_original": valor,
            "estado": "pendiente_revision" if conflicto_ruta else "confirmado_manual",
            "fuente": "correccion_manual_confirmada", "confianza": 1.0,
            "inferido": False, "requiere_revision": conflicto_ruta,
            "valor_seguro_ruta": original_ruta if conflicto_ruta else None,
            **correccion}
    fila.setdefault("campos", {})[campo] = dato
    fila.setdefault("consolidado", {}).setdefault("campos", {})[campo] = dato
    fila["campos_faltantes"] = [c for c in fila.get("campos_faltantes", []) if c != campo]
    fila["conflictos"] = list(dict.fromkeys([
        *[c for c in fila.get("conflictos", []) if c != campo],
        *([campo] if conflicto_ruta else []),
    ]))
    fila["requiere_revision"] = bool(fila["conflictos"] or fila["campos_faltantes"])
    fila["consolidado"].update({
        "campos_faltantes": fila["campos_faltantes"],
        "conflictos": fila["conflictos"],
        "requiere_revision": fila["requiere_revision"],
    })
    fila.setdefault("comparacion", {})["resultado"] = (
        "discrepancia" if fila["conflictos"] else
        "coincidencia_parcial" if fila["campos_faltantes"] else "coincidencia_total")
    # En el perfil empresarial son claves de plantilla, no tokens OCR.
    fila["comparacion"]["faltantes"] = []
    fila.setdefault("historial_acciones", []).append({
        "tipo": "correccion_campo", "campo": campo, "valor": valor,
        "usuario": solicitud.usuario, "fecha": ahora_iso,
        "conflicto_con_ruta": conflicto_ruta,
    })
    _guardar_json_atomico(RUTA_VALIDACION, datos)
    _cache.update({"mtime": None, "datos": None})
    gestor.actualizar_revision("carpeta", clave, estado="parcial")
    respuesta = {"campo": campo, "dato": dato, "conflictos": fila["conflictos"]}
    try:
        from generar_excel import generar_excel
        respuesta["archivo_excel"] = str(generar_excel(
            RUTA_VALIDACION, datos.get("archivo_excel"), CONFIG,
            ruta_plantilla=datos.get("ruta_plantilla")))
    except Exception as exc:
        respuesta["advertencia_excel"] = str(exc)
    return respuesta


def _base_conocimiento() -> BaseConocimiento:
    cfg = CONFIG.get("empresarial", {})
    return BaseConocimiento(
        RAIZ_PROYECTO / cfg.get("base_conocimiento", "base_conocimiento.json"),
        cfg.get("reglas_minimo_ids", 3), cfg.get("reglas_consenso_minimo", 0.90))


@app.get("/api/reglas")
def reglas_conocimiento(estado: str = ""):
    reglas = _base_conocimiento().datos.get("reglas", [])
    if estado:
        reglas = [r for r in reglas if r.get("estado") == estado]
    return {"total": len(reglas), "reglas": reglas}


@app.post("/api/reglas/{regla_id}")
def actualizar_regla(regla_id: str, solicitud: SolicitudRegla):
    try:
        return _base_conocimiento().cambiar_estado(
            regla_id, solicitud.estado, solicitud.usuario)
    except KeyError as exc:
        raise HTTPException(404, "No existe la regla solicitada.") from exc


@app.post("/api/casos/{clave}/reprocesar", status_code=202)
def reprocesar_caso(clave: str, solicitud: SolicitudReproceso):
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    fila = next((f for f in datos.get("resultados", []) if _id_fila(f) == clave), None)
    if not fila or not fila.get("case_key"):
        raise HTTPException(400, "El reproceso selectivo requiere un caso empresarial.")
    imagenes = set(solicitud.imagenes)
    rutas_validas = {i.get("ruta") for i in fila.get("imagenes", [])}
    if imagenes and not imagenes <= rutas_validas:
        raise HTTPException(400, "Se solicitó una imagen que no pertenece al caso.")
    if solicitud.modo_recorte == "manual" and solicitud.roi_manual:
        objetivo = next((i for i in fila.get("imagenes", [])
                         if not imagenes or i.get("ruta") in imagenes), None)
        if objetivo:
            proyecto = str(datos.get("raiz") or "proyecto")
            clave_roi = (Path(objetivo.get("ruta", "imagen")).name
                         if solicitud.roi_alcance == "etiqueta" else proyecto)
            GestorAprendizaje(CONFIG).guardar_roi_preferida(
                solicitud.roi_alcance, clave_roi, objetivo.get("fase"),
                solicitud.roi_manual, solicitud.zoom_forzado)
    with _pipeline_lock:
        if _pipeline_estado["estado"] in {"procesando", "pausado"}:
            raise HTTPException(409, "Ya hay un procesamiento activo.")
        _pipeline_continuar.set()
        _pipeline_cancelar.clear()
        _pipeline_estado.update({
            "estado": "procesando", "fase": "reproceso", "mensaje": "Preparando reproceso selectivo",
            "ruta": datos["raiz"], "iniciado_en": datetime.now().isoformat(timespec="seconds"),
            "finalizado_en": None, "error": None, "porcentaje": 0,
            "resultados_parciales": [], "tipo_st": fila.get("tipo_st"),
        })
        plantilla = datos.get("ruta_plantilla") or _pipeline_estado.get("ruta_plantilla")
        nombre_excel = _pipeline_estado.get("nombre_excel")
    hilo = threading.Thread(target=_ejecutar_pipeline_fondo, kwargs={
        "ruta": Path(datos["raiz"]), "nombre_excel": nombre_excel,
        "sobrescribir_excel": True, "tipo_st": fila.get("tipo_st"),
        "ruta_plantilla": plantilla, "casos_filtrados": {fila["case_key"]},
        "imagenes_filtradas": imagenes or None, "solo_errores": solicitud.solo_errores,
        "modo_recorte": solicitud.modo_recorte, "roi_manual": solicitud.roi_manual,
        "modo_ejecucion": "completo", "zoom_forzado": solicitud.zoom_forzado,
    }, daemon=True)
    hilo.start()
    return {"aceptado": True, "case_key": fila["case_key"],
            "imagenes": len(imagenes), "solo_errores": solicitud.solo_errores}


@app.get("/api/pruebas/{clave}")
def detalle(clave: str):
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    buscada = unquote(clave)
    fila = next((f for f in datos["resultados"] if _id_fila(f) == buscada), None)
    if fila is None and RUTA_ESTRUCTURA.is_file():
        try:
            estructura_actual = json.loads(RUTA_ESTRUCTURA.read_text(encoding="utf-8"))
            caso = next((c for c in estructura_actual.get("casos_empresariales", [])
                         if _id_fila(c) == buscada), None)
            if caso:
                fila = {**caso, "identificador": caso.get("metadata_ruta", {}).get("test_number"),
                        **caso.get("metadata_ruta", {}), "perfil": "empresarial",
                        "comparacion": {"resultado": "sin_procesar", "ratio": None,
                                        "coincidentes": [], "faltantes": []},
                        "confianza_ocr_pct": None, "qr_detectado": False,
                        "imagenes": [{"id": hashlib.sha256(f["ruta"].encode()).hexdigest()[:16],
                                      "nombre": Path(f["ruta"]).name, "ruta": f["ruta"],
                                      "ruta_relativa": f.get("ruta_relativa"), "fase": f.get("fase"),
                                      "tor": f.get("tor"), "rol": "foto_empresarial",
                                      "estado_imagen": "pendiente",
                                      "resultado_ocr": {}}
                                     for f in caso.get("fotos", [])],
                        "alertas": [], "observaciones": []}
        except (OSError, json.JSONDecodeError):
            pass
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
        _fila_publica(fila)["revision"]["estado"])
    raiz_local = _resolver_raiz_datos(datos)
    ruta_local = _reubicar_ruta(str(fila["ruta"]), datos, raiz_local) if raiz_local else None
    detalle_json["ruta_mostrada"] = str(ruta_local) if ruta_local else str(fila["ruta"])
    detalle_json["archivo_excel"] = datos.get("archivo_excel")
    detalle_json["alertas"] = _alertas_pendientes(
        "carpeta", _id_fila(fila), fila.get("alertas", []))
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
    correcciones = gestor.listar_correcciones_texto(rutas_locales)
    rotaciones = gestor.listar_rotaciones(rutas_locales)
    por_hash: dict[str, list[dict]] = {}
    for anotacion in anotaciones:
        por_hash.setdefault(anotacion["imagen_hash"], []).append(anotacion)
    correcciones_por_hash: dict[str, list[dict]] = {}
    for correccion in correcciones:
        correcciones_por_hash.setdefault(correccion["imagen_hash"], []).append(correccion)
    for item in fila.get("imagenes", []):
        publico = dict(item)
        publico["resultado_ocr"] = dict(item.get("resultado_ocr") or {})
        publico["ruta_api"] = f"/api/imagen?ruta={quote(str(item['ruta']), safe='')}"
        publico["anotaciones"] = []
        publico["correcciones"] = []
        if raiz_local:
            try:
                ruta_item = _resolver_imagen(str(item["ruta"]), datos, raiz_local)
                imagen_hash = hash_archivo(ruta_item)
                publico["anotaciones"] = por_hash.get(imagen_hash, [])
                publico["correcciones"] = correcciones_por_hash.get(imagen_hash, [])
                publico["resultado_ocr"] = _aplicar_correcciones_publicas(
                    publico.get("resultado_ocr") or {}, publico["correcciones"])
                rotacion = rotaciones.get(imagen_hash) or {}
                preferida = int(rotacion.get("grados", 0))
                ocr = publico.get("resultado_ocr") or {}
                aplicada = int(ocr.get("rotacion_manual_aplicada_grados") or 0)
                base = _orientacion_base_publica(ocr)
                ocr["orientacion_texto_base_grados"] = base
                ajuste = float(ocr.get("deskew_texto_aplicado_grados") or
                               ocr.get("deskew_aplicado_grados") or 0)
                ruta_codificada = quote(str(item["ruta"]), safe="")
                publico["rotacion_manual_preferida_grados"] = preferida
                publico["rotacion_pendiente"] = preferida != aplicada
                publico["ruta_api_visual"] = (
                    f"/api/imagen/orientada?ruta={ruta_codificada}"
                    f"&rotacion={(preferida + base) % 360}&ajuste={ajuste}")
                publico["ruta_api_orientada"] = (
                    f"/api/imagen/orientada?ruta={ruta_codificada}"
                    f"&rotacion={(aplicada + base) % 360}&ajuste={ajuste}")
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


@app.get("/api/imagen/orientada")
def imagen_orientada(ruta: str, rotacion: int = 0, ajuste: float = 0.0):
    """Vista enderezada, restringida a las mismas imágenes registradas."""
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    permitida = _resolver_raiz_datos(datos)
    if permitida is None:
        raise HTTPException(503, "La raíz de imágenes no está disponible en este equipo.")
    objetivo = _resolver_imagen(unquote(ruta), datos, permitida)
    if not objetivo.is_relative_to(permitida):
        raise HTTPException(403, "Ruta fuera de la raíz de datos permitida.")
    return _imagen_transformada(objetivo, rotacion, ajuste)


# Frontend estático: se monta al final para no tapar los endpoints /api.
app.mount("/", StaticFiles(directory=str(DIR_FRONTEND), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    puerto = int(CONFIG.get("dashboard", {}).get("puerto", 8000))
    print(f"Dashboard: http://127.0.0.1:{puerto}")
    uvicorn.run(app, host="127.0.0.1", port=puerto, log_level="warning")
