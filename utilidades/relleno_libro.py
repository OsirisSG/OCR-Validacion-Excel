"""Relleno aditivo de un libro que YA tiene datos (P08, reglas 2 y 7).

El problema que resuelve
------------------------
Hasta V16.0.21, generar la matriz **vacía la hoja y la vuelve a escribir** con lo que el
pipeline leyó. Si el libro que se usa como plantilla es el libro del usuario, eso borra lo
que ya estaba escrito a mano (y explica por qué el resultado tiene 149 celdas vacías cuando
el libro de referencia las trae llenas). Aquí se invierte la regla:

  1. Nunca se sobrescribe una celda que ya tiene valor. Si lo leído discrepa, se conserva
     el valor del libro y la discrepancia se anota para que la revise una persona.
  2. Las columnas que son constantes en el libro (IT BMG, EDAG, 2GJ.880.204.J, 03S…) se
     ofrecen como valor para las filas nuevas **en bloque**, con una sola confirmación; no
     se copian a ciegas celda por celda.

Todo se calcula antes de escribir (`planificar`) y sólo después se aplica (`aplicar`), de
modo que el plan se puede revisar, probar y volcar a la cola de dudas.
"""
from __future__ import annotations

from openpyxl.utils import get_column_letter


def _texto(valor) -> str:
    if valor is None:
        return ""
    return " ".join(str(valor).split()).upper()


def leer_constantes(hoja, claves, inicio: int = 8, fin: int = 107) -> dict[str, dict]:
    """Columnas con un único valor no vacío en las filas de datos del libro.

    Devuelve `{clave: {"valor": v, "filas": n, "columna": c}}` sólo para las columnas donde
    TODOS los valores presentes coinciden y hay al menos dos (una sola fila no es una
    constante: es un caso).
    """
    constantes: dict[str, dict] = {}
    for columna, clave in enumerate(claves, start=1):
        valores = {_texto(hoja.cell(fila, columna).value)
                   for fila in range(inicio, fin + 1)}
        valores.discard("")
        if len(valores) == 1:
            valor = valores.pop()
            filas = sum(1 for fila in range(inicio, fin + 1)
                        if _texto(hoja.cell(fila, columna).value))
            if filas >= 2:
                constantes[clave] = {"valor": valor, "filas": filas, "columna": columna}
    return constantes


def _huella(datos: dict) -> tuple:
    """Identidad de un caso sin usar el número de prueba: lo que no cambia al releerlo."""
    return tuple(_texto(datos.get(clave)) for clave in
                 ("week", "temperature_condition", "module_part_number", "test_place",
                  "test_date", "module_serial_number"))


def emparejar_filas(hoja, resultados, claves, inicio: int = 8, fin: int = 107) -> dict:
    """Empareja cada resultado con SU fila del libro.

    Dos intentos, en este orden:

    1. **por número de prueba** (lo normal);
    2. **por identidad del caso** (semana, temperatura, número de parte, lugar, fecha y serie).
       Así un caso cuyo número de prueba se leyó mal -o cuyo nombre de carpeta está
       equivocado- sigue encontrando su fila en el libro en lugar de crear una nueva y dejar
       el error publicado al lado. Es la diferencia entre «corregir» y «duplicar».

    Devuelve ``{"filas": {id: fila}, "por_identidad": [...], "sin_fila": [...],
    "huerfanas": [...]}``.
    """
    indice_prueba = list(claves).index("test_number") + 1
    del_libro: dict[str, int] = {}
    identidades: dict[tuple, int] = {}
    for fila in range(inicio, fin + 1):
        numero = "".join(ch for ch in str(hoja.cell(fila, indice_prueba).value or "")
                         if ch.isdigit())
        if numero:
            del_libro.setdefault(numero, fila)
        datos = {clave: _texto(hoja.cell(fila, col).value)
                 for col, clave in enumerate(claves, start=1)}
        huella = _huella(datos)
        if sum(1 for parte in huella if parte) >= 4 and huella[0] and huella[1]:
            # Sólo sirve una identidad que distinga ESTA fila de las demás: si dos filas del
            # libro comparten huella, emparejar por ella sería una adivinanza.
            identidades[huella] = -1 if huella in identidades else fila

    filas, sin_fila, por_identidad = {}, [], []
    usadas = set()
    pendientes = []
    for resultado in resultados:
        numero = "".join(ch for ch in str(resultado.get("test_number") or
                                         (resultado.get("campos") or {})
                                         .get("test_number", {}).get("valor") or "")
                         if ch.isdigit())
        if numero and numero in del_libro and del_libro[numero] not in usadas:
            filas[id(resultado)] = del_libro[numero]
            usadas.add(del_libro[numero])
        else:
            pendientes.append(resultado)
    for resultado in pendientes:
        datos = {clave: _texto(resultado.get(clave) or
                              (resultado.get("campos") or {}).get(clave, {}).get("valor"))
                 for clave in claves}
        huella = _huella(datos)
        fila = identidades.get(huella)
        if fila is not None and fila != -1 and fila not in usadas:
            filas[id(resultado)] = fila
            usadas.add(fila)
            por_identidad.append({"resultado": resultado.get("test_number"), "fila": fila,
                                  "coincide_en": [c for c, v in zip(
                                      ("week", "temperature_condition", "module_part_number",
                                       "test_place", "test_date", "module_serial_number"),
                                      huella) if v]})
        else:
            sin_fila.append(resultado)
    huerfanas = sorted(f for f in del_libro.values() if f not in usadas)
    return {"filas": filas, "por_identidad": por_identidad, "sin_fila": sin_fila,
            "huerfanas": huerfanas}


