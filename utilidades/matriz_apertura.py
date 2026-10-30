"""Definición única de la matriz de apertura y del semáforo de tiempos.

V15.10: el dashboard y el Excel comparten una matriz dinámica de casos reales.
Este módulo define:

- Siete categorías estables HT/RT/NT × UGL/OGL/NOM; sólo se crean celdas para
  casos existentes. Los cupos históricos se conservan como metadatos, no como
  posiciones vacantes visibles.
- La evaluación del semáforo de apertura a partir de los límites confirmados
  (verde ≤ V, V < amarillo ≤ A, rojo > A) con valores por defecto 6/7 ms.
- Estados explicables para cada caso. Nunca se inventan IDs ni tiempos ni se
  sustituye la ausencia de medición por cero.

Los valores sólo se colorean cuando son finitos, estrictamente positivos y confiables
(``estado`` ni ``conflicto``/``pendiente_revision`` ni ``requiere_revision``).
"""
from __future__ import annotations

import math
import re
from typing import Iterable

from configuracion import evaluar_criterio

# Orden visual de la matriz resumen (izquierda -> derecha) y cupos esperados.
COLUMNAS_MATRIZ: list[dict] = [
    {"id": "HT_UGL", "col": "D", "temperature_condition": "HT", "inflator_type": "UGL",
     "temperatura": "+85°C", "generador": "UGL", "esperados": 5},
    {"id": "HT_OGL", "col": "E", "temperature_condition": "HT", "inflator_type": "OGL",
     "temperatura": "+85°C", "generador": "OGL", "esperados": 5},
    {"id": "HT_NOM", "col": "F", "temperature_condition": "HT", "inflator_type": "NOM",
     "temperatura": "+85°C", "generador": "nominal", "esperados": 10},
    {"id": "RT_NOM", "col": "G", "temperature_condition": "RT", "inflator_type": "NOM",
     "temperatura": "RT", "generador": "nominal", "esperados": 10},
    {"id": "NT_NOM", "col": "H", "temperature_condition": "NT", "inflator_type": "NOM",
     "temperatura": "-35°C", "generador": "nominal", "esperados": 10},
    {"id": "NT_OGL", "col": "I", "temperature_condition": "NT", "inflator_type": "OGL",
     "temperatura": "-35°C", "generador": "OGL", "esperados": 5},
    {"id": "NT_UGL", "col": "J", "temperature_condition": "NT", "inflator_type": "UGL",
     "temperatura": "-35°C", "generador": "UGL", "esperados": 5},
]

COMBINACIONES_MATRIZ = {(s["temperature_condition"], s["inflator_type"]) for s in COLUMNAS_MATRIZ}

# Valores iniciales del proyecto: 5.8 ms -> verde; 6.4 ms -> amarillo; 7.2 ms -> rojo.
VERDE_PREDETERMINADO_MS = 6.0
AMARILLO_PREDETERMINADO_MS = 7.0

_ESTADOS_NO_COLOR = {"conflicto", "pendiente_revision", "error", "descartado"}
_RE_VERDE = re.compile(r"^<=\s*([0-9]+(?:[.,][0-9]+)?)\s*(?:ms)?$", re.IGNORECASE)
_RE_ROJO = re.compile(r"^>\s*([0-9]+(?:[.,][0-9]+)?)\s*(?:ms)?$", re.IGNORECASE)


def limites_predefinidos() -> tuple[float, float]:
    """(verde hasta, amarillo hasta) predeterminados del proyecto: 6.0 / 7.0 ms."""
    return VERDE_PREDETERMINADO_MS, AMARILLO_PREDETERMINADO_MS


def criterio_desde_limites(verde_max: float, amarillo_max: float) -> dict:
    """Reglas legibles del semáforo a partir de los dos límites numéricos."""
    verde, amarillo = validar_limites(verde_max, amarillo_max)
    return {"verde": f"<= {verde:g}", "amarillo": f"{verde:g}-{amarillo:g}",
            "rojo": f"> {amarillo:g}"}


