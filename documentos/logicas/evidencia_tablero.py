"""Evidencia del TABLERO de instrumentos por caso (P30).

Lee las cuatro columnas del tablero que faltaban en el libro:

| Columna | Dónde está | Cómo se reconoce |
|---|---|---|
| `dashboard_part_number` | grabado en el plástico | dos bandas finas; la de **abajo** termina en una letra o número más grande (`2GJ.857.003.[G]`) |
| `dashboard_serial_number` | etiqueta blanca con QR | de los códigos impresos, **el más largo** (`052 3KVJ008R6E`); se descarta el del PAB (`…ZRZ…`) |
| `dashboard_date` | otra etiqueta, con **pegatina de color** al lado | `17/MAY/2025` (mes en letra) o `17/05/2025` |
| `dashboard_engineering_level` | **estampa de color** | `##S` / `##K` |

El trabajo va **en tres pasos** porque la máquina tiene 2 GB y un OCR por foto se los come:

1. `--lista`   : filtro barato por color/formas de todas las fotos → lista de candidatas por caso.
2. `--rango`   : lee con OCR un tramo de esa lista y acumula las lecturas (un proceso por tramo).
3. `--cerrar`  : consenso por caso (voto por posición) → `evidencia_tablero.json`.

Así se puede reanudar sin repetir ni perder lo leído, y ninguna lectura se inventa: lo que no sale
queda sin valor y sale como duda con el recorte al lado.

Uso (lo normal es dejar que `leer_tablero_lote.py` haga los tres pasos):
    python evidencia_tablero.py --fotos ... --json evidencia_tablero.json --salida evidencia_tablero \
        --catalogo 2GJ.857.003.G --lista /tmp/lista_tablero.json
"""
from __future__ import annotations

import argparse
import gc
import json
from collections import Counter, defaultdict
from pathlib import Path

import cv2

from utilidades import codigos_modulo as CM
from utilidades import tablero_campos as T

CAMPOS = ("dashboard_part_number", "dashboard_serial_number", "dashboard_date",
          "dashboard_engineering_level")
EXTENSIONES = (".jpg", ".jpeg", ".png")
CUPOS = {"estampa": 5, "pegatina": 4, "codigo": 5, "etiqueta": 5, "grabado": 2}
# cuántas lecturas iguales hacen falta para dar un valor por bueno. La serie es el campo donde el
# OCR falla más en la cola (una foto lee `…R6E` y otra `…R6E1`), así que pide más acuerdo.
MINIMOS = {"dashboard_serial_number": 2, "dashboard_part_number": 1, "dashboard_date": 2,
           "dashboard_engineering_level": 2}


def fotos_de_caso(carpeta: Path) -> list[Path]:
    return sorted(p for p in carpeta.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONES)


def _leer(pista_ruta: Path, lado: int) -> object:
    imagen = cv2.imread(str(pista_ruta))
    if imagen is None:
        return None
    alto, ancho = imagen.shape[:2]
    if max(alto, ancho) > lado:
        factor = lado / max(alto, ancho)
        imagen = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    return imagen


def lista_de_candidatas(carpeta: Path) -> dict:
    """Paso 1: qué fotos pueden tener algo del tablero, con cupo por tipo."""
    candidatas = []
    revisadas = 0
    for ruta in fotos_de_caso(carpeta):
        imagen = _leer(ruta, 1000)
        if imagen is None:
            continue
        revisadas += 1
        pista = T.pista_de_tablero(imagen)
        del imagen
        if revisadas % 25 == 0:
            gc.collect()
        if pista["algo"]:
            candidatas.append({"ruta": str(ruta), "pista": pista})
    elegidas: list[dict] = []
    vistos: set[str] = set()
    for tipo, cupo in CUPOS.items():
        if tipo == "codigo":
            grupo = sorted((c for c in candidatas if c["pista"].get("codigos")),
                           key=lambda c: (c["pista"]["codigos"][0]["area"]
                                          if c["pista"].get("codigos") else 0), reverse=True)
        elif tipo == "grabado":
            grupo = sorted((c for c in candidatas if c["pista"].get("grabado")
                            and c["pista"].get("blanco", 0) < 0.05),
                           key=lambda c: c["pista"].get("blanco", 0))
        elif tipo == "etiqueta":
            # primero las etiquetas que además traen código: son las de la serie y la fecha
            grupo = sorted((c for c in candidatas if c["pista"].get("etiqueta")),
                           key=lambda c: (c["pista"]["codigos"][0]["area"]
                                          if c["pista"].get("codigos") else 0), reverse=True)
        else:
            grupo = [c for c in candidatas if c["pista"].get(tipo)]
        for candidata in grupo[:cupo]:
            if candidata["ruta"] in vistos:
                continue
            vistos.add(candidata["ruta"])
            elegidas.append(candidata)
    return {"caso": carpeta.name, "caso_numero": carpeta.name.split()[0],
            "fotos": revisadas, "con_pista": len(candidatas), "elegidas": elegidas}


