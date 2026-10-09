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

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
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
from utilidades.persistencia import escribir_json_seguro  # noqa: E402

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

app = FastAPI(title="OCR Versuchsmatrix", version="15.7.4")


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


class SolicitudZonaVideo(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=256)
    video_id: str = Field(min_length=1, max_length=128)
    bbox_norm: list[float] = Field(min_length=4, max_length=4)
    frame_index: int | None = Field(default=None, ge=0)
    tipo_camara: str | None = Field(default=None, max_length=64)
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


class SolicitudMaximoVideo(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=256)
    video_id: str = Field(min_length=1, max_length=128)
    frame_index: int = Field(ge=0, strict=True)
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


class SolicitudCriteriosApertura(BaseModel):
    verde_max: float = Field(ge=0, allow_inf_nan=False, strict=True)
    amarillo_max: float = Field(gt=0, allow_inf_nan=False, strict=True)
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


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


class SolicitudExportacion(BaseModel):
    idiomas: list[str] = Field(default_factory=lambda: ["es"], min_length=1, max_length=3)


class SolicitudConsolidacion(BaseModel):
    archivos: list[str] = Field(min_length=1, max_length=20)
    regenerar_excel: bool = True


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
    fila, item, region, ruta = _resolver_region_orientacion(
        solicitud.prueba_id, solicitud.imagen_id, solicitud.marco)
    gestor = GestorAprendizaje(CONFIG)
    if gestor.estado_revision("carpeta", solicitud.prueba_id,
            _fila_publica(fila)["revision"]["estado"])["estado"] == "completada":
        raise HTTPException(409, "Reabre la revisión antes de editar.")
    # No cambiar preferencias mientras el pipeline está utilizando el modelo.
    if _pipeline_hilo and _pipeline_hilo.is_alive():
        raise HTTPException(409, "Detén conservando el avance antes de cambiar la orientación regional.")
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
    resultado = gestor.marcar_no_texto(ruta, solicitud.bbox,
        str(unidad.get("texto_ocr") or unidad.get("texto") or ""),
        solicitud.usuario, activo=not solicitud.restaurar)
    gestor.actualizar_revision("carpeta", solicitud.prueba_id, estado="parcial")
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
    resultados = []
    for bbox in unicas:
        unidad = next((u for u in fuente_unidades if _bbox_igual(u.get("bbox"), bbox)), None)
        if unidad is None:
            raise HTTPException(400, f"La región {bbox} ya no coincide con una detección disponible.")
        resultados.append(gestor.marcar_no_texto(
            ruta, bbox, str(unidad.get("texto_ocr") or unidad.get("texto") or ""),
            solicitud.usuario, activo=not solicitud.restaurar))
    gestor.actualizar_revision("carpeta", solicitud.prueba_id, estado="parcial")
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
    usuario: str = Field(default="dashboard", min_length=1, max_length=128)


