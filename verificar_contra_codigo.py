#!/usr/bin/env python3
"""P42 · contrastar el libro contra el CÓDIGO, que es la fuente, no contra el libro de referencia.

    python3 verificar_contra_codigo.py --libro versionV16_0_50.xlsx \
        --dm-tablero /tmp/p42/dm_v2.json --dm-modulo /home/user/modulo_dm.json \
        --fotos /var/tmp/fotos --html /home/user/vmatrix/codigo_vs_libro.html

Por qué existe: el marcador contra `Book-10-Examples_CORREGIDO.xlsx` dice «coincide con la
referencia», que no es lo mismo que «es verdad». Cuando la etiqueta lleva un DataMatrix, el dato
del código es mejor juez que cualquier libro: lo puso la máquina que imprimió la etiqueta.

Lo que hace:
  * compara, campo a campo, lo que trae el código con lo que dice el libro y con lo que dice la
    referencia;
  * dice en cada caso quién tiene razón y con qué se sostiene;
  * genera un HTML con el recorte de la etiqueta de las celdas en discusión, para que se pueda
    mirar a ojo (con giro y zoom).

No escribe nada. Las correcciones se aplican aparte, a propósito.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path

import cv2
from openpyxl import load_workbook

COLUMNAS = {7: "module_part_number", 9: "module_serial_number", 10: "module_date",
            15: "dashboard_part_number", 16: "dashboard_serial_number"}


def leer_libro(ruta: Path) -> dict[str, dict[str, str]]:
    hoja = load_workbook(ruta, data_only=True)["Versuchsmatrix"]
    filas: dict[str, dict[str, str]] = {}
    for fila in range(8, hoja.max_row + 1):
        valor = hoja.cell(fila, 3).value
        if valor in (None, ""):
            continue
        numero = str(valor).strip()
        if len(numero) != 6 or not numero.isdigit():
            continue
        registro = {}
        for columna, campo in COLUMNAS.items():
            dato = hoja.cell(fila, columna).value
            if dato is None:
                registro[campo] = ""
            elif hasattr(dato, "date"):
                registro[campo] = str(dato.date())
            else:
                registro[campo] = str(dato).strip()
        filas[numero] = registro
    return filas


def fecha_de_ddmmyy(texto: str) -> str:
    """`100425` -> `2025-04-10`. Pura."""
    if not re.fullmatch(r"\d{6}", texto or ""):
        return ""
    dia, mes, anio = texto[:2], texto[2:4], texto[4:]
    return f"20{anio}-{mes}-{dia}"


def serie_del_modulo(payload: str) -> str:
    """La serie del módulo, tal cual viene entre asteriscos. Pura."""
    encontrado = re.search(r"\*([^*]+)\*", payload or "")
    return encontrado.group(1).strip() if encontrado else ""


def comparar(caso: str, campo: str, codigo: str, libro: str, referencia: str) -> dict:
    """Quién tiene razón en una celda. Pura.

    `codigo` vacío = el código no dice nada de ese campo: no se opina.
    """
    codigo = (codigo or "").strip()
    libro = (libro or "").strip()
    referencia = (referencia or "").strip()
    if not codigo:
        return {"veredicto": "sin dato en el código", "corregir": False}
    if libro == codigo:
        if referencia and referencia != codigo:
            return {"veredicto": "el libro y el código coinciden; la referencia no",
                    "corregir": False,
                    "nota": "la referencia difiere del código: se queda el libro"}
        return {"veredicto": "coincide con el código", "corregir": False}
    if not libro:
        return {"veredicto": "el libro está vacío y el código tiene dato",
                "corregir": True, "nuevo": codigo}
    return {"veredicto": "el libro NO coincide con el código", "corregir": True, "nuevo": codigo}


def caja_del_datamatrix(imagen):
    import zxingcpp
    gris = cv2.cvtColor(cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(
        cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)), cv2.COLOR_GRAY2BGR)
    for escala in (1.0, 0.65, 0.45):
        for vista in (imagen, gris):
            muestra = vista if escala == 1.0 else cv2.resize(
                vista, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
            try:
                lecturas = zxingcpp.read_barcodes(muestra,
                                                 formats=zxingcpp.BarcodeFormat.DataMatrix)
            except Exception:                                    # noqa: BLE001
                continue
            for barcode in lecturas:
                if not getattr(barcode, "valid", False):
                    continue
                puntos = [barcode.position.top_left, barcode.position.top_right,
                          barcode.position.bottom_right, barcode.position.bottom_left]
                xs = [p.x / escala for p in puntos]
                ys = [p.y / escala for p in puntos]
                return min(xs), min(ys), max(xs), max(ys)
    return None


def recorte(ruta: Path, lado_mayor: int = 1000):
    imagen = cv2.imread(str(ruta))
    if imagen is None:
        return None
    caja = caja_del_datamatrix(imagen)
    alto, ancho = imagen.shape[:2]
    if caja:
        x0, y0, x1, y1 = caja
        ancho_caja, alto_caja = x1 - x0, y1 - y0
        x0 = int(max(0, x0 - ancho_caja * 1.6)); x1 = int(min(ancho, x1 + ancho_caja * 1.6))
        y0 = int(max(0, y0 - alto_caja * 1.2)); y1 = int(min(alto, y1 + alto_caja * 1.2))
        trozo = imagen[y0:y1, x0:x1]
    else:
        trozo = imagen[int(alto * .15):int(alto * .85), int(ancho * .15):int(ancho * .85)]
    if trozo.size == 0:
        return None
    factor = lado_mayor / max(trozo.shape[:2])
    if factor > 1:
        trozo = cv2.resize(trozo, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    ok, bufer = cv2.imencode(".jpg", trozo, [int(cv2.IMWRITE_JPEG_QUALITY), 84])
    return "data:image/jpeg;base64," + base64.b64encode(bufer.tobytes()).decode("ascii") if ok else None


TARJETA = """
  <section class="celda">
    <div class="izq">
      <div class="marco"><img src="{imagen}" alt="etiqueta del módulo" style="transform:rotate({giro}deg)"></div>
      <div class="pie2">{foto}</div>
    </div>
    <div class="der">
      <div class="tit">{caso} · {campo}</div>
      <table>
        <tr><th>el CÓDIGO dice</th><td class="mono ok">{codigo}</td></tr>
        <tr><th>el LIBRO dice</th><td class="mono {clase_libro}">{libro}</td></tr>
        <tr><th>la REFERENCIA dice</th><td class="mono {clase_ref}">{referencia}</td></tr>
      </table>
      <div class="veredicto {clase}">{veredicto}</div>
      <div class="nota2">{nota}</div>
    </div>
  </section>
