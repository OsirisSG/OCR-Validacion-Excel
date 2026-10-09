"""Uniones humanas reversibles, separadas del OCR bruto y del entrenamiento.

V14.13 añade geometría flexible: una edición puede conservar un cuadrilátero
(polígono de cuatro esquinas) además de su bbox envolvente. La bbox mantiene
compatibilidad con datos anteriores; el polígono se usa para decidir qué
bloques están realmente dentro de la selección y para generar recortes limpios.
"""
import hashlib
import json
from copy import deepcopy


def interseca(a, b):
    return bool(a and b and min(a[0]+a[2], b[0]+b[2]) > max(a[0], b[0])
                and min(a[1]+a[3], b[1]+b[3]) > max(a[1], b[1]))


def _punto_en_poligono(punto, poligono):
    """Ray casting sencillo para un cuadrilátero convexo/no auto-cruzado."""
    x, y = float(punto[0]), float(punto[1])
    dentro = False
    pts = [(float(px), float(py)) for px, py in (poligono or [])]
    if len(pts) != 4:
        return False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        cruza = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        )
        if cruza:
            dentro = not dentro
        j = i
    return dentro


def _orientacion(a, b, c):
    return (float(b[0])-float(a[0]))*(float(c[1])-float(a[1])) - (float(b[1])-float(a[1]))*(float(c[0])-float(a[0]))


def _segmentos_intersectan(a, b, c, d):
    eps = 1e-8
    o1, o2 = _orientacion(a,b,c), _orientacion(a,b,d)
    o3, o4 = _orientacion(c,d,a), _orientacion(c,d,b)
    if ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps)):
        return True
    return False


def interseca_poligono_bbox(poligono, bbox):
    """Intersección entre cuadrilátero y bbox sin depender de OpenCV."""
    if not poligono or len(poligono) != 4 or not bbox or len(bbox) != 4:
        return False
    x, y, w, h = [float(v) for v in bbox]
    rect = [(x,y), (x+w,y), (x+w,y+h), (x,y+h)]
    if any(_punto_en_poligono(p, poligono) for p in rect):
        return True
    if any(x <= float(px) <= x+w and y <= float(py) <= y+h for px,py in poligono):
        return True
    aristas_p = list(zip(poligono, poligono[1:]+poligono[:1]))
    aristas_r = list(zip(rect, rect[1:]+rect[:1]))
    return any(_segmentos_intersectan(a,b,c,d) for a,b in aristas_p for c,d in aristas_r)


def interseca_region(bbox_region, bbox_unidad, poligono=None):
    return interseca_poligono_bbox(poligono, bbox_unidad) if poligono else interseca(bbox_region, bbox_unidad)


def validar_caja(b, dimensiones):
    if (len(b) != 4 or len(dimensiones) != 2 or min(b[:2]) < 0
            or min(b[2:]) < 2 or b[0]+b[2] > dimensiones[0]
            or b[1]+b[3] > dimensiones[1]):
        raise ValueError("La región queda fuera de la imagen o es demasiado pequeña.")


def unidades(ocr):
    return ocr.get("lineas_texto") or ocr.get("tokens") or []


def unidades_en_region(ocr, bbox, poligono=None):
    return [u for u in unidades(ocr) if interseca_region(bbox, u.get("bbox"), poligono)]


