"""P46 · Overlay de los vídeos EDAG dentro de la corrida normal (fecha, lugar, número, motivo).

Medido con los vídeos del usuario (`OsirisSG79/Videos`, caso 252590, 4 cámaras):

    pie:      «VW316/5 252590 RdW RT NOM 0ms EDAG Mex BMG 19 JUN 25 Rec5000 fps, Schutter 80us»
    cabecera: «EDAG México … EDAG Testlab … 75.0»

Hasta ahora el pie sólo lo leían herramientas sueltas (`rellenar_desde_videos.py`,
`evidencia_video.py`); `validar_lote_empresarial` analizaba el vídeo sólo para la apertura. Por eso
D (fecha de prueba), E (lugar) y A (semana) nunca se llenaban en la corrida normal.

Qué hace: de cada vídeo del caso toma pocos fotogramas, recorta el pie y la cabecera, hace OCR
(el mismo RapidOCR del tablero) y lo interpreta con `barra_estado.interpretar_barra` y
`video_cabecera.lugar_de_texto`. Cada vídeo es UN voto por campo (mayoría entre sus fotogramas).

P50 · `delay_ms`: el «0ms» del pie SÍ es el delay (lo usaba ya la lógica del usuario,
`barra_estado`/`rellenar_desde_videos`; el libro histórico escribe `--`, `5ms`, `200ms`). Se
publica sólo si es el MISMO en los fotogramas del vídeo (un contador cambiaría entre el 5 %, el
50 % y el 90 % del vídeo y no tendría mayoría). `0ms` se escribe `--` (convención del libro).
El motivo («BMG») se propone; `decisiones_lote` lo cierra con el vocabulario del libro histórico.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

VERSION = "p50-overlay-2"
# Recortes medidos: el pie ocupa el ~3,5 % inferior del fotograma 960×772; la cabecera el ~4 %
# superior. Se prueban variantes hasta que el pie dé número + fecha (orden de eficacia medida).
VARIANTES_PIE = ((0.965, 2.0, False), (0.965, 1.0, False), (0.94, 1.0, False), (0.94, 2.0, True))
CORTES_CABECERA = (0.04, 0.035, 0.045)
# P51 · el motivo va ENTRE «EDAG Mex» y la fecha, a veces entre comillas («"BMG"», «'BMG'»).
PATRON_MOTIVO = re.compile(
    r"EDAG\s*M[EÉ]X(?:ICO)?\s*(?:[A-Z]\s+(?=[A-Z]{2}))?[\"'“”‘’«»]?\s*(?P<motivo>[A-Z][A-Z0-9]{1,10}(?:\s+[A-Z][A-Z0-9]{1,10})?)"
    r"\s*[\"'“”‘’«»]?\s*\d{1,2}\s*[A-Z]{3}", re.I)
CAMPOS_PIE = ("test_date", "test_number", "temperature_condition", "inflator_type",
              "module_version", "delay_ms")


def formato_delay(ms) -> str | None:
    """`0` → `--` (sin retardo, como en el libro); `5` → `5ms`."""
    try:
        n = int(str(ms).strip())
    except (TypeError, ValueError):
        return None
    return "--" if n == 0 else f"{n}ms"


def normalizar_pie(texto: str) -> str:
    """Separa lo que el OCR pega («0msEDAG MexBMG19 JUN25Rec5000») sin cambiar caracteres. Pura."""
    t = " ".join(str(texto or "").split())
    # P50 · medido en los 4 vídeos de 252590: el OCR lee el delay «0ms» como «Oms» (letra O) en 2 de
    # cada 3 fotogramas. Sólo justo detrás del generador (NOM/OGL/UGL) y delante de «ms».
    t = re.sub(r"\b(NOM|OGL|UGL)\s+[Oo](?=\s?ms)", r"\1 0", t)
    t = re.sub(r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)", " ", t)
    t = re.sub(r"(EDAG\s*M[eé]x(?:ico)?)(?=[A-Z])", r"\1 ", t)
    t = re.sub(r"(?<=\d)\s?ms(?=[A-Za-z])", " ms ", t)                 # «0msEDAG» → «0 ms EDAG»
    t = re.sub(r"\bVW\s+(\d{3})\s*/\s*(\d)", r"VW\1/\2", t)      # devuelve VW316/5 a su forma
    return " ".join(t.split())


def interpretar_pie(texto: str) -> dict:
    """Campos del pie con las reglas de `barra_estado`. Pura."""
    from utilidades.barra_estado import interpretar_barra
    limpio = normalizar_pie(texto)
    datos = dict(interpretar_barra(limpio))
    if "delay_ms" in datos:
        datos["delay_ms"] = formato_delay(datos["delay_ms"])
        if datos["delay_ms"] is None:
            datos.pop("delay_ms")
    motivo = PATRON_MOTIVO.search(limpio)
    if motivo:
        datos["test_reason"] = " ".join(motivo.group("motivo").split()).upper()
    return datos


def _fotogramas(ruta: Path, muestras: int):
    import cv2
    captura = cv2.VideoCapture(str(ruta))
    try:
        total = int(captura.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        posiciones = [int(total * f) for f in (0.05, 0.5, 0.9)][:muestras] if total > 0 else [0]
        for posicion in posiciones:
            captura.set(cv2.CAP_PROP_POS_FRAMES, posicion)
            ok, fotograma = captura.read()
            if ok and fotograma is not None:
                yield posicion, fotograma
    finally:
        captura.release()


def leer_overlay(ruta: str | Path, motor, muestras: int = 3) -> dict:
    """Lee pie y cabecera de un vídeo. Devuelve votos por campo y el texto crudo."""
    import cv2

    from utilidades.tablero_campos import _textos
    from utilidades.video_cabecera import lugar_de_texto
    votos: dict[str, Counter] = {}
    textos, fotogramas = [], 0
    for posicion, fotograma in _fotogramas(Path(ruta), muestras):
        fotogramas += 1
        alto = fotograma.shape[0]
        datos = {}
        for corte, escala, invertir in VARIANTES_PIE:
            pie = fotograma[int(alto * corte):, :]
            if escala != 1.0:
                pie = cv2.resize(pie, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
            if invertir:
                pie = 255 - pie
            texto = " ".join(t for t, _ in _textos(pie, motor))
            datos = interpretar_pie(texto)
            if datos.get("test_date") and datos.get("test_number"):
                textos.append(f"[{posicion}] {texto}")
                break
        for corte in CORTES_CABECERA:
            cabecera = cv2.resize(fotograma[:int(alto * corte), :], None, fx=2, fy=2,
                                  interpolation=cv2.INTER_CUBIC)
            texto_cabecera = " ".join(t for t, _ in _textos(cabecera, motor))
            # «EDAG Testlab» explícito (el contrato pide el rótulo del laboratorio, no «EDAG Mex»)
            if re.search(r"TEST\s*L?A?B", texto_cabecera.upper()) and "EDAG" in texto_cabecera.upper():
                datos["test_place_cabecera"] = lugar_de_texto(texto_cabecera)
                break
        for campo, valor in datos.items():
            if campo in (*CAMPOS_PIE, "test_reason", "test_place_cabecera") and valor:
                votos.setdefault(campo, Counter())[str(valor)] += 1
    return {"version": VERSION, "fotogramas": fotogramas, "textos": textos,
            "votos": {k: dict(v) for k, v in votos.items()}}


def candidatos_overlay(caso: dict, video: dict, lectura: dict) -> list[dict]:
    """Un candidato por campo y vídeo, con el contrato de `extraer_candidatos_texto`. Pura.

    Sólo vale el valor que tiene MAYORÍA estricta entre los fotogramas leídos del vídeo.
    """
    salida = []
    leidos = max(1, int(lectura.get("fotogramas") or 0))
    reglas = {"test_date": "fecha_en_barra_de_video", "test_number": "numero_en_barra_de_video",
              "temperature_condition": "temperatura_en_barra_de_video",
              "inflator_type": "inflador_en_barra_de_video",
              "module_version": "version_en_barra_de_video",
              "test_reason": "motivo_en_barra_de_video",
              "delay_ms": "delay_en_barra_de_video",
              "test_place_cabecera": "laboratorio_edag_explicito"}
    for campo, votos in (lectura.get("votos") or {}).items():
        if not votos:
            continue
        valor, n = Counter(votos).most_common(1)[0]
        if n * 2 <= min(leidos, sum(votos.values())) and len(votos) > 1:
            continue                                   # sin mayoría dentro del vídeo
        clave = "test_place" if campo == "test_place_cabecera" else campo
        salida.append({
            "proyecto": caso.get("project_id"), "etapa": caso.get("tipo_st"),
            "caso": caso.get("case_key"), "componente": "por_identificar", "clave": clave,
            "valor_original": next((t for t in lectura.get("textos") or []), "")[:200] or valor,
            "valor_normalizado": valor, "fuente": "barra_video",
            "imagen": video.get("ruta_relativa") or Path(str(video.get("ruta"))).name,
            "imagen_absoluta": video.get("ruta"), "bbox_original": None, "orientacion_grados": 0,
            "transformaciones": [], "fase": None, "tor": None, "confianza_ocr": round(n / leidos, 3),
            "valido_catalogo": True, "valido_regex": True, "regla_aplicada": reglas.get(campo, campo),
            "confirmacion_manual": False,
            # el motivo del pie («BMG») no es el texto del libro («IT BMG»): se propone, no se publica
            "requiere_confirmacion_manual": clave == "test_reason",
            "votos": n, "version_procesamiento": VERSION,
            "motivo_p42": ("el pie dice «%s»; confirmar el texto completo en el panel" % valor
                           if clave == "test_reason" else "")})
    return salida
