"""R15.8 · Instalador con identidad única de versión + P2 de la revalidación.

Cubre los hallazgos de documentación/operación de
`AUDITORIA_REVALIDADA_R15_7_20261016.md` y la identidad del release vigente:

* BAJO-09 — el README raíz ya no se presenta como R15.6: declara R15.8.
* BAJO-10 — los mensajes de ``INSTALAR_R15_8.ps1`` derivan de UNA variable de
  versión (``$PatchBuild``); ningún mensaje menciona R15.6.
* BAJO-11 — el runbook no usa un conteo fijo de integridad (el «17/17» del
  runbook R15.7 producía falso diagnóstico con un payload mayor).
* Observación «Tmax» — definición formal: Tmax = tiempo de apertura publicado
  (no el «máximo inflado» del análisis de video).
* ALTO-03/04/05 + MEDIO-08 de las auditorías R15/R15.1 (contratos heredados):
  base conocida fail-closed, marker por contenido, marker previo respaldado,
  rollback de reubicaciones, VERSION.txt verificado, .bat reenvía ``%*``.

Sin pwsh disponible en CI, la verificación es a nivel de código fuente (mismo
criterio que las suites de instaladores anteriores). La ejecución real en
Windows con fallo inducido queda documentada como validación de campo
(``validacion_campo/VALIDACION_CAMPO_R15_8.md``, §9-6).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PS1 = RAIZ / "INSTALAR_R15_8.ps1"
BAT = RAIZ / "INSTALAR_R15_8.bat"

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
# Contratos heredados (R15/R15.1/R15.2) — el instalador R15.8 los conserva
# --------------------------------------------------------------------------

def test_bat_reenvia_argumentos_al_ps1():
    assert BAT.is_file(), "Falta INSTALAR_R15_8.bat"
    texto = BAT.read_text(encoding="utf-8", errors="replace")
    assert "INSTALAR_R15_8.ps1" in texto
    linea = next(l for l in texto.splitlines() if "INSTALAR_R15_8.ps1" in l)
    assert "%*" in linea, "el .bat no reenvía argumentos: 'INSTALAR_R15_8.bat -Force' no transmite -Force"


def test_preflight_exige_base_conocida_antes_de_modificar():
    texto = _texto()
    base = _funcion(texto, "Assert-BaseConocida")
    assert "VERSION.txt" in base
    for version in ("15.10.1-r14", "15.10.1-r15", "15.10.1-r15.1",
                    "15.10.1-r15.2", "15.10.1-r15.3", "15.10.1-r15.4",
                    "15.10.1-r15.5", "15.10.1-r15.6", "15.10.1-r15.7",
                    "15.10.1-r15.8"):
        assert version in base, f"falta la base aceptada {version}"
    for marker in ("PATCH_INSTALLED_V15_10_1_R14.json",
                   "PATCH_INSTALLED_V15_10_1_R15.json",
                   "PATCH_INSTALLED_V15_10_1_R15_1.json",
                   "PATCH_INSTALLED_V15_10_1_R15_2.json",
                   "PATCH_INSTALLED_V15_10_1_R15_3.json",
                   "PATCH_INSTALLED_V15_10_1_R15_4.json",
                   "PATCH_INSTALLED_V15_10_1_R15_5.json",
                   "PATCH_INSTALLED_V15_10_1_R15_6.json",
                   "PATCH_INSTALLED_V15_10_1_R15_7.json",
                   "PATCH_INSTALLED_V15_10_1_R15_8.json"):
        assert marker in base, f"falta el marker aceptado {marker}"
    assert "throw" in base, "base desconocida debe abortar"
    # Debe ejecutarse ANTES de leer manifiesto/copiar/reubicar (nada modifica).
    principal = texto.split("\ntry {", 1)[-1]
    assert principal.index("Assert-BaseConocida") < principal.index("Read-Manifest")
    assert principal.index("Assert-BaseConocida") < principal.index("Copy-Verified $item.Src")


def test_marker_base_se_valida_por_contenido_no_solo_existencia():
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


def test_rollback_retira_copias_de_acumulados():
    texto = _texto()
    relocate = _funcion(texto, "Relocate-LegacyRootDocs")
    rollback = _funcion(texto, "Rollback-Transaction")
    assert "RelocatedDests" in relocate, (
        "las copias a acumulados no se registran al crearse")
    assert "RelocatedDests" in rollback, (
        "el rollback no retira las copias creadas en acumulados")


def test_postflight_verifica_version_txt():
    texto = _texto()
    postflight = texto.split("Verificacion SHA-256 en destino", 1)[-1]
    assert "VERSION.txt" in postflight, (
        "el postflight no verifica VERSION.txt (ALTO-05)")
    assert re.search(r"15\\.10\\.1-r15\\.8", postflight) or \
        "[regex]::Escape($PatchBuild)" in postflight, (
        "el postflight no exige el contenido 15.10.1-r15.8 en VERSION.txt")


# --------------------------------------------------------------------------
# Identidad del release vigente (15.10.1-r15.8)
# --------------------------------------------------------------------------

def test_identidad_r15_8_coherente_en_el_instalador_historico():
    """R15.9 (SUPERSEDE): este módulo verifica el INSTALADOR R15.8 histórico
    (que permanece en el árbol como artefacto). La identidad del árbol
    vigente (VERSION.txt, PATCH_BUILD, cache-busting) la verifica
    ``test_v15_10_1_r15_9_instalador_base.py``; aquí no se exige la versión
    actual para no acoplar un artefacto histórico al release en curso."""
    texto = _texto()
    for patron in ("MANIFEST_SHA256_R15_8.txt",
                   "PATCH_INSTALLED_V15_10_1_R15_8.json",
                   "'15.10.1-r15.8'", "_BACKUP_PRE_R15_8_",
                   "PARCHE_R15_8_COPIADO_Y_VERIFICADO_OK",
                   "R15_8_VERIFICADO_OK"):
        assert patron in texto, f"falta {patron} en INSTALAR_R15_8.ps1"


# --------------------------------------------------------------------------
# BAJO-10 — mensajes del instalador derivados de una única variable
# --------------------------------------------------------------------------

def test_bajo10_mensajes_del_instalador_derivados_de_variable_de_version():
    texto = _texto()
    # Ninguna cadena de usuario cita una versión anterior como si fuera la
    # vigente (BAJO-10: el instalador R15.7 decía «R15.6»).
    assert "R15.6" not in texto, (
        "BAJO-10: mensajes del instalador citan R15.6 (versión equivocada)")
    assert "V-Matrix ' + $PatchBuild" in texto, (
        "el banner de instalación debe derivar de $PatchBuild")
    for ancla in ("index.html no contiene la version de cache",
                  "app.py no contiene PATCH_BUILD",
                  "VERSION.txt no declara "):
        fragmento = next((l for l in texto.splitlines() if ancla in l), "")
        assert fragmento, f"falta el mensaje {ancla!r}"
        assert "$PatchBuild" in fragmento, (
            f"BAJO-10: {ancla!r} usa un literal de versión en vez de la variable")
    # El postflight construye sus regex desde la variable (escapada).
    assert texto.count("[regex]::Escape($PatchBuild)") >= 3, (
        "index/app.py/VERSION.txt deben verificarse con la versión variable")


# --------------------------------------------------------------------------
# BAJO-09 / BAJO-11 / Observación Tmax — documentación y runbook
# --------------------------------------------------------------------------

def test_bajo09_readme_raiz_declara_la_version_vigente():
    """R15.9 (version-aware): el README raíz ya no se identifica con una
    versión anterior; la sección y el instalador citados siguen al release
    vigente (fuente única: VERSION.txt)."""
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    build = (RAIZ / "VERSION.txt").read_text(encoding="utf-8").strip()
    if build.startswith("16."):
        assert f"**Versión V{build}" in readme
        assert "INSTALAR_V16.bat" in readme
        return
    sufijo = build.split("-", 1)[1].upper().replace(".", "_")  # R15_9
    release = sufijo.replace("_", ".")                          # R15.9
    assert f"**Versión V15.10.1 · {release}" in readme, (
        "BAJO-09: el README raíz aún se identifica con una versión anterior")
    assert "**Versión V15.10.1 · R15.6" not in readme
    # La familia del instalador conserva el nombre R15_9 aunque el build de
    # revisión use la identidad inequívoca R15.9.1.
    sufijo_instalador = "R15_9" if sufijo == "R15_9_1" else sufijo
    assert f"INSTALAR_{sufijo_instalador}.bat" in readme
    assert f"### {release}" in readme


def test_bajo11_runbook_sin_conteo_fijo_de_integridad():
    for runbook in ("VALIDACION_CAMPO_R15_8.md", "VALIDACION_CAMPO_R15_7.md"):
        ruta = RAIZ / "validacion_campo" / runbook
        assert ruta.is_file(), f"falta {runbook}"
        texto = ruta.read_text(encoding="utf-8")
        assert "17/17" not in texto, (
            f"BAJO-11: {runbook} conserva un conteo fijo que produce falso "
            "diagnóstico cuando el payload cambia")
    vigente = (RAIZ / "validacion_campo" / "VALIDACION_CAMPO_R15_8.md").read_text(
        encoding="utf-8")
    assert "SHA256SUMS.txt" in vigente and "VERIFICAR_SHA256_R15_8" in vigente


def test_observacion_tmax_definicion_formal():
    herramienta = (RAIZ / "validacion_campo" / "validar_tmax_semaforo.py").read_text(
        encoding="utf-8")
    assert "máximo inflado" in herramienta and "tiempo de apertura PUBLICADO" in herramienta, (
        "la herramienta no define formalmente Tmax vs máximo inflado")
    runbook = (RAIZ / "validacion_campo" / "VALIDACION_CAMPO_R15_8.md").read_text(
        encoding="utf-8")
    assert "tiempo de apertura PUBLICADO" in runbook
    assert "máximo inflado" in runbook and "NO es el" in runbook


def test_soak_herramienta_documenta_ejecucion_id():
    soak = (RAIZ / "validacion_campo" / "soak_r157.py").read_text(encoding="utf-8")
    assert "MEDIO-07" in soak and "MEDIO-08" in soak, (
        "el soak no documenta la semántica corregida de ejecucion_id")
    assert "locals().get" not in soak, (
        "MEDIO-08: el soak sigue leyendo estado con locals().get()")
