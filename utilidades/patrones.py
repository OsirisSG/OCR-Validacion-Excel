"""Detección de PATRONES e INCONSISTENCIAS en las lecturas (P11).

Para qué sirve
--------------
Revisar 150 dudas una por una es lento y aburrido; casi siempre se repiten unos pocos patrones.
Este módulo los busca y los pone encima de la mesa:

- **confusiones sistemáticas del OCR**: pares de lecturas del mismo campo que difieren en un solo
  carácter (`ZRZO`/`ZRZ0`, `01S`/`02S`, `NOM`/`NQL`). Si el mismo par se repite, es una confusión
  del motor, no un caso raro: se avisa y se propone la corrección.
- **columnas constantes**: campos que valen lo mismo en todos los casos (rellenables en bloque).
- **carpeta contra etiqueta**: casos en los que el nombre de la carpeta contradice la mayoría de
  las lecturas. Se listan aparte porque son los que acaban mal en el libro.
- **campos sin ninguna lectura válida**: los que no se pueden resolver por software.

Todo son funciones puras sobre las lecturas: no tocan el libro ni el aprendizaje.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher

from utilidades.validacion_formas import normalizar, revisar_forma

# Campos cuyo texto libre no se compara carácter a carácter (un proveedor escrito distinto no es
# una confusión del motor).
CAMPOS_SIN_CONFUSION = {"test_reason", "test_place", "pab_comments", "dashboard_comments",
                        "test_environment_comments", "laser_opening",
                        # catálogos cerrados: NT/RT/HT y NOM/OGL/UGL son valores distintos de
                        # verdad, no dos lecturas del mismo valor.
                        "temperature_condition", "inflator_type", "module_version"}
LONGITUD_MINIMA = 4  # por debajo, dos valores distintos se parecen demasiado


def _parecido(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def confusiones(lecturas: dict[str, dict], minimo: int = 2) -> list[dict]:
    """Pares de lecturas que difieren en una sola posición y se repiten.

    ``lecturas`` es ``{caso: {"ocr": {campo: {valor: nº imágenes}}}}`` (el mismo formato que usa
    la cola de dudas). Devuelve los pares ordenados por repeticiones.
    """
    pares: Counter = Counter()
    casos: dict[tuple, set] = defaultdict(set)
    for caso, fuentes in (lecturas or {}).items():
        for campo, votos in ((fuentes.get("ocr") or {}).items()):
            if campo in CAMPOS_SIN_CONFUSION or campo.startswith("_"):
                continue
            valores = [normalizar(v) for v in votos]
            for i, primero in enumerate(valores):
                for segundo in valores[i + 1:]:
                    if not primero or not segundo or primero == segundo:
                        continue
                    if min(len(primero), len(segundo)) < LONGITUD_MINIMA:
                        continue
                    if len(primero) != len(segundo):
                        continue
                    diferencias = [k for k in range(len(primero)) if primero[k] != segundo[k]]
                    if len(diferencias) != 1:
                        continue
                    posicion = diferencias[0]
                    clave = (campo, min(primero, segundo), max(primero, segundo), posicion)
                    pares[clave] += 1
                    casos[clave].add(caso)
    resultado = []
    for (campo, uno, otro, posicion), veces in pares.items():
        if veces < minimo:
            continue
        resultado.append({"campo": campo, "a": uno, "b": otro, "posicion": posicion,
                          "repeticiones": veces, "casos": sorted(casos[(campo, uno, otro, posicion)]),
                          "confusion": f"«{uno[posicion]}» ↔ «{otro[posicion]}»",
                          "explicacion": (f"en {veces} casos el mismo campo se leyó de dos formas "
                                          f"que sólo cambian el carácter {posicion + 1}")})
    return sorted(resultado, key=lambda d: -d["repeticiones"])


def constantes(libro_filas: dict[str, dict], campos, minimo: int = 3) -> list[dict]:
    """Campos que valen lo mismo en todas las filas y cumplen la forma del campo."""
    detectadas = []
    for campo in campos:
        valores = {normalizar(fila.get(campo)) for fila in (libro_filas or {}).values()}
        valores.discard("")
        if len(valores) != 1:
            continue
        valor = valores.pop()
        filas = sum(1 for fila in (libro_filas or {}).values()
                    if normalizar(fila.get(campo)) == valor)
        if filas < minimo or not revisar_forma(campo, valor)["valido"]:
            continue
        detectadas.append({"campo": campo, "valor": valor, "filas": filas,
                           "accion": "rellenar en bloque (confirmar una vez)"})
    return detectadas


def carpeta_contra_etiqueta(lecturas: dict[str, dict]) -> list[dict]:
    """Casos donde la carpeta dice una cosa y la mayoría de las lecturas otra."""
    conflictos = []
    for caso, fuentes in (lecturas or {}).items():
        carpeta = fuentes.get("carpeta") or {}
        ocr = fuentes.get("ocr") or {}
        for campo, valor_carpeta in carpeta.items():
            votos = ocr.get(campo) or {}
            if not votos or not valor_carpeta:
                continue
            objetivo = normalizar(valor_carpeta)
            contrarios = {v: n for v, n in votos.items() if normalizar(v) != objetivo}
            if not contrarios:
                continue
            total_contrario = sum(contrarios.values())
            if total_contrario >= 2:
                conflictos.append({"caso": caso, "campo": campo, "carpeta": objetivo,
                                   "lecturas_contrarias": contrarios,
                                   "imagenes": total_contrario,
                                   "riesgo": "alto" if total_contrario >= 3 else "medio"})
    return sorted(conflictos, key=lambda d: (-d["imagenes"], d["caso"]))


def campos_sin_lectura_valida(libro_filas: dict[str, dict], lecturas: dict[str, dict]) -> list[dict]:
    """Campos vacíos en el libro que además no tienen ninguna lectura con forma válida."""
    faltan = []
    for caso, fila in (libro_filas or {}).items():
        fuentes = (lecturas or {}).get(caso) or {}
        for campo, valor in fila.items():
            if valor not in (None, ""):
                continue
            candidatos = []
            for fuente in ("carpeta", "diagrama", "barra_video"):
                if (fuentes.get(fuente) or {}).get(campo):
                    candidatos.append(fuente)
            validos = [v for v in (fuentes.get("ocr") or {}).get(campo, {})
                       if revisar_forma(campo, v)["valido"]]
            if not candidatos and not validos:
                faltan.append({"caso": caso, "campo": campo,
                               "accion": "no hay nada que leer: dejarlo vacío o escribirlo a mano"})
    return faltan


def resumen(lecturas: dict[str, dict], libro_filas: dict[str, dict], campos) -> dict:
    """Todo junto, listo para pintar en la página de dudas."""
    return {
        "confusiones": confusiones(lecturas),
        "constantes": constantes(libro_filas, campos),
        "carpeta_contra_etiqueta": carpeta_contra_etiqueta(lecturas),
        "sin_lectura": campos_sin_lectura_valida(libro_filas, lecturas),
    }
