"""P45 · Vocabulario de valores que el LIBRO HISTÓRICO ya usó, para OFRECER opciones en las dudas.

Respuesta del usuario (11/11/2026): motivo, lugar, proveedores y apertura láser «pueden variar; es
importante buscar los que aparecen». La plantilla institucional (`plantillas/reporte_bmg_1st_2st.xlsx`,
90 filas históricas) es el libro con esos textos. Aquí se cuentan los valores por columna y se
devuelven como OPCIONES del panel de dudas, con el número de veces que aparecen.

Reglas:
- nunca se publica un valor por estar en el vocabulario (no es lectura de la foto);
- columnas de texto de proyecto (B, E, G, N, O, S, T) y, desde P50, nivel K y delay L como OPCIONES
  del formulario (nunca se publican por estar aquí); nunca serie, fechas ni número;
- NO se debe configurar con el Book corregido de evaluación (`vocabulario_libros` en config.yaml).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

COLUMNAS = {2: "test_reason", 5: "test_place", 7: "module_part_number", 11: "engineering_level",
            12: "delay_ms", 14: "inflator_supplier", 15: "dashboard_part_number", 19: "laser_opening",
            20: "dashboard_supplier"}
# P50 · en el delay «--» ES un valor del libro (sin retardo); en las demás columnas es «vacío».
CONSERVAR_GUIONES = {"delay_ms"}
_CACHE: dict[tuple, dict] = {}


def vocabulario(rutas, hojas=("Versuchsmatrix",)) -> dict[str, dict[str, int]]:
    """{campo: {valor: veces}} de las filas con número de prueba de 6 dígitos. Sin E/S repetida."""
    salida: dict[str, Counter] = {campo: Counter() for campo in COLUMNAS.values()}
    for ruta in rutas or ():
        ruta = Path(str(ruta).strip().strip('"\''))
        if not ruta.is_file():
            continue
        clave = (str(ruta.resolve()), ruta.stat().st_mtime_ns)
        if clave not in _CACHE:
            from openpyxl import load_workbook
            libro = load_workbook(ruta, read_only=True, data_only=True)
            cuenta: dict[str, Counter] = {campo: Counter() for campo in COLUMNAS.values()}
            for nombre in hojas:
                if nombre not in libro.sheetnames:
                    continue
                for fila in libro[nombre].iter_rows(min_row=8, max_col=20, values_only=True):
                    numero = str(fila[2] or "").strip()
                    if not (len(numero) == 6 and numero.isdigit()):
                        continue
                    for columna, campo in COLUMNAS.items():
                        valor = fila[columna - 1]
                        texto = " ".join(str(valor).split()) if valor is not None else ""
                        if texto and (campo in CONSERVAR_GUIONES or texto not in {"-", "--", "|", "—"}):
                            cuenta[campo][texto] += 1
            libro.close()
            _CACHE[clave] = {k: dict(v) for k, v in cuenta.items()}
        for campo, valores in _CACHE[clave].items():
            salida[campo].update(valores)
    return {campo: dict(c.most_common(8)) for campo, c in salida.items() if c}


def rutas_configuradas(config: dict, raiz: Path) -> list[Path]:
    """`empresarial.vocabulario_libros`; si está vacío, la plantilla BMG configurada."""
    rutas = list(((config.get("empresarial") or {}).get("vocabulario_libros")) or [])
    if not rutas:
        plantilla = (((config.get("fase3") or {}).get("reporte_bmg")) or {}).get("plantilla")
        if plantilla:
            rutas = [plantilla]
    salida = []
    for ruta in rutas:
        ruta = Path(str(ruta).strip().strip('"\''))
        salida.append(ruta if ruta.is_absolute() else raiz / ruta)
    return salida
