"""R15 · Instalador transaccional con preflight fail-closed (MEDIA-12).

Prueba obligatoria 17 de la auditoría R14: «CIM falla durante la instalación
⇒ fallback o abortar, NUNCA continuar silenciosamente».

El ``Assert-VMatrixStopped`` de R14 hacía ``try { Get-CimInstance … } catch
{ return }``: si CIM/WMI estaba deshabilitado, denegado o fallaba, el
instalador continuaba SIN comprobar que V-Matrix estuviera cerrado, aunque el
README presentaba ese preflight como garantía.

Corrección R15 (plan del usuario + auditoría §7): aviso visible + fallback
con ``Get-Process``; si tampoco puede validar, FALLA CERRADO salvo ``-Force``
explícito. Además el instalador R15 conserva el patrón transaccional R14
(manifiesto SHA-256, copia verificada, backup_pre_R15, rollback automático).

Sin pwsh disponible en el entorno de CI, la verificación es a nivel de
código fuente (mismo criterio que test_v15_10_1_r14_auditoria_preventiva).
La ejecución real en Windows queda pendiente de validación de campo.

R15.5 (SUPERSEDE documentado): el instalador se renombra INSTALAR_R15_5.* y
la identidad pasa a 15.10.1-r15.5 (auditoría R15.4, identidad del release).
R15.4 (SUPERSEDE documentado): el instalador se renombra INSTALAR_R15_4.* y
la identidad pasa a 15.10.1-r15.4 (auditoría R15.3, identidad del release).
R15.3 (SUPERSEDE documentado): el instalador se renombra INSTALAR_R15_3.* y
la identidad pasa a 15.10.1-r15.3 (auditoría R15.2, identidad del release).
R15.2 (SUPERSEDE documentado): el instalador se renombra INSTALAR_R15_2.* y
la identidad pasa a 15.10.1-r15.2 (auditoría R15.1, MEDIO/BAJO-06).
R15.1: el instalador se renombró INSTALAR_R15_1.* y
su identidad sigue al release (manifiesto MANIFEST_SHA256_R15_1.txt, marker
PATCH_INSTALLED_V15_10_1_R15_1.json, backup _BACKUP_PRE_R15_1_,
PatchBuild 15.10.1-r15.1). Los contratos probados aquí son los mismos.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PS1 = RAIZ / "INSTALAR_R15_5.ps1"
BAT = RAIZ / "INSTALAR_R15_5.bat"

# Mismo criterio que test_instalador_r14: el instalador sólo existe en el
# paquete distribuible (raíz del ZIP), no en el árbol instalado.
pytestmark = pytest.mark.skipif(
    not PS1.is_file(),
    reason="El instalador sólo existe en el paquete distribuible, no en el árbol instalado.")


def _texto() -> str:
    assert PS1.is_file(), "Falta INSTALAR_R15_4.ps1 en la raíz del paquete"
    return PS1.read_text(encoding="utf-8-sig")


def _funcion(texto: str, nombre: str) -> str:
    patron = re.compile(
        rf"function {re.escape(nombre)}\b.*?(?=\nfunction |\ntry \{{)",
        re.DOTALL)
    match = patron.search(texto)
    assert match, f"no se encontró la función {nombre}"
    return match.group(0)


def test_preflight_procesos_falla_cerrado_si_cim_falla():
    """Prueba obligatoria 17: CIM falla ⇒ fallback visible o abortar."""
    texto = _texto()
    preflight = _funcion(texto, "Assert-VMatrixStopped")
    # R14: `catch { return }` — continuación silenciosa prohibida.
    assert not re.search(r"catch\s*\{\s*return\s*\}", preflight), (
        "el preflight sigue fallando ABIERTO: catch { return }")
    # Fallback con Get-Process cuando CIM no está disponible.
    assert "Get-Process" in preflight, "falta el fallback Get-Process"
    # Aviso visible del fallo de CIM.
    assert "Write-Warning" in preflight, "el fallo de CIM debe avisar de forma visible"
    # Si nada pudo validarse: aborto (throw) salvo -Force explícito.
    assert re.search(r"if\s*\(\s*\$Force\s*\)", preflight), (
        "el preflight no distingue -Force explícito")
    assert preflight.count("throw") >= 2, (
        "el preflight debe lanzar tanto si hay procesos activos como si no pudo verificar")


def test_param_force_existe_y_no_es_predeterminado():
    texto = _texto()
    assert re.search(r"param\([^)]*\[switch\]\$Force", texto, re.DOTALL), (
        "falta [switch]$Force en param()")


def test_instalador_r15_5_es_transaccional_con_backup_pre_r15_5():
    texto = _texto()
    for patron in (
        "Rollback-Transaction", "Assert-VMatrixStopped", "Assert-TargetWritable",
        "Assert-FreeSpace", "Assert-SafeRelative", "Copy-Verified",
        "PATCH_INSTALLED_V15_10_1_R15_5.json", "15.10.1-r15.5",
        "MANIFEST_SHA256_R15_5.txt",
        "_BACKUP_PRE_R15_5_",
        "PARCHE_R15_5_COPIADO_Y_VERIFICADO_OK",
    ):
        assert patron in texto, f"falta {patron} en INSTALAR_R15_5.ps1"
    # El rollback se invoca en el catch final (transacción real).
    assert "Rollback-Transaction" in texto.split("catch", 1)[-1]
    # La copia verificada compara SHA-256 antes y después del move.
    copia = _funcion(texto, "Copy-Verified")
    assert copia.count("Get-Sha256") >= 2


def test_instalador_r14_conservado_como_referencia():
    """El instalador R14 auditado queda en el árbol sin modificar."""
    r14 = RAIZ / "INSTALAR_R14.ps1"
    assert r14.is_file()
    texto = r14.read_text(encoding="utf-8-sig")
    assert "PATCH_INSTALLED_V15_10_1_R14.json" in texto
    assert "15.10.1-r14" in texto


def test_bat_r15_5_invoca_al_ps1_y_reporta():
    assert BAT.is_file(), "Falta INSTALAR_R15_5.bat"
    texto = BAT.read_text(encoding="utf-8", errors="replace")
    assert "INSTALAR_R15_5.ps1" in texto
    assert "15.10.1-r15.5" in texto
    assert "ERRORLEVEL" in texto
