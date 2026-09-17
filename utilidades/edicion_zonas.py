"""Uniones humanas reversibles, separadas del OCR bruto y del entrenamiento."""
import hashlib
import json
from copy import deepcopy


def interseca(a, b):
    return bool(a and b and min(a[0]+a[2], b[0]+b[2]) > max(a[0], b[0])
                and min(a[1]+a[3], b[1]+b[3]) > max(a[1], b[1]))


def validar_caja(b, dimensiones):
    if (len(b) != 4 or len(dimensiones) != 2 or min(b[:2]) < 0
            or min(b[2:]) < 2 or b[0]+b[2] > dimensiones[0]
            or b[1]+b[3] > dimensiones[1]):
        raise ValueError("La región queda fuera de la imagen o es demasiado pequeña.")


def unidades(ocr):
    return ocr.get("lineas_texto") or ocr.get("tokens") or []


def expandir(bbox, ocr):
    """No partir unidades existentes: cerrar transitivamente la selección."""
    b = list(bbox)
    while True:
        anterior = b[:]
        for u in unidades(ocr):
            q = u.get("bbox")
            if interseca(b, q):
                x, y = min(b[0], q[0]), min(b[1], q[1])
                b = [x, y, max(b[0]+b[2], q[0]+q[2])-x,
                     max(b[1]+b[3], q[1]+q[3])-y]
        if b == anterior:
            return b


def marco(ocr):
    campos = ("dimensiones", "orientacion_texto_base_grados", "orientacion_base_grados",
              "orientacion_texto_grados", "orientacion_corregida_grados",
              "rotacion_manual_aplicada_grados", "orientacion_manual_prioritaria",
              "deskew_texto_aplicado_grados", "deskew_aplicado_grados")
    # El campo base puede añadirse durante la publicación. Derivar un marco canónico.
    manual = float(ocr.get("rotacion_manual_aplicada_grados") or 0)
    base = ocr.get(campos[1], ocr.get(campos[2]))
    if base is None:
        base = round((float(ocr.get(campos[3], ocr.get(campos[4], 0)) or 0)-manual)/90)*90
    return json.dumps([ocr.get("dimensiones"), float(base) % 360, manual,
                       bool(ocr.get("orientacion_manual_prioritaria")),
                       float(ocr.get("deskew_texto_aplicado_grados") or
                             ocr.get("deskew_aplicado_grados") or 0)])


def firma(ocr, imagen_hash):
    datos = [imagen_hash, marco(ocr), unidades(ocr), ocr.get("ediciones_zona", [])]
    return hashlib.sha256(json.dumps(datos, sort_keys=True, default=str).encode()).hexdigest()


def tabla(con):
    con.execute("""CREATE TABLE IF NOT EXISTS ediciones_zona (
        id INTEGER PRIMARY KEY AUTOINCREMENT, imagen_hash TEXT NOT NULL,
        marco TEXT NOT NULL, bbox TEXT NOT NULL, texto TEXT NOT NULL,
        activo INTEGER NOT NULL DEFAULT 1, creado TEXT DEFAULT CURRENT_TIMESTAMP)""")
    con.execute("""CREATE TABLE IF NOT EXISTS ediciones_zona_detalle (
        edicion_id INTEGER PRIMARY KEY, contenido TEXT NOT NULL)""")


