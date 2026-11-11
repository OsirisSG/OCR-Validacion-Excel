#!/usr/bin/env python3
"""Panel de dudas: la página donde el programa pide ayuda y el usuario decide.

El programa no publica lo que no tiene seguro. En vez de eso, deja la celda vacía y
**avisa aquí**: cada duda trae sus opciones, con la fuente que la propone y dónde mirar
para comprobarla. Lo que se elige se escribe en el Excel con el adaptador que no toca
cabeceras ni fórmulas.

Uso:
    python panel_confirmacion.py --libro libro.xlsx --lecturas lecturas.json
    python panel_confirmacion.py --libro libro.xlsx --base aprendizaje.sqlite3
    (abre http://127.0.0.1:8099)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from utilidades.dudas_y_opciones import lecturas_desde_base, resumen_dudas

AQUI = Path(__file__).resolve().parent

from utilidades.cola_dudas import DudaDesconocida, Estado, NadaQueGuardar

app = FastAPI(title="Panel de dudas · V-Matrix")
ESTADO: Estado | None = None


class Decision(BaseModel):
    id: str
    valor: str | None = None


@app.get("/", response_class=HTMLResponse)
def inicio():
    return HTMLResponse(PAGINA)


@app.get("/api/estado")
def api_estado():
    if ESTADO is None:
        raise HTTPException(503, "panel sin libro cargado")
    return {"libro": str(ESTADO.libro), "hoja": ESTADO.hoja,
            "casos": len(ESTADO.filas),
            "filas_sin_numero_de_caso": ESTADO.sin_numero,
            "silenciadas": {k: v["campo"] for k, v in ESTADO.silenciadas.items()},
            "resumen": resumen_dudas(ESTADO.dudas),
            "decisiones": len(ESTADO.decisiones),
            "ultimo_guardado": ESTADO.ultimo_guardado}


@app.get("/api/dudas")
def api_dudas():
    if ESTADO is None:
        raise HTTPException(503, "panel sin libro cargado")
    return {"dudas": ESTADO.dudas, "decisiones": ESTADO.decisiones,
            "resumen": resumen_dudas(ESTADO.dudas)}


@app.post("/api/decidir")
def api_decidir(decision: Decision):
    if ESTADO is None:
        raise HTTPException(503, "panel sin libro cargado")
    try:
        return ESTADO.decidir(decision.id, decision.valor)
    except DudaDesconocida as error:
        raise HTTPException(404, str(error)) from error


@app.post("/api/guardar")
def api_guardar():
    if ESTADO is None:
        raise HTTPException(503, "panel sin libro cargado")
    try:
        return ESTADO.guardar()
    except NadaQueGuardar as error:
        raise HTTPException(400, str(error)) from error


@app.get("/api/descargar")
def api_descargar():
    if ESTADO is None or ESTADO.ultimo_guardado is None:
        raise HTTPException(404, "todavía no se ha guardado nada")
    return FileResponse(ESTADO.ultimo_guardado["salida"], filename=Path(
        ESTADO.ultimo_guardado["salida"]).name)


PAGINA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel de dudas · V-Matrix</title>
<style>
 :root{--tinta:#12212e;--gris:#5b6b7a;--linea:#dde3e9;--fondo:#f5f7f9;--ok:#0b7a54;
       --alerta:#b4690b;--mal:#a32424;--acento:#1f5fa8}
 *{box-sizing:border-box}
 body{margin:0;font:15px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
      color:var(--tinta);background:var(--fondo)}
 header{background:#0f1c26;color:#fff;padding:14px 20px;display:flex;flex-wrap:wrap;
        align-items:baseline;gap:14px}
 header h1{font-size:17px;margin:0;font-weight:650;letter-spacing:.2px}
 header .meta{color:#9db0c0;font-size:12.5px}
 main{max-width:1020px;margin:0 auto;padding:18px 16px 90px}
 .barra{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:14px}
 .chip{border:1px solid var(--linea);background:#fff;border-radius:999px;padding:5px 11px;
       font-size:12.5px;color:var(--gris);cursor:pointer}
 .chip.on{border-color:var(--acento);color:var(--acento);background:#eef4fb;font-weight:600}
 .duda{background:#fff;border:1px solid var(--linea);border-radius:12px;padding:14px 16px;
       margin-bottom:12px;box-shadow:0 1px 2px rgba(16,32,48,.04)}
 .duda h2{font-size:14.5px;margin:0 0 4px;font-weight:650}
 .caso{font-variant-numeric:tabular-nums;background:#eef2f6;border-radius:6px;padding:1px 7px;
       margin-right:7px;font-size:13px}
 .campo{color:var(--acento);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}
 .motivo{font-size:12px;border-radius:999px;padding:2px 9px;margin-left:8px;font-weight:600}
 .m-conflicto{background:#fdf1e0;color:var(--alerta)}
 .m-sin{background:#eef1f4;color:var(--gris)}
 .detalle{color:var(--gris);font-size:13px;margin:6px 0 10px}
 .donde{font-size:12.5px;color:var(--gris);margin:0 0 10px;padding-left:16px}
 .donde li{margin:1px 0}
 .ops{display:flex;flex-direction:column;gap:6px}
 .op{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--linea);
     border-radius:9px;padding:8px 11px;background:#fbfcfd;cursor:pointer;text-align:left;
     font:inherit;color:inherit;width:100%}
 .op:hover{border-color:#b9c9d8}
 .op.sel{border-color:var(--acento);background:#eef4fb;box-shadow:inset 0 0 0 1px var(--acento)}
 .val{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13.5px;font-weight:650;
      min-width:150px}
 .fuente{font-size:11.5px;color:#fff;background:#7d8b98;border-radius:5px;padding:1px 7px;
         white-space:nowrap}
 .fuente.carpeta,.fuente.barra_video{background:#1f5fa8}
 .fuente.lectura_ocr{background:#0b7a54}
 .fuente.serie{background:#6b4fa8}
 .fuente.otros_casos_del_libro{background:#8a6d3b}
 .fuente.no_lo_tengo{background:#98a4b0}
 .resp{font-size:12px;color:var(--gris)}
 footer{position:fixed;left:0;right:0;bottom:0;background:#fff;border-top:1px solid var(--linea);
        padding:11px 20px;display:flex;gap:14px;align-items:center;justify-content:space-between;
        flex-wrap:wrap}
 button.accion{background:var(--acento);color:#fff;border:0;border-radius:9px;padding:10px 18px;
        font:inherit;font-weight:650;cursor:pointer}
 button.accion:disabled{background:#b7c3ce;cursor:not-allowed}
 button.sec{background:#fff;color:var(--acento);border:1px solid var(--acento)}
 #aviso{font-size:13px;color:var(--ok)}
 .vacio{background:#fff;border:1px dashed var(--linea);border-radius:12px;padding:26px;
        text-align:center;color:var(--gris)}
</style></head><body>
<header>
  <h1>Panel de dudas</h1>
  <span class="meta" id="meta">cargando…</span>
</header>
<main>
  <div class="barra" id="filtros"></div>
  <div id="lista"></div>
</main>
<footer>
  <span id="aviso">Nada elegido todavía.</span>
  <span>
    <button class="accion sec" id="descargar" style="display:none">Descargar Excel</button>
    <button class="accion" id="guardar" disabled>Guardar en Excel</button>
  </span>
</footer>
<script>
let DATOS = {dudas: [], decisiones: {}, resumen: {}};
let filtro = 'todos';

function pintarFiltros() {
  const c = DATOS.resumen.por_motivo || {};
  const chips = [['todos', `Todas (${DATOS.resumen.dudas ?? 0})`],
    ['fuentes_en_conflicto', `Fuentes en conflicto (${c.fuentes_en_conflicto || 0})`],
    ['sin_lectura_valida', `Sin lectura (${c.sin_lectura_valida || 0})`]];
  document.getElementById('filtros').innerHTML = chips.map(([k, t]) =>
    `<button class="chip ${filtro === k ? 'on' : ''}" data-f="${k}">${t}</button>`).join('');
  document.querySelectorAll('.chip').forEach(b => b.onclick = () => { filtro = b.dataset.f; pintarFiltros(); pintarLista(); });
}

function pintarLista() {
  const dudas = DATOS.dudas.filter(d => filtro === 'todos' || d.motivo === filtro);
  if (!dudas.length) {
    document.getElementById('lista').innerHTML = '<div class="vacio">No hay dudas pendientes. Todo lo que el programa pudo leer está en el libro.</div>';
    return;
  }
  document.getElementById('lista').innerHTML = dudas.map(d => {
    const sel = DATOS.decisiones[d.id];
    const opciones = d.opciones.map((o, i) => {
      const valor = o.valor === null ? 'No lo tengo' : o.valor;
      const marcada = sel && String(sel.valor) === String(o.valor);
      return `<button class="op ${marcada ? 'sel' : ''}" data-id="${d.id}" data-val="${o.valor === null ? '' : o.valor}">
        <span class="val">${valor}</span>
        <span class="fuente ${o.fuente}">${o.fuente.replace(/_/g, ' ')}</span>
        <span class="resp">${o.respaldo}${o.confianza ? ' · confianza ' + o.confianza : ''}</span>
      </button>`;
    }).join('');
    const descartadas = (d.opciones_descartadas || []).length
      ? `<div class="detalle">Descartado por la serie: ${d.opciones_descartadas.map(o => o.valor).join(', ')}</div>` : '';
    const donde = (d.donde_mirar || []).length
      ? `<ul class="donde">${d.donde_mirar.map(t => `<li>${t}</li>`).join('')}</ul>` : '';
    return `<section class="duda">
      <h2><span class="caso">${d.caso}</span><span class="campo">${d.campo}</span>
        ${d.columna ? `<span class="resp"> · columna ${d.columna}</span>` : ''}
        <span class="motivo ${d.motivo === 'fuentes_en_conflicto' ? 'm-conflicto' : 'm-sin'}">${d.motivo.replace(/_/g, ' ')}</span></h2>
      <div class="detalle">${d.detalle}</div>
      ${donde}${descartadas}
      <div class="ops">${opciones}</div>
    </section>`;
  }).join('');
  document.querySelectorAll('.op').forEach(b => b.onclick = () => decidir(b.dataset.id, b.dataset.val));
}

async function decidir(id, valor) {
  await fetch('/api/decidir', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id, valor: valor === '' ? null : valor})});
  await cargar();
}

async function cargar() {
  const r = await fetch('/api/dudas'); DATOS = await r.json();
  const e = await (await fetch('/api/estado')).json();
  const n = Object.keys(DATOS.decisiones).length;
  document.getElementById('meta').textContent =
    `${e.casos} casos · ${DATOS.resumen.dudas} dudas · ${e.resumen.con_al_menos_una_opcion} con opciones · ${e.libro.split(/[\\\\/]/).pop()}`;
  document.getElementById('aviso').textContent = n
    ? `${n} decisión(es) elegida(s), sin guardar.` : 'Nada elegido todavía.';
  document.getElementById('guardar').disabled = !n;
  pintarFiltros(); pintarLista();
}

document.getElementById('guardar').onclick = async () => {
  const r = await fetch('/api/guardar', {method: 'POST'});
  if (!r.ok) { document.getElementById('aviso').textContent = 'No se pudo guardar.'; return; }
  const d = await r.json();
  document.getElementById('aviso').textContent =
    `Guardado: ${d.escritos} celdas escritas en ${d.salida.split(/[\\\\/]/).pop()}`;
  document.getElementById('descargar').style.display = 'inline-block';
  await cargar();
};
document.getElementById('descargar').onclick = () => { location.href = '/api/descargar'; };
cargar();
</script></body></html>"""


