"""Contrato canónico de evidencia/decisión de caso (V15.10.1).

Este módulo proyecta los resultados existentes sin borrar campos ni cambiar
fuentes originales. Una lectura OCR o un consenso heurístico no se convierte
en auto-verificado por tener un score alto.
"""
from __future__ import annotations

import math
from typing import Any

VERSION_SCHEMA_RESULTADO = "resultado-caso-v1"
DECISIONES_CAMPO = {
    "VERIFICADO_HUMANO", "AUTO_VERIFICABLE", "PROPUESTA", "CONFLICTO",
    "NO_APLICA", "NO_OBSERVADO",
}


def _texto(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _milisegundos(v: Any) -> float | None:
    """Acepta ms numéricos/localizados, sin convertir valores inválidos en cero."""
    if v is None or isinstance(v, bool):
        return None
    texto = str(v).strip().casefold()
    if not texto or texto in {"--", "-"}:
        return None
    texto = texto.removesuffix("ms").strip().replace(",", ".")
    try:
        numero = float(texto)
    except (TypeError, ValueError, OverflowError):
        return None
    return numero if math.isfinite(numero) else None


def _raw_tiempos_coinciden(raw: Any, normalizado: Any) -> bool:
    """Compara raw con su proyección sin convertir no finitos ni reparar el signo."""
    def numero_crudo(valor: Any) -> float | None:
        if valor is None or isinstance(valor, bool):
            return None
        texto = str(valor).strip().casefold().removesuffix("ms").strip().replace(",", ".")
        if not texto:
            return None
        try:
            return float(texto)
        except (TypeError, ValueError, OverflowError):
            return None

    a, b = numero_crudo(raw), numero_crudo(normalizado)
    if a is not None and b is not None:
        if math.isnan(a) or math.isnan(b):
            return math.isnan(a) and math.isnan(b)
        if a == b:
            return True
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=0.0, abs_tol=1e-6)
    texto_raw = str(raw).strip().casefold().removesuffix("ms").strip().replace(",", ".")
    texto_normalizado = str(normalizado).strip().casefold().removesuffix("ms").strip().replace(",", ".")
    return bool(texto_raw) and texto_raw == texto_normalizado


def _tiempo_crudo_serializable(v: Any) -> Any:
    """Preserva el raw sin dejar NaN/Infinity como números JSON inválidos."""
    if v is None or isinstance(v, (str, int, bool)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else repr(v)
    try:
        escalar = v.item()
    except (AttributeError, ValueError):
        escalar = v
    if escalar is None or isinstance(escalar, (str, int, bool)):
        return escalar
    if isinstance(escalar, float):
        return escalar if math.isfinite(escalar) else repr(escalar)
    return str(v)


def _evento_censurado(registro: dict | None) -> bool:
    """True si la evidencia declara que el inicio real queda fuera del clip."""
    dato = registro if isinstance(registro, dict) else {}
    estados = {_texto(dato.get("estado")).casefold(),
               _texto(dato.get("estado_evento")).casefold(),
               _texto(dato.get("estado_operativo")).casefold()}
    return bool(dato.get("censurado_por_izquierda") or dato.get("evento_al_inicio")
                or estados & {"evento_al_inicio", "censurado", "censurado_por_izquierda"}
                or _texto(dato.get("estado_tiempo")).upper() == "CENSURADO")


def _referencia_tiempo_valida(registro: dict | None) -> bool:
    """Sólo reconoce una referencia explícitamente validada.

    Una marca ``False`` explícita prevalece sobre un estado heredado
    ``VALIDO``; no se debe rescatar una referencia que otro componente rechazó.
    """
    dato = registro if isinstance(registro, dict) else {}
    if "referencia_tiempo_valida" in dato:
        return dato.get("referencia_tiempo_valida") is True
    return dato.get("estado_tiempo") == "VALIDO"


def _estado_tiempo_invalido(valor: Any, referencia_valida: bool,
                            estado_origen: Any = None) -> str | None:
    """Clasifica un tiempo FINAL sin alterar el valor crudo ni su signo."""
    numero = _milisegundos(valor)
    if numero is not None and numero <= 0:
        return "NO_POSITIVO"
    if numero is None:
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            return "NO_INTERPRETABLE"
        try:
            candidato = float(str(valor).strip().casefold().removesuffix("ms").strip().replace(",", "."))
            if not math.isfinite(candidato):
                return "NO_FINITO"
        except (TypeError, ValueError, OverflowError):
            pass
        return "NO_INTERPRETABLE"
    estado = _texto(estado_origen).upper()
    if estado in {"NO_FINITO", "NO_POSITIVO", "NO_INTERPRETABLE",
                  "REFERENCIA_INVALIDA", "PENDIENTE", "CENSURADO"}:
        return estado
    if not referencia_valida:
        return "REFERENCIA_INVALIDA"
    return None


def _auditoria_tiempo(fuente: str, valor_crudo: Any, estado: str,
                      motivo: str, *, referencia_valida: bool = False,
                      afecta_decision: bool = True, **extra) -> dict:
    """Registro aditivo de rechazo; ``raw_time_ms`` conserva incluso texto/NaN."""
    dato = {
        "fuente": fuente,
        "tiempo_ms_crudo": _milisegundos(valor_crudo),
        "raw_time_ms": _tiempo_crudo_serializable(valor_crudo),
        "estado_tiempo": estado,
        "referencia_tiempo_valida": bool(referencia_valida),
        "motivo": motivo,
        "motivo_rechazo": motivo,
        "afecta_decision": bool(afecta_decision),
    }
    dato.update({k: v for k, v in extra.items() if v is not None})
    return dato


def _intervalo_positivo(intervalo: Any) -> list[float] | None:
    """Intervalo de tiempo final seguro; las cotas crudas quedan en la evidencia."""
    if not isinstance(intervalo, (list, tuple)) or len(intervalo) != 2:
        return None
    try:
        a, b = float(intervalo[0]), float(intervalo[1])
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(a) or not math.isfinite(b) or a <= 0 or b <= 0:
        return None
    return [round(min(a, b), 6), round(max(a, b), 6)]


def _valor_no_vacio(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, tuple, dict, set)):
        return bool(v)
    try:
        return not (isinstance(v, float) and math.isnan(v))
    except TypeError:
        return True


def _manual(campo: dict) -> bool:
    fuente = _texto(campo.get("fuente_preferida") or campo.get("fuente")).casefold()
    return bool(campo.get("confirmacion_manual") or campo.get("valor_confirmado_humano") is not None
                or campo.get("confirmado_por_usuario") or campo.get("decision_humana")
                or fuente in {"manual", "correccion_manual", "correccion_manual_confirmada"}
                or campo.get("estado") in {"extraido_manual", "confirmado_manual"})


