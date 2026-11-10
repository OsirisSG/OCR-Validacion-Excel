#!/usr/bin/env python3
"""P42 · rehace la evidencia con el lector nuevo, sin tabla y sin usar el payload como N/P.

    python3 rehacer_evidencia_p42.py --base evidencia_tablero_p40.json \
        --parcial /tmp/lecturas_tablero.json --dm /tmp/p42/dm_v2.json \
        --salida /home/user/evidencia_tablero_p42.json

Qué hace y por qué:

  * la serie sale de las lecturas del DataMatrix **tal cual** (barrido nuevo, sin tabla);
  * el número de parte **no** se toma del payload: se borran las lecturas `datamatrix` de ese
    campo para que se conserve lo que dio el grabado en P40 (decisión pendiente del usuario, A6);
  * la fecha y el nivel se conservan de la pasada de OCR que ya estaba medida;
  * el cierre usa `cerrar()` del árbol, con `consensuar_completo()` para la fecha.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidencia_tablero as E  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="evidencia anterior (P40), de la que se funde")
    ap.add_argument("--parcial", required=True, help="parcial con las lecturas de OCR")
    ap.add_argument("--dm", required=True, help="barrido del DataMatrix con el lector nuevo")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--np-del-payload", action="store_true",
                    help="autorizado por el usuario (A6): si el grabado no dio lectura, se toma el "
                         "número de parte del DataMatrix y se marca cómo se obtuvo")
    args = ap.parse_args()

    parcial = json.loads(Path(args.parcial).read_text(encoding="utf-8"))
    dm = json.loads(Path(args.dm).read_text(encoding="utf-8"))

    for caso, registro in parcial.items():
        lecturas = registro.setdefault("lecturas", {})
        # 1) la serie: sólo lo que diga el código, sin transformar
        del_dm = [l for l in (dm.get(caso) or []) if l.get("valor")]
        if del_dm:
            lecturas["dashboard_serial_number"] = del_dm
        # 2) el número de parte: fuera lo que venga del payload, salvo que el usuario lo haya
        #    autorizado (A6) y el grabado no haya dado nada en este caso
        grabado = [l for l in (lecturas.get("dashboard_part_number") or [])
                   if not str(l.get("origen", "")).startswith("datamatrix")
                   and l.get("valor")]
        if grabado or not args.np_del_payload:
            if "dashboard_part_number" in lecturas:
                lecturas["dashboard_part_number"] = [
                    l for l in lecturas["dashboard_part_number"]
                    if not str(l.get("origen", "")).startswith("datamatrix")]
        else:
            parte = next((l.get("parte") for l in (dm.get(caso) or []) if l.get("parte")), "")
            if parte:
                mejor = max(dm.get(caso), key=lambda l: float(l.get("confianza") or 0))
                lecturas["dashboard_part_number"] = [{
                    "valor": parte, "confianza": float(mejor.get("confianza") or .95),
                    "foto": mejor.get("foto", ""), "carpeta": mejor.get("carpeta", ""),
                    "origen": "datamatrix_payload_np",
                    "texto": mejor.get("payload_text", "") or mejor.get("texto", ""),
                    "payload_hex": mejor.get("payload_hex", ""),
                    "formato": mejor.get("formato", ""),
                    "version_decode": mejor.get("version_decode", ""),
                    "dudoso": False, "conflicto": [], "cola_cruda": "", "clase_cola": "",
                    "autorizado_por": "usuario_A6_2026-10-29"}]

    limpio = Path("/tmp/parcial_limpio_p42.json")
    limpio.write_text(json.dumps(parcial, ensure_ascii=False, indent=1), encoding="utf-8")
    base_copia = Path("/tmp/base_p42.json")
    base_copia.write_text(Path(args.base).read_text(encoding="utf-8"), encoding="utf-8")
    # `cerrar(parcial, json_path, carpeta_de_capturas)`: el resultado se guarda aquí mismo
    evidencia = E.cerrar(limpio, base_copia, Path(args.salida).parent)
    Path(args.salida).write_text(json.dumps(evidencia, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    print(f"evidencia escrita en {args.salida} · {len(evidencia)} casos")
    for caso in sorted(evidencia):
        dato = evidencia[caso]
        dudosos = dato.get("dudoso") or {}
        print(f"  {caso}: {dato.get('dashboard_serial_number') or '—'} · "
              f"{dato.get('dashboard_date') or '—'} · "
              f"{'DUDA ' + ','.join(sorted(dudosos)) if dudosos else 'sin duda'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
