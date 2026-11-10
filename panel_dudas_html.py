#!/usr/bin/env python3
"""Página de dudas autocontenida (P11): un solo HTML, sin red, fácil de leer.

Genera un folio de revisión para un libro concreto:

    python panel_dudas_html.py --libro "mi_libro.xlsx" --lecturas "lecturas.json" --salida dudas.html

Qué muestra, en este orden:
1. **resumen**: cuántas celdas faltan, cuántas se pueden rellenar solas, cuántas necesitan a una
   persona, y qué se ha detectado raro;
2. **patrones**: confusiones del OCR que se repiten, columnas constantes y casos donde la carpeta
   contradice a la etiqueta (con su riesgo);
3. **dudas**: una tarjeta por caso y campo, con las opciones como botones, de dónde sale cada una,
   y dónde mirar.

Todo el diseño va dentro del HTML (sin CDN): se abre igual en el equipo del taller, sin internet.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from utilidades.dudas_y_opciones import construir_dudas, resumen_dudas
from utilidades.patrones import resumen as resumen_patrones


def _leer_libro(ruta: Path) -> dict[str, dict]:
    from openpyxl import load_workbook
    from utilidades.relleno_libro import _texto
    libro = load_workbook(ruta, data_only=True)
    hoja = libro[libro.sheetnames[0]]
    indice = {}
    for columna in range(1, hoja.max_column + 1):
        titulo = _texto(hoja.cell(7, columna).value).lower()
        for clave in ("test_number", "week", "temperature_condition", "module_version",
                      "module_part_number", "engineering_level", "inflator_type"):
            if titulo.startswith(clave.split("_")[0][:5]):
                indice.setdefault(clave, columna)
    filas = {}
    for fila in range(8, hoja.max_row + 1):
        numero = _texto(hoja.cell(fila, indice.get("test_number", 3)).value).strip()
        if not numero.isdigit():
            continue
        filas[numero] = {clave: _texto(hoja.cell(fila, columna).value)
                         for clave, columna in indice.items()}
    return filas


PLANTILLA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dudas del libro · V-Matrix</title>
<style>
  :root{
    --fondo:#0b1220; --panel:#111b2e; --panel2:#16233a; --borde:#1f3350;
    --texto:#e8eef9; --tenue:#94a7c4; --acento:#4da3ff; --ok:#2fbf71; --aviso:#f0b429;
    --mal:#ef5b5b; --radio:14px; --sombra:0 10px 30px rgba(0,0,0,.35);
    --fuente: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  }
  @media (prefers-color-scheme: light){
    :root{--fondo:#f5f7fb;--panel:#fff;--panel2:#f0f4fa;--borde:#dbe4f0;
          --texto:#12203a;--tenue:#5b6f8c;--sombra:0 8px 24px rgba(20,40,80,.08)}
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--fondo);color:var(--texto);font-family:var(--fuente);
       line-height:1.5;-webkit-font-smoothing:antialiased}
  .envoltorio{max-width:1120px;margin:0 auto;padding:32px 20px 80px}
  header.hero{display:flex;gap:24px;align-items:center;justify-content:space-between;
              flex-wrap:wrap;margin-bottom:28px}
  .marca{display:flex;gap:14px;align-items:center}
  .logo{width:46px;height:46px;border-radius:12px;background:linear-gradient(135deg,#4da3ff,#7b5cff);
        display:grid;place-items:center;font-weight:700;font-size:18px;color:#fff}
  h1{font-size:1.55rem;margin:0;letter-spacing:-.02em}
  .sub{margin:2px 0 0;color:var(--tenue);font-size:.92rem}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;
        margin-bottom:26px}
  .kpi{background:var(--panel);border:1px solid var(--borde);border-radius:var(--radio);
       padding:16px 18px;box-shadow:var(--sombra)}
  .kpi b{display:block;font-size:1.9rem;letter-spacing:-.03em}
  .kpi span{color:var(--tenue);font-size:.82rem;text-transform:uppercase;letter-spacing:.06em}
  .kpi.ok b{color:var(--ok)} .kpi.aviso b{color:var(--aviso)} .kpi.mal b{color:var(--mal)}
  section{margin-bottom:34px}
  section h2{font-size:1.05rem;margin:0 0 12px;display:flex;align-items:center;gap:10px}
  section h2 .pastilla{background:var(--panel2);border:1px solid var(--borde);color:var(--tenue);
        font-size:.75rem;padding:2px 9px;border-radius:999px;font-weight:600}
  .rejilla{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
  .tarjeta{background:var(--panel);border:1px solid var(--borde);border-radius:var(--radio);
           padding:16px 18px;box-shadow:var(--sombra);transition:transform .18s ease,
           border-color .18s ease}
  .tarjeta:hover{transform:translateY(-2px);border-color:var(--acento)}
  .tarjeta h3{margin:0 0 6px;font-size:.98rem}
  .tarjeta p{margin:0;color:var(--tenue);font-size:.88rem}
  .etiqueta{display:inline-block;font-size:.72rem;padding:2px 8px;border-radius:999px;
            border:1px solid var(--borde);color:var(--tenue);margin-left:6px}
  .riesgo-alto .etiqueta{color:var(--mal);border-color:var(--mal)}
  .riesgo-medio .etiqueta{color:var(--aviso);border-color:var(--aviso)}
  .duda{background:var(--panel);border:1px solid var(--borde);border-radius:var(--radio);
        padding:16px 18px;margin-bottom:12px;border-left:4px solid var(--acento)}
  .duda.motivo-fuentes_en_conflicto{border-left-color:var(--aviso)}
  .duda.motivo-sin_lectura_valida{border-left-color:var(--mal)}
  .duda-cabecera{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
                 align-items:baseline}
  .duda-caso{font-weight:700} .duda-campo{color:var(--acento);font-family:ui-monospace,monospace;
        font-size:.86rem}
  .duda-detalle{color:var(--tenue);font-size:.86rem;margin:6px 0 12px}
  .opciones{display:flex;flex-wrap:wrap;gap:8px}
  .opcion{border:1px solid var(--borde);background:var(--panel2);color:var(--texto);
          padding:8px 12px;border-radius:10px;cursor:pointer;font:inherit;font-size:.88rem;
          transition:all .15s ease;display:flex;flex-direction:column;gap:2px;text-align:left}
  .opcion:hover{border-color:var(--acento);transform:translateY(-1px)}
  .opcion:focus-visible{outline:3px solid var(--acento);outline-offset:2px}
  .opcion.elegida{border-color:var(--ok);box-shadow:0 0 0 2px rgba(47,191,113,.25)}
  .opcion small{color:var(--tenue);font-size:.72rem}
  .donde{color:var(--tenue);font-size:.82rem;margin-top:10px}
  .duda-cuerpo{display:grid;gap:16px;grid-template-columns:1fr}
  @media (min-width:820px){.duda-cuerpo.con-imagen{grid-template-columns:1fr 260px}}
  .evidencia{margin:0;border:1px solid var(--borde);border-radius:12px;overflow:hidden;
             background:var(--panel2)}
  .evidencia img{display:block;width:100%;height:auto}
  .evidencia figcaption{font-size:.72rem;color:var(--tenue);padding:6px 8px;
             border-top:1px solid var(--borde);word-break:break-all}
  .acciones{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap}
  .dudo{border:1px solid var(--aviso);background:transparent;color:var(--aviso);padding:7px 12px;
        border-radius:10px;cursor:pointer;font:inherit;font-size:.85rem}
  .dudo[aria-pressed=true]{background:var(--aviso);color:#241a00;font-weight:600}
  .dudo:focus-visible{outline:3px solid var(--aviso);outline-offset:2px}
  .marcada{box-shadow:0 0 0 2px var(--aviso)}
  #marcadas{position:fixed;right:16px;bottom:16px;max-width:320px;background:var(--panel);
    border:1px solid var(--aviso);border-radius:12px;padding:12px 14px;font-size:.82rem;
    box-shadow:var(--sombra);display:none}
  #marcadas.abierto{display:block}
  #marcadas h4{margin:0 0 6px;font-size:.85rem}
  #marcadas ul{margin:0;padding-left:16px;max-height:180px;overflow:auto}
  #marcadas textarea{width:100%;height:70px;margin-top:8px;background:var(--panel2);
    color:var(--texto);border:1px solid var(--borde);border-radius:8px;font-family:ui-monospace,monospace;
    font-size:.75rem}
  .vacio{background:var(--panel2);border:1px dashed var(--borde);border-radius:var(--radio);
         padding:22px;text-align:center;color:var(--tenue)}
  footer{color:var(--tenue);font-size:.8rem;text-align:center;margin-top:40px}
  @media (prefers-reduced-motion: reduce){*{transition:none!important;transform:none!important}}
</style>
</head>
<body>
<div class="envoltorio">
  <header class="hero">
    <div class="marca">
      <div class="logo">VM</div>
      <div>
        <h1>Dudas del libro</h1>
        <p class="sub">__LIBRO__ · __CASOS__ casos · generado el __FECHA__</p>
      </div>
    </div>
  </header>

  <div class="kpis">
    <div class="kpi aviso"><b>__DUDAS__</b><span>celdas por decidir</span></div>
    <div class="kpi"><b>__BLOQUE__</b><span>rellenables solas</span></div>
    <div class="kpi ok"><b>__CONSTANTES__</b><span>columnas constantes</span></div>
    <div class="kpi mal"><b>__RIESGO__</b><span>carpeta contra etiqueta</span></div>
  </div>

  __PATRONES__

  <section>
    <h2>Qué hay que decidir <span class="pastilla">__DUDAS__ pendientes</span></h2>
    <p class="sub" style="margin:-4px 0 14px">Cada tarjeta es una celda vacía del libro. Elige una
    opción y se escribirá en el Excel; «dejar vacío» también es una decisión válida.</p>
    __DUDAS_HTML__
  </section>

  <div id="marcadas" aria-live="polite"><h4>Dudas marcadas</h4><ul id="lista"></ul>
    <textarea id="copia" readonly aria-label="Lista para copiar"></textarea></div>
  <footer>V-Matrix · V16.0.26 · esta página no envía datos a ningún sitio: todo va dentro del archivo.</footer>
</div>
<script>
  document.querySelectorAll('.duda').forEach((duda, i) => {
    const botones = [...duda.querySelectorAll('.opcion')];
    botones.forEach((boton, j) => {
      boton.addEventListener('click', () => {
        botones.forEach(otro => otro.classList.remove('elegida'));
        boton.classList.add('elegida');
        const estado = duda.querySelector('.elegido');
        if (estado) {
          estado.textContent = 'Elegido: ' + boton.dataset.valor;
        }
      });
      boton.addEventListener('keydown', (evento) => {
        if (evento.key === 'Enter' || evento.key === ' ') { evento.preventDefault(); boton.click(); }
      });
    });
    // «Tengo duda»: marca la tarjeta y la apunta en el panel de la esquina
    const boton = duda.querySelector('.dudo');
    if (boton) {
      boton.addEventListener('click', () => {
        const activo = boton.getAttribute('aria-pressed') === 'true';
        boton.setAttribute('aria-pressed', String(!activo));
        duda.classList.toggle('marcada', !activo);
        actualizarMarcadas();
      });
    }
    // atajos: número = elegir esa opción, J/K = siguiente/anterior
    document.addEventListener('keydown', (evento) => {
      if (evento.target.matches('input, textarea')) return;
      const numero = Number.parseInt(evento.key, 10);
      if (numero >= 1 && numero <= botones.length) botones[numero - 1].click();
    });
  });

  function actualizarMarcadas() {
    const panel = document.getElementById('marcadas');
    const lista = document.getElementById('lista');
    if (!panel) return;
    const marcadas = [...document.querySelectorAll('.duda.marcada')];
    panel.classList.toggle('abierto', marcadas.length > 0);
    lista.replaceChildren(...marcadas.map((d) => {
      const li = document.createElement('li');
      li.textContent = 'Caso ' + d.dataset.caso + ' · ' + d.dataset.campo;
      return li;
    }));
    document.getElementById('copia').value = JSON.stringify(
      marcadas.map((d) => ({ caso: d.dataset.caso, campo: d.dataset.campo,
                             decision: 'duda_humana' })));
  }
</script>
</body>
</html>
"""


