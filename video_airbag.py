"""Análisis local de videos de despliegue de airbag.

V15.6 analiza el nacimiento del airbag como un evento temporal y unifica la
fuente de tiempo para que frame, reloj visible y casilla del dashboard no puedan
contradecirse. Primero busca
evidencia fuerte y persistente de despliegue y después retrocede hasta el primer
cuadro con evidencia débil coherente. Esto permite conservar como tiempo de
apertura la primera punta visible, sin aceptar reflejos aislados como evento.

La resolución temporal real siempre se conserva. Un archivo a 1000 fps aporta
muestras cada 1.0 ms; el estimador sub-frame puede devolver décimas, pero no se
presenta como exactitud física de 0.1 ms salvo que el timestamp visible o la tasa
nativa del archivo la sustenten.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable

import cv2
import numpy as np

from configuracion import RAIZ_PROYECTO, cargar_config
from utilidades import firma_video
from utilidades.persistencia import escribir_json_seguro

EXTENSIONES_VIDEO = {".avi", ".mp4", ".mov", ".mkv", ".wmv", ".m4v"}
CARPETAS_VIDEO = {"video", "videos"}
RUTA_CACHE = RAIZ_PROYECTO / ".cache_ocr" / "video_airbag.json"
RUTA_REVISIONES = RAIZ_PROYECTO / ".aprendizaje" / "revisiones_video.json"
ALGORITMO_VERSION = "v15.8-ruptura-nativa-corroborada"


def _cfg(config: dict | None = None) -> dict:
    config = config or cargar_config()
    base = {
        "activar": True,
        "leer_timestamp_overlay": True,
        # V15.1: se conserva más detalle para no perder el primer borde blanco
        # de la bolsa al reducir demasiado la imagen.
        "max_ancho_analisis": 960,
        # La reducción puede borrar el primer píxel. Los umbrales se aplican
        # sobre la ROI nativa; sólo el cálculo de flujo puede reducirse.
        "analisis_resolucion_nativa": True,
        "fraccion_superior_overlay": 0.18,
        "fraccion_inferior_overlay": 0.18,
        "margen_vertical_deteccion": 0.12,
        # La línea de tiempo de estos AVI puede indicar 8 fps de reproducción
        # aunque hayan sido grabados a 5000 fps. Por eso el baseline ya no se
        # dimensiona con CAP_PROP_FPS: debe ser corto y anterior al despliegue.
        # V15.7: con Rec5000 la bolsa aparece desde ~1.4 ms; un baseline de 8
        # cuadros (0-1.4 ms) la contaminaba y fijaba un suelo en el cuadro 8.
        "frames_baseline_min": 3,
        "frames_baseline_max": 6,
        "baseline_duracion_objetivo_ms": 0.6,
        # Tope duro cuando se conoce la tasa real: protege contra valores
        # antiguos de config.yaml (p.ej. frames_baseline_min: 8).
        "baseline_max_ms": 1.0,
        # V15.7: un tablero que se hincha se deforma y mueve sus brillos, pero
        # no aporta material nuevo. Se compensa ese movimiento con flujo óptico
        # y sólo cuenta como bolsa lo que el movimiento no explica.
        "compensar_movimiento": True,
        "residuo_min_compensado": 18,
        "flujo_ancho_max": 480,
        "flujo_max_px": 10.0,
        # Umbrales relativos al ruido medido en los cuadros del baseline.
        "ruido_factor_pixeles": 3.0,
        "ruido_margen_pixeles": 3,
        # Antes del primer cuadro con bolsa debe haber cuadros limpios.
        "frames_previos_limpios": 2,
        "detener_tras_confirmacion": True,
        "umbral_diff_min": 6.0,
        "persistencia_frames": 2,
        # Detector de "primer blanco nuevo". El evento se fija en el PRIMER
        # cuadro y los siguientes sólo sirven para confirmar que no fue ruido.
        "umbral_luminancia_blanco": 135,
        "umbral_incremento_blanco": 18,
        # Una costura también puede abrir como una fisura oscura antes de que
        # asome tela clara. Hace falta un contorno NUEVO, no sólo más brillo.
        "umbral_luminancia_grieta": 120,
        "umbral_discontinuidad_nueva": 6.0,
        "min_pixeles_indicio": 1,
        "radio_indicio_px": 3.0,
        "max_componentes_indicio": 64,
        # V15.7: mínimos absolutos más bajos (unos pocos píxeles) porque ahora
        # el ruido del video y la compensación de movimiento filtran lo falso.
        "min_fraccion_blanco_nuevo": 0.00001,
        "min_fraccion_componente_blanco": 0.000006,
        # V15.3: el primer indicio puede ser menor que el umbral normal. Sólo
        # se acepta si cuadros posteriores confirman crecimiento/persistencia.
        "evidencia_debil_factor": 0.45,
        "ventana_confirmacion_frames": 5,
        "min_frames_confirmacion": 2,
        "crecimiento_ratio_min": 1.8,
        "fuerte_multiplicador_componente": 2.2,
        "fuerte_multiplicador_pixeles": 1.7,
        "backtracking_max_frames": 7,
        "retroceso_hasta_indicio_continuo": True,
        "usar_perfil_evento_aprendido": True,
        "min_ejemplos_perfil_evento": 3,
        "rescate_cambio_general": False,
        "permitir_persistencia_sin_crecimiento": False,
        "tolerancia_consenso_ms": 0.15,
        "min_videos_consenso": 3,
        # V15.2: cuando el nombre no identifica la cámara, una referencia debe
        # superar este nivel de similitud para heredar su zona aprendida.
        "similitud_minima_zona": 0.34,
        "similitud_minima_zona_nombre": 0.18,
        # V15.4: tolerancia mínima para validar el reloj visible contra la
        # posición temporal del frame. Nunca se aceptan tiempos negativos.
        "timestamp_tolerancia_min_ms": 0.25,
        "timestamp_tolerancia_frames": 1.5,
    }
    base.update((config.get("video_airbag") or {}))
    return base


def descubrir_videos_caso(ruta_caso: str | Path) -> list[dict]:
    """Encuentra videos dentro de VIDEO/VIDEOS (sin importar mayúsculas)."""
    caso = Path(ruta_caso)
    carpetas = []
    try:
        carpetas = [p for p in caso.iterdir() if p.is_dir() and p.name.casefold() in CARPETAS_VIDEO]
    except OSError:
        return []
    salida = []
    for base in sorted(carpetas, key=lambda p: p.name.casefold()):
        for archivo in sorted(base.rglob("*")):
            if not archivo.is_file() or archivo.suffix.lower() not in EXTENSIONES_VIDEO:
                continue
            salida.append({
                "ruta": str(archivo.resolve()),
                "ruta_relativa": archivo.relative_to(caso).as_posix(),
                "nombre": archivo.name,
                "carpeta_video": base.name,
            })
    return salida


def _firma(ruta: str | Path) -> str:
    """Firma por contenido: no cambia al copiar o mover la carpeta del lote."""
    return firma_video.firma_contenido(ruta)


def _leer_json(ruta: Path, defecto):
    try:
        if ruta.is_file():
            data = json.loads(ruta.read_text(encoding="utf-8"))
            return data
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return defecto


def _guardar_json(ruta: Path, data) -> None:
    escribir_json_seguro(ruta, data, lanzar=False, compacto=True)


def cargar_revisiones() -> dict:
    data = _leer_json(RUTA_REVISIONES, {"version": 1, "revisiones": {}})
    if not isinstance(data, dict) or not isinstance(data.get("revisiones"), dict):
        return {"version": 1, "revisiones": {}}
    return data


def guardar_revision_video(ruta_video: str | Path, *, case_key: str | None,
                           frame_index: int | None, tiempo_ms: float | None,
                           estado: str = "confirmado", usuario: str = "dashboard",
                           comentario: str | None = None) -> dict:
    if estado not in {"confirmado", "sin_evento", "pendiente"}:
        raise ValueError("Estado de revisión de video inválido.")
    if estado == "confirmado" and tiempo_ms is not None:
        valor_tiempo = float(tiempo_ms)
        if not math.isfinite(valor_tiempo) or valor_tiempo < 0:
            raise ValueError("El tiempo de apertura confirmado no puede ser negativo.")
    ident = firma_video.identidad(ruta_video)
    firma = ident["firma"]
    data = cargar_revisiones()
    # Sustituye revisiones previas del mismo video aunque se guardaran con la
    # firma antigua o desde otra carpeta.
    data["revisiones"] = {k: v for k, v in data["revisiones"].items()
                          if not firma_video.coincide(v, ident)}
    revision = {
        "firma": firma, "firma_legacy": ident["firma_legacy"], "tamano": ident["tamano"],
        "ruta_video": str(Path(ruta_video).resolve()),
        "case_key": case_key, "frame_index": None if frame_index is None else int(frame_index),
        "tiempo_ms": None if tiempo_ms is None else round(float(tiempo_ms), 3),
        "estado": estado, "usuario": usuario, "comentario": comentario or "",
    }
    from datetime import datetime
    revision["confirmado_en"] = datetime.now().isoformat(timespec="seconds")
    data["revisiones"][firma] = revision
    _guardar_json(RUTA_REVISIONES, data)
    return revision


def revision_video(ruta_video: str | Path) -> dict | None:
    try:
        ident = firma_video.identidad(ruta_video)
    except OSError:
        return None
    revisiones = cargar_revisiones().get("revisiones", {})
    directa = revisiones.get(ident["firma"]) or revisiones.get(ident["firma_legacy"])
    if directa:
        return directa
    # Revisión guardada antes de mover/copiar la carpeta del lote.
    return firma_video.buscar(revisiones.values(), ident)


def _redimensionar_gris(frame: np.ndarray, max_ancho: int) -> np.ndarray:
    gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gris.shape[:2]
    if w > max_ancho:
        escala = max_ancho / float(w)
        gris = cv2.resize(gris, (max_ancho, max(1, int(round(h * escala)))), interpolation=cv2.INTER_AREA)
    return gris


def _roi_deteccion(gris: np.ndarray, margen_vertical: float) -> np.ndarray:
    h, w = gris.shape[:2]
    y1 = max(0, min(h - 1, int(round(h * margen_vertical))))
    y2 = max(y1 + 1, min(h, int(round(h * (1.0 - margen_vertical)))))
    # También se descarta un margen lateral pequeño donde suelen vivir overlays/bordes.
    x1 = max(0, int(round(w * 0.04)))
    x2 = max(x1 + 1, min(w, int(round(w * 0.96))))
    return gris[y1:y2, x1:x2]


def _roi_deteccion_aprendida(gris: np.ndarray, zona: dict | None, margen_vertical: float) -> np.ndarray:
    """Recorta la zona supervisada; si no existe, conserva el ROI general V15.1."""
    bbox = (zona or {}).get("bbox_norm") if (zona or {}).get("activa") else None
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return _roi_deteccion(gris, margen_vertical)
    h, w = gris.shape[:2]
    try:
        x1n, y1n, x2n, y2n = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return _roi_deteccion(gris, margen_vertical)
    x1 = max(0, min(w - 1, int(round(x1n * w))))
    y1 = max(0, min(h - 1, int(round(y1n * h))))
    x2 = max(x1 + 1, min(w, int(round(x2n * w))))
    y2 = max(y1 + 1, min(h, int(round(y2n * h))))
    # Un ROI degenerado no debe romper el análisis automático.
    if (x2 - x1) < 3 or (y2 - y1) < 3:
        return _roi_deteccion(gris, margen_vertical)
    return gris[y1:y2, x1:x2]


def _parsear_timestamp_ms(textos: Iterable[str]) -> list[float]:
    valores: list[float] = []
    for texto in textos:
        t = str(texto or "").replace(",", ".")
        # Prioridad a valores explícitamente etiquetados como ms.
        for m in re.finditer(r"(?<!\d)(-?\d{1,5}(?:\.\d{1,3})?)\s*ms\b", t, re.IGNORECASE):
            try:
                valores.append(float(m.group(1)))
            except ValueError:
                pass
        # Formatos tipo t=6.3 sin unidad, sólo si existe una etiqueta temporal.
        for m in re.finditer(r"(?:\bt\b|time|zeit)\s*[:=]\s*(-?\d{1,5}(?:\.\d{1,3})?)", t, re.IGNORECASE):
            try:
                v = float(m.group(1))
            except ValueError:
                continue
            if v not in valores:
                valores.append(v)
    return valores


def _parsear_fps_grabacion(textos: Iterable[str]) -> list[float]:
    """Extrae la tasa REAL de grabación impresa por la cámara.

    Los AVI EDAG de alta velocidad pueden declarar 8 fps como velocidad de
    reproducción, mientras el overlay contiene por ejemplo ``Rec5000 fps``.
    Esa segunda tasa es la que define la separación temporal entre cuadros.
    """
    valores: list[float] = []
    for texto in textos:
        t = str(texto or "").replace(",", ".")
        patrones = (
            # OCR puede confundir 0/O y 1/I/l en la franja inferior. Sólo
            # normalizamos esos caracteres cuando están inmediatamente detrás
            # de Rec/Recording/Capture y delante de "fps".
            r"\bRec\s*[:=]?\s*([0-9OoIl]{2,6}(?:[\.,][0-9OoIl]+)?)\s*fps\b",
            r"\b(?:record(?:ing|ed)?|capture)\s*[:=]?\s*([0-9OoIl]{2,6}(?:[\.,][0-9OoIl]+)?)\s*fps\b",
        )
        for patron in patrones:
            for m in re.finditer(patron, t, re.IGNORECASE):
                bruto = (m.group(1).replace("O", "0").replace("o", "0")
                         .replace("I", "1").replace("l", "1").replace(",", "."))
                try:
                    v = float(bruto)
                except ValueError:
                    continue
                if 1.0 <= v <= 1_000_000 and v not in valores:
                    valores.append(v)
    return valores



TASAS_ESTANDAR_FPS = (250, 500, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 6000, 7500,
                      8000, 10000, 12500, 15000, 20000, 25000, 30000, 40000, 50000, 100000)


def validar_fps_con_reloj(fps_rec: float | None, frame_index: int,
                          reloj_frame_ms: float | None, reloj_inicial_ms: float | None,
                          leer_reloj=None, total_frames: int | None = None,
                          tolerancia: float = 0.2) -> dict:
    """Contrasta Rec…fps con el avance del reloj visible.

    El reloj avanza ``1000 / fps`` ms por cuadro. Si ``Rec5000 fps`` se leyó
    mal (p.ej. ``Rec500``) el tiempo saldría 10 veces mayor. Con el reloj del
    cuadro 0 y del cuadro del evento se calcula la tasa implícita. Como una de
    las dos lecturas puede ser la equivocada, sólo se corrige la tasa si un
    tercer cuadro (``leer_reloj``) confirma al reloj y la tasa resultante es una
    tasa estándar de cámara. Si no hay confirmación, sólo se avisa.
    """
    rec = _numero_no_negativo(fps_rec)
    t1 = _numero_no_negativo(reloj_frame_ms)
    t0 = _numero_no_negativo(reloj_inicial_ms)
    salida = {"fps": rec, "fps_reloj": None, "fps_reloj_control": None,
              "corregido": False, "advertencia": None}
    if t1 is None or t0 is None or frame_index < 4 or t1 - t0 <= 0:
        return salida
    implicita = 1000.0 * frame_index / (t1 - t0)
    salida["fps_reloj"] = round(implicita, 3)
    if rec and abs(rec - implicita) / implicita <= tolerancia:
        return salida  # Rec…fps y reloj coinciden.

    confirma = None
    if leer_reloj is not None:
        f2 = frame_index + max(10, frame_index)
        if total_frames:
            f2 = min(f2, int(total_frames) - 1)
        if f2 > frame_index:
            try:
                t2 = _numero_no_negativo(leer_reloj(f2))
            except Exception:
                t2 = None
            if t2 is not None and t2 > t0:
                control = 1000.0 * f2 / (t2 - t0)
                salida["fps_reloj_control"] = round(control, 3)
                if abs(control - implicita) / implicita <= 0.1:
                    confirma = "reloj"
                elif rec and abs(control - rec) / rec <= tolerancia:
                    confirma = "rec"
    estandar = min(TASAS_ESTANDAR_FPS, key=lambda x: abs(x - implicita))
    if confirma == "reloj" and abs(estandar - implicita) / estandar <= 0.08:
        salida.update(fps=float(estandar), corregido=True, advertencia=(
            f"La tasa leída ({rec:g} fps) no coincide con el avance del reloj en dos "
            f"cuadros ({implicita:.0f} fps); se usa {estandar} fps." if rec else
            f"No se leyó Rec…fps; el avance del reloj en dos cuadros indica {estandar} fps."))
    elif confirma == "rec":
        salida["advertencia"] = ("El reloj del cuadro del evento no cuadra con Rec…fps ni con "
                                 "otro cuadro; se mantiene la tasa leída.")
    elif rec:
        salida["advertencia"] = (
            f"La tasa leída ({rec:g} fps) no coincide con el avance del reloj "
            f"({implicita:.0f} fps). Revisa este video.")
    return salida


def fps_grabacion_desde_item(item: dict | None) -> float | None:
    """Obtiene la tasa REAL de grabación de un resultado de video.

    V15.6 da prioridad al texto del overlay (``Rec5000 fps``) frente a
    ``CAP_PROP_FPS``. Esto repara también resultados antiguos guardados cuando
    OpenCV sólo reportó 8 fps de reproducción.
    """
    item = item or {}
    # V15.7.1: tasa ya contrastada con el reloj del propio video; tiene
    # prioridad sobre un "Rec…fps" mal leído en el texto del overlay.
    validado = _numero_no_negativo(item.get("fps_validado_reloj"))
    if validado and validado > 0:
        return float(validado)
    textos = [
        item.get("overlay_texto"), item.get("overlay_texto_esquina"),
        item.get("texto_overlay"), item.get("texto"),
    ]
    valores = _parsear_fps_grabacion([str(x) for x in textos if x])
    if valores:
        return float(valores[0])
    valor = _numero_no_negativo(item.get("fps_grabacion"))
    if valor and valor > 0:
        return float(valor)
    if str(item.get("fps_fuente") or "") == "overlay_rec":
        valor = _numero_no_negativo(item.get("fps"))
        if valor and valor > 0:
            return float(valor)
    return None

def _parsear_numero_timestamp_esquina(textos: Iterable[str]) -> tuple[float | None, float | None]:
    """Lee un timestamp numérico aislado, como ``2.2`` o ``4.4``.

    Se usa EXCLUSIVAMENTE con el recorte pequeño de la esquina superior
    derecha, donde los videos del banco muestran el reloj en milisegundos.
    Así evitamos confundirlo con IDs, fechas o con el ``0ms`` fijo del pie.
    """
    candidatos: list[tuple[float, int]] = []
    for texto in textos:
        t = str(texto or "").strip().replace(",", ".")
        # Si OCR agregó la unidad, también es válido.
        m_ms = re.search(r"(?<!\d)(-?\d{1,5}(?:\.\d{1,3})?)\s*ms\b", t, re.I)
        if m_ms:
            try:
                valor = float(m_ms.group(1))
                dec = len((m_ms.group(1).split(".", 1) + [""])[1])
                candidatos.append((valor, dec))
            except ValueError:
                pass
            continue
        # En estos videos el reloj suele ser sólo un número: 2.2, 4.4, 5.0...
        m = re.fullmatch(r"\s*(-?\d{1,5}(?:\.\d{1,3})?)\s*", t)
        if not m:
            # Algunos OCR agrupan el rótulo y el reloj en una misma lectura,
            # por ejemplo "EDAG Testlab 2.2". Al estar ya dentro del recorte
            # de esquina, el último decimal sigue siendo el mejor candidato.
            m = re.search(r"(-?\d{1,5}\.\d{1,3})\s*$", t)
        if m:
            try:
                valor = float(m.group(1))
            except ValueError:
                continue
            dec = len((m.group(1).split(".", 1) + [""])[1])
            candidatos.append((valor, dec))
    if not candidatos:
        return None, None
    # El recorte es muy pequeño; normalmente hay uno solo. Se prefiere el que
    # conserve decimales porque es el formato esperado del reloj de ensayo.
    valor, dec = max(candidatos, key=lambda x: (x[1] > 0, x[1]))
    precision = 10 ** (-dec) if dec > 0 else 1.0
    return valor, precision


def _leer_overlay(frame: np.ndarray, config: dict | None = None) -> dict:
    cfg = _cfg(config)
    if not cfg.get("leer_timestamp_overlay", True):
        return {"texto": "", "tiempos_ms": [], "fps_grabacion": [],
                "timestamp_esquina_ms": None, "precision_timestamp_esquina_ms": None,
                "texto_esquina": "", "error": None}
    h, w = frame.shape[:2]
    fs = float(cfg.get("fraccion_superior_overlay", 0.18))
    fi = float(cfg.get("fraccion_inferior_overlay", 0.18))
    superior = frame[:max(1, int(h * fs)), :]
    inferior = frame[max(0, int(h * (1.0 - fi))):, :]
    tiras = [("superior", superior), ("inferior", inferior)]
    lecturas = []
    lecturas_superior = []
    lecturas_esquina = []
    try:
        from ocr_engine import obtener_motor
        motor, _ = obtener_motor(config)
        # Reloj del ensayo: la captura real lo muestra en la esquina superior
        # derecha sin la palabra "ms" (p.ej. 2.2). Se OCRiza aparte para evitar
        # que un 0ms del pie se tome erróneamente como tiempo del cuadro.
        x1 = max(0, int(round(w * 0.72)))
        y2 = max(1, int(round(h * 0.10)))
        esquina = frame[:y2, x1:]
        if esquina.size:
            esc = esquina
            if esc.shape[1] < 700:
                escala = min(4.0, 700.0 / max(1, esc.shape[1]))
                esc = cv2.resize(esc, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
            items_esc = motor.leer_texto_completo(esc)
            lecturas_esquina.extend(str(x.get("texto") or "").strip() for x in items_esc if x.get("texto"))
        for nombre_tira, tira in tiras:
            if tira.size == 0:
                continue
            # Ampliar overlays pequeños sin alterar el cuadro principal.
            if tira.shape[1] < 1600:
                escala = min(2.0, 1600.0 / max(1, tira.shape[1]))
                tira = cv2.resize(tira, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
            items = motor.leer_texto_completo(tira)
            textos_tira = [str(x.get("texto") or "") for x in items if x.get("texto")]
            lecturas.extend(textos_tira)
            if nombre_tira == "superior":
                lecturas_superior.extend(textos_tira)
    except Exception as exc:
        return {"texto": "", "tiempos_ms": [], "fps_grabacion": [],
                "timestamp_esquina_ms": None, "precision_timestamp_esquina_ms": None,
                "texto_esquina": "", "error": f"{type(exc).__name__}: {exc}"}
    texto = " | ".join(lecturas)
    tiempo_esquina, precision_esquina = _parsear_numero_timestamp_esquina(lecturas_esquina)
    origen_timestamp = "esquina_crop" if tiempo_esquina is not None else None
    # Respaldo: en la captura real el OCR general ya devolvía "4.4" como
    # primera lectura, aunque la versión anterior lo ignoraba por no llevar ms.
    # V15.7: el respaldo sólo mira la franja SUPERIOR. La inferior contiene el
    # "0ms" fijo del pie, que nunca es el reloj del cuadro.
    if tiempo_esquina is None:
        tiempo_esquina, precision_esquina = _parsear_numero_timestamp_esquina(lecturas_superior)
        if tiempo_esquina is not None:
            origen_timestamp = "overlay_superior"
    if _numero_no_negativo(tiempo_esquina) is None:
        tiempo_esquina, precision_esquina = None, None
        origen_timestamp = None
    return {
        "texto": texto,
        "tiempos_ms": _parsear_timestamp_ms(lecturas),
        "fps_grabacion": _parsear_fps_grabacion(lecturas),
        "timestamp_esquina_ms": tiempo_esquina,
        "precision_timestamp_esquina_ms": precision_esquina,
        "timestamp_origen": origen_timestamp,
        "texto_esquina": " | ".join(lecturas_esquina),
        "error": None,
    }



def _numero_no_negativo(valor) -> float | None:
    """Convierte a float sólo si es finito y no negativo."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numero) or numero < 0:
        return None
    return numero


