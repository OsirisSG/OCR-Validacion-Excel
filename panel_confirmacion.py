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


class DecisionConValor(BaseModel):
    """P53 · antes se llamaba `Decision` y tapaba a la de arriba (valor opcional): por HTTP,
    «No lo tengo» (valor nulo) se rechazaba con 422 y el botón no hacía nada."""
    id: str
    valor: str


class Varias(BaseModel):
    decisiones: list[DecisionConValor]


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


class Deshacer(BaseModel):
    id: str


@app.post("/api/deshacer")
def api_deshacer(deshacer: Deshacer):
    """P53 · quita una decisión elegida y todavía sin guardar. No toca el libro ni lo silenciado."""
    if ESTADO is None:
        raise HTTPException(503, "panel sin libro cargado")
    return {"id": deshacer.id, "deshecha": ESTADO.decisiones.pop(deshacer.id, None) is not None}


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
<html lang="es" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel de dudas · V-Matrix</title>
<style>
 /* P53 · sistema visual (guía IGNIS adaptada): un solo acento (el azul de la marca), rojo sólo
    para error, verde sólo para hecho/verificado. Sin fuentes ni recursos de red. */
 :root{--fondo:#0b1114;--sup:#131c21;--sup2:#1b272e;--borde:#2b3a43;
       --tinta:#f2f6f8;--tinta2:#c9d5db;--tenue:#8fa1ab;
       --acento:#2fb9d3;--sobre-acento:#03222b;--peligro:#ff5a4f;--exito:#2fc46b;--aviso:#e0a23a;
       --exito-osc:#0c3a22;--radio:18px;
       --f-sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
       --f-mono:ui-monospace,"Cascadia Mono",Consolas,Menlo,monospace;
       --entra:cubic-bezier(.2,.8,.2,1);--rebote:cubic-bezier(.34,1.56,.64,1)}
 html[data-theme=light]{--fondo:#f3f7f8;--sup:#ffffff;--sup2:#eaf1f4;--borde:#d5e0e5;
       --tinta:#0f222b;--tinta2:#3c4d55;--tenue:#5d6d75;
       --acento:#196a8a;--sobre-acento:#ffffff;--peligro:#c0392b;--exito:#1c7d46;--aviso:#93610a;
       --exito-osc:#14532d}
 *{box-sizing:border-box}
 [hidden]{display:none!important}
 html{-webkit-text-size-adjust:100%}
 body{margin:0;font:15px/1.5 var(--f-sans);color:var(--tinta);background:var(--fondo);
      min-height:100svh;transition:background-color .25s,color .25s}
 :focus-visible{outline:2px solid var(--acento);outline-offset:2px}
 button{font:inherit;color:inherit}
 .mono{font-family:var(--f-mono)}
 .cifra{font-variant-numeric:tabular-nums;font-weight:700;letter-spacing:-.01em}
 .etiqueta{font:600 11px var(--f-mono);letter-spacing:.06em;text-transform:uppercase;color:var(--tenue)}

 header{position:sticky;top:0;z-index:10;background:color-mix(in srgb,var(--fondo) 88%,transparent);
        backdrop-filter:blur(10px);border-bottom:1px solid var(--borde)}
 .cab{max-width:1080px;margin:0 auto;padding:12px 16px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
 .anillo{position:relative;width:54px;height:54px;flex:none}
 .anillo svg{width:54px;height:54px;transform:rotate(-90deg)}
 .anillo circle{fill:none;stroke-width:5}
 .anillo .pista{stroke:var(--sup2)}
 .anillo .avance{stroke:var(--acento);stroke-linecap:round;stroke-dasharray:138.2;stroke-dashoffset:138.2;
                 transition:stroke-dashoffset 1.1s var(--entra),stroke .3s}
 .anillo.lleno .avance{stroke:var(--exito)}
 .anillo b{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:13px}
 .titulo{flex:1;min-width:180px}
 .titulo h1{font-size:19px;line-height:1.2;margin:0;font-weight:700;letter-spacing:-.01em}
 .titulo .meta{color:var(--tenue);font-size:12.5px;overflow-wrap:anywhere}
 .kpis{display:flex;gap:18px}
 .kpi{display:flex;flex-direction:column;min-width:52px}
 .kpi .cifra{font-size:22px;line-height:1.1}
 /* interruptor día/noche: el mismo del modo sencillo del dashboard */
 .tema-switch{position:relative;display:inline-flex;align-items:center;min-height:44px;cursor:pointer}
 .tema-switch input{position:absolute;inset:0;opacity:0;cursor:pointer;margin:0}
 .tema-pista{position:relative;display:block;width:62px;height:32px;border-radius:999px;overflow:hidden;
             background:#bfe4ed;border:1px solid var(--borde);transition:background-color .35s}
 .tema-astro{position:absolute;top:4px;left:4px;width:22px;height:22px;border-radius:50%;background:#f6c64b;
             box-shadow:0 0 0 4px rgba(246,198,75,.28);
             transition:transform .45s var(--rebote),background-color .35s,box-shadow .35s}
 .tema-pista i{position:absolute;width:3px;height:3px;border-radius:50%;background:#fff;opacity:0;transform:scale(.2);
               transition:opacity .3s,transform .45s var(--rebote)}
 .tema-pista i:nth-child(1){left:12px;top:8px}.tema-pista i:nth-child(2){left:22px;top:18px}.tema-pista i:nth-child(3){left:30px;top:9px}
 .tema-switch input:checked+.tema-pista{background:#0b1b2a}
 .tema-switch input:checked+.tema-pista .tema-astro{transform:translateX(30px);background:#e8eef2;box-shadow:inset -6px -2px 0 0 #b9c7d1}
 .tema-switch input:checked+.tema-pista i{opacity:1;transform:scale(1)}
 .tema-switch:has(input:focus-visible) .tema-pista{outline:2px solid var(--acento);outline-offset:2px}

 main{max-width:1080px;margin:0 auto;padding:16px 16px 120px}
 .barra{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:14px}
 .segmentos{position:relative;display:grid;grid-template-columns:repeat(4,1fr);gap:4px;padding:4px;
            border-radius:12px;background:var(--sup2);isolation:isolate;flex:1;min-width:280px}
 .segmentos::before{content:'';position:absolute;z-index:-1;inset:4px auto 4px 4px;
            width:calc((100% - 20px) / 4);border-radius:9px;background:var(--acento);
            transition:transform .45s cubic-bezier(.34,1.4,.64,1)}
 .segmentos:has(button:nth-child(2).sel)::before{transform:translateX(calc(100% + 4px))}
 .segmentos:has(button:nth-child(3).sel)::before{transform:translateX(calc(200% + 8px))}
 .segmentos:has(button:nth-child(4).sel)::before{transform:translateX(calc(300% + 12px))}
 .segmentos button{min-height:44px;border:0;background:none;color:var(--tinta2);font-weight:600;font-size:13px;
            cursor:pointer;border-radius:9px;padding:2px 4px;line-height:1.15;transition:color .2s}
 .segmentos button.sel{color:var(--sobre-acento)}
 .segmentos button i{font-style:normal;font-variant-numeric:tabular-nums;opacity:.75;display:block;font-size:11.5px}
 .busca{flex:0 1 230px;min-width:150px;min-height:46px;border-radius:12px;border:1px solid var(--borde);
        background:var(--sup);color:var(--tinta);padding:0 12px;font:inherit}
 .busca::placeholder{color:var(--tenue)}

 .btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:46px;padding:0 16px;
      border-radius:999px;border:1px solid var(--acento);background:var(--acento);color:var(--sobre-acento);
      font-weight:700;cursor:pointer;transition:transform .2s var(--rebote),opacity .2s}
 .btn:active{transform:scale(.96)}
 .btn.sec{background:transparent;color:var(--acento)}
 .btn.chico{min-height:46px;padding:0 12px;font-size:13px;font-weight:600}
 .btn:disabled{opacity:.4;cursor:not-allowed;transform:none}

 .spot{position:relative;overflow:hidden;isolation:isolate}
 .spot::after{content:'';position:absolute;inset:0;z-index:-1;opacity:0;transition:opacity .3s;pointer-events:none;
   background:radial-gradient(220px circle at var(--mx,50%) var(--my,50%),color-mix(in srgb,var(--acento) 13%,transparent),transparent 70%)}
 .spot:hover::after,.spot:focus-within::after{opacity:1}

 @keyframes subeEntra{from{opacity:0;transform:translateY(22px) scale(.97)}}
 .entra{animation:subeEntra .55s var(--entra) both;animation-delay:calc(var(--i,0) * 40ms)}

 .lotes{background:var(--sup);border:1px solid var(--borde);border-left:3px solid var(--acento);
        border-radius:var(--radio);padding:12px 14px;margin-bottom:14px}
 .lotes summary{cursor:pointer;min-height:44px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;list-style:none}
 .lotes summary::-webkit-details-marker{display:none}
 .lotes summary::before{content:'';width:8px;height:8px;border-right:2px solid var(--acento);border-bottom:2px solid var(--acento);
                        transform:rotate(-45deg);transition:transform .25s var(--entra);margin-right:6px}
 .lotes[open] summary::before{transform:rotate(45deg)}
 .lotes p{margin:4px 0 8px;color:var(--tenue);font-size:12.5px}
 .lote{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 0;
       border-top:1px solid var(--borde);font-size:13.5px;flex-wrap:wrap}
 .lote>span:first-child{flex:1;min-width:200px;overflow-wrap:anywhere}
 .lote b{font-family:var(--f-mono);font-size:13px}
 .lote .acciones{display:flex;gap:6px;flex-wrap:wrap}
 .resp{font-size:12.5px;color:var(--tenue)}

 .duda{background:var(--sup);border:1px solid var(--borde);border-radius:var(--radio);padding:14px 16px;
       margin-bottom:12px;scroll-margin-top:96px;transition:border-color .2s}
 .duda.foco{border-color:var(--acento)}
 .duda.hecha{border-left:3px solid var(--exito)}
 .duda h2{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:15.5px;margin:0 0 2px;font-weight:700}
 .caso{font:700 13px var(--f-mono);font-variant-numeric:tabular-nums;background:var(--sup2);
       border-radius:6px;padding:2px 8px}
 .motivo{font:600 10.5px var(--f-mono);letter-spacing:.05em;text-transform:uppercase;border-radius:999px;
         padding:3px 9px;border:1px solid var(--borde);color:var(--tenue)}
 .m-conflicto{color:var(--aviso);border-color:color-mix(in srgb,var(--aviso) 55%,transparent)}
 .listo{margin-left:auto;display:inline-flex;align-items:center;gap:5px;color:var(--exito);font-size:12.5px;font-weight:700}
 .listo svg{width:16px;height:16px}
 .pieza{font-size:12.5px;color:var(--tenue);margin:0 0 6px}
 .pieza b{color:var(--tinta2);font-weight:600}
 .detalle{color:var(--tinta2);font-size:13.5px;margin:4px 0 10px;max-width:75ch}
 .donde{font-size:12.5px;color:var(--tenue);margin:0 0 10px;padding-left:16px;max-width:75ch}
 .ops{display:flex;flex-direction:column;gap:6px}
 .opw{display:flex;gap:8px;align-items:stretch;flex-wrap:wrap}
 .op{flex:1 1 280px;display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:2px 10px;align-items:center;
     min-height:48px;border:1px solid var(--borde);border-radius:10px;padding:8px 12px;background:var(--sup2);
     cursor:pointer;text-align:left;width:100%;transition:border-color .18s,transform .2s var(--rebote)}
 .op:hover{border-color:var(--acento)}
 .op:active{transform:scale(.985)}
 .op.sel{border-color:var(--exito);box-shadow:inset 0 0 0 1px var(--exito)}
 .op kbd{grid-row:1 / span 2;font:600 11px var(--f-mono);color:var(--tenue);border:1px solid var(--borde);
         border-radius:5px;min-width:22px;text-align:center;padding:2px 0}
 .val{font:700 14.5px var(--f-mono);overflow-wrap:anywhere}
 .op .linea{grid-column:2;display:flex;flex-wrap:wrap;gap:6px;align-items:center;min-width:0}
 .fuente{font:600 10.5px var(--f-mono);letter-spacing:.04em;text-transform:uppercase;color:var(--tenue);
         border:1px solid var(--borde);border-radius:5px;padding:1px 6px;white-space:nowrap}
 .fuente.serie_verificada,.fuente.serie_verificada_sin_control{color:var(--exito);border-color:color-mix(in srgb,var(--exito) 55%,transparent)}
 .reco{grid-column:3;grid-row:1;font-size:11.5px;color:var(--acento);font-weight:700;white-space:nowrap}
 .conf{grid-column:3;grid-row:2;display:flex;align-items:center;gap:6px;font:600 11px var(--f-mono);
       color:var(--tenue);font-variant-numeric:tabular-nums;justify-self:end}
 .conf span{display:block;width:54px;height:5px;border-radius:3px;background:var(--borde);overflow:hidden}
 .conf span i{display:block;height:100%;background:var(--acento);transform-origin:left;transform:scaleX(var(--c,0));
              transition:transform .7s var(--entra)}
 .minis{display:flex;gap:6px;align-items:center}
 .minis img{height:56px;width:auto;max-width:96px;object-fit:cover;border-radius:8px;border:1px solid var(--borde);
            cursor:zoom-in;background:var(--sup2);transition:transform .2s var(--rebote)}
 .minis img:hover,.minis img:focus-visible{transform:scale(1.06)}
 .minis .sinfoto{font-size:11px;color:var(--tenue);padding:0 4px;white-space:nowrap}
 .propio{font-size:12.5px;color:var(--acento);margin-top:6px}
 .otro input{font:inherit;font-size:14px;border:1px solid var(--borde);border-radius:9px;padding:0 10px;min-height:44px;
             width:220px;max-width:100%;background:var(--sup2);color:var(--tinta)}
 .otro .forma{display:block;font-size:12px;color:var(--aviso);margin-top:3px}
 /* ---- vista guiada: una duda a la vez, con la foto grande ---- */
 .vistas{display:inline-grid;grid-template-columns:1fr 1fr;gap:4px;padding:4px;border-radius:999px;background:var(--sup2)}
 .vistas button{min-height:44px;padding:0 14px;border:0;border-radius:999px;background:none;color:var(--tinta2);
                font-weight:600;font-size:13px;cursor:pointer}
 .vistas button.sel{background:var(--sup);color:var(--tinta);box-shadow:0 1px 2px rgba(0,0,0,.2)}
 .guia{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px;flex-wrap:wrap}
 .guia .cuenta{font:600 12px var(--f-mono);letter-spacing:.06em;text-transform:uppercase;color:var(--tenue)}
 .guia .cuenta b{color:var(--tinta);font-size:15px}
 .guia .pasos{display:flex;gap:8px}
 .duda.guiada{padding:20px}
 .duda.guiada .cuerpo{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.05fr);gap:20px;align-items:start}
 .duda.guiada .cuerpo.sin-foto{grid-template-columns:1fr}
 .lienzo{position:relative;height:340px;border-radius:14px;border:1px solid var(--borde);background:#0a1014;
         display:grid;place-items:center;overflow:hidden}
 .lienzo img{max-width:100%;max-height:100%;cursor:zoom-in;transition:transform .35s var(--entra)}
 .lienzo .sinimagen{color:#8fa1ab;font-size:13px;padding:20px;text-align:center}
 .barra-foto{display:flex;align-items:center;gap:6px;margin-top:8px;flex-wrap:wrap}
 .barra-foto .leyenda{flex:1;min-width:120px;font-size:12px;color:var(--tenue);overflow-wrap:anywhere}
 .ico{display:inline-grid;place-items:center;width:44px;height:44px;border-radius:50%;border:1px solid var(--borde);
      background:var(--sup);color:var(--tinta2);cursor:pointer;transition:transform .2s var(--rebote),border-color .2s,color .2s}
 .ico svg{width:19px;height:19px}
 .ico:hover{border-color:var(--acento);color:var(--acento)}
 .ico:active{transform:scale(.92)}
 .minis img.activa{outline:2px solid var(--acento);outline-offset:1px}
 /* «Otro texto»: una opción más, a la vista */
 .op.otra{border-style:dashed;background:none}
 .op.otra .val{font-family:var(--f-sans);font-weight:600}
 .otro{margin-top:6px}
 .otro form{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:6px}
 .otro form input{flex:1;min-width:180px}
 #volver{text-decoration:none}
 .vacio{background:var(--sup);border:1px dashed var(--borde);border-radius:var(--radio);padding:30px 20px;
        text-align:center;color:var(--tenue)}
 .vacio b{display:block;color:var(--tinta);font-size:16px;margin-bottom:4px}
 .atajos{color:var(--tenue);font-size:12px;margin:14px 2px 0}
 .atajos kbd{font:600 11px var(--f-mono);border:1px solid var(--borde);border-radius:5px;padding:1px 5px;margin:0 1px}

 footer{position:fixed;left:0;right:0;bottom:0;z-index:10;background:color-mix(in srgb,var(--sup) 94%,transparent);
        backdrop-filter:blur(10px);border-top:1px solid var(--borde)}
 .pie{max-width:1080px;margin:0 auto;padding:10px 16px;display:flex;gap:12px;align-items:center;
      justify-content:space-between;flex-wrap:wrap}
 #aviso{font-size:13.5px;color:var(--tinta2);flex:1;min-width:160px}
 #aviso.error{color:var(--peligro)}
 #aviso.bien{color:var(--exito)}

 #visor{position:fixed;inset:0;background:rgba(4,9,12,.9);display:none;align-items:center;
        justify-content:center;flex-direction:column;z-index:20;cursor:zoom-out;padding:18px}
 #visor.abierto{display:flex;animation:subeEntra .3s var(--entra)}
 #visor img{max-width:92vw;max-height:74svh;border-radius:10px;background:#fff;cursor:grab;touch-action:none;
            transition:transform .3s var(--entra)}
 #visor img.arrastra{cursor:grabbing;transition:none}
 #visor .herr{display:flex;gap:8px;margin-bottom:12px;cursor:default;position:relative;z-index:2}
 #visor .pie-foto{position:relative;z-index:2}
 #visor .herr .ico{background:rgba(20,30,36,.85);border-color:rgba(255,255,255,.25);color:#fff}
 #visor .pie-foto{color:#e6eef2;font-size:13px;margin-top:10px;text-align:center;max-width:90vw}

 .chispa{position:fixed;z-index:5000;pointer-events:none}
 .chispa i{position:absolute;left:-1.5px;top:-6px;width:3px;height:12px;border-radius:3px;background:var(--acento);
   transform-origin:1.5px 6px;transform:rotate(calc(var(--k) * 45deg)) translateY(-10px);animation:chispa .55s var(--entra) forwards}
 .chispa i:nth-child(1){--k:0}.chispa i:nth-child(2){--k:1}.chispa i:nth-child(3){--k:2}.chispa i:nth-child(4){--k:3}
 .chispa i:nth-child(5){--k:4}.chispa i:nth-child(6){--k:5}.chispa i:nth-child(7){--k:6}.chispa i:nth-child(8){--k:7}
 @keyframes chispa{to{transform:rotate(calc(var(--k) * 45deg)) translateY(-34px) scaleY(.2);opacity:0}}

 #fiesta{position:fixed;inset:0;z-index:6000;background:var(--exito-osc);color:#fff;display:none;
         flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:24px;cursor:pointer}
 #fiesta.va{display:flex;animation:subeEntra .45s var(--entra)}
 #fiesta canvas{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
 #fiesta svg{width:120px;height:120px;position:relative}
 #fiesta svg circle{fill:none;stroke:rgba(255,255,255,.25);stroke-width:5}
 #fiesta svg path{fill:none;stroke:#fff;stroke-width:7;stroke-linecap:round;stroke-linejoin:round;
                  stroke-dasharray:80;stroke-dashoffset:80}
 #fiesta.va svg path{animation:palomita .7s .25s var(--entra) forwards}
 @keyframes palomita{to{stroke-dashoffset:0}}
 #fiesta h2{position:relative;font-size:clamp(26px,6vw,44px);margin:18px 0 6px;letter-spacing:-.02em}
 #fiesta p{position:relative;margin:0;opacity:.85;max-width:46ch}

 @media (max-width:640px){
   header{position:static}
   .kpis{order:3;width:100%;justify-content:space-between;gap:8px}
   .duda{scroll-margin-top:12px}
   .segmentos{min-width:100%}
   .busca{flex:1 1 100%}
   .pie .btn{flex:1}
   .op{grid-template-columns:auto minmax(0,1fr)}
   .reco,.conf{grid-column:2;grid-row:auto;justify-self:start}
   .atajos{display:none}
   .duda.guiada .cuerpo{grid-template-columns:1fr}
   .lienzo{height:240px}
   .guia .pasos{width:100%}
   .guia .pasos .btn{flex:1}
 }
 @media (prefers-reduced-motion:reduce){
   *,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}
 }