def _tarjeta_patron(titulo: str, detalle: str, etiqueta: str = "", clase: str = "") -> str:
    return (f'<div class="tarjeta {clase}"><h3>{html.escape(titulo)}'
            f'{f"<span class=\'etiqueta\'>{html.escape(etiqueta)}</span>" if etiqueta else ""}'
            f'</h3><p>{html.escape(detalle)}</p></div>')


def _seccion_patrones(patrones: dict) -> str:
    bloques = []
    if patrones["confusiones"]:
        tarjetas = "".join(
            _tarjeta_patron(f"{c['campo']}: {c['confusion']}",
                            f"{c['explicacion']} ({', '.join(c['casos'][:4])})",
                            f"×{c['repeticiones']}")
            for c in patrones["confusiones"][:6])
        bloques.append('<section><h2>Patrones del OCR <span class="pastilla">se repiten</span></h2>'
                       f'<div class="rejilla">{tarjetas}</div></section>')
    if patrones["carpeta_contra_etiqueta"]:
        tarjetas = "".join(
            _tarjeta_patron(f"{c['caso']} · {c['campo']}",
                            f"la carpeta dice «{c['carpeta']}» y la etiqueta "
                            f"{', '.join(list(c['lecturas_contrarias'])[:3])}",
                            c["riesgo"], f"riesgo-{c['riesgo']}")
            for c in patrones["carpeta_contra_etiqueta"][:8])
        bloques.append('<section><h2>La carpeta contradice a la etiqueta '
                       '<span class="pastilla">revisar primero</span></h2>'
                       f'<div class="rejilla">{tarjetas}</div></section>')
    if patrones["constantes"]:
        tarjetas = "".join(
            _tarjeta_patron(f"{c['campo']} = {c['valor']}",
                            f"igual en {c['filas']} filas · se puede rellenar en bloque")
            for c in patrones["constantes"][:12])
        bloques.append('<section><h2>Columnas constantes '
                       '<span class="pastilla">rellenar en bloque</span></h2>'
                       f'<div class="rejilla">{tarjetas}</div></section>')
    return "\n".join(bloques)