def resolver_tiempo_metadata(*, frame_index: int, fps: float | None,
                              timestamp_actual_ms: float | None = None,
                              timestamp_inicial_ms: float | None = None,
                              precision_overlay_ms: float | None = None,
                              config: dict | None = None) -> dict:
    """Resuelve una única fuente de verdad temporal para un frame.

    V15.6 compara dos hipótesis cuando hay reloj visible: tiempo cero en el
    frame 0 y tiempo anclado al timestamp inicial. Se queda con la que mejor
    explica el reloj del MISMO frame. Así un timestamp inicial mal leído no
    puede hacer que un ``2.2 ms`` visible termine convertido en ``1375 ms``.
    """
    cfg = _cfg(config)
    frame = max(0, int(frame_index or 0))
    fps_val = _numero_no_negativo(fps)
    if fps_val is not None and fps_val <= 0:
        fps_val = None
    resolucion = (1000.0 / fps_val) if fps_val else None
    inicial = _numero_no_negativo(timestamp_inicial_ms)
    actual = _numero_no_negativo(timestamp_actual_ms)
    precision = _numero_no_negativo(precision_overlay_ms)

    tiempo_fps = (frame * resolucion) if resolucion is not None else None
    if tiempo_fps is not None:
        tiempo_fps = max(0.0, float(tiempo_fps))

    candidatos_esperados: list[tuple[str, float]] = []
    if tiempo_fps is not None:
        candidatos_esperados.append(("cero", tiempo_fps))
        if inicial is not None:
            anclado = max(0.0, float(inicial) + tiempo_fps)
            if abs(anclado - tiempo_fps) > 1e-9:
                candidatos_esperados.append(("overlay_inicial", anclado))

    tolerancia = float(cfg.get("timestamp_tolerancia_min_ms", 0.25))
    if resolucion is not None:
        tolerancia = max(tolerancia,
                         float(cfg.get("timestamp_tolerancia_frames", 1.5)) * resolucion)
    if precision is not None:
        tolerancia = max(tolerancia, 1.5 * precision)

    esperado = None
    anclaje = None
    discrepancia = None
    advertencia = None
    overlay_valido = False

    if actual is not None:
        if not candidatos_esperados:
            tiempo = actual
            fuente = "timestamp_overlay_esquina"
            overlay_valido = True
            anclaje = "solo_overlay"
        else:
            anclaje, esperado = min(candidatos_esperados, key=lambda x: abs(actual - x[1]))
            discrepancia = actual - esperado
            if abs(discrepancia) <= tolerancia:
                tiempo = actual
                fuente = "timestamp_overlay_esquina"
                overlay_valido = True
            else:
                tiempo = esperado
                fuente = ("fps_anclado_overlay_inicial" if anclaje == "overlay_inicial"
                          else "fps_grabacion_validado")
                advertencia = (
                    f"El OCR del reloj del cuadro leyó {actual:.3f} ms, pero con la tasa "
                    f"de grabación se esperaban {esperado:.3f} ms. Se descartó esa lectura "
                    "para evitar una contradicción temporal."
                )
    elif candidatos_esperados:
        # Sin reloj legible se conserva el anclaje inicial cuando existe; de
        # lo contrario se usa frame/FPS desde cero.
        if inicial is not None:
            encontrado = next((x for x in candidatos_esperados if x[0] == "overlay_inicial"), None)
        else:
            encontrado = None
        anclaje, esperado = encontrado or candidatos_esperados[0]
        tiempo = esperado
        fuente = ("fps_anclado_overlay_inicial" if anclaje == "overlay_inicial"
                  else "fps_grabacion")
    else:
        tiempo = None
        fuente = "sin_fuente_temporal"

    if tiempo is not None:
        tiempo = max(0.0, float(tiempo))
    return {
        "frame_index": frame,
        "tiempo_ms": None if tiempo is None else round(tiempo, 3),
        # V15.7: sólo un reloj VALIDADO cuenta como tiempo de overlay. La
        # lectura cruda se conserva aparte para mostrarla como "no coincide";
        # así el consenso nunca calibra con una lectura ya descartada.
        "tiempo_overlay_ms": actual if overlay_valido else None,
        "tiempo_overlay_leido_ms": actual,
        "tiempo_fps_ms": None if tiempo_fps is None else round(tiempo_fps, 6),
        "timestamp_inicial_ms": inicial,
        "fuente_tiempo": fuente,
        "overlay_valido": overlay_valido,
        "anclaje_tiempo": anclaje,
        "discrepancia_ms": None if discrepancia is None else round(float(discrepancia), 6),
        "advertencia": advertencia,
        "resolucion_nativa_ms": None if resolucion is None else round(resolucion, 6),
        "precision_overlay_ms": precision,
        "tolerancia_validacion_ms": round(float(tolerancia), 6),
    }


