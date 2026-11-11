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

P39 · `cerrar` **funde por campo**: cerrar un caso sólo reescribe los campos que tienen consenso en
este parcial; los demás campos del caso (y sus votos, confianza, dudas y fuente) se conservan tal
como estaban en el JSON. Y `por_que_dudoso` se rellena también cuando las lecturas discrepan.

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
# P40 · RESPUESTA_17 §3: leer **todas** las candidatas del caso (antes 5 por tipo y salía 1 lectura
# de serie por caso). Los topes sólo evitan carpetas patológicas; `--cupos` los cambia.
CUPOS = {"pestana": 8, "estampa": 10, "pegatina": 4, "codigo": 14, "etiqueta": 14,
         "grabado": 2, "datamatrix": 2}
# cuántas lecturas iguales hacen falta para dar un valor por bueno. La serie es el campo donde el
# OCR falla más en la cola (una foto lee `…R6E` y otra `…R6E1`), así que pide más acuerdo.
MINIMOS = {"dashboard_serial_number": 2, "dashboard_part_number": 1, "dashboard_date": 2,
           "dashboard_engineering_level": 2}
# subclaves del resultado de un caso que van indexadas por campo (las que funde `cerrar`)
POR_CAMPO = ("votos", "confianza", "dudoso", "por_que_dudoso", "fuente")


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


def lista_de_candidatas(carpeta: Path, cupos: dict | None = None) -> dict:
    """Paso 1: qué fotos pueden tener algo del tablero, con cupo por tipo."""
    cupos = cupos or CUPOS
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
    for tipo, cupo in cupos.items():
        if tipo == "pestana":
            # P40: el ancla de la fecha; primero las pestañas más grandes (etiqueta más cerca)
            grupo = sorted((c for c in candidatas if c["pista"].get("pestanas")),
                           key=lambda c: c["pista"]["pestanas"][0]["area"], reverse=True)
        elif tipo == "codigo":
            grupo = sorted((c for c in candidatas if c["pista"].get("codigos")),
                           key=lambda c: (c["pista"]["codigos"][0]["area"]
                                          if c["pista"].get("codigos") else 0), reverse=True)
        elif tipo == "grabado":
            grupo = sorted((c for c in candidatas if c["pista"].get("grabado")
                            and c["pista"].get("blanco", 0) < 0.05),
                           key=lambda c: c["pista"].get("blanco", 0))
        elif tipo == "datamatrix":
            grupo = [c for c in candidatas if c["pista"].get("datamatrix")]
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
                "origen": str(dato.get("origen", ""))[:60],
                # P40: de qué ancla sale (la fecha de la pestaña azul vale más) y si es un descarte
                "ancla": str(dato.get("ancla", "") or ""), "descartada": bool(dato.get("descartada")),
                # P42 · revisión de Astra (F2): la duda y la evidencia viajan hasta el final. Antes
                # se perdían aquí y un valor dudoso salía del cierre como si estuviera confirmado.
                "dudoso": bool(dato.get("dudoso")),
                "texto": str(dato.get("texto", ""))[:200],
                "cola_cruda": str(dato.get("cola_cruda", "")),
                "clase_cola": str(dato.get("clase_cola", "")),
                "conflicto": list(dato.get("conflicto") or []),
                "payload_hex": str(dato.get("payload_hex", ""))[:400],
                "formato": str(dato.get("formato", "")),
                "version_decode": str(dato.get("version_decode", ""))})
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


def _solo_clase(lecturas, clase: str = "tablero") -> list[dict]:
    """Si alguna lectura viene de la pegatina del tablero, las demás no compiten. Pura.

    P42 · 2026-10-29: en 232564 votaban juntas la fecha del tablero (17/05), la de una etiqueta
    de proveedor (06/05, «Lieferant») y una del módulo (11/04). Con el voto mezclado, la buena
    perdía. La clase la pone `buscar_mas.clase_de_pegatina()`; las lecturas antiguas no la traen
    y por eso no se descartan: sin clase, se comporta como siempre.
    """
    del_tablero = [l for l in lecturas if str(l.get("clase") or "") == clase]
    return del_tablero or lecturas