def constantes_confiables(hoja, claves, inicio: int = 8, fin: int = 107,
                          minimo: int = 3) -> dict[str, dict]:
    """Constantes del libro que se pueden aplicar sin preguntar una por una.

    Se exige que el valor esté repetido en al menos ``minimo`` filas y que **cumpla la forma**
    del campo: así no se propaga un valor raro que estuviera repetido por casualidad. Lo que no
    cumpla la forma se queda como propuesta para la cola de dudas.
    """
    from utilidades.validacion_formas import revisar_forma

    fiables = {}
    for clave, dato in leer_constantes(hoja, claves, inicio, fin).items():
        if dato["filas"] < minimo:
            continue
        if not revisar_forma(clave, dato["valor"])["valido"]:
            continue
        fiables[clave] = dato
    return fiables


def planificar(hoja, pares, claves, constante_confirmada=None,
               inicio: int = 8, fin: int = 107) -> dict:
    """Calcula qué se escribiría, sin escribir nada.

    ``pares`` es una lista de ``{"fila": 12, "valores": {"test_number": "232561", ...}}``:
    la fila del libro ya emparejada por número de prueba y lo que el pipeline propone.
    Devuelve cuatro listas:

    - ``escribir``: celdas vacías que se llenan (valor leído, o constante confirmada).
    - ``conservar``: la celda ya tenía valor y coincide con lo propuesto.
    - ``discrepancias``: la celda ya tenía valor y NO coincide → no se toca, se avisa.
    - ``constantes_propuestas``: columnas constantes del libro que rellenarían huecos y que
      todavía no están confirmadas por nadie.

    ``constante_confirmada`` es el conjunto de claves cuyas constantes el usuario confirmó
    por lote; sin confirmación, la constante se PROPONE pero no se escribe (regla 7: una
    sola confirmación sirve para todas las filas, pero hace falta que exista).
    """
    constantes = leer_constantes(hoja, claves, inicio, fin)
    confirmadas = set(constante_confirmada or ())
    escribir, conservar, discrepancias, constantes_propuestas = [], [], [], []
    for par in pares:
        fila = par.get("fila")
        propuestos = dict(par.get("valores") or {})
        if fila is None:
            continue
        for columna, clave in enumerate(claves, start=1):
            propuesto = propuestos.get(clave)
            if propuesto in (None, ""):
                constante = constantes.get(clave)
                if constante and clave in confirmadas:
                    propuesto, origen = constante["valor"], "constante_confirmada"
                elif constante:
                    constantes_propuestas.append({
                        "clave": clave, "fila": fila, "columna": columna,
                        "valor": constante["valor"], "filas_libro": constante["filas"]})
                    continue
                else:
                    continue
            else:
                origen = "lectura"
            actual = hoja.cell(fila, columna).value
            entrada = {"clave": clave, "fila": fila, "columna": columna,
                       "columna_letra": get_column_letter(columna),
                       "valor_propuesto": propuesto, "valor_libro": actual, "origen": origen}
            if actual in (None, ""):
                escribir.append(entrada)
            elif _texto(actual) == _texto(propuesto):
                conservar.append(entrada)
            else:
                discrepancias.append(entrada)
    return {"escribir": escribir, "conservar": conservar, "discrepancias": discrepancias,
            "constantes": constantes, "constantes_propuestas": constantes_propuestas}


def aplicar(hoja, plan: dict) -> int:
    """Escribe SÓLO las celdas vacías del plan. Devuelve cuántas escribió."""
    escritas = 0
    for entrada in plan.get("escribir", []):
        celda = hoja.cell(entrada["fila"], entrada["columna"])
        if celda.value not in (None, ""):  # el libro cambió entre planificar y aplicar
            continue
        celda.value = entrada["valor_propuesto"]
        escritas += 1
    return escritas


def resumen(plan: dict) -> str:
    """Una línea legible para el informe y para la pantalla."""
    return (f"{len(plan.get('escribir', []))} celdas a rellenar · "
            f"{len(plan.get('conservar', []))} ya correctas · "
            f"{len(plan.get('discrepancias', []))} discrepancias (no se tocan) · "
            f"{len(plan.get('constantes', {}))} columnas constantes")


def lecturas_de_constantes(plan: dict, casos) -> dict[str, dict]:
    """Traduce las constantes detectadas al formato que consume la cola de dudas.

    Devuelve ``{caso: {"libro_constante": {campo: valor}}}`` para cada caso de ``casos``:
    así cada celda vacía de una columna constante aparece en el panel con la opción
    «el libro lo repite igual en todos los casos» y se decide una sola vez.
    """
    constantes = {campo: dato["valor"] for campo, dato in (plan.get("constantes") or {}).items()}
    return {str(caso): {"libro_constante": dict(constantes)} for caso in casos}
