#!/usr/bin/env python3
"""P43 · Verificación automática de un libro de salida frente al libro de partida.

    python verificar_salida_p43.py --base "libro del cliente.xlsx" --salida "salida nueva.xlsx" \
        [--validacion validacion_resultados.json] [--informe-tablero informe_tablero_p42.json] \
        [--referencia Book-10-Examples_CORREGIDO.xlsx] [--json verificacion.json]

Comprueba (y sale con código 1 si algo de lo OBLIGATORIO falla):

1. el libro de partida no cambió (SHA-256 antes/después, si se pasa `--huella-base`);
   la salida es OTRO archivo;
2. imágenes del .xlsx idénticas (huella de cada `xl/media/*`);
3. comentarios de Versuchsmatrix y Rangos idénticos;
4. ninguna celda A:T ocupada en la partida cambió en la salida (filas ≥ 8, Versuchsmatrix y
   Rangos), comparando por COORDENADA; las celdas nuevas se listan;
5. cada celda nueva de las columnas del tablero (O:R) tiene detrás un candidato `tablero_p42`
   en estado `consenso` del mismo caso, o una fuente no-P42 publicada (se informa cuál);
6. cobertura del tablero: fotos presentes, examinadas, descartadas con motivo, con error y
   pendientes (del informe de la corrida).

La referencia (`--referencia`) sólo se usa para EVALUAR con `cierre_libro.leer`: nunca para
escribir. La comparación normalizada de espacios (p. ej. el serial de 222504) se muestra
APARTE como diagnóstico y NO cuenta como coincidencia estricta.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

HOJAS = ("Versuchsmatrix", "Rangos")
COLUMNAS_TABLERO = {15: "dashboard_part_number", 16: "dashboard_serial_number",
                    17: "dashboard_date", 18: "dashboard_engineering_level"}


def huella(ruta: Path) -> str:
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def medios(ruta: Path) -> list[str]:
    with zipfile.ZipFile(ruta) as z:
        return sorted(hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()
                      if n.startswith("xl/media/"))


def _celdas(ruta: Path) -> tuple[dict, dict]:
    from openpyxl import load_workbook
    libro = load_workbook(ruta)
    valores, comentarios = {}, {}
    for nombre in HOJAS:
        if nombre not in libro.sheetnames:
            continue
        hoja = libro[nombre]
        for fila in hoja.iter_rows(min_row=1, max_row=hoja.max_row, max_col=55):
            for celda in fila:
                if celda.comment:
                    comentarios[(nombre, celda.coordinate)] = celda.comment.text
                if celda.row >= 8 and celda.column <= 20 and celda.value not in (None, ""):
                    valores[(nombre, celda.row, celda.column)] = celda.value
    return valores, comentarios


def _numero_por_fila(valores: dict) -> dict:
    return {(h, f): str(v).strip() for (h, f, c), v in valores.items() if c == 3}


def verificar(base: Path, salida: Path, validacion: dict | None = None,
              informe: dict | None = None, huella_base: str | None = None) -> dict:
    base, salida = Path(base), Path(salida)
    errores: list[str] = []
    avisos: list[str] = []
    if base.resolve() == salida.resolve():
        errores.append("la salida es el mismo archivo que el libro de partida")
    if huella_base and huella(base) != huella_base:
        errores.append("el libro de partida CAMBIÓ durante la corrida")
    if medios(base) != medios(salida):
        errores.append("las imágenes del libro no son idénticas")
    v_base, c_base = _celdas(base)
    v_sal, c_sal = _celdas(salida)
    if c_base != {k: c_sal.get(k) for k in c_base}:
        errores.append("se perdió o cambió algún comentario de Versuchsmatrix/Rangos")
    cambiadas = [{"hoja": h, "fila": f, "columna": c, "antes": v, "despues": v_sal.get((h, f, c))}
                 for (h, f, c), v in v_base.items() if v_sal.get((h, f, c)) != v]
    if cambiadas:
        errores.append(f"{len(cambiadas)} celda(s) ocupada(s) cambiaron o se vaciaron")
    numeros = _numero_por_fila(v_sal)
    nuevas = [{"hoja": h, "fila": f, "columna": c, "numero": numeros.get((h, f)), "valor": v}
              for (h, f, c), v in v_sal.items() if (h, f, c) not in v_base]

    # 5. respaldo de las celdas nuevas del tablero
    respaldo = []
    if validacion:
        por_numero: dict[str, list[dict]] = {}
        for fila in validacion.get("resultados") or []:
            por_numero.setdefault(str(fila.get("test_number") or ""), []).append(fila)
        for celda in nuevas:
            campo = COLUMNAS_TABLERO.get(celda["columna"])
            if not campo or celda["hoja"] != "Versuchsmatrix":
                continue
            filas = por_numero.get(str(celda["numero"]), [])
            if len(filas) != 1:
                errores.append(f"{celda['numero']} {campo}: identidad ambigua o ausente en la validación")
                continue
            candidatos = [c for c in filas[0].get("candidatos") or []
                          if c.get("clave") == campo
                          and str(c.get("valor_normalizado")) == str(celda["valor"])]
            p42 = [c for c in candidatos if c.get("fuente") == "tablero_p42"
                   and c.get("estado_p42") == "consenso"]
            otra = [c for c in candidatos if c.get("fuente") != "tablero_p42"]
            if p42:
                origen = "tablero_p42:consenso"
            elif otra:
                origen = "otra fuente: " + ", ".join(sorted({str(c.get("fuente")) for c in otra}))
            else:
                origen = "SIN RESPALDO"
                errores.append(f"{celda['numero']} {campo}={celda['valor']!r} no tiene candidato que lo sostenga")
            respaldo.append({**celda, "campo": campo, "origen": origen,
                             "fotos": sorted({str(c.get("imagen")) for c in p42 or otra})})
    cobertura = (informe or {}).get("totales") or {}
    if informe is None:
        avisos.append("sin informe del tablero: no se puede comprobar la cobertura")
    elif cobertura.get("pendientes"):
        avisos.append(f"{cobertura['pendientes']} foto(s) pendientes: ningún campo afectado puede "
                      "cerrarse como «sin dato»")
    return {"ok": not errores, "errores": errores, "avisos": avisos,
            "celdas_ocupadas_cambiadas": cambiadas, "celdas_nuevas": nuevas,
            "respaldo_tablero": respaldo, "cobertura": cobertura,
            "imagenes": len(medios(salida)), "comentarios_vm_rangos": len(c_sal)}


def evaluar(salida: Path, referencia: Path) -> dict:
    """SÓLO evaluación contra la referencia (no escribe nada). Separa coincidencias estrictas,
    huecos, «sin dato» (vacío frente a `--`) y la comparación normalizada de espacios."""
    import cierre_libro as C
    libro, ref = C.leer(Path(salida)), C.leer(Path(referencia))
    cajas: dict[str, int] = {}
    normalizadas = []
    for caso in sorted(ref):
        for campo in C.COLUMNAS.values():
            nuestro = libro.get(caso, {}).get(campo, "")
            esperado = ref[caso].get(campo, "")
            estado = C.clasificar(nuestro, esperado)
            cajas[estado] = cajas.get(estado, 0) + 1
            if estado == "discrepancia" and nuestro.replace(" ", "") == esperado.replace(" ", ""):
                normalizadas.append({"caso": caso, "campo": campo, "libro": nuestro,
                                     "referencia": esperado,
                                     "nota": "sólo difiere en espacios: NO cuenta como coincidencia"})
    total = sum(cajas.values())
    return {"total": total, "cajas": cajas,
            "cerradas_estrictas": cajas.get("coincide", 0) + cajas.get("sin dato", 0),
            "diagnostico_espacios": normalizadas}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verifica una salida P43 sin modificar nada")
    ap.add_argument("--base", required=True)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--validacion", default="")
    ap.add_argument("--informe-tablero", default="")
    ap.add_argument("--huella-base", default="")
    ap.add_argument("--referencia", default="", help="SÓLO para evaluar (Book corregido)")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)
    validacion = (json.loads(Path(args.validacion).read_text(encoding="utf-8"))
                  if args.validacion else None)
    informe = (json.loads(Path(args.informe_tablero).read_text(encoding="utf-8"))
               if args.informe_tablero else None)
    resultado = verificar(Path(args.base), Path(args.salida), validacion, informe,
                          args.huella_base or None)
    if args.referencia:
        resultado["evaluacion"] = evaluar(Path(args.salida), Path(args.referencia))
    print(texto(resultado))
    if args.json:
        Path(args.json).write_text(json.dumps(resultado, ensure_ascii=False, indent=1, default=str),
                                   encoding="utf-8")
    return 0 if resultado["ok"] else 1


def texto(resultado: dict) -> str:
    lineas = ["VERIFICACIÓN P43 · " + ("OK" if resultado["ok"] else "FALLA")]
    lineas += [f"  ERROR: {e}" for e in resultado["errores"]]
    lineas += [f"  aviso: {a}" for a in resultado["avisos"]]
    lineas.append(f"  imágenes en la salida ........ {resultado['imagenes']}")
    lineas.append(f"  comentarios Versuchsmatrix/Rangos {resultado['comentarios_vm_rangos']}")
    lineas.append(f"  celdas ocupadas cambiadas .... {len(resultado['celdas_ocupadas_cambiadas'])}")
    lineas.append(f"  celdas nuevas ................ {len(resultado['celdas_nuevas'])}")
    for r in resultado["respaldo_tablero"]:
        lineas.append(f"    {r['numero']} {r['campo']:28s} {r['valor']!s:18s} ← {r['origen']} {r['fotos'][:3]}")
    c = resultado.get("cobertura") or {}
    if c:
        lineas.append(f"  cobertura tablero: presentes {c.get('presentes', 0)} · examinadas "
                      f"{c.get('examinadas', 0)} · descartadas {c.get('descartadas', 0)} · "
                      f"errores {c.get('errores', 0)} · pendientes {c.get('pendientes', 0)}")
    evaluacion = resultado.get("evaluacion")
    if evaluacion:
        lineas.append(f"  EVALUACIÓN (sólo medición): {evaluacion['cajas']} · cerradas estrictas "
                      f"{evaluacion['cerradas_estrictas']}/{evaluacion['total']}")
        for d in evaluacion["diagnostico_espacios"]:
            lineas.append(f"    diagnóstico espacios {d['caso']} {d['campo']}: {d['libro']!r} vs "
                          f"{d['referencia']!r} — {d['nota']}")
    return "\n".join(lineas)


if __name__ == "__main__":
    sys.exit(main())