</style></head><body>
<header><div class="cab">
  <div class="anillo" id="anillo" role="img" aria-label="Avance de las decisiones">
    <svg viewBox="0 0 54 54" aria-hidden="true"><circle class="pista" cx="27" cy="27" r="22"/><circle class="avance" id="arco" cx="27" cy="27" r="22"/></svg>
    <b class="cifra"><span id="pct">0</span>%</b>
  </div>
  <div class="titulo">
    <h1 id="titular">Panel de dudas</h1>
    <div class="meta" id="meta">cargando…</div>
  </div>
  <div class="kpis">
    <div class="kpi"><span class="cifra" id="k-casos">0</span><span class="etiqueta">casos</span></div>
    <div class="kpi"><span class="cifra" id="k-dudas">0</span><span class="etiqueta">dudas</span></div>
    <div class="kpi"><span class="cifra" id="k-hechas">0</span><span class="etiqueta">elegidas</span></div>
  </div>
  <a class="btn sec chico" id="volver" hidden>← Volver al programa</a>
  <label class="tema-switch" title="Tema claro u oscuro"><input type="checkbox" role="switch" aria-label="Modo noche">
    <span class="tema-pista" aria-hidden="true"><i></i><i></i><i></i><span class="tema-astro"></span></span>
  </label>
