"""P50 · Decisiones con evidencia de VARIAS fuentes o de VARIOS casos de la misma corrida.

El usuario (12/11): «busca y aplica estrategias para que lo llene lo máximo posible; que si no
funciona un protocolo salte a otro». Cada protocolo sólo llena celdas VACÍAS, nunca toca una
decisión humana ni un valor ya publicado, y deja su regla en el campo y en la Trazabilidad.
Ninguno usa el Book corregido: las fuentes son las lecturas de esta corrida, el pie de los vídeos
y el libro histórico de la plantilla (vocabulario).

Protocolos, en orden:

1. **Nivel del módulo (K) = estampa amarilla, con la regla de nomenclatura del usuario.**
   `##K` si la etiqueta del módulo dice PROTOTYPE, `##S` si es de serie. Una lectura de estampa con
   el sufijo equivocado se descarta. Estampa leída igual en ≥2 fotos → se publica. Etiqueta de
   serie leída SIN estampa → nivel de partida `01S` (regla de `codigos_modulo`), sólo si otros
   ≥2 casos de la corrida están en la misma situación (consenso entre carpetas).
2. **Tablero en lote** (nivel R, fecha Q): una sola lectura del lector del tablero en el caso,
   igual al consenso de ≥2 casos con el MISMO N/P de tablero y sin ningún caso que diga otra cosa.
3. **Proveedor por número de parte** (N): mismo N/P de módulo que ≥2 casos con proveedor
   publicado y unánime; sin lectura en contra.
4. **Motivo (B) = pie del vídeo + libro histórico**: el pie dice «BMG» y el único valor del libro
   histórico que contiene esa palabra es «IT BMG».
5. **P52 · Serie del módulo con dígito de control** (I): la serie «671 ZRZ0539983E» termina en el
   carácter de control Code 39 (módulo 43) de lo anterior. Si las lecturas del caso, con la
   corrección de forma (O→0, I→1… sólo en la parte numérica), dejan UNA sola serie con control
   válido, se publica. Por azar sólo 1 de cada 43 lecturas erróneas pasaría el control.
6. **P52 · Unánime en el lote** (fecha y N/P del módulo): ≥6 casos de la corrida con el mismo valor
   publicado, ninguna lectura en toda la corrida que diga otro, y la etiqueta del módulo vista en
   las fotos del caso. Queda marcado con su regla para revisarlo en la Trazabilidad.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

VERSION = "p52-lote-3"
PROTOTIPO = re.compile(r"PROTOTYP", re.I)


def _valor(fila: dict, clave: str):
    dato = (fila.get("campos") or {}).get(clave)
    return dato.get("valor") if isinstance(dato, dict) else dato


def _vacio(fila: dict, clave: str) -> bool:
    dato = (fila.get("campos") or {}).get(clave) or {}
    return (dato.get("valor") in (None, "") and not dato.get("confirmacion_manual")
            and dato.get("estado") not in {"extraido_manual", "confirmado_manual"})


def _publicar(fila: dict, clave: str, valor, regla: str, motivo: str, informe: list) -> None:
    anterior = dict((fila.get("campos") or {}).get(clave) or {})
    fila.setdefault("campos", {})[clave] = {
        **{k: v for k, v in anterior.items() if k in ("candidatos", "fuentes", "opciones_consenso")},
        "valor": valor, "estado": "decision_lote", "regla": regla, "motivo": motivo,
        "inferido": True, "requiere_revision": False, "version_decision": VERSION,
        "valor_propuesto_anterior": anterior.get("valor_propuesto")}
    fila["campos_faltantes"] = [c for c in fila.get("campos_faltantes") or [] if c != clave]
    fila["conflictos"] = [c for c in fila.get("conflictos") or [] if c != clave]
    fila.setdefault("candidatos", []).append({
        "proyecto": fila.get("project_id"), "etapa": fila.get("tipo_st"), "caso": fila.get("case_key"),
        "componente": "por_identificar", "clave": clave, "valor_original": str(valor),
        "valor_normalizado": valor, "fuente": "decision_lote", "imagen": None,
        "regla_aplicada": regla, "confirmacion_manual": False, "estado_p42": "decision_lote",
        "motivo_p42": motivo[:300], "version_procesamiento": VERSION})
    informe.append({"caso": fila.get("test_number") or fila.get("case_key"), "campo": clave,
                    "valor": valor, "regla": regla})


def tipo_pieza(fila: dict) -> str | None:
    """«prototipo» / «serie» según la ETIQUETA DEL MÓDULO leída (regla del usuario: ##K / ##S).

    Prototipo si el lector marcó la etiqueta como PROTOTYPE, si la estampa leída termina en K, o si
    la foto de la etiqueta muestra «PROTOTYPE» y ninguna estampa dice ##S. Serie si se leyó la
    etiqueta del módulo y nada de lo anterior. Sin etiqueta leída: desconocido.
    """
    lecturas = (fila.get("etiqueta_modulo") or {}).get("lecturas") or []
    estampas = [str(l.get("estampa") or "").upper() for l in lecturas if l.get("estampa")]
    if any(l.get("prototipo") for l in lecturas) or any(e.endswith("K") for e in estampas):
        return "prototipo"
    if textos_prototipo_modulo(fila):
        return "prototipo"
    if (any("prototipo" in (l.get("ganchos") or []) for l in lecturas if l.get("es_modulo"))
            and not any(e.endswith("S") for e in estampas)):
        return "prototipo"
    if any(l.get("es_modulo") for l in lecturas):
        return "serie"
    return None


GANCHOS_MODULO = re.compile(r"2GJ\s*\.?\s*880|ZRZ|65153\d{4}|\b\d{2}\.\d{2}\.\d{2}\b|AIRBAG\s*MOD", re.I)
# la pegatina amarilla del GENERADOR también dice «PROTOTYPE AQW» y sale en casos de serie
GANCHOS_GENERADOR = re.compile(r"\bAQ[WU]\b|ACHTUNG|AVISO|GENERAD|ZUL[AÄ]SSIG|SPANN", re.I)


def textos_prototipo_modulo(fila: dict) -> list[str]:
    """Textos de foto donde «PROTOTYPE» va con ganchos de la etiqueta del MÓDULO y no del generador."""
    salida = []
    for t in fila.get("trazabilidad") or []:
        texto = str(t.get("texto_crudo") or "")
        if PROTOTIPO.search(texto) and GANCHOS_MODULO.search(texto) and not GANCHOS_GENERADOR.search(texto):
            salida.append(texto)
    return salida


def sufijo_valido(nivel: str, tipo: str | None) -> bool:
    if tipo is None:
        return True
    return str(nivel).upper().endswith("K" if tipo == "prototipo" else "S")


def _estampas(fila: dict) -> list[tuple[str, str]]:
    salida = []
    for l in (fila.get("etiqueta_modulo") or {}).get("lecturas") or []:
        if l.get("estampa"):
            salida.append((str(l["estampa"]).upper(), str(l.get("foto"))))
    return salida


def _protocolo_nivel_modulo(resultados: list[dict], informe: list) -> None:
    sin_estampa_serie = []
    for fila in resultados:
        fila["tipo_pieza"] = tipo_pieza(fila)
        if not _vacio(fila, "engineering_level"):
            continue
        tipo = fila["tipo_pieza"]
        estampas = [(v, f) for v, f in _estampas(fila) if re.fullmatch(r"\d{2}[SK]", v) and sufijo_valido(v, tipo)]
        if tipo == "prototipo":
            # el OCR genérico también lee la estampa («OGL | 66K | … | PROTOTYPE | 2GJ 880 204 J»)
            for i, texto in enumerate(textos_prototipo_modulo(fila)):
                for m in re.finditer(r"(?<![A-Z0-9])(\d{2}K)(?![A-Z0-9])", texto.upper()):
                    estampas.append((m.group(1), f"texto_generico_{i}"))
        valores = {v for v, _ in estampas}
        fotos = {f for _, f in estampas}
        campo = fila.setdefault("campos", {}).setdefault("engineering_level", {})
        if len(valores) == 1 and len(fotos) >= 2:
            _publicar(fila, "engineering_level", valores.pop(), "estampa_dos_lecturas_sufijo_ok",
                      f"nivel igual en {len(fotos)} lecturas (estampa / texto de la etiqueta); sufijo "
                      f"coherente con {tipo or 'la etiqueta'}", informe)
            continue
        if len(valores) == 1:
            campo["valor_propuesto"] = next(iter(valores))
            continue
        propuesto = campo.get("valor_propuesto")
        if propuesto and not sufijo_valido(propuesto, tipo):
            campo["valor_propuesto_descartado"] = propuesto
            campo["valor_propuesto"] = None
            campo["motivo_sufijo"] = (f"«{propuesto}» no puede ser: la etiqueta es de "
                                      f"{tipo} ({'##K' if tipo == 'prototipo' else '##S'})")
        if tipo == "serie" and not estampas:
            sin_estampa_serie.append(fila)
    if len(sin_estampa_serie) >= 3:
        for fila in sin_estampa_serie:
            _publicar(fila, "engineering_level", "01S", "nivel_de_partida_sin_estampa",
                      f"etiqueta de serie sin estampa amarilla; {len(sin_estampa_serie)} casos de la "
                      "corrida en la misma situación (nivel de partida 01S, regla de codigos_modulo)", informe)


def _protocolo_lote(resultados: list[dict], clave: str, grupo: str, informe: list, regla: str,
                    lecturas_propias) -> None:
    por_grupo: dict[str, list[dict]] = defaultdict(list)
    for fila in resultados:
        g = _valor(fila, grupo)
        if g not in (None, ""):
            por_grupo[str(g)].append(fila)
    for g, filas in por_grupo.items():
        publicados = Counter(str(_valor(f, clave)) for f in filas if _valor(f, clave) not in (None, ""))
        if len(publicados) != 1:
            continue
        valor, n = publicados.most_common(1)[0]
        if n < 2:
            continue
        for fila in filas:
            if not _vacio(fila, clave):
                continue
            propias = lecturas_propias(fila, clave)
            if propias and set(propias) != {valor}:
                continue                                   # el caso dice otra cosa: sigue en duda
            if not propias and clave not in {"inflator_supplier"}:
                continue                                   # sin lectura propia no se decide
            _publicar(fila, clave, valor, regla,
                      f"{n} casos de la corrida con {grupo} = {g} tienen «{valor}»"
                      + (f"; el caso lo leyó {len(propias)} vez/veces igual" if propias else ""), informe)


def _lecturas_tablero(fila: dict, clave: str) -> list[str]:
    salida = []
    dato = ((fila.get("tablero_p42") or {}).get("campos") or {}).get(clave) or {}
    for valor, n in (dato.get("votos") or {}).items():
        salida.extend([str(valor)] * int(n or 1))
    propuesto = ((fila.get("campos") or {}).get(clave) or {}).get("valor_propuesto")
    if propuesto and not salida:
        salida.append(str(propuesto))
    return salida


def _lecturas_proveedor(fila: dict, clave: str) -> list[str]:
    return [str(c.get("valor_normalizado")) for c in fila.get("candidatos") or []
            if c.get("clave") == clave and c.get("valor_normalizado") not in (None, "")
            and c.get("fuente") != "decision_lote"]


def _protocolo_motivo(resultados: list[dict], vocabulario: dict, informe: list, mapa: dict | None = None) -> None:
    """B · regla del usuario: lo que haya en la POSICIÓN del motivo del pie (entre «EDAG Mex» y la
    fecha, a veces entre comillas) se imprime; «BMG» se imprime «IT BMG» (mapa configurable). Si el
    pie de ese caso no trae motivo, se usa el motivo unánime de ≥3 casos de la misma corrida."""
    opciones = (vocabulario or {}).get("test_reason") or {}
    mapa = {str(k).upper(): v for k, v in (mapa or {"BMG": "IT BMG"}).items()}
    sin_motivo = []
    for fila in resultados:
        if not _vacio(fila, "test_reason"):
            continue
        pie = Counter(str(c.get("valor_normalizado")).upper() for c in fila.get("candidatos") or []
                      if c.get("clave") == "test_reason" and c.get("fuente") == "barra_video"
                      and c.get("valor_normalizado"))
        if not pie:
            leyo_pie = any(c.get("fuente") == "barra_video" for c in fila.get("candidatos") or [])
            if leyo_pie:
                sin_motivo.append(fila)
            continue
        palabra, votos = pie.most_common(1)[0]
        if len(pie) > 1 and votos * 2 <= sum(pie.values()):
            continue
        if palabra in mapa:
            _publicar(fila, "test_reason", mapa[palabra], "motivo_regla_usuario",
                      f"el pie de {votos} vídeo(s) dice «{palabra}»; regla del usuario: «{palabra}» → «{mapa[palabra]}»",
                      informe)
            continue
        encajan = [v for v in opciones if re.search(rf"(?<![A-Z0-9]){re.escape(palabra)}(?![A-Z0-9])", v.upper())]
        if len(encajan) == 1:
            _publicar(fila, "test_reason", encajan[0], "pie_video_mas_libro_historico",
                      f"el pie de {votos} vídeo(s) dice «{palabra}» y el único motivo del libro histórico "
                      f"que lo contiene es «{encajan[0]}» ({opciones[encajan[0]]} filas)", informe)
        else:
            _publicar(fila, "test_reason", palabra, "motivo_tal_cual_del_pie",
                      f"el pie de {votos} vídeo(s) dice «{palabra}» en la posición del motivo", informe)
    publicados = Counter(str(_valor(f, "test_reason")) for f in resultados if _valor(f, "test_reason") not in (None, ""))
    if len(publicados) == 1 and next(iter(publicados.values())) >= 3:
        valor, n = publicados.most_common(1)[0]
        for fila in sin_motivo:
            _publicar(fila, "test_reason", valor, "motivo_consenso_lote",
                      f"el pie de este caso no trae motivo; {n} casos de la corrida dicen «{valor}» y ninguno otra cosa",
                      informe)


def _desempate_por_lote(resultados: list[dict], clave: str, informe: list, minimo: int = 3) -> None:
    """Lecturas propias en conflicto (p. ej. 2025-04-01 y 2025-04-10): si UNA es la que tienen
    publicada ≥3 casos de la corrida (y ninguno otra), manda esa."""
    publicados = Counter(str(_valor(f, clave)) for f in resultados if _valor(f, clave) not in (None, ""))
    if len(publicados) != 1:
        return
    valor, n = publicados.most_common(1)[0]
    if n < minimo:
        return
    for fila in resultados:
        if not _vacio(fila, clave):
            continue
        propias = {str(c.get("valor_normalizado")) for c in fila.get("candidatos") or []
                   if c.get("clave") == clave and c.get("valor_normalizado") not in (None, "")
                   and c.get("fuente") not in {"decision_lote", "manual"}}
        if len(propias) >= 2 and valor in propias:
            _publicar(fila, clave, valor, "desempate_por_lote",
                      f"el caso leyó {sorted(propias)}; «{valor}» es lo que tienen {n} casos de la corrida", informe)


def _proveedor_unanime(resultados: list[dict], informe: list, minimo: int = 5) -> None:
    """N · si ≥5 casos de la corrida tienen el mismo proveedor y ninguna lectura dice otro, se
    aplica a los casos con etiqueta del módulo vista (ganchos en sus fotos) aunque falte su N/P."""
    publicados = Counter(str(_valor(f, "inflator_supplier")) for f in resultados
                         if _valor(f, "inflator_supplier") not in (None, ""))
    contrarias = {str(c.get("valor_normalizado")) for f in resultados for c in f.get("candidatos") or []
                  if c.get("clave") == "inflator_supplier" and c.get("valor_normalizado")}
    if len(publicados) != 1 or contrarias - set(publicados):
        return
    valor, n = publicados.most_common(1)[0]
    if n < minimo:
        return
    for fila in resultados:
        if not _vacio(fila, "inflator_supplier"):
            continue
        visto = ((fila.get("etiqueta_modulo") or {}).get("lecturas") or
                 [t for t in fila.get("trazabilidad") or [] if GANCHOS_MODULO.search(str(t.get("texto_crudo") or ""))])
        if visto:
            _publicar(fila, "inflator_supplier", valor, "proveedor_unanime_corrida",
                      f"{n} casos de la corrida con «{valor}» y ninguna lectura de otro proveedor; "
                      "la etiqueta del módulo aparece en las fotos del caso", informe)


DIGITO = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1", "S": "5",
                        "B": "8", "Z": "2", "G": "6", "T": "7"})
SERIE_MODULO = re.compile(r"(?<![0-9A-Z])(\d{3}) ?(ZRZ) ?([0-9OQDILSBZGT|]{7}) ?([0-9A-Z$%/+.\-])(?![0-9A-Z])")


def formas_serie_modulo(texto: str) -> list[str]:
    """«671ZRZ0539983E» / «671 ZRZ O539983 E» → «671 ZRZ0539983E» (forma del lector, con espacio)."""
    limpio = re.sub(r"[^0-9A-Z$%/+.\-| \n]", "", str(texto or "").upper())
    return [f"{m.group(1)} {m.group(2)}{m.group(3).translate(DIGITO)}{m.group(4)}"
            for linea in limpio.splitlines() for m in SERIE_MODULO.finditer(re.sub(r" +", " ", linea))]


PARECIDOS = {"8": "B", "B": "8", "0": "OD", "O": "0D", "D": "0O", "1": "IL", "I": "1L", "L": "1I",
             "5": "S", "S": "5$", "$": "S", "2": "Z", "Z": "2", "6": "G", "G": "6", "7": "T", "T": "7"}


def con_control_valido(forma: str, valida) -> str | None:
    """La forma si su control es válido; si no, la ÚNICA variante del último carácter (8↔B, 0↔O…)
    que lo cumpla. El cuerpo no se toca: sólo se corrige el carácter que se suele imprimir mal."""
    if valida(forma):
        return forma
    buenas = [forma[:-1] + c for c in PARECIDOS.get(forma[-1], "") if valida(forma[:-1] + c)]
    return buenas[0] if len(buenas) == 1 else None


def _protocolo_control_serie_modulo(resultados: list[dict], informe: list) -> None:
    from tablero_integracion import valida_code39
    clave = "module_serial_number"
    for fila in resultados:
        if not _vacio(fila, clave):
            continue
        lecturas = [c.get("valor_original") or c.get("valor_normalizado")
                    for c in fila.get("candidatos") or []
                    if c.get("clave") == clave and c.get("fuente") not in {"decision_lote"}]
        # texto completo de las fotos: el lector de campos pudo no reconocer la serie
        lecturas += [t.get("texto_crudo") for t in fila.get("trazabilidad") or [] if t.get("texto_crudo")]
        validas = sorted({v for texto in lecturas for f in formas_serie_modulo(texto)
                          if (v := con_control_valido(f, valida_code39))})
        if len(validas) == 1:
            _publicar(fila, clave, validas[0], "control_code39_serie_modulo",
                      f"la lectura cumple el dígito de control Code 39 (mod 43) y es la única que lo cumple",
                      informe)


def _modulo_visto(fila: dict) -> bool:
    return bool((fila.get("etiqueta_modulo") or {}).get("lecturas") or
                [t for t in fila.get("trazabilidad") or [] if GANCHOS_MODULO.search(str(t.get("texto_crudo") or ""))])


def _unanime_lote(resultados: list[dict], clave: str, informe: list, minimo: int = 6) -> None:
    publicados = Counter(str(_valor(f, clave)) for f in resultados if _valor(f, clave) not in (None, ""))
    if len(publicados) != 1:
        return
    valor, n = publicados.most_common(1)[0]
    if n < minimo:
        return
    contrarias = {str(c.get("valor_normalizado")) for f in resultados for c in f.get("candidatos") or []
                  if c.get("clave") == clave and c.get("valor_normalizado") not in (None, "")
                  and c.get("fuente") not in {"decision_lote"}} - {valor}
    if contrarias:
        return
    for fila in resultados:
        if _vacio(fila, clave) and _modulo_visto(fila):
            _publicar(fila, clave, valor, "unanime_lote_modulo",
                      f"{n} casos de la corrida con «{valor}», ninguna lectura de otro valor y la etiqueta "
                      "del módulo aparece en las fotos del caso", informe)


def aplicar(resultados: list[dict], vocabulario: dict | None = None, mapa_motivos: dict | None = None,
            unanime_lote: int = 6) -> dict:
    informe: list[dict] = []
    _protocolo_control_serie_modulo(resultados, informe)
    _protocolo_nivel_modulo(resultados, informe)
    for clave in ("module_date", "module_part_number", "dashboard_date"):
        _desempate_por_lote(resultados, clave, informe)
    for clave in ("dashboard_engineering_level", "dashboard_date"):
        _protocolo_lote(resultados, clave, "dashboard_part_number", informe,
                        "consenso_lote_tablero", _lecturas_tablero)
    _protocolo_lote(resultados, "inflator_supplier", "module_part_number", informe,
                    "proveedor_por_numero_de_parte", _lecturas_proveedor)
    _proveedor_unanime(resultados, informe)
    _protocolo_motivo(resultados, vocabulario or {}, informe, mapa_motivos)
    if unanime_lote and unanime_lote > 0:
        for clave in ("module_part_number", "module_date"):
            _unanime_lote(resultados, clave, informe, unanime_lote)
    return {"version": VERSION, "decisiones": informe, "total": len(informe)}