def validar_limites(verde_max, amarillo_max) -> tuple[float, float]:
    """Valida los límites: números finitos, no negativos y 0 ≤ verde < amarillo."""
    for valor in (verde_max, amarillo_max):
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) \
                or not math.isfinite(valor):
            raise ValueError("Los límites deben ser números finitos (se admiten decimales en ms).")
    verde, amarillo = float(verde_max), float(amarillo_max)
    if verde < 0 or amarillo < 0:
        raise ValueError("Los límites no pueden ser negativos.")
    if not verde < amarillo:
        raise ValueError("Los límites deben cumplir: 0 ≤ verde < amarillo; el rojo queda por encima.")
    return verde, amarillo


def limites_desde_criterio(criterio: dict | None) -> tuple[float, float]:
    """Recupera (verde, amarillo) desde las reglas de texto del criterio."""
    criterio = criterio or {}
    m_v = _RE_VERDE.match(str(criterio.get("verde") or "").strip())
    m_r = _RE_ROJO.match(str(criterio.get("rojo") or "").strip())
    if m_v and m_r:
        try:
            return validar_limites(float(m_v.group(1).replace(",", ".")),
                                   float(m_r.group(1).replace(",", ".")))
        except ValueError:
            pass
    return limites_predefinidos()


def criterio_apertura_efectivo(reglas: dict | None = None,
                               criterios_usuario: dict | None = None,
                               instantanea: dict | None = None) -> tuple[dict, str]:
    """Criterio vigente y su origen: instantánea de ejecución > usuario > YAML/default.

    Devuelve (criterio_texto, origen) con origen en
    ``instantanea_ejecucion | criterios_usuario | predeterminado``.
    """
    if instantanea:
        try:
            verde, amarillo = validar_limites(instantanea.get("verde_max"),
                                              instantanea.get("amarillo_max"))
            return criterio_desde_limites(verde, amarillo), "instantanea_ejecucion"
        except (ValueError, TypeError):
            pass
    if criterios_usuario:
        try:
            verde, amarillo = validar_limites(criterios_usuario.get("verde_max"),
                                              criterios_usuario.get("amarillo_max"))
            return criterio_desde_limites(verde, amarillo), "criterios_usuario"
        except (ValueError, TypeError):
            pass
    reglas = reglas or {}
    criterio = (reglas.get("criterios") or {}).get("tiempo_apertura_ms")
    if criterio:
        try:
            return dict(criterio), "yaml"
        except (TypeError, ValueError):
            pass
    verde, amarillo = limites_predefinidos()
    return criterio_desde_limites(verde, amarillo), "predeterminado"


def _numero_ms(valor):
    if isinstance(valor, bool) or valor in {None, "", "--", "-"}:
        return None
    try:
        numero = float(str(valor).strip().lower().replace("ms", "").replace(",", "."))
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) else None


def valor_confiable(dato) -> float | None:
    """Valor usable para colorear: finito, > 0 y sin revisión/conflicto pendiente."""
    if dato is None:
        return None
    if isinstance(dato, dict):
        if dato.get("requiere_revision") or str(dato.get("estado") or "") in _ESTADOS_NO_COLOR:
            return None
        numero = _numero_ms(dato.get("valor"))
    else:
        numero = _numero_ms(dato)
    if numero is None or numero <= 0:
        return None
    return numero


def evaluar_apertura(valor_ms, criterio: dict, dato=None) -> tuple[str, float | None, str]:
    """(estado, valor, motivo) de una celda de apertura.

    ``estado`` en verde/amarillo/rojo/gris. El motivo explica el gris:
    ``sin_tiempo``, ``valor_no_finito``, ``valor_negativo``, ``pendiente_revision``,
    ``conflicto`` — o ``ok`` cuando hay color.
    """
    if dato is None and isinstance(valor_ms, dict):
        dato, valor_ms = valor_ms, valor_ms.get("valor")
    if dato is not None and (dato.get("requiere_revision")
                             or str(dato.get("estado") or "") in _ESTADOS_NO_COLOR):
        motivo = ("conflicto" if str(dato.get("estado") or "") == "conflicto"
                  else "pendiente_revision")
        return "gris", _numero_ms(dato.get("valor")), motivo
    numero = _numero_ms(valor_ms)
    if numero is None:
        return "gris", None, "sin_tiempo"
    if not math.isfinite(numero):
        return "gris", None, "valor_no_finito"
    if numero < 0:
        return "gris", None, "valor_negativo"
    if numero == 0:
        return "gris", None, "valor_no_positivo"
    estado = evaluar_criterio(criterio, numero) or "gris"
    return estado, numero, ("ok" if estado != "gris" else "sin_regla")


