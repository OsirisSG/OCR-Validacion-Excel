"""Lectura de las etiquetas del tablero y del módulo con las **anclas** de la guía (P18).

Flujo por foto, tal como pide la guía:

1. **¿qué etiqueta es?** — `tablero_anclas.que_es()` la clasifica por color/forma:
   pestaña **azul** → fecha de fabricación del tablero; **estampa redonda de color** (rosa) →
   nivel de ingeniería; **DataMatrix con texto vertical** → código del tablero.
2. **se recorta la etiqueta** alrededor del ancla (`recorte_etiqueta`).
3. **se lee** con el motor intercambiable (`lector_etiquetas`: RapidOCR o el `ocr_engine` del
   usuario) probando la imagen tal cual y realzada para texto grabado.
4. **se interpreta** con la gramática de cada campo (fecha `DD/MM/AAAA`, nivel `03S`,
   parte `2GJ.857.003.G`, serie `052 3KVJ008R52V`, serie del módulo `671 ZRZ0539985G`).
5. **se corrobora** módulo contra tablero: «Usar el Module para corroborar la información del
   tablero» (guía, pág. 5).
6. lo que no se puede leer o queda a medias **no se inventa**: se devuelve como duda con el
   recorte al lado (por ejemplo, el último carácter de la serie del tablero).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from utilidades import lector_etiquetas as L
from utilidades.tablero_anclas import Ancla, que_es, recorte_etiqueta

CAMPOS_TABLERO = ("dashboard_date", "dashboard_engineering_level", "dashboard_part_number",
                  "dashboard_serial_number", "dashboard_supplier")
CAMPOS_MODULO = ("engineering_level", "module_part_number", "module_date", "module_serial_number",
                 "inflator_supplier")
ANCLA_DE_CAMPO = {
    "dashboard_date": "pestana_azul",
    "dashboard_engineering_level": "estampa_color",
    "dashboard_part_number": "codigo_cuadrado",
    "dashboard_serial_number": "codigo_cuadrado",
}
# qué campo de la guía corresponde a cada combinación (contenido leído, ancla)
ASIGNACION = {
    ("date", "pestana_azul"): "dashboard_date",
    ("date", "codigo_cuadrado"): "dashboard_date",
    ("date", "texto_vertical"): "module_date",
    ("engineering_level", "estampa_color"): "dashboard_engineering_level",
    ("engineering_level", "etiqueta_modulo"): "engineering_level",
    ("part_number", "codigo_cuadrado"): "dashboard_part_number",
    ("part_number", "texto_vertical"): "module_part_number",
    ("dashboard_serial_number", "codigo_cuadrado"): "dashboard_serial_number",
    ("serial_number", "texto_vertical"): "module_serial_number",
    ("supplier", "etiqueta_modulo"): "inflator_supplier",
    ("supplier", "codigo_cuadrado"): "dashboard_supplier",
}


@dataclass
class Prueba:
    campo: str
    valor: str
    confianza: float
    archivo: str
    ancla: str
    recorte: str = ""
    origen: str = ""
    dudoso: bool = False
    nota: str = ""

    def as_dict(self) -> dict:
        return {"campo": self.campo, "valor": self.valor, "confianza": round(self.confianza, 3),
                "archivo": self.archivo, "ancla": self.ancla, "recorte": self.recorte,
                "origen": self.origen, "dudoso": self.dudoso, "nota": self.nota}


@dataclass
class Resultado:
    campos: dict[str, dict] = field(default_factory=dict)
    dudas: list[dict] = field(default_factory=list)
    pruebas: list[Prueba] = field(default_factory=list)
    corroboracion: dict = field(default_factory=dict)
    fotos: int = 0
    fotos_con_lectura: int = 0


def _es_etiqueta_de_modulo(lectura) -> bool:
    """La etiqueta del módulo se reconoce por su contenido: `VW AG`, `Made in…`, `Airbag Module`,
    `Autoliv`. Es más fiable que el color, que a veces confunde una zona blanca con la pestaña."""
    texto = " ".join(t for t, _ in lectura.lineas).upper()
    pistas = ("VW", "MADE", "MEXICO", "AIRBA", "AUTOLIV", "PROTOTYPES", "PN CUST")
    return ("ZRZ" in texto) or sum(1 for pista in pistas if pista in texto) >= 2


def _campo_de(campo_leido: str, ancla: str) -> str | None:
    return ASIGNACION.get((campo_leido, ancla))


def _parece_grabado(imagen) -> bool:
    """¿Hay dos líneas finas claras sobre oscuro? Es la firma del número grabado.

    Arriba va el número de molde (`4148399X`) y **abajo el número de parte**, que es el que usa el
    libro (lo confirmó el usuario).
    """
    bandas = L.bandas_con_columnas(imagen)
    finas = [b for b in bandas if 10 <= (b[0][1] - b[0][0]) <= 70 and (b[1][1] - b[1][0]) >= 30]
    return len(finas) >= 2


def leer_fotos(rutas, motor=None, carpeta_evidencia: Path | None = None,
               caso: str = "", catalogo=None) -> Resultado:
    """`catalogo` son los números de parte que el libro ya conoce (para el texto grabado)."""
    motor = motor if motor is not None else L.motor_disponible()
    resultado = Resultado()
    votos: dict[str, Counter] = {}
    pruebas_por_campo: dict[str, list[Prueba]] = {}
    for ruta in rutas:
        ruta = Path(ruta)
        imagen = cv2.imread(str(ruta))
        if imagen is None:
            continue
        resultado.fotos += 1
        alto, ancho = imagen.shape[:2]
        if max(alto, ancho) > 1600:                     # el OCR no necesita 12 MP
            factor = 1600 / max(alto, ancho)
            imagen = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
        resumen = que_es(imagen)
        anclas = resumen.get("anclas") or []
        tipos = [a["tipo"] for a in anclas] or ["sin_ancla"]
        lectura, campos = L.leer_con_giros(imagen, motor, modos=("original", "auto"),
                                           catalogo=catalogo)
        if lectura.lineas:
            resultado.fotos_con_lectura += 1
        # el número grabado en el plástico no lo lee el OCR: se busca aparte y, si no sale, se
        # propone el catálogo del libro con el recorte al lado (la decisión es del usuario)
        if catalogo and "dashboard_part_number" not in campos:
            grabado = L.leer_grabado(imagen, motor, catalogo=catalogo)
            if grabado and not grabado.get("dudoso"):
                campos["dashboard_part_number"] = {
                    "valor": grabado["valor"], "confianza": grabado.get("confianza", 0.0),
                    "origen": grabado.get("origen", ""), "reparado": True}
            elif grabado is not None or (not anclas and _parece_grabado(imagen)):
                resultado.dudas.append({
                    "campo": "dashboard_part_number", "motivo": "grabado_no_legible",
                    "valor": "", "imagen": "",
                    "detalle": ("El número va grabado en el plástico y el OCR no lo lee con "
                                f"seguridad (leyó «{(grabado or {}).get('origen', 'nada')}»). La etiqueta de "
                                "abajo es la buena; arriba va el número de molde."),
                    "opciones": [{"valor": c, "fuente": "catalogo",
                                  "detalle": "número de parte del catálogo del libro"}
                                 for c in catalogo] +
                                [{"valor": None, "fuente": "vacio", "detalle": "dejar vacío"}],
                })
        de_modulo = _es_etiqueta_de_modulo(lectura)
        for campo_leido, dato in campos.items():
            destino = None
            if de_modulo:
                # la etiqueta del módulo manda sobre el color: si no, su fecha se colaría en la
                # columna del tablero
                destino = {"date": "module_date", "part_number": "module_part_number",
                           "engineering_level": "engineering_level",
                           "serial_number": "module_serial_number",
                           "supplier": "inflator_supplier"}.get(campo_leido)
            if destino is None:
                for tipo in tipos:
                    destino = _campo_de(campo_leido, tipo) or destino
            if destino is None and campo_leido in ("date",):
                destino = "dashboard_date" if "pestana_azul" in tipos else "module_date"
            elif destino is None and campo_leido == "engineering_level":
                destino = "dashboard_engineering_level" if "estampa_color" in tipos else "engineering_level"
            elif destino is None and campo_leido == "part_number":
                destino = "dashboard_part_number" if "codigo_cuadrado" in tipos else "module_part_number"
            elif destino is None:
                continue
            recorte = ""
            if carpeta_evidencia is not None and anclas:
                principal = Ancla(anclas[0]["tipo"], tuple(anclas[0]["caja"]), anclas[0]["area"])
                trozo = recorte_etiqueta(imagen, principal)
                if trozo is not None and trozo.size:
                    carpeta_evidencia.mkdir(parents=True, exist_ok=True)
                    archivo = carpeta_evidencia / f"{caso or 'caso'}_{destino}_{ruta.stem}.png"
                    cv2.imwrite(str(archivo), trozo)
                    recorte = str(archivo)
            prueba = Prueba(destino, str(dato["valor"]), float(dato.get("confianza", 0)),
                            str(ruta), tipos[0], recorte, str(dato.get("origen", "")),
                            bool(dato.get("dudoso", False)))
            resultado.pruebas.append(prueba)
            pruebas_por_campo.setdefault(destino, []).append(prueba)
            votos.setdefault(destino, Counter())[prueba.valor] += 1
    for campo, contador in votos.items():
        valor, cuantos = contador.most_common(1)[0]
        pruebas = [p for p in pruebas_por_campo.get(campo, []) if p.valor == valor]
        dudoso = any(p.dudoso for p in pruebas)
        recorte = next((p.recorte for p in pruebas if p.recorte), "")
        resultado.campos[campo] = {
            "valor": valor, "votos": cuantos, "fotos": resultado.fotos,
            "confianza": round(max((p.confianza for p in pruebas), default=0.0), 3),
            "dudoso": dudoso, "recorte": recorte, "ancla": pruebas[0].ancla if pruebas else "",
            "origen": pruebas[0].origen if pruebas else "",
        }
        if dudoso:
            resultado.dudas.append({
                "campo": campo, "motivo": "etiqueta_dudosa", "valor": valor,
                "detalle": ("el último carácter del código no se lee con seguridad "
                            f"(leído {valor!r} de «{pruebas[0].origen}»)" if campo.endswith("serial_number")
                            else "la lectura es dudosa"),
                "imagen": recorte,
                "opciones": [{"valor": valor, "fuente": "etiqueta", "detalle": "usar la lectura"},
                             {"valor": None, "fuente": "vacio", "detalle": "dejar vacío"}],
            })
    # una duda por campo (varias fotos pueden disparar la misma)
    unicas: dict[str, dict] = {}
    for duda in resultado.dudas:
        clave = duda["campo"]
        if clave in unicas:
            unicas[clave]["fotos"] = unicas[clave].get("fotos", 1) + 1
            continue
        unicas[clave] = dict(duda, fotos=1)
    resultado.dudas = list(unicas.values())

    # regla de la guía: el módulo corrobora al tablero
    modulo = {c: resultado.campos[c] for c in CAMPOS_MODULO if c in resultado.campos}
    tablero = {c: resultado.campos[c] for c in CAMPOS_TABLERO if c in resultado.campos}
    resultado.corroboracion = L.corroborar(
        {k.replace("module_", "").replace("engineering", "engineering"): v for k, v in modulo.items()},
        {k.replace("dashboard_", ""): v for k, v in tablero.items()})
    return resultado


def campos_disponibles() -> tuple[str, ...]:
    return tuple(CAMPOS_TABLERO + CAMPOS_MODULO)
