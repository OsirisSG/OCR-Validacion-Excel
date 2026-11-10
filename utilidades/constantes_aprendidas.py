"""Constantes confirmadas una vez y aplicadas solas (Fase 1 del plan, P12).

Un proyecto es uno: el lugar de prueba, el motivo, el delay y el proveedor suelen ser los mismos
en los 10 casos y en los 200 futuros. En vez de que una persona los escriba 200 veces, se confirman
**una vez**, quedan guardados con su autor y su fecha, y a partir de ahí:

- se escriben solos en toda celda vacía de esa columna;
- **nunca** sobrescriben una celda ocupada;
- **no** se aplican al caso que tiene su propia lectura y contradice la constante: ése va a dudas
  con las dos versiones (una constante no puede tapar una excepción real);
- se pueden revocar, y queda registro de quién la confirmó.

Almacén: `aprendizaje/constantes_confirmadas.json` (texto plano, legible, versionable).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from utilidades.protocolo_campos import evaluar, limpiar

ALMACEN = Path("aprendizaje") / "constantes_confirmadas.json"


def _ruta(base: Path | None = None) -> Path:
    return (base or Path(".")) / ALMACEN


def cargar(base: Path | None = None) -> dict:
    ruta = _ruta(base)
    if not ruta.is_file():
        return {"version": 1, "constantes": {}}
    return json.loads(ruta.read_text(encoding="utf-8"))


def guardar(datos: dict, base: Path | None = None) -> Path:
    ruta = _ruta(base)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return ruta


def confirmar(campo: str, valor: str, autor: str = "operador", nota: str = "",
              base: Path | None = None, forzar: bool = False) -> dict:
    """Registra una constante. Rechaza valores que no cumplan el protocolo del campo."""
    veredicto = evaluar(campo, valor)
    if not veredicto.escribible and not forzar:
        raise ValueError(f"«{valor}» no vale como constante de {campo}: {veredicto.motivo}")
    datos = cargar(base)
    datos["constantes"][campo] = {"valor": limpiar(valor), "autor": autor, "nota": nota,
                                  "fecha": datetime.now().isoformat(timespec="seconds"),
                                  "protocolo": veredicto.motivo}
    guardar(datos, base)
    return datos["constantes"][campo]


def revocar(campo: str, base: Path | None = None) -> bool:
    datos = cargar(base)
    if campo not in datos["constantes"]:
        return False
    del datos["constantes"][campo]
    guardar(datos, base)
    return True


def proponer(lecturas: dict[str, dict], campos, minimo_casos: int = 3,
             cuota: float = 0.9) -> list[dict]:
    """Propone constantes a partir de lo que ya se leyó: un valor que domina en casi todos los casos.

    `lecturas` = {caso: {campo: {valor: votos}}}. No confirma nada: sólo propone, para que una
    persona lo acepte de un clic.
    """
    propuestas = []
    for campo in campos:
        valores: dict[str, int] = {}
        casos_con_dato = 0
        for datos in lecturas.values():
            votos = (datos.get("carpeta") or {})
            if campo in votos and votos[campo]:
                casos_con_dato += 1
                valores[limpiar(votos[campo])] = valores.get(limpiar(votos[campo]), 0) + 1
        if casos_con_dato < minimo_casos or not valores:
            continue
        valor, veces = max(valores.items(), key=lambda kv: kv[1])
        if veces / casos_con_dato < cuota:
            continue
        propuestas.append({"campo": campo, "valor": valor, "casos": casos_con_dato,
                           "coincidencias": veces,
                           "confianza": round(veces / casos_con_dato, 2),
                           "protocolo": evaluar(campo, valor).estado})
    return propuestas


def aplicar(hoja, columnas: dict[str, int], constantes: dict | None = None,
            fila_encabezado: int = 7, primera_fila: int = 8,
            lecturas: dict[str, dict] | None = None, base: Path | None = None) -> dict:
    """Escribe las constantes en las celdas vacías. Devuelve lo escrito y las excepciones.

    `lecturas` permite detectar la excepción: si ese caso leyó otra cosa, no se aplica la constante.
    """
    constantes = (constantes or cargar(base).get("constantes") or {})
    escritas, excepciones = [], []
    for fila in range(primera_fila, hoja.max_row + 1):
        numero = hoja.cell(fila, columnas.get("test_number", 3)).value
        if numero in (None, ""):
            continue
        for campo, datos in constantes.items():
            columna = columnas.get(campo)
            if not columna:
                continue
            actual = hoja.cell(fila, columna).value
            if actual not in (None, ""):
                if limpiar(actual) != limpiar(datos["valor"]):
                    excepciones.append({"caso": str(numero), "campo": campo,
                                        "constante": datos["valor"], "leido": limpiar(actual),
                                        "accion": "el caso ya tenía otro valor: no se sobrescribe"})
                continue
            propia = ((lecturas or {}).get(str(numero)) or {}).get(campo)
            if propia and limpiar(propia) != limpiar(datos["valor"]):
                excepciones.append({"caso": str(numero), "campo": campo,
                                    "constante": datos["valor"], "leido": limpiar(propia),
                                    "accion": "no se aplica: el caso tiene lectura propia distinta"})
                continue
            hoja.cell(fila, columna).value = datos["valor"]
            escritas.append({"caso": str(numero), "campo": campo, "valor": datos["valor"],
                             "origen": "constante_confirmada", "autor": datos.get("autor")})
    return {"escritas": escritas, "excepciones": excepciones}
