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
            candidatos = [normalizar(t.get("texto_original") or t.get("texto", ""))
                          for t in tokens_completos] or [""]
            mejor = min(candidatos, key=lambda texto: distancia_edicion(esperado, texto))
            distancia = distancia_edicion(esperado, mejor)
            similitud = 1.0 - distancia / max(len(esperado), len(mejor), 1)
            esperados = [esperado]
            encontrados = [esperado] if mejor == esperado else []
        else:
            esperados = caso["esperados"]
            texto_normalizado = normalizar(ocr.get("texto_completo", ""))
            encontrados = [fragmento for fragmento in esperados
                           if normalizar(fragmento) in texto_normalizado]
            similitud = len(encontrados) / max(len(esperados), 1)
            mejor = ocr.get("texto_completo", "")
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
            "coincidencia_exacta": len(encontrados) == len(esperados),
            "similitud_caracteres": round(similitud, 4),
            "cobertura": round(len(encontrados) / max(len(esperados), 1), 4),
            "tokens": tokens_completos,
            "lineas_texto": ocr.get("lineas_texto", []),
            "texto_completo": ocr.get("texto_completo", ""),
            "orientacion_grados": ocr.get("orientacion_corregida_grados"),
            "variante": ocr.get("variante_preprocesamiento"),
            "intentos": len(ocr.get("intentos_ocr", [])),
            "motor": ocr.get("motor"),
            "segundos": round(time.perf_counter() - inicio, 2),
        }
        resultados.append(fila)
        if al_resultado:
            al_resultado(indice, len(CASOS), fila)

    codigos = [fila for fila in resultados if fila["tipo"] == "codigo"]
    textos = [fila for fila in resultados if fila["tipo"] == "texto"]
    exactos = sum(fila["coincidencia_exacta"] for fila in codigos)
    fragmentos = sum(len(fila["esperados"]) for fila in textos)
    fragmentos_ok = sum(len(fila["encontrados"]) for fila in textos)
    documento = {
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "fuentes": list(FUENTES.values()),
        "casos": len(resultados),
        "exactos": exactos,
        "casos_codigo": len(codigos),
        "exactitud": round(exactos / len(codigos), 4) if codigos else None,
        "similitud_media_caracteres": round(
            sum(fila["similitud_caracteres"] for fila in codigos) / len(codigos), 4)
            if codigos else None,
        "fragmentos_texto": fragmentos,
        "fragmentos_texto_detectados": fragmentos_ok,
        "cobertura_texto": round(fragmentos_ok / fragmentos, 4) if fragmentos else None,
        "resultados": resultados,
    }
    salida.parent.mkdir(parents=True, exist_ok=True)
    temporal = salida.with_suffix(salida.suffix + ".tmp")
    temporal.write_text(json.dumps(documento, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(salida)
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
