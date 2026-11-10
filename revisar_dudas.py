#!/usr/bin/env python3
"""P42 · cola de confirmación humana: una duda, una foto, una decisión.

    python3 revisar_dudas.py --evidencia evidencia_tablero_p42.json \
        --referencia Book-10-Examples_CORREGIDO.xlsx \
        --decisiones decisiones_p42.json \
        --precedentes precedentes_p42.json \
        --fotos /var/tmp/fotos --salida confirmar.html

Genera **un solo archivo HTML** que se abre con doble clic, sin red, sin servidor y sin instalar
nada: muestra una etiqueta cada vez, con su recorte ampliado y las opciones posibles. Al final
descarga dos archivos:

  decisiones_p42.json ... las decisiones de esta sesión (lo lee `rellenar_tablero_p42.py`)
  precedentes_p42.json .. lo que el sistema aprende: patrón de cola -> valor confirmado

Reglas que respeta, y que vienen de la revisión de Astra:

  * **No decide nada por su cuenta.** La opción que sugiere el aprendizaje aparece marcada como
    «aprendida» y con cuántos casos la apoyan; nunca se aplica sola.
  * Cada opción dice **de dónde sale** (código, OCR, libro anterior, aprendizaje). Sin origen no
    hay opción.
  * «Otro» siempre está: escribe el valor y queda registrado como decisión humana.
  * Si no lo tienes claro, «Dejar en blanco» es una respuesta válida y no penaliza.
  * Un patrón con menos de 3 casos se avisa como **flojo**: puede ser casualidad.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
from pathlib import Path

import cv2
import numpy as np

try:
    import zxingcpp
except ImportError:                                  # sin la librería se sigue, sin recortes finos
    zxingcpp = None

CAMPOS = {
    "dashboard_serial_number": "serie del tablero",
    "dashboard_date": "fecha del tablero",
    "dashboard_part_number": "número de parte",
    "dashboard_engineering_level": "nivel de ingeniería",
}
MINIMO_PARA_FIARSE = 3        # menos casos que esto = patrón flojo, se avisa


# ---------------------------------------------------------------------------------------
# recortes
# ---------------------------------------------------------------------------------------
def caja_del_datamatrix(imagen) -> tuple | None:
    """Dónde está el DataMatrix en la foto, en coordenadas de la foto. Pura salvo por zxing."""
    if zxingcpp is None or imagen is None or imagen.size == 0:
        return None
    gris = cv2.cvtColor(cv2.cvtColor(
        cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(
            cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)), cv2.COLOR_GRAY2BGR), cv2.COLOR_BGR2GRAY)
    gris3 = cv2.cvtColor(gris, cv2.COLOR_GRAY2BGR)
    for escala in (1.0, 0.65, 0.45):
        for vista in (imagen, gris3):
            muestra = vista if escala == 1.0 else cv2.resize(
                vista, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
            try:
                lecturas = zxingcpp.read_barcodes(
                    muestra, formats=zxingcpp.BarcodeFormat.DataMatrix)
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


def recorte_de_etiqueta(imagen, lado_mayor: int = 1100):
    """Recorte alrededor del DataMatrix: el código y la serie impresa que lo acompaña."""
    alto, ancho = imagen.shape[:2]
    caja = caja_del_datamatrix(imagen)
    if caja:
        x0, y0, x1, y1 = caja
        ancho_caja, alto_caja = x1 - x0, y1 - y0
        margen_x = ancho_caja * 1.5
        margen_y = alto_caja * 1.1
        x0 = int(max(0, x0 - margen_x)); x1 = int(min(ancho, x1 + margen_x))
        y0 = int(max(0, y0 - margen_y)); y1 = int(min(alto, y1 + margen_y))
    else:                                     # sin caja: el centro, que es donde suele estar
        x0, x1 = int(ancho * 0.2), int(ancho * 0.8)
        y0, y1 = int(alto * 0.2), int(alto * 0.8)
    trozo = imagen[y0:y1, x0:x1]
    if trozo.size == 0:
        trozo = imagen
    factor = lado_mayor / max(trozo.shape[:2])
    if factor > 1:
        trozo = cv2.resize(trozo, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    return trozo, caja is not None


def a_data_uri(imagen, calidad: int = 80, lado_mayor: int = 1280) -> str:
    """Recorte -> data URI. WebP: misma nitidez aparente, ~1/6 del peso del JPEG que había.

    No se toca nada más de la imagen (ni nitidez, ni contraste, ni recorte): lo que se
    enseña tiene que ser la evidencia, no una versión «mejorada» de la evidencia.
    """
    alto, ancho = imagen.shape[:2]
    factor = min(1.0, lado_mayor / max(alto, ancho, 1))
    if factor < 1.0:
        imagen = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    ok, bufer = cv2.imencode(".webp", imagen, [int(cv2.IMWRITE_WEBP_QUALITY), calidad])
    if not ok:                       # build de OpenCV sin WebP: JPEG, que nunca falta
        ok, bufer = cv2.imencode(".jpg", imagen, [int(cv2.IMWRITE_JPEG_QUALITY), calidad + 4])
        return "data:image/jpeg;base64," + base64.b64encode(bufer.tobytes()).decode("ascii")
    return "data:image/webp;base64," + base64.b64encode(bufer.tobytes()).decode("ascii")


def medidas_de_uri(uri: str) -> tuple[int, int]:
    """Ancho y alto de un data URI. Sirven para reservar el hueco y que nada salte. Pura."""
    if not uri or "," not in uri:
        return (0, 0)
    try:
        crudo = base64.b64decode(uri.split(",", 1)[1])
        imagen = cv2.imdecode(np.frombuffer(crudo, np.uint8), cv2.IMREAD_COLOR)
    except Exception:                                    # noqa: BLE001
        return (0, 0)
    if imagen is None:
        return (0, 0)
    alto, ancho = imagen.shape[:2]
    return (int(ancho), int(alto))


# ---------------------------------------------------------------------------------------
# la cola y las opciones
# ---------------------------------------------------------------------------------------
def patron_de(lectura: dict) -> str:
    """Patrón con el que se aprende: la clase de cola y qué carácter la hace rara. Pura."""
    cola = str(lectura.get("cola_cruda") or "")
    clase = str(lectura.get("clase_cola") or "limpia")
    raros = "".join(sorted({ch for ch in cola if not ch.isalnum()}))
    digitos = "d" if any(ch.isdigit() for ch in cola[1:]) and cola[:1].isalpha() else "a"
    return f"{clase}|largo={len(cola)}|{digitos}|raros={raros or '-'}"


def opciones_de(caso: str, campo: str, dato: dict, referencia: dict, precedentes: dict) -> list[dict]:
    """Las opciones que se le ofrecen al usuario, cada una con su origen. Pura.

    Nunca se inventa una opción: o viene de una lectura, o del libro anterior, o de un patrón
    aprendido, o la escribe el usuario en «Otro».
    """
    opciones: list[dict] = []
    fuente = (dato.get("fuente") or {}).get(campo) or {}
    codificado = str(fuente.get("valor_codificado") or "")
    clase = str(fuente.get("clase_cola") or "")

    if codificado:
        cola_txt = f", cola {clase}" if clase and clase != "limpia" else ""
        opciones.append({"valor": codificado, "origen": "código DataMatrix",
                         "nota": f"lectura directa del código{cola_txt}",
                         "principal": True})
    for lectura in (dato.get("lecturas_crudas") or {}).get(campo) or []:
        valor = str(lectura.get("valor") or "")
        if valor and all(valor != o["valor"] for o in opciones):
            opciones.append({"valor": valor, "origen": f"lectura OCR ({lectura.get('foto', '')})",
                             "nota": f"confianza {float(lectura.get('confianza') or 0):.2f}"})
    anterior = str((referencia.get(caso) or {}).get(campo) or "")
    if anterior and all(anterior != o["valor"] for o in opciones):
        opciones.append({"valor": anterior, "origen": "libro anterior",
                         "nota": "lo que decía el libro, no una lectura"})
    patron = patron_de(fuente)
    aprendido = (precedentes.get(patron) or {})
    if aprendido.get("valor"):
        # si el valor aprendido ya está en la lista, se marca ahí en vez de repetirlo
        for opcion in opciones:
            if opcion["valor"] == str(aprendido["valor"]):
                opcion["sugerida"] = True
                opcion["floja"] = int(aprendido.get("casos", 0)) < MINIMO_PARA_FIARSE
                opcion["nota"] += (f" · sugerida por aprendizaje "
                                   f"({aprendido.get('casos', 0)} caso(s)"
                                   + (", flojo" if opcion["floja"] else "") + ")")
                break
        else:
            opciones.append({"valor": str(aprendido["valor"]), "origen": "aprendido",
                         "nota": f"{aprendido.get('casos', 0)} caso(s) con este mismo patrón"
                                 + ("; patrón flojo, puede ser casualidad"
                                    if int(aprendido.get("casos", 0)) < MINIMO_PARA_FIARSE else ""),
                             "sugerida": True,
                             "floja": int(aprendido.get("casos", 0)) < MINIMO_PARA_FIARSE})
    return opciones


def construir_cola(evidencia: dict, referencia: dict, decisiones: dict, precedentes: dict) -> list[dict]:
    """Las celdas que necesitan una persona, con sus opciones. Pura."""
    cola = []
    for caso in sorted(evidencia):
        dato = evidencia[caso]
        dudosos = dato.get("dudoso") or {}
        for campo, nombre in CAMPOS.items():
            valor = dato.get(campo)
            motivo = (dato.get("por_que_dudoso") or {}).get(campo)
            fuente = (dato.get("fuente") or {}).get(campo) or {}
            clase = str(fuente.get("clase_cola") or "")
            decision = decisiones.get((caso, campo))
            # A la cola va TODO lo que necesita a una persona:
            #   1. lo dudoso que aún no tiene decisión;
            #   2. lo que ya decidió la máquina o yo y el usuario todavía no ha confirmado
            #      (`pendiente_de_confirmar` y `manual_revisada_por_agente`);
            #   3. lo que el usuario dejó en blanco a propósito no vuelve a preguntarse.
            estado = str((decision or {}).get("estado") or "")
            pendiente = (bool(dudosos.get(campo)) and not decision) \
                or estado in ("pendiente_de_confirmar", "manual_revisada_por_agente")
            if not pendiente:
                continue
            if state_blanco := (estado == "dejar_en_blanco"):
                continue
            cola.append({
                "caso": caso, "campo": campo, "nombre": nombre,
                "propuesto": (decision or {}).get("publicada") or valor or "",
                "motivo": motivo or ("confirmar lo que ya se decidió a mano"
                                     if decision else "el dato no tiene la forma esperada"),
                "clase": clase, "cola_cruda": str(fuente.get("cola_cruda") or ""),
                "foto": f"{fuente.get('carpeta', '')}/{fuente.get('foto', '')}".strip("/"),
                "patron": patron_de(fuente),
                "opciones": opciones_de(caso, campo, dato, referencia, precedentes),
            })
    return cola


def leer_referencia(ruta: Path, campos: dict) -> dict:
    from openpyxl import load_workbook
    hoja = load_workbook(ruta, data_only=True)["Versuchsmatrix"]
    columnas = {"dashboard_part_number": 15, "dashboard_serial_number": 16,
                "dashboard_date": 17, "dashboard_engineering_level": 18}
    salida = {}
    for fila in range(8, hoja.max_row + 1):
        numero = hoja.cell(fila, 3).value
        numero = str(numero).strip() if numero not in (None, "") else ""
        if len(numero) != 6 or not numero.isdigit():
            continue
        salida[numero] = {campo: (str(hoja.cell(fila, col).value).strip()
                                  if hoja.cell(fila, col).value not in (None, "") else "")
                          for campo, col in columnas.items()}
    return salida


# ---------------------------------------------------------------------------------------
# el HTML
# ---------------------------------------------------------------------------------------
PLANTILLA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#14161a">
<title>P42 · confirmar la etiqueta</title>
<style>:root{
  /* superficies */
  --lienzo:#14161a; --pozo:#0b0d10; --panel:#191c21; --alza:#21252c; --alza-2:#272c34;
  --borde:#2b313a; --borde-fuerte:#3d4652;
  /* tinta */
  --tinta:#eceef2; --tenue:#a6aebc; --apagado:#8a93a0;
  /* acento único */
  --ambar:#e8a33d; --ambar-claro:#ffd79a; --ambar-tinta:#1a1206;
  /* estados */
  --acero:#93b7cc; --verde:#57c99a; --verde-tinta:#08221a; --rojo:#e2705f;
  /* tipografía */
  --fuente:ui-sans-serif,system-ui,"Segoe UI Variable Text","Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,"SF Mono","Cascadia Mono","Roboto Mono",Menlo,Consolas,monospace;
  /* movimiento */
  --t-1:120ms; --t-2:220ms; --t-3:380ms;
  --ease:cubic-bezier(.22,.72,.2,1);
  --radio:14px; --radio-s:10px;

  /* derivados: un solo uso, pero con nombre (nada de hex sueltos en las reglas) */
  --blanco:#ffffff; --pozo-alto:#12151a; --brillo-arriba:#1d222b;
  --barra-1:#1c2027; --barra-2:#181b20; --barra-herr:#101318; --tecla:#2a3038;
  --ambar-hover:#f2b455; --borde-ambar:#5a4520; --chip-flojo:#f0c9a0; --borde-acero:#3a4b57;
  --marcador:#6b7481; --kbd-fondo:#252a32; --linea-tabla:#23282f;
  --fallo-fondo:#120f0f; --fallo-tinta:#f0c4bb; --fallo-titulo:#ffd9d1; --fallo-ruta:#c99a9a;
  --borde-verde:#2f5b49; --verde-hover:#6ad7a9;
}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; min-height:100dvh; color:var(--tinta); font:15px/1.55 var(--fuente);
  background:
    radial-gradient(1100px 520px at 50% -12%, var(--brillo-arriba) 0%, transparent 60%),
    var(--lienzo);
  display:grid; place-items:center; padding:clamp(12px,2.4vw,32px);
}
/* sin `align-items:center` a pelo: en pantallas bajas recorta la cabecera */
.marco{
  width:min(1080px,100%); background:var(--panel); border:1px solid var(--borde);
  border-radius:var(--radio); overflow:hidden;
  box-shadow:0 1px 0 rgba(255,255,255,.04) inset, 0 28px 70px -20px rgba(0,0,0,.75);
}
:where(button,input,[role="radio"],a):focus-visible{
  outline:2px solid var(--ambar); outline-offset:2px; border-radius:6px;
}
.solo-lector{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
  clip:rect(0 0 0 0);white-space:nowrap;border:0}

/* ---------- cabecera ---------- */
.barra{display:flex; align-items:center; gap:16px; padding:14px clamp(14px,2vw,22px);
  border-bottom:1px solid var(--borde); background:linear-gradient(180deg,var(--barra-1),var(--barra-2))}
.marca{display:flex; align-items:center; gap:10px; min-width:0}
.marca svg{flex:none; color:var(--ambar)}
.marca b{font-weight:650; letter-spacing:-.01em}
.marca b + span{border-left:1px solid var(--borde-fuerte); padding-left:10px}
.marca span{color:var(--apagado); font-size:12.5px; white-space:nowrap}
.avance{margin-left:auto; display:flex; align-items:center; gap:14px}
.pasos{display:flex; gap:5px; margin:0; padding:0; list-style:none}
.pasos li{width:22px; height:4px; border-radius:2px; background:var(--borde-fuerte);
  transition:background var(--t-2) var(--ease)}
.pasos li.hecho{background:var(--apagado)}
.pasos li.actual{background:var(--ambar)}
.cuenta{font:600 13px/1 var(--mono); font-variant-numeric:tabular-nums; color:var(--tenue);
  letter-spacing:.02em; white-space:nowrap}
.cuenta b{color:var(--tinta); font-weight:700}

/* ---------- rejilla principal ---------- */
main{display:grid; grid-template-columns:minmax(0,1.15fr) minmax(0,1fr)}
@media (max-width:880px){ main{grid-template-columns:1fr} }

/* ---------- visor ---------- */
.visor{display:flex; flex-direction:column; gap:12px; padding:clamp(14px,2vw,20px);
  background:var(--pozo); border-right:1px solid var(--borde); min-width:0}
.pozo{position:relative; display:grid; place-items:center; border-radius:var(--radio-s);
  border:1px solid var(--borde); min-height:180px; overflow:hidden;
  background:radial-gradient(120% 100% at 50% 0%, var(--pozo-alto) 0%, var(--pozo) 70%);
  box-shadow:0 1px 0 rgba(255,255,255,.03) inset}
#img{display:block; max-width:100%; max-height:52vh; width:auto; height:auto;
  transform-origin:center center; cursor:zoom-in; background:var(--blanco);
  transition:transform var(--t-2) var(--ease), opacity var(--t-2) var(--ease)}
#img.zoom{cursor:zoom-out}
#img.entra{animation:entra var(--t-2) var(--ease) both}
@keyframes entra{from{opacity:0; transform:scale(.985)} to{opacity:1}}
.carga{position:absolute; inset:0; display:grid; place-items:center; background:var(--pozo);
  color:var(--apagado); font-size:12.5px; gap:10px; transition:opacity var(--t-2) var(--ease)}
.carga[hidden]{display:none}
.carga .latido{width:34px; height:34px; border-radius:50%;
  border:2px solid var(--borde-fuerte); border-top-color:var(--ambar);
  animation:gira 900ms linear infinite}
@keyframes gira{to{transform:rotate(360deg)}}
.fallo{position:absolute; inset:0; display:none; flex-direction:column; align-items:center;
  justify-content:center; gap:8px; padding:20px; text-align:center; background:var(--fallo-fondo);
  color:var(--fallo-tinta); font-size:13px}
.fallo.visible{display:flex}
.fallo b{color:var(--fallo-titulo); font-size:14px}
.fallo code{font:12px var(--mono); color:var(--fallo-ruta); word-break:break-all}

.herramientas{display:flex; align-items:center; gap:8px; flex-wrap:wrap;
  background:var(--barra-herr); border:1px solid var(--borde); border-radius:var(--radio-s);
  padding:7px 9px}
.herr{display:inline-flex; align-items:center; justify-content:center; gap:6px;
  min-width:44px; min-height:44px; padding:0 12px; border:1px solid transparent;
  border-radius:8px; background:var(--alza); color:var(--tinta); cursor:pointer;
  font:600 13px/1 var(--fuente); transition:background var(--t-1) var(--ease),
  transform var(--t-1) var(--ease), border-color var(--t-1) var(--ease)}
.herr:hover{background:var(--alza-2); border-color:var(--borde-fuerte)}
.herr:active{transform:translateY(1px)}
.herr svg{flex:none}
.herr.txt{font-weight:550; color:var(--tenue)}
.afinador{display:flex; align-items:center; gap:8px; flex:1 1 150px; min-width:130px}
.afinador input[type=range]{flex:1; min-width:70px; accent-color:var(--ambar); height:44px}
.afinador output{font:600 12px/1 var(--mono); color:var(--tenue); min-width:40px;
  text-align:right; font-variant-numeric:tabular-nums}
.pie-foto{display:flex; align-items:center; gap:8px; margin:0; min-width:0;
  font:11.5px/1.4 var(--mono); color:var(--apagado)}
.pie-foto span{overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.detalles{font-size:11.5px; color:var(--apagado)}
.detalles summary{cursor:pointer; color:var(--apagado); list-style:none; width:max-content}
.detalles summary::-webkit-details-marker{display:none}
.detalles summary::before{content:"›"; display:inline-block; margin-right:6px;
  transition:transform var(--t-1) var(--ease)}
.detalles[open] summary::before{transform:rotate(90deg)}
.detalles p{margin:6px 0 0; font-family:var(--mono); word-break:break-word}

/* ---------- columna de decisión ---------- */
.decision{display:flex; flex-direction:column; gap:14px; padding:clamp(16px,2vw,24px);
  min-width:0}
.meta{display:flex; align-items:baseline; gap:10px; flex-wrap:wrap}
.caso{font:600 13px/1 var(--mono); letter-spacing:.04em; color:var(--tenue);
  font-variant-numeric:tabular-nums}
.campo{font-size:12.5px; color:var(--apagado)}
h1{margin:0; font-size:clamp(20px,2.2vw,25px); line-height:1.2; font-weight:640;
  letter-spacing:-.02em; text-wrap:balance}
.porque{margin:0; display:flex; gap:8px; align-items:flex-start; font-size:13px;
  color:var(--tenue); line-height:1.45}
.porque::before{content:""; flex:none; width:6px; height:6px; margin-top:7px; border-radius:50%;
  background:var(--ambar); box-shadow:0 0 0 3px rgba(232,163,61,.14)}

/* la placa: las opciones son el control y el dato a la vez */
.opciones{display:flex; flex-direction:column; gap:8px; margin-top:2px}
.op{position:relative; display:grid; grid-template-columns:26px minmax(0,1fr) auto 18px;
  align-items:center; gap:12px; padding:12px 14px; min-height:56px;
  border:1px solid var(--borde); border-radius:var(--radio-s); background:var(--alza);
  cursor:pointer; transition:border-color var(--t-1) var(--ease),
  background var(--t-1) var(--ease), transform var(--t-1) var(--ease),
  box-shadow var(--t-2) var(--ease)}
.op::before{content:""; position:absolute; left:0; top:10px; bottom:10px; width:3px;
  border-radius:0 3px 3px 0; background:transparent; transition:background var(--t-1) var(--ease)}
.op:hover{border-color:var(--borde-fuerte); background:var(--alza-2)}
.op[aria-checked="true"]{border-color:var(--ambar); background:rgba(232,163,61,.09);
  box-shadow:0 0 0 1px rgba(232,163,61,.35) inset}
.op[aria-checked="true"]::before{background:var(--ambar)}
.tecla{display:grid; place-items:center; width:26px; height:26px; border-radius:7px;
  background:var(--tecla); color:var(--tenue); font:600 12px/1 var(--mono);
  transition:background var(--t-1) var(--ease), color var(--t-1) var(--ease)}
.op[aria-checked="true"] .tecla{background:var(--ambar); color:var(--ambar-tinta)}
.texto{display:flex; flex-direction:column; gap:4px; min-width:0}
.valor{font:600 16.5px/1.35 var(--mono); letter-spacing:.015em; white-space:pre;
  font-variant-numeric:tabular-nums; font-feature-settings:"zero" 1;
  overflow-wrap:anywhere; color:var(--tinta)}
/* el carácter que cambia: fondo, no borde → no mueve ni un píxel la alineación */
.valor .dif{background:rgba(232,163,61,.34); color:var(--ambar-claro); font-weight:700;
  border-radius:3px; box-shadow:0 0 0 1.5px rgba(232,163,61,.6)}
.origen{font-size:12px; color:var(--apagado); line-height:1.4; display:-webkit-box;
  -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden}
.marcas{display:flex; align-items:center; gap:6px; flex:none}
.chip{font-size:10.5px; letter-spacing:.02em; padding:3px 8px; border-radius:20px;
  border:1px solid var(--borde-fuerte); color:var(--tenue); white-space:nowrap}
.chip.codigo{color:var(--acero); border-color:var(--borde-acero)}
.chip.aprendida{color:var(--ambar-claro); border-color:var(--borde-ambar)}
.chip.flojo{color:var(--chip-flojo); border-color:var(--borde-ambar); border-style:dashed}
.chip.libro{color:var(--tenue)}
.tilde{width:18px; height:18px; flex:none; opacity:0; transform:scale(.7);
  color:var(--ambar-tinta); background:var(--ambar); border-radius:50%;
  transition:opacity var(--t-1) var(--ease), transform var(--t-1) var(--ease)}
.op[aria-checked="true"] .tilde{opacity:1; transform:scale(1)}

.pista-dif{margin:-2px 0 0; font-size:12.5px; color:var(--apagado); min-height:19px}
.pista-dif b{color:var(--tenue); font-weight:600}

.campo-otro{display:flex; flex-direction:column; gap:6px}
.campo-otro label{font-size:12.5px; color:var(--tenue)}
.campo-otro label em{font-style:normal; color:var(--apagado)}
#otro{width:100%; min-height:46px; padding:11px 13px; border-radius:var(--radio-s);
  border:1px solid var(--borde); background:var(--alza); color:var(--tinta);
  font:15px/1.3 var(--mono); letter-spacing:.01em;
  transition:border-color var(--t-1) var(--ease), background var(--t-1) var(--ease)}
#otro::placeholder{color:var(--marcador)}
#otro:hover{border-color:var(--borde-fuerte)}
#otro:focus{outline:none; border-color:var(--ambar); background:var(--alza-2);
  box-shadow:0 0 0 3px rgba(232,163,61,.14)}

.acciones{display:flex; gap:8px; align-items:center; margin-top:auto; padding-top:6px;
  flex-wrap:wrap}
.btn{text-decoration:none; min-height:46px; padding:0 18px; border-radius:var(--radio-s); border:1px solid transparent;
  font:600 14px/1 var(--fuente); cursor:pointer; display:inline-flex; align-items:center;
  gap:8px; transition:background var(--t-1) var(--ease), color var(--t-1) var(--ease),
  border-color var(--t-1) var(--ease), transform var(--t-1) var(--ease),
  box-shadow var(--t-2) var(--ease)}
.btn:active{transform:translateY(1px)}
.btn.principal{margin-left:auto; background:var(--ambar); color:var(--ambar-tinta);
  padding-inline:22px}
.btn.principal:hover{background:var(--ambar-hover)}
.btn.principal[aria-disabled="true"]{background:var(--alza); color:var(--apagado);
  cursor:not-allowed; box-shadow:none}
.btn.principal:not([aria-disabled="true"]){box-shadow:0 0 0 0 rgba(232,163,61,.5);
  animation:listo var(--t-3) var(--ease) 1}
@keyframes listo{from{box-shadow:0 0 0 4px rgba(232,163,61,.18)}
  to{box-shadow:0 0 0 0 rgba(232,163,61,0)}}
.et-corto{display:none}
.btn.fantasma{background:transparent; border-color:var(--borde); color:var(--tenue)}
.btn.fantasma:hover{background:var(--alza); color:var(--tinta); border-color:var(--borde-fuerte)}
.btn.fantasma[disabled]{opacity:.35; cursor:not-allowed}
.atajos{margin:0; display:flex; flex-wrap:wrap; gap:6px 12px; font-size:11.5px;
  color:var(--apagado)}
.atajos span{display:inline-flex; align-items:center; gap:5px}
kbd{font:600 10.5px/1 var(--mono); padding:3px 5px; border-radius:4px;
  background:var(--kbd-fondo); border:1px solid var(--borde-fuerte); color:var(--tenue)}

/* ---------- cambio de caso ---------- */
.cambia{animation:cambia var(--t-2) var(--ease) both}
@keyframes cambia{from{opacity:0; transform:translateY(6px)} to{opacity:1; transform:none}}

/* ---------- pantalla final ---------- */
#fin{display:none; flex-direction:column; gap:18px; padding:clamp(20px,3vw,32px)}
#fin.visible{display:flex; animation:cambia var(--t-3) var(--ease) both}
#fin h2{margin:0; font-size:clamp(20px,2.4vw,26px); font-weight:650; letter-spacing:-.02em}
#fin .resumen-linea{margin:0; color:var(--tenue); font-size:13.5px}
.tabla{width:100%; border-collapse:collapse; font-size:13.5px}
.tabla th{text-align:left; font-weight:600; font-size:11.5px; color:var(--apagado);
  padding:0 10px 8px 0; border-bottom:1px solid var(--borde)}
.tabla td{padding:9px 10px 9px 0; border-bottom:1px solid var(--linea-tabla); vertical-align:baseline}
.tabla td.mono{font-family:var(--mono); letter-spacing:.01em;
  font-feature-settings:"zero" 1}
.tabla tr:last-child td{border-bottom:0}
.tabla .vacio{color:var(--apagado); font-style:italic; font-family:var(--fuente)}
.estado{font-size:10.5px; padding:2px 7px; border-radius:20px; border:1px solid var(--borde-fuerte);
  color:var(--tenue); white-space:nowrap}
.estado.ok{color:var(--verde); border-color:var(--borde-verde)}
.estado.blanco{color:var(--apagado)}
.acciones-fin{display:flex; gap:8px; flex-wrap:wrap; align-items:center}
.btn.descarga{background:var(--verde); color:var(--verde-tinta); text-decoration:none}
.btn.descarga:hover{background:var(--verde-hover)}
.btn.secundario{background:var(--alza); color:var(--tinta); border-color:var(--borde)}
.btn.secundario:hover{background:var(--alza-2)}
.texto-json{display:none; width:100%; height:130px; background:var(--pozo); color:var(--tenue);
  border:1px solid var(--borde); border-radius:var(--radio-s); padding:10px;
  font:12px/1.5 var(--mono)}
.nota{font-size:12px; color:var(--apagado); line-height:1.55; max-width:70ch}
.nota code{font-family:var(--mono); color:var(--tenue)}

/* ---------- avisos flotantes ---------- */
.aviso-flotante{position:fixed; left:50%; bottom:22px; transform:translate(-50%,12px);
  background:var(--verde); color:var(--verde-tinta); font:600 13px/1 var(--fuente);
  padding:11px 16px; border-radius:20px; opacity:0; pointer-events:none;
  transition:opacity var(--t-2) var(--ease), transform var(--t-2) var(--ease);
  box-shadow:0 10px 30px -8px rgba(0,0,0,.6)}
.aviso-flotante.visible{opacity:1; transform:translate(-50%,0)}

/* ---------- móvil ---------- */
@media (max-width:880px){
  body{padding:0; place-items:stretch}
  .marco{width:100%; min-height:100dvh; border-radius:0; border:0; border-top:1px solid var(--borde)}
  .visor{border-right:0; border-bottom:1px solid var(--borde); gap:10px}
  #img{max-height:24vh}
  .pozo{width:max-content; max-width:100%; margin-inline:auto}
  .pozo{min-height:110px}
  .herramientas{gap:6px; padding:6px 7px}
  .herr{min-width:44px; padding:0 9px}
  .herr.txt{font-size:12.5px; padding:0 10px}
  .afinador output{display:none}
  .afinador{order:5; flex:1 1 100%; min-width:0}
  .herr.txt{flex:0 1 auto; padding:0 10px}
  .acciones{flex-wrap:nowrap}
  .acciones .btn{padding-inline:12px}
  .acciones #atras .et{display:none}
  .et-largo{display:none}
  .et-corto{display:inline}
  .pie-foto{font-size:11px}
  .decision{padding-bottom:0; gap:11px}
  h1{font-size:21px}
  .porque{font-size:12.5px}
  .marco{overflow:visible}
  .acciones{position:sticky; bottom:0; background:var(--panel); border-top:1px solid var(--borde);
    padding:8px 0 12px; margin-top:6px; z-index:3;
    box-shadow:0 -14px 22px -16px rgba(0,0,0,.95)}
  .acciones .btn.principal{flex:1 1 auto; padding-inline:16px}
  .atajos{display:none}
  .barra{align-items:flex-start; flex-wrap:wrap; gap:10px 12px}
  .avance{width:100%; margin-left:0; justify-content:space-between; order:3}
  .pasos{flex:1}
  .pasos li{flex:1; width:auto}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.001ms !important; animation-iteration-count:1 !important;
    transition-duration:.001ms !important; scroll-behavior:auto !important}
  #img{transition:none}
}
</style>
</head>
<body>
<div class="marco">

  <header class="barra">
    <div class="marca">
      <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true" fill="currentColor">
        <rect x="0" y="0" width="6" height="6" rx="1"/><rect x="16" y="0" width="6" height="6" rx="1"/>
        <rect x="0" y="16" width="6" height="6" rx="1"/><rect x="9" y="0" width="2" height="2"/>
        <rect x="13" y="2" width="2" height="2"/><rect x="9" y="4" width="2" height="2"/>
        <rect x="3" y="9" width="2" height="2"/><rect x="7" y="10" width="2" height="2"/>
        <rect x="12" y="9" width="2" height="2"/><rect x="16" y="11" width="2" height="2"/>
        <rect x="9" y="14" width="2" height="2"/><rect x="14" y="15" width="2" height="2"/>
        <rect x="18" y="17" width="2" height="2"/><rect x="9" y="18" width="2" height="2"/>
      </svg>
      <b>P42</b><span>confirmación de matriz de datos</span>
    </div>
    <div class="avance">
      <ol class="pasos" id="pasos" aria-hidden="true"></ol>
      <span class="cuenta" id="cuenta"><b>1</b> de 6</span>
    </div>
  </header>

  <main id="juego" aria-labelledby="pregunta">
    <section class="visor" aria-label="Imagen de la etiqueta">
      <div class="pozo">
        <img id="img" alt="" width="__P0_W__" height="__P0_H__" decoding="async">
        <div class="carga" id="carga" hidden><div class="latido" aria-hidden="true"></div>
          <span>Preparando la imagen…</span></div>
        <div class="fallo" id="fallo" role="alert">
          <b>No se pudo abrir el recorte</b>
          <span>Desde aquí no se puede ver la foto. Puedes decidir igualmente con las opciones de la derecha.</span>
          <code id="fallo_ruta"></code>
        </div>
      </div>
      <div class="herramientas">
        <button class="herr" id="izq" type="button" aria-label="Girar 90 grados a la izquierda" title="Girar 90° a la izquierda (Shift+R)">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
            <path d="M6 3.5H3.5V1M3.8 3.2A6 6 0 1 1 2.2 9" stroke-linecap="round"/></svg>
        </button>
        <button class="herr" id="der" type="button" aria-label="Girar 90 grados a la derecha" title="Girar 90° a la derecha (R)">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
            <path d="M10 3.5h2.5V1M12.2 3.2A6 6 0 1 0 13.8 9" stroke-linecap="round"/></svg>
        </button>
        <div class="afinador">
          <input type="range" id="ajuste" min="-20" max="20" step="0.5" value="0"
                 aria-label="Ajuste fino del ángulo" title="Ajuste fino (teclas [ y ])">
          <output id="ajuste_val" for="ajuste">0°</output>
        </div>
        <button class="herr txt" id="reset_vista" type="button" title="Volver a la vista original (tecla 0)">Centrar</button>
        <button class="herr txt" id="zoom" type="button" aria-pressed="false" title="Ampliar (tecla Z)">Ampliar</button>
      </div>
      <p class="pie-foto"><span id="foto_txt">—</span></p>
      <details class="detalles">
        <summary>Detalle técnico de la lectura</summary>
        <p id="detalle">—</p>
      </details>
    </section>

    <section class="decision">
      <div class="meta">
        <span class="caso" id="caso">—</span>
        <span class="campo" id="cual">—</span>
      </div>
      <h1 id="pregunta">¿Qué dice la etiqueta?</h1>
      <p class="porque" id="aviso_txt"></p>

      <div class="opciones" id="opciones" role="radiogroup" aria-labelledby="pregunta"></div>
      <p class="pista-dif" id="pista_dif"></p>

      <div class="campo-otro">
        <label for="otro">Otro valor <em>— escríbelo tal como lo ves, si no está arriba</em></label>
        <input type="text" id="otro" autocomplete="off" spellcheck="false"
               placeholder="052 3KVJ008R6E…">
      </div>

      <div class="acciones">
        <button class="btn fantasma" id="atras" type="button" aria-label="Caso anterior"><span aria-hidden="true">←</span><span class="et">Anterior</span></button>
        <button class="btn fantasma" id="blanco" type="button" aria-label="Dejar el campo en blanco"><span class="et-largo">Dejar en blanco</span><span class="et-corto">En blanco</span></button>
        <button class="btn principal" id="siguiente" type="button" aria-disabled="true">Siguiente →</button>
      </div>
      <p class="atajos">
        <span><kbd>1</kbd><kbd>2</kbd> elegir</span>
        <span><kbd>↑</kbd><kbd>↓</kbd> moverse</span>
        <span><kbd>Enter</kbd> siguiente</span>
        <span><kbd>B</kbd> en blanco</span>
        <span><kbd>R</kbd> girar</span>
        <span><kbd>[</kbd><kbd>]</kbd> afinar</span>
        <span><kbd>Z</kbd> ampliar</span>
        <span><kbd>0</kbd> centrar</span>
      </p>
    </section>
  </main>

  <section id="fin" aria-labelledby="fin_titulo">
    <h2 id="fin_titulo">Listo — esto es lo que decidiste</h2>
    <p class="resumen-linea" id="fin_linea"></p>
    <table class="tabla">
      <thead><tr><th>Caso</th><th>Campo</th><th>Valor publicado</th><th>Estado</th></tr></thead>
      <tbody id="resumen"></tbody>
    </table>
    <div class="acciones-fin">
      <a class="btn descarga" id="dl_dec" download="decisiones_p42.json">Descargar decisiones_p42.json</a>
      <a class="btn secundario" id="dl_prec" download="precedentes_p42.json">Descargar lo aprendido</a>
      <button class="btn secundario" id="copiar" type="button">Copiar al portapapeles</button>
      <button class="btn fantasma" id="volver" type="button">Volver a la última</button>
    </div>
    <textarea class="texto-json" id="texto_json" spellcheck="false" aria-label="Decisiones en JSON"></textarea>
    <p class="nota">Guarda los dos archivos junto a <code>rellenar_tablero_p42.py</code> y vuelve a ejecutarlo.
      Si el navegador no deja descargar (por ejemplo dentro de una vista previa), usa «copiar» y pégalo en
      <code>decisiones_p42.json</code>. Lo aprendido nunca se aplica solo: la próxima vez aparecerá como
      opción sugerida, no como valor.</p>
  </section>

  <div class="aviso-flotante" id="aviso_flotante" role="status" aria-live="polite"></div>
  <p class="solo-lector" id="anuncio" role="status" aria-live="polite"></p>
</div>

<script>
const CASOS = __CASOS__;
const PRECEDENTES_PREVIOS = __PRECEDENTES__;

const $ = (id) => document.getElementById(id);
const RM = window.matchMedia("(prefers-reduced-motion: reduce)");
const NS = "http://www.w3.org/2000/svg";

let i = 0;
const respuestas = new Array(CASOS.length).fill(null);
const aprendido = JSON.parse(JSON.stringify(PRECEDENTES_PREVIOS || {}));
const vista = { paso: 0, fino: 0, zoom: false };

// ------------------------------------------------------------------ utilidades
function el(tag, clase, texto) {
  const n = document.createElement(tag);
  if (clase) n.className = clase;
  if (texto !== undefined && texto !== null) n.textContent = texto;
  return n;
}

function anunciar(texto) {
  const caja = $("anuncio");
  caja.textContent = "";
  window.setTimeout(() => { caja.textContent = texto; }, 40);
}

function flotante(texto) {
  const caja = $("aviso_flotante");
  caja.textContent = texto;
  caja.classList.add("visible");
  window.clearTimeout(flotante.t);
  flotante.t = window.setTimeout(() => caja.classList.remove("visible"), 2200);
}

// el carácter (o caracteres) donde las lecturas no coinciden
function posicionesQueCambian(valores) {
  const largo = Math.max(...valores.map((v) => v.length));
  const marcas = [];
  for (let k = 0; k < largo; k++) {
    const vistos = new Set(valores.map((v) => (k < v.length ? v[k] : "\u0000")));
    marcas.push(vistos.size > 1);
  }
  return marcas;
}

function fraseDeDiferencia(valores) {
  const largos = new Set(valores.map((v) => v.length));
  if (largos.size === 1 && valores.every((v) => v === valores[0])) return "";
  const marcas = posicionesQueCambian(valores);
  const posiciones = marcas.map((m, k) => (m ? k : -1)).filter((k) => k >= 0);
  if (!posiciones.length) return "Mismo valor, distinto origen.";
  const humano = posiciones.length === 1
    ? "el carácter " + (posiciones[0] + 1)
    : "los caracteres " + posiciones.map((k) => k + 1).join(" y ");
  const plural = posiciones.length === 1 ? "cambia" : "cambian";
  return "Solo " + plural + " en " + humano + " de " + Math.max(...valores.map((v) => v.length)) + ".";
}

// ------------------------------------------------------------------ vista de la imagen
function escalaParaCaber() {
  const img = $("img"), marco = img.parentElement;
  const w = img.clientWidth || 1, h = img.clientHeight || 1;
  const cw = marco.clientWidth - 2 || w, ch = marco.clientHeight - 2 || h;
  const vertical = (((vista.paso % 2) + 2) % 2) === 1;
  const ancho = vertical ? h : w, alto = vertical ? w : h;
  return Math.min(1, cw / ancho, ch / alto);
}

function aplicarVista() {
  const img = $("img");
  const angulo = vista.paso * 90 + vista.fino;
  const base = img.naturalWidth ? escalaParaCaber() : 1;
  const escala = base * (vista.zoom ? 1.9 : 1);
  img.style.transform = "rotate(" + angulo + "deg) scale(" + escala.toFixed(4) + ")";
  img.classList.toggle("zoom", vista.zoom);
  $("ajuste").value = vista.fino;
  $("ajuste_val").textContent = (vista.fino > 0 ? "+" : "") + vista.fino + "°";
  const grados = ((vista.paso * 90) % 360 + 360) % 360;
  $("izq").title = "Girar 90° a la izquierda (Shift+R)" + (grados ? " · ahora " + grados + "°" : "");
  $("zoom").setAttribute("aria-pressed", String(vista.zoom));
  $("zoom").textContent = vista.zoom ? "Reducir" : "Ampliar";
}

const girar = (pasos) => { vista.paso += pasos; aplicarVista(); };
const afinar = (g) => { vista.fino = Math.max(-20, Math.min(20, vista.fino + g)); aplicarVista(); };
const centrar = () => { vista.paso = 0; vista.fino = 0; vista.zoom = false; aplicarVista(); };

// ------------------------------------------------------------------ carga de la imagen
let temporizadorCarga = null;
function cargarImagen(caso) {
  const img = $("img"), carga = $("carga"), fallo = $("fallo");
  window.clearTimeout(temporizadorCarga);
  fallo.classList.remove("visible");
  img.classList.remove("entra");
  img.removeAttribute("src");
  centrar();

  if (!caso.imagen) {                       // estado vacío: no hay recorte, pero se puede decidir
    img.style.visibility = "hidden";
    carga.hidden = true;
    fallo.classList.add("visible");
    $("fallo_ruta").textContent = caso.foto || "sin recorte para este caso";
    return;
  }
  img.style.visibility = "visible";
  if (caso.ancho && caso.alto) { img.width = caso.ancho; img.height = caso.alto; }
  else { img.removeAttribute("width"); img.removeAttribute("height"); }

  // el esqueleto solo si de verdad tarda: nunca un parpadeo
  carga.hidden = true;
  temporizadorCarga = window.setTimeout(() => { carga.hidden = false; }, 120);

  img.onload = () => {
    window.clearTimeout(temporizadorCarga);
    carga.hidden = true;
    aplicarVista();
    if (!RM.matches) { img.classList.add("entra"); }
  };
  img.onerror = () => {
    window.clearTimeout(temporizadorCarga);
    carga.hidden = true;
    img.style.visibility = "hidden";
    fallo.classList.add("visible");
    $("fallo_ruta").textContent = caso.foto || "recorte no disponible";
    anunciar("No se pudo abrir el recorte del caso " + caso.caso + ".");
  };
  img.src = caso.imagen;
  if (img.complete && img.naturalWidth) { window.clearTimeout(temporizadorCarga); carga.hidden = true; aplicarVista(); }
}

// ------------------------------------------------------------------ pintar un caso
function pintarPasos() {
  const caja = $("pasos");
  if (caja.children.length !== CASOS.length) {
    caja.replaceChildren(...CASOS.map(() => document.createElement("li")));
  }
  [...caja.children].forEach((li, k) => {
    li.className = k < i ? "hecho" : (k === i ? "actual" : "");
  });
}

function pintar() {
  const c = CASOS[i];
  $("cuenta").innerHTML = "<b>" + (i + 1) + "</b> de " + CASOS.length;
  $("caso").textContent = c.caso;
  $("cual").textContent = c.nombre || c.campo.replace("dashboard_", "");
  const motivo = c.motivo || "";
  $("aviso_txt").textContent = motivo ? motivo.charAt(0).toUpperCase() + motivo.slice(1) : "";
  $("aviso_txt").hidden = !motivo;
  $("foto_txt").textContent = c.foto || "recorte no disponible";
  $("detalle").textContent = (c.cola_cruda ? "cola " + c.cola_cruda + " · " : "") + "patrón " + (c.patron || "—");
  $("otro").value = "";
  pintarPasos();
  cargarImagen(c);

  const valores = c.opciones.map((o) => o.valor);
  const marcas = posicionesQueCambian(valores);

  const caja = $("opciones");
  caja.replaceChildren();
  c.opciones.forEach((o, k) => {
    const fila = el("div", "op");
    fila.setAttribute("role", "radio");
    fila.setAttribute("aria-checked", "false");
    fila.tabIndex = k === 0 ? 0 : -1;
    fila.dataset.valor = o.valor;
    fila.dataset.origen = o.origen;

    const tecla = el("span", "tecla", String(k + 1));
    tecla.setAttribute("aria-hidden", "true");

    const texto = el("span", "texto");
    const valor = el("span", "valor");
    [...o.valor].forEach((ch, pos) => {
      const s = el("span", marcas[pos] ? "dif" : null, ch);
      valor.appendChild(s);
    });
    const origen = el("span", "origen", o.nota || o.origen);
    texto.append(valor, origen);

    const marcasCaja = el("span", "marcas");
    if (o.origen.startsWith("código")) marcasCaja.appendChild(el("span", "chip codigo", "código"));
    else if (o.origen.startsWith("lectura OCR")) marcasCaja.appendChild(el("span", "chip", "ocr"));
    else if (o.origen.startsWith("libro")) marcasCaja.appendChild(el("span", "chip libro", "libro"));
    if (o.sugerida) marcasCaja.appendChild(el("span", "chip aprendida", "aprendida"));
    if (o.floja) marcasCaja.appendChild(el("span", "chip flojo", "flojo"));

    const tilde = document.createElementNS(NS, "svg");
    tilde.setAttribute("class", "tilde");
    tilde.setAttribute("viewBox", "0 0 18 18");
    tilde.setAttribute("aria-hidden", "true");
    tilde.innerHTML = '<path d="M5 9.4l2.6 2.6L13 6.4" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>';

    fila.append(tecla, texto, marcasCaja, tilde);
    fila.addEventListener("click", () => elegir(k));
    fila.addEventListener("keydown", (ev) => moverConFlechas(ev, k));
    caja.appendChild(fila);
  });

  const frase = fraseDeDiferencia(valores);
  $("pista_dif").textContent = frase || "\u00a0";

  if (!c.opciones.length) {
    const vacio = el("p", "origen", "Este campo no trae lecturas del sistema. Escribe el valor abajo o déjalo en blanco.");
    caja.appendChild(vacio);
  }

  const previa = respuestas[i];
  if (previa) {
    if (previa.origen === "otro_escrito_por_la_persona") { $("otro").value = previa.valor; }
    else if (previa.origen === "dejar_en_blanco") { /* sin marca visible */ }
    else {
      const fila = [...caja.querySelectorAll(".op")].find((f) => f.dataset.valor === previa.valor);
      if (fila) fila.setAttribute("aria-checked", "true");
    }
  }
  actualizarSiguiente();
  $("atras").disabled = i === 0;
  $("siguiente").textContent = (i === CASOS.length - 1) ? "Terminar" : "Siguiente →";
  if (!RM.matches) {
    $("juego").classList.remove("cambia");
    void $("juego").offsetWidth;
    $("juego").classList.add("cambia");
  }
  anunciar("Caso " + c.caso + ", " + (c.nombre || c.campo) + ". " + (i + 1) + " de " + CASOS.length + ".");
}

function moverConFlechas(ev, k) {
  const filas = [...$("opciones").querySelectorAll(".op")];
  let destino = null;
  if (ev.key === "ArrowDown" || ev.key === "ArrowRight") destino = filas[(k + 1) % filas.length];
  if (ev.key === "ArrowUp" || ev.key === "ArrowLeft") destino = filas[(k - 1 + filas.length) % filas.length];
  if (ev.key === " " || ev.key === "Enter") { ev.preventDefault(); elegir(k); return; }
  if (!destino) return;
  ev.preventDefault();
  filas.forEach((f) => { f.tabIndex = -1; });
  destino.tabIndex = 0;
  destino.focus();
}

// ------------------------------------------------------------------ responder
function guardar(valor, origen) {
  respuestas[i] = { caso: CASOS[i].caso, campo: CASOS[i].campo, valor, origen };
  actualizarSiguiente();
}

function elegir(k) {
  const c = CASOS[i];
  const o = c.opciones[k];
  if (!o) return;
  [...$("opciones").querySelectorAll(".op")].forEach((f) => {
    f.setAttribute("aria-checked", String(f.dataset.valor === o.valor));
    f.tabIndex = f.dataset.valor === o.valor ? 0 : -1;
  });
  $("otro").value = "";
  guardar(o.valor, o.origen);
  anunciar("Elegido: " + o.valor);
}

function enBlanco() {
  [...$("opciones").querySelectorAll(".op")].forEach((f) => f.setAttribute("aria-checked", "false"));
  $("otro").value = "";
  guardar("", "dejar_en_blanco");
  anunciar("Se dejará en blanco.");
}

function actualizarSiguiente() {
  const boton = $("siguiente");
  const listo = Boolean(respuestas[i]);
  boton.setAttribute("aria-disabled", listo ? "false" : "true");
}

function siguiente() {
  if ($("siguiente").getAttribute("aria-disabled") === "true") {
    flotante("Elige una opción, escribe el valor o déjalo en blanco");
    return;
  }
  if (i < CASOS.length - 1) { i += 1; pintar(); }
  else { terminar(); }
}

$("otro").addEventListener("input", (ev) => {
  const v = ev.target.value.trim();
  [...$("opciones").querySelectorAll(".op")].forEach((f) => f.setAttribute("aria-checked", "false"));
  if (!v) { respuestas[i] = null; actualizarSiguiente(); return; }
  guardar(v, "otro_escrito_por_la_persona");
});

// ------------------------------------------------------------------ teclado global
document.addEventListener("keydown", (ev) => {
  const escribiendo = ev.target instanceof HTMLInputElement && ev.target.type === "text";
  if (escribiendo) {
    if (ev.key === "Enter") { ev.preventDefault(); siguiente(); }
    return;
  }
  if (ev.key === "Enter" && !ev.altKey) { ev.preventDefault(); siguiente(); return; }
  if (ev.key.toLowerCase() === "b") { enBlanco(); return; }
  if (ev.key.toLowerCase() === "r") { girar(ev.shiftKey ? -1 : 1); return; }
  if (ev.key.toLowerCase() === "z") { vista.zoom = !vista.zoom; aplicarVista(); return; }
  if (ev.key === "[") { afinar(-5); return; }
  if (ev.key === "]") { afinar(5); return; }
  if (ev.key === "0") { centrar(); return; }
  if (ev.altKey && ev.key === "ArrowLeft") { atras(); return; }
  const n = parseInt(ev.key, 10);
  if (n >= 1 && n <= 9 && CASOS[i] && CASOS[i].opciones[n - 1]) {
    elegir(n - 1);
    const fila = $("opciones").querySelectorAll(".op")[n - 1];
    if (fila) fila.focus();
  }
});

function atras() {
  if (i === 0) return;
  i -= 1;
  pintar();
}

// ------------------------------------------------------------------ final
function terminar() {
  $("juego").style.display = "none";
  const fin = $("fin");
  fin.classList.add("visible");
  pintarPasos();
  [...$("pasos").children].forEach((li) => { li.className = "hecho"; });

  const decisiones = [];
  const resumen = $("resumen");
  resumen.replaceChildren();
  let conValor = 0;

  respuestas.forEach((r) => {
    if (!r) return;
    const caso = CASOS.find((c) => c.caso === r.caso && c.campo === r.campo);
    const codificada = (caso && caso.opciones[0] && caso.opciones[0].origen.startsWith("código"))
      ? caso.opciones[0].valor : "";
    decisiones.push({
      caso: r.caso, campo: r.campo, codificada,
      publicada: r.valor, fuente_decision: r.origen,
      estado: r.valor ? "manual_validada" : "dejar_en_blanco",
      nota: "decidido en la cola de confirmación (revisar_dudas.py)",
    });
    if (r.valor && caso) {
      const p = aprendido[caso.patron] || { valor: r.valor, casos: 0, casos_ids: [] };
      if (!p.casos_ids.includes(r.caso)) { p.casos_ids.push(r.caso); p.casos += 1; }
      p.valor = r.valor;
      aprendido[caso.patron] = p;
    }
    if (r.valor) conValor += 1;

    const fila = document.createElement("tr");
    fila.appendChild(el("td", "mono", r.caso));
    fila.appendChild(el("td", null, (r.campo || "").replace("dashboard_", "")));
    const celda = el("td", r.valor ? "mono" : "vacio", r.valor || "en blanco");
    fila.appendChild(celda);
    const estado = el("span", "estado " + (r.valor ? "ok" : "blanco"), r.valor ? "publicado" : "sin publicar");
    const celdaEstado = el("td");
    celdaEstado.appendChild(estado);
    fila.appendChild(celdaEstado);
    resumen.appendChild(fila);
  });

  const total = respuestas.filter(Boolean).length;
  $("fin_linea").textContent = total + " de " + CASOS.length + " respondidas · "
    + conValor + " con valor para publicar · " + (total - conValor) + " en blanco.";

  const prec = {};
  Object.entries(aprendido).forEach(([p, v]) => { prec[p] = { valor: v.valor, casos: v.casos }; });

  $("dl_dec").href = "data:application/json;charset=utf-8," + encodeURIComponent(JSON.stringify(decisiones, null, 1));
  $("dl_prec").href = "data:application/json;charset=utf-8," + encodeURIComponent(JSON.stringify(prec, null, 1));

  const texto = JSON.stringify(decisiones, null, 1);
  $("texto_json").value = texto;
  anunciar("Terminado. " + total + " de " + CASOS.length + " respondidas.");
  window.scrollTo({ top: 0, behavior: RM.matches ? "auto" : "smooth" });
}

$("copiar").addEventListener("click", async () => {
  const area = $("texto_json");
  try {
    await navigator.clipboard.writeText(area.value);
    flotante("Copiado");
  } catch (e) {
    area.style.display = "block";
    area.select();
    try { document.execCommand("copy"); flotante("Copiado"); }
    catch (e2) { flotante("Selecciona y copia con Ctrl+C"); }
  }
});

$("volver").addEventListener("click", () => {
  $("fin").classList.remove("visible");
  $("juego").style.display = "grid";
  i = Math.max(0, CASOS.length - 1);
  pintar();
});

// ------------------------------------------------------------------ cableado
$("siguiente").addEventListener("click", siguiente);
$("blanco").addEventListener("click", enBlanco);
$("atras").addEventListener("click", atras);
$("img").addEventListener("click", () => { vista.zoom = !vista.zoom; aplicarVista(); });
$("izq").addEventListener("click", () => girar(-1));
$("der").addEventListener("click", () => girar(1));
$("ajuste").addEventListener("input", (ev) => { vista.fino = parseFloat(ev.target.value); aplicarVista(); });
$("reset_vista").addEventListener("click", centrar);
$("zoom").addEventListener("click", () => { vista.zoom = !vista.zoom; aplicarVista(); });
window.addEventListener("resize", () => aplicarVista());
if (RM.addEventListener) { RM.addEventListener("change", () => aplicarVista()); }

pintar();
</script>
</body>
</html>"""