def _imagen_embebida(ruta: str) -> str:
    """Devuelve un data URI si el archivo existe (así la página se abre en cualquier equipo)."""
    import base64
    from pathlib import Path as _P
    archivo = _P(ruta)
    if not archivo.is_file():
        return ""
    sufijo = archivo.suffix.lower().lstrip(".") or "png"
    tipo = "jpeg" if sufijo in ("jpg", "jpeg") else sufijo
    return f"data:image/{tipo};base64," + base64.b64encode(archivo.read_bytes()).decode()


def _tarjeta_duda(duda: dict) -> str:
    opciones = []
    for opcion in duda["opciones"]:
        valor = opcion.get("valor")
        texto = "Dejar vacío" if valor in (None, "") else str(valor)
        detalle = opcion.get("detalle") or str(opcion.get("fuente") or "").replace("_", " ")
        elegida = " elegida" if valor == duda.get("opcion_recomendada") else ""
        opciones.append(
            f'<button type="button" class="opcion{elegida}" data-valor="{html.escape(texto)}" '
            f'aria-label="{html.escape(texto)} · {html.escape(str(detalle))}">'
            f'<span>{html.escape(texto)}</span><small>{html.escape(str(detalle))}</small></button>')
    donde = "".join(f"<li>{html.escape(str(punto))}</li>"
                    for punto in (duda.get("donde_mirar") or [])[:4])
    imagen = duda.get("imagen") or ""
    datos = _imagen_embebida(imagen) if imagen else ""
    evidencia = ""
    if datos:
        evidencia = (f'<figure class="evidencia"><img src="{datos}" '
                     f'alt="Evidencia del caso {html.escape(str(duda["caso"]))}">'
                     f'<figcaption>{html.escape(imagen)}</figcaption></figure>')
    bloque_valores = (
        f'<div><p class="duda-detalle">{html.escape(str(duda.get("detalle") or ""))}</p>'
        f'<div class="opciones">{"".join(opciones)}</div>'
        + (f'<div class="donde">Dónde mirar:<ul>{donde}</ul></div>' if donde else "")
        + '</div>' + evidencia)
    columna = f' · columna {duda["columna"]}' if duda.get("columna") else ""
    return (f'<div class="duda motivo-{html.escape(str(duda.get("motivo")))}" '
            f'data-caso="{html.escape(str(duda["caso"]))}" '
            f'data-campo="{html.escape(duda["campo"])}">'
            f'<div class="duda-cabecera"><span class="duda-caso">Caso '
            f'{html.escape(str(duda["caso"]))}</span>'
            f'<span class="duda-campo">{html.escape(duda["campo"])}{html.escape(columna)}</span></div>'
            f'<div class="duda-cuerpo{" con-imagen" if datos else ""}">{bloque_valores}</div>'
            f'<div class="acciones"><button type="button" class="dudo" aria-pressed="false">'
            f'Tengo duda · mandar a revisar</button></div>'
            '</div>')