def guardar_bloque(con, imagen_hash, ocr, origen, regiones):
    """Reemplaza exactamente una unidad por una o dos, sin absorber vecinas."""
    tabla(con)
    if len(regiones) not in (1, 2):
        raise ValueError("Confirma una región ajustada o dos regiones separadas.")
    coincidencias = [u for u in unidades(ocr) if list(u.get("bbox") or []) == origen]
    if len(coincidencias) != 1:
        raise ValueError("El bloque original cambió o es ambiguo. Selecciónalo nuevamente.")
    for r in regiones:
        validar_caja(r["bbox"], ocr.get("dimensiones") or [])
        if not r.get("texto", "").strip() or len(r["texto"]) > 8192:
            raise ValueError("Confirma el texto de cada región (1 a 8192 caracteres).")
    if len(regiones) == 2 and interseca(regiones[0]["bbox"], regiones[1]["bbox"]):
        raise ValueError("Las dos regiones deben estar separadas, sin solaparse.")
    identificador = guardar(con, imagen_hash, ocr, origen, coincidencias[0].get("texto") or " ")
    con.execute("INSERT INTO ediciones_zona_detalle VALUES (?,?)",
                (identificador, json.dumps({"origen": origen, "regiones": regiones})))
    return identificador


def guardar(con, imagen_hash, ocr, bbox, texto):
    tabla(con)
    validar_caja(bbox, ocr.get("dimensiones") or [])
    if not texto.strip() or len(texto) > 8192:
        raise ValueError("Escribe entre 1 y 8192 caracteres.")
    return con.execute("INSERT INTO ediciones_zona(imagen_hash,marco,bbox,texto) VALUES(?,?,?,?)",
                       (imagen_hash, marco(ocr), json.dumps(bbox), texto)).lastrowid


def deshacer(con, imagen_hash, ocr):
    tabla(con)
    fila = con.execute("SELECT id FROM ediciones_zona WHERE imagen_hash=? AND marco=? AND activo=1 ORDER BY id DESC LIMIT 1",
                       (imagen_hash, marco(ocr))).fetchone()
    if fila:
        con.execute("UPDATE ediciones_zona SET activo=0 WHERE id=?", (fila[0],))
    return bool(fila)


def aplicar(con, imagen_hash, ocr):
    tabla(con)
    salida = deepcopy(ocr.get("_antes_ediciones_zona", ocr))
    filas = con.execute("SELECT id,bbox,texto FROM ediciones_zona WHERE imagen_hash=? AND marco=? AND activo=1 ORDER BY id",
                        (imagen_hash, marco(salida))).fetchall()
    if not filas:
        return salida
    original = deepcopy(salida)
    for identificador, caja, texto in filas:
        detalle = con.execute("SELECT contenido FROM ediciones_zona_detalle WHERE edicion_id=?", (identificador,)).fetchone()
        if detalle:
            cambio = json.loads(detalle[0])
            lista = unidades(salida)
            indices = [i for i,u in enumerate(lista) if list(u.get("bbox") or []) == cambio["origen"]]
            if len(indices) != 1:
                continue  # No aplicar a un OCR reprocesado cuya geometría ya cambió.
            nuevas = [{"texto": r["texto"], "bbox": r["bbox"], "confianza": None,
                       "edicion_zona": identificador, "origen": "geometria_manual",
                       "correccion_confirmada": True} for r in cambio["regiones"]]
            i = indices[0]
            salida["lineas_texto"] = lista[:i] + nuevas + lista[i+1:]
            salida["tokens"] = deepcopy(salida["lineas_texto"])
            salida["codigos_detectados"] = [u for u in salida.get("codigos_detectados", [])
                                            if not interseca(cambio["origen"], u.get("bbox"))]
            continue
        b = json.loads(caja)
        for clave in ("tokens", "lineas_texto", "codigos_detectados"):
            salida[clave] = [u for u in salida.get(clave, []) if not interseca(b, u.get("bbox"))]
        u = {"texto": texto, "bbox": b, "confianza": 1.0,
             "unidad_id": f"zona-{identificador}", "edicion_zona": identificador,
             "origen": "union_manual", "correccion_confirmada": True}
        salida["tokens"].append(deepcopy(u))
        salida["lineas_texto"].append(u)
    salida["texto_completo"] = "\n".join(str(u.get("texto", "")) for u in unidades(salida))
    salida["ediciones_zona"] = [f[0] for f in filas]
    salida["_antes_ediciones_zona"] = original
    return salida
