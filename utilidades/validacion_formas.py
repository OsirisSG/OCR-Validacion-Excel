"""Validación de FORMA de los valores antes de publicarlos (P08).

Por qué existe
--------------
La ejecución local de V16.0.21 publicó `GJ.880.204.J` (sin el `2` inicial) y `02S` en tres
casos donde el libro dice `01S`. Ninguno de los dos es un valor imposible «en general»: son
lecturas malformadas del OCR. La regla de este módulo es simple y ruda:

    un valor que no tiene la forma del libro NO se publica; se manda a la cola de dudas.

Con esto no se acierta más: se deja de publicar lo que no se puede sostener. La cobertura baja
y la precisión sube, que es el orden correcto cuando el dato va a una matriz de validación.

Qué NO hace
-----------
- No decide entre dos valores válidos que se contradicen: eso es `flujo_empresarial`.
- No valida fechas ni tiempos: tienen sus propias comprobaciones.
- No usa un catálogo cerrado de niveles: el usuario confirmó que en prototipos puede haber
  más (`##K` o `##S`), así que la forma es `dos dígitos + K/S`.
"""
from __future__ import annotations

import re
from typing import Iterable

# --------------------------------------------------------------------------- formas
# Cada patrón está copiado del libro real (Book-10-Examples, 10 casos) y admite las
# variantes que ese libro usa de verdad. Si un valor no encaja, no es publicable.
PATRONES: dict[str, tuple[str, str]] = {
    "test_number": (r"\d{6}", "número de prueba de 6 dígitos (232561)"),
    # El OCR entrega el número de parte con puntos o con espacios («2GJ 880 204 J»);
    # lo que NO puede faltar es el dígito inicial, que es justo lo que perdía el OCR.
    "module_part_number": (r"\d[A-Z]{2}[. ]?\d{3}[. ]?\d{3}[. ]?[A-Z]",
                           "número de parte tipo 2GJ.880.204.J"),
    "dashboard_part_number": (r"\d[A-Z]{2}[. ]?\d{3}[. ]?\d{3}[. ]?[A-Z]",
                              "número de parte tipo 2GJ.857.003.G"),
    "module_serial_number": (r"\d{3}\s?[A-Z0-9]{8,12}", "serie tipo 671 ZRZ0539983E"),
    "dashboard_serial_number": (r"\d{3}\s?[A-Z0-9]{8,12}", "serie tipo 052 3KVJ008R6E"),
    "engineering_level": (r"\d{2}[KS]", "nivel tipo 01S o 66K"),
    "dashboard_engineering_level": (r"\d{2}[KS]", "nivel tipo 03S o 66K"),
    "temperature_condition": (r"NT|RT|HT", "temperatura NT, RT o HT"),
    "inflator_type": (r"NOM|OGL|UGL", "generador NOM, OGL o UGL"),
    "module_version": (r"RDW|NAR", "versión RDW o NAR"),
    "week": (r"\d{1,2}", "semana de 1 a 53"),
}

# Campos que exigen que MÁS DE UNA fuente independiente diga lo mismo para publicarse.
# Medido: `02S` salió de dos lecturas de la misma imagen y el libro decía `01S`.
CORROBORACION_MINIMA: dict[str, int] = {
    "engineering_level": 2,
    "dashboard_engineering_level": 2,
}

_CAMPOS_SIN_TILDES = str.maketrans("", "")


def normalizar(valor) -> str:
    """Texto comparable: sin espacios de más y en mayúsculas. No cambia el valor."""
    if valor is None:
        return ""
    return " ".join(str(valor).split()).upper().translate(_CAMPOS_SIN_TILDES)


def revisar_forma(clave: str, valor) -> dict:
    """¿Tiene este valor la forma que el libro usa para ese campo?

    Devuelve `{"valido": bool, "motivo": str|None, "valor": str}`. Los campos sin
    patrón declarado (proveedores, apertura láser, textos) se dan por válidos: no se
    inventa una regla que el libro no tiene.
    """
    texto = normalizar(valor)
    if not texto:
        return {"valido": False, "motivo": "sin valor", "valor": ""}
    patron = PATRONES.get(clave)
    if patron is None:
        return {"valido": True, "motivo": None, "valor": texto}
    expresion, descripcion = patron
    if re.fullmatch(expresion, texto):
        return {"valido": True, "motivo": None, "valor": texto}
    return {"valido": False,
            "motivo": f"«{texto}» no tiene la forma esperada: {descripcion}",
            "valor": texto}


def filtrar_candidatos(clave: str, valores: Iterable) -> tuple[list[str], list[dict]]:
    """Separa los valores con forma válida de los rechazados (con motivo)."""
    validos: list[str] = []
    rechazados: list[dict] = []
    for valor in valores:
        revision = revisar_forma(clave, valor)
        if revision["valido"]:
            if revision["valor"] not in validos:
                validos.append(revision["valor"])
        else:
            rechazados.append({"valor": revision["valor"], "motivo": revision["motivo"]})
    return validos, rechazados


def corroborado(clave: str, fuentes: Iterable) -> bool:
    """¿Hay suficientes fuentes independientes para publicar este campo?"""
    minimo = CORROBORACION_MINIMA.get(clave)
    if minimo is None:
        return True
    return len({str(f) for f in fuentes if f}) >= minimo


def motivo_para_duda(clave: str, valor, rechazados: list[dict], fuentes: Iterable) -> str | None:
    """Motivo legible cuando un campo no se publica, o None si todo está bien."""
    revision = revisar_forma(clave, valor)
    if valor not in (None, "") and not revision["valido"]:
        return revision["motivo"]
    if valor not in (None, "") and not corroborado(clave, fuentes):
        return (f"una sola fuente sostiene «{valor}» y este campo necesita "
                f"{CORROBORACION_MINIMA.get(clave, 1)} lecturas independientes")
    if valor in (None, "") and rechazados:
        return ("ninguna lectura válida: " + "; ".join(r["motivo"] for r in rechazados[:3]))
    return None