def generar_desde_dudas(dudas: list[dict], salida: Path, titulo: str = "Dudas del tablero",
                        subtitulo: str = "", patrones: dict | None = None) -> dict:
    """Escribe la página a partir de una lista de dudas ya construida (sin libro)."""
    from datetime import date

    patrones = patrones or {"confusiones": [], "constantes": [], "carpeta_contra_etiqueta": []}
    documento = (PLANTILLA
                 .replace("__LIBRO__", html.escape(titulo))
                 .replace("__CASOS__", subtitulo or str(len({d.get("caso") for d in dudas})))
                 .replace("__FECHA__", date.today().isoformat())
                 .replace("__DUDAS__", str(len(dudas)))
                 .replace("__BLOQUE__", "0")
                 .replace("__CONSTANTES__", str(len(patrones["constantes"])))
                 .replace("__RIESGO__", str(len(patrones["carpeta_contra_etiqueta"])))
                 .replace("__PATRONES__", _seccion_patrones(patrones))
                 .replace("__DUDAS_HTML__", "".join(_tarjeta_duda(d) for d in dudas)
                          or '<div class="vacio">Nada pendiente.</div>'))
    Path(salida).write_text(documento, encoding="utf-8")
    return {"dudas": len(dudas), "salida": str(salida)}


