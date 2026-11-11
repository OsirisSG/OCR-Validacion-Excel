"""Consenso ponderado de valores (P09): la parte buena de la lógica de la sandbox, sin su trampa.

Qué había en la sandbox
-----------------------
Se medía «3 de 4 lecturas coinciden» sobre la **base de aprendizaje**, y de ahí salió el famoso
22/22 = 100 %. Aquel número no valía: votaba lecturas ya guardadas, no ejecutaba el pipeline.
Pero la idea de fondo sí era buena y aquí se conserva, con dos cambios:

1. **No se vota para medir**: se vota para **decidir** un valor, y sólo cuando el consolidador
   se quedaba en blanco. Nunca se pisa una decisión que ya estaba tomada.
2. **Los votos pesan distinto según de dónde vienen.** Una persona que confirma vale más que
   una barra de vídeo, y una barra vale más que un OCR suelto. Un mismo texto leído dos veces
   en la *misma* foto no son dos votos: es uno.

Reglas de decisión
------------------
- gana el valor con más peso; para publicar hacen falta **2,0 puntos**;
- si el segundo está a menos de 0,5 puntos del primero, no hay decisión: es un empate y va a
  la cola de dudas con las opciones ordenadas;
- los niveles (`##K`/`##S`) exigen además **dos fotos distintas**: en la ejecución real dos
  lecturas de la misma foto publicaron `02S` donde el libro decía `01S`;
- una lectura con la forma rota se intenta **reparar** sólo si la reparación es estructural
  (falta un separador, falta el cero o el dígito inicial y otra fuente lo aporta). No se
  adivinan caracteres: `ZRZO539999L` frente a `ZRZ0539999L` es una duda, no una reparación.
"""
from __future__ import annotations

import re

from utilidades.validacion_formas import CORROBORACION_MINIMA, normalizar, revisar_forma

# Peso de cada procedencia. Los números están elegidos para que una sola lectura de OCR nunca
# decida sola un campo que exige respaldo, y para que una confirmación humana mande siempre.
PESOS: dict[str, float] = {
    "manual_confirmado": 4.0,
    "manual": 3.0,
    "ruta_carpeta": 2.5,
    "barra_video": 2.0,
    "qr": 2.0,
    "diagrama": 1.5,
    "ocr": 1.0,
}
UMBRAL_PUBLICACION = 2.0
MARGEN_EMPATE = 0.5

# Campos que el nombre de la carpeta decide por convenio, no por lectura: la condición de
# temperatura y la versión (RDW/NAR) se escriben al archivar el caso y coincidieron en los
# 10 casos. Lo que esté impreso en la etiqueta («300C», «NT RT HT») es otra cosa y no debe
# votar contra el convenio. El número de prueba también manda desde la carpeta, salvo que el
# pie de página lo contradiga (ahí decide el consenso, no el convenio).
SOLO_CARPETA_MANDA = {"temperature_condition", "module_version"}
CARPETA_Y_ETIQUETA = {"test_number", "inflator_type"}
# Con cuánta fuerza puede la etiqueta contradecir a la carpeta. Medido en los 10 casos:
# el número de prueba de la carpeta acertó 9/10 (falla cuando la carpeta está mal, y entonces
# nada lo salva), así que sólo cede ante evidencia FUERTE (≥2 fotos diciendo otra cosa); en
# cambio el inflador de la carpeta falló 3/10, así que cede ante CUALQUIER lectura contraria.
VETO_FUERTE = {"test_number"}
# Campos de identidad con una forma muy específica: una sola lectura bien formada basta.
# No es lo mismo que un nivel o un texto libre, donde un único acierto de forma no prueba nada.
UNA_LECTURA_BASTA = {
    "module_part_number", "dashboard_part_number", "module_serial_number",
    "dashboard_serial_number", "week", "test_date", "module_date", "dashboard_date",
    "inflator_supplier", "dashboard_supplier", "laser_opening", "test_place", "test_reason",
}
# Campos que NO se publican nunca sólo con OCR. Medido sobre los 10 casos: de 13 lecturas de
# nivel, NINGUNA coincidió con el libro (dice `01S` y se lee `02S`, dice `69K` y se lee `03S`).
# Publicar eso es publicar un error con toda la confianza estadística del mundo. Se quedan en
# la cola de dudas para que los decida una persona (o una regla de aprendizaje confirmada).
NUNCA_AUTOMATICO = {"engineering_level", "dashboard_engineering_level"}
# Para estos campos sólo cuentan las lecturas que el extractor marca como «esto identifica el
# campo»: en la trazabilidad hay números de otras etiquetas que no son candidatos.
REGLAS_IDENTIFICAN: dict[str, set[str]] = {
    "test_number": {"numero_prueba_impreso_sin_etiqueta", "numero_en_barra_de_video"},
    "inflator_type": {"catalogo_inflator", "catalogo_inflator_tolerante",
                      "inflador_en_barra_de_video"},
    "module_part_number": {"numero_parte"},
    "dashboard_part_number": {"numero_parte"},
    "module_serial_number": {"serial_impreso_en_etiqueta", "serial_etiquetado"},
    "dashboard_serial_number": {"serial_impreso_en_etiqueta", "serial_etiquetado"},
}