</div></header>
<main>
  <noscript><div class="vacio"><b>Esta página necesita JavaScript.</b>Actívalo en el navegador para ver y decidir las dudas.</div></noscript>
  <div class="barra">
    <div class="segmentos" id="filtros" role="tablist" aria-label="Filtro de dudas"></div>
    <div class="vistas" role="tablist" aria-label="Forma de revisar">
      <button role="tab" id="v-guiada" data-v="guiada">Una a una</button><button role="tab" id="v-lista" data-v="lista">Lista</button>
    </div>
    <input class="busca" id="busca" type="search" placeholder="Buscar caso o campo" aria-label="Buscar caso o campo" autocomplete="off">
  </div>
  <div id="lotes"></div>
  <div id="lista" aria-live="polite"></div>
  <p class="atajos">Atajos: <kbd>J</kbd>/<kbd>K</kbd> siguiente y anterior · <kbd>1</kbd>–<kbd>9</kbd> elegir opción · <kbd>Enter</kbd> usar la recomendada · <kbd>O</kbd> otro texto · <kbd>R</kbd> girar la foto · <kbd>/</kbd> buscar · <kbd>Esc</kbd> cerrar foto</p>
</main>
<div id="visor" role="dialog" aria-label="Foto de la evidencia">
  <div class="herr" id="visor-herr">
    <button class="ico" data-a="izq" aria-label="Girar a la izquierda" title="Girar a la izquierda (Mayús + R)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 4v6h6"/><path d="M3.5 10a9 9 0 1 1 2.1 8.4"/></svg></button>
    <button class="ico" data-a="der" aria-label="Girar a la derecha" title="Girar a la derecha (R)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 4v6h-6"/><path d="M20.5 10a9 9 0 1 0-2.1 8.4"/></svg></button>
    <button class="ico" data-a="menos" aria-label="Alejar" title="Alejar (-)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14"/></svg></button>
    <button class="ico" data-a="mas" aria-label="Acercar" title="Acercar (+)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14M12 5v14"/></svg></button>
    <button class="ico" data-a="cerrar" aria-label="Cerrar la foto" title="Cerrar (Esc)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
  </div>
  <img id="visor-img" alt="" draggable="false"><div class="pie-foto" id="visor-pie"></div></div>
