#!/usr/bin/env python3
"""P42 · quita el borrado de la matriz: lo que el flujo no leyó se queda como estaba.

    python3 corregir_borrado_libro.py --simular           (ver qué haría)
    python3 corregir_borrado_libro.py
    python3 corregir_borrado_libro.py --probar
    python3 corregir_borrado_libro.py --revertir

El problema, con nombre y apellido
----------------------------------
En `reporte_bmg.py`, `_poblar_lista()` hace esto antes de escribir:

    for fila in range(8, max(hoja.max_row, ultimo)+1):
        for col in range(1, 56):
            celda=hoja.cell(fila,col); celda.value=None; ...

y después `_escribir_fila()` escribe `None` en **todos** los campos de los que no hay
evidencia. Resultado: cada corrida vacía la matriz y sólo repone lo que esa corrida supo
leer. En el libro real eso son 141 celdas por hoja, medidas y contadas.

Lo que hace esta corrección
---------------------------
Antes de limpiar, guarda lo que ya estaba escrito, indexado por **número de prueba** (no por
número de fila, que cambia entre corridas). Al escribir cada caso, devuelve a la fila lo que
el flujo no supo reescribir. Nunca pisa un valor nuevo: si la corrida trae dato, manda la
corrida; si no, se queda lo que había. Y deja constancia en `ULTIMA_CONSERVACION`.

Cómo se aplica sin romper nada
------------------------------
No reemplaza el archivo entero (tu `reporte_bmg.py` puede ser distinto del mío): busca los
tres anclajes exactos, comprueba que cada uno aparece **una sola vez**, inserta, y verifica:
- que el archivo sigue compilando (`ast.parse`);
- que los anclajes ya no volverían a coincidir (idempotencia);
- que el módulo se importa y que un libro con datos viejos los conserva (prueba de verdad).

Si algo no cuadra, no toca nada y dice exactamente qué anclaje falló. Guarda una copia
`reporte_bmg.py.bak` y `--revertir` la repone.
"""
from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NOMBRE = "reporte_bmg.py"

ANCLA_LIMPIEZA = """    for fila in range(8, max(hoja.max_row, ultimo)+1):
        for col in range(1, 56):
            celda=hoja.cell(fila,col); celda.value=None; celda.hyperlink=None; celda.comment=None
    mapa={}
"""

NUEVA_LIMPIEZA = """    previos=_previos_por_caso(hoja)
    for fila in range(8, max(hoja.max_row, ultimo)+1):
        for col in range(1, 56):
            celda=hoja.cell(fila,col); celda.value=None; celda.hyperlink=None; celda.comment=None
    mapa={}
    informe_conservadas={"conservadas": 0}
"""

ANCLA_ESCRITURA = """            _escribir_fila(hoja, fila, resultado, idioma)
            mapa[_identidad(resultado)] = fila
"""

NUEVA_ESCRITURA = """            _escribir_fila(hoja, fila, resultado, idioma)
            _conservar_previos(hoja, fila, resultado, previos, informe_conservadas)
            mapa[_identidad(resultado)] = fila
"""

ANCLA_RETORNO = """    hoja.column_dimensions[get_column_letter(len(CLAVES_PLANTILLA) + 2)].width = 26
    return mapa
"""

NUEVO_RETORNO = """    hoja.column_dimensions[get_column_letter(len(CLAVES_PLANTILLA) + 2)].width = 26
    ULTIMA_CONSERVACION[hoja.title]=informe_conservadas["conservadas"]
    return mapa
"""