_PARTE = re.compile(r"^(\d?)([A-Z]{2})(\d{3})(\d{3})([A-Z])$")
_SERIE = re.compile(r"^(\d{3})([A-Z0-9]{8,12})$")
_NIVEL = re.compile(r"^(\d{1,2})([KS])$")


def peso_de(evidencia: dict) -> float:
    """Cuánto vale esta evidencia. Una confirmación humana pesa más que cualquier lectura."""
    if evidencia.get("confirmacion_manual") or evidencia.get("fuente") == "manual":
        return PESOS["manual_confirmado"] if evidencia.get("confirmacion_manual") else PESOS["manual"]
    return PESOS.get(str(evidencia.get("fuente") or "ocr"), 1.0)


def canonizar(clave: str, valor) -> str:
    """Forma canónica de un valor, para que dos lecturas buenas cuenten como la misma.

    Aquí sólo se unifican separadores y mayúsculas; no se cambia ningún carácter.
    """
    texto = normalizar(valor)
    if not texto:
        return ""
    if clave in {"module_part_number", "dashboard_part_number"}:
        compacto = re.sub(r"[. ]", "", texto)
        partes = _PARTE.match(compacto)
        if partes:
            inicial, familia, a, b, final = partes.groups()
            return f"{inicial}{familia}.{a}.{b}.{final}"
    if clave in {"module_serial_number", "dashboard_serial_number"}:
        compacto = re.sub(r"[. ]", "", texto)
        serie = _SERIE.match(compacto)
        if serie:
            return f"{serie.group(1)} {serie.group(2)}"
    if clave in {"engineering_level", "dashboard_engineering_level"}:
        nivel = _NIVEL.match(texto)
        if nivel:
            return f"{int(nivel.group(1)):02d}{nivel.group(2)}"
    if clave == "test_number":
        digitos = re.sub(r"\D", "", texto)
        return digitos if len(digitos) == 6 else texto
    return texto


def reparar(clave: str, valor, otras: list[str]) -> tuple[str, bool, str]:
    """Intenta arreglar una lectura MALFORMADA sin inventar caracteres.

    Devuelve ``(valor_reparado, reparado, motivo)``. Si no hay una reparación estructural
    justificada, devuelve el valor tal cual y ``reparado=False``.
    """
    canonico = canonizar(clave, valor)
    if revisar_forma(clave, canonico)["valido"]:
        return canonico, canonico != normalizar(valor), ""

    if clave in {"module_part_number", "dashboard_part_number"}:
        compacto = re.sub(r"[. ]", "", normalizar(valor))
        partes = _PARTE.match(compacto)
        if partes and not partes.group(1):
            # Falta el dígito inicial: se toma de otra lectura que sí lo tenga y que
            # coincida en TODO lo demás. Si nadie lo aporta, no se adivina.
            cola = compacto
            for otra in otras:
                candidato = re.sub(r"[. ]", "", normalizar(otra))
                piezas = _PARTE.match(candidato)
                if piezas and piezas.group(1) and candidato[1:] == cola:
                    reparado = f"{piezas.group(1)}{piezas.group(2)}.{piezas.group(3)}.{piezas.group(4)}.{piezas.group(5)}"
                    return reparado, True, "faltaba el dígito inicial; se toma de otra lectura"
        return canonico, False, ""

    if clave in {"engineering_level", "dashboard_engineering_level"}:
        nivel = _NIVEL.match(normalizar(valor))
        if nivel:
            reparado = f"{int(nivel.group(1)):02d}{nivel.group(2)}"
            return reparado, True, "faltaba el cero a la izquierda"
        return canonico, False, ""
    return canonico, False, ""


