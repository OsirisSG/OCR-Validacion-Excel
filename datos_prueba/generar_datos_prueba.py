"""
generar_datos_prueba.py — Crea un lote sintético completo para validar el pipeline.

Propósito
---------
Genera imágenes de etiquetas y de referencia con OpenCV (sin datos reales de la
empresa) para poder ejecutar y verificar las Fases 0-3 de extremo a extremo.

Qué produce (todo bajo datos_prueba/):
  Lote_Pruebas/                      ← raíz con jerarquía no uniforme
    01_A1_variante2/                 ← conforme; referencia por pista de nombre
    02_A1_variante3/                 ← conforme; foto lateral invertida 180°
    03_B7_variante1/                 ← conforme; referencia SIN pista de nombre
                                        (la debe encontrar la heurística de
                                        densidad de texto) + foto skewed
    04_B7_variante2/                 ← conforme; referencia con código DISTINTO
                                        (debe salir discrepancia)
    05_C2_variante1/                 ← conforme; SIN imagen de referencia
    notas_sueltas/                   ← anómala: sin patrón ni imágenes
  casos_ocr/                         ← los 4 casos obligatorios de docs/fase1_ocr.md
    caso_a_qr_texto_arriba.png
    caso_b_qr_texto_abajo.png
    caso_c_sin_qr_texto_arriba.png
    caso_d_sin_qr_texto_abajo.png

Uso:  python datos_prueba/generar_datos_prueba.py [--destino datos_prueba]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

FUENTE = cv2.FONT_HERSHEY_SIMPLEX


def _texto_ajustado(img, texto, org_izq, y, escala, grosor, color=(0, 0, 0)):
    """Dibuja `texto` garantizando que quepa: reduce la escala si excede el ancho."""
    alto_img, ancho_img = img.shape[:2]
    (ancho, _), _ = cv2.getTextSize(texto, FUENTE, escala, grosor)
    while org_izq + ancho > ancho_img - 30 and escala > 0.4:
        escala *= 0.9
        (ancho, _), _ = cv2.getTextSize(texto, FUENTE, escala, grosor)
    cv2.putText(img, texto, (org_izq, y), FUENTE, escala, color, grosor, cv2.LINE_AA)


def _qr(lado_px: int, contenido: str) -> np.ndarray:
    """Genera un QR como imagen BGR cuadrada de lado_px (contenido NO se decodifica luego)."""
    enc = cv2.QRCodeEncoder_create()
    qr = enc.encode(contenido)
    return cv2.cvtColor(
        cv2.resize(qr, (lado_px, lado_px), interpolation=cv2.INTER_NEAREST),
        cv2.COLOR_GRAY2BGR,
    )


def _lienzo(alto=760, ancho=1040) -> np.ndarray:
    """Lienzo 'foto': blanco roto con viñeta suave y ruido leve (no pixel-perfect)."""
    img = np.full((alto, ancho, 3), 250, np.uint8)
    ruido = np.random.default_rng(42).normal(0, 4, img.shape).astype(np.float32)
    img = np.clip(img.astype(np.float32) + ruido, 0, 255).astype(np.uint8)
    cv2.rectangle(img, (12, 12), (ancho - 12, alto - 12), (208, 208, 208), 3)
    return img


def etiqueta(codigo: str, qr: bool, texto_arriba: bool, rotar_180=False, skew_grados=0.0) -> np.ndarray:
    """Foto de etiqueta: código alfanumérico + QR opcional, en posiciones variables."""
    img = _lienzo()
    if qr:
        q = _qr(210, f"LOTE|{codigo}")
        img[500:710, 60:270] = q  # QR abajo-izquierda, fijo (el texto es el que se mueve)
    y_texto = 190 if texto_arriba else 600
    _texto_ajustado(img, codigo, 330, y_texto, 2.6, 7)
    cv2.putText(img, "PRUEBA DE ETIQUETA", (330, y_texto - 90 if texto_arriba else y_texto + 100),
                FUENTE, 1.0, (90, 90, 90), 3, cv2.LINE_AA)
    if rotar_180:
        img = cv2.rotate(img, cv2.ROTATE_180)
    if skew_grados:
        h, w = img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), skew_grados, 1.0)
        img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(250, 250, 250))
    return img


def referencia(codigo: str, lineas_extra: list[str] | None = None) -> np.ndarray:
    """Imagen de referencia: bloque denso de texto con la nomenclatura destacada."""
    img = _lienzo(760, 1040)
    _texto_ajustado(img, codigo, 70, 160, 3.0, 8)
    y = 260
    for linea in (lineas_extra or [
        "FICHA TECNICA DE REFERENCIA",
        "REV 2 - AREA DE ENSAYOS",
        "VERIFICAR NOMENCLATURA ANTES DE ENSAYO",
        "CUALQUIER DIFERENCIA DETENER PROCESO",
        "CONTACTO: LAB-CALIDAD INT 4051",
    ]):
        cv2.putText(img, linea, (70, y), FUENTE, 1.1, (40, 40, 40), 3, cv2.LINE_AA)
        y += 90
    return img


def _video_demo(ruta: Path, ancho=320, alto=240, cuadros=12) -> None:
    """Video corto de relleno para que la Fase 0 clasifique por extensión."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    escritor = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"mp4v"), 12, (ancho, alto))
    if not escritor.isOpened():
        ruta.write_bytes(b"")  # respaldo: archivo vacío, la clasificación es por extensión
        return
    for i in range(cuadros):
        cuadro = np.full((alto, ancho, 3), 250, np.uint8)
        cv2.putText(cuadro, f"ENSAYO {i:02d}", (60, 130), FUENTE, 1.0, (0, 0, 0), 3)
        escritor.write(cuadro)
    escritor.release()