def consensuar_completo(lecturas, minimo: int = 2) -> dict:
    """Consenso **por valor completo**: sólo vale una lectura que alguien leyó entera. Pura.

    P42 · revisión de Astra (F6). El consenso por posiciones puede fabricar un valor que ninguna
    foto dio: con `2025-04-11`, `2025-05-06` y `2025-05-17` sale `2025-05-11`, que no está en
    ninguna lectura. Medido en el lote real: es exactamente lo que pasaba en 232561 y 232564
    (lecturas 11/04, 17/05, 06/05, 06/05, 11/04 → el motor publicaba 2025-05-11).

    Aquí se agrupan las lecturas por valor exacto y gana el más repetido; si ninguno llega a
    `minimo`, no hay valor y el campo queda en duda con el recuento a la vista.
    """
    validas = [l for l in lecturas if l.get("valor")]
    if not validas:
        return {}
    cuenta = Counter(str(l["valor"]) for l in validas)
    valor, votos = cuenta.most_common(1)[0]
    respaldo = [l for l in validas if str(l["valor"]) == valor]
    confianza = max(float(l.get("confianza") or 0) for l in respaldo)
    dudoso = votos < minimo or len(cuenta) > 1
    return {"valor": valor, "votos": votos, "dudoso": dudoso, "posiciones_dudosas": [],
            "confianza": confianza, "reparto": dict(cuenta.most_common(5)),
            "descartadas_por_largo": len(validas) - votos}


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
            "posiciones_dudosas": dudosas, "apoyo": apoyo_por_posicion(valor, lecturas),
            "descartadas_por_largo": len(lecturas) - max(1, votos)}


def apoyo_por_posicion(valor: str, lecturas: list[dict]) -> int:
    """P40 · cuántas lecturas sostienen **cada** carácter del valor, en el peor carácter. Pura.

    `052 3KVJ008R6E` con lecturas `…R6E`, `…R6E7` y `…R6EI` tiene apoyo 3 (las tres dicen lo mismo
    en las 14 posiciones del valor), aunque ninguna cadena se repita entera. El final del valor
    lo decide el voto de `_consenso_alineado` (las que se paran ahí también votan).
    """
    valor = str(valor)
    if not valor:
        return 0
    return min(sum(1 for l in lecturas if len(str(l["valor"])) > i and str(l["valor"])[i] == c)
               for i, c in enumerate(valor))


def filtrar_fechas(lecturas: list[dict]) -> tuple[list[dict], int]:
    """Lecturas de `dashboard_date` que valen para el consenso, y cuántas se descartan. Pura.

    - fuera las que vienen de la cadena del DataMatrix del módulo (`T.es_fecha_de_datamatrix`
      sobre el `origen`, que es el texto crudo leído) y las marcadas `descartada` por el lector;
    - P40 · si alguna lectura sale de la **pestaña azul** (`ancla = pestana_azul`), sólo cuentan
      ésas: las de texto suelto quedan como red de seguridad para los casos sin pestaña;
    - **una lectura por foto** (la de más confianza): una misma foto leída dos veces no puede
      corroborarse a sí misma y llegar al mínimo de 2.
    """
    validas = [l for l in lecturas if not l.get("descartada")
               and not T.es_fecha_de_datamatrix(l.get("origen")) and l.get("valor")]
    descartadas = sum(1 for l in lecturas
                      if l.get("descartada") or T.es_fecha_de_datamatrix(l.get("origen")))
    de_ancla = [l for l in validas if l.get("ancla") == "pestana_azul"]
    if de_ancla:
        validas = de_ancla
    # una lectura por foto, quedándose con la que más información trae: la del sticker del
    # tablero manda sobre la que no sabe de qué pegatina sale (P42 · 2026-10-29)
    def _peso(lectura: dict) -> tuple:
        return (str(lectura.get("clase") or "") == "tablero",
                bool(lectura.get("clase")),
                float(lectura.get("confianza") or 0))
    por_foto: dict = {}
    for i, l in enumerate(validas):
        clave = (l.get("carpeta", ""), l.get("foto", "")) if l.get("foto") else ("#", i)
        if clave not in por_foto or _peso(l) > _peso(por_foto[clave]):
            por_foto[clave] = l
    return list(por_foto.values()), descartadas