def fps_temporal_confiable(fps_grabacion: float | None, fps_archivo: float | None,
                           config: dict | None = None) -> tuple[float | None, str]:
    """Elige la tasa que define ms/cuadro y dice de dónde salió.

    Orden: ``RecXXXX fps`` del overlay; ``fps_grabacion_forzado`` de
    config.yaml; FPS del contenedor sólo si es plausible para alta velocidad.
    Un AVI que declara 8 fps de reproducción nunca se usa como tasa de
    grabación: devolvería 125 ms/cuadro. En ese caso se devuelve ``None`` y el
    tiempo sale del reloj visible o queda marcado como desconocido.
    """
    cfg = (config or cargar_config()).get("video_airbag") or {}
    rec = _numero_no_negativo(fps_grabacion)
    if rec and rec > 0:
        return float(rec), "overlay_rec"
    forzado = _numero_no_negativo(cfg.get("fps_grabacion_forzado"))
    if forzado and forzado > 0:
        return float(forzado), "config_forzado"
    archivo = _numero_no_negativo(fps_archivo)
    minimo = float(cfg.get("fps_archivo_minimo_confiable", 500.0))
    if archivo and archivo >= minimo:
        return float(archivo), "archivo"
    return None, "desconocido"


def _tiempo_coherente_con_frame(tiempo_ms, frame_index: int, fps: float,
                                timestamp_inicial_ms=None, config: dict | None = None) -> bool:
    """¿El tiempo guardado corresponde a ese cuadro con esa tasa real?"""
    valor = _numero_no_negativo(tiempo_ms)
    if valor is None:
        return False
    ref = resolver_tiempo_metadata(frame_index=frame_index, fps=fps,
                                   timestamp_actual_ms=valor,
                                   timestamp_inicial_ms=timestamp_inicial_ms, config=config)
    return bool(ref.get("overlay_valido"))


def normalizar_item_temporal_video(item: dict, config: dict | None = None,
                                   fps_caso: float | None = None) -> bool:
    """Repara en memoria metadatos temporales antiguos de un video.

    Caso principal: un resultado guardado como 8 fps/125 ms por cuadro cuyo
    propio ``overlay_texto`` contiene ``Rec5000 fps``. Devuelve ``True`` si
    modificó algo. No toca la detección espacial ni el aprendizaje.
    """
    if not isinstance(item, dict):
        return False
    cambiado = False
    fps_rec = fps_grabacion_desde_item(item)
    fuente_fps = "overlay_rec" if fps_rec else None
    if not fps_rec and fps_caso:
        # V15.7: otra cámara del MISMO ensayo leyó RecXXXX fps. Todas graban a
        # la misma tasa, así que un OCR fallido aquí no vuelve a 125 ms/cuadro.
        fps_rec, fuente_fps = float(fps_caso), "overlay_rec_otra_camara"
    if not fps_rec:
        fps_rec, fuente_fps = fps_temporal_confiable(
            None, item.get("fps_archivo") or item.get("fps"), config)
    fps_declarado = _numero_no_negativo(item.get("fps_archivo") or item.get("fps"))
    if not fps_rec and fps_declarado:
        # Sin tasa fiable no se inventa un tiempo con los FPS de reproducción
        # (8 fps → 125 ms/cuadro). Sin ningún dato de FPS no se toca nada.
        if item.get("fps_fuente") != "desconocido" and item.get("estado") == "candidato":
            item["fps_fuente"] = "desconocido"
            item["advertencia_tiempo"] = (
                "No se pudo leer la tasa real (Rec…fps) y los FPS del archivo no son de alta "
                "velocidad. El tiempo sólo se acepta desde el reloj visible.")
            overlay = _numero_no_negativo(item.get("tiempo_overlay_ms"))
            item["tiempo_ms"] = None if overlay is None else round(overlay, 1)
            item["fuente_tiempo"] = "timestamp_overlay_esquina" if overlay is not None else "sin_fuente_temporal"
            cambiado = True
    if fps_rec and fps_rec > 0:
        resol = 1000.0 / fps_rec
        for clave, valor in (
            ("fps_grabacion", float(fps_rec)),
            ("fps", float(fps_rec)),
            ("fps_fuente", fuente_fps),
            ("resolucion_nativa_ms", round(resol, 6)),
        ):
            if item.get(clave) != valor:
                item[clave] = valor
                cambiado = True

        frame_auto = item.get("frame_evento")
        try:
            frame_auto = max(0, int(frame_auto)) if frame_auto is not None else None
        except (TypeError, ValueError):
            frame_auto = None
        if frame_auto is not None:
            resuelto = resolver_tiempo_metadata(
                frame_index=frame_auto, fps=fps_rec,
                timestamp_actual_ms=item.get("tiempo_overlay_ms"),
                timestamp_inicial_ms=item.get("overlay_timestamp_inicial_ms"),
                precision_overlay_ms=item.get("precision_fuente_ms"), config=config)
            mapa = {
                "tiempo_ms": None if resuelto.get("tiempo_ms") is None else round(float(resuelto["tiempo_ms"]), 1),
                "tiempo_fps_ms": resuelto.get("tiempo_fps_ms"),
                "fuente_tiempo": resuelto.get("fuente_tiempo"),
                "discrepancia_tiempo_ms": resuelto.get("discrepancia_ms"),
                "advertencia_tiempo": resuelto.get("advertencia"),
                "overlay_validado": bool(resuelto.get("overlay_valido")),
            }
            for clave, valor in mapa.items():
                if item.get(clave) != valor:
                    item[clave] = valor
                    cambiado = True

        rev = item.get("revision_manual") or {}
        if rev.get("estado") == "confirmado" and rev.get("frame_index") is not None:
            try:
                f_rev = max(0, int(rev.get("frame_index")))
            except (TypeError, ValueError):
                f_rev = None
            # V15.7: el tiempo que el usuario confirmó NO se reescribe si es
            # coherente con su cuadro y la tasa real. Sólo se repara si es
            # inválido (negativo, vacío) o contradictorio (p.ej. 1375 ms
            # guardado con 8 fps), y se deja constancia del valor anterior.
            if f_rev is not None and not _tiempo_coherente_con_frame(
                    rev.get("tiempo_ms"), f_rev, fps_rec,
                    item.get("overlay_timestamp_inicial_ms"), config):
                r_rev = resolver_tiempo_metadata(
                    frame_index=f_rev, fps=fps_rec,
                    timestamp_inicial_ms=item.get("overlay_timestamp_inicial_ms"), config=config)
                nuevo = r_rev.get("tiempo_ms")
                if nuevo is not None:
                    rev = dict(rev)
                    rev.setdefault("tiempo_original_ms", rev.get("tiempo_ms"))
                    rev["tiempo_ms"] = round(float(nuevo), 1)
                    rev["tiempo_reparado"] = True
                    rev["motivo_reparacion"] = (
                        f"El tiempo guardado ({rev.get('tiempo_original_ms')} ms) no correspondía al "
                        f"cuadro {f_rev} a {fps_rec:g} fps; se recalculó como {rev['tiempo_ms']} ms.")
                    item["revision_manual"] = rev
                    cambiado = True
    return cambiado