def resolver_campo(campo: dict | None, *, campo_id: str = "",
                   min_evidencias_independientes: int = 2,
                   umbral_probabilidad_calibrada: float = 0.995) -> dict:
    """Proyecta un campo sin inferir calibración a partir de confianza OCR."""
    dato = campo if isinstance(campo, dict) else {}
    valor = dato.get("valor")
    decision_previa = _texto(dato.get("decision_v15_10")).upper()
    if decision_previa not in DECISIONES_CAMPO:
        decision_previa = ""
    razones: list[str] = []
    candidato_list = dato.get("candidatos") if isinstance(dato.get("candidatos"), list) else []
    estado_legacy = _texto(dato.get("estado")).casefold()
    requiere_revision = bool(dato.get("requiere_revision") or dato.get("requiere_confirmacion_manual"))

    if decision_previa:
        decision = decision_previa
        razones.extend(str(x) for x in dato.get("razones_decision_v15_10", []) if x)
    elif estado_legacy in {"conflicto", "inconsistente"} or dato.get("conflicto"):
        decision = "CONFLICTO"
        razones.append("hay_valores_o_fuentes_en_conflicto")
    elif estado_legacy in {"no_aplica", "no_aplicable"} or dato.get("no_aplica"):
        decision = "NO_APLICA"
        razones.append("marcado_expresamente_como_no_aplicable")
    elif _manual(dato) and (estado_legacy in {"conflicto", "pendiente_revision"}
                            or dato.get("conflicto") or dato.get("valor_seguro_ruta")):
        decision = "CONFLICTO"
        razones.append("correccion_humana_preservada_pero_queda_un_conflicto_explicito")
    elif _manual(dato) and requiere_revision:
        decision = "PROPUESTA"
        razones.append("confirmacion_humana_marcada_con_revision_pendiente")
    elif _manual(dato):
        decision = "VERIFICADO_HUMANO"
        razones.append("valor_confirmado_o_corregido_por_persona")
    elif estado_legacy.startswith("faltante") and not candidato_list:
        decision = "NO_OBSERVADO"
        razones.append("campo_sin_evidencia_observada")
    elif not _valor_no_vacio(valor):
        if candidato_list or requiere_revision or estado_legacy in {"pendiente", "propuesto", "sin_consenso"}:
            decision = "PROPUESTA"
            razones.append("hay_evidencia_pendiente_sin_valor_confirmado")
        else:
            decision = "NO_OBSERVADO"
            razones.append("sin_valor_ni_evidencia_observable")
    else:
        p = dato.get("probabilidad_calibrada")
        try:
            p = float(p)
        except (TypeError, ValueError):
            p = None
        n_ind = dato.get("evidencias_independientes")
        try:
            n_ind = int(n_ind)
        except (TypeError, ValueError):
            n_ind = 0
        calibrada = bool(dato.get("calibracion_validada"))
        reglas_ok = bool(dato.get("reglas_deterministas_aprobadas"))
        calidad_ok = bool(dato.get("calidad_fuente_validada"))
        independientes_ok = n_ind >= max(2, int(min_evidencias_independientes))
        prob_ok = p is not None and math.isfinite(p) and p >= umbral_probabilidad_calibrada
        if calibrada and reglas_ok and calidad_ok and independientes_ok and prob_ok and not requiere_revision:
            decision = "AUTO_VERIFICABLE"
            razones.append("gates_explicitos_de_calibracion_y_evidencia_independiente_cumplidos")
        else:
            decision = "PROPUESTA"
            razones.append("confianza_ocr_o_consenso_no_equivale_a_probabilidad_calibrada")
            if requiere_revision:
                razones.append("revision_humana_pendiente")
            if not calibrada:
                razones.append("calibracion_no_validada_en_datos_reservados")
            if not independientes_ok:
                razones.append("evidencias_independientes_insuficientes")
    if decision not in DECISIONES_CAMPO:
        decision = "NO_OBSERVADO"
        razones.append("decision_fuera_del_contrato_falla_cerrado")

    fuentes = dato.get("fuentes") if isinstance(dato.get("fuentes"), list) else []
    evidencia = []
    for item in fuentes[:5]:
        if not isinstance(item, dict):
            continue
        evidencia.append({k: item.get(k) for k in (
            "fuente", "imagen", "video", "fase", "tor", "bbox_original", "clave")
            if item.get(k) is not None})
    if not evidencia and dato.get("fuente"):
        evidencia.append({"fuente": dato.get("fuente")})
    return {
        "campo_id": campo_id,
        "valor": valor if _valor_no_vacio(valor) else None,
        "decision": decision,
        "estado_origen": dato.get("estado"),
        "fuente_preferida": dato.get("fuente_preferida") or dato.get("fuente"),
        "evidencias": evidencia,
        "cantidad_candidatos": len(candidato_list),
        "cantidad_fuentes": len(fuentes),
        "probabilidad_calibrada": dato.get("probabilidad_calibrada"),
        "requiere_revision": decision in {"PROPUESTA", "CONFLICTO"} or requiere_revision,
        "razones": list(dict.fromkeys(razones)),
    }


