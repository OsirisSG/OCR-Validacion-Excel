#!/usr/bin/env python3
"""P42 · comprobacion del entorno en 5 segundos, sin fotos y sin red.

Dice si la maquina puede correr P42 y si el DataMatrix del tablero se lee:

    python3 comprobar_entorno_p42.py
    python3 comprobar_entorno_p42.py --foto "/ruta/232561 RDW OGL HT/NACH/IMG_4221.JPG"

Salida: una linea por comprobacion y un veredicto. Codigo de salida 0 si todo
lo imprescindible esta, 1 si falta algo.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

RUTA_AQUI = Path(__file__).resolve().parent

FALTA = []
ESPERADO_OCR = "17/05/2025"


def _linea(nombre: str, ok: bool, detalle: str = "") -> bool:
    print(f"  [{'OK ' if ok else 'NO '}] {nombre:34s} {detalle}")
    return ok


def versiones() -> None:
    print("1) Versiones instaladas")
    print(f"  python                             {sys.version.split()[0]}")
    for modulo, etiqueta in (("cv2", "opencv"), ("numpy", "numpy"),
                             ("onnxruntime", "onnxruntime"),
                             ("rapidocr_onnxruntime", "OCR (rapidocr)"),
                             ("zxingcpp", "DataMatrix (zxing-cpp)")):
        try:
            paquete = __import__(modulo)
            version = getattr(paquete, "__version__", "")
            _linea(etiqueta, True, version)
        except ImportError:
            _linea(etiqueta, False, "FALTA: pip install " + modulo)
            FALTA.append(modulo)


def datamatrix() -> None:
    print("2) El DataMatrix del tablero")
    try:
        import cv2
        import numpy as np
        import zxingcpp
    except ImportError as error:
        _linea("importar zxing-cpp + cv2", False, str(error))
        FALTA.append("zxingcpp")
        return
    payload = "052# 2GJ 857 003 G#       #812506467#19052500*052 3KVJ008R6E1*="
    codigo = np.asarray(zxingcpp.create_barcode(payload,
                                                zxingcpp.BarcodeFormat.DataMatrix).to_image())
    codigo = np.where(codigo > 127, 255, 0).astype(np.uint8)
    lado = 420
    lienzo = np.full((lado, lado), 255, dtype=np.uint8)
    alto, ancho = codigo.shape[:2]
    y0, x0 = max(0, (lado - alto) // 2), max(0, (lado - ancho) // 2)
    lienzo[y0:y0 + alto, x0:x0 + ancho] = codigo[: lado - y0, : lado - x0]
    imagen = cv2.cvtColor(cv2.resize(lienzo, None, fx=2, fy=2,
                                     interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
    inicio = time.time()
    lecturas = zxingcpp.read_barcodes(imagen)   # los valores por defecto ya giran y reducen
    ms = (time.time() - inicio) * 1000
    textos = [r.text for r in lecturas]
    ok = any("3KVJ008R6E1" in t for t in textos)
    _linea("decodifica una etiqueta de prueba", ok, f"{ms:.0f} ms")
    if not ok:
        FALTA.append("zxingcpp-decodifica")

    # y el lector de verdad, con la tabla de colisiones incluida
    sys.path.insert(0, str(RUTA_AQUI))
    try:
        from utilidades import tablero_campos as T
        dato = T.leer_serie_de_datamatrix(imagen)
        esperado = "052 3KVJ008R6E1"          # el valor del payload, sin transformar
        _linea("leer_serie_de_datamatrix()", dato.get("valor") == esperado,
               f"{dato.get('valor')} (esperado {esperado})")
        if dato.get("valor") != esperado:
            FALTA.append("serie")
        parte = dato.get("parte")
        _linea("numero de parte del payload", parte == "2GJ.857.003.G", str(parte))
        if parte != "2GJ.857.003.G":
            FALTA.append("parte")
    except Exception as error:                        # noqa: BLE001
        _linea("importar utilidades.tablero_campos", False, f"{type(error).__name__}: {error}")
        FALTA.append("tablero_campos")


def ocr() -> None:
    print("3) El OCR")
    try:
        import cv2
        import numpy as np
    except ImportError:
        return
    try:
        from utilidades import codigos_modulo as CM
        motor = CM.motor_compartido()
    except Exception as error:                        # noqa: BLE001
        _linea("motor OCR", False, f"{type(error).__name__}: {error}")
        FALTA.append("ocr")
        return
    lienzo = np.full((90, 760, 3), 255, dtype=np.uint8)
    cv2.putText(lienzo, "17/05/2025", (12, 66), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 4)
    inicio = time.time()
    try:
        resultado = motor.leer(lienzo) if hasattr(motor, "leer") else motor(lienzo)
    except Exception as error:                        # noqa: BLE001
        resultado = f"{type(error).__name__}: {error}"
    ms = (time.time() - inicio) * 1000
    # el motor devuelve (cajas, texto, confianzas) con formas distintas según la versión: sólo
    # cuentan los textos. Antes se miraba cualquier dígito en str(resultado) y los tiempos
    # (0.12, 0.03…) daban un falso OK.
    textos: list[str] = []
    def _recoger(nodo) -> None:
        if isinstance(nodo, str):
            textos.append(nodo)
        elif isinstance(nodo, (list, tuple)):
            for hijo in nodo:
                _recoger(hijo)
    _recoger(resultado)
    crudo = " ".join(textos)
    ok = ESPERADO_OCR.replace("/", "") in crudo.replace("/", "").replace(" ", "")
    _linea("lee una fecha de prueba", ok, f"{ms:.0f} ms · {crudo[:60] or '(sin texto)'}")
    if not ok:
        FALTA.append("ocr-lectura")


def foto(ruta: str) -> None:
    print(f"4) DataMatrix en una foto real: {ruta}")
    try:
        import cv2
        sys.path.insert(0, str(RUTA_AQUI))
        from utilidades import tablero_campos as T
    except ImportError as error:
        _linea("importar", False, str(error))
        return
    imagen = cv2.imread(ruta)
    if imagen is None:
        _linea("abrir la foto", False, "no se pudo leer (ruta o permisos)")
        FALTA.append("foto-ilegible")
        return
    alto, ancho = imagen.shape[:2]
    if max(alto, ancho) > 2000:
        factor = 2000 / max(alto, ancho)
        imagen = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    inicio = time.time()
    dato = T.leer_serie_de_datamatrix_resistente(imagen)   # la que usa el motor
    ms = (time.time() - inicio) * 1000
    _linea("serie en la foto (con variantes)", bool(dato.get("valor")),
           f"{dato.get('valor', '—')} · {ms:.0f} ms · clase {dato.get('clase_cola', '—')}")
    if not dato.get("valor"):
        FALTA.append("foto-sin-codigo")


def main() -> int:
    ap = argparse.ArgumentParser(description="Comprobacion del entorno de P42")
    ap.add_argument("--foto", default="", help="foto real para probar el DataMatrix")
    args = ap.parse_args()
    print("=" * 78)
    print("P42 · comprobacion del entorno")
    print("=" * 78)
    versiones()
    datamatrix()
    ocr()
    if args.foto:
        foto(args.foto)
    print("-" * 78)
    if FALTA:
        print("VEREDICTO: faltan cosas:", ", ".join(sorted(set(FALTA))))
        print("  - sin zxing-cpp: no se lee el DataMatrix del tablero (la serie cae al OCR)")
        print("  - sin rapidocr: no hay ninguna lectura de fecha ni nivel")
        print("  - foto-sin-codigo / foto-ilegible: la foto de prueba no sirvió, prueba otra")
        return 1
    print("VEREDICTO: el entorno puede correr P42 sin cambios.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
