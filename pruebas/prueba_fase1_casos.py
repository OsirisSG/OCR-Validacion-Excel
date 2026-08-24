"""
prueba_fase1_casos.py — Valida los 4 casos obligatorios del Documento Maestro §3:
(a) QR + texto arriba, (b) QR + texto abajo, (c) sin QR + texto arriba,
(d) sin QR + texto abajo. Los cuatro deben extraer el código correctamente,
sin que la presencia del QR o la posición del texto cambien el resultado.
Además: foto invertida 180° y foto con skew 4° del lote de pruebas.
"""

from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr_engine import extraer_texto

RAIZ = Path(__file__).resolve().parents[1] / "datos_prueba"

casos = [
    ("a", RAIZ / "casos_ocr" / "caso_a_qr_texto_arriba.png", True, "ETQ-2024-A1-V2"),
    ("b", RAIZ / "casos_ocr" / "caso_b_qr_texto_abajo.png", True, "ETQ-2024-A1-V2"),
    ("c", RAIZ / "casos_ocr" / "caso_c_sin_qr_texto_arriba.png", False, "ETQ-2024-A1-V2"),
    ("d", RAIZ / "casos_ocr" / "caso_d_sin_qr_texto_abajo.png", False, "ETQ-2024-A1-V2"),
    ("extra-180", RAIZ / "Lote_Pruebas" / "02_A1_variante3" / "foto_lateral.jpg", False, "ETQ-2024-A1-V3"),
    ("extra-skew4", RAIZ / "Lote_Pruebas" / "03_B7_variante1" / "foto_frontal.jpg", True, "ETQ-2024-B7-V1"),
]

fallos = 0
for etiqueta, ruta, qr_esperado, codigo_esperado in casos:
    r = extraer_texto(str(ruta))
    tokens = [t["texto"] for t in r["tokens"]]
    codigo_ok = any(codigo_esperado in t.replace(" ", "") for t in tokens)
    qr_ok = (r["qr_bbox"] is not None) == qr_esperado
    estado = "OK " if (codigo_ok and qr_ok) else "FALLO"
    fallos += 0 if (codigo_ok and qr_ok) else 1
    print(f"[{estado}] caso {etiqueta}: qr={r['qr_bbox'] is not None} (esperado {qr_esperado}) "
          f"rot={r['orientacion_corregida_grados']} conf={r['confianza_media']} "
          f"motor={r['motor']}")
    print(f"        tokens={tokens} (se espera que contenga {codigo_esperado})")

print(f"\n{'TODOS LOS CASOS OK' if fallos == 0 else f'{fallos} CASOS FALLIDOS'}")
sys.exit(1 if fallos else 0)