class SolicitudImagenVerificada(BaseModel):
    prueba_id: str = Field(min_length=1, max_length=128)
    imagen_id: str = Field(min_length=1, max_length=128)
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
    except (OSError, json.JSONDecodeError):
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
_cache_rutas_registradas: dict = {"firma": None, "rutas": set()}


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
    """Reubica una ruta registrada bajo la raíz local equivalente.

    Acepta tanto rutas absolutas como rutas relativas guardadas por el flujo
    empresarial (por ejemplo ``PHOTOS/NACH/IMG_4144.JPG``).
    """
    ruta_texto = str(ruta or "").strip()
    if not ruta_texto:
        return None
    objeto = Path(ruta_texto).expanduser()
    if objeto.is_absolute():
        directa = objeto.resolve()
        if directa.exists():
            return directa
    else:
        partes_relativas = _partes_portables(ruta_texto)
        candidata_relativa = raiz.joinpath(*partes_relativas).resolve()
        if candidata_relativa.exists() and candidata_relativa.is_relative_to(raiz):
            return candidata_relativa

    partes_ruta = _partes_portables(ruta_texto)
    partes_raiz_original = _partes_portables(str(datos.get("raiz") or ""))
    n = len(partes_raiz_original)
    if n and tuple(partes_ruta[:n]) == tuple(partes_raiz_original):
        candidata = raiz.joinpath(*partes_ruta[n:]).resolve()
        if candidata.exists() and candidata.is_relative_to(raiz):
            return candidata
    return None


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
    idiomas = _normalizar_idiomas_exportacion(datos.get("idiomas_exportacion") or ["es"])
    etiquetas = {"es": "ES", "en": "EN", "de": "DE"}
    declarados = dict(datos.get("archivos_excel") or {})
    base = Path(datos.get("nombre_excel_base") or datos.get("archivo_excel") or (RAIZ_PROYECTO / CONFIG.get(
        "fase3", {}).get("archivo_salida", "resultado_maestro.xlsx")))
    if not base.is_absolute():
        base = RAIZ_PROYECTO / base
    generados = {}
    for idioma in idiomas:
        destino = Path(declarados.get(idioma) or base)
        if not destino.is_absolute():
            destino = RAIZ_PROYECTO / destino
        if not declarados.get(idioma) and (len(idiomas) > 1 or idioma != "es"):
            destino = base.with_name(f"{base.stem}_{etiquetas[idioma]}{base.suffix}")
        generado = _generar_excel_serializado(
            RUTA_VALIDACION, destino, CONFIG, REGLAS,
            ruta_plantilla=datos.get("ruta_plantilla"), datos_validacion=datos, idioma=idioma)
        generados[idioma] = str(generado)
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
        generar_excel = _generar_excel_serializado
        ruta_plantilla = estado.get("ruta_plantilla")
        generados = {}
        for idioma in idiomas:
            sufijo = "" if len(idiomas) == 1 and idioma == "es" else f"_{etiquetas[idioma]}"
            ruta_excel = RAIZ_PROYECTO / f"{base}_parcial{sufijo}.xlsx"
            generado = generar_excel(
                ruta_json, ruta_excel, CONFIG, REGLAS, ruta_plantilla=ruta_plantilla,
                datos_validacion=datos_parciales, idioma=idioma)
            generados[idioma] = str(generado)
        principal = generados.get(idiomas[0]) or next(iter(generados.values()))
        with _pipeline_lock:
            _pipeline_estado.update(
                archivo_excel_parcial=principal, archivos_excel_parcial=generados,
                excel_parcial_actualizado_en=datetime.now().isoformat(timespec="seconds"),
                advertencia_excel_parcial=None, excel_parcial_pendiente=False,
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
                             contenido: str = "todo") -> None:

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
            contenido=contenido)
        _cache.update({"mtime": None, "datos": None})
        fase3 = (resumen.get("fases") or {}).get("fase3") or {}
        _actualizar_pipeline(
            estado="completado", fase="completado", mensaje="Procesamiento terminado",
            finalizado_en=datetime.now().isoformat(timespec="seconds"), resumen=resumen,
            archivos_excel=fase3.get("archivos") or {},
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


MATRIZ_APERTURA_COLUMNAS = [
    {"id": "HT_UGL", "temperature_condition": "HT", "inflator_type": "UGL",
     "temperatura": "+85°C", "generador": "UGL", "esperados": 5},
    {"id": "HT_OGL", "temperature_condition": "HT", "inflator_type": "OGL",
     "temperatura": "+85°C", "generador": "OGL", "esperados": 5},
    {"id": "HT_NOM", "temperature_condition": "HT", "inflator_type": "NOM",
     "temperatura": "+85°C", "generador": "nominal", "esperados": 10},
    {"id": "RT_NOM", "temperature_condition": "RT", "inflator_type": "NOM",
     "temperatura": "RT", "generador": "nominal", "esperados": 10},
    {"id": "NT_NOM", "temperature_condition": "NT", "inflator_type": "NOM",
     "temperatura": "-35°C", "generador": "nominal", "esperados": 10},
    {"id": "NT_OGL", "temperature_condition": "NT", "inflator_type": "OGL",
     "temperatura": "-35°C", "generador": "OGL", "esperados": 5},
    {"id": "NT_UGL", "temperature_condition": "NT", "inflator_type": "UGL",
     "temperatura": "-35°C", "generador": "UGL", "esperados": 5},
]


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
        from video_airbag import normalizar_videos_caso, consenso_videos
        cambiado = normalizar_videos_caso(videos, CONFIG)
        if cambiado:
            consenso = consenso_videos(videos, CONFIG)
            _aplicar_consenso_video_a_fila(fila, consenso)
        return cambiado
    except Exception:
        # Una autorreparación de compatibilidad nunca debe impedir abrir el
        # listado o un detalle; el reanálisis explícito seguirá disponible.
        return False


def _estado_apertura_fila(fila: dict) -> tuple[str, float | None]:
    valor = _numero_ms(_campo_resultado(fila, "opening_time_ms", solo_confiable=True))
    if valor is None:
        return "gris", None
    criterio = REGLAS.get("criterios", {}).get("tiempo_apertura_ms") or {
        "verde": "<= 6", "amarillo": "6-7", "rojo": "> 7"}
    return evaluar_criterio(criterio, valor) or "gris", valor


def _clave_prueba_orden(valor):
    try:
        return (0, int(str(valor).strip()))
    except (TypeError, ValueError):
        return (1, str(valor or ""))


def _matriz_apertura(filas: list[dict]) -> dict | None:
    if not any(str(f.get("tipo_st") or "").upper() in {"1ST", "2ST"} for f in filas):
        return None
    etapas = []
    for tipo_st in ("1ST", "2ST"):
        columnas = []
        etapa = [f for f in filas if str(f.get("tipo_st") or "").upper() == tipo_st]
        for spec in MATRIZ_APERTURA_COLUMNAS:
            grupo = [f for f in etapa
                     if str(f.get("temperature_condition") or "").upper() == spec["temperature_condition"]
                     and str(f.get("inflator_type") or "").upper() == spec["inflator_type"]]
            grupo.sort(key=lambda f: _clave_prueba_orden(f.get("test_number") or f.get("identificador")),
                       reverse=True)
            alto = max(10, len(grupo))
            celdas = [None] * max(0, alto - len(grupo))
            for fila in grupo:
                celdas.append({
                    "id": fila.get("id"),
                    "test_number": fila.get("test_number") or fila.get("identificador") or fila.get("nombre"),
                    "estado": fila.get("semaforo_apertura") or "gris",
                    "opening_time_ms": fila.get("opening_time_ms"),
                    "enlace": fila.get("enlace"),
                })
            columnas.append({**spec, "celdas": celdas})
        etapas.append({"tipo_st": tipo_st, "columnas": columnas})
    return {
        "etapas": etapas,
        "regla": {**{color: f"{valor} ms" for color, valor in (
            REGLAS.get("criterios", {}).get("tiempo_apertura_ms") or {
                "verde": "<= 6", "amarillo": "6-7", "rojo": "> 7"}).items()},
            "gris": "valor aún no conocido"},
    }


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
    semaforo_apertura, opening_time_ms = _estado_apertura_fila(fila)
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
        "semaforo_apertura": semaforo_apertura,
        "test_number": fila.get("test_number") or _campo_resultado(fila, "test_number"),
        "ruta": fila.get("ruta"), "ruta_relativa": fila.get("ruta_relativa"),
        "estructura_valida": fila.get("estructura_valida"),
        "estado": fila.get("estado", "detectada"), "progreso": fila.get("progreso", {}),
        "total_imagenes": fila.get("total_imagenes", 0),
        "total_videos": fila.get("total_videos", len(fila.get("videos") or [])),
        "video_apertura": fila.get("video_apertura"),
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
    from criterios_usuario import cargar_criterios_usuario
    advertencia = None
    try:
        criterios_usuario = cargar_criterios_usuario()
    except (OSError, ValueError, TypeError) as exc:
        criterios_usuario = None
        advertencia = f"No se pudieron leer los límites elegidos; revisa antes de valorar: {exc}"
    return {
        "nombre_herramienta": "OCR Versuchsmatrix",
        "colores": CONFIG.get("colores", {}),
        "reglas": REGLAS.get("criterios", {}),
        "idiomas_interfaz": ["es", "en", "de"],
        "idiomas_exportacion": ["es", "en", "de"],
        "criterios_usuario": criterios_usuario,
        "advertencia_criterios": advertencia,
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
            auto_activar = bool(CONFIG.get("aprendizaje", {}).get("visual", {}).get(
                "auto_activar_si_mejora", True))
            if (modo == "auto" and auto_activar and resultado.get("estado") == "candidato_aprobado"
                    and resultado.get("version")):
                activado = GestorAprendizaje(CONFIG).activar_modelo_visual(resultado["version"])
                resultado["activado_automaticamente"] = True
                resultado["modelo_activo"] = activado.get("activo")
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
    try:
        correcto = (str(token.get("texto") or solicitud.texto_ocr) if solicitud.accion == "aceptar"
                    else solicitud.texto_correcto)
        metadatos_supervision = {k: fila.get(k) for k in
            ("tipo_st", "module_version", "temperature_condition", "inflator_type")}
        metadatos_supervision.update({
            "project_id": fila.get("project_id"),
            "case_key": fila.get("case_key"),
            "componente": getattr(solicitud, "componente", None) or "por_identificar",
            "campo_propuesto": getattr(solicitud, "campo_destino", None),
            "bbox_original": token.get("bbox"),
            "giro_foto": float(ocr.get("orientacion_texto_grados") or 0),
            "poligono_lectura": token.get("poligono_lectura"),
            "orientacion_region_grados": token.get("orientacion_region_grados"),
            "marco_region": token.get("marco_region"),
            "estrategia_ocr_confirmada": getattr(solicitud, "estrategia_ocr", None),
        })
        if token.get("edicion_zona") and solicitud.accion not in {"ilegible", "no_es_campo"}:
            from utilidades.edicion_zonas import guardar_bloque
            if not correcto.strip():
                raise ValueError("Escribe o confirma el texto del bloque.")
            if correcto != token.get("texto"):
                with gestor._conectar() as con:
                    guardar_bloque(con, hash_archivo(ruta_local), ocr, list(token["bbox"]),
                                   [{"bbox": list(token["bbox"]), "texto": correcto}])
            muestra = gestor.registrar_muestra_visual(
                ruta_local, solicitud.prueba_id,
                str(token.get("texto_original") or token.get("texto") or solicitud.texto_ocr), correcto,
                token.get("bbox"), accion="confirmar_entrenar", entrenable=True,
                campo=solicitud.campo, fase=item.get("fase"), tor=item.get("tor"),
                confianza=token.get("confianza"), modelo_origen=ocr.get("modelo_visual_version")
                or ocr.get("motor"), usuario=solicitud.usuario, metadatos=metadatos_supervision)
            resultado = {"registrada": True, "tipo": "confirmacion_bloque", "entrenamiento": None,
                         "muestra_visual": muestra}
        elif solicitud.accion in {"ilegible", "no_es_campo"}:
            muestra = gestor.registrar_muestra_visual(
                ruta_local, solicitud.prueba_id, solicitud.texto_ocr, correcto,
                token.get("bbox"), accion=solicitud.accion, entrenable=False,
                campo=solicitud.campo, fase=item.get("fase"), tor=item.get("tor"),
                confianza=token.get("confianza"), modelo_origen=ocr.get("modelo_visual_version")
                or ocr.get("motor"), usuario=solicitud.usuario,
                metadatos=metadatos_supervision)
            resultado = {"registrada": True, "tipo": "supervision_visual",
                         "muestra_visual": muestra, "entrenamiento": None}
        else:
            if not correcto.strip():
                raise ValueError("Escribe el texto correcto antes de confirmar.")
            resultado = gestor.registrar_correccion(
                str(token.get("texto_original") or token.get("texto") or solicitud.texto_ocr), correcto, ruta_imagen=str(ruta_local),
                bbox=token.get("bbox"), fuente="dashboard", caso_id=solicitud.prueba_id,
                accion=solicitud.accion,
                entrenar_visual=True,
                campo=solicitud.campo, fase=item.get("fase"), tor=item.get("tor"),
                confianza=token.get("confianza"), modelo_origen=ocr.get("modelo_visual_version")
                or ocr.get("motor"), usuario=solicitud.usuario,
                metadatos=metadatos_supervision)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
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
            "texto_ocr_original": token.get("texto_original") or solicitud.texto_ocr,
            "texto_corregido": correcto,
            "orientacion_grados": token.get("orientacion_region_grados")
                if token.get("orientacion_region_grados") is not None
                else ocr.get("orientacion_texto_grados"),
        }
        fila.setdefault("confirmaciones_extraccion", []).append({
            **evidencia, "componente": componente_supervision or "por_identificar",
            "campo": campo_destino, "usuario": solicitud.usuario,
            "fecha": datetime.now().isoformat(timespec="seconds")})
        if campo_destino and fila.get("perfil") == "empresarial":
            try:
                dato = _aplicar_campo_manual_en_fila(
                    fila, campo_destino, correcto, solicitud.usuario,
                    componente_supervision, evidencia)
                resultado["campo_confirmado"] = {"campo": campo_destino, "dato": dato}
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        guardado = _guardar_json_atomico(RUTA_VALIDACION, datos)
        if guardado is False:
            raise HTTPException(500, "La corrección OCR se guardó, pero no se pudo persistir su clasificación de campo.")
        _cache.update({"mtime": None, "datos": None})
    muestra_confirmada = resultado.get("muestra_visual") if isinstance(resultado, dict) else None
    programador_auto = globals().get("_programar_entrenamiento_visual_auto")
    if (isinstance(muestra_confirmada, dict) and muestra_confirmada.get("entrenable")
            and callable(programador_auto)):
        resultado["aprendizaje_visual_automatico"] = programador_auto(
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
    try:
        poligono = (_validar_poligono_recorte(solicitud.poligono, [ancho_imagen, alto_imagen]).tolist()
                    if solicitud.poligono is not None else None)
        resultado = gestor.registrar_region(
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
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    gestor.actualizar_revision("carpeta", solicitud.prueba_id, estado="parcial")
    if resultado.get("muestra_visual"):
        resultado["aprendizaje_visual_automatico"] = _programar_entrenamiento_visual_auto(
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
    """Memoriza la orientación humana; el siguiente OCR la usa como punto de partida."""
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
        if gestor.filtrar_no_texto(ocr_objetivo, ruta).get("ediciones_zona"):
            raise HTTPException(409, "Deshaz las uniones de esta imagen antes de cambiar su giro guardado. El zoom y el giro de vista siguen disponibles.")
        dimensiones_respaldo = _dimensiones_ocr_desde_archivo(ruta, ocr_objetivo)
        giro = _rotar_resultado_existente(
            ocr_objetivo, solicitud.grados, dimensiones_respaldo,
            restaurar_automatico=solicitud.usar_automatico)
        # Los recortes guardados pertenecen al marco anterior. No mostrar ni
        # entrenar con polígonos regionales obsoletos tras girar toda la foto.
        ocr_objetivo["recortes"] = []
        for unidad in [*(ocr_objetivo.get("tokens") or []), *(ocr_objetivo.get("lineas_texto") or [])]:
            unidad.pop("poligono_lectura", None)
            unidad.pop("marco_region", None)
        resultado = (gestor.eliminar_rotacion(ruta) if solicitud.usar_automatico
                     else gestor.actualizar_rotacion(ruta, solicitud.grados))
        resultado.update(gestor.rotar_evidencias_imagen(
            ruta, giro["delta"], giro["dimensiones_anteriores"],
            grados_desde=giro["angulo_anterior"], grados_hasta=giro["angulo_nuevo"],
            dimensiones_fuente=giro["dimensiones_fuente"]))
        if solicitud.tipo == "carpeta":
            # Etiqueta/referencia son vistas resumidas de las mismas imágenes.
            for campo in ("etiqueta", "referencia"):
                copia = fila.get(campo)
                if (copia and str(copia.get("ruta")) == str(item.get("ruta")) and
                        copia.get("resultado_ocr") is not ocr_objetivo):
                    ocr_copia = copia.get("resultado_ocr") or {}
                    _rotar_resultado_existente(
                        ocr_copia, solicitud.grados,
                        _dimensiones_ocr_desde_archivo(ruta, ocr_copia),
                        restaurar_automatico=solicitud.usar_automatico)
            _guardar_json_atomico(RUTA_VALIDACION, datos)
            _cache.update({"mtime": None, "datos": None})
        else:
            _guardar_json_atomico(salida_externa, documento_externo)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    gestor.actualizar_revision(solicitud.tipo, solicitud.prueba_id, estado="parcial")
    resultado["mensaje"] = ((
        "Se restauró la orientación automática y se ajustaron sus cajas y regiones.")
        if solicitud.usar_automatico else (
        "Imagen rotada ahora. También se ajustaron sus cajas y regiones; "
        "el próximo OCR conservará esta orientación manual."))
    return resultado


@app.post("/api/imagenes/sin-datos")
def marcar_imagen_sin_datos(solicitud: SolicitudImagenSinDatos):
    """Registra una decisión humana válida; no la presenta como error OCR."""
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
        resultado = gestor.registrar_imagen_sin_datos(
            ruta, solicitud.prueba_id, solicitud.motivo, solicitud.usuario)
        item["estado_imagen"] = "revisada_sin_datos"
        item["revision_sin_datos"] = resultado
        if item.get("resultado_ocr") is not None:
            item["resultado_ocr"]["estado_imagen"] = "revisada_sin_datos"
        for traza in fila.get("trazabilidad", []):
            if str(traza.get("ruta_absoluta")) == str(ruta):
                traza.update({"estado_imagen": "revisada_sin_datos",
                              "requiere_revision": False,
                              "mensaje_error": solicitud.motivo or None})
        _guardar_json_atomico(RUTA_VALIDACION, datos)
        _cache.update({"mtime": None, "datos": None})
    else:
        from pruebas_externas import cargar, rutas
        documento = cargar(CONFIG)
        fila = next((f for f in documento.get("resultados", [])
                     if f.get("id") == solicitud.prueba_id), None)
        if fila is None:
            raise HTTPException(404, "La prueba externa indicada no existe.")
        ruta = Path(str(fila.get("ruta") or "")).resolve()
        resultado = gestor.registrar_imagen_sin_datos(
            ruta, solicitud.prueba_id, solicitud.motivo, solicitud.usuario)
        fila["estado_imagen"] = "revisada_sin_datos"
        fila["revision_sin_datos"] = resultado
        _, salida = rutas(CONFIG)
        _guardar_json_atomico(salida, documento)
    gestor.actualizar_revision(solicitud.tipo, solicitud.prueba_id, estado="parcial")
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
    if _pipeline_hilo is not None and _pipeline_hilo.is_alive():
        raise HTTPException(409, "Detén conservando el avance antes de restaurar la imagen.")
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
        _restaurar_estado_con_texto(item)
        for alias in (fila.get("etiqueta"), fila.get("referencia")):
            if alias and str(alias.get("ruta")) == str(item["ruta"]):
                _restaurar_estado_con_texto(alias)
        for traza in fila.get("trazabilidad", []):
            if str(traza.get("ruta_absoluta")) in {str(ruta), str(item["ruta"])}:
                traza.update(estado_imagen="pendiente", requiere_revision=True, mensaje_error=None)
        destino = RUTA_VALIDACION
    else:
        from pruebas_externas import cargar, rutas
        datos = deepcopy(cargar(CONFIG))
        item = next((f for f in datos.get("resultados", []) if f.get("id") == solicitud.prueba_id), None)
        if item is None:
            raise HTTPException(404, "Prueba externa no encontrada.")
        ruta = Path(str(item.get("ruta") or "")).resolve()
        if not ruta.is_file():
            raise HTTPException(404, "La imagen ya no está disponible.")
        _restaurar_estado_con_texto(item)
        _, destino = rutas(CONFIG)
    # Si falla la escritura JSON, la transacción no elimina la marca persistida.
    with gestor._conectar() as con:
        con.execute("DELETE FROM imagenes_sin_datos WHERE imagen_hash=?", (hash_archivo(ruta),))
        _guardar_json_atomico(destino, datos)
    _cache.update({"mtime": None, "datos": None})
    gestor.actualizar_revision(solicitud.tipo, solicitud.prueba_id, estado="parcial")
    resultado = {"restaurada": True, "estado_imagen": "pendiente",
                 "mensaje": "Marca sin texto retirada. La imagen queda pendiente de revisión. Si no tiene lecturas, reprocesa esta imagen."}
    _regenerar_excel(resultado)
    return resultado


@app.post("/api/imagenes/verificar")
def verificar_imagen(solicitud: SolicitudImagenVerificada):
    """Confirma que una imagen con texto ya fue revisada por una persona."""
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
    item["estado_imagen"] = "verificada"
    item["revision_imagen"] = revision
    if item.get("resultado_ocr") is not None:
        item["resultado_ocr"]["estado_imagen"] = "verificada"
    for traza in fila.get("trazabilidad", []):
        if str(traza.get("ruta_absoluta")) == str(item.get("ruta")):
            traza.update({"estado_imagen": "verificada", "requiere_revision": False})
    _guardar_json_atomico(RUTA_VALIDACION, datos)
    _cache.update({"mtime": None, "datos": None})
    gestor = GestorAprendizaje(CONFIG)
    gestor.actualizar_revision("carpeta", solicitud.prueba_id, estado="parcial")
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
    except (OSError, ValueError):
        # Verificar la imagen nunca debe fallar porque una unión histórica no
        # pueda materializarse como recorte entrenable.
        union_historica = None
    auto_visual = None
    if bool(CONFIG.get("aprendizaje", {}).get("visual", {}).get("auto_entrenar_al_verificar", True)):
        auto_visual = _programar_entrenamiento_visual_auto(
            f"Imagen verificada: {solicitud.prueba_id}/{solicitud.imagen_id}")
    nuevas_union = int((union_historica or {}).get("nuevas") or 0)
    mensaje_union = (f" Se incorporaron {nuevas_union} muestra(s) de uniones guardadas al entrenamiento."
                     if nuevas_union else "")
    return {"verificada": True, "revision_imagen": revision,
            "aprendizaje_visual_automatico": auto_visual,
            "uniones_historicas_entrenamiento": union_historica,
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
    _actualizar_revision_parcial_en_memoria(
        solicitud.tipo, solicitud.item_id, resultado)
    _regenerar_excel(resultado)
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
    try:
        correcto = (str(token.get("texto") or solicitud.texto_ocr) if solicitud.accion == "aceptar"
                    else solicitud.texto_correcto)
        if solicitud.accion in {"ilegible", "no_es_campo"}:
            muestra = gestor.registrar_muestra_visual(
                fila["ruta"], solicitud.prueba_id, solicitud.texto_ocr, correcto,
                token.get("bbox"), accion=solicitud.accion, entrenable=False,
                confianza=token.get("confianza"), modelo_origen=fila.get("modelo_visual_version")
                or fila.get("motor"), usuario=solicitud.usuario,
                metadatos={"origen": "externa"})
            resultado = {"registrada": True, "tipo": "supervision_visual",
                         "muestra_visual": muestra, "entrenamiento": None}
        else:
            if not correcto.strip():
                raise ValueError("Escribe el texto correcto antes de confirmar.")
            resultado = gestor.registrar_correccion(
                str(token.get("texto_original") or token.get("texto") or solicitud.texto_ocr), correcto, ruta_imagen=fila["ruta"],
                bbox=token.get("bbox"), fuente="dashboard_externo",
                caso_id=solicitud.prueba_id, accion=solicitud.accion,
                entrenar_visual=True,
                confianza=token.get("confianza"), modelo_origen=fila.get("modelo_visual_version")
                or fila.get("motor"), usuario=solicitud.usuario,
                metadatos={"origen": "externa"})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    gestor.actualizar_revision("externa", solicitud.prueba_id, estado="parcial")
    muestra_confirmada = resultado.get("muestra_visual") if isinstance(resultado, dict) else None
    programador_auto = globals().get("_programar_entrenamiento_visual_auto")
    if (isinstance(muestra_confirmada, dict) and muestra_confirmada.get("entrenable")
            and callable(programador_auto)):
        resultado["aprendizaje_visual_automatico"] = programador_auto(
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
    try:
        resultado = gestor.registrar_region(
            solicitud.texto_correcto, solicitud.bbox, ruta_imagen=str(ruta),
            carpeta_id=solicitud.prueba_id, carpeta_nombre="Pruebas complejas",
            imagen_nombre=fila.get("imagen"), fuente="dashboard_externo",
            modelo_origen=fila.get("modelo_visual_version") or fila.get("motor"),
            usuario=solicitud.usuario,
            entrenable=True,
            metadatos={"origen": "externa"})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    gestor.actualizar_revision("externa", solicitud.prueba_id, estado="parcial")
    if resultado.get("muestra_visual"):
        resultado["aprendizaje_visual_automatico"] = _programar_entrenamiento_visual_auto(
            f"Región externa confirmada: {solicitud.prueba_id}")
    _regenerar_excel(resultado)
    resultado["estado"] = gestor.estado()
    return resultado


@app.post("/api/pipeline", status_code=202)
def iniciar_pipeline(solicitud: SolicitudPipeline):
    global _pipeline_hilo
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

    capacidad = _capacidad_pipeline()
    if not capacidad["listo"]:
        raise HTTPException(503, {"mensaje": "El entorno OCR no está listo.", **capacidad})

    with _pipeline_lock:
        hilo_vivo = bool(_pipeline_hilo and _pipeline_hilo.is_alive())
        if hilo_vivo:
            raise HTTPException(409, "El procesamiento anterior todavía está cerrando recursos; vuelve a intentar cuando termine.")
        # Un estado cancelando/pausado persistido sin hilo vivo es un checkpoint,
        # no un proceso real. V14 permite iniciar de nuevo sin borrar cachés.
        if _pipeline_estado["estado"] == "reanudando" and (
                str(solicitud.ejecucion_id or "") != str(_pipeline_estado.get("ejecucion_id") or "")):
            _pipeline_estado.update(estado="detenido_con_avance", reanudable=True)
        _pipeline_continuar.set()
        _pipeline_cancelar.clear()
        _pipeline_detener_fin_id.clear()
        ejecucion_id = str(solicitud.ejecucion_id or uuid.uuid4().hex)
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
        obtener_gestor_recursos(perfil_rendimiento).configurar(perfil_rendimiento)
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
            "metricas_recursos": obtener_gestor_recursos(perfil_rendimiento).snapshot(forzar=True),
            "idiomas_exportacion": idiomas_exportacion, "archivos_excel": {},
            "archivos_excel_parcial": {},
            "tipo_st": solicitud.tipo_st, "ruta_plantilla": ruta_plantilla,
            "plantilla_id": solicitud.plantilla_id,
            "modo_ejecucion": solicitud.modo_ejecucion,
            "ruta_inventario": ruta_inventario,
            "ultimo_id": None, "ultimo_id_nombre": None,
            "reanudable": False, "solicitud": solicitud_guardada,
            "ejecucion_id": ejecucion_id,
            "archivo_excel_parcial": None, "excel_parcial_actualizado_en": None,
            "advertencia_excel_parcial": None, "excel_parcial_pendiente": False,
            "advertencias_cache": [],
            "actualizado_en": datetime.now().isoformat(timespec="milliseconds"),
        })
    _persistir_checkpoint_pipeline()

    _pipeline_hilo = threading.Thread(target=_ejecutar_pipeline_fondo, kwargs={
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
    }, daemon=True)
    _pipeline_hilo.start()
    return {"aceptado": True, "ruta": str(ruta), "estado": "procesando"}


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
        "matriz_apertura": _matriz_apertura(filas),
        "generado_en": datos.get("generado_en"),
        "raiz": _raiz_publica(datos),
        "raiz_origen": datos.get("raiz"),
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
    if not datos and not parciales:
        raise HTTPException(404, "Sin datos procesados.")
    revisiones = GestorAprendizaje(CONFIG).listar_revisiones()
    atendidas = GestorAprendizaje(CONFIG).listar_alertas_atendidas()
    filas = [_fila_publica(f, revisiones, atendidas) for f in (datos or {}).get("resultados", [])]
    por_id = {f["id"]: f for f in filas}
    for parcial in parciales:
        if parcial.get("origen") == "carpeta":
            # El parcial puede haberse creado antes de que el usuario cambiara la
            # revisión. Nunca debe tapar una revisión persistida más reciente.
            por_id[parcial["id"]] = _revision_vigente_en_fila_publica(parcial, revisiones)
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
    base=Path(datos.get("nombre_excel_base") or datos.get("archivo_excel") or (RAIZ_PROYECTO / CONFIG.get("fase3",{}).get("archivo_salida","resultado_maestro.xlsx")))
    if not base.is_absolute(): base=RAIZ_PROYECTO/base
    generados=[]
    for idioma in idiomas:
        destino=base.with_name(f"{base.stem}_{permitidos[idioma]}.xlsx")
        try:
            generado=_generar_excel_serializado(RUTA_VALIDACION,destino,CONFIG,REGLAS,ruta_plantilla=datos.get("ruta_plantilla"),datos_validacion=datos,idioma=idioma)
        except PermissionError as exc: raise HTTPException(423,str(exc)) from exc
        generados.append({"idioma":idioma,"nombre":Path(generado).name,"url":f"/api/resultados/exportado?archivo={quote(Path(generado).name)}"})
    return {"generados":generados,"instantanea":datos.get("generado_en"),"reutilizo_ocr":True}


@app.get("/api/resultados/exportado")
def descargar_exportado(archivo: str):
    nombre=Path(unquote(archivo)).name; datos=_cargar_datos() or {}
    base=Path(datos.get("nombre_excel_base") or datos.get("archivo_excel") or (RAIZ_PROYECTO / CONFIG.get("fase3",{}).get("archivo_salida","resultado_maestro.xlsx")))
    if not base.is_absolute(): base=RAIZ_PROYECTO/base
    candidato=(base.parent/nombre).resolve()
    if candidato.parent != base.parent.resolve() or not candidato.is_file() or candidato.suffix.lower()!=".xlsx": raise HTTPException(404,"El Excel exportado no está disponible.")
    return FileResponse(candidato,filename=candidato.name,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/api/resultados/consolidar")
def consolidar_resultados(solicitud: SolicitudConsolidacion):
    """Une ejecuciones separadas 1ST/2ST de forma idempotente sin repetir OCR."""
    from utilidades.consolidacion import consolidar_documentos
    documentos=[]; usados=[]
    for declarada in solicitud.archivos:
        ruta=Path(str(declarada)).expanduser(); ruta=(ruta if ruta.is_absolute() else RAIZ_PROYECTO/ruta).resolve()
        if not ruta.is_file() or ruta.suffix.lower()!=".json": raise HTTPException(400,f"JSON inválido: {declarada}")
        try: doc=json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError) as exc: raise HTTPException(400,f"No se pudo leer {ruta.name}: {exc}") from exc
        if not isinstance(doc,dict) or not isinstance(doc.get("resultados"),list): raise HTTPException(400,f"{ruta.name} no es una ejecución OCR consolidable.")
        documentos.append(doc); usados.append(str(ruta))
    actual=_cargar_datos()
    if actual: documentos.insert(0,deepcopy(actual))
    consolidado=consolidar_documentos(documentos); consolidado["fuentes_consolidadas"]=usados
    # Conserva preferencias de exportación del proyecto actual y, si no existen,
    # usa la unión de idiomas declarados por las ejecuciones consolidadas.
    idiomas=[]
    for doc in documentos:
        for codigo in doc.get("idiomas_exportacion") or []:
            codigo=str(codigo).lower()
            if codigo in {"es","en","de"} and codigo not in idiomas: idiomas.append(codigo)
    consolidado["idiomas_exportacion"] = idiomas or ["es"]
    if actual:
        for clave in ("archivo_excel","archivos_excel","nombre_excel_base","ruta_plantilla"):
            if actual.get(clave) is not None: consolidado[clave]=deepcopy(actual.get(clave))
    _guardar_json_atomico(RUTA_VALIDACION,consolidado); _cache.update({"mtime":None,"datos":None})
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
        if numero < 0 or numero > 1000:
            raise ValueError("El tiempo de apertura está fuera del rango válido 0–1000 ms.")
        valor = f"{numero:g}"
    ahora_iso = datetime.now().isoformat(timespec="seconds")
    componente = componente or "por_identificar"
    correccion = {"valor": valor, "corregido_en": ahora_iso,
                  "corregido_por": usuario, "componente": componente}
    fila.setdefault("correcciones_manual_campos", {})[campo] = correccion
    original_ruta = fila.get(campo) if campo in {
        "test_number", "module_version", "inflator_type", "temperature_condition"} else None
    conflicto_ruta = original_ruta not in {None, "", valor}
    dato = {"valor": valor, "valor_original": valor,
            "estado": "pendiente_revision" if conflicto_ruta else "confirmado_manual",
            "fuente": "correccion_manual_confirmada", "confianza": 1.0,
            "inferido": False, "requiere_revision": conflicto_ruta,
            "valor_seguro_ruta": original_ruta if conflicto_ruta else None,
            "componente": componente, **correccion}
    fila.setdefault("campos", {})[campo] = dato
    consolidado = fila.setdefault("consolidado", {})
    consolidado.setdefault("campos", {})[campo] = dato
    fila["campos_faltantes"] = [c for c in fila.get("campos_faltantes", []) if c != campo]
    fila["conflictos"] = list(dict.fromkeys([
        *[c for c in fila.get("conflictos", []) if c != campo],
        *([campo] if conflicto_ruta else []),
    ]))
    fila["requiere_revision"] = bool(fila["conflictos"] or fila["campos_faltantes"])
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
        if numero < 0 or numero > 1000:
            raise HTTPException(400, "El tiempo de apertura está fuera del rango válido 0–1000 ms.")
        valor = f"{numero:g}"
    ahora_iso = datetime.now().isoformat(timespec="seconds")
    correccion = {"valor": valor, "corregido_en": ahora_iso,
                  "corregido_por": solicitud.usuario,
                  "componente": getattr(solicitud, "componente", None) or "por_identificar"}
    fila.setdefault("correcciones_manual_campos", {})[campo] = correccion
    original_ruta = fila.get(campo) if campo in {
        "test_number", "module_version", "inflator_type", "temperature_condition"} else None
    conflicto_ruta = original_ruta not in {None, "", valor}
    dato = {"valor": valor, "valor_original": valor,
            "estado": "pendiente_revision" if conflicto_ruta else "confirmado_manual",
            "fuente": "correccion_manual_confirmada", "confianza": 1.0,
            "inferido": False, "requiere_revision": conflicto_ruta,
            "valor_seguro_ruta": original_ruta if conflicto_ruta else None,
            "componente": getattr(solicitud, "componente", None) or "por_identificar",
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
    global _pipeline_hilo
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
        if _pipeline_hilo is not None and _pipeline_hilo.is_alive():
            raise HTTPException(409, "Ya hay un procesamiento activo o cerrando recursos.")
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
    perfil_reproceso = normalizar_perfil(_pipeline_estado.get("perfil_rendimiento") or "alto")
    _pipeline_hilo = threading.Thread(target=_ejecutar_pipeline_fondo, kwargs={
        "ruta": Path(datos["raiz"]), "nombre_excel": nombre_excel,
        "sobrescribir_excel": True, "tipo_st": fila.get("tipo_st"),
        "ruta_plantilla": plantilla, "casos_filtrados": {fila["case_key"]},
        "imagenes_filtradas": imagenes or None, "solo_errores": solicitud.solo_errores,
        "modo_recorte": solicitud.modo_recorte, "roi_manual": solicitud.roi_manual,
        "modo_ejecucion": "completo", "zoom_forzado": solicitud.zoom_forzado,
        "idiomas_exportacion": list((datos.get("idiomas_exportacion") or
                                      _pipeline_estado.get("idiomas_exportacion") or ["es"])),
        "perfil_rendimiento": perfil_reproceso,
    }, daemon=True)
    _pipeline_hilo.start()
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
        publico_video = dict(video)
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
        }
        campos["opening_time_ms"] = dato
        campos_con["opening_time_ms"] = dict(dato)
        fila["campos_faltantes"] = [x for x in (fila.get("campos_faltantes") or []) if x != "opening_time_ms"]
        consolidado["campos_faltantes"] = [x for x in (consolidado.get("campos_faltantes") or []) if x != "opening_time_ms"]
    else:
        actual = campos.get("opening_time_ms") or {}
        if str(actual.get("fuente") or "").startswith("video"):
            campos["opening_time_ms"] = {"valor": None, "estado": "faltante_requerido", "requerido": True, "requiere_revision": True}
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
                    conservar = {k: video_item.get(k) for k in (
                        "id", "ruta_relativa", "carpeta_video", "revision_manual",
                        "ultima_zona_nacimiento"
                    ) if video_item.get(k) is not None}
                    anterior = {k: video_item.get(k) for k in (
                        "frame_evento", "tiempo_ms", "algoritmo_video", "desde_cache"
                    ) if k in video_item}
                    video_item.clear()
                    video_item.update(nuevo)
                    video_item.update(conservar)
                    video_item["reanalizado_en"] = ahora_etiqueta
                    video_item["origen_resultado_video"] = "recalculado_v15_7_4"
                    video_item["deteccion_anterior"] = anterior
                    video_item["desde_cache"] = False
                except Exception as exc:
                    errores += 1
                    ultimo_error = f"{nombre}: {type(exc).__name__}: {exc}"
                procesados += 1
                _estado_reanalisis_video(
                    procesados=procesados, errores=errores, ultimo_error=ultimo_error)

            consenso = consenso_videos(fila.get("videos") or [], CONFIG)
            _aplicar_consenso_video_a_fila(fila, consenso)

        datos["generado_en"] = datetime.now().isoformat(timespec="seconds")
        datos["video_reanalizado_en"] = datos["generado_en"]
        datos["video_reanalisis_version"] = "15.7.4"
        escribir_json_seguro(RUTA_VALIDACION, datos, lanzar=True, compacto=True)
        _cache.update({"mtime": None, "datos": None})
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
    with _pipeline_lock:
        if _pipeline_estado.get("estado") in {"procesando", "pausando", "pausado", "cancelando", "reanudando"}:
            raise HTTPException(409, "Detén o termina el procesamiento OCR antes de reanalizar videos.")
    with _video_reanalisis_lock:
        if _video_reanalisis_hilo is not None and _video_reanalisis_hilo.is_alive():
            raise HTTPException(409, "Ya hay un reanálisis de videos en curso.")
        _video_reanalisis_estado.update({
            "estado": "preparando", "mensaje": ("Preparando recálculo del video" if solicitud.video_id else "Preparando reanálisis de video"),
            "prueba_id": solicitud.prueba_id, "video_id": solicitud.video_id, "total_videos": 0, "procesados": 0,
            "errores": 0, "video_actual": None, "iniciado_en": datetime.now().isoformat(timespec="seconds"),
            "finalizado_en": None, "ultimo_error": None, "algoritmo": None,
        })
        _video_reanalisis_hilo = threading.Thread(
            target=_reanalizar_videos_fondo, args=(solicitud.prueba_id, solicitud.video_id), daemon=True)
        _video_reanalisis_hilo.start()
    return {"aceptado": True, "estado": "preparando", "prueba_id": solicitud.prueba_id, "video_id": solicitud.video_id}


@app.post("/api/video/revision")
def revisar_video(solicitud: SolicitudRevisionVideo):
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
    from video_airbag import (guardar_revision_video, consenso_videos, resolver_tiempo_frame,
                              fps_real_item, normalizar_videos_caso)
    normalizar_videos_caso(fila.get("videos") or [], CONFIG)

    # V15.6: el frame confirmado es la fuente de verdad. El tiempo enviado por
    # el navegador sólo se conserva como dato de auditoría; el backend lo vuelve
    # a resolver usando el reloj del MISMO frame + Rec...fps. Así un offset viejo
    # del frontend no puede guardarse como apertura negativa o contradictoria.
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
        if tiempo_confirmado is None:
            raise HTTPException(422, "No se pudo resolver un tiempo válido para ese cuadro.")
        tiempo_confirmado = max(0.0, float(tiempo_confirmado))

    revision = guardar_revision_video(
        ruta_local, case_key=fila.get("case_key"), frame_index=solicitud.frame_index,
        tiempo_ms=(tiempo_confirmado if solicitud.estado == "confirmado" else None),
        estado=solicitud.estado, usuario=solicitud.usuario, comentario=solicitud.comentario)
    video_item["revision_manual"] = revision
    if solicitud.frame_index is not None and solicitud.estado == "confirmado":
        video_item["frame_evento"] = int(solicitud.frame_index)
    if tiempo_confirmado is not None:
        video_item["tiempo_ms"] = round(float(tiempo_confirmado), 1)
        video_item["tiempo_overlay_ms"] = tiempo_resuelto.get("tiempo_overlay_ms")
        video_item["tiempo_fps_ms"] = tiempo_resuelto.get("tiempo_fps_ms")
        video_item["fuente_tiempo"] = tiempo_resuelto.get("fuente_tiempo")
        video_item["discrepancia_tiempo_ms"] = tiempo_resuelto.get("discrepancia_ms")
        video_item["advertencia_tiempo"] = tiempo_resuelto.get("advertencia")
        video_item["overlay_validado"] = bool(tiempo_resuelto.get("overlay_valido"))
        if tiempo_resuelto.get("fps"):
            video_item["fps"] = float(tiempo_resuelto.get("fps"))
            video_item["fps_grabacion"] = float(tiempo_resuelto.get("fps"))
            video_item["fps_fuente"] = video_item.get("fps_fuente") if fps_real_item(video_item) else tiempo_resuelto.get("fps_fuente")
            video_item["resolucion_nativa_ms"] = round(1000.0 / float(tiempo_resuelto.get("fps")), 6)
        if tiempo_resuelto.get("overlay_texto_esquina"):
            video_item["overlay_texto_esquina"] = tiempo_resuelto.get("overlay_texto_esquina")

    # V15.7.4: una confirmación guarda dos escalas distintas:
    #   1) ROI general = dónde debe mirar el detector;
    #   2) microzona = dónde aparece exactamente el primer fragmento.
    # Si el usuario no dibujó la microzona, el backend la propone automáticamente
    # comparando F-3..F-1 con el cuadro confirmado y su crecimiento posterior.
    ejemplo_aprendido = None
    advertencia_aprendizaje = None
    localizacion_nacimiento = None
    if solicitud.estado == "confirmado" and solicitud.frame_index is not None:
        try:
            from aprendizaje_video_airbag import (guardar_ejemplo_evento, perfil_evento_aprendido,
                                                   localizar_nacimiento_evento, _bbox_evento_normalizada)
            zona = (video_item.get("zona_deteccion") or {}).get("bbox_norm")
            tipo_camara = (video_item.get("tipo_camara") or
                           (video_item.get("zona_deteccion") or {}).get("tipo_camara"))
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
            ejemplo_aprendido = guardar_ejemplo_evento(
                ruta_local, frame_index=int(solicitud.frame_index), bbox_norm=zona,
                bbox_evento_norm=bbox_evento, tipo_camara=tipo_camara,
                tiempo_ms=tiempo_confirmado, fps=video_item.get("fps"), usuario=solicitud.usuario)
            video_item["ultima_zona_nacimiento"] = localizacion_nacimiento
            video_item["perfil_evento_aprendido"] = perfil_evento_aprendido(tipo_camara)
        except Exception as exc:  # La revisión manual nunca debe perderse por un fallo del dataset.
            advertencia_aprendizaje = f"{type(exc).__name__}: {exc}"

    consenso = consenso_videos(fila.get("videos") or [], CONFIG)
    _aplicar_consenso_video_a_fila(fila, consenso)
    datos["generado_en"] = datetime.now().isoformat(timespec="seconds")
    escribir_json_seguro(RUTA_VALIDACION, datos, lanzar=True, compacto=True)
    _cache.update({"mtime": None, "datos": None})
    diferencia_cliente_ms = None
    if tiempo_confirmado is not None and solicitud.tiempo_ms is not None:
        try:
            diferencia_cliente_ms = round(float(solicitud.tiempo_ms) - float(tiempo_confirmado), 6)
        except (TypeError, ValueError):
            diferencia_cliente_ms = None
    resultado = {
        "revision": revision, "consenso": consenso, "guardado": True,
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
        if (_pipeline_estado.get("estado") in {
                "procesando", "pausando", "pausado", "cancelando", "reanudando"}
                or (_video_reanalisis_hilo is not None and _video_reanalisis_hilo.is_alive())):
            raise HTTPException(409, "Termina o detén el procesamiento antes de confirmar el máximo.")
        datos = _cargar_datos() or {}
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
    resultado = {"guardado": True, "despliegue_maximo": revision, "tiempo_resuelto": resuelto}
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
        bbox = [float(x) for x in solicitud.bbox_norm]
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "La zona de video contiene coordenadas inválidas.") from exc
    if len(bbox) != 4 or any((not math.isfinite(x) or x < 0 or x > 1) for x in bbox):
        raise HTTPException(422, "La zona de video debe tener cuatro coordenadas normalizadas entre 0 y 1.")
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
        bbox = [float(x) for x in solicitud.bbox_norm]
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "La zona de video contiene coordenadas inválidas.") from exc
    if any((not math.isfinite(x) or x < 0 or x > 1) for x in bbox):
        raise HTTPException(422, "La zona de video debe estar normalizada entre 0 y 1.")
    from aprendizaje_video_airbag import guardar_zona_aprendida, resumen_aprendizajes
    from video_airbag import analizar_video, consenso_videos
    try:
        perfil = guardar_zona_aprendida(
            ruta_local, bbox, tipo_camara=solicitud.tipo_camara,
            frame_index=solicitud.frame_index, usuario=solicitud.usuario)
        nuevo = analizar_video(ruta_local, CONFIG, usar_cache=False)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Conserva metadatos del inventario que no pertenecen al analizador.
    conservar = {k: video_item.get(k) for k in ("id", "ruta_relativa", "carpeta_video") if k in video_item}
    video_item.update(nuevo)
    video_item.update(conservar)
    consenso = consenso_videos(fila.get("videos") or [], CONFIG)
    _aplicar_consenso_video_a_fila(fila, consenso)
    datos["generado_en"] = datetime.now().isoformat(timespec="seconds")
    escribir_json_seguro(RUTA_VALIDACION, datos, lanzar=True, compacto=True)
    _cache.update({"mtime": None, "datos": None})
    resultado = {
        "guardado": True, "perfil": perfil, "video": video_item,
        "consenso": consenso, "aprendizaje": resumen_aprendizajes(),
    }
    _regenerar_excel(resultado)
    return resultado


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
        if _pipeline_hilo is not None and _pipeline_hilo.is_alive():
            raise HTTPException(409, "Detén conservando el avance antes de editar zonas; pausar mantiene el hilo activo.")
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
        gestor.actualizar_revision("carpeta", solicitud.prueba_id, estado="parcial")
        _regenerar_excel(resultado)
        return resultado
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        _zona_lock.release()


# Frontend estático: se monta al final para no tapar los endpoints /api.
app.mount("/", StaticFiles(directory=str(DIR_FRONTEND), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    puerto = int(CONFIG.get("dashboard", {}).get("puerto", 8000))
    print(f"Dashboard: http://127.0.0.1:{puerto}")
    uvicorn.run(app, host="127.0.0.1", port=puerto, log_level="warning")
