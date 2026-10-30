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

import contextlib
import hashlib
import importlib.util
import json
import math
import sys
import threading
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path, PureWindowsPath
from urllib.parse import quote, unquote

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ_PROYECTO))

from fastapi import Depends, FastAPI, HTTPException, Query, Request  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from configuracion import cargar_config, cargar_reglas, clasificar, evaluar_criterio  # noqa: E402
from aprendizaje import (GestorAprendizaje, hash_archivo, normalizar_codigo,
                         dimensiones_rotadas, rotar_bbox,
                         transformar_bbox_entre_rotaciones)  # noqa: E402
from ocr_engine import rotar_imagen_libre  # noqa: E402
from recursos import detectar_recursos  # noqa: E402
from gestor_recursos import PERFILES, normalizar_perfil, obtener_gestor_recursos  # noqa: E402
from flujo_empresarial import BaseConocimiento, CLAVES_PLANTILLA  # noqa: E402
from utilidades.matriz_apertura import (  # noqa: E402
    COLUMNAS_MATRIZ,
    construir_matriz_dashboard,
    criterio_desde_limites,
    evaluar_apertura,
    limites_predefinidos,
    validar_limites,
)
from utilidades.persistencia import escribir_json_seguro  # noqa: E402
from utilidades import persistencia_documento as _pdoc  # noqa: E402  (R15.2)
from utilidades.validacion_entradas import (  # noqa: E402
    es_raiz_codigo_seleccionada, validar_bbox_normalizado, validar_nombre_excel,
)
from utilidades.rutas_recursos import (  # noqa: E402
    partes_portables as _partes_portables_seguras,
    resolver_raiz_datos as _resolver_raiz_datos_segura,
    reubicar_ruta as _reubicar_ruta_segura,
)

CONFIG = cargar_config()
REGLAS = cargar_reglas()
RUTA_VALIDACION = RAIZ_PROYECTO / "validacion_resultados.json"
RUTA_ESTRUCTURA = RAIZ_PROYECTO / CONFIG.get("fase0", {}).get(
    "archivo_salida", "estructura_detectada.json")
RUTA_CHECKPOINT_PIPELINE = RAIZ_PROYECTO / ".cache_ocr" / "estado_pipeline.json"
DIR_FRONTEND = RAIZ_PROYECTO / "dashboard" / "frontend"

_PERSISTENCIA_CFG = CONFIG.get("persistencia", {}) or {}
_CHECKPOINT_DEBOUNCE = max(0.05, float(_PERSISTENCIA_CFG.get("checkpoint_debounce_segundos", 0.35)))
_EXCEL_DEBOUNCE = max(0.10, float(_PERSISTENCIA_CFG.get("excel_debounce_segundos", 0.80)))
_EXCEL_LATENCIA_MAX = max(_EXCEL_DEBOUNCE, float(_PERSISTENCIA_CFG.get("excel_latencia_max_segundos", 2.50)))

PATCH_BUILD = "16.0.5"

# ---------------------------------------------------------------------------
# R15.8 (ALTO-03, auditoría R15.7): POLÍTICA TRANSVERSAL de recuperación.
# Ningún endpoint mutante (POST/PUT/PATCH/DELETE) puede ejecutarse mientras el
# sistema esté en MODO RECUPERACIÓN, sea cual sea su pantalla. La salida única
# es el propio flujo de recuperación (prefijo ``/api/recuperacion/``), más las
# dos acciones de SEGURIDAD que detienen trabajo (pausar/cancelar el pipeline):
# detener análisis no crea estado nuevo y no puede quedar bloqueado por el
# modo. El test contractual del catálogo (R15.8) obliga a que toda ruta
# mutante nueva declare su política: guard transversal o exención declarada.
# ---------------------------------------------------------------------------

_ENDPOINTS_SEGUROS_EN_RECUPERACION = ("/api/recuperacion/",
                                       "/api/pipeline/pausar",
                                       "/api/pipeline/cancelar")


def _guard_recuperacion_transversal(peticion: Request) -> None:
    if str(peticion.method or "").upper() not in {"POST", "PUT", "PATCH",
                                                  "DELETE"}:
        return
    ruta = peticion.url.path
    if ruta.startswith(_ENDPOINTS_SEGUROS_EN_RECUPERACION):
        return
    _assert_sistema_recuperable(f"ejecutar {peticion.method} {ruta}")


app = FastAPI(title="OCR Versuchsmatrix", version=PATCH_BUILD,
              dependencies=[Depends(_guard_recuperacion_transversal)])


# Cache acotada de lecturas 0/90/180/270 de cajas exactas. Evita repetir
# cuatro inferencias al volver a un bloque ya inspeccionado; se invalida
# cuando cambia el archivo, su orientación o el modelo visual.
_variantes_lectura_cache: dict[tuple, dict] = {}
_variantes_lectura_lock = threading.Lock()
_VARIANTES_CACHE_MAX = 256

def _limpiar_cache_variantes() -> None:
    with _variantes_lectura_lock:
        _variantes_lectura_cache.clear()


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


class ProyectoSolicitud(BaseModel):
    """V15.9.2 (C7): proyecto declarado por el usuario ANTES de procesar.

    ``nombre_proyecto`` es el texto visible elegido por una persona;
    ``proyecto_id`` es su ID técnico estable (si se omite se deriva del
    nombre). ``sin_asignar=True`` es la decisión expresa de no identificar
    todavía el lote: queda pendiente y visible, nunca se hereda en silencio
    de la plantilla, la carpeta, la corrida anterior ni la config global.
    """
    nombre_proyecto: str | None = Field(default=None, max_length=120)
    proyecto_id: str | None = Field(default=None, max_length=80,
                                    pattern=r"^[a-z0-9._-]*$")
    sin_asignar: bool = False
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)
    # P04: cambiar el proyecto de un checkpoint exige esta bandera expresa.
    migracion_explicita: bool = False


class SolicitudPipeline(BaseModel):
    ruta: str = Field(min_length=1, max_length=4096)
    nombre_excel: str | None = Field(default=None, max_length=128)
    sobrescribir_excel: bool = False
    tipo_st: str | None = Field(default=None, pattern="^(1ST|2ST|LEGACY)$")
    ruta_plantilla: str | None = Field(default=None, max_length=4096)
    plantilla_id: str | None = Field(default=None, max_length=128)
    modo_ejecucion: str = Field(default="completo", pattern="^(completo|inventario|reanudar)$")
    ruta_inventario: str | None = Field(default=None, max_length=4096)
    idiomas_exportacion: list[str] = Field(default_factory=lambda: ["es"], min_length=1, max_length=3)
    # Uso interno al recuperar un checkpoint. No aparece como control visual.
    casos_omitidos: list[str] = Field(default_factory=list, max_length=100000)
    ejecucion_id: str | None = Field(default=None, max_length=128)
    perfil_rendimiento: str = Field(default="alto", pattern="^(estable|alto|maximo)$")
    contenido: str = Field(default="todo", pattern="^(todo|fotos|videos)$")
    # V15.9: rangos confirmados ANTES de iniciar. Sin ellos se usa la
    # preferencia vigente o los predeterminados 6/7 ms y se registra igual.
    rango_apertura: RangoAperturaSolicitud | None = None
    # V15.9.2 (C7): proyecto declarado explícitamente en el mismo diálogo
    # previo (dos bloques independientes: proyecto + rangos de apertura).
    proyecto: ProyectoSolicitud | None = None


class SolicitudRevisionVideo(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=256)
    video_id: str = Field(min_length=1, max_length=128)
    frame_index: int | None = Field(default=None, ge=0)
    tiempo_ms: float | None = Field(default=None, ge=0, le=100000)
    estado: str = Field(default="confirmado", pattern="^(confirmado|sin_evento|pendiente)$")
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)
    comentario: str | None = Field(default=None, max_length=2048)
    # V15.7.4: microzona exacta donde aparece el primer fragmento de bolsa.
    # Se separa de la ROI general para no hacer frágil el detector ante pequeños
    # movimientos de cámara.
    bbox_evento_norm: list[float] | None = Field(default=None, min_length=4, max_length=4)
    # R15 (MEDIA-14): CAS de documento; None = el cliente no versiona todavía.
    expected_revision: int | None = Field(default=None, ge=0)


class SolicitudZonaVideo(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=256)
    video_id: str = Field(min_length=1, max_length=128)
    bbox_norm: list[float] = Field(min_length=4, max_length=4)
    frame_index: int | None = Field(default=None, ge=0)
    tipo_camara: str | None = Field(default=None, max_length=64)
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)
    expected_revision: int | None = Field(default=None, ge=0)  # R15 (MEDIA-14)


class SolicitudZonaRevertir(BaseModel):
    """V15.9.1 (A1): restaura una ROI previa del historial del video."""
    prueba_id: str = Field(min_length=1, max_length=256)
    video_id: str = Field(min_length=1, max_length=128)
    indice: int = Field(default=0, ge=0, le=7)
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)
    expected_revision: int | None = Field(default=None, ge=0)  # R15 (MEDIA-14)


class SolicitudMaximoVideo(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=256)
    video_id: str = Field(min_length=1, max_length=128)
    frame_index: int = Field(ge=0, strict=True)
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)
    expected_revision: int | None = Field(default=None, ge=0)  # R15 (MEDIA-14)


class SolicitudCriteriosApertura(BaseModel):
    verde_max: float = Field(ge=0, allow_inf_nan=False, strict=True)
    amarillo_max: float = Field(gt=0, allow_inf_nan=False, strict=True)
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


class RangoAperturaSolicitud(BaseModel):
    """Rangos confirmados en el diálogo previo a «Procesar carpeta» (V15.9).

    ``origen``: ``predeterminado`` (6/7 ms), ``vigente`` (preferencia guardada)
    o ``elegido`` (capturados ahora). ``guardar_preferencia`` sólo se cumple si
    el usuario lo marcó explícitamente; si es falso, los rangos aplican sólo a
    este lote (instantánea) y la preferencia global no cambia. Con
    ``origen='predeterminado'`` NUNCA se guarda preferencia (V15.9.1, A7):
    los predeterminados son sólo para esa ejecución.
    """
    verde_max: float = Field(ge=0, allow_inf_nan=False)
    amarillo_max: float = Field(gt=0, allow_inf_nan=False)
    origen: str = Field(default="elegido", pattern="^(predeterminado|vigente|elegido)$")
    guardar_preferencia: bool = False
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


# SolicitudPipeline se define antes que este modelo; se reconstruye aquí para
# que la anotación diferida quede resuelta antes de cualquier instanciación.
SolicitudPipeline.model_rebuild()


class SolicitudRefinarZonaVideo(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=256)
    video_id: str = Field(min_length=1, max_length=128)
    bbox_norm: list[float] = Field(min_length=4, max_length=4)
    frame_index: int = Field(ge=0)


class SolicitudReanalisisVideos(BaseModel):
    prueba_id: str | None = Field(default=None, max_length=256)
    video_id: str | None = Field(default=None, max_length=128)


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
    componente: str | None = Field(default=None, pattern="^(bolsa_aire|tablero|otro|por_identificar)$")
    expected_revision: int | None = Field(default=None, ge=0)  # R15.1 (ALTO-02): CAS opcional en writers del documento.


class SolicitudExportacion(BaseModel):
    idiomas: list[str] = Field(default_factory=lambda: ["es"], min_length=1, max_length=3)


class SolicitudConsolidacion(BaseModel):
    archivos: list[str] = Field(min_length=1, max_length=20)
    regenerar_excel: bool = True
    expected_revision: int | None = Field(default=None, ge=0)  # R15.1 (ALTO-02): CAS opcional en writers del documento.


class SolicitudCorreccion(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    campo: str = Field(default="etiqueta", pattern="^(etiqueta|referencia)$")
    imagen_id: str | None = Field(default=None, max_length=128)
    texto_ocr: str = Field(min_length=1, max_length=4096)
    texto_correcto: str = Field(default="", max_length=4096)
    bbox: list[int] | None = Field(default=None, min_length=4, max_length=4)
    tipo_unidad: str | None = Field(default=None, max_length=32)
    componente: str | None = Field(default=None, pattern="^(bolsa_aire|tablero|otro|por_identificar)$")
    campo_destino: str | None = Field(default=None, max_length=128)
    estrategia_ocr: dict | None = None
    accion: str = Field(default="guardar_sin_entrenar", pattern=(
        "^(aceptar|corregir|ilegible|no_es_campo|guardar_sin_entrenar|confirmar_entrenar)$"))
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)
    expected_revision: int | None = Field(default=None, ge=0)  # R15.1 (ALTO-02)


class SolicitudAnotacionRegion(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    imagen_id: str = Field(min_length=1, max_length=128)
    bbox: list[int] = Field(min_length=4, max_length=4)
    # V14.13: cualquier recorte confirmado puede conservar cuatro esquinas
    # independientes. El bbox se mantiene por compatibilidad/indexación.
    poligono: list[list[float]] | None = None
    texto_correcto: str = Field(min_length=1, max_length=8192)
    proponer_entrenamiento: bool = True
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


class SolicitudNoTexto(SolicitudAnotacionRegion):
    texto_correcto: str = Field(default="", max_length=8192)
    restaurar: bool = False


class SolicitudNoTextoLote(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    imagen_id: str = Field(min_length=1, max_length=128)
    bboxes: list[list[int]] = Field(min_length=1, max_length=500)
    restaurar: bool = False
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


class SolicitudOrientacionRegional(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    imagen_id: str = Field(min_length=1, max_length=128)
    marco: str = Field(pattern="^[a-f0-9]{64}$")
    grados: int | None = None


def _resolver_region_orientacion(prueba_id, imagen_id, marco):
    datos = _cargar_datos()
    fila = next((f for f in (datos or {}).get("resultados", [])
                 if _id_fila(f) == prueba_id), None)
    if fila is None:
        raise HTTPException(404, "Carpeta no encontrada.")
    item = next((i for i in fila.get("imagenes", []) if i.get("id") == imagen_id), None)
    if item is None:
        raise HTTPException(404, "Imagen no encontrada.")
    region = next((r for r in ((item.get("resultado_ocr") or {}).get("recortes") or [])
                   if r.get("marco") == marco), None)
    if region is None:
        raise HTTPException(409, "El recorte cambió. Actualiza el detalle y selecciónalo otra vez.")
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "No se encuentra la raíz de imágenes.")
    ruta = _resolver_imagen(str(item["ruta"]), datos, raiz)
    huella = (item.get("resultado_ocr") or {}).get("huella_imagen")
    if not huella or hash_archivo(ruta) != huella:
        raise HTTPException(409, "La imagen cambió desde su OCR. Reprocésala antes de elegir orientación.")
    return fila, item, region, ruta


@app.post("/api/aprendizaje/orientacion-region")
def guardar_orientacion_region(solicitud: SolicitudOrientacionRegional):
    # R15.6 (ALTO-09): no cambiar preferencias mientras el pipeline utiliza
    # el modelo — guard uniforme (hilo + reserva + estado), antes de cualquier
    # lookup o efecto.
    _assert_pipeline_inactivo("cambiar la orientación regional")
    fila, item, region, ruta = _resolver_region_orientacion(
        solicitud.prueba_id, solicitud.imagen_id, solicitud.marco)
    gestor = GestorAprendizaje(CONFIG)
    if gestor.estado_revision("carpeta", solicitud.prueba_id,
            _fila_publica(fila)["revision"]["estado"])["estado"] == "completada":
        raise HTTPException(409, "Reabre la revisión antes de editar.")
    try:
        resultado = gestor.guardar_orientacion_regional(ruta, solicitud.marco, solicitud.grados)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"guardada": True, **resultado,
            "mensaje": "Orientación guardada. Reprocesa la imagen visible para actualizar texto y cajas."}


@app.get("/api/imagen/region-orientacion")
def vista_region_orientacion(prueba_id: str, imagen_id: str, marco: str, grados: int = 0):
    if grados not in (0,90,180,270):
        raise HTTPException(400, "Ángulo no válido.")
    _, item, region, ruta = _resolver_region_orientacion(prueba_id, imagen_id, marco)
    import cv2
    from ocr_engine import cargar_imagen, _recorte_perspectiva, _rotar_recto
    ocr = item.get("resultado_ocr") or {}
    foto = rotar_imagen_libre(cargar_imagen(str(ruta)),
                             float(ocr.get("rotacion_manual_aplicada_grados") or 0))
    if region.get("poligono_fuente"):
        recorte = _recorte_perspectiva(foto, region["poligono_fuente"])
    else:
        x,y,w,h = map(int,region["bbox"])
        recorte = foto[max(0,y):y+h,max(0,x):x+w]
    if not recorte.size:
        raise HTTPException(409, "Recorte vacío; reprocesa la imagen.")
    recorte = _rotar_recto(recorte, grados)
    escala = min(1.0, 768/max(recorte.shape[:2]))
    if escala < 1:
        recorte = cv2.resize(recorte, None, fx=escala, fy=escala)
    ok, imagen = cv2.imencode(".png", recorte)
    if not ok:
        raise HTTPException(500, "No se pudo preparar la previsualización.")
    return Response(imagen.tobytes(), media_type="image/png")


@app.post("/api/aprendizaje/no-texto")
def marcar_region_no_texto(solicitud: SolicitudNoTexto):
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    fila = next((f for f in datos["resultados"] if _id_fila(f) == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "Carpeta no encontrada.")
    gestor = GestorAprendizaje(CONFIG)
    if gestor.estado_revision("carpeta", solicitud.prueba_id,
                             _fila_publica(fila)["revision"]["estado"])["estado"] == "completada":
        raise HTTPException(409, "Reabre la revisión antes de editar.")
    item = next((i for i in fila.get("imagenes", []) if i.get("id") == solicitud.imagen_id), None)
    if not item:
        raise HTTPException(404, "Imagen no encontrada en esta carpeta.")
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "Raíz de imágenes no disponible.")
    ruta = _resolver_imagen(str(item["ruta"]), datos, raiz)
    ocr = item.get("resultado_ocr") or {}
    if solicitud.restaurar:
        unidades = gestor.filtrar_no_texto(ocr, ruta).get("regiones_no_texto", [])
    else:
        unidades = [*(ocr.get("tokens") or []), *(ocr.get("lineas_texto") or [])]
    unidad = next((u for u in unidades if _bbox_igual(u.get("bbox"), solicitud.bbox)), None)
    if unidad is None:
        raise HTTPException(400, "Selecciona una detección existente o un descarte activo.")

    # R15.6 (MEDIO-06): marca + estado de revisión en una sola transacción.
    def _efectos():
        efecto = gestor.marcar_no_texto(
            ruta, solicitud.bbox,
            str(unidad.get("texto_ocr") or unidad.get("texto") or ""),
            solicitud.usuario, activo=not solicitud.restaurar)
        gestor.actualizar_revision("carpeta", solicitud.prueba_id,
                                   estado="parcial")
        return efecto

    resultado = _transaccion_efecto_humano(
        "marca de región sin texto", gestor, "carpeta", solicitud.prueba_id,
        _efectos,
        recurso=_recurso_imagen(solicitud.prueba_id, solicitud.imagen_id),
        ruta_imagen=ruta)
    _regenerar_excel(resultado)
    return resultado


@app.post("/api/aprendizaje/no-texto-lote")
def marcar_regiones_no_texto_lote(solicitud: SolicitudNoTextoLote):
    """Descarta/restaura varias detecciones de una imagen con una sola recarga de Excel."""
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    fila = next((f for f in datos["resultados"] if _id_fila(f) == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "Carpeta no encontrada.")
    gestor = GestorAprendizaje(CONFIG)
    if gestor.estado_revision("carpeta", solicitud.prueba_id,
                             _fila_publica(fila)["revision"]["estado"])["estado"] == "completada":
        raise HTTPException(409, "Reabre la revisión antes de editar.")
    item = next((i for i in fila.get("imagenes", []) if i.get("id") == solicitud.imagen_id), None)
    if not item:
        raise HTTPException(404, "Imagen no encontrada en esta carpeta.")
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "Raíz de imágenes no disponible.")
    ruta = _resolver_imagen(str(item["ruta"]), datos, raiz)
    ocr = item.get("resultado_ocr") or {}
    fuente_unidades = (gestor.filtrar_no_texto(ocr, ruta).get("regiones_no_texto", [])
                       if solicitud.restaurar else
                       [*(ocr.get("tokens") or []), *(ocr.get("lineas_texto") or [])])
    unicas = []
    vistas = set()
    for bbox in solicitud.bboxes:
        if len(bbox) != 4:
            raise HTTPException(400, "Cada región debe contener x, y, ancho y alto.")
        limpia = tuple(int(round(float(v))) for v in bbox)
        if limpia in vistas:
            continue
        vistas.add(limpia)
        unicas.append(list(limpia))
    if not unicas:
        raise HTTPException(400, "No hay regiones válidas para procesar.")
    pares = []
    for bbox in unicas:
        unidad = next((u for u in fuente_unidades if _bbox_igual(u.get("bbox"), bbox)), None)
        if unidad is None:
            raise HTTPException(400, f"La región {bbox} ya no coincide con una detección disponible.")
        pares.append((bbox, str(unidad.get("texto_ocr") or unidad.get("texto") or "")))

    # R15.6 (MEDIO-06): lote ATÓMICO — todas las marcas + la revisión se
    # aplican dentro de una sola transacción compensable; si cualquier marca
    # falla, el snapshot común restaura también las ya aplicadas.
    def _efectos():
        resultados = [gestor.marcar_no_texto(
                          ruta, bbox, texto, solicitud.usuario,
                          activo=not solicitud.restaurar)
                      for bbox, texto in pares]
        gestor.actualizar_revision("carpeta", solicitud.prueba_id,
                                   estado="parcial")
        return resultados

    resultados = _transaccion_efecto_humano(
        "marca por lote de regiones sin texto", gestor, "carpeta",
        solicitud.prueba_id, _efectos,
        recurso=_recurso_imagen(solicitud.prueba_id, solicitud.imagen_id),
        ruta_imagen=ruta)
    respuesta = {"actualizadas": len(resultados), "restauradas": bool(solicitud.restaurar),
                 "mensaje": (f"{len(resultados)} regiones restauradas." if solicitud.restaurar
                             else f"{len(resultados)} textos descartados; puedes restaurarlos después.")}
    _regenerar_excel(respuesta)
    return respuesta


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
    grados: float = Field(ge=-360, le=360)
    usar_automatico: bool = False
    expected_revision: int | None = Field(default=None, ge=0)  # R15.1 (ALTO-02): CAS opcional en writers del documento.


class SolicitudPlantilla(BaseModel):
    ruta: str = Field(min_length=1, max_length=4096)
    nombre: str | None = Field(default=None, max_length=128)
    tipos_st: list[str] = Field(default_factory=list, max_length=2)
    marcadores_ruta: list[str] = Field(default_factory=list, max_length=20)


class SolicitudDetencion(BaseModel):
    accion: str = Field(default="conservar_avance", pattern="^(conservar_avance|fin_id)$")


class SolicitudImagenSinDatos(BaseModel):
    tipo: str = Field(pattern="^(carpeta|externa)$")
    prueba_id: str = Field(min_length=1, max_length=128)
    imagen_id: str | None = Field(default=None, max_length=128)
    motivo: str | None = Field(default=None, max_length=512)
    expected_revision: int | None = Field(default=None, ge=0)  # R15.1 (ALTO-02): CAS opcional en writers del documento.
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


class SolicitudImagenVerificada(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    imagen_id: str = Field(min_length=1, max_length=128)
    expected_revision: int | None = Field(default=None, ge=0)  # R15.1 (ALTO-02): CAS opcional en writers del documento.
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


class SolicitudCorreccionExterna(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    texto_ocr: str = Field(min_length=1, max_length=4096)
    texto_correcto: str = Field(default="", max_length=4096)
    bbox: list[int] | None = Field(default=None, min_length=4, max_length=4)
    accion: str = Field(default="guardar_sin_entrenar", pattern=(
        "^(aceptar|corregir|ilegible|no_es_campo|guardar_sin_entrenar|confirmar_entrenar)$"))
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


class SolicitudRegionExterna(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    bbox: list[int] = Field(min_length=4, max_length=4)
    texto_correcto: str = Field(min_length=1, max_length=8192)
    proponer_entrenamiento: bool = True
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


_pipeline_lock = threading.Lock()
_pipeline_continuar = threading.Event()
_pipeline_continuar.set()
_pipeline_cancelar = threading.Event()
_pipeline_detener_fin_id = threading.Event()
_pipeline_hilo: threading.Thread | None = None
# R15 (auditoría R14, CRIT-01/ALTA-02): reserva del ÚNICO slot de worker.
# En R14 existía una ventana de carrera entre comprobar ``is_alive()`` dentro
# del lock y asignar/arrancar el hilo después de persistir el checkpoint: dos
# solicitudes simultáneas podían ser admitidas y arrancar dos pipelines. La
# reserva se adquiere de forma ATÓMICA en el mismo lock que cambia el estado
# y se libera cuando el hilo arranca (o mediante rollback si algo falla).
_pipeline_reserva: dict | None = None


def _slot_pipeline_ocupado_locked() -> bool:
    """True si el slot del worker está ocupado o reservado.

    Debe llamarse con ``_pipeline_lock`` adquirido. ``is_alive()`` solo no
    basta: un hilo creado pero todavía no arrancado devuelve False.
    """
    if _pipeline_reserva is not None:
        return True
    return bool(_pipeline_hilo is not None and _pipeline_hilo.is_alive())


def _rollback_admision_pipeline(estado_anterior: dict,
                                hilo_fallido: "threading.Thread | None" = None,
                                ) -> None:
    """R15: deshace la admisión (estado, reserva, hilo) si el arranque falla.

    El slot es exclusivo: entre la admisión y el rollback ninguna otra
    solicitud pudo tomarlo (todas reciben 409 mientras la reserva existe), de
    modo que restaurar la instantánea previa es seguro. Vuelve a persistir el
    checkpoint para no dejar un «procesando fantasma» (prueba obligatoria 4).
    """
    global _pipeline_hilo, _pipeline_reserva
    with _pipeline_lock:
        _pipeline_estado.clear()
        _pipeline_estado.update(estado_anterior)
        _pipeline_reserva = None
        if hilo_fallido is not None and _pipeline_hilo is hilo_fallido:
            _pipeline_hilo = None
    try:
        _persistir_checkpoint_pipeline()
    except Exception:  # noqa: BLE001 — el rollback no enmascara el error original
        pass
_pipeline_excel_lock = threading.Lock()
_externas_lock = threading.Lock()
_entrenamiento_lock = threading.Lock()
_entrenamiento_estado = {"estado": "inactivo", "resultado": None, "error": None,
                         "modo": None, "pendiente_auto": False,
                         "ultimo_rowid_entrenado": 0}
_entrenamiento_auto_guard = threading.Lock()
_entrenamiento_auto_timer: threading.Timer | None = None
_pipeline_estado: dict = {
    "estado": "inactivo", "fase": None, "mensaje": None, "ruta": None,
    "iniciado_en": None, "finalizado_en": None, "error": None, "resumen": None,
    "bitacora": None, "porcentaje": 0, "procesadas": 0, "total": 0,
    "restantes": 0, "eta_segundos": None, "transcurrido_segundos": 0,
    # V14.1: el reloj mide sólo tiempo activo. La pausa no incrementa este valor.
    "transcurrido_base_segundos": 0, "segmento_activo_iniciado_en": None,
    "pausado_en": None,
    "resultados_parciales": [], "imagenes_procesadas": 0, "imagenes_total": 0,
    "imagenes_restantes": 0, "imagen_actual": None, "actualizado_en": None,
    "recursos": None, "nombre_excel": None, "ultimo_id": None,
    "ultimo_id_nombre": None, "reanudable": False, "solicitud": None,
    "archivo_excel_parcial": None, "excel_parcial_actualizado_en": None,
    "advertencia_excel_parcial": None, "excel_parcial_pendiente": False,
    "archivos_excel_parcial": {}, "archivos_excel": {},
    "archivos_excel_parcial_borrador": {}, "archivos_excel_borrador": {},
    "idiomas_exportacion": ["es"],
    "advertencias_cache": [],
    "ejecucion_id": None,
    "perfil_rendimiento": "alto",
    "metricas_recursos": {},
}


# V15.5: reproceso de video independiente del OCR. Permite recalcular sólo
# los AVI con el algoritmo actual sin repetir las imágenes ni borrar aprendizaje.
_video_reanalisis_lock = threading.Lock()
_video_reanalisis_hilo: threading.Thread | None = None
_video_reanalisis_estado: dict = {
    "estado": "inactivo", "mensaje": None, "prueba_id": None, "video_id": None,
    "total_videos": 0, "procesados": 0, "errores": 0, "video_actual": None,
    "iniciado_en": None, "finalizado_en": None, "ultimo_error": None,
    "algoritmo": None,
}


def _parse_fecha_pipeline(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return None


def _tiempo_activo_pipeline_locked(ahora: datetime | None = None) -> float:
    """Tiempo activo acumulado, excluyendo cualquier intervalo en pausa.

    Debe llamarse con ``_pipeline_lock`` adquirido. El valor base se congela al
    pausar; al continuar comienza un segmento nuevo. Esto también permite
    reanudar un checkpoint sin contar el tiempo que el programa estuvo cerrado.
    """
    ahora = ahora or datetime.now()
    base = float(_pipeline_estado.get("transcurrido_base_segundos") or 0.0)
    guardado = float(_pipeline_estado.get("transcurrido_segundos") or 0.0)
    inicio_segmento = _parse_fecha_pipeline(_pipeline_estado.get("segmento_activo_iniciado_en"))
    if inicio_segmento is not None and _pipeline_estado.get("estado") in {
            "procesando", "pausando", "cancelando", "reanudando"}:
        base += max(0.0, (ahora - inicio_segmento).total_seconds())
        return round(max(base, guardado), 1)
    # V15.5: al pasar a completado/error el segmento deja de estar activo, pero
    # ``transcurrido_segundos`` ya contiene el total calculado justo antes del
    # cambio de estado. No volver a caer al base (que puede seguir en 0).
    return round(max(base, guardado), 1)


def _congelar_tiempo_pipeline_locked(ahora: datetime | None = None) -> float:
    """Congela el reloj activo al solicitar una pausa."""
    ahora = ahora or datetime.now()
    total = _tiempo_activo_pipeline_locked(ahora)
    _pipeline_estado.update(
        transcurrido_base_segundos=total, transcurrido_segundos=total,
        segmento_activo_iniciado_en=None,
        pausado_en=ahora.isoformat(timespec="milliseconds"),
    )
    return total


def _reanudar_tiempo_pipeline_locked(ahora: datetime | None = None) -> None:
    """Inicia un nuevo segmento activo sin sumar el tiempo que duró la pausa."""
    ahora = ahora or datetime.now()
    _pipeline_estado.update(
        segmento_activo_iniciado_en=ahora.isoformat(timespec="milliseconds"),
        pausado_en=None,
        transcurrido_segundos=float(_pipeline_estado.get("transcurrido_base_segundos") or 0.0),
    )


def _tiempo_activo_pipeline() -> float:
    with _pipeline_lock:
        return _tiempo_activo_pipeline_locked()


_checkpoint_timer_lock = threading.Lock()
_checkpoint_timer: threading.Timer | None = None


def _persistir_checkpoint_pipeline() -> bool:
    """Guarda de inmediato el checkpoint crítico con reemplazo atómico.

    Se usa en pausa, cancelación, cierre y cambios de estado. Los eventos de
    progreso frecuentes usan ``_programar_checkpoint_pipeline`` para no hacer
    un fsync completo varias veces por segundo.
    """
    global _checkpoint_timer
    with _checkpoint_timer_lock:
        if _checkpoint_timer is not None and _checkpoint_timer.is_alive():
            _checkpoint_timer.cancel()
        _checkpoint_timer = None
    with _pipeline_lock:
        serializable = deepcopy(_pipeline_estado)
    resultado = escribir_json_seguro(
        RUTA_CHECKPOINT_PIPELINE, serializable, compacto=True)
    if not resultado:
        with _pipeline_lock:
            advertencias = _pipeline_estado.setdefault("advertencias_cache", [])
            if resultado.error and resultado.error not in advertencias:
                advertencias.append(resultado.error)
    return bool(resultado)


def _programar_checkpoint_pipeline() -> None:
    """Agrupa eventos de progreso muy seguidos y persiste sólo el más reciente.

    El retardo es corto (350 ms por defecto), así que ante un cierre inesperado
    se pierde como máximo una fracción mínima del progreso visual, mientras que
    pausa/cancelación/finalización siguen forzando una escritura inmediata.
    """
    global _checkpoint_timer

    def guardar() -> None:
        global _checkpoint_timer
        with _pipeline_lock:
            serializable = deepcopy(_pipeline_estado)
        resultado = escribir_json_seguro(
            RUTA_CHECKPOINT_PIPELINE, serializable, compacto=True)
        if not resultado:
            with _pipeline_lock:
                advertencias = _pipeline_estado.setdefault("advertencias_cache", [])
                if resultado.error and resultado.error not in advertencias:
                    advertencias.append(resultado.error)
        with _checkpoint_timer_lock:
            _checkpoint_timer = None

    with _checkpoint_timer_lock:
        if _checkpoint_timer is not None and _checkpoint_timer.is_alive():
            _checkpoint_timer.cancel()
        _checkpoint_timer = threading.Timer(_CHECKPOINT_DEBOUNCE, guardar)
        _checkpoint_timer.daemon = True
        _checkpoint_timer.start()


def _recuperar_checkpoint_pipeline() -> None:
    if not RUTA_CHECKPOINT_PIPELINE.is_file():
        return
    try:
        guardado = json.loads(RUTA_CHECKPOINT_PIPELINE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Auditoría R14: un checkpoint corrupto no se ignora en silencio. No se
        # borra ni se sobreescribe: queda disponible para diagnóstico y el
        # dashboard explica que no puede reanudarse automáticamente.
        _pipeline_estado.setdefault("advertencias_cache", []).append(
            f"Checkpoint de ejecución ilegible; no se reanudó automáticamente: {type(exc).__name__}: {exc}")
        _pipeline_estado.update(estado="inactivo", reanudable=False,
                                mensaje="El checkpoint anterior está dañado; inicia una ejecución nueva o revisa el archivo de recuperación.")
        return
    if not isinstance(guardado, dict):
        return
    _pipeline_estado.update({k: v for k, v in guardado.items() if k in _pipeline_estado})
    if _pipeline_estado.get("estado") in {"procesando", "pausando", "cancelando"}:
        # Tras un reinicio no se conoce con precisión el último segmento activo;
        # se conserva el último valor confirmado y el tiempo cerrado no se suma.
        confirmado = float(_pipeline_estado.get("transcurrido_segundos") or 0.0)
        _pipeline_estado.update({
            "estado": "pausado", "reanudable": True,
            "mensaje": "Ejecución recuperada; puedes reanudar desde el avance guardado.",
            "transcurrido_base_segundos": confirmado,
            "segmento_activo_iniciado_en": None,
            "pausado_en": datetime.now().isoformat(timespec="milliseconds"),
        })
    elif _pipeline_estado.get("estado") == "pausado":
        confirmado = float(_pipeline_estado.get("transcurrido_segundos") or 0.0)
        _pipeline_estado.update(
            transcurrido_base_segundos=confirmado,
            segmento_activo_iniciado_en=None,
        )


_recuperar_checkpoint_pipeline()

# ---------------------------------------------------------------------------
# Carga de datos con caché por mtime (refresco automático tras cada pipeline)
# ---------------------------------------------------------------------------

_cache: dict = {"mtime": None, "datos": None}
# V15.9.4 (ALTA-N5): si la migración de consensos no se pudo PERSISTIR, no se
# declara hecha: se expone aquí (visible en /api/estado) y se invalida la
# caché para reintentarla en la próxima carga. Los datos anteriores del disco
# se conservan intactos.
_advertencia_migracion_consensos: str | None = None
_cache_rutas_registradas: dict = {"firma": None, "rutas": set()}


def _degradar_campos_consenso_legacy(fila: dict) -> None:
    """V15.9.3 (CRIT-01): degrada a pendiente el tiempo publicado por un
    consenso legado inválido, conservando la medida como evidencia.

    No toca correcciones manuales del campo ni valores cuya fuente no sea el
    consenso de video. El estado ``pendiente_revision`` se muestra sin colorear
    (tooltip), igual que las propuestas sin confirmar de V15.9.1 (B1).
    """
    if (fila.get("correcciones_manual_campos") or {}).get("opening_time_ms"):
        return
    motivos = [str(x) for x in ((fila.get("video_apertura") or {}).get("motivo_revision") or [])]
    contenedores = [fila.get("campos"), (fila.get("consolidado") or {}).get("campos")]
    for contenedor in contenedores:
        if not isinstance(contenedor, dict):
            continue
        dato = contenedor.get("opening_time_ms")
        if not isinstance(dato, dict):
            continue
        if not str(dato.get("fuente") or "").startswith("video"):
            continue
        if dato.get("estado") == "pendiente_revision":
            continue
        dato["estado"] = "pendiente_revision"
        dato["requiere_revision"] = True
        dato["motivos_revision"] = motivos


def _migrar_fila_consensos(fila, algoritmo_version: str, consenso_videos,
                           consenso_valido) -> bool:
    """R15.2 (CRÍTICO-01): migración de UNA fila; idempotente y sin persistir.

    Devuelve True si la fila cambió. El llamador decide sobre qué documento
    aplicarla: la vista en memoria (degradación fail-closed para mostrar) o
    el documento fresco bajo lock (única base válida para persistir).
    """
    if not isinstance(fila, dict):
        return False
    anterior = fila.get("video_apertura")
    if not isinstance(anterior, dict) or not anterior:
        return False
    if anterior.get("algoritmo_consenso") == algoritmo_version:
        return False
    videos = fila.get("videos") or []
    if not videos:
        # V15.9.3 (CRIT-01): sin videos originales que recalcular, el
        # consenso legado se juzga con la regla vigente. Si NO la supera
        # (p.ej. metadatos incompletos sin ``total_principales``, o
        # soporte 2 con total 4), no se publica: la evidencia original se
        # conserva en ``video_apertura_anterior``, la fila queda marcada
        # para revisión y el tiempo que ese consenso hubiera publicado se
        # degrada a ``pendiente_revision`` conservando la medida. Si la
        # supera, sólo se sella la versión del algoritmo para no
        # re-juzgarlo en cada carga (sin elevar ni cambiar su estado).
        if consenso_valido(anterior):
            fila["video_apertura"] = {**anterior,
                                      "algoritmo_consenso": algoritmo_version}
            return True
        fila["video_apertura_anterior"] = anterior
        motivos = [str(x) for x in (anterior.get("motivo_revision") or [])]
        motivos.append(
            "V15.9.3 (CRIT-01): consenso legado con metadatos incompletos o "
            "regla obsoleta; sin videos originales para recalcular, se "
            "conserva como evidencia pendiente de revisión humana.")
        fila["video_apertura"] = {**anterior,
                                  "algoritmo_consenso": algoritmo_version,
                                  "requiere_revision": True,
                                  "motivo_revision": motivos}
        _degradar_campos_consenso_legacy(fila)
        return True
    try:
        fila["video_apertura_anterior"] = anterior
        consenso = consenso_videos(videos, CONFIG)
        _aplicar_consenso_video_a_fila(fila, consenso)
        return True
    except Exception:
        fila.pop("video_apertura_anterior", None)
        return False


def _migrar_consensos_video(datos: dict) -> int:
    """V15.9.2 (C1): reevalúa consensos persistidos con reglas anteriores.

    Un consenso guardado por una versión previa del algoritmo de consolidación
    (p.ej. los 2/4 que V15.8.x publicaba como confirmados) NO se vuelve a
    publicar tal cual: se conserva el resultado original como evidencia en
    ``video_apertura_anterior`` y se recalcula la confirmación con la regla
    vigente (soporte 3-de-4, causas graves B2, alertas sin clasificar C2).
    Las confirmaciones manuales reales se preservan porque viven en los items
    de video y el recálculo las respeta. La migración se persiste una sola
    vez vía la primitiva compartida, re-aplicando el patch por fila sobre el
    documento FRESCO bajo lock (R15.2); si algo falla, no se aborta la carga
    (la vista usa datos en memoria).
    """
    try:
        from video_airbag import (CONSENSO_ALGORITMO_VERSION, consenso_videos,
                                  consenso_valido)
    except Exception:
        return 0

    def _migrar_fila(fila):
        return _migrar_fila_consensos(fila, CONSENSO_ALGORITMO_VERSION,
                                      consenso_videos, consenso_valido)

    migradas = sum(1 for fila in (datos.get("resultados", []) or [])
                   if _migrar_fila(fila))
    if migradas:
        # V15.9.4 (ALTA-N5): la migración sólo se declara si quedó PERSISTIDA.
        # Con escritura fallida (guardado=False o excepción) no se cuenta como
        # hecha: se invalida la caché para reintentar en la próxima carga, se
        # expone el fallo en /api/estado y los datos anteriores del disco se
        # conservan intactos. La vista en memoria conserva la degradación
        # fail-closed (evidencia en ``video_apertura_anterior`` preservada).
        #
        # R15.2 (CRÍTICO-01): la persistencia NO escribe el snapshot leído
        # antes de migrar — eso perdería commits concurrentes (carreras con
        # ediciones UI/pipeline). Se delega en la primitiva compartida, que
        # bajo el lock ÚNICO lee el documento FRESCO y re-aplica el patch por
        # fila (idempotente); si el documento fresco ya quedó migrado por una
        # ejecución concurrente, no se commitea (SIN_CAMBIOS).
        global _advertencia_migracion_consensos
        detalle_error = None
        try:
            def _persistir_migracion(frescos):
                aplicadas = sum(1 for fila in (frescos.get("resultados", []) or [])
                                if _migrar_fila(fila))
                return aplicadas if aplicadas else _pdoc.SIN_CAMBIOS

            # Se llama a la primitiva compartida DIRECTA (no al envoltorio
            # HTTP): la migración corre DENTRO de ``_cargar_datos`` y el
            # post_commit de invalidación de caché descartaría la vista que
            # se está cargando. El mtime cacheado queda anterior a esta
            # escritura: la próxima carga detecta el cambio y releé.
            _revision, _aplicadas = _pdoc.mutar_documento(
                RUTA_VALIDACION, _persistir_migracion)
        except Exception as exc:  # noqa: BLE001 — se comunica, no se aborta la carga
            detalle_error = f"{type(exc).__name__}: {exc}"
        if detalle_error:
            _advertencia_migracion_consensos = (
                f"La migración de consensos legados ({migradas} fila(s)) NO se "
                f"pudo persistir en {RUTA_VALIDACION.name}: {detalle_error}. "
                "El archivo anterior sigue intacto y el reanálisis queda "
                "pendiente; se reintentará en la próxima carga. Revisa espacio/"
                "permisos del disco.")
            _cache["mtime"] = None  # fuerza recarga + reintento
            with _pipeline_lock:
                advertencias = _pipeline_estado.setdefault("advertencias_cache", [])
                if _advertencia_migracion_consensos not in advertencias:
                    advertencias.append(_advertencia_migracion_consensos)
            return 0
        _advertencia_migracion_consensos = None
    return migradas


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
        # Feedback separado: no reescribir resultados/checkpoints para añadir
        # un máximo manual, ni mezclarlo con opening/full_inflation_time_ms.
        from maximos_video import incorporar_maximos
        for fila in cargados.get("resultados", []):
            incorporar_maximos(fila)
        # V15.9.2 (C1): migración única de consensos con regla obsoleta.
        _migrar_consensos_video(cargados)
    return _cache["datos"]


# R15 (ALTA-03 + ALTA-07 + MEDIA-14) + R15.2 (CRÍTICO-01/CRÍTICO-02): la
# política central de mutación de validacion_resultados.json vive en
# ``utilidades.persistencia_documento``, la ÚNICA autoridad de escritura
# compartida por backend, pipeline y validación. Contrato: lock por ruta →
# leer fresco → validar revisión (CAS) → aplicar patch → incrementar
# ``revision_documento`` → escritura atómica verificada. Los commits de fondo
# (reanálisis) aplican un merge por video sobre el documento MÁS RECIENTE en
# disco en lugar de reescribir un snapshot completo: una edición humana hecha
# durante el reanálisis sobrevive. Los endpoints mutantes aceptan
# ``expected_revision`` (compare-and-swap): si otra pestaña ya cambió el
# documento, se responde 409 «recarga antes de guardar».


def _lock_documento() -> "threading.RLock":
    """Lock de la autoridad única para el documento activo (compartido)."""
    return _pdoc.lock_documento(RUTA_VALIDACION)


def _invalidar_cache_documento(_revision: int, _datos: dict) -> None:
    _cache.update({"mtime": None, "datos": None})


# R15.4 (HIGH-01): mensaje único para fallo de escritura del documento.
_MSG_GUARDADO_FALLO = (
    "No se pudo guardar el documento de resultados (disco, permisos o "
    "archivo bloqueado). El cambio NO se aplicó. Revisa espacio/permisos y "
    "vuelve a intentarlo.")


# R15.4 (MEDIUM-02): reserva de operación por recurso. Las etapas pesadas
# (análisis de video) corren FUERA del lock del documento; la reserva
# garantiza que una segunda operación incompatible sobre el mismo recurso
# reciba 423 inmediato con mensaje visible, en vez de esperar el lock en
# silencio. El lock documental sólo se toma en entradas/salidas cortas.
_operaciones_lock = threading.Lock()
_operaciones_activas: dict = {}


def _reservar_operacion(recurso: str, accion: str) -> None:
    # R15.5 (P0): un recurso con inconsistencia sin resolver no admite
    # operaciones nuevas hasta la resolución manual documentada.
    _assert_recurso_consistente(recurso, accion)
    with _operaciones_lock:
        activa = _operaciones_activas.get(recurso)
        if activa is not None:
            raise HTTPException(423, (
                f"Otra operación sobre este video está en curso "
                f"({activa['accion']}, iniciada {activa['inicio']}). "
                "Espera a que termine e inténtalo de nuevo."))
        _operaciones_activas[recurso] = {
            "accion": accion,
            "inicio": datetime.now().isoformat(timespec="seconds")}


def _liberar_operacion(recurso: str) -> None:
    with _operaciones_lock:
        _operaciones_activas.pop(recurso, None)


# R15.4 (MEDIUM-03): estados del pipeline en los que los parciales del
# checkpoint forman parte legítimamente de la vista ACTUAL (corrida viva,
# pausa, detención recuperable o reanudación explícita). Fuera de estos
# estados el checkpoint es HISTÓRICO: no puede presentarse como resultado
# actual si falta el documento oficial.
_ESTADOS_CHECKPOINT_VIGENTE = frozenset({
    "procesando", "pausando", "pausado", "cancelando", "reanudando",
    "detenido_con_avance"})


def _es_fallo_escritura_documento(exc: BaseException) -> bool:
    """True si la excepción es (o envuelve) un fallo de escritura verificada."""
    if isinstance(exc, _pdoc.EscrituraFallida):
        return True
    return isinstance(getattr(exc, "__cause__", None), _pdoc.EscrituraFallida)


def _restaurar_marca_sin_datos(gestor, ruta, previa) -> bool:
    """R15.4 (HIGH-01): devuelve la marca sin-datos a su estado previo."""
    try:
        imagen_hash = hash_archivo(ruta)
        with gestor._conectar() as con:
            if previa is None:
                con.execute("DELETE FROM imagenes_sin_datos WHERE imagen_hash=?",
                            (imagen_hash,))
            else:
                columnas = ",".join(previa.keys())
                marcas = ",".join("?" * len(previa))
                con.execute(
                    f"INSERT OR REPLACE INTO imagenes_sin_datos ({columnas}) "
                    f"VALUES ({marcas})", tuple(previa.values()))
        return True
    except Exception:  # noqa: BLE001 — la compensación no enmascara el error
        return False


def _capturar_revision_estado(gestor, tipo: str, item_id: str) -> dict:
    """R15.5 (HIGH-03): estado previo de la revisión humana (compensable)."""
    return gestor.estado_revision(tipo, item_id, "por_revisar")


def _restaurar_revision_estado(gestor, tipo: str, item_id: str,
                               previo: dict) -> bool:
    """Devuelve la revisión a su estado previo; fila ausente ⇒ DELETE."""
    try:
        if not previo or previo.get("actualizado_en") is None:
            with gestor._conectar() as con:
                con.execute("DELETE FROM revisiones WHERE tipo=? AND item_id=?",
                            (tipo, item_id))
            return True
        gestor.actualizar_revision(
            tipo, item_id, estado=previo.get("estado") or "por_revisar",
            oculto=bool(previo.get("oculto")))
        return True
    except Exception:  # noqa: BLE001 — la compensación no enmascara el error
        return False


def _transaccion_efecto_humano(operacion: str, gestor, tipo: str, prueba_id: str,
                               aplicar_efectos, recurso: "str | None" = None,
                               ruta_imagen=None, commit_fn=None):
    """R15.6 (Causa A): helper único «efecto humano + estado de revisión».

    Secuencia transaccional sobre ``TransaccionMultiAlmacen``:

    1. snapshot — evidencias de la imagen + estado de revisión si hay
       ``ruta_imagen`` (7+3 tablas SQLite y fila de ``revisiones``); si no,
       sólo el estado de revisión;
    2. ``aplicar_efectos()`` — efectos durables (SQLite) + revisión humana;
    3. ``commit_fn(resultado)`` opcional — documento oficial o JSON externo
       SIEMPRE al final.

    Cualquier fallo ⇒ restauración VERIFICADA (cero efectos persistentes);
    doble fallo ⇒ inconsistencia durable + bloqueo del recurso. ``ValueError``
    de los almacenes se traduce a 400 (contrato heredado) tras compensar.
    """
    if recurso is not None:
        _assert_recurso_consistente(recurso, operacion)
    tx = TransaccionMultiAlmacen(operacion, recurso=recurso)
    if ruta_imagen is not None:
        tipo_revision = "externa" if tipo == "externa" else "carpeta"
        nombre = "evidencias y estado de revisión"
        capturar = lambda: gestor.snapshot_evidencias_imagen(  # noqa: E731
            ruta_imagen, prueba_id, tipo_revision=tipo_revision)
        restaurar = gestor.restaurar_evidencias_imagen
    else:
        nombre = "estado de revisión"
        capturar = lambda: _capturar_revision_estado(  # noqa: E731
            gestor, tipo, prueba_id)
        restaurar = lambda estado: _restaurar_revision_estado(  # noqa: E731
            gestor, tipo, prueba_id, estado)
    try:
        _, resultado = tx.aplicar(nombre, capturar, aplicar_efectos, restaurar)
        if commit_fn is not None:
            commit_fn(resultado)
    except BaseException as exc:
        try:
            tx.fallar(exc)
        except HTTPException:
            raise
        except ValueError as vexc:
            raise HTTPException(400, str(vexc)) from vexc
        except Exception:  # noqa: BLE001 — fallo de almacén, compensado
            raise HTTPException(503, (
                f"No se pudo completar '{operacion}' "
                f"({type(exc).__name__}: {exc}). Los efectos externos fueron "
                "restaurados; la solicitud no produjo efectos "
                "persistentes.")) from exc
    tx.exito()
    return resultado


def _aprendizaje_opcional(resultado: dict, fn, motivo: str) -> None:
    """R15.6 (política HIGH-01 de R15.5): el entrenamiento automático es un
    efecto OPCIONAL posterior al commit; si falla, éxito + advertencia."""
    try:
        resultado["aprendizaje_visual_automatico"] = fn(motivo)
    except Exception as exc:  # noqa: BLE001 — nunca revierte la confirmación
        resultado["aprendizaje_visual_automatico"] = {
            "programado": False,
            "error": f"{type(exc).__name__}: {exc}"}


def _restaurar_revisiones_video(snapshot: dict) -> bool:
    """R15.4 (HIGH-01): restaura el registro durable de revisiones de video."""
    try:
        from video_airbag import restaurar_revisiones
        restaurar_revisiones(snapshot)
        return True
    except Exception:  # noqa: BLE001 — la compensación no enmascara el error
        return False


def _restaurar_zona_aprendida(ruta_local, estado) -> bool:
    """R15.5 (P0): restaura el perfil de zona aprendido con verificación.

    ``estado=None`` ⇒ la zona no existía antes: se elimina la creada.
    """
    try:
        from aprendizaje_video_airbag import (eliminar_zona_aprendida,
                                              restaurar_perfil_zona)
        if estado is not None:
            restaurar_perfil_zona(ruta_local, estado)
        else:
            eliminar_zona_aprendida(ruta_local)
        return True
    except Exception:  # noqa: BLE001 — la compensación no enmascara el error
        return False


# ---------------------------------------------------------------------------
# R15.5 (P0): coordinador único de mutaciones multi-almacén + registro de
# estados inconsistentes. Política transaccional común (plan del auditor):
#   snapshot → efectos externos → commit del documento → ante CUALQUIER
#   fallo, restaurar TODOS los efectos en orden inverso y VERIFICAR la
#   restauración. Si la restauración también falla (doble fallo: disco lleno,
#   antivirus, permisos), se registra una inconsistencia EXPLÍCITA y durable:
#   las operaciones incompatibles sobre el recurso quedan bloqueadas hasta
#   resolución manual, y el mensaje nunca afirma «revertido/restaurado»
#   cuando no lo fue (MEDIUM-05).
# ---------------------------------------------------------------------------
RUTA_INCONSISTENCIAS = RAIZ_PROYECTO / ".cache_ocr" / "estado_inconsistente.json"
# R15.6 (ALTO-03): recuperación fail-closed. Centinela durable del «modo
# recuperación» (se activa si el registro no pudo escribirse o es ilegible) y
# auditoría de las resoluciones explícitas (MEDIO-05: quién y cuándo).
RUTA_RECUPERACION = RAIZ_PROYECTO / ".cache_ocr" / "recuperacion_requerida.json"
# R15.7 (ALTO-03): SEGUNDA ubicación independiente del centinela (directorio de
# estado del usuario). Si todo el árbol del proyecto no es escribible, el
# arranque debe seguir detectando la recuperación pendiente tras reiniciar.
RUTA_RECUPERACION_ESPEJO = Path.home() / ".v_matrix_ocr" / "recuperacion_requerida.json"
RUTA_AUDITORIA_RESOLUCIONES = RAIZ_PROYECTO / ".cache_ocr" / "inconsistencias_resueltas.json"
_inconsistencias_lock = threading.Lock()
_inconsistencias_activas: dict = {}
_modo_recuperacion: "dict | None" = None
_sonda_lock = threading.Lock()


# ---------------------------------------------------------------------------
# R15.7 (ALTO-02): identidad CANÓNICA de recursos.
#
# Auditoría R15.6, ALTO-02: el mismo caso se identificaba como `carpeta:<id>`,
# ruta absoluta de imagen o ruta absoluta de video, de modo que un bloqueo
# registrado por una pantalla no bloqueaba las demás. Identidad única:
#
#   carpeta:<case_id>                    mutaciones de carpeta (caso completo)
#   carpeta:<case_id>#imagen:<imagen_id> subrecurso de imagen
#   carpeta:<case_id>#video:<video_id>   subrecurso de video
#   externa:<case_id>                    pruebas externas/complejas
#
# Regla de bloqueo: dos recursos están relacionados si comparten raíz canónica
# (todo lo anterior a "#"), de forma que un bloqueo del CASO detiene también
# sus imágenes/videos y un bloqueo de una imagen detiene también las
# operaciones de la carpeta del mismo caso (misma relación padre↔hijo).
# ---------------------------------------------------------------------------

def _recurso_carpeta(prueba_id: str) -> str:
    return f"carpeta:{prueba_id}"


def _recurso_externa(prueba_id: str) -> str:
    return f"externa:{prueba_id}"


def _recurso_imagen(prueba_id: str, imagen_id: "str | None" = None) -> str:
    return f"carpeta:{prueba_id}#imagen:{imagen_id or '?'}"


def _recurso_video(prueba_id: str, video_id: "str | None" = None) -> str:
    return f"carpeta:{prueba_id}#video:{video_id or '?'}"


def _raiz_recurso(recurso: str) -> str:
    """Parte canónica sin subrecurso (``carpeta:<id>`` / ``externa:<id>``)."""
    return str(recurso or "").split("#", 1)[0]


def _padre_recurso(recurso: str) -> "str | None":
    """Recurso padre explícito de un subrecurso (``carpeta:<id>``)."""
    raiz = _raiz_recurso(recurso)
    return raiz if raiz and raiz != str(recurso or "") else None


def _clave_ruta(ruta) -> str:
    texto = str(ruta or "").strip()
    if not texto:
        return ""
    try:
        return str(Path(texto).resolve())
    except (OSError, RuntimeError, ValueError):
        return texto


def _raiz_documento() -> "Path | None":
    """Raíz del lote declarada por el documento actual (``datos['raiz']``).
    R15.8 (ALTO-02): las rutas RELATIVAS heredadas del documento o del
    registro R15.6 se resuelven contra esta raíz, no contra el working
    directory del servidor."""
    cargar_datos = globals().get("_cargar_datos")
    try:
        datos = cargar_datos() if callable(cargar_datos) else None
    except Exception:  # noqa: BLE001 — la raíz es best-effort
        return None
    texto = str((datos or {}).get("raiz") or "").strip()
    if not texto:
        return None
    try:
        return Path(texto).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _variantes_clave_ruta(texto) -> list:
    """Todas las claves bajo las que una ruta almacenada puede haberse
    registrado (R15.8, ALTO-02): resuelta contra el working directory
    (comportamiento heredado), resuelta contra ``datos['raiz']`` si la ruta es
    relativa, y su forma literal normalizada. La variante relativa→raíz exige
    CONFINAMIENTO: si la ruta se escapa de la raíz del lote no se mapea al
    recurso del caso."""
    texto = str(texto or "").strip()
    if not texto:
        return []
    variantes: list = []
    candidata = _clave_ruta(texto)
    if candidata:
        variantes.append(candidata)
    try:
        ruta = Path(texto)
    except (OSError, RuntimeError, ValueError):
        ruta = None
    if ruta is not None and not ruta.is_absolute():
        raiz = _raiz_documento()
        if raiz is not None:
            try:
                conjunta = (raiz / ruta).resolve()
            except (OSError, RuntimeError, ValueError):
                conjunta = None
            if conjunta is not None:
                try:
                    confinada = conjunta.is_relative_to(raiz)
                except (OSError, RuntimeError, ValueError):
                    confinada = False
                if confinada and str(conjunta) not in variantes:
                    variantes.append(str(conjunta))
    if texto not in variantes:
        variantes.append(texto)
    return variantes


_indice_rutas_cache: dict = {"firma": None, "indice": {}}


def _indice_rutas_documento() -> dict:
    """Mapa ruta local → identidad canónica, derivado del documento actual y
    del documento externo. Sólo se usa para MIGRAR entradas heredadas (R15.6
    guardaba rutas) y para consultas puntuales; las rutas de mutación ya
    construyen su identidad canónica explícitamente."""
    cargar_datos = globals().get("_cargar_datos")
    try:
        datos = cargar_datos() if callable(cargar_datos) else None
    except Exception:  # noqa: BLE001 — el índice es best-effort
        datos = None
    filas = (datos or {}).get("resultados") or []
    firma = (str(globals().get("RUTA_VALIDACION")),
             (datos or {}).get("revision_documento"), len(filas))
    if filas and _indice_rutas_cache["firma"] == firma:
        return _indice_rutas_cache["indice"]
    id_fila = globals().get("_id_fila")
    indice: dict = {}
    for fila in filas:
        fila_id = str(id_fila(fila)) if callable(id_fila) else ""
        if not fila_id:
            continue
        for imagen in fila.get("imagenes") or []:
            for clave in _variantes_clave_ruta(imagen.get("ruta")):
                indice.setdefault(clave, _recurso_imagen(fila_id, imagen.get("id")))
        for video in fila.get("videos") or []:
            for clave in _variantes_clave_ruta(video.get("ruta")):
                indice.setdefault(clave, _recurso_video(fila_id, video.get("id")))
        for campo in ("etiqueta", "referencia"):
            copia = fila.get(campo)
            if isinstance(copia, dict) and copia.get("ruta"):
                for clave in _variantes_clave_ruta(copia.get("ruta")):
                    indice.setdefault(clave, _recurso_carpeta(fila_id))
    if filas:
        _indice_rutas_cache["firma"] = firma
        _indice_rutas_cache["indice"] = indice
    return dict(_indice_rutas_externas(), **indice)


def _indice_rutas_externas() -> dict:
    try:
        from pruebas_externas import cargar as _cargar_externas
        documento = _cargar_externas(CONFIG)
    except Exception:  # noqa: BLE001 — banco externo opcional
        return {}
    indice: dict = {}
    for fila in documento.get("resultados") or []:
        clave = _clave_ruta(fila.get("ruta"))
        if clave and fila.get("id"):
            indice.setdefault(clave, _recurso_externa(str(fila["id"])))
    return indice


def _recurso_canonico(recurso: str) -> str:
    """Normaliza una identidad (canónica, heredada por ruta o desconocida).

    R15.8 (ALTO-02): la búsqueda prueba TODAS las variantes de la ruta
    (absoluta, relativa contra ``datos['raiz']`` y literal), de modo que una
    clave heredada de R15.6 bloquea al recurso canónico del caso tenga el
    documento la imagen almacenada con ruta absoluta o relativa."""
    texto = str(recurso or "").strip()
    if not texto or texto.startswith("carpeta:") or texto.startswith("externa:"):
        return texto
    indice = _indice_rutas_documento()
    for clave in _variantes_clave_ruta(texto):
        canonico = indice.get(clave)
        if canonico:
            return canonico
    return texto


def _entradas_bloqueantes(recurso: str) -> list:
    """Entradas del registro relacionadas con el recurso consultado."""
    canonico = _recurso_canonico(recurso)
    raiz = _raiz_recurso(canonico)
    salida: list = []
    vistas: set = set()
    for clave, entrada in _inconsistencias_activas.items():
        if id(entrada) in vistas:
            continue
        raiz_entrada = _raiz_recurso(str(entrada.get("recurso") or clave))
        if canonico == clave or _raiz_recurso(clave) == raiz or raiz_entrada == raiz:
            vistas.add(id(entrada))
            salida.append(entrada)
    return salida


def _recursos_relacionados(recurso: str) -> set:
    """Familia canónica del recurso: sí mismo, su padre y sus subrecursos
    registrados (contrato público del bloqueo por caso, ALTO-02)."""
    canonico = _recurso_canonico(recurso)
    raiz = _raiz_recurso(canonico)
    familia = {canonico, raiz}
    for clave in list(_inconsistencias_activas) + [canonico]:
        if _raiz_recurso(str(clave)) == raiz:
            familia.add(str(clave))
    for subrecurso in _indice_rutas_documento().values():
        if _raiz_recurso(subrecurso) == raiz:
            familia.add(subrecurso)
    return {elemento for elemento in familia if elemento}


def _escribir_json_verificado(ruta: Path, payload: dict) -> None:
    """R15.6 (ALTO-03): temporal + fsync + replace + relectura de verificación.

    Lanza OSError/ValueError si el resultado no es durable y legible; nunca
    reporta éxito sin verificar.
    """
    import os
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    with open(temporal, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    temporal.replace(ruta)
    with open(ruta, encoding="utf-8") as fh:
        if json.load(fh) != payload:
            raise ValueError(f"verificación de escritura fallida en '{ruta.name}'")


def _activar_modo_recuperacion(motivo: str) -> None:
    """Fail-closed: sin registro durable fiable se bloquean las mutaciones
    gobernadas.

    R15.7 (ALTO-03): el centinela se escribe en DOS ubicaciones independientes
    (árbol del proyecto y directorio de estado del usuario). Si ninguna puede
    escribirse, el arranque queda protegido por la sonda de escritura/lectura
    obligatoria (``inicializar_recuperacion``), que activa este mismo modo al
    no poder garantizar el registro durable. Llamar con
    ``_inconsistencias_lock`` tomado."""
    global _modo_recuperacion
    _modo_recuperacion = {"motivo": motivo,
                          "fecha": datetime.now().isoformat(timespec="seconds")}
    for ruta in (RUTA_RECUPERACION, RUTA_RECUPERACION_ESPEJO):
        try:
            _escribir_json_verificado(ruta, dict(_modo_recuperacion))
        except (OSError, ValueError):
            continue


def _ruta_respaldo_sonda() -> Path:
    """R15.9 (ALTO-03, auditoría R15.8): copia durable del registro que la
    sonda guarda ANTES de sustituir el target (mismo directorio, sufijo fijo).
    Si el proceso muere entre la sustitución y la restauración, este respaldo
    permite recuperar las entradas al reiniciar (``_leer_registro_o_respaldo``)."""
    return RUTA_INCONSISTENCIAS.with_name(RUTA_INCONSISTENCIAS.name
                                          + ".respaldo_sonda")


def _escribir_bytes_verificados(ruta: Path, crudos: bytes) -> None:
    """R15.9 (MEDIO-04, auditoría R15.8): temporal + fsync + replace +
    relectura a nivel de BYTES. Conserva el contenido EXACTO del registro
    (CRLF, BOM, UTF-8) sin normalización de saltos de línea. Lanza
    OSError/ValueError si el resultado no es durable e idéntico byte a byte."""
    import os
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    try:
        with open(temporal, "wb") as fh:
            fh.write(crudos)
            fh.flush()
            os.fsync(fh.fileno())
        temporal.replace(ruta)
    except BaseException:
        try:
            temporal.unlink()
        except OSError:
            pass
        raise
    if ruta.read_bytes() != crudos:
        raise ValueError(f"verificación de escritura fallida en '{ruta.name}'")


def _sonda_recuperacion() -> dict:
    """R15.7 (ALTO-03): write/read probe OBLIGATORIA del almacén de
    recuperación. R15.8 (ALTO-01): la sonda actúa sobre el TARGET EXACTO
    (``estado_inconsistente.json``), no sobre un archivo hermano. R15.9
    (MEDIO-04): el contenido se preserva BYTE A BYTE (lectura/escritura en
    binario: CRLF/BOM intactos). R15.9 (ALTO-03): antes de sustituir el
    registro por la sonda se escribe un RESPALDO DURABLE del contenido
    (fsync + replace + relectura); si el proceso muere entre la sustitución y
    la restauración, el respaldo queda en disco y el siguiente arranque
    recupera las entradas — la sonda nunca deja el único registro de
    anomalías reemplazado sin backup. Cualquier fallo de lectura, respaldo,
    escritura, reemplazo, relectura o restauración ⇒ fail-closed. La sonda NO
    escribe un registro válido a propósito: si el proceso muere a mitad de la
    prueba, el remanente no puede leerse como un registro «todo en orden»
    (pero SÍ es recuperable desde el respaldo)."""
    if not _sonda_lock.acquire(blocking=False):
        return {"escribible": True, "releido": True, "error": None,
                "ruta": str(RUTA_INCONSISTENCIAS), "en_curso": True}
    try:
        original: "bytes | None" = None
        if RUTA_INCONSISTENCIAS.exists():
            if not RUTA_INCONSISTENCIAS.is_file():
                return {"escribible": False, "releido": False,
                        "error": "el almacén de recuperación no es un archivo "
                                 "regular",
                        "ruta": str(RUTA_INCONSISTENCIAS)}
            try:
                original = RUTA_INCONSISTENCIAS.read_bytes()
                json.loads(original)
            except (OSError, ValueError) as exc:
                return {"escribible": False, "releido": False,
                        "error": f"el registro existente no es legible "
                                 f"({type(exc).__name__}: {exc})",
                        "ruta": str(RUTA_INCONSISTENCIAS)}
            # R15.9 (ALTO-03): respaldo durable ANTES de tocar el target.
            _escribir_bytes_verificados(_ruta_respaldo_sonda(), original)
        payload = {"sonda": True,
                   "fecha": datetime.now().isoformat(timespec="seconds")}
        _escribir_json_verificado(RUTA_INCONSISTENCIAS, payload)
        try:
            if original is None:
                RUTA_INCONSISTENCIAS.unlink()
            else:
                _escribir_bytes_verificados(RUTA_INCONSISTENCIAS, original)
        except (OSError, ValueError) as exc:
            return {"escribible": False, "releido": False,
                    "error": f"no se pudo dejar el almacén intacto tras la "
                             f"sonda ({type(exc).__name__}: {exc}); el "
                             "respaldo durable queda disponible para el "
                             "próximo arranque",
                    "ruta": str(RUTA_INCONSISTENCIAS)}
        try:
            _ruta_respaldo_sonda().unlink()
        except OSError:
            pass
        return {"escribible": True, "releido": True, "error": None,
                "ruta": str(RUTA_INCONSISTENCIAS)}
    except (OSError, ValueError) as exc:
        return {"escribible": False, "releido": False,
                "error": f"{type(exc).__name__}: {exc}",
                "ruta": str(RUTA_INCONSISTENCIAS)}
    finally:
        _sonda_lock.release()


def inicializar_recuperacion() -> dict:
    """Arranque del guard de recuperación (R15.7, ALTO-03).

    Carga el registro durable y EJECUTA la sonda de escritura/lectura. Si el
    almacén de recuperación no es durable, arranca en MODO RECUPERACIÓN
    (fail-closed) incluso aunque no exista centinela.
    """
    _cargar_inconsistencias()
    sonda = _sonda_recuperacion()
    if not sonda.get("escribible"):
        _activar_modo_recuperacion(
            f"almacén de recuperación no escribible ({sonda.get('error')})")
    return sonda


def _eliminar_centinela() -> "str | None":
    """R15.7 (BAJO-07): elimina el centinela en sus dos ubicaciones y VERIFICA
    que ya no existe. Devuelve la advertencia si no pudo garantizarse (la
    sesión actual queda desbloqueada, pero el próximo arranque volvería a
    recuperarse: el usuario debe saberlo)."""
    fallos = []
    for ruta in (RUTA_RECUPERACION, RUTA_RECUPERACION_ESPEJO):
        try:
            ruta.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            fallos.append(f"{ruta}: {type(exc).__name__}")
        if ruta.exists():
            fallos.append(f"{ruta} sigue presente")
    if not fallos:
        return None
    return ("No se pudo garantizar la eliminación del centinela de "
            "recuperación (" + "; ".join(fallos) + "). El sistema está "
            "desbloqueado en esta sesión, pero el próximo arranque podría "
            "volver a activar el modo recuperación.")


def _mensaje_modo_recuperacion(accion: str, modo: dict) -> str:
    return (
        f"No es posible {accion}: el sistema está en MODO RECUPERACIÓN "
        f"({modo.get('motivo')}). El registro durable de inconsistencias no "
        "es fiable. Revisa GET /api/recuperacion/inconsistencias y resuelve "
        "cada entrada con POST /api/recuperacion/inconsistencias/{recurso}/"
        "resolver (o POST /api/recuperacion/modo-recuperacion/resolver si no "
        "quedan entradas activas).")


def _validar_esquema_registro_inconsistencias(datos: object) -> dict:
    """Valida todo el esquema antes de migrar o mutar el estado en memoria.

    JSON sintácticamente válido con entradas mal tipadas es corrupción lógica:
    activa recuperación en vez de lanzar AttributeError/TypeError o persistir
    una migración parcial. Se preservan campos adicionales.
    """
    if not isinstance(datos, dict):
        raise ValueError("la raíz JSON no es un objeto")
    entradas = datos.get("inconsistencias")
    if not isinstance(entradas, list):
        raise ValueError("'inconsistencias' no es una lista")
    for indice, entrada in enumerate(entradas):
        if not isinstance(entrada, dict):
            raise ValueError(f"inconsistencias[{indice}] no es un objeto")
        recurso = entrada.get("recurso")
        if not isinstance(recurso, str) or not recurso.strip():
            raise ValueError(f"inconsistencias[{indice}].recurso debe ser texto no vacío")
        if "aliases" in entrada:
            aliases = entrada["aliases"]
            if (not isinstance(aliases, list)
                    or any(not isinstance(alias, str) for alias in aliases)):
                raise ValueError(
                    f"inconsistencias[{indice}].aliases debe ser una lista de textos")
    return datos


def _leer_registro_o_respaldo() -> "dict | None":
    """R15.9 (ALTO-03, auditoría R15.8): protocolo de recuperación del
    registro tras una interrupción de la sonda.

    1. Registro sano ⇒ se devuelve y se retira cualquier respaldo residual.
    2. Registro ausente o dañado ⇒ se restaura BYTE A BYTE desde el respaldo
       durable de la sonda (si existe y es válido) y se devuelven sus datos.
    3. Nada utilizable ⇒ ``None`` (el llamador activa modo recuperación sólo
       si el target EXISTÍA y era ilegible; ausente sin respaldo = instalación
       fresca).

    Ejecutar en el arranque (mismo hilo que la sonda); sin concurrencia con
    otra sonda en vuelo.
    """
    try:
        if RUTA_INCONSISTENCIAS.is_file():
            # R15.9.1 revisión (auditoría del paquete entregado): lectura en
            # BYTES con el MISMO criterio que usa la sonda — json.loads
            # sobre bytes detecta utf-8-sig, de modo que un registro válido
            # con BOM (p. ej. re-guardado con un editor de Windows) ya no se
            # reporta «ilegible» en falso. Un fichero truncado/corrupto
            # sigue fallando (fail-closed R15.6).
            datos = _validar_esquema_registro_inconsistencias(
                json.loads(RUTA_INCONSISTENCIAS.read_bytes()))
            try:
                _ruta_respaldo_sonda().unlink()
            except OSError:
                pass
            return datos
    except (OSError, ValueError):
        pass
    respaldo = _ruta_respaldo_sonda()
    try:
        if respaldo.is_file():
            crudos = respaldo.read_bytes()
            datos = _validar_esquema_registro_inconsistencias(json.loads(crudos))
            _escribir_bytes_verificados(RUTA_INCONSISTENCIAS, crudos)
            try:
                respaldo.unlink()
            except OSError:
                pass
            return datos
    except (OSError, ValueError):
        return None
    return None


def _cargar_inconsistencias() -> None:
    """(Re)carga el registro durable; los bloqueos sobreviven reinicios.

    R15.6 (ALTO-03): un registro ilegible/corrupto o un centinela de sesión
    anterior arrancan en MODO RECUPERACIÓN — nunca se ignoran (fail-open).
    R15.9 (ALTO-03): un registro dañado por una sonda interrumpida se
    RECUPERA primero desde su respaldo durable; sólo sin respaldo utilizable
    se entra en modo recuperación.
    """
    global _modo_recuperacion
    with _inconsistencias_lock:
        _inconsistencias_activas.clear()
        _modo_recuperacion = None
        centinela_ruta = next((ruta for ruta in (
            RUTA_RECUPERACION, RUTA_RECUPERACION_ESPEJO)
            if ruta.is_file()), None)
        if centinela_ruta is not None:
            motivo, fecha = "centinela de recuperación de una sesión anterior", ""
            try:
                centinela = json.loads(
                    centinela_ruta.read_text(encoding="utf-8"))
                if isinstance(centinela, dict):
                    motivo = str(centinela.get("motivo") or motivo)
                    fecha = str(centinela.get("fecha") or "")
            except (OSError, ValueError):
                motivo = "centinela de recuperación ilegible"
            _modo_recuperacion = {"motivo": motivo, "fecha": fecha}
        # R15.9 (ALTO-03): la lectura pasa por el protocolo de recuperación —
        # registro sano ⇒ datos (+ limpieza de respaldo residual); registro
        # dañado ⇒ restauración desde el respaldo durable de la sonda.
        datos = _leer_registro_o_respaldo()
        if datos is not None:
            try:
                datos = _validar_esquema_registro_inconsistencias(datos)
            except ValueError as exc:
                _activar_modo_recuperacion(
                    f"registro de inconsistencias ilegible (estructura no reconocida: {exc})")
                return
            entradas_duras = datos["inconsistencias"]
        elif (RUTA_INCONSISTENCIAS.is_file()
              or _ruta_respaldo_sonda().is_file()):
            # Target o respaldo ilegible/inválido sin copia utilizable:
            # fail-closed (también si el target falta y sólo queda un respaldo
            # inválido; nunca se confunde esa situación con instalación fresca).
            # El motivo conserva el detalle para diagnóstico de campo.
            ruta_danada = (RUTA_INCONSISTENCIAS
                           if RUTA_INCONSISTENCIAS.is_file()
                           else _ruta_respaldo_sonda())
            etiqueta = ("registro de inconsistencias ilegible"
                        if ruta_danada == RUTA_INCONSISTENCIAS
                        else "respaldo del registro de inconsistencias ilegible")
            detalle = ""
            try:
                vistos = json.loads(ruta_danada.read_bytes())
            except (OSError, ValueError) as exc:
                detalle = f" ({type(exc).__name__}: {exc})"
            else:
                try:
                    _validar_esquema_registro_inconsistencias(vistos)
                except ValueError as exc:
                    detalle = f" (estructura no reconocida: {exc})"
            _activar_modo_recuperacion(f"{etiqueta}{detalle}")
            return
        else:
            entradas_duras = []  # instalación fresca: registro vacío
        try:
            migrado = False
            for entrada in entradas_duras:
                recurso = str(entrada.get("recurso") or "")
                if not recurso:
                    continue
                # R15.7 (ALTO-02): migración de claves heredadas — el
                # upgrade puede encontrar rutas absolutas escritas por
                # R15.6; se conservan como ALIAS para que el bloqueo siga
                # vigente en todas las pantallas del mismo caso.
                # R15.8 (ALTO-02): la resolución a canónico entiende rutas
                # RELATIVAS (contra ``datos['raiz']``) y la migración se
                # PERSISTE para que el registro durable quede canónico.
                previa = dict(entrada)
                entrada = dict(entrada)
                canonico = _recurso_canonico(recurso)
                aliases = {str(a) for a in (entrada.get("aliases") or [])}
                aliases.discard(canonico)
                aliases.discard(recurso)
                if recurso != canonico:
                    aliases.add(recurso)
                entrada["recurso"] = canonico
                if aliases:
                    entrada["aliases"] = sorted(aliases)
                else:
                    entrada.pop("aliases", None)
                if entrada != previa:
                    migrado = True
                _inconsistencias_activas[canonico] = entrada
                for alias in aliases:
                    _inconsistencias_activas[alias] = entrada
            if migrado:
                _persistir_inconsistencias()
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            _activar_modo_recuperacion(
                f"registro de inconsistencias ilegible ({type(exc).__name__}: {exc})")


def _persistir_inconsistencias() -> None:
    """R15.6 (ALTO-03): persistencia VERIFICADA del registro. Si no puede
    escribirse, activa el modo recuperación (fail-closed) en lugar de ignorar
    el error en silencio. Llamar con ``_inconsistencias_lock`` tomado."""
    unicas: list = []
    vistas: set = set()
    for entrada in _inconsistencias_activas.values():
        if id(entrada) in vistas:
            continue
        vistas.add(id(entrada))
        unicas.append(entrada)
    payload = {"inconsistencias": unicas}
    try:
        _escribir_json_verificado(RUTA_INCONSISTENCIAS, payload)
    except (OSError, ValueError) as exc:
        _activar_modo_recuperacion(f"registro durable no escribible ({exc})")


def _registrar_inconsistencia(recurso: str, operacion: str,
                              detalle: str) -> None:
    """R15.7 (ALTO-02): registra el bloqueo en identidad CANÓNICA y conserva
    la clave recibida como alias (así ninguna pantalla puede saltarse el
    bloqueo por usar un identificador distinto del mismo caso)."""
    canonico = _recurso_canonico(recurso)
    entrada = {"recurso": canonico, "operacion": operacion,
               "detalle": detalle,
               "fecha": datetime.now().isoformat(timespec="seconds")}
    aliases = {str(recurso)} - {canonico}
    if aliases:
        entrada["aliases"] = sorted(aliases)
    with _inconsistencias_lock:
        _inconsistencias_activas[canonico] = entrada
        for alias in aliases:
            _inconsistencias_activas[alias] = entrada
        _persistir_inconsistencias()


def _resolver_inconsistencias(recurso: str) -> None:
    """Retira el bloqueo del recurso indicado (identidad canónica O alias).

    R15.7 (ALTO-01): esta función YA NO se invoca desde el éxito de una
    transacción; sólo sirve a la resolución explícita (y a herramientas/tests
    que la usan como atajo del flujo formal). Acepta la clave heredada por
    ruta y la normaliza a la identidad canónica del caso.
    """
    with _inconsistencias_lock:
        canonico = _recurso_canonico(recurso)
        entrada = (_inconsistencias_activas.get(canonico)
                   or _inconsistencias_activas.get(str(recurso)))
        if entrada is None:
            return
        for clave in [k for k, v in _inconsistencias_activas.items()
                      if v is entrada]:
            _inconsistencias_activas.pop(clave, None)
        _persistir_inconsistencias()


def _assert_recurso_consistente(recurso: str, accion: str) -> None:
    with _inconsistencias_lock:
        modo = _modo_recuperacion
        entradas = _entradas_bloqueantes(str(recurso))
    entrada = entradas[0] if entradas else None
    if modo is not None:
        raise HTTPException(503, _mensaje_modo_recuperacion(accion, modo))
    if entrada is not None:
        # R15.6 (MEDIO-05): el mensaje remite al flujo explícito de
        # recuperación; ya NO pide borrar archivos a mano.
        raise HTTPException(503, (
            f"No es posible {accion}: hay un estado potencialmente "
            f"inconsistente sin resolver en este recurso (operación "
            f"'{entrada.get('operacion')}', {entrada.get('fecha')}). "
            "Acción recomendada: verifica el documento de resultados y los "
            "almacenes de aprendizaje/revisiones y, una vez comprobados, "
            "resuelve el bloqueo con POST /api/recuperacion/inconsistencias/"
            "{recurso}/resolver (listado en GET /api/recuperacion/"
            "inconsistencias)."))


def _assert_sistema_recuperable(accion: str) -> None:
    """R15.6 (ALTO-03): en modo recuperación no hay mutaciones gobernadas."""
    with _inconsistencias_lock:
        modo = _modo_recuperacion
    if modo is not None:
        raise HTTPException(503, _mensaje_modo_recuperacion(accion, modo))


class SolicitudResolucionInconsistencia(BaseModel):
    """MEDIO-05: confirmación explícita de la verificación manual."""
    usuario: str = Field(min_length=1, max_length=128)
    confirmo_verificacion: bool = False
    nota: str | None = Field(default=None, max_length=2048)


def _leer_auditoria_resoluciones() -> list:
    try:
        datos = json.loads(
            RUTA_AUDITORIA_RESOLUCIONES.read_text(encoding="utf-8"))
        if isinstance(datos, dict) and isinstance(datos.get("resoluciones"), list):
            return datos["resoluciones"]
    except (OSError, ValueError):
        pass
    return []


def _auditar_resolucion(entrada: dict,
                        solicitud: SolicitudResolucionInconsistencia) -> "str | None":
    """Registro durable de quién/cuándo resolvió. Best-effort: si la auditoría
    no puede escribirse, la resolución ya verificada no se revierte; se avisa."""
    registro = {"recurso": str(entrada.get("recurso") or ""),
                "operacion": entrada.get("operacion"),
                "registrada_en": entrada.get("fecha"),
                "usuario": solicitud.usuario,
                "nota": solicitud.nota,
                "resuelta_en": datetime.now().isoformat(timespec="seconds")}
    try:
        actuales = _leer_auditoria_resoluciones()
        _escribir_json_verificado(RUTA_AUDITORIA_RESOLUCIONES,
                                  {"resoluciones": [*actuales, registro]})
        return None
    except (OSError, ValueError) as exc:
        return f"No se pudo registrar la resolución en la auditoría: {exc}"


@app.get("/api/recuperacion/inconsistencias")
def listar_inconsistencias():
    """MEDIO-05: listado público de bloqueos activos y modo recuperación.

    R15.8 (MEDIO-06): el registro indexa cada entrada también por sus aliases
    (R15.7); el listado DEDUPLICA por incidente (identidad de objeto) para no
    inflar ``total`` ni duplicar tarjetas en la UI, y expone ``claves`` con
    todas las identidades bajo las que responde el mismo incidente."""
    with _inconsistencias_lock:
        modo = dict(_modo_recuperacion) if _modo_recuperacion else None
        entradas: list = []
        vistas: set = set()
        for entrada in _inconsistencias_activas.values():
            if id(entrada) in vistas:
                continue
            vistas.add(id(entrada))
            item = dict(entrada)
            item["claves"] = sorted(
                clave for clave, valor in _inconsistencias_activas.items()
                if valor is entrada)
            entradas.append(item)
    return {"modo_recuperacion": modo,
            "registro": str(RUTA_INCONSISTENCIAS),
            "centinela": str(RUTA_RECUPERACION),
            "inconsistencias": entradas,
            "total": len(entradas),
            "resoluciones": _leer_auditoria_resoluciones()}


@app.post("/api/recuperacion/inconsistencias/{recurso:path}/resolver")
def resolver_inconsistencia(recurso: str,
                            solicitud: SolicitudResolucionInconsistencia):
    """MEDIO-05: resolución explícita tras la verificación manual.

    Sólo limpia memoria + registro durable si la escritura verificada tiene
    éxito; si falla, el bloqueo se mantiene (fail-closed). Deja auditoría de
    quién y cuándo, y si no quedan entradas limpia el modo recuperación.
    """
    global _modo_recuperacion
    if not solicitud.confirmo_verificacion:
        raise HTTPException(400, (
            "Confirma la verificación manual del documento y los almacenes "
            "(confirmo_verificacion=true) antes de resolver el bloqueo."))
    advertencia_centinela = None
    with _inconsistencias_lock:
        entrada = _inconsistencias_activas.get(recurso)
        if entrada is None:
            canonico = _recurso_canonico(recurso)
            entrada = _inconsistencias_activas.get(canonico)
        if entrada is None:
            raise HTTPException(
                404, "El recurso indicado no tiene inconsistencias activas.")
        claves_entrada = {k for k, v in _inconsistencias_activas.items()
                          if v is entrada}
        unicas: list = []
        vistas: set = set()
        for clave, valor in _inconsistencias_activas.items():
            if id(valor) in vistas:
                continue
            vistas.add(id(valor))
            if valor is not entrada:
                unicas.append(dict(valor))
        try:
            _escribir_json_verificado(RUTA_INCONSISTENCIAS,
                                      {"inconsistencias": unicas})
        except (OSError, ValueError) as exc:
            raise HTTPException(503, (
                f"No se pudo actualizar el registro durable ({exc}); el "
                "bloqueo se mantiene (fail-closed).")) from exc
        for clave in claves_entrada:
            _inconsistencias_activas.pop(clave, None)
        if _modo_recuperacion is not None and not _inconsistencias_activas:
            _modo_recuperacion = None
            advertencia_centinela = _eliminar_centinela()
        advertencia = _auditar_resolucion(entrada, solicitud)
        modo = dict(_modo_recuperacion) if _modo_recuperacion else None
    return {"resuelta": True, "recurso": entrada.get("recurso") or recurso,
            "restantes": len(unicas), "modo_recuperacion": modo,
            "centinela_eliminado": advertencia_centinela is None,
            "advertencia_centinela": advertencia_centinela,
            "advertencia_auditoria": advertencia}


@app.post("/api/recuperacion/modo-recuperacion/resolver")
def resolver_modo_recuperacion(solicitud: SolicitudResolucionInconsistencia):
    """ALTO-03/MEDIO-05: limpia el modo recuperación global tras verificación.

    Exige que no queden entradas activas (se resuelven una a una primero),
    reconstruye el registro durable con escritura verificada y elimina el
    centinela. Si el registro sigue sin poder escribirse, el modo continúa.
    """
    global _modo_recuperacion
    if not solicitud.confirmo_verificacion:
        raise HTTPException(400, (
            "Confirma la verificación manual del documento y los almacenes "
            "(confirmo_verificacion=true) antes de limpiar el modo "
            "recuperación."))
    with _inconsistencias_lock:
        if _modo_recuperacion is None:
            raise HTTPException(404, "El sistema no está en modo recuperación.")
        if _inconsistencias_activas:
            raise HTTPException(409, (
                "Quedan inconsistencias activas: resuélvelas una a una con "
                "POST /api/recuperacion/inconsistencias/{recurso}/resolver "
                "antes de limpiar el modo recuperación."))
        try:
            _escribir_json_verificado(RUTA_INCONSISTENCIAS,
                                      {"inconsistencias": []})
        except (OSError, ValueError) as exc:
            raise HTTPException(503, (
                f"El registro durable sigue sin poder escribirse ({exc}); el "
                "modo recuperación se mantiene.")) from exc
        _modo_recuperacion = None
        advertencia_centinela = _eliminar_centinela()
        advertencia = _auditar_resolucion(
            {"recurso": "(modo recuperación)",
             "operacion": "modo_recuperacion",
             "fecha": datetime.now().isoformat(timespec="seconds")},
            solicitud)
    return {"resuelta": True, "modo_recuperacion": None,
            "centinela_eliminado": advertencia_centinela is None,
            "advertencia_centinela": advertencia_centinela,
            "advertencia_auditoria": advertencia}


class TransaccionMultiAlmacen:
    """R15.5 (P0): política transaccional común para rutas multi-almacén.

    Uso::

        tx = TransaccionMultiAlmacen("operación", recurso=str(ruta))
        estado = tx.capturar("efecto", capturar, restaurar)  # restaurar(estado)→bool
        try:
            ...aplicar el efecto externo...
            tx.aplicado()          # el efecto QUEDÓ aplicado: se compensará
            ...commit del documento...
        except BaseException as exc:
            tx.fallar(exc)   # compensa, verifica, registra y traduce
        tx.exito()           # R15.7 (ALTO-01): cierre sin efectos colaterales

    Si la APLICACIÓN del efecto falla, no se llama ``aplicado()`` y el efecto
    no se registra: los almacenes usan escritura atómica/verificada, así que
    o no cambiaron o están inaccesibles — y el error original ya lo dice.
    Registrarlo produciría una «inconsistencia» falsa cuando el almacén está
    simplemente caído (el fallo de compensación enmascararía el error real).
    """

    def __init__(self, operacion: str, recurso: "str | None" = None):
        self.operacion = operacion
        self.recurso = str(recurso) if recurso is not None else None
        self._efectos: list = []  # (nombre, restaurar: () -> bool)
        self._pendiente = None
        self.fallos_restauracion: list = []
        self.inconsistente = False

    def capturar(self, nombre: str, capturar, restaurar):
        """Captura el estado previo; se registrará al confirmar ``aplicado()``."""
        estado = capturar()
        self._pendiente = (nombre, lambda: bool(restaurar(estado)))
        return estado

    def aplicado(self) -> None:
        """Confirma que el efecto capturado se aplicó: registra su
        restauración verificada para la compensación."""
        if self._pendiente is not None:
            self._efectos.append(self._pendiente)
            self._pendiente = None

    def aplicar(self, nombre: str, capturar, aplicar_fn, restaurar):
        """Captura → aplica → registra, con la misma política verificada.

        Si la aplicación falla a mitad (estado parcial/incierto), el efecto se
        registra de todos modos y se compensa; si la restauración también
        falla ⇒ inconsistencia explícita. Devuelve ``(estado, resultado)``.
        """
        estado = self.capturar(nombre, capturar, restaurar)
        try:
            resultado = aplicar_fn()
        except BaseException:
            # Aplicación parcial/incierta ⇒ el efecto queda registrado para
            # la compensación; quien captura el error llama ``fallar`` una vez.
            self.aplicado()
            raise
        self.aplicado()
        return estado, resultado

    def compensar(self) -> bool:
        """Restaura los efectos registrados en orden inverso; True si todos
        quedaron verificados."""
        self.fallos_restauracion = []
        for nombre, restaurar in reversed(self._efectos):
            try:
                ok = bool(restaurar())
            except Exception:  # noqa: BLE001 — la compensación no enmascara
                ok = False
            if not ok:
                self.fallos_restauracion.append(nombre)
        self.inconsistente = bool(self.fallos_restauracion)
        if self.inconsistente and self.recurso is not None:
            _registrar_inconsistencia(
                self.recurso, self.operacion,
                "restauración automática fallida de: "
                + ", ".join(self.fallos_restauracion))
        return not self.inconsistente

    def exito(self) -> None:
        """R15.7 (ALTO-01): una transacción EXITOSA no resuelve NADA.

        Auditoría R15.6: `exito()` llamaba a `_resolver_inconsistencias`, de
        modo que una operación B ya en vuelo borraba la inconsistencia
        registrada por otra operación A que falló mientras B seguía corriendo
        (doble fallo real silenciosamente desbloqueado). El único camino para
        levantar un bloqueo es el flujo formal de recuperación
        (`POST /api/recuperacion/.../resolver`) tras la verificación manual.

        Nota: la transacción que falla y no puede restaurar NO se desbloquea a
        sí misma; `compensar()` registra la inconsistencia y su propio fallo.
        """
        return None

    def fallar(self, exc: BaseException):
        """Compensa y traduce el fallo a respuesta HTTP controlada.

        MEDIUM-05: el resultado del rollback NUNCA se ignora — si la
        restauración falló, el mensaje declara estado potencialmente
        inconsistente (jamás afirma «revertido») y el recurso queda bloqueado.
        """
        self.compensar()
        if self.inconsistente:
            raise HTTPException(503, (
                "ATENCIÓN: estado potencialmente inconsistente. La operación "
                f"'{self.operacion}' falló y la restauración automática no "
                "pudo completarse ("
                + ", ".join(self.fallos_restauracion) + "). "
                f"Recurso afectado: {self.recurso or 'n/d'}. "
                "Acción manual recomendada: verifica el documento de "
                "resultados y los almacenes de aprendizaje/revisiones; las "
                "operaciones incompatibles sobre este recurso quedan "
                "bloqueadas hasta que se resuelva.")) from exc
        if _es_fallo_escritura_documento(exc):
            raise HTTPException(503, _MSG_GUARDADO_FALLO + (
                " Los efectos externos fueron restaurados; la solicitud no "
                "produjo efectos persistentes.")) from exc
        raise exc


def mutar_documento(mutacion, expected_revision: "int | None" = None,
                    *, permitir_ausente: bool = False, estricto: bool = False):
    """R15.2: delega en la primitiva compartida y traduce a HTTP.

    Ver ``utilidades.persistencia_documento.mutar_documento`` para el
    contrato completo (fresh-read bajo lock, CAS, monotonía, escritura
    verificada). Las callbacks reciben el documento FRESCO, aplican sólo su
    propio patch y NO deben llamar a ``_cargar_datos()``. Devuelve
    ``(revision_nueva, resultado_de_mutacion)``.

    ``estricto=True`` (R15.2 ALTO-04, mutaciones humanas): documento ya
    versionado exige ``expected_revision`` explícita.
    """
    try:
        return _pdoc.mutar_documento(
            RUTA_VALIDACION, mutacion, expected_revision,
            estricto=estricto, permitir_ausente=permitir_ausente,
            post_commit=_invalidar_cache_documento)
    except _pdoc.ConflictoRevision as exc:
        raise HTTPException(409, str(exc)) from exc
    except _pdoc.DocumentoAusente as exc:
        raise HTTPException(404, "Sin datos procesados.") from exc
    except _pdoc.FormatoInvalido as exc:
        raise HTTPException(503, str(exc)) from exc
    except _pdoc.EscrituraFallida as exc:
        # R15.4 (HIGH-01): fallo de guardado ⇒ 503 controlado con mensaje
        # claro; nunca un 500 crudo ni la impresión de que se guardó.
        raise HTTPException(503, _MSG_GUARDADO_FALLO) from exc


def _leer_documento_disco() -> dict:
    """Lee el documento de resultados directo del disco (sin caché).

    R15.2: delega en la autoridad compartida; se usa dentro de los commits
    bajo lock, donde hace falta la última versión persistida para fusionar
    cambios concurrentes.
    """
    try:
        return _pdoc.leer_fresco(RUTA_VALIDACION)
    except _pdoc.DocumentoAusente as exc:
        raise HTTPException(404, "Sin datos procesados.") from exc
    except _pdoc.FormatoInvalido as exc:
        raise HTTPException(503, str(exc)) from exc


def _commit_documento(datos: dict) -> int:
    """Persiste el documento incrementando ``revision_documento``.

    R15.2: delega en la autoridad compartida. Requiere tener
    ``_lock_documento()`` adquirido. La escritura es verificada: nunca se
    devuelve éxito si el guardado falló.
    """
    return _pdoc.commit_documento(RUTA_VALIDACION, datos,
                                  post_commit=_invalidar_cache_documento)


def _verificar_expected_revision(expected: "int | None", datos: dict,
                                 *, estricto: bool = False) -> None:
    """MEDIA-14: CAS de documento; una pantalla vieja debe recargar (409).

    R15.1 (ALTO-02): con ``estricto=True`` (endpoints mutantes R15), un
    documento YA versionado rechaza ``expected_revision=None``: una pestaña
    vieja no puede bypasear el CAS omitiendo el campo. Los documentos sin
    versionar (legacy, previos a R15) aceptan la primera mutación, que los
    versiona. R15.2: la regla vive en la autoridad compartida (idéntica para
    backend, pipeline y cualquier escritor futuro).
    """
    try:
        _pdoc.verificar_expected_revision(expected, datos, estricto=estricto)
    except _pdoc.ConflictoRevision as exc:
        raise HTTPException(409, str(exc)) from exc


def _guard_mutacion_video(accion: str) -> None:
    """ALTA-07: guard servidor para mutaciones de video.

    Mismo patrón que /api/video/maximo: 409 si hay pipeline activo, slot
    reservado (admisión en curso, R15) o reanálisis de videos en curso.
    R15.6 (ALTO-03): en modo recuperación tampoco hay mutaciones de video.
    """
    _assert_sistema_recuperable(accion)
    with _pipeline_lock, _video_reanalisis_lock:
        if (_pipeline_estado.get("estado") in {"procesando", "pausando", "pausado",
                                               "cancelando", "reanudando"}
                or _slot_pipeline_ocupado_locked()):
            raise HTTPException(409, f"Termina o detén el procesamiento antes de {accion}.")
        if _video_reanalisis_hilo is not None and _video_reanalisis_hilo.is_alive():
            raise HTTPException(409, f"Hay un reanálisis de videos en curso; termínalo antes de {accion}.")


def _assert_pipeline_inactivo(accion: str, *,
                              incluir_reanalisis: bool = False) -> None:
    """R15.6 (Causa B, ALTO-08/09/10): guard uniforme de pipeline.

    Sustituye los checks locales de ``_pipeline_hilo.is_alive()`` que
    ignoraban la reserva atómica del slot de worker (ventana TOCTOU entre la
    admisión y el arranque del hilo) y los estados transitorios. Cubre:
    hilo vivo, reserva tomada, estado de procesamiento (incluido pausado) y,
    con ``incluir_reanalisis=True``, el reanálisis de videos en curso (el
    caso todavía puede estar siendo modificado).
    """
    _assert_sistema_recuperable(accion)
    with _pipeline_lock:
        if (_pipeline_estado.get("estado") in {"procesando", "pausando", "pausado",
                                               "cancelando", "reanudando"}
                or _slot_pipeline_ocupado_locked()):
            raise HTTPException(409, f"Termina o detén el procesamiento antes de {accion}.")
    if incluir_reanalisis:
        with _video_reanalisis_lock:
            if _video_reanalisis_hilo is not None and _video_reanalisis_hilo.is_alive():
                raise HTTPException(409, (
                    "Hay un reanálisis de videos en curso; termínalo antes de "
                    f"{accion}."))


def _assert_documento_editable(accion: str = "editar el documento") -> None:
    """R15.2 (CRÍTICO-02, P0 temporal): UI y pipeline no editan a la vez.

    Mientras el worker del pipeline (o su slot reservado) posee el documento,
    los endpoints mutantes de UI lo rechazan con 409 ANTES de cualquier
    lookup o efecto lateral; las lecturas siguen disponibles y el frontend
    muestra «procesamiento activo». El reanálisis de videos NO bloquea: sus
    commits fusionan por video bajo el mismo lock compartido (R15).
    """
    # R15.6 (ALTO-03): en modo recuperación no se edita el documento.
    _assert_sistema_recuperable(accion)
    with _pipeline_lock:
        if (_pipeline_estado.get("estado") in {"procesando", "pausando", "pausado",
                                               "cancelando", "reanudando"}
                or _slot_pipeline_ocupado_locked()):
            raise HTTPException(409, f"Termina o detén el procesamiento antes de {accion}.")


def _prechequeo_cas_documento(expected_revision: "int | None", *,
                              estricto: bool = True) -> None:
    """R15.2 (ALTO-04): CAS ANTES de cualquier efecto lateral irreversible.

    Endpoints que registran evidencia en la base de aprendizaje (correcciones,
    marcas sin-datos) antes de mutar el documento deben verificar primero
    ``expected_revision`` contra el disco: una pestaña desactualizada recibe
    409 sin haber generado efectos. El CAS definitivo se repite dentro de
    ``mutar_documento`` (autoritativo, bajo lock).
    """
    with _lock_documento():
        try:
            frescos = _pdoc.leer_fresco(RUTA_VALIDACION)
        except _pdoc.DocumentoAusente:
            return  # sin documento aún: mutar_documento decidirá (404/crear)
        except _pdoc.FormatoInvalido as exc:
            raise HTTPException(503, str(exc)) from exc
        try:
            _pdoc.verificar_expected_revision(expected_revision, frescos,
                                              estricto=estricto)
        except _pdoc.ConflictoRevision as exc:
            raise HTTPException(409, str(exc)) from exc


def _verificar_revision_no_completada(prueba_id: str, fila: dict, accion: str) -> None:
    """ALTA-07: el servidor es autoritativo; revisión completada ⇒ 409.

    ``estado_inicial`` es sólo el fallback del gestor cuando no hay registro
    en su BD (y los valores inválidos se coercen a «por_revisar»): si la fila
    está incompleta para ``_fila_publica``, se degrada a ese valor por diseño.
    """
    try:
        inicial = _fila_publica(fila)["revision"]["estado"]
    except (KeyError, TypeError, ValueError):
        inicial = "por_revisar"
    estado = GestorAprendizaje(CONFIG).estado_revision("carpeta", prueba_id, inicial)
    if estado.get("estado") == "completada":
        raise HTTPException(409, f"Reabre la revisión antes de {accion}.")


def _localizar_fila_video(datos: dict, prueba_id: str, video_id: str):
    """Localiza (fila, video_item) en un documento; 404 si no existen."""
    fila = next((f for f in datos.get("resultados", [])
                 if _id_fila(f) == prueba_id), None)
    if fila is None:
        raise HTTPException(404, "No existe el ID solicitado.")
    video_item = next((v for v in (fila.get("videos") or [])
                       if str(v.get("id")) == str(video_id)), None)
    if video_item is None:
        raise HTTPException(404, "Video no encontrado en este ID.")
    return fila, video_item


def _id_fila(fila: dict) -> str:
    """Id corto y estable; evita colisiones cuando distintos lotes repiten nombre."""
    clave = str(fila.get("case_key") or fila.get("ruta") or fila.get("nombre") or "")
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()[:16]


def _partes_portables(ruta: str) -> tuple[str, ...]:
    """Compatibilidad: separación portable centralizada en utilidades."""
    return _partes_portables_seguras(ruta)


def _resolver_raiz_datos(datos: dict) -> Path | None:
    """Resuelve la raíz actual incluso si la configuración quedó obsoleta.

    V15.10.1 R3: una ``raiz_datos_permitida`` inexistente ya no eclipsa una
    ``datos["raiz"]`` válida. Como último recurso se infiere la raíz sólo a
    partir de archivos ya registrados en la corrida.
    """
    configurada = CONFIG.get("dashboard", {}).get("raiz_datos_permitida")
    return _resolver_raiz_datos_segura(
        datos, configurada=configurada, raiz_proyecto=RAIZ_PROYECTO)


def _reubicar_ruta(ruta: str, datos: dict, raiz: Path) -> Path | None:
    """Reubica rutas persistidas sin salir de la raíz efectiva del lote."""
    return _reubicar_ruta_segura(ruta, datos, raiz)


def _rutas_registradas(datos: dict) -> set[str]:
    """Índice reutilizable de rutas del lote para no recorrer miles de imágenes por GET."""
    firma = (_cache.get("mtime"), id(datos))
    if _cache_rutas_registradas.get("firma") == firma:
        return _cache_rutas_registradas["rutas"]
    registradas: set[str] = set()
    for fila in datos.get("resultados", []):
        items = list(fila.get("imagenes") or [])
        items.extend(list(fila.get("videos") or []))
        items.extend(item for item in (fila.get("etiqueta"), fila.get("referencia")) if item)
        registradas.update(str(item["ruta"]) for item in items if item.get("ruta"))
    _cache_rutas_registradas.update(firma=firma, rutas=registradas)
    return registradas


def _resolver_imagen(ruta: str, datos: dict, raiz: Path) -> Path:
    """Convierte una ruta registrada (incluso de otro SO) a su archivo local."""
    if ruta not in _rutas_registradas(datos):
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


def _imagen_transformada(ruta: Path, rotacion: float = 0,
                         ajuste: float = 0.0) -> Response:
    """Entrega una vista orientada igual que la usada por el OCR."""
    import cv2
    import numpy as np

    datos = np.fromfile(str(ruta), dtype=np.uint8)
    imagen = cv2.imdecode(datos, cv2.IMREAD_COLOR)
    if imagen is None:
        raise HTTPException(422, "La imagen está corrupta o no se puede decodificar.")
    imagen = rotar_imagen_libre(imagen, float(rotacion))
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
    manual = float(ocr.get("rotacion_manual_aplicada_grados") or 0) % 360
    orientacion = (manual if ocr.get("orientacion_manual_prioritaria") else
                   (_orientacion_base_publica(ocr) + manual) % 360)
    return dimensiones_rotadas(ancho_original, alto_original, orientacion)


def _rotar_resultado_existente(
        ocr: dict, grados_nuevos: float,
        dimensiones_respaldo: tuple[int, int] | None = None,
        restaurar_automatico: bool | None = None) -> dict:
    """Gira cajas al instante; la geometría automática queda restaurable."""
    dimensiones = ocr.get("dimensiones") or []
    if len(dimensiones) == 2:
        ancho, alto = int(dimensiones[0]), int(dimensiones[1])
    elif dimensiones_respaldo:
        ancho, alto = dimensiones_respaldo
        ocr["dimensiones"] = [ancho, alto]
    else:
        raise ValueError("No fue posible obtener las dimensiones de la imagen para girarla.")
    dimensiones_anteriores = (ancho, alto)
    aplicados = float(ocr.get("rotacion_manual_aplicada_grados") or 0) % 360
    nuevos = round(float(grados_nuevos) % 360, 3)
    restaurar_automatico = (not nuevos if restaurar_automatico is None
                            else bool(restaurar_automatico))
    prioridad_manual = bool(ocr.get("orientacion_manual_prioritaria"))
    base_automatica = (_orientacion_base_publica(ocr) if not prioridad_manual else
                       float(ocr.get("orientacion_automatica_preservada_grados") or 0))
    actual = aplicados if prioridad_manual else (aplicados + base_automatica) % 360
    claves_orientacion = (
        "orientacion_base_grados", "orientacion_texto_base_grados",
        "deskew_aplicado_grados", "deskew_texto_aplicado_grados",
        "orientacion_corregida_grados", "orientacion_texto_grados", "orientacion_grados")

    def capturar_geometria() -> dict:
        dimensiones_fuente = ocr.get("dimensiones_originales") or [ancho, alto]
        return {
            "dimensiones": list(ocr.get("dimensiones") or [ancho, alto]),
            "dimensiones_fuente": [int(dimensiones_fuente[0]), int(dimensiones_fuente[1])],
            "angulo_referencia": actual,
            "referencia_automatica": not prioridad_manual,
            "tokens": [deepcopy(unidad.get("bbox")) for unidad in ocr.get("tokens") or []],
            "lineas_texto": [deepcopy(unidad.get("bbox"))
                              for unidad in ocr.get("lineas_texto") or []],
            "qr_bbox": deepcopy(ocr.get("qr_bbox")), "roi_usado": deepcopy(ocr.get("roi_usado")),
            "orientacion": {clave: ocr.get(clave) for clave in claves_orientacion},
        }

    def restaurar_geometria(guardada: dict) -> None:
        ocr["dimensiones"] = list(guardada["dimensiones"])
        for clave in ("tokens", "lineas_texto"):
            for unidad, bbox in zip(ocr.get(clave) or [], guardada.get(clave) or []):
                unidad["bbox"] = deepcopy(bbox)
        ocr["qr_bbox"] = deepcopy(guardada.get("qr_bbox"))
        ocr["roi_usado"] = deepcopy(guardada.get("roi_usado"))
        for clave, valor in guardada.get("orientacion", {}).items():
            if valor is None:
                ocr.pop(clave, None)
            else:
                ocr[clave] = valor

    guardada = ocr.get("geometria_automatica_preservada")
    if not guardada:
        if not prioridad_manual:
            ocr["orientacion_automatica_preservada_grados"] = base_automatica
            ocr["deskew_automatico_preservado_grados"] = float(
                ocr.get("deskew_texto_aplicado_grados") or
                ocr.get("deskew_aplicado_grados") or 0)
        guardada = capturar_geometria()
        ocr["geometria_automatica_preservada"] = guardada
    else:
        restaurar_geometria(guardada)
    referencia = float(guardada.get("angulo_referencia", base_automatica)) % 360
    fuente = guardada.get("dimensiones_fuente") or ocr.get("dimensiones_originales") or [ancho, alto]
    ancho_fuente, alto_fuente = int(fuente[0]), int(fuente[1])
    if not restaurar_automatico:
        objetivo = nuevos
        delta_geometria = (objetivo - referencia) % 360
        ocr["orientacion_manual_prioritaria"] = True
        ocr["orientacion_base_grados"] = 0
        ocr["orientacion_texto_base_grados"] = 0
        ocr["deskew_aplicado_grados"] = 0.0
        ocr["deskew_texto_aplicado_grados"] = 0.0
    else:
        objetivo = base_automatica
        delta_geometria = (objetivo - referencia) % 360
        ocr["orientacion_manual_prioritaria"] = False
        ocr["orientacion_base_grados"] = int(round(base_automatica)) % 360
        ocr["orientacion_texto_base_grados"] = int(round(base_automatica)) % 360
        ajuste = float(ocr.get("deskew_automatico_preservado_grados") or 0)
        ocr["deskew_aplicado_grados"] = ajuste
        ocr["deskew_texto_aplicado_grados"] = ajuste
    delta_evidencias = (objetivo - actual) % 360
    if abs(delta_geometria) < 1e-6:
        ocr["rotacion_manual_aplicada_grados"] = 0 if restaurar_automatico else nuevos
        return {"delta": delta_evidencias, "dimensiones_anteriores": dimensiones_anteriores,
                "angulo_anterior": actual, "angulo_nuevo": objetivo,
                "dimensiones_fuente": (ancho_fuente, alto_fuente)}
    for clave in ("tokens", "lineas_texto"):
        for unidad in ocr.get(clave) or []:
            if unidad.get("bbox") is not None:
                unidad["bbox"] = transformar_bbox_entre_rotaciones(
                    unidad["bbox"], referencia, objetivo, ancho_fuente, alto_fuente)
    for clave in ("qr_bbox", "roi_usado"):
        if ocr.get(clave) is not None:
            ocr[clave] = transformar_bbox_entre_rotaciones(
                ocr[clave], referencia, objetivo, ancho_fuente, alto_fuente)
    ocr["dimensiones"] = list(dimensiones_rotadas(
        ancho_fuente, alto_fuente, objetivo))
    for clave in ("orientacion_corregida_grados", "orientacion_texto_grados",
                  "orientacion_grados"):
        if ocr.get(clave) is not None:
            ocr[clave] = objetivo % 360
    ocr["rotacion_manual_aplicada_grados"] = 0 if restaurar_automatico else nuevos
    return {"delta": delta_evidencias, "dimensiones_anteriores": dimensiones_anteriores,
            "angulo_anterior": actual, "angulo_nuevo": objetivo,
            "dimensiones_fuente": (ancho_fuente, alto_fuente)}


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
    # El JSON consolidado puede ser grande; el formato compacto conserva el
    # contenido exacto y reduce el tiempo de serialización/escritura.
    escribir_json_seguro(ruta, documento, lanzar=True, compacto=True)


def _commit_documento_externo(salida: Path, documento: dict) -> int:
    """R15.6 (ALTO-04): commit verificado del documento de pruebas externas.

    ``revision_documento`` monotónica + escritura atómica verificada. Exige
    tener adquirido el lock por ruta (``lock_documento(salida)``): la misma
    autoridad que protege el documento principal cubre lectura fresca →
    patch → commit de las ramas externas humanas.
    """
    revision = int(documento.get("revision_documento") or 0) + 1
    documento["revision_documento"] = revision
    _guardar_json_atomico(salida, documento)
    return revision


def _buscar_unidad_ocr(unidades: list[dict], texto: str,
                       bbox: list[int] | None = None,
                       tipo_unidad: str | None = None) -> dict | None:
    """Localiza primero por texto/caja exactos y normaliza sólo como respaldo.

    Esto es importante al reconfirmar OCR que originalmente fue sólo puntuación
    (p. ej. ``;`` leído en una imagen que realmente dice ``41``):
    ``normalizar_codigo(';')`` queda vacío y no debe volver ambigua la selección.
    """
    texto_crudo = str(texto or "").strip()
    # El frontend sabe si el usuario eligió un renglón, token o bloque completo.
    # Usar esa identidad evita resolver accidentalmente otra representación que
    # comparte la misma bbox (algo frecuente cuando tokens y líneas coexisten).
    if tipo_unidad:
        del_tipo = [u for u in unidades if u.get("tipo_unidad") == tipo_unidad]
        if del_tipo:
            unidades = del_tipo

    def textos(unidad: dict) -> set[str]:
        return {
            str(unidad.get("texto_original") or "").strip(),
            str(unidad.get("texto") or "").strip(),
        } - {""}

    # Una caja exacta es la identidad espacial más fuerte del formulario.
    # Dentro de ella aceptamos el original o el texto actualmente proyectado.
    if bbox is not None:
        por_caja = [u for u in unidades if _bbox_igual(u.get("bbox"), bbox)]
        exactas = [u for u in por_caja if texto_crudo in textos(u)]
        if exactas:
            # tokens y lineas_texto pueden contener dos representaciones de la
            # misma caja; con bbox exacta ambas son la misma selección humana.
            return exactas[0]
        if por_caja:
            firmas = {(tuple(u.get("bbox") or []), tuple(sorted(textos(u)))) for u in por_caja}
            if len(firmas) == 1:
                # Permite un cliente que conserva la lectura visible anterior
                # justo después de una reconfirmación, sin confundir otra región.
                return por_caja[0]
        if not por_caja:
            return None

    exactas = [u for u in unidades if texto_crudo in textos(u)]
    if bbox is None:
        sin_caja = [u for u in exactas if u.get("bbox") is None]
        if len(sin_caja) == 1:
            return sin_caja[0]
        if len(exactas) == 1:
            return exactas[0]

    buscado = normalizar_codigo(texto_crudo)
    if not buscado:
        return None
    candidatas = [unidad for unidad in unidades if any(
        normalizar_codigo(valor) == buscado for valor in textos(unidad))]
    if bbox is not None:
        por_caja = [unidad for unidad in candidatas
                    if _bbox_igual(unidad.get("bbox"), bbox)]
        return por_caja[0] if len(por_caja) == 1 else None
    sin_caja = [unidad for unidad in candidatas if unidad.get("bbox") is None]
    if len(sin_caja) == 1:
        return sin_caja[0]
    return candidatas[0] if len(candidatas) == 1 else None


def _aplicar_correcciones_publicas(ocr: dict, correcciones: list[dict]) -> dict:
    """Refleja en la respuesta el texto humano sin alterar el OCR bruto guardado."""
    from utilidades.correcciones_ocr import aplicar_correcciones
    return aplicar_correcciones(ocr, correcciones)


def _regenerar_excel(resultado: dict) -> None:
    """La corrección ya está guardada; programa su exportación durable."""
    try:
        resultado["revision_excel"] = _cola_excel.solicitar()
        resultado["excel_pendiente"] = True
    except Exception as exc:
        resultado["advertencia_excel"] = f"Corrección guardada, no se pudo encolar Excel: {exc}"


_excel_escritura_lock = threading.Lock()


def _generar_excel_serializado(*args, **kwargs):
    from generar_excel import generar_excel
    with _excel_escritura_lock:
        return generar_excel(*args, **kwargs)


def _normalizar_idiomas_exportacion(valores) -> list[str]:
    permitidos = {"es", "en", "de"}
    salida = []
    for valor in (valores or ["es"]):
        codigo = str(valor).lower().strip()
        if codigo not in permitidos:
            raise ValueError(f"Idioma de exportación no soportado: {valor}")
        if codigo not in salida:
            salida.append(codigo)
    return salida or ["es"]


def _generar_excel_asociado():
    """Regenera los Excel asociados a la instantánea actual sin repetir OCR."""
    datos = deepcopy(_cargar_datos() or {})
    if not datos.get("resultados"):
        raise FileNotFoundError("No hay resultados procesados para actualizar el Excel.")
    # V15.9: mismo criterio que muestra la matriz en este momento, declarado.
    verde_c, amarillo_c, origen_c, _instant = _limites_apertura_efectivos()
    criterios_usados = {"verde_max": verde_c, "amarillo_max": amarillo_c, "origen": origen_c}
    idiomas = _normalizar_idiomas_exportacion(datos.get("idiomas_exportacion") or ["es"])
    etiquetas = {"es": "ES", "en": "EN", "de": "DE"}
    declarados = dict(datos.get("archivos_excel") or {})
    base = Path(datos.get("nombre_excel_base") or datos.get("archivo_excel") or (RAIZ_PROYECTO / CONFIG.get(
        "fase3", {}).get("archivo_salida", "resultado_maestro.xlsx")))
    if not base.is_absolute():
        base = RAIZ_PROYECTO / base
    generados = {}
    borradores = {}
    from utilidades.identidad_excel import (PublicacionExcelBloqueadaError,
                                            es_borrador_no_publicable)
    for idioma in idiomas:
        destino = Path(declarados.get(idioma) or base)
        if not destino.is_absolute():
            destino = RAIZ_PROYECTO / destino
        if not declarados.get(idioma) and (len(idiomas) > 1 or idioma != "es"):
            destino = base.with_name(f"{base.stem}_{etiquetas[idioma]}{base.suffix}")
        generado = _generar_excel_serializado(
            RUTA_VALIDACION, destino, CONFIG, REGLAS,
            ruta_plantilla=datos.get("ruta_plantilla"), datos_validacion=datos, idioma=idioma,
            criterios_apertura=criterios_usados)
        # V15.9.4 (ALTA-N6): un borrador bloqueado no es un Excel oficial.
        if es_borrador_no_publicable(generado):
            borradores[idioma] = str(generado)
        else:
            generados[idioma] = str(generado)
    if borradores:
        # La cola durable registra el error y CONSERVA el estado pendiente
        # hasta que el usuario corrija el mapeo/identidad (nada de marcar la
        # reexportación como guardada con un borrador).
        rutas = ", ".join(f"{k}: {v}" for k, v in sorted(borradores.items()))
        raise PublicacionExcelBloqueadaError(
            "Exportación Excel BLOQUEADA: existe una contradicción real o una "
            "estructura de identidad no resoluble de forma segura en la plantilla. "
            f"Borrador(es) no publicable(s) guardado(s) aparte "
            f"para diagnóstico — {rutas}. El destino oficial no se modificó; "
            "corrige la plantilla o la declaración del proyecto y reintenta.")
    return generados.get(idiomas[0]) or next(iter(generados.values()))


from utilidades.cola_excel import ColaExcel

# V14.9 usaba demora=3.0 fija. V14.10 conserva la misma cola durable,
# pero usa una ventana deslizante configurable y más rápida.
_cola_excel = ColaExcel(
    RAIZ_PROYECTO / ".cache_ocr" / "cola_excel.sqlite3",
    _generar_excel_asociado, demora=_EXCEL_DEBOUNCE,
    latencia_maxima=_EXCEL_LATENCIA_MAX)


@asynccontextmanager
async def _lifespan_dashboard(_app):
    _cola_excel.iniciar()
    try:
        yield
    finally:
        # Si había un checkpoint de progreso agrupado, lo fuerza antes de cerrar.
        try:
            _persistir_checkpoint_pipeline()
        finally:
            _cola_excel.detener()


app.router.lifespan_context = _lifespan_dashboard


@app.get("/api/excel/cola")
def estado_cola_excel():
    return _cola_excel.estado()


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
    motores = {"easyocr": importlib.util.find_spec("easyocr") is not None}
    if not motores["easyocr"]:
        faltantes.append("EasyOCR")
    recursos = detectar_recursos(CONFIG.get("fase1", {}).get("dispositivo", "auto"))
    perfil = normalizar_perfil(CONFIG.get("fase1", {}).get("rendimiento", {}).get("perfil_sop", "alto"))
    recursos["perfil_sop"] = perfil
    recursos["limites_sop"] = dict(PERFILES[perfil])
    return {"listo": not faltantes, "faltantes": faltantes,
            "motores": motores, "recursos": recursos, "perfiles": PERFILES,
            "perfil_predeterminado": perfil}


def _actualizar_pipeline(**cambios) -> None:
    with _pipeline_lock:
        _pipeline_estado.update(cambios)
    _persistir_checkpoint_pipeline()


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


def _registrar_advertencia_excel_parcial(mensaje: str) -> None:
    with _pipeline_lock:
        _pipeline_estado.update(
            advertencia_excel_parcial=mensaje, excel_parcial_pendiente=False,
            actualizado_en=datetime.now().isoformat(timespec="milliseconds"))
    _persistir_checkpoint_pipeline()


def _exportar_excel_parcial_pipeline() -> str | None:
    """Genera un Excel recuperable sin convertir sus fallos en errores OCR."""
    if not _pipeline_excel_lock.acquire(blocking=False):
        return _pipeline_estado.get("archivo_excel_parcial")
    try:
        with _pipeline_lock:
            estado = deepcopy(_pipeline_estado)
        if not estado.get("excel_parcial_pendiente"):
            return estado.get("archivo_excel_parcial")

        filas: list[dict] = []
        claves_checkpoint = {
            str(item.get("case_key")) for item in estado.get("resultados_parciales", [])
            if item.get("case_key") and item.get("estado") not in {"procesando", "cancelada"}}
        if RUTA_VALIDACION.is_file() and claves_checkpoint:
            try:
                validacion = json.loads(RUTA_VALIDACION.read_text(encoding="utf-8"))
                filas.extend(fila for fila in validacion.get("resultados", [])
                             if str(fila.get("case_key")) in claves_checkpoint)
            except (OSError, ValueError, json.JSONDecodeError):
                pass

        ruta_avances = RAIZ_PROYECTO / CONFIG.get("empresarial", {}).get(
            "archivo_avance_ids", ".cache_ocr/avances_ids.json")
        if ruta_avances.is_file():
            try:
                avances = json.loads(ruta_avances.read_text(encoding="utf-8"))
                for avance in (avances.get("avances_ids") or {}).values():
                    fila = avance.get("fila_parcial")
                    if fila and avance.get("estado") == "procesando":
                        filas = [item for item in filas
                                 if item.get("case_key") != fila.get("case_key")]
                        filas.append(fila)
            except (OSError, ValueError, json.JSONDecodeError):
                pass

        datos_parciales = {
            "raiz": estado.get("ruta"), "perfil": "empresarial", "parcial": True,
            "generado_en": datetime.now().isoformat(timespec="seconds"),
            "resultados": filas,
        }
        # V15.9: el Excel parcial colorea con los rangos confirmados de esta
        # ejecución, no con una preferencia posterior ajena al lote.
        instantanea_parcial = (estado.get("solicitud") or {}).get("criterios_apertura")
        if instantanea_parcial:
            datos_parciales["criterios_apertura_ejecucion"] = dict(instantanea_parcial)
        ruta_json = RAIZ_PROYECTO / ".cache_ocr" / "validacion_excel_parcial.json"
        resultado_json = escribir_json_seguro(ruta_json, datos_parciales)
        if not resultado_json:
            with _pipeline_lock:
                advertencias = _pipeline_estado.setdefault("advertencias_cache", [])
                if resultado_json.error and resultado_json.error not in advertencias:
                    advertencias.append(resultado_json.error)

        nombre = str(estado.get("nombre_excel") or CONFIG.get("fase3", {}).get(
            "archivo_salida", "resultado_maestro.xlsx"))
        base = Path(nombre).stem or "resultado_maestro"
        idiomas = _normalizar_idiomas_exportacion(estado.get("idiomas_exportacion") or ["es"])
        etiquetas = {"es": "ES", "en": "EN", "de": "DE"}
        datos_parciales["idiomas_exportacion"] = idiomas
        # V15.9.4 (ALTA-N6): la identidad declarada de la ejecución también
        # rige el Excel parcial (mismo contrato de publicación).
        proyecto_parcial = (estado.get("solicitud") or {}).get("proyecto_ejecucion")
        if proyecto_parcial:
            datos_parciales["proyecto_ejecucion"] = dict(proyecto_parcial)
        generar_excel = _generar_excel_serializado
        ruta_plantilla = estado.get("ruta_plantilla")
        generados = {}
        borradores = {}
        from utilidades.identidad_excel import es_borrador_no_publicable
        for idioma in idiomas:
            sufijo = "" if len(idiomas) == 1 and idioma == "es" else f"_{etiquetas[idioma]}"
            ruta_excel = RAIZ_PROYECTO / f"{base}_parcial{sufijo}.xlsx"
            generado = generar_excel(
                ruta_json, ruta_excel, CONFIG, REGLAS, ruta_plantilla=ruta_plantilla,
                datos_validacion=datos_parciales, idioma=idioma)
            if es_borrador_no_publicable(generado):
                borradores[idioma] = str(generado)
            else:
                generados[idioma] = str(generado)
        principal = (generados.get(idiomas[0])
                     or (next(iter(generados.values())) if generados else None))
        advertencia_bloqueo = None
        if borradores:
            rutas = ", ".join(f"{k}: {v}" for k, v in sorted(borradores.items()))
            advertencia_bloqueo = (
                "Exportación Excel BLOQUEADA: la identidad del proyecto no es "
                "verificable en la plantilla (celda de proyecto ausente o "
                "título contradictorio); la salida oficial no se generó. "
                f"Borrador(es) no publicable(s) aparte para diagnóstico: {rutas}.")
        with _pipeline_lock:
            _pipeline_estado.update(
                archivo_excel_parcial=principal, archivos_excel_parcial=generados,
                archivos_excel_parcial_borrador=borradores,
                excel_parcial_actualizado_en=datetime.now().isoformat(timespec="seconds"),
                advertencia_excel_parcial=advertencia_bloqueo,
                excel_parcial_pendiente=False,
                actualizado_en=datetime.now().isoformat(timespec="milliseconds"))
        _persistir_checkpoint_pipeline()
        return principal
    except Exception as exc:
        _registrar_advertencia_excel_parcial(
            f"El avance OCR quedó guardado, pero el Excel parcial no pudo actualizarse: "
            f"{type(exc).__name__}: {exc}")
        return None
    finally:
        _pipeline_excel_lock.release()


def _esperar_continuacion() -> None:
    """Pausa cooperativa: nunca interrumpe una inferencia a la mitad.

    El endpoint sólo solicita la pausa. El estado cambia a ``pausado`` aquí,
    cuando el worker alcanza un punto seguro; justo entonces se congela también
    el reloj de tiempo activo.
    """
    if _pipeline_cancelar.is_set():
        _exportar_excel_parcial_pipeline()
        raise PipelineCancelado("Procesamiento cancelado por el usuario.")
    if not _pipeline_continuar.is_set():
        cambio_estado = False
        with _pipeline_lock:
            if _pipeline_estado.get("estado") == "pausando":
                _congelar_tiempo_pipeline_locked()
                _pipeline_estado.update(
                    estado="pausado", mensaje="Procesamiento en pausa",
                    eta_segundos=None, reanudable=True,
                    actualizado_en=datetime.now().isoformat(timespec="milliseconds"),
                )
                cambio_estado = True
        if cambio_estado:
            _persistir_checkpoint_pipeline()
        _exportar_excel_parcial_pipeline()
    while not _pipeline_continuar.wait(timeout=0.25):
        if _pipeline_cancelar.is_set():
            _exportar_excel_parcial_pipeline()
            raise PipelineCancelado("Procesamiento cancelado por el usuario.")


class PipelineCancelado(RuntimeError):
    pass


def _ejecutar_pipeline_fondo(ruta: Path, nombre_excel: str | None = None,
                             sobrescribir_excel: bool = False,
                             tipo_st: str | None = None,
                             ruta_plantilla: str | None = None,
                             plantilla_id: str | None = None,
                             casos_filtrados: set[str] | None = None,
                             imagenes_filtradas: set[str] | None = None,
                             solo_errores: bool = False,
                             modo_recorte: str | None = None,
                             roi_manual: dict[str, float] | None = None,
                             casos_omitidos: set[str] | None = None,
                             modo_ejecucion: str = "completo",
                             ruta_inventario: str | None = None,
                             zoom_forzado: float | None = None,
                             idiomas_exportacion: list[str] | None = None,
                             ejecucion_id: str | None = None,
                             perfil_rendimiento: str = "alto",
                             contenido: str = "todo",
                             criterios_apertura: dict | None = None,
                             proyecto: dict | None = None) -> None:

    def progreso(fase: str, mensaje: str, detalle: dict | None = None) -> None:
        detalle = dict(detalle or {})
        fila = detalle.pop("resultado", None)
        caso = detalle.pop("caso_detectado", None)
        caso_actualizado = detalle.pop("caso_actualizado", None)
        with _pipeline_lock:
            _pipeline_estado.update(
                fase=fase, mensaje=mensaje,
                transcurrido_segundos=_tiempo_activo_pipeline_locked(),
                actualizado_en=datetime.now().isoformat(timespec="milliseconds"),
                **detalle,
            )
            if fila is not None:
                publica = _fila_publica(fila)
                _pipeline_estado["resultados_parciales"] = [
                    f for f in _pipeline_estado["resultados_parciales"] if f["id"] != publica["id"]]
                _pipeline_estado["resultados_parciales"].append(publica)
                _pipeline_estado["ultimo_id"] = publica.get("id")
                _pipeline_estado["ultimo_id_nombre"] = publica.get("nombre")
                _cache.update({"mtime": None, "datos": None})
                if _pipeline_detener_fin_id.is_set():
                    _pipeline_cancelar.set()
            elif caso is not None:
                publica = _fila_publica(caso)
                if not any(f["id"] == publica["id"] for f in _pipeline_estado["resultados_parciales"]):
                    _pipeline_estado["resultados_parciales"].append(publica)
            elif caso_actualizado is not None:
                publica = _fila_publica(caso_actualizado)
                _pipeline_estado["resultados_parciales"] = [
                    f for f in _pipeline_estado["resultados_parciales"] if f["id"] != publica["id"]]
                _pipeline_estado["resultados_parciales"].append(publica)
        _programar_checkpoint_pipeline()

    try:
        from pipeline import ejecutar_pipeline
        if not criterios_apertura:
            # Reprocesos/reanálisis sin diálogo: conserva el criterio que la
            # pantalla muestra ahora (instantánea, cambio posterior o vigente).
            verde_c, amarillo_c, origen_c, _instant = _limites_apertura_efectivos()
            criterios_apertura = {"verde_max": verde_c, "amarillo_max": amarillo_c,
                                  "origen": origen_c}
        resumen = ejecutar_pipeline(
            ruta, al_progreso=progreso, nombre_excel=nombre_excel,
            sobrescribir_excel=sobrescribir_excel,
            control=_esperar_continuacion, tipo_st=tipo_st,
            ruta_plantilla=ruta_plantilla, casos_filtrados=casos_filtrados,
            plantilla_id=plantilla_id,
            imagenes_filtradas=imagenes_filtradas, solo_errores=solo_errores,
            casos_omitidos=casos_omitidos,
            modo_recorte=modo_recorte, roi_manual=roi_manual,
            modo_ejecucion=modo_ejecucion, ruta_inventario=ruta_inventario,
            zoom_forzado=zoom_forzado, idiomas_exportacion=idiomas_exportacion,
            ejecucion_id=ejecucion_id, perfil_rendimiento=perfil_rendimiento,
            contenido=contenido, criterios_apertura=criterios_apertura,
            proyecto=proyecto)
        _cache.update({"mtime": None, "datos": None})

        # Auditoría R14: no ocultar una escritura fallida bajo un estado
        # visual de éxito. Pipeline/validación pueden anidar la advertencia en
        # distintas fases, así que se recolecta de forma acotada y sólo por la
        # clave explícita ``advertencias_persistencia``.
        advertencias_persistencia = []
        def _recolectar_advertencias_persistencia(obj, profundidad=0):
            if profundidad > 8:
                return
            if isinstance(obj, dict):
                valor = obj.get("advertencias_persistencia")
                if isinstance(valor, (list, tuple)):
                    advertencias_persistencia.extend(str(x) for x in valor if x)
                elif valor:
                    advertencias_persistencia.append(str(valor))
                for v in obj.values():
                    _recolectar_advertencias_persistencia(v, profundidad + 1)
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    _recolectar_advertencias_persistencia(v, profundidad + 1)
        _recolectar_advertencias_persistencia(resumen)
        advertencias_persistencia = list(dict.fromkeys(advertencias_persistencia))

        fase3 = (resumen.get("fases") or {}).get("fase3") or {}
        # V15.9.4 (ALTA-N6): los borradores bloqueados NUNCA entran en la
        # lista oficial de Excel del pipeline.
        _actualizar_pipeline(
            estado="completado", fase="completado",
            mensaje=("Procesamiento terminado con advertencias de persistencia; verifica los archivos antes de cerrar."
                     if advertencias_persistencia else "Procesamiento terminado"),
            persistencia_segura=not bool(advertencias_persistencia),
            advertencias_persistencia=advertencias_persistencia,
            finalizado_en=datetime.now().isoformat(timespec="seconds"), resumen=resumen,
            archivos_excel=fase3.get("archivos") or {},
            archivos_excel_borrador=fase3.get("borradores") or {},
            idiomas_exportacion=fase3.get("idiomas") or idiomas_exportacion or ["es"],
            porcentaje=100, restantes=0, eta_segundos=0,
            transcurrido_segundos=_tiempo_activo_pipeline(), reanudable=False,
        )
    except PipelineCancelado:
        with _pipeline_lock:
            for parcial in _pipeline_estado.get("resultados_parciales", []):
                if parcial.get("estado") == "procesando":
                    parcial["estado"] = "cancelada"
        hasta = _pipeline_estado.get("ultimo_id_nombre") or _pipeline_estado.get("imagen_actual") or "inicio"
        _actualizar_pipeline(
            estado="detenido_con_avance", fase="detenido",
            mensaje=f"Proceso terminado hasta: {hasta}", reanudable=True,
            finalizado_en=datetime.now().isoformat(timespec="seconds"), error=None,
            eta_segundos=None,
            transcurrido_segundos=_tiempo_activo_pipeline())
    except Exception as exc:  # el error se expone y también queda en errores/
        bitacora = _registrar_error_pipeline(ruta, exc)
        _actualizar_pipeline(
            estado="error", mensaje="El procesamiento no pudo completarse",
            finalizado_en=datetime.now().isoformat(timespec="seconds"),
            error=f"{type(exc).__name__}: {exc}", bitacora=str(bitacora),
            eta_segundos=None,
            transcurrido_segundos=_tiempo_activo_pipeline(),
        )
    finally:
        # El cierre cooperativo siempre libera las banderas. No se publica un
        # nuevo propietario CUDA hasta que este hilo haya salido realmente.
        _pipeline_cancelar.clear()
        _pipeline_detener_fin_id.clear()
        _pipeline_continuar.set()
        _persistir_checkpoint_pipeline()
        if bool(_entrenamiento_estado.get("pendiente_auto")):
            _programar_entrenamiento_visual_auto("OCR finalizado; retomando aprendizaje pendiente")


def _lote_de(fila: dict) -> str:
    """Nombre de la carpeta contenedora inmediata (el 'lote')."""
    partes = _partes_portables(str(fila["ruta"]))
    return partes[-2] if len(partes) >= 2 else "Sin lote"


# Columnas de la matriz: definición única en utilidades.matriz_apertura
# (compartida con reporte_bmg). Se conserva el nombre local por compatibilidad.
MATRIZ_APERTURA_COLUMNAS = COLUMNAS_MATRIZ


def _campo_resultado(fila: dict, clave: str, *, solo_confiable: bool = False):
    dato = (fila.get("campos") or {}).get(clave)
    if isinstance(dato, dict):
        if solo_confiable and (dato.get("requiere_revision") or
                               dato.get("estado") in {"conflicto", "pendiente_revision"}):
            return None
        return dato.get("valor")
    if dato not in {None, ""}:
        return dato
    if clave in fila:
        return fila.get(clave)
    return (fila.get("metadata_ruta") or {}).get(clave)


def _numero_ms(valor):
    if isinstance(valor, bool) or valor in {None, "", "--", "-"}:
        return None
    try:
        return float(str(valor).strip().lower().replace("ms", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _normalizar_tiempos_video_fila(fila: dict) -> bool:
    """Autorrepara resultados 8-fps cuando el overlay declara RecXXXX fps.

    V15.6 lo hace también al leer resultados antiguos, de modo que el dashboard
    y la matriz no sigan enseñando 125 ms/cuadro sólo porque el AVI declare 8
    fps de reproducción. La persistencia definitiva ocurre al reanalizar o
    confirmar, pero la vista queda corregida inmediatamente.
    """
    videos = list(fila.get("videos") or [])
    if not videos:
        return False
    try:
        from video_airbag import (CONSENSO_ALGORITMO_VERSION, consenso_videos,
                                  normalizar_videos_caso)
        cambiado = normalizar_videos_caso(videos, CONFIG)
        anterior = fila.get("video_apertura")
        # V15.9.2 (C1): además de cuando cambian los datos de tiempo, se
        # reevalúa si el consenso guardado proviene de otra versión del
        # algoritmo de consolidación (migración en caliente de la vista).
        sello_obsoleto = (isinstance(anterior, dict) and bool(anterior)
                          and anterior.get("algoritmo_consenso") != CONSENSO_ALGORITMO_VERSION)
        if cambiado or sello_obsoleto:
            if isinstance(anterior, dict) and anterior:
                fila["video_apertura_anterior"] = anterior
            consenso = consenso_videos(videos, CONFIG)
            _aplicar_consenso_video_a_fila(fila, consenso)
        return bool(cambiado or sello_obsoleto)
    except Exception:
        # Una autorreparación de compatibilidad nunca debe impedir abrir el
        # listado o un detalle; el reanálisis explícito seguirá disponible.
        return False


def _instantanea_ejecucion_vigente() -> dict | None:
    """Instantánea de rangos de la ejecución cuyos resultados se están viendo."""
    try:
        datos = _cargar_datos()
    except Exception:
        datos = None
    instantanea = (datos or {}).get("criterios_apertura_ejecucion")
    return instantanea if isinstance(instantanea, dict) else None


def _limites_apertura_efectivos() -> tuple[float, float, str, dict | None]:
    """(verde, amarillo, origen, instantánea_usada) para pantalla y exportación.

    Resolución documentada (V15.9): manda el cambio posterior confirmado por el
    usuario en «Resumen»; si no lo hay, la instantánea de la ejecución que
    produjo estos resultados; si tampoco existe, la preferencia guardada o los
    predeterminados 6/7 ms. El origen se publica en la API para que nunca haya
    divergencias silenciosas entre lo mostrado y lo exportado.
    """
    from criterios_usuario import cargar_criterios_usuario
    from utilidades.matriz_apertura import validar_limites
    try:
        usuario = cargar_criterios_usuario()
    except (OSError, ValueError, TypeError):
        usuario = None
    instantanea = _instantanea_ejecucion_vigente()
    if instantanea and usuario and usuario.get("confirmado_en") and instantanea.get("confirmado_en") \
            and str(usuario["confirmado_en"]) > str(instantanea["confirmado_en"]):
        try:
            verde, amarillo = validar_limites(usuario.get("verde_max"), usuario.get("amarillo_max"))
            return verde, amarillo, "cambio_posterior_confirmado", None
        except (ValueError, TypeError):
            pass
    if instantanea:
        try:
            verde, amarillo = validar_limites(instantanea.get("verde_max"),
                                              instantanea.get("amarillo_max"))
            origen = f"instantanea_ejecucion:{instantanea.get('origen') or 'elegido'}"
            return verde, amarillo, origen, instantanea
        except (ValueError, TypeError):
            pass
    if usuario:
        try:
            verde, amarillo = validar_limites(usuario.get("verde_max"), usuario.get("amarillo_max"))
            return verde, amarillo, "criterios_usuario", None
        except (ValueError, TypeError):
            pass
    verde, amarillo = limites_predefinidos()
    return verde, amarillo, "predeterminado", None


def _criterio_apertura_efectivo() -> tuple[dict, str]:
    """Criterio textual del semáforo vigente y su origen (para la leyenda)."""
    verde, amarillo, origen, _instantanea = _limites_apertura_efectivos()
    return criterio_desde_limites(verde, amarillo), origen


def _tiempo_apertura_positivo_api(valor) -> float | None:
    """Validador defensivo de tiempo final para rutas legacy de la API."""
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        numero = float(str(valor).strip().casefold().removesuffix("ms").replace(",", "."))
    except (TypeError, ValueError, OverflowError):
        return None
    return numero if math.isfinite(numero) and numero > 0 else None


def _estado_apertura_fila(fila: dict) -> tuple[str, float | None]:
    """(estado, valor) del semáforo de apertura con el motor compartido V15.9.

    Contrato histórico: sin valor confiable se reporta (\"gris\", None).
    """
    estado, valor, _motivo, _pendiente = _estado_apertura_detalle(fila)
    return estado, valor


def _estado_apertura_detalle(fila: dict, resultado_canonico: dict | None = None) -> tuple[str, float | None, str, float | None]:
    """(estado, valor_publicable, motivo, valor_pendiente).

    Para resultados empresariales V15.10 la vista usa el contrato canónico:
    confirmaciones humanas y resultados AUTO_VERIFICABLES confiables colorean;
    propuestas/conflictos permanecen grises sin borrar la evidencia histórica.
    """
    criterio, _origen = _criterio_apertura_efectivo()
    canonico = resultado_canonico or fila.get("resultado_caso_canonico")
    # Recalcular sólo cuando existen fuentes estructuradas reales. Una fila
    # legacy que únicamente trae ``opening_time_ms`` debe conservar el fallback
    # de compatibilidad y no convertirse artificialmente en NO_OBSERVADO.
    if ("campos" in fila or "consolidado" in fila or "videos" in fila or "video_apertura" in fila):
        try:
            from utilidades.resultado_caso import resolver_resultado_caso
            canonico = resolver_resultado_caso(fila)
        except (TypeError, ValueError):
            canonico = None
    if isinstance(canonico, dict):
        apertura = canonico.get("apertura") if isinstance(canonico.get("apertura"), dict) else {}
        decision = apertura.get("estado")
        if decision in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"}:
            valor_confirmado = _tiempo_apertura_positivo_api(apertura.get("tiempo_ms"))
            if valor_confirmado is not None and apertura.get("referencia_tiempo_valida") is True:
                return evaluar_apertura({"valor": valor_confirmado}, criterio) + (None,)
            return "gris", None, "referencia_invalida", None
        if decision == "CONFLICTO":
            pendiente = _tiempo_apertura_positivo_api(apertura.get("tiempo_propuesto_ms"))
            return "gris", None, "conflicto", pendiente
        if decision == "PROPUESTA":
            # V16.0.2: el color automático ESTIMADO usa la referencia independiente
            # del detector de video (frame/FPS), no se eleva a tiempo definitivo.
            # El motor canónico ya descartó censura, conflicto humano y señales
            # inconsistentes mediante auto_color_elegible.
            estimado = (_tiempo_apertura_positivo_api(apertura.get("tiempo_estimado_auto_ms"))
                        if apertura.get("auto_color_elegible") is True else None)
            if estimado is not None:
                color, _valor, _motivo = evaluar_apertura(
                    {"valor": estimado, "estado": "estimado_automatico"}, criterio)
                if color != "gris":
                    # None impide que el tiempo estimado se publique como verificado.
                    return color, None, "estimacion_automatica_alta_confianza", None
            pendiente = _tiempo_apertura_positivo_api(apertura.get("tiempo_propuesto_ms"))
            return "gris", None, "pendiente_revision", pendiente
        if decision in {"NO_OBSERVADO", "NO_APLICA"}:
            return "gris", None, "sin_tiempo", None
    dato = (fila.get("campos") or {}).get("opening_time_ms")
    if dato is None or (isinstance(dato, str) and dato == ""):
        # V15.9.1 (A5): compatibilidad con resultados antiguos que conservan
        # el tiempo fuera de ``campos`` (``fila.opening_time_ms`` o
        # ``metadata_ruta``). Sin este respaldo, una fila legacy válida se
        # volvería gris al reabrir el lote. La confiabilidad se preserva: un
        # dato marcado pendiente/conflicto nunca llega por estas rutas.
        for legado in (fila.get("opening_time_ms"),
                       (fila.get("metadata_ruta") or {}).get("opening_time_ms")):
            if legado is None or (isinstance(legado, str) and legado == ""):
                continue
            dato = legado if isinstance(legado, dict) else {"valor": legado}
            break
    if not isinstance(dato, dict):
        dato = {"valor": dato} if dato not in {None, ""} else None
    if isinstance(dato, dict) and _tiempo_apertura_positivo_api(dato.get("valor")) is not None:
        referencia_valida = (dato.get("referencia_tiempo_valida") is True
                             if "referencia_tiempo_valida" in dato
                             else dato.get("estado_tiempo") == "VALIDO")
        # Compatibilidad segura con correcciones humanas antiguas: antes de
        # V15.10 no se persistía metadata temporal en el campo manual.
        if (not referencia_valida and "referencia_tiempo_valida" not in dato
                and not dato.get("estado_tiempo")
                and (dato.get("estado") in {"extraido_manual", "confirmado_manual"}
                     or str(dato.get("fuente") or dato.get("fuente_preferida") or "").casefold()
                     in {"manual", "correccion_manual", "correccion_manual_confirmada"})):
            referencia_valida = True
        if not referencia_valida:
            return "gris", None, "referencia_invalida", None
    estado, valor, motivo = evaluar_apertura(dato, criterio)
    if estado == "gris":
        pendiente = valor if motivo in {"pendiente_revision", "conflicto", "sin_regla"} else None
        return "gris", None, motivo, pendiente
    return estado, valor, motivo, None


def _clave_prueba_orden(valor):
    try:
        return (0, int(str(valor).strip()))
    except (TypeError, ValueError):
        return (1, str(valor or ""))


def _matriz_apertura(filas: list[dict]) -> dict | None:
    """Matriz completa V15.9: todas las posiciones, vacantes visibles y sin clasificar.

    Usa la definición compartida ``utilidades.matriz_apertura``: los cupos
    ``esperados`` (5/10) se expanden si hay más casos, las posiciones sin caso
    se pintan como ``vacante`` (sin ID ni tiempo) y los casos sin
    etapa/temperatura/generador verificable aparecen en ``sin_clasificar``.
    """
    if not filas:
        return None
    criterio, origen = _criterio_apertura_efectivo()
    matriz = construir_matriz_dashboard(filas, criterio, origen)
    if matriz is None:
        return None
    # La API conserva el formato histórico de la leyenda («<= 6 ms»).
    from utilidades.matriz_apertura import regla_publica
    matriz["regla"] = regla_publica(
        criterio, origen,
        "sin tiempo confiable, pendiente/conflicto o posición sin caso")
    return matriz


def _evento_censurado_video_api(video: dict | None) -> bool:
    """Reconoce censura tanto en el resultado como en la revisión anidada."""
    if not isinstance(video, dict):
        return False
    revision = video.get("revision_manual")
    revision = revision if isinstance(revision, dict) else {}
    estados = {"evento_al_inicio", "censurado", "censurado_por_izquierda"}
    for registro in (video, revision):
        if (registro.get("evento_al_inicio") or registro.get("censurado_por_izquierda")
                or str(registro.get("estado") or "").casefold() in estados
                or str(registro.get("estado_evento") or "").casefold() in estados
                or str(registro.get("estado_operativo") or "").casefold() in estados
                or str(registro.get("estado_tiempo") or "").upper() == "CENSURADO"):
            return True
    return False


def _video_apertura_publica(video: dict | None) -> dict | None:
    """API defensiva: los tiempos crudos inválidos nunca salen como propuesta normal."""
    if not isinstance(video, dict):
        return video
    salida = dict(video)
    referencia = (salida.get("referencia_tiempo_valida") is True
                  if "referencia_tiempo_valida" in salida
                  else salida.get("estado_tiempo") == "VALIDO")
    estado_origen = str(salida.get("estado_tiempo") or "").upper()
    estados_no_publicables = {
        "NO_FINITO", "NO_POSITIVO", "NO_INTERPRETABLE", "REFERENCIA_INVALIDA",
        "PENDIENTE", "CONFLICTO", "NO_APLICA", "CENSURADO",
    }
    invalidas = salida.get("revisiones_temporales_invalidas")
    invalidas = list(invalidas) if isinstance(invalidas, list) else []
    censurado = _evento_censurado_video_api(salida)
    motivo_por_estado = {
        "NO_POSITIVO": "El tiempo final de apertura debe ser estrictamente mayor que cero.",
        "NO_FINITO": "El tiempo final de apertura debe ser finito.",
        "NO_INTERPRETABLE": "El tiempo final no se puede interpretar como milisegundos.",
        "REFERENCIA_INVALIDA": "La referencia temporal no está validada; el raw queda sólo en auditoría.",
        "PENDIENTE": "La referencia temporal sigue pendiente de validación.",
        "CONFLICTO": "El tiempo está en conflicto; no se publica como tiempo final.",
        "NO_APLICA": "El caso no declara una apertura aplicable.",
        "CENSURADO": "El evento está al inicio del clip; el nacimiento real queda censurado y no se propone tiempo final.",
    }
    estado_final = estado_origen
    motivo_final = salida.get("motivo_rechazo")
    for clave, campo_estado, campo_motivo in (
        ("tiempo_ms", "estado_tiempo", "motivo_rechazo"),
        ("tiempo_propuesto_ms", "estado_tiempo_propuesto", "motivo_rechazo_propuesto"),
    ):
        raw = salida.get(clave)
        if raw is None:
            continue
        try:
            numero = (None if isinstance(raw, bool) else
                      float(str(raw).strip().casefold().removesuffix("ms").replace(",", ".")))
        except (TypeError, ValueError, OverflowError):
            numero = None
        estado_clave_origen = (estado_origen if clave == "tiempo_ms" else
                               str(salida.get("estado_tiempo_propuesto") or "").upper())
        estado = None
        if censurado:
            estado = "CENSURADO"
        elif numero is None:
            estado = "NO_INTERPRETABLE"
        elif not math.isfinite(numero):
            estado = "NO_FINITO"
        elif numero <= 0:
            estado = "NO_POSITIVO"
        elif estado_clave_origen in estados_no_publicables:
            estado = estado_clave_origen
        elif not referencia:
            estado = "REFERENCIA_INVALIDA"
        if estado is None:
            salida[clave] = numero
            salida[campo_estado] = "VALIDO"
            continue
        raw_json = raw
        if isinstance(raw_json, float) and not math.isfinite(raw_json):
            raw_json = repr(raw_json)
        if salida.get("tiempo_crudo_ms") is None:
            salida["tiempo_crudo_ms"] = raw_json
        if salida.get("raw_time_ms") is None:
            salida["raw_time_ms"] = raw_json
        motivo = (salida.get(campo_motivo) or
                  (motivo_final if clave == "tiempo_ms" else None) or
                  motivo_por_estado.get(estado, "Tiempo no publicable."))
        invalidas.append({
            "fuente": f"video_apertura.{clave}", "raw_time_ms": raw_json,
            "tiempo_ms_crudo": numero if numero is not None and math.isfinite(numero) else None,
            "estado_tiempo": estado, "referencia_tiempo_valida": referencia,
            "motivo": motivo, "motivo_rechazo": motivo,
        })
        salida[clave] = None
        salida[campo_estado] = estado
        salida[campo_motivo] = motivo
        if clave == "tiempo_ms":
            estado_final = estado
            motivo_final = motivo
    if censurado:
        estado_final = "CENSURADO"
        motivo_final = motivo_final or motivo_por_estado["CENSURADO"]
        referencia = False
    elif not referencia and estado_final not in estados_no_publicables:
        estado_final = "REFERENCIA_INVALIDA"
        motivo_final = motivo_final or motivo_por_estado["REFERENCIA_INVALIDA"]
    if estado_final:
        salida["estado_tiempo"] = estado_final
    if motivo_final:
        salida["motivo_rechazo"] = motivo_final
    salida["referencia_tiempo_valida"] = bool(referencia and not censurado)
    salida["revisiones_temporales_invalidas"] = invalidas
    return salida


def _campo_apertura_publico(campo: dict | None, resultado_canonico: dict | None) -> dict:
    """Proyecta el campo de apertura desde el contrato canónico, dejando raw sólo en auditoría."""
    original = dict(campo) if isinstance(campo, dict) else {}
    campos = (resultado_canonico or {}).get("campos") if isinstance(resultado_canonico, dict) else {}
    canonico = campos.get("opening_time_ms") if isinstance(campos, dict) else None
    apertura = ((resultado_canonico or {}).get("apertura")
                if isinstance(resultado_canonico, dict) else {})
    if not isinstance(canonico, dict):
        # La ruta no publica el raw como tiempo normal si el resolver canónico
        # falla. Se permite sólo una cifra finita >0 con referencia explícita.
        tiempo_legacy = original.get("tiempo_ms")
        if tiempo_legacy is None:
            tiempo_legacy = original.get("valor")
        referencia_legacy = (original.get("referencia_tiempo_valida") is True
                             if "referencia_tiempo_valida" in original
                             else original.get("estado_tiempo") == "VALIDO")
        proxy = _video_apertura_publica({
            **original,
            "tiempo_ms": tiempo_legacy,
            "tiempo_propuesto_ms": original.get("tiempo_propuesto_ms"),
        }) or {}
        salida_legacy = {**original, **proxy}
        invalido = (proxy.get("estado_tiempo") in {
            "NO_FINITO", "NO_POSITIVO", "NO_INTERPRETABLE", "REFERENCIA_INVALIDA", "PENDIENTE", "CENSURADO"
        } or (tiempo_legacy is not None and
              _tiempo_apertura_positivo_api(tiempo_legacy) is None)
          or (tiempo_legacy is not None and not referencia_legacy))
        if invalido:
            raw = original.get("raw_time_ms")
            if raw is None:
                raw = original.get("tiempo_crudo_ms")
            if raw is None:
                raw = tiempo_legacy
            if isinstance(raw, float) and not math.isfinite(raw):
                raw = repr(raw)
            salida_legacy.update({
                "valor": None, "tiempo_ms": None, "tiempo_propuesto_ms": None,
                "raw_time_ms": raw, "tiempo_crudo_ms": raw,
                "referencia_tiempo_valida": False,
                "estado": "pendiente_revision",
                "decision": "PROPUESTA", "decision_v15_10": "PROPUESTA",
                "requiere_revision": True,
                "motivo_rechazo": (proxy.get("motivo_rechazo") or
                    "El tiempo de apertura no cumple el contrato finito, >0 ms y referencia validada."),
            })
            if proxy.get("estado_tiempo"):
                salida_legacy["estado_tiempo"] = proxy["estado_tiempo"]
        else:
            tiempo_seguro = _tiempo_apertura_positivo_api(tiempo_legacy)
            salida_legacy["valor"] = tiempo_seguro
            salida_legacy["tiempo_ms"] = tiempo_seguro
            propuesta = original.get("tiempo_propuesto_ms")
            salida_legacy["tiempo_propuesto_ms"] = _tiempo_apertura_positivo_api(propuesta)
        return salida_legacy
    decision = canonico.get("decision") or apertura.get("estado") or "NO_OBSERVADO"
    estados_legacy = {
        "VERIFICADO_HUMANO": "confirmado_manual", "PROPUESTA": "pendiente_revision",
        "CONFLICTO": "conflicto", "NO_APLICA": "no_aplica", "NO_OBSERVADO": "sin_dato",
        "AUTO_VERIFICABLE": "confirmado_automatico",
    }
    salida = {**original, **canonico}
    salida.update({
        "valor": canonico.get("valor"),
        "decision": decision,
        "decision_v15_10": decision,
        "estado": estados_legacy.get(decision, "pendiente_revision"),
        "requiere_revision": decision in {"PROPUESTA", "CONFLICTO"},
        "tiempo_ms": apertura.get("tiempo_ms"),
        "tiempo_propuesto_ms": apertura.get("tiempo_propuesto_ms"),
        "tiempo_crudo_ms": apertura.get("tiempo_crudo_ms"),
        "raw_time_ms": apertura.get("raw_time_ms"),
        "estado_tiempo": apertura.get("estado_tiempo"),
        "referencia_tiempo_valida": apertura.get("referencia_tiempo_valida") is True,
        "motivo_rechazo": apertura.get("motivo_rechazo"),
    })
    return salida


def _video_item_publico(video: dict | None) -> dict | None:
    """Sanitiza también la revisión anidada de cada video sin borrar historial/raw."""
    if not isinstance(video, dict):
        return video
    salida = dict(video)
    revision = salida.get("revision_manual")
    revision = revision if isinstance(revision, dict) else {}
    censurado = _evento_censurado_video_api(salida)
    if censurado:
        raw = salida.get("tiempo_ms_sospechoso")
        if raw is None:
            raw = salida.get("tiempo_crudo_ms", salida.get("tiempo_ms"))
        if raw is not None:
            salida.setdefault("tiempo_crudo_ms", raw)
            salida.setdefault("raw_time_ms", raw)
        salida["estado_tiempo"] = "CENSURADO"
        salida["motivo_rechazo"] = (salida.get("motivo_rechazo") or
                                    "El evento está censurado al inicio del clip; falta evidencia previa del nacimiento.")
    revision = salida.get("revision_manual")
    salida = _video_apertura_publica(salida)
    if isinstance(revision, dict):
        revision_publica = dict(revision)
        if censurado:
            revision_publica["censurado_por_izquierda"] = True
            revision_publica["estado_tiempo"] = "CENSURADO"
            revision_publica["motivo_rechazo"] = (revision_publica.get("motivo_rechazo") or
                "El evento está censurado al inicio del clip; falta evidencia previa del nacimiento.")
        salida["revision_manual"] = _video_apertura_publica(revision_publica)
    return salida


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
    _normalizar_tiempos_video_fila(fila)
    resultado_canonico = fila.get("resultado_caso_canonico")
    if ("campos" in fila or "consolidado" in fila or "videos" in fila or "video_apertura" in fila
            or not isinstance(resultado_canonico, dict)):
        try:
            from utilidades.resultado_caso import resolver_resultado_caso
            resultado_canonico = resolver_resultado_caso(fila)
        except (TypeError, ValueError):
            resultado_canonico = fila.get("resultado_caso_canonico") if isinstance(
                fila.get("resultado_caso_canonico"), dict) else None
    semaforo_apertura, opening_time_ms, apertura_motivo, apertura_pendiente = \
        _estado_apertura_detalle(fila, resultado_canonico)
    apertura_canonica = (resultado_canonico.get("apertura")
                         if isinstance(resultado_canonico, dict)
                         and isinstance(resultado_canonico.get("apertura"), dict) else {})
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
        "opening_time_ms": opening_time_ms,
        "opening_time_estimado_ms": (apertura_canonica.get("tiempo_estimado_auto_ms")
            if apertura_motivo == "estimacion_automatica_alta_confianza" else None),
        "apertura_es_estimada": apertura_motivo == "estimacion_automatica_alta_confianza",
        "apertura_tiempo_publicable": opening_time_ms is not None,
        "semaforo_apertura": semaforo_apertura,
        "apertura_motivo": apertura_motivo,
        "opening_time_pendiente_ms": apertura_pendiente,
        "opening_time_raw_ms": apertura_canonica.get("tiempo_crudo_ms"),
        "opening_time_status": apertura_canonica.get("estado_tiempo"),
        "opening_time_reference_valid": apertura_canonica.get("referencia_tiempo_valida"),
        "opening_time_rejection_reason": apertura_canonica.get("motivo_rechazo"),
        "test_number": fila.get("test_number") or _campo_resultado(fila, "test_number"),
        "ruta": fila.get("ruta"), "ruta_relativa": fila.get("ruta_relativa"),
        "estructura_valida": fila.get("estructura_valida"),
        "estado": fila.get("estado", "detectada"), "progreso": fila.get("progreso", {}),
        "total_imagenes": fila.get("total_imagenes", 0),
        "total_videos": fila.get("total_videos", len(fila.get("videos") or [])),
        "video_apertura": _video_apertura_publica(fila.get("video_apertura")),
        "resultado_caso_canonico": resultado_canonico,
        "imagenes_nach": fila.get("imagenes_nach", 0),
        "imagenes_vor": fila.get("imagenes_vor", 0),
        "carpetas_tor": fila.get("carpetas_tor", []),
        "estado_deteccion": fila.get("estado_deteccion") or
                            ("estructura_valida" if fila.get("estructura_valida") else
                             "estructura_incompleta" if fila.get("estructura_valida") is False else None),
        "campos_encontrados": (int(fila.get("campos_encontrados"))
            if isinstance(fila.get("campos_encontrados"), (int, float))
            else sum(dato.get("valor") not in {None, ""} for dato in fila.get("campos", {}).values())),
        "campos_faltantes": (int(fila.get("campos_faltantes"))
            if isinstance(fila.get("campos_faltantes"), (int, float))
            else len(fila.get("campos_faltantes") or [])),
        "conflictos": (int(fila.get("conflictos"))
            if isinstance(fila.get("conflictos"), (int, float))
            else len(fila.get("conflictos") or [])),
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

@app.get("/api/salud")
def salud():
    """Diagnóstico mínimo que no depende de que los resultados OCR sean legibles."""
    with _pipeline_lock:
        estado_pipeline = str(_pipeline_estado.get("estado") or "inactivo")
        advertencias = list(_pipeline_estado.get("advertencias_cache") or [])
        advertencias_persistencia = list(_pipeline_estado.get("advertencias_persistencia") or [])
        persistencia_segura = _pipeline_estado.get("persistencia_segura")
    return {
        "ok_backend": True,
        "patch_build": PATCH_BUILD,
        "version_api": app.version,
        "estado_pipeline": estado_pipeline,
        "persistencia_segura": persistencia_segura,
        "advertencias": list(dict.fromkeys([*advertencias, *advertencias_persistencia])),
        "validacion_existe": RUTA_VALIDACION.is_file(),
        "checkpoint_existe": RUTA_CHECKPOINT_PIPELINE.is_file(),
        "raiz_proyecto": str(RAIZ_PROYECTO),
    }


@app.get("/api/estado")
def estado():
    datos = _cargar_datos()
    return {
        "hay_datos": datos is not None and len(datos.get("resultados", [])) > 0,
        "total": len(datos.get("resultados", [])) if datos else 0,
        "generado_en": datos.get("generado_en") if datos else None,
        "raiz": _raiz_publica(datos) if datos else None,
        "raiz_origen": datos.get("raiz") if datos else None,
        # V15.9.4 (ALTA-N5): fallo de persistencia de la migración, visible.
        "advertencia_migracion_consensos": _advertencia_migracion_consensos,
        "patch_build": PATCH_BUILD,
    }


@app.get("/api/config")
def config_dashboard():
    from criterios_usuario import cargar_criterios_usuario, criterios_o_predeterminados
    advertencia = None
    try:
        criterios_usuario = cargar_criterios_usuario()
    except (OSError, ValueError, TypeError) as exc:
        criterios_usuario = None
        advertencia = f"No se pudieron leer los límites elegidos; revisa antes de valorar: {exc}"
    try:
        vigentes = criterios_o_predeterminados()
    except (OSError, ValueError, TypeError):
        vigentes = None
    verde_def, amarillo_def = limites_predefinidos()
    criterio_efectivo, origen_efectivo = _criterio_apertura_efectivo()
    instantanea = _instantanea_ejecucion_vigente()
    return {
        "nombre_herramienta": "OCR Versuchsmatrix",
        "patch_build": PATCH_BUILD,
        "colores": CONFIG.get("colores", {}),
        "reglas": REGLAS.get("criterios", {}),
        "idiomas_interfaz": ["es", "en", "de"],
        "idiomas_exportacion": ["es", "en", "de"],
        "criterios_usuario": criterios_usuario,
        "advertencia_criterios": advertencia,
        # V15.9: diálogo previo a «Procesar carpeta».
        "criterios_predeterminados": {"verde_max": verde_def, "amarillo_max": amarillo_def},
        "criterios_vigentes": vigentes,
        "criterio_efectivo": {"limites": criterio_efectivo, "origen": origen_efectivo},
        "instantanea_ejecucion": instantanea,
    }


@app.post("/api/config/criterios-apertura")
def configurar_criterios_apertura(solicitud: SolicitudCriteriosApertura):
    from criterios_usuario import guardar_criterios_apertura, reglas_apertura
    with _pipeline_lock, _video_reanalisis_lock:
        if (_pipeline_estado.get("estado") in {
                "procesando", "pausando", "pausado", "cancelando", "reanudando"}
                or (_video_reanalisis_hilo is not None and _video_reanalisis_hilo.is_alive())):
            raise HTTPException(409, "Termina o detén el procesamiento antes de cambiar sus criterios.")
        try:
            actual = guardar_criterios_apertura(
                solicitud.verde_max, solicitud.amarillo_max, solicitud.usuario)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "No se guardaron los límites; se conservan los anteriores.") from exc
        REGLAS.setdefault("criterios", {})["tiempo_apertura_ms"] = reglas_apertura(actual)
    return {"guardado": True, "criterios_usuario": actual,
            "nota": "La matriz cambia ahora; vuelve a exportar para actualizar el Excel. No modifica los tiempos medidos."}


@app.get("/api/plantillas")
def listar_plantillas():
    from plantilla_empresarial import RegistroPlantillas
    return {"plantillas": RegistroPlantillas(CONFIG).listar()}


@app.get("/api/proyectos")
def listar_proyectos():
    """V15.9.2 (C7): proyectos declarados + sugerencias pendientes de aceptación.

    Los registrados vienen de elecciones humanas confirmadas. Las sugerencias
    (carpeta actual, resultados anteriores) SIEMPRE llevan
    ``pendiente_aceptacion=True``: el frontend debe mostrarlas como candidatos
    y nunca asignarlas en silencio. La plantilla Excel no aparece aquí.
    """
    from utilidades import proyectos as registro_proyectos
    try:
        registrados = registro_proyectos.listar_proyectos()
    except registro_proyectos.RegistroProyectosCorruptoError as exc:
        # CRIT-04: registro ilegible ⇒ error visible, nunca lista vacía fingida.
        raise HTTPException(503, f"Registro de proyectos ilegible: {exc}") from exc
    conocidos = {str(p.get("proyecto_id")) for p in registrados}
    try:
        datos = _cargar_datos()
    except Exception:
        datos = None
    sugerencias = [s for s in registro_proyectos.sugerir_desde_datos(datos)
                   if s["proyecto_id"] not in conocidos]
    with _pipeline_lock:
        actual = _pipeline_estado.get("proyecto_ejecucion")
    if actual is None and isinstance(datos, dict):
        actual = datos.get("proyecto_ejecucion")
    return {"proyectos": registrados, "sugerencias": sugerencias,
            "proyecto_actual": actual,
            "sin_asignar": {"proyecto_id": "sin-asignar", "nombre_proyecto": None,
                            "sin_asignar": True, "pendiente": True}}


@app.post("/api/plantillas", status_code=201)
def registrar_plantilla(solicitud: SolicitudPlantilla):
    from plantilla_empresarial import RegistroPlantillas
    try:
        return RegistroPlantillas(CONFIG).registrar(
            solicitud.ruta, solicitud.nombre, solicitud.tipos_st,
            solicitud.marcadores_ruta)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/pipeline/capacidad")
def capacidad_pipeline():
    return _capacidad_pipeline()


@app.get("/api/pipeline/estado")
def estado_pipeline():
    with _pipeline_lock:
        estado = dict(_pipeline_estado)
        estado["resultados_parciales"] = list(_pipeline_estado["resultados_parciales"])
        estado["transcurrido_segundos"] = _tiempo_activo_pipeline_locked()
        estado["tiempo_medido_en"] = datetime.now().isoformat(timespec="milliseconds")
    perfil = normalizar_perfil(estado.get("perfil_rendimiento") or "alto")
    try:
        estado["metricas_recursos"] = obtener_gestor_recursos(perfil).snapshot()
    except Exception as exc:
        estado["metricas_recursos"] = {"perfil": perfil, "error": f"{type(exc).__name__}: {exc}"}
    try:
        estado["persistencia"] = _cola_excel.estado()
    except Exception as exc:
        estado["persistencia"] = {"estado_persistencia": "error", "error": str(exc)}
    return estado


@app.get("/api/aprendizaje")
def estado_aprendizaje():
    return {**GestorAprendizaje(CONFIG).estado(),
            "entrenamiento_visual": dict(_entrenamiento_estado)}


def _estadisticas_muestras_entrenables() -> dict:
    gestor = GestorAprendizaje(CONFIG)
    try:
        with gestor._conectar() as con:
            fila = con.execute("""SELECT COUNT(*) AS muestras,
                COUNT(DISTINCT caso_id) AS ids, COALESCE(MAX(rowid), 0) AS max_rowid
                FROM muestras_visuales WHERE entrenable=1""").fetchone()
        return {"muestras": int(fila["muestras"] or 0), "ids": int(fila["ids"] or 0),
                "max_rowid": int(fila["max_rowid"] or 0)}
    except Exception:
        return {"muestras": 0, "ids": 0, "max_rowid": 0}


def _pipeline_activo_para_entrenamiento() -> bool:
    with _pipeline_lock:
        estado = str(_pipeline_estado.get("estado") or "")
        hilo_vivo = bool(_pipeline_hilo and _pipeline_hilo.is_alive())
    return bool(hilo_vivo and estado in {"preparando", "procesando", "pausando", "pausado",
                                        "cancelando", "reanudando"})


def _lanzar_entrenamiento_visual(modo: str = "manual", objetivo_rowid: int | None = None) -> bool:
    """Arranca un ajuste visual. El modo auto nunca compite con el pipeline OCR."""
    if modo == "auto" and _pipeline_activo_para_entrenamiento():
        _entrenamiento_estado.update({"estado": "pendiente", "modo": "auto",
                                      "pendiente_auto": True,
                                      "motivo_pendiente": "Esperando a que la GPU termine el OCR."})
        return False
    if not _entrenamiento_lock.acquire(blocking=False):
        if modo == "auto":
            _entrenamiento_estado["pendiente_auto"] = True
        return False
    stats_inicio = _estadisticas_muestras_entrenables()
    objetivo_rowid = int(objetivo_rowid if objetivo_rowid is not None else stats_inicio["max_rowid"])
    _entrenamiento_estado.update({"estado": "entrenando", "resultado": None, "error": None,
                                  "modo": modo, "pendiente_auto": False,
                                  "objetivo_rowid": objetivo_rowid,
                                  "iniciado_en": datetime.now().isoformat(timespec="seconds")})

    def trabajo():
        relanzar = False
        try:
            from entrenamiento_easyocr import entrenar_lote
            config_entreno = deepcopy(CONFIG)
            if modo == "auto":
                visual = config_entreno.setdefault("aprendizaje", {}).setdefault("visual", {})
                visual["epocas"] = max(1, int(visual.get("epocas_auto", 1)))
            try:
                resultado = entrenar_lote(config_entreno)
            except RuntimeError as exc:
                if "out of memory" not in str(exc).lower():
                    raise
                config_cpu = deepcopy(config_entreno)
                config_cpu.setdefault("fase1", {})["dispositivo"] = "cpu"
                resultado = entrenar_lote(config_cpu)
                resultado["advertencia"] = (
                    "La GPU se quedó sin memoria; el ajuste visual se reintentó automáticamente en CPU.")
            resultado["modo"] = modo
            if modo == "auto":
                # V15.10: el entrenamiento puede crear un candidato, pero no
                # promover pesos en segundo plano. La activación requiere una
                # evaluación sellada y aprobación humana explícita.
                resultado["activado_automaticamente"] = False
                resultado["motivo_no_activacion"] = (
                    "La liberación visual está bloqueada hasta aprobar el test sellado y registrar revisión humana.")
            _entrenamiento_estado.update({"estado": resultado.get("estado", "terminado"),
                                          "resultado": resultado, "error": None,
                                          "ultimo_rowid_entrenado": objetivo_rowid})
            from ocr_engine import _MOTORES
            _MOTORES.clear()
            _limpiar_cache_variantes()
        except Exception as exc:
            _entrenamiento_estado.update({"estado": "error", "resultado": None,
                                          "error": f"{type(exc).__name__}: {exc}"})
        finally:
            _entrenamiento_estado["finalizado_en"] = datetime.now().isoformat(timespec="seconds")
            _entrenamiento_lock.release()
            actuales = _estadisticas_muestras_entrenables()
            relanzar = bool(_entrenamiento_estado.pop("pendiente_auto", False) or
                            actuales["max_rowid"] > int(objetivo_rowid or 0))
            if relanzar:
                _programar_entrenamiento_visual_auto("Nueva evidencia recibida durante el entrenamiento")

    threading.Thread(target=trabajo, daemon=True).start()
    return True


def _programar_entrenamiento_visual_auto(motivo: str = "imagen verificada") -> dict:
    """Coalesce eventos por imagen y entrena solo cuando hay una muestra nueva utilizable."""
    global _entrenamiento_auto_timer
    visual = CONFIG.get("aprendizaje", {}).get("visual", {})
    if not bool(visual.get("auto_entrenar", True)):
        return {"programado": False, "motivo": "auto_entrenamiento_desactivado"}
    stats = _estadisticas_muestras_entrenables()
    minimo = int(visual.get("minimo_muestras", 12))
    minimo_ids = int(visual.get("minimo_ids", 5))
    if stats["muestras"] < minimo or stats["ids"] < minimo_ids:
        return {"programado": False, "motivo": "evidencia_insuficiente", **stats,
                "minimo_muestras": minimo, "minimo_ids": minimo_ids}
    if stats["max_rowid"] <= int(_entrenamiento_estado.get("ultimo_rowid_entrenado") or 0):
        return {"programado": False, "motivo": "sin_muestras_nuevas", **stats}
    if _pipeline_activo_para_entrenamiento():
        _entrenamiento_estado.update({"estado": "pendiente", "modo": "auto",
                                      "pendiente_auto": True, "motivo_pendiente": motivo})
        return {"programado": True, "diferido": True, "motivo": "pipeline_ocr_activo", **stats}
    espera = max(0.2, min(10.0, float(visual.get("auto_debounce_segundos", 1.5))))
    with _entrenamiento_auto_guard:
        if _entrenamiento_auto_timer is not None and _entrenamiento_auto_timer.is_alive():
            _entrenamiento_auto_timer.cancel()
        objetivo = stats["max_rowid"]
        def disparar():
            _lanzar_entrenamiento_visual("auto", objetivo)
        _entrenamiento_auto_timer = threading.Timer(espera, disparar)
        _entrenamiento_auto_timer.daemon = True
        _entrenamiento_auto_timer.start()
    _entrenamiento_estado.update({"estado": "programado", "modo": "auto",
                                  "pendiente_auto": True, "motivo_pendiente": motivo})
    return {"programado": True, "diferido": False, "en_segundos": espera, **stats}


@app.post("/api/aprendizaje/entrenar-visual", status_code=202)
def iniciar_entrenamiento_visual():
    if not _lanzar_entrenamiento_visual("manual"):
        raise HTTPException(409, "Ya existe un entrenamiento visual activo o la GPU está ocupada.")
    return {"aceptado": True, "estado": "entrenando", "modo": "manual"}


@app.post("/api/aprendizaje/modelos-visuales/{version}/activar")
def activar_modelo_visual(version: str):
    try:
        resultado = GestorAprendizaje(CONFIG).activar_modelo_visual(version)
        from ocr_engine import _MOTORES
        _MOTORES.clear()
        _limpiar_cache_variantes()
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
    _assert_documento_editable("guardar la corrección")
    # R15.3 (ALTO-02): si esta corrección persistirá confirmación/campo en el
    # documento, CAS + efectos sqlite + commit ocurren en la MISMA región de
    # exclusión (más abajo): un 409 ya no puede emitirse con efectos durables.
    va_a_mutar_documento = (solicitud.accion not in {"ilegible", "no_es_campo"}
                            and bool(getattr(solicitud, "componente", None)
                                     or getattr(solicitud, "campo_destino", None)))
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
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "La raíz de imágenes no está disponible en este equipo.")
    ruta_local = _resolver_imagen(str(item["ruta"]), datos, raiz)
    ocr = _aplicar_correcciones_publicas(item["resultado_ocr"], gestor.listar_correcciones_texto([ruta_local]))
    ocr = gestor.filtrar_no_texto(ocr, ruta_local)
    unidades = ([{**u, "tipo_unidad": "token"} for u in (ocr.get("tokens") or [])] +
                [{**u, "tipo_unidad": "renglón"} for u in (ocr.get("lineas_texto") or [])])
    if ocr.get("texto_completo"):
        unidades.append({"texto": ocr["texto_completo"], "bbox": None,
                         "tipo_unidad": "bloque completo",
                         "texto_original": ocr.get("texto_completo_original") or ocr["texto_completo"]})
    token = _buscar_unidad_ocr(unidades, solicitud.texto_ocr, solicitud.bbox,
                              getattr(solicitud, "tipo_unidad", None))
    if token is None:
        raise HTTPException(
            400, "La lectura OCR no coincide de forma única; vuelve a seleccionarla en la imagen.")
    # R15.3 (ALTO-02): región de exclusión del documento — CAS autoritativo,
    # efectos durables (sqlite/entrenamiento) y commit atómicos. Las rutas
    # que NO mutan el documento (ilegible/no_es_campo sin destino) conservan
    # su comportamiento anterior sin tomar el lock.
    # R15.6 (ALTO-02): la operación completa —evidencias SQLite, estado de
    # revisión y commit documental— queda bajo el coordinador común en TODAS
    # sus ramas (incluidas ilegible/no_es_campo, que antes no capturaban
    # snapshot). Doble fallo ⇒ inconsistencia durable + bloqueo del caso.
    _assert_recurso_consistente(f"carpeta:{solicitud.prueba_id}",
                                "guardar la corrección")
    with _lock_documento() if va_a_mutar_documento else contextlib.nullcontext():
        if va_a_mutar_documento:
            _prechequeo_cas_documento(solicitud.expected_revision)
        tx = TransaccionMultiAlmacen(
            "corrección de lectura",
            recurso=f"carpeta:{solicitud.prueba_id}")
        tx.capturar(
            "evidencias y estado de revisión",
            lambda: gestor.snapshot_evidencias_imagen(
                ruta_local, caso_id=solicitud.prueba_id),
            gestor.restaurar_evidencias_imagen)
        tx.aplicado()  # el bloque siguiente ES el efecto: compensar si falla
        try:
            try:
                texto_actual = str(token.get("texto") or solicitud.texto_ocr)
                texto_original = str(token.get("texto_original") or texto_actual)
                correcto = texto_actual if solicitud.accion == "aceptar" else solicitud.texto_correcto
                estado_supervision = ("aceptado_provisional" if solicitud.accion == "aceptar"
                                      else "corregido_humano" if solicitud.accion in {
                                          "corregir", "guardar_sin_entrenar", "confirmar_entrenar"}
                                      else solicitud.accion)
                metadatos_supervision = {k: fila.get(k) for k in
                    ("tipo_st", "module_version", "temperature_condition", "inflator_type")}
                metadatos_supervision.update({
                    "project_id": fila.get("project_id"),
                    "case_key": fila.get("case_key"),
                    "componente": getattr(solicitud, "componente", None) or "por_identificar",
                    "campo_propuesto": getattr(solicitud, "campo_destino", None),
                    "campo_fuente": solicitud.campo,
                    "bbox_original": token.get("bbox"),
                    "texto_ocr_original": texto_original,
                    "texto_lectura_previa": texto_actual,
                    "estado_supervision": estado_supervision,
                    "fuente_supervision": "aceptar_ocr" if solicitud.accion == "aceptar" else "dashboard",
                    "giro_foto": float(ocr.get("orientacion_texto_grados") or 0),
                    "poligono_lectura": token.get("poligono_lectura"),
                    "orientacion_region_grados": token.get("orientacion_region_grados"),
                    "marco_region": token.get("marco_region"),
                    "estrategia_ocr_confirmada": getattr(solicitud, "estrategia_ocr", None),
                })
                if (getattr(solicitud, "campo_destino", None) == "opening_time_ms"
                        and solicitud.accion not in {"aceptar", "ilegible", "no_es_campo"}):
                    try:
                        tiempo_apertura = float(str(correcto).strip().replace(",", "."))
                    except (TypeError, ValueError, OverflowError) as exc:
                        raise ValueError("El tiempo de apertura debe ser numérico, finito y > 0 ms.") from exc
                    if not math.isfinite(tiempo_apertura) or tiempo_apertura <= 0 or tiempo_apertura > 1000:
                        raise ValueError("El tiempo de apertura debe ser finito, > 0 y ≤ 1000 ms.")
                if token.get("edicion_zona") and solicitud.accion not in {"ilegible", "no_es_campo"}:
                    from utilidades.edicion_zonas import guardar_bloque
                    if not correcto.strip():
                        raise ValueError("Escribe o confirma el texto del bloque.")
                    if correcto != token.get("texto"):
                        with gestor._conectar() as con:
                            guardar_bloque(con, hash_archivo(ruta_local), ocr, list(token["bbox"]),
                                           [{"bbox": list(token["bbox"]), "texto": correcto}])
                    accion_muestra = ("aceptar" if solicitud.accion == "aceptar" else "confirmar_entrenar")
                    muestra = gestor.registrar_muestra_visual(
                        ruta_local, solicitud.prueba_id,
                        texto_actual if solicitud.accion == "aceptar" else texto_original,
                        correcto, token.get("bbox"), accion=accion_muestra,
                        entrenable=accion_muestra != "aceptar",
                        campo=getattr(solicitud, "campo_destino", None) or solicitud.campo,
                        fase=item.get("fase"), tor=item.get("tor"),
                        confianza=token.get("confianza"), modelo_origen=ocr.get("modelo_visual_version")
                        or ocr.get("motor"), usuario=solicitud.usuario, metadatos=metadatos_supervision)
                    resultado = {"registrada": True, "tipo": "supervision_visual",
                                 "estado_supervision": estado_supervision,
                                 "entrenamiento": None, "muestra_visual": muestra}
                elif solicitud.accion in {"ilegible", "no_es_campo"}:
                    muestra = gestor.registrar_muestra_visual(
                        ruta_local, solicitud.prueba_id, solicitud.texto_ocr, correcto,
                        token.get("bbox"), accion=solicitud.accion, entrenable=False,
                        campo=getattr(solicitud, "campo_destino", None) or solicitud.campo,
                        fase=item.get("fase"), tor=item.get("tor"),
                        confianza=token.get("confianza"), modelo_origen=ocr.get("modelo_visual_version")
                        or ocr.get("motor"), usuario=solicitud.usuario,
                        metadatos=metadatos_supervision)
                    resultado = {"registrada": True, "tipo": "supervision_visual",
                                 "muestra_visual": muestra, "entrenamiento": None}
                else:
                    if not correcto.strip():
                        raise ValueError("Escribe el texto correcto antes de confirmar.")
                    resultado = gestor.registrar_correccion(
                        texto_actual, correcto, ruta_imagen=str(ruta_local),
                        bbox=token.get("bbox"), fuente="dashboard", caso_id=solicitud.prueba_id,
                        accion=solicitud.accion,
                        entrenar_visual=True,
                        campo=getattr(solicitud, "campo_destino", None) or solicitud.campo,
                        fase=item.get("fase"), tor=item.get("tor"),
                        confianza=token.get("confianza"), modelo_origen=ocr.get("modelo_visual_version")
                        or ocr.get("motor"), usuario=solicitud.usuario,
                        metadatos=metadatos_supervision)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            if isinstance(resultado, dict):
                resultado.setdefault("estado_supervision", estado_supervision)
            estrategia_confirmada = getattr(solicitud, "estrategia_ocr", None)
            if (estrategia_confirmada and solicitud.accion not in {"ilegible", "no_es_campo"}
                    and token.get("bbox") is not None):
                try:
                    contexto_estrategia = {
                        "project_id": fila.get("project_id"), "tipo_st": fila.get("tipo_st"),
                        "module_version": fila.get("module_version"), "fase": item.get("fase"),
                        "componente": getattr(solicitud, "componente", None) or "por_identificar",
                        "campo": getattr(solicitud, "campo_destino", None) or solicitud.campo,
                    }
                    estrategia_guardada = gestor.registrar_estrategia_ocr(
                        str(ruta_local), token.get("bbox"), ocr.get("dimensiones") or [],
                        estrategia_confirmada, caso_id=solicitud.prueba_id,
                        contexto=contexto_estrategia, usuario=solicitud.usuario)
                    resultado["estrategia_ocr_guardada"] = estrategia_guardada
                    _limpiar_cache_variantes()
                except (ValueError, OSError) as exc:
                    resultado["advertencia_estrategia_ocr"] = str(exc)
            gestor.actualizar_revision("carpeta", solicitud.prueba_id, estado="parcial")
            # La selección de componente/campo del editor es una confirmación explícita
            # distinta del entrenamiento OCR. Se guarda en el JSON consolidado para que
            # sobreviva al reinicio y llegue a Excel; no se propaga a otros casos.
            # getattr mantiene compatibilidad con clientes/pruebas antiguos que aún no
            # envían estos campos opcionales.
            componente_supervision = getattr(solicitud, "componente", None)
            campo_destino = getattr(solicitud, "campo_destino", None)
            if solicitud.accion not in {"ilegible", "no_es_campo"} and (
                    componente_supervision or campo_destino):
                evidencia = {
                    "imagen_id": solicitud.imagen_id, "imagen": item.get("ruta"),
                    "bbox_original": token.get("bbox"),
                    "texto_ocr_original": texto_original,
                    "texto_lectura_previa": texto_actual,
                    "texto_corregido": correcto,
                    "estado_supervision": estado_supervision,
                    "fuente": "aceptar_ocr" if solicitud.accion == "aceptar" else "correccion_manual",
                    "orientacion_grados": token.get("orientacion_region_grados")
                        if token.get("orientacion_region_grados") is not None
                        else ocr.get("orientacion_texto_grados"),
                }
                confirmacion = {
                    **evidencia, "componente": componente_supervision or "por_identificar",
                    "campo": campo_destino, "usuario": solicitud.usuario,
                    "fecha": datetime.now().isoformat(timespec="seconds")}
                if campo_destino and solicitud.accion == "aceptar":
                    resultado["campo_provisional"] = {
                        "campo": campo_destino, "valor": correcto,
                        "estado_supervision": "aceptado_provisional",
                        "requiere_revision": True,
                    }

                # R15.1 (CRÍTICO-01): la clasificación se persiste sobre el documento
                # fresco bajo lock; un ValueError de campo aborta SIN commitear nada.
                def _persistir_en_fresco(frescos: dict):
                    fila_f = next((f for f in frescos.get("resultados", [])
                                   if _id_fila(f) == solicitud.prueba_id), None)
                    if fila_f is None:
                        raise HTTPException(404, "La prueba indicada ya no existe.")
                    fila_f.setdefault("confirmaciones_extraccion", []).append(confirmacion)
                    if (campo_destino and fila_f.get("perfil") == "empresarial"
                            and solicitud.accion not in {"aceptar", "ilegible", "no_es_campo"}):
                        try:
                            return _aplicar_campo_manual_en_fila(
                                fila_f, campo_destino, correcto, solicitud.usuario,
                                componente_supervision, evidencia)
                        except ValueError as exc:
                            raise HTTPException(400, str(exc)) from exc
                    return None

                revision_documento, dato = mutar_documento(
                    _persistir_en_fresco, solicitud.expected_revision, estricto=True)
                if dato is not None:
                    resultado["campo_confirmado"] = {"campo": campo_destino, "dato": dato}
                resultado["revision_documento"] = revision_documento
        except BaseException as exc:
            # R15.6 (ALTO-02): compensación VERIFICADA por el coordinador;
            # si la restauración también falla, registra la inconsistencia de
            # forma durable (nunca un doble fallo silencioso) y bloquea el
            # recurso hasta su resolución.
            try:
                tx.fallar(exc)
            except HTTPException:
                raise
            except ValueError as vexc:
                raise HTTPException(400, str(vexc)) from vexc
            except Exception:  # noqa: BLE001 — fallo de almacén, compensado
                raise HTTPException(503, (
                    "No se pudo completar 'corrección de lectura' "
                    f"({type(exc).__name__}: {exc}). Los efectos externos "
                    "fueron restaurados; la solicitud no produjo efectos "
                    "persistentes.")) from exc
        tx.exito()

    muestra_confirmada = resultado.get("muestra_visual") if isinstance(resultado, dict) else None
    programador_auto = globals().get("_programar_entrenamiento_visual_auto")
    if (isinstance(muestra_confirmada, dict) and muestra_confirmada.get("entrenable")
            and callable(programador_auto)):
        # R15.6 (política HIGH-01 de R15.5): aprendizaje = efecto opcional
        # post-commit; su fallo jamás revierte la confirmación humana.
        _aprendizaje_opcional(
            resultado, programador_auto,
            f"Supervisión confirmada: {solicitud.prueba_id}/{solicitud.imagen_id or solicitud.campo}")
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
    poligono = (_validar_poligono_recorte(solicitud.poligono, [ancho_imagen, alto_imagen]).tolist()
                if solicitud.poligono is not None else None)

    # R15.6 (MEDIO-06): anotación + estado de revisión en una sola
    # transacción; el entrenamiento automático queda DESPUÉS del éxito
    # (efecto opcional tolerante a fallo, política HIGH-01 de R15.5).
    def _efectos():
        efecto = gestor.registrar_region(
            solicitud.texto_correcto, solicitud.bbox, poligono=poligono,
            ruta_imagen=str(ruta_local), carpeta_id=_id_fila(fila),
            carpeta_nombre=fila.get("nombre"),
            imagen_nombre=item.get("nombre") or ruta_local.name,
            fase=item.get("fase"), tor=item.get("tor"),
            modelo_origen=(item.get("resultado_ocr") or {}).get("modelo_visual_version")
            or (item.get("resultado_ocr") or {}).get("motor"),
            usuario=solicitud.usuario,
            entrenable=True,
            metadatos={**{k: fila.get(k) for k in
                       ("tipo_st", "module_version", "temperature_condition", "inflator_type")},
                       "giro_foto": float((item.get("resultado_ocr") or {}).get("orientacion_texto_grados") or 0)})
        gestor.actualizar_revision("carpeta", solicitud.prueba_id,
                                   estado="parcial")
        return efecto

    resultado = _transaccion_efecto_humano(
        "anotación de región manual", gestor, "carpeta", solicitud.prueba_id,
        _efectos,
        recurso=_recurso_imagen(solicitud.prueba_id, solicitud.imagen_id),
        ruta_imagen=ruta_local)
    if resultado.get("muestra_visual"):
        _aprendizaje_opcional(
            resultado, _programar_entrenamiento_visual_auto,
            f"Región manual confirmada: {solicitud.prueba_id}/{solicitud.imagen_id}")
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
    """R15.6 (ALTO-04): la rotación externa corre bajo el lock por ruta del
    documento externo (lectura fresca → patch → commit verificado)."""
    if solicitud.tipo != "carpeta":
        from pruebas_externas import rutas
        _, salida = rutas(CONFIG)
        with _pdoc.lock_documento(salida):
            return _guardar_rotacion_impl(solicitud)
    return _guardar_rotacion_impl(solicitud)


def _guardar_rotacion_impl(solicitud: SolicitudRotacion):
    """Memoriza la orientación humana; el siguiente OCR la usa como punto de partida."""
    if solicitud.tipo == "carpeta":
        _assert_documento_editable("rotar la imagen")
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
        # R15.6 (ALTO-04): CAS sobre la lectura fresca (bajo lock por ruta).
        # R15.7 (MEDIO-05): ESTRICTO — un writer humano sobre un documento
        # externo ya versionado no puede omitir expected_revision.
        _verificar_expected_revision(solicitud.expected_revision,
                                     documento_externo, estricto=True)
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
    # R15.5 (HIGH-02): transacción única — snapshot del almacén de
    # aprendizaje, efectos externos (rotación + evidencias + estado de
    # revisión) y commit del documento AL FINAL; cualquier fallo ⇒
    # restauración verificada (coordinador P0); doble fallo ⇒ inconsistencia
    # explícita y bloqueo del recurso.
    # R15.7 (ALTO-02): identidad canónica (subrecurso de imagen) — un bloqueo
    # de la CARPETA detiene también esta rotación y viceversa.
    recurso_rotacion = _recurso_imagen(
        solicitud.prueba_id, solicitud.imagen_id)
    if solicitud.tipo != "carpeta":
        recurso_rotacion = _recurso_externa(solicitud.prueba_id)
    _assert_recurso_consistente(recurso_rotacion, "rotar la imagen")
    tx = TransaccionMultiAlmacen("rotación de imagen",
                                 recurso=recurso_rotacion)

    def _aplicar_almacen(giro: dict) -> dict:
        efecto = (gestor.eliminar_rotacion(ruta) if solicitud.usar_automatico
                  else gestor.actualizar_rotacion(ruta, solicitud.grados))
        efecto.update(gestor.rotar_evidencias_imagen(
            ruta, giro["delta"], giro["dimensiones_anteriores"],
            grados_desde=giro["angulo_anterior"], grados_hasta=giro["angulo_nuevo"],
            dimensiones_fuente=giro["dimensiones_fuente"]))
        gestor.actualizar_revision(solicitud.tipo, solicitud.prueba_id,
                                   estado="parcial")
        return efecto

    try:
        if gestor.filtrar_no_texto(ocr_objetivo, ruta).get("ediciones_zona"):
            raise HTTPException(409, "Deshaz las uniones de esta imagen antes de cambiar su giro guardado. El zoom y el giro de vista siguen disponibles.")
        dimensiones_respaldo = _dimensiones_ocr_desde_archivo(ruta, ocr_objetivo)

        def _limpiar_geometria(ocr_rotado: dict) -> None:
            # Los recortes guardados pertenecen al marco anterior. No mostrar
            # ni entrenar con polígonos regionales obsoletos tras girar la foto.
            ocr_rotado["recortes"] = []
            for unidad in [*(ocr_rotado.get("tokens") or []), *(ocr_rotado.get("lineas_texto") or [])]:
                unidad.pop("poligono_lectura", None)
                unidad.pop("marco_region", None)

        if solicitud.tipo == "carpeta":
            # R15.1 (CRÍTICO-01): el giro se calcula sobre el documento FRESCO
            # bajo lock (el documento es la fuente de verdad del delta).
            # R15.5 (HIGH-02): el COMMIT se hace al final, después de los
            # efectos externos compensables.
            def _rotar_en_fresco(frescos: dict):
                fila_f = next((f for f in frescos.get("resultados", [])
                               if _id_fila(f) == solicitud.prueba_id), None)
                if fila_f is None:
                    raise HTTPException(404, "La carpeta indicada no existe.")
                item_f = next((imagen for imagen in fila_f.get("imagenes", [])
                               if imagen.get("id") == solicitud.imagen_id), None)
                if item_f is None:
                    raise HTTPException(404, "La imagen indicada no pertenece a la carpeta.")
                ocr_f = item_f.get("resultado_ocr") or {}
                giro_f = _rotar_resultado_existente(
                    ocr_f, solicitud.grados, dimensiones_respaldo,
                    restaurar_automatico=solicitud.usar_automatico)
                _limpiar_geometria(ocr_f)
                # Etiqueta/referencia son vistas resumidas de las mismas imágenes.
                for campo in ("etiqueta", "referencia"):
                    copia = fila_f.get(campo)
                    if (copia and str(copia.get("ruta")) == str(item_f.get("ruta")) and
                            copia.get("resultado_ocr") is not ocr_f):
                        ocr_copia = copia.get("resultado_ocr") or {}
                        _rotar_resultado_existente(
                            ocr_copia, solicitud.grados,
                            _dimensiones_ocr_desde_archivo(ruta, ocr_copia),
                            restaurar_automatico=solicitud.usar_automatico)
                return giro_f

            try:
                with _lock_documento():
                    datos_frescos = _leer_documento_disco()
                    _verificar_expected_revision(solicitud.expected_revision,
                                                 datos_frescos, estricto=True)
                    giro = _rotar_en_fresco(datos_frescos)
                    _, resultado = tx.aplicar(
                        "rotación, evidencias y revisión",
                        lambda: gestor.snapshot_evidencias_imagen(
                            ruta, solicitud.prueba_id),
                        lambda: _aplicar_almacen(giro),
                        gestor.restaurar_evidencias_imagen)
                    revision_documento = _commit_documento(datos_frescos)
            except BaseException as exc:
                try:
                    tx.fallar(exc)
                except HTTPException:
                    raise
                except Exception:  # noqa: BLE001 — fallo del almacén, compensado
                    raise HTTPException(503, (
                        "No se pudo actualizar el almacén de rotaciones/"
                        f"evidencias ({type(exc).__name__}: {exc}). Los efectos "
                        "externos fueron restaurados; la solicitud no produjo "
                        "efectos persistentes.")) from exc
            resultado["revision_documento"] = revision_documento
        else:
            giro = _rotar_resultado_existente(
                ocr_objetivo, solicitud.grados, dimensiones_respaldo,
                restaurar_automatico=solicitud.usar_automatico)
            _limpiar_geometria(ocr_objetivo)
            try:
                _, resultado = tx.aplicar(
                    "rotación, evidencias y revisión",
                    lambda: gestor.snapshot_evidencias_imagen(
                        ruta, solicitud.prueba_id, tipo_revision="externa"),
                    lambda: _aplicar_almacen(giro),
                    gestor.restaurar_evidencias_imagen)
                _commit_documento_externo(salida_externa, documento_externo)
            except BaseException as exc:
                try:
                    tx.fallar(exc)
                except HTTPException:
                    raise
                except Exception:  # noqa: BLE001 — fallo de almacén/JSON, compensado
                    raise HTTPException(503, (
                        "No se pudo completar la rotación en la prueba externa "
                        f"({type(exc).__name__}: {exc}). Los efectos externos "
                        "fueron restaurados; la solicitud no produjo efectos "
                        "persistentes.")) from exc
        tx.exito()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    resultado["mensaje"] = ((
        "Se restauró la orientación automática y se ajustaron sus cajas y regiones.")
        if solicitud.usar_automatico else (
        "Imagen rotada ahora. También se ajustaron sus cajas y regiones; "
        "el próximo OCR conservará esta orientación manual."))
    return resultado


@app.post("/api/imagenes/sin-datos")
def marcar_imagen_sin_datos(solicitud: SolicitudImagenSinDatos):
    """R15.6 (ALTO-04): la marca externa corre bajo el lock por ruta del
    documento externo (lectura fresca → patch → commit verificado)."""
    if solicitud.tipo != "carpeta":
        from pruebas_externas import rutas
        _, salida = rutas(CONFIG)
        with _pdoc.lock_documento(salida):
            return _marcar_imagen_sin_datos_impl(solicitud)
    return _marcar_imagen_sin_datos_impl(solicitud)


def _marcar_imagen_sin_datos_impl(solicitud: SolicitudImagenSinDatos):
    """Registra una decisión humana válida; no la presenta como error OCR."""
    if solicitud.tipo == "carpeta":
        _assert_documento_editable("marcar la imagen sin datos")
    gestor = GestorAprendizaje(CONFIG)
    if solicitud.tipo == "carpeta":
        datos = _cargar_datos()
        fila = next((f for f in (datos or {}).get("resultados", [])
                     if _id_fila(f) == solicitud.prueba_id), None)
        if fila is None:
            raise HTTPException(404, "La carpeta indicada no existe.")
        item = next((imagen for imagen in fila.get("imagenes", [])
                     if imagen.get("id") == solicitud.imagen_id), None)
        if item is None:
            raise HTTPException(404, "La imagen indicada no pertenece a la carpeta.")
        raiz = _resolver_raiz_datos(datos)
        if raiz is None:
            raise HTTPException(503, "La raíz de imágenes no está disponible en este equipo.")
        ruta = _resolver_imagen(str(item["ruta"]), datos, raiz)

        # R15.1 (CRÍTICO-01): patch sobre el documento fresco, bajo lock.
        def _marcar_en_fresco(frescos: dict):
            fila_f = next((f for f in frescos.get("resultados", [])
                           if _id_fila(f) == solicitud.prueba_id), None)
            if fila_f is None:
                raise HTTPException(404, "La carpeta indicada no existe.")
            item_f = next((imagen for imagen in fila_f.get("imagenes", [])
                           if imagen.get("id") == solicitud.imagen_id), None)
            if item_f is None:
                raise HTTPException(404, "La imagen indicada no pertenece a la carpeta.")
            item_f["estado_imagen"] = "revisada_sin_datos"
            item_f["revision_sin_datos"] = resultado
            if item_f.get("resultado_ocr") is not None:
                item_f["resultado_ocr"]["estado_imagen"] = "revisada_sin_datos"
            for traza in fila_f.get("trazabilidad", []):
                if str(traza.get("ruta_absoluta")) == str(ruta):
                    traza.update({"estado_imagen": "revisada_sin_datos",
                                  "requiere_revision": False,
                                  "mensaje_error": solicitud.motivo or None})

        # R15.3 (ALTO-02): CAS autoritativo, efecto durable (SQLite) y commit
        # en la MISMA región de exclusión del documento. El prechequeo ya no
        # es una garantía aparte: mientras se sostiene el lock ningún otro
        # escritor puede mover la revisión, así que un 409 sólo puede ocurrir
        # ANTES del registro (cero efectos persistentes de una petición
        # rechazada) y el commit final no puede encontrar un conflicto nuevo.
        # R15.5 (MEDIUM-04): política uniforme — marca sin-datos y estado de
        # revisión son efectos compensables ANTES del commit documental,
        # coordinados por TransaccionMultiAlmacen (restauración VERIFICADA;
        # doble fallo ⇒ inconsistencia explícita + bloqueo del recurso).
        recurso_imagen = _recurso_imagen(
            solicitud.prueba_id, solicitud.imagen_id)
        _assert_recurso_consistente(recurso_imagen, "marcar la imagen sin datos")
        tx = TransaccionMultiAlmacen("marcar imagen sin datos",
                                     recurso=recurso_imagen)
        with _lock_documento():
            _prechequeo_cas_documento(solicitud.expected_revision)
            try:
                tx.capturar("marca sin-datos",
                            lambda: gestor.imagen_sin_datos(ruta),
                            lambda estado: _restaurar_marca_sin_datos(
                                gestor, ruta, estado))
                resultado = gestor.registrar_imagen_sin_datos(
                    ruta, solicitud.prueba_id, solicitud.motivo,
                    solicitud.usuario)
                tx.aplicado()
                tx.capturar("estado de revisión",
                            lambda: _capturar_revision_estado(
                                gestor, "carpeta", solicitud.prueba_id),
                            lambda estado: _restaurar_revision_estado(
                                gestor, "carpeta", solicitud.prueba_id, estado))
                gestor.actualizar_revision(solicitud.tipo, solicitud.prueba_id,
                                           estado="parcial")
                tx.aplicado()
                resultado["revision_documento"] = mutar_documento(
                    _marcar_en_fresco, solicitud.expected_revision, estricto=True)[0]
            except BaseException as exc:
                tx.fallar(exc)
            tx.exito()
    else:
        from pruebas_externas import cargar, rutas
        documento = cargar(CONFIG)
        # R15.6 (ALTO-04): CAS sobre la lectura fresca (bajo lock por ruta).
        # R15.7 (MEDIO-05): ESTRICTO en writers humanos externos.
        _verificar_expected_revision(solicitud.expected_revision, documento,
                                     estricto=True)
        fila = next((f for f in documento.get("resultados", [])
                     if f.get("id") == solicitud.prueba_id), None)
        if fila is None:
            raise HTTPException(404, "La prueba externa indicada no existe.")
        ruta = Path(str(fila.get("ruta") or "")).resolve()
        # R15.5 (MEDIUM-04): la rama externa comparte la MISMA política: la
        # marca SQLite y el estado de revisión son efectos compensables y el
        # JSON externo es el commit final; si falla, restauración verificada
        # (antes la marca sobrevivía al fallo de escritura del JSON).
        recurso_externo = _recurso_externa(solicitud.prueba_id)
        _assert_recurso_consistente(recurso_externo, "marcar la imagen sin datos")
        tx = TransaccionMultiAlmacen("marcar imagen sin datos (externa)",
                                     recurso=recurso_externo)
        try:
            tx.capturar("marca sin-datos",
                        lambda: gestor.imagen_sin_datos(ruta),
                        lambda estado: _restaurar_marca_sin_datos(
                            gestor, ruta, estado))
            resultado = gestor.registrar_imagen_sin_datos(
                ruta, solicitud.prueba_id, solicitud.motivo, solicitud.usuario)
            tx.aplicado()
            tx.capturar("estado de revisión",
                        lambda: _capturar_revision_estado(
                            gestor, "externa", solicitud.prueba_id),
                        lambda estado: _restaurar_revision_estado(
                            gestor, "externa", solicitud.prueba_id, estado))
            gestor.actualizar_revision(solicitud.tipo, solicitud.prueba_id,
                                       estado="parcial")
            tx.aplicado()
            fila["estado_imagen"] = "revisada_sin_datos"
            fila["revision_sin_datos"] = resultado
            _, salida = rutas(CONFIG)
            resultado["revision_documento_externo"] = _commit_documento_externo(
                salida, documento)
        except BaseException as exc:
            try:
                tx.fallar(exc)
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001 — fallo de almacén, compensado
                raise HTTPException(503, (
                    "No se pudo completar la marca sin-datos en la prueba "
                    f"externa ({type(exc).__name__}: {exc}). Los efectos "
                    "externos fueron restaurados; la solicitud no produjo "
                    "efectos persistentes.")) from exc
        tx.exito()
    resultado["mensaje"] = "Imagen revisada y registrada sin datos de texto útiles."
    return resultado


def _restaurar_estado_con_texto(item: dict) -> None:
    item.pop("revision_sin_datos", None)
    item.pop("revision_imagen", None)
    item.pop("motivo_sin_datos", None)
    item["estado_imagen"] = "pendiente"
    ocr = item.get("resultado_ocr")
    if isinstance(ocr, dict):
        ocr.pop("revision_sin_datos", None)
        ocr.pop("motivo_sin_datos", None)
        ocr["estado_imagen"] = "pendiente"


@app.post("/api/imagenes/con-texto")
def restaurar_imagen_con_texto(solicitud: SolicitudImagenSinDatos):
    """R15.6 (ALTO-04): la restauración externa corre bajo el lock por ruta
    del documento externo (lectura fresca → patch → commit verificado)."""
    if solicitud.tipo != "carpeta":
        from pruebas_externas import rutas
        _, salida = rutas(CONFIG)
        with _pdoc.lock_documento(salida):
            return _restaurar_imagen_con_texto_impl(solicitud)
    return _restaurar_imagen_con_texto_impl(solicitud)


def _restaurar_imagen_con_texto_impl(solicitud: SolicitudImagenSinDatos):
    # R15.3 (ALTO-03): guarda UNIFORME de pipeline. En R15.2 esta ruta sólo
    # miraba el hilo vivo e ignoraba _pipeline_reserva: durante la ventana
    # entre admisión y arranque del worker aceptaba restauraciones que el
    # pipeline estaba a punto de procesar.
    if solicitud.tipo == "carpeta":
        _assert_documento_editable("restaurar la imagen")
    gestor = GestorAprendizaje(CONFIG)
    if solicitud.tipo == "carpeta":
        datos = deepcopy(_cargar_datos())
        fila = next((f for f in (datos or {}).get("resultados", []) if _id_fila(f) == solicitud.prueba_id), None)
        if fila is None:
            raise HTTPException(404, "Carpeta no encontrada.")
        item = next((i for i in fila.get("imagenes", []) if i.get("id") == solicitud.imagen_id), None)
        if item is None:
            raise HTTPException(404, "Imagen no encontrada en esta carpeta.")
        raiz = _resolver_raiz_datos(datos)
        if raiz is None:
            raise HTTPException(503, "La raíz de imágenes no está disponible.")
        ruta = _resolver_imagen(str(item["ruta"]), datos, raiz)

        # Garantía V15.9.3 preservada bajo R15.1: si la escritura JSON falla,
        # la marca persistida NO se elimina. El DELETE queda preparado dentro
        # de una transacción sqlite abierta y sólo se confirma (con.commit)
        # después de que ``mutar_documento`` persista el documento con éxito.
        # R15.5 (MEDIUM-04): el estado de revisión es efecto compensable
        # aplicado ANTES del commit, con la misma política transversal.
        recurso_imagen = _recurso_imagen(
            solicitud.prueba_id, solicitud.imagen_id)
        _assert_recurso_consistente(recurso_imagen, "restaurar la imagen")
        tx = TransaccionMultiAlmacen("restaurar imagen con texto",
                                     recurso=recurso_imagen)
        try:
            tx.capturar("estado de revisión",
                        lambda: _capturar_revision_estado(
                            gestor, "carpeta", solicitud.prueba_id),
                        lambda estado: _restaurar_revision_estado(
                            gestor, "carpeta", solicitud.prueba_id, estado))
            gestor.actualizar_revision(solicitud.tipo, solicitud.prueba_id,
                                       estado="parcial")
            tx.aplicado()
        except BaseException as exc:
            try:
                tx.fallar(exc)
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001 — fallo de almacén, compensado
                raise HTTPException(503, (
                    "No se pudo actualizar el estado de revisión "
                    f"({type(exc).__name__}: {exc}). La solicitud no produjo "
                    "efectos persistentes.")) from exc
        con = gestor._conectar()
        try:
            def _restaurar_en_fresco(frescos: dict):
                fila_f = next((f for f in frescos.get("resultados", [])
                               if _id_fila(f) == solicitud.prueba_id), None)
                if fila_f is None:
                    raise HTTPException(404, "Carpeta no encontrada.")
                item_f = next((i for i in fila_f.get("imagenes", [])
                               if i.get("id") == solicitud.imagen_id), None)
                if item_f is None:
                    raise HTTPException(404, "Imagen no encontrada en esta carpeta.")
                con.execute("DELETE FROM imagenes_sin_datos WHERE imagen_hash=?",
                            (hash_archivo(ruta),))
                _restaurar_estado_con_texto(item_f)
                for alias in (fila_f.get("etiqueta"), fila_f.get("referencia")):
                    if alias and str(alias.get("ruta")) == str(item_f["ruta"]):
                        _restaurar_estado_con_texto(alias)
                for traza in fila_f.get("trazabilidad", []):
                    if str(traza.get("ruta_absoluta")) in {str(ruta), str(item_f["ruta"])}:
                        traza.update(estado_imagen="pendiente", requiere_revision=True,
                                     mensaje_error=None)

            resultado = {"restaurada": True, "estado_imagen": "pendiente"}
            resultado["revision_documento"] = mutar_documento(
                _restaurar_en_fresco, solicitud.expected_revision, estricto=True)[0]
            con.commit()
        except BaseException as exc:
            con.rollback()
            tx.fallar(exc)  # compensa el estado de revisión ya aplicado
        finally:
            con.close()
        tx.exito()
    else:
        from pruebas_externas import cargar, rutas
        datos = deepcopy(cargar(CONFIG))
        # R15.6 (ALTO-04): CAS sobre la lectura fresca (bajo lock por ruta).
        # R15.7 (MEDIO-05): ESTRICTO en writers humanos externos.
        _verificar_expected_revision(solicitud.expected_revision, datos,
                                     estricto=True)
        item = next((f for f in datos.get("resultados", []) if f.get("id") == solicitud.prueba_id), None)
        if item is None:
            raise HTTPException(404, "Prueba externa no encontrada.")
        ruta = Path(str(item.get("ruta") or "")).resolve()
        if not ruta.is_file():
            raise HTTPException(404, "La imagen ya no está disponible.")
        _restaurar_estado_con_texto(item)
        _, destino = rutas(CONFIG)
        # Si falla la escritura JSON, la transacción no elimina la marca persistida.
        # R15.5 (MEDIUM-04): estado de revisión compensable antes del commit.
        recurso_externo = _recurso_externa(solicitud.prueba_id)
        _assert_recurso_consistente(recurso_externo, "restaurar la imagen")
        tx = TransaccionMultiAlmacen("restaurar imagen con texto (externa)",
                                     recurso=recurso_externo)
        try:
            tx.capturar("estado de revisión",
                        lambda: _capturar_revision_estado(
                            gestor, "externa", solicitud.prueba_id),
                        lambda estado: _restaurar_revision_estado(
                            gestor, "externa", solicitud.prueba_id, estado))
            gestor.actualizar_revision(solicitud.tipo, solicitud.prueba_id,
                                       estado="parcial")
            tx.aplicado()
            with gestor._conectar() as con:
                con.execute("DELETE FROM imagenes_sin_datos WHERE imagen_hash=?", (hash_archivo(ruta),))
                _commit_documento_externo(destino, datos)
        except BaseException as exc:
            try:
                tx.fallar(exc)
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001 — fallo de almacén/JSON, compensado
                raise HTTPException(503, (
                    "No se pudo restaurar la imagen en la prueba externa "
                    f"({type(exc).__name__}: {exc}). Los efectos externos "
                    "fueron restaurados; la solicitud no produjo efectos "
                    "persistentes.")) from exc
        tx.exito()
        resultado = {"restaurada": True, "estado_imagen": "pendiente"}
    resultado["mensaje"] = ("Marca sin texto retirada. La imagen queda pendiente de revisión. "
                            "Si no tiene lecturas, reprocesa esta imagen.")
    _regenerar_excel(resultado)
    return resultado


@app.post("/api/imagenes/verificar")
def verificar_imagen(solicitud: SolicitudImagenVerificada):
    """Confirma que una imagen con texto ya fue revisada por una persona."""
    _assert_documento_editable("verificar la imagen")
    datos = _cargar_datos()
    fila = next((f for f in (datos or {}).get("resultados", [])
                 if _id_fila(f) == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "La carpeta indicada no existe.")
    item = next((imagen for imagen in fila.get("imagenes", [])
                 if imagen.get("id") == solicitud.imagen_id), None)
    if item is None:
        raise HTTPException(404, "La imagen indicada no pertenece a la carpeta.")
    if item.get("revision_sin_datos") or item.get("estado_imagen") == "revisada_sin_datos":
        raise HTTPException(409, "Esta imagen ya fue confirmada sin texto.")
    ahora = datetime.now().isoformat(timespec="seconds")
    revision = {"estado": "verificada", "usuario": solicitud.usuario, "fecha": ahora}

    # R15.1 (CRÍTICO-01): patch sobre el documento fresco, bajo lock.
    def _verificar_en_fresco(frescos: dict):
        fila_f = next((f for f in frescos.get("resultados", [])
                       if _id_fila(f) == solicitud.prueba_id), None)
        if fila_f is None:
            raise HTTPException(404, "La carpeta indicada no existe.")
        item_f = next((imagen for imagen in fila_f.get("imagenes", [])
                       if imagen.get("id") == solicitud.imagen_id), None)
        if item_f is None:
            raise HTTPException(404, "La imagen indicada no pertenece a la carpeta.")
        if item_f.get("revision_sin_datos") or item_f.get("estado_imagen") == "revisada_sin_datos":
            raise HTTPException(409, "Esta imagen ya fue confirmada sin texto.")
        item_f["estado_imagen"] = "verificada"
        item_f["revision_imagen"] = revision
        if item_f.get("resultado_ocr") is not None:
            item_f["resultado_ocr"]["estado_imagen"] = "verificada"
        for traza in fila_f.get("trazabilidad", []):
            if str(traza.get("ruta_absoluta")) == str(item_f.get("ruta")):
                traza.update({"estado_imagen": "verificada", "requiere_revision": False})

    # R15.5 (HIGH-03): transacción única — el estado de revisión es un efecto
    # externo compensable que se aplica ANTES del commit documental; si algo
    # falla ⇒ restauración verificada (coordinador P0), nunca un documento
    # confirmado con el estado de revisión humano pendiente.
    gestor = GestorAprendizaje(CONFIG)
    # R15.7 (ALTO-02): identidad canónica — la verificación de la imagen es un
    # subrecurso de su CARPETA, así que un bloqueo del caso la detiene (repro
    # del auditor: antes usaba la ruta absoluta y no encontraba `carpeta:<id>`).
    recurso = _recurso_imagen(solicitud.prueba_id, solicitud.imagen_id)
    _assert_recurso_consistente(recurso, "verificar la imagen")
    tx = TransaccionMultiAlmacen("verificación de imagen", recurso=recurso)
    try:
        tx.capturar("estado de revisión",
                    lambda: _capturar_revision_estado(
                        gestor, "carpeta", solicitud.prueba_id),
                    lambda estado: _restaurar_revision_estado(
                        gestor, "carpeta", solicitud.prueba_id, estado))
        gestor.actualizar_revision("carpeta", solicitud.prueba_id, estado="parcial")
        tx.aplicado()
        revision_documento = mutar_documento(
            _verificar_en_fresco, solicitud.expected_revision, estricto=True)[0]
    except BaseException as exc:
        try:
            tx.fallar(exc)
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 — fallo de almacén, compensado
            raise HTTPException(503, (
                "No se pudo actualizar el estado de revisión "
                f"({type(exc).__name__}: {exc}). Los efectos externos fueron "
                "restaurados; la solicitud no produjo efectos "
                "persistentes.")) from exc
    tx.exito()
    # R15.7 (MEDIO-04): TODO lo posterior al commit principal es una tarea
    # AUXILIAR best-effort. Repro del auditor: un RuntimeError en
    # `incorporar_uniones_guardadas` escapaba del endpoint después de que la
    # revisión humana y el documento ya estaban confirmados, convirtiendo un
    # commit exitoso en respuesta de error. Ahora el fallo se reporta como
    # `advertencia_aprendizaje` y la respuesta sigue siendo verificada=true.
    avisos_aprendizaje: list = []
    # V14.12: si esta imagen ya tenía uniones creadas en versiones anteriores,
    # incorporarlas ahora al dataset visual. Es una migración oportunista: no
    # recorremos miles de archivos al arrancar y la firma evita duplicados.
    union_historica = None
    try:
        raiz = _resolver_raiz_datos(datos)
        if raiz is not None:
            ruta_local = _resolver_imagen(str(item.get("ruta") or ""), datos, raiz)
            union_historica = gestor.incorporar_uniones_guardadas(
                ruta_local, _id_fila(fila), item.get("resultado_ocr") or {},
                fase=item.get("fase"), tor=item.get("tor"),
                modelo_origen=(item.get("resultado_ocr") or {}).get("modelo_visual_version")
                or (item.get("resultado_ocr") or {}).get("motor"),
                usuario=solicitud.usuario,
                metadatos={k: fila.get(k) for k in
                           ("tipo_st", "module_version", "temperature_condition", "inflator_type")})
    except Exception as exc:  # noqa: BLE001 — tarea OPCIONAL post-commit
        # Verificar la imagen nunca debe fallar porque una unión histórica no
        # pueda materializarse como recorte entrenable.
        union_historica = None
        avisos_aprendizaje.append(
            "no se pudieron incorporar las uniones guardadas "
            f"({type(exc).__name__}: {exc})")
    auto_visual = None
    try:
        if bool(CONFIG.get("aprendizaje", {}).get("visual", {}).get(
                "auto_entrenar_al_verificar", True)):
            auto_visual = _programar_entrenamiento_visual_auto(
                f"Imagen verificada: {solicitud.prueba_id}/{solicitud.imagen_id}")
    except Exception as exc:  # noqa: BLE001 — tarea OPCIONAL post-commit
        avisos_aprendizaje.append(
            "no se pudo programar el entrenamiento visual automático "
            f"({type(exc).__name__}: {exc})")
        auto_visual = {"programado": False,
                       "error": f"{type(exc).__name__}: {exc}"}
    nuevas_union = int((union_historica or {}).get("nuevas") or 0)
    mensaje_union = (f" Se incorporaron {nuevas_union} muestra(s) de uniones guardadas al entrenamiento."
                     if nuevas_union else "")
    return {"verificada": True, "revision_imagen": revision,
            "revision_documento": revision_documento,
            "aprendizaje_visual_automatico": auto_visual,
            "uniones_historicas_entrenamiento": union_historica,
            "advertencia_aprendizaje": ("; ".join(avisos_aprendizaje) if avisos_aprendizaje
                                        else None),
            "mensaje": "Imagen verificada y marcada en verde." + mensaje_union +
                       " El aprendizaje disponible se aplica de inmediato; el ajuste visual se gestiona automáticamente."}


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
        rotacion_guardada = rotaciones.get(imagen_hash)
        preferida = float((rotacion_guardada or {}).get("grados", 0)) % 360
        aplicada = float(fila.get("rotacion_manual_aplicada_grados") or 0) % 360
        base = _orientacion_base_publica(fila)
        ajuste = float(fila.get("deskew_texto_aplicado_grados") or
                       fila.get("deskew_aplicado_grados") or 0)
        item["rotacion_manual_preferida_grados"] = preferida
        item["rotacion_manual_definida"] = rotacion_guardada is not None
        item["orientacion_texto_base_grados"] = base
        item["rotacion_pendiente"] = abs(preferida - aplicada) >= 0.01
        rotacion_vista = preferida if rotacion_guardada is not None else base
        ajuste_vista = 0.0 if rotacion_guardada is not None else ajuste
        prioridad_aplicada = bool(fila.get("orientacion_manual_prioritaria"))
        rotacion_ocr = aplicada if prioridad_aplicada else (aplicada + base) % 360
        ajuste_ocr = 0.0 if prioridad_aplicada else ajuste
        item["ruta_api_visual"] = (
            f"/api/externas/imagen-orientada/{quote(str(fila['imagen']), safe='')}"
            f"?rotacion={rotacion_vista}&ajuste={ajuste_vista}")
        item["ruta_api_orientada"] = (
            f"/api/externas/imagen-orientada/{quote(str(fila['imagen']), safe='')}"
            f"?rotacion={rotacion_ocr}&ajuste={ajuste_ocr}")
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
    # R15.8 (ALTO-03, auditoría R15.7): recalcular/persistir el banco externo
    # durante MODO RECUPERACIÓN queda expresamente bloqueado (el guard
    # transversal también lo cubre; se declara aquí de forma explícita).
    _assert_sistema_recuperable("evaluar el banco externo")
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
    # R15.8 (ALTO-04, auditoría R15.7): ninguna transición durable de revisión
    # puede ejecutarse sobre un caso que el propio sistema considera
    # inconsistente: guard canónico del recurso antes de tocar almacenes.
    _assert_recurso_consistente(
        _recurso_carpeta(solicitud.item_id) if solicitud.tipo == "carpeta"
        else _recurso_externa(solicitud.item_id),
        "actualizar la revisión")
    # R15.6 (ALTO-10): cerrar la revisión humana como «completada» exige que
    # el caso no pueda estar siendo modificado: sin pipeline activo/reservado
    # y sin reanálisis de videos en curso. El resto de transiciones conserva
    # el comportamiento heredado.
    if solicitud.tipo == "carpeta" and solicitud.estado == "completada":
        _assert_pipeline_inactivo("cerrar la revisión como completada",
                                  incluir_reanalisis=True)
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
    _actualizar_revision_parcial_en_memoria(
        solicitud.tipo, solicitud.item_id, resultado)
    _regenerar_excel(resultado)
    return resultado


@app.post("/api/alertas/atender")
def atender_alerta(solicitud: SolicitudAlerta):
    # R15.8 (MEDIO-05, auditoría R15.7): una anomalía no puede marcarse como
    # atendida (ocultándose) mientras su caso esté formalmente bloqueado.
    _assert_recurso_consistente(
        _recurso_carpeta(solicitud.item_id) if solicitud.tipo == "carpeta"
        else _recurso_externa(solicitud.item_id),
        "atender la alerta")
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
def imagen_externa_orientada(nombre: str, rotacion: float = 0, ajuste: float = 0.0):
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
    fila = _aplicar_correcciones_publicas(fila, gestor.listar_correcciones_texto([fila["ruta"]]))
    unidades = list(fila.get("tokens", [])) + list(fila.get("lineas_texto", []))
    if fila.get("texto_completo"):
        unidades.append({"texto": fila["texto_completo"], "bbox": None,
                         "texto_original": fila.get("texto_completo_original") or fila["texto_completo"]})
    token = _buscar_unidad_ocr(unidades, solicitud.texto_ocr, solicitud.bbox)
    if token is None:
        raise HTTPException(
            400, "La lectura OCR no coincide de forma única; vuelve a seleccionarla.")
    texto_actual = str(token.get("texto") or solicitud.texto_ocr)
    texto_original = str(token.get("texto_original") or texto_actual)
    correcto = texto_actual if solicitud.accion == "aceptar" else solicitud.texto_correcto
    estado_supervision = ("aceptado_provisional" if solicitud.accion == "aceptar"
                          else "corregido_humano" if solicitud.accion in {
                              "corregir", "guardar_sin_entrenar", "confirmar_entrenar"}
                          else solicitud.accion)
    metadatos_supervision = {
        "origen": "externa", "fuente_supervision": "aceptar_ocr"
            if solicitud.accion == "aceptar" else "dashboard_externo",
        "texto_ocr_original": texto_original,
        "texto_lectura_previa": texto_actual,
        "estado_supervision": estado_supervision,
        "bbox_original": token.get("bbox"),
    }
    if solicitud.accion not in {"ilegible", "no_es_campo"} and not correcto.strip():
        raise HTTPException(400, "Escribe el texto correcto antes de confirmar.")

    # R15.6 (MEDIO-06): supervisión externa + estado de revisión en una sola
    # transacción compensable (snapshot común de la imagen cuando existe).
    ruta_efecto = Path(str(fila.get("ruta") or ""))

    def _efectos():
        if solicitud.accion in {"ilegible", "no_es_campo"}:
            muestra = gestor.registrar_muestra_visual(
                fila["ruta"], solicitud.prueba_id, texto_actual, correcto,
                token.get("bbox"), accion=solicitud.accion, entrenable=False,
                confianza=token.get("confianza"), modelo_origen=fila.get("modelo_visual_version")
                or fila.get("motor"), usuario=solicitud.usuario,
                metadatos=metadatos_supervision)
            efecto = {"registrada": True, "tipo": "supervision_visual",
                      "muestra_visual": muestra, "entrenamiento": None}
        else:
            efecto = gestor.registrar_correccion(
                texto_actual, correcto, ruta_imagen=fila["ruta"],
                bbox=token.get("bbox"), fuente="dashboard_externo",
                caso_id=solicitud.prueba_id, accion=solicitud.accion,
                entrenar_visual=True,
                confianza=token.get("confianza"), modelo_origen=fila.get("modelo_visual_version")
                or fila.get("motor"), usuario=solicitud.usuario,
                metadatos=metadatos_supervision)
        gestor.actualizar_revision("externa", solicitud.prueba_id,
                                   estado="parcial")
        return efecto

    resultado = _transaccion_efecto_humano(
        "supervisión de prueba externa", gestor, "externa",
        solicitud.prueba_id, _efectos,
        recurso=_recurso_externa(solicitud.prueba_id),
        ruta_imagen=(ruta_efecto if ruta_efecto.is_file() else None))
    if isinstance(resultado, dict):
        resultado.setdefault("estado_supervision", estado_supervision)
    muestra_confirmada = resultado.get("muestra_visual") if isinstance(resultado, dict) else None
    programador_auto = globals().get("_programar_entrenamiento_visual_auto")
    if (isinstance(muestra_confirmada, dict) and muestra_confirmada.get("entrenable")
            and callable(programador_auto)):
        _aprendizaje_opcional(
            resultado, programador_auto,
            f"Supervisión externa confirmada: {solicitud.prueba_id}")
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
    # R15.6 (MEDIO-06): región externa + estado de revisión en una sola
    # transacción compensable; entrenamiento automático después del éxito.
    def _efectos():
        efecto = gestor.registrar_region(
            solicitud.texto_correcto, solicitud.bbox, ruta_imagen=str(ruta),
            carpeta_id=solicitud.prueba_id, carpeta_nombre="Pruebas complejas",
            imagen_nombre=fila.get("imagen"), fuente="dashboard_externo",
            modelo_origen=fila.get("modelo_visual_version") or fila.get("motor"),
            usuario=solicitud.usuario,
            entrenable=True,
            metadatos={"origen": "externa"})
        gestor.actualizar_revision("externa", solicitud.prueba_id,
                                   estado="parcial")
        return efecto

    resultado = _transaccion_efecto_humano(
        "anotación de región externa", gestor, "externa", solicitud.prueba_id,
        _efectos, recurso=_recurso_externa(solicitud.prueba_id),
        ruta_imagen=ruta)
    if resultado.get("muestra_visual"):
        _aprendizaje_opcional(
            resultado, _programar_entrenamiento_visual_auto,
            f"Región externa confirmada: {solicitud.prueba_id}")
    _regenerar_excel(resultado)
    resultado["estado"] = gestor.estado()
    return resultado


def _resolver_instantanea_para_ejecucion(ejecucion_id: str,
                                         rango: "RangoAperturaSolicitud | None") -> dict:
    """Instantánea de rangos de ESTA ejecución, fijada antes de procesar nada.

    - Reanudación de checkpoint: conserva la instantánea original del mismo
      ``ejecucion_id`` (no cambian los colores a mitad de lote).
    - Diálogo con rangos: registra lo confirmado; guarda preferencia global
      sólo si el usuario lo pidió explícitamente.
    - Sin diálogo: registra la preferencia vigente o los predeterminados 6/7 ms.
    """
    from criterios_usuario import (
        cargar_instantanea_ejecucion,
        criterios_o_predeterminados,
        guardar_criterios_apertura,
        guardar_instantanea_ejecucion,
        reglas_apertura,
    )
    try:
        existente = cargar_instantanea_ejecucion(ejecucion_id)
    except (OSError, ValueError, TypeError):
        existente = None
    if existente:
        return existente
    try:
        if rango is not None:
            # V15.9.1 (A7): «Usar predeterminados» aplica SOLO a esta
            # ejecución y jamás toca la preferencia global, aunque el estado
            # del diálogo trajera guardar_preferencia activo. La semántica es
            # única y explícita; el frontend también lo fuerza.
            if rango.guardar_preferencia and rango.origen != "predeterminado":
                actual = guardar_criterios_apertura(
                    rango.verde_max, rango.amarillo_max, rango.usuario)
                REGLAS.setdefault("criterios", {})["tiempo_apertura_ms"] = reglas_apertura(actual)
            return guardar_instantanea_ejecucion(
                ejecucion_id, verde_max=rango.verde_max, amarillo_max=rango.amarillo_max,
                origen=rango.origen, usuario=rango.usuario)
        vigente = criterios_o_predeterminados()
        return guardar_instantanea_ejecucion(
            ejecucion_id, verde_max=vigente["verde_max"], amarillo_max=vigente["amarillo_max"],
            origen=vigente["origen"], usuario=vigente.get("usuario"))
    except ValueError as exc:
        raise HTTPException(422, f"Los rangos de apertura no son válidos: {exc}") from exc
    except OSError as exc:
        raise HTTPException(503, "No se pudo registrar la instantánea de rangos; no se inicia el procesamiento.") from exc


@app.post("/api/pipeline", status_code=202)
def iniciar_pipeline(solicitud: SolicitudPipeline):
    global _pipeline_hilo, _pipeline_reserva
    # R14: validar primero los criterios declarados. Esto evita hacer trabajo de
    # rutas/plantillas o devolver un error secundario cuando la solicitud ya es
    # inválida por sus límites de semáforo. No persiste nada.
    if solicitud.rango_apertura is not None:
        try:
            validar_limites(
                solicitud.rango_apertura.verde_max,
                solicitud.rango_apertura.amarillo_max,
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, f"Los rangos de apertura no son válidos: {exc}") from exc
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
    if es_raiz_codigo_seleccionada(ruta, RAIZ_PROYECTO):
        raise HTTPException(400, "Seleccionaste la carpeta de V-Matrix (o una carpeta que la contiene) como lote. Elige la carpeta específica que contiene las pruebas, no la carpeta del programa ni un padre que la incluya.")
    try:
        nombre_excel = validar_nombre_excel(solicitud.nombre_excel)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        idiomas_exportacion = _normalizar_idiomas_exportacion(solicitud.idiomas_exportacion)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    ruta_plantilla = (solicitud.ruta_plantilla or "").strip().strip('"\'') or None
    if ruta_plantilla:
        plantilla = Path(ruta_plantilla).expanduser()
        plantilla = ((RAIZ_PROYECTO / plantilla).resolve() if not plantilla.is_absolute()
                     else plantilla.resolve())
        if not plantilla.is_file() or plantilla.suffix.lower() != ".xlsx":
            raise HTTPException(400, "La plantilla debe ser un archivo .xlsx accesible.")
        ruta_plantilla = str(plantilla)
    if solicitud.plantilla_id:
        from plantilla_empresarial import RegistroPlantillas
        if not RegistroPlantillas(CONFIG).obtener(solicitud.plantilla_id):
            raise HTTPException(400, "La plantilla seleccionada no está registrada o disponible.")
    ruta_inventario = (solicitud.ruta_inventario or "").strip().strip('"\'') or None
    if ruta_inventario:
        inventario = Path(ruta_inventario).expanduser()
        inventario = ((RAIZ_PROYECTO / inventario).resolve() if not inventario.is_absolute()
                      else inventario.resolve())
        if solicitud.modo_ejecucion == "reanudar" and not inventario.is_file():
            raise HTTPException(400, "El inventario indicado no existe.")
        ruta_inventario = str(inventario)

    # V15.9.2 (C7): identidad autoritativa del proyecto de esta ejecución.
    # Prioridad: declarado por el usuario (o «Sin asignar» expreso) > config
    # empresarial legacy > nombre de carpeta (legacy, siempre pendiente).
    # La plantilla Excel NUNCA aporta identidad: sólo contrato de formato.
    from utilidades import proyectos as registro_proyectos
    from utilidades.identidad import resolver_identidad_proyecto
    proyecto_declarado = None
    if solicitud.proyecto is not None:
        proyecto_declarado = {
            "nombre_proyecto": (solicitud.proyecto.nombre_proyecto or "").strip() or None,
            "proyecto_id": (solicitud.proyecto.proyecto_id or "").strip().lower() or None,
            "sin_asignar": bool(solicitud.proyecto.sin_asignar),
            "usuario": solicitud.proyecto.usuario,
            "migracion_explicita": bool(solicitud.proyecto.migracion_explicita),
        }
        if (not proyecto_declarado["sin_asignar"]
                and not proyecto_declarado["nombre_proyecto"]
                and not proyecto_declarado["proyecto_id"]):
            raise HTTPException(
                400, "Declara el proyecto al que pertenecen las pruebas (nombre "
                "visible) o elige expresamente «Sin asignar»; nunca se toma de "
                "la plantilla, la carpeta ni la corrida anterior.")
        # P04: reanudar conserva el proyecto del checkpoint; cambiarlo exige
        # migración explícita.
        previa = ((_pipeline_estado.get("solicitud") or {}).get("proyecto_ejecucion")
                  or {})
        if (solicitud.modo_ejecucion == "reanudar" and previa.get("project_id")
                and not proyecto_declarado["migracion_explicita"]):
            nueva_pid = resolver_identidad_proyecto(
                declarado=proyecto_declarado, raiz=ruta)["project_id"]
            if nueva_pid != previa["project_id"]:
                raise HTTPException(
                    409, f"El checkpoint pertenece al proyecto «{previa.get('nombre_proyecto') or previa['project_id']}». "
                    f"Reanudar con «{nueva_pid}» exige una migración explícita "
                    "(con historial y respaldo); no se acepta en silencio.")
        # R15 (MEDIA-15): el registro persistente del proyecto se trasladó
        # DESPUÉS de la admisión atómica del slot (más abajo): una solicitud
        # que será rechazada (409) no debe dejar efectos persistentes.
    identidad_proyecto = resolver_identidad_proyecto(
        declarado=proyecto_declarado, raiz=ruta,
        configurado=(CONFIG.get("empresarial") or {}).get("proyecto_id"))
    proyecto_ejecucion = {**identidad_proyecto,
                          "fecha": datetime.now().isoformat(timespec="seconds")}

    capacidad = _capacidad_pipeline()
    if not capacidad["listo"]:
        raise HTTPException(503, {"mensaje": "El entorno OCR no está listo.", **capacidad})

    with _pipeline_lock, _video_reanalisis_lock:
        # R15 (CRIT-01): admisión ATÓMICA del único slot de worker. La reserva
        # se adquiere en la misma sección crítica que cambia el estado; antes
        # se comprobaba is_alive() y el hilo se asignaba después de persistir
        # el checkpoint, dejando una ventana de doble arranque. Orden de locks
        # pipeline→reanálisis, el mismo que /api/video/maximo (sin inversión).
        if _pipeline_hilo is not None and _pipeline_hilo.is_alive():
            # Mensaje V14 conservado: hilo anterior vivo cerrando recursos.
            raise HTTPException(409, "El procesamiento anterior todavía está cerrando recursos; vuelve a intentar cuando termine.")
        if _pipeline_reserva is not None:
            raise HTTPException(409, "Ya hay un procesamiento admitido (reserva en curso); vuelve a intentar cuando termine.")
        if _video_reanalisis_hilo is not None and _video_reanalisis_hilo.is_alive():
            raise HTTPException(409, "Hay un reanálisis de videos en curso; termínalo antes de iniciar un procesamiento.")
        estado_anterior = deepcopy(_pipeline_estado)
        ejecucion_id = str(solicitud.ejecucion_id or uuid.uuid4().hex)
        _pipeline_reserva = {
            "ejecucion_id": ejecucion_id, "origen": "pipeline",
            "reservado_en": datetime.now().isoformat(timespec="milliseconds")}
        # Un estado cancelando/pausado persistido sin hilo vivo es un checkpoint,
        # no un proceso real. V14 permite iniciar de nuevo sin borrar cachés.
        if _pipeline_estado["estado"] == "reanudando" and (
                str(solicitud.ejecucion_id or "") != str(_pipeline_estado.get("ejecucion_id") or "")):
            _pipeline_estado.update(estado="detenido_con_avance", reanudable=True)
        _pipeline_continuar.set()
        _pipeline_cancelar.clear()
        _pipeline_detener_fin_id.clear()
        proyecto_ejecucion["ejecucion_id"] = ejecucion_id
        # V15.9: la instantánea de rangos se fija ANTES de cualquier trabajo y
        # explica el semáforo de esta ejecución. Si el usuario marcó «Guardar
        # para próximas carpetas», además se persiste como preferencia.
        try:
            instantanea = _resolver_instantanea_para_ejecucion(ejecucion_id, solicitud.rango_apertura)
        except BaseException:
            _pipeline_reserva = None   # R15: no dejar reserva colgada si falla
            raise
        es_reanudacion_checkpoint = (
            _pipeline_estado.get("estado") == "reanudando" and
            str(_pipeline_estado.get("ejecucion_id") or "") == ejecucion_id
        )
        transcurrido_previo = (float(_pipeline_estado.get("transcurrido_segundos") or 0.0)
                               if es_reanudacion_checkpoint else 0.0)
        inicio_original = (_pipeline_estado.get("iniciado_en")
                           if es_reanudacion_checkpoint and _pipeline_estado.get("iniciado_en")
                           else datetime.now().isoformat(timespec="seconds"))
        ahora_segmento = datetime.now().isoformat(timespec="milliseconds")
        perfil_rendimiento = normalizar_perfil(solicitud.perfil_rendimiento)
        try:
            obtener_gestor_recursos(perfil_rendimiento).configurar(perfil_rendimiento)
            metricas_iniciales = obtener_gestor_recursos(perfil_rendimiento).snapshot(forzar=True)
        except BaseException:
            _pipeline_reserva = None   # R15: no dejar reserva colgada si falla
            raise
        solicitud_guardada = {
            "ruta": str(ruta), "nombre_excel": nombre_excel,
            "sobrescribir_excel": solicitud.sobrescribir_excel,
            "tipo_st": solicitud.tipo_st, "plantilla_id": solicitud.plantilla_id,
            "modo_ejecucion": solicitud.modo_ejecucion,
            "idiomas_exportacion": idiomas_exportacion,
            "casos_omitidos": list(solicitud.casos_omitidos),
            "ejecucion_id": ejecucion_id,
            "perfil_rendimiento": perfil_rendimiento,
            "contenido": solicitud.contenido,
            "criterios_apertura": dict(instantanea),
            # C7: el checkpoint guarda la identidad autoritativa (P04/P09).
            "proyecto": proyecto_declarado,
            "proyecto_ejecucion": dict(proyecto_ejecucion),
        }
        _pipeline_estado.update({
            "estado": "procesando", "fase": "preparando",
            "mensaje": "Preparando el pipeline", "ruta": str(ruta),
            "iniciado_en": inicio_original,
            "finalizado_en": None, "error": None, "resumen": None, "bitacora": None,
            "porcentaje": 0, "procesadas": 0, "total": 0, "restantes": 0,
            "eta_segundos": None, "transcurrido_segundos": transcurrido_previo,
            "transcurrido_base_segundos": transcurrido_previo,
            "segmento_activo_iniciado_en": ahora_segmento, "pausado_en": None,
            "resultados_parciales": [], "imagenes_procesadas": 0,
            "imagenes_total": 0, "imagenes_restantes": 0,
            "imagen_actual": None,
            "recursos": capacidad.get("recursos"), "nombre_excel": nombre_excel,
            "perfil_rendimiento": perfil_rendimiento, "contenido": solicitud.contenido,
            "metricas_recursos": metricas_iniciales,
            "idiomas_exportacion": idiomas_exportacion, "archivos_excel": {},
            "archivos_excel_parcial": {},
            "archivos_excel_borrador": {}, "archivos_excel_parcial_borrador": {},
            "tipo_st": solicitud.tipo_st, "ruta_plantilla": ruta_plantilla,
            "plantilla_id": solicitud.plantilla_id,
            "modo_ejecucion": solicitud.modo_ejecucion,
            "ruta_inventario": ruta_inventario,
            "ultimo_id": None, "ultimo_id_nombre": None,
            "reanudable": False, "solicitud": solicitud_guardada,
            "ejecucion_id": ejecucion_id,
            "proyecto_ejecucion": dict(proyecto_ejecucion),
            "archivo_excel_parcial": None, "excel_parcial_actualizado_en": None,
            "advertencia_excel_parcial": None, "excel_parcial_pendiente": False,
            "advertencias_cache": [],
            "actualizado_en": datetime.now().isoformat(timespec="milliseconds"),
        })
    # R15 (MEDIA-15): el registro persistente del proyecto ocurre solo DESPUÉS
    # de la admisión atómica del slot. Si el registro falla, la admisión se
    # revierte (rollback) y no queda un «procesando fantasma» ni reserva colgada.
    if proyecto_declarado is not None and not proyecto_declarado["sin_asignar"]:
        try:
            # P12: colisión de ID con nombre distinto ⇒ 409, sin fusión.
            registro_proyectos.registrar_proyecto(
                proyecto_declarado["nombre_proyecto"]
                or proyecto_declarado["proyecto_id"],
                proyecto_id=proyecto_declarado["proyecto_id"],
                responsable=proyecto_declarado["usuario"])
        except registro_proyectos.ColisionProyectoError as exc:
            _rollback_admision_pipeline(estado_anterior)
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            _rollback_admision_pipeline(estado_anterior)
            raise HTTPException(400, str(exc)) from exc
        except registro_proyectos.RegistroProyectosCorruptoError as exc:
            # CRIT-04: fallar cerrado ANTES de procesar; el registro no se
            # toca (cero bytes modificados) y el error es visible.
            _rollback_admision_pipeline(estado_anterior)
            raise HTTPException(503, f"Registro de proyectos ilegible: {exc}") from exc
        except registro_proyectos.ErrorPersistenciaProyectos as exc:
            _rollback_admision_pipeline(estado_anterior)
            raise HTTPException(503, f"El proyecto no se registró: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — fallo no previsto del registro
            _rollback_admision_pipeline(estado_anterior)
            raise HTTPException(503, f"El proyecto no se registró: {exc}") from exc

    try:
        _persistir_checkpoint_pipeline()
    except BaseException:
        # R15: no admitir un procesamiento cuyo checkpoint no se pudo persistir
        # (persistencia atómica verificada); la admisión se revierte.
        _rollback_admision_pipeline(estado_anterior)
        raise

    hilo_pipeline = threading.Thread(target=_ejecutar_pipeline_fondo, kwargs={
        "ruta": ruta, "nombre_excel": nombre_excel,
        "sobrescribir_excel": solicitud.sobrescribir_excel,
        "tipo_st": solicitud.tipo_st, "ruta_plantilla": ruta_plantilla,
        "plantilla_id": solicitud.plantilla_id,
        "casos_omitidos": set(solicitud.casos_omitidos),
        "modo_ejecucion": solicitud.modo_ejecucion,
        "ruta_inventario": ruta_inventario,
        "idiomas_exportacion": idiomas_exportacion,
        "ejecucion_id": ejecucion_id,
        "perfil_rendimiento": perfil_rendimiento,
        "contenido": solicitud.contenido,
        "criterios_apertura": dict(instantanea),
        "proyecto": proyecto_declarado,
    }, daemon=True)
    # R15 (CRIT-01): se asigna el slot global mientras la reserva sigue activa
    # (is_alive() de un hilo no arrancado es False; la reserva cierra ese hueco)
    # y se libera solo tras un arranque verificado. Si start() falla, rollback
    # completo: estado anterior + slot libre + checkpoint repersistido.
    with _pipeline_lock:
        _pipeline_hilo = hilo_pipeline
    try:
        hilo_pipeline.start()
    except BaseException as exc:  # noqa: BLE001 — rollback + 500 explícito
        _rollback_admision_pipeline(estado_anterior, hilo_fallido=hilo_pipeline)
        raise HTTPException(500, f"No se pudo iniciar el worker de procesamiento: {exc}") from exc
    with _pipeline_lock:
        if (_pipeline_reserva is not None
                and _pipeline_reserva.get("ejecucion_id") == ejecucion_id):
            _pipeline_reserva = None
    # Trazabilidad C7: la ejecución queda anotada en el registro de proyectos.
    advertencia_registro = None
    try:
        registro_proyectos.registrar_ejecucion(
            identidad_proyecto["project_id"], ejecucion_id,
            responsable=identidad_proyecto.get("responsable"))
    except Exception as exc:  # noqa: BLE001 — no aborta una ejecución válida
        advertencia_registro = f"Proyecto no anotado en el registro: {exc}"
    respuesta = {"aceptado": True, "ruta": str(ruta), "estado": "procesando",
                 "criterios_apertura": dict(instantanea),
                 "proyecto_ejecucion": dict(proyecto_ejecucion)}
    if advertencia_registro:
        respuesta["advertencia_registro_proyecto"] = advertencia_registro
    return respuesta


@app.post("/api/pipeline/pausar")
def pausar_pipeline():
    with _pipeline_lock:
        if _pipeline_estado["estado"] != "procesando":
            raise HTTPException(409, "No hay un procesamiento activo que se pueda pausar.")
        _pipeline_continuar.clear()
        _pipeline_estado.update(
            estado="pausando", mensaje="Pausa solicitada; se detendrá al terminar la imagen actual",
            eta_segundos=None, reanudable=True, excel_parcial_pendiente=True,
            actualizado_en=datetime.now().isoformat(timespec="milliseconds"))
    _persistir_checkpoint_pipeline()
    return {"estado": "pausando", "seguro": True}


def _caso_realmente_completado_para_reanudar(item: dict) -> bool:
    """Distingue resultados terminados de filas sólo descubiertas/inventariadas.

    La Fase A publica todos los casos con estados como ``detectada`` o
    ``inventariada``. Esas filas NO son avance OCR completado y nunca deben
    convertirse en ``casos_omitidos`` al reconstruir un checkpoint.
    """
    if not isinstance(item, dict):
        return False
    estado = str(item.get("estado") or "").strip().lower()
    if estado in {
        "procesando", "cancelada", "detectada", "inventariada",
        "estructura_incompleta", "pendiente", "pausada", "pausado",
        "sin_procesar", "error", "fallido",
    }:
        return False
    if estado in {"procesada", "procesada_con_advertencias", "con_conflictos", "completado"}:
        return True

    # Compatibilidad con el flujo legacy: las filas completas históricas no
    # siempre llevan ``estado``, pero sí un resultado de comparación definitivo.
    resultado = str(item.get("resultado") or "").strip().lower()
    if resultado in {"coincidencia_total", "coincidencia_parcial", "discrepancia"}:
        return True
    return False


@app.post("/api/pipeline/reanudar")
def reanudar_pipeline():
    global _pipeline_hilo
    reiniciar = None
    parciales_guardados = []
    ultimo_guardado = (None, None)
    with _pipeline_lock:
        if _pipeline_estado["estado"] not in {"pausado", "detenido_con_avance"}:
            raise HTTPException(409, "No existe un avance pausado que se pueda reanudar.")
        hilo_vivo = bool(_pipeline_hilo and _pipeline_hilo.is_alive())
        if hilo_vivo and _pipeline_estado["estado"] == "pausado":
            # Publicar la revisión antes de despertar al hilo OCR.
            _esperar_continuacion.revision_conocimiento = getattr(
                _esperar_continuacion, "revision_conocimiento", 0) + 1
            _reanudar_tiempo_pipeline_locked()
            _pipeline_continuar.set()
            _pipeline_estado.update(
                estado="procesando", mensaje="Procesamiento reanudado",
                actualizado_en=datetime.now().isoformat(timespec="milliseconds"))
        else:
            reiniciar = deepcopy(_pipeline_estado.get("solicitud"))
            if not reiniciar:
                raise HTTPException(409, "El checkpoint no conserva los datos necesarios para reanudar.")
            parciales_guardados = deepcopy(_pipeline_estado.get("resultados_parciales") or [])
            # ``casos_omitidos`` es un campo interno de recuperación. V14.1 pudo
            # contaminarlo con casos meramente detectados; por eso al recuperar
            # un checkpoint se reconstruye desde evidencia actual en vez de
            # heredar esa lista. Así también se reparan checkpoints ya afectados.
            omitidos = {
                str(item.get("case_key") or item.get("ruta"))
                for item in parciales_guardados
                if (item.get("case_key") or item.get("ruta")) and
                _caso_realmente_completado_para_reanudar(item)
            }
            reiniciar["casos_omitidos"] = sorted(omitidos)
            reiniciar["ejecucion_id"] = str(
                reiniciar.get("ejecucion_id") or _pipeline_estado.get("ejecucion_id") or uuid.uuid4().hex)
            _pipeline_estado["ejecucion_id"] = reiniciar["ejecucion_id"]
            ultimo_guardado = (_pipeline_estado.get("ultimo_id"),
                               _pipeline_estado.get("ultimo_id_nombre"))
            # V13: reserva atómica de la reanudación. Un segundo clic/request
            # ya no puede lanzar un segundo hilo sobre el mismo checkpoint.
            _pipeline_estado.update(
                estado="reanudando",
                mensaje="Recuperando la ejecución guardada",
                actualizado_en=datetime.now().isoformat(timespec="milliseconds"))
    if reiniciar:
        respuesta = iniciar_pipeline(SolicitudPipeline(**reiniciar))
        with _pipeline_lock:
            actuales = {item.get("id"): item for item in
                        _pipeline_estado.get("resultados_parciales", [])}
            for item in parciales_guardados:
                actuales.setdefault(item.get("id"), item)
            _pipeline_estado["resultados_parciales"] = list(actuales.values())
            if not _pipeline_estado.get("ultimo_id"):
                _pipeline_estado["ultimo_id"], _pipeline_estado["ultimo_id_nombre"] = ultimo_guardado
        _persistir_checkpoint_pipeline()
        respuesta["desde_checkpoint"] = True
        return respuesta
    _persistir_checkpoint_pipeline()
    return {"estado": "procesando"}


@app.post("/api/pipeline/cancelar")
def cancelar_pipeline(solicitud: SolicitudDetencion | None = None):
    solicitud = solicitud or SolicitudDetencion()
    with _pipeline_lock:
        if _pipeline_estado["estado"] not in {"procesando", "pausando", "pausado"}:
            raise HTTPException(409, "No hay un procesamiento activo que detener.")
        if _pipeline_estado["estado"] == "pausado":
            # La espera previa permanece excluida; desde la orden de detener sí
            # vuelve a correr el reloj mientras se cierran de forma cooperativa.
            _reanudar_tiempo_pipeline_locked()
        if solicitud.accion == "fin_id":
            _pipeline_detener_fin_id.set()
            _pipeline_continuar.set()
            mensaje = "Se detendrá al finalizar la carpeta/ID actual y conservará el avance"
        else:
            _pipeline_cancelar.set()
            _pipeline_continuar.set()
            mensaje = "Se detendrá al finalizar la imagen actual y conservará el avance"
        _pipeline_estado.update(
            estado="cancelando", mensaje=mensaje, reanudable=True,
            excel_parcial_pendiente=True,
            actualizado_en=datetime.now().isoformat(timespec="milliseconds"))
    _persistir_checkpoint_pipeline()
    return {"estado": "cancelando", "seguro": True, "accion": solicitud.accion}


@app.get("/api/resumen")
def resumen():
    """Resumen coherente con la ejecución vigente.

    R11: mientras el pipeline está activo/pausado/reanudando, el resumen usa
    EXCLUSIVAMENTE ``resultados_parciales`` de esa ejecución. Nunca mezcla
    colores ni IDs del resultado final de una corrida anterior. Los casos aún
    no analizados se cuentan como ``pendiente`` y no como gris definitivo.
    """
    with _pipeline_lock:
        estado_pipeline = str(_pipeline_estado.get("estado") or "inactivo")
        parciales = [dict(f) for f in _pipeline_estado.get("resultados_parciales", [])
                     if isinstance(f, dict) and f.get("origen") == "carpeta"]
        total_pipeline = int(_pipeline_estado.get("total") or 0)
        procesadas_pipeline = int(_pipeline_estado.get("procesadas") or 0)
        ejecucion_id = _pipeline_estado.get("ejecucion_id")
        ruta_pipeline = _pipeline_estado.get("ruta")
        actualizado_pipeline = _pipeline_estado.get("actualizado_en")

    estados_en_vivo = {"procesando", "pausando", "pausado", "cancelando", "reanudando"}
    en_vivo = estado_pipeline in estados_en_vivo

    if en_vivo:
        # Los parciales ya son filas públicas creadas por ``progreso``. Se
        # copian/etiquetan, pero NO se vuelven a pasar por _fila_publica.
        filas = parciales
        for f in filas:
            # R12: el avance real no se deduce sólo de ``resultado``. La fase de
            # inventario puede crear una fila pública con metadatos/semáforo OCR
            # antes de que OCR/video hayan terminado. Sólo los estados realmente
            # finales dejan de ser azules.
            completada = _caso_realmente_completado_para_reanudar(f)
            f["pipeline_completada"] = bool(completada)
            f["pipeline_pendiente"] = not completada
            f["pipeline_ejecucion_id"] = ejecucion_id
        datos = None
    else:
        datos = _cargar_datos()
        if not datos:
            raise HTTPException(404, "Sin datos procesados. Ejecuta primero el pipeline.")
        filas = [_fila_publica(f) for f in datos["resultados"]]

    procesadas = [f for f in filas if (
        _caso_realmente_completado_para_reanudar(f) if en_vivo
        else f.get("resultado") != "sin_procesar"
    )]
    n = len(procesadas)
    # Durante la ejecución, ``total`` puede conocerse antes de tener una fila
    # parcial para cada caso. Nunca se reutiliza el total de una corrida vieja.
    total_visible = max(len(filas), total_pipeline if en_vivo else len(filas))
    pendientes_pipeline = (max(0, total_visible - n) if en_vivo else 0)

    conteo = {"verde": 0, "amarillo": 0, "rojo": 0, "sin_clasificar": 0}
    conteo_apertura = {"verde": 0, "amarillo": 0, "rojo": 0,
                       "sin_clasificar": 0, "pendiente": 0}
    confianzas = []
    por_lote: dict[str, dict] = {}
    por_lote_apertura: dict[str, dict] = {}
    pendientes_visibles = 0
    calidad_decision = {
        "confirmada": 0, "estimada_automatica": 0,
        "abstencion": 0, "pendiente": 0,
    }

    for f in filas:
        clave = f.get("semaforo") or "sin_clasificar"
        conteo[clave] = conteo.get(clave, 0) + 1
        lote = f.get("lote") or "sin_lote"
        bucket = por_lote.setdefault(lote, {"verde": 0, "amarillo": 0, "rojo": 0,
                                            "sin_clasificar": 0, "total": 0})
        bucket[clave] = bucket.get(clave, 0) + 1
        bucket["total"] += 1

        if en_vivo and f.get("pipeline_pendiente"):
            clave_apertura = "pendiente"
            pendientes_visibles += 1
            calidad_decision["pendiente"] += 1
        else:
            clave_apertura = f.get("semaforo_apertura") or "sin_clasificar"
            if clave_apertura == "gris":
                clave_apertura = "sin_clasificar"
            canon = f.get("resultado_caso_canonico") if isinstance(f.get("resultado_caso_canonico"), dict) else {}
            apertura = canon.get("apertura") if isinstance(canon.get("apertura"), dict) else {}
            decision = str(apertura.get("estado") or "")
            if decision in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"}:
                calidad_decision["confirmada"] += 1
            elif apertura.get("auto_color_elegible") is True and clave_apertura in {"verde", "amarillo", "rojo"}:
                calidad_decision["estimada_automatica"] += 1
            else:
                calidad_decision["abstencion"] += 1
        conteo_apertura[clave_apertura] = conteo_apertura.get(clave_apertura, 0) + 1
        bucket_a = por_lote_apertura.setdefault(
            lote, {"verde": 0, "amarillo": 0, "rojo": 0,
                   "sin_clasificar": 0, "pendiente": 0, "total": 0})
        bucket_a[clave_apertura] = bucket_a.get(clave_apertura, 0) + 1
        bucket_a["total"] += 1
        if f.get("confianza_ocr_pct") is not None:
            confianzas.append(f["confianza_ocr_pct"])

    # Casos descubiertos por inventario que todavía no tienen fila parcial.
    pendientes_no_visibles = max(0, pendientes_pipeline - pendientes_visibles)
    if pendientes_no_visibles:
        conteo_apertura["pendiente"] += pendientes_no_visibles
        calidad_decision["pendiente"] += pendientes_no_visibles

    return {
        "total_carpetas": total_visible,
        "total_procesadas": n,
        "total_parciales_visibles": len(filas),
        "pendientes_pipeline": pendientes_pipeline,
        "pendientes_sin_fila": pendientes_no_visibles,
        "resumen_en_vivo": en_vivo,
        "estado_pipeline": estado_pipeline,
        "ejecucion_id": ejecucion_id if en_vivo else None,
        "semaforo": conteo,
        "pct": {k: round(100 * v / len(filas), 1) for k, v in conteo.items()} if filas else {},
        "semaforo_apertura": conteo_apertura,
        "calidad_decision_apertura": calidad_decision,
        "pct_apertura": {k: round(100 * v / total_visible, 1)
                         for k, v in conteo_apertura.items()} if total_visible else {},
        "confianza_promedio": round(sum(confianzas) / len(confianzas), 1) if confianzas else None,
        "distribucion_por_lote": por_lote,
        "distribucion_apertura_por_lote": por_lote_apertura,
        "matriz_apertura": _matriz_apertura(filas),
        "generado_en": (actualizado_pipeline if en_vivo else datos.get("generado_en")),
        "raiz": (ruta_pipeline if en_vivo else _raiz_publica(datos)),
        "raiz_origen": (ruta_pipeline if en_vivo else datos.get("raiz")),
    }


def _revision_vigente_en_fila_publica(fila_publica: dict, revisiones: dict) -> dict:
    """Devuelve una copia con la revisión persistida vigente.

    Los resultados parciales del pipeline son una instantánea y pueden conservar un
    estado de revisión anterior. La revisión guardada por el usuario siempre debe
    prevalecer en el Listado.
    """
    salida = dict(fila_publica)
    item_id = salida.get("id")
    if item_id:
        vigente = revisiones.get(("carpeta", item_id))
        if vigente is not None:
            salida["revision"] = dict(vigente)
    return salida


def _actualizar_revision_parcial_en_memoria(tipo: str, item_id: str, revision: dict) -> None:
    """Sincroniza la caché de resultados parciales tras una revisión manual."""
    if tipo != "carpeta":
        return
    with _pipeline_lock:
        for fila in _pipeline_estado.get("resultados_parciales", []):
            if fila.get("id") == item_id:
                fila["revision"] = dict(revision)


@app.get("/api/pruebas")
def pruebas(q: str = "", estado: str = "", limit: int = Query(200, ge=1, le=1000),
            offset: int = Query(0, ge=0), incluir_ocultos: bool = False):
    datos = _cargar_datos()
    with _pipeline_lock:
        parciales = [dict(f) for f in _pipeline_estado.get("resultados_parciales", [])]
        estado_pipeline = _pipeline_estado.get("estado")
        ejecucion_ckpt = _pipeline_estado.get("ejecucion_id")
        progreso_ckpt = _pipeline_estado.get("porcentaje")
    if not datos and not parciales:
        raise HTTPException(404, "Sin datos procesados.")
    # R15.4 (MEDIUM-03): los parciales de un checkpoint sólo son vista válida
    # cuando el pipeline está realmente en curso/recuperable. Un checkpoint
    # histórico (p. ej. 'completado') con documento oficial AUSENTE no puede
    # presentarse como resultado actual: estado claro de recuperación.
    checkpoint_vigente = estado_pipeline in _ESTADOS_CHECKPOINT_VIGENTE
    fuente = "documento"
    if not datos:
        if not checkpoint_vigente:
            raise HTTPException(503, (
                "El documento oficial de resultados "
                "(validacion_resultados.json) no existe. Se conserva un "
                f"checkpoint de una corrida en estado "
                f"'{estado_pipeline or 'desconocido'}' (ejecución "
                f"{ejecucion_ckpt or 'sin id'}, progreso {progreso_ckpt or 0}%). "
                "Esos resultados parciales NO se muestran como actuales: "
                "reprocesa el lote o restaura el documento oficial."))
        fuente = "checkpoint_recuperacion"
    revisiones = GestorAprendizaje(CONFIG).listar_revisiones()
    atendidas = GestorAprendizaje(CONFIG).listar_alertas_atendidas()
    filas = [_fila_publica(f, revisiones, atendidas) for f in (datos or {}).get("resultados", [])]
    por_id = {f["id"]: f for f in filas}
    if checkpoint_vigente:
        for parcial in parciales:
            if parcial.get("origen") == "carpeta":
                # El parcial puede haberse creado antes de que el usuario cambiara la
                # revisión. Nunca debe tapar una revisión persistida más reciente.
                publicada = _revision_vigente_en_fila_publica(parcial, revisiones)
                if fuente == "checkpoint_recuperacion":
                    publicada = {**publicada, "fuente": "checkpoint_recuperacion"}
                por_id[parcial["id"]] = publicada
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
            "incluye_externas": True,
            # R15.4 (MEDIUM-03): fuente explícita de la vista para que el
            # frontend comunique cuándo está mostrando una recuperación.
            "fuente": fuente,
            # R15.2 (ALTO-04): la UI necesita la revisión vigente para enviar
            # expected_revision en cada mutación (CAS estricto).
            "revision_documento": int((datos or {}).get("revision_documento") or 0)}


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


@app.get("/api/pipeline/excel-parcial")
def descargar_excel_parcial(idioma: str = ""):
    with _pipeline_lock:
        codigo = str(idioma or "").lower().strip()
        declarada = ((_pipeline_estado.get("archivos_excel_parcial") or {}).get(codigo)
                     if codigo else _pipeline_estado.get("archivo_excel_parcial"))
    if not declarada:
        raise HTTPException(404, "Todavía no se ha generado un Excel parcial.")
    archivo = Path(declarada).resolve()
    if not archivo.is_relative_to(RAIZ_PROYECTO.resolve()) or not archivo.is_file():
        raise HTTPException(404, "El Excel parcial ya no está disponible.")
    return FileResponse(archivo, filename=archivo.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/pipeline/borrador-parcial")
def descargar_borrador_parcial(idioma: str = ""):
    """V15.9.4 (ALTA-N6): descarga diferenciada del borrador NO publicable."""
    with _pipeline_lock:
        codigo = str(idioma or "").lower().strip()
        borradores = dict(_pipeline_estado.get("archivos_excel_parcial_borrador") or {})
        declarada = borradores.get(codigo) if codigo else next(iter(borradores.values()), None)
    if not declarada:
        raise HTTPException(404, "No hay ningún borrador bloqueado generado.")
    archivo = Path(declarada).resolve()
    from utilidades.identidad_excel import es_borrador_no_publicable
    if (not archivo.is_relative_to(RAIZ_PROYECTO.resolve()) or not archivo.is_file()
            or not es_borrador_no_publicable(archivo)):
        raise HTTPException(404, "El borrador ya no está disponible.")
    return FileResponse(archivo, filename=archivo.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/casos")
def casos(q: str = "", estado: str = "", limit: int = Query(500, ge=1, le=1000),
          offset: int = Query(0, ge=0)):
    respuesta = pruebas(q=q, estado=estado, limit=1000, offset=0)
    items = [item for item in respuesta["items"] if item.get("origen") == "carpeta"]
    return {"total": len(items), "items": items[offset:offset + limit]}


@app.post("/api/resultados/exportar")
def exportar_resultados(solicitud: SolicitudExportacion):
    """Exporta ES/EN/DE desde una misma instantánea, sin repetir OCR."""
    permitidos={"es":"ES","en":"EN","de":"DE"}; idiomas=[]
    for idioma in solicitud.idiomas:
        idioma=str(idioma).lower().strip()
        if idioma not in permitidos: raise HTTPException(400,f"Idioma no soportado: {idioma}")
        if idioma not in idiomas: idiomas.append(idioma)
    datos=deepcopy(_cargar_datos() or {})
    if not datos.get("resultados"): raise HTTPException(404,"No hay resultados procesados para exportar.")
    # V15.9.5 (ALTA-N9): la decisión «Sin asignar» publica como PENDIENTE con
    # estado diferenciado; jamás como identidad de proyecto verificada.
    proyecto_ejecucion=datos.get("proyecto_ejecucion") or {}
    pendiente_sin_asignar=bool(proyecto_ejecucion.get("sin_asignar"))
    base=Path(datos.get("nombre_excel_base") or datos.get("archivo_excel") or (RAIZ_PROYECTO / CONFIG.get("fase3",{}).get("archivo_salida","resultado_maestro.xlsx")))
    if not base.is_absolute(): base=RAIZ_PROYECTO/base
    generados=[]
    # V15.9: el libro usa el mismo criterio que muestra la matriz ahora mismo
    # (cambio posterior confirmado > instantánea de la ejecución) y lo declara.
    verde_c, amarillo_c, origen_c, instantanea_c = _limites_apertura_efectivos()
    criterios_usados = {"verde_max": verde_c, "amarillo_max": amarillo_c, "origen": origen_c}
    bloqueados=[]
    for idioma in idiomas:
        destino=base.with_name(f"{base.stem}_{permitidos[idioma]}.xlsx")
        try:
            generado=_generar_excel_serializado(RUTA_VALIDACION,destino,CONFIG,REGLAS,ruta_plantilla=datos.get("ruta_plantilla"),datos_validacion=datos,idioma=idioma,criterios_apertura=criterios_usados)
        except PermissionError as exc: raise HTTPException(423,str(exc)) from exc
        # V15.9.4 (ALTA-N6): un borrador bloqueado por identidad NO es una
        # exportación oficial: no entra en ``generados`` ni en sus URLs; se
        # lista aparte como diagnóstico etiquetado con su propia ruta.
        from utilidades.identidad_excel import es_borrador_no_publicable
        ruta_generada=Path(generado)
        if es_borrador_no_publicable(ruta_generada):
            bloqueados.append({"idioma":idioma,"nombre":ruta_generada.name,
                               "estado_publicacion":"bloqueada",
                               "motivo":("Identidad del proyecto no verificable en la "
                                         "plantilla (celda de proyecto ausente o título "
                                         "contradictorio). El Excel oficial NO se publicó."),
                               "ruta_borrador":str(ruta_generada),
                               "url_borrador":f"/api/resultados/borrador?archivo={quote(ruta_generada.name)}"})
            continue
        generados.append({"idioma":idioma,"nombre":ruta_generada.name,"url":f"/api/resultados/exportado?archivo={quote(ruta_generada.name)}",
                          "estado_identidad":("pendiente_sin_asignar" if pendiente_sin_asignar else "verificada")})
    return {"generados":generados,"instantanea":datos.get("generado_en"),"reutilizo_ocr":True,
            "publicable":bool(generados) and not bloqueados,
            "identidad_verificada":bool(generados) and not bloqueados and not pendiente_sin_asignar,
            "pendiente_sin_asignar":pendiente_sin_asignar and bool(generados),
            "estado_publicacion":("pendiente_publicada" if generados and not bloqueados and pendiente_sin_asignar
                                  else "publicada" if generados and not bloqueados
                                  else "bloqueada" if bloqueados and not generados
                                  else "parcial_bloqueada" if bloqueados else "sin_salida"),
            "bloqueados":bloqueados,
            "criterios_usados":criterios_usados,
            "nota_criterios": ("Se aplicó el cambio posterior confirmado en Resumen."
                               if origen_c == "cambio_posterior_confirmado" else
                               "Se aplicaron los criterios de la ejecución que produjo estos resultados."
                               if instantanea_c else
                               "Se aplicaron los criterios vigentes (sin instantánea de ejecución previa).")}


@app.get("/api/resultados/exportado")
def descargar_exportado(archivo: str):
    nombre=Path(unquote(archivo)).name; datos=_cargar_datos() or {}
    base=Path(datos.get("nombre_excel_base") or datos.get("archivo_excel") or (RAIZ_PROYECTO / CONFIG.get("fase3",{}).get("archivo_salida","resultado_maestro.xlsx")))
    if not base.is_absolute(): base=RAIZ_PROYECTO/base
    candidato=(base.parent/nombre).resolve()
    # V15.9.4 (ALTA-N6): la ruta oficial NUNCA sirve un borrador bloqueado.
    from utilidades.identidad_excel import es_borrador_no_publicable
    if es_borrador_no_publicable(candidato):
        raise HTTPException(404,"El Excel oficial no fue publicado (identidad del proyecto no verificable). El borrador de diagnóstico se descarga por /api/resultados/borrador.")
    if candidato.parent != base.parent.resolve() or not candidato.is_file() or candidato.suffix.lower()!=".xlsx": raise HTTPException(404,"El Excel exportado no está disponible.")
    return FileResponse(candidato,filename=candidato.name,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/resultados/borrador")
def descargar_borrador(archivo: str):
    """V15.9.4 (ALTA-N6): descarga DIFERENCIADA del borrador no publicable.

    Ruta explícita y separada de la oficial; sólo sirve archivos marcados
    ``.borrador_no_publicable`` de la carpeta de resultados.
    """
    nombre=Path(unquote(archivo)).name; datos=_cargar_datos() or {}
    base=Path(datos.get("nombre_excel_base") or datos.get("archivo_excel") or (RAIZ_PROYECTO / CONFIG.get("fase3",{}).get("archivo_salida","resultado_maestro.xlsx")))
    if not base.is_absolute(): base=RAIZ_PROYECTO/base
    candidato=(base.parent/nombre).resolve()
    from utilidades.identidad_excel import es_borrador_no_publicable
    if (candidato.parent != base.parent.resolve() or not candidato.is_file()
            or candidato.suffix.lower()!=".xlsx"
            or not es_borrador_no_publicable(candidato)):
        raise HTTPException(404,"El borrador no publicable no está disponible.")
    return FileResponse(candidato,filename=candidato.name,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/api/resultados/consolidar")
def consolidar_resultados(solicitud: SolicitudConsolidacion):
    """Une ejecuciones separadas 1ST/2ST de forma idempotente sin repetir OCR."""
    _assert_documento_editable("consolidar resultados")
    from utilidades.consolidacion import consolidar_documentos
    documentos=[]; usados=[]
    for declarada in solicitud.archivos:
        ruta=Path(str(declarada)).expanduser(); ruta=(ruta if ruta.is_absolute() else RAIZ_PROYECTO/ruta).resolve()
        if not ruta.is_file() or ruta.suffix.lower()!=".json": raise HTTPException(400,f"JSON inválido: {declarada}")
        try: doc=json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError) as exc: raise HTTPException(400,f"No se pudo leer {ruta.name}: {exc}") from exc
        if not isinstance(doc,dict) or not isinstance(doc.get("resultados"),list): raise HTTPException(400,f"{ruta.name} no es una ejecución OCR consolidable.")
        documentos.append(doc); usados.append(str(ruta))
    # R15.1 (CRÍTICO-01): consolida sobre el documento FRESCO en disco (el
    # snapshot cacheado podía perder commits concurrentes al reescribir todo).
    hay_actual = RUTA_VALIDACION.exists()

    def _consolidar_en_fresco(frescos: dict):
        documentos_cb = ([deepcopy(frescos)] if hay_actual else []) + documentos
        consolidado_cb = consolidar_documentos(documentos_cb)
        consolidado_cb["fuentes_consolidadas"] = usados
        # Conserva preferencias de exportación del proyecto actual y, si no
        # existen, usa la unión de idiomas declarados por las ejecuciones.
        idiomas = []
        for doc in documentos_cb:
            for codigo in doc.get("idiomas_exportacion") or []:
                codigo = str(codigo).lower()
                if codigo in {"es", "en", "de"} and codigo not in idiomas:
                    idiomas.append(codigo)
        consolidado_cb["idiomas_exportacion"] = idiomas or ["es"]
        if hay_actual:
            for clave in ("archivo_excel", "archivos_excel", "nombre_excel_base", "ruta_plantilla"):
                if frescos.get(clave) is not None:
                    consolidado_cb[clave] = deepcopy(frescos.get(clave))
        # Revisión monotónica global: el documento consolidado no puede
        # reiniciar el contador (criterio de liberación del auditor R15).
        revision_previa = int(frescos.get("revision_documento") or 0)
        frescos.clear(); frescos.update(consolidado_cb)
        if int(frescos.get("revision_documento") or 0) < revision_previa:
            frescos["revision_documento"] = revision_previa
        return consolidado_cb

    consolidado = mutar_documento(_consolidar_en_fresco, solicitud.expected_revision,
                                  permitir_ausente=True, estricto=True)[1]
    excel=None
    if solicitud.regenerar_excel:
        try: excel=str(_generar_excel_asociado())
        except PermissionError as exc: raise HTTPException(423,f"Consolidación guardada; Excel bloqueado: {exc}") from exc
    return {"casos":len(consolidado.get("resultados",[])),"tipos_st":consolidado.get("tipos_st",[]),"archivo_excel":excel,"idiomas_exportacion":consolidado.get("idiomas_exportacion"),"reutilizo_ocr":True,"idempotente":True}


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


def _aplicar_campo_manual_en_fila(fila: dict, campo: str, valor: str, usuario: str,
                                  componente: str | None = None,
                                  evidencia: dict | None = None) -> dict:
    """Aplica una confirmación de campo sin depender de la vista que la originó."""
    if campo not in (fila.get("campos") or {}) and campo not in CLAVES_PLANTILLA:
        raise ValueError("La clave no pertenece al contrato Excel activo.")
    valor = str(valor or "").strip()
    if not valor:
        raise ValueError("El valor confirmado no puede quedar vacío.")
    if campo == "opening_time_ms":
        try:
            numero = float(valor.replace(",", "."))
        except ValueError as exc:
            raise ValueError("El tiempo de apertura debe ser un número en ms.") from exc
        if not math.isfinite(numero) or numero <= 0 or numero > 1000:
            raise ValueError("El tiempo de apertura debe ser finito, > 0 y ≤ 1000 ms.")
        valor = f"{numero:g}"
    ahora_iso = datetime.now().isoformat(timespec="seconds")
    componente = componente or "por_identificar"
    correccion = {"valor": valor, "corregido_en": ahora_iso,
                  "corregido_por": usuario, "componente": componente}
    fila.setdefault("correcciones_manual_campos", {})[campo] = correccion
    original_ruta = fila.get(campo) if campo in {
        "test_number", "module_version", "inflator_type", "temperature_condition"} else None
    conflicto_ruta = original_ruta not in {None, "", valor}
    referencia_tiempo_valida = False
    if campo == "opening_time_ms" and isinstance(evidencia, dict):
        try:
            frame_evidencia_valido = (evidencia.get("frame_index") is not None
                                      and int(evidencia.get("frame_index")) >= 0)
        except (TypeError, ValueError, OverflowError):
            frame_evidencia_valido = False
        referencia_tiempo_valida = (evidencia.get("referencia_tiempo_valida") is True
                                    and frame_evidencia_valido)
    requiere_revision_campo = conflicto_ruta or (campo == "opening_time_ms" and not referencia_tiempo_valida)
    dato = {"valor": valor, "valor_original": valor,
            "estado": "pendiente_revision" if requiere_revision_campo else "confirmado_manual",
            "fuente": "correccion_manual_confirmada", "confianza": 1.0,
            "inferido": False, "requiere_revision": requiere_revision_campo,
            "valor_seguro_ruta": original_ruta if conflicto_ruta else None,
            "componente": componente, **correccion}
    if campo == "opening_time_ms":
        dato.update({
            "raw_time_ms": valor,
            "referencia_tiempo_valida": referencia_tiempo_valida,
            "estado_tiempo": "VALIDO" if referencia_tiempo_valida else "REFERENCIA_INVALIDA",
            "motivo_rechazo": "La corrección escrita no incluye un cuadro/referencia temporal validada; confirma desde la revisión de video."
                if not referencia_tiempo_valida else None,
        })
    fila.setdefault("campos", {})[campo] = dato
    consolidado = fila.setdefault("consolidado", {})
    consolidado.setdefault("campos", {})[campo] = dato
    fila["campos_faltantes"] = [c for c in fila.get("campos_faltantes", []) if c != campo]
    fila["conflictos"] = list(dict.fromkeys([
        *[c for c in fila.get("conflictos", []) if c != campo],
        *([campo] if conflicto_ruta else []),
    ]))
    fila["requiere_revision"] = bool(fila["conflictos"] or fila["campos_faltantes"]
                                    or dato.get("requiere_revision"))
    consolidado.update({"campos_faltantes": fila["campos_faltantes"],
                        "conflictos": fila["conflictos"],
                        "requiere_revision": fila["requiere_revision"]})
    fila.setdefault("comparacion", {})["resultado"] = (
        "discrepancia" if fila["conflictos"] else
        "coincidencia_parcial" if fila["campos_faltantes"] else "coincidencia_total")
    fila["comparacion"]["faltantes"] = []
    accion = {"tipo": "correccion_campo", "campo": campo, "valor": valor,
              "usuario": usuario, "fecha": ahora_iso,
              "componente": componente, "conflicto_con_ruta": conflicto_ruta}
    if evidencia:
        accion["evidencia"] = evidencia
    fila.setdefault("historial_acciones", []).append(accion)
    return dato


@app.post("/api/casos/{clave}/campos/{campo}")
def corregir_campo_caso(clave: str, campo: str, solicitud: SolicitudCampoManual):
    """Confirma una clave del contrato activo sin alterar archivos originales."""
    _assert_documento_editable("corregir el campo")
    datos = _cargar_datos()
    fila = next((f for f in (datos or {}).get("resultados", []) if _id_fila(f) == clave), None)
    if not fila or fila.get("perfil") != "empresarial":
        raise HTTPException(404, "No existe el caso empresarial solicitado.")
    if campo not in (fila.get("campos") or {}) and campo not in CLAVES_PLANTILLA:
        raise HTTPException(400, "La clave no pertenece al contrato Excel activo.")
    gestor = GestorAprendizaje(CONFIG)
    inicial = _fila_publica(fila)["revision"]["estado"]
    if gestor.estado_revision("carpeta", clave, inicial)["estado"] == "completada":
        raise HTTPException(409, "La revisión está completada. Reábrela antes de editar.")
    valor = solicitud.valor.strip()
    if campo == "opening_time_ms":
        try:
            numero = float(valor.replace(",", "."))
        except ValueError as exc:
            raise HTTPException(400, "El tiempo de apertura debe ser un número en ms.") from exc
        if not math.isfinite(numero) or numero <= 0 or numero > 1000:
            raise HTTPException(400, "El tiempo de apertura debe ser finito, > 0 y ≤ 1000 ms.")
        valor = f"{numero:g}"
    # R15.1 (CRÍTICO-01): la mutación se aplica sobre el documento FRESCO y
    # bajo lock global; el snapshot cacheado sólo se usó para validar.
    def _aplicar_en_fresco(frescos: dict):
        fila_f = next((f for f in frescos.get("resultados", [])
                       if _id_fila(f) == clave), None)
        if fila_f is None:
            raise HTTPException(404, "El caso empresarial indicado ya no existe.")
        ahora_iso = datetime.now().isoformat(timespec="seconds")
        correccion = {"valor": valor, "corregido_en": ahora_iso,
                      "corregido_por": solicitud.usuario,
                      "componente": getattr(solicitud, "componente", None) or "por_identificar"}
        fila_f.setdefault("correcciones_manual_campos", {})[campo] = correccion
        original_ruta = fila_f.get(campo) if campo in {
            "test_number", "module_version", "inflator_type", "temperature_condition"} else None
        conflicto_ruta = original_ruta not in {None, "", valor}
        referencia_tiempo_valida = False
        requiere_revision_campo = conflicto_ruta or campo == "opening_time_ms"
        dato = {"valor": valor, "valor_original": valor,
                "estado": "pendiente_revision" if requiere_revision_campo else "confirmado_manual",
                "fuente": "correccion_manual_confirmada", "confianza": 1.0,
                "inferido": False, "requiere_revision": requiere_revision_campo,
                "valor_seguro_ruta": original_ruta if conflicto_ruta else None,
                "componente": getattr(solicitud, "componente", None) or "por_identificar",
                **correccion}
        if campo == "opening_time_ms":
            dato.update({
                "raw_time_ms": valor,
                "referencia_tiempo_valida": referencia_tiempo_valida,
                "estado_tiempo": "REFERENCIA_INVALIDA",
                "motivo_rechazo": "La corrección escrita no incluye un cuadro/referencia temporal validada; confirma desde la revisión de video.",
            })
        fila_f.setdefault("campos", {})[campo] = dato
        fila_f.setdefault("consolidado", {}).setdefault("campos", {})[campo] = dato
        fila_f["campos_faltantes"] = [c for c in fila_f.get("campos_faltantes", []) if c != campo]
        fila_f["conflictos"] = list(dict.fromkeys([
            *[c for c in fila_f.get("conflictos", []) if c != campo],
            *([campo] if conflicto_ruta else []),
        ]))
        fila_f["requiere_revision"] = bool(fila_f["conflictos"] or fila_f["campos_faltantes"]
                                        or dato.get("requiere_revision"))
        fila_f["consolidado"].update({
            "campos_faltantes": fila_f["campos_faltantes"],
            "conflictos": fila_f["conflictos"],
            "requiere_revision": fila_f["requiere_revision"],
        })
        fila_f.setdefault("comparacion", {})["resultado"] = (
            "discrepancia" if fila_f["conflictos"] else
            "coincidencia_parcial" if fila_f["campos_faltantes"] else "coincidencia_total")
        # En el perfil empresarial son claves de plantilla, no tokens OCR.
        fila_f["comparacion"]["faltantes"] = []
        fila_f.setdefault("historial_acciones", []).append({
            "tipo": "correccion_campo", "campo": campo, "valor": valor,
            "usuario": solicitud.usuario, "fecha": ahora_iso,
            "conflicto_con_ruta": conflicto_ruta,
        })
        return {"campo": campo, "dato": dato, "conflictos": fila_f["conflictos"]}

    # R15.6 (CRÍTICO-01): el estado de revisión es efecto compensable que se
    # aplica ANTES del commit documental; si cualquiera falla, el documento no
    # avanza (o se restaura la revisión). Nunca más documento confirmado con
    # la revisión durable pendiente.
    caja: dict = {}

    def _efectos():
        gestor.actualizar_revision("carpeta", clave, estado="parcial")
        return None

    def _commit(_resultado):
        revision_documento, respuesta = mutar_documento(
            _aplicar_en_fresco, solicitud.expected_revision, estricto=True)
        respuesta["revision_documento"] = revision_documento
        caja["respuesta"] = respuesta

    _transaccion_efecto_humano(
        "corrección manual de campo", gestor, "carpeta", clave,
        _efectos, recurso=f"carpeta:{clave}", commit_fn=_commit)
    respuesta = caja["respuesta"]
    _regenerar_excel(respuesta)
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
    global _pipeline_hilo, _pipeline_reserva
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
    with _pipeline_lock, _video_reanalisis_lock:
        # R15 (ALTA-02): misma admisión atómica que iniciar_pipeline (CRIT-01).
        # Orden de locks pipeline→reanálisis (sin inversión respecto a /maximo).
        if _pipeline_hilo is not None and _pipeline_hilo.is_alive():
            # Mensaje V14 conservado para el caso de hilo vivo.
            raise HTTPException(409, "Ya hay un procesamiento activo o cerrando recursos.")
        if _pipeline_reserva is not None:
            raise HTTPException(409, "Ya hay un procesamiento admitido (reserva en curso).")
        if _video_reanalisis_hilo is not None and _video_reanalisis_hilo.is_alive():
            raise HTTPException(409, "Hay un reanálisis de videos en curso; termínalo antes de reprocesar.")
        estado_anterior = deepcopy(_pipeline_estado)
        ejecucion_id = f"reproceso-{uuid.uuid4().hex[:12]}"
        _pipeline_reserva = {
            "ejecucion_id": ejecucion_id, "origen": "reproceso",
            "reservado_en": datetime.now().isoformat(timespec="milliseconds")}
        try:
            _pipeline_continuar.set()
            _pipeline_cancelar.clear()
            _pipeline_estado.update({
                "estado": "procesando", "fase": "reproceso",
                "mensaje": "Preparando reproceso selectivo",
                "ejecucion_id": ejecucion_id,
                "ruta": datos["raiz"], "iniciado_en": datetime.now().isoformat(timespec="seconds"),
                "finalizado_en": None, "error": None, "porcentaje": 0,
                "resultados_parciales": [], "tipo_st": fila.get("tipo_st"),
            })
            plantilla = datos.get("ruta_plantilla") or _pipeline_estado.get("ruta_plantilla")
            nombre_excel = _pipeline_estado.get("nombre_excel")
        except BaseException:
            _pipeline_reserva = None
            _pipeline_estado.clear()
            _pipeline_estado.update(estado_anterior)
            raise
    # R15 (ALTA-02): la ROI preferida es un efecto PERSISTENTE: se guarda solo
    # tras la admisión (antes se escribía incluso en respuestas 409).
    if solicitud.modo_recorte == "manual" and solicitud.roi_manual:
        objetivo = next((i for i in fila.get("imagenes", [])
                         if not imagenes or i.get("ruta") in imagenes), None)
        if objetivo:
            proyecto = str(datos.get("raiz") or "proyecto")
            clave_roi = (Path(objetivo.get("ruta", "imagen")).name
                         if solicitud.roi_alcance == "etiqueta" else proyecto)
            try:
                GestorAprendizaje(CONFIG).guardar_roi_preferida(
                    solicitud.roi_alcance, clave_roi, objetivo.get("fase"),
                    solicitud.roi_manual, solicitud.zoom_forzado)
            except BaseException as exc:  # noqa: BLE001 — rollback + 503
                _rollback_admision_pipeline(estado_anterior)
                raise HTTPException(503, f"No se pudo guardar la ROI preferida: {exc}") from exc
    perfil_reproceso = normalizar_perfil(_pipeline_estado.get("perfil_rendimiento") or "alto")
    hilo_reproceso = threading.Thread(target=_ejecutar_pipeline_fondo, kwargs={
        "ruta": Path(datos["raiz"]), "nombre_excel": nombre_excel,
        "sobrescribir_excel": True, "tipo_st": fila.get("tipo_st"),
        "ruta_plantilla": plantilla, "casos_filtrados": {fila["case_key"]},
        "imagenes_filtradas": imagenes or None, "solo_errores": solicitud.solo_errores,
        "modo_recorte": solicitud.modo_recorte, "roi_manual": solicitud.roi_manual,
        "modo_ejecucion": "completo", "zoom_forzado": solicitud.zoom_forzado,
        "idiomas_exportacion": list((datos.get("idiomas_exportacion") or
                                      _pipeline_estado.get("idiomas_exportacion") or ["es"])),
        "perfil_rendimiento": perfil_reproceso,
        "ejecucion_id": ejecucion_id,
    }, daemon=True)
    # R15 (CRIT-01): asignación bajo lock con reserva activa; arranque verificado.
    with _pipeline_lock:
        _pipeline_hilo = hilo_reproceso
    try:
        hilo_reproceso.start()
    except BaseException as exc:  # noqa: BLE001 — rollback + 500 explícito
        _rollback_admision_pipeline(estado_anterior, hilo_fallido=hilo_reproceso)
        raise HTTPException(500, f"No se pudo iniciar el reproceso: {exc}") from exc
    with _pipeline_lock:
        if (_pipeline_reserva is not None
                and _pipeline_reserva.get("ejecucion_id") == ejecucion_id):
            _pipeline_reserva = None
    return {"aceptado": True, "case_key": fila["case_key"],
            "imagenes": len(imagenes), "solo_errores": solicitud.solo_errores,
            "ejecucion_id": ejecucion_id}


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
                        "videos": [{"id": hashlib.sha256(v["ruta"].encode()).hexdigest()[:16],
                                    "nombre": Path(v["ruta"]).name, "ruta": v["ruta"],
                                    "ruta_relativa": v.get("ruta_relativa"), "estado": "pendiente"}
                                   for v in caso.get("videos", [])],
                        "video_apertura": {"estado": "pendiente", "tiempo_ms": None, "soporte": 0},
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
    _normalizar_tiempos_video_fila(fila)
    detalle_json = dict(fila)
    detalle_json["video_apertura"] = _video_apertura_publica(fila.get("video_apertura"))
    detalle_json["video_apertura_anterior"] = _video_apertura_publica(
        fila.get("video_apertura_anterior"))
    detalle_json["id"] = _id_fila(fila)
    detalle_json["lote"] = _lote_de(fila)
    # R15 (MEDIA-14): revisión del documento para CAS en las mutaciones.
    detalle_json["revision_documento"] = int(datos.get("revision_documento") or 0)
    try:
        from utilidades.resultado_caso import resolver_resultado_caso
        detalle_json["resultado_caso_canonico"] = resolver_resultado_caso(fila)
    except (TypeError, ValueError):
        detalle_json["resultado_caso_canonico"] = fila.get("resultado_caso_canonico")
    campos_detalle = dict(fila.get("campos") or {})
    if "opening_time_ms" in campos_detalle or isinstance(detalle_json.get("resultado_caso_canonico"), dict):
        campos_detalle["opening_time_ms"] = _campo_apertura_publico(
            campos_detalle.get("opening_time_ms"), detalle_json.get("resultado_caso_canonico"))
        detalle_json["campos"] = campos_detalle
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
                rotacion = rotaciones.get(imagen_hash)
                preferida = float((rotacion or {}).get("grados", 0)) % 360
                ocr = publico.get("resultado_ocr") or {}
                aplicada = float(ocr.get("rotacion_manual_aplicada_grados") or 0) % 360
                base = _orientacion_base_publica(ocr)
                ocr["orientacion_texto_base_grados"] = base
                ajuste = float(ocr.get("deskew_texto_aplicado_grados") or
                               ocr.get("deskew_aplicado_grados") or 0)
                ruta_codificada = quote(str(item["ruta"]), safe="")
                publico["rotacion_manual_preferida_grados"] = preferida
                publico["rotacion_manual_definida"] = rotacion is not None
                publico["rotacion_pendiente"] = abs(preferida - aplicada) >= 0.01
                rotacion_vista = preferida if rotacion is not None else base
                ajuste_vista = 0.0 if rotacion is not None else ajuste
                prioridad_aplicada = bool(ocr.get("orientacion_manual_prioritaria"))
                rotacion_ocr = aplicada if prioridad_aplicada else (aplicada + base) % 360
                ajuste_ocr = 0.0 if prioridad_aplicada else ajuste
                publico["ruta_api_visual"] = (
                    f"/api/imagen/orientada?ruta={ruta_codificada}"
                    f"&rotacion={rotacion_vista}&ajuste={ajuste_vista}")
                publico["ruta_api_orientada"] = (
                    f"/api/imagen/orientada?ruta={ruta_codificada}"
                    f"&rotacion={rotacion_ocr}&ajuste={ajuste_ocr}")
            except (HTTPException, OSError):
                pass
        if raiz_local:
            ruta_filtro = _reubicar_ruta(str(item["ruta"]), datos, raiz_local)
            publico["resultado_ocr"] = gestor.filtrar_no_texto(publico.get("resultado_ocr") or {}, ruta_filtro)
        detalle_json["imagenes"].append(publico)
    detalle_json["videos"] = []
    for video in fila.get("videos", []) or []:
        publico_video = _video_item_publico(video)
        if not isinstance(publico_video, dict):
            continue
        ruta_codificada = quote(str(video.get("ruta") or ""), safe="")
        publico_video["ruta_api"] = f"/api/video?ruta={ruta_codificada}"
        frame = video.get("frame_evento")
        if frame is not None:
            publico_video["frame_api"] = f"/api/video/frame?ruta={ruta_codificada}&frame={int(frame)}"
        detalle_json["videos"].append(publico_video)
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


@app.get("/api/video")
def video(ruta: str):
    """Sirve un video registrado del lote. FileResponse permite reproducción local."""
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    permitida = _resolver_raiz_datos(datos)
    if permitida is None:
        raise HTTPException(503, "La raíz del lote no está disponible en este equipo.")
    objetivo = _resolver_imagen(unquote(ruta), datos, permitida)
    if objetivo.suffix.lower() not in {".avi", ".mp4", ".mov", ".mkv", ".wmv", ".m4v"}:
        raise HTTPException(415, "El archivo registrado no es un video soportado.")
    return FileResponse(objetivo)


@app.get("/api/video/frame")
def video_frame(ruta: str, frame: int = Query(ge=0)):
    """Extrae un cuadro concreto para revisar el instante de apertura."""
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    permitida = _resolver_raiz_datos(datos)
    if permitida is None:
        raise HTTPException(503, "La raíz del lote no está disponible en este equipo.")
    objetivo = _resolver_imagen(unquote(ruta), datos, permitida)
    import cv2
    cap = cv2.VideoCapture(str(objetivo))
    try:
        if not cap.isOpened():
            raise HTTPException(422, "No se pudo abrir el video.")
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total and frame >= total:
            raise HTTPException(416, f"El video sólo contiene {total} cuadros.")
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame))
        ok, imagen_frame = cap.read()
        if not ok or imagen_frame is None:
            raise HTTPException(422, "No se pudo extraer ese cuadro del video.")
        # No introducir otra compresión con pérdida sobre el primer filamento
        # de ruptura: el revisor recibe los píxeles decodificados sin reducir.
        ok, codificada = cv2.imencode(".png", imagen_frame)
        if not ok:
            raise HTTPException(500, "No se pudo codificar el cuadro.")
        return Response(codificada.tobytes(), media_type="image/png",
                        headers={"Cache-Control": "no-store"})
    finally:
        cap.release()



@app.get("/api/video/tiempo-frame")
def video_tiempo_frame(prueba_id: str, video_id: str, frame: int = Query(ge=0)):
    """Devuelve el tiempo autoritativo del cuadro solicitado.

    V15.4 evita que el dashboard calcule por su cuenta un offset antiguo. El
    backend contrasta el reloj de la esquina superior derecha del MISMO frame
    con la tasa real de grabación y jamás devuelve tiempos negativos.
    """
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    fila = next((f for f in datos.get("resultados", []) if _id_fila(f) == prueba_id), None)
    if fila is None:
        raise HTTPException(404, "No existe el ID solicitado.")
    video_item = next((v for v in (fila.get("videos") or []) if str(v.get("id")) == video_id), None)
    if video_item is None:
        raise HTTPException(404, "Video no encontrado en este ID.")
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "La raíz del lote no está disponible en este equipo.")
    ruta_local = _resolver_imagen(str(video_item.get("ruta") or ""), datos, raiz)
    from video_airbag import resolver_tiempo_frame, fps_real_item, normalizar_videos_caso
    # V15.7: la tasa real se comparte entre las cámaras del ensayo; nunca se
    # usa el FPS de reproducción del AVI (8 fps → 125 ms/cuadro).
    normalizar_videos_caso(fila.get("videos") or [], CONFIG)
    fps_real = fps_real_item(video_item)
    info = resolver_tiempo_frame(
        ruta_local, int(frame),
        fps_preferido=fps_real,
        timestamp_inicial_ms=video_item.get("overlay_timestamp_inicial_ms"),
        config=CONFIG,
    )
    if fps_real:
        info["fps_fuente"] = video_item.get("fps_fuente") or info.get("fps_fuente")
    info["video_id"] = str(video_id)
    info["prueba_id"] = str(prueba_id)
    return info

def _aplicar_consenso_video_a_fila(fila: dict, consenso: dict) -> None:
    fila["video_apertura"] = consenso
    # Una corrección manual explícita del campo tiene prioridad sobre el video.
    if (fila.get("correcciones_manual_campos") or {}).get("opening_time_ms"):
        return
    campos = fila.setdefault("campos", {})
    consolidado = fila.setdefault("consolidado", {})
    campos_con = consolidado.setdefault("campos", campos)
    from video_airbag import consenso_valido
    valor = consenso.get("tiempo_ms") if consenso_valido(consenso) else None
    if valor is not None:
        dato = {
            "valor": str(round(float(valor), 1)), "estado": "extraido_video",
            "fuente": "video_airbag_consenso", "confianza": min(0.99, 0.75 + 0.08 * int(consenso.get("soporte") or 0)),
            "inferido": False, "requiere_revision": bool(consenso.get("requiere_revision")),
            "soporte_videos": int(consenso.get("soporte") or 0),
            "raw_time_ms": consenso.get("tiempo_crudo_ms", valor),
            "referencia_tiempo_valida": True, "estado_tiempo": "VALIDO",
        }
        campos["opening_time_ms"] = dato
        campos_con["opening_time_ms"] = dict(dato)
        fila["campos_faltantes"] = [x for x in (fila.get("campos_faltantes") or []) if x != "opening_time_ms"]
        consolidado["campos_faltantes"] = [x for x in (consolidado.get("campos_faltantes") or []) if x != "opening_time_ms"]
    else:
        # Si todas las cámaras evaluables concluyen explícitamente que no hubo
        # evento, un tiempo viejo de video no puede sobrevivir como pendiente:
        # el resultado correcto es faltante/no observado. Esto evita arrastrar
        # una medición de una corrida previa.
        if str(consenso.get("estado_consenso") or "").casefold() == "sin_evento":
            dato = {
                "valor": None, "estado": "faltante_requerido", "requerido": True,
                "requiere_revision": True, "fuente": "video_airbag_consenso",
                "soporte_videos": int(consenso.get("soporte") or 0),
                "motivos_revision": list(consenso.get("motivo_revision") or ["sin_evento"]),
            }
            campos["opening_time_ms"] = dato
            campos_con["opening_time_ms"] = dict(dato)
            if "opening_time_ms" not in fila.setdefault("campos_faltantes", []):
                fila["campos_faltantes"].append("opening_time_ms")
            if "opening_time_ms" not in consolidado.setdefault("campos_faltantes", []):
                consolidado["campos_faltantes"].append("opening_time_ms")
            return
        # V15.9.1 (B1/B2): un consenso propuesto o con causa grave NO publica
        # el tiempo. Si existe una medida sin confirmar se conserva como
        # pendiente (visible sólo en el tooltip, nunca coloreada); si no hay
        # medida y el valor anterior venía del video, se marca faltante.
        propuesto = consenso.get("tiempo_propuesto_ms")
        if propuesto is None:
            propuesto = consenso.get("tiempo_ms")
        referencia_propuesta = (consenso.get("referencia_tiempo_valida") is True
                                if "referencia_tiempo_valida" in consenso
                                else consenso.get("estado_tiempo") == "VALIDO")
        propuesto_util = (
            isinstance(propuesto, (int, float)) and not isinstance(propuesto, bool)
            and math.isfinite(float(propuesto)) and float(propuesto) > 0
            and referencia_propuesta
            and consenso.get("estado_consenso") in {"confirmado", "propuesto", "discordancia"})
        if propuesto_util:
            dato = {
                "valor": str(round(float(propuesto), 1)), "estado": "pendiente_revision",
                "fuente": "video_airbag_consenso", "inferido": False,
                "requiere_revision": True,
                "soporte_videos": int(consenso.get("soporte") or 0),
                "motivos_revision": list(consenso.get("motivo_revision") or []),
                "raw_time_ms": consenso.get("tiempo_crudo_ms", propuesto),
                "referencia_tiempo_valida": True, "estado_tiempo": "VALIDO",
            }
            campos["opening_time_ms"] = dato
            campos_con["opening_time_ms"] = dict(dato)
            fila["campos_faltantes"] = [x for x in (fila.get("campos_faltantes") or []) if x != "opening_time_ms"]
            consolidado["campos_faltantes"] = [x for x in (consolidado.get("campos_faltantes") or []) if x != "opening_time_ms"]
            return
        actual = campos.get("opening_time_ms") or {}
        if str(actual.get("fuente") or "").startswith("video"):
            raw = actual.get("raw_time_ms")
            if raw is None:
                raw = actual.get("valor")
            if raw is not None:
                try:
                    numero_raw = float(str(raw).strip().casefold().removesuffix("ms").replace(",", "."))
                    estado_raw = ("NO_FINITO" if not math.isfinite(numero_raw) else
                                  "NO_POSITIVO" if numero_raw <= 0 else "REFERENCIA_INVALIDA")
                except (TypeError, ValueError, OverflowError):
                    estado_raw = "NO_INTERPRETABLE"
                motivo_raw = (consenso.get("motivo_rechazo") or
                              "El tiempo crudo queda en auditoría; no se publica sin signo positivo y referencia validada.")
                campos["opening_time_ms"] = {
                    **actual, "valor": None, "raw_time_ms": raw,
                    "estado": "pendiente_revision", "estado_tiempo": estado_raw,
                    "referencia_tiempo_valida": False,
                    "motivo_rechazo": motivo_raw, "requiere_revision": True,
                }
            else:
                campos["opening_time_ms"] = {
                    "valor": None, "estado": "faltante_requerido", "requerido": True,
                    "requiere_revision": True,
                }
            campos_con["opening_time_ms"] = dict(campos["opening_time_ms"])
            if "opening_time_ms" not in fila.setdefault("campos_faltantes", []):
                fila["campos_faltantes"].append("opening_time_ms")


def _estado_reanalisis_video(**cambios) -> dict:
    with _video_reanalisis_lock:
        _video_reanalisis_estado.update(cambios)
        return dict(_video_reanalisis_estado)


def _reanalizar_videos_fondo(prueba_id: str | None = None, video_id: str | None = None) -> None:
    global _video_reanalisis_hilo
    try:
        datos_origen = _cargar_datos()
        if not datos_origen:
            raise RuntimeError("No hay resultados procesados para reanalizar.")
        datos = deepcopy(datos_origen)
        raiz = _resolver_raiz_datos(datos)
        if raiz is None:
            raise RuntimeError("La raíz del lote no está disponible en este equipo.")

        filas = list(datos.get("resultados") or [])
        if prueba_id:
            filas = [f for f in filas if _id_fila(f) == prueba_id]
            if not filas:
                raise RuntimeError("No existe el ID solicitado para reanalizar videos.")
        def videos_objetivo(fila: dict) -> list[dict]:
            videos = list(fila.get("videos") or [])
            if video_id:
                videos = [v for v in videos if str(v.get("id")) == str(video_id)]
            return videos

        total = sum(len(videos_objetivo(f)) for f in filas)
        if not total:
            if video_id:
                raise RuntimeError("No se encontró el video solicitado dentro de este ID.")
            raise RuntimeError("No hay videos registrados en los resultados actuales.")

        from video_airbag import ALGORITMO_VERSION, analizar_video, consenso_videos
        _estado_reanalisis_video(
            estado="procesando", mensaje=("Recalculando un video sin repetir OCR" if video_id else "Reanalizando videos sin repetir OCR"),
            prueba_id=prueba_id, video_id=video_id, total_videos=total, procesados=0, errores=0,
            video_actual=None, iniciado_en=datetime.now().isoformat(timespec="seconds"),
            finalizado_en=None, ultimo_error=None, algoritmo=ALGORITMO_VERSION,
        )
        procesados = 0
        errores = 0
        ultimo_error = None
        ahora_etiqueta = datetime.now().isoformat(timespec="seconds")
        parches: list = []   # R15 (ALTA-03): patch por video, merge al commit

        for fila in filas:
            for video_item in videos_objetivo(fila):
                nombre = str(video_item.get("nombre") or Path(str(video_item.get("ruta") or "video")).name)
                _estado_reanalisis_video(video_actual=nombre, mensaje=f"Reanalizando {nombre}")
                ruta_local = _reubicar_ruta(str(video_item.get("ruta") or ""), datos, raiz)
                if ruta_local is None or not ruta_local.is_file():
                    errores += 1
                    ultimo_error = f"No se encontró el video: {nombre}"
                    procesados += 1
                    _estado_reanalisis_video(procesados=procesados, errores=errores, ultimo_error=ultimo_error)
                    continue
                try:
                    nuevo = analizar_video(ruta_local, CONFIG, usar_cache=False)
                    # R15 (ALTA-03): NO se muta el snapshot viejo; el patch se
                    # fusionará al final sobre el documento MÁS RECIENTE.
                    parches.append({
                        "fila_id": _id_fila(fila),
                        "video_id": str(video_item.get("id")),
                        "nombre": nombre, "nuevo": nuevo})
                except Exception as exc:
                    errores += 1
                    ultimo_error = f"{nombre}: {type(exc).__name__}: {exc}"
                procesados += 1
                _estado_reanalisis_video(
                    procesados=procesados, errores=errores, ultimo_error=ultimo_error)

        # R15 (ALTA-03): commit por merge bajo lock de mutación: se relee el
        # documento más reciente en disco y se aplican SOLO los patches por
        # video (campos manuales como revision_manual se conservan desde la
        # versión fresca). Las ediciones hechas durante el reanálisis sobreviven.
        filas_alcance = [_id_fila(f) for f in filas]
        with _lock_documento():
            datos_frescos = _leer_documento_disco()
            filas_frescas = {_id_fila(f): f
                             for f in (datos_frescos.get("resultados") or [])}
            for parche in parches:
                fila_fresca = filas_frescas.get(parche["fila_id"])
                item_fresco = None
                if fila_fresca is not None:
                    item_fresco = next(
                        (v for v in (fila_fresca.get("videos") or [])
                         if str(v.get("id")) == parche["video_id"]), None)
                if item_fresco is None:
                    # El caso/video ya no está en el documento actual: se
                    # descarta SU patch y se hace visible; nunca en silencio.
                    errores += 1
                    ultimo_error = (f"{parche['nombre']}: el caso/video ya no "
                                    "existe en el documento actual; patch descartado")
                    continue
                conservar = {k: item_fresco.get(k) for k in (
                    "id", "ruta_relativa", "carpeta_video", "revision_manual",
                    "ultima_zona_nacimiento"
                ) if item_fresco.get(k) is not None}
                anterior = {k: item_fresco.get(k) for k in (
                    "frame_evento", "tiempo_ms", "algoritmo_video", "desde_cache"
                ) if k in item_fresco}
                item_fresco.clear()
                item_fresco.update(parche["nuevo"])
                item_fresco.update(conservar)
                item_fresco["reanalizado_en"] = ahora_etiqueta
                item_fresco["origen_resultado_video"] = "recalculado_v15_7_4"
                item_fresco["deteccion_anterior"] = anterior
                item_fresco["desde_cache"] = False
            for fila_id in filas_alcance:
                fila_fresca = filas_frescas.get(fila_id)
                if fila_fresca is None:
                    continue
                consenso = consenso_videos(fila_fresca.get("videos") or [], CONFIG)
                _aplicar_consenso_video_a_fila(fila_fresca, consenso)
            datos_frescos["video_reanalizado_en"] = datetime.now().isoformat(timespec="seconds")
            datos_frescos["video_reanalisis_version"] = "15.7.4"
            _commit_documento(datos_frescos)
        resultado_excel = {}
        _regenerar_excel(resultado_excel)
        _estado_reanalisis_video(
            estado="completado", mensaje=(
                f"Recálculo individual terminado: {procesados - errores} correcto(s), {errores} con error."
                if video_id else f"Reanálisis de video terminado: {procesados - errores} correctos, {errores} con error."
            ), procesados=procesados, errores=errores, video_actual=None,
            finalizado_en=datetime.now().isoformat(timespec="seconds"),
        )
    except Exception as exc:
        _estado_reanalisis_video(
            estado="error", mensaje="No se pudo completar el reanálisis de videos.",
            ultimo_error=f"{type(exc).__name__}: {exc}",
            finalizado_en=datetime.now().isoformat(timespec="seconds"),
        )
    finally:
        with _video_reanalisis_lock:
            _video_reanalisis_hilo = None


@app.get("/api/video/reanalisis/estado")
def estado_reanalisis_videos():
    with _video_reanalisis_lock:
        return dict(_video_reanalisis_estado)


@app.post("/api/video/reanalizar")
def reanalizar_videos(solicitud: SolicitudReanalisisVideos):
    global _video_reanalisis_hilo
    # R15.3 (CRÍTICO-01): admisión ATÓMICA en una ÚNICA región con el mismo
    # orden de locks que iniciar_pipeline (_pipeline_lock → _video_reanalisis_lock).
    # En R15.2 la comprobación del pipeline y la admisión del reanálisis eran
    # dos secciones distintas: entre ellas el pipeline podía ser admitido y
    # ambos procesos quedaban activos a la vez. Validación, reserva de estado,
    # creación y arranque del hilo ocurren sin liberar los locks.
    with _pipeline_lock, _video_reanalisis_lock:
        # R15: también se rechaza si el slot está RESERVADO (admisión en curso)
        # o si hay un hilo creado pero todavía no arrancado (is_alive()=False).
        if (_pipeline_estado.get("estado") in {"procesando", "pausando", "pausado",
                                               "cancelando", "reanudando"}
                or _slot_pipeline_ocupado_locked()):
            raise HTTPException(409, "Detén o termina el procesamiento OCR antes de reanalizar videos.")
        if _video_reanalisis_hilo is not None and _video_reanalisis_hilo.is_alive():
            raise HTTPException(409, "Ya hay un reanálisis de videos en curso.")
        estado_anterior = dict(_video_reanalisis_estado)
        _video_reanalisis_estado.update({
            "estado": "preparando", "mensaje": ("Preparando recálculo del video" if solicitud.video_id else "Preparando reanálisis de video"),
            "prueba_id": solicitud.prueba_id, "video_id": solicitud.video_id, "total_videos": 0, "procesados": 0,
            "errores": 0, "video_actual": None, "iniciado_en": datetime.now().isoformat(timespec="seconds"),
            "finalizado_en": None, "ultimo_error": None, "algoritmo": None,
        })
        hilo = threading.Thread(
            target=_reanalizar_videos_fondo, args=(solicitud.prueba_id, solicitud.video_id), daemon=True)
        # El slot se reserva con el hilo creado (aún no arrancado) dentro de la
        # misma región: ninguna admisión concurrente puede colarse.
        _video_reanalisis_hilo = hilo
        try:
            hilo.start()
        except BaseException as exc:  # noqa: BLE001 — rollback + 500 explícito
            # R15.3 (MEDIO-05): nunca dejar «preparando fantasma»: se restaura
            # el estado anterior, se marca el error visible y se libera el slot
            # (mismo criterio que _rollback_admision_pipeline en el pipeline).
            if _video_reanalisis_hilo is hilo:
                _video_reanalisis_hilo = None
            _video_reanalisis_estado.clear()
            _video_reanalisis_estado.update(estado_anterior)
            _video_reanalisis_estado.update({
                "estado": "error",
                "mensaje": "El reanálisis no pudo arrancar",
                "finalizado_en": datetime.now().isoformat(timespec="seconds"),
                "ultimo_error": str(exc) or exc.__class__.__name__,
            })
            raise HTTPException(500, f"El reanálisis no pudo arrancar: {exc}") from exc
    return {"aceptado": True, "estado": "preparando", "prueba_id": solicitud.prueba_id, "video_id": solicitud.video_id}


@app.post("/api/video/revision")
def revisar_video(solicitud: SolicitudRevisionVideo):
    # R15 (ALTA-07, pruebas obligatorias 6 y 8): guard servidor autoritativo;
    # 409 sin efectos laterales si hay pipeline activo/reservado o reanálisis.
    _guard_mutacion_video("revisar el video")
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    _verificar_expected_revision(solicitud.expected_revision, datos, estricto=True)
    fila = next((f for f in datos.get("resultados", []) if _id_fila(f) == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "No existe el ID solicitado.")
    video_item = next((v for v in (fila.get("videos") or []) if str(v.get("id")) == solicitud.video_id), None)
    if video_item is None:
        raise HTTPException(404, "Video no encontrado en este ID.")
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "La raíz del lote no está disponible en este equipo.")
    ruta_local = _resolver_imagen(str(video_item.get("ruta") or ""), datos, raiz)
    # R15 (ALTA-07): pre-chequeo ANTES de efectos persistentes (el archivo
    # durable de la revisión); en el commit se revalida contra el fresco.
    _verificar_revision_no_completada(solicitud.prueba_id, fila, "revisar el video")
    from video_airbag import (cargar_revisiones, guardar_revision_video, consenso_videos, resolver_tiempo_frame,
                              fps_real_item, normalizar_videos_caso,
                              ErrorPersistenciaRevisiones)
    normalizar_videos_caso(fila.get("videos") or [], CONFIG)
    evento_censurado = _evento_censurado_video_api(video_item)
    if solicitud.estado == "confirmado" and evento_censurado:
        raise HTTPException(422,
            "El evento está censurado al inicio del clip; no puede confirmarse como tiempo final sin evidencia previa del nacimiento.")

    # El backend vuelve a resolver el cuadro seleccionado usando reloj del MISMO
    # frame y FPS fiables. Los valores crudos (incluidos offsets negativos) se
    # guardan separados de la apertura final; no se corrigen ni se clipean.
    tiempo_resuelto = None
    tiempo_confirmado = None
    if solicitud.estado == "confirmado" and solicitud.frame_index is not None:
        tiempo_resuelto = resolver_tiempo_frame(
            ruta_local, int(solicitud.frame_index),
            fps_preferido=fps_real_item(video_item),
            timestamp_inicial_ms=video_item.get("overlay_timestamp_inicial_ms"),
            config=CONFIG,
        )
        tiempo_confirmado = tiempo_resuelto.get("tiempo_ms")
        try:
            tiempo_confirmado = float(tiempo_confirmado)
        except (TypeError, ValueError, OverflowError):
            tiempo_confirmado = None
        if tiempo_confirmado is None or not math.isfinite(tiempo_confirmado) or tiempo_confirmado <= 0:
            raise HTTPException(422, "El tiempo final de apertura debe ser finito y > 0 ms; revisa el reloj/frame.")
        fuente = str(tiempo_resuelto.get("fps_fuente") or "")
        referencia_tiempo_valida = bool(
            tiempo_resuelto.get("overlay_valido")
            or (tiempo_resuelto.get("fps") is not None
                and fuente in {"overlay_rec", "config_forzado", "archivo"})
        )
        if not referencia_tiempo_valida:
            raise HTTPException(422, "No hay una referencia temporal validada para confirmar la apertura.")

    # R15 (ALTA-03): los cambios al item se aplican en el commit sobre el
    # documento MÁS RECIENTE (bajo lock), no sobre la primera lectura.
    # R15.3 (ALTO-02): el registro durable de la revisión se movió DENTRO de
    # la región de lock, después del CAS autoritativo (más abajo).
    perfil_aprendido = None

    def _aplicar_a_item(item: dict) -> None:
        item["revision_manual"] = revision
        if solicitud.frame_index is not None and solicitud.estado == "confirmado":
            item["frame_evento"] = int(solicitud.frame_index)
        if tiempo_confirmado is not None:
            item["tiempo_ms"] = round(float(tiempo_confirmado), 1)
            item["tiempo_overlay_ms"] = tiempo_resuelto.get("tiempo_overlay_ms")
            item["tiempo_overlay_leido_ms"] = tiempo_resuelto.get("tiempo_overlay_leido_ms")
            item["tiempo_fps_ms"] = tiempo_resuelto.get("tiempo_fps_ms")
            item["fuente_tiempo"] = tiempo_resuelto.get("fuente_tiempo")
            item["discrepancia_tiempo_ms"] = tiempo_resuelto.get("discrepancia_ms")
            item["advertencia_tiempo"] = tiempo_resuelto.get("advertencia")
            item["overlay_validado"] = bool(tiempo_resuelto.get("overlay_valido"))
            if tiempo_resuelto.get("fps"):
                item["fps"] = float(tiempo_resuelto.get("fps"))
                item["fps_grabacion"] = float(tiempo_resuelto.get("fps"))
                item["fps_fuente"] = item.get("fps_fuente") if fps_real_item(item) else tiempo_resuelto.get("fps_fuente")
                item["resolucion_nativa_ms"] = round(1000.0 / float(tiempo_resuelto.get("fps")), 6)
            if tiempo_resuelto.get("overlay_texto_esquina"):
                item["overlay_texto_esquina"] = tiempo_resuelto.get("overlay_texto_esquina")
        if localizacion_nacimiento is not None:
            item["ultima_zona_nacimiento"] = localizacion_nacimiento
        if perfil_aprendido is not None:
            item["perfil_evento_aprendido"] = perfil_aprendido

    # V15.7.4: una confirmación guarda dos escalas distintas (ROI general y
    # microzona). R15.5 (HIGH-01): la escritura del dataset de eventos es un
    # efecto OPCIONAL posterior al commit principal (más abajo); dentro del
    # lock sólo queda la localización pura (su resultado es parte del
    # documento: ultima_zona_nacimiento).
    ejemplo_aprendido = None
    advertencia_aprendizaje = None
    localizacion_nacimiento = None
    datos_aprendizaje = None

    # R15 (ALTA-03 + MEDIA-14): commit sobre el documento MÁS RECIENTE, bajo
    # lock de mutación, con CAS y revalidación de revisión completada.
    # R15.3 (ALTO-02): el CAS de esta región es AUTORITATIVO y el efecto
    # durable autoritativo (registro de revisión) ocurre DENTRO de la misma
    # exclusión: un 409 sólo puede emitirse antes de cualquier efecto
    # persistente. R15.5 (HIGH-01): el dataset de eventos es efecto OPCIONAL
    # y se entrena sólo tras el commit exitoso (fuera del lock). R15
    # (ALTA-04) se conserva: si el registro durable falla, se reporta error y
    # la revisión NO se aplica al documento.
    # R15.5 (P0): política transaccional común — snapshot verificado del
    # almacén durable y compensación coordinada ante cualquier fallo.
    # R15.7 (ALTO-02): el video es subrecurso explícito de su carpeta.
    recurso_video = _recurso_video(solicitud.prueba_id, solicitud.video_id)
    _assert_recurso_consistente(recurso_video, "revisar el video")
    tx = TransaccionMultiAlmacen("revisión de video", recurso=recurso_video)
    with _lock_documento():
        datos_frescos = _leer_documento_disco()
        _verificar_expected_revision(solicitud.expected_revision, datos_frescos,
                                                estricto=True)
        fila_fresca, item_fresco = _localizar_fila_video(
            datos_frescos, solicitud.prueba_id, solicitud.video_id)
        _verificar_revision_no_completada(solicitud.prueba_id, fila_fresca,
                                          "revisar el video")
        # R15.4 (HIGH-01): snapshot del registro durable ANTES del efecto.
        revisiones_antes = tx.capturar("revisiones de video", cargar_revisiones,
                                       _restaurar_revisiones_video)
        try:
            try:
                revision = guardar_revision_video(
                    ruta_local, case_key=fila_fresca.get("case_key"),
                    frame_index=solicitud.frame_index,
                    tiempo_ms=(tiempo_confirmado if solicitud.estado == "confirmado" else None),
                    estado=solicitud.estado, usuario=solicitud.usuario,
                    comentario=solicitud.comentario,
                    fuente_tiempo=(tiempo_resuelto or {}).get("fuente_tiempo"),
                    referencia_tiempo_valida=(referencia_tiempo_valida if solicitud.estado == "confirmado" else None),
                    evento_censurado=evento_censurado,
                    tiempo_overlay_leido_ms=(tiempo_resuelto or {}).get("tiempo_overlay_leido_ms"),
                    tiempo_overlay_validado_ms=(tiempo_resuelto or {}).get("tiempo_overlay_ms"),
                    tiempo_fps_ms=(tiempo_resuelto or {}).get("tiempo_fps_ms"),
                    discrepancia_tiempo_ms=(tiempo_resuelto or {}).get("discrepancia_ms"),
                    advertencia_tiempo=(tiempo_resuelto or {}).get("advertencia"))
            except ErrorPersistenciaRevisiones as exc:
                raise HTTPException(503, f"La revisión no se guardó: {exc}") from exc
            tx.aplicado()  # la revisión durable QUEDÓ guardada
            if solicitud.estado == "confirmado" and solicitud.frame_index is not None:
                try:
                    from aprendizaje_video_airbag import (perfil_evento_aprendido,
                                                           localizar_nacimiento_evento, _bbox_evento_normalizada)
                    zona = (item_fresco.get("zona_deteccion") or {}).get("bbox_norm")
                    tipo_camara = (item_fresco.get("tipo_camara") or
                                   (item_fresco.get("zona_deteccion") or {}).get("tipo_camara"))
                    bbox_evento = None
                    if solicitud.bbox_evento_norm:
                        bbox_evento = _bbox_evento_normalizada(solicitud.bbox_evento_norm)
                        localizacion_nacimiento = {
                            "bbox_norm": bbox_evento, "frame_index": int(solicitud.frame_index),
                            "metodo": "manual_dashboard", "confianza": 1.0,
                        }
                    else:
                        localizacion_nacimiento = localizar_nacimiento_evento(
                            ruta_local, frame_index=int(solicitud.frame_index), bbox_norm=zona)
                        bbox_evento = localizacion_nacimiento.get("bbox_norm")
                    # R15.5 (HIGH-01): la escritura del dataset NO ocurre aquí;
                    # se guarda lo necesario para entrenar sólo si el commit
                    # documental tiene éxito.
                    datos_aprendizaje = {
                        "zona": zona, "tipo_camara": tipo_camara,
                        "bbox_evento": bbox_evento, "fps_item": item_fresco.get("fps"),
                    }
                    perfil_aprendido = perfil_evento_aprendido(tipo_camara)
                except Exception as exc:  # La revisión manual nunca debe perderse por un fallo del aprendizaje.
                    advertencia_aprendizaje = f"{type(exc).__name__}: {exc}"
            _aplicar_a_item(item_fresco)
            consenso = consenso_videos(fila_fresca.get("videos") or [], CONFIG)
            _aplicar_consenso_video_a_fila(fila_fresca, consenso)
            revision_documento = _commit_documento(datos_frescos)
        except BaseException as exc:
            # Commit fallido (o cualquier error tras el registro durable) ⇒
            # la revisión durable NO puede sobrevivir a la petición fallida.
            # R15.5 (P0): compensación verificada vía coordinador; doble
            # fallo ⇒ estado inconsistente explícito (nunca «restaurada»).
            tx.fallar(exc)
    tx.exito()
    # R15.5 (HIGH-01): fase 2 del aprendizaje — efecto OPCIONAL posterior al
    # commit principal. La confirmación humana ya está commiteada de forma
    # transaccional; si el dataset falla aquí, se devuelve éxito con
    # `advertencia_aprendizaje` (sin revertir la revisión), y una petición
    # fallida (503/409 anterior) NUNCA deja ejemplos entrenados.
    if datos_aprendizaje is not None and advertencia_aprendizaje is None:
        try:
            from aprendizaje_video_airbag import guardar_ejemplo_evento
            ejemplo_aprendido = guardar_ejemplo_evento(
                ruta_local, frame_index=int(solicitud.frame_index),
                bbox_norm=datos_aprendizaje["zona"],
                bbox_evento_norm=datos_aprendizaje["bbox_evento"],
                tipo_camara=datos_aprendizaje["tipo_camara"],
                tiempo_ms=tiempo_confirmado, fps=datos_aprendizaje["fps_item"],
                usuario=solicitud.usuario)
        except Exception as exc:  # La revisión manual nunca debe perderse por un fallo del dataset.
            advertencia_aprendizaje = f"{type(exc).__name__}: {exc}"
    diferencia_cliente_ms = None
    if tiempo_confirmado is not None and solicitud.tiempo_ms is not None:
        try:
            diferencia_cliente_ms = round(float(solicitud.tiempo_ms) - float(tiempo_confirmado), 6)
        except (TypeError, ValueError):
            diferencia_cliente_ms = None
    resultado = {
        "revision": revision, "consenso": consenso, "guardado": True,
        "revision_documento": revision_documento,
        "tiempo_resuelto": tiempo_resuelto,
        "diferencia_cliente_ms": diferencia_cliente_ms,
        "ejemplo_aprendido": ejemplo_aprendido,
        "localizacion_nacimiento": localizacion_nacimiento,
        "advertencia_aprendizaje": advertencia_aprendizaje,
    }
    _regenerar_excel(resultado)
    return resultado


@app.post("/api/video/maximo")
def confirmar_maximo_video(solicitud: SolicitudMaximoVideo):
    """El revisor marca máximo visible; no equivale a apertura/inflado completo."""
    with _pipeline_lock, _video_reanalisis_lock:
        # R15.2 (CRÍTICO-02): mismo criterio de slot que el resto de guards;
        # antes no contemplaba el slot reservado ni el hilo vivo sin estado.
        if (_pipeline_estado.get("estado") in {
                "procesando", "pausando", "pausado", "cancelando", "reanudando"}
                or _slot_pipeline_ocupado_locked()
                or (_video_reanalisis_hilo is not None and _video_reanalisis_hilo.is_alive())):
            raise HTTPException(409, "Termina o detén el procesamiento antes de confirmar el máximo.")
        datos = _cargar_datos() or {}
        # R15 (MEDIA-14): CAS de documento también al confirmar el máximo.
        _verificar_expected_revision(solicitud.expected_revision, datos, estricto=True)
        fila = next((f for f in datos.get("resultados", [])
                     if _id_fila(f) == solicitud.prueba_id), None)
        if fila is None:
            raise HTTPException(404, "No existe el ID solicitado.")
        inicial = _fila_publica(fila)["revision"]["estado"]
        gestor = GestorAprendizaje(CONFIG)
        if gestor.estado_revision("carpeta", solicitud.prueba_id, inicial)["estado"] == "completada":
            raise HTTPException(409, "Reabre la revisión antes de confirmar un máximo.")
        item = next((v for v in fila.get("videos", [])
                     if str(v.get("id")) == solicitud.video_id), None)
        if item is None:
            raise HTTPException(404, "Vídeo no encontrado en este ID.")
        raiz = _resolver_raiz_datos(datos)
        if raiz is None:
            raise HTTPException(503, "La raíz del lote no está disponible en este equipo.")
        ruta = _resolver_imagen(str(item.get("ruta") or ""), datos, raiz)
        if not ruta.is_relative_to(raiz):
            raise HTTPException(403, "Vídeo fuera de la raíz permitida.")
        import cv2
        cap = cv2.VideoCapture(str(ruta))
        try:
            if not cap.isOpened():
                raise HTTPException(422, "No se pudo abrir el vídeo para confirmar el máximo.")
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total and solicitud.frame_index >= total:
                raise HTTPException(416, f"El vídeo sólo contiene {total} cuadros.")
            cap.set(cv2.CAP_PROP_POS_FRAMES, solicitud.frame_index)
            ok, imagen = cap.read()
            if not ok or imagen is None:
                raise HTTPException(422, "El cuadro no se puede decodificar; no se guardó un máximo.")
        finally:
            cap.release()
        from video_airbag import fps_real_item, resolver_tiempo_frame
        apertura = item.get("revision_manual") or {}
        if (apertura.get("estado") != "confirmado"
                or apertura.get("frame_index") is None):
            raise HTTPException(409, "Primero confirma la ruptura en este vídeo; después marca su máximo visible.")
        if solicitud.frame_index < int(apertura["frame_index"]):
            raise HTTPException(422, "El máximo no puede estar antes de la ruptura confirmada.")
        resuelto = resolver_tiempo_frame(
            ruta, solicitud.frame_index, fps_preferido=fps_real_item(item),
            timestamp_inicial_ms=item.get("overlay_timestamp_inicial_ms"), config=CONFIG)
        resuelto["timestamp_inicial_ms"] = item.get("overlay_timestamp_inicial_ms")
        from maximos_video import guardar_maximo
        try:
            revision = guardar_maximo(ruta, frame_index=solicitud.frame_index,
                tiempo_resuelto=resuelto, usuario=solicitud.usuario, case_key=fila.get("case_key"))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "No se pudo guardar el máximo. Se conserva la revisión anterior; reintenta.") from exc
        # Guardado durable antes de invalidar vista/exportar. No se toca el
        # JSON de resultados ni se entrena con una etiqueta temporal distinta.
        _cache.update({"mtime": None, "datos": None})
    resultado = {"guardado": True, "despliegue_maximo": revision, "tiempo_resuelto": resuelto,
                 "revision_documento": int((datos or {}).get("revision_documento") or 0)}
    _regenerar_excel(resultado)
    return resultado


@app.post("/api/video/refinar-zona-apertura")
def refinar_zona_apertura_video(solicitud: SolicitudRefinarZonaVideo):
    """Propone una microzona exacta dentro de la ROI sin modificar el aprendizaje."""
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    fila = next((f for f in datos.get("resultados", []) if _id_fila(f) == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "No existe el ID solicitado.")
    video_item = next((v for v in (fila.get("videos") or []) if str(v.get("id")) == solicitud.video_id), None)
    if video_item is None:
        raise HTTPException(404, "Video no encontrado en este ID.")
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "La raíz del lote no está disponible en este equipo.")
    ruta_local = _resolver_imagen(str(video_item.get("ruta") or ""), datos, raiz)
    try:
        bbox = validar_bbox_normalizado(solicitud.bbox_norm)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        from aprendizaje_video_airbag import localizar_nacimiento_evento
        resultado = localizar_nacimiento_evento(
            ruta_local, frame_index=int(solicitud.frame_index), bbox_norm=bbox)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"guardado": False, "video_id": solicitud.video_id, **resultado}


@app.post("/api/video/zona-aprendizaje")
def aprender_zona_video(solicitud: SolicitudZonaVideo):
    """Guarda una zona supervisada y reprocesa el video con ese aprendizaje."""
    # R15 (ALTA-07): guard servidor autoritativo antes de cualquier efecto.
    _guard_mutacion_video("aprender la zona")
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    _verificar_expected_revision(solicitud.expected_revision, datos, estricto=True)
    fila = next((f for f in datos.get("resultados", []) if _id_fila(f) == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "No existe el ID solicitado.")
    video_item = next((v for v in (fila.get("videos") or []) if str(v.get("id")) == solicitud.video_id), None)
    if video_item is None:
        raise HTTPException(404, "Video no encontrado en este ID.")
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "La raíz del lote no está disponible en este equipo.")
    ruta_local = _resolver_imagen(str(video_item.get("ruta") or ""), datos, raiz)
    # R15 (ALTA-07): pre-chequeo ANTES de guardar la zona aprendida.
    _verificar_revision_no_completada(solicitud.prueba_id, fila, "aprender la zona")
    try:
        bbox = validar_bbox_normalizado(solicitud.bbox_norm)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    from aprendizaje_video_airbag import (
        ErrorPersistenciaAprendizaje,
        guardar_zona_aprendida,
        perfil_zona_aprendida,
        resumen_aprendizajes,
    )
    from video_airbag import analizar_video, consenso_videos
    # R15.4 (MEDIUM-02): flujo de TRES etapas — (1) entrada corta al lock:
    # CAS + ROI bajo exclusión; (2) análisis pesado FUERA del lock; (3)
    # reentrada corta: CAS fresco + commit. La reserva de operación da 423
    # inmediato a una operación concurrente incompatible sobre el mismo
    # video. Si el CAS o el commit de la etapa 3 fallan, la ROI se COMPENSA
    # (ALTO-02/HIGH-01: petición fallida ⇒ cero efectos persistentes).
    recurso = _recurso_video(solicitud.prueba_id, solicitud.video_id)
    _reservar_operacion(recurso, "aprendizaje de ROI con reanálisis")
    # R15.5 (P0): política transaccional común (coordinador multi-almacén).
    tx = TransaccionMultiAlmacen("aprendizaje de ROI con reanálisis",
                                 recurso=recurso)
    try:
        with _lock_documento():
            datos_frescos = _leer_documento_disco()
            _verificar_expected_revision(solicitud.expected_revision, datos_frescos,
                                                    estricto=True)
            fila_fresca, item_fresco = _localizar_fila_video(
                datos_frescos, solicitud.prueba_id, solicitud.video_id)
            _verificar_revision_no_completada(solicitud.prueba_id, fila_fresca,
                                              "aprender la zona")
            snapshot_zona = tx.capturar(
                "zona aprendida",
                lambda: perfil_zona_aprendida(ruta_local),
                lambda estado: _restaurar_zona_aprendida(ruta_local, estado))
            try:
                perfil = guardar_zona_aprendida(
                    ruta_local, bbox, tipo_camara=solicitud.tipo_camara,
                    frame_index=solicitud.frame_index, usuario=solicitud.usuario)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            except ErrorPersistenciaAprendizaje as exc:
                raise HTTPException(503, f"La ROI no se guardó: {exc}") from exc
            tx.aplicado()  # la ROI nueva QUEDÓ persistida
        # Etapa 2 — análisis pesado FUERA del lock documental.
        try:
            nuevo = analizar_video(ruta_local, CONFIG, usar_cache=False)
        except ValueError as exc:
            # Contrato existente: la ROI explícita del usuario se conserva
            # (queda en aprendizajes con su historial) y el documento no se
            # toca; el reanálisis puede reintentarse.
            raise HTTPException(422, str(exc)) from exc
        # Etapa 3 — reentrada corta: CAS fresco + commit.
        with _lock_documento():
            try:
                datos_frescos = _leer_documento_disco()
                _verificar_expected_revision(solicitud.expected_revision,
                                             datos_frescos, estricto=True)
                fila_fresca, item_fresco = _localizar_fila_video(
                    datos_frescos, solicitud.prueba_id, solicitud.video_id)
                _verificar_revision_no_completada(solicitud.prueba_id, fila_fresca,
                                                  "aprender la zona")
                # R15 (ALTA-06): mismo patrón que el reanálisis global — conservar
                # metadatos de inventario Y datos humanos, clear(), cargar el nuevo
                # resultado y reponer. Ningún campo obsoleto de la detección anterior
                # sobrevive; ninguna revisión manual se pierde.
                conservar = {k: item_fresco.get(k) for k in (
                    "id", "ruta_relativa", "carpeta_video", "revision_manual",
                    "ultima_zona_nacimiento") if item_fresco.get(k) is not None}
                item_fresco.clear()
                item_fresco.update(nuevo)
                item_fresco.update(conservar)
                consenso = consenso_videos(fila_fresca.get("videos") or [], CONFIG)
                _aplicar_consenso_video_a_fila(fila_fresca, consenso)
                revision_documento = _commit_documento(datos_frescos)
            except BaseException as exc:
                # R15.3 (ALTO-02) + R15.4: 409/commit fallido tras la ROI ⇒
                # compensar; la compensación no enmascara el error original.
                # R15.5 (P0/MEDIUM-05): vía coordinador — restauración
                # VERIFICADA; doble fallo ⇒ estado inconsistente explícito y
                # el mensaje nunca afirma «revertida» cuando no lo fue.
                tx.fallar(exc)
        tx.exito()
    finally:
        _liberar_operacion(recurso)
    resultado = {
        "guardado": True, "perfil": perfil, "video": item_fresco,
        "consenso": consenso, "aprendizaje": resumen_aprendizajes(),
        "revision_documento": revision_documento,
    }
    _regenerar_excel(resultado)
    return resultado


@app.post("/api/video/zona-revertir")
def revertir_zona_video(solicitud: SolicitudZonaRevertir):
    """V15.9.1 (A1) + V15.9.2 (C3/C4): revierte la ROI de forma transaccional.

    Orden de operaciones seguro:
    1. Pre-chequeo: el video existe y su primer cuadro se puede decodificar.
    2. Snapshot del perfil de zona actual (para rollback).
    3. Reversión persistida con escritura VERIFICADA (C3: si el JSON no se
       guarda, se reporta el fallo y no se declara éxito).
    4. Reanálisis + consenso + JSON de resultados. Si CUALQUIER paso falla,
       el snapshot se restaura (rollback, C4) y se informa con precisión.
    Revertir nunca destruye la ROI desplazada: también entra al historial.
    """
    # R15 (ALTA-07): guard servidor autoritativo antes de cualquier efecto.
    _guard_mutacion_video("revertir la zona")
    datos = _cargar_datos()
    if not datos:
        raise HTTPException(404, "Sin datos procesados.")
    _verificar_expected_revision(solicitud.expected_revision, datos, estricto=True)
    fila = next((f for f in datos.get("resultados", []) if _id_fila(f) == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "No existe el ID solicitado.")
    video_item = next((v for v in (fila.get("videos") or []) if str(v.get("id")) == solicitud.video_id), None)
    if video_item is None:
        raise HTTPException(404, "Video no encontrado en este ID.")
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "La raíz del lote no está disponible en este equipo.")
    ruta_local = _resolver_imagen(str(video_item.get("ruta") or ""), datos, raiz)
    # R15 (ALTA-07): pre-chequeo de revisión completada ANTES de efectos
    # persistentes; en el commit se revalida contra el documento fresco.
    _verificar_revision_no_completada(solicitud.prueba_id, fila, "revertir la zona")
    from aprendizaje_video_airbag import (
        ErrorPersistenciaAprendizaje,
        historial_zona_aprendida,
        perfil_zona_aprendida,
        revertir_zona_aprendida,
        resumen_aprendizajes,
    )
    from video_airbag import analizar_video, consenso_videos

    # R15.4 (MEDIUM-02): misma reserva de recurso que aprender_zona_video;
    # el análisis de la reversión también corre fuera del lock documental.
    recurso = _recurso_video(solicitud.prueba_id, solicitud.video_id)
    _reservar_operacion(recurso, "reversión de ROI con reanálisis")
    # R15.5 (P0): política transaccional común (coordinador multi-almacén).
    tx = TransaccionMultiAlmacen("reversión de ROI con reanálisis",
                                 recurso=recurso)
    try:
        # 1) Pre-chequeo de decodificación: fallar aquí no toca nada persistente.
        if not Path(ruta_local).is_file():
            raise HTTPException(404, "El archivo de video no está disponible en este equipo.")
        try:
            import cv2 as _cv2
            cap = _cv2.VideoCapture(str(ruta_local))
            try:
                ok, cuadro = cap.read()
            finally:
                cap.release()
            if not ok or cuadro is None:
                raise ValueError("No se pudo decodificar el primer cuadro del video.")
        except ValueError as exc:
            raise HTTPException(422, f"Reversión no iniciada: {exc}") from exc

        # 2) Snapshot para rollback ANTES de mutar el aprendizaje (R15.5 P0:
        #    registrado en el coordinador con restauración verificada).
        snapshot = tx.capturar(
            "zona aprendida",
            lambda: perfil_zona_aprendida(ruta_local),
            lambda estado: _restaurar_zona_aprendida(ruta_local, estado))
        historial_previo = historial_zona_aprendida(ruta_local)

        # 3) Reversión con escritura verificada (C3).
        try:
            perfil = revertir_zona_aprendida(ruta_local, usuario=solicitud.usuario,
                                             indice=solicitud.indice)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ErrorPersistenciaAprendizaje as exc:
            raise HTTPException(503, f"La ROI no cambió: {exc}") from exc
        tx.aplicado()  # la reversión QUEDÓ persistida

        # 4) Reanálisis y persistencia de resultados; rollback ante cualquier fallo.
        #    R15 (ALTA-03 + MEDIA-14): el commit se hace sobre el documento MÁS
        #    RECIENTE bajo lock, con CAS; si el commit se rechaza, la reversión
        #    del aprendizaje también se deshace (nada queda a medias, C4).
        # R15.5 (P0/MEDIUM-05): compensación VERIFICADA vía coordinador;
        # doble fallo ⇒ estado inconsistente explícito + bloqueo del recurso,
        # nunca «se deshizo» cuando no se deshizo.
        try:
            nuevo = analizar_video(ruta_local, CONFIG, usar_cache=False)
            with _lock_documento():
                datos_frescos = _leer_documento_disco()
                _verificar_expected_revision(solicitud.expected_revision, datos_frescos,
                                                    estricto=True)
                fila_fresca, item_fresco = _localizar_fila_video(
                    datos_frescos, solicitud.prueba_id, solicitud.video_id)
                _verificar_revision_no_completada(solicitud.prueba_id, fila_fresca,
                                                  "revertir la zona")
                # R15 (ALTA-06): conservar metadatos de inventario Y datos
                # humanos, clear(), cargar el nuevo resultado y reponer.
                conservar = {k: item_fresco.get(k) for k in (
                    "id", "ruta_relativa", "carpeta_video", "revision_manual",
                    "ultima_zona_nacimiento") if item_fresco.get(k) is not None}
                item_fresco.clear()
                item_fresco.update(nuevo)
                item_fresco.update(conservar)
                consenso = consenso_videos(fila_fresca.get("videos") or [], CONFIG)
                _aplicar_consenso_video_a_fila(fila_fresca, consenso)
                revision_documento = _commit_documento(datos_frescos)
        except BaseException as exc:
            _cache.update({"mtime": None, "datos": None})
            try:
                tx.fallar(exc)
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001 — error original ya compensado
                raise HTTPException(500, (
                    f"La reversión se DESHIZO porque un paso posterior falló "
                    f"({type(exc).__name__}: {exc}). Los efectos externos "
                    "fueron restaurados; la solicitud no produjo efectos "
                    "persistentes.")) from exc
        tx.exito()
        _cache.update({"mtime": None, "datos": None})
        resultado = {
            "revertido": True, "perfil": perfil, "video": item_fresco,
            "consenso": consenso, "aprendizaje": resumen_aprendizajes(),
            "historial_roi": historial_zona_aprendida(ruta_local),
            "roi_anterior": list(historial_previo[0]["bbox_norm"]) if historial_previo else None,
            "escritura_verificada": True,
            "revision_documento": revision_documento,
        }
        _regenerar_excel(resultado)
        return resultado


    finally:
        _liberar_operacion(recurso)


@app.get("/api/imagen/orientada")
def imagen_orientada(ruta: str, rotacion: float = 0, ajuste: float = 0.0):
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


class RegionAjustada(BaseModel):
    bbox: list[int] = Field(min_length=4, max_length=4)
    texto: str = Field(min_length=1, max_length=8192)
    poligono: list[list[float]] | None = None
    orientacion_base: int = 0
    ajuste: float = Field(default=0.0, ge=-45.0, le=45.0)
    variante: str = Field(default="auto", pattern="^(auto|original|clahe|adaptativa|relieve)$")
    tipo_esperado: str = Field(default="auto", pattern="^(auto|codigo|fecha|numero|texto)$")


class SolicitudZona(BaseModel):
    prueba_id: str
    imagen_id: str
    bbox: list[int] = Field(min_length=4, max_length=4)
    accion: str = "previsualizar"
    releer: bool = False
    firma: str = ""
    texto: str = Field(default="", max_length=8192)
    # V14.12: las uniones humanas pueden entrar al dataset visual. Se deja
    # activo por defecto porque la unión ya es una confirmación explícita del
    # usuario, pero el frontend permite desactivarlo para zonas excepcionales.
    proponer_entrenamiento: bool = True
    poligono: list[list[float]] | None = None
    exacta: bool = False
    origen: list[int] | None = None
    regiones: list[RegionAjustada] = Field(default_factory=list, max_length=2)


class SolicitudLecturasOrientacion(BaseModel):
    prueba_id: str
    imagen_id: str
    bbox: list[int] = Field(min_length=4, max_length=4)
    poligono: list[list[float]] | None = None


class SolicitudLecturaManual(BaseModel):
    """Relectura explícita de una caja/polígono con parámetros elegidos por el revisor."""
    prueba_id: str
    imagen_id: str
    bbox: list[int] = Field(min_length=4, max_length=4)
    poligono: list[list[float]] | None = None
    orientacion_base: int = 0
    ajuste_manual: float = Field(default=0.0, ge=-45.0, le=45.0)
    variante: str = Field(default="auto", pattern="^(auto|original|clahe|adaptativa|relieve)$")
    tipo_esperado: str = Field(default="auto", pattern="^(auto|codigo|fecha|numero|texto)$")


def _validar_poligono_recorte(poligono, dimensiones):
    """Valida cuatro esquinas en coordenadas OCR y devuelve float32.

    El orden esperado es superior-izquierda, superior-derecha,
    inferior-derecha, inferior-izquierda. Se admite una pequeña tolerancia
    numérica para puntos situados justo sobre el borde de la imagen.
    """
    if poligono is None:
        return None
    import numpy as np
    puntos = np.asarray(poligono, dtype=np.float32)
    if puntos.shape != (4, 2) or not np.isfinite(puntos).all():
        raise ValueError("El recorte inclinado debe contener exactamente cuatro esquinas válidas.")
    if len(dimensiones or []) != 2:
        raise ValueError("No se conocen las dimensiones de la imagen para validar el recorte inclinado.")
    ancho, alto = float(dimensiones[0]), float(dimensiones[1])
    if ancho <= 1 or alto <= 1:
        raise ValueError("Las dimensiones de la imagen no son válidas.")
    if ((puntos[:, 0] < -0.5).any() or (puntos[:, 1] < -0.5).any() or
            (puntos[:, 0] > ancho - 0.5).any() or (puntos[:, 1] > alto - 0.5).any()):
        raise ValueError("El recorte inclinado queda fuera de la imagen.")
    # Evita polígonos degenerados o cruzados. El área shoelace también impide
    # que cuatro puntos prácticamente colineales lleguen a warpPerspective.
    x, y = puntos[:, 0], puntos[:, 1]
    area = 0.5 * abs(float((x * np.roll(y, -1) - y * np.roll(x, -1)).sum()))
    if area < 4.0:
        raise ValueError("El recorte inclinado es demasiado pequeño.")
    return puntos


def _recortar_region_revisada(foto, bbox, poligono=None):
    """Recorta una región rectangular o rectifica un rectángulo inclinado."""
    import cv2
    import numpy as np
    if poligono is None:
        x, y, w, h = [int(v) for v in bbox]
        return foto[y:y + h, x:x + w]
    puntos = _validar_poligono_recorte(poligono, [foto.shape[1], foto.shape[0]])
    ancho_sup = np.linalg.norm(puntos[1] - puntos[0])
    ancho_inf = np.linalg.norm(puntos[2] - puntos[3])
    alto_izq = np.linalg.norm(puntos[3] - puntos[0])
    alto_der = np.linalg.norm(puntos[2] - puntos[1])
    rw = max(2, int(round(max(ancho_sup, ancho_inf))))
    rh = max(2, int(round(max(alto_izq, alto_der))))
    destino = np.array([[0, 0], [rw - 1, 0], [rw - 1, rh - 1], [0, rh - 1]], dtype=np.float32)
    matriz = cv2.getPerspectiveTransform(puntos, destino)
    return cv2.warpPerspective(foto, matriz, (rw, rh), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)


def _leer_variantes_caja_exacta(fila, item, bbox, poligono=None):
    """Lee una caja exacta en 0/90/180/270 sin alterar ni bloquear la revisión.

    Esta ruta es deliberadamente de solo lectura: no expande la caja, no consulta
    anotaciones de edición y no exige confirmar la orientación regional. Así, el
    editor puede mostrar siempre las cuatro propuestas del bloque que el usuario
    seleccionó, incluso cuando esa caja proviene de una región OCR dudosa.
    """
    from utilidades.edicion_zonas import validar_caja
    import cv2
    from ocr_engine import cargar_imagen, obtener_motor, _leer_recorte_orientado

    datos = _cargar_datos()
    gestor = GestorAprendizaje(CONFIG)
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "La raíz de imágenes no está disponible.")
    ruta = _resolver_imagen(str(item["ruta"]), datos, raiz)
    ocr = _aplicar_correcciones_publicas(item.get("resultado_ocr") or {},
                                         gestor.listar_correcciones_texto([ruta]))
    ocr = gestor.filtrar_no_texto(ocr, ruta)
    validar_caja(bbox, ocr.get("dimensiones") or [])

    manual = float(ocr.get("rotacion_manual_aplicada_grados") or 0)
    prioritaria = bool(ocr.get("orientacion_manual_prioritaria"))
    giro = manual if prioritaria else manual + _orientacion_base_publica(ocr)
    ajuste = 0 if prioritaria else float(ocr.get("deskew_texto_aplicado_grados")
                                        or ocr.get("deskew_aplicado_grados") or 0)
    cache_key = None
    try:
        stat = ruta.stat()
        aprendizaje_mtime = gestor.db.stat().st_mtime_ns if gestor.db.exists() else 0
        firma_poligono = (tuple(round(float(v), 3) for punto in poligono for v in punto)
                          if poligono is not None else None)
        cache_key = (str(ruta), stat.st_mtime_ns, stat.st_size, tuple(int(v) for v in bbox),
                     firma_poligono, round(giro % 360, 3), round(ajuste, 3), aprendizaje_mtime)
    except OSError:
        # Las pruebas usan imágenes simuladas. En una ruta real inexistente,
        # cargar_imagen seguirá informando el error; no se cachea el resultado.
        pass
    if cache_key is not None:
        with _variantes_lectura_lock:
            cacheado = _variantes_lectura_cache.get(cache_key)
        if cacheado is not None:
            return deepcopy(cacheado)

    foto = cargar_imagen(str(ruta))
    foto = rotar_imagen_libre(foto, giro)
    alto, ancho = foto.shape[:2]
    if abs(ajuste) >= .05:
        matriz = cv2.getRotationMatrix2D((ancho / 2, alto / 2), ajuste, 1)
        foto = cv2.warpAffine(foto, matriz, (ancho, alto), flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)
    if [ancho, alto] != list(ocr.get("dimensiones") or []):
        raise HTTPException(409, "El marco de la imagen cambió; reprocesa esta imagen antes de releer el bloque.")

    x, y, w, h = bbox
    poligono_validado = _validar_poligono_recorte(poligono, ocr.get("dimensiones") or []) if poligono is not None else None
    recorte = _recortar_region_revisada(foto, bbox, poligono_validado)
    if recorte.size == 0:
        raise HTTPException(400, "La región seleccionada no contiene píxeles.")
    alto_recorte, ancho_recorte = recorte.shape[:2]
    escala = min(3.0, max(1.0, 160 / min(ancho_recorte, alto_recorte)), 2400 / max(ancho_recorte, alto_recorte))
    if abs(escala - 1) > .01:
        recorte = cv2.resize(recorte, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
    motor, _ = obtener_motor(CONFIG)
    ajuste_cfg = CONFIG.get("fase1", {}).get("preprocesamiento", {}).get("ajuste_fino_regiones", {})
    _, orientacion = _leer_recorte_orientado(
        recorte, motor,
        ajuste_fino=bool(ajuste_cfg.get("activar", True)),
        ajuste_fino_todas=bool(ajuste_cfg.get("todas_variantes_editor", True)),
        angulo_fino_min=float(ajuste_cfg.get("angulo_minimo", 1.25)),
        angulo_fino_max=float(ajuste_cfg.get("angulo_maximo", 15.0)),
        angulo_fino_extendido_max=float(ajuste_cfg.get("angulo_maximo_extendido", 30.0)),
        micro_ajuste_grados=float(ajuste_cfg.get("micro_ajuste_grados", 2.0)))
    candidatos = list(orientacion.get("candidatos_orientacion") or [])
    por_angulo = {int(c.get("grados", -1)): c for c in candidatos}
    # Conserva el orden de calidad que ya entrega el motor (como en el panel
    # clásico) y agrega al final cualquier ángulo ausente como lectura vacía.
    completos = []
    presentes = set()
    for c in candidatos:
        grados = int(c.get("grados", -1))
        if grados not in (0, 90, 180, 270) or grados in presentes:
            continue
        presentes.add(grados)
        completos.append({"grados": grados,
                          "grados_efectivos": float(c.get("grados_efectivos", grados)),
                          "ajuste_fino_grados": float(c.get("ajuste_fino_grados") or 0),
                          "confianza": float(c.get("confianza") or 0),
                          "texto": str(c.get("texto") or ""),
                          "confianza_base": float(c.get("confianza_base", c.get("confianza") or 0)),
                          "texto_base": str(c.get("texto_base", c.get("texto") or "")),
                          "recomendada": bool(c.get("recomendada")),
                          "probable_codigo": bool(c.get("probable_codigo")),
                          "tipo_codigo_probable": str(c.get("tipo_codigo_probable") or ""),
                          "mayus_minus_coherente": bool(c.get("mayus_minus_coherente", True)),
                          "longitud_util": int(c.get("longitud_util") or 0),
                          "tipo_informacion": str(c.get("tipo_informacion") or "ruido"),
                          "etiqueta_informacion": str(c.get("etiqueta_informacion") or "Lectura"),
                          "score_informacion": float(c.get("score_informacion") or 0),
                          "es_ruido": bool(c.get("es_ruido")),
                          "recomendacion_util": bool(c.get("recomendacion_util", not c.get("es_ruido"))),
                          "razones_congruencia": list(c.get("razones_congruencia") or []),
                          "consenso": int(c.get("consenso") or 1),
                          "similitud_consenso": float(c.get("similitud_consenso") or 0),
                          "ajuste_fino_confiable": bool(c.get("ajuste_fino_confiable")),
                          "ajuste_fino_modo": str(c.get("ajuste_fino_modo") or "ninguno"),
                          "evidencia_geometrica": dict(c.get("evidencia_geometrica") or {})})
    for grados in (0, 90, 180, 270):
        if grados not in presentes:
            completos.append({"grados": grados, "grados_efectivos": float(grados),
                              "ajuste_fino_grados": 0.0, "confianza": 0.0, "texto": "",
                              "confianza_base": 0.0, "texto_base": "",
                              "recomendada": False, "probable_codigo": False,
                              "tipo_codigo_probable": "", "mayus_minus_coherente": True,
                              "longitud_util": 0, "tipo_informacion": "ruido",
                              "etiqueta_informacion": "Sin lectura", "score_informacion": 0.0,
                              "es_ruido": True, "recomendacion_util": False, "razones_congruencia": [], "consenso": 1,
                              "similitud_consenso": 0.0, "ajuste_fino_confiable": False,
                              "ajuste_fino_modo": "ninguno", "evidencia_geometrica": {}})
    contexto_estrategia = {
        "project_id": fila.get("project_id"), "tipo_st": fila.get("tipo_st"),
        "module_version": fila.get("module_version"), "fase": item.get("fase"),
        "campo": "etiqueta",
    }
    sugerir_estrategia = getattr(gestor, "sugerir_estrategia_ocr", None)
    estrategia_aprendida = (sugerir_estrategia(
        ruta, bbox, ocr.get("dimensiones") or [ancho, alto], contexto_estrategia)
        if callable(sugerir_estrategia) else None)
    candidata_aprendida = None
    if estrategia_aprendida and estrategia_aprendida.get("nivel") in {"inmediata", "sugerida", "automatica"}:
        try:
            candidata_aprendida = _leer_angulo_manual_caja_exacta(
                fila, item, bbox, estrategia_aprendida.get("orientacion_base", 0),
                estrategia_aprendida.get("ajuste", 0), estrategia_aprendida.get("variante", "auto"),
                estrategia_aprendida.get("tipo_esperado", "auto"), poligono=poligono)
            candidata_aprendida["origen_aprendizaje"] = True
            candidata_aprendida["soporte_aprendizaje"] = int(estrategia_aprendida.get("soporte") or 0)
            candidata_aprendida["dominancia_aprendizaje"] = float(estrategia_aprendida.get("dominancia") or 0)
        except Exception:
            candidata_aprendida = None
    respuesta = {
        "bbox": list(bbox), "poligono": poligono, "candidatos_orientacion": completos,
        "orientacion_recomendada_grados": int(orientacion.get(
            "orientacion_recomendada_grados", orientacion.get("orientacion_grados", 0)) or 0),
        "criterio_orientacion": str(orientacion.get("criterio_orientacion") or ""),
        "estrategia_aprendida": estrategia_aprendida,
        "candidata_aprendida": candidata_aprendida,
    }
    if cache_key is not None:
        with _variantes_lectura_lock:
            _variantes_lectura_cache[cache_key] = deepcopy(respuesta)
            while len(_variantes_lectura_cache) > _VARIANTES_CACHE_MAX:
                _variantes_lectura_cache.pop(next(iter(_variantes_lectura_cache)))
    return respuesta


@app.post("/api/aprendizaje/lecturas-orientacion")
def lecturas_orientacion(solicitud: SolicitudLecturasOrientacion):
    datos = _cargar_datos()
    fila = next((f for f in (datos or {}).get("resultados", [])
                 if _id_fila(f) == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "Carpeta no encontrada.")
    item = next((i for i in fila.get("imagenes", []) if i.get("id") == solicitud.imagen_id), None)
    if item is None:
        raise HTTPException(404, "Imagen no encontrada en esta carpeta.")
    try:
        return _leer_variantes_caja_exacta(fila, item, solicitud.bbox, solicitud.poligono)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _leer_angulo_manual_caja_exacta(fila, item, bbox, orientacion_base=0,
                                     ajuste_manual=0.0, variante="auto", tipo_esperado="auto",
                                     poligono=None):
    """Relee una caja exactamente en el ángulo y tratamiento pedidos por el usuario.

    No modifica resultados, aprendizaje ni orientación persistida. Es una herramienta
    de inspección: sólo devuelve una candidata que el revisor puede copiar después.
    """
    from utilidades.edicion_zonas import validar_caja
    import cv2
    from ocr_engine import (cargar_imagen, obtener_motor, aplicar_variante,
                            reconstruir_lineas_texto, _perfil_congruencia_region)

    base = int(orientacion_base) % 360
    if base not in (0, 90, 180, 270):
        raise ValueError("La orientación base manual debe ser 0, 90, 180 o 270 grados.")
    ajuste = float(ajuste_manual)
    if not -45.0 <= ajuste <= 45.0:
        raise ValueError("El ajuste manual debe estar entre -45° y +45°.")
    variante = str(variante or "auto").lower()
    permitidas = ("auto", "original", "clahe", "adaptativa", "relieve")
    if variante not in permitidas:
        raise ValueError("Tratamiento visual manual no válido.")
    tipo_esperado = str(tipo_esperado or "auto").lower()
    if tipo_esperado not in ("auto", "codigo", "fecha", "numero", "texto"):
        raise ValueError("Tipo de información esperado no válido.")

    datos = _cargar_datos()
    gestor = GestorAprendizaje(CONFIG)
    raiz = _resolver_raiz_datos(datos)
    if raiz is None:
        raise HTTPException(503, "La raíz de imágenes no está disponible.")
    ruta = _resolver_imagen(str(item["ruta"]), datos, raiz)
    ocr = _aplicar_correcciones_publicas(item.get("resultado_ocr") or {},
                                         gestor.listar_correcciones_texto([ruta]))
    ocr = gestor.filtrar_no_texto(ocr, ruta)
    validar_caja(bbox, ocr.get("dimensiones") or [])

    manual_global = float(ocr.get("rotacion_manual_aplicada_grados") or 0)
    prioritaria = bool(ocr.get("orientacion_manual_prioritaria"))
    giro_global = manual_global if prioritaria else manual_global + _orientacion_base_publica(ocr)
    deskew_global = 0 if prioritaria else float(ocr.get("deskew_texto_aplicado_grados")
                                               or ocr.get("deskew_aplicado_grados") or 0)
    foto = cargar_imagen(str(ruta))
    foto = rotar_imagen_libre(foto, giro_global)
    alto, ancho = foto.shape[:2]
    if abs(deskew_global) >= .05:
        matriz = cv2.getRotationMatrix2D((ancho / 2, alto / 2), deskew_global, 1)
        foto = cv2.warpAffine(foto, matriz, (ancho, alto), flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)
    if [ancho, alto] != list(ocr.get("dimensiones") or []):
        raise HTTPException(409, "El marco de la imagen cambió; reprocesa esta imagen antes de releer el bloque.")

    x, y, w, h = [int(v) for v in bbox]
    poligono_validado = _validar_poligono_recorte(poligono, ocr.get("dimensiones") or []) if poligono is not None else None
    recorte = _recortar_region_revisada(foto, bbox, poligono_validado)
    if recorte.size == 0:
        raise HTTPException(400, "La región seleccionada no contiene píxeles.")
    alto_recorte, ancho_recorte = recorte.shape[:2]
    escala = min(3.0, max(1.0, 160 / min(ancho_recorte, alto_recorte)), 2400 / max(ancho_recorte, alto_recorte))
    if abs(escala - 1) > .01:
        recorte = cv2.resize(recorte, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)

    angulo_efectivo = (base + ajuste) % 360
    vista = rotar_imagen_libre(recorte, angulo_efectivo)
    motor, _ = obtener_motor(CONFIG)
    prep = CONFIG.get("fase1", {}).get("preprocesamiento", {})
    variantes = [variante] if variante != "auto" else ["original", "clahe", "adaptativa", "relieve"]
    intentos = []
    mejor = None
    for nombre in variantes:
        procesada = aplicar_variante(vista, nombre, prep)
        lecturas = motor.leer_texto_completo(procesada) or []
        pesos = [min(32, len(str(l.get("texto") or "").strip())) for l in lecturas]
        confianza = (sum(float(l.get("confianza") or 0) * peso
                          for l, peso in zip(lecturas, pesos)) / max(1, sum(pesos)))
        perfil = _perfil_congruencia_region(lecturas, confianza)
        renglones = reconstruir_lineas_texto(lecturas)
        texto = "\n".join(str(l.get("texto") or "") for l in renglones).strip()[:2048]
        intento = {
            "variante": nombre, "texto": texto, "confianza": round(float(confianza), 4),
            "tipo_informacion": str(perfil.get("tipo_informacion") or "ruido"),
            "etiqueta_informacion": str(perfil.get("etiqueta_informacion") or "Lectura"),
            "score_informacion": round(float(perfil.get("score_informacion") or 0), 2),
            "es_ruido": bool(perfil.get("es_ruido")),
            "probable_codigo": bool(perfil.get("probable_codigo")),
            "tipo_codigo_probable": str(perfil.get("tipo") or ""),
            "razones_congruencia": list(perfil.get("razones") or []),
            "longitud_util": int(perfil.get("longitud") or 0),
            "pureza": round(float(perfil.get("pureza") or 0), 4),
            "clave": tuple(perfil.get("clave") or ()),
        }
        intentos.append(intento)
        if mejor is None or (intento["clave"], intento["confianza"]) > (mejor["clave"], mejor["confianza"]):
            mejor = intento

    if tipo_esperado != "auto":
        compatibles = [i for i in intentos if i.get("tipo_informacion") == tipo_esperado]
        if compatibles:
            mejor = max(compatibles, key=lambda i: (float(i.get("score_informacion") or 0),
                                                     float(i.get("confianza") or 0)))

    mejor = dict(mejor or {"variante": variante, "texto": "", "confianza": 0.0,
                            "tipo_informacion": "ruido", "etiqueta_informacion": "Sin lectura",
                            "score_informacion": 0.0, "es_ruido": True, "probable_codigo": False,
                            "tipo_codigo_probable": "", "razones_congruencia": [],
                            "longitud_util": 0, "pureza": 0.0, "clave": ()})
    mejor.pop("clave", None)
    for intento in intentos:
        intento.pop("clave", None)
    mejor.update({
        "orientacion_base": base, "ajuste_manual": round(ajuste, 2),
        "grados_efectivos": round(angulo_efectivo, 2), "tipo_esperado": tipo_esperado,
        "coincide_tipo_esperado": bool(tipo_esperado == "auto" or mejor.get("tipo_informacion") == tipo_esperado),
        "recomendacion_util": bool(not mejor.get("es_ruido") and float(mejor.get("score_informacion") or 0) >= 45),
        "intentos": intentos,
    })
    return mejor


@app.post("/api/aprendizaje/lectura-angulo-manual")
def lectura_angulo_manual(solicitud: SolicitudLecturaManual):
    datos = _cargar_datos()
    fila = next((f for f in (datos or {}).get("resultados", [])
                 if _id_fila(f) == solicitud.prueba_id), None)
    if fila is None:
        raise HTTPException(404, "Carpeta no encontrada.")
    item = next((i for i in fila.get("imagenes", []) if i.get("id") == solicitud.imagen_id), None)
    if item is None:
        raise HTTPException(404, "Imagen no encontrada en esta carpeta.")
    try:
        return _leer_angulo_manual_caja_exacta(
            fila, item, solicitud.bbox, solicitud.orientacion_base,
            solicitud.ajuste_manual, solicitud.variante, solicitud.tipo_esperado,
            poligono=solicitud.poligono)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


_zona_lock = threading.Lock()


@app.post("/api/aprendizaje/zonas")
def editar_zona(solicitud: SolicitudZona):
    from utilidades.edicion_zonas import (expandir, firma, guardar, deshacer,
                                          validar_caja, unidades, interseca, guardar_bloque,
                                          unidades_en_region, interseca_region)
    if solicitud.accion not in ("previsualizar", "guardar", "deshacer", "estado", "guardar_bloque"):
        raise HTTPException(400, "Acción desconocida.")
    if not _zona_lock.acquire(blocking=False):
        raise HTTPException(409, "Hay otra zona en proceso. Espera a que termine.")
    try:
        # R15.6 (ALTO-08): guard uniforme — la reserva atómica del slot
        # también bloquea (ventana entre admisión y arranque del hilo).
        _assert_pipeline_inactivo("editar zonas")
        datos = _cargar_datos()
        fila = next((f for f in (datos or {}).get("resultados", [])
                     if _id_fila(f) == solicitud.prueba_id), None)
        if fila is None:
            raise HTTPException(404, "Carpeta no encontrada.")
        item = next((i for i in fila.get("imagenes", []) if i.get("id") == solicitud.imagen_id), None)
        if item is None:
            raise HTTPException(404, "Imagen no encontrada en esta carpeta.")
        gestor = GestorAprendizaje(CONFIG)
        if gestor.estado_revision("carpeta", solicitud.prueba_id,
                                  _fila_publica(fila)["revision"]["estado"])["estado"] == "completada":
            raise HTTPException(409, "Reabre la revisión antes de editar.")
        raiz = _resolver_raiz_datos(datos)
        if raiz is None:
            raise HTTPException(503, "La raíz de imágenes no está disponible.")
        ruta = _resolver_imagen(str(item["ruta"]), datos, raiz)
        imagen_hash = hash_archivo(ruta)
        ocr = _aplicar_correcciones_publicas(item.get("resultado_ocr") or {},
                                           gestor.listar_correcciones_texto([ruta]))
        ocr = gestor.filtrar_no_texto(ocr, ruta)
        version = firma(ocr, imagen_hash)
        if solicitud.accion == "estado":
            return {"firma": version, "bbox": solicitud.bbox}
        if solicitud.accion in ("guardar", "deshacer", "guardar_bloque") and solicitud.firma != version:
            raise HTTPException(409, "La imagen cambió. Vuelve a previsualizar la zona.")
        # R15.6 (ALTO-11): las acciones de mutación y el estado de revisión
        # quedan bajo el coordinador común; fallo de revisión ⇒ restauración
        # verificada de la edición (cero efectos persistentes).
        tx = None
        if solicitud.accion in ("guardar", "deshacer", "guardar_bloque"):
            _assert_recurso_consistente(f"carpeta:{solicitud.prueba_id}",
                                        "editar la zona")
            tx = TransaccionMultiAlmacen(
                "edición de zona",
                recurso=f"carpeta:{solicitud.prueba_id}")
            tx.capturar(
                "evidencias y estado de revisión",
                lambda: gestor.snapshot_evidencias_imagen(
                    ruta, caso_id=solicitud.prueba_id),
                gestor.restaurar_evidencias_imagen)
            tx.aplicado()  # las ramas siguientes SON el efecto
        try:
            if solicitud.accion == "guardar_bloque":
                regiones = []
                for r in solicitud.regiones:
                    validar_caja(r.bbox, ocr.get("dimensiones") or [])
                    pol_solicitado = getattr(r, "poligono", None)
                    pol = (_validar_poligono_recorte(pol_solicitado, ocr.get("dimensiones") or []).tolist()
                           if pol_solicitado is not None else None)
                    regiones.append({"bbox": list(r.bbox), "texto": r.texto, "poligono": pol,
                                     "orientacion_base": int(getattr(r, "orientacion_base", 0) or 0),
                                     "ajuste": float(getattr(r, "ajuste", 0) or 0),
                                     "variante": getattr(r, "variante", "auto"),
                                     "tipo_esperado": getattr(r, "tipo_esperado", "auto")})
                # Las anotaciones manuales viven en una capa independiente. Ajustar o
                # dividir un bloque OCR no debe quedar bloqueado por una anotación que
                # se superpone: se conserva intacta y no se fusiona con el bloque OCR.
                anotaciones_superpuestas = [a for a in gestor.listar_anotaciones([ruta])
                    if any(interseca_region(r["bbox"], a.get("bbox"), r.get("poligono")) for r in regiones)]
                with gestor._conectar() as con:
                    identificador = guardar_bloque(con, imagen_hash, ocr, solicitud.origen, regiones)
                muestras, nuevas, duplicadas, advertencias = [], 0, 0, []
                estrategias_guardadas = []
                if hasattr(gestor, "registrar_muestra_visual"):
                    original = next((u for u in unidades(ocr) if list(u.get("bbox") or []) == list(solicitud.origen or [])), {})
                    contexto = {k: fila.get(k) for k in
                                ("project_id", "tipo_st", "module_version", "temperature_condition", "inflator_type")}
                    contexto.update({"fase": item.get("fase")})
                    for indice, region in enumerate(regiones, 1):
                        try:
                            muestra = gestor.registrar_muestra_visual(
                                ruta, _id_fila(fila), str(original.get("texto") or ""), region["texto"],
                                region["bbox"], accion="confirmar_entrenar", entrenable=True,
                                campo="division_bloque" if len(regiones) > 1 else "ajuste_bloque",
                                fase=item.get("fase"), tor=item.get("tor"),
                                modelo_origen=(item.get("resultado_ocr") or {}).get("modelo_visual_version")
                                or (item.get("resultado_ocr") or {}).get("motor"), usuario="dashboard",
                                metadatos={**contexto, "origen": "geometria_manual",
                                           "edicion_zona_id": identificador, "region_indice": indice,
                                           "poligono_lectura": region.get("poligono"),
                                           "giro_foto": float((item.get("resultado_ocr") or {}).get("orientacion_texto_grados") or 0)})
                            muestras.append(muestra)
                            if muestra.get("duplicada"): duplicadas += 1
                            else: nuevas += 1
                        except ValueError as exc:
                            advertencias.append(str(exc))
                        try:
                            if not hasattr(gestor, "registrar_estrategia_ocr"):
                                continue
                            estrategias_guardadas.append(gestor.registrar_estrategia_ocr(
                                ruta, region["bbox"], ocr.get("dimensiones") or [],
                                {"orientacion_base": region.get("orientacion_base", 0),
                                 "ajuste_manual": region.get("ajuste", 0),
                                 "variante": region.get("variante", "auto"),
                                 "tipo_esperado": region.get("tipo_esperado", "auto"),
                                 "texto_resultado": region["texto"], "origen": "geometria_manual"},
                                caso_id=_id_fila(fila), contexto=contexto, usuario="dashboard"))
                        except ValueError as exc:
                            advertencias.append(str(exc))
                auto_visual = (_programar_entrenamiento_visual_auto(
                    f"Geometría confirmada: {solicitud.prueba_id}/{solicitud.imagen_id}")
                    if nuevas > 0 else None)
                resultado = {"guardado": True, "edicion_id": identificador,
                             "entrenamiento": bool(muestras),
                             "muestras_geometria": muestras, "muestras_nuevas": nuevas,
                             "muestras_duplicadas": duplicadas, "estrategias": estrategias_guardadas,
                             "aprendizaje_visual_automatico": auto_visual,
                             "advertencias_entrenamiento": advertencias,
                             "anotaciones_manual_preservadas": len(anotaciones_superpuestas)}
            elif solicitud.accion == "deshacer":
                with gestor._conectar() as con:
                    cambio = deshacer(con, imagen_hash, ocr)
                resultado = {"guardado": cambio}
            else:
                validar_caja(solicitud.bbox, ocr.get("dimensiones") or [])
                poligono_solicitud = getattr(solicitud, "poligono", None)
                poligono = (_validar_poligono_recorte(poligono_solicitud, ocr.get("dimensiones") or []).tolist()
                            if poligono_solicitud is not None else None)
                # Con geometría libre no expandimos la bbox: el cuadrilátero es la
                # fuente de verdad y evita absorber texto vecino por su envolvente.
                bbox = (list(solicitud.bbox) if poligono is not None
                        else (solicitud.bbox if getattr(solicitud, "exacta", False) and solicitud.accion == "previsualizar"
                              else expandir(solicitud.bbox, ocr)))
                validar_caja(bbox, ocr.get("dimensiones") or [])
                if (not getattr(solicitud, "exacta", False) and
                        any(interseca_region(bbox, a.get("bbox"), poligono) for a in gestor.listar_anotaciones([ruta]))):
                    raise HTTPException(409, "Esta unión incluye una anotación manual de texto omitido. Ajusta el área para excluirla o usa Ajustar / dividir bloque; la anotación manual se conserva por separado.")
                afectadas = unidades_en_region(ocr, bbox, poligono)
                anterior = "\n".join(str(u.get("texto", "")) for u in afectadas)
                if solicitud.accion == "previsualizar":
                    propuesta, orientacion = anterior, {}
                    if solicitud.releer:
                        import cv2
                        from ocr_engine import cargar_imagen, obtener_motor, _leer_recorte_orientado
                        foto = cargar_imagen(str(ruta))
                        manual = float(ocr.get("rotacion_manual_aplicada_grados") or 0)
                        prioritaria = bool(ocr.get("orientacion_manual_prioritaria"))
                        giro = manual if prioritaria else manual + _orientacion_base_publica(ocr)
                        foto = rotar_imagen_libre(foto, giro)
                        ajuste = 0 if prioritaria else float(ocr.get("deskew_texto_aplicado_grados") or ocr.get("deskew_aplicado_grados") or 0)
                        alto, ancho = foto.shape[:2]
                        if abs(ajuste) >= .05:
                            matriz = cv2.getRotationMatrix2D((ancho/2, alto/2), ajuste, 1)
                            foto = cv2.warpAffine(foto, matriz, (ancho, alto), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
                        if [ancho, alto] != list(ocr.get("dimensiones") or []):
                            raise HTTPException(409, "El marco de la imagen cambió; reprocesa esta imagen antes de releer regiones.")
                        x,y,w,h = bbox
                        if poligono is None:
                            recorte = foto[y:y+h, x:x+w]
                        else:
                            recorte = _recortar_region_revisada(foto, bbox, poligono)
                        rh, rw = recorte.shape[:2]
                        escala = min(3.0, max(1.0, 160/min(rw,rh)), 2400/max(rw,rh))
                        if abs(escala-1) > .01:
                            recorte = cv2.resize(recorte, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
                        motor, _ = obtener_motor(CONFIG)
                        lecturas, orientacion = _leer_recorte_orientado(recorte, motor)
                        propuesta = "\n".join(str(u.get("texto", "")) for u in lecturas)
                    return {"bbox": bbox, "poligono": poligono, "anterior": anterior, "texto": propuesta,
                            "bloques": len(afectadas), "firma": version, **orientacion}
                if list(bbox) != solicitud.bbox:
                    raise HTTPException(409, "La selección cambió. Previsualiza otra vez antes de confirmar.")
                with gestor._conectar() as con:
                    identificador = guardar(con, imagen_hash, ocr, bbox, solicitud.texto, poligono=poligono)
                aprendizaje_union = None
                auto_visual = None
                advertencia_entrenamiento = None
                if hasattr(gestor, "registrar_union_visual"):
                    try:
                        aprendizaje_union = gestor.registrar_union_visual(
                            ruta, _id_fila(fila), solicitud.texto, bbox,
                            unidades_originales=afectadas, poligono=poligono, fase=item.get("fase"), tor=item.get("tor"),
                            modelo_origen=(item.get("resultado_ocr") or {}).get("modelo_visual_version")
                            or (item.get("resultado_ocr") or {}).get("motor"),
                            usuario="dashboard",
                            metadatos={**{k: fila.get(k) for k in
                                       ("tipo_st", "module_version", "temperature_condition", "inflator_type")},
                                       "edicion_zona_id": identificador,
                                       "giro_foto": float((item.get("resultado_ocr") or {}).get("orientacion_texto_grados") or 0)})
                        if int(aprendizaje_union.get("nuevas") or 0) > 0:
                            auto_visual = _programar_entrenamiento_visual_auto(
                                f"Unión confirmada: {solicitud.prueba_id}/{solicitud.imagen_id}")
                    except ValueError as exc:
                        # La edición humana es prioritaria: si el recorte visual no
                        # puede crearse, la unión sigue guardada y se informa aparte.
                        advertencia_entrenamiento = str(exc)
                resultado = {
                    "guardado": True, "edicion_id": identificador,
                    "entrenamiento": bool(aprendizaje_union and aprendizaje_union.get("muestras")),
                    "aprendizaje_union": aprendizaje_union,
                    "aprendizaje_visual_automatico": auto_visual,
                    "advertencia_entrenamiento": advertencia_entrenamiento,
                }
            if tx is not None:
                gestor.actualizar_revision("carpeta", solicitud.prueba_id,
                                           estado="parcial")
        except BaseException as exc:
            if tx is None:
                raise
            try:
                tx.fallar(exc)
            except HTTPException:
                raise
            except ValueError as vexc:
                raise HTTPException(400, str(vexc)) from vexc
            except Exception:  # noqa: BLE001 — fallo de almacén, compensado
                raise HTTPException(503, (
                    "No se pudo completar 'edición de zona' "
                    f"({type(exc).__name__}: {exc}). Los efectos externos "
                    "fueron restaurados; la solicitud no produjo efectos "
                    "persistentes.")) from exc
        if tx is not None:
            tx.exito()
        _regenerar_excel(resultado)
        return resultado
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        _zona_lock.release()


# Frontend estático: se monta al final para no tapar los endpoints /api.
app.mount("/", StaticFiles(directory=str(DIR_FRONTEND), html=True), name="frontend")


# R15.7 (ALTO-03): arranque fail-closed. Carga el registro durable de
# inconsistencias y ejecuta la SONDA obligatoria de escritura/lectura del
# almacén de recuperación; si el almacén no es durable, el sistema arranca en
# MODO RECUPERACIÓN aunque no exista centinela (así el escenario «registro +
# centinela no escribibles» ya no vuelve a modo normal tras reiniciar).
try:
    _SONDA_ARRANQUE = inicializar_recuperacion()
except Exception as _exc_arranque:  # noqa: BLE001 — el arranque nunca cae
    _SONDA_ARRANQUE = {"escribible": False, "releido": False,
                       "error": f"{type(_exc_arranque).__name__}: {_exc_arranque}"}
    _activar_modo_recuperacion(
        f"error inesperado durante el arranque del guard ({_exc_arranque})")


if __name__ == "__main__":
    import uvicorn
    puerto = int(CONFIG.get("dashboard", {}).get("puerto", 8000))
    print(f"Dashboard: http://127.0.0.1:{puerto}")
    uvicorn.run(app, host="127.0.0.1", port=puerto, log_level="warning")
