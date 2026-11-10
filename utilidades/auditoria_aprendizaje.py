"""utilidades/auditoria_aprendizaje.py — Auditoría estricta de la base de aprendizaje.

Se ejecuta contra el `aprendizaje.sqlite3` real; no lo modifica (solo lectura).

    python utilidades/auditoria_aprendizaje.py /ruta/aprendizaje.sqlite3 --json informe.json

Qué decide, y con qué criterio
------------------------------
La pregunta no es «¿cuántos datos hay?» sino «¿qué de esto se puede usar sin
arriesgar un dato mal puesto?». Cada bloque de la base se clasifica:

  utilizable            -> se puede usar tal cual
  utilizable_con_condiciones -> sirve como evidencia o como pista, no como regla
  no_utilizable         -> usarlo introduciría errores

Criterios concretos
-------------------
* **Correcciones**: solo son regla global si el texto corregido conserva los
  mismos caracteres alfanuméricos (cambia mayúsculas, espacios o puntuación).
  Si añaden, quitan o cambian letras o dígitos, son evidencia de ESA imagen: una
  corrección como `100475 -> 100425` aplicada en general reescribiría cualquier
  número que acabe en 475.
* **Correcciones contradictorias**: el mismo texto de origen con dos destinos
  distintos no es aprendizaje, es ruido; va a cuarentena.
* **Correcciones de 1-2 caracteres**: no identifican nada; van a cuarentena.
* **Campos del libro**: se comprueba si la base guarda el campo del Excel. Si el
  campo solo toma valores como `etiqueta` o `union_manual`, es el tipo de
  elemento de la interfaz, no una columna del libro.
* **Modelos**: si las tablas de modelos están vacías, no hay modelo entrenado y
  no se puede afirmar que el programa «haya aprendido».
* **Orientaciones**: se informan como pista solo si tienen respaldo suficiente.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

CAMPOS_UI = {"etiqueta", "union_manual", "ajuste_bloque", "bloque", "region", "zona"}


def _alfanumerico(texto: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(texto or "").upper())


def clasificar_correccion(origen: str, destino: str) -> tuple[str, str]:
    """Devuelve (estado, motivo) de una pareja corrección.

    estados: `regla_segura`, `evidencia_de_imagen`, `cuarentena`
    """
    o, d = str(origen or "").strip(), str(destino or "").strip()
    if len(o) <= 2:
        return "cuarentena", f"origen de {len(o)} carácter(es): no identifica nada"
    if not d:
        return "cuarentena", "destino vacío"
    if _alfanumerico(o) == _alfanumerico(d):
        return "regla_segura", "solo cambia mayúsculas/espacios/puntuación"
    return "evidencia_de_imagen", "cambia letras o dígitos: solo vale para su imagen"


def auditar(ruta: str | Path, tope_ejemplos: int = 8) -> dict:
    ruta = Path(ruta)
    conexion = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    conexion.row_factory = sqlite3.Row

    def filas(sql: str, *args):
        return conexion.execute(sql, args).fetchall()

    def escalar(sql: str, *args):
        return conexion.execute(sql, args).fetchone()[0]

    tablas = {r[0] for r in filas("select name from sqlite_master where type='table'")}
    informe: dict = {"archivo": str(ruta), "bytes": ruta.stat().st_size,
                     "quick_check": escalar("pragma quick_check"), "bloques": {}}

    # ---------------------------------------------------------------- campos
    bloque_campos = {"estado": "no_utilizable", "detalle": {}, "motivo": ""}
    for tabla, columna in (("muestras_visuales", "campo"), ("estrategias_ocr", "campo")):
        if tabla not in tablas:
            continue
        total = escalar(f"select count(*) from {tabla}")
        vacias = escalar(f"select count(*) from {tabla} where trim(coalesce({columna},''))=''")
        valores = [r[0] for r in filas(
            f"select distinct {columna} from {tabla} where trim(coalesce({columna},''))<>''")]
        de_ui = [v for v in valores if str(v).strip().lower() in CAMPOS_UI]
        bloque_campos["detalle"][tabla] = {
            "filas": total, "campo_vacio": vacias, "valores": valores,
            "valores_de_interfaz": de_ui}
    valores_totales = {v for d in bloque_campos["detalle"].values() for v in d["valores"]}
    if not valores_totales:
        bloque_campos["motivo"] = "no hay ningún campo declarado"
    elif valores_totales <= CAMPOS_UI:
        bloque_campos["motivo"] = ("la columna `campo` no guarda columnas del libro: "
                                  f"solo tipos de elemento {sorted(valores_totales)}")
    else:
        bloque_campos["estado"] = "utilizable_con_condiciones"
        bloque_campos["motivo"] = f"valores mixtos: {sorted(valores_totales)}"
    informe["bloques"]["campos_del_libro"] = bloque_campos

    # ----------------------------------------------------------- correcciones
    bloque_corr: dict = {"estado": "no_utilizable", "detalle": {}, "motivo": ""}
    for tabla in ("correcciones", "correcciones_texto"):
        if tabla not in tablas:
            continue
        parejas = [(r["texto_ocr"], r["texto_correcto"]) for r in filas(
            f"select texto_ocr, texto_correcto from {tabla}")]
        destinos: dict[str, set] = defaultdict(set)
        for origen, destino in parejas:
            destinos[str(origen).strip().lower()].add(str(destino).strip())
        estados = Counter()
        cuarentena, reglas, evidencias = [], [], []
        for origen, conjunto in destinos.items():
            if len(conjunto) > 1:
                estados["cuarentena"] += 1
                cuarentena.append({"origen": origen, "destinos": sorted(conjunto),
                                   "motivo": f"{len(conjunto)} destinos distintos para el mismo texto"})
                continue
            estado, motivo = clasificar_correccion(origen, next(iter(conjunto)))
            estados[estado] += 1
            registro = {"origen": origen, "destino": next(iter(conjunto)), "motivo": motivo}
            (reglas if estado == "regla_segura" else
             evidencias if estado == "evidencia_de_imagen" else cuarentena).append(registro)
        bloque_corr["detalle"][tabla] = {
            "filas": len(parejas), "textos_distintos": len(destinos),
            "cuenta": dict(estados),
            "reglas_seguras": reglas[:tope_ejemplos],
            "evidencia_de_imagen": evidencias[:tope_ejemplos],
            "cuarentena": cuarentena[:tope_ejemplos],
            "reglas_seguras_total": len(reglas),
            "evidencia_total": len(evidencias),
            "cuarentena_total": len(cuarentena),
        }
    if bloque_corr["detalle"]:
        seguro = sum(d["reglas_seguras_total"] for d in bloque_corr["detalle"].values())
        evid = sum(d["evidencia_total"] for d in bloque_corr["detalle"].values())
        cuar = sum(d["cuarentena_total"] for d in bloque_corr["detalle"].values())
        bloque_corr["estado"] = "utilizable_con_condiciones" if seguro else "no_utilizable"
        bloque_corr["motivo"] = (f"{seguro} reglas seguras (normalizan forma), "
                                 f"{evid} válidas solo para su imagen, {cuar} en cuarentena. "
                                 "Ninguna corrección que cambie dígitos puede aplicarse en general.")
    informe["bloques"]["correcciones"] = bloque_corr

    # ---------------------------------------------------------------- modelos
    conteo_modelos = {t: escalar(f"select count(*) from {t}") for t in
                      ("modelos", "modelos_visuales", "roi_preferidas") if t in tablas}
    informe["bloques"]["modelos"] = {
        "estado": "no_utilizable" if not any(conteo_modelos.values()) else "utilizable",
        "detalle": conteo_modelos,
        "motivo": ("no hay ningún modelo entrenado" if not any(conteo_modelos.values())
                   else "hay modelos registrados"),
    }

    # ---------------------------------------------------------- orientaciones
    if "estrategias_ocr" in tablas:
        por_orientacion = {int(r[0]): {"n": r[1], "confianza_media": round(r[2] or 0, 3)}
                           for r in filas("select orientacion_base, count(*), avg(confianza) "
                                          "from estrategias_ocr group by 1")}
        total = sum(v["n"] for v in por_orientacion.values())
        informe["bloques"]["orientaciones"] = {
            "estado": "utilizable_con_condiciones" if total >= 10 else "no_utilizable",
            "detalle": por_orientacion,
            "motivo": (f"{total} estrategias registradas; la orientación es una pista, "
                       "no una regla: se confirma leyendo la imagen"),
        }
        sin_campo = escalar("select count(*) from estrategias_ocr "
                            "where trim(coalesce(campo,''))=''")
        tentativas = [{"texto": r["texto_resultado"], "confianza": r["confianza"],
                       "orientacion": r["orientacion_base"]}
                      for r in filas("select texto_resultado, confianza, orientacion_base "
                                     "from estrategias_ocr order by coalesce(confianza,0) desc limit 6")]
        informe["bloques"]["estrategias"] = {
            "estado": "utilizable_con_condiciones",
            "detalle": {"total": total, "sin_campo_asignado": sin_campo,
                        "mejores": tentativas},
            "motivo": ("las estrategias no declaran campo del libro y algunas contienen "
                       "lecturas erróneas guardadas con confianza alta: sirven para priorizar "
                       "orientación, no para fijar valores"),
        }

    # ------------------------------------------------------- tokens del OCR
    if "observaciones" in tablas:
        total = escalar("select count(*) from observaciones")
        imagenes = escalar("select count(distinct imagen_hash) from observaciones")
        confianza = escalar("select avg(confianza) from observaciones") or 0
        largos = Counter()
        unicos = 0
        for r in filas("select texto_ocr from observaciones"):
            texto = (r[0] or "").strip()
            largos[len(texto)] += 1
        un_char = largos.get(1, 0)
        palabras = sum(v for k, v in largos.items() if k >= 3)
        unicos = escalar("select count(distinct texto_ocr) from observaciones")
        informe["bloques"]["tokens_ocr"] = {
            "estado": "utilizable_con_condiciones",
            "detalle": {"tokens": total, "imagenes": imagenes,
                        "confianza_media": round(confianza, 3),
                        "un_caracter": un_char,
                        "un_caracter_pct": round(un_char * 100 / total, 1) if total else 0,
                        "tres_o_mas": palabras,
                        "distintos": unicos},
            "motivo": (f"{un_char * 100 / total:.1f}% de los tokens son un solo carácter: "
                       "el OCR está partiendo las etiquetas, que es justo lo que impide "
                       "formar campos") if total else "sin observaciones",
        }

    # --------------------------------------------------- imágenes sin datos
    if "imagenes_sin_datos" in tablas:
        sin_motivo = escalar("select count(*) from imagenes_sin_datos "
                             "where trim(coalesce(motivo,''))=''")
        total = escalar("select count(*) from imagenes_sin_datos")
        informe["bloques"]["descartes"] = {
            "estado": "utilizable" if sin_motivo == 0 else "utilizable_con_condiciones",
            "detalle": {"total": total, "sin_motivo": sin_motivo},
            "motivo": (f"{sin_motivo} de {total} descartes no dicen por qué: no sirven "
                       "para corregir el proceso"),
        }

    conexion.close()
    informe["veredicto_general"] = _veredicto(informe)
    return informe


def _veredicto(informe: dict) -> str:
    bloques = informe["bloques"]
    utiles = [n for n, b in bloques.items() if b["estado"] == "utilizable"]
    cond = [n for n, b in bloques.items() if b["estado"] == "utilizable_con_condiciones"]
    no = [n for n, b in bloques.items() if b["estado"] == "no_utilizable"]
    return (f"utilizable: {utiles or 'nada'} · con condiciones: {cond or 'nada'} · "
            f"no utilizable: {no or 'nada'}")


def resumen_markdown(informe: dict) -> str:
    lineas = [f"# Auditoría de la base de aprendizaje", "",
              f"- Archivo: `{informe['archivo']}` ({informe['bytes']} bytes)",
              f"- Integridad SQLite: `{informe['quick_check']}`", "",
              f"**{informe['veredicto_general']}**", ""]
    for nombre, bloque in informe["bloques"].items():
        lineas.append(f"## {nombre} · `{bloque['estado']}`")
        lineas.append(f"{bloque['motivo']}")
        for tabla, detalle in (bloque.get("detalle") or {}).items():
            if isinstance(detalle, dict):
                resumen = {k: v for k, v in detalle.items()
                           if not isinstance(v, list) and not isinstance(v, dict)}
                lineas.append(f"- `{tabla}`: {resumen}")
                for clave in ("reglas_seguras", "evidencia_de_imagen", "cuarentena"):
                    for ejemplo in detalle.get(clave, [])[:5]:
                        lineas.append(f"  - {clave}: {ejemplo}")
            else:
                lineas.append(f"- `{tabla}`: {detalle}")
        lineas.append("")
    return "\n".join(lineas)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Auditoría estricta de aprendizaje.sqlite3")
    ap.add_argument("base")
    ap.add_argument("--json", dest="salida_json")
    ap.add_argument("--markdown", dest="salida_md")
    args = ap.parse_args(argv)
    informe = auditar(args.base)
    if args.salida_json:
        Path(args.salida_json).write_text(json.dumps(informe, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    if args.salida_md:
        Path(args.salida_md).write_text(resumen_markdown(informe), encoding="utf-8")
    print(json.dumps({"veredicto_general": informe["veredicto_general"]}, ensure_ascii=False))
    for nombre, bloque in informe["bloques"].items():
        print(f"  {nombre:<20} {bloque['estado']:<28} {bloque['motivo'][:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
