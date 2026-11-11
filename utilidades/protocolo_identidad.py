"""Identidad del caso a partir de las marcas que el propio operador deja.

Tres fuentes, tres lecturas distintas:

1. **Barra inferior del vídeo** (`VW316/5  222509  RdW  NT  NOM  0ms …`): la pinta el
   sistema de vídeo en cada fotograma. Es texto renderizado, no manuscrito, y no se
   puede olvidar en una foto suelta.
2. **Nombre de la carpeta del caso** (`222509 RDW NOM NT`): la escribe el operador.
   Es determinante para este taller.
3. **Título del diagrama** (`VW316/5 222521 RdW NT OGL`): un rótulo por caso.

Ninguna se usa para *rellenar a ciegas*: cada valor viaja con su fuente, y cuando dos
fuentes no coinciden se declara el conflicto y no se escribe nada.

La cuarta pieza es la **serie de casos** que se deduce de la base de aprendizaje
(7 000+ observaciones): 22xxxx = NT, 23xxxx = HT, 25xxxx = RT, y los bloques de
inflador van de cinco en cinco. Eso no rellena nada: sirve para **detectar** una errata
como la del libro (222550 marcado HT, cuando 22xxxx es NT).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Serie observada en aprendizaje.sqlite3 (ruta_imagen -> carpeta del caso).
# Se conserva con sus recuentos para que se pueda volver a auditar.
# ---------------------------------------------------------------------------
SERIE_CONOCIDA: list[dict] = [
    {"desde": 222501, "hasta": 222510, "temperatura": "NT", "inflador": "NOM", "casos": 10},
    {"desde": 222521, "hasta": 222525, "temperatura": "NT", "inflador": "OGL", "casos": 5},
    {"desde": 222526, "hasta": 222530, "temperatura": "NT", "inflador": "UGL", "casos": 5},
    {"desde": 232541, "hasta": 232550, "temperatura": "HT", "inflador": "NOM", "casos": 10},
    {"desde": 232561, "hasta": 232565, "temperatura": "HT", "inflador": "OGL", "casos": 5},
    {"desde": 232566, "hasta": 232570, "temperatura": "HT", "inflador": "UGL", "casos": 5},
    {"desde": 252581, "hasta": 252590, "temperatura": "RT", "inflador": "NOM", "casos": 10},
]

TEMPERATURA_POR_PREFIJO = {"22": "NT", "23": "HT", "25": "RT"}

# Regla del taller (2026-10-30): RDW y NAR NO son variantes de escritura, son etapas
# distintas del ensayo. Si una carpeta de 2ST dice RDW (o al revés), algo está mal.
VERSION_POR_ETAPA = {"RDW": "1ST", "NAR": "2ST"}
ETAPA_POR_VERSION = {"1ST": "RDW", "2ST": "NAR"}

# orden de autoridad cuando dos fuentes discrepan (nunca se elige en silencio)
PRIORIDAD_FUENTES = ("barra_video", "carpeta", "diagrama")

CAMPOS_DE_IDENTIDAD = ("test_number", "module_version", "temperature_condition", "inflator_type")

_RE_CARPETA = re.compile(
    r"^(?P<numero>\d{6})[\s_-]+(?P<version>RDW|NAR)[\s_-]+"
    r"(?P<inflador>NOM|OGL|UGL)[\s_-]+(?P<temperatura>NT|RT|HT)$", re.IGNORECASE)


def _limpio(texto: str) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip()


# ---------------------------------------------------------------------------
# 1 · nombre de la carpeta del caso
# ---------------------------------------------------------------------------
def leer_nombre_carpeta(nombre: str) -> dict:
    """`'222509 RDW NOM NT'` -> identidad del caso. Estricto: si no encaja, nada.

    Devuelve `{}` cuando el nombre no cumple el patrón completo. No se acepta un
    nombre «casi» correcto: un caso mal identificado contamina el aprendizaje.
    """
    texto = _limpio(nombre)
    if not texto:
        return {}
    # admite la ruta completa: busca entre los tramos, del último hacia atrás
    partes = [p for p in re.split(r"[\\/]", str(nombre)) if p.strip()]
    for candidato in list(reversed(partes)) + [texto]:
        m = _RE_CARPETA.match(_limpio(candidato))
        if m:
            return {
                "test_number": m.group("numero"),
                "module_version": m.group("version").upper(),
                "temperature_condition": m.group("temperatura").upper(),
                "inflator_type": m.group("inflador").upper(),
                "fuente": "carpeta",
                "texto_fuente": _limpio(candidato),
            }
    return {}


# ---------------------------------------------------------------------------
# 2 · barra inferior del vídeo
# ---------------------------------------------------------------------------
_RE_NUMERO = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_RE_VERSION = re.compile(r"\b(R\s?D\s?W|N\s?A\s?R)\b", re.IGNORECASE)
_RE_TEMP = re.compile(r"(?<![A-Z0-9])(NT|RT|HT)(?![A-Z0-9])")
_RE_INFLADOR = re.compile(r"(?<![A-Z0-9])(NOM|OGL|UGL)(?![A-Z0-9])")
_RE_PROYECTO = re.compile(r"\b(VW\s?\d{3}\s?/\s?\d{1,2})\b")
_RE_MS = re.compile(r"(?<!\d)(\d{1,4})\s?ms\b", re.IGNORECASE)
_RE_SEMANA = re.compile(r"\b(\d{1,2}\s+[A-Z]{3}\s+\d{2,4})\b")


def leer_barra_video(texto: str) -> dict:
    """Lee la franja de estado quemada en el vídeo.

    Formato real (fotograma del caso 222509)::

        VW316/5   222509   RdW   NT   NOM   0ms   EDAG Mex   BMG   28 MAY 25   Rec5000 fps …

    `RdW` es la forma en que el sistema de vídeo escribe RDW; se normaliza. El número
    se busca como seis dígitos sueltos, y **no** se acepta si hay más de uno distinto:
    ahí habría que adivinar.
    """
    texto = _limpio(texto)
    if not texto:
        return {}
    identidad: dict = {"fuente": "barra_video", "texto_fuente": texto}

    numeros = {n for n in _RE_NUMERO.findall(texto)}
    if len(numeros) == 1:
        identidad["test_number"] = numeros.pop()
    elif len(numeros) > 1:
        identidad["conflicto_numero"] = sorted(numeros)

    m = _RE_VERSION.search(texto)
    if m:
        identidad["module_version"] = re.sub(r"\s", "", m.group(1)).upper()
    m = _RE_TEMP.search(texto)
    if m:
        identidad["temperature_condition"] = m.group(1)
    m = _RE_INFLADOR.search(texto)
    if m:
        identidad["inflator_type"] = m.group(1)
    m = _RE_PROYECTO.search(texto)
    if m:
        identidad["proyecto"] = re.sub(r"\s", "", m.group(1))
    m = _RE_MS.search(texto)
    if m:
        identidad["video_ms"] = int(m.group(1))
    m = _RE_SEMANA.search(texto)
    if m:
        identidad["fecha_video"] = m.group(1)
    if re.search(r"EDAG", texto, re.IGNORECASE):
        identidad["test_place"] = "EDAG"
    return identidad if len(identidad) > 2 else {}


def franja_inferior(imagen, fraccion: float = 0.90):
    """Recorta la banda inferior donde vive la barra de estado (90 %→100 % de alto).

    Es el paso previo del protocolo: nunca se lanza OCR sobre el fotograma completo
    (agota la memoria y ensucia la lectura con el vídeo de fondo).
    """
    ancho, alto = imagen.size
    return imagen.crop((0, int(alto * fraccion), ancho, alto))


# ---------------------------------------------------------------------------
# 3 · título del diagrama
# ---------------------------------------------------------------------------
_RE_TITULO = re.compile(
    r"VW\s?\d{3}\s?/\s?\d{1,2}\s+(?P<numero>\d{6})\s+(?P<version>R\s?D\s?W|N\s?A\s?R)\s+"
    r"(?P<temperatura>NT|RT|HT)\s+(?P<inflador>NOM|OGL|UGL)", re.IGNORECASE)


def leer_titulo_diagrama(texto: str) -> dict:
    """Título del plano -> identidad.

    No se exige un orden fijo de los tres rótulos: el plano real dice
    `VW316/5 222521 RdW NT OGL`, pero un proyecto nuevo puede escribir
    `VW270/2 310055 NAR OGL NT`. Se busca el número y, en la ventana siguiente, la
    versión, la temperatura y el inflador donde estén. Si falta el número, no hay
    identidad: no se inventa.
    """
    texto = _limpio(texto)
    if not texto:
        return {}
    m_num = _RE_NUMERO.search(texto)
    if not m_num:
        return {}
    ventana = texto[m_num.end():m_num.end() + 40]
    identidad = {"test_number": m_num.group(1), "fuente": "diagrama", "texto_fuente": texto}
    m = _RE_VERSION.search(ventana)
    if m:
        identidad["module_version"] = re.sub(r"\s", "", m.group(1)).upper()
    m = _RE_TEMP.search(ventana)
    if m:
        identidad["temperature_condition"] = m.group(1)
    m = _RE_INFLADOR.search(ventana)
    if m:
        identidad["inflator_type"] = m.group(1)
    return identidad if len(identidad) > 3 else {}


# ---------------------------------------------------------------------------
# Serie: coherencia, nunca relleno
# ---------------------------------------------------------------------------
def bloque_de_serie(numero) -> dict:
    """Bloque de la serie al que pertenece un número, si se conoce."""
    try:
        n = int(str(numero).strip())
    except (TypeError, ValueError):
        return {}
    for bloque in SERIE_CONOCIDA:
        if bloque["desde"] <= n <= bloque["hasta"]:
            return dict(bloque)
    return {}


def revisar_serie(numero, temperatura=None, inflador=None, version=None) -> dict:
    """Comprueba la identidad contra la serie conocida.

    Estados: `coherente`, `fuera_de_serie` (número que la base no tiene: no es un
    error, es un caso nuevo) o `incoherente` (el número pertenece a un bloque y los
    datos dicen otra cosa). Lo incoherente **no se corrige solo**: se avisa.
    """
    bloque = bloque_de_serie(numero)
    if not bloque:
        prefijo = str(numero).strip()[:2]
        esperada = TEMPERATURA_POR_PREFIJO.get(prefijo)
        if esperada and temperatura and str(temperatura).upper() != esperada:
            return {"estado": "incoherente", "motivo":
                    f"el prefijo {prefijo} de {numero} corresponde a {esperada}, no a {temperatura}",
                    "temperatura_esperada": esperada}
        return {"estado": "fuera_de_serie",
                "motivo": f"{numero} no aparece en la serie de la base de aprendizaje"}
    problemas = []
    if temperatura and str(temperatura).upper() != bloque["temperatura"]:
        problemas.append(f"temperatura: el bloque {bloque['desde']}-{bloque['hasta']} es "
                         f"{bloque['temperatura']}, no {temperatura}")
    if inflador and str(inflador).upper() != bloque["inflador"]:
        problemas.append(f"inflador: el bloque {bloque['desde']}-{bloque['hasta']} es "
                         f"{bloque['inflador']}, no {inflador}")
    if problemas:
        return {"estado": "incoherente", "motivo": " · ".join(problemas), "bloque": bloque}
    return {"estado": "coherente", "bloque": bloque}


def revisar_etapa(version, tipo_st) -> dict:
    """Comprueba la regla RDW=1ST / NAR=2ST.

    No rellena nada: si la etapa y la versión no se corresponden, el caso está mal
    nombrado y hay que verlo antes de volcar datos.
    """
    if not version or not tipo_st:
        return {"estado": "sin_comprobar", "motivo": "falta la versión o la etapa"}
    version, etapa = str(version).upper(), str(tipo_st).upper()
    esperada = VERSION_POR_ETAPA.get(version)
    if esperada is None:
        return {"estado": "fuera_de_catalogo",
                "motivo": f"versión {version} desconocida: se esperaba RDW o NAR"}
    if etapa == esperada:
        return {"estado": "coherente", "etapa": etapa, "version": version}
    return {"estado": "incoherente",
            "motivo": (f"la versión {version} corresponde a {esperada}, pero el caso está "
                       f"en la etapa {etapa}"),
            "etapa_esperada": esperada}


# ---------------------------------------------------------------------------
# Consolidación de fuentes
# ---------------------------------------------------------------------------
@dataclass
class Consolidado:
    valores: dict[str, str] = field(default_factory=dict)
    procedencia: dict[str, str] = field(default_factory=dict)
    conflictos: dict[str, dict] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    serie: dict = field(default_factory=dict)

    @property
    def dudosos(self) -> list[str]:
        return sorted(self.conflictos)

    def escribible(self, campo: str) -> bool:
        return campo in self.valores and campo not in self.conflictos


def consolidar(*fuentes: dict) -> Consolidado:
    """Funde las lecturas de varias fuentes en una sola identidad, sin resolver aún."""
    salida = Consolidado()
    for campo in CAMPOS_DE_IDENTIDAD:
        aportes: dict[str, list[str]] = {}
        for fuente in fuentes:
            if not fuente:
                continue
            valor = fuente.get(campo)
            if valor in (None, ""):
                continue
            aportes.setdefault(str(valor).upper(), []).append(
                fuente.get("fuente") or "desconocida")
        if not aportes:
            continue
        if len(aportes) == 1:
            valor, quienes = next(iter(aportes.items()))
            salida.valores[campo] = valor
            salida.procedencia[campo] = " + ".join(sorted(set(quienes)))
            if len(set(quienes)) == 1:
                salida.avisos.append(f"{campo}={valor}: una sola fuente ({quienes[0]}), sin corroborar")
            continue
        salida.conflictos[campo] = {"dice": {k: sorted(set(v)) for k, v in aportes.items()}}
    return salida


def _resolver_conflicto(salida: Consolidado, campo: str, numero: str) -> None:
    """Rompe el empate de un campo con dos criterios, en este orden:

    1. **La serie manda**: si el valor de una fuente cuadra con la serie conocida y el
       de la otra no, gana el que cuadra (`resuelto_por_serie`).
    2. **La carpeta es determinante** (instrucción del usuario): si no hay serie que
       decida, gana el valor de la carpeta (`resuelto_por_determinante`). Nunca en
       silencio: queda el valor perdedor en el registro.

    Si la carpeta no participa del conflicto, no se elige: queda a confirmación manual.
    """
    conflicto = salida.conflictos[campo]
    candidatos = conflicto["dice"]
    otros = dict(salida.valores)
    coherentes = []
    for valor in candidatos:
        prueba = dict(otros)
        prueba[campo] = valor
        if revisar_serie(numero, prueba.get("temperature_condition"),
                         prueba.get("inflator_type"))["estado"] == "coherente":
            coherentes.append(valor)
    if len(coherentes) == 1:
        elegido, criterio = coherentes[0], "resuelto_por_serie"
    elif "carpeta" in candidatos.get(list(candidatos)[0], []) or \
            any("carpeta" in fuentes for fuentes in candidatos.values()):
        elegido = next((v for v, fuentes in candidatos.items() if "carpeta" in fuentes), None)
        criterio = "resuelto_por_determinante" if elegido else "sin_resolver"
    else:
        elegido, criterio = None, "sin_resolver"

    if elegido is None:
        salida.avisos.append(f"{campo}: conflicto sin criterio de desempate -> confirmación manual")
        return
    salida.valores[campo] = elegido
    salida.procedencia[campo] = f"{criterio} ({'+'.join(candidatos[elegido])})"
    perdedores = {v: f for v, f in candidatos.items() if v != elegido}
    conflicto["elegido"] = elegido
    conflicto["criterio"] = criterio
    conflicto["descartado"] = perdedores
    salida.avisos.append(f"{campo}: fuentes discrepantes {candidatos} -> se toma {elegido} ({criterio})")


def identidad_del_caso(carpeta: str | None = None, barra: str | None = None,
                       diagrama: str | None = None) -> Consolidado:
    """Lee las tres fuentes, consolida, desempata y revisa la coherencia con la serie."""
    fuentes = [f for f in (leer_barra_video(barra or ""), leer_nombre_carpeta(carpeta or ""),
                           leer_titulo_diagrama(diagrama or "")) if f]
    salida = consolidar(*fuentes)
    if "test_number" in salida.conflictos:
        salida.avisos.append("test_number: dos fuentes dan números distintos -> confirmación manual")
    numero = salida.valores.get("test_number")
    for campo in ("temperature_condition", "inflator_type", "module_version"):
        if campo in salida.conflictos and numero:
            _resolver_conflicto(salida, campo, numero)
    if numero:
        salida.serie = revisar_serie(numero, salida.valores.get("temperature_condition"),
                                     salida.valores.get("inflator_type"))
        salida.avisos.append(f"serie: {salida.serie['estado']}"
                             + (f" — {salida.serie['motivo']}" if salida.serie.get("motivo") else ""))
    return salida


# ---------------------------------------------------------------------------
# Integración con el flujo: candidatos en el mismo formato que el extractor
# ---------------------------------------------------------------------------
ETIQUETA_CAMPO = {
    "test_number": "numero_en_barra_de_video",
    "module_version": "version_en_barra_de_video",
    "temperature_condition": "temperatura_en_barra_de_video",
    "inflator_type": "inflador_en_barra_de_video",
}


def candidatos_desde_barra(texto: str, imagen: dict | None = None,
                           contexto: dict | None = None) -> list[dict]:
    """Devuelve candidatos para `extender` la lista de evidencias del flujo.

    Solo emite si el texto **es** una barra de estado de vídeo: lleva el proyecto
    (`VW316/5`) y además versión, milisegundos o fecha. Un texto cualquiera que
    contenga `NT` no se convierte en una lectura de temperatura.

    Los candidatos van con `fuente="barra_video"` y confianza alta pero **no** se
    marcan como confirmados: la barra es texto renderizado, no una verdad revelada.
    """
    lectura = leer_barra_video(texto)
    if not lectura:
        return []
    tiene_proyecto = bool(lectura.get("proyecto"))
    tiene_marca_de_video = (lectura.get("video_ms") is not None
                            and bool(re.search(r"fps|Rec\d", texto or "", re.IGNORECASE)))
    cuatro_campos = all(lectura.get(c) for c in
                        ("test_number", "module_version", "temperature_condition", "inflator_type"))
    if not (tiene_proyecto or tiene_marca_de_video or cuatro_campos):
        return []
    imagen = imagen or {}
    contexto = contexto or {}
    try:
        from flujo_empresarial import _votos
    except Exception:                                    # pragma: no cover
        def _votos(_valor):
            return {}
    confianza = float(imagen.get("confianza_ocr") or 0.9)
    salida = []
    for campo, etiqueta in ETIQUETA_CAMPO.items():
        valor = lectura.get(campo)
        if not valor:
            continue
        salida.append({
            "proyecto": contexto.get("project_id") or contexto.get("proyecto"),
            "etapa": contexto.get("tipo_st") or contexto.get("stage"),
            "caso": contexto.get("case_key") or contexto.get("test_number"),
            "componente": contexto.get("componente") or "por_identificar",
            "clave": campo, "valor_original": str(valor), "valor_normalizado": str(valor),
            "fuente": "barra_video",
            "imagen": imagen.get("ruta_relativa") or imagen.get("ruta"),
            "imagen_absoluta": imagen.get("ruta_absoluta") or imagen.get("ruta"),
            "bbox_original": imagen.get("bbox_original") or imagen.get("bbox"),
            "orientacion_grados": imagen.get("orientacion_grados") or 0,
            "transformaciones": list(imagen.get("transformaciones") or []),
            "fase": imagen.get("fase"), "tor": imagen.get("tor"),
            "confianza_ocr": round(confianza, 4),
            "valido_catalogo": True, "valido_regex": True, "regla_aplicada": etiqueta,
            "confirmacion_manual": False, "requiere_confirmacion_manual": False,
            "votos": _votos(str(valor)),
            "version_procesamiento": contexto.get("version_procesamiento") or "v8",
            "texto_barra": lectura.get("texto_fuente"),
        })
    return salida
