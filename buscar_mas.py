#!/usr/bin/env python3
"""P42 · segunda pasada: cuando un campo sigue en duda, se buscan MÁS fotos, no menos.

    python3 buscar_mas.py --caso "/var/tmp/fotos/232564 RDW OGL HT" --campo fecha \
        --parcial /tmp/lecturas_tablero.json [--maximo-fotos 400] [--presupuesto-s 900]

Por qué existe. El 2026-10-29 el usuario encontró a mano una foto (`NACH/IMG_4408.JPG`) con el
sticker de la fecha de 232564 que el sistema había dado por perdido. La foto estaba en disco: lo
que falló fue **la búsqueda**, que sólo miraba las fotos elegidas por una pista (la pestaña azul)
y con un cupo. En esa foto el ancla es una pegatina redonda, no una pestaña, así que el detector
no la marcó y nunca se hizo OCR sobre ella.

La primera pasada busca **dónde mirar** (barata, con pistas y cupos). Esta segunda pasada no
supone nada: recorre todas las fotos del caso que aún no se miraron, localiza **etiquetas
blancas** (que es lo que son los stickers) y las lee. Se para en cuanto hay dos lecturas iguales,
porque a partir de ahí ya hay consenso y seguir gastando no aporta.

Regla que implementa, y que es del usuario: *ante duda, buscar más; nunca inventar*. Un campo
sólo puede cerrarse como «sin dato» cuando esta pasada también se agota, y eso queda registrado
en el informe con el número de fotos examinadas.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from utilidades import tablero_campos as T          # noqa: E402

SUFIJOS = {".jpg", ".jpeg", ".png"}
AVISO = 2          # lecturas iguales que hacen falta para parar


def fotos_del_caso(carpeta: Path) -> list[Path]:
    """Todas las fotos del caso, una vez cada una (sin duplicar por mayúsculas)."""
    vistas: dict[str, Path] = {}
    for ruta in sorted(carpeta.rglob("*")):
        if ruta.is_file() and ruta.suffix.lower() in SUFIJOS:
            vistas.setdefault(str(ruta.resolve()).lower(), ruta)
    return list(vistas.values())


def etiquetas_blancas(imagen, maximo: int = 2) -> list[tuple]:
    """Cajas de las manchas blancas grandes con pinta de etiqueta. Pura.

    No se busca una forma concreta ni un color de ancla: se buscan las zonas claras y poco
    saturadas, que es de lo que están hechas todas las etiquetas del lote.
    """
    alto, ancho = imagen.shape[:2]
    hsv = cv2.cvtColor(imagen, cv2.COLOR_BGR2HSV)
    mascara = cv2.inRange(hsv, (0, 0, 140), (180, 70, 255))
    nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, nucleo, iterations=3)
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cajas = []
    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        area = w * h
        if area < 0.012 * alto * ancho:            # menos del 1,2 % de la foto: no es la etiqueta
            continue
        relleno = cv2.contourArea(contorno) / float(area)
        if relleno < 0.45:                         # hueca o rota: no es una etiqueta
            continue
        cajas.append((area, x, y, w, h))
    cajas.sort(reverse=True)
    return [(x, y, w, h) for _, x, y, w, h in cajas[:maximo]]


RESTOS_DEL_MODULO = ("2GJ", "880 204", "880204", "ZRZ", "INFLADOR", "AIRBAG")
# P42 · 2026-10-29: no todas las fechas de una foto son la fecha del tablero. En 232564 ganó el
# voto una etiqueta de proveedor («Lieferant : Farbe:») frente a la del tablero, que decía bien
# 17/05/2025. Antes de votar hay que saber de qué pegatina viene cada fecha.
RESTOS_DEL_PROVEEDOR = ("LIEFERANT", "FARBE", "MAT", "QTY", "MENGE", "CHARGE", "LOT")
RELOJ = __import__("re").compile(r"\b\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM|A\.M\.|P\.M\.)?\b", __import__("re").I)


def clase_de_pegatina(texto: str) -> str:
    """De qué pegatina sale esta fecha. Pura.

    `tablero`     · la buena: lleva hora y un código de parte largo (es el sticker del tablero)
    `modulo`      · la del módulo (2GJ…, ZRZ…), que lleva su propia fecha
    `proveedor`   · etiquetas de suministro: Lieferant, Farbe, MAT, número de lote…
    `desconocida` · sin marcas: no se usa para votar contra las demás
    """
    crudo = "".join(str(texto or "").upper().split())
    if not crudo:
        return "desconocida"
    if any(resto.replace(" ", "") in crudo for resto in RESTOS_DEL_MODULO):
        return "modulo"
    if any(resto in crudo for resto in RESTOS_DEL_PROVEEDOR):
        return "proveedor"
    if RELOJ.search(str(texto or "")) and any(ch.isdigit() for ch in crudo):
        return "tablero"
    return "desconocida"


def parece_del_modulo(texto: str) -> bool:
    """¿El recorte es del sticker del MÓDULO y no del tablero? Pura.

    El sticker del módulo también lleva fecha (la del módulo, un mes antes). Si no se descarta,
    la búsqueda exhaustiva llena el caso de fechas que no son y el consenso se vuelve ruido.
    """
    crudo = "".join(str(texto or "").upper().split())
    return any(resto.replace(" ", "") in crudo for resto in RESTOS_DEL_MODULO)


def fechas_de_una_foto(ruta: Path, motor=None) -> list[dict]:
    """Todas las fechas plausibles de una foto, con la evidencia de dónde salieron. Pura salvo OCR."""
    imagen = cv2.imread(str(ruta))
    if imagen is None:
        return []
    alto, ancho = imagen.shape[:2]
    if max(alto, ancho) > 1600:
        factor = 1600 / max(alto, ancho)
        imagen = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    salida = []
    # 1) el ancla buena de este lote: el sticker lleva siempre un código al lado de la fecha.
    #    Sin código a la vista no se hace OCR: es el filtro barato que hace que 130 fotos se
    #    recorran en un par de minutos y no en quince.
    pista = T.pista_de_tablero(imagen)
    for caja in (pista.get("codigos") or [])[:2]:
        x, y, w, h = caja["x"], caja["y"], caja["w"], caja["h"]
        for k in (2.5, 4.0):                      # primero justo al lado; si no, más abierto
            trozo = imagen[max(0, y - int(h * k)):y + h + int(h * 0.5),
                           max(0, x - int(w * k)):x + w + int(w * 0.5)]
            if trozo.size == 0:
                continue
            escala = 1000 / max(trozo.shape[:2])
            if escala > 1:
                trozo = cv2.resize(trozo, None, fx=escala, fy=escala,
                                   interpolation=cv2.INTER_CUBIC)
            textos = T._textos(trozo, motor)
            unido = " ".join(texto for texto, _ in textos)
            if not textos:                        # nada legible: puede estar al revés
                volteado = cv2.rotate(trozo, cv2.ROTATE_180)
                textos = T._textos(volteado, motor)
                unido = " ".join(texto for texto, _ in textos)
                if unido:
                    fecha = T.leer_fecha_de_etiqueta(textos, motor)
                    if fecha.get("fecha") and not parece_del_modulo(unido):
                        salida.append({"valor": fecha["fecha"], "giro": 180,
                                       "ancla": "codigo", "clase": clase_de_pegatina(unido),
                                       "texto": unido[:160]})
                        break
                continue
            if parece_del_modulo(unido):
                continue
            fecha = T.leer_fecha_de_etiqueta(textos, motor)
            if fecha.get("fecha"):
                salida.append({"valor": fecha["fecha"], "giro": 0,
                               "ancla": "codigo", "clase": clase_de_pegatina(unido),
                               "texto": unido[:160]})
                break
        if salida:
            break
    if salida:
        return salida
    # 2) sin código a la vista: las manchas blancas con pinta de etiqueta
    for x, y, w, h in etiquetas_blancas(imagen):
        margen_x, margen_y = int(w * 0.10), int(h * 0.10)
        trozo = imagen[max(0, y - margen_y):y + h + margen_y,
                       max(0, x - margen_x):x + w + margen_x]
        if trozo.size == 0:
            continue
        escala = 1000 / max(trozo.shape[:2])
        if escala > 1:
            trozo = cv2.resize(trozo, None, fx=escala, fy=escala,
                               interpolation=cv2.INTER_CUBIC)
        for giro, codigo in ((0, None), (180, cv2.ROTATE_180)):
            vista = trozo if codigo is None else cv2.rotate(trozo, codigo)
            textos = T._textos(vista, motor)
            unido = " ".join(texto for texto, _ in textos)
            if parece_del_modulo(unido):
                continue
            fecha = T.leer_fecha_de_etiqueta(textos, motor)
            if fecha.get("fecha"):
                salida.append({"valor": fecha["fecha"], "giro": giro,
                               "ancla": "etiqueta_blanca", "clase": clase_de_pegatina(unido),
                               "texto": unido[:160]})
                break
        if salida:
            break
    return salida


def leer_fecha_de_una_foto(ruta: Path, motor=None) -> dict | None:
    """La primera fecha plausible de una foto (compatibilidad)."""
    encontradas = fechas_de_una_foto(ruta, motor)
    return encontradas[0] if encontradas else None


def _leer_fecha_de_una_foto_viejo(ruta: Path, motor=None) -> dict | None:
    """La fecha del sticker de una foto, probando el recorte de la etiqueta y la foto entera."""
    imagen = cv2.imread(str(ruta))
    if imagen is None:
        return None
    alto, ancho = imagen.shape[:2]
    if max(alto, ancho) > 1600:
        factor = 1600 / max(alto, ancho)
        imagen = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    for x, y, w, h in etiquetas_blancas(imagen):
        margen_x, margen_y = int(w * 0.10), int(h * 0.10)
        trozo = imagen[max(0, y - margen_y):y + h + margen_y,
                       max(0, x - margen_x):x + w + margen_x]
        if trozo.size == 0:
            continue
        escala = 1000 / max(trozo.shape[:2])
        if escala > 1:
            trozo = cv2.resize(trozo, None, fx=escala, fy=escala,
                               interpolation=cv2.INTER_CUBIC)
        for giro, codigo in ((0, None), (180, cv2.ROTATE_180)):
            vista = trozo if codigo is None else cv2.rotate(trozo, codigo)
            fecha = T.leer_fecha_de_etiqueta(T._textos(vista, motor), motor)
            if fecha.get("fecha"):
                return {"valor": fecha["fecha"], "giro": giro,
                        "texto": str(fecha.get("texto", ""))[:120]}
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Segunda pasada: buscar más fotos para un campo")
    ap.add_argument("--caso", required=True, help="carpeta del caso")
    ap.add_argument("--campo", default="fecha")
    ap.add_argument("--parcial", default="", help="parcial del que se leen las fotos ya miradas")
    ap.add_argument("--salida", default="", help="JSON con las lecturas nuevas")
    ap.add_argument("--maximo-fotos", type=int, default=400)
    ap.add_argument("--presupuesto-s", type=float, default=900.0)
    args = ap.parse_args()

    carpeta = Path(args.caso)
    caso = carpeta.name.split()[0]
    ya_miradas = set()
    if args.parcial and Path(args.parcial).exists():
        parcial = json.loads(Path(args.parcial).read_text(encoding="utf-8"))
        registro = parcial.get(caso) or {}
        for lecturas in (registro.get("lecturas") or {}).values():
            for lectura in lecturas:
                if lectura.get("foto"):
                    ya_miradas.add(str(lectura["foto"]))
    todas = fotos_del_caso(carpeta)
    pendientes = [r for r in todas if r.name not in ya_miradas]
    print(f"{caso}: {len(todas)} fotos · {len(ya_miradas)} ya miradas · "
          f"{len(pendientes)} por mirar (se miran como mucho {args.maximo_fotos})")

    lecturas = []
    inicio = time.time()
    examinadas = 0
    for ruta in pendientes[:args.maximo_fotos]:
        if time.time() - inicio > args.presupuesto_s:
            print(f"  presupuesto agotado tras {examinadas} fotos ({args.presupuesto_s:.0f} s)")
            break
        datos = fechas_de_una_foto(ruta)
        dato = datos[0] if datos else None
        examinadas += 1
        if dato:
            lecturas.append({"valor": dato["valor"], "confianza": 0.8,
                             "foto": ruta.name, "carpeta": ruta.parent.name,
                             "origen": "busqueda_exhaustiva", "giro": dato["giro"],
                             "ancla": dato.get("ancla", ""), "clase": dato.get("clase", ""),
                             "texto": dato["texto"]})
            print(f"  [{examinadas}/{len(pendientes)}] {ruta.parent.name}/{ruta.name} -> "
                  f"{dato['valor']}  [{dato.get('clase', '?')}]", flush=True)
            conteo = {}
            for lectura in [l for l in lecturas if l.get("clase") == "tablero"]:
                conteo[lectura["valor"]] = conteo.get(lectura["valor"], 0) + 1
            if conteo and max(conteo.values()) >= AVISO:
                print(f"  consenso alcanzado: {max(conteo, key=conteo.get)} "
                      f"({max(conteo.values())} lecturas iguales)")
                break
        if examinadas % 20 == 0:
            print(f"  ... {examinadas} fotos, {len(lecturas)} fecha(s), "
                  f"{time.time() - inicio:.0f} s", flush=True)

    segundos = time.time() - inicio
    print(f"\n{examinadas} foto(s) examinada(s) en {segundos:.0f} s · {len(lecturas)} lectura(s)")
    for valor in sorted({l["valor"] for l in lecturas}):
        veces = sum(1 for l in lecturas if l["valor"] == valor)
        print(f"  {valor}  x{veces}")

    if args.salida:
        Path(args.salida).write_text(json.dumps(
            {"caso": caso, "campo": args.campo, "examinadas": examinadas, "segundos": round(segundos, 1),
             "lecturas": lecturas}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"escrito {args.salida}")
    return 0 if lecturas else 3


if __name__ == "__main__":
    raise SystemExit(main())
