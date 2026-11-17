#!/usr/bin/env python3
"""P43 · Reproduce, SIN fotos, los defectos confirmados. Ejecutar contra el código antiguo y
contra el nuevo para ver el antes/después:

    python -I reproducir_defectos_p43.py --codigo "C:\\ruta\\codigo_antiguo"
    python -I reproducir_defectos_p43.py --codigo "C:\\Programas Base\\OCR-Validacion-Excel-ocr-gpu-produccion"

`-I` es necesario: sin él, Python antepone la carpeta del script a `sys.path` y, si el script
está en el código nuevo, mezclaría módulos nuevos al medir el antiguo.

Cada línea: [DEFECTO] si el comportamiento antiguo está presente, [OK] si no.
No modifica nada fuera de un directorio temporal.
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
import tempfile
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codigo", required=True)
    args = ap.parse_args(argv)
    raiz = Path(args.codigo).resolve()
    sys.path.insert(0, str(raiz))
    defectos = 0

    def linea(defecto: bool, texto: str):
        nonlocal defectos
        defectos += int(defecto)
        print(f"  [{'DEFECTO' if defecto else 'OK     '}] {texto}")

    print(f"código: {raiz}")
    # D1 · el flujo normal no conecta ningún lector del tablero
    fuente = "".join((raiz / n).read_text(encoding="utf-8") for n in
                     ("validacion.py", "pipeline.py", "flujo_empresarial.py"))
    conectado = "tablero_integracion" in fuente
    linea(not conectado, "D1 · validar_lote_empresarial incorpora candidatos especializados del tablero")

    # D2 · semana derivada sin perfil EDAG y sin mirar el WW del número
    fe = importlib.import_module("flujo_empresarial")
    caso = {"case_key": "P|1ST|512504", "project_id": "P", "tipo_st": "1ST", "ruta_relativa": "x",
            "metadata_ruta": {"test_number": "512504"}}
    fechas = [{"clave": "test_date", "valor_normalizado": "2025-05-28", "valor_original": "x",
               "fuente": "ocr", "imagen": f"{i}.jpg", "confianza_ocr": .9} for i in range(2)]
    semana = fe.consolidar_caso(caso, fechas)["campos"]["week"]
    linea(semana.get("valor") is not None,
          f"D2 · semana sin perfil EDAG (512504, fecha semana 22) → {semana.get('valor')!r} "
          f"estado {semana.get('estado')!r}")

    # D3 · segunda pasada y auditoría identifican fotos sólo por nombre
    with tempfile.TemporaryDirectory() as tmp:
        carpeta = Path(tmp) / "232564 RDW OGL HT"
        for fase in ("NACH", "VOR"):
            (carpeta / fase).mkdir(parents=True)
            (carpeta / fase / "IMG_4408.JPG").write_bytes(b"x")
        A = importlib.import_module("auditar_cobertura")
        presentes = A.por_caso(Path(tmp)).get("232564", {})
        linea(len(presentes) != 2, f"D3a · auditoría: 2 fotos NACH/VOR con el mismo nombre → {len(presentes)} registro(s)")
        B = importlib.import_module("buscar_mas")
        ok = hasattr(B, "fotos_ya_miradas")
        if ok:
            parcial = Path(tmp) / "p.json"
            parcial.write_text(json.dumps({"232564": {"lecturas": {"dashboard_serial_number": [
                {"foto": "IMG_4408.JPG", "carpeta": "VOR"}]}}}), encoding="utf-8")
            vistas = B.fotos_ya_miradas(parcial, "232564", carpeta)
            ok = vistas == {"vor/img_4408.jpg"}
        linea(not ok, "D3b · buscar_mas: leer VOR/IMG_4408 no debe dar por mirada NACH/IMG_4408")

    # D4 · leer_tablero_lote con rutas /tmp fijas y parcial compartido
    texto = (raiz / "leer_tablero_lote.py").read_text(encoding="utf-8")
    linea('Path("/tmp/' in texto, "D4 · leer_tablero_lote usa /tmp fijo y parcial compartido entre corridas")

    # D5 · un error del motor OCR se confunde con «sin texto»
    T = importlib.import_module("utilidades.tablero_campos")
    import numpy as np

    def motor_roto(_):
        raise RuntimeError("onnx")
    sin_texto = T._textos(np.zeros((8, 8, 3), np.uint8), motor_roto) == []
    vigilado = False
    try:
        TI = importlib.import_module("tablero_integracion")
        m = TI.MotorVigilado(motor_roto)
        T._textos(np.zeros((8, 8, 3), np.uint8), m)
        vigilado = m.errores == 1
    except ImportError:
        pass
    linea(sin_texto and not vigilado,
          "D5 · tablero_campos._textos devuelve [] ante un error del OCR (sin contador de errores)")

    # D6 · cerrar() funde con el JSON anterior sin opción de no hacerlo
    E = importlib.import_module("evidencia_tablero")
    linea(not hasattr(E, "cerrar_registro"),
          "D6 · cierre P42 sólo disponible fundiendo con un JSON previo (sin cierre en memoria)")
    print(f"\n{defectos} defecto(s) presentes")
    return 1 if defectos else 0


if __name__ == "__main__":
    raise SystemExit(main())