def _ya_embebidas(ruta: Path) -> dict:
    """Recortes de una ejecución anterior de este mismo HTML: {clave: data URI}.

    Sirve cuando las fotos originales ya no están (una carpeta temporal que se vació,
    otro portátil): la evidencia que ya se recortó no se pierde y la página se puede
    reconstruir sin volver a recorrer el repositorio.
    """
    if not ruta or not Path(ruta).exists():
        return {}
    texto = Path(ruta).read_text(encoding="utf-8", errors="ignore")
    encontrado = re.search(r"const CASOS = (\[.*?\]);\n", texto, re.S)
    if not encontrado:
        return {}
    try:
        casos = json.loads(encontrado.group(1))
    except json.JSONDecodeError:
        return {}
    return {(str(c.get("caso")), str(c.get("campo"))): str(c.get("imagen") or "")
            for c in casos if c.get("imagen")}


def _json_seguro(dato) -> str:
    """JSON que se puede meter dentro de <script> sin cerrarlo por accidente."""
    return json.dumps(dato, ensure_ascii=False).replace("</", "<\\/")


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera la cola de confirmación en un solo HTML")
    ap.add_argument("--evidencia", required=True)
    ap.add_argument("--referencia", default="")
    ap.add_argument("--decisiones", default="")
    ap.add_argument("--precedentes", default="")
    ap.add_argument("--fotos", default="", help="carpeta con las fotos, para recortar la etiqueta")
    ap.add_argument("--imagenes-de", default="",
                    help="HTML anterior: reutiliza sus recortes si las fotos ya no están")
    ap.add_argument("--salida", default="confirmar.html")
    ap.add_argument("--solo-serie", action="store_true",
                    help="sólo las dudas de la serie del tablero (las demás van con el flujo normal)")
    args = ap.parse_args()

    evidencia = json.loads(Path(args.evidencia).read_text(encoding="utf-8"))
    referencia = leer_referencia(Path(args.referencia), CAMPOS) if args.referencia else {}
    decisiones = {}
    if args.decisiones and Path(args.decisiones).exists():
        for entrada in json.loads(Path(args.decisiones).read_text(encoding="utf-8")):
            decisiones[(str(entrada.get("caso")), str(entrada.get("campo")))] = entrada
    precedentes = {}
    if args.precedentes and Path(args.precedentes).exists():
        precedentes = json.loads(Path(args.precedentes).read_text(encoding="utf-8"))

    cola = construir_cola(evidencia, referencia, decisiones, precedentes)
    if args.solo_serie:
        cola = [c for c in cola if c["campo"] == "dashboard_serial_number"]

    reutilizables = _ya_embebidas(Path(args.imagenes_de)) if args.imagenes_de else {}
    for entrada in cola:
        entrada["imagen"] = ""
        entrada["ancho"], entrada["alto"] = 0, 0
        entrada["origen_imagen"] = "ninguna"
        if args.fotos and entrada["foto"]:
            ruta = Path(args.fotos) / entrada["caso"]
            foto = None
            for carpeta in ruta.parent.glob(f"{entrada['caso']}*"):
                posible = carpeta / entrada["foto"].split("/")[0] / entrada["foto"].split("/")[-1]
                if posible.exists():
                    foto = posible
                    break
            if foto is not None:
                imagen = cv2.imread(str(foto))
                if imagen is not None:
                    recorte, _ = recorte_de_etiqueta(imagen)
                    entrada["imagen"] = a_data_uri(recorte)
                    entrada["ancho"], entrada["alto"] = medidas_de_uri(entrada["imagen"])
                    entrada["origen_imagen"] = "foto"
        if not entrada["imagen"]:
            previa = reutilizables.get((entrada["caso"], entrada["campo"]), "")
            if previa:
                crudo = base64.b64decode(previa.split(",", 1)[1])
                imagen = cv2.imdecode(np.frombuffer(crudo, np.uint8), cv2.IMREAD_COLOR)
                if imagen is not None:
                    entrada["imagen"] = a_data_uri(imagen)
                    entrada["ancho"], entrada["alto"] = medidas_de_uri(entrada["imagen"])
                    entrada["origen_imagen"] = "reutilizada"

    primero = cola[0] if cola else {}
    documento = (PLANTILLA
                 .replace("__CASOS__", _json_seguro(cola))
                 .replace("__PRECEDENTES__", _json_seguro(precedentes))
                 .replace("__P0_W__", str(primero.get("ancho") or 1200))
                 .replace("__P0_H__", str(primero.get("alto") or 900)))
    Path(args.salida).write_text(documento, encoding="utf-8")

    peso = sum(len(c["imagen"]) for c in cola) / 1024
    con_foto = sum(1 for c in cola if c.get("imagen"))
    print(f"{len(cola)} duda(s) en la cola · {con_foto} con recorte · "
          f"{peso:.0f} KB de imágenes · {args.salida}")
    for entrada in cola:
        print(f"  {entrada['caso']} · {entrada['campo']} · "
              f"{entrada['propuesto'] or '—'} · {len(entrada['opciones'])} opción(es) · "
              f"{entrada['origen_imagen']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
