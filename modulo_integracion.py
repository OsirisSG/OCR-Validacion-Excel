"""P49 · Lector DEDICADO de la etiqueta del módulo (PAB) dentro de la corrida normal.

Hasta P48 la etiqueta del módulo sólo la leía el OCR genérico (EasyOCR en producción), que la
confunde: «Autolm B V», «GJ.880.204.J», la serie vertical sin leer. El proyecto ya tenía un
lector propio (`utilidades.codigos_modulo`: RapidOCR por líneas + consenso dentro de la
etiqueta + estampa amarilla del nivel), pero sólo lo usaban herramientas sueltas. Aquí entra al
flujo igual que el tablero P42.

Ganchos de la etiqueta (guía del usuario, 12/11):

    VW AG · Made in Mexico · T 2GJ 204 · 0589-P1-000678
    Airbag Module APM2/1 · Autoliv B.V. & Co. KG · Emmy-Noether-Str.7a · 85221 Dachau · GERMANY
    10.04.25 (fecha, junto al triángulo)            → module_date
    ZRZ 02S 2GJ 880 204 J (línea inferior)          → module_part_number (el «02S» NO es la
                                                       columna K: K sale de la estampa amarilla)
    «671 ZRZ0540011V» vertical junto al DataMatrix  → module_serial_number
    «Autoliv» o su dirección (Dachau/Noether/85221) → inflator_supplier = Autoliv

Sólo se leen fotos cuyo texto genérico ya muestra al menos dos ganchos (máximo configurable por
caso). Cada valor sale como candidato `etiqueta_modulo` con su foto y su caja: la consolidación y el
formulario de dudas lo tratan como cualquier otra evidencia. El nivel (estampa) nunca se publica
solo: se propone.
"""
from __future__ import annotations

import re
from pathlib import Path

VERSION = "p50-modulo-2"
GANCHOS = (
    ("airbag", re.compile(r"AIRBAG\s*MOD", re.I)),
    ("autoliv", re.compile(r"\bAUTOL(?:IV|[IVLMN1|]{1,2})", re.I)),
    ("direccion", re.compile(r"DACHAU|NOETHER|85221", re.I)),
    ("zrz", re.compile(r"ZRZ", re.I)),
    ("np", re.compile(r"2GJ[\s.]*880", re.I)),
    ("vwag", re.compile(r"\bVW\s*AG\b", re.I)),
    ("mexico", re.compile(r"MADE\s*IN\s*MEX", re.I)),
    ("prototipo", re.compile(r"PROTOTYP", re.I)),
)
AUTOLIV_EN_ETIQUETA = re.compile(r"\bAUTOL(?:IV|[IVLMN1|]{1,2})(?:\b|(?=B\.?\s*V))|DACHAU|NOETHER|85221",
                                 re.I)
FUERZA_CONFIANZA = {"confirmado_por_dos": 0.95, "repetido_junto": 0.9, "una_sola_lectura": 0.85}


def ganchos(texto: str) -> list[str]:
    return [nombre for nombre, patron in GANCHOS if patron.search(texto or "")]


def elegir_fotos(fotos: list[dict], textos: dict[str, str], maximo: int = 6) -> list[dict]:
    """Fotos con ≥2 ganchos de la etiqueta del módulo, las de más ganchos primero."""
    puntuadas = []
    for foto in fotos:
        rel = str(foto.get("ruta_relativa") or "")
        n = len(ganchos(textos.get(rel, "")))
        if n >= 2:
            puntuadas.append((-n, rel, foto))
    return [foto for _, _, foto in sorted(puntuadas, key=lambda t: (t[0], t[1]))[:maximo]]


def _clave(texto) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(texto or "").upper())


def _caja_de(lineas: list[dict], valor, original=None):
    for buscado in (_clave(original), _clave(valor)):
        if len(buscado) < 3:
            continue
        for linea in lineas:
            if buscado in _clave(linea.get("texto")) and linea.get("caja"):
                c = linea["caja"]
                return [int(c["x"]), int(c["y"]), int(c["w"]), int(c["h"])]
    return None


