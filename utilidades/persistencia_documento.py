"""R15.2 (CRÍTICO-01/CRÍTICO-02): autoridad ÚNICA de escritura del documento.

Toda escritura de ``validacion_resultados.json`` —backend, pipeline,
validación, migraciones, reprocesos y cualquier escritor futuro— pasa por
este módulo. Contrato exigido por la auditoría independiente R15.1:

    lock por ruta → leer fresco → validar generación/revisión → aplicar
    patch/merge → incrementar revisión → escritura atómica verificada

Reglas:

* El lock es de proceso (``threading.RLock``). Un lock por ruta se resuelve
  dinámicamente para que backend y pipeline compartan la MISMA autoridad
  aunque importen el módulo por separado. La serialización entre procesos
  distintos sigue fuera de contrato (el instalador exige V-Matrix cerrado).
* Las callbacks reciben el documento FRESCO leído dentro del lock y deben
  aplicar sólo su propio patch (re-localizando su objetivo). No deben leer
  el documento por su cuenta ni llamar a caches del backend.
* ``SIN_CAMBIOS``: una callback que decide no mutar devuelve este centinela
  y NO se commitea (la revisión no se infla).
* La revisión es monotónica para TODA mutación: ninguna callback puede
  hacerla retroceder y los reemplazos completos (pipeline/validación)
  heredan la revisión en disco.
* Escritura verificada: si ``escribir_json_seguro`` falla se lanza
  ``EscrituraFallida``; nunca se devuelve éxito con guardado fallido.

Este módulo no conoce FastAPI: lanza excepciones propias que cada capa
traduce a su protocolo (HTTPException 409/404/503/500 en el backend).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from utilidades.persistencia import escribir_json_seguro

__all__ = [
    "SIN_CAMBIOS", "ConflictoRevision", "DocumentoAusente", "FormatoInvalido",
    "EscrituraFallida", "lock_documento", "leer_fresco",
    "verificar_expected_revision", "mutar_documento", "commit_documento",
    "persistir_documento_completo",
]

#: Centinela: la callback no aplicó cambios ⇒ no hay commit.
SIN_CAMBIOS = object()

_locks_por_ruta: dict[str, threading.RLock] = {}
_guarda_locks = threading.Lock()


class ConflictoRevision(Exception):
    """CAS fallido: ``expected_revision`` no coincide con el documento."""

    def __init__(self, mensaje: str, actual: int | None = None,
                 esperada: int | None = None):
        super().__init__(mensaje)
        self.actual = actual
        self.esperada = esperada


class DocumentoAusente(Exception):
    """El documento todavía no existe en disco."""


class FormatoInvalido(Exception):
    """El documento existe pero no tiene el formato esperado."""


class EscrituraFallida(Exception):
    """La escritura atómica verificada falló; el archivo anterior sigue intacto."""


def lock_documento(ruta: str | Path | None = None) -> threading.RLock:
    """Lock del documento para ``ruta`` (RLock reentrante, por ruta resuelta).

    Backend y pipeline obtienen el MISMO objeto para la misma ruta: es la
    autoridad de serialización intra-proceso.
    """
    if ruta is None:
        clave = "<global>"
    else:
        try:
            clave = str(Path(ruta).resolve())
        except OSError:
            clave = str(ruta)
    with _guarda_locks:
        lock = _locks_por_ruta.get(clave)
        if lock is None:
            lock = threading.RLock()
            _locks_por_ruta[clave] = lock
        return lock


def leer_fresco(ruta: str | Path) -> dict:
    """Lee el documento directo de disco (sin caches).

    Lanza ``DocumentoAusente`` si no existe y ``FormatoInvalido`` si está
    corrupto o no tiene ``resultados`` en lista (fail-closed: un documento
    ilegible nunca se sobrescribe en silencio).
    """
    ruta = Path(ruta)
    if not ruta.exists():
        raise DocumentoAusente(str(ruta))
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise FormatoInvalido(f"No se pudieron leer los resultados: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("resultados", []), list):
        raise FormatoInvalido("El documento de resultados no tiene el formato esperado.")
    return doc


def verificar_expected_revision(expected: Any, datos: dict, *,
                                estricto: bool = False) -> None:
    """Compare-and-swap del documento.

    ``estricto=True`` (mutaciones humanas/UI): un documento YA versionado
    (revisión > 0) rechaza ``expected_revision=None`` — una pestaña vieja no
    puede bypasear el CAS omitiendo el campo. Los documentos sin versionar
    aceptan la primera mutación, que los versiona.
    """
    actual = int(datos.get("revision_documento") or 0)
    if expected is None:
        if estricto and actual > 0:
            raise ConflictoRevision(
                f"El documento ya está versionado (revisión {actual}) y esta "
                "petición no envía expected_revision; recarga la pantalla y "
                "reintenta.", actual=actual, esperada=None)
        return
    try:
        esperada = int(expected)
    except (TypeError, ValueError) as exc:
        raise ConflictoRevision(
            f"expected_revision inválida: {expected!r}", actual=actual) from exc
    if esperada != actual:
        raise ConflictoRevision(
            f"Los datos cambiaron (revisión {actual}, esperada {esperada}); "
            "recarga antes de guardar.", actual=actual, esperada=esperada)


def commit_documento(ruta: str | Path, datos: dict, *,
                     post_commit: Callable[[int, dict], None] | None = None) -> int:
    """Incrementa ``revision_documento`` y persiste con escritura verificada.

    Requiere tener ``lock_documento(ruta)`` adquirido. Sella ``generado_en``
    y lanza ``EscrituraFallida`` si el guardado no se pudo verificar.
    """
    revision = int(datos.get("revision_documento") or 0) + 1
    datos["revision_documento"] = revision
    datos["generado_en"] = datetime.now().isoformat(timespec="seconds")
    resultado = escribir_json_seguro(Path(ruta), datos, lanzar=False, compacto=True)
    if not resultado:
        raise EscrituraFallida(str(getattr(resultado, "error", None)
                                   or "escritura no verificada"))
    if post_commit is not None:
        post_commit(revision, datos)
    return revision


def mutar_documento(ruta: str | Path,
                    mutacion: Callable[[dict], Any],
                    expected_revision: Any = None, *,
                    estricto: bool = False,
                    permitir_ausente: bool = False,
                    post_commit: Callable[[int, dict], None] | None = None,
                    ) -> tuple[int, Any]:
    """Primitiva transaccional del documento (contrato completo arriba).

    Devuelve ``(revision_nueva, resultado_de_mutacion)``. Si la callback
    devuelve ``SIN_CAMBIOS`` no se commitea y devuelve
    ``(revision_actual, None)``. Cualquier excepción de la callback propaga
    SIN commitear (el disco queda intacto).
    """
    ruta = Path(ruta)
    with lock_documento(ruta):
        try:
            frescos = leer_fresco(ruta)
        except DocumentoAusente:
            if not permitir_ausente:
                raise
            frescos = {"resultados": []}
        verificar_expected_revision(expected_revision, frescos, estricto=estricto)
        revision_entrada = int(frescos.get("revision_documento") or 0)
        resultado = mutacion(frescos)
        if resultado is SIN_CAMBIOS:
            return revision_entrada, None
        # Monotonía global: ninguna callback puede hacer retroceder la revisión.
        if int(frescos.get("revision_documento") or 0) < revision_entrada:
            frescos["revision_documento"] = revision_entrada
        revision = commit_documento(ruta, frescos, post_commit=post_commit)
        return revision, resultado


def persistir_documento_completo(ruta: str | Path, documento: dict, *,
                                 al_error: Callable[[str], None] | None = None,
                                 ) -> bool:
    """Reemplazo completo del documento por artefactos de pipeline/validación.

    Pasa por la MISMA primitiva: lock compartido, revisión heredada del
    disco (monótona; ``revision_documento`` nunca desaparece) y escritura
    verificada. La protección contra edición concurrente de UI durante el
    pipeline vive en el servidor (409 antes de efectos) — ver
    ``_assert_documento_editable`` en dashboard/backend/app.py.

    Devuelve True si guardó; en fallo llama ``al_error(mensaje)`` (contrato
    heredado de ``escribir_json_seguro``) y devuelve False sin tocar el
    archivo anterior. Un documento en disco corrupto NO se sobrescribe
    (fail-closed V15.9.2): se reporta por ``al_error``.
    """
    def _reemplazar(frescos: dict):
        rev_disco = int(frescos.get("revision_documento") or 0)
        try:
            rev_doc = int(documento.get("revision_documento") or 0)
        except (TypeError, ValueError):
            rev_doc = 0
        nuevo = dict(documento)
        nuevo["revision_documento"] = max(rev_disco, rev_doc)
        frescos.clear()
        frescos.update(nuevo)

    def _sincronizar(revision: int, frescos: dict):
        # El artefacto en memoria refleja lo persistido (revisión/sello):
        # escrituras posteriores del mismo objeto la heredan, no la pierden.
        documento["revision_documento"] = revision
        documento["generado_en"] = frescos.get("generado_en")

    try:
        mutar_documento(ruta, _reemplazar, permitir_ausente=True,
                        post_commit=_sincronizar)
        return True
    except (EscrituraFallida, FormatoInvalido) as exc:
        if al_error is not None:
            al_error(str(exc))
        return False
