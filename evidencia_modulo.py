#!/usr/bin/env python3
"""Evidencia de la **estampa del nivel** y de la etiqueta del **módulo PAB** por caso: dos códigos, doble lectura y consenso entre carpetas.

Se ejecuta aparte del relleno (igual que `evidencia_video.py`) porque recorrer cientos de fotos en el
mismo proceso que el libro agota la memoria.

    python evidencia_modulo.py --fotos "C:\\Programas Base\\Resumen-1-Step" --salida evidencia_modulo

Por cada caso:

* lee **todas** las fotos que contengan etiqueta de módulo (número de parte o serie `ZRZ`);
* cada foto se resuelve con el protocolo de **dos códigos**: un valor que aparece **dos veces** en la
  misma etiqueta es firme; si los dos códigos dicen cosas distintas, la foto va a discrepancia;
* después se **vota entre fotos y entre carpetas**: lo que se repite gana, y lo que no tiene mayoría
  queda en duda (nunca se inventa);
* deja `evidencia_modulo.json` y un recorte por caso en `evidencia_modulo/<caso>.png`.

Las claves del JSON son las del libro: `part_number`, `date`, `serial_number`, `engineering_level`,
`module_version`, más `prototipo`, `discrepancias` y `votos`.
"""
from __future__ import annotations

import argparse
import gc
import json
from collections import Counter
from pathlib import Path

import cv2

from utilidades import codigos_modulo as CM

EXTENSIONES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def fotos_de_caso(carpeta: Path) -> list[Path]:
    return sorted(ruta for ruta in carpeta.rglob("*") if ruta.suffix.lower() in EXTENSIONES)


def datos_de_la_carpeta(nombre: str) -> dict:
    """Datos del caso que van en el nombre de la carpeta: `232561 RDW OGL HT`.

    `RDW` es la **variante** del módulo (`PAB · Variante`), `OGL` el tipo de generador
    (`Gasgenerator`) y `HT` la condición de temperatura de la prueba (`Temperatura`).
    """
    partes = nombre.split()
    salida: dict = {"caso_numero": partes[0] if partes else ""}
    resto = [parte.upper() for parte in partes[1:]]
    for parte in resto:
        if parte in ("RDW", "NAR", "ROW"):
            salida["module_version"] = parte
        elif parte in ("NOM", "OGL", "UGL"):
            salida["inflator_type"] = parte
        elif parte in ("NT", "HT", "RT", "KT"):
            salida["temperature_condition"] = parte
    return salida