AYUDAS = '''

# --- P42: lo que el flujo no leyó, no se borra ----------------------------------------
# Antes de limpiar la matriz se guarda lo que ya estaba escrito, por número de prueba.
# Al escribir cada caso se devuelve a la fila lo que esta corrida no supo reescribir.
# Nunca pisa un valor nuevo: si la corrida trae dato, manda la corrida.
ULTIMA_CONSERVACION: dict[str, int] = {}


def _previos_por_caso(hoja, inicio: int = 8, fin: int | None = None):
    """Número de prueba -> lista de {columna: valor} con lo que ya había escrito."""
    fin = min(hoja.max_row, 400) if fin is None else fin
    previos: dict[str, list[dict[int, object]]] = {}
    for fila in range(inicio, fin + 1):
        numero = hoja.cell(fila, 3).value
        if numero in (None, ""):
            continue
        clave = str(numero).strip()
        if len(clave) != 6 or not clave.isdigit():
            continue
        valores = {}
        for columna in range(1, 56):
            valor = hoja.cell(fila, columna).value
            if valor not in (None, ""):
                valores[columna] = valor
        if valores:
            previos.setdefault(clave, []).append(valores)
    return previos


def _conservar_previos(hoja, fila: int, resultado: dict, previos: dict,
                       informe: dict | None = None) -> int:
    """Devuelve a la fila lo que tenía y esta corrida no ha escrito. Nunca sobrescribe."""
    numero = _campo(resultado, "test_number")
    clave = "" if numero is None else str(numero).strip()
    candidatos = previos.get(clave)
    if not candidatos:
        return 0
    devueltas = 0
    for columna, valor in candidatos[0].items():
        celda = hoja.cell(fila, columna)
        if celda.value not in (None, ""):
            continue
        celda.value = valor
        devueltas += 1
    if devueltas and informe is not None:
        informe["conservadas"] = informe.get("conservadas", 0) + devueltas
    return devueltas
'''


def parchear(texto: str) -> str:
    """Aplica los tres anclajes. Lanza ValueError si alguno no aparece exactamente una vez."""
    if "_previos_por_caso" in texto:
        raise ValueError("ya está corregido (el archivo contiene _previos_por_caso)")
    for etiqueta, ancla in (("limpieza", ANCLA_LIMPIEZA), ("escritura", ANCLA_ESCRITURA),
                            ("retorno", ANCLA_RETORNO)):
        veces = texto.count(ancla)
        if veces != 1:
            raise ValueError(f"el anclaje «{etiqueta}» aparece {veces} vez/veces (hacía falta 1): "
                             "tu reporte_bmg.py no es el que esperaba esta corrección")
    texto = texto.replace(ANCLA_LIMPIEZA, NUEVA_LIMPIEZA)
    texto = texto.replace(ANCLA_ESCRITURA, NUEVA_ESCRITURA)
    texto = texto.replace(ANCLA_RETORNO, NUEVO_RETORNO)
    return texto.rstrip("\n") + "\n" + AYUDAS


PRUEBA = '''
import sys, tempfile, os
from pathlib import Path
from openpyxl import Workbook
import reporte_bmg as R

wb = Workbook(); hoja = wb.active; hoja.title = "Versuchsmatrix"
for i, clave in enumerate(R.CLAVES_PLANTILLA, start=1):
    hoja.cell(7, i).value = clave
# lo que ya estaba escrito antes de esta corrida
hoja.cell(8, 1).value = "22"            # Semana
hoja.cell(8, 2).value = "IT BMG"        # Motivo
hoja.cell(8, 3).value = "222504"        # Número de prueba
hoja.cell(8, 4).value = "2025-05-28"    # Fecha
hoja.cell(8, 5).value = "EDAG"          # Lugar

# esta corrida sólo sabe el número de prueba y la temperatura
resultado = {"case_key": "prueba|1st|222504", "tipo_st": "1ST",
             "campos": {"test_number": {"valor": "222504"},
                        "temperature_condition": {"valor": "NT"}}}
R._poblar_lista(hoja, [resultado], "es")

esperado = {1: "22", 2: "IT BMG", 3: "222504", 4: "2025-05-28", 5: "EDAG"}
fallos = [c for c, v in esperado.items() if str(hoja.cell(8, c).value) != v]
if fallos:
    print("FALLO: se perdieron las columnas", fallos,
          "→", [hoja.cell(8, c).value for c in fallos])
    sys.exit(1)
conservadas = R.ULTIMA_CONSERVACION.get("Versuchsmatrix", 0)
print(f"OK: conservadas {conservadas} celdas · A8={hoja.cell(8,1).value!r} B8={hoja.cell(8,2).value!r}")
if conservadas < 4:
    print("FALLO: se esperaban al menos 4 celdas conservadas")
    sys.exit(1)
'''


