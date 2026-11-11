"""Enganche de las anclas del tablero al flujo del libro (Fase 3, P14).

Flujo completo, foto a foto:

1. **¿Qué es esta foto?** — `tablero_anclas.que_es()` la clasifica por color/forma
   (pestaña azul = fecha, estampa de color = nivel, DataMatrix = código).
2. **Se recorta la etiqueta** alrededor del ancla y se guarda como evidencia (para que en la
   página de dudas se vea la imagen al lado del campo).
3. **Se lee** el recorte: si hay motor OCR disponible, con sus variantes de orientación
   (tal cual, 180°, con la letra delante); si no, el campo queda como duda `requiere_lectura`.
4. **Se valida con el protocolo** del campo correspondiente del tablero.
5. **Se decide**: valor con mayoría entre fotos, o duda con la imagen al lado.

Nada se escribe aquí: el módulo produce *propuestas* y *dudas*. Escribir es cosa de
`rescatar_libro`/`constantes`, que ya respetan «nunca sobrescribir».
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from utilidades.protocolo_campos import GRAMATICAS, evaluar
from utilidades.tablero_anclas import (Ancla, CAMPO_POR_ANCLA, normalizar_giro, que_es,
                                       recorte_etiqueta)

EXTENSIONES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".JPG", ".JPEG", ".PNG"}

DONDE_MIRAR = {
    "dashboard_date": ["la etiqueta blanca con pestaña azul del tablero",
                       "la fecha impresa junto al número de parte"],
    "dashboard_engineering_level": ["la pegatina redonda de color del tablero",
                                     "si viene girada, el número va primero: 03S"],
    "dashboard_part_number": ["el DataMatrix con el texto vertical al lado",
                              "el último carácter es el que suele leerse mal"],
}


@dataclass
class Evidencia:
    campo: str
    archivo: str
    tipo_ancla: str
    caja: tuple[int, int, int, int]
    recorte: str = ""
    texto: str = ""
    estado: str = "sin_leer"
    nota: str = ""


@dataclass
class Propuesta:
    campo: str
    valor: str = ""
    estado: str = "sin_datos"
    votos: int = 0
    evidencias: list[Evidencia] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"campo": self.campo, "valor": self.valor, "estado": self.estado, "votos": self.votos,
                "evidencias": [{"archivo": e.archivo, "ancla": e.tipo_ancla,
                                "recorte": e.recorte, "texto": e.texto, "estado": e.estado}
                               for e in self.evidencias]}


def _leer(imagen, motor_ocr, campo: str) -> tuple[str, str, str]:
    """Lee el recorte probando orientaciones. Devuelve (texto, estado, nota)."""
    if motor_ocr is None:
        return "", "sin_leer", "no hay motor OCR disponible: se manda a dudas con la imagen"
    candidatos = []
    for giro in (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE):
        trozo = imagen if giro is None else cv2.rotate(imagen, giro)
        try:
            texto = motor_ocr(trozo) or ""
        except Exception:                                    # noqa: BLE001
            continue
        if texto.strip():
            candidatos.append(texto.strip())
    if not candidatos:
        return "", "sin_texto", "el motor no devolvió texto en ninguna orientación"

    valida = lambda c, t: evaluar(c, t).estado in ("valido", "reparado")   # noqa: E731
    for texto in candidatos:
        valor, como = normalizar_giro(texto, campo, valida)
        if como != "sin_corregir":
            return valor, "leido", f"leído {como}"
    return candidatos[0], "dudoso", "ninguna orientación dio un valor válido"


def analizar_fotos(rutas, motor_ocr=None, carpeta_evidencia: Path | None = None,
                   caso: str = "") -> dict[str, Propuesta]:
    """Clasifica y lee cada foto. Devuelve una propuesta por campo del tablero."""
    propuestas: dict[str, Propuesta] = {}
    for ruta in rutas:
        ruta = Path(ruta)
        if ruta.suffix not in EXTENSIONES:
            continue
        imagen = cv2.imread(str(ruta))
        if imagen is None:
            continue
        resumen = que_es(imagen)
        campo = resumen["campo"]
        if not campo:
            continue
        principal = resumen["anclas"][0]
        ancla = Ancla(principal["tipo"], tuple(principal["caja"]), principal["area"])
        recorte = recorte_etiqueta(imagen, ancla)
        destino = ""
        if carpeta_evidencia is not None and recorte.size:
            carpeta_evidencia.mkdir(parents=True, exist_ok=True)
            archivo = carpeta_evidencia / f"{caso or 'caso'}_{campo}_{ruta.stem}.png"
            cv2.imwrite(str(archivo), recorte)
            destino = str(archivo)
        texto, estado, nota = _leer(recorte, motor_ocr, campo)
        propuesta = propuestas.setdefault(campo, Propuesta(campo))
        propuesta.evidencias.append(Evidencia(campo, str(ruta), principal["tipo"],
                                              tuple(principal["caja"]), destino, texto, estado, nota))
    for propuesta in propuestas.values():
        leidos = [e for e in propuesta.evidencias if e.estado == "leido" and e.texto]
        if leidos:
            valor, veces = Counter(e.texto for e in leidos).most_common(1)[0]
            veredicto = evaluar(propuesta.campo, valor)
            propuesta.valor, propuesta.votos = veredicto.valor, veces
            propuesta.estado = "propuesto" if veredicto.escribible else "dudoso"
        elif propuesta.evidencias:
            propuesta.estado = "requiere_lectura"
    return propuestas


def a_dudas(caso: str, propuestas: dict[str, Propuesta]) -> list[dict]:
    """Convierte las propuestas en dudas con la imagen al lado, para la página."""
    salida = []
    for campo, propuesta in propuestas.items():
        if propuesta.estado == "propuesto":
            continue
        imagen = next((e.recorte for e in propuesta.evidencias if e.recorte), "")
        opciones = []
        if propuesta.valor:
            opciones.append({"valor": propuesta.valor, "fuente": "ocr",
                             "detalle": f"{propuesta.votos} foto(s) coinciden"})
        for evidencia in propuesta.evidencias:
            if evidencia.texto and evidencia.texto != propuesta.valor:
                opciones.append({"valor": evidencia.texto, "fuente": "ocr",
                                 "detalle": Path(evidencia.archivo).name})
        opciones.append({"valor": None, "fuente": "vacio", "detalle": "dejar vacío"})
        salida.append({
            "caso": caso, "campo": campo, "motivo": "tablero_" + propuesta.estado,
            "detalle": (f"{len(propuesta.evidencias)} foto(s) del tablero. "
                        f"{propuesta.evidencias[0].nota if propuesta.evidencias else ''}"),
            "opciones": opciones, "donde_mirar": DONDE_MIRAR.get(campo, []), "imagen": imagen})
    return salida


def campos_con_protocolo() -> list[str]:
    return [c for c in GRAMATICAS if c.startswith("dashboard_")]