def motivos_de_duda(campo: str, consenso: dict, lecturas: list[dict]) -> list[str]:
    """Por qué un campo queda en duda, en palabras. Lista vacía = no es dudoso. Pura.

    P39: también cuando las lecturas **discrepan** (antes `dudoso` salía True con
    `por_que_dudoso` vacío).
    P42 · revisión de Astra (F2): la duda que trae la propia lectura ya no se pierde. Antes un
    valor con `dudoso=True` y una cola transformada salía del cierre como si estuviera confirmado.
    """
    motivos = []
    minimo = MINIMOS.get(campo, 2)
    del_codigo = bool(lecturas) and all(
        str(l.get("origen", "")).startswith("datamatrix") for l in lecturas)
    conflictos = sorted({v for l in lecturas for v in (l.get("conflicto") or [])})
    # P42 · una decodificación de DataMatrix sin conflicto vale por sí sola: el código lleva
    # corrección de errores. Con dos valores distintos en la misma foto, no.
    if del_codigo and not conflictos:
        minimo = 1
    apoyo = consenso.get("apoyo", 0) if not consenso.get("posiciones_dudosas") else 0
    if consenso.get("exenta"):
        return motivos + [f"exenta por la regla «{consenso['exenta']}»"] if motivos else []
    if max(consenso["votos"], apoyo) < minimo:
        motivos.append(f"{consenso['votos']} lectura(s) iguales de {len(lecturas)}"
                       + (f" (apoyo por posición {apoyo})" if apoyo else "")
                       + f"; hacen falta {minimo}")
    if conflictos:
        motivos.append("dos códigos distintos en la misma foto: " + ", ".join(conflictos))
    # la duda que declaró el lector (cola con símbolos, forma rara, símbolo equivocado)
    dudosas = [l for l in lecturas if l.get("dudoso")]
    if dudosas:
        clases = sorted({str(l.get("clase_cola")) for l in dudosas if l.get("clase_cola")})
        colas = sorted({str(l.get("cola_cruda")) for l in dudosas if l.get("cola_cruda")})
        detalle = []
        if clases:
            detalle.append("clase " + "/".join(clases))
        if colas:
            detalle.append("cola cruda " + ", ".join(colas))
        motivos.append("el dato decodificado no tiene la forma esperada"
                       + (f" ({'; '.join(detalle)})" if detalle else ""))
    if campo == "dashboard_serial_number" and not del_codigo \
            and str(consenso["valor"])[-1:].isdigit():
        motivos.append("la serie termina en dígito (posible carácter de control)")
    if consenso["dudoso"] and len(lecturas) > 1:
        distintas = Counter(str(l["valor"]) for l in lecturas if l.get("valor"))
        detalle = ", ".join(f"«{v}»×{n}" for v, n in distintas.most_common(4))
        posiciones = consenso.get("posiciones_dudosas") or []
        motivos.append("las lecturas discrepan" + (f" en las posiciones {posiciones}"
                                                   if posiciones else "") + f": {detalle}")
    return motivos