def procesar_caso(carpeta: Path, aprendizaje: dict | None, maximo_fotos: int | None,
                  salida: Path | None = None) -> dict:
    rutas = fotos_de_caso(carpeta)
    if maximo_fotos:
        rutas = rutas[:maximo_fotos]
    votos: dict[str, Counter] = {campo: Counter() for campo in
                                 ("part_number", "date", "serial_number", "engineering_level",
                                  "module_version")}
    variantes: dict[str, Counter] = {}
    sin_estampa = 0
    prototipos_vistos = 0
    estampas: list[dict] = []
    discrepancias: list[dict] = []
    prototipo = False
    leidas, con_modulo = 0, 0
    mejor = None
    for ruta in rutas:
        imagen = cv2.imread(str(ruta))
        if imagen is None:
            continue
        leidas += 1
        if leidas % 15 == 0:
            gc.collect()          # el proceso vive con 1 GB: se libera a mano cada 15 fotos
        lectura = CM.leer_foto_modulo(imagen, aprendizaje=None)
        if not lectura.get("es_modulo") and not lectura.get("estampa") and len(estampas) < 25:
            # acercamientos a la pegatina donde no se lee ni el número de parte: se busca una sola
            # candidata y a media resolución, que de sobra para un nivel de tres caracteres
            suelta = CM.leer_estampa_nivel(imagen, maximo=1, lado_busqueda=1000)
            if suelta.get("nivel"):
                estampas.append({"foto": ruta.name, "giro": suelta["giro"],
                                 "confianza": round(suelta["confianza"], 2),
                                 "texto": suelta["texto"], "area": suelta["area"],
                                 "nivel": suelta["nivel"], "solo_estampa": True})
        if lectura.get("estampa") and lectura.get("engineering_level"):
            # la estampa cuenta aunque el OCR no haya visto el número de parte en esa foto
            estampas.append({"foto": ruta.name, **lectura["estampa"],
                             "nivel": lectura["engineering_level"]})
        if not lectura.get("es_modulo"):
            continue
        con_modulo += 1
        if lectura.get("prototipo"):
            prototipo = True
        if any("PROTOTIP" in str(texto).upper() or "PROTOTYPE" in str(texto).upper()
               for texto in lectura.get("lineas") or []):
            prototipos_vistos += 1
        for campo, contador in votos.items():
            if campo == "engineering_level":
                continue          # el nivel se decide con las estampas, más abajo
            if lectura.get(campo):
                contador[lectura[campo]] += 1
        for campo in ("variante", "farbe", "codigo_proveedor", "generador"):
            if lectura.get(campo):
                variantes.setdefault(campo, Counter())[lectura[campo]] += 1
        if lectura.get("sin_estampa"):
            sin_estampa += 1
        for discrepancia in lectura.get("discrepancias") or []:
            # una foto suelta que lee distinto no es una duda: la duda es que el caso entero no se
            # ponga de acuerdo (se filtra al final, cuando ya hay votos)
            discrepancias.append({"foto": ruta.name, **discrepancia})
        if lectura.get("part_number") and mejor is None:
            mejor = (imagen.copy(), ruta.name)
    campos: dict[str, object] = {"caso": carpeta.name, "fotos": leidas, "fotos_con_modulo": con_modulo}
    campos.update(datos_de_la_carpeta(carpeta.name))
    for campo, contador in votos.items():
        if not contador:
            continue
        valor, veces = contador.most_common(1)[0]
        campos[campo] = valor
        campos.setdefault("votos", {})[campo] = dict(contador.most_common(4))
        campos.setdefault("confianza", {})[campo] = round(veces / max(1, con_modulo), 2)
    niveles = Counter(estampa["nivel"] for estampa in estampas if estampa.get("nivel"))
    if niveles:
        nivel, veces = niveles.most_common(1)[0]
        campos["engineering_level"] = nivel
        campos["votos"] = campos.get("votos") or {}
        campos["votos"]["engineering_level"] = dict(niveles.most_common(4))
        campos["confianza"] = campos.get("confianza") or {}
        campos["confianza"]["engineering_level"] = round(veces / max(1, len(estampas)), 2)
        campos.setdefault("fuente_nivel", {})["engineering_level"] = "estampa_amarilla"
    campos["fotos_sin_estampa"] = sin_estampa
    if estampas:
        campos["estampas"] = estampas[:6]
    for campo, contador in variantes.items():
        campos.setdefault("variante_pab", {})[campo] = contador.most_common(1)[0][0]
    if prototipo:
        campos["prototipo"] = True
    if prototipos_vistos:
        campos["prototipo_visto"] = prototipos_vistos
    dudosas = [discrepancia for discrepancia in discrepancias
               if (campos.get("confianza") or {}).get(discrepancia.get("campo"), 0.0) < 0.75]
    if dudosas:
        campos["discrepancias"] = dudosas[:8]
    if mejor is not None:
        campos["foto_evidencia"] = mejor[1]
        if salida is not None:
            captura = salida / f"{carpeta.name.split()[0]}.png"
            captura.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(captura), mejor[0])
            campos["captura"] = str(captura)
    return campos


# Pares que en la **estampa** se confunden de verdad. `6`/`9` no están: en la pegatina se distinguen,
# y meterlos convertiría el nivel `69K` de una carpeta en el `66K` de otra, que es otra lectura.
CONFUSABLES = (("5", "6"), ("0", "6"), ("8", "6"), ("1", "6"), ("1", "7"), ("2", "7"))
# Cuando la pegatina está medio tapada, el dígito incompleto se lee como un trozo: `6` -> `5`, `0` o
# `1`. Por eso, entre dos lecturas que sólo difieren en un dígito confundible, se queda la del dígito
# **que necesita el glifo entero**. No es una preferencia estética: un `6` tapado nunca se lee `6`.
PESO_DIGITO = {"1": 0, "7": 0, "5": 1, "0": 1, "2": 2, "8": 2, "6": 3, "9": 3, "3": 3}