"""

PLANTILLA = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Código vs libro · P42</title>
<style>
 :root{{--fondo:#0f1115;--panel:#171a21;--panel2:#1f232c;--borde:#2b3140;--texto:#e8ecf3;
        --tenue:#98a2b3;--bien:#3ddc97;--mal:#ff6b6b;--aviso:#ffb020;--acento:#5b9dff}}
 *{{box-sizing:border-box}}
 body{{margin:0;padding:28px;background:radial-gradient(1200px 600px at 50% -10%,#1b2233,#0f1115 55%);
      color:var(--texto);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
 h1{{font-size:20px;margin:0 0 4px}}
 .sub{{color:var(--tenue);font-size:13px;margin-bottom:22px}}
 .celda{{display:grid;grid-template-columns:1.05fr 1fr;gap:0;background:var(--panel);
         border:1px solid var(--borde);border-radius:14px;overflow:hidden;margin-bottom:18px;
         box-shadow:0 18px 44px rgba(0,0,0,.45)}}
 @media (max-width:860px){{.celda{{grid-template-columns:1fr}}}}
 .izq{{background:#0b0d11;padding:16px;border-right:1px solid var(--borde)}}
 .marco{{height:clamp(200px,40vh,380px);display:grid;place-items:center;overflow:hidden;
         border-radius:10px;border:1px solid var(--borde);background:#0b0d11}}
 .marco img{{max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;
             transition:transform .2s}}
 .pie2{{color:var(--tenue);font-size:11.5px;margin-top:8px;word-break:break-all}}
 .der{{padding:20px 22px}}
 .tit{{font-weight:700;font-size:17px;margin-bottom:12px}}
 table{{width:100%;border-collapse:collapse;font-size:13.5px}}
 th{{text-align:left;color:var(--tenue);font-weight:600;padding:7px 0;width:44%;vertical-align:top}}
 td{{padding:7px 0}}
 .mono{{font-family:ui-monospace,Menlo,monospace}}
 .ok{{color:var(--bien)}} .no{{color:var(--mal)}} .du{{color:var(--aviso)}}
 .veredicto{{margin-top:14px;padding:11px 13px;border-radius:10px;font-size:13.5px;font-weight:600}}
 .v{{background:#152a22;border:1px solid #1e4436;color:#8ff0c0}}
 .x{{background:#2a1618;border:1px solid #4a2226;color:#ffb3b3}}
 .w{{background:#242019;border:1px solid #4a3a1c;color:#ffd591}}
 .nota2{{color:var(--tenue);font-size:12.5px;margin-top:10px}}
 h2{{font-size:16px;margin:26px 0 12px}}
 table.todo{{border-collapse:collapse;width:100%;font-size:13px;background:var(--panel);
             border:1px solid var(--borde);border-radius:12px;overflow:hidden}}
 table.todo th,table.todo td{{padding:8px 10px;border-bottom:1px solid #232936;text-align:left}}
 table.todo th{{color:var(--tenue);font-weight:600;background:#1b2029}}
 table.todo tr:last-child td{{border-bottom:0}}
</style></head><body>
<h1>El código frente al libro</h1>
<div class="sub">La etiqueta lleva DataMatrix: lo que trae el código lo puso la máquina que imprimió.
Cuando el libro y el código no coinciden, el código es el juez. Aquí están las celdas en discusión,
con su recorte para mirarlas a ojo.</div>
{tarjetas}
<h2>Los 5 campos que el código puede zanjar, caso por caso</h2>
<table class="todo">{tabla}</table>
<div class="nota2" style="margin-top:14px">Generado por <span class="mono">verificar_contra_codigo.py</span>.
El recorte se puede girar: abre este archivo en el navegador y usa la rueda del botón derecho, o
sencillamente amplía con Ctrl + rueda.</div>
</body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Contrasta el libro contra los DataMatrix")
    ap.add_argument("--libro", required=True)
    ap.add_argument("--referencia", default="")
    ap.add_argument("--dm-tablero", required=True)
    ap.add_argument("--dm-modulo", required=True)
    ap.add_argument("--fotos", default="")
    ap.add_argument("--html", default="")
    args = ap.parse_args()

    libro = leer_libro(Path(args.libro))
    referencia = leer_libro(Path(args.referencia)) if args.referencia else {}
    tablero = json.loads(Path(args.dm_tablero).read_text(encoding="utf-8"))
    modulo = json.loads(Path(args.dm_modulo).read_text(encoding="utf-8"))

    filas_tabla = []
    contadores = {"coincide": 0, "coincide_referencia_no": 0, "discrepa": 0, "sin_dato": 0}
    correcciones = []
    discusion = []
    for caso in sorted(libro):
        del_tablero = (tablero.get(caso) or [{}])[0]
        del_modulo = modulo.get(caso) or {}
        candidatos = {
            "dashboard_part_number": str(del_tablero.get("parte") or ""),
            "dashboard_serial_number": str(del_tablero.get("valor") or ""),
            "module_part_number": str(del_modulo.get("parte") or "").replace("2GJ880204J",
                                                                            "2GJ.880.204.J"),
            "module_serial_number": serie_del_modulo(str(del_modulo.get("payload") or "")),
            "module_date": fecha_de_ddmmyy(str(del_modulo.get("fecha_ddmmyy") or "")),
        }
        for campo, codigo in candidatos.items():
            nuestro = libro.get(caso, {}).get(campo, "")
            suyo = (referencia.get(caso) or {}).get(campo, "")
            juicio = comparar(caso, campo, codigo, nuestro, suyo)
            marca = "ok" if juicio["veredicto"].startswith("coincide") else \
                    ("du" if juicio["veredicto"].startswith("el libro y el código") else "no")
            if juicio["veredicto"].startswith("coincide"):
                contadores["coincide"] += 1
            elif juicio["veredicto"].startswith("el libro y el código"):
                contadores["coincide_referencia_no"] += 1
            elif not codigo:
                contadores["sin_dato"] += 1
            else:
                contadores["discrepa"] += 1
            filas_tabla.append(
                f"<tr><td>{caso}</td><td>{campo}</td>"
                f"<td class='mono ok'>{codigo or '—'}</td>"
                f"<td class='mono {marca}'>{nuestro or '—'}</td>"
                f"<td class='mono'>{suyo or '—'}</td>"
                f"<td>{juicio['veredicto']}</td></tr>")
            foto_celda = (str(del_modulo.get("foto") or "") if campo.startswith("module")
                          else f"{del_tablero.get('carpeta', '')}/{del_tablero.get('foto', '')}".strip("/"))
            if juicio.get("corregir"):
                correcciones.append({"caso": caso, "campo": campo, "antes": nuestro,
                                     "despues": juicio["nuevo"], "codigo": codigo,
                                     "foto": foto_celda})
            if not juicio["veredicto"].startswith("coincide") and codigo:
                discusion.append({"caso": caso, "campo": campo, "codigo": codigo,
                                  "libro": nuestro, "referencia": suyo, "juicio": juicio,
                                  "foto": foto_celda,
                                  "payload": del_modulo.get("payload", "")})

    tarjetas = []
    for entrada in discusion:
        imagen = ""
        if args.fotos and entrada["foto"]:
            carpeta = next((p for p in Path(args.fotos).iterdir()
                            if p.is_dir() and p.name.startswith(entrada["caso"])), None)
            if carpeta:
                ruta = carpeta / entrada["foto"].split("/")[0] / entrada["foto"].split("/")[-1]
                if ruta.exists():
                    imagen = recorte(ruta) or ""
        clase = "x" if entrada["juicio"].get("corregir") else "w"
        tarjetas.append(TARJETA.format(
            imagen=imagen, giro=0, foto=entrada["foto"] or "sin foto",
            caso=entrada["caso"], campo=entrada["campo"],
            codigo=entrada["codigo"] or "—",
            libro=entrada["libro"] or "—",
            referencia=entrada["referencia"] or "—",
            clase_libro="ok" if entrada["libro"] == entrada["codigo"] else "no",
            clase_ref="ok" if entrada["referencia"] == entrada["codigo"] else "no",
            veredicto=f"{entrada['juicio']['veredicto']}"
                      + (f" → corregir a «{entrada['juicio']['nuevo']}»"
                         if entrada["juicio"].get("corregir") else " → no se toca"),
            clase=clase,
            nota=(f"payload del módulo: <span class='mono'>{entrada['payload'][:70]}</span>"
                  if entrada["payload"] else "")))

    if args.html:
        Path(args.html).write_text(PLANTILLA.format(tarjetas="".join(tarjetas),
                                                    tabla="".join(filas_tabla)), encoding="utf-8")
        print(f"html: {args.html}")

    print(f"celdas contrastadas contra el código: {len(filas_tabla)}")
    print(f"  el libro coincide con el código .......... {contadores['coincide']}")
    print(f"  coincide y la referencia no ............. {contadores['coincide_referencia_no']}")
    print(f"  el libro NO coincide con el código ...... {contadores['discrepa']}")
    print(f"  el código no dice nada de ese campo ..... {contadores['sin_dato']}")
    if correcciones:
        print("\nCORRECCIONES PROPUESTAS (no aplicadas):")
        for c in correcciones:
            print(f"  {c['caso']} {c['campo']}: {c['antes']!r} -> {c['despues']!r} "
                  f"(código {c['codigo']!r})")
    if discusion:
        print("\nEN DISCUSIÓN:")
        for d in discusion:
            print(f"  {d['caso']} {d['campo']}: código {d['codigo']!r} · libro {d['libro']!r} · "
                  f"referencia {d['referencia']!r} -> {d['juicio']['veredicto']}")
    if args.html:
        Path(args.html.replace(".html", "_correcciones.json")).write_text(
            json.dumps(correcciones, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
