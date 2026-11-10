#!/usr/bin/env python3
"""Evidencia de la **semana de prueba**: número de prueba leído de la barra del vídeo.

Para cada caso con vídeos:
  1. Lee la barra inferior en varios fotogramas (voto mayoritario) → `test_number`, `test_date`.
  2. Guarda una **captura** del fotograma ganador con la barra ampliada y lo leído escrito encima
     (`evidencia_semana/<caso>.png`): eso es la prueba que se puede abrir y mirar.
  3. Deriva la **semana** de los dos primeros dígitos del número (guía, pág. 2) y la corrobora con la
     semana ISO de la fecha de prueba. Si no coinciden, la marca como conflicto y no la da por buena.
  4. Escribe un informe `informe_semana.md` y `informe_semana.json`.

Uso:
    python evidencia_semana.py --casos "C:\\Programas Base\\Resumen-1-Step" --salida evidencia_semana
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import cv2
import numpy as np

from utilidades import barra_estado as B
from utilidades.video_campos import videos


# el proyecto/pizarra va en la barra justo después del lugar: `EDAG Mex BMG`
PATRON_PIZARRA = re.compile(r"EDAG\s?ME?X?I?C?O?\s+(?P<proyecto>[A-Z]{2,5})\b")


def proyecto_de_barra(texto: str) -> str:
    """Devuelve el código que la barra pone tras «EDAG Mex» (`BMG`). Es el candidato a motivo."""
    encontrado = PATRON_PIZARRA.search(" ".join(str(texto or "").upper().split()))
    return encontrado.group("proyecto") if encontrado else ""


def semana_de_numero(numero: str) -> str | None:
    """`232541` → `23`. Es la regla de la guía: los dos primeros dígitos son la semana."""
    digitos = str(numero or "").strip()
    if len(digitos) < 6 or not digitos.isdigit():
        return None
    semana = int(digitos[:2])
    return f"{semana:02d}" if 1 <= semana <= 53 else None


def semana_iso(fecha) -> str | None:
    if not fecha:
        return None
    if isinstance(fecha, datetime):
        fecha = fecha.date()
    if isinstance(fecha, date):
        return f"{fecha.isocalendar().week:02d}"
    try:
        return f"{datetime.strptime(str(fecha)[:10], '%Y-%m-%d').date().isocalendar().week:02d}"
    except ValueError:
        return None


def _anotar(fotograma, lectura: dict, campos: dict, numero: str, semana: str | None,
            fuente: str, segundo: float) -> np.ndarray:
    """Fotograma + barra ampliada + lo leído. Todo ASCII: cv2.putText no dibuja acentos."""
    alto, ancho = fotograma.shape[:2]
    if ancho > 900:
        f = 900 / ancho
        fotograma = cv2.resize(fotograma, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    franja = fotograma[int(fotograma.shape[0] * 0.94):, :]
    if franja.size:
        f = max(1.0, min(4.0, 1500 / max(1, franja.shape[1])))
        franja = cv2.resize(franja, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    pie = np.zeros((190, fotograma.shape[1], 3), np.uint8)
    lineas = [
        f"VIDEO: {Path(fuente).name}   t={segundo:.1f}s",
        f"BARRA: {lectura.get('texto', '')[:70]}",
        f"NUMERO DE PRUEBA: {numero or 'no legible'}",
        f"SEMANA (2 primeros digitos): {semana or '?'}   FECHA: {campos.get('test_date') or '?'}",
        f"SEMANA ISO DE LA FECHA: {semana_iso(campos.get('test_date')) or '?'}",
    ]
    for i, texto in enumerate(lineas):
        cv2.putText(pie, texto[:110], (8, 26 + i * 34), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                    (0, 220, 255) if i == 2 else (230, 230, 230), 1, cv2.LINE_AA)
    partes = [fotograma, franja] if franja.size else [fotograma]
    partes.append(pie)
    return np.vstack([p if p.shape[1] == fotograma.shape[1] else cv2.resize(
        p, (fotograma.shape[1], p.shape[0])) for p in partes])


def evidencia_de_caso(carpeta: Path, salida: Path, muestras: int = 5,
                      banco=None) -> dict:
    rutas = videos(carpeta)
    if banco is None:
        banco = B.cargar_banco(Path(__file__).resolve().parent / "aprendizaje" / "barra_estado.json")
    resultado = {"caso": carpeta.name, "videos": [r.name for r in rutas], "lecturas": []}
    votos_numero: Counter = Counter()
    votos_fecha: Counter = Counter()
    votos_proyecto: Counter = Counter()
    mejor = None
    for ruta in rutas:
        captura = cv2.VideoCapture(str(ruta))
        total = int(captura.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total <= 0:
            captura.release()
            continue
        for indice in range(muestras):
            # mismas posiciones que `barra_estado.leer_video`: dentro del ensayo, no en el arranque
            posicion = int(total * (0.15 + 0.7 * (indice / max(1, muestras - 1))))
            captura.set(cv2.CAP_PROP_POS_FRAMES, posicion)
            bien, fotograma = captura.read()
            if not bien or fotograma is None:
                continue
            lectura = B.leer(fotograma, banco)
            if not lectura.get("texto"):
                continue
            campos = B.interpretar_barra(lectura["texto"])
            numero = str(campos.get("test_number") or "")
            proyecto = proyecto_de_barra(lectura["texto"])
            if proyecto:
                votos_proyecto[proyecto] += 1
            segundo = posicion / max(1.0, captura.get(cv2.CAP_PROP_FPS) or 25.0)
            resultado["lecturas"].append({"video": ruta.name, "segundo": round(segundo, 1),
                                          "texto": lectura["texto"][:120],
                                          "confianza": lectura.get("confianza"),
                                          "numero": numero or None,
                                          "proyecto": proyecto or None,
                                          "fecha": campos.get("test_date")})
            if numero:
                votos_numero[numero] += 1
                if campos.get("test_date"):
                    votos_fecha[campos["test_date"]] += 1
                # se guarda el fotograma que sí trae número: es el que sirve de prueba
                if mejor is None or lectura.get("confianza", 0) > mejor["confianza"]:
                    mejor = {"fotograma": fotograma.copy(), "lectura": lectura, "campos": campos,
                             "video": str(ruta), "segundo": segundo,
                             "confianza": lectura.get("confianza", 0)}
        captura.release()
    numero = votos_numero.most_common(1)[0][0] if votos_numero else ""
    proyecto = votos_proyecto.most_common(1)[0][0] if votos_proyecto else ""
    fecha = votos_fecha.most_common(1)[0][0] if votos_fecha else ""
    semana = semana_de_numero(numero)
    iso = semana_iso(fecha)
    resultado.update({
        "numero": numero, "fecha": fecha, "semana": semana, "semana_iso": iso,
        "proyecto_barra": proyecto, "votos_proyecto": dict(votos_proyecto),
        "votos_numero": dict(votos_numero),
        "estado": ("confirmada" if semana and iso and semana == iso
                   else "confirmada_sin_fecha" if semana and not iso
                   else "conflicto_numero_fecha" if semana and iso else "sin_video_legible"),
        "como": "dos primeros digitos del numero de prueba" if semana else "",
    })
    if mejor is not None:
        salida.mkdir(parents=True, exist_ok=True)
        imagen = _anotar(mejor["fotograma"], mejor["lectura"], mejor["campos"], numero, semana,
                         mejor["video"], mejor["segundo"])
        destino = salida / f"semana_{carpeta.name}.png"
        cv2.imwrite(str(destino), imagen)
        resultado["captura"] = str(destino)
    return resultado


def main() -> int:
    ap = argparse.ArgumentParser(description="Capturas de vídeo como evidencia de la semana")
    ap.add_argument("--casos", required=True, help="carpeta con una subcarpeta por caso")
    ap.add_argument("--salida", default="evidencia_semana", help="dónde dejar las capturas")
    ap.add_argument("--informe", default="informe_semana")
    ap.add_argument("--muestras", type=int, default=5)
    args = ap.parse_args()
    raiz = Path(args.casos)
    salida = Path(args.salida)
    casos = [c for c in sorted(raiz.iterdir()) if c.is_dir() and videos(c)] if raiz.is_dir() else []
    if not casos:
        print(f"no hay carpetas con vídeos en {raiz}")
        return 1
    banco = B.cargar_banco(Path(__file__).resolve().parent / "aprendizaje" / "barra_estado.json")
    resultados = [evidencia_de_caso(c, salida, muestras=args.muestras, banco=banco) for c in casos]
    for r in resultados:
        print(f"  {r['caso']}: numero={r['numero'] or '?':6s} semana={r['semana'] or '?':2s} "
              f"fecha={r['fecha'] or '?':10s} iso={r['semana_iso'] or '?':2s} "
              f"pizarra={r['proyecto_barra'] or '?':4s} [{r['estado']}]")
    lineas = ["# Semana de prueba · evidencia de los vídeos", "",
              "| Caso | Número de prueba (barra) | Semana (2 primeros dígitos) | Fecha de prueba | Semana ISO | Proyecto en la barra | Estado | Captura |",
              "|---|---|---|---|---|---|---|---|"]
    for r in resultados:
        captura = Path(r["captura"]).name if r.get("captura") else "—"
        lineas.append(f"| {r['caso']} | {r['numero'] or '—'} | **{r['semana'] or '—'}** | "
                      f"{r['fecha'] or '—'} | {r['semana_iso'] or '—'} | {r['proyecto_barra'] or '—'} | "
                      f"{r['estado']} | "
                      f"{f'[{captura}]({r["captura"]})' if r.get('captura') else '—'} |")
    lineas += ["", "La semana se deriva del número de prueba (guía, pág. 2: `232541` = 23 · 25 · 41) y se",
               "corrobora con la semana ISO de la fecha que la propia barra muestra. Si discrepan, queda en",
               "conflicto y no se escribe en el libro."]
    Path(f"{args.informe}.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    Path(f"{args.informe}.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    print(f"capturas en {salida} · informe {args.informe}.md / {args.informe}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
