"""Banco local y reproducible de fotografías OCR difíciles.

Las imágenes viven en ``.pruebas_externas`` (fuera de Git). El módulo solo
versiona el contrato, las verdades esperadas y las métricas. De este modo el
dashboard puede mostrarlas sin redistribuir archivos de terceros.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Callable

from configuracion import RAIZ_PROYECTO, cargar_config
from ocr_engine import extraer_texto
from utilidades.persistencia import escribir_json_seguro

FUENTES = {
    "embossed": {
        "nombre": "Embossed-Text-Reader",
        "url": "https://github.com/DevashishPrasad/Embossed-Text-Reader",
        "licencia": "sin licencia declarada; uso local, no redistribuido",
    },
    "easyocr": {
        "nombre": "EasyOCR examples",
        "url": "https://github.com/JaidedAI/EasyOCR/tree/master/examples",
        "licencia": "Apache-2.0",
    },
}

CASOS = {
    "test4.jpg": {"tipo": "codigo", "esperado": "IBC20", "fuente": "embossed"},
    "test5.jpg": {"tipo": "codigo", "esperado": "GCC10", "fuente": "embossed"},
    "test18.jpg": {"tipo": "codigo", "esperado": "123456789", "fuente": "embossed"},
    "test2.jpg": {"tipo": "codigo", "esperado": "96819216", "fuente": "embossed"},
    "easyocr_english.png": {
        "tipo": "texto", "fuente": "easyocr",
        "esperados": [
            "Reduce your risk of coronavirus infection",
            "Clean hands with soap and water",
            "Cover nose and mouth when coughing and sneezing with tissue or flexed elbow",
            "Avoid close contact with anyone with cold or flu-like symptoms",
            "Thoroughly cook meat and eggs",
            "No unprotected contact with live wild or farm animals",
            "World Health Organization",
        ],
    },
    "easyocr_example3.png": {
        "tipo": "texto", "fuente": "easyocr",
        "esperados": ["50 40", "BASRURKAR MARKET", "SPEED LIMIT"],
    },
    "easyocr_french.jpg": {
        "tipo": "texto", "fuente": "easyocr",
        "esperados": ["Mairie du 1er", "Palais du Louvre", "LES ARTS DECORATIFS",
                      "Musee du Louvre", "Theatre du PALAIS ROYAL"],
    },
    "easyocr_chinese.jpg": {
        "tipo": "texto", "fuente": "easyocr",
        "esperados": ["315", "Yuyuan Rd", "309"],
    },
}


def normalizar(texto: str) -> str:
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", str(texto))
                          if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]", "", sin_acentos.upper())


def distancia_edicion(a: str, b: str) -> int:
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(actual[-1] + 1, anterior[j] + 1,
                              anterior[j - 1] + (ca != cb)))
        anterior = actual
    return anterior[-1]


def rutas(config: dict | None = None) -> tuple[Path, Path]:
    config = config or cargar_config()
    bloque = config.get("pruebas_externas", {})
    directorio = Path(bloque.get(
        "directorio", ".pruebas_externas/embossed-text-reader/images"))
    salida = Path(bloque.get(
        "archivo_resultados", ".pruebas_externas/resultados.json"))
    if not directorio.is_absolute():
        directorio = RAIZ_PROYECTO / directorio
    if not salida.is_absolute():
        salida = RAIZ_PROYECTO / salida
    return directorio.resolve(), salida.resolve()


def evaluar(config: dict | None = None,
            al_resultado: Callable[[int, int, dict], None] | None = None) -> dict:
    config = config or cargar_config()
    directorio, salida = rutas(config)
    faltantes = [nombre for nombre in CASOS if not (directorio / nombre).is_file()]
    if faltantes:
        raise FileNotFoundError("Faltan imágenes externas: " + ", ".join(faltantes))

    resultados = []
    for indice, (nombre, caso) in enumerate(CASOS.items(), start=1):
        ruta = (directorio / nombre).resolve()
        inicio = time.perf_counter()
        ocr = extraer_texto(str(ruta), config)
        tokens_completos = ocr.get("tokens", [])
        if caso["tipo"] == "codigo":
            esperado = caso["esperado"]
            candidatos = [normalizar(t.get("texto", ""))
                          for t in tokens_completos] or [""]
            candidatos_brutos = [normalizar(t.get("texto_original") or t.get("texto", ""))
                                 for t in tokens_completos] or [""]
            mejor = min(candidatos, key=lambda texto: distancia_edicion(esperado, texto))
            mejor_bruto = min(candidatos_brutos,
                               key=lambda texto: distancia_edicion(esperado, texto))
            distancia = distancia_edicion(esperado, mejor)
            distancia_bruta = distancia_edicion(esperado, mejor_bruto)
            similitud = 1.0 - distancia / max(len(esperado), len(mejor), 1)
            similitud_bruta = 1.0 - distancia_bruta / max(
                len(esperado), len(mejor_bruto), 1)
            esperados = [esperado]
            encontrados = [esperado] if mejor == esperado else []
        else:
            esperados = caso["esperados"]
            texto_normalizado = normalizar(ocr.get("texto_completo", ""))
            encontrados = [fragmento for fragmento in esperados
                           if normalizar(fragmento) in texto_normalizado]
            similitud = len(encontrados) / max(len(esperados), 1)
            mejor = ocr.get("texto_completo", "")
            mejor_bruto = mejor
            similitud_bruta = similitud
            esperado = "\n".join(esperados)
        fila = {
            "id": f"externa-{Path(nombre).stem}",
            "imagen": nombre,
            "ruta": str(ruta),
            "esperado": esperado,
            "esperados": esperados,
            "encontrados": encontrados,
            "tipo": caso["tipo"],
            "fuente": FUENTES[caso["fuente"]],
            "mejor_candidato": mejor,
            "mejor_candidato_bruto": mejor_bruto,
            "coincidencia_exacta": len(encontrados) == len(esperados),
            "coincidencia_exacta_bruta": (mejor_bruto == esperado
                                           if caso["tipo"] == "codigo"
                                           else len(encontrados) == len(esperados)),
            "similitud_caracteres": round(similitud, 4),
            "similitud_caracteres_bruta": round(similitud_bruta, 4),
            "correccion_memorizada": any(
                t.get("correccion_modelo", {}).get("tipo") == "memoria_imagen_confirmada"
                for t in tokens_completos),
            "cobertura": round(len(encontrados) / max(len(esperados), 1), 4),
            "tokens": tokens_completos,
            "lineas_texto": ocr.get("lineas_texto", []),
            "texto_completo": ocr.get("texto_completo", ""),
            "orientacion_grados": ocr.get("orientacion_corregida_grados"),
            "rotacion_manual_aplicada_grados": ocr.get(
                "rotacion_manual_aplicada_grados", 0),
            "orientacion_base_grados": ocr.get("orientacion_base_grados", 0),
            "deskew_aplicado_grados": ocr.get("deskew_aplicado_grados", 0),
            "orientacion_texto_base_grados": ocr.get(
                "orientacion_texto_base_grados", 0),
            "deskew_texto_aplicado_grados": ocr.get(
                "deskew_texto_aplicado_grados", 0),
            "variante": ocr.get("variante_preprocesamiento"),
            "intentos": len(ocr.get("intentos_ocr", [])),
            "motor": ocr.get("motor"),
            "dispositivo": ocr.get("dispositivo", "cpu"),
            "dimensiones": ocr.get("dimensiones"),
            "dimensiones_originales": ocr.get("dimensiones_originales"),
            "alertas": [
                {"codigo": "FALLBACK_ACELERADOR", "nivel": "advertencia", "mensaje": mensaje}
                for mensaje in ocr.get("advertencias_motor", [])
            ] + ([{
                "codigo": "SIN_TEXTO_DETECTADO", "nivel": "advertencia",
                "mensaje": "El OCR no encontró texto legible en esta imagen externa.",
            }] if not ocr.get("texto_completo", "").strip() else []),
            "segundos": round(time.perf_counter() - inicio, 2),
        }
        resultados.append(fila)
        if al_resultado:
            al_resultado(indice, len(CASOS), fila)

    codigos = [fila for fila in resultados if fila["tipo"] == "codigo"]
    textos = [fila for fila in resultados if fila["tipo"] == "texto"]
    exactos = sum(fila["coincidencia_exacta"] for fila in codigos)
    exactos_brutos = sum(fila["coincidencia_exacta_bruta"] for fila in codigos)
    fragmentos = sum(len(fila["esperados"]) for fila in textos)
    fragmentos_ok = sum(len(fila["encontrados"]) for fila in textos)
    documento = {
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "fuentes": list(FUENTES.values()),
        "casos": len(resultados),
        "exactos": exactos,
        "exactos_ocr_brutos": exactos_brutos,
        "casos_codigo": len(codigos),
        "exactitud": round(exactos / len(codigos), 4) if codigos else None,
        "exactitud_ocr_bruta": round(exactos_brutos / len(codigos), 4) if codigos else None,
        "exactitud_efectiva": round(exactos / len(codigos), 4) if codigos else None,
        "similitud_media_caracteres": round(
            sum(fila["similitud_caracteres"] for fila in codigos) / len(codigos), 4)
            if codigos else None,
        "similitud_media_ocr_bruta": round(
            sum(fila["similitud_caracteres_bruta"] for fila in codigos) / len(codigos), 4)
            if codigos else None,
        "fragmentos_texto": fragmentos,
        "fragmentos_texto_detectados": fragmentos_ok,
        "cobertura_texto": round(fragmentos_ok / fragmentos, 4) if fragmentos else None,
        "resultados": resultados,
    }
    salida.parent.mkdir(parents=True, exist_ok=True)
    escribir_json_seguro(salida, documento, lanzar=True)
    return documento


def cargar(config: dict | None = None) -> dict:
    directorio, salida = rutas(config)
    disponibles = [nombre for nombre in CASOS if (directorio / nombre).is_file()]
    if not salida.is_file():
        return {
            "generado_en": None, "fuentes": list(FUENTES.values()), "casos": len(disponibles),
            "exactos": 0, "exactitud": None, "similitud_media_caracteres": None,
            "cobertura_texto": None, "fragmentos_texto": 0,
            "fragmentos_texto_detectados": 0,
            "resultados": [], "imagenes_disponibles": disponibles,
        }
    documento = json.loads(salida.read_text(encoding="utf-8"))
    documento["imagenes_disponibles"] = disponibles
    return documento


if __name__ == "__main__":
    print(json.dumps(evaluar(), ensure_ascii=False, indent=2))
