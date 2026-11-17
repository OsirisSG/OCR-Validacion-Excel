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


# P48 · fotos de la evidencia. Solo se sirven las rutas que ya están en las dudas (lista
# cerrada por token): el panel no puede leer ningún otro archivo de la computadora.
FOTOS: dict[str, dict] = {}
_CACHE_FOTOS: dict[tuple, bytes] = {}


def _token(*partes) -> str:
    import hashlib
    return hashlib.sha1("|".join(str(p) for p in partes).encode("utf-8")).hexdigest()[:16]


def _para_cliente(dudas: list[dict]) -> list[dict]:
    """Copia de las dudas con la evidencia convertida en tokens (sin rutas de disco)."""
    salida = []
    for duda in dudas:
        opciones = []
        for opcion in duda.get("opciones") or []:
            fotos = []
            for ev in opcion.get("evidencia") or []:
                dato = {"foto": ev.get("foto", ""), "fuente": ev.get("fuente", ""),
                        "texto": ev.get("texto", ""), "con_caja": bool(ev.get("caja"))}
                if ev.get("ruta") and Path(ev["ruta"]).is_file():
                    dato["token"] = _token(ev["ruta"], ev.get("caja"), ev.get("giro"))
                    FOTOS[dato["token"]] = {"ruta": ev["ruta"], "caja": ev.get("caja"),
                                            "giro": ev.get("giro") or 0}
                if ev.get("recorte") and Path(ev["recorte"]).is_file():
                    dato["token_recorte"] = _token(ev["recorte"])
                    FOTOS[dato["token_recorte"]] = {"ruta": ev["recorte"], "caja": None, "giro": 0}
                fotos.append(dato)
            opciones.append({**{k: v for k, v in opcion.items() if k != "evidencia"}, "fotos": fotos})
        salida.append({**duda, "opciones": opciones})
    return salida


def _dibujar(dato: dict, tam: str) -> bytes:
    import cv2
    import numpy as np
    imagen = cv2.imdecode(np.fromfile(dato["ruta"], dtype=np.uint8), cv2.IMREAD_COLOR)
    if imagen is None:
        raise HTTPException(415, "no se pudo abrir la imagen")
    if dato.get("giro"):
        from ocr_engine import rotar_imagen_libre       # mismo giro que usó el OCR
        imagen = rotar_imagen_libre(imagen, float(dato["giro"]))
    alto, ancho = imagen.shape[:2]
    caja = [int(v) for v in dato["caja"]] if dato.get("caja") else None
    if caja and (caja[0] >= ancho or caja[1] >= alto or caja[0] + caja[2] <= 0 or caja[1] + caja[3] <= 0):
        caja = None                                     # la caja no cae en esta foto: sin recuadro
    x0, y0 = 0, 0
    if caja and tam == "mini":                          # la miniatura enfoca el área leída
        x, y, w, h = caja
        cx, cy = x + w / 2, y + h / 2
        lado = max(w, h) * 1.6 + 60
        x0, y0 = int(max(0, cx - lado)), int(max(0, cy - lado * 0.75))
        x1, y1 = int(min(ancho, cx + lado)), int(min(alto, cy + lado * 0.75))
        if x1 > x0 and y1 > y0:
            imagen = imagen[y0:y1, x0:x1]
        else:
            x0, y0 = 0, 0
    limite = 1600 if tam == "grande" else 260
    factor = min(1.0, limite / max(imagen.shape[:2]))
    if factor < 1:
        imagen = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    if caja:                                            # el recuadro se dibuja ya a escala
        x, y, w, h = caja
        grosor = 2 if tam == "mini" else 3
        m = 3 + grosor
        p0 = (int((x - x0) * factor) - m, int((y - y0) * factor) - m)
        p1 = (int((x - x0 + w) * factor) + m, int((y - y0 + h) * factor) + m)
        cv2.rectangle(imagen, p0, p1, (0, 140, 255), grosor)
    ok, datos = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise HTTPException(500, "no se pudo preparar la imagen")
    return datos.tobytes()


