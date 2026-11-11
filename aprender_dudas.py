#!/usr/bin/env python3
"""P42 · qué aprende el sistema de las confirmaciones humanas, y hasta dónde puede usarlo.

    python3 aprender_dudas.py --precedentes precedentes_p42.json \
        --decisiones decisiones_p42.json --informe aprender.txt

El sistema **no** aprende reglas que se apliquen solas. Aprende **precedentes**: para cada patrón
de cola (clase, largo y caracteres raros), qué valor confirmó una persona y en cuántos casos.
Qué hace con ellos:

  * `revisar_dudas.py` los enseña como **opción sugerida** en la cola siguiente, diciendo cuántos
    casos la apoyan. Nunca los aplica.
  * `rellenar_tablero_p42.py` **no los lee**. Sólo lee decisiones por celda.

Por qué así: la revisión de Astra tumbó la tabla de colisiones precisamente por esto. Una regla
aprendida de tres respuestas parece una regla y es una casualidad; si se aplica sola, el error se
propaga a etiquetas que nadie miró. Como sugerencia, en cambio, ahorra tiempo y no decide nada.

Umbral: con menos de 3 casos el patrón se marca FLOJO y se avisa. Con dos valores distintos para
el mismo patrón, se marca EN CONFLICTO y no se sugiere ninguno.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

UMBRAL_FLOJO = 3


def fusionar(precedentes: dict, decisiones: list[dict]) -> tuple[dict, list[str]]:
    """Mete las decisiones nuevas en los precedentes y devuelve (precedentes, avisos). Pura."""
    avisos: list[str] = []
    for decision in decisiones:
        patron = str(decision.get("patron") or "")
        valor = str(decision.get("publicada") or "")
        caso = str(decision.get("caso") or "")
        if not patron or not valor:
            continue
        registro = precedentes.setdefault(patron, {"valor": valor, "casos": 0, "casos_ids": []})
        anterior = registro.get("valor")
        if caso not in registro["casos_ids"]:
            registro["casos_ids"].append(caso)
            registro["casos"] = len(registro["casos_ids"])
        if anterior and anterior != valor:
            registro.setdefault("valores", {})
            registro["valores"][valor] = registro["valores"].get(valor, 0) + 1
            registro["valores"].setdefault(anterior, 1)
            avisos.append(f"patrón {patron}: dos valores distintos ({anterior} y {valor}); "
                          f"no se sugiere ninguno hasta que haya más casos")
            if max(registro["valores"].values()) * 2 > sum(registro["valores"].values()):
                registro["valor"] = max(registro["valores"], key=registro["valores"].get)
            else:
                registro["valor"] = ""
            continue
        registro["valor"] = valor
    for patron, registro in precedentes.items():
        if 0 < int(registro.get("casos", 0)) < UMBRAL_FLOJO:
            avisos.append(f"patrón {patron}: sólo {registro['casos']} caso(s); se sugiere pero "
                          f"se marca flojo")
    return precedentes, avisos


def main() -> int:
    ap = argparse.ArgumentParser(description="Funde decisiones en precedentes y avisa de lo flojo")
    ap.add_argument("--precedentes", required=True, help="archivo de precedentes a actualizar")
    ap.add_argument("--decisiones", required=True, help="decisiones con su patrón (del HTML)")
    ap.add_argument("--informe", default="", help="archivo de texto donde dejar el resumen")
    args = ap.parse_args()

    previos = {}
    if Path(args.precedentes).exists():
        previos = json.loads(Path(args.precedentes).read_text(encoding="utf-8"))
    decisiones = json.loads(Path(args.decisiones).read_text(encoding="utf-8"))
    if isinstance(decisiones, dict):                 # por si llega el de precedentes
        decisiones = []

    fusionados, avisos = fusionar(previos, decisiones)
    Path(args.precedentes).write_text(
        json.dumps(fusionados, ensure_ascii=False, indent=1), encoding="utf-8")

    lineas = [f"precedentes en {args.precedentes}: {len(fusionados)} patrón(es)"]
    for patron, registro in sorted(fusionados.items()):
        lineas.append(f"  {patron:34s} -> {registro.get('valor') or '(sin valor claro)':16s} "
                      f"{registro.get('casos', 0)} caso(s)")
    lineas += ["", "avisos:"] + [f"  - {a}" for a in avisos] if avisos else ["", "sin avisos"]
    texto = "\n".join(lineas)
    print(texto)
    if args.informe:
        Path(args.informe).write_text(texto + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