def _compatible(a: str, b: str) -> bool:
    """¿Dos niveles son el mismo leído con **un** dígito confundido? (`56K` ~ `66K`).

    Sólo un dígito: `69K` no puede convertirse en `56K` aunque cada cambio por separado sea posible,
    porque sería otra lectura, no una errata de OCR.
    """
    if len(a) != len(b) or a[-1] != b[-1]:
        return False
    distintos = [(izquierda, derecha) for izquierda, derecha in zip(a[:-1], b[:-1])
                 if izquierda != derecha]
    if len(distintos) != 1:
        return False
    izquierda, derecha = distintos[0]
    return any({izquierda, derecha} == set(par) for par in CONFUSABLES)


def _peso(valor: str) -> int:
    """Cuánto «glifo entero» pide un nivel: `66K` (3) pesa más que `56K` (1) o `16K` (0)."""
    return sum(PESO_DIGITO.get(caracter, 0) for caracter in str(valor or "")[:-1])


def resolver_niveles(resultados: dict[str, dict]) -> None:
    """Confronta el nivel de cada carpeta con el de las demás.

    * si el mismo valor aparece en otra carpeta, se queda tal cual (nada que decidir);
    * si sólo difiere en **un** dígito confundible del de otra carpeta, gana el que pide el glifo
      entero —una pegatina medio tapada nunca se lee `66K`, se lee `56K`/`16K`— y queda anotada la
      lectura original;
    * si el valor es de otra familia (`69K` frente a `66K`), no se toca: son niveles distintos.

    Siempre se parte de `engineering_level_lectura`, así que repetir la pasada da el mismo resultado.
    """
    lecturas: dict[str, str] = {}
    for clave, resultado in resultados.items():
        valor = resultado.get("engineering_level_lectura") or resultado.get("engineering_level")
        if valor:
            lecturas[clave] = valor
    if not lecturas:
        return
    for clave, valor in lecturas.items():
        resultados[clave].setdefault("engineering_level_lectura", valor)
        candidatos = {valor: 1}
        for otra, otro_valor in lecturas.items():
            if otra == clave or otro_valor == valor:
                continue
            if otro_valor in candidatos:
                candidatos[otro_valor] += 1
            elif _compatible(valor, otro_valor):
                candidatos[otro_valor] = 1
        if len(candidatos) == 1:
            resultados[clave]["engineering_level"] = valor
            continue
        ganador = max(candidatos, key=lambda opcion: (_peso(opcion), candidatos[opcion]))
        resultados[clave]["engineering_level"] = ganador
        if ganador != valor:
            resultados[clave].setdefault("fuente_nivel", {})["engineering_level"] = (
                f"consenso entre carpetas ({valor} leído -> {ganador})")