def resolver_apertura(fila: dict | None) -> dict:
    """Estructura la apertura sin elevar raw, offsets o censura a tiempos finales."""
    dato = fila if isinstance(fila, dict) else {}
    campos = dato.get("campos") if isinstance(dato.get("campos"), dict) else {}
    videos = dato.get("videos") if isinstance(dato.get("videos"), list) else []
    video = dato.get("video_apertura") if isinstance(dato.get("video_apertura"), dict) else {}
    campo_original = campos.get("opening_time_ms")
    campo = (campo_original if isinstance(campo_original, dict) else
             {"valor": campo_original} if _valor_no_vacio(campo_original) else {})

    manuales: list[float] = []
    automaticos: list[float] = []
    propuestas: list[dict] = []
    revisiones_temporales_invalidas: list[dict] = []
    candidatos_sombra: list[dict] = []
    auto_color_estimaciones: list[dict] = []
    llenado_estimaciones: list[dict] = []
    max_inflado_estimaciones: list[dict] = []
    eventos_inicio: list[str] = []
    estados_sin_evento: list[str] = []
    tiene_evidencia_temporal = False

    def _presente(v: Any) -> bool:
        return v is not None and not (isinstance(v, str) and v.strip() in {"", "--", "-"})

    def _auditar(fuente: str, raw: Any, referencia: bool, motivo: str,
                 *, estado: str | None = None, afecta: bool = True, **extra) -> None:
        clasificacion = estado or _estado_tiempo_invalido(raw, referencia)
        if clasificacion is None:
            clasificacion = "PENDIENTE"
        revisiones_temporales_invalidas.append(_auditoria_tiempo(
            fuente, raw, clasificacion, motivo, referencia_valida=referencia,
            afecta_decision=afecta, **extra))

    def _proponer(raw: Any, registro: dict, fuente: str, intervalo: Any = None) -> bool:
        valor = _milisegundos(raw)
        referencia = _referencia_tiempo_valida(registro)
        estado = _estado_tiempo_invalido(raw, referencia, registro.get("estado_tiempo"))
        if estado is not None:
            motivo = (registro.get("motivo_rechazo") or {
                "NO_POSITIVO": "El tiempo final de apertura debe ser estrictamente mayor que cero.",
                "NO_FINITO": "El tiempo final de apertura debe ser finito.",
                "NO_INTERPRETABLE": "El tiempo final de apertura no se puede interpretar como milisegundos.",
                "REFERENCIA_INVALIDA": "La referencia temporal no está validada; se conserva el raw para revisión.",
                "PENDIENTE": "La referencia temporal sigue pendiente de validación.",
            }.get(estado, "El tiempo final no cumple el contrato temporal."))
            _auditar(fuente, raw, referencia, motivo, estado=estado,
                     afecta=(fuente.startswith("campo_manual") or fuente.startswith("revision_manual")))
            return False
        if valor is None or not math.isfinite(valor) or valor <= 0:
            return False
        propuestas.append({"valor": valor, "fuente": fuente,
                           "intervalo": _intervalo_positivo(intervalo),
                           "referencia_tiempo_valida": True})
        return True

    # Revisión manual individual: manda sólo con tiempo > 0, cuadro y referencia
    # temporal explícitamente válidos. El raw histórico nunca se recalcula.
    for item in videos:
        if not isinstance(item, dict):
            continue
        rev = item.get("revision_manual") if isinstance(item.get("revision_manual"), dict) else {}
        evento_censurado_item = _evento_censurado(item)
        evaluacion_estandar = (item.get("evaluacion_apertura_estandar")
                               if isinstance(item.get("evaluacion_apertura_estandar"), dict) else {})
        llenado_item = item.get("llenado_visual") if isinstance(item.get("llenado_visual"), dict) else {}
        secuencia_item = item.get("secuencia_despliegue_r13") if isinstance(item.get("secuencia_despliegue_r13"), dict) else {}
        tiempo_max_item = _milisegundos(secuencia_item.get("tiempo_max_inflado_ms"))
        duracion_max_item = _milisegundos(secuencia_item.get("duracion_expansion_ms"))
        # R15.1 (MEDIO-09): se recoge toda evidencia con frame de máximo
        # (incluida la censurada de 0 ms, por auditabilidad), etiquetada con
        # el estado de la secuencia; la métrica confirmada del caso sólo se
        # calcula sobre estado == "maximo_inflado_estimado".
        if (secuencia_item.get("frame_max_inflado") is not None
                and tiempo_max_item is not None and tiempo_max_item >= 0):
            max_inflado_estimaciones.append({
                "video": item.get("id") or item.get("nombre"),
                "estado_secuencia": str(secuencia_item.get("estado") or "sin_estado"),
                "frame_breakout": secuencia_item.get("frame_breakout"),
                "frame_max_inflado": secuencia_item.get("frame_max_inflado"),
                "tiempo_max_inflado_ms": tiempo_max_item,
                "duracion_expansion_ms": duracion_max_item,
                "confianza_maximo": secuencia_item.get("confianza_maximo"),
                "anomalias": list(secuencia_item.get("anomalías") or []),
                "tiempo_relativo_inicio_video": True,
            })
        duracion_llenado = _milisegundos(llenado_item.get("duracion_llenado_ms"))
        if (llenado_item.get("estado") == "meseta_visual_estimada"
                and duracion_llenado is not None and duracion_llenado >= 0):
            llenado_estimaciones.append({
                "video": item.get("id") or item.get("nombre"),
                "duracion_ms": duracion_llenado,
                "frame_llenado": llenado_item.get("frame_llenado"),
                "frame_onset": item.get("frame_color_estimado", item.get("frame_evento")),
                "estado": llenado_item.get("estado"),
            })
        # R10: el color estimado tiene su propio contrato temporal. Puede usar
        # frame/FPS de captura confiable aunque todavía no exista sincronización
        # multicámara publicable. Nunca se reutilizan 8 fps de reproducción.
        referencia_color = (item.get("referencia_color_valida") is True
                            or ("referencia_color_valida" not in item
                                and _referencia_tiempo_valida(item)))
        raw_auto_color = item.get("tiempo_color_estimado_ms")
        if raw_auto_color is None:
            raw_auto_color = item.get("tiempo_ms")
        if (evaluacion_estandar.get("auto_colorable") is True
                and not evento_censurado_item
                and referencia_color):
            valor_auto = _milisegundos(raw_auto_color)
            if valor_auto is not None and math.isfinite(valor_auto) and valor_auto > 0:
                tiene_evidencia_temporal = True
                auto_color_estimaciones.append({
                    "valor": valor_auto,
                    "score_evidencia": evaluacion_estandar.get("score_evidencia"),
                    "nivel": evaluacion_estandar.get("nivel"),
                    "video": item.get("id") or item.get("nombre"),
                    "frame": item.get("frame_color_estimado", item.get("frame_evento")),
                    "resolucion_ms": item.get("resolucion_nativa_ms"),
                    "fuente_tiempo_color": item.get("fuente_tiempo_color"),
                    "referencia_color_valida": True,
                    "version_estandar": evaluacion_estandar.get("version_estandar"),
                    "puertas_decision": evaluacion_estandar.get("puertas_decision"),
                    "puertas_fallidas": evaluacion_estandar.get("puertas_fallidas"),
                    "razones": evaluacion_estandar.get("razones"),
                    "riesgos": evaluacion_estandar.get("riesgos"),
                })
        if evento_censurado_item:
            eventos_inicio.append(item.get("id") or item.get("nombre"))
            raw_sospechoso = item.get("tiempo_ms_sospechoso")
            if raw_sospechoso is None:
                raw_sospechoso = item.get("tiempo_crudo_ms")
            if raw_sospechoso is None:
                raw_sospechoso = item.get("tiempo_ms")
            tiene_evidencia_temporal = tiene_evidencia_temporal or _presente(raw_sospechoso)
            _auditar(
                "evento_censurado_video", raw_sospechoso,
                _referencia_tiempo_valida(item),
                item.get("motivo_rechazo") or "Evento visible al inicio del clip: el nacimiento queda censurado a la izquierda.",
                estado="CENSURADO", afecta=False,
                video=item.get("id") or item.get("nombre"),
                frame_index=item.get("frame_evento"))
        if rev.get("estado") == "confirmado":

            tiene_evidencia_temporal = True
            raw_revision = rev.get("raw_time_ms")
            if raw_revision is None:
                raw_revision = rev.get("tiempo_ms")
            referencia = _referencia_tiempo_valida(rev)
            estado = ("CENSURADO" if evento_censurado_item else
                      _estado_tiempo_invalido(raw_revision, referencia, rev.get("estado_tiempo")))
            try:
                frame_manual_valido = (rev.get("frame_index") is not None
                                       and int(rev.get("frame_index")) >= 0)
            except (TypeError, ValueError, OverflowError):
                frame_manual_valido = False
            if not frame_manual_valido and estado is None:
                estado = "REFERENCIA_INVALIDA"
            if estado is not None:
                motivo = rev.get("motivo_rechazo") or {
                    "NO_POSITIVO": "El tiempo final de apertura debe ser estrictamente mayor que cero.",
                    "NO_FINITO": "El tiempo final de apertura debe ser finito.",
                    "NO_INTERPRETABLE": "La revisión manual no conserva un tiempo interpretable.",
                    "REFERENCIA_INVALIDA": "La revisión manual no tiene cuadro o referencia temporal validada.",
                    "PENDIENTE": "La referencia temporal de la revisión manual sigue pendiente.",
                    "CENSURADO": "El evento está al inicio del clip; no hay evidencia previa para estimar su nacimiento.",
                }.get(estado, "La revisión manual no es publicable como tiempo final.")
                _auditar("revision_manual_video", raw_revision, referencia, motivo,
                         estado=estado, afecta=not evento_censurado_item,
                         video=item.get("id") or item.get("nombre"),
                         frame_index=rev.get("frame_index"))
            else:
                valor = _milisegundos(raw_revision)
                if valor is not None and valor > 0:
                    manuales.append(valor)
        if rev.get("estado") == "sin_evento":
            estados_sin_evento.append(item.get("id") or item.get("nombre"))

        # Las detecciones automáticas individuales no son un consenso. Si su
        # referencia o signo es inválido quedan como evidencia, no como propuesta.
        if rev.get("estado") != "confirmado" and item.get("estado") == "candidato":
            raw_candidato = item.get("tiempo_crudo_ms")
            if raw_candidato is None:
                raw_candidato = item.get("tiempo_ms")
            if _presente(raw_candidato):
                tiene_evidencia_temporal = True
                referencia = _referencia_tiempo_valida(item)
                estado = _estado_tiempo_invalido(
                    raw_candidato, referencia, item.get("estado_tiempo"))
                if estado is not None:
                    _auditar(
                        "candidato_video", raw_candidato, referencia,
                        item.get("motivo_rechazo") or (
                            "El tiempo candidato no es positivo." if estado == "NO_POSITIVO" else
                            "La referencia temporal del candidato no está validada."),
                        estado=estado, afecta=False,
                        video=item.get("id") or item.get("nombre"),
                        frame_index=item.get("frame_evento"))

        cand = item.get("candidatos_apertura_sombra")
        if isinstance(cand, list):
            for candidato in cand:
                if not isinstance(candidato, dict):
                    continue
                expandido = {**candidato, "video_id": item.get("id"),
                             "video": item.get("nombre")}
                candidatos_sombra.append(expandido)
                raw_local = candidato.get("tiempo_local_ms")
                if raw_local is None:
                    raw_local = candidato.get("tiempo_crudo_ms")
                if _presente(raw_local):
                    tiene_evidencia_temporal = True
                    estado = _estado_tiempo_invalido(raw_local, False)
                    estado = estado or "REFERENCIA_INVALIDA"
                    _auditar(
                        "candidato_sombra", raw_local, False,
                        "Tiempo local de sombra sin referencia sincronizada; se conserva como hipótesis, no como propuesta final.",
                        estado=estado, afecta=False,
                        video=item.get("id") or item.get("nombre"),
                        frame_index=candidato.get("frame"))

    # Valor agregado de video. Se admite como candidato normal sólo si su
    # tiempo final es positivo y la referencia fue validada; una lectura de
    # overlay por sí sola se conserva en campos crudos separados.
    campo_estado = _texto(campo.get("estado")).casefold()
    campo_decision_previa = _texto(campo.get("decision_v15_10")).upper()
    conflicto_campo = (campo_decision_previa == "CONFLICTO"
                       or campo_estado in {"conflicto", "inconsistente"}
                       or bool(campo.get("conflicto")))

    estado_video = _texto(video.get("estado")).casefold()
    video_censurado = _evento_censurado(video)
    if video_censurado:
        eventos_inicio.append(video.get("video_id") or video.get("id") or "video_apertura")
    video_manual = estado_video == "confirmado_manual"
    video_time_key = ("tiempo_propuesto_ms" if _presente(video.get("tiempo_propuesto_ms"))
                      else "tiempo_ms")
    video_raw = video.get(video_time_key)
    video_raw_only = False
    if not _presente(video_raw):
        for clave_raw in ("tiempo_crudo_ms", "raw_time_ms", "tiempo_ms_sospechoso"):
            video_raw = video.get(clave_raw)
            if _presente(video_raw):
                video_raw_only = True
                break
    if video_censurado:
        _auditar(
            "video_apertura_censurado", video_raw,
            _referencia_tiempo_valida(video),
            video.get("motivo_rechazo") or "Evento visible al inicio del clip: el nacimiento queda censurado a la izquierda.",
            estado="CENSURADO", afecta=False,
            video=video.get("video_id") or video.get("id"),
            frame_index=video.get("frame_evento"))
    if _presente(video_raw):
        tiene_evidencia_temporal = True
        referencia = _referencia_tiempo_valida(video)
        if video_censurado:
            pass  # Raw auditado arriba; nunca se convierte en propuesta.
        elif video_raw_only:
            estado = _estado_tiempo_invalido(video_raw, referencia, video.get("estado_tiempo"))
            estado = estado or "PENDIENTE"
            _auditar("video_apertura_raw", video_raw, referencia,
                     video.get("motivo_rechazo") or "El tiempo crudo no está declarado como tiempo final/propuesta.",
                     estado=estado, afecta=False)
        elif video_manual:
            estado = _estado_tiempo_invalido(video_raw, referencia, video.get("estado_tiempo"))
            if estado is None:
                valor = _milisegundos(video_raw)
                if valor is not None and valor > 0:
                    manuales.append(valor)
            else:
                motivo = video.get("motivo_rechazo") or {
                    "NO_POSITIVO": "El tiempo final de apertura debe ser estrictamente mayor que cero.",
                    "NO_FINITO": "El tiempo final de apertura debe ser finito.",
                    "NO_INTERPRETABLE": "El tiempo final de apertura no se puede interpretar como milisegundos.",
                    "REFERENCIA_INVALIDA": "La referencia temporal del consenso manual no está validada.",
                    "PENDIENTE": "La referencia temporal del consenso manual sigue pendiente.",
                }.get(estado, "El tiempo manual agregado no es publicable.")
                _auditar("video_apertura_manual", video_raw, referencia, motivo,
                         estado=estado, afecta=True)
        elif estado_video not in {"sin_evento", "sin_datos", "no_observado"}:
            # V16.0.14: un mismo verificador para consenso y matriz.
            # V16.0.7 permitía dos cámaras pero ataba esa ruta al sello v3;
            # V16.0.13 trae un sello distinto. El motor debe demostrar
            # independencia, origen temporal y evidencia física vigente.
            # No se publica sólo por soporte >=2 o por una ROI sugerida.
            try:
                from video_airbag import consenso_valido
                auto_consenso_valido = bool(consenso_valido(video))
            except (ImportError, AttributeError, TypeError, ValueError,
                    RuntimeError, OverflowError):
                auto_consenso_valido = False
            causas_auto = video.get("causas_revision_consolidado")
            causas_auto = causas_auto if isinstance(causas_auto, list) else []
            auto_consenso_valido = bool(
                auto_consenso_valido
                and str(video.get("estado_consenso") or "").casefold() == "confirmado"
                and referencia
                and video.get("requiere_revision") is not True
                and video.get("revision_no_clasificada") is not True
                and not causas_auto
            )
            if auto_consenso_valido:
                valor = _milisegundos(video_raw)
                if valor is not None and math.isfinite(valor) and valor > 0:
                    automaticos.append(valor)
                else:
                    _proponer(video_raw, video, "video_apertura", video.get("intervalo_tiempo_ms"))
            else:
                _proponer(video_raw, video, "video_apertura", video.get("intervalo_tiempo_ms"))

    # Campo empresarial/manual. Una referencia ausente no se presume válida;
    # raw_time_ms se audita incluso cuando el campo normalizado está vacío.
    valor_campo = campo.get("valor")
    raw_campo = campo.get("raw_time_ms")
    campo_tiene_valor = _presente(valor_campo)
    campo_tiene_raw = _presente(raw_campo)
    candidato_campo = valor_campo if campo_tiene_valor else raw_campo
    if campo_tiene_valor or campo_tiene_raw:
        tiene_evidencia_temporal = True
        legacy_manual_sin_metadata = bool(
            _manual(campo)
            and "referencia_tiempo_valida" not in campo
            and not campo.get("estado_tiempo")
        )
        referencia_campo = _referencia_tiempo_valida(campo) or legacy_manual_sin_metadata
        if not campo_tiene_valor and campo_tiene_raw:
            estado = _estado_tiempo_invalido(raw_campo, referencia_campo, campo.get("estado_tiempo"))
            estado = estado or "PENDIENTE"
            _auditar("opening_time_ms_raw", raw_campo, referencia_campo,
                     campo.get("motivo_rechazo") or "El raw se conserva en auditoría y no figura como valor normalizado.",
                     estado=estado, afecta=True)
        else:
            estado = _estado_tiempo_invalido(
                candidato_campo, referencia_campo, campo.get("estado_tiempo"))
            if campo_tiene_raw and campo_tiene_valor:
                if not _raw_tiempos_coinciden(raw_campo, valor_campo):
                    conflicto_campo = True
                    if estado is None:
                        estado = _estado_tiempo_invalido(raw_campo, False) or "REFERENCIA_INVALIDA"
                    _auditar(
                        "opening_time_ms_raw", raw_campo, False,
                        "El valor normalizado contradice el raw; ambos se conservan y requieren revisión.",
                        estado=estado, afecta=True)
            if estado is not None:
                motivo = campo.get("motivo_rechazo") or {
                    "NO_POSITIVO": "El tiempo final de apertura debe ser estrictamente mayor que cero.",
                    "NO_FINITO": "El tiempo final de apertura debe ser finito.",
                    "NO_INTERPRETABLE": "El tiempo final de apertura no se puede interpretar como milisegundos.",
                    "REFERENCIA_INVALIDA": "La referencia temporal del campo no está validada; el raw queda sólo en auditoría.",
                    "PENDIENTE": "La referencia temporal del campo sigue pendiente de validación.",
                }.get(estado, "El campo temporal requiere revisión.")
                raw_auditoria = raw_campo if campo_tiene_raw else candidato_campo
                _auditar("opening_time_ms", raw_auditoria, referencia_campo,
                         motivo, estado=estado, afecta=True,
                         fuente_campo=campo.get("fuente_preferida") or campo.get("fuente"))
            else:
                valor = _milisegundos(candidato_campo)
                if valor is not None and valor > 0:
                    campo_humano = (_manual(campo) and not conflicto_campo
                                    and not bool(campo.get("requiere_revision")
                                                 or campo.get("requiere_confirmacion_manual")))
                    if campo_humano:
                        manuales.append(valor)
                    else:
                        propuestas.append({
                            "valor": valor, "fuente": "opening_time_ms",
                            "intervalo": _intervalo_positivo(campo.get("intervalo_tiempo_ms")),
                            "referencia_tiempo_valida": True,
                        })

    manuales_unicos = sorted(set(round(x, 6) for x in manuales if math.isfinite(x) and x > 0))
    automaticos_unicos = sorted(set(round(x, 6) for x in automaticos if math.isfinite(x) and x > 0))
    auto_color_valores = sorted(
        float(x["valor"]) for x in auto_color_estimaciones
        if isinstance(x, dict) and _milisegundos(x.get("valor")) is not None and float(x["valor"]) > 0
    )
    if auto_color_valores:
        mitad = len(auto_color_valores) // 2
        if len(auto_color_valores) % 2:
            tiempo_auto_color = auto_color_valores[mitad]
        else:
            tiempo_auto_color = (auto_color_valores[mitad - 1] + auto_color_valores[mitad]) / 2.0
        resoluciones_auto = [_milisegundos(x.get("resolucion_ms")) for x in auto_color_estimaciones]
        resoluciones_auto = [x for x in resoluciones_auto if x is not None and x > 0]
        tolerancia_auto = max([0.5] + resoluciones_auto)
        conflicto_auto_color = ((max(auto_color_valores) - min(auto_color_valores)) > tolerancia_auto
                               if len(auto_color_valores) > 1 else False)
    else:
        tiempo_auto_color = None
        tolerancia_auto = 0.5
        conflicto_auto_color = False
    llenado_valores = sorted(float(x["duracion_ms"]) for x in llenado_estimaciones
                              if _milisegundos(x.get("duracion_ms")) is not None)
    if llenado_valores:
        mitad_ll = len(llenado_valores) // 2
        duracion_llenado_estimada = (llenado_valores[mitad_ll] if len(llenado_valores) % 2
                                     else (llenado_valores[mitad_ll - 1] + llenado_valores[mitad_ll]) / 2.0)
        tolerancia_llenado = max(0.5, duracion_llenado_estimada * 0.25)
        conflicto_llenado = ((max(llenado_valores) - min(llenado_valores)) > tolerancia_llenado
                             if len(llenado_valores) > 1 else False)
    else:
        duracion_llenado_estimada = None
        tolerancia_llenado = 0.5
        conflicto_llenado = False

    # R15.1 (MEDIO-09): agregación separada por estado explícito; nunca se
    # mezcla un máximo no confirmado en la mediana confirmada del caso.
    max_inflado_confirmadas = [x for x in max_inflado_estimaciones
                               if x.get("estado_secuencia") == "maximo_inflado_estimado"]
    max_inflado_no_confirmadas = [x for x in max_inflado_estimaciones
                                  if x.get("estado_secuencia") == "maximo_visible_observado_no_confirmado"]
    max_tiempos = sorted(float(x["tiempo_max_inflado_ms"]) for x in max_inflado_confirmadas
                         if _milisegundos(x.get("tiempo_max_inflado_ms")) is not None)
    max_duraciones = sorted(float(x["duracion_expansion_ms"]) for x in max_inflado_confirmadas
                            if _milisegundos(x.get("duracion_expansion_ms")) is not None)
    max_tiempos_nc = sorted(float(x["tiempo_max_inflado_ms"]) for x in max_inflado_no_confirmadas
                            if _milisegundos(x.get("tiempo_max_inflado_ms")) is not None)
    def _mediana(lista):
        if not lista:
            return None
        m=len(lista)//2
        return lista[m] if len(lista)%2 else (lista[m-1]+lista[m])/2.0
    tiempo_max_inflado_estimado = _mediana(max_tiempos)
    duracion_hasta_max_inflado = _mediana(max_duraciones)
    tiempo_max_inflado_no_confirmado = _mediana(max_tiempos_nc)
    if max_inflado_confirmadas:
        max_inflado_estado_caso = "maximo_inflado_estimado"
    elif max_inflado_no_confirmadas:
        max_inflado_estado_caso = "maximo_visible_observado_no_confirmado"
    elif max_inflado_estimaciones:
        max_inflado_estado_caso = "sin_maximo_defendible"
    else:
        max_inflado_estado_caso = None
    tolerancia_max = max(0.5, (duracion_hasta_max_inflado or 0.0) * 0.25)
    conflicto_max_inflado = bool(len(max_tiempos) > 1 and (max(max_tiempos)-min(max_tiempos)) > tolerancia_max)
    anomalias_max_inflado = list(dict.fromkeys(
        str(a) for x in max_inflado_estimaciones for a in (x.get("anomalias") or []) if a
    ))

    manual_sin_evento = [v for v in videos if isinstance(v, dict)
                         and isinstance(v.get("revision_manual"), dict)
                         and v["revision_manual"].get("estado") == "sin_evento"]
    sin_apertura_manual_completo = bool(videos) and len(manual_sin_evento) == len(videos)
    audit_blocking = any(x.get("afecta_decision") for x in revisiones_temporales_invalidas)
    audit_humano_bloqueante = any(
        x.get("afecta_decision") and (
            str(x.get("fuente") or "").startswith("revision_manual")
            or str(x.get("fuente") or "") == "video_apertura_manual"
            or (str(x.get("fuente") or "") == "opening_time_ms"
                and str(x.get("fuente_campo") or "").casefold() in {
                    "manual", "correccion_manual", "correccion_manual_confirmada"})
        )
        for x in revisiones_temporales_invalidas
    )
    # Un campo derivado/legacy inválido NO puede degradar una fuente de mayor
    # jerarquía ya verificada. Las contradicciones humanas explícitas sí se
    # conservan. Esto evita que el mismo consenso 3/4 aparezca verde en video
    # y gris en matriz/Excel por un raw de campo sin metadata temporal.
    campo_conflicto_humano = bool(conflicto_campo and _manual(campo))
    razones: list[str] = []
    propuesta_valida = propuestas[0] if propuestas else None
    if sin_apertura_manual_completo and not manuales_unicos:
        decision = "NO_APLICA"
        tiempo = None
        intervalo = None
        razones.append("no_apertura_confirmada_manualmente_en_todas_las_vistas")
    elif len(manuales_unicos) > 1:
        decision = "CONFLICTO"
        tiempo = None
        intervalo = [min(manuales_unicos), max(manuales_unicos)]
        razones.append("confirmaciones_humanas_discrepantes_requieren_resolucion")
    elif audit_humano_bloqueante:
        decision = "PROPUESTA"
        tiempo = None
        intervalo = None
        propuesta_valida = None
        razones.append("revision_humana_temporal_invalida_requiere_resolucion")
        razones.append("el_valor_crudo_se_conserva_sin_reparacion_automatica")
    elif manuales_unicos and not campo_conflicto_humano:
        decision = "VERIFICADO_HUMANO"
        tiempo = manuales_unicos[0]
        intervalo = _intervalo_positivo(video.get("intervalo_tiempo_ms")) or _intervalo_positivo(campo.get("intervalo_tiempo_ms"))
        razones.append("tiempo_confirmado_humanamente_con_referencia_temporal_valida")
        if audit_blocking:
            razones.append("auditoria_de_fuente_inferior_conservada_sin_degradar_confirmacion_humana")
    elif conflicto_campo:
        decision = "CONFLICTO"
        tiempo = None
        intervalo = _intervalo_positivo(campo.get("intervalo_tiempo_ms"))
        razones.append("el_campo_de_apertura_conserva_un_conflicto_no_resuelto")
    elif len(automaticos_unicos) > 1:
        decision = "CONFLICTO"
        tiempo = None
        intervalo = [min(automaticos_unicos), max(automaticos_unicos)]
        razones.append("consensos_automaticos_discrepantes_requieren_revision")
    elif automaticos_unicos:
        decision = "AUTO_VERIFICABLE"
        tiempo = automaticos_unicos[0]
        intervalo = _intervalo_positivo(video.get("intervalo_tiempo_ms"))
        razones.append("consenso_automatico_dos_camaras_con_regla_vigente_y_referencia_validada")
        if audit_blocking:
            razones.append("auditoria_de_fuente_inferior_conservada_sin_degradar_consenso_valido")
    elif audit_blocking:
        decision = "PROPUESTA"
        tiempo = None
        intervalo = None
        propuesta_valida = None
        razones.append("evidencia_temporal_invalida_o_sin_referencia_requiere_revision")
        razones.append("el_valor_crudo_se_conserva_sin_reparacion_automatica")
    elif eventos_inicio:
        decision = "PROPUESTA"
        tiempo = None
        intervalo = None
        propuesta_valida = None
        razones.append("evento_censurado_al_inicio_falta_evidencia_previa")
    elif propuesta_valida:
        decision = "PROPUESTA"
        tiempo = propuesta_valida["valor"]
        intervalo = propuesta_valida.get("intervalo")
        razones.append("tiempo_positivo_con_referencia_valida_pero_pendiente_de_confirmacion")
    elif tiene_evidencia_temporal or candidatos_sombra or revisiones_temporales_invalidas:
        decision = "PROPUESTA"
        tiempo = None
        intervalo = None
        razones.append("evidencia_temporal_cruda_no_publicable_como_tiempo_final")
        if candidatos_sombra:
            razones.append("hipotesis_local_en_modo_sombra_sin_sincronizacion_multicamara")
    elif videos and len(estados_sin_evento) == len(videos):
        decision = "NO_OBSERVADO"
        tiempo = None
        intervalo = None
        razones.append("todas_las_vistas_reportan_sin_evento; no_certifica_ausencia_fisica")
    else:
        decision = "NO_OBSERVADO"
        tiempo = None
        intervalo = None
        razones.append("sin_tiempo_confirmado_ni_hipotesis_disponible")

    if decision == "PROPUESTA" and tiempo is not None:
        razones.append("valor_no_publicable_como_tiempo_confirmado_v15_10")
    # Los registros que realmente determinan el tiempo aparecen primero para
    # que la matriz/Excel presenten el motivo pertinente, no una hipótesis sombra.
    revisiones_temporales_invalidas.sort(
        key=lambda x: (not bool(x.get("afecta_decision")), str(x.get("fuente") or "")))
    resolucion = video.get("resolucion_nativa_ms")
    if resolucion is None and candidatos_sombra:
        resolucion = candidatos_sombra[0].get("resolucion_ms")
    try:
        resolucion = float(resolucion) if resolucion is not None else None
        if resolucion is not None and (not math.isfinite(resolucion) or resolucion <= 0):
            resolucion = None
    except (TypeError, ValueError, OverflowError):
        resolucion = None

    primaria_invalida = next((x for x in revisiones_temporales_invalidas if isinstance(x, dict)), {})
    raw_publico = primaria_invalida.get("raw_time_ms")
    if raw_publico is None:
        if decision in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"}:
            raw_publico = tiempo
        elif propuesta_valida:
            raw_publico = propuesta_valida.get("valor")
        elif candidatos_sombra:
            raw_publico = _tiempo_crudo_serializable(candidatos_sombra[0].get("tiempo_local_ms"))
        else:
            raw_publico = _tiempo_crudo_serializable(campo.get("raw_time_ms") or campo.get("valor"))
    estado_tiempo = (primaria_invalida.get("estado_tiempo") or
                     "VALIDO" if decision in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"} else
                     "PENDIENTE" if decision == "PROPUESTA" else
                     "CONFLICTO" if decision == "CONFLICTO" else "SIN_MEDICION")
    if primaria_invalida.get("estado_tiempo"):
        estado_tiempo = primaria_invalida["estado_tiempo"]
    motivo_rechazo = primaria_invalida.get("motivo") or primaria_invalida.get("motivo_rechazo")
    referencia_publica = bool(
        decision in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"}
        or (propuesta_valida is not None and propuesta_valida.get("referencia_tiempo_valida") is True)
    )
    estado_operativo = ("sin_apertura_confirmada_manual"
                        if decision == "NO_APLICA" and sin_apertura_manual_completo
                        else decision.casefold())
    fuente_publica = ("revision_humana" if decision == "VERIFICADO_HUMANO" else
                      "video_airbag_consenso" if decision == "AUTO_VERIFICABLE" else
                      propuesta_valida.get("fuente") if propuesta_valida else
                      primaria_invalida.get("fuente_campo") or primaria_invalida.get("fuente") or "")
    candidatos_resumen = []
    for c in candidatos_sombra[:5]:
        raw_local = c.get("tiempo_local_ms")
        estado_local = _estado_tiempo_invalido(raw_local, False) or "REFERENCIA_INVALIDA"
        candidatos_resumen.append({
            "video_id": c.get("video_id"), "video": c.get("video"),
            "frame": c.get("frame"),
            "tiempo_local_ms": _tiempo_crudo_serializable(raw_local),
            "tiempo_crudo_ms": _tiempo_crudo_serializable(raw_local),
            "intervalo_tiempo_local_ms": [
                _tiempo_crudo_serializable(x) for x in c.get("intervalo_tiempo_local_ms", [])
            ] if isinstance(c.get("intervalo_tiempo_local_ms"), (list, tuple)) else None,
            "estado_tiempo": estado_local,
            "referencia_tiempo_valida": False,
            "resolucion_ms": c.get("resolucion_ms"),
            "score_candidato": c.get("score_candidato"),
            "score_es_probabilidad": c.get("score_es_probabilidad"),
            "tipo_senales": c.get("tipo_senales"),
        })
    tiempo_confirmado = (_milisegundos(tiempo)
                        if decision in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"} else None)
    if tiempo_confirmado is not None and tiempo_confirmado <= 0:
        tiempo_confirmado = None
    tiempo_propuesto = (_milisegundos(propuesta_valida.get("valor"))
                        if decision in {"PROPUESTA", "CONFLICTO"}
                        and propuesta_valida is not None else None)
    if tiempo_propuesto is not None and tiempo_propuesto <= 0:
        tiempo_propuesto = None
    auto_color_elegible = bool(
        decision == "PROPUESTA"
        and tiempo_auto_color is not None
        and not conflicto_auto_color
        and not eventos_inicio
        and not campo_conflicto_humano
        and not audit_humano_bloqueante
    )
    auto_color_prioridad = ("video_unico_defendible" if auto_color_elegible and len(auto_color_estimaciones) == 1
                            else "evidencia_multivista_coherente" if auto_color_elegible and len(auto_color_estimaciones) > 1
                            else None)
    if auto_color_prioridad == "video_unico_defendible":
        razones.append("un_video_con_apertura_fisica_defendible_habilita_color_estimado")
    return {
        "estado": decision,
        "estado_operativo": estado_operativo,
        "tiempo_ms": tiempo_confirmado,
        "tiempo_propuesto_ms": tiempo_propuesto,
        "tiempo_crudo_ms": raw_publico,
        "raw_time_ms": raw_publico,
        "estado_tiempo": estado_tiempo,
        "referencia_tiempo_valida": referencia_publica,
        "motivo_rechazo": motivo_rechazo,
        "intervalo_tiempo_ms": intervalo,
        "resolucion_ms": resolucion,
        "incertidumbre_ms": (resolucion / 2 if resolucion is not None else None),
        "fuente": fuente_publica,
        "frame_evento": video.get("frame_evento"),
        "soporte_independiente": video.get("soporte"),
        "estado_consenso_legacy": video.get("estado_consenso"),
        "revisiones_temporales_invalidas": revisiones_temporales_invalidas,
        "candidatos_sombra": candidatos_resumen,
        "requiere_revision": decision in {"PROPUESTA", "CONFLICTO"},
        "auto_publicable": decision == "AUTO_VERIFICABLE",
        "auto_color_elegible": auto_color_elegible,
        "tiempo_estimado_auto_ms": (round(float(tiempo_auto_color), 3)
                                    if tiempo_auto_color is not None else None),
        "auto_color_soporte": len(auto_color_estimaciones),
        "auto_color_conflicto": conflicto_auto_color,
        "auto_color_tolerancia_ms": round(float(tolerancia_auto), 6),
        "auto_color_evidencias": auto_color_estimaciones[:8],
        "auto_color_no_equivale_publicacion": True,
        "auto_color_prioridad": auto_color_prioridad,
        "duracion_llenado_estimada_ms": (round(float(duracion_llenado_estimada), 3)
                                          if duracion_llenado_estimada is not None and not conflicto_llenado else None),
        "llenado_visual_soporte": len(llenado_estimaciones),
        "llenado_visual_conflicto": conflicto_llenado,
        "llenado_visual_evidencias": llenado_estimaciones[:8],
        "llenado_visual_no_equivale_volumen_fisico": True,
        "tiempo_max_inflado_estimado_ms": (round(float(tiempo_max_inflado_estimado), 3)
                                             if tiempo_max_inflado_estimado is not None and not conflicto_max_inflado else None),
        "duracion_hasta_max_inflado_ms": (round(float(duracion_hasta_max_inflado), 3)
                                           if duracion_hasta_max_inflado is not None and not conflicto_max_inflado else None),
        "tiempo_max_inflado_no_confirmado_ms": (round(float(tiempo_max_inflado_no_confirmado), 3)
                                                if tiempo_max_inflado_no_confirmado is not None else None),
        "max_inflado_estado": max_inflado_estado_caso,
        "max_inflado_soporte": len(max_inflado_confirmadas),
        "max_inflado_no_confirmado_soporte": len(max_inflado_no_confirmadas),
        "max_inflado_conflicto": conflicto_max_inflado,
        "max_inflado_anomalias": anomalias_max_inflado,
        "max_inflado_evidencias": max_inflado_estimaciones[:8],
        "tiempos_relativos_inicio_video": True,
        "trigger_electrico_disponible": False,
        "probabilidad_calibrada": None,
        "motivos": list(dict.fromkeys(razones)),
        "censurado_por_izquierda": bool(eventos_inicio),
        "no_certifica_ausencia": decision == "NO_OBSERVADO",
        "version_politica": "opening-publication-r13-breakout-maximo-autonomo",
    }


def resolver_resultado_caso(fila: dict | None) -> dict:
    dato = fila if isinstance(fila, dict) else {}
    campos = dato.get("campos") if isinstance(dato.get("campos"), dict) else {}
    campos_canonicos = {
        str(k): resolver_campo(v, campo_id=str(k))
        for k, v in campos.items() if isinstance(v, dict)
    }
    apertura = resolver_apertura(dato)
    campos_canonicos.setdefault("opening_time_ms", {
        "campo_id": "opening_time_ms",
        "valor": (apertura.get("tiempo_ms") if apertura.get("estado") in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"}
                  else apertura.get("tiempo_propuesto_ms")),
        "decision": apertura.get("estado", "NO_OBSERVADO"),
        "estado_origen": apertura.get("estado_consenso_legacy"),
        "fuente_preferida": apertura.get("fuente"),
        "evidencias": apertura.get("candidatos_sombra", []),
        "cantidad_candidatos": len(apertura.get("candidatos_sombra", [])),
        "cantidad_fuentes": apertura.get("soporte_independiente") or 0,
        "probabilidad_calibrada": None,
        "requiere_revision": apertura.get("requiere_revision", False),
        "razones": apertura.get("motivos", []),
    })
    # La decisión agregada reemplaza el estado genérico del campo de apertura.
    # Un raw negativo/ilegible sólo se conserva en llaves de auditoría; nunca
    # queda en ``campos.opening_time_ms.valor`` ni en una propuesta normal.
    campo_apertura = campos_canonicos["opening_time_ms"]
    decision_apertura = apertura.get("estado", "NO_OBSERVADO")
    valor_apertura = (apertura.get("tiempo_ms") if decision_apertura in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"}
                      else apertura.get("tiempo_propuesto_ms"))
    valor_apertura = _milisegundos(valor_apertura)
    if valor_apertura is None or valor_apertura <= 0:
        valor_apertura = None
    campo_apertura["valor"] = valor_apertura
    campo_apertura["decision"] = decision_apertura
    campo_apertura["requiere_revision"] = decision_apertura in {"PROPUESTA", "CONFLICTO"}
    campo_apertura["tiempo_crudo_ms"] = apertura.get("tiempo_crudo_ms")
    campo_apertura["raw_time_ms"] = apertura.get("raw_time_ms")
    campo_apertura["estado_tiempo"] = apertura.get("estado_tiempo")
    campo_apertura["referencia_tiempo_valida"] = apertura.get("referencia_tiempo_valida") is True
    campo_apertura["motivo_rechazo"] = apertura.get("motivo_rechazo")
    campo_apertura["intervalo_tiempo_ms"] = apertura.get("intervalo_tiempo_ms")
    campo_apertura["razones"] = list(dict.fromkeys(
        list(campo_apertura.get("razones") or []) + list(apertura.get("motivos") or [])))
    return {
        "schema": VERSION_SCHEMA_RESULTADO,
        "case_key": dato.get("case_key") or dato.get("id"),
        "decision_version": "v15.10.1",
        "campos": campos_canonicos,
        "apertura": apertura,
        "resumen": {
            "campos_totales": len(campos_canonicos),
            "campos_humanos": sum(x.get("decision") == "VERIFICADO_HUMANO" for x in campos_canonicos.values()),
            "campos_propuestos": sum(x.get("decision") == "PROPUESTA" for x in campos_canonicos.values()),
            "campos_en_conflicto": sum(x.get("decision") == "CONFLICTO" for x in campos_canonicos.values()),
            "probabilidades_calibradas": False,
            "auto_publicacion_habilitada": False,
        },
        "limitaciones": [
            "La confianza OCR y los scores heurísticos no son probabilidades calibradas.",
            "No se dispuso del conjunto reservado de datos reales etiquetados para calibrar.",
            "La ausencia de detección no certifica la ausencia física del evento.",
        ],
    }