class LectorModulo:
    """Adaptador del lector real (las pruebas lo sustituyen por uno sintético)."""

    def leer(self, ruta: str) -> dict:
        import buscar_mas as B
        from utilidades import codigos_modulo as CM
        imagen = B.cargar_foto(Path(ruta))
        if imagen is None:
            raise ValueError("no se pudo abrir la foto")
        lineas = CM.lineas_con_caja(imagen)
        campos = CM.leer_etiqueta_modulo(lineas, None)        # sin «lo aprendido»: nada inferido
        salida = {k: v for k, v in campos.items() if k in (
            "part_number", "serial_number", "date", "fuerza", "discrepancias", "apariciones",
            "es_modulo", "prototipo", "nivel_texto_candidato")}
        salida["lineas"] = [{"texto": l.get("texto"), "caja": l.get("caja") or {}} for l in lineas]
        if campos.get("es_modulo") or campos.get("prototipo"):
            # P50 · la estampa (01S/66K/69K) también va en la etiqueta de PROTOTIPO
            estampa = CM.leer_estampa_nivel(imagen)
            if estampa:
                salida["estampa"] = {"nivel": estampa["nivel"], "confianza": round(float(estampa["confianza"]), 2),
                                     "texto": estampa.get("texto"), "giro": estampa.get("giro")}
        return salida


def candidatos_de_lectura(caso: dict, foto: dict, lectura: dict, ganchos_foto=()) -> list[dict]:
    if not (lectura.get("es_modulo") or lectura.get("prototipo")):
        return []
    lineas = lectura.get("lineas") or []
    texto = " ".join(str(l.get("texto") or "") for l in lineas)
    fuerza = lectura.get("fuerza") or {}
    discrepantes = {d.get("campo"): d for d in lectura.get("discrepancias") or []}
    salida = []

    def agregar(clave, valor, original, regla, confianza, **extra):
        salida.append({
            "proyecto": caso.get("project_id"), "etapa": caso.get("tipo_st"),
            "caso": caso.get("case_key"), "componente": "bolsa_aire", "clave": clave,
            "valor_original": str(original or valor)[:120], "valor_normalizado": valor,
            "fuente": "etiqueta_modulo", "imagen": foto.get("ruta_relativa"),
            "imagen_absoluta": foto.get("ruta"),
            "bbox_original": _caja_de(lineas, valor, original), "orientacion_grados": 0,
            "transformaciones": [], "fase": foto.get("fase"), "tor": None,
            "confianza_ocr": confianza, "valido_catalogo": True, "valido_regex": True,
            "regla_aplicada": regla, "confirmacion_manual": False,
            # P50 · si la foto muestra la etiqueta PROTOTYPES, lo que se lea ahí es «prototipo»: la
            # regla del usuario da prioridad a la etiqueta del módulo cuando discrepan
            "etiqueta": "prototipo" if (lectura.get("prototipo") or "prototipo" in ganchos_foto) else "modulo",
            "version_procesamiento": VERSION, **extra})

    for campo, clave in (("part_number", "module_part_number"), ("serial_number", "module_serial_number"),
                         ("date", "module_date")):
        if campo in discrepantes:
            for valor in discrepantes[campo].get("valores") or []:
                agregar(clave, valor, valor, "etiqueta_modulo_discrepancia_interna", 0.6,
                        requiere_confirmacion_manual=True,
                        motivo_p42="los dos códigos de la etiqueta no dicen lo mismo")
            continue
        valor = lectura.get(campo)
        if valor:
            original = None
            if campo == "date":                     # el texto tal como está impreso (10.04.25)
                for l in lineas:
                    if re.fullmatch(r"\s*\d{1,2}[./]\d{1,2}[./]\d{2,4}\s*", str(l.get("texto") or "")):
                        original = l.get("texto")
                        break
            agregar(clave, valor, original, f"etiqueta_modulo_dedicada:{fuerza.get(campo, 'una_sola_lectura')}",
                    FUERZA_CONFIANZA.get(fuerza.get(campo), 0.85))
    marca = AUTOLIV_EN_ETIQUETA.search(texto)
    if marca:
        agregar("inflator_supplier", "Autoliv", marca.group(),
                "proveedor_por_marca_o_direccion_etiqueta_modulo", 0.95)
    estampa = lectura.get("estampa") or {}
    if estampa.get("nivel"):
        agregar("engineering_level", estampa["nivel"], estampa.get("texto") or estampa["nivel"],
                "nivel_estampa_amarilla", float(estampa.get("confianza") or 0.5),
                motivo_p42="nivel de la estampa amarilla (no el «ZRZ 02S» impreso)")
    return salida