def leer_tramo(caso: dict, desde: int, hasta: int, parcial: Path, catalogo, salida: Path) -> int:
    """Paso 2: OCR de un tramo de la lista; las lecturas se acumulan en el archivo parcial."""
    acumulado: dict = {}
    if parcial.exists():
        acumulado = json.loads(parcial.read_text(encoding="utf-8"))
    clave = caso["caso_numero"]
    registro = acumulado.setdefault(clave, {"caso": caso["caso"], "caso_numero": clave,
                                            "fotos": caso["fotos"],
                                            "con_pista": caso["con_pista"], "lecturas": {}})
    motor = CM.motor_compartido()
    hechas = 0
    for candidata in caso["elegidas"][desde:hasta]:
        imagen = _leer(Path(candidata["ruta"]), 1280)
        if imagen is None:
            continue
        campos = T.leer_foto_de_tablero(imagen, motor, catalogo, pista=candidata["pista"])
        ruta = Path(candidata["ruta"])
        for campo, dato in campos.items():
            registro["lecturas"].setdefault(campo, []).append({
                "valor": dato.get("valor"), "confianza": round(float(dato.get("confianza") or 0), 3),
                "foto": ruta.name, "carpeta": ruta.parent.name,
                "origen": str(dato.get("origen", ""))[:60]})
            recorte = dato.get("recorte")
            if recorte is not None and getattr(recorte, "size", 0):
                salida.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(salida / f"{clave}_{campo}_{ruta.stem}.jpg"), recorte,
                            [cv2.IMWRITE_JPEG_QUALITY, 88])
        del imagen
        gc.collect()
        hechas += 1
    parcial.write_text(json.dumps(acumulado, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  tramo {clave} {desde}:{hasta} · fotos leídas {hechas}", flush=True)
    return hechas


def consensuar(lecturas) -> dict:
    """Consenso por posición sobre **todas** las lecturas, alineadas por el prefijo.

    La cola de un código se lee distinta en cada foto (`…R6E`, `…R6E1`, `…R6E7`). En vez de votar
    sólo entre las lecturas del largo más repetido, se vota posición a posición contando también a
    las que se quedan cortas: la longitud la decide la posición final con más apoyo.
    """
    lecturas = [dict(l) for l in lecturas if l.get("valor")]
    if not lecturas:
        return {}
    if len(lecturas) > 1:
        alineado = _consenso_alineado(lecturas)
        if alineado:
            return alineado
    largos = Counter(len(str(l["valor"])) for l in lecturas)
    largo = largos.most_common(1)[0][0]
    mismo = [l for l in lecturas if len(str(l["valor"])) == largo]
    mejor = Counter(str(l["valor"]) for l in mismo).most_common(1)[0][0]
    if len(mismo) == 1:
        return {"valor": mejor, "votos": 1, "dudoso": True, "posiciones_dudosas": [],
                "descartadas_por_largo": len(lecturas) - 1}
    dudosas = []
    letras = []
    for posicion in range(largo):
        cuenta: dict[str, float] = defaultdict(float)
        for lectura in mismo:
            cuenta[str(lectura["valor"])[posicion]] += float(lectura.get("confianza") or 0.1)
        elegido, peso = max(cuenta.items(), key=lambda par: par[1])
        total = sum(cuenta.values()) or 1.0
        letras.append(elegido)
        if peso / total < 0.7:
            dudosas.append(posicion)
    return {"valor": "".join(letras), "votos": len(mismo), "dudoso": bool(dudosas),
            "posiciones_dudosas": dudosas, "descartadas_por_largo": len(lecturas) - len(mismo)}


def _consenso_alineado(lecturas: list[dict]) -> dict:
    """Voto por posición (con el espacio como separador que el libro usa).

    Cada lectura aporta su confianza a cada posición; se corta cuando la siguiente posición no
    tiene apoyo suficiente (`< 50 %` del peso), que es justo lo que pasa cuando el OCR añade un
    carácter que la etiqueta no imprime.
    """
    pesos: list[dict[str, float]] = []
    for lectura in lecturas:
        valor = str(lectura["valor"])
        confianza = float(lectura.get("confianza") or 0.1)
        for posicion, caracter in enumerate(valor):
            while len(pesos) <= posicion:
                pesos.append(defaultdict(float))
            pesos[posicion][caracter] += confianza
    # las lecturas que **terminan** antes de una posición también votan ahí: si la mayoría no
    # llega a ese carácter, el carácter no está en el código
    for posicion in range(len(pesos)):
        for lectura in lecturas:
            if len(str(lectura["valor"])) <= posicion:
                pesos[posicion]["\u2205"] += float(lectura.get("confianza") or 0.1)
    if not pesos:
        return {}
    letras, dudosas = [], []
    for posicion, cuenta in enumerate(pesos):
        elegido, peso = max(cuenta.items(), key=lambda par: par[1])
        total = sum(cuenta.values()) or 1.0
        if elegido == "\u2205" or (posicion > 10 and peso / total < 0.5):
            break                      # aquí termina el código: ni la cola ni la marca de corte
        letras.append(elegido)
        if peso / total < 0.7:
            dudosas.append(posicion)
    valor = "".join(letras).strip()
    if not valor:
        return {}
    votos = sum(1 for l in lecturas if str(l["valor"]) == valor)
    return {"valor": valor, "votos": max(1, votos), "dudoso": bool(dudosas),
            "posiciones_dudosas": dudosas,
            "descartadas_por_largo": len(lecturas) - max(1, votos)}


def cerrar(parcial: Path, json_path: Path, salida: Path) -> dict:
    """Paso 3: consenso por caso y escrito del JSON de evidencia."""
    acumulado = json.loads(parcial.read_text(encoding="utf-8"))
    resultados: dict[str, dict] = {}
    if json_path.exists():
        resultados = json.loads(json_path.read_text(encoding="utf-8"))
    for clave, registro in sorted(acumulado.items()):
        resultado = {"caso": registro.get("caso", ""), "caso_numero": clave,
                     "fotos": registro.get("fotos", 0),
                     "fotos_con_pista": registro.get("con_pista", 0)}
        for campo in CAMPOS:
            lecturas = (registro.get("lecturas") or {}).get(campo) or []
            if campo == "dashboard_part_number":
                # las lecturas de `grabado_banda_*` son del número impreso en la etiqueta del
                # **módulo** (`2GJ.880.204.J`): para el número moldeado del tablero no valen
                lecturas = [l for l in lecturas
                            if not str(l.get("origen", "")).startswith("grabado_banda")]
            consenso = consensuar(lecturas)
            if not consenso:
                continue
            resultado[campo] = consenso["valor"]
            resultado.setdefault("votos", {})[campo] = dict(
                Counter(str(l["valor"]) for l in lecturas).most_common(5))
            resultado.setdefault("confianza", {})[campo] = round(
                max(float(l.get("confianza") or 0) for l in lecturas), 2)
            pocas = consenso["votos"] < MINIMOS.get(campo, 2)
            # el número de parte se escribe con **una** foto que lo sostenga: el bloque final, si
            # no se lee, se completa con el del catálogo y así queda anotado en el origen
            moldeado = (campo == "dashboard_part_number"
                        and str(consenso["valor"]).startswith("2GJ.857."))
            # una serie que termina en dígito puede llevar ahí un carácter de control que el libro
            # no usa: se deja en duda en vez de escribirlo (la etiqueta del 222504 imprime `…R6E1`
            # y el libro trae `…R6E`)
            cola_numerica = campo == "dashboard_serial_number" and str(consenso["valor"])[-1:].isdigit()
            resultado.setdefault("dudoso", {})[campo] = bool(
                (consenso["dudoso"] or pocas or cola_numerica) and not moldeado)
            if pocas or cola_numerica:
                resultado.setdefault("por_que_dudoso", {})[campo] = (
                    f"{consenso['votos']} lectura(s) iguales de {len(lecturas)}; "
                    f"hacen falta {MINIMOS.get(campo, 2)}"
                    + ("; la serie termina en dígito (posible carácter de control)" if cola_numerica
                       else ""))
            mejor = max(lecturas, key=lambda l: float(l.get("confianza") or 0))
            capturas = sorted(salida.glob(f"{clave}_{campo}_*.jpg"))
            resultado.setdefault("fuente", {})[campo] = {
                "foto": mejor.get("foto", ""), "carpeta": mejor.get("carpeta", ""),
                "origen": mejor.get("origen", ""), "lecturas": len(lecturas),
                "posiciones_dudosas": consenso["posiciones_dudosas"],
                "descartadas_por_largo": consenso.get("descartadas_por_largo", 0),
                "captura": str(capturas[0]) if capturas else ""}
        resultados[clave] = resultado
    json_path.write_text(json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")
    return resultados


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lee las columnas del tablero en las fotos de cada caso")
    ap.add_argument("--fotos", default="", help="carpeta con una subcarpeta por caso")
    ap.add_argument("--json", default="evidencia_tablero.json")
    ap.add_argument("--salida", default="evidencia_tablero", help="dónde dejar los recortes")
    ap.add_argument("--caso", default="", help="procesar sólo un caso (por su número)")
    ap.add_argument("--catalogo", default="", help="números de parte del libro, separados por comas")
    ap.add_argument("--lista", default="", help="paso 1: escribir aquí las candidatas")
    ap.add_argument("--parcial", default="", help="paso 2: archivo donde se acumulan las lecturas")
    ap.add_argument("--rango", default="", help="paso 2: tramo `desde:hasta` de la lista")
    ap.add_argument("--cerrar", action="store_true", help="paso 3: consenso y JSON final")
    args = ap.parse_args(argv)

    salida = Path(args.salida)
    json_path = Path(args.json)
    catalogo = [c.strip() for c in args.catalogo.split(",") if c.strip()]

    if args.cerrar:
        if not args.parcial:
            raise SystemExit("--cerrar necesita --parcial")
        resultados = cerrar(Path(args.parcial), json_path, salida)
        print(f"cerrado: {len(resultados)} caso(s) en {json_path}")
        return 0

    if args.rango:
        if not args.parcial:
            raise SystemExit("--rango necesita --parcial")
        desde, _, hasta = args.rango.partition(":")
        lista = json.loads(Path(args.lista or "").read_text(encoding="utf-8"))
        clave = args.caso
        caso = lista[clave] if clave else next(iter(lista.values()))
        leer_tramo(caso, int(desde or 0), int(hasta or 999), Path(args.parcial), catalogo, salida)
        return 0

    if args.lista:
        raiz = Path(args.fotos)
        listas = {}
        casos = [c for c in sorted(raiz.iterdir()) if c.is_dir() and fotos_de_caso(c)]
        if args.caso:
            casos = [c for c in casos if c.name.split()[0] == args.caso]
        for carpeta in casos:
            listas[carpeta.name.split()[0]] = lista_de_candidatas(carpeta)
            print(f"  {carpeta.name.split()[0]}: {listas[carpeta.name.split()[0]]['fotos']} "
                  f"foto(s) · con pista {listas[carpeta.name.split()[0]]['con_pista']} · "
                  f"a leer {len(listas[carpeta.name.split()[0]]['elegidas'])}", flush=True)
        Path(args.lista).write_text(json.dumps(listas, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
        return 0

    raise SystemExit("indique --lista, --rango o --cerrar")


if __name__ == "__main__":
    raise SystemExit(main())