def aplicar_nivel_de_partida(resultados: dict[str, dict]) -> None:
    """Sin pegatina amarilla el módulo está en el **nivel de partida** (`01S`).

    Se marca como tal —`nivel_sin_estampa` y la fuente lo dicen con todas las letras— para que se vea
    en el libro que ese valor no sale de una lectura, sino de que la estampa no existe.
    """
    for resultado in resultados.values():
        if resultado.get("engineering_level") or resultado.get("prototipo"):
            continue
        if not resultado.get("fotos_con_modulo"):
            continue
        resultado["engineering_level"] = CM.NIVEL_DE_PARTIDA
        resultado["nivel_sin_estampa"] = True
        resultado.setdefault("fuente_nivel", {})["engineering_level"] = (
            f"sin pegatina amarilla en {resultado.get('fotos_con_modulo', 0)} foto(s): nivel de partida")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evidencia del módulo PAB (dos códigos por etiqueta)")
    ap.add_argument("--fotos", required=True, help="árbol con una carpeta por caso")
    ap.add_argument("--salida", default="evidencia_modulo", help="carpeta de recortes")
    ap.add_argument("--json", default="evidencia_modulo.json")
    ap.add_argument("--maximo-fotos", type=int, default=None)
    ap.add_argument("--aprendizaje", default=None, help="aprendizaje previo (por defecto el del proyecto)")
    ap.add_argument("--proveedor", action="store_true",
                    help="sólo busca el proveedor (Autoliv) en el texto vertical de la etiqueta y lo "
                         "añade al JSON; no vuelve a leer parte, serie ni nivel")
    ap.add_argument("--reanudar", action="store_true",
                    help="no vuelve a leer los casos que ya están en el JSON (por si se corta)")
    args = ap.parse_args(argv)

    raiz = Path(args.fotos)
    if not raiz.is_dir():
        print(f"no existe la carpeta: {raiz}")
        return 1
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    aprendizaje = CM.cargar_aprendizaje(Path(args.aprendizaje) if args.aprendizaje else None)
    casos = [c for c in sorted(raiz.iterdir()) if c.is_dir() and fotos_de_caso(c)]
    resultados: dict[str, dict] = {}
    pendientes: dict[str, dict] = {}
    if args.reanudar and Path(args.json).exists():
        resultados = json.loads(Path(args.json).read_text(encoding="utf-8"))
        print(f"  se reanuda con {len(resultados)} caso(s) ya leídos", flush=True)
    if args.proveedor:
        # el JSON se carga SIEMPRE: esta pasada sólo añade el proveedor y no debe borrar lo demás
        if Path(args.json).exists():
            resultados = json.loads(Path(args.json).read_text(encoding="utf-8"))
        for carpeta in casos:
            clave = carpeta.name.split()[0]
            datos = resultados.setdefault(clave, {"caso": carpeta.name})
            if datos.get("inflator_supplier"):
                continue
            for ruta in sorted(fotos_de_caso(carpeta)):
                imagen = cv2.imread(str(ruta))
                if imagen is None:
                    continue
                lectura = CM.leer_proveedor(imagen)
                if lectura:
                    datos["inflator_supplier"] = lectura["inflator_supplier"]
                    datos["proveedor"] = {"texto": lectura["texto"], "foto": ruta.name,
                                          "giro": lectura["giro"],
                                          "confianza": round(lectura["confianza"], 2)}
                    print(f"  {clave}: proveedor leído «{lectura['texto']}» ({ruta.name})", flush=True)
                    Path(args.json).write_text(json.dumps(resultados, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
                    break
        Path(args.json).write_text(json.dumps(resultados, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"proveedor: {sum(1 for d in resultados.values() if d.get('inflator_supplier'))}"
              f"/{len(resultados)} casos con lectura")
        return 0

    for carpeta in casos:
        if args.reanudar and carpeta.name.split()[0] in resultados:
            continue
        resultado = procesar_caso(carpeta, aprendizaje, args.maximo_fotos, salida)
        if not resultado.get("fotos_con_modulo"):
            print(f"  {resultado['caso'].split()[0]}: sin lectura de módulo "
                  f"({resultado['fotos']} fotos revisadas)", flush=True)
            pendientes[resultado["caso"].split()[0]] = resultado
            continue
        resultados[resultado["caso"].split()[0]] = resultado
        # se guarda caso a caso: si el proceso se corta, no se pierde lo leído
        Path(args.json).write_text(json.dumps(resultados, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"  {resultado['caso'].split()[0]}: {resultado['fotos_con_modulo']} foto(s) de módulo · "
              f"parte={resultado.get('part_number') or '?'} fecha={resultado.get('date') or '?'} "
              f"serie={resultado.get('serial_number') or '?'} nivel={resultado.get('engineering_level') or '?'}",
              flush=True)
    resolver_niveles(resultados)
    aplicar_nivel_de_partida(resultados)
    if pendientes:
        print(f"casos sin lectura de módulo: {len(pendientes)} · revisar a mano", flush=True)
    if resultados:
        CM.aprender({clave: valor for clave, valor in resultados.items()})
    Path(args.json).write_text(json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"casos: {len(resultados)} · json {args.json} · recortes {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