<div id="fiesta" role="status"><canvas id="confeti"></canvas>
  <svg viewBox="0 0 60 60" aria-hidden="true"><circle cx="30" cy="30" r="26"/><path d="M17 31l9 9 17-19"/></svg>
  <h2>Todo decidido</h2><p id="fiesta-txt"></p></div>
<footer><div class="pie">
  <span id="aviso" role="status">Nada elegido todavía.</span>
  <button class="btn sec" id="descargar" hidden>Descargar Excel</button>
  <button class="btn" id="guardar" disabled>Guardar en Excel</button>
</div></footer>
<script>
const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = id => document.getElementById(id);
let DATOS = {dudas: [], decisiones: {}, resumen: {}};
let filtro = 'con', busca = '', animar = true, foco = -1, visibles = [];
const ALTA = 0.9;
// P54 · «una a una» (por defecto) o lista; giro de cada foto y foto activa de cada duda
let vista = 'guiada'; try { vista = localStorage.getItem('dudas_vista') === 'lista' ? 'lista' : 'guiada'; } catch (e) {}
const giros = {}, fotoActiva = {};
const ICO_IZQ = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 4v6h6"/><path d="M3.5 10a9 9 0 1 1 2.1 8.4"/></svg>';
const ICO_DER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 4v6h-6"/><path d="M20.5 10a9 9 0 1 0-2.1 8.4"/></svg>';
const ICO_AMP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>';

// Una foto girada 90° debe seguir cabiendo en su caja: se gira y se reduce lo justo.
function aplicarGiro(img, grados, zoom = 1, dx = 0, dy = 0) {
  const caja = img.parentElement.getBoundingClientRect(), w = img.offsetWidth || 1, h = img.offsetHeight || 1;
  const tumbada = Math.abs(grados % 180) === 90;
  const cabe = tumbada ? Math.min(1, caja.width / h, caja.height / w) : 1;
  img.style.transform = `translate(${dx}px, ${dy}px) rotate(${grados}deg) scale(${(cabe * zoom).toFixed(3)})`;
}
function fotosDe(d) {
  const vistas = [];
  d.opciones.forEach(o => (o.fotos || []).forEach(f => { const tok = f.token || f.token_recorte;
    if (tok && !vistas.some(v => v.tok === tok)) vistas.push({tok, foto: f.foto, fuente: f.fuente, texto: f.texto, con_caja: f.con_caja}); }));
  return vistas;
}
function pieDe(d, f) {
  return `${d.pieza ? d.pieza + ' · ' : ''}${f.foto} · ${f.fuente}${f.texto ? ' · leído: «' + f.texto + '»' : ''}${f.con_caja ? '' : ' · (sin recuadro: no se encontró la posición exacta)'}`;
}
(function volver() {      // enlace de regreso al dashboard: sólo se acepta una dirección de este equipo
  let destino = ''; try { destino = new URLSearchParams(location.search).get('volver') || ''; } catch (e) {}
  if (!/^http:[/][/](127[.]0[.]0[.]1|localhost)(:[0-9]+)?[/]/.test(destino)) return;
  const a = $('volver'); a.href = destino; a.hidden = false;
})();
document.querySelectorAll('.vistas button').forEach(b => b.onclick = () => {
  vista = b.dataset.v; try { localStorage.setItem('dudas_vista', vista); } catch (e) {}
  animar = true; foco = -1; pintarLotes(); pintarLista(); });

// ---- tema día/noche (se recuerda; avisa con el evento «tema») ----
(function tema() {
  const chks = [...document.querySelectorAll('.tema-switch input')];
  const aplicar = noche => {
    document.documentElement.dataset.theme = noche ? 'dark' : 'light';
    chks.forEach(c => c.checked = noche);
    try { localStorage.setItem('tema', noche ? 'dark' : 'light'); } catch (e) {}
    window.dispatchEvent(new Event('tema'));
  };
  let g = null; try { g = localStorage.getItem('tema'); } catch (e) {}
  chks.forEach(c => c.onchange = () => aplicar(c.checked));
  aplicar(g ? g === 'dark' : true);
})();