def consensuar(clave: str, evidencias, reparar_con=()) -> dict:
    """Decide un valor a partir de todas las lecturas disponibles.

    Devuelve un diccionario con ``valor`` (None si no hay decisión), ``peso``, ``estado``
    (``consenso`` / ``empate`` / ``soporte_insuficiente`` / ``sin_lecturas``), ``opciones``
    ordenadas por peso y ``reparado`` cuando el valor salió de una reparación estructural.
    """
    reglas = REGLAS_IDENTIFICAN.get(clave)
    lecturas: list[dict] = []
    for evidencia in evidencias:
        if reglas and evidencia.get("fuente") not in {"manual", "ruta_carpeta"} \
                and evidencia.get("regla") and str(evidencia["regla"]) not in reglas:
            continue
        valor = evidencia.get("valor_normalizado")
        if valor in (None, ""):
            continue
        peso = peso_de(evidencia)
        texto = normalizar(valor)
        canonico = canonizar(clave, valor)
        reparado, motivo = False, ""
        if not revisar_forma(clave, canonico)["valido"]:
            canonico, reparado, motivo = reparar(clave, valor, [*reparar_con, texto])
        if not revisar_forma(clave, canonico)["valido"]:
            continue  # ni reparado cumple la forma: no compite
        lecturas.append({"valor": canonico, "peso": peso,
                         "imagen": evidencia.get("imagen") or evidencia.get("fuente"),
                         "fuente": evidencia.get("fuente") or "ocr",
                         "reparado": reparado, "motivo": motivo})

    if clave in NUNCA_AUTOMATICO:
        humanas = [l for l in lecturas if l["fuente"] in {"manual", "manual_confirmado"}]
        if not humanas:
            return {"valor": None, "peso": round(sum(l["peso"] for l in lecturas), 2),
                    "estado": "solo_lecturas_automaticas", "reparado": False,
                    "opciones": [{"valor": l["valor"], "peso": round(l["peso"], 2),
                                  "imagenes": 1, "reparado": l["reparado"]}
                                 for l in lecturas][:4],
                    "motivo": (f"este campo no se publica sólo con lecturas automáticas "
                               f"({len(lecturas)} lectura(s), ninguna confirmada: se midió que "
                               f"el nivel se lee mal de forma sistemática)")}

    if clave in CARPETA_Y_ETIQUETA:
        carpeta = next((l for l in lecturas if l["fuente"] == "ruta_carpeta"), None)
        etiqueta = [l for l in lecturas if l["fuente"] != "ruta_carpeta"]
        if carpeta is not None:
            contrarias = {l["valor"] for l in etiqueta if l["valor"] != carpeta["valor"]}
            if clave in VETO_FUERTE:
                # sólo veta lo que sostienen dos fotos distintas
                peso_contrario: dict[str, float] = {}
                for lectura in etiqueta:
                    if lectura["valor"] != carpeta["valor"]:
                        peso_contrario[lectura["valor"]] = (peso_contrario.get(lectura["valor"], 0.0)
                                                            + lectura["peso"])
                contrarias = {v for v, peso in peso_contrario.items() if peso >= 2.0}
            if not etiqueta or contrarias:
                motivo = ("la etiqueta no aporta ninguna lectura que confirme la carpeta"
                          if not etiqueta else
                          f"la carpeta dice «{carpeta['valor']}» y la etiqueta dice "
                          f"{', '.join(sorted(contrarias)[:3])}")
                return {"valor": None, "peso": round(carpeta["peso"], 2),
                        "estado": "carpeta_no_confirmada", "opciones": [],
                        "reparado": False, "motivo": motivo}
            return {"valor": carpeta["valor"], "peso": round(carpeta["peso"], 2),
                    "estado": "consenso", "reparado": carpeta["reparado"],
                    "opciones": [{"valor": carpeta["valor"], "peso": round(carpeta["peso"], 2),
                                  "imagenes": len({l["imagen"] for l in etiqueta}),
                                  "reparado": carpeta["reparado"]}],
                    "motivo": "la carpeta y la etiqueta coinciden"}

    if clave in SOLO_CARPETA_MANDA:
        carpeta = next((l for l in lecturas if l["fuente"] == "ruta_carpeta"), None)
        if carpeta is not None:
            return {"valor": carpeta["valor"], "peso": round(carpeta["peso"], 2),
                    "estado": "consenso", "reparado": carpeta["reparado"],
                    "opciones": [{"valor": carpeta["valor"], "peso": round(carpeta["peso"], 2),
                                  "imagenes": 0, "reparado": carpeta["reparado"]}],
                    "motivo": "el nombre de la carpeta decide este campo"}

    if not lecturas:
        return {"valor": None, "peso": 0.0, "estado": "sin_lecturas",
                "opciones": [], "reparado": False, "motivo": "ninguna lectura con forma válida"}

    # Un mismo texto en la MISMA foto no son dos votos. Se cuenta una vez por imagen.
    agrupado: dict[str, dict] = {}
    for lectura in lecturas:
        entrada = agrupado.setdefault(lectura["valor"], {"peso": 0.0, "imagenes": set(),
                                                         "fuentes": set(), "reparado": False,
                                                         "motivo": ""})
        clave_peso = (lectura["fuente"], lectura["imagen"])
        if clave_peso not in entrada["fuentes"]:
            entrada["fuentes"].add(clave_peso)
            entrada["peso"] += lectura["peso"]
        entrada["imagenes"].add(lectura["imagen"])
        entrada["reparado"] = entrada["reparado"] or lectura["reparado"]
        entrada["motivo"] = entrada["motivo"] or lectura["motivo"]

    ranking = sorted(agrupado.items(), key=lambda par: -par[1]["peso"])
    opciones = [{"valor": valor, "peso": round(dato["peso"], 2),
                 "imagenes": len(dato["imagenes"]), "reparado": dato["reparado"]}
                for valor, dato in ranking]
    ganador, datos = ranking[0]
    segundo = ranking[1][1]["peso"] if len(ranking) > 1 else 0.0
    # Una confirmación humana no necesita dos fotos: la persona ya miró la etiqueta.
    confirmado_por_persona = any(
        l["valor"] == ganador and l["fuente"] in {"manual", "manual_confirmado"}
        for l in lecturas)
    minimo_fotos = 1 if confirmado_por_persona else CORROBORACION_MINIMA.get(clave, 1)

    if len(datos["imagenes"]) < minimo_fotos:
        return {"valor": None, "peso": round(datos["peso"], 2), "estado": "soporte_insuficiente",
                "opciones": opciones, "reparado": datos["reparado"],
                "motivo": (f"«{ganador}» lo sostienen {len(datos['imagenes'])} foto(s) y este "
                           f"campo necesita {minimo_fotos}")}
    umbral = 1.0 if clave in UNA_LECTURA_BASTA else UMBRAL_PUBLICACION
    if datos["peso"] < umbral:
        return {"valor": None, "peso": round(datos["peso"], 2), "estado": "soporte_insuficiente",
                "opciones": opciones, "reparado": datos["reparado"],
                "motivo": (f"«{ganador}» reúne {datos['peso']:.1f} puntos y hacen falta "
                           f"{umbral:.1f}")}
    if segundo and datos["peso"] - segundo < MARGEN_EMPATE:
        return {"valor": None, "peso": round(datos["peso"], 2), "estado": "empate",
                "opciones": opciones, "reparado": datos["reparado"],
                "motivo": (f"«{ganador}» ({datos['peso']:.1f}) y «{ranking[1][0]}» "
                           f"({segundo:.1f}) están demasiado cerca")}
    return {"valor": ganador, "peso": round(datos["peso"], 2), "estado": "consenso",
            "opciones": opciones, "reparado": datos["reparado"],
            "motivo": datos["motivo"] or f"{len(datos['imagenes'])} foto(s) coinciden"}