def _fotos_por_protocolo(fotos: list[dict], textos: dict[str, str], maximo: int, rescate: int):
    """P50 · protocolos en cascada: si uno no encuentra la etiqueta, se pasa al siguiente.

    1. fotos con ≥2 ganchos de la etiqueta (las más claras);
    2. fotos con 1 gancho (EasyOCR a veces sólo ve «ZRZ» o «Dachau»);
    3. fotos VOR sin ganchos (la etiqueta se fotografía antes de la prueba), hasta `rescate`.
    """
    puntos = {str(f.get("ruta_relativa") or ""): len(ganchos(textos.get(str(f.get("ruta_relativa") or ""), "")))
              for f in fotos}
    orden = lambda f: (-puntos[str(f.get("ruta_relativa") or "")], str(f.get("ruta_relativa") or ""))  # noqa: E731
    primero = sorted([f for f in fotos if puntos[str(f.get("ruta_relativa") or "")] >= 2], key=orden)[:maximo]
    segundo = sorted([f for f in fotos if puntos[str(f.get("ruta_relativa") or "")] == 1], key=orden)[:maximo]
    tercero = sorted([f for f in fotos if puntos[str(f.get("ruta_relativa") or "")] == 0
                      and ("VOR" in str(f.get("fase") or "").upper()
                           or "/VOR/" in "/" + str(f.get("ruta_relativa") or "").upper())],
                     key=orden)[:rescate]
    return (("ganchos_2", primero), ("ganchos_1", segundo), ("vor_sin_ganchos", tercero))


def procesar_caso_modulo(caso: dict, fotos: list[dict], textos: dict[str, str], *,
                         maximo_fotos: int = 6, lector=None, cache=None, control=None,
                         maximo_rescate: int = 6) -> dict:
    lector = lector or LectorModulo()
    candidatos, lecturas, alertas, desde_cache = [], [], [], 0
    protocolos_usados, elegidas_total = [], 0
    for protocolo, elegidas in _fotos_por_protocolo(fotos, textos, maximo_fotos, maximo_rescate):
        if not elegidas:
            continue
        protocolos_usados.append(protocolo)
        encontro = False
        for foto in elegidas:
            if control:
                control()
            elegidas_total += 1
            rel = str(foto.get("ruta_relativa") or "")
            huella = cache.huella_archivo(foto.get("ruta")) if cache is not None else None
            lectura = cache.obtener(huella, "modulo2") if huella else None
            if lectura is not None:
                desde_cache += 1
            else:
                try:
                    lectura = lector.leer(str(foto.get("ruta")))
                except Exception as exc:                          # noqa: BLE001
                    alertas.append({"codigo": "MODULO_ERROR_LECTURA", "nivel": "warning", "imagen": rel,
                                    "mensaje": f"{type(exc).__name__}: {exc}"[:200]})
                    continue
                if huella:
                    cache.guardar(huella, "modulo2", lectura)
            nuevos = candidatos_de_lectura(caso, foto, lectura, ganchos(textos.get(rel, "")))
            candidatos.extend(nuevos)
            encontro = encontro or bool(lectura.get("es_modulo"))
            lecturas.append({"foto": rel, "protocolo": protocolo, "ganchos": ganchos(textos.get(rel, "")),
                             "es_modulo": bool(lectura.get("es_modulo")),
                             "prototipo": bool(lectura.get("prototipo")),
                             "estampa": (lectura.get("estampa") or {}).get("nivel"),
                             "valores": {c["clave"]: c["valor_normalizado"] for c in nuevos}})
        if encontro:
            break                                         # la etiqueta ya apareció: no hace falta seguir
    return {"version": VERSION, "fotos_elegidas": elegidas_total, "desde_cache": desde_cache,
            "protocolos": protocolos_usados, "lecturas": lecturas, "candidatos": candidatos,
            "alertas": alertas}