// ---- monerías: chispas, luz que sigue al cursor, números que corren ----
document.addEventListener('pointerdown', e => {
  if (RM) return; const t = e.target.closest('.btn, .op, [data-chispa]'); if (!t || t.disabled) return;
  const s = document.createElement('div'); s.className = 'chispa';
  s.style.left = e.clientX + 'px'; s.style.top = e.clientY + 'px'; s.innerHTML = '<i></i>'.repeat(8);
  document.body.appendChild(s); setTimeout(() => s.remove(), 650);
}, {passive: true});
document.addEventListener('pointermove', e => { const t = e.target.closest && e.target.closest('.spot'); if (!t) return;
  const r = t.getBoundingClientRect(); t.style.setProperty('--mx', e.clientX - r.left + 'px'); t.style.setProperty('--my', e.clientY - r.top + 'px'); }, {passive: true});
const previo = {};
function correr(el, hasta, ms = 900) {
  const desde = previo[el.id] ?? 0; previo[el.id] = hasta;
  el.textContent = hasta; if (RM || desde === hasta) return;
  const t0 = performance.now();
  const paso = now => { const k = Math.min(1, (now - t0) / ms);
    el.textContent = Math.round(desde + (hasta - desde) * (1 - Math.pow(1 - k, 4)));
    if (k < 1 && previo[el.id] === hasta) requestAnimationFrame(paso); };
  requestAnimationFrame(paso);
}

function esc(t) {
  return String(t ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
const legible = t => esc(String(t ?? '').replace(/_/g, ' '));
const nombre = r => String(r ?? '').replace(/^.*[\\\\/]/, '');
const conPropuesta = d => d.opciones.some(o => o.valor !== null);
const recomendada = d => d.opciones.find(o => o.valor !== null);
const post = (url, cuerpo) => fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify(cuerpo || {})});
function aviso(texto, clase) { const a = $('aviso'); a.textContent = texto; a.className = clase || ''; }

function pintarFiltros() {
  const con = DATOS.dudas.filter(conPropuesta).length, sin = DATOS.dudas.length - con;
  const c = DATOS.resumen.por_motivo || {};
  const chips = [['con', 'Con propuesta', con], ['fuentes_en_conflicto', 'En conflicto', c.fuentes_en_conflicto || 0],
    ['sin', 'Sin propuesta', sin], ['todos', 'Todas', DATOS.dudas.length]];
  $('filtros').innerHTML = chips.map(([k, t, n]) =>
    `<button role="tab" aria-selected="${filtro === k}" class="${filtro === k ? 'sel' : ''}" data-f="${k}">${t}<i>${n}</i></button>`).join('');
  $('filtros').querySelectorAll('button').forEach(b => b.onclick = () => {
    filtro = b.dataset.f; animar = true; foco = -1; pintarFiltros(); pintarLista(); });
  pintarLotes();
}

function pintarLotes() {
  const pendientes = DATOS.dudas.filter(d => conPropuesta(d) && !DATOS.decisiones[d.id]);
  // P49 · una fila por campo con la misma recomendación en varios casos: se acepta de una vez
  const grupos = {};
  pendientes.forEach(d => {
    const reco = recomendada(d), k = d.campo + '||' + reco.valor;
    (grupos[k] = grupos[k] || {campo: d.campo, pieza: d.pieza, valor: reco.valor, fuente: reco.fuente, ids: []}).ids.push(d.id);
  });
  const filas = Object.values(grupos).filter(g => g.ids.length >= 2).sort((a, b) => b.ids.length - a.ids.length);
  // P52 · series verificadas por dígito de control: cada caso con SU serie, una decisión para todas
  const verif = {completa: [], sin: []};
  const tiene = (o, f) => o.fuente === f || (o.fuentes || []).includes(f);
  DATOS.dudas.forEach(d => {
    if (DATOS.decisiones[d.id]) return;
    const c = d.opciones.find(o => tiene(o, 'serie_verificada'));
    const b = d.opciones.find(o => tiene(o, 'serie_verificada_sin_control'));
    if (c) verif.completa.push({id: d.id, valor: String(c.valor)});
    if (b) verif.sin.push({id: d.id, valor: String(b.valor)});
  });
  // P53 · todas las recomendadas de confianza alta, cada caso con SU valor, en una decisión
  const altas = pendientes.map(d => ({id: d.id, valor: String(recomendada(d).valor), c: +recomendada(d).confianza || 0}))
    .filter(x => x.c >= ALTA);
  const htmlAltas = altas.length >= 2 ? `<div class="lote"><span>Recomendadas de confianza alta (${ALTA.toFixed(2)} o más)
      <span class="resp">· ${altas.length} dudas, cada una con su valor</span></span>
      <span class="acciones"><button class="btn chico" id="aceptarAltas">Aceptar las ${altas.length}</button></span></div>` : '';
  const htmlVerif = verif.completa.length ? `<div class="lote"><span>Serie del tablero verificada por dígito de control
      <span class="resp">· ${verif.completa.length} casos (cada uno con su serie)</span></span>
      <span class="acciones"><button class="btn chico" id="verifCompleta">Completa</button>
      <button class="btn chico sec" id="verifSin">Sin dígito de control</button></span></div>` : '';
  const atajos = filas.length + (htmlVerif ? 1 : 0) + (htmlAltas ? 1 : 0);
  // en «una a una» va plegado para que la duda quede arriba; en la lista, abierto
  $('lotes').innerHTML = atajos ? `<details class="lotes ${animar ? 'entra' : ''}" ${vista === 'lista' ? 'open' : ''}>
    <summary><b>Aceptar de una vez</b> <span class="resp">· ${atajos} ${atajos === 1 ? 'atajo' : 'atajos'} para decidir varias dudas con un clic</span></summary><p>La opción recomendada se repite en varios casos, o ya está verificada. Un clic decide todas; después puedes cambiar cualquiera.</p>${htmlAltas}${htmlVerif}${
    filas.map((g, i) => `<div class="lote"><span>${esc(g.pieza || g.campo)} · <b>${esc(g.valor)}</b>
      <span class="resp">(${legible(g.fuente)}) · ${g.ids.length} casos</span></span>
      <span class="acciones"><button class="btn chico sec" data-i="${i}">Usar en los ${g.ids.length}</button></span></div>`).join('')}</details>` : '';
  const enviar = async lista => { await post('/api/decidir_varias', {decisiones: lista.map(x => ({id: x.id, valor: x.valor}))}); await cargar(); };
  if (htmlAltas) $('aceptarAltas').onclick = () => enviar(altas);
  if (htmlVerif) {
    $('verifCompleta').onclick = () => enviar(verif.completa);
    $('verifSin').onclick = () => enviar(verif.sin);
  }
  $('lotes').querySelectorAll('button[data-i]').forEach(b => b.onclick = async () => {
    await post('/api/decidir_lote', {ids: filas[+b.dataset.i].ids}); await cargar(); });
}

