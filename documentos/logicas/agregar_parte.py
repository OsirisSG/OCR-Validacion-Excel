"""Mete las lecturas del **número moldeado** en las lecturas del tablero y deja sus recortes.

`barrer_parte.py` guarda un `.jsonl` por caso con lo leído foto a foto. Aquí eso se convierte en
lecturas con la misma forma que las demás (valor, confianza, foto, carpeta, origen) para que
`evidencia_tablero.py --cerrar` las consense como cualquier otro campo, y se guardan los recortes
de la zona del grabado para el panel de dudas.

Uso: python3 agregar_parte.py --lecturas /tmp/lecturas_p30_total2.json --parte /tmp/parte \
        --salida /tmp/lecturas_p30_total3.json --recortes /home/user/evidencia_tablero
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import cv2

from utilidades.grabado_punteado import PARTE_TABLERO


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lecturas", required=True)
    ap.add_argument("--parte", required=True)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--recortes", default="")
    ap.add_argument("--fotos", default="/var/tmp/fotos")
    args = ap.parse_args()

    lecturas = json.loads(Path(args.lecturas).read_text(encoding="utf-8"))
    recortes = Path(args.recortes) if args.recortes else None
    if recortes:
        recortes.mkdir(parents=True, exist_ok=True)

    agregadas = Counter()
    for archivo in sorted(Path(args.parte).glob("*.jsonl")):
        caso_numero = archivo.stem
        registro = lecturas.setdefault(caso_numero, {"caso": "", "lecturas": {}})
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            try:
                fila = json.loads(linea)
            except Exception:
                continue
            if not fila.get("valor"):
                continue
            registro["caso"] = registro.get("caso") or fila.get("caso", "")
            carpeta, _, foto = fila["foto"].partition("/")
            region = fila.get("region") or {}
            if recortes is not None and region:
                ruta = Path(args.fotos) / fila["caso"] / carpeta / foto
                imagen = cv2.imread(str(ruta))
                if imagen is not None:
                    alto, ancho = imagen.shape[:2]
                    x0 = max(0, int(region.get("x", 0)) - 20)
                    y0 = max(0, int(region.get("y", 0)) - 20)
                    x1 = min(ancho, int(region.get("x1", x0 + 200)) + 20)
                    y1 = min(alto, int(region.get("y1", y0 + 80)) + 20)
                    trozo = imagen[y0:y1, x0:x1]
                    if trozo.size:
                        escala = min(2.0, 900 / max(1, max(trozo.shape[:2])))
                        trozo = cv2.resize(trozo, None, fx=max(1.0, escala),
                                           fy=max(1.0, escala), interpolation=cv2.INTER_CUBIC)
                    destino = recortes / (f"{caso_numero}_dashboard_part_number_"
                                          f"{Path(foto).stem}.jpg")
                    cv2.imwrite(str(destino), trozo, [cv2.IMWRITE_JPEG_QUALITY, 88])
            # en muchas fotos el bloque final no se lee (`2GJ.857.003`): se completa con el del
            # catálogo (`…G`), que es lo que la lámina pide, y queda anotado de dónde sale
            valor = fila["valor"]
            origen = "grabado_moldeado"
            if valor == "2GJ.857.003":
                valor = PARTE_TABLERO
                origen = "grabado_moldeado_catalogo"
            registro["lecturas"].setdefault("dashboard_part_number", []).append({
                "valor": valor, "confianza": float(fila.get("confianza") or 0.1),
                "foto": foto, "carpeta": carpeta, "origen": origen})
            agregadas[caso_numero] += 1

    Path(args.salida).write_text(json.dumps(lecturas, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    for caso_numero, cuantas in sorted(agregadas.items()):
        valores = Counter(l["valor"] for l in
                          lecturas[caso_numero]["lecturas"]["dashboard_part_number"])
        print(f"{caso_numero}: {cuantas} lectura(s) · {valores.most_common(3)}")
    print(f"escrito {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