def main() -> None:
    global ESTADO
    ap = argparse.ArgumentParser(description="Panel de dudas para confirmar campos dudosos")
    ap.add_argument("--libro", required=True, help="libro .xlsx de trabajo")
    ap.add_argument("--lecturas", help="JSON con las lecturas por caso")
    ap.add_argument("--base", help="aprendizaje.sqlite3 de donde sacar las lecturas")
    ap.add_argument("--hoja", default=None)
    ap.add_argument("--mapa", help="JSON {caso: fila} para filas sin número legible")
    ap.add_argument("--puerto", type=int, default=8099)
    args = ap.parse_args()

    libro = Path(args.libro)
    if not libro.is_file():
        raise SystemExit(f"no encuentro el libro: {libro}")
    lecturas: dict = {}
    if args.lecturas:
        lecturas = json.loads(Path(args.lecturas).read_text(encoding="utf-8"))
    elif args.base:
        from openpyxl import load_workbook
        wb = load_workbook(libro, data_only=True)
        ws = wb[args.hoja] if args.hoja else wb[wb.sheetnames[0]]
        casos = [str(int(ws.cell(f, 3).value)) for f in range(8, ws.max_row + 1)
                 if ws.cell(f, 3).value not in (None, "")]
        lecturas = lecturas_desde_base(args.base, casos)
    mapa = json.loads(Path(args.mapa).read_text(encoding="utf-8")) if args.mapa else {}
    ESTADO = Estado(libro, lecturas, args.hoja, mapa)

    import uvicorn
    print(f"Panel de dudas · libro: {libro} · {len(ESTADO.filas)} casos · "
          f"{len(ESTADO.dudas)} dudas · http://127.0.0.1:{args.puerto}")
    uvicorn.run(app, host="0.0.0.0", port=args.puerto, log_level="warning")


if __name__ == "__main__":
    main()