def fundir_caso(anterior: dict, nuevo: dict, campos_cerrados) -> dict:
    """Funde el resultado de un caso **por campo**. Pura.

    Los campos de `campos_cerrados` se toman de `nuevo` (y se borran sus restos viejos en las
    subclaves por campo); el resto de campos del caso se queda como estaba en `anterior`.
    """
    salida = {k: v for k, v in (anterior or {}).items()}
    for clave in ("caso", "caso_numero", "fotos", "fotos_con_pista"):
        if nuevo.get(clave) not in (None, ""):
            salida[clave] = nuevo[clave]
    for campo in campos_cerrados:
        salida.pop(campo, None)
        for sub in POR_CAMPO:
            if isinstance(salida.get(sub), dict):
                salida[sub] = {k: v for k, v in salida[sub].items() if k != campo}
        if campo in nuevo:
            salida[campo] = nuevo[campo]
        for sub in POR_CAMPO:
            if campo in (nuevo.get(sub) or {}):
                salida.setdefault(sub, {})
                salida[sub] = {**salida[sub], campo: nuevo[sub][campo]}
    for sub in POR_CAMPO:
        if sub in salida and not salida[sub]:
            del salida[sub]
    return salida


def cerrar(parcial: Path, json_path: Path, salida: Path) -> dict:
    """Paso 3: consenso por caso y escrito del JSON de evidencia (fundiendo por campo)."""
    acumulado = json.loads(parcial.read_text(encoding="utf-8"))
    resultados: dict[str, dict] = {}
    if json_path.exists():
        resultados = json.loads(json_path.read_text(encoding="utf-8"))
    for clave, registro in sorted(acumulado.items()):
        resultado = {"caso": registro.get("caso", ""), "caso_numero": clave,
                     "fotos": registro.get("fotos", 0),
                     "fotos_con_pista": registro.get("con_pista", 0)}
        cerrados = []
        for campo in CAMPOS:
            lecturas = (registro.get("lecturas") or {}).get(campo) or []
            descartadas = 0
            if campo == "dashboard_date":
                lecturas, descartadas = filtrar_fechas(lecturas)
                if descartadas and not lecturas:
                    # sólo había fechas del DataMatrix del módulo: el campo se CIERRA vacío y en
                    # duda (si no se cerrara, `fundir_caso` conservaría la fecha mala de antes)
                    cerrados.append(campo)
                    resultado[campo] = None
                    resultado.setdefault("dudoso", {})[campo] = True
                    resultado.setdefault("por_que_dudoso", {})[campo] = (
                        f"{descartadas} lectura(s) de fecha descartadas: venían del DataMatrix del "
                        f"módulo, no del sticker de la fecha")
                    continue
            if campo == "dashboard_part_number":
                # las lecturas de `grabado_banda_*` son del número impreso en la etiqueta del
                # **módulo** (`2GJ.880.204.J`): para el número moldeado del tablero no valen
                lecturas = [l for l in lecturas
                            if not str(l.get("origen", "")).startswith("grabado_banda")]
            # P42 · revisión de Astra (F6): el voto por posiciones fabrica valores (`R6E` + `R6E1`
            # → un valor que nadie leyó; `11/04` + `06/05` + `17/05` → `11/05`). Se vota **por
            # valor completo** en todos los campos, no sólo en la fecha.
            if campo == "dashboard_date":
                del_tablero = _solo_clase(lecturas)
                if len(del_tablero) == 1 and str(del_tablero[0].get("clase") or "") == "tablero":
                    # REGLA DEL USUARIO (2026-10-29): si en el caso hay **una sola** foto del
                    # sticker del tablero, esa lectura basta. Hay muchas fechas en un caso
                    # (proveedor, módulo, tablero) y no significan lo mismo; cuando la del
                    # tablero es única no hay con qué contradecirla, y su firma —hora + N/P—
                    # no la produce ninguna de las otras. Si hubiera dos o más, votan entre
                    # ellas: ahí sí hay algo que decidir.
                    consenso = {"valor": del_tablero[0]["valor"], "votos": 1,
                                "dudoso": False, "posiciones_dudosas": [],
                                "reparto": {del_tablero[0]["valor"]: 1},
                                "descartadas_por_largo": 0,
                                "exenta": "unica_foto_del_sticker_del_tablero"}
                else:
                    consenso = consensuar_completo(del_tablero, minimo=MINIMOS.get(campo, 2))
            else:
                consenso = consensuar_completo(lecturas, minimo=MINIMOS.get(campo, 2))
            if not consenso:
                continue
            cerrados.append(campo)
            resultado[campo] = consenso["valor"]
            resultado.setdefault("votos", {})[campo] = dict(
                Counter(str(l["valor"]) for l in lecturas).most_common(5))
            resultado.setdefault("confianza", {})[campo] = round(
                max(float(l.get("confianza") or 0) for l in lecturas), 2)
            # P37: ya no hay excepción para el número de parte. Lo que llega aquí ya lo decidió el
            # voto del caso en `leer_parte_por_parecido` y `agregar_parte` sólo deja pasar lo
            # publicado; si aun así las lecturas no concuerdan, es duda.
            motivos = motivos_de_duda(campo, consenso, lecturas)
            resultado.setdefault("dudoso", {})[campo] = bool(motivos)
            if motivos:
                resultado.setdefault("por_que_dudoso", {})[campo] = "; ".join(motivos)
            mejor = max(lecturas, key=lambda l: (str(l.get("clase") or "") == "tablero",
                                                 float(l.get("confianza") or 0)))
            capturas = sorted(salida.glob(f"{clave}_{campo}_*.jpg"))
            resultado.setdefault("fuente", {})[campo] = {
                "foto": mejor.get("foto", ""), "carpeta": mejor.get("carpeta", ""),
                "origen": mejor.get("origen", ""), "lecturas": len(lecturas),
                # P42 · revisión de Astra (F5): el valor **tal como se codificó/leyó** y el
                # payload original viajan hasta la hoja de trazabilidad.
                "valor_codificado": str(mejor.get("valor", "")),
                "texto": str(mejor.get("texto", ""))[:200],
                "cola_cruda": str(mejor.get("cola_cruda", "")),
                "clase_cola": str(mejor.get("clase_cola", "")),
                "payload_hex": str(mejor.get("payload_hex", ""))[:400],
                "formato": str(mejor.get("formato", "")),
                "version_decode": str(mejor.get("version_decode", "")),
                "conflicto": list(mejor.get("conflicto") or []),
                "posiciones_dudosas": consenso["posiciones_dudosas"],
                "descartadas_por_largo": consenso.get("descartadas_por_largo", 0),
                "descartadas_datamatrix": descartadas,
                "de_pestana_azul": sum(1 for l in lecturas if l.get("ancla") == "pestana_azul"),
                "captura": str(capturas[0]) if capturas else ""}
        resultados[clave] = fundir_caso(resultados.get(clave, {}), resultado, cerrados)

    json_path.write_text(json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")
    return resultados


def leer_cupos(texto: str) -> dict:
    """`codigo=5,etiqueta=5` → CUPOS con esos dos cambiados. Pura."""
    cupos = dict(CUPOS)
    for trozo in filter(None, (t.strip() for t in str(texto or "").split(","))):
        tipo, _, numero = trozo.partition("=")
        if tipo.strip() not in CUPOS:
            raise SystemExit(f"--cupos: tipo desconocido {tipo!r} (vale {', '.join(CUPOS)})")
        cupos[tipo.strip()] = int(numero)
    return cupos


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
    ap.add_argument("--cupos", default="",
                    help="paso 1: topes por tipo, p. ej. `codigo=5,etiqueta=5` (por defecto CUPOS)")
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
            numero = carpeta.name.split()[0]
            listas[numero] = lista_de_candidatas(carpeta, leer_cupos(args.cupos))
            print(f"  {numero}: {listas[numero]['fotos']} foto(s) · con pista "
                  f"{listas[numero]['con_pista']} · a leer {len(listas[numero]['elegidas'])}",
                  flush=True)
        Path(args.lista).write_text(json.dumps(listas, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
        return 0

    raise SystemExit("indique --lista, --rango o --cerrar")


if __name__ == "__main__":
    raise SystemExit(main())
