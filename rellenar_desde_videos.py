#!/usr/bin/env python3
"""Rellena el libro con lo que dice la **barra de estado de los vídeos** (P16).

Esto es lo que faltaba: P15 sabía leer la barra, pero nada la escribía en el Excel.

    python rellenar_desde_videos.py --libro versionV16_0_28.xlsx --casos "C:\\...\\Resumen-1-Step" \\
                                    --salida versionV16_0_29.xlsx [--simular] [--informe informe.json]

Reglas que no se saltan nunca:

* **no se sobrescribe una celda con dato**: si la celda ya tiene algo, se deja tal cual y se anota
  como «ocupada»;
* el valor tiene que pasar el **protocolo del campo** (`utilidades/protocolo_campos.evaluar`);
* la barra tiene que hablar del **mismo número de prueba** que la fila; si no, no se escribe nada;
* cada celda escrita queda registrada con el valor, el acuerdo entre fotogramas y la ruta del vídeo
  del que sale.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from utilidades.barra_estado import cargar_banco, leer_video
from utilidades.protocolo_campos import evaluar
from utilidades.barra_estado import interpretar_barra_reparada
from utilidades.video_campos import ACUERDO_MINIMO, LEXICO, videos

COLUMNAS = {
    "test_date": "Fecha de prueba",
    "test_place": "Lugar de prueba",
    "temperature_condition": "Temperatura",
    "delay_ms": "Delay ms",
    "inflator_type": "Tipo de generador",
}
NO_ESCRIBIBLES = ("test_number",)   # la fila ya se identifica por el número


def mapa_de_casos(raiz: Path, conocidos: set[str] | None = None) -> dict[str, list[Path]]:
    """Número de prueba → vídeos. El número va en el nombre de la carpeta del caso.

    Se recorren las carpetas de arriba abajo y se queda el número **más cercano** al vídeo, y sólo
    si ese número está en el libro (`conocidos`): así una fecha o un número de parte que aparezca
    en la ruta no confunde el reparto.
    """
    encontrados: dict[str, list[Path]] = defaultdict(list)
    for archivo in videos(raiz):
        elegido = None
        for parte in reversed(archivo.relative_to(raiz).parts[:-1]):
            numeros = re.findall(r"\b(\d{6})\b", parte)
            if conocidos:
                numeros = [n for n in numeros if n in conocidos]
            if numeros:
                elegido = numeros[0]
                break
        if elegido:
            encontrados[elegido].append(archivo)
    return {k: sorted(set(v)) for k, v in encontrados.items()}


def numero_de_la_carpeta(rutas) -> str:
    """El número de prueba del nombre de la carpeta del caso (`232550 RDW NOM HT` → `232550`)."""
    import re
    for ruta in rutas:
        for parte in Path(ruta).parts[::-1]:
            encontrado = re.match(r"(\d{6})\b", parte.strip())
            if encontrado:
                return encontrado.group(1)
    return ""


def leer_caso(rutas: list[Path], banco) -> dict[str, dict]:
    """Lee la barra en todos los vídeos del caso y vota campo por campo.

    El número de la **carpeta** se usa para reparar la lectura de la barra: `22250A` → `222504`, y para
    desempatar meses parecidos (`MAf` ~ `MAR`/`MAY`) con la semana de ese número.
    """
    votos: dict[str, Counter] = {}
    acuerdo: dict[str, list[float]] = {}
    origen: dict[str, str] = {}
    textos: Counter = Counter()
    esperado = numero_de_la_carpeta(rutas)
    for ruta in rutas:
        lectura = leer_video(ruta, muestras=5, banco=banco, lexico=None)
        if lectura.get("texto"):
            textos[lectura["texto"]] += 1
            # se reinterpreta el texto ya reparado y se votan esos campos
            reparado = interpretar_barra_reparada(lectura["texto"], numero_esperado=esperado)
            for campo, valor in reparado.items():
                if campo == "texto":
                    continue
                if campo == "test_number":
                    # la carpeta manda: si la barra no repite el número exacto, no se da por leído
                    lectura["campos"][campo] = valor
                    continue
                if valor in (None, ""):
                    continue
                lectura["campos"][campo] = valor
                lectura["acuerdo"].setdefault(campo, round(lectura.get("confianza", 0) or 0.8, 2))
        for campo, valor in lectura["campos"].items():
            if valor in (None, ""):
                continue
            votos.setdefault(campo, Counter())[valor] += 1
            acuerdo.setdefault(campo, []).append(float(lectura["acuerdo"].get(campo, 0.0)))
            origen.setdefault(campo, str(ruta))
    salida = {}
    for campo, contador in votos.items():
        valor, cuantos = contador.most_common(1)[0]
        salida[campo] = {
            "valor": valor,
            "acuerdo": round(cuantos / max(1, len(rutas)), 2),
            "acuerdo_interno": round(sum(acuerdo.get(campo, [0])) / max(1, len(acuerdo.get(campo, [1]))), 2),
            "video": origen.get(campo, ""),
            "votos": cuantos,
            "videos": len(rutas),
        }
    if textos:
        # la barra tal cual: de aquí sale el proyecto (`EDAG Mex BMG`) y sirve de evidencia
        salida["__resumen__"] = {"texto": textos.most_common(1)[0][0], "videos": len(rutas)}
    return salida


def a_valor_de_celda(campo: str, texto: str):
    """El libro guarda la fecha como fecha y el delay como número, no como texto."""
    if campo == "test_date":
        try:
            return datetime.strptime(texto, "%Y-%m-%d").date()
        except ValueError:
            return None
    if campo == "delay_ms":
        if str(texto).strip() in ("--", "-"):
            return "--"           # convención del libro: sin retardo registrado
        try:
            return float(texto)
        except ValueError:
            return None
    return texto


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Rellenar el libro desde la barra de los vídeos")
    ap.add_argument("--libro", required=True)
    ap.add_argument("--casos", required=True)
    ap.add_argument("--salida", default=None)
    ap.add_argument("--hoja", default="Versuchsmatrix")
    ap.add_argument("--simular", action="store_true", help="no escribe el libro, sólo informa")
    ap.add_argument("--informe", default=None)
    args = ap.parse_args(argv)

    libro_entrada = Path(args.libro)
    salida = Path(args.salida) if args.salida else libro_entrada.with_name(
        libro_entrada.stem + "_videos.xlsx")
    raiz = Path(args.casos)
    if not raiz.is_dir():
        print(f"no existe la carpeta de casos: {raiz}")
        return 1

    banco = cargar_banco(Path(__file__).resolve().parent / "aprendizaje" / "barra_estado.json")
    previo = load_workbook(libro_entrada, data_only=True)[args.hoja]
    col_previo = next((c.column for c in previo[7] if str(c.value or "").strip() == "Número de prueba"), None)
    conocidos = ({"".join(ch for ch in str(previo.cell(f, col_previo).value) if ch.isdigit())
                  for f in range(8, previo.max_row + 1) if previo.cell(f, col_previo).value}
                 if col_previo else set())
    casos = mapa_de_casos(raiz, conocidos)
    print(f"{len(casos)} caso(s) con vídeo en {raiz}")

    # se trabaja sobre una copia: el original no se toca ni en `--simular`
    if not args.simular:
        salida.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(libro_entrada, salida)
    destino = salida if not args.simular else libro_entrada
    libro = load_workbook(destino)
    ws = libro[args.hoja]

    # encabezados de la fila 7
    columna = {}
    for celda in ws[7]:
        if celda.value:
            columna[str(celda.value).strip()] = celda.column
    faltan = [n for n in COLUMNAS.values() if n not in columna]
    if faltan:
        print(f"faltan columnas en el libro: {faltan}")
        return 1
    col_numero = columna["Número de prueba"]

    registro, escritas, ocupadas, sin_video, conflictos = [], 0, 0, [], []
    for fila in range(8, ws.max_row + 1):
        numero = ws.cell(fila, col_numero).value
        if numero in (None, ""):
            continue
        clave = "".join(ch for ch in str(numero) if ch.isdigit())
        rutas = casos.get(clave)
        if not rutas:
            sin_video.append(clave)
            continue
        campos = leer_caso(rutas, banco)
        numero_barra = (campos.get("test_number") or {}).get("valor")
        if numero_barra and numero_barra != clave:
            conflictos.append({"caso": clave, "barra": numero_barra, "videos": [str(p) for p in rutas]})
            continue
        for campo, nombre in COLUMNAS.items():
            if campo in NO_ESCRIBIBLES:
                continue
            dato = campos.get(campo)
            if not dato:
                continue
            veredicto = evaluar(campo, dato["valor"])
            if not veredicto.escribible:
                registro.append({"caso": clave, "campo": campo, "resultado": "no_pasa_protocolo",
                                 "valor": dato["valor"], "estado": veredicto.estado})
                continue
            celda = ws.cell(fila, columna[nombre])
            if celda.value not in (None, ""):
                ocupadas += 1
                registro.append({"caso": clave, "campo": campo, "resultado": "ocupada",
                                 "valor_actual": str(celda.value), "valor_leido": dato["valor"]})
                continue
            if dato["acuerdo"] < ACUERDO_MINIMO:
                registro.append({"caso": clave, "campo": campo, "resultado": "acuerdo_insuficiente",
                                 "valor": dato["valor"], "acuerdo": dato["acuerdo"]})
                continue
            valor = a_valor_de_celda(campo, dato["valor"])
            if valor is None:
                registro.append({"caso": clave, "campo": campo, "resultado": "no_convertible",
                                 "valor": dato["valor"]})
                continue
            if not args.simular:
                celda.value = valor
            escritas += 1
            registro.append({"caso": clave, "campo": campo, "resultado": "escrita",
                             "fila": fila, "columna": nombre, "valor": dato["valor"],
                             "acuerdo": dato["acuerdo"], "acuerdo_interno": dato["acuerdo_interno"],
                             "votos": dato["votos"], "videos": dato["videos"], "video": dato["video"]})

    if not args.simular:
        libro.save(salida)
    print(f"celdas escritas: {escritas} · ocupadas (respetadas): {ocupadas} · "
          f"casos sin vídeo: {len(sin_video)} {sin_video}")
    for linea in registro:
        if linea["resultado"] == "escrita":
            print(f"  + {linea['caso']} {linea['campo']:22s} = {linea['valor']!r} "
                  f"(acuerdo {linea['acuerdo']:.0%} de {linea['videos']} vídeo/s)")
    if conflictos:
        print(f"  ATENCIÓN: {len(conflictos)} caso(s) con barra de otro ensayo: {conflictos}")
    if args.informe:
        Path(args.informe).write_text(json.dumps({
            "libro_entrada": str(libro_entrada), "libro_salida": None if args.simular else str(salida),
            "simulado": bool(args.simular), "casos_con_video": sorted(casos),
            "celdas_escritas": escritas, "celdas_ocupadas_respetadas": ocupadas,
            "casos_sin_video": sin_video, "conflictos": conflictos, "detalle": registro,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"informe: {args.informe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