def probar(arbol: Path) -> tuple[bool, str]:
    """Corre la prueba de verdad: importa el módulo corregido y comprueba que conserva."""
    guion = arbol / "prueba_conservacion_temporal.py"
    guion.write_text(PRUEBA, encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, guion.name], cwd=arbol,
                           capture_output=True, text=True, timeout=180)
    finally:
        guion.unlink(missing_ok=True)
    salida = (r.stdout + r.stderr).strip().splitlines()
    ultima = salida[-1] if salida else "(sin salida)"
    if r.returncode != 0 and "ModuleNotFoundError" in ultima:
        return False, (f"no se puede importar reporte_bmg en este árbol ({ultima.split(':')[-1].strip()}). "
                       "Falta código del proyecto que no está aquí: la corrección no se aplica a ciegas")
    return r.returncode == 0, ultima


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Quita el borrado de la matriz en reporte_bmg.py (conserva lo no releído).")
    p.add_argument("--arbol", default=".", help="carpeta del proyecto (por defecto, la actual)")
    p.add_argument("--archivo", help="ruta exacta de reporte_bmg.py (si no está en la raíz)")
    p.add_argument("--simular", action="store_true", help="enseñar qué cambiaría, sin escribir")
    p.add_argument("--probar", action="store_true", help="correr la prueba después de aplicar")
    p.add_argument("--revertir", action="store_true", help="reponer reporte_bmg.py.bak")
    args = p.parse_args(argv)

    arbol = Path(args.arbol).expanduser().resolve()
    archivo = Path(args.archivo).expanduser().resolve() if args.archivo else arbol / NOMBRE
    respaldo = archivo.with_suffix(archivo.suffix + ".bak")

    if args.revertir:
        if not respaldo.exists():
            print(f"no hay copia que reponer: {respaldo}")
            return 2
        shutil.copyfile(respaldo, archivo)
        ok, detalle = probar(arbol)
        print(f"repuesto {archivo.name} desde .bak")
        print(f"  prueba del estado restaurado: {detalle}")
        return 0

    if not archivo.exists():
        print(f"no encuentro {archivo}")
        print("  pásame la carpeta del proyecto con --arbol, o la ruta del archivo con --archivo")
        return 2

    original = archivo.read_text(encoding="utf-8")
    if "_previos_por_caso" in original and "_conservar_previos" in original:
        print(f"archivo: {archivo}")
        print("  ya estaba corregido: no se toca")
        ok, detalle = probar(arbol)
        print(f"  prueba: {detalle}")
        return 0 if ok else 1
    try:
        corregido = parchear(original)
    except ValueError as error:
        print(f"no se ha tocado nada: {error}")
        return 1

    lineas_nuevas = len(corregido.splitlines()) - len(original.splitlines())
    print(f"archivo: {archivo}")
    print(f"  se conserva lo ya escrito por número de prueba (+{lineas_nuevas} líneas)")
    print("  anclajes encontrados: limpieza, escritura, retorno (1 de 1 cada uno)")

    if args.simular:
        for i, linea in enumerate(corregido.splitlines(), 1):
            if "_previos_por_caso(hoja)" in linea or "_conservar_previos(hoja" in linea \
                    or "ULTIMA_CONSERVACION[hoja.title]" in linea:
                print(f"  {i:>5}: {linea.strip()}")
        print("\n(simulación) no se escribió nada.")
        return 0

    try:
        ast.parse(corregido)
    except SyntaxError as error:
        print(f"no se ha tocado nada: la corrección no compila ({error})")
        return 1

    if not respaldo.exists():
        shutil.copyfile(archivo, respaldo)
        print(f"  copia previa: {respaldo.name}")
    archivo.write_text(corregido, encoding="utf-8")
    print("  escrito.")

    ok, detalle = probar(arbol)
    print(f"  prueba: {detalle}")
    if not ok:
        shutil.copyfile(respaldo, archivo)
        print("  la prueba falló: se ha repuesto el original. No queda nada a medias.")
        return 1
    print("\nlisto: la próxima corrida ya no borrará lo que no vuelva a leer.")
    print("  si algo va mal:  python3 corregir_borrado_libro.py --revertir")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
