"""Campos del libro que salen del **vídeo**, no de las fotos (P15).

En cada vídeo de eDAG hay una barra de estado pegada al borde inferior:

    VW316/5 252590 RdW RT NOM 0ms EDAG Mex BMG 19 JUN 25 Rec5000 fps, Schutter 80us

De ahí salen la **fecha de prueba**, el **número de prueba**, el **lugar de prueba**, la
**temperatura** y el **delay**. Eso es justo lo que la Fase 2 dejaba casi vacío (`test_date`
3/10). Este módulo lee la barra con `barra_estado` en varios fotogramas del vídeo, vota campo por
campo y devuelve propuestas con su nivel de acuerdo.

Regla de oro: si el acuerdo entre fotogramas es bajo, el campo **no** se propone; se manda a dudas.
Nunca se rellena un campo con un valor inventado.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from utilidades.barra_estado import (cargar_banco, interpretar_barra, leer_video)

EXTENSIONES_VIDEO = {".avi", ".mp4", ".mov", ".mkv", ".m4v"}
ACUERDO_MINIMO = 0.6

# Campos que se leen de la barra. `module_version` se midió y NO es fiable: la barra lo imprime
# como «RdW» y el clasificador lo confunde con «R5MM» (0 de 4 vídeos). No se propone.
CAMPOS_VIDEO = ("test_date", "test_number", "test_place", "temperature_condition", "delay_ms")
CAMPOS_DESCARTADOS = {
    "module_version": "la barra lo imprime en minúsculas mezcladas («RdW») y se confunde con «R5MM»: 0/4 vídeos",
    "proyecto": "el proyecto ya se conoce por la carpeta del caso; la barra lo imprime pegado a «/» y se degrada",
}

LEXICO = {
    "temperature_condition": ("RT", "NT", "HT", "KT"),
    "test_place": ("EDAG MEX", "EDAG MEXICO", "EDAG PUEBLA"),
}


def videos(carpeta) -> list[Path]:
    """Todos los vídeos de una carpeta de caso (vienen mezclados con las fotos)."""
    return sorted(p for p in Path(carpeta).rglob("*")
                  if p.suffix.lower() in EXTENSIONES_VIDEO and p.is_file())


def analizar_videos(rutas, banco=None, muestras: int = 5, lexico: dict | None = None) -> dict[str, dict]:
    """Lee la barra de todos los vídeos y devuelve una propuesta por campo.

    Si hay varios vídeos del mismo ensayo (varias cámaras), los votos se suman entre vídeos.
    """
    banco = banco if banco is not None else cargar_banco(Path(__file__).resolve().parent.parent
                                                         / "aprendizaje" / "barra_estado.json")
    lexico = LEXICO if lexico is None else lexico
    votos: dict[str, Counter] = {}
    acuerdos: dict[str, list[float]] = {}
    textos: Counter = Counter()
    usados, con_barra = 0, 0
    for ruta in rutas:
        lectura = leer_video(ruta, muestras=muestras, banco=banco, lexico=lexico)
        if not lectura.get("muestras"):
            continue
        usados += 1
        if lectura.get("texto"):
            con_barra += 1
            textos[lectura["texto"]] += 1
        for campo, valor in lectura["campos"].items():
            if campo in CAMPOS_DESCARTADOS or valor in (None, ""):
                continue
            votos.setdefault(campo, Counter())[valor] += 1
            acuerdos.setdefault(campo, []).append(float(lectura["acuerdo"].get(campo, 0.0)))
    propuestas: dict[str, dict] = {}
    for campo in CAMPOS_VIDEO:
        contador = votos.get(campo)
        if not contador:
            continue
        valor, cuantos = contador.most_common(1)[0]
        acuerdo = round(cuantos / usados, 2) if usados else 0.0
        propuestas[campo] = {
            "campo": campo, "valor": valor,
            "estado": "propuesto" if acuerdo >= ACUERDO_MINIMO else "dudoso",
            "acuerdo": acuerdo, "votos": cuantos, "videos": usados,
            "acuerdo_interno": round(sum(acuerdos.get(campo, [0.0])) / max(1, len(acuerdos.get(campo, [0]))), 2),
            "fuente": "barra_estado_video",
        }
    if propuestas:
        propuestas["__resumen__"] = {
            "videos": usados, "videos_con_barra": con_barra,
            "texto": textos.most_common(1)[0][0] if textos else "",
            "campos_descartados": dict(CAMPOS_DESCARTADOS),
        }
    return propuestas


def congruencia_con_caso(propuestas: dict[str, dict], caso: str) -> dict[str, dict]:
    """Comprueba que la barra del vídeo habla del **mismo ensayo** que la carpeta del caso.

    Los vídeos se guardan por carpeta y es fácil que en una carpeta de un caso acabe el vídeo de
    otro ensayo. Si el número de la barra no es el del caso, los campos de fecha/número/lugar no
    se proponen: se marcan en conflicto para que salgan como duda con la barra a la vista.
    """
    numero = propuestas.get("test_number", {}).get("valor")
    esperado = "".join(ch for ch in str(caso) if ch.isdigit()) or str(caso)
    if not numero or not esperado or numero == esperado:
        return propuestas
    for campo in ("test_number", "test_date", "test_place"):
        if campo in propuestas:
            propuestas[campo] = {**propuestas[campo], "estado": "conflicto",
                                 "conflicto": f"la barra dice {numero!r} y el caso es {esperado!r}"}
    return propuestas


def a_dudas(caso: str, propuestas: dict[str, dict]) -> list[dict]:
    """Las propuestas con acuerdo bajo se convierten en dudas (sin imagen: la barra es texto)."""
    salida = []
    for campo, propuesta in propuestas.items():
        if campo.startswith("__") or propuesta["estado"] == "propuesto":
            continue
        if propuesta["estado"] == "conflicto":
            salida.append({
                "caso": caso, "campo": campo, "motivo": "video_no_coincide_con_caso",
                "detalle": (f"{propuesta.get('conflicto', '')}. Comprueba que el vídeo de la carpeta "
                            f"es el del ensayo antes de usar su barra."),
                "opciones": [{"valor": propuesta["valor"], "fuente": "video",
                              "detalle": "usar la barra de todos modos"},
                             {"valor": None, "fuente": "vacio", "detalle": "dejar vacío"}],
                "donde_mirar": ["el número de la carpeta del caso y el de la barra del vídeo"],
                "imagen": "",
            })
            continue
        salida.append({
            "caso": caso, "campo": campo, "motivo": "video_barra_dudoso",
            "detalle": (f"La barra del vídeo da {propuesta['valor']!r} en {propuesta['votos']} de "
                        f"{propuesta['videos']} vídeo(s) (acuerdo {propuesta['acuerdo']:.0%})."),
            "opciones": [{"valor": propuesta["valor"], "fuente": "video", "detalle": "lectura de la barra"},
                         {"valor": None, "fuente": "vacio", "detalle": "dejar vacío"}],
            "donde_mirar": ["la barra blanca del pie del vídeo, a la derecha del número de prueba"],
            "imagen": "",
        })
    return salida


def campos_disponibles() -> tuple[str, ...]:
    return CAMPOS_VIDEO