def regla_publica(criterio: dict, origen: str | None = None, nota_gris: str | None = None) -> dict:
    """Texto de leyenda común para el dashboard y el Excel.

    Los límites numéricos se muestran con la unidad «ms» (p. ej. ``<= 6 ms``),
    como publica la API del dashboard desde V15.8.
    """
    def _con_unidad(valor) -> str:
        texto = str(valor or "—")
        return texto if "ms" in texto.lower() or texto == "—" else f"{texto} ms"

    regla = {
        "verde": _con_unidad(criterio.get("verde")),
        "amarillo": _con_unidad(criterio.get("amarillo")),
        "rojo": _con_unidad(criterio.get("rojo")),
        "gris": nota_gris or "sin tiempo confiable o pendiente/conflicto",
    }
    if origen:
        regla["origen_criterio"] = origen
    return regla


def _campo_resultado(fila: dict, clave: str):
    dato = (fila.get("campos") or {}).get(clave)
    if isinstance(dato, dict):
        return dato
    if dato not in {None, ""}:
        return {"valor": dato}
    return None


def _test_number(fila: dict):
    dato = _campo_resultado(fila, "test_number")
    if isinstance(dato, dict) and dato.get("valor") not in {None, ""}:
        return dato.get("valor")
    return fila.get("test_number") or fila.get("identificador") or fila.get("nombre")


def _clave_orden(fila: dict):
    valor = _test_number(fila)
    try:
        return (0, int(str(valor).strip()))
    except (TypeError, ValueError):
        return (1, str(valor or ""))


