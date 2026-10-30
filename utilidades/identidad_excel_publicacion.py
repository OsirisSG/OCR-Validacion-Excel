"""Política de publicación Excel compatible con proyecto elegido por el usuario.

V15.10.1 R3
------------
La plantilla es un contrato de formato, no la fuente de identidad del proyecto.
Cuando el usuario eligió explícitamente el proyecto para esta ejecución y la
plantilla NO contiene una celda de proyecto mapeable, se permite publicar si y
sólo si no existe ninguna contradicción real/estructural. La selección humana
queda registrada en el bloque de identidad; no se hace búsqueda/reemplazo global
ni se modifica un título contradictorio.

Las contradicciones reales siguen fallando de forma cerrada.
"""
from __future__ import annotations

from typing import Any

_ORIGENES_USUARIO = {
    "declarado_usuario", "seleccion_usuario", "usuario", "dashboard_usuario",
    "confirmado_usuario", "seleccion_explicita_usuario",
}

_NOTAS_FALLBACK = {
    "es": ("Plantilla sin celda de proyecto mapeable: identidad tomada de la "
           "selección explícita del usuario para esta ejecución. No se modificaron "
           "títulos ni referencias no mapeadas."),
    "en": ("Template without a mappable project cell: identity taken from the "
           "user's explicit selection for this run. Unmapped titles/references "
           "were not modified."),
    "de": ("Vorlage ohne zuordenbare Projektzelle: Identität aus der expliziten "
           "Benutzerauswahl für diesen Lauf. Nicht zugeordnete Titel/Referenzen "
           "wurden nicht geändert."),
}


def _origen_usuario(identidad: dict | None, meta: dict | None) -> bool:
    identidad = identidad or {}
    meta = meta or {}
    origen = str(identidad.get("origen") or "").strip().casefold()
    if origen in _ORIGENES_USUARIO:
        return True
    # Compatibilidad futura: un origen nuevo puede declarar expresamente el
    # carácter humano, sin abrir el fallback para identidades legacy/config.
    return bool(identidad.get("declarado_por_usuario") is True
                or identidad.get("seleccion_explicita") is True)


def _fallback_permitido(identidad: dict | None, meta: dict | None) -> bool:
    identidad = identidad or {}
    meta = meta or {}
    if not identidad or identidad.get("sin_asignar"):
        return False
    if not _origen_usuario(identidad, meta):
        return False
    if meta.get("publicable") is not False:
        return False
    if meta.get("contradicciones"):
        return False
    # Si ya se identificaron celdas pero la política base bloqueó, hay otra
    # causa que no debe ser ignorada por este fallback.
    if meta.get("celdas") or meta.get("celdas_complementarias"):
        return False
    return bool(meta.get("decision_usuario_confirmada", True))


def _limpiar_marcadores_borrador(libro, hoja_resumen: str, idioma: str) -> None:
    """Retira sólo marcadores generados por la política base para este caso.

    Nunca toca títulos existentes ni fórmulas; únicamente celdas cuyo valor
    coincide exactamente con los textos internos de advertencia/borrador.
    """
    from utilidades.identidad_excel import textos_identidad

    if hoja_resumen not in libro.sheetnames:
        return
    hoja = libro[hoja_resumen]
    t = textos_identidad(idioma)
    a_borrar = {t.get("advertencia"), t.get("borrador")}
    for fila in hoja.iter_rows():
        for celda in fila:
            if celda.value in a_borrar:
                celda.value = None
            elif celda.value == t.get("verificacion"):
                # La identidad se verifica por una decisión humana explícita,
                # no por una celda heredada de la plantilla.
                hoja.cell(celda.row, celda.column + 1, t.get("afirmativo"))

    fila = max((hoja.max_row or 1), 1) + 1
    hoja.cell(fila, 1, _NOTAS_FALLBACK.get((idioma or "es").lower(), _NOTAS_FALLBACK["es"]))


def aplicar_identidad_a_salida_publicable(libro, identidad: dict | None, *,
                                            idioma: str = "es",
                                            hojas_busqueda: list[str],
                                            hoja_resumen: str,
                                            fila_max: int = 4,
                                            hojas_exentas: list[str] | None = None) -> dict[str, Any]:
    """Aplica la política base y habilita sólo el fallback seguro solicitado."""
    from utilidades.identidad_excel import aplicar_identidad_a_salida

    meta = aplicar_identidad_a_salida(
        libro, identidad, idioma=idioma, hojas_busqueda=hojas_busqueda,
        hoja_resumen=hoja_resumen, fila_max=fila_max,
        hojas_exentas=hojas_exentas)

    if not _fallback_permitido(identidad, meta):
        return meta

    _limpiar_marcadores_borrador(libro, hoja_resumen, idioma)
    meta = dict(meta)
    meta.update({
        "publicable": True,
        "identidad_verificada": True,
        "estado_identidad": "verificada_por_seleccion_usuario",
        "fuente_verificacion": "seleccion_usuario",
        "fallback_plantilla_sin_celda": True,
        "advertencias": [],
    })
    return meta
