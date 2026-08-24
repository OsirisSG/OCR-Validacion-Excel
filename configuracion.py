"""
configuracion.py — Carga centralizada de parámetros y motor de reglas del semáforo.

Propósito
---------
Único punto de lectura de `config.yaml` y `reglas_cumplimiento.yaml` para todas
las fases y para el backend del dashboard. Así ningún módulo duplica valores por
defecto y el semáforo se evalúa exactamente igual en Excel y en el dashboard.

Decisiones de diseño
--------------------
- Los archivos YAML se buscan relativos a la raíz del proyecto (carpeta que
  contiene este archivo), no al directorio de trabajo: permite ejecutar el
  pipeline desde cualquier ubicación.
- El evaluador de reglas (`evaluar_criterio`) interpreta la sintaxis declarada
  en `reglas_cumplimiento.yaml` (rangos numéricos y listas categóricas); los
  umbrales nunca están fijos en el código.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

RAIZ_PROYECTO = Path(__file__).resolve().parent
RUTA_CONFIG = RAIZ_PROYECTO / "config.yaml"
RUTA_REGLAS = RAIZ_PROYECTO / "reglas_cumplimiento.yaml"

# Valor por defecto si algún archivo no existe: el pipeline debe poder
# ejecutarse con valores sensatos y avisar, no morir por un YAML faltante.
_CONFIG_DEFECTO: dict = {
    "fase0": {"min_carpetas_para_patron": 2},
    "fase1": {"motor": "paddle", "motor_fallback": "easyocr", "lang": "en",
              "umbral_confianza": 0.5, "umbral_espacio_px": 40},
    "colores": {"verde": "#22c55e", "amarillo": "#f59e0b", "rojo": "#ef4444"},
}

_RE_OPERADOR = re.compile(r"^(>=|<=|>|<|=)\s*(-?\d+(?:[.,]\d+)?)$")
_RE_RANGO = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s*-\s*(-?\d+(?:[.,]\d+)?)$")


def cargar_config(ruta: str | Path | None = None) -> dict:
    """Carga config.yaml y lo fusiona con valores por defecto mínimos."""
    ruta = Path(ruta) if ruta else RUTA_CONFIG
    if not ruta.exists():
        import warnings
        warnings.warn(f"config.yaml no encontrado en {ruta}; se usan valores por defecto mínimos.")
        return _CONFIG_DEFECTO
    with open(ruta, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def cargar_reglas(ruta: str | Path | None = None) -> dict:
    """Carga reglas_cumplimiento.yaml (criterios del semáforo)."""
    ruta = Path(ruta) if ruta else RUTA_REGLAS
    with open(ruta, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Motor de reglas: interpreta los valores declarados en reglas_cumplimiento.yaml
# ---------------------------------------------------------------------------

def _parsear_regla(valor: str):
    """
    Convierte el texto de una regla en un predicado.

    Sintaxis soportada:
      - Numérico con operador: ">= 90", "< 70", "= 100"
      - Rango numérico inclusivo: "70-89"
      - Categórico: "coincidencia_total" o "discrepancia,sin_referencia"

    Retorna una función (valor_evaluar -> bool) o None si la regla no aplica.
    """
    valor = str(valor).strip()
    m = _RE_OPERADOR.match(valor)
    if m:
        op, num = m.group(1), float(m.group(2).replace(",", "."))
        return {
            ">=": lambda v: _a_num(v) is not None and _a_num(v) >= num,
            "<=": lambda v: _a_num(v) is not None and _a_num(v) <= num,
            ">": lambda v: _a_num(v) is not None and _a_num(v) > num,
            "<": lambda v: _a_num(v) is not None and _a_num(v) < num,
            "=": lambda v: _a_num(v) is not None and _a_num(v) == num,
        }[op]
    m = _RE_RANGO.match(valor)
    if m:
        lo, hi = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
        return lambda v: _a_num(v) is not None and lo <= _a_num(v) <= hi
    # Categórico: conjunto de valores exactos separados por coma.
    categorias = {c.strip() for c in valor.split(",") if c.strip()}
    if categorias:
        return lambda v: str(v).strip() in categorias
    return None


def _a_num(v):
    """Convierte v a float si es posible (acepta '85,3' y '85.3'); si no, None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def estructura_regla(valor: str) -> dict:
    """
    Parsea el texto de una regla a estructura (sin predicado), para que
    generar_excel construya formato condicional de openpyxl desde el YAML:
      {"tipo": "operador", "op": ">=", "valor": 90}
      {"tipo": "rango", "min": 70, "max": 89}
      {"tipo": "categorico", "valores": {"coincidencia_total"}}
    """
    valor = str(valor).strip()
    m = _RE_OPERADOR.match(valor)
    if m:
        return {"tipo": "operador", "op": m.group(1), "valor": float(m.group(2).replace(",", "."))}
    m = _RE_RANGO.match(valor)
    if m:
        return {"tipo": "rango", "min": float(m.group(1).replace(",", ".")),
                "max": float(m.group(2).replace(",", "."))}
    return {"tipo": "categorico",
            "valores": {c.strip() for c in valor.split(",") if c.strip()}}


def evaluar_criterio(criterio: dict, valor) -> str | None:
    """
    Evalúa un criterio del semáforo contra un valor.

    `criterio` es el dict del YAML, p.ej. {"verde": ">= 90", "amarillo": "70-89", "rojo": "< 70"}.
    Retorna "verde" | "amarillo" | "rojo" según la primera regla que cumpla,
    o None si ninguna aplica (queda "sin clasificar" y se reporta).
    """
    for color in ("verde", "amarillo", "rojo"):
        regla = criterio.get(color)
        if regla is None:
            continue
        predicado = _parsear_regla(regla)
        if predicado is None:
            raise ValueError(f"Regla ilegible en criterio, color={color}: {regla!r}")
        try:
            if predicado(valor):
                return color
        except TypeError:
            continue
    return None


def clasificar(confianza_ocr_pct, coincidencia_texto: str, reglas: dict | None = None) -> dict:
    """
    Clasificación completa de una fila: aplica todos los criterios del YAML
    dinámicamente y agrega el semáforo global (peor color entre criterios).
    Usada por generar_excel.py y por el backend del dashboard.
    """
    reglas = reglas if reglas is not None else cargar_reglas()
    criterios = reglas.get("criterios", {})
    out = {}
    for nombre, criterio in criterios.items():
        valor = confianza_ocr_pct if nombre == "confianza_ocr" else (
            coincidencia_texto if nombre == "coincidencia_texto" else None)
        out[nombre] = evaluar_criterio(criterio, valor) if valor is not None else None
    # Semáforo global: el color más restrictivo entre los criterios evaluados.
    orden = {"rojo": 0, "amarillo": 1, "verde": 2, None: 3}
    evaluados = [c for c in out.values() if c is not None]
    out["semaforo_global"] = min(evaluados, key=lambda c: orden[c]) if evaluados else None
    return out