def celda_caso(fila: dict, criterio: dict) -> dict:
    """Celda ocupada con semáforo y procedencia/rechazo de tiempo trazables."""
    canonico = fila.get("resultado_caso_canonico")
    apertura = {}
    campo = {}
    decision_apertura = None
    estado_tiempo = fila.get("estado_tiempo")
    motivo_rechazo = fila.get("motivo_rechazo")
    raw_time_ms = fila.get("raw_time_ms")
    fuente_evidencia = fila.get("fuente_evidencia") or fila.get("fuente_apertura")
    razones = []
    campos_crudos = fila.get("campos") if isinstance(fila.get("campos"), dict) else None
    videos_crudos = fila.get("videos") if isinstance(fila.get("videos"), list) else None
    video_apertura_crudo = fila.get("video_apertura") if isinstance(fila.get("video_apertura"), dict) else None
    tiene_fuentes_crudas = bool(campos_crudos or videos_crudos or video_apertura_crudo)
    if tiene_fuentes_crudas or isinstance(canonico, dict):
        # V16.0.2: la fila PÚBLICA ya fue resuelta con TODAS sus fuentes en
        # _fila_publica. Recalcularla aquí con campos/videos eliminados por la
        # proyección pierde evidencia y puede generar otro color (caso 252581).
        # Los datos brutos aún se recalculan, sin confiar en snapshots antiguos.
        es_fila_publica = (isinstance(canonico, dict)
                           and "semaforo_apertura" in fila
                           and "apertura_motivo" in fila)
        if (not es_fila_publica
                and (tiene_fuentes_crudas or not isinstance(canonico, dict))):
            try:
                from utilidades.resultado_caso import resolver_resultado_caso
                canonico = resolver_resultado_caso(fila)
            except (TypeError, ValueError):
                canonico = fila.get("resultado_caso_canonico") if isinstance(fila.get("resultado_caso_canonico"), dict) else None
        campos = fila.get("campos") if isinstance(fila.get("campos"), dict) else {}
        campo = campos.get("opening_time_ms") if isinstance(campos.get("opening_time_ms"), dict) else {}
        apertura = ((canonico or {}).get("apertura")
                    if isinstance((canonico or {}).get("apertura"), dict) else {})
        decision_apertura = apertura.get("estado")
        invalidas = apertura.get("revisiones_temporales_invalidas")
        invalidas = invalidas if isinstance(invalidas, list) else []
        invalida = invalidas[0] if invalidas and isinstance(invalidas[0], dict) else {}
        if invalida:
            estado_tiempo = invalida.get("estado_tiempo") or estado_tiempo
            motivo_rechazo = invalida.get("motivo") or motivo_rechazo
            if invalida.get("raw_time_ms") is not None:
                raw_time_ms = invalida.get("raw_time_ms")
        if raw_time_ms is None:
            raw_time_ms = campo.get("raw_time_ms")
        if fuente_evidencia is None:
            fuente_evidencia = (invalida.get("fuente_campo") or invalida.get("fuente")
                                or invalida.get("video") or campo.get("fuente_preferida")
                                or campo.get("fuente") or apertura.get("fuente"))
        razones = list(apertura.get("motivos") or [])
        if decision_apertura in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"}:
            dato = {"valor": apertura.get("tiempo_ms"),
                    "estado": "confirmado_manual" if decision_apertura == "VERIFICADO_HUMANO" else "confirmado_automatico"}
        elif decision_apertura == "CONFLICTO":
            dato = {"valor": apertura.get("tiempo_propuesto_ms"),
                    "estado": "conflicto", "requiere_revision": True}
        elif decision_apertura == "PROPUESTA" and apertura.get("auto_color_elegible") is True:
            dato = {"valor": apertura.get("tiempo_estimado_auto_ms"),
                    "estado": "estimado_automatico"}
        elif decision_apertura == "PROPUESTA":
            dato = {"valor": apertura.get("tiempo_propuesto_ms"),
                    "estado": "pendiente_revision", "requiere_revision": True}
        else:
            dato = {"valor": None, "estado": "sin_tiempo"}
        estado, valor, motivo = evaluar_apertura(dato, criterio)
        if es_fila_publica:
            color_resumen = fila.get("semaforo_apertura")
            if color_resumen in {"verde", "amarillo", "rojo", "gris"} and estado != color_resumen:
                estado = color_resumen
                motivo = fila.get("apertura_motivo") or motivo
                # Nunca publicar un tiempo cuando la decisión fuente se abstuvo.
                if estado == "gris":
                    valor = None
        if (decision_apertura == "PROPUESTA"
                and apertura.get("auto_color_elegible") is True
                and estado != "gris"):
            motivo = "estimacion_automatica_alta_confianza"
        if not estado_tiempo:
            estado_tiempo = ("VALIDO" if decision_apertura in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"} and valor is not None
                             else "ESTIMADO_AUTO" if decision_apertura == "PROPUESTA" and apertura.get("auto_color_elegible") is True and valor is not None
                             else "CONFLICTO" if decision_apertura == "CONFLICTO"
                             else "PENDIENTE" if decision_apertura == "PROPUESTA"
                             else "SIN_MEDICION")
        if invalida and decision_apertura != "CONFLICTO":
            motivo = str(estado_tiempo or "pendiente").casefold()
    else:
        valor = _numero_ms(fila.get("opening_time_ms"))
        pendiente = _numero_ms(fila.get("opening_time_pendiente_ms"))
        estado = str(fila.get("semaforo_apertura") or "gris")
        motivo = fila.get("apertura_motivo")
        decision_apertura = fila.get("decision_apertura") or fila.get("decision_v15_10")
        referencia_valida = (fila.get("referencia_tiempo_valida") is True
                             if "referencia_tiempo_valida" in fila
                             else fila.get("estado_tiempo") == "VALIDO")
        if raw_time_ms is None:
            raw_original = fila.get("opening_time_ms_crudo", fila.get("tiempo_ms_crudo"))
            if raw_original is None:
                raw_original = fila.get("opening_time_ms")
            if isinstance(raw_original, float) and not math.isfinite(raw_original):
                raw_time_ms = repr(raw_original)
            else:
                raw_time_ms = raw_original
        if valor is not None and valor <= 0:
            valor = None
            pendiente = None
            estado = "gris"
            motivo = "valor_no_positivo"
            estado_tiempo = "NO_POSITIVO"
        elif valor is not None and not referencia_valida:
            valor = None
            pendiente = None
            estado = "gris"
            motivo = "referencia_invalida"
            estado_tiempo = "REFERENCIA_INVALIDA"
        if pendiente is not None and (pendiente <= 0 or not referencia_valida):
            if estado_tiempo is None:
                estado_tiempo = "NO_POSITIVO" if pendiente <= 0 else "REFERENCIA_INVALIDA"
            motivo = "valor_no_positivo" if pendiente <= 0 else "referencia_invalida"
            pendiente = None
            estado = "gris"
        elif estado != "gris" and valor is not None:
            motivo = "ok"
        elif not motivo:
            motivo = ("sin_tiempo" if pendiente is None else "pendiente_revision")
        if estado == "gris" and valor is None and pendiente is not None:
            valor = pendiente
        if estado_tiempo is None:
            estado_tiempo = "VALIDO" if estado != "gris" else "PENDIENTE" if pendiente is not None else "SIN_MEDICION"
        if fuente_evidencia is None:
            fuente_evidencia = fila.get("fuente") or fila.get("origen_tiempo")
        motivo_rechazo = motivo_rechazo or fila.get("motivo_rechazo")
        razones = fila.get("razones_apertura") if isinstance(fila.get("razones_apertura"), list) else []
    pipeline_pendiente = bool(fila.get("pipeline_pendiente"))
    if pipeline_pendiente:
        estado = "pendiente"
        valor = None
        motivo = "procesamiento_pendiente"
        estado_tiempo = "PENDIENTE_PIPELINE"
        motivo_rechazo = None
        decision_apertura = decision_apertura or "PENDIENTE"
    es_gris = estado == "gris"

    auto_evidencias = apertura.get("auto_color_evidencias") if apertura else None
    auto_evidencias = auto_evidencias if isinstance(auto_evidencias, list) else []
    scores_auto = []
    niveles_auto = []
    puertas_auto = {}
    puertas_fallidas_auto = []
    razones_auto = []
    riesgos_auto = []
    for evidencia in auto_evidencias:
        if not isinstance(evidencia, dict):
            continue
        try:
            score = float(evidencia.get("score_evidencia"))
            if math.isfinite(score):
                scores_auto.append(score)
        except (TypeError, ValueError, OverflowError):
            pass
        if evidencia.get("nivel"):
            niveles_auto.append(str(evidencia.get("nivel")))
        if isinstance(evidencia.get("puertas_decision"), dict):
            for k, v in evidencia.get("puertas_decision", {}).items():
                puertas_auto[str(k)] = bool(v) if str(k) not in puertas_auto else bool(puertas_auto[str(k)] and v)
        puertas_fallidas_auto.extend(str(x) for x in (evidencia.get("puertas_fallidas") or []))
        razones_auto.extend(str(x) for x in (evidencia.get("razones") or []))
        riesgos_auto.extend(str(x) for x in (evidencia.get("riesgos") or []))

    return {
        "tipo": "caso",
        "id": fila.get("id"),
        "test_number": _test_number(fila),
        "estado": estado,
        "motivo_estado": motivo,
        "pipeline_pendiente": pipeline_pendiente,
        "decision_apertura": decision_apertura,
        "estado_tiempo": estado_tiempo,
        "motivo_rechazo": motivo_rechazo,
        "raw_time_ms": raw_time_ms,
        "fuente_evidencia": fuente_evidencia,
        "razones_apertura": razones,
        "intervalo_tiempo_ms": apertura.get("intervalo_tiempo_ms") if apertura else fila.get("intervalo_tiempo_ms"),
        "resolucion_ms": apertura.get("resolucion_ms") if apertura else fila.get("resolucion_ms"),
        "incertidumbre_ms": apertura.get("incertidumbre_ms") if apertura else fila.get("incertidumbre_ms"),
        "opening_time_ms": (None if valor is None or es_gris else round(float(valor), 3)),
        "tiempo_pendiente_ms": (round(float(valor), 3) if es_gris and valor is not None else None),
        "tiempo_estimado_auto_ms": (apertura.get("tiempo_estimado_auto_ms") if apertura else None),
        "auto_color_elegible": bool(apertura.get("auto_color_elegible")) if apertura else False,
        "auto_color_soporte": apertura.get("auto_color_soporte") if apertura else None,
        "auto_color_prioridad": apertura.get("auto_color_prioridad") if apertura else None,
        "auto_color_score_max": (round(max(scores_auto), 6) if scores_auto else None),
        "auto_color_niveles": sorted(set(niveles_auto)),
        "auto_color_puertas": puertas_auto,
        "auto_color_puertas_fallidas": sorted(set(puertas_fallidas_auto)),
        "auto_color_razones": list(dict.fromkeys(razones_auto)),
        "auto_color_riesgos": list(dict.fromkeys(riesgos_auto)),
        "duracion_llenado_estimada_ms": apertura.get("duracion_llenado_estimada_ms") if apertura else None,
        "llenado_visual_soporte": apertura.get("llenado_visual_soporte") if apertura else None,
        "llenado_visual_conflicto": bool(apertura.get("llenado_visual_conflicto")) if apertura else False,
        "tiempo_max_inflado_estimado_ms": apertura.get("tiempo_max_inflado_estimado_ms") if apertura else None,
        "duracion_hasta_max_inflado_ms": apertura.get("duracion_hasta_max_inflado_ms") if apertura else None,
        "max_inflado_soporte": apertura.get("max_inflado_soporte") if apertura else None,
        "max_inflado_conflicto": bool(apertura.get("max_inflado_conflicto")) if apertura else False,
        "max_inflado_anomalias": list(apertura.get("max_inflado_anomalias") or []) if apertura else [],
        "max_inflado_estado": apertura.get("max_inflado_estado") if apertura else None,
        "tiempo_max_inflado_no_confirmado_ms": apertura.get("tiempo_max_inflado_no_confirmado_ms") if apertura else None,
        "tiempo_es_estimado": bool(decision_apertura == "PROPUESTA" and apertura.get("auto_color_elegible") is True and not es_gris),
        "color_fuente": ("estimacion_automatica_estandar_r11"
                         if decision_apertura == "PROPUESTA" and apertura.get("auto_color_elegible") is True and not es_gris
                         else "decision_confirmada" if decision_apertura in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"}
                         else "sin_color_confiable"),
        "color_motor_version": ("apertura-estandar-r13-v5"
                                if decision_apertura == "PROPUESTA" and apertura.get("auto_color_elegible") is True and not es_gris
                                else None),
        "enlace": fila.get("enlace"),
    }