function pintarLista() {
  const q = busca.trim().toLowerCase();
  visibles = DATOS.dudas.filter(d => filtro === 'todos' || (filtro === 'con' ? conPropuesta(d)
      : filtro === 'sin' ? !conPropuesta(d) : d.motivo === filtro))
    .filter(d => !q || `${d.caso} ${d.campo} ${d.pieza || ''} ${d.columna || ''}`.toLowerCase().includes(q))
    .sort((a, b) => (a.campo + a.caso).localeCompare(b.campo + b.caso));
  document.querySelectorAll('.vistas button').forEach(b => { b.classList.toggle('sel', b.dataset.v === vista);
    b.setAttribute('aria-selected', b.dataset.v === vista); });
  const guiada = vista === 'guiada';
  if (guiada && visibles.length) {
    if (foco < 0 || foco >= visibles.length) {
      const pendiente = visibles.findIndex(d => !DATOS.decisiones[d.id]);
      foco = pendiente < 0 ? 0 : pendiente;
    }
  }
  if (!visibles.length) {
    $('lista').innerHTML = `<div class="vacio ${animar ? 'entra' : ''}">${DATOS.dudas.length
      ? '<b>Nada con este filtro.</b>Cambia el filtro o borra la búsqueda para ver las demás dudas.'
      : '<b>No hay dudas pendientes.</b>Todo lo que el programa pudo leer está en el libro.'}</div>`;
    animar = false; return;
  }
  const aPintar = guiada ? [[visibles[foco], foco]] : visibles.map((d, n) => [d, n]);
  const hechasVisibles = visibles.filter(d => DATOS.decisiones[d.id]).length;
  const cabeceraGuia = guiada ? `<div class="guia">
      <span class="cuenta">Duda <b>${foco + 1}</b> de ${visibles.length} · ${hechasVisibles} ${hechasVisibles === 1 ? 'elegida' : 'elegidas'}</span>
      <span class="pasos"><button class="btn chico sec" id="g-ant" ${foco <= 0 ? 'disabled' : ''}>← Anterior</button>
      <button class="btn chico" id="g-sig" ${foco >= visibles.length - 1 ? 'disabled' : ''}>Siguiente →</button></span></div>` : '';
  $('lista').innerHTML = cabeceraGuia + aPintar.map(([d, n]) => {
    const sel = DATOS.decisiones[d.id], reco = recomendada(d);
    const opciones = d.opciones.map((o, i) => {
      const valor = o.valor === null ? 'No lo tengo' : o.valor;
      const marcada = sel && String(sel.valor) === String(o.valor);
      const c = Math.max(0, Math.min(1, +o.confianza || 0));
      return `<div class="opw"><button class="op ${marcada ? 'sel' : ''}" aria-pressed="${!!marcada}" data-id="${esc(d.id)}" data-val="${o.valor === null ? '' : esc(o.valor)}">
        <kbd>${i < 9 ? i + 1 : '·'}</kbd>
        <span class="val">${esc(valor)}</span>
        ${o.valor !== null && reco && o.valor === reco.valor ? '<span class="reco">★ recomendada</span>' : ''}
        <span class="linea"><span class="fuente ${esc(o.fuente)}">${legible(o.fuente)}</span>
          <span class="resp">${esc(o.respaldo)}</span></span>
        ${c ? `<span class="conf" title="confianza ${c.toFixed(2)}"><span><i style="--c:${c}"></i></span>${c.toFixed(2)}</span>` : ''}
      </button>${miniaturas(o, d)}</div>`;
    }).join('');
    const propio = sel && !d.opciones.some(o => String(o.valor) === String(sel.valor))
      ? `<div class="propio">Elegiste un valor escrito por ti: <b>${esc(sel.valor)}</b></div>` : '';
    const otro = `<div class="otro" data-id="${esc(d.id)}" data-campo="${esc(d.campo)}">
        <button type="button" class="op otra otro-link"><kbd>O</kbd><span class="val">Otro texto</span>
          <span class="linea"><span class="resp">Ninguna opción es correcta: escribe tú el valor.</span></span></button>
        <form hidden><input placeholder="escribe el texto correcto" aria-label="Otro texto" autocomplete="off">
          <button class="btn chico" type="submit">Usar</button></form><span class="forma"></span></div>`;
    const descartadas = (d.opciones_descartadas || []).length
      ? `<div class="resp">Descartado por la serie: ${d.opciones_descartadas.map(o => esc(o.valor)).join(', ')}</div>` : '';
    const donde = (d.donde_mirar || []).length
      ? `<ul class="donde">${d.donde_mirar.map(t => `<li>${esc(t)}</li>`).join('')}</ul>` : '';
    const fotos = guiada ? fotosDe(d) : [];
    const activa = fotos.find(f => f.tok === fotoActiva[d.id]) || fotos[0];
    const panelFoto = !guiada ? '' : activa ? `<figure style="margin:0">
        <div class="lienzo"><img id="foto-grande" src="/api/foto/${esc(activa.tok)}?tam=grande" data-grande="${esc(activa.tok)}"
          data-pie="${esc(pieDe(d, activa))}" alt="Foto ${esc(activa.foto)}" tabindex="0" role="button" draggable="false"></div>
        <figcaption class="barra-foto">
          <button class="ico" id="f-izq" aria-label="Girar la foto a la izquierda" title="Girar a la izquierda (Mayús + R)">${ICO_IZQ}</button>
          <button class="ico" id="f-der" aria-label="Girar la foto a la derecha" title="Girar a la derecha (R)">${ICO_DER}</button>
          <button class="ico" id="f-amp" aria-label="Ampliar la foto" title="Ampliar">${ICO_AMP}</button>
          <span class="leyenda">${esc(activa.foto)}${activa.texto ? ' · leído: «' + esc(activa.texto) + '»' : ''}${fotos.length > 1 ? ` · ${fotos.length} fotos: pulsa una miniatura para verla aquí` : ''}</span>
        </figcaption></figure>` : '';
    const cuerpoIni = guiada ? `<div class="cuerpo ${activa ? '' : 'sin-foto'}">${panelFoto}<div>` : '';
    const cuerpoFin = guiada ? '</div></div>' : '';
    return `<section class="duda spot ${guiada ? 'guiada' : ''} ${sel ? 'hecha' : ''} ${animar ? 'entra' : ''} ${n === foco ? 'foco' : ''}" style="--i:${guiada ? 0 : Math.min(n, 12)}" tabindex="0" data-n="${n}" data-id="${esc(d.id)}">
      <h2><span class="caso">${esc(d.caso)}</span><span>${esc(d.pieza || d.campo)}</span>
        <span class="motivo ${d.motivo === 'fuentes_en_conflicto' ? 'm-conflicto' : ''}">${legible(d.motivo)}</span>
        ${sel ? '<span class="listo"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 13l4 4L19 7"/></svg>elegida</span>' : ''}</h2>
      <div class="pieza">Pieza: <b>${esc(d.pieza || 'sin identificar')}</b> · <span class="mono">${esc(d.campo)}</span>${d.columna ? ` · columna ${esc(d.columna)}` : ''}</div>
      <div class="detalle">${esc(d.detalle)}</div>
      ${cuerpoIni}${donde}${descartadas}
      <div class="ops">${opciones}</div>${propio}${otro}${cuerpoFin}
    </section>`;
  }).join('');
  animar = false;
  $('lista').querySelectorAll('.op:not(.otra)').forEach(b => b.onclick = () => elegir(b));
  // miniaturas: en «una a una» cambian la foto grande; en la lista abren el visor
  const alMini = i => { if (!guiada) { abrirVisor(i); return; }
    fotoActiva[visibles[foco].id] = i.dataset.grande; pintarLista(); };
  $('lista').querySelectorAll('.minis img').forEach(i => {
    const g = giros[i.dataset.grande] || 0; if (g) i.style.transform = `rotate(${g}deg)`;
    if (guiada && activaTok() === i.dataset.grande) i.classList.add('activa');
    i.onclick = () => alMini(i);
    i.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); alMini(i); } }; });
  const grande = $('foto-grande');
  if (grande) {
    const pintarGiro = () => aplicarGiro(grande, giros[grande.dataset.grande] || 0);
    grande.onload = pintarGiro; if (grande.complete) pintarGiro();
    grande.onclick = () => abrirVisor(grande);
    grande.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); abrirVisor(grande); } };
    $('f-izq').onclick = () => girarGrande(-90); $('f-der').onclick = () => girarGrande(90);
    $('f-amp').onclick = () => abrirVisor(grande);
  }
  if (guiada) {
    const ant = $('g-ant'), sig = $('g-sig');
    if (ant) ant.onclick = () => irA(foco - 1);
    if (sig) sig.onclick = () => irA(foco + 1);
  }
  $('lista').querySelectorAll('.otro').forEach(prepararOtro);
  if (!guiada) $('lista').querySelectorAll('.duda').forEach(s => s.onfocus = () => marcarFoco(+s.dataset.n, false));
}