def generar(destino: Path) -> dict:
    """Crea toda la estructura y retorna un resumen de archivos generados."""
    np.random.seed(42)
    lote = destino / "Lote_Pruebas"
    resumen = {"imagenes": 0, "videos": 0, "otros": 0}

    def guardar(img, carpeta: str, nombre: str):
        no_existe = not (lote / carpeta).exists()
        (lote / carpeta).mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(lote / carpeta / nombre), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        resumen["imagenes"] += 1

    # --- 01: referencia por PISTA DE NOMBRE (info_referencia.jpg) -------------
    guardar(etiqueta("ETQ-2024-A1-V2", qr=True, texto_arriba=True),
            "01_A1_variante2", "foto_frontal.jpg")                       # caso (a)
    guardar(etiqueta("ETQ-2024-A1-V2", qr=False, texto_arriba=False),
            "01_A1_variante2", "foto_lateral.jpg")                       # caso (d)
    guardar(referencia("ETQ-2024-A1-V2"), "01_A1_variante2", "info_referencia.jpg")
    _video_demo(lote / "01_A1_variante2" / "video_ensayo.mp4")
    resumen["videos"] += 1

    # --- 02: foto lateral INVERTIDA 180 (ejercita detección de invertida) -----
    guardar(etiqueta("ETQ-2024-A1-V3", qr=True, texto_arriba=False),
            "02_A1_variante3", "foto_frontal.jpg")                       # caso (b)
    guardar(etiqueta("ETQ-2024-A1-V3", qr=False, texto_arriba=True, rotar_180=True),
            "02_A1_variante3", "foto_lateral.jpg")                       # caso (c) + 180°
    guardar(referencia("ETQ-2024-A1-V3"), "02_A1_variante3", "info_referencia.jpg")

    # --- 03: referencia SIN pista de nombre (heurística de densidad) ----------
    guardar(etiqueta("ETQ-2024-B7-V1", qr=True, texto_arriba=True, skew_grados=4.0),
            "03_B7_variante1", "foto_frontal.jpg")                       # skew 4°
    guardar(etiqueta("ETQ-2024-B7-V1", qr=False, texto_arriba=True),
            "03_B7_variante1", "foto_detalle.jpg")
    guardar(referencia("ETQ-2024-B7-V1"), "03_B7_variante1", "IMG_20240312.jpg")

    # --- 04: referencia con código DISTINTO (debe salir discrepancia) ---------
    guardar(etiqueta("ETQ-2024-B7-V2", qr=True, texto_arriba=False),
            "04_B7_variante2", "foto_frontal.jpg")
    guardar(referencia("ETQ-2024-B7-V9"), "04_B7_variante2", "info_referencia.jpg")

    # --- 05: SIN referencia (debe salir sin_referencia) -----------------------
    guardar(etiqueta("ETQ-2024-C2-V1", qr=False, texto_arriba=True),
            "05_C2_variante1", "foto_frontal.jpg")
    guardar(etiqueta("ETQ-2024-C2-V1", qr=False, texto_arriba=False),
            "05_C2_variante1", "foto_lateral.jpg")

    # --- carpeta anómala del ejemplo del Documento Maestro --------------------
    (lote / "notas_sueltas").mkdir(parents=True, exist_ok=True)
    (lote / "notas_sueltas" / "nota_revision.txt").write_text(
        "Notas sueltas del operador, sin fotos ni patrón de nombre.", encoding="utf-8")
    resumen["otros"] += 1

    # --- 4 casos obligatorios de la Fase 1 ------------------------------------
    casos = destino / "casos_ocr"
    casos.mkdir(parents=True, exist_ok=True)
    for nombre, img in {
        "caso_a_qr_texto_arriba.png": etiqueta("ETQ-2024-A1-V2", qr=True, texto_arriba=True),
        "caso_b_qr_texto_abajo.png": etiqueta("ETQ-2024-A1-V2", qr=True, texto_arriba=False),
        "caso_c_sin_qr_texto_arriba.png": etiqueta("ETQ-2024-A1-V2", qr=False, texto_arriba=True),
        "caso_d_sin_qr_texto_abajo.png": etiqueta("ETQ-2024-A1-V2", qr=False, texto_arriba=False),
    }.items():
        cv2.imwrite(str(casos / nombre), img)
        resumen["imagenes"] += 1

    return resumen


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Genera el lote sintético de pruebas.")
    parser.add_argument("--destino", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    resumen = generar(Path(args.destino))
    print(f"Datos de prueba generados en {args.destino}: {resumen}")
