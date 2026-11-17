#!/usr/bin/env python3
"""P43 · SIMULACIÓN con evidencia SINTÉTICA de la ruta normal completa (sin fotos privadas).

    python simular_tablero_p43.py --libro "C:\\ruta\\versionV16_0_51.xlsx" --salida "C:\\ruta\\sim" \
        [--vaciar-tablero] [--referencia Book-10-Examples_CORREGIDO.xlsx]

Qué hace (todo en un directorio NUEVO dentro de --salida; el --libro no se modifica):
1. lee los números de prueba 1ST del libro (sólo la identidad, ningún valor);
2. crea un proyecto sintético con esas carpetas de caso y fotos sintéticas (JPG de 32×32);
3. corre `validacion.validar_lote_empresarial` (consolidación, dudas, trazabilidad) con un OCR
   genérico vacío y un LECTOR P42 SINTÉTICO que cubre los escenarios: consenso, fechas de
   módulo/proveedor frente al sticker, fechas contradictorias, error de OCR, foto sin ancla y
   foto omitida que encuentra la segunda pasada;
4. exporta con `reporte_bmg.generar_reporte_bmg` a un libro NUEVO usando el libro dado (o una
   copia con O:R vaciadas si `--vaciar-tablero`) como partida;
5. verifica la salida con `verificar_salida_p43` y, si se da `--referencia`, la EVALÚA.

Los valores sintéticos (fechas de 2031, series «999 SIM…») NO existen en la referencia: si
aparecieran coincidencias en O:R, algo estaría copiando la referencia. ESTO NO ES UNA
LECTURA REAL: no sirve como entregable ni demuestra lectura desde fotos.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

AQUI = Path(__file__).resolve().parent
if str(AQUI) not in sys.path:
    sys.path.insert(0, str(AQUI))

PISTA = {"algo": True, "etiqueta": True, "codigos": [{"area": 100, "x": 0, "y": 0, "w": 1, "h": 1}],
         "pestanas": [], "blanco": 0.2, "grabado": False, "datamatrix": False}
FOTOS = ("NACH/IMG_0001.JPG", "NACH/IMG_0002.JPG", "NACH/IMG_0003.JPG", "VOR/IMG_0001.JPG",
         "VOR/IMG_0002.JPG")


class LectorSintetico:
    """Mismo contrato que `tablero_integracion.LectorP42`, con respuestas por guion."""

    def __init__(self, guion: dict):
        self.guion, self.errores_ocr, self.ultimo_error = guion, 0, ""

    def cargar(self, ruta):
        return ruta

    def pista(self, imagen):
        return self.guion.get(imagen, {}).get("pista", {"algo": False})

    def leer(self, imagen, pista):
        dato = self.guion.get(imagen, {})
        if dato.get("errores"):
            self.errores_ocr += dato["errores"]
            self.ultimo_error = "RuntimeError: OCR sintético con error"
        return dict(dato.get("campos") or {})

    def fechas(self, imagen):
        return list(self.guion.get(imagen, {}).get("fechas") or [])

    @staticmethod
    def guardar_recorte(destino, recorte):
        return False


def escenario(indice: int, numero: str) -> tuple[str, dict]:
    """Guion sintético por ruta relativa (PHOTOS/...). Valores imposibles de confundir."""
    serie = f"999 SIM{int(numero) % 100000:05d}A"
    dia = 1 + indice % 27
    fecha_ok = f"2031-02-{dia:02d}"
    s = {"dashboard_serial_number": {"valor": serie, "confianza": 0.9}}
    tipo = indice % 5
    if tipo == 0:
        nombre = "consenso: serie en 2 fotos, fecha en 2 fotos"
        guion = {"NACH/IMG_0001.JPG": {"pista": PISTA, "campos": {**s, "dashboard_date": {
                     "valor": fecha_ok, "confianza": .8, "origen": fecha_ok}}},
                 "VOR/IMG_0001.JPG": {"pista": PISTA, "campos": {**s, "dashboard_date": {
                     "valor": fecha_ok, "confianza": .8, "origen": fecha_ok}}}}
    elif tipo == 1:
        nombre = "clases: módulo y proveedor no compiten con el sticker (2.ª pasada)"
        guion = {"NACH/IMG_0001.JPG": {"pista": PISTA, "campos": {"dashboard_date": {
                     "valor": "2031-01-11", "confianza": .8, "origen": "11/01/2031"}}},
                 "NACH/IMG_0002.JPG": {"pista": PISTA, "campos": {"dashboard_date": {
                     "valor": "2031-01-06", "confianza": .8, "origen": "06/01/2031"}}},
                 "VOR/IMG_0002.JPG": {"fechas": [{"valor": "2031-01-06", "clase": "proveedor",
                                                  "texto": "LIEFERANT 06/01/2031"}]},
                 "NACH/IMG_0003.JPG": {"fechas": [{"valor": fecha_ok, "clase": "tablero",
                                                   "ancla": "etiqueta_blanca",
                                                   "texto": f"{fecha_ok} 10:32 N/P"}]}}
    elif tipo == 2:
        nombre = "fechas del tablero contradictorias: duda, no se publica"
        guion = {"NACH/IMG_0003.JPG": {"fechas": [{"valor": fecha_ok, "clase": "tablero"}]},
                 "VOR/IMG_0002.JPG": {"fechas": [{"valor": "2031-03-30", "clase": "tablero"}]}}
    elif tipo == 3:
        nombre = "error de OCR: fotos con error, nada es «sin dato»"
        guion = {f: {"pista": PISTA, "errores": 2} for f in FOTOS}
    else:
        nombre = "sin ancla en ninguna foto: la 2.ª pasada examina y no encuentra"
        guion = {}
    return nombre, {f"PHOTOS/{k}": v for k, v in guion.items()}


def numeros_1st(libro: Path) -> list[str]:
    from openpyxl import load_workbook
    hoja = load_workbook(libro, read_only=True, data_only=True)["Versuchsmatrix"]
    numeros = []
    for fila in hoja.iter_rows(min_row=8, max_row=57, min_col=3, max_col=3, values_only=True):
        texto = str(fila[0] or "").strip()
        if len(texto) == 6 and texto.isdigit() and texto not in numeros:
            numeros.append(texto)
    return numeros


def vaciar_tablero(origen: Path, destino: Path, numeros: list[str]) -> None:
    """Copia del libro con O:R de los casos vaciadas (simula una plantilla sin tablero)."""
    from openpyxl import load_workbook
    shutil.copy2(origen, destino)
    libro = load_workbook(destino)
    for nombre in ("Versuchsmatrix", "Rangos"):
        if nombre not in libro.sheetnames:
            continue
        hoja = libro[nombre]
        for fila in range(8, hoja.max_row + 1):
            if str(hoja.cell(fila, 3).value or "").strip() in numeros:
                for columna in range(15, 19):
                    hoja.cell(fila, columna).value = None
    libro.save(destino)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Simulación sintética de la integración del tablero")
    ap.add_argument("--libro", required=True, help="libro de partida (no se modifica)")
    ap.add_argument("--salida", required=True, help="carpeta donde crear el directorio de la simulación")
    ap.add_argument("--vaciar-tablero", action="store_true",
                    help="usar una COPIA del libro con O:R vacías como partida")
    ap.add_argument("--referencia", default="", help="sólo para evaluar")
    args = ap.parse_args(argv)

    import cv2
    import numpy as np

    import validacion
    import verificar_salida_p43 as V
    from configuracion import cargar_config, cargar_reglas
    from estructura import guardar_estructura, mapear_estructura
    from reporte_bmg import generar_reporte_bmg

    libro_original = Path(args.libro).resolve()
    huella_original = hashlib.sha256(libro_original.read_bytes()).hexdigest()
    Path(args.salida).mkdir(parents=True, exist_ok=True)
    trabajo = Path(tempfile.mkdtemp(prefix="sim_p43_", dir=str(Path(args.salida).resolve())))
    numeros = numeros_1st(libro_original)
    if not numeros:
        print("el libro no tiene casos 1ST en Versuchsmatrix filas 8-57", file=sys.stderr)
        return 2
    base = trabajo / f"partida_{libro_original.name}"
    if args.vaciar_tablero:
        vaciar_tablero(libro_original, base, numeros)
    else:
        shutil.copy2(libro_original, base)
    huella_base = hashlib.sha256(base.read_bytes()).hexdigest()

    raiz = trabajo / "Proyecto sintetico_1ST"
    guion: dict[str, dict] = {}
    escenarios = {}
    pequena = cv2.imencode(".jpg", np.full((32, 32, 3), 180, np.uint8))[1]
    for indice, numero in enumerate(numeros):
        caso = raiz / "HT" / f"{numero} RDW OGL HT"
        nombre, por_relativa = escenario(indice, numero)
        escenarios[numero] = nombre
        for relativa in FOTOS:
            ruta = caso / "PHOTOS" / relativa
            ruta.parent.mkdir(parents=True, exist_ok=True)
            pequena.tofile(str(ruta))
        for relativa, dato in por_relativa.items():
            guion[str(caso / relativa)] = dato

    config = deepcopy(cargar_config())
    emp = config.setdefault("empresarial", {})
    emp.update({"archivo_cache": str(trabajo / "cache.sqlite3"),
                "archivo_avance_ids": str(trabajo / "avances.json"),
                "base_conocimiento": str(trabajo / "base.json")})
    emp.setdefault("tablero_p42", {})["activar"] = True
    config.setdefault("aprendizaje", {})["directorio"] = str(trabajo / "aprendizaje")

    def ocr_vacio(ruta, _config, **_kwargs):
        return {"imagen": ruta, "texto_completo": "", "tokens": [], "lineas_texto": [],
                "confianza_media": 0.0, "estado_imagen": "descartada_sin_texto"}

    validacion.extraer_texto_empresarial = ocr_vacio        # sólo en este proceso
    estructura = guardar_estructura(mapear_estructura(raiz, config), trabajo / "estructura.json")
    resultado = validacion.validar_lote_empresarial(
        estructura, config, archivo_salida=trabajo / "validacion_simulada.json",
        dir_corrida=trabajo / "artefactos",
        fabrica_lector_tablero=lambda: LectorSintetico(guion))
    salida = generar_reporte_bmg(base, trabajo / "SALIDA_SIMULADA_NO_ES_LECTURA_REAL.xlsx",
                                 resultado["resultados"], config, cargar_reglas())
    informe = json.loads((trabajo / "artefactos" / "informe_tablero_p42.json").read_text(encoding="utf-8"))
    verificacion = V.verificar(base, salida, resultado, informe, huella_base)
    if hashlib.sha256(libro_original.read_bytes()).hexdigest() != huella_original:
        verificacion["ok"] = False
        verificacion["errores"].append("el --libro original cambió")
    if args.referencia:
        verificacion["evaluacion"] = V.evaluar(salida, Path(args.referencia))
    verificacion["escenarios"] = escenarios
    (trabajo / "verificacion.json").write_text(
        json.dumps(verificacion, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("SIMULACIÓN SINTÉTICA (no es lectura de fotos)")
    for numero, nombre in escenarios.items():
        campos = next(r for r in resultado["resultados"] if r["test_number"] == numero)["campos"]
        print(f"  {numero}: {nombre}\n      fecha={campos['dashboard_date'].get('valor')!s:12s} "
              f"serie={campos['dashboard_serial_number'].get('valor')!s}")
    print(V.texto(verificacion))
    print(f"\ndirectorio: {trabajo}\nsalida:     {salida}\n"
          f"informe:    {trabajo / 'artefactos' / 'informe_tablero_p42.txt'}")
    return 0 if verificacion["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
