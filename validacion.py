"""
validacion.py — Fase 2: recorrido de carpetas hoja y validación cruzada.

Propósito
---------
Usa `estructura_detectada.json` (Fase 0) para saber qué carpetas hoja procesar,
clasifica cada archivo (fotografía / diagrama / video / candidato a referencia),
corre `extraer_texto()` (Fase 1) sobre las imágenes, elige la imagen de
referencia con una heurística AISLADA y sustituible, y compara los tokens de la
etiqueta contra los de la referencia.

Resultados posibles de la comparación:
  coincidencia_total   | coincidencia_parcial | discrepancia | sin_referencia

Salida: validacion_resultados.json (la consume la Fase 3 y el dashboard).

Nota de diseño: cada imagen se OCR-ea UNA sola vez por lote (caché por ruta) y
la heurística de referencia no hace OCR propio: recibe los resultados ya
calculados. Así, sustituir la heurística por una regla de nombre de archivo no
cambia el costo del pipeline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import time
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from aprendizaje import GestorAprendizaje
from configuracion import RAIZ_PROYECTO, cargar_config
from estructura import carpetas_hoja
from flujo_empresarial import (BaseConocimiento, CAMPOS_REQUERIDOS_DEFAULT,
                               CLAVES_PLANTILLA,
                               CacheOCR, EXTENSIONES_IMAGEN, ahora,
                               consolidar_caso, evidencias_desde_qr,
                               extraer_candidatos_texto)
from ocr_engine import cargar_imagen, extraer_texto, extraer_texto_empresarial

_RE_TOKEN_CODIGO = re.compile(r"^([A-Za-z]+)(\d+)$")


# ---------------------------------------------------------------------------
# Clasificación de archivos
# ---------------------------------------------------------------------------

def clasificar_archivo(nombre: str, config: dict) -> str:
    """
    Categoría de un archivo por extensión + heurística de contenido:
    'video' | 'otro' | 'candidato_referencia' (pista de nombre) |
    'diagrama' | 'fotografia'.
    """
    f0 = config.get("fase0", {})
    f2 = config.get("fase2", {})
    ext = Path(nombre).suffix.lower()
    ext_imagen = {e.lower() for e in f0.get("extensiones_imagen", [])}
    if ext in {e.lower() for e in f0.get("extensiones_video", [])}:
        return "video"
    if ext not in ext_imagen:
        return "otro"
    if f2.get("usar_pista_nombre", True):
        pistas = [p.lower() for p in f2.get("palabras_pista_referencia", [])]
        base = Path(nombre).stem.lower()
        if any(p in base for p in pistas):
            return "candidato_referencia"
    return _fotografia_o_diagrama(nombre, f2)


def _fotografia_o_diagrama(nombre: str, f2: dict) -> str:
    """
    Heurística v1 foto vs diagrama (documentada en docs/fase2_validacion.md):
    un diagrama tiene pocos colores cuantizados y poco ruido fotográfico;
    una foto tiene variación de iluminación y ruido de sensor.
    """
    try:
        img = cargar_imagen(nombre)
    except Exception:
        return "fotografia"  # si no se puede leer, no bloquea la validación
        # (el OCR de esta imagen reportará su propio error más adelante)
    pequena = cv2.resize(img, (160, 120), interpolation=cv2.INTER_AREA)
    gris = cv2.cvtColor(pequena, cv2.COLOR_BGR2GRAY)
    cuantizada = (gris // 32).astype(np.uint8)  # 8 niveles de gris
    n_colores = len(np.unique(cuantizada))
    ruido = float(cv2.Laplacian(gris, cv2.CV_64F).var())
    if n_colores <= int(f2.get("diagrama_max_colores", 4)) and \
            ruido < float(f2.get("diagrama_max_ruido", 50.0)):
        return "diagrama"
    return "fotografia"


# ---------------------------------------------------------------------------
# Heurística de imagen de referencia (AISLADA y sustituible, doc §4)
# ---------------------------------------------------------------------------

def densidad_texto(resultado_ocr: dict) -> float:
    """Fracción del área de la imagen cubierta por cajas de texto detectadas."""
    (w, h) = resultado_ocr.get("dimensiones", (1, 1))
    area = float(w) * float(h)
    if area <= 0:
        return 0.0
    cubierta = sum(bx * by for (_, _, bx, by) in
                   [t["bbox"] for t in resultado_ocr.get("tokens", [])])
    return min(cubierta / area, 1.0)


def identificar_referencia(imagenes_con_ocr: list[dict],
                           umbral: float = 0.01,
                           ventaja_minima: float = 1.5) -> str | None:
    """
    Heurística por densidad de texto (doc §4): la imagen de referencia es la de
    MAYOR densidad de texto, siempre que:
      - haya al menos 2 imágenes (una única foto es la etiqueta, no referencia),
      - su densidad supere `umbral` (fracción de área cubierta por texto), y
      - supere por `ventaja_minima` × a la segunda mejor (si no hay ganador
        claro, se declara sin_referencia en vez de adivinar).
    Recibe [{'ruta': str, 'resultado_ocr': dict}, ...] para no repetir
    inferencias. Sustituible por una regla de nombre de archivo sin tocar el
    resto del pipeline (la pista de nombre ya se aplica antes, en
    clasificar_archivo; esta función es el fallback).
    """
    if len(imagenes_con_ocr) < 2:
        return None
    densidades = sorted(
        ((item["ruta"], densidad_texto(item["resultado_ocr"])) for item in imagenes_con_ocr),
        key=lambda par: par[1], reverse=True)
    (mejor, d_mejor), (_, d_segunda) = densidades[0], densidades[1]
    if d_mejor < umbral:
        return None
    if d_mejor < ventaja_minima * d_segunda:
        return None  # ambigüedad: dos imágenes igual de "textosas"
    return mejor


# ---------------------------------------------------------------------------
# Comparación de tokens
# ---------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    """Mayúsculas y solo alfanuméricos: 'ETQ-2024 a1 v2' -> 'ETQ2024A1V2'."""
    return re.sub(r"[^A-Z0-9]", "", texto.upper())


def es_token_codigo(texto: str) -> bool:
    """
    True si el token parece nomenclatura/código: contiene al menos un dígito.
    'ETQ-2024-A1-V2' -> True; 'PRUEBA DE ETIQUETA' -> False (lenguaje natural).
    El Documento Maestro §1 define el dominio como códigos alfanuméricos.
    """
    return any(c.isdigit() for c in normalizar(texto))


def comparar_tokens(tokens_etiqueta: list[str], tokens_referencia: list[str],
                    umbral_total: float = 1.0,
                    solo_tokens_codigo: bool = True) -> dict:
    """
    Compara los tokens normalizados de la etiqueta contra la referencia.
    ratio = |etiqueta ∩ referencia| / |etiqueta| (los extras de la referencia
    no penalizan: la ficha puede tener más información que la etiqueta).
    Con solo_tokens_codigo=True se comparan únicamente tokens tipo código
    (con dígitos), ignorando rótulos de lenguaje natural de la etiqueta.
    """
    filtro = (lambda t: es_token_codigo(t)) if solo_tokens_codigo else (lambda t: True)
    E = {normalizar(t) for t in tokens_etiqueta if filtro(t)}
    E = {t for t in E if t}
    R = {normalizar(t) for t in tokens_referencia if filtro(t)}
    R = {t for t in R if t}
    if not R:
        return {"resultado": "sin_referencia", "ratio": None, "coincidentes": [],
                "faltantes": sorted(E)}
    if not E:
        return {"resultado": "discrepancia", "ratio": 0.0, "coincidentes": [],
                "faltantes": [], "observacion": "etiqueta sin texto legible"}
    inter = sorted(E & R)
    ratio = len(inter) / len(E)
    resultado = ("coincidencia_total" if ratio >= umbral_total
                 else "coincidencia_parcial" if ratio > 0
                 else "discrepancia")
    return {"resultado": resultado, "ratio": round(ratio, 4),
            "coincidentes": inter, "faltantes": sorted(E - R)}


# ---------------------------------------------------------------------------
# Validación por carpeta y por lote
# ---------------------------------------------------------------------------

def _parsear_identificador(nombre: str, patron_dominante: str | None) -> dict:
    """Extrae prefijo numérico, nomenclatura y variante del nombre de carpeta."""
    prefijo = re.match(r"^(\d+)", nombre)
    partes = re.split(r"[_\-\s]+", nombre)
    variante = next((m.group(2) for p in partes
                     if (m := _RE_TOKEN_CODIGO.match(p)) and m.group(1).lower() == "variante"), None)
    nomenclatura = partes[1] if len(partes) > 1 and prefijo else None
    return {"prefijo_numerico": prefijo.group(1) if prefijo else None,
            "nomenclatura": nomenclatura, "variante": variante,
            "identificador": nombre}


def validar_lote(ruta_estructura: str | Path | None = None,
                 config: dict | None = None,
                 archivo_salida: str | Path | None = None,
                 al_resultado: Callable[[int, int, dict, float | None], None] | None = None,
                 al_imagen: Callable[[int, int, str, float | None], None] | None = None,
                 control: Callable[[], None] | None = None,
                 casos_omitidos: set[str] | None = None) -> dict:
    """
    Recorre las carpetas hoja de la estructura detectada, valida cada una y
    serializa validacion_resultados.json. Retorna la estructura completa
    (no imprime; el CLI se encarga de eso).
    """
    config = config or cargar_config()
    f2 = config.get("fase2", {})
    ruta_estructura = Path(ruta_estructura) if ruta_estructura else \
        RAIZ_PROYECTO / config.get("fase0", {}).get("archivo_salida", "estructura_detectada.json")
    with open(ruta_estructura, "r", encoding="utf-8") as f:
        estructura = json.load(f)

    patron_dominante = estructura.get("patron_dominante")
    cache_ocr: dict[str, dict] = {}
    cache_persistente = CacheOCR(
        RAIZ_PROYECTO / config.get("empresarial", {}).get(
            "archivo_cache_legacy", ".cache_ocr/imagenes_legacy.sqlite3"),
        {"fase1": config.get("fase1", {}),
         "normalizacion": config.get("normalizacion", {})})
    gestor_aprendizaje = GestorAprendizaje(config)
    resultados_existentes = []
    destino = Path(archivo_salida) if archivo_salida else RAIZ_PROYECTO / "validacion_resultados.json"
    if casos_omitidos and destino.is_file():
        try:
            resultados_existentes = json.loads(
                destino.read_text(encoding="utf-8")).get("resultados", [])
        except (OSError, json.JSONDecodeError):
            resultados_existentes = []
    resultados = [fila for fila in resultados_existentes
                  if str(fila.get("case_key") or fila.get("ruta")) in casos_omitidos]
    hojas = carpetas_hoja(estructura)
    if casos_omitidos:
        hojas = [carpeta for carpeta in hojas
                 if str(carpeta.get("case_key") or carpeta.get("ruta")) not in casos_omitidos]
    inicio = time.monotonic()
    total_imagenes = sum(len(c.get("archivos", {}).get("imagenes", [])) for c in hojas)
    imagenes_procesadas = 0
    ultimo_evento = inicio
    duraciones: deque[float] = deque(maxlen=8)

    def imagen_lista(ruta_imagen: str) -> None:
        nonlocal imagenes_procesadas, ultimo_evento
        ahora = time.monotonic()
        duraciones.append(max(0.01, ahora - ultimo_evento))
        ultimo_evento = ahora
        imagenes_procesadas += 1
        if al_imagen:
            muestras = list(duraciones)[1:] if imagenes_procesadas > 1 else []
            eta = (statistics.median(muestras) * (total_imagenes - imagenes_procesadas)
                   if muestras else None)
            al_imagen(imagenes_procesadas, total_imagenes, ruta_imagen,
                      round(eta, 1) if eta is not None else None)

    def persistir_legacy(parcial: bool) -> None:
        salida_parcial = {
            "raiz": estructura["raiz"],
            "generado_en": datetime.now().isoformat(timespec="seconds"),
            "estructura_usada": str(ruta_estructura), "perfil": "legacy",
            "parcial": parcial, "carpetas_procesadas": len(resultados),
            "resultados": resultados,
        }
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_suffix(destino.suffix + ".tmp")
        temporal.write_text(json.dumps(salida_parcial, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        temporal.replace(destino)

    for indice, carpeta in enumerate(hojas, start=1):
        fila = _validar_carpeta(
            carpeta, config, f2, cache_ocr, patron_dominante, imagen_lista, control,
            cache_persistente, gestor_aprendizaje)
        resultados.append(fila)
        persistir_legacy(parcial=True)
        if al_resultado:
            transcurrido = time.monotonic() - inicio
            eta = (transcurrido / indice) * (len(hojas) - indice) if indice else None
            al_resultado(indice, len(hojas), fila,
                         round(eta, 1) if eta is not None else None)

    aprendizaje = None
    if config.get("aprendizaje", {}).get("activar", True):
        try:
            from aprendizaje import GestorAprendizaje
            aprendizaje = GestorAprendizaje(config).registrar_ejecucion(
                list(cache_ocr.values()), raiz=estructura.get("raiz"))
        except Exception as exc:
            # El registro de aprendizaje nunca debe invalidar un lote ya
            # procesado; el error queda explícito en el artefacto de salida.
            aprendizaje = {"registrada": False, "error": f"{type(exc).__name__}: {exc}"}

    salida = {
        "raiz": estructura["raiz"],
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "estructura_usada": str(ruta_estructura),
        "carpetas_procesadas": len(resultados),
        "aprendizaje": aprendizaje,
        "resultados": resultados,
    }
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    salida["archivo_salida"] = str(destino)
    return salida


def _imagenes_legacy_caso(caso: dict) -> list[dict]:
    """Fallback acotado al caso incompleto; nunca degrada los demás casos."""
    raiz = Path(caso["ruta"])
    return [{"ruta": str(p), "ruta_relativa": p.relative_to(raiz).as_posix(),
             "fase": "LEGACY", "tor": None}
            for p in sorted(raiz.rglob("*"))
            if p.is_file() and p.suffix.lower() in EXTENSIONES_IMAGEN]


def validar_lote_empresarial(ruta_estructura: str | Path, config: dict | None = None,
                             archivo_salida: str | Path | None = None,
                             al_resultado: Callable[[int, int, dict, float | None], None] | None = None,
                             al_imagen: Callable[[int, int, str, float | None], None] | None = None,
                             control: Callable[[], None] | None = None,
                             casos_filtrados: set[str] | None = None,
                             casos_omitidos: set[str] | None = None,
                             imagenes_filtradas: set[str] | None = None,
                             solo_errores: bool = False,
                             modo_recorte: str | None = None,
                             roi_manual: dict[str, float] | None = None,
                             zoom_forzado: float | None = None,
                             al_caso: Callable[[dict], None] | None = None) -> dict:
    """Procesa todos los casos empresariales y consolida una sola salida por ID."""
    config = config or cargar_config()
    if roi_manual:
        config = deepcopy(config)
        config.setdefault("ocr", {}).setdefault("roi_manual", {})
        config["ocr"]["roi_manual"].update({"NACH": roi_manual, "VOR": roi_manual})
    with open(ruta_estructura, encoding="utf-8") as archivo:
        estructura = json.load(archivo)
    casos = estructura.get("casos_empresariales", [])
    if casos_filtrados:
        casos = [c for c in casos if c["case_key"] in casos_filtrados]
    if casos_omitidos:
        casos = [c for c in casos if c["case_key"] not in casos_omitidos]
    cfg_emp = config.get("empresarial", {})
    gestor_aprendizaje = GestorAprendizaje(config)
    estado_modelos = gestor_aprendizaje.estado()
    cache = CacheOCR(
        RAIZ_PROYECTO / cfg_emp.get("archivo_cache", ".cache_ocr/imagenes.json"),
        {"fase1": config.get("fase1", {}), "ocr": config.get("ocr", {}),
         "normalizacion": config.get("normalizacion", {}),
         "modelo_correccion": (estado_modelos.get("modelo_activo") or {}).get("version"),
         "modelo_visual": (estado_modelos.get("modelo_visual_activo") or {}).get("version")})
    conocimiento = BaseConocimiento(
        RAIZ_PROYECTO / cfg_emp.get("base_conocimiento", "base_conocimiento.json"),
        cfg_emp.get("reglas_minimo_ids", 3), cfg_emp.get("reglas_consenso_minimo", 0.90))
    todas_las_fotos = [f for c in casos for f in (
        c.get("fotos", []) if c.get("estructura_valida") else _imagenes_legacy_caso(c))]
    anotaciones_por_ruta: dict[str, list[dict]] = defaultdict(list)
    for anotacion in gestor_aprendizaje.listar_anotaciones(
            [f["ruta"] for f in todas_las_fotos]):
        if anotacion.get("ruta_imagen"):
            anotaciones_por_ruta[str(anotacion["ruta_imagen"])].append(anotacion)
    muestras_por_ruta: dict[str, list[dict]] = defaultdict(list)
    for muestra in gestor_aprendizaje.listar_muestras_visuales(
            [f["ruta"] for f in todas_las_fotos]):
        muestras_por_ruta[str(muestra.get("ruta_imagen"))].append(muestra)
    destino = Path(archivo_salida) if archivo_salida else RAIZ_PROYECTO / "validacion_resultados.json"
    resultados: list[dict] = []
    resultados_previos: list[dict] = []
    resultados_existentes: list[dict] = []
    avances_ids: dict[str, dict] = {}
    ruta_avances = RAIZ_PROYECTO / cfg_emp.get(
        "archivo_avance_ids", ".cache_ocr/avances_ids.json")
    if destino.is_file():
        try:
            resultados_existentes = json.loads(
                destino.read_text(encoding="utf-8")).get("resultados", [])
        except (OSError, json.JSONDecodeError):
            resultados_existentes = []
    if casos_filtrados or casos_omitidos:
        resultados_previos = resultados_existentes
    inicio = time.monotonic()
    total_imagenes = sum(len(c.get("fotos", [])) if c.get("estructura_valida")
                         else len(_imagenes_legacy_caso(c)) for c in casos)
    procesadas = 0
    duraciones: deque[float] = deque(maxlen=12)
    anterior = inicio

    def persistir(parcial: bool) -> None:
        combinados = {r.get("case_key") or r.get("ruta"): r for r in resultados_previos}
        combinados.update({r.get("case_key") or r.get("ruta"): r for r in resultados})
        salida_parcial = {
            "raiz": estructura["raiz"], "generado_en": datetime.now().isoformat(timespec="seconds"),
            "estructura_usada": str(ruta_estructura), "perfil": "empresarial",
            "tipo_st": estructura.get("tipo_st"), "tipos_st": estructura.get("tipos_st", []),
            "parcial": parcial, "carpetas_procesadas": len(combinados),
            "casos_encontrados": len(combinados), "resultados": list(combinados.values()),
        }
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_suffix(destino.suffix + ".tmp")
        with open(temporal, "w", encoding="utf-8") as archivo:
            json.dump(salida_parcial, archivo, ensure_ascii=False, indent=2)
        temporal.replace(destino)

    def persistir_avance_id() -> None:
        """Guarda sólo el ID activo; evita reescribir todo el lote por imagen."""
        ruta_avances.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta_avances.with_suffix(ruta_avances.suffix + ".tmp")
        temporal.write_text(json.dumps({
            "actualizado_en": ahora(), "avances_ids": avances_ids,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        temporal.replace(ruta_avances)

    for indice, caso in enumerate(casos, start=1):
        if control:
            control()
        caso = dict(caso)
        if modo_recorte:
            caso["modo_recorte"] = modo_recorte
        caso["estado"] = "procesando"
        if al_caso:
            al_caso(deepcopy(caso))
        fotos = caso.get("fotos", []) if caso.get("estructura_valida") else _imagenes_legacy_caso(caso)
        trazabilidad, evidencias, imagenes_salida, alertas = [], [], [], []
        if not fotos:
            alertas.append({"codigo": "SIN_IMAGENES", "nivel": "warning",
                            "mensaje": "El ID no contiene fotografías NACH/VOR procesables."})
        con_texto = sin_texto = errores = 0
        for foto in fotos:
            if control:
                control()
            ruta = foto["ruta"]
            resultado = None
            revision_sin_datos = gestor_aprendizaje.imagen_sin_datos(ruta)
            if revision_sin_datos:
                resultado = {"imagen": ruta, "tokens": [], "lineas_texto": [],
                             "texto_completo": "", "estado_imagen": "revisada_sin_datos",
                             "motivo_sin_datos": revision_sin_datos.get("motivo"),
                             "modo_recorte": "revision_manual"}
            try:
                resultado = resultado or cache.obtener(ruta)
            except OSError:
                resultado = resultado
            desde_cache = resultado is not None
            estado_cache = "revision_manual" if revision_sin_datos else (
                "leida" if desde_cache else "omitida")
            if imagenes_filtradas and ruta in imagenes_filtradas and not revision_sin_datos:
                resultado = None
                desde_cache = False
            if (solo_errores and desde_cache and not revision_sin_datos and
                    (resultado.get("error") or str(resultado.get("estado_imagen", "")).startswith("error"))):
                resultado = None
                desde_cache = False
            if resultado is None:
                try:
                    if caso.get("estructura_valida"):
                        preferencia_roi = gestor_aprendizaje.roi_preferida(
                            str(estructura.get("raiz") or "proyecto"),
                            str(foto.get("fase") or "VOR"), Path(ruta).name)
                        roi_foto = roi_manual or ((preferencia_roi or {}).get("roi"))
                        modo_foto = caso.get("modo_recorte")
                        if preferencia_roi and modo_recorte is None:
                            modo_foto = "manual"
                        resultado = extraer_texto_empresarial(
                            ruta, config, fase=foto.get("fase", "VOR"),
                            modo_recorte=modo_foto, roi_manual=roi_foto,
                            zoom_forzado=(zoom_forzado if zoom_forzado is not None else
                                          (preferencia_roi or {}).get("zoom")))
                    else:
                        resultado = extraer_texto(ruta, config)
                        resultado.update({"estado_imagen": "procesada_con_texto" if
                                          resultado.get("tokens") or resultado.get("lineas_texto")
                                          else "descartada_sin_texto",
                                          "modo_recorte": "completo", "tiempo_deteccion_seg": None,
                                          "tiempo_ocr_seg": None, "numero_regiones": None,
                                          "zoom_aplicado": 1.0})
                    estado_cache = cache.guardar(ruta, resultado).get("estado", "desconocida")
                except Exception as exc:
                    resultado = {"imagen": ruta, "tokens": [], "lineas_texto": [],
                                 "texto_completo": "", "estado_imagen": "error_ocr",
                                 "error": f"{type(exc).__name__}: {exc}", "modo_recorte":
                                 "auto" if caso.get("estructura_valida") else "completo"}
                    try:
                        estado_cache = cache.guardar(ruta, resultado).get("estado", "desconocida")
                    except OSError as cache_exc:
                        estado_cache = "error_cache"
                        alertas.append({"codigo": "ERROR_CACHE", "nivel": "warning",
                                        "imagen": Path(ruta).name,
                                        "mensaje": f"OCR conservado en memoria: {cache_exc}"})
            if estado_cache == "error_cache":
                alertas.append({"codigo": "ERROR_CACHE", "nivel": "warning",
                                "imagen": Path(ruta).name,
                                "mensaje": "No se pudo confirmar la escritura del caché; se reintentará."})
            estado_imagen = resultado.get("estado_imagen", "procesada_con_texto")
            if estado_imagen in {"procesada_con_texto", "procesada_con_qr"}:
                con_texto += 1
            elif estado_imagen in {"descartada_sin_texto", "revisada_sin_datos"}:
                sin_texto += 1
            else:
                errores += 1
                es_corrupta = "ValueError" in str(resultado.get("error", "")) and \
                    "decodificar" in str(resultado.get("error", "")).lower()
                alertas.append({"codigo": "IMAGEN_CORRUPTA" if es_corrupta else "ERROR_OCR",
                                "nivel": "error",
                                "imagen": Path(ruta).name,
                                "mensaje": resultado.get("error", "No se pudo leer la imagen.")})
            confianza = resultado.get("confianza_media") or 0.0
            foto_contexto = {**foto, "confianza_ocr": confianza}
            evidencias.extend(extraer_candidatos_texto(
                resultado.get("texto_completo", ""), foto_contexto,
                caso.get("metadata_ruta", {})))
            evidencias.extend(evidencias_desde_qr(
                resultado.get("qrs", []), foto_contexto,
                config.get("fase1", {}).get("qr", {}).get("aliases")))
            for qr in resultado.get("qrs", []):
                interpretacion = qr.get("interpretacion", {})
                qr.update({
                    "qr_detectado": True, "payload_original": qr.get("payload", ""),
                    "formato": interpretacion.get("formato", "desconocido"),
                    "imagen": foto.get("ruta_relativa") or ruta,
                    "fase": foto.get("fase"), "tor": foto.get("tor"),
                    "valido_esquema": bool(interpretacion.get("campos")),
                    "campos_extraidos": interpretacion.get("campos", {}),
                })
            for anotacion in anotaciones_por_ruta.get(str(ruta), []):
                evidencias.extend(extraer_candidatos_texto(
                    anotacion.get("texto_correcto", ""),
                    {**foto_contexto, "fuente": "manual", "confianza_ocr": 1.0},
                    caso.get("metadata_ruta", {})))
            qrs_foto = resultado.get("qrs", [])
            evidencias_foto = [e for e in evidencias
                               if e.get("imagen") == foto.get("ruta_relativa")]
            trazabilidad.append({
                "test_number": caso.get("metadata_ruta", {}).get("test_number"),
                "tipo_st": caso.get("tipo_st"),
                "temperature_condition": caso.get("metadata_ruta", {}).get("temperature_condition"),
                "module_version": caso.get("metadata_ruta", {}).get("module_version"),
                "inflator_type": caso.get("metadata_ruta", {}).get("inflator_type"),
                "fase": foto.get("fase"), "tor": foto.get("tor"),
                "ruta_absoluta": ruta, "ruta_relativa": foto.get("ruta_relativa"),
                "estado_imagen": estado_imagen,
                "texto_crudo": resultado.get("texto_completo", ""),
                "confianza_ocr": resultado.get("confianza_media"),
                "coordenadas_roi": resultado.get("roi_usado"),
                "zoom_aplicado": resultado.get("zoom_aplicado"),
                "modo_recorte": resultado.get("modo_recorte"),
                "dispositivo": resultado.get("dispositivo"),
                "tiempo_deteccion": resultado.get("tiempo_deteccion_seg"),
                "tiempo_ocr": resultado.get("tiempo_ocr_seg"),
                "campos_detectados": sorted({e["clave"] for e in evidencias
                                             if e.get("imagen") == foto.get("ruta_relativa")}),
                "requiere_revision": bool(resultado.get("error")),
                "mensaje_error": resultado.get("error"), "desde_cache": desde_cache,
                "revision_sin_datos": revision_sin_datos,
                "estado_cache": estado_cache,
                "qr_payloads": [q.get("payload") for q in resultado.get("qrs", [])
                                if q.get("payload")],
                "qr_detectado": bool(qrs_foto),
                "payload_qr": [q.get("payload_original") or q.get("payload") for q in qrs_foto],
                "poligono_qr": [q.get("poligono") for q in qrs_foto],
                "fuente_campo": sorted({f"{e.get('clave')}:{e.get('fuente')}"
                                         for e in evidencias_foto}),
                "modelo_ocr": resultado.get("modelo_visual_version") or resultado.get("motor"),
                "correccion_confirmada": bool(anotaciones_por_ruta.get(str(ruta))),
                "dataset_entrenamiento": [m.get("ruta_recorte")
                                           for m in muestras_por_ruta.get(str(ruta), [])],
            })
            imagenes_salida.append({"id": hashlib.sha256(ruta.encode()).hexdigest()[:16],
                                    "nombre": Path(ruta).name, "ruta": ruta,
                                    "ruta_relativa": foto.get("ruta_relativa"),
                                    "fase": foto.get("fase"), "tor": foto.get("tor"),
                                    "rol": "foto_empresarial", "estado_imagen": estado_imagen,
                                    "resultado_ocr": _compacto(resultado)})
            procesadas += 1
            caso["progreso"] = {
                "total_imagenes": len(fotos), "revisadas": len(trazabilidad),
                "con_texto": con_texto, "sin_texto": sin_texto, "errores": errores,
                "porcentaje": round(100 * len(trazabilidad) / len(fotos), 2) if fotos else 100.0,
            }
            if al_caso:
                al_caso(deepcopy(caso))
            avances_ids[caso["case_key"]] = {
                "case_key": caso["case_key"], "nombre": caso.get("nombre"),
                "progreso": deepcopy(caso["progreso"]),
                "imagenes": deepcopy(imagenes_salida),
                "trazabilidad": deepcopy(trazabilidad),
                "evidencias": deepcopy(evidencias),
                "actualizado_en": ahora(),
            }
            persistir_avance_id()
            ahora_monotonic = time.monotonic()
            duraciones.append(max(0.001, ahora_monotonic - anterior))
            anterior = ahora_monotonic
            if al_imagen:
                eta = statistics.median(duraciones) * max(total_imagenes - procesadas, 0)
                al_imagen(procesadas, total_imagenes, ruta, round(eta, 1))

        recuperacion_cache = cache.recuperar_pendientes()
        fallos_cache = [item for item in recuperacion_cache
                        if item.get("estado") == "error_cache"]
        if fallos_cache:
            alertas.append({"codigo": "ERROR_CACHE", "nivel": "warning",
                            "mensaje": (f"Persisten {len(fallos_cache)} escrituras OCR en memoria; "
                                        "se reintentará en la siguiente ejecución.")})

        previo = next((r for r in resultados_existentes
                       if r.get("case_key") == caso.get("case_key")), {})
        consolidado = consolidar_caso(
            caso, evidencias,
            requeridos=set(cfg_emp.get("campos_requeridos") or CAMPOS_REQUERIDOS_DEFAULT),
            reglas_confirmadas=conocimiento.confirmadas(),
            claves=cfg_emp.get("claves_plantilla") or CLAVES_PLANTILLA)
        correcciones_manual_campos = deepcopy(previo.get("correcciones_manual_campos", {}))
        for clave, correccion in correcciones_manual_campos.items():
            if clave not in consolidado["campos"] or not correccion.get("valor"):
                continue
            original_ruta = caso.get("metadata_ruta", {}).get(clave)
            conflicto_ruta = original_ruta not in {None, "", correccion["valor"]}
            consolidado["campos"][clave] = {
                "valor": correccion["valor"], "valor_original": correccion["valor"],
                "estado": "pendiente_revision" if conflicto_ruta else "confirmado_manual",
                "fuente": "correccion_manual_confirmada", "confianza": 1.0,
                "inferido": False, "requiere_revision": conflicto_ruta,
                "valor_seguro_ruta": original_ruta if conflicto_ruta else None,
                "corregido_en": correccion.get("corregido_en"),
                "corregido_por": correccion.get("corregido_por"),
            }
            consolidado["campos_faltantes"] = [
                campo for campo in consolidado["campos_faltantes"] if campo != clave]
            if conflicto_ruta and clave not in consolidado["conflictos"]:
                consolidado["conflictos"].append(clave)
            elif not conflicto_ruta:
                consolidado["conflictos"] = [
                    campo for campo in consolidado["conflictos"] if campo != clave]
        consolidado["requiere_revision"] = bool(
            consolidado["conflictos"] or any(
                dato.get("requiere_revision") for dato in consolidado["campos"].values()))
        progreso = {"total_imagenes": len(fotos), "revisadas": len(trazabilidad),
                    "con_texto": con_texto, "sin_texto": sin_texto,
                    "errores": errores,
                    "porcentaje": round(100 * len(trazabilidad) / len(fotos), 2) if fotos else 100.0}
        alertas_agrupadas: dict[tuple[str, str], dict] = {}
        for alerta in alertas:
            clave_alerta = (alerta.get("codigo", "ADVERTENCIA"), alerta.get("mensaje", ""))
            grupo = alertas_agrupadas.setdefault(clave_alerta, {
                **alerta, "imagenes": [], "cantidad": 0})
            grupo["cantidad"] += 1
            if alerta.get("imagen") and alerta["imagen"] not in grupo["imagenes"]:
                grupo["imagenes"].append(alerta["imagen"])
        alertas = list(alertas_agrupadas.values())
        estado = ("con_conflictos" if consolidado["conflictos"] else
                  "procesada_con_advertencias" if consolidado["campos_faltantes"] or errores else
                  "procesada")
        fila = {
            "case_key": caso["case_key"], "id": hashlib.sha256(caso["case_key"].encode()).hexdigest()[:16],
            "ruta": caso["ruta"], "ruta_relativa": caso["ruta_relativa"], "nombre": caso["nombre"],
            "identificador": consolidado["test_number"] or caso["nombre"],
            "test_number": consolidado["test_number"], "tipo_st": caso.get("tipo_st"),
            **caso.get("metadata_ruta", {}), "perfil": "empresarial",
            "modo_procesamiento": caso["modo_procesamiento"],
            "estructura_valida": caso["estructura_valida"], "validaciones": caso["validaciones"],
            "estado": estado, "progreso": progreso, "total_imagenes": len(fotos),
            "imagenes_nach": caso.get("imagenes_nach", 0), "imagenes_vor": caso.get("imagenes_vor", 0),
            "carpetas_tor": caso.get("carpetas_tor", []),
            "imagenes_omitidas_fuera_photos": caso.get("imagenes_omitidas_fuera_photos", 0),
            "imagenes": imagenes_salida, "trazabilidad": trazabilidad,
            "consolidado": consolidado, "campos": consolidado["campos"],
            "correcciones_manual_campos": correcciones_manual_campos,
            "campos_faltantes": consolidado["campos_faltantes"],
            "conflictos": consolidado["conflictos"],
            "candidatos": consolidado["candidatos"],
            "requiere_revision": consolidado["requiere_revision"] or bool(errores),
            "ultima_ejecucion": ahora(), "alertas": alertas,
            # Compatibilidad con Excel/dashboard anteriores.
            "tipos_archivo": {"fotografia": [i["nombre"] for i in imagenes_salida]},
            "etiqueta": ({"ruta": imagenes_salida[0]["ruta"],
                           "resultado_ocr": imagenes_salida[0]["resultado_ocr"]}
                          if imagenes_salida else None),
            "referencia": None, "comparacion": {
                "resultado": "coincidencia_total" if not consolidado["conflictos"] and
                not consolidado["campos_faltantes"] else
                "discrepancia" if consolidado["conflictos"] else "coincidencia_parcial",
                "ratio": None, "coincidentes": [], "faltantes": []},
            "confianza_ocr_pct": (round(statistics.mean(
                [t["confianza_ocr"] for t in trazabilidad if t.get("confianza_ocr") is not None]) * 100, 2)
                if any(t.get("confianza_ocr") is not None for t in trazabilidad) else None),
            "qr_detectado": any(i.get("resultado_ocr", {}).get("qrs") for i in imagenes_salida),
            "observaciones": (["procesado por fallback legacy del caso"]
                                                       if not caso["estructura_valida"] else []),
            "historial_ejecuciones": [*previo.get("historial_ejecuciones", []), {
                "iniciado_en": datetime.fromtimestamp(
                    datetime.now().timestamp() - (time.monotonic() - inicio)
                ).isoformat(timespec="seconds"),
                "finalizado_en": ahora(), "estado": estado,
                "modo_recorte": caso.get("modo_recorte") or
                                config.get("ocr", {}).get("modo_recorte", "auto"),
                "imagenes_revisadas": len(trazabilidad), "con_texto": con_texto,
                "sin_texto": sin_texto, "errores": errores,
                "reproceso_selectivo": bool(casos_filtrados),
            }],
            "historial_acciones": deepcopy(previo.get("historial_acciones", [])),
        }
        resultados.append(fila)
        avances_ids.pop(caso["case_key"], None)
        persistir_avance_id()
        persistir(parcial=True)
        if al_resultado:
            transcurrido = time.monotonic() - inicio
            eta = transcurrido / indice * (len(casos) - indice)
            al_resultado(indice, len(casos), fila, round(eta, 1))

    propuestas = conocimiento.proponer([*resultados_previos, *resultados])
    persistir(parcial=False)
    salida = json.loads(destino.read_text(encoding="utf-8"))
    salida.update({
        "archivo_salida": str(destino), "base_conocimiento": str(conocimiento.ruta),
        "reglas_propuestas": propuestas,
        "resumen_empresarial": {
            "estructura": "Empresarial", "tipos_st": estructura.get("tipos_st", []),
            "casos_encontrados": len(casos),
            "casos_validos": sum(c.get("estructura_valida", False) for c in casos),
            "casos_legacy": sum(not c.get("estructura_valida", False) for c in casos),
            "fotos_revisadas": sum(r["progreso"]["revisadas"] for r in resultados),
            "fotos_con_texto": sum(r["progreso"]["con_texto"] for r in resultados),
            "fotos_descartadas_sin_texto": sum(r["progreso"]["sin_texto"] for r in resultados),
            "imagenes_omitidas_fuera_photos": sum(r["imagenes_omitidas_fuera_photos"] for r in resultados),
            "ids_completos": sum(not r["campos_faltantes"] and not r["conflictos"] for r in resultados),
            "ids_con_informacion_faltante": sum(bool(r["campos_faltantes"]) for r in resultados),
            "ids_con_conflictos": sum(bool(r["conflictos"]) for r in resultados),
            "reglas_propuestas": len(propuestas),
        },
    })
    with open(destino, "w", encoding="utf-8") as archivo:
        json.dump(salida, archivo, ensure_ascii=False, indent=2)
    return salida


def _validar_carpeta(carpeta: dict, config: dict, f2: dict,
                     cache_ocr: dict, patron_dominante: str | None,
                     al_imagen: Callable[[str], None] | None = None,
                     control: Callable[[], None] | None = None,
                     cache_persistente: CacheOCR | None = None,
                     gestor_aprendizaje: GestorAprendizaje | None = None) -> dict:
    """Procesa una carpeta hoja completa (clasificación + OCR + comparación)."""
    ruta = Path(carpeta["ruta"])
    observaciones: list[str] = []
    alertas: list[dict] = []
    if not carpeta["conforme"]:
        observaciones.append(f"anomalía de Fase 0: {carpeta['motivo_anomalia']}")

    # 1. Clasificar archivos (imágenes se OCR-ean con caché).
    categorias: dict[str, list[str]] = {}
    for nombre in (carpeta["archivos"]["imagenes"] + carpeta["archivos"]["otros"]
                   + carpeta["archivos"]["videos"]):
        cat = clasificar_archivo(str(ruta / nombre), config)
        categorias.setdefault(cat, []).append(nombre)
    if categorias.get("video"):
        alertas.append({
            "codigo": "VIDEOS_IGNORADOS", "nivel": "info",
            "mensaje": (f"Se ignoraron {len(categorias['video'])} video(s). "
                        "Esta versión procesa únicamente fotografías."),
        })

    imagenes = [ruta / n for n in carpeta["archivos"]["imagenes"]]
    ocr_por_imagen = []
    for img in imagenes:
        if control:
            control()
        clave = str(img)
        if clave not in cache_ocr:
            try:
                sin_datos = (gestor_aprendizaje.imagen_sin_datos(clave)
                             if gestor_aprendizaje else None)
                cache_ocr[clave] = ({"imagen": clave, "tokens": [], "lineas_texto": [],
                                     "texto_completo": "",
                                     "estado_imagen": "revisada_sin_datos",
                                     "motivo_sin_datos": sin_datos.get("motivo")}
                                    if sin_datos else
                                    (cache_persistente.obtener(clave)
                                     if cache_persistente else None))
                if cache_ocr[clave] is None:
                    cache_ocr[clave] = extraer_texto(clave, config)
                    if cache_persistente:
                        cache_persistente.guardar(clave, cache_ocr[clave])
            except Exception as exc:
                cache_ocr[clave] = {"imagen": clave, "tokens": [], "qr_bbox": None,
                                    "orientacion_corregida_grados": 0.0,
                                    "confianza_media": None, "num_lineas_ocr": 0,
                                    "error": str(exc)}
                if cache_persistente:
                    try:
                        cache_persistente.guardar(clave, cache_ocr[clave])
                    except OSError:
                        pass
                alertas.append({
                    "codigo": ("IMAGEN_CORRUPTA" if isinstance(exc, ValueError)
                               else "ERROR_LECTURA_IMAGEN"),
                    "nivel": "error", "imagen": img.name,
                    "mensaje": f"No se pudo procesar {img.name}: {exc}",
                })
        resultado_actual = cache_ocr[clave]
        if (resultado_actual.get("estado_imagen") != "revisada_sin_datos" and
                not resultado_actual.get("error") and
                not resultado_actual.get("tokens") and
                not resultado_actual.get("lineas_texto")):
            alertas.append({
                "codigo": "SIN_TEXTO_DETECTADO", "nivel": "warning",
                "imagen": img.name,
                "mensaje": f"No se encontró texto legible en {img.name}; requiere revisión manual.",
            })
        for warning_motor in resultado_actual.get("advertencias_motor", []):
            alerta = {"codigo": "FALLBACK_ACELERADOR", "nivel": "warning",
                      "imagen": img.name, "mensaje": warning_motor}
            if alerta not in alertas:
                alertas.append(alerta)
        ocr_por_imagen.append({"ruta": clave, "resultado_ocr": cache_ocr[clave]})
        if al_imagen:
            al_imagen(clave)

    if not imagenes:
        alertas.append({
            "codigo": "SIN_IMAGENES", "nivel": "warning",
            "mensaje": "La carpeta no contiene fotografías compatibles; no se ejecutó OCR.",
        })
        return {
            "ruta": str(ruta), "nombre": carpeta["nombre"],
            **_parsear_identificador(carpeta["nombre"], patron_dominante),
            "es_conforme": carpeta["conforme"],
            "anomalia_fase0": carpeta["motivo_anomalia"],
            "tipos_archivo": categorias,
            "etiqueta": None, "referencia": None, "imagenes": [],
            "comparacion": {"resultado": "sin_procesar", "ratio": None,
                            "coincidentes": [], "faltantes": []},
            "confianza_ocr_pct": None, "qr_detectado": False,
            "observaciones": observaciones + ["carpeta sin imágenes"],
            "alertas": alertas,
        }

    # 2. Referencia: pista de nombre primero; si no, heurística de densidad.
    candidatos_nombre = [c for c in categorias.get("candidato_referencia", [])]
    referencias: set[str] = set()
    if candidatos_nombre:
        referencias = {str(ruta / nombre) for nombre in candidatos_nombre}
    else:
        detectada = identificar_referencia(
            ocr_por_imagen,
            umbral=float(f2.get("umbral_densidad_texto", 0.01)),
            ventaja_minima=float(f2.get("ventaja_minima_referencia", 1.5)))
        if detectada is not None:
            referencias.add(detectada)
            observaciones.append("referencia detectada por densidad de texto")

    referencia = sorted(referencias)[0] if referencias else None
    items_referencia = [x for x in ocr_por_imagen if x["ruta"] in referencias]
    ref_ocr = items_referencia[0]["resultado_ocr"] if items_referencia else None

    # 3. Etiqueta: la mejor fotografía (o la primera, según estrategia).
    fotos = [x for x in ocr_por_imagen if x["ruta"] not in referencias]
    estrategia = f2.get("estrategia_etiqueta", "mejor_confianza")
    if estrategia == "mejor_confianza" and fotos:
        etiqueta_item = max(fotos, key=lambda x: (x["resultado_ocr"].get("confianza_media") or 0.0))
    else:
        etiqueta_item = sorted(fotos, key=lambda x: x["ruta"])[0] if fotos else None

    if etiqueta_item is None:  # solo había imagen(es) de referencia
        imagenes_salida = [_imagen_salida(x, "referencia") for x in items_referencia]
        return {
            "ruta": str(ruta), "nombre": carpeta["nombre"],
            **_parsear_identificador(carpeta["nombre"], patron_dominante),
            "es_conforme": carpeta["conforme"],
            "anomalia_fase0": carpeta["motivo_anomalia"],
            "tipos_archivo": categorias,
            "etiqueta": None,
            "referencia": {"ruta": referencia, "resultado_ocr": _compacto(ref_ocr)},
            "imagenes": imagenes_salida,
            "comparacion": {"resultado": "sin_procesar", "ratio": None,
                            "coincidentes": [], "faltantes": []},
            "confianza_ocr_pct": None, "qr_detectado": False,
            "observaciones": observaciones + ["sin fotografías de etiqueta"],
            "alertas": alertas,
        }

    et_ocr = etiqueta_item["resultado_ocr"]
    tokens_etiqueta = [t["texto"] for foto in fotos
                       for t in foto["resultado_ocr"].get("tokens", [])]
    tokens_referencia = [t["texto"] for item in items_referencia
                         for t in item["resultado_ocr"].get("tokens", [])]
    comparacion = comparar_tokens(
        tokens_etiqueta,
        tokens_referencia,
        umbral_total=float(f2.get("umbral_coincidencia_total", 1.0)),
        solo_tokens_codigo=bool(f2.get("comparar_solo_tokens_codigo", True)),
    )
    if referencia is None:
        observaciones.append("sin imagen de referencia en la carpeta")
    for foto in fotos:
        if foto["resultado_ocr"].get("error"):
            observaciones.append(
                f"error OCR {Path(foto['ruta']).name}: {foto['resultado_ocr']['error']}")

    conf_pct = round(et_ocr["confianza_media"] * 100, 2) if et_ocr.get("confianza_media") is not None else None

    imagenes_salida = []
    for item in ocr_por_imagen:
        if item["ruta"] in referencias:
            rol = "referencia"
        elif item["ruta"] == etiqueta_item["ruta"]:
            rol = "etiqueta_principal"
        else:
            rol = "etiqueta_adicional"
        imagenes_salida.append(_imagen_salida(item, rol))

    return {
        "ruta": str(ruta),
        "nombre": carpeta["nombre"],
        **_parsear_identificador(carpeta["nombre"], patron_dominante),
        "es_conforme": carpeta["conforme"],
        "anomalia_fase0": carpeta["motivo_anomalia"],
        "tipos_archivo": categorias,
        "etiqueta": {"ruta": etiqueta_item["ruta"], "resultado_ocr": _compacto(et_ocr)},
        "referencia": ({"ruta": referencia, "resultado_ocr": _compacto(ref_ocr)}
                       if referencia else None),
        "imagenes": imagenes_salida,
        "comparacion": comparacion,
        "confianza_ocr_pct": conf_pct,
        "qr_detectado": any(f["resultado_ocr"].get("qr_bbox") is not None for f in fotos),
        "observaciones": observaciones,
        "alertas": alertas,
    }


def _compacto(resultado_ocr: dict | None) -> dict | None:
    """Versión ligera del resultado OCR para el JSON (sin campos voluminosos)."""
    if resultado_ocr is None:
        return None
    return {k: resultado_ocr.get(k) for k in (
        "tokens", "lineas_texto", "texto_completo", "codigos_detectados",
        "reglas_codigo", "qr_bbox",
        "confianza_media", "num_lineas_ocr",
        "rotacion_manual_aplicada_grados", "orientacion_manual_prioritaria",
        "orientacion_automatica_preservada_grados",
        "deskew_automatico_preservado_grados", "geometria_automatica_preservada",
        "orientacion_base_grados",
        "deskew_aplicado_grados", "orientacion_corregida_grados",
        "orientacion_texto_base_grados", "deskew_texto_aplicado_grados",
        "orientacion_texto_grados", "variante_preprocesamiento",
        "variante_texto_completo", "dimensiones_originales",
        "intentos_ocr", "motor", "dispositivo", "advertencias_motor",
        "dimensiones", "estado_imagen", "modo_recorte", "tiempo_deteccion_seg",
        "tiempo_ocr_seg", "numero_regiones", "zoom_aplicado", "roi_usado", "error",
        "qrs", "recortes", "modelo_visual_version")}


def _imagen_salida(item: dict, rol: str) -> dict:
    """Serializa cada imagen de la carpeta sin descartar tomas adicionales."""
    ruta = str(item["ruta"])
    return {
        "id": hashlib.sha256(ruta.encode("utf-8")).hexdigest()[:16],
        "nombre": Path(ruta).name,
        "ruta": ruta,
        "rol": rol,
        "resultado_ocr": _compacto(item["resultado_ocr"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fase 2: validación cruzada por carpeta.")
    parser.add_argument("--estructura", default=None,
                        help="Ruta de estructura_detectada.json (default: config).")
    parser.add_argument("--salida", default=None, help="JSON de salida (default: validacion_resultados.json).")
    args = parser.parse_args()

    salida = validar_lote(args.estructura, archivo_salida=args.salida)
    print(f"Carpetas procesadas: {salida['carpetas_procesadas']}")
    for fila in salida["resultados"]:
        comp = fila["comparacion"]["resultado"]
        conf = fila["confianza_ocr_pct"]
        print(f"  {fila['nombre']:22} -> {comp:20} conf={conf}  qr={fila['qr_detectado']} "
              f"ref={'sí' if fila['referencia'] else 'no'}  obs={fila['observaciones']}")
    print(f"JSON guardado en: {salida['archivo_salida']}")