FUENTES_FPS_REALES = {"overlay_rec", "overlay_rec_otra_camara", "config_forzado", "archivo",
                      "reloj_overlay"}


def fps_real_item(item: dict | None) -> float | None:
    """FPS de grabación de un video ya normalizado, o None si no es fiable."""
    item = item or {}
    rec = fps_grabacion_desde_item(item)
    if rec:
        return float(rec)
    if item.get("fps_fuente") in FUENTES_FPS_REALES:
        valor = _numero_no_negativo(item.get("fps"))
        if valor and valor > 0:
            return float(valor)
    return None


def fps_grabacion_caso(items: Iterable[dict]) -> float | None:
    """Tasa RecXXXX leída en cualquier cámara del ensayo (la más repetida)."""
    valores = [fps_grabacion_desde_item(x) for x in items if isinstance(x, dict)]
    valores = [v for v in valores if v]
    if not valores:
        return None
    return max(set(valores), key=valores.count)


def normalizar_videos_caso(items: Iterable[dict], config: dict | None = None) -> bool:
    """Normaliza todas las cámaras de un ensayo compartiendo la tasa real."""
    items = [x for x in items if isinstance(x, dict)]
    fps_caso = fps_grabacion_caso(items)
    cambiado = False
    for item in items:
        cambiado = normalizar_item_temporal_video(item, config, fps_caso=fps_caso) or cambiado
    return cambiado

_cache_reloj: dict[tuple, dict] = {}
_CACHE_RELOJ_MAX = 4096


def leer_timestamp_esquina_frame(ruta_video: str | Path, frame_index: int,
                                  config: dict | None = None) -> dict:
    """OCR sólo del reloj superior derecho de un frame concreto.

    No mira el pie del video y por tanto no puede confundir el ``0ms`` fijo de
    la franja inferior con el reloj del cuadro actual. V15.7.1: cada lectura
    correcta se recuerda por (video, cuadro); al ir y volver cuadro a cuadro en
    el revisor no se repite EasyOCR ni se reabre el video.
    """
    ruta = Path(ruta_video)
    try:
        clave = (firma_video.firma_contenido(ruta), max(0, int(frame_index or 0)),
                 bool(_cfg(config).get("leer_timestamp_overlay", True)))
    except OSError:
        clave = None
    if clave is not None and clave in _cache_reloj:
        return dict(_cache_reloj[clave])
    resultado = _leer_timestamp_esquina_frame_sin_cache(ruta, frame_index, config)
    if clave is not None and resultado.get("error") is None:
        if len(_cache_reloj) >= _CACHE_RELOJ_MAX:
            _cache_reloj.pop(next(iter(_cache_reloj)))
        _cache_reloj[clave] = dict(resultado)
    return resultado


