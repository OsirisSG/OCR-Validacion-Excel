"""
evidencia_fase1.py — Genera la evidencia para docs/fase1_ocr.md:
texto crudo del motor OCR vs tokens finales segmentados, sobre el caso (a).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from configuracion import cargar_config
from ocr_engine import (_pasada_ocr, cargar_imagen, obtener_motor,
                        segmentar_tokens)

ruta = Path(__file__).resolve().parents[1] / "datos_prueba" / "casos_ocr" / "caso_a_qr_texto_arriba.png"
config = cargar_config()
motor, f1 = obtener_motor(config)
imagen = cargar_imagen(ruta)

pasada = _pasada_ocr(imagen, f1, motor)
tokens = segmentar_tokens(pasada["lineas"], int(f1["umbral_espacio_px"]))

print("=== TEXTO CRUDO DEL MOTOR (lineas con caja y confianza) ===")
for l in pasada["lineas"]:
    print(f"  {l['texto']!r:40} bbox={l['bbox']} conf={l['confianza']:.4f}")
print("\n=== TOKENS FINALES SEGMENTADOS ===")
for t in tokens:
    print(f"  {t['texto']!r:40} bbox={t['bbox']} conf={t['confianza']:.4f}")
print("\nqr_bbox:", pasada["qr"], "| roi:", pasada["roi"])
