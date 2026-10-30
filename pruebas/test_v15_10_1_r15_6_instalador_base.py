"""R15.1 · Fase 4 — Instalador: base conocida, fail-closed real, VERSION.txt
coherente y rollback transaccional de documentos reubicados.

Hallazgos de la auditoría independiente R15 cubiertos aquí:

* ALTO-03: el fallback ``Get-Process`` fallaba ABIERTO: si veía CUALQUIER
  ruta ejecutable (p. ej. ``C:\\Python311\\python.exe`` ejecutando V-Matrix)
  marcaba ``$verificado = $true`` sin poder ver la línea de comando. Además
  ``INSTALAR_R15.bat`` no reenviaba argumentos (``%*``).
* ALTO-04: el preflight sólo comprobaba archivos genéricos; no exigía una
  base conocida (VERSION.txt R14/R15 o marker), permitiendo instalaciones
  híbridas sobre carpetas viejas o equivocadas.
* ALTO-05: ``VERSION.txt`` quedaba en la versión anterior tras instalar
  (no estaba en el manifiesto ni en el postflight) ⇒ benchmark/soporte
  etiquetados con versión falsa. R15.1: VERSION.txt = 15.10.1-r15.1 y
  postflight lo verifica; backend/frontend/marker/instalador reportan la
  MISMA versión.
* MEDIO-08: ``Relocate-LegacyRootDocs`` eliminaba README_R14.md de la raíz
  (dedup) SIN registrarlo para rollback, y las copias creadas en
  ``docs\\historial\\parches\\acumulados`` no se retiraban al revertir.

R15.6 (SUPERSEDE documentado): el instalador se renombra INSTALAR_R15_6.* y
la identidad del paquete pasa a 15.10.1-r15.6; las bases aceptadas son
acumulativas (r14, r15, r15.1, r15.2, r15.3, r15.4, r15.5, r15.6).
R15.4 (SUPERSEDE documentado): el instalador se renombra INSTALAR_R15_4.* y
la identidad del paquete pasa a 15.10.1-r15.4; las bases aceptadas son
acumulativas (r14, r15, r15.1, r15.2, r15.3, r15.4).

R15.3 (SUPERSEDE documentado): el instalador se renombra INSTALAR_R15_3.* y
la identidad del paquete pasa a 15.10.1-r15.3; las bases aceptadas son
acumulativas (r14, r15, r15.1, r15.2, r15.3).

R15.2 (MEDIO/BAJO-06, auditoría R15.1): el marker de base se valida por
CONTENIDO (patch_build conocido), no sólo por existencia, y la reinstalación
respalda el marker previo para que el rollback lo restaure. SUPERSEDE
documentado: el instalador se renombra INSTALAR_R15_2.* y la identidad del
paquete pasa a 15.10.1-r15.2.

Sin pwsh disponible en CI, la verificación es a nivel de código fuente
(mismo criterio que test_v15_10_1_r15_instalador). La ejecución real en
Windows con fallo inducido queda documentada como validación de campo.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PS1 = RAIZ / "INSTALAR_R15_6.ps1"
BAT = RAIZ / "INSTALAR_R15_6.bat"

pytestmark = pytest.mark.skipif(
    not PS1.is_file(),
    reason="El instalador sólo existe en el paquete distribuible, no en el árbol instalado.")


def _texto() -> str:
    return PS1.read_text(encoding="utf-8-sig")


def _funcion(texto: str, nombre: str) -> str:
    patron = re.compile(
        rf"function {re.escape(nombre)}\b.*?(?=\nfunction |\ntry \{{)",
        re.DOTALL)
    match = patron.search(texto)
    assert match, f"no se encontró la función {nombre}"
    return match.group(0)


# --------------------------------------------------------------------------
# ALTO-03 — fallback Get-Process fail-closed + .bat reenvía argumentos
# --------------------------------------------------------------------------

def test_fallback_get_process_es_fail_closed():
    preflight = _funcion(_texto(), "Assert-VMatrixStopped")
    # La lógica fail-open de R15 (contador de rutas «inspeccionadas» que
    # marcaba verificado=true viendo sólo el ejecutable) debe desaparecer.
    assert "inspeccionados" not in preflight, (
        "el fallback sigue fallando ABIERTO: cuenta rutas inspeccionadas y "
        "da por verificado un intérprete global cuya línea de comando no ve")
    # Sin intérpretes python/pythonw/uvicorn/node ⇒ seguro (V-Matrix no corre).
    assert re.search(r"\$candidatos\.Count\s+-eq\s+0", preflight), (
        "falta la rama 'ningún intérprete en ejecución ⇒ verificado'")
    # Con candidatos cuya línea de comando no es visible ⇒ NO verificado.
    assert "$verificado = $false" in preflight, (
        "el fallback debe dejar $verificado=false cuando existen candidatos")


def test_bat_reenvia_argumentos_al_ps1():
    assert BAT.is_file(), "Falta INSTALAR_R15_6.bat"
    texto = BAT.read_text(encoding="utf-8", errors="replace")
    assert "INSTALAR_R15_6.ps1" in texto
    linea = next(l for l in texto.splitlines() if "INSTALAR_R15_6.ps1" in l)
    assert "%*" in linea, "el .bat no reenvía argumentos: 'INSTALAR_R15_1.bat -Force' no transmite -Force"


# --------------------------------------------------------------------------
# ALTO-04 — preflight de base conocida
# --------------------------------------------------------------------------

def test_preflight_exige_base_conocida_antes_de_modificar():
    texto = _texto()
    base = _funcion(texto, "Assert-BaseConocida")
    assert "VERSION.txt" in base
    for version in ("15.10.1-r14", "15.10.1-r15", "15.10.1-r15.1",
                    "15.10.1-r15.2", "15.10.1-r15.3", "15.10.1-r15.4",
                    "15.10.1-r15.5", "15.10.1-r15.6"):
        assert version in base, f"falta la base aceptada {version}"
    for marker in ("PATCH_INSTALLED_V15_10_1_R14.json",
                   "PATCH_INSTALLED_V15_10_1_R15.json",
                   "PATCH_INSTALLED_V15_10_1_R15_1.json",
                   "PATCH_INSTALLED_V15_10_1_R15_2.json",
                   "PATCH_INSTALLED_V15_10_1_R15_3.json",
                   "PATCH_INSTALLED_V15_10_1_R15_4.json",
                   "PATCH_INSTALLED_V15_10_1_R15_5.json",
                   "PATCH_INSTALLED_V15_10_1_R15_6.json"):
        assert marker in base, f"falta el marker aceptado {marker}"
    assert "throw" in base, "base desconocida debe abortar"
    # Debe ejecutarse ANTES de leer manifiesto/copiar/reubicar (nada modifica).
    principal = texto.split("\ntry {", 1)[-1]
    assert principal.index("Assert-BaseConocida") < principal.index("Read-Manifest")
    assert principal.index("Assert-BaseConocida") < principal.index("Copy-Verified $item.Src")


# --------------------------------------------------------------------------
# ALTO-05 — identidad r15.1 coherente + VERSION.txt verificado
# --------------------------------------------------------------------------

def test_identidad_r15_6_coherente_en_el_instalador_historico():
    """R15.7 (SUPERSEDE): este módulo verifica el INSTALADOR R15.6 histórico
    (que permanece en el árbol como artefacto de rollback). La identidad del
    árbol vigente (VERSION.txt, PATCH_BUILD, cache-busting) la verifica
    ``test_v15_10_1_r15_7_instalador_base.py``; aquí no se exige la versión
    actual para no acoplar un artefacto histórico al release en curso."""
    texto = _texto()
    for patron in ("MANIFEST_SHA256_R15_6.txt",
                   "PATCH_INSTALLED_V15_10_1_R15_6.json",
                   "'15.10.1-r15.6'", "_BACKUP_PRE_R15_6_",
                   "PARCHE_R15_6_COPIADO_Y_VERIFICADO_OK"):
        assert patron in texto, f"falta {patron} en INSTALAR_R15_6.ps1"


# --------------------------------------------------------------------------
# R15.2 (MEDIO/BAJO-06) — marker de base por CONTENIDO + marker previo
# --------------------------------------------------------------------------

def test_marker_base_se_valida_por_contenido_no_solo_existencia():
    """Un marker vacío, corrupto o de otro proyecto no prueba base conocida."""
    base = _funcion(_texto(), "Assert-BaseConocida")
    assert "ConvertFrom-Json" in base, (
        "Assert-BaseConocida sólo comprueba la EXISTENCIA del marker: debe "
        "validar su contenido (patch_build conocido)")
    assert "patch_build" in base


def test_marker_previo_se_respalda_antes_de_sobrescribir():
    texto = _texto()
    assert "_MARKER_PREVIO.json" in texto, (
        "la reinstalación sobrescribe el marker anterior sin respaldo")
    copia = texto.index("_MARKER_PREVIO.json")
    escritura = texto.index("Set-Content -LiteralPath $markerPath")
    assert copia < escritura, "el respaldo debe ocurrir ANTES de sobrescribir"


def test_rollback_restaura_marker_previo():
    rollback = _funcion(_texto(), "Rollback-Transaction")
    assert "_MARKER_PREVIO.json" in rollback, (
        "el rollback no restaura el marker de la instalación anterior")


def test_postflight_verifica_version_txt():
    texto = _texto()
    postflight = texto.split("Verificacion SHA-256 en destino", 1)[-1]
    assert "VERSION.txt" in postflight, (
        "el postflight no verifica VERSION.txt (ALTO-05)")
    assert re.search(r"15\\\.10\\\.1-r15\\\.6", postflight), (
        "el postflight no exige el contenido 15.10.1-r15.6 en VERSION.txt")


# --------------------------------------------------------------------------
# MEDIO-08 — rollback transaccional de reubicaciones
# --------------------------------------------------------------------------

def test_rollback_registra_dedup_de_readme_raiz():
    relocate = _funcion(_texto(), "Relocate-LegacyRootDocs")
    # La eliminación por dedup del README_R14.md de raíz debe registrarse
    # (backup + RootDocsMoved) ANTES de ejecutarla.
    bloque = relocate.split("foreach ($name in", 1)[0]
    assert "RootDocsMoved.Add" in bloque, (
        "el dedup de README_R14.md elimina sin registrar para rollback")
    assert bloque.index("RootDocsMoved.Add") < bloque.index("Remove-Item -LiteralPath $raizR14")


def test_rollback_retira_copias_de_acumulados():
    texto = _texto()
    relocate = _funcion(texto, "Relocate-LegacyRootDocs")
    rollback = _funcion(texto, "Rollback-Transaction")
    # Las copias creadas en docs\historial\parches\acumulados se registran…
    assert "RelocatedDests" in relocate, (
        "las copias a acumulados no se registran al crearse")
    # …y el rollback las retira o restaura el destino previo.
    assert "RelocatedDests" in rollback, (
        "el rollback no retira las copias creadas en acumulados")