function activaTok() {
  const d = visibles[foco]; if (!d) return null;
  const fotos = fotosDe(d); return (fotos.find(f => f.tok === fotoActiva[d.id]) || fotos[0] || {}).tok || null;
}
function girarGrande(cuanto) {
  const g = $('foto-grande'); if (!g) return;
  giros[g.dataset.grande] = ((giros[g.dataset.grande] || 0) + cuanto) % 360;
  aplicarGiro(g, giros[g.dataset.grande]);
  $('lista').querySelectorAll('.minis img').forEach(i => { if (i.dataset.grande === g.dataset.grande) i.style.transform = `rotate(${giros[g.dataset.grande]}deg)`; });
}
function irA(n) {
  if (!visibles.length) return;
  foco = Math.max(0, Math.min(visibles.length - 1, n)); animar = true; pintarLista();
  const t = $('lista').querySelector('.duda'); if (t) t.focus({preventScroll: true});
}

function miniaturas(o, d) {
  if (o.valor === null) return '';
  const fotos = (o.fotos || []).slice(0, 3);
  if (!fotos.length) return '';
  return `<div class="minis">${fotos.map(f => {
    const tok = f.token_recorte || f.token;
    if (!tok) return `<span class="sinfoto" title="${esc(f.foto)}">${esc(f.fuente)}</span>`;
    const pie = pieDe(d, f);
    return `<img loading="lazy" tabindex="0" role="button" src="/api/foto/${esc(tok)}?tam=mini" data-grande="${esc(f.token || tok)}" data-pie="${esc(pie)}" alt="Foto ${esc(f.foto)}: ampliar" title="${esc(f.foto)}">`;
  }).join('')}</div>`;
}

const V = {tok: null, zoom: 1, x: 0, y: 0};
const pintarVisor = () => aplicarGiro($('visor-img'), giros[V.tok] || 0, V.zoom, V.x, V.y);
function abrirVisor(img) {
  V.tok = img.dataset.grande; V.zoom = 1; V.x = 0; V.y = 0;
  const v = $('visor-img'); v.style.transform = ''; v.onload = pintarVisor;
  v.src = `/api/foto/${V.tok}?tam=grande`;
  $('visor-pie').textContent = img.dataset.pie;
  $('visor').classList.add('abierto');
  if (v.complete) pintarVisor();
}
function cerrarVisor() {
  if (!$('visor').classList.contains('abierto')) return;
  $('visor').classList.remove('abierto');
  if (vista === 'guiada') pintarLista();          // la foto grande conserva el giro elegido en el visor
}
function accionVisor(a) {
  if (a === 'cerrar') { cerrarVisor(); return; }
  if (a === 'izq' || a === 'der') giros[V.tok] = ((giros[V.tok] || 0) + (a === 'der' ? 90 : -90)) % 360;
  if (a === 'mas') V.zoom = Math.min(4, V.zoom * 1.4);
  if (a === 'menos') { V.zoom = Math.max(1, V.zoom / 1.4); if (V.zoom === 1) { V.x = 0; V.y = 0; } }
  pintarVisor();
}
$('visor').onclick = e => { if (e.target === $('visor')) cerrarVisor(); };
$('visor-herr').querySelectorAll('button').forEach(b => b.onclick = e => { e.stopPropagation(); accionVisor(b.dataset.a); });
(function arrastre() {       // con zoom, la foto se mueve arrastrando (ratón o dedo)
  const v = $('visor-img'); let ini = null;
  v.onpointerdown = e => { if (V.zoom <= 1) return; ini = {x: e.clientX - V.x, y: e.clientY - V.y};
    v.classList.add('arrastra'); try { v.setPointerCapture(e.pointerId); } catch (err) {} };
  v.onpointermove = e => { if (!ini) return; V.x = e.clientX - ini.x; V.y = e.clientY - ini.y; pintarVisor(); };
  v.onpointerup = v.onpointercancel = () => { ini = null; v.classList.remove('arrastra'); };
  v.ondblclick = () => accionVisor(V.zoom > 1 ? 'menos' : 'mas');
})();

function prepararOtro(caja) {
  const enlace = caja.querySelector('.otro-link'), form = caja.querySelector('form');
  const entrada = form.querySelector('input'), nota = caja.querySelector('.forma');
  let confirmado = null;
  const abrir = () => { enlace.hidden = true; form.hidden = false; entrada.focus(); };
  enlace.onclick = abrir;
  entrada.oninput = () => { confirmado = null; nota.textContent = ''; form.querySelector('button').textContent = 'Usar'; };
  form.onsubmit = async ev => {
    ev.preventDefault();
    const valor = entrada.value.trim();
    if (!valor) return;
    if (confirmado !== valor) {
      const r = await (await post('/api/revisar', {campo: caja.dataset.campo, valor})).json();
      if (r.valido) { await decidir(caja.dataset.id, r.valor); return; }
      nota.textContent = `No tiene la forma habitual de este campo${r.motivo ? ' (' + r.motivo + ')' : ''}. Pulsa otra vez para usarlo igual.`;
      form.querySelector('button').textContent = 'Usar igual';
      confirmado = valor;
      return;
    }
    await decidir(caja.dataset.id, valor);
  };
}

async function elegir(boton) {
  // pulsar la opción ya elegida la deshace: nada queda decidido sin querer
  if (boton.classList.contains('sel') && boton.dataset.val !== '') {
    await post('/api/deshacer', {id: boton.dataset.id}); await cargar(); return;
  }
  await decidir(boton.dataset.id, boton.dataset.val);
}

async function decidir(id, valor) {
  const r = await post('/api/decidir', {id, valor: valor === '' ? null : valor});
  if (!r.ok) { aviso('No se pudo registrar la decisión. Recarga la página e inténtalo de nuevo.', 'error'); return; }
  const era = visibles[foco] && visibles[foco].id === id;
  await cargar();
  if (vista === 'guiada' && era && valor !== '') {
    // la tarjeta muestra un instante lo elegido y pasa a la siguiente que falte
    const sig = visibles.findIndex((d, i) => i > foco && !DATOS.decisiones[d.id]);
    const otra = sig >= 0 ? sig : visibles.findIndex(d => !DATOS.decisiones[d.id]);
    if (otra >= 0 && otra !== foco) setTimeout(() => { if (visibles[foco] && visibles[foco].id === id) irA(otra); }, RM ? 0 : 450);
  }
}

