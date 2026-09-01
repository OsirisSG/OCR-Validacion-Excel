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
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from configuracion import RAIZ_PROYECTO, cargar_config
from estructura import carpetas_hoja
from ocr_engine import cargar_imagen, extraer_texto

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
                 control: Callable[[], None] | None = None) -> dict:
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
    resultados = []
    hojas = carpetas_hoja(estructura)
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

    for indice, carpeta in enumerate(hojas, start=1):
        fila = _validar_carpeta(
            carpeta, config, f2, cache_ocr, patron_dominante, imagen_lista, control)
        resultados.append(fila)
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
    destino = Path(archivo_salida) if archivo_salida else RAIZ_PROYECTO / "validacion_resultados.json"
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    salida["archivo_salida"] = str(destino)
    return salida


def _validar_carpeta(carpeta: dict, config: dict, f2: dict,
                     cache_ocr: dict, patron_dominante: str | None,
                     al_imagen: Callable[[str], None] | None = None,
                     control: Callable[[], None] | None = None) -> dict:
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
                cache_ocr[clave] = extraer_texto(clave, config)
            except Exception as exc:
                cache_ocr[clave] = {"imagen": clave, "tokens": [], "qr_bbox": None,
                                    "orientacion_corregida_grados": 0.0,
                                    "confianza_media": None, "num_lineas_ocr": 0,
                                    "error": str(exc)}
                alertas.append({
                    "codigo": ("IMAGEN_CORRUPTA" if isinstance(exc, ValueError)
                               else "ERROR_LECTURA_IMAGEN"),
                    "nivel": "error", "imagen": img.name,
                    "mensaje": f"No se pudo procesar {img.name}: {exc}",
                })
        resultado_actual = cache_ocr[clave]
        if (not resultado_actual.get("error") and
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
        "tokens", "lineas_texto", "texto_completo", "qr_bbox",
        "confianza_media", "num_lineas_ocr",
        "rotacion_manual_aplicada_grados", "orientacion_base_grados",
        "deskew_aplicado_grados", "orientacion_corregida_grados",
        "orientacion_texto_base_grados", "deskew_texto_aplicado_grados",
        "orientacion_texto_grados", "variante_preprocesamiento",
        "variante_texto_completo", "dimensiones_originales",
        "intentos_ocr", "motor", "dispositivo", "advertencias_motor",
        "dimensiones", "error")}


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