def rescatar(campos: dict, evidencias_por_clave: dict, solo_estados=None,
             excluir=None) -> dict:
    """Rellena con consenso los campos que el consolidador dejó SIN valor.

    No toca ningún campo que ya tenga valor ni ninguna decisión humana: sólo intenta sacar
    de la duda los que quedaron en blanco. Devuelve ``{clave: decisión}`` con lo rescatado y
    anota en el propio campo el motivo y las opciones para la cola de dudas.
    """
    solo_estados = solo_estados or {"conflicto", "faltante", "faltante_requerido",
                                    "forma_invalida", "pendiente_corroboracion"}
    # Un conflicto deliberado (p. ej. la semana EDAG que no cuadra con la fecha de prueba) no
    # se rescata: se marcó a propósito y hay que mirarlo, no promediarlo.
    excluir = set(excluir or ())
    rescatados = {}
    for clave, campo in campos.items():
        if clave in excluir:
            continue
        pendientes = [e for e in evidencias_por_clave.get(clave, [])
                      if e.get("requiere_confirmacion_manual") and not e.get("confirmacion_manual")]
        if pendientes:
            continue  # el propio extractor dice que esto lo tiene que confirmar una persona
        if campo.get("valor") not in (None, ""):
            continue
        if str(campo.get("estado") or "") not in solo_estados:
            continue
        if campo.get("confirmacion_manual"):
            continue
        decision = consensuar(clave, evidencias_por_clave.get(clave, []),
                              reparar_con=[campo.get("valor_propuesto") or ""])
        opciones = decision["opciones"]
        if decision["valor"] is not None:
            campo.update(valor=decision["valor"], estado="consenso_ponderado",
                         requiere_revision=False, decision_v15_10="CONSENSO",
                         peso_consenso=decision["peso"],
                         motivo_consenso=decision["motivo"],
                         reparado_por_forma=decision["reparado"],
                         opciones_consenso=opciones)
            rescatados[clave] = decision
        else:
            campo["opciones_consenso"] = opciones
            campo["motivo_consenso"] = decision["motivo"]
            campo["estado_consenso"] = decision["estado"]
    return rescatados
