#!/usr/bin/env python3
"""Auditoría celda por celda del rescate: qué había, qué se puso, con qué pruebas (P12)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from openpyxl import load_workbook

from rescatar_libro import ENCABEZADOS

ESTADOS = {"ya_estaba": ("#2fbf71", "ya estaba en tu libro"),
           "rescatada": ("#4da3ff", "rescatada de Trazabilidad"),
           "vacia": ("#8b9ab1", "sigue vacía (nada leído)")}


def leer(ruta: Path, hoja="Versuchsmatrix", fila_encabezado=7):
    ws = load_workbook(ruta, data_only=True)[hoja]
    cols = {}
    for c in range(1, ws.max_column + 1):
        t = str(ws.cell(fila_encabezado, c).value or "").strip().lower()
        if t in ENCABEZADOS:
            cols[c] = (ENCABEZADOS[t], t)
    casos = []
    for f in range(fila_encabezado + 1, ws.max_row + 1):
        num = ws.cell(f, 3).value
        if num in (None, ""):
            continue
        casos.append((str(num), f, {campo: ws.cell(f, c).value for c, (campo, _) in cols.items()
                                    for _ in [0]}))
    titulos = {campo: t for campo, t in cols.values()}
    return casos, titulos


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--antes", required=True)
    ap.add_argument("--despues", required=True)
    ap.add_argument("--rescate", required=True, help=".rescate.json")
    ap.add_argument("--salida", default="AUDITORIA_CELDAS.html")
    a = ap.parse_args(argv)

    antes, titulos = leer(Path(a.antes))
    despues, _ = leer(Path(a.despues))
    plan = {(p["caso"], p["campo"]): p for p in json.loads(Path(a.rescate).read_text("utf-8"))["plan"]}

    total = len(despues) * len(titulos)
    cuenta = {"ya_estaba": 0, "rescatada": 0, "vacia": 0}
    bloques = []
    for (caso, fila, valores), (_, _, nuevos) in zip(antes, despues):
        filas_html, resumen_caso = [], {"ya_estaba": 0, "rescatada": 0, "vacia": 0}
        for campo, titulo in titulos.items():
            previo = valores.get(campo)
            actual = nuevos.get(campo)
            if previo not in (None, ""):
                estado, valor, detalle = "ya_estaba", previo, "venía de la corrida"
            elif actual not in (None, ""):
                estado, valor = "rescatada", actual
                p = plan.get((caso, campo)) or {}
                detalle = f"{p.get('origen', '?')} · {p.get('votos', 0)} lectura(s) · {p.get('regla', '')}"
            else:
                estado, valor, detalle = "vacia", "—", "no hay lectura de este campo en el proyecto"
            cuenta[estado] += 1
            resumen_caso[estado] += 1
            color = ESTADOS[estado][0]
            filas_html.append(
                f'<tr data-estado="{estado}"><td class="campo">{titulo}</td>'
                f'<td class="valor">{valor}</td>'
                f'<td><span class="punto" style="background:{color}"></span>{ESTADOS[estado][1]}</td>'
                f'<td class="detalle">{detalle}</td></tr>')
        bloques.append(
            f'<section class="caso"><h2>Caso {caso} '
            f'<span class="cuenta">{resumen_caso["ya_estaba"]} ya · {resumen_caso["rescatada"]} nuevas · '
            f'{resumen_caso["vacia"]} vacías</span></h2>'
            f'<table><thead><tr><th>Columna</th><th>Valor</th><th>Estado</th><th>De dónde sale</th></tr>'
            f'</thead><tbody>{"".join(filas_html)}</tbody></table></section>')

    html = PLANTILLA.replace("__YA__", str(cuenta["ya_estaba"])).replace("__NUEVAS__", str(cuenta["rescatada"])) \
        .replace("__VACIAS__", str(cuenta["vacia"])).replace("__TOTAL__", str(total)) \
        .replace("__PCT__", f"{100 * (cuenta['ya_estaba'] + cuenta['rescatada']) / total:.1f}") \
        .replace("__PCT_ANTES__", f"{100 * cuenta['ya_estaba'] / total:.1f}") \
        .replace("__BLOQUES__", "".join(bloques))
    Path(a.salida).write_text(html, encoding="utf-8")
    print(f"{a.salida}: {total} celdas · {cuenta}")
    return 0


PLANTILLA = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Auditoría celda por celda · V-Matrix</title><style>
:root{--fondo:#0b1220;--panel:#111b2e;--panel2:#16233a;--borde:#1f3350;--texto:#e8eef9;
--tenue:#94a7c4;--acento:#4da3ff;--ok:#2fbf71;--radio:14px}
@media (prefers-color-scheme:light){:root{--fondo:#f5f7fb;--panel:#fff;--panel2:#eef3f9;
--borde:#dbe4f0;--texto:#12203a;--tenue:#5b6f8c}}
*{box-sizing:border-box}body{margin:0;background:var(--fondo);color:var(--texto);
font-family:ui-sans-serif,system-ui,"Segoe UI",Roboto,Arial,sans-serif;line-height:1.5}
.w{max-width:1020px;margin:0 auto;padding:30px 18px 70px}
h1{font-size:1.5rem;letter-spacing:-.02em;margin:0 0 4px}
.sub{color:var(--tenue);margin:0 0 22px;font-size:.9rem}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:22px}
.kpi{background:var(--panel);border:1px solid var(--borde);border-radius:var(--radio);padding:14px 16px}
.kpi b{display:block;font-size:1.7rem}.kpi span{color:var(--tenue);font-size:.78rem;text-transform:uppercase;letter-spacing:.05em}
.filtros{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}
.filtros button{border:1px solid var(--borde);background:var(--panel2);color:var(--texto);
padding:7px 13px;border-radius:999px;cursor:pointer;font:inherit;font-size:.85rem}
.filtros button[aria-pressed=true]{border-color:var(--acento);color:var(--acento)}
.caso{background:var(--panel);border:1px solid var(--borde);border-radius:var(--radio);
padding:14px 16px;margin-bottom:14px}
.caso h2{font-size:1rem;margin:0 0 10px;display:flex;justify-content:space-between;
gap:12px;flex-wrap:wrap;align-items:baseline}
.cuenta{color:var(--tenue);font-size:.8rem;font-weight:500}
table{width:100%;border-collapse:collapse;font-size:.87rem}
th{text-align:left;color:var(--tenue);font-weight:600;font-size:.75rem;text-transform:uppercase;
letter-spacing:.05em;padding:6px 8px;border-bottom:1px solid var(--borde)}
td{padding:6px 8px;border-bottom:1px solid var(--panel2);vertical-align:top}
tr:last-child td{border-bottom:none}
.campo{color:var(--tenue);width:26%}.valor{font-family:ui-monospace,monospace;width:22%}
.detalle{color:var(--tenue);font-size:.8rem}
.punto{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
footer{color:var(--tenue);font-size:.8rem;text-align:center;margin-top:26px}
</style></head><body><div class="w">
<h1>Auditoría celda por celda</h1>
<p class="sub">10 casos × 20 columnas = __TOTAL__ celdas · cobertura __PCT_ANTES__ % → __PCT__ %</p>
<div class="kpis">
<div class="kpi"><b>__YA__</b><span>ya venían</span></div>
<div class="kpi"><b>__NUEVAS__</b><span>rescatadas</span></div>
<div class="kpi"><b>__VACIAS__</b><span>siguen vacías</span></div>
<div class="kpi"><b>__PCT__%</b><span>cobertura</span></div></div>
<div class="filtros">
<button aria-pressed="true" data-f="todo">Todas</button>
<button aria-pressed="false" data-f="rescatada">Sólo rescatadas</button>
<button aria-pressed="false" data-f="vacia">Sólo vacías</button>
<button aria-pressed="false" data-f="ya_estaba">Sólo las que ya estaban</button></div>
__BLOQUES__
<footer>V-Matrix · el valor «—» significa que no se inventó nada: no había lectura.</footer></div>
<script>
document.querySelectorAll('.filtros button').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.filtros button').forEach(o=>o.setAttribute('aria-pressed','false'));
  b.setAttribute('aria-pressed','true');
  const f=b.dataset.f;
  document.querySelectorAll('tr[data-estado]').forEach(tr=>{
    tr.style.display=(f==='todo'||tr.dataset.estado===f)?'':'none';
  });
}));
</script></body></html>"""

if __name__ == "__main__":
    raise SystemExit(main())
