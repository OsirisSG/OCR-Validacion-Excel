"""¿Esta imagen trae datos, o solo ruido?

Dos problemas distintos que hasta ahora se trataban igual:

1. **Texto que no usamos.** El OCR devuelve letras sueltas, números de esquina, sombras,
   reflejos. Medido sobre el corpus real del taller: del total de tokens OCR de la base
   (322 484), el **52,3 % son de un solo carácter** y el **74,7 % tienen tres o menos**.
   Eso no son datos: es la textura del tablero.
2. **Imágenes sin texto de nada.** El operador las marca a mano (`imagenes_sin_datos`) y
   el programa, aun así, les escribe observaciones. Medido: de las 93 imágenes marcadas
   sin datos, 10 tienen observaciones y su mediana es de **2 caracteres**.

Este módulo clasifica el texto de una imagen en cuatro clases y devuelve, cuando no hay
datos, **un motivo de un catálogo cerrado** — para que «sin datos» signifique algo.
"""
from __future__ import annotations

import re

# Catálogo cerrado de motivos: lo que se escribe en `imagenes_sin_datos.motivo`.
MOTIVOS = (
    "sin_texto_detectable",     # el OCR no encontró nada con forma de texto
    "solo_ruido_ocr",           # hay caracteres sueltos, pero nada legible
    "texto_legible_sin_campos", # se lee algo, pero no es ninguno de los campos del contrato
    "imagen_no_pertinente",     # la imagen no es del caso (fondo, herramienta, mano)
)

# Un token cuenta como «útil» si tiene al menos este largo y algún carácter alfanumérico.
LARGO_MINIMO_UTIL = 4
# Por debajo de estos umbrales, lo que hay no es texto: es ruido.
RATIO_UTIL_MINIMO = 0.20
UTILES_MINIMOS = 2


def _tokens(texto: str) -> list[str]:
    return [t for t in str(texto or "").split() if t]


def _es_util(token: str) -> bool:
    return len(token) >= LARGO_MINIMO_UTIL and any(c.isalnum() for c in token)


def metricas(texto: str) -> dict:
    """Lo que se puede medir del texto sin saber todavía si trae campos."""
    tokens = _tokens(texto)
    utiles = [t for t in tokens if _es_util(t)]
    largo = sum(len(t) for t in tokens)
    return {
        "tokens": len(tokens),
        "tokens_utiles": len(utiles),
        "ratio_util": round(len(utiles) / len(tokens), 4) if tokens else 0.0,
        "caracteres": largo,
        "caracteres_utiles": sum(len(t) for t in utiles),
        "largo_maximo": max((len(t) for t in tokens), default=0),
    }


def clasificar(texto: str, candidatos: list[dict] | None = None) -> dict:
    """Clasifica el texto de UNA imagen.

    `candidatos` son los que devolvió el extractor del flujo; si no se pasan, la clase
    se decide solo con la forma del texto. Cuando hay candidatos válidos, mandan ellos:
    una imagen con un dato bueno es «con datos» aunque el resto sea basura.
    """
    m = metricas(texto)
    validos = [c for c in (candidatos or []) if c.get("valido_catalogo") is not False
               and str(c.get("valor_normalizado") or "").strip()]

    if validos:
        return {"clase": "con_datos", "motivo": None, "campos": sorted({c["clave"] for c in validos}),
                **m}

    if m["tokens"] == 0 or m["largo_maximo"] <= 2:
        return {"clase": "sin_texto", "motivo": "sin_texto_detectable", "campos": [], **m}
    if m["tokens_utiles"] < UTILES_MINIMOS or m["ratio_util"] < RATIO_UTIL_MINIMO:
        return {"clase": "solo_ruido", "motivo": "solo_ruido_ocr", "campos": [], **m}
    return {"clase": "texto_no_pertinente", "motivo": "texto_legible_sin_campos",
            "campos": [], **m}


def motivo_para_imagen_sin_datos(texto: str) -> str:
    """Motivo listo para escribir en `imagenes_sin_datos.motivo` (catálogo cerrado)."""
    clasificacion = clasificar(texto)
    if clasificacion["clase"] == "con_datos":
        # si tiene datos, marcarla como «sin datos» es el error: se avisa, no se inventa motivo
        return "revisar: la imagen contiene campos"
    return clasificacion["motivo"]


def resumen(clasificaciones: list[dict]) -> dict:
    """Cuenta por clase y calcula el ruido que se estaría procesando de más."""
    total = len(clasificaciones)
    cuenta: dict[str, int] = {}
    for c in clasificaciones:
        cuenta[c["clase"]] = cuenta.get(c["clase"], 0) + 1
    return {
        "imagenes": total,
        "por_clase": cuenta,
        "con_datos": cuenta.get("con_datos", 0),
        "descartables": total - cuenta.get("con_datos", 0),
        "porcentaje_descartable": round(100 * (total - cuenta.get("con_datos", 0)) / total, 1)
        if total else 0.0,
    }