def generar(libro: Path, lecturas: Path, salida: Path) -> dict:
    from datetime import date
    datos_lecturas = json.loads(Path(lecturas).read_text(encoding="utf-8"))
    filas = _leer_libro(libro)
    dudas = construir_dudas(filas, datos_lecturas)
    patrones = resumen_patrones(datos_lecturas, filas, tuple(
        campo for fila in filas.values() for campo in fila))
    informe = resumen_dudas(dudas) if callable(resumen_dudas) else {}
    bloque = informe.get("vale_la_pena_confirmar", 0) if isinstance(informe, dict) else 0
    documento = (PLANTILLA
                 .replace("__LIBRO__", html.escape(Path(libro).name))
                 .replace("__CASOS__", str(len(filas)))
                 .replace("__FECHA__", date.today().isoformat())
                 .replace("__DUDAS__", str(len(dudas)))
                 .replace("__BLOQUE__", str(bloque))
                 .replace("__CONSTANTES__", str(len(patrones["constantes"])))
                 .replace("__RIESGO__", str(len(patrones["carpeta_contra_etiqueta"])))
                 .replace("__PATRONES__", _seccion_patrones(patrones))
                 .replace("__DUDAS_HTML__", "".join(_tarjeta_duda(d) for d in dudas)
                          or '<div class="vacio">No hay celdas vacías: el libro está completo.</div>'))
    Path(salida).write_text(documento, encoding="utf-8")
    return {"dudas": len(dudas), "constantes": len(patrones["constantes"]),
            "riesgos": len(patrones["carpeta_contra_etiqueta"]),
            "confusiones": len(patrones["confusiones"]), "salida": str(salida)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Folio de dudas en un HTML autocontenido")
    parser.add_argument("--libro", required=True)
    parser.add_argument("--lecturas", required=True)
    parser.add_argument("--salida", default="dudas.html")
    args = parser.parse_args(argv)
    resultado = generar(Path(args.libro), Path(args.lecturas), Path(args.salida))
    print(f"página escrita en {resultado['salida']}: {resultado['dudas']} dudas · "
          f"{resultado['constantes']} columnas constantes · {resultado['riesgos']} riesgos · "
          f"{resultado['confusiones']} patrones de OCR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