def celda_vacante(indice: int) -> dict:
    """Constructor legado; V15.10 no lo usa en dashboard, Excel ni matriz dinámica."""
    return {"tipo": "vacante", "id": None, "test_number": None,
            "estado": "vacante", "motivo_estado": "sin_caso",
            "opening_time_ms": None, "enlace": None, "posicion": indice}


def agrupar_casos(filas: Iterable[dict]) -> tuple[dict[tuple[str, str], list[dict]], list[dict]]:
    """Separa los casos por columna de matriz y los que quedan sin clasificar."""
    por_columna: dict[tuple[str, str], list[dict]] = {c: [] for c in COMBINACIONES_MATRIZ}
    sin_clasificar: list[dict] = []
    for fila in filas:
        temp = str(fila.get("temperature_condition") or "").upper()
        gen = str(fila.get("inflator_type") or "").upper()
        etapa = str(fila.get("tipo_st") or "").upper()
        clave = (temp, gen)
        if etapa in {"1ST", "2ST"} and clave in COMBINACIONES_MATRIZ:
            por_columna[clave].append(fila)
        else:
            sin_clasificar.append(fila)
    for grupo in por_columna.values():
        grupo.sort(key=_clave_orden, reverse=True)
    sin_clasificar.sort(key=_clave_orden)
    return por_columna, sin_clasificar


