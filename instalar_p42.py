#!/usr/bin/env python3
"""P42 · instala la lectura de la serie por DataMatrix sobre un arbol de trabajo.

    python3 instalar_p42.py /ruta/al/arbol          # copia los archivos y hace copia previa
    python3 instalar_p42.py /ruta/al/arbol --probar  # y además corre las pruebas

Qué toca (y nada más):

    utilidades/tablero_campos.py     reemplazado (lector del DataMatrix + pista + enganche)
    evidencia_tablero.py             reemplazado (una lectura del DataMatrix basta; cupo nuevo)
    barrer_datamatrix.py             nuevo (barrido suelto de todas las fotos)
    fundir_datamatrix.py             nuevo (fusiona el barrido con el parcial)
    rellenar_tablero_p42.py          nuevo (vuelca la evidencia en el libro)
    medir_tablero_p42.py             nuevo (marcador de 40 celdas)
    comprobar_entorno_p42.py         nuevo (autocomprobación sin fotos)
    pruebas/test_p42_datamatrix.py   nuevo (17 pruebas)

Los originales se guardan en `.backup_p42/` con la fecha, así que se puede volver atrás
copiándolos de nuevo.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
# origen en el paquete -> destino dentro del árbol
REEMPLAZA = {
    "tablero_campos.py": "utilidades/tablero_campos.py",
    "evidencia_tablero.py": "evidencia_tablero.py",
}
NUEVOS = ("barrer_datamatrix.py", "fundir_datamatrix.py", "rellenar_tablero_p42.py",
          "medir_tablero_p42.py", "comprobar_entorno_p42.py")
PRUEBAS = {"test_p42_datamatrix.py": "pruebas/test_p42_datamatrix.py"}


def _origen(nombre: str) -> Path:
    """El archivo puede venir plano (paquete) o en su carpeta (árbol). Pura."""
    for candidato in (AQUI / nombre, AQUI / "utilidades" / nombre, AQUI / "pruebas" / nombre):
        if candidato.exists():
            return candidato
    return AQUI / nombre


def main() -> int:
    ap = argparse.ArgumentParser(description="Instala P42 en un árbol de trabajo")
    ap.add_argument("arbol")
    ap.add_argument("--probar", action="store_true", help="corre las pruebas al terminar")
    args = ap.parse_args()
    arbol = Path(args.arbol).resolve()
    if not (arbol / "utilidades" / "tablero_campos.py").exists():
        print(f"ERROR: {arbol} no parece el árbol del proyecto (falta utilidades/tablero_campos.py)")
        return 1

    # primero se comprueba que vienen todos los archivos: no dejar media instalación
    faltan = [n for n in list(REEMPLAZA) + list(NUEVOS) + list(PRUEBAS)
              if not _origen(n).exists()]
    if faltan:
        print("ERROR: faltan archivos en el paquete:", ", ".join(faltan))
        return 1
    (arbol / "pruebas").mkdir(exist_ok=True)

    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    respaldo = arbol / ".backup_p42" / sello
    for origen in list(REEMPLAZA) + list(PRUEBAS) + list(NUEVOS):
        destino = arbol / (REEMPLAZA.get(origen) or PRUEBAS.get(origen) or origen)
        if destino.exists():
            respaldo_destino = respaldo / destino.relative_to(arbol)
            respaldo_destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(destino, respaldo_destino)
    print(f"copia previa en {respaldo}")

    for origen, destino in list(REEMPLAZA.items()) + list(PRUEBAS.items()):
        shutil.copyfile(_origen(origen), arbol / destino)
        print(f"  escrito {destino}")
    for nombre in NUEVOS:
        shutil.copyfile(_origen(nombre), arbol / nombre)
        print(f"  escrito {nombre}")

    for modulo, modulo_txt in (("zxingcpp", "zxing-cpp"),
                               ("rapidocr_onnxruntime", "rapidocr-onnxruntime")):
        try:
            __import__(modulo)
            print(f"  [OK ] {modulo_txt} instalado")
        except ImportError:
            paquete = {"zxingcpp": "zxing-cpp",
                       "rapidocr_onnxruntime": "rapidocr-onnxruntime"}.get(modulo, modulo)
            print(f"  [FALTA] {modulo_txt} → pip install {paquete}")

    if args.probar:
        print("\npruebas:")
        orden = [sys.executable, "-m", "pytest", "-q",
                 "pruebas/test_p42_datamatrix.py",
                 "pruebas/test_p40_anclas_fecha.py",
                 "pruebas/test_p39_parte2.py"]
        resultado = subprocess.run(orden, cwd=arbol)
        print(f"\nautocomprobación: {sys.executable} comprobar_entorno_p42.py --foto RUTA")
        return resultado.returncode
    print("\nlisto. Ahora: python3 comprobar_entorno_p42.py --foto RUTA_DE_UNA_FOTO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