function marcarFoco(n, mover = true) {
  if (!visibles.length) return;
  foco = Math.max(0, Math.min(visibles.length - 1, n));
  const tarjetas = $('lista').querySelectorAll('.duda');
  tarjetas.forEach((s, i) => s.classList.toggle('foco', i === foco));
  if (mover && tarjetas[foco]) { tarjetas[foco].focus({preventScroll: true});
    tarjetas[foco].scrollIntoView({block: 'nearest', behavior: RM ? 'auto' : 'smooth'}); }
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { cerrarVisor(); cerrarFiesta(); return; }
  if (e.target.closest('input, textarea, select') || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if ($('visor').classList.contains('abierto')) {
    if (k === 'r') accionVisor(e.shiftKey ? 'izq' : 'der');
    if (k === '+' || k === '=') accionVisor('mas');
    if (k === '-') accionVisor('menos');
    return;
  }
  if (k === '/') { e.preventDefault(); $('busca').focus(); return; }
  const guiada = vista === 'guiada';
  if (k === 'j' || k === 'k' || (guiada && (k === 'arrowright' || k === 'arrowleft'))) {
    e.preventDefault(); const paso = (k === 'j' || k === 'arrowright') ? 1 : -1;
    if (guiada) irA(foco + paso); else marcarFoco(foco + paso); return; }
  if (k === 'r' && guiada) { girarGrande(e.shiftKey ? -90 : 90); return; }
  const tarjeta = guiada ? $('lista').querySelector('.duda') : $('lista').querySelectorAll('.duda')[foco];
  if (!tarjeta) return;
  if (k === 'o') { const enlace = tarjeta.querySelector('.otro-link'); if (enlace) { e.preventDefault(); enlace.click(); } return; }
  if (/^[1-9]$/.test(k)) { const b = tarjeta.querySelectorAll('.op:not(.otra)')[+k - 1];
    if (b) { e.preventDefault(); elegir(b).then(() => { if (!guiada) marcarFoco(foco); }); } return; }
  if (k === 'enter' && (e.target === tarjeta || e.target === document.body)) {
    const d = visibles[foco], reco = d && recomendada(d);
    if (reco) { e.preventDefault(); decidir(d.id, String(reco.valor)).then(() => { if (!guiada) marcarFoco(foco + 1); }); }
  }
});
$('busca').oninput = e => { busca = e.target.value; foco = -1; pintarLista(); };
window.addEventListener('resize', () => { const g = $('foto-grande'); if (g) aplicarGiro(g, giros[g.dataset.grande] || 0);
  if ($('visor').classList.contains('abierto')) pintarVisor(); });

async function cargar() {
  let e;
  try {
    DATOS = await (await fetch('/api/dudas')).json();
    e = await (await fetch('/api/estado')).json();
  } catch (error) { aviso('No se pudo hablar con el panel. Comprueba que la ventana del programa sigue abierta y recarga.', 'error'); return; }
  const n = Object.keys(DATOS.decisiones).length, total = DATOS.dudas.length;
  $('meta').textContent = `${nombre(e.libro)} · ${e.resumen.con_al_menos_una_opcion} de ${DATOS.resumen.dudas} dudas traen propuesta`;
  $('titular').textContent = total ? (n >= total ? 'Todo elegido: falta guardar' : 'Panel de dudas') : 'Sin dudas pendientes';
  correr($('k-casos'), e.casos); correr($('k-dudas'), total); correr($('k-hechas'), n);
  const parte = total ? Math.min(1, n / total) : 1;
  correr($('pct'), Math.round(parte * 100));
  $('arco').style.strokeDashoffset = (138.2 * (1 - parte)).toFixed(1);
  $('anillo').classList.toggle('lleno', parte >= 1);
  if (!$('aviso').classList.contains('bien') || n) aviso(n ? `${n} ${n === 1 ? 'decisión elegida' : 'decisiones elegidas'}, sin guardar.` : 'Nada elegido todavía.');
  $('guardar').disabled = !n;
  pintarFiltros(); pintarLista();
}

// ---- celebración: sólo cuando se guarda y ya no queda ninguna duda ----
let rafFiesta = 0, relojFiesta = 0;
function cerrarFiesta() { $('fiesta').classList.remove('va'); cancelAnimationFrame(rafFiesta); clearTimeout(relojFiesta); }
$('fiesta').onclick = cerrarFiesta;
function celebrar(texto) {
  $('fiesta-txt').textContent = texto; $('fiesta').classList.add('va');
  try { navigator.vibrate && navigator.vibrate(60); } catch (e) {}
  relojFiesta = setTimeout(cerrarFiesta, 3800);
  if (RM) return;
  const lienzo = $('confeti'), dpr = Math.min(2, window.devicePixelRatio || 1);
  const W = lienzo.width = innerWidth * dpr, H = lienzo.height = innerHeight * dpr, ctx = lienzo.getContext('2d');
  const colores = ['#ffffff', '#bff3d2', '#7fe0a6', '#2fb9d3', '#ffe08a'];
  const piezas = Array.from({length: 120}, () => ({x: W / 2, y: H * .45, vx: (Math.random() - .5) * 22 * dpr,
    vy: (-Math.random() * 20 - 6) * dpr, g: (.45 + Math.random() * .3) * dpr, r: Math.random() * 6.28, vr: (Math.random() - .5) * .4,
    w: (5 + Math.random() * 7) * dpr, c: colores[Math.floor(Math.random() * colores.length)]}));
  const t0 = performance.now();
  const cuadro = now => {
    ctx.clearRect(0, 0, W, H);
    piezas.forEach(p => { p.vy += p.g; p.x += p.vx; p.y += p.vy; p.vx *= .99; p.r += p.vr;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r); ctx.fillStyle = p.c; ctx.fillRect(-p.w / 2, -p.w / 4, p.w, p.w / 2); ctx.restore(); });
    if (now - t0 < 2800 && !document.hidden) rafFiesta = requestAnimationFrame(cuadro); else ctx.clearRect(0, 0, W, H);
  };
  rafFiesta = requestAnimationFrame(cuadro);
}

$('guardar').onclick = async () => {
  $('guardar').disabled = true;
  const r = await post('/api/guardar');
  if (!r.ok) { aviso('No se pudo guardar. Cierra el Excel si lo tienes abierto y vuelve a pulsar Guardar.', 'error'); $('guardar').disabled = false; return; }
  const d = await r.json();
  $('descargar').hidden = false;
  await cargar();
  aviso(`Guardado: ${d.escritos} ${d.escritos === 1 ? 'celda escrita' : 'celdas escritas'} en ${nombre(d.salida)}`, 'bien');
  if (d.dudas_restantes === 0) celebrar(`${d.escritos} ${d.escritos === 1 ? 'celda escrita' : 'celdas escritas'} en ${nombre(d.salida)}. El libro original no se tocó.`);
};
$('descargar').onclick = () => { location.href = '/api/descargar'; };
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