def construir_columnas(filas_etapa: list[dict], criterio: dict) -> list[dict]:
    """Siete categorías dinámicas; cada celda representa exactamente un caso real.

    ``esperados`` se conserva como metadato legado de la plantilla BMG, pero no
    crea posiciones, cupos visibles ni celdas vacantes.
    """
    por_columna, _ = agrupar_casos(filas_etapa)
    columnas = []
    for spec in COLUMNAS_MATRIZ:
        grupo = por_columna[(spec["temperature_condition"], spec["inflator_type"])]
        celdas = [celda_caso(f, criterio) for f in grupo]
        columnas.append({**spec, "celdas": celdas, "ocupados": len(grupo),
                         "cupos": len(grupo), "esperados": int(spec["esperados"])})
    return columnas


def causa_sin_clasificar(fila: dict) -> str:
    """Causa legible por la que un caso queda fuera de las columnas de la matriz.

    V15.9.1 (B3): dashboard y Excel usan ESTA misma función, de modo que la
    paridad de IDs y motivos entre ambas vistas quede garantizada por
    construcción (etapas 3RD/LEGACY/ausentes y combinaciones fuera de columnas).
    """
    etapa = str(fila.get("tipo_st") or "").strip().upper()
    temp = str(fila.get("temperature_condition") or "").strip().upper()
    gen = str(fila.get("inflator_type") or "").strip().upper()
    if not etapa:
        return "Sin etapa declarada (tipo de prueba ausente)"
    if etapa not in {"1ST", "2ST"}:
        return f"Etapa fuera de matriz ({etapa})"
    if not temp and not gen:
        return f"{etapa}: sin temperatura ni generador declarados"
    if not temp:
        return f"{etapa}: sin temperatura de prueba declarada"
    if not gen:
        return f"{etapa}: sin tipo de generador declarado"
    return f"{etapa}: combinación {temp}/{gen} fuera de las columnas de la matriz"