def _leer_timestamp_esquina_frame_sin_cache(ruta: Path, frame_index: int,
                                            config: dict | None = None) -> dict:
    cap = cv2.VideoCapture(str(ruta))
    try:
        if not cap.isOpened():
            return {"timestamp_ms": None, "precision_ms": None, "texto": "", "error": "video_no_abierto"}
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frame = max(0, int(frame_index or 0))
        if total:
            frame = min(frame, max(0, total - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, imagen = cap.read()
        if not ok or imagen is None:
            return {"timestamp_ms": None, "precision_ms": None, "texto": "", "error": "frame_no_leido"}
    finally:
        cap.release()

    cfg = _cfg(config)
    if not cfg.get("leer_timestamp_overlay", True):
        return {"timestamp_ms": None, "precision_ms": None, "texto": "", "error": None}
    h, w = imagen.shape[:2]
    x1 = max(0, int(round(w * 0.72)))
    y2 = max(1, int(round(h * 0.10)))
    esquina = imagen[:y2, x1:]
    lecturas: list[str] = []
    try:
        from ocr_engine import obtener_motor
        motor, _ = obtener_motor(config)
        esc = esquina
        if esc.size and esc.shape[1] < 700:
            escala = min(4.0, 700.0 / max(1, esc.shape[1]))
            esc = cv2.resize(esc, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
        items = motor.leer_texto_completo(esc) if esc.size else []
        lecturas = [str(x.get("texto") or "").strip() for x in items if x.get("texto")]
        valor, precision = _parsear_numero_timestamp_esquina(lecturas)
        # Un '-' espurio del OCR no debe convertirse jamás en apertura negativa.
        if _numero_no_negativo(valor) is None:
            valor = None
        return {"timestamp_ms": valor, "precision_ms": precision,
                "texto": " | ".join(lecturas), "error": None}
    except Exception as exc:
        return {"timestamp_ms": None, "precision_ms": None, "texto": " | ".join(lecturas),
                "error": f"{type(exc).__name__}: {exc}"}


def resolver_tiempo_frame(ruta_video: str | Path, frame_index: int, *,
                           fps_preferido: float | None = None,
                           timestamp_inicial_ms: float | None = None,
                           config: dict | None = None) -> dict:
    """Lee el reloj del frame solicitado y devuelve el tiempo autoritativo."""
    ruta = Path(ruta_video)
    fps_archivo = None
    cap = cv2.VideoCapture(str(ruta))
    try:
        if cap.isOpened():
            fps_archivo = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or None
    finally:
        cap.release()
    # V15.7: nunca caer a los 8 fps de reproducción del AVI.
    fps, fps_fuente = fps_temporal_confiable(fps_preferido, fps_archivo, config)
    lectura = leer_timestamp_esquina_frame(ruta, frame_index, config)
    resuelto = resolver_tiempo_metadata(
        frame_index=frame_index, fps=fps,
        timestamp_actual_ms=lectura.get("timestamp_ms"),
        timestamp_inicial_ms=timestamp_inicial_ms,
        precision_overlay_ms=lectura.get("precision_ms"), config=config,
    )
    resuelto.update({
        "fps": fps,
        "fps_fuente": fps_fuente,
        "fps_archivo": fps_archivo,
        "overlay_texto_esquina": lectura.get("texto", ""),
        "overlay_error": lectura.get("error"),
    })
    return resuelto

def _ajustar_cfg_con_perfil_evento(cfg: dict, perfil: dict | None) -> dict:
    """Ajusta sólo hacia mayor sensibilidad usando ejemplos confirmados.

    El aprendizaje nunca vuelve el detector más estricto que la configuración
    del usuario. Con al menos N ejemplos, puede bajar moderadamente los umbrales
    si las aperturas reales de esa cámara nacen con componentes aún más pequeños.
    """
    salida = dict(cfg)
    perfil = perfil or {}
    minimo = max(1, int(cfg.get("min_ejemplos_perfil_evento", 3)))
    if not bool(cfg.get("usar_perfil_evento_aprendido", True)) or int(perfil.get("ejemplos") or 0) < minimo:
        return salida
    pares = (
        ("min_fraccion_blanco_nuevo", "mediana_fraccion_blanco"),
        ("min_fraccion_componente_blanco", "mediana_fraccion_componente"),
    )
    for clave_cfg, clave_perfil in pares:
        try:
            actual = float(cfg.get(clave_cfg))
            aprendido = float(perfil.get(clave_perfil))
        except (TypeError, ValueError):
            continue
        if actual <= 0 or aprendido <= 0 or not math.isfinite(aprendido):
            continue
        objetivo = aprendido * 0.55
        # Evita que un ejemplo atípico vuelva el detector excesivamente sensible.
        suelo = actual * 0.35
        salida[clave_cfg] = max(suelo, min(actual, objetivo))
    return salida


def _baseline_compensado(roi: np.ndarray, baseline: np.ndarray, cfg: dict) -> np.ndarray:
    """Deforma el baseline para que coincida con el cuadro actual.

    El flujo óptico explica desplazamientos suaves (tablero que se hincha,
    brillos que se corren). La tela que asoma es material que no existía en el
    baseline, así que ningún desplazamiento razonable la reproduce y queda en
    el residuo.
    """
    h, w = roi.shape[:2]
    if h < 8 or w < 8:
        return baseline
    ancho_flujo = max(32, int(cfg.get("flujo_ancho_max", 480)))
    escala = min(1.0, ancho_flujo / float(w))
    if escala < 1.0:
        tam = (max(8, int(round(w * escala))), max(8, int(round(h * escala))))
        a = cv2.resize(roi, tam, interpolation=cv2.INTER_AREA)
        b = cv2.resize(baseline, tam, interpolation=cv2.INTER_AREA)
    else:
        a, b = roi, baseline
    # flujo[y, x] indica dónde está en el baseline el píxel (x, y) del cuadro actual.
    flujo = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 21, 3, 5, 1.1, 0)
    tope = float(cfg.get("flujo_max_px", 10.0)) * escala
    np.clip(flujo, -tope, tope, out=flujo)
    if escala < 1.0:
        flujo = cv2.resize(flujo, (w, h), interpolation=cv2.INTER_LINEAR) / escala
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    return cv2.remap(baseline, xx + flujo[..., 0], yy + flujo[..., 1],
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _metricas_primer_blanco(roi: np.ndarray, baseline: np.ndarray, cfg: dict,
                            ruido: dict | None = None) -> dict:
    """Mide un contorno de ruptura NUEVO respecto al baseline nativo.

    La diferencia de intensidad sola también detecta un tablero que se hincha.
    Exigimos residuo tras compensar ese movimiento y una discontinuidad local
    nueva. Se conserva un indicio de un solo píxel, claro u oscuro, pero sólo
    cuadros posteriores con crecimiento coherente pueden corroborarlo. No se
    desenfoca ni se hace apertura morfológica sobre la señal de ruptura.

    Estas reglas son heurísticas: un brillo, sombra o artefacto de compresión
    aún puede parecer una fisura. No sustituyen una revisión de vídeos reales.
    """
    actual = roi.astype(np.int16)
    base = baseline.astype(np.int16)
    delta = actual - base
    delta = delta - int(round(float(np.median(delta))))
    lum = int(cfg.get("umbral_luminancia_blanco", 135))
    inc = int(cfg.get("umbral_incremento_blanco", 18))
    mascara_brillo = (actual >= lum) & (delta >= inc)
    mascara_oscura = ((actual <= int(cfg.get("umbral_luminancia_grieta", 120))) &
                      (delta <= -inc))
    total = int(mascara_brillo.size)
    pixeles_sin_compensar = int(np.count_nonzero(mascara_brillo))

    min_pix = max(3, int(round(total * float(cfg.get("min_fraccion_blanco_nuevo", 0.00003)))))
    min_comp = max(2, int(round(total * float(cfg.get("min_fraccion_componente_blanco", 0.000015)))))
    if ruido:
        factor = max(1.0, float(cfg.get("ruido_factor_pixeles", 3.0)))
        margen = max(0, int(cfg.get("ruido_margen_pixeles", 3)))
        min_pix = max(min_pix, int(math.ceil(float(ruido.get("pixeles") or 0) * factor)) + margen)
        min_comp = max(min_comp, int(math.ceil(float(ruido.get("componente") or 0) * factor)) + margen)
    min_pix_debil = max(1, int(cfg.get("min_pixeles_indicio", 1)))
    min_comp_debil = 1
    # Los mínimos fuertes sí dependen del ruido/área. El indicio no: hacerlo
    # relativo a toda la imagen volvería a borrar una primera fisura de 1 px.

    compensado = False
    deformado = base
    residuo = delta
    if (bool(cfg.get("compensar_movimiento", True)) and
            (pixeles_sin_compensar >= min_pix_debil or np.any(mascara_oscura))):
        deformado = _baseline_compensado(roi, baseline, cfg).astype(np.int16)
        residuo = actual - deformado
        residuo = residuo - int(round(float(np.median(residuo))))
        compensado = True

    # Centro menos sus cuatro vecinos: retiene íntegra la señal de 1 px.
    # Un abombamiento/iluminación suave no crea esta discontinuidad, aunque
    # supere los umbrales de intensidad y tenga mucha área.
    kernel = np.array([[0, -0.25, 0], [-0.25, 1, -0.25],
                       [0, -0.25, 0]], dtype=np.float32)
    contraste_actual = np.abs(cv2.filter2D(actual.astype(np.float32), -1, kernel,
                                         borderType=cv2.BORDER_REPLICATE))
    contraste_base = np.abs(cv2.filter2D(deformado.astype(np.float32), -1, kernel,
                                       borderType=cv2.BORDER_REPLICATE))
    discontinuidad = (contraste_actual - contraste_base >=
                      float(cfg.get("umbral_discontinuidad_nueva", 6.0)))
    residuo_min = int(cfg.get("residuo_min_compensado", 18))
    blanco = mascara_brillo & (residuo >= residuo_min) & discontinuidad
    grieta = mascara_oscura & (residuo <= -residuo_min) & discontinuidad
    mascara = (blanco | grieta).astype(np.uint8)
    pixeles = int(np.count_nonzero(blanco))
    pixeles_grieta = int(np.count_nonzero(grieta))
    pixeles_ruptura = int(np.count_nonzero(mascara))

    mayor = 0
    bbox = None
    bbox_norm = None
    centro = None
    componentes = []
    componentes_truncados = False
    if pixeles_ruptura:
        n, etiquetas, stats, centroides = cv2.connectedComponentsWithStats(mascara, connectivity=8)
        if n > 1:
            orden = np.argsort(-stats[1:, cv2.CC_STAT_AREA], kind="stable") + 1
            limite_componentes = max(1, int(cfg.get("max_componentes_indicio", 64)))
            componentes_truncados = len(orden) > limite_componentes
            for ci in orden[:limite_componentes]:
                cx, cy, cw, ch, area = [int(v) for v in stats[ci]]
                pertenece = etiquetas[cy:cy + ch, cx:cx + cw] == ci
                blancos_ci = int(np.count_nonzero(blanco[cy:cy + ch, cx:cx + cw] & pertenece))
                componentes.append({
                    "area": area, "blancos": blancos_ci, "grieta": area - blancos_ci,
                    "bbox": [cx, cy, cx + cw, cy + ch],
                    "bbox_norm": [cx / roi.shape[1], cy / roi.shape[0],
                                  (cx + cw) / roi.shape[1], (cy + ch) / roi.shape[0]],
                    "centro_norm": [float(centroides[ci][0]) / roi.shape[1],
                                    float(centroides[ci][1]) / roi.shape[0]],
                })
            idx = int(orden[0])
            mayor = int(stats[idx, cv2.CC_STAT_AREA])
            x, y, w, h = [int(v) for v in stats[idx, :4]]
            bbox = [x, y, x + w, y + h]
            if total and roi.shape[1] and roi.shape[0]:
                centro = [round(float(centroides[idx][0]) / roi.shape[1], 6),
                          round(float(centroides[idx][1]) / roi.shape[0], 6)]
                bbox_norm = [round(x / roi.shape[1], 6), round(y / roi.shape[0], 6),
                             round((x + w) / roi.shape[1], 6), round((y + h) / roi.shape[0], 6)]
    detectado = pixeles_ruptura >= min_pix and mayor >= min_comp
    evidencia_debil = pixeles_ruptura >= min_pix_debil and mayor >= min_comp_debil

    # La tela que emerge crea contornos nuevos aun cuando todavía no ocupa gran área.
    gris_actual = np.clip(actual, 0, 255).astype(np.uint8)
    gris_base = np.clip(base, 0, 255).astype(np.uint8)
    e0 = cv2.Canny(gris_base, 45, 120)
    e1 = cv2.Canny(gris_actual, 45, 120)
    e0d = cv2.dilate((e0 > 0).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1)
    bordes_nuevos = int(np.count_nonzero((e1 > 0) & (e0d == 0)))
    return {
        "pixeles_blanco_nuevo": pixeles,
        "pixeles_grieta_nueva": pixeles_grieta,
        "pixeles_ruptura": pixeles_ruptura,
        "componente_ruptura_px": mayor,
        "roi_ancho": int(roi.shape[1]), "roi_alto": int(roi.shape[0]),
        "radio_indicio_px": float(cfg.get("radio_indicio_px", 3.0)),
        "componentes_indicio": componentes,
        "componentes_indicio_truncados": componentes_truncados,
        "pixeles_sin_compensar": pixeles_sin_compensar,
        "compensado": compensado,
        "fraccion_blanco_nuevo": (pixeles / total if total else 0.0),
        "componente_blanco_px": mayor,
        "fraccion_componente_blanco": (mayor / total if total else 0.0),
        "bbox_componente": bbox,
        "bbox_componente_norm": bbox_norm,
        "centro_componente_norm": centro,
        "bordes_nuevos_px": bordes_nuevos,
        "fraccion_borde_nuevo": (bordes_nuevos / total if total else 0.0),
        "min_pixeles_blanco": min_pix,
        "min_componente_blanco": min_comp,
        "min_pixeles_debil": min_pix_debil,
        "min_componente_debil": min_comp_debil,
        "evidencia_debil": bool(evidencia_debil),
        "detectado": bool(detectado),
    }


def _ruido_baseline(rois_base: list[np.ndarray], cfg: dict) -> dict:
    """Nivel de "falsa evidencia" que produce el propio sensor sin evento.

    Cada cuadro del baseline se compara con el baseline formado por los demás
    (leave-one-out). Lo que aparezca ahí es ruido, compresión o parpadeo.
    """
    pix, comp, scores = [0], [0], [0.0]
    if len(rois_base) >= 2:
        cfg_crudo = dict(cfg)
        cfg_crudo["compensar_movimiento"] = False
        for i, roi in enumerate(rois_base):
            otros = [r for j, r in enumerate(rois_base) if j != i]
            ref = np.median(np.stack(otros, axis=0), axis=0).astype(np.uint8)
            actual = roi.astype(np.uint8)
            m = _metricas_primer_blanco(actual, ref, cfg_crudo)
            pix.append(int(m.get("pixeles_ruptura", m["pixeles_blanco_nuevo"])))
            comp.append(int(m["componente_blanco_px"]))
            diff = cv2.absdiff(actual, ref)
            scores.append(float(np.mean(diff)) + 70.0 * float(np.mean(cv2.subtract(actual, ref) > 28)))
    return {"pixeles": max(pix), "componente": max(comp), "score_max": max(scores),
            "cuadros": len(rois_base)}


def _cerca(a: dict, b: dict, margen: float = 0.08) -> bool:
    """¿La evidencia ``a`` está en el mismo sitio que la componente ``b``?"""
    ca = a.get("centro_componente_norm")
    bb = b.get("bbox_componente_norm")
    if not ca:
        return False
    # Un ruido puntual situado a decenas de píxeles del nacimiento no debe
    # adelantar el evento sólo por caer dentro del antiguo margen del 8 %.
    if int(a.get("componente_ruptura_px", a.get("componente_blanco_px", 0)) or 0) <= 2:
        ancho, alto = int(a.get("roi_ancho") or 0), int(a.get("roi_alto") or 0)
        if ancho and alto and bb:
            radio = max(0.0, float(a.get("radio_indicio_px", 3.0)))
            return (bb[0] - radio / ancho <= ca[0] <= bb[2] + radio / ancho and
                    bb[1] - radio / alto <= ca[1] <= bb[3] + radio / alto)
    if bb:
        return (bb[0] - margen <= ca[0] <= bb[2] + margen and
                bb[1] - margen <= ca[1] <= bb[3] + margen)
    cb = b.get("centro_componente_norm")
    return bool(cb) and math.hypot(ca[0] - cb[0], ca[1] - cb[1]) <= 0.12


def _trayectoria_coherente(metricas: list[dict], inicio: int, fin: int) -> bool:
    """Descarta destellos que saltan de posición entre cuadros."""
    centros = [metricas[i].get("centro_componente_norm") for i in range(inicio, fin + 1)
               if metricas[i].get("evidencia_debil") and metricas[i].get("centro_componente_norm")]
    if len(centros) < 2:
        return True
    for a, b in zip(centros, centros[1:]):
        distancia = math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))
        if distancia > 0.28:
            return False
    return True


def _vista_componente(metrica: dict, componente: dict) -> dict:
    """Evidencia de una misma fisura; no suma ruidos de otras posiciones."""
    salida = dict(metrica)
    area = int(componente["area"])
    total = max(1, int(metrica.get("roi_ancho") or 1) * int(metrica.get("roi_alto") or 1))
    salida.update({
        "pixeles_ruptura": area, "componente_ruptura_px": area,
        "pixeles_blanco_nuevo": int(componente["blancos"]),
        "pixeles_grieta_nueva": int(componente["grieta"]),
        # Nombre legado preservado para consumidores anteriores.
        "componente_blanco_px": area,
        "fraccion_blanco_nuevo": int(componente["blancos"]) / total,
        "fraccion_componente_blanco": area / total,
        "bbox_componente": componente["bbox"],
        "bbox_componente_norm": componente["bbox_norm"],
        "centro_componente_norm": componente["centro_norm"],
        "detectado": area >= max(int(metrica.get("min_pixeles_blanco") or 1),
                                  int(metrica.get("min_componente_blanco") or 1)),
        "evidencia_debil": area >= max(int(metrica.get("min_pixeles_debil") or 1),
                                        int(metrica.get("min_componente_debil") or 1)),
    })
    return salida


def _componente_cercano(metrica: dict, siguiente: dict) -> dict | None:
    """Conserva un indicio real aunque otro píxel caliente sea más grande."""
    componentes = metrica.get("componentes_indicio")
    if componentes is None:
        return metrica if metrica.get("evidencia_debil") and _cerca(metrica, siguiente) else None
    bb = siguiente.get("bbox_componente_norm")
    if not bb:
        return None
    ancho, alto = int(metrica.get("roi_ancho") or 1), int(metrica.get("roi_alto") or 1)
    radio = max(0.0, float(metrica.get("radio_indicio_px", 3.0)))
    candidatos = []
    for comp in componentes:
        cx, cy = comp["centro_norm"]
        if (bb[0] - radio / ancho <= cx <= bb[2] + radio / ancho and
                bb[1] - radio / alto <= cy <= bb[3] + radio / alto):
            vista = _vista_componente(metrica, comp)
            if vista["evidencia_debil"]:
                candidatos.append(vista)
    if not candidatos:
        return None
    centro = siguiente.get("centro_componente_norm") or [(bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2]
    return min(candidatos, key=lambda m: math.hypot(
        (m["centro_componente_norm"][0] - centro[0]) * ancho,
        (m["centro_componente_norm"][1] - centro[1]) * alto))


def _evaluar_confirmacion(metricas: list[dict], scores: list[float], umbral: float,
                          nbase: int, cfg: dict, confirmacion: int) -> dict | None:
    """Valida un cuadro de evidencia fuerte y retrocede al primer indicio.

    V15.7: el inicio es el principio de la racha continua de evidencia que
    desemboca en la confirmación, en la misma posición, precedida por
    ``frames_previos_limpios`` cuadros sin evidencia. Si la racha llega hasta
    el baseline sin cuadros limpios, se marca para revisión en lugar de
    fingir que ese cuadro es el nacimiento.
    """
    total = len(metricas)
    if confirmacion < nbase or confirmacion >= total:
        return None
    ventana = max(2, int(cfg.get("ventana_confirmacion_frames", 5)))
    min_frames = max(2, int(cfg.get("min_frames_confirmacion", 2)))
    ratio_min = max(1.05, float(cfg.get("crecimiento_ratio_min", 1.8)))
    mult_comp = max(1.0, float(cfg.get("fuerte_multiplicador_componente", 2.2)))
    mult_pix = max(1.0, float(cfg.get("fuerte_multiplicador_pixeles", 1.7)))
    max_back = max(1, int(cfg.get("backtracking_max_frames", 7)))
    limpios_req = max(1, int(cfg.get("frames_previos_limpios", 2)))

    def es_fuerte(m: dict) -> bool:
        return bool(m.get("detectado")) and (
            float(m.get("componente_blanco_px") or 0) >= float(m.get("min_componente_blanco") or 1) * mult_comp
            or float(m.get("pixeles_ruptura", m.get("pixeles_blanco_nuevo")) or 0) >=
            float(m.get("min_pixeles_blanco") or 1) * mult_pix)

    mconf = metricas[confirmacion]
    if mconf.get("componentes_indicio"):
        mconf = _vista_componente(mconf, mconf["componentes_indicio"][0])
    if not es_fuerte(mconf):
        return None
    post_fin = min(total - 1, confirmacion + ventana - 1)
    post = metricas[confirmacion:post_fin + 1]
    post_cercano = [_componente_cercano(m, mconf) for m in post]
    if len(post) < min_frames or not all(m is not None for m in post_cercano[:min_frames]):
        return None

    inicio = confirmacion
    metrica_inicio = mconf
    trayectoria = [mconf]
    huecos = 0
    antes_limpio = False
    limite = (nbase if cfg.get("retroceso_hasta_indicio_continuo", True)
              else max(nbase, confirmacion - max_back))
    k = confirmacion - 1
    while k >= limite:
        mk = metricas[k]
        cercana = _componente_cercano(mk, metrica_inicio)
        if not huecos and cercana is not None:
            inicio = k
            metrica_inicio = cercana
            trayectoria.append(cercana)
            huecos = 0
        else:
            huecos += 1
            if huecos >= limpios_req:
                antes_limpio = all(_componente_cercano(metricas[j], metrica_inicio) is None
                                   for j in range(k, min(total, k + limpios_req)))
                break
        k -= 1
    borde_baseline = (not antes_limpio) and limite == nbase and inicio - nbase < limpios_req

    area0 = max(1.0, float(metrica_inicio.get("componente_blanco_px") or 0))
    max_area = max(float(m.get("componente_blanco_px") or 0)
                   for m in trayectoria + [m for m in post_cercano if m is not None])
    crecimiento = max_area / area0
    # Una punta mínima sólo se acepta si después crece; si el primer cuadro ya
    # es fuerte basta con la persistencia.
    if inicio != confirmacion and crecimiento < ratio_min and not es_fuerte(metrica_inicio):
        return None
    if not _trayectoria_coherente(trayectoria, 0, len(trayectoria) - 1):
        return None
    return {
        "frame_inicio": int(inicio),
        "frame_confirmacion": int(confirmacion),
        "retroceso_frames": int(confirmacion - inicio),
        "crecimiento_ratio": round(float(crecimiento), 4),
        "max_componente_px": int(round(max_area)),
        "antes_limpio": bool(antes_limpio),
        "inicio_en_borde_baseline": bool(borde_baseline),
        "metodo": "crecimiento_backtracking",
        "indicio_un_pixel": int(metrica_inicio.get("pixeles_ruptura") or
                                 metrica_inicio.get("pixeles_blanco_nuevo") or 0) == 1,
        "metricas_inicio": metrica_inicio,
    }


def _buscar_inicio_confirmado(metricas: list[dict], scores: list[float], umbral: float,
                               nbase: int, cfg: dict) -> dict | None:
    """Primer evento confirmado del video (recorrido completo)."""
    for confirmacion in range(nbase, len(metricas)):
        resultado = _evaluar_confirmacion(metricas, scores, umbral, nbase, cfg, confirmacion)
        if resultado:
            return resultado
    return None


def _puntaje_apertura(metricas: dict, score_diff: float, umbral: float,
                      crecimiento: float, zona: dict | None, perfil: dict | None) -> float:
    pix_ratio = float(metricas.get("pixeles_blanco_nuevo") or 0) / max(1.0, float(metricas.get("min_pixeles_debil") or 1))
    comp_ratio = float(metricas.get("componente_blanco_px") or 0) / max(1.0, float(metricas.get("min_componente_debil") or 1))
    blanco = min(1.0, pix_ratio / 3.0)
    componente = min(1.0, comp_ratio / 3.0)
    crec = min(1.0, max(0.0, crecimiento - 1.0) / 2.0)
    diff = min(1.0, max(0.0, score_diff) / max(umbral, 1e-6))
    borde = min(1.0, float(metricas.get("fraccion_borde_nuevo") or 0.0) / 0.003)
    zona_score = float((zona or {}).get("confianza") or 0.0) if (zona or {}).get("activa") else 0.45
    aprendido = 1.0 if int((perfil or {}).get("ejemplos") or 0) >= 3 else 0.0
    score = (0.25 * blanco + 0.25 * componente + 0.18 * crec + 0.12 * diff +
             0.08 * borde + 0.09 * zona_score + 0.03 * aprendido)
    return max(0.0, min(0.99, score))


def analizar_video(ruta_video: str | Path, config: dict | None = None, *, usar_cache: bool = True) -> dict:
    """Detecta el primer cuadro visible del airbag y lo valida con cuadros futuros."""
    ruta = Path(ruta_video).resolve()
    cfg = _cfg(config)
    firma = _firma(ruta)
    from aprendizaje_video_airbag import version_aprendizajes
    # Sólo las zonas/ejemplos que pueden afectar a ESTE video invalidan su caché.
    version_zonas = version_aprendizajes(ruta)
    cache = _leer_json(RUTA_CACHE, {"version": 4, "items": {}})
    cache_key = hashlib.sha256(json.dumps(
        {"firma": firma, "cfg": cfg, "algoritmo": ALGORITMO_VERSION, "zonas": version_zonas},
        sort_keys=True, default=str).encode()).hexdigest()
    if usar_cache and isinstance(cache, dict):
        item = (cache.get("items") or {}).get(cache_key)
        if isinstance(item, dict):
            item = dict(item)
            # La firma es por contenido: el caché puede venir de otra carpeta.
            item["ruta"], item["nombre"] = str(ruta), ruta.name
            normalizar_item_temporal_video(item, config)
            item["desde_cache"] = True
            rev = revision_video(ruta)
            if rev:
                item["revision_manual"] = rev
                normalizar_item_temporal_video(item, config)
            return item

    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        return {"ruta": str(ruta), "nombre": ruta.name, "estado": "error",
                "error": "OpenCV no pudo abrir el video.", "firma": firma}
    fps_archivo = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frames_decl = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    max_ancho = int(cfg.get("max_ancho_analisis", 960))
    margen = float(cfg.get("margen_vertical_deteccion", 0.12))

    ok_ref, primer_frame_ref = cap.read()
    primer_frame = primer_frame_ref if ok_ref and primer_frame_ref is not None else None
    overlay_inicial = (_leer_overlay(primer_frame, config) if primer_frame is not None
                       else {"texto": "", "tiempos_ms": [], "fps_grabacion": [],
                             "timestamp_esquina_ms": None, "precision_timestamp_esquina_ms": None,
                             "texto_esquina": "", "error": None})
    fps_rec_inicial = (overlay_inicial.get("fps_grabacion") or [None])[0]
    fps_temporal_pre = float(fps_rec_inicial) if fps_rec_inicial else fps_archivo
    resolucion_pre = (1000.0 / fps_temporal_pre) if fps_temporal_pre > 0 else None

    if primer_frame is not None:
        from aprendizaje_video_airbag import seleccionar_zona_aprendida, perfil_evento_aprendido
        zona_aprendida = seleccionar_zona_aprendida(ruta, primer_frame, {"video_airbag": cfg})
        perfil_evento = perfil_evento_aprendido(zona_aprendida.get("tipo_camara"))
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    else:
        zona_aprendida = {"activa": False, "bbox_norm": None, "fuente": "sin_frame_referencia",
                          "tipo_camara": None, "confianza": 0.0, "total_aprendizajes": 0}
        perfil_evento = {"tipo_camara": None, "ejemplos": 0}
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    cfg_det = _ajustar_cfg_con_perfil_evento(cfg, perfil_evento)

    # Baseline temporal: unos pocos cuadros iniciales, siempre antes de la
    # apertura. Con la tasa real conocida se acota también por tiempo.
    nbase_min = max(2, int(cfg.get("frames_baseline_min", 3)))
    nbase_max = max(nbase_min, int(cfg.get("frames_baseline_max", 6)))
    objetivo_ms = max(0.1, float(cfg.get("baseline_duracion_objetivo_ms", 0.6)))
    # Misma regla de tasa real que el resto del módulo (Rec…fps, forzado en
    # config.yaml o contenedor plausible); nunca los 8 fps de reproducción.
    fps_baseline, _ = fps_temporal_confiable(fps_rec_inicial, fps_archivo, {"video_airbag": cfg})
    if fps_baseline:
        estimado = int(round(fps_baseline * objetivo_ms / 1000.0))
    else:
        estimado = nbase_min
    nbase_obj = max(nbase_min, min(nbase_max, max(2, estimado)))
    if fps_baseline:
        tope_ms = max(0.1, float(cfg.get("baseline_max_ms", 1.0)))
        nbase_obj = min(nbase_obj, max(2, int(float(fps_baseline) * tope_ms / 1000.0)))

    ventana_conf = max(2, int(cfg_det.get("ventana_confirmacion_frames", 5)))
    max_back = max(1, int(cfg_det.get("backtracking_max_frames", 7)))
    detener = bool(cfg.get("detener_tras_confirmacion", True))
    # Cuadros originales recientes: el candidato se toma de aquí y no por seek,
    # que en algunos códecs cae en otro cuadro y desincroniza el overlay.
    recientes: deque[tuple[int, np.ndarray]] = deque(maxlen=max_back + ventana_conf + 1)

    frames_base: list[np.ndarray] = []
    scores: list[float] = []
    metricas_blanco: list[dict] = []
    indice = 0
    baseline = None
    ruido_base: dict = {}
    umbral = float(cfg.get("umbral_diff_min", 6.0))
    confirmacion = None
    detenido_en = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        recientes.append((indice, frame))
        gris = _redimensionar_gris(
            frame, max(ancho, frame.shape[1]) if cfg.get("analisis_resolucion_nativa", True) else max_ancho)
        roi = _roi_deteccion_aprendida(gris, zona_aprendida, margen)
        if indice < nbase_obj:
            frames_base.append(roi.astype(np.float32))
            scores.append(0.0)
            metricas_blanco.append({
                "detectado": False, "evidencia_debil": False,
                "pixeles_blanco_nuevo": 0, "fraccion_blanco_nuevo": 0.0,
                "componente_blanco_px": 0, "fraccion_componente_blanco": 0.0,
                "fraccion_borde_nuevo": 0.0, "centro_componente_norm": None,
                "bbox_componente_norm": None,
            })
        else:
            if baseline is None:
                baseline = np.median(np.stack(frames_base, axis=0), axis=0).astype(np.uint8)
                # El ruido se mide sólo con cuadros anteriores a cualquier evento.
                ruido_base = _ruido_baseline(frames_base, cfg_det)
                umbral = max(umbral, 2.0 * float(ruido_base.get("score_max") or 0.0))
            diff = cv2.absdiff(roi, baseline)
            diff_mean = float(np.mean(diff))
            delta_claro = cv2.subtract(roi, baseline)
            frac_clara = float(np.mean(delta_claro > 28))
            score = diff_mean + 70.0 * frac_clara
            scores.append(score)
            metricas_blanco.append(_metricas_primer_blanco(roi, baseline, cfg_det, ruido_base))
            # Evaluación en línea: cuando la ventana posterior de un posible
            # cuadro fuerte ya está completa, se decide y se deja de leer.
            if detener:
                c = indice - (ventana_conf - 1)
                if c >= nbase_obj:
                    confirmacion = _evaluar_confirmacion(metricas_blanco, scores, umbral,
                                                         nbase_obj, cfg_det, c)
                    if confirmacion:
                        detenido_en = indice
                        indice += 1
                        break
        indice += 1
    cap.release()
    frames_leidos = len(scores)
    total_frames = max(frames_leidos, frames_decl) if detenido_en is not None else frames_leidos
    if frames_leidos <= nbase_obj:
        return {"ruta": str(ruta), "nombre": ruta.name, "estado": "error",
                "error": "El video contiene muy pocos cuadros para analizar.", "firma": firma,
                "fps": fps_temporal_pre, "fps_archivo": fps_archivo, "total_frames": total_frames,
                "zona_deteccion": zona_aprendida, "baseline_frames": nbase_obj}

    if confirmacion is None:
        confirmacion = _buscar_inicio_confirmado(metricas_blanco, scores, umbral, nbase_obj, cfg_det)
    candidato = confirmacion.get("frame_inicio") if confirmacion else None
    tipo_deteccion = "primer_blanco_nuevo" if candidato is not None else None

    # Fallback conservador V15.2: si no hubo crecimiento cuantificable, acepta
    # una aparición normal sólo cuando persiste de manera consecutiva.
    persistencia = max(1, int(cfg.get("persistencia_frames", 2)))
    if candidato is None and bool(cfg.get("permitir_persistencia_sin_crecimiento", False)):
        for i in range(nbase_obj, frames_leidos - persistencia + 1):
            if not metricas_blanco[i].get("detectado"):
                continue
            if all(metricas_blanco[j].get("detectado") for j in range(i, i + persistencia)):
                candidato = i
                confirmacion = {
                    "frame_inicio": i, "frame_confirmacion": i + persistencia - 1,
                    "retroceso_frames": persistencia - 1, "crecimiento_ratio": 1.0,
                    "max_componente_px": max(int(metricas_blanco[j].get("componente_blanco_px") or 0)
                                              for j in range(i, i + persistencia)),
                    "metodo": "persistencia_sin_crecimiento",
                }
                tipo_deteccion = "primer_blanco_nuevo"
                break

    if candidato is None and bool(cfg.get("rescate_cambio_general", False)):
        for i in range(nbase_obj, frames_leidos - persistencia + 1):
            if all(scores[j] >= umbral for j in range(i, i + persistencia)):
                candidato = i
                confirmacion = {"frame_inicio": i, "frame_confirmacion": i + persistencia - 1,
                                "retroceso_frames": persistencia - 1, "crecimiento_ratio": 1.0,
                                "metodo": "cambio_general"}
                tipo_deteccion = "cambio_general"
                break
    if candidato is None and bool(cfg.get("rescate_cambio_general", False)):
        deltas = [(scores[i] - scores[i - 1], i) for i in range(nbase_obj + 1, frames_leidos)]
        salto, pos = max(deltas, default=(0.0, nbase_obj))
        if salto >= max(3.0, umbral * 0.35):
            candidato = pos
            confirmacion = {"frame_inicio": pos, "frame_confirmacion": pos,
                            "retroceso_frames": 0, "crecimiento_ratio": 1.0,
                            "metodo": "salto_general"}
            tipo_deteccion = "salto_general"

    if candidato is None:
        resultado = {"ruta": str(ruta), "nombre": ruta.name, "firma": firma,
                     "estado": "sin_evento", "fps": fps_temporal_pre,
                     "fps_archivo": fps_archivo,
                     "fps_grabacion": (float(fps_rec_inicial) if fps_rec_inicial else None),
                     "fps_fuente": ("overlay_rec" if fps_rec_inicial else "archivo"),
                     "total_frames": total_frames,
                     "ancho": ancho, "alto": alto, "umbral": round(umbral, 4),
                     "resolucion_nativa_ms": (round(resolucion_pre, 6) if resolucion_pre else None),
                     "overlay_texto": overlay_inicial.get("texto", ""),
                     "overlay_timestamp_inicial_ms": _numero_no_negativo(overlay_inicial.get("timestamp_esquina_ms")),
                     "confianza": 0.0, "score_apertura": 0.0, "desde_cache": False,
                     "algoritmo_video": ALGORITMO_VERSION,
                     "zona_deteccion": zona_aprendida,
                     "tipo_camara": zona_aprendida.get("tipo_camara"),
                     "baseline_frames": nbase_obj,
                     "perfil_evento_aprendido": perfil_evento}
    else:
        actual = scores[candidato]
        mb = ((confirmacion or {}).get("metricas_inicio") or
              (metricas_blanco[candidato] if candidato < len(metricas_blanco) else {}))
        crecimiento = float((confirmacion or {}).get("crecimiento_ratio") or 1.0)
        score_apertura = _puntaje_apertura(mb, actual, umbral, crecimiento,
                                           zona_aprendida, perfil_evento)
        if (confirmacion or {}).get("metodo") == "crecimiento_backtracking":
            confianza = max(0.72, min(0.99, 0.62 + 0.37 * score_apertura))
        elif tipo_deteccion == "primer_blanco_nuevo":
            confianza = max(0.62, min(0.92, 0.55 + 0.32 * score_apertura))
        else:
            confianza = max(0.45, min(0.88, 0.45 + 0.30 * score_apertura))

        frame_evento = next((f for i, f in recientes if i == candidato), None)
        ok = frame_evento is not None
        if not ok:
            cap2 = cv2.VideoCapture(str(ruta))
            # Un indicio de 1 px puede permanecer más que el ring antes de
            # crecer. Se vuelve a decodificar hasta él sin seek por keyframe:
            # no se guarda todo el vídeo ni se arriesga leer otro fotograma.
            try:
                for _ in range(candidato + 1):
                    ok, frame_evento = cap2.read()
                    if not ok:
                        break
            finally:
                cap2.release()
        advertencia_deteccion = None
        if (confirmacion or {}).get("inicio_en_borde_baseline"):
            # La bolsa ya podría verse dentro de los cuadros de referencia.
            confianza = min(confianza, 0.6)
            advertencia_deteccion = (
                "La evidencia empieza justo después de los cuadros de referencia; "
                "la bolsa podría ser visible antes. Revísalo cuadro por cuadro.")
        overlay = (_leer_overlay(frame_evento, config) if ok else
                   {"texto": "", "tiempos_ms": [], "fps_grabacion": [],
                    "timestamp_esquina_ms": None, "precision_timestamp_esquina_ms": None,
                    "texto_esquina": "", "error": None})
        fps_rec_vals = list(overlay.get("fps_grabacion") or []) or list(overlay_inicial.get("fps_grabacion") or [])
        fps_grabacion = float(fps_rec_vals[0]) if fps_rec_vals else None
        control_fps = validar_fps_con_reloj(
            fps_grabacion, candidato, overlay.get("timestamp_esquina_ms"),
            overlay_inicial.get("timestamp_esquina_ms"),
            leer_reloj=lambda f: leer_timestamp_esquina_frame(ruta, f, config).get("timestamp_ms"),
            total_frames=total_frames)
        if control_fps.get("corregido"):
            fps_grabacion = float(control_fps["fps"])
        fps_temporal = fps_grabacion or fps_archivo
        resolucion = (1000.0 / fps_temporal) if fps_temporal > 0 else None
        tiempo_fps = (candidato / fps_temporal * 1000.0) if fps_temporal > 0 else None

        tiempo_esquina = overlay.get("timestamp_esquina_ms")
        precision_esquina = overlay.get("precision_timestamp_esquina_ms")
        tiempo_resuelto = resolver_tiempo_metadata(
            frame_index=candidato, fps=fps_temporal,
            timestamp_actual_ms=tiempo_esquina,
            timestamp_inicial_ms=overlay_inicial.get("timestamp_esquina_ms"),
            precision_overlay_ms=precision_esquina, config=config)
        tiempo_overlay = tiempo_resuelto.get("tiempo_overlay_ms")
        tiempo = tiempo_resuelto.get("tiempo_ms")
        fuente = tiempo_resuelto.get("fuente_tiempo")
        precision = (precision_esquina if tiempo_resuelto.get("overlay_valido") else resolucion)
        if tiempo_resuelto.get("overlay_valido"):
            confianza = max(confianza, 0.93)
        offset_overlay = None
        if tiempo_overlay is not None and tiempo_fps is not None and tiempo_resuelto.get("overlay_valido"):
            offset_overlay = float(tiempo_overlay) - float(tiempo_fps)
        resultado = {
            "ruta": str(ruta), "nombre": ruta.name, "firma": firma,
            "estado": "candidato", "fps": fps_temporal,
            "fps_archivo": fps_archivo, "fps_grabacion": fps_grabacion,
            "fps_fuente": ("reloj_overlay" if control_fps.get("corregido") else
                           "overlay_rec" if fps_grabacion else "archivo"),
            "fps_validado_reloj": (fps_grabacion if control_fps.get("corregido") else None),
            "fps_segun_reloj": control_fps.get("fps_reloj"),
            "advertencia_fps": control_fps.get("advertencia"),
            "total_frames": total_frames, "ancho": ancho, "alto": alto,
            "frame_evento": int(candidato),
            "frame_confirmacion_automatica": int((confirmacion or {}).get("frame_confirmacion", candidato)),
            "retroceso_frames": int((confirmacion or {}).get("retroceso_frames", 0)),
            "crecimiento_ratio": round(crecimiento, 4),
            "metodo_confirmacion": (confirmacion or {}).get("metodo"),
            "score_evento": round(float(actual), 4), "umbral": round(float(umbral), 4),
            "score_apertura": round(float(score_apertura), 4),
            "tiempo_ms": None if tiempo is None else round(float(tiempo), 1),
            "tiempo_fps_ms": None if tiempo_fps is None else round(float(tiempo_fps), 3),
            "tiempo_subframe_estimado_ms": None,
            "tiempo_overlay_ms": tiempo_overlay, "fuente_tiempo": fuente,
            "resolucion_nativa_ms": None if resolucion is None else round(float(resolucion), 6),
            "precision_fuente_ms": None if precision is None else round(float(precision), 6),
            "exactitud_0_1ms_sustentada": bool(precision is not None and precision <= 0.1000001),
            "estimacion_subframe": False,
            "confianza": round(float(confianza), 4),
            "overlay_texto": overlay.get("texto", ""),
            "overlay_texto_esquina": overlay.get("texto_esquina", ""),
            "overlay_timestamp_inicial_ms": _numero_no_negativo(overlay_inicial.get("timestamp_esquina_ms")),
            "offset_overlay_ms": None if offset_overlay is None else round(offset_overlay, 6),
            "discrepancia_tiempo_ms": tiempo_resuelto.get("discrepancia_ms"),
            "advertencia_tiempo": tiempo_resuelto.get("advertencia"),
            "overlay_validado": bool(tiempo_resuelto.get("overlay_valido")),
            "overlay_error": overlay.get("error"), "tipo_deteccion": tipo_deteccion,
            "pixeles_blanco_nuevo": int(mb.get("pixeles_blanco_nuevo") or 0),
            "pixeles_grieta_nueva": int(mb.get("pixeles_grieta_nueva") or 0),
            "pixeles_ruptura": int(mb.get("pixeles_ruptura") or 0),
            "componente_ruptura_px": int(mb.get("componente_ruptura_px") or 0),
            "indicio_un_pixel": bool((confirmacion or {}).get("indicio_un_pixel")),
            "fraccion_blanco_nuevo": round(float(mb.get("fraccion_blanco_nuevo") or 0.0), 8),
            "componente_blanco_px": int(mb.get("componente_blanco_px") or 0),
            "fraccion_componente_blanco": round(float(mb.get("fraccion_componente_blanco") or 0.0), 8),
            "fraccion_borde_nuevo": round(float(mb.get("fraccion_borde_nuevo") or 0.0), 8),
            "desde_cache": False, "algoritmo_video": ALGORITMO_VERSION,
            "zona_deteccion": zona_aprendida, "tipo_camara": zona_aprendida.get("tipo_camara"),
            "baseline_frames": nbase_obj, "perfil_evento_aprendido": perfil_evento,
            "antes_limpio": bool((confirmacion or {}).get("antes_limpio")),
            "inicio_en_borde_baseline": bool((confirmacion or {}).get("inicio_en_borde_baseline")),
            "advertencia_deteccion": advertencia_deteccion,
            "pixeles_sin_compensar": int(mb.get("pixeles_sin_compensar") or 0),
        }
    resultado["ruido_baseline"] = ruido_base
    resultado["compensacion_movimiento"] = bool(cfg.get("compensar_movimiento", True))
    resultado["analisis_resolucion_nativa"] = bool(cfg.get("analisis_resolucion_nativa", True))
    resultado["requiere_revision"] = True
    resultado["validado_con_videos_reales"] = False
    resultado["definicion_evento"] = "Primer contorno visible de ruptura corroborado; no abombamiento."
    resultado["parametros_ruptura"] = {
        "incremento_minimo": int(cfg_det.get("umbral_incremento_blanco", 18)),
        "discontinuidad_local_minima": float(cfg_det.get("umbral_discontinuidad_nueva", 6.0)),
        "pixeles_indicio_minimos": int(cfg_det.get("min_pixeles_indicio", 1)),
        "radio_seguimiento_px": float(cfg_det.get("radio_indicio_px", 3.0)),
        "frames_confirmacion_minimos": int(cfg_det.get("min_frames_confirmacion", 2)),
        "crecimiento_minimo": float(cfg_det.get("crecimiento_ratio_min", 1.8)),
    }
    resultado["limitacion_detector"] = (
        "Candidato heurístico pendiente de validación con vídeos reales: ruido, compresión, "
        "reflejos o sombras pueden ocultar o imitar un píxel de ruptura. Revisar el fotograma propuesto.")
    resultado["frames_leidos"] = frames_leidos
    if any(m.get("componentes_indicio_truncados") for m in metricas_blanco):
        resultado["advertencia_componentes"] = (
            "Hay más contornos que el límite de seguimiento; un indicio pequeño "
            "podría quedar fuera. Ajustar la ROI a la costura y revisar manualmente.")
    if (candidato is None and metricas_blanco and
            metricas_blanco[-1].get("evidencia_debil")):
        resultado["advertencia_deteccion"] = (
            "El vídeo termina con un indicio sin suficiente crecimiento posterior "
            "para corroborar su primer fotograma. Revisar el final del clip.")
    rev = revision_video(ruta)
    if rev:
        resultado["revision_manual"] = rev
    items_cache = cache.setdefault("items", {})
    # Poda: cada video conserva sólo su resultado vigente y se descartan los
    # de algoritmos anteriores (antes el archivo crecía sin límite).
    for clave in [k for k, v in items_cache.items()
                  if not isinstance(v, dict) or v.get("algoritmo_video") != ALGORITMO_VERSION
                  or v.get("firma") == firma]:
        items_cache.pop(clave, None)
    items_cache[cache_key] = {k: v for k, v in resultado.items() if k != "revision_manual"}
    cache["version"] = 7
    _guardar_json(RUTA_CACHE, cache)
    return resultado

def tiempo_efectivo_video(item: dict) -> tuple[float | None, str, bool]:
    rev = item.get("revision_manual") or {}
    if rev.get("estado") == "sin_evento":
        return None, "revision_manual_sin_evento", True
    if rev.get("estado") == "confirmado" and rev.get("tiempo_ms") is not None:
        valor = _numero_no_negativo(rev.get("tiempo_ms"))
        return (valor, "revision_manual", True) if valor is not None else (None, "revision_manual_invalida", True)
    if item.get("estado") == "candidato" and item.get("tiempo_ms") is not None:
        valor = _numero_no_negativo(item.get("tiempo_ms"))
        if valor is not None:
            return valor, str(item.get("fuente_tiempo") or "automatico"), False
    return None, "sin_evento", False


ESTADOS_CONSENSO_VALIDOS = {"confirmado_manual", "primera_aparicion", "confirmado_3_de_4"}


def consenso_valido(consenso: dict | None) -> bool:
    """¿El consenso de video puede rellenar ``opening_time_ms``?"""
    c = consenso or {}
    return c.get("estado") in ESTADOS_CONSENSO_VALIDOS and _numero_no_negativo(c.get("tiempo_ms")) is not None


def _camara_item(item: dict) -> str | None:
    tipo = item.get("tipo_camara") or (item.get("zona_deteccion") or {}).get("tipo_camara")
    if tipo:
        return str(tipo).upper()
    from aprendizaje_video_airbag import inferir_tipo_camara_nombre
    return inferir_tipo_camara_nombre(item.get("nombre") or item.get("ruta") or "")


def consenso_videos(items: Iterable[dict], config: dict | None = None) -> dict:
    """Tiempo de apertura del ensayo a partir de sus cámaras.

    V15.7, regla definida por el usuario: la apertura es el PRIMER cuadro en
    que la bolsa es físicamente visible, aunque sean pocos píxeles. Por eso se
    toma la cámara más temprana, no la mediana. La vista trasera (SCHEIBE) es
    la menos fiable y no define el tiempo; sólo se usa si no hay otra cámara.

    - Si alguna cámara principal tiene revisión manual confirmada, manda la
      confirmación manual más temprana (``confirmado_manual``).
    - Si sólo hay detecciones automáticas, se toma la más temprana que al
      menos ``min_camaras_primera_aparicion`` cámaras principales respaldan
      dentro de ±1 cuadro (``primera_aparicion``). Una detección aislada más
      temprana se informa y pide revisión. Sin respaldo: ``sin_consenso``.
    """
    cfg = _cfg(config)
    vcfg = (config or cargar_config()).get("video_airbag") or {}
    items = [x for x in items if isinstance(x, dict)]
    # Blindaje: todas las cámaras se normalizan con la tasa real del ensayo
    # antes de comparar nada (nunca se mezclan 8 fps con 5000 fps).
    normalizar_videos_caso(items, config)
    excluidas = {str(x).upper() for x in (vcfg.get("camaras_excluidas_consenso") or ["SCHEIBE"])}
    min_camaras = max(1, int(vcfg.get("min_camaras_primera_aparicion", 2)))

    # Calibración overlay: sólo con relojes VALIDADOS y tasa real conocida.
    offsets = []
    for item in items:
        if item.get("overlay_validado") is False or item.get("fps_fuente") == "desconocido":
            continue
        overlay_v = _numero_no_negativo(item.get("tiempo_overlay_ms"))
        fps_v = _numero_no_negativo(item.get("tiempo_fps_ms"))
        if overlay_v is None or fps_v is None:
            continue
        offsets.append(overlay_v - fps_v)
    offset_overlay = median(offsets) if offsets else None

    datos = []
    for item in items:
        valor, fuente, manual = tiempo_efectivo_video(item)
        if valor is None:
            continue
        resol = _numero_no_negativo(item.get("resolucion_nativa_ms")) or 1.0
        valor_usado = float(valor)
        fuente_usada = fuente
        if (not manual and not str(fuente).startswith("timestamp_overlay") and offset_overlay is not None and
                item.get("tiempo_fps_ms") is not None):
            candidato_calibrado = float(item["tiempo_fps_ms"]) + float(offset_overlay)
            if math.isfinite(candidato_calibrado) and candidato_calibrado >= 0:
                valor_usado = candidato_calibrado
                fuente_usada = "fps_calibrado_por_overlay"
        camara = _camara_item(item)
        datos.append({"valor": round(valor_usado, 3), "fuente": fuente_usada, "manual": manual,
                      "resolucion": float(resol), "nombre": item.get("nombre"),
                      "camara": camara, "principal": camara not in excluidas,
                      "requiere_revision": bool(item.get("requiere_revision")) and not manual})
    vacio = {"tiempo_ms": None, "soporte": 0, "total_validos": len(datos),
             "requiere_revision": True, "calibracion_overlay_ms": None,
             "regla": "primera_aparicion", "camaras_excluidas": sorted(excluidas)}
    if not datos:
        return {"estado": "sin_datos", **vacio}
    principales = [x for x in datos if x["principal"]]
    usa_excluidas = not principales
    pool = principales or datos
    manuales = [x for x in pool if x["manual"]]
    tol_base = float(cfg.get("tolerancia_consenso_ms", 0.15))

    def _tolerancia(x: dict) -> float:
        return max(tol_base, x["resolucion"] * 1.0 + 1e-6)

    def _soporte(x: dict) -> list[dict]:
        return [y for y in pool if abs(y["valor"] - x["valor"]) <= _tolerancia(x)]

    necesario = min(min_camaras, len(pool))
    anterior_sin_respaldo = None
    if manuales:
        primero = min(manuales, key=lambda x: x["valor"])
        estado = "confirmado_manual"
    else:
        # La cámara más temprana que otra cámara principal respalda (±1 cuadro).
        # Una detección aislada aún más temprana no se descarta en silencio:
        # se informa para que el usuario la revise.
        ordenados = sorted(pool, key=lambda x: x["valor"])
        primero = next((x for x in ordenados if len(_soporte(x)) >= necesario), None)
        if primero is None:
            primero, estado = ordenados[0], "sin_consenso"
        else:
            estado = "primera_aparicion"
            previo = ordenados[0]
            if previo["valor"] < primero["valor"] - _tolerancia(primero):
                anterior_sin_respaldo = {"video": previo["nombre"], "camara": previo["camara"],
                                         "tiempo_ms": round(previo["valor"], 3)}
    tolerancia = _tolerancia(primero)
    soporte_items = _soporte(primero)
    if usa_excluidas and estado != "confirmado_manual":
        # Sólo hay vista trasera: no basta para fijar el tiempo automáticamente.
        estado = "sin_consenso"
    precision_sustentada = all(x["resolucion"] <= 0.2000001 for x in soporte_items)
    requiere_revision = estado != "confirmado_manual" and (
        estado == "sin_consenso" or anterior_sin_respaldo is not None or
        any(x["requiere_revision"] for x in soporte_items))
    return {
        "estado": estado, "tiempo_ms": round(float(primero["valor"]), 1),
        "regla": "primera_aparicion",
        "camara_referencia": primero["camara"], "video_referencia": primero["nombre"],
        "fuente_referencia": primero["fuente"],
        "soporte": len(soporte_items), "total_validos": len(datos),
        "total_principales": len(principales),
        "camaras_excluidas": sorted(excluidas),
        "videos_coincidentes": [x["nombre"] for x in soporte_items],
        "valores_coincidentes_ms": [round(x["valor"], 3) for x in soporte_items],
        "fuentes_coincidentes": [x["fuente"] for x in soporte_items],
        "valores_por_camara": {str(x["camara"] or x["nombre"]): round(x["valor"], 3) for x in datos},
        "tolerancia_ms": round(tolerancia, 4),
        "calibracion_overlay_ms": None if offset_overlay is None else round(float(offset_overlay), 3),
        "camara_anterior_sin_respaldo": anterior_sin_respaldo,
        "requiere_revision": requiere_revision,
        "exactitud_0_1ms_sustentada": precision_sustentada,
        "nota_precision": ("Resolución de un cuadro o mejor (Rec…fps)." if precision_sustentada else
                           "Al menos un video tiene una resolución temporal más gruesa que 0.2 ms."),
    }

def evidencia_apertura_desde_consenso(caso: dict, consenso: dict) -> dict | None:
    if not consenso_valido(consenso):
        return None
    return {
        "proyecto": caso.get("project_id"), "etapa": caso.get("tipo_st"),
        "caso": caso.get("case_key"), "componente": "bolsa_aire",
        "clave": "opening_time_ms", "valor_original": str(consenso["tiempo_ms"]),
        "valor_normalizado": str(consenso["tiempo_ms"]), "fuente": "video",
        "imagen": None, "video": ", ".join(consenso.get("videos_coincidentes") or []),
        "bbox_original": None, "orientacion_grados": 0, "transformaciones": ["deteccion_video_airbag"],
        "fase": "VIDEO", "tor": None, "confianza_ocr": 0.99 if consenso.get("estado") == "confirmado_manual" else min(0.99, 0.75 + 0.08 * consenso.get("soporte", 0)),
        "valido_catalogo": True, "valido_regex": True,
        "confirmacion_manual": consenso.get("estado") == "confirmado_manual",
        "requiere_confirmacion_manual": bool(consenso.get("requiere_revision")) and
                                         consenso.get("estado") != "confirmado_manual",
    }