def expandir(bbox, ocr):
    """No partir unidades existentes: cerrar transitivamente la selección rectangular."""
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
        poligono TEXT,
        activo INTEGER NOT NULL DEFAULT 1, creado TEXT DEFAULT CURRENT_TIMESTAMP)""")
    columnas = {fila[1] for fila in con.execute("PRAGMA table_info(ediciones_zona)")}
    if "poligono" not in columnas:
        con.execute("ALTER TABLE ediciones_zona ADD COLUMN poligono TEXT")
    con.execute("""CREATE TABLE IF NOT EXISTS ediciones_zona_detalle (
        edicion_id INTEGER PRIMARY KEY, contenido TEXT NOT NULL)""")


def _cargar_poligono(valor):
    if not valor:
        return None
    try:
        puntos = json.loads(valor) if isinstance(valor, str) else valor
        if isinstance(puntos, list) and len(puntos) == 4:
            return puntos
    except Exception:
        pass
    return None


def uniones_activas(con, imagen_hash, ocr):
    """Devuelve uniones simples activas del marco OCR vigente."""
    tabla(con)
    filas = con.execute("""
        SELECT e.id, e.bbox, e.texto, e.poligono, e.creado
        FROM ediciones_zona e
        LEFT JOIN ediciones_zona_detalle d ON d.edicion_id=e.id
        WHERE e.imagen_hash=? AND e.marco=? AND e.activo=1
          AND d.edicion_id IS NULL
        ORDER BY e.id
    """, (imagen_hash, marco(ocr or {}))).fetchall()
    salida = []
    for fila in filas:
        try:
            bbox = json.loads(fila["bbox"] if hasattr(fila, "keys") else fila[1])
        except Exception:
            continue
        if hasattr(fila, "keys"):
            identificador, texto, poligono, creado = fila["id"], fila["texto"], fila["poligono"], fila["creado"]
        else:
            identificador, texto, poligono, creado = fila[0], fila[2], fila[3], fila[4]
        salida.append({"id": identificador, "bbox": bbox,
                       "poligono": _cargar_poligono(poligono),
                       "texto": texto, "creado": creado})
    return salida


def guardar_bloque(con, imagen_hash, ocr, origen, regiones):
    """Reemplaza exactamente una unidad por una o dos, con geometría flexible."""
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
        # Dos bbox pueden solaparse aunque los cuadriláteros no. Sólo se rechaza
        # cuando no existe geometría flexible suficiente para distinguirlas.
        p0, p1 = regiones[0].get("poligono"), regiones[1].get("poligono")
        if not p0 or not p1:
            raise ValueError("Las dos regiones deben estar separadas, sin solaparse.")
    identificador = guardar(con, imagen_hash, ocr, origen, coincidencias[0].get("texto") or " ")
    con.execute("INSERT INTO ediciones_zona_detalle VALUES (?,?)",
                (identificador, json.dumps({"origen": origen, "regiones": regiones})))
    return identificador


def guardar(con, imagen_hash, ocr, bbox, texto, poligono=None):
    tabla(con)
    validar_caja(bbox, ocr.get("dimensiones") or [])
    if not texto.strip() or len(texto) > 8192:
        raise ValueError("Escribe entre 1 y 8192 caracteres.")
    poligono_json = json.dumps(poligono) if poligono else None
    return con.execute("INSERT INTO ediciones_zona(imagen_hash,marco,bbox,texto,poligono) VALUES(?,?,?,?,?)",
                       (imagen_hash, marco(ocr), json.dumps(bbox), texto, poligono_json)).lastrowid


def deshacer(con, imagen_hash, ocr):
    tabla(con)
    fila = con.execute("SELECT id FROM ediciones_zona WHERE imagen_hash=? AND marco=? AND activo=1 ORDER BY id DESC LIMIT 1",
                       (imagen_hash, marco(ocr))).fetchone()
    if fila:
        con.execute("UPDATE ediciones_zona SET activo=0 WHERE id=?", (fila[0],))
    return bool(fila)


def aplicar(con, imagen_hash, ocr):
    tabla(con)
    ocr = ocr or {}
    salida = deepcopy(ocr.get("_antes_ediciones_zona", ocr))
    filas = con.execute("SELECT id,bbox,texto,poligono FROM ediciones_zona WHERE imagen_hash=? AND marco=? AND activo=1 ORDER BY id",
                        (imagen_hash, marco(salida))).fetchall()
    if not filas:
        return salida
    original = deepcopy(salida)
    for clave in ("tokens", "lineas_texto", "codigos_detectados"):
        if salida.get(clave) is None:
            salida[clave] = []
    for identificador, caja, texto, poligono_json in filas:
        detalle = con.execute("SELECT contenido FROM ediciones_zona_detalle WHERE edicion_id=?", (identificador,)).fetchone()
        if detalle:
            cambio = json.loads(detalle[0])
            lista = unidades(salida)
            indices = [i for i,u in enumerate(lista) if list(u.get("bbox") or []) == cambio["origen"]]
            if len(indices) != 1:
                continue
            nuevas = []
            for r in cambio["regiones"]:
                u = {"texto": r["texto"], "bbox": r["bbox"], "confianza": None,
                     "edicion_zona": identificador, "origen": "geometria_manual",
                     "correccion_confirmada": True}
                if r.get("poligono"):
                    u["poligono_lectura"] = r["poligono"]
                nuevas.append(u)
            i = indices[0]
            salida["lineas_texto"] = lista[:i] + nuevas + lista[i+1:]
            salida["tokens"] = deepcopy(salida["lineas_texto"])
            salida["codigos_detectados"] = [u for u in (salida.get("codigos_detectados") or [])
                                            if not interseca(cambio["origen"], u.get("bbox"))]
            continue
        b = json.loads(caja)
        poligono = _cargar_poligono(poligono_json)
        for clave in ("tokens", "lineas_texto", "codigos_detectados"):
            salida[clave] = [u for u in (salida.get(clave) or [])
                             if not interseca_region(b, u.get("bbox"), poligono)]
        u = {"texto": texto, "bbox": b, "confianza": 1.0,
             "unidad_id": f"zona-{identificador}", "edicion_zona": identificador,
             "origen": "union_manual", "correccion_confirmada": True}
        if poligono:
            u["poligono_lectura"] = poligono
        salida["tokens"].append(deepcopy(u))
        salida["lineas_texto"].append(u)
    salida["texto_completo"] = "\n".join(str(u.get("texto", "")) for u in unidades(salida))
    salida["ediciones_zona"] = [f[0] for f in filas]
    salida["_antes_ediciones_zona"] = original
    return salida