def construir_sin_clasificar(filas_fuera: list[dict], criterio: dict) -> list[dict]:
    """Casos visibles fuera de las columnas: sin etapa/temperatura/generador verificable."""
    salida = []
    for fila in filas_fuera:
        celda = celda_caso(fila, criterio)
        celda.update({
            "tipo_st": fila.get("tipo_st"),
            "temperature_condition": fila.get("temperature_condition"),
            "inflator_type": fila.get("inflator_type"),
            "causa": causa_sin_clasificar(fila),
        })
        salida.append(celda)
    return salida


def construir_matriz_dashboard(filas: list[dict], criterio: dict,
                               origen: str | None = None) -> dict | None:
    """Matriz dinámica: una celda por caso real y sección aparte sin clasificar."""
    if not filas:
        return None
    etapas = []
    for tipo_st in ("1ST", "2ST"):
        etapa = [f for f in filas if str(f.get("tipo_st") or "").upper() == tipo_st]
        if not etapa:
            continue
        etapas.append({"tipo_st": tipo_st, "columnas": construir_columnas(etapa, criterio)})
    _, fuera = agrupar_casos(filas)
    sin_clasificar = construir_sin_clasificar(fuera, criterio)
    if not etapas and not sin_clasificar:
        return None
    todas = [c for e in etapas for col in e.get("columnas", []) for c in col.get("celdas", [])] + sin_clasificar
    pendientes = sum(1 for c in todas if c.get("estado") == "pendiente")
    return {
        "etapas": etapas,
        "sin_clasificar": sin_clasificar,
        "regla": regla_publica(criterio, origen),
        "criterio": dict(criterio),
        "origen_criterio": origen,
        "pendientes": pendientes,
        "tiene_pendientes": bool(pendientes),
        "casos_visibles": len(todas),
    }