@app.get("/api/foto/{token}")
def api_foto(token: str, tam: str = "mini"):
    from fastapi.responses import Response
    dato = FOTOS.get(token)
    if dato is None:
        raise HTTPException(404, "foto no disponible")
    clave = (token, tam)
    if clave not in _CACHE_FOTOS:
        if len(_CACHE_FOTOS) > 400:
            _CACHE_FOTOS.clear()
        _CACHE_FOTOS[clave] = _dibujar(dato, "grande" if tam == "grande" else "mini")
    return Response(_CACHE_FOTOS[clave], media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600"})


class Lote(BaseModel):
    ids: list[str]


@app.post("/api/decidir_lote")
def api_decidir_lote(lote: Lote):
    """P49 · «usar la recomendada» en varias dudas a la vez (p. ej. el motivo en los 10 casos)."""
    if ESTADO is None:
        raise HTTPException(503, "panel sin libro cargado")
    hechas = []
    for id_duda in lote.ids:
        duda = ESTADO.por_id.get(id_duda)
        recomendada = (duda or {}).get("opcion_recomendada")
        if duda is None or recomendada in (None, ""):
            continue
        hechas.append(ESTADO.decidir(id_duda, recomendada))
    return {"decididas": len(hechas)}


class Decision(BaseModel):
    id: str
    valor: str


class Varias(BaseModel):
    decisiones: list[Decision]


@app.post("/api/decidir_varias")
def api_decidir_varias(varias: Varias):
    """P52 · varias dudas, cada una con SU valor (p. ej. la serie verificada de cada tablero).

    Solo se acepta un valor que sea una de las opciones de esa duda: el panel no inventa."""
    if ESTADO is None:
        raise HTTPException(503, "panel sin libro cargado")
    hechas = 0
    for d in varias.decisiones:
        duda = ESTADO.por_id.get(d.id)
        if duda is None or d.valor not in {str(o.get("valor")) for o in duda.get("opciones") or []}:
            continue
        ESTADO.decidir(d.id, d.valor)
        hechas += 1
    return {"decididas": hechas}


class Revision(BaseModel):
    campo: str
    valor: str


@app.post("/api/revisar")
def api_revisar(revision: Revision):
    """P48 · «otro valor»: se comprueba la forma del campo; si no cuadra se avisa, no se bloquea."""
    from datetime import datetime

    from utilidades.validacion_formas import revisar_forma
    texto = revision.valor.strip()
    if revision.campo.endswith("date"):                 # fechas: se aceptan las formas del libro
        for formato in ("%Y-%m-%d", "%d.%m.%y", "%d.%m.%Y", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y"):
            try:
                return {"valido": True, "motivo": "",
                        "valor": datetime.strptime(texto, formato).strftime("%Y-%m-%d")}
            except ValueError:
                continue
        return {"valido": False, "motivo": "no se reconoce como fecha (ej. 2025-04-10 o 10.04.25)",
                "valor": texto}
    resultado = revisar_forma(revision.campo, texto)
    return {"valido": bool(resultado.get("valido")), "motivo": resultado.get("motivo") or "",
            "valor": resultado.get("valor") or texto}


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
    return {"dudas": _para_cliente(ESTADO.dudas), "decisiones": ESTADO.decisiones,
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
 .pieza{font-size:12.5px;color:var(--gris);margin:2px 0 6px}
 .lotes{background:#fff;border:1px solid var(--linea);border-radius:12px;padding:10px 14px;margin-bottom:14px}
 .lotes h3{font-size:13px;margin:0 0 6px;color:var(--gris);font-weight:600}
 .lote{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:5px 0;
       border-top:1px solid #eef1f4;font-size:13px}
 .lote:first-of-type{border-top:0}
 .lote b{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
 .lote button{font:inherit;font-size:12px;border:1px solid var(--acento);color:var(--acento);background:#fff;
              border-radius:7px;padding:3px 10px;cursor:pointer;white-space:nowrap}
 .reco{font-size:11px;color:var(--ok);font-weight:600;margin-left:auto;white-space:nowrap}
 .pieza b{color:var(--tinta);font-weight:600}
 .opw{display:flex;gap:8px;align-items:stretch}
 .opw .op{flex:1}
 .minis{display:flex;gap:5px;align-items:center}
 .minis img{height:56px;width:auto;max-width:96px;object-fit:cover;border-radius:6px;
            border:1px solid var(--linea);cursor:zoom-in;background:#eef2f6}
 .minis img:hover{border-color:#b9c9d8}
 .minis .sinfoto{font-size:11px;color:#9aa7b3;padding:0 4px;white-space:nowrap}
 .otro{margin-top:6px;text-align:right}
 .otro a{font-size:12px;color:#8a97a3;cursor:pointer;text-decoration:none;border-bottom:1px dotted #c3ccd4}
 .otro a:hover{color:var(--acento);border-color:var(--acento)}
 .otro form{display:inline-flex;gap:6px;align-items:center}
 .otro form[hidden],.otro a[hidden]{display:none}
 .otro input{font:inherit;font-size:13px;border:1px solid var(--linea);border-radius:7px;padding:4px 8px;
             width:210px;background:#fbfcfd}
 .otro input:focus{outline:none;border-color:#9fb6cc;background:#fff}
 .otro button{font:inherit;font-size:12px;border:1px solid var(--linea);background:#fff;border-radius:7px;
              padding:4px 10px;color:var(--gris);cursor:pointer}
 .otro .forma{display:block;font-size:11.5px;color:var(--alerta);margin-top:3px}
 .propio{font-size:12.5px;color:var(--acento);margin-top:6px}
 #visor{position:fixed;inset:0;background:rgba(10,18,26,.82);display:none;align-items:center;
        justify-content:center;flex-direction:column;z-index:20;cursor:zoom-out;padding:18px}
 #visor img{max-width:96vw;max-height:84vh;border-radius:8px;background:#fff}
 #visor .pie{color:#dfe7ee;font-size:13px;margin-top:10px;text-align:center;max-width:90vw}
</style></head><body>
<header>
  <h1>Panel de dudas</h1>
  <span class="meta" id="meta">cargando…</span>
</header>
<main>
  <div class="barra" id="filtros"></div>
  <div id="lotes"></div>
  <div id="lista"></div>
</main>
<div id="visor"><img id="visor-img" alt=""><div class="pie" id="visor-pie"></div></div>
<footer>
  <span id="aviso">Nada elegido todavía.</span>
  <span>
    <button class="accion sec" id="descargar" style="display:none">Descargar Excel</button>
    <button class="accion" id="guardar" disabled>Guardar en Excel</button>
  </span>
</footer>
<script>
let DATOS = {dudas: [], decisiones: {}, resumen: {}};
let filtro = 'con';

function conPropuesta(d) { return d.opciones.some(o => o.valor !== null); }

function pintarFiltros() {
  const con = DATOS.dudas.filter(conPropuesta).length, sin = DATOS.dudas.length - con;
  const c = DATOS.resumen.por_motivo || {};
  const chips = [['con', `Con propuesta (${con})`],
    ['fuentes_en_conflicto', `Fuentes en conflicto (${c.fuentes_en_conflicto || 0})`],
    ['sin', `Sin propuesta (${sin})`], ['todos', `Todas (${DATOS.dudas.length})`]];
  document.getElementById('filtros').innerHTML = chips.map(([k, t]) =>
    `<button class="chip ${filtro === k ? 'on' : ''}" data-f="${k}">${t}</button>`).join('');
  document.querySelectorAll('.chip').forEach(b => b.onclick = () => { filtro = b.dataset.f; pintarFiltros(); pintarLista(); });
  pintarLotes();
}

function pintarLotes() {
  // P49 · una fila por campo con la misma recomendación en varios casos: se acepta de una vez
  const grupos = {};
  DATOS.dudas.filter(conPropuesta).forEach(d => {
    if (DATOS.decisiones[d.id]) return;
    const reco = d.opciones.find(o => o.valor !== null);
    const k = d.campo + '||' + reco.valor;
    (grupos[k] = grupos[k] || {campo: d.campo, pieza: d.pieza, valor: reco.valor, fuente: reco.fuente, ids: []}).ids.push(d.id);
  });
  const filas = Object.values(grupos).filter(g => g.ids.length >= 2).sort((a, b) => b.ids.length - a.ids.length);
  // P52 · series verificadas por dígito de control: cada caso con SU serie, una decisión para todas
  const verif = {completa: [], sin: []};
  DATOS.dudas.forEach(d => {
    if (DATOS.decisiones[d.id]) return;
    const c = d.opciones.find(o => o.fuente === 'serie_verificada' || (o.fuentes || []).includes('serie_verificada'));
    const b = d.opciones.find(o => o.fuente === 'serie_verificada_sin_control' || (o.fuentes || []).includes('serie_verificada_sin_control'));
    if (c) verif.completa.push({id: d.id, valor: String(c.valor)});
    if (b) verif.sin.push({id: d.id, valor: String(b.valor)});
  });
  const htmlVerif = verif.completa.length ? `<div class="lote"><span>Serie del tablero verificada por dígito de control
      <span class="resp">· ${verif.completa.length} casos (cada uno con su serie)</span></span>
      <button id="verifCompleta">Completa</button> <button id="verifSin">Sin dígito de control</button></div>` : '';
  document.getElementById('lotes').innerHTML = (filas.length || htmlVerif) ? `<div class="lotes"><h3>Aceptar de una vez (la opción recomendada es la misma en varios casos)</h3>${htmlVerif}${
    filas.map((g, i) => `<div class="lote"><span>${esc(g.pieza || g.campo)} · <b>${esc(g.valor)}</b>
      <span class="resp">(${g.fuente.replace(/_/g, ' ')}) · ${g.ids.length} casos</span></span>
      <button data-i="${i}">Usar en los ${g.ids.length}</button></div>`).join('')}</div>` : '';
  const enviar = async lista => { await fetch('/api/decidir_varias', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({decisiones: lista})}); await cargar(); };
  if (htmlVerif) {
    document.getElementById('verifCompleta').onclick = () => enviar(verif.completa);
    document.getElementById('verifSin').onclick = () => enviar(verif.sin);
  }
  document.querySelectorAll('.lote button[data-i]').forEach(b => b.onclick = async () => {
    await fetch('/api/decidir_lote', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ids: filas[+b.dataset.i].ids})});
    await cargar();
  });
}

function pintarLista() {
  const dudas = DATOS.dudas.filter(d => filtro === 'todos' || (filtro === 'con' ? conPropuesta(d)
      : filtro === 'sin' ? !conPropuesta(d) : d.motivo === filtro))
    .sort((a, b) => (a.campo + a.caso).localeCompare(b.campo + b.caso));
  if (!dudas.length) {
    document.getElementById('lista').innerHTML = '<div class="vacio">No hay dudas pendientes. Todo lo que el programa pudo leer está en el libro.</div>';
    return;
  }
  document.getElementById('lista').innerHTML = dudas.map(d => {
    const sel = DATOS.decisiones[d.id];
    const opciones = d.opciones.map((o, i) => {
      const valor = o.valor === null ? 'No lo tengo' : o.valor;
      const marcada = sel && String(sel.valor) === String(o.valor);
      return `<div class="opw"><button class="op ${marcada ? 'sel' : ''}" data-id="${d.id}" data-val="${o.valor === null ? '' : esc(o.valor)}">
        <span class="val">${esc(valor)}</span>
        <span class="fuente ${o.fuente}">${o.fuente.replace(/_/g, ' ')}</span>
        <span class="resp">${esc(o.respaldo)}${o.confianza ? ' · confianza ' + o.confianza : ''}</span>
        ${o.valor !== null && o.valor === (d.opciones.find(x => x.valor !== null) || {}).valor ? '<span class="reco">★ recomendada</span>' : ''}
      </button>${miniaturas(o, d)}</div>`;
    }).join('');
    const propio = sel && !d.opciones.some(o => String(o.valor) === String(sel.valor))
      ? `<div class="propio">Elegiste un valor escrito por ti: <b>${esc(sel.valor)}</b></div>` : '';
    const otro = `<div class="otro" data-id="${d.id}" data-campo="${d.campo}">
        <a class="otro-link">+ otro valor</a>
        <form hidden><input placeholder="escribe el valor correcto" autocomplete="off">
          <button type="submit">Usar</button></form><span class="forma"></span></div>`;
    const descartadas = (d.opciones_descartadas || []).length
      ? `<div class="detalle">Descartado por la serie: ${d.opciones_descartadas.map(o => o.valor).join(', ')}</div>` : '';
    const donde = (d.donde_mirar || []).length
      ? `<ul class="donde">${d.donde_mirar.map(t => `<li>${t}</li>`).join('')}</ul>` : '';
    return `<section class="duda">
      <h2><span class="caso">${d.caso}</span><span class="campo">${d.campo}</span>
        ${d.columna ? `<span class="resp"> · columna ${d.columna}</span>` : ''}
        <span class="motivo ${d.motivo === 'fuentes_en_conflicto' ? 'm-conflicto' : 'm-sin'}">${d.motivo.replace(/_/g, ' ')}</span></h2>
      ${d.pieza ? `<div class="pieza">Pieza: <b>${esc(d.pieza)}</b></div>` : ''}
      <div class="detalle">${d.detalle}</div>
      ${donde}${descartadas}
      <div class="ops">${opciones}</div>${propio}${otro}
    </section>`;
  }).join('');
  document.querySelectorAll('.op').forEach(b => b.onclick = () => decidir(b.dataset.id, b.dataset.val));
  document.querySelectorAll('.minis img').forEach(i => i.onclick = () => abrirVisor(i));
  document.querySelectorAll('.otro').forEach(prepararOtro);
}

function esc(t) {
  return String(t ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function miniaturas(o, d) {
  if (o.valor === null) return '';
  const fotos = (o.fotos || []).slice(0, 3);
  if (!fotos.length) return '';
  return `<div class="minis">${fotos.map(f => {
    const tok = f.token_recorte || f.token;
    if (!tok) return `<span class="sinfoto" title="${esc(f.foto)}">${esc(f.fuente)}</span>`;
    const pie = `${d.pieza ? d.pieza + ' · ' : ''}${f.foto} · ${f.fuente}${f.texto ? ' · leído: «' + f.texto + '»' : ''}${f.con_caja ? '' : ' · (sin recuadro: no se encontró la posición exacta)'}`;
    return `<img loading="lazy" src="/api/foto/${tok}?tam=mini" data-grande="${f.token || tok}" data-pie="${esc(pie)}" alt="${esc(f.foto)}" title="${esc(f.foto)}">`;
  }).join('')}</div>`;
}

function abrirVisor(img) {
  document.getElementById('visor-img').src = `/api/foto/${img.dataset.grande}?tam=grande`;
  document.getElementById('visor-pie').textContent = img.dataset.pie;
  document.getElementById('visor').style.display = 'flex';
}
document.getElementById('visor').onclick = () => { document.getElementById('visor').style.display = 'none'; };
document.addEventListener('keydown', e => { if (e.key === 'Escape') document.getElementById('visor').style.display = 'none'; });

function prepararOtro(caja) {
  const enlace = caja.querySelector('.otro-link'), form = caja.querySelector('form');
  const entrada = form.querySelector('input'), aviso = caja.querySelector('.forma');
  let confirmado = null;
  enlace.onclick = () => { enlace.hidden = true; form.hidden = false; entrada.focus(); };
  entrada.oninput = () => { confirmado = null; aviso.textContent = ''; form.querySelector('button').textContent = 'Usar'; };
  form.onsubmit = async ev => {
    ev.preventDefault();
    const valor = entrada.value.trim();
    if (!valor) return;
    if (confirmado !== valor) {
      const r = await (await fetch('/api/revisar', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({campo: caja.dataset.campo, valor})})).json();
      if (r.valido) { await decidir(caja.dataset.id, r.valor); return; }
      if (!r.valido) {
        aviso.textContent = `No tiene la forma habitual de este campo${r.motivo ? ' (' + r.motivo + ')' : ''}. Pulsa otra vez para usarlo igual.`;
        form.querySelector('button').textContent = 'Usar igual';
        confirmado = valor;
        return;
      }
    }
    await decidir(caja.dataset.id, valor);
  };
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
    ap.add_argument("--validacion", help="P45 · JSON de validación de la corrida (tablero P42, "
                    "lecturas OCR, variantes de la serie y vocabulario del libro histórico)")
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
    elif args.validacion:
        from configuracion import RAIZ_PROYECTO, cargar_config
        from utilidades.dudas_y_opciones import lecturas_desde_validacion
        from utilidades.vocabulario_libro import rutas_configuradas, vocabulario
        config = cargar_config()
        lecturas, ambiguos = lecturas_desde_validacion(
            json.loads(Path(args.validacion).read_text(encoding="utf-8")),
            vocabulario(rutas_configuradas(config, RAIZ_PROYECTO)))
        if ambiguos:
            print("AVISO · números repetidos en varias etapas (no se ofrecen sus lecturas): "
                  + ", ".join(ambiguos))
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
    # P48 · solo esta computadora: el panel ahora muestra fotos del cliente
    uvicorn.run(app, host="127.0.0.1", port=args.puerto, log_level="warning")


if __name__ == "__main__":
    main()
