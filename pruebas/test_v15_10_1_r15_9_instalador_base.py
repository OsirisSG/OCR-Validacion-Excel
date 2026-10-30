"""R15.9 · Instalador incremental: verificador de versión por argumento,
contrato de base íntegra y limpieza de metadatos.

Cubre los hallazgos del instalador de la auditoría independiente R15.8
(`AUDITORIA_INDEPENDIENTE_R15_8_20261018.md`):

* ALTO-01 — ``Verify-ImportResolution`` comparaba el PATCH_BUILD del árbol
  contra el LITERAL ``'15.10.1-r15.7'`` ⇒ cualquier instalación correcta de
  R15.8 fallaba con ``SystemExit(33)`` (repro del auditor: exit 33). Ahora la
  versión esperada llega por ARGUMENTO (``sys.argv[2]``) desde ``$PatchBuild``
  y la prueba EJECUTA el snippet real extraído del instalador.
* ALTO-02 — el instalador declaraba bases R14…R15.8 pero el paquete sólo
  lleva el delta R15.8/R15.9: sobre R15.6 quedaba un árbol HÍBRIDO. Decisión
  aplicada (opción «b» del auditor): base restringida a R15.7/R15.8/R15.9 y
  CONTRATO DE INTEGRIDAD por hash (``Assert-BaseIntegra``): un árbol que no
  coincida byte a byte con el contenido conocido de los releases base aborta
  ANTES de copiar nada.
* BAJO-06 — ``$markersBase`` duplicaba el marker R15.8 y el mensaje de error
  citaba bases inexistentes. Ahora: listas únicas y mensaje del contrato real.

Sin pwsh disponible en CI, la verificación es a nivel de código fuente más la
EJECUCIÓN REAL del snippet Python embebido (mismo criterio que las suites de
instaladores anteriores). La ejecución en Windows real queda como validación
de campo (``validacion_campo/VALIDACION_CAMPO_R15_9.md``, §9-6).
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PS1 = RAIZ / "INSTALAR_R15_9.ps1"
BAT = RAIZ / "INSTALAR_R15_9.bat"
VERSION_ACTUAL = (RAIZ / "VERSION.txt").read_text(encoding="utf-8").strip()
BUILD = "15.10.1-r15.9.1" if VERSION_ACTUAL.startswith("16.") else VERSION_ACTUAL

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
# ALTO-01 — el verificador de importaciones usa la versión por ARGUMENTO
# --------------------------------------------------------------------------

def test_alto01_verificador_sin_literales_de_version():
    verificar = _funcion(_texto(), "Verify-ImportResolution")
    assert "sys.argv[2]" in verificar, (
        "ALTO-01: el snippet debe comparar PATCH_BUILD con la versión pasada "
        "por argumento")
    assert "15.10.1-r15.7" not in verificar and "15.10.1-r15.8" not in verificar, (
        "ALTO-01: el verificador conserva un literal de versión obsoleto")
    assert "-c $code $Target $BuildEsperado" in verificar
    firma = _texto()
    assert "Verify-ImportResolution $python $PatchBuild" in firma, (
        "la llamada debe transmitir la versión única del paquete")


def _snippet_verificador() -> str:
    verificar = _funcion(_texto(), "Verify-ImportResolution")
    match = re.search(r"@'\n(.*?)\n'@", verificar, re.DOTALL)
    assert match, "no se encontró el snippet Python embebido"
    return match.group(1)


def _ejecutar_snippet(arbol: Path, build_esperado: str) -> int:
    resultado = subprocess.run(
        [sys.executable, "-c", _snippet_verificador(), str(arbol),
         build_esperado],
        capture_output=True, text=True, timeout=120)
    return resultado.returncode


def test_alto01_snippet_real_del_instalador_acepta_el_arbol_vigente(tmp_path):
    if VERSION_ACTUAL.startswith("16."):
        pytest.skip("El instalador R15.9 es histórico; su import-check exige el backend R15.9.1")
    """Prueba exigida por el auditor: ejecutar el snippet REAL extraído del
    instalador sobre el árbol vigente ⇒ exit 0 (R15.8 devolvía 33)."""
    assert _ejecutar_snippet(RAIZ, BUILD) == 0, (
        "ALTO-01: el snippet real del instalador rechaza el árbol correcto")


def test_alto01_snippet_real_rechaza_un_build_equivocado(tmp_path):
    """El verificador sigue siendo estricto: un árbol cuyo PATCH_BUILD no es
    el esperado debe salir 33 (falso negativo sería peor que el bug)."""
    falso = tmp_path / "arbol_falso"
    falso.mkdir()
    backend = falso / "dashboard" / "backend"
    backend.mkdir(parents=True)
    (backend / "app.py").write_text(
        'import os\nos.environ.setdefault("VMATRIX_SIN_EJECUTAR", "1")\n'
        f'PATCH_BUILD = "{BUILD}"\n', encoding="utf-8")
    # Sin el resto del árbol el snippet falla antes (31); con el árbol real y
    # un argumento equivocado debe fallar por versión (33).
    codigo = _ejecutar_snippet(RAIZ, "15.10.1-r15.7")
    assert codigo == 33, (
        f"el snippet no rechazó (exit {codigo}) una versión distinta de la "
        "esperada")


# --------------------------------------------------------------------------
# ALTO-02 — contrato de base íntegra (árbol híbrido = abortar)
# --------------------------------------------------------------------------

def _tabla_contrato() -> list:
    integridad = _funcion(_texto(), "Assert-BaseIntegra")
    filas = re.findall(
        r"@\('([^']+)', @\(((?:'[0-9a-f]{64}'(?:,\s*)?)+)\), \$(true|false)\)",
        integridad)
    assert filas, "no se encontró la tabla-contrato"
    return [(rel, re.findall(r"'([0-9a-f]{64})'", hashes), req == "true")
            for rel, hashes, req in filas]


def test_alto02_tabla_cubre_todos_los_artefactos_de_los_releases_base():
    """Las 23 claves del manifiesto R15.7 y las 19 del R15.8 deben estar en el
    contrato (unión = 32), y las claves requeridas son exactamente las del
    release base R15.7."""
    filas = {rel: (set(hashes), req) for rel, hashes, req in _tabla_contrato()}
    assert len(filas) == 32, (
        f"el contrato debe cubrir 32 claves (unión R15.7∪R15.8), tiene {len(filas)}")
    # El árbol no lleva los manifiestos históricos; el contrato se valida
    # contra los ficheros congelados del paquete R15.7 si están disponibles.
    paquete157 = RAIZ.parent / "paquete_R15_7" / "MANIFEST_SHA256_R15_7.txt"
    paquete158 = RAIZ.parent / "paquete_R15_8" / "MANIFEST_SHA256_R15_8.txt"
    if not paquete157.is_file() or not paquete158.is_file():
        pytest.skip("manifiestos congelados no disponibles en este árbol")
    claves157 = {l.split(None, 1)[1].strip()
                 for l in paquete157.read_text().splitlines() if l.strip()}
    claves158 = {l.split(None, 1)[1].strip()
                 for l in paquete158.read_text().splitlines() if l.strip()}
    assert set(filas) == claves157 | claves158
    assert {rel for rel, (_, req) in filas.items() if req} == claves157


def test_alto02_el_arbol_vigente_satisface_el_contrato_completo():
    if VERSION_ACTUAL.startswith("16."):
        pytest.skip("El contrato R15.9.1 describe versiones base históricas, no V16")
    """Validación FUNCIONAL: cada fichero del árbol vigente tiene el hash que
    el instalador acepta como base (r15.9 recién instalado = reinstalable)."""
    filas = _tabla_contrato()
    for rel, hashes, requerido in filas:
        ruta = RAIZ / rel
        if not ruta.is_file():
            assert not requerido, f"falta {rel} (requerido por el contrato)"
            continue
        assert hashlib.sha256(ruta.read_bytes()).hexdigest() in hashes, (
            f"ALTO-02: {rel} del árbol vigente NO pasa el contrato del "
            "propio instalador")


def test_alto02_un_hash_r15_6_rechazado_por_el_contrato():
    """Cruce con el manifiesto R15.6 auditado: sus hashes NO deben aceptarse
    (un árbol R15.6 con VERSION editada aborta — el bug ALTO-02)."""
    paquete157 = RAIZ.parent / "paquete_R15_7" / "MANIFEST_SHA256_R15_7.txt"
    manifest_r15_6 = RAIZ.parent / "repo_parches" / "MANIFEST_SHA256_R15_6.txt"
    if not paquete157.is_file() or not manifest_r15_6.is_file():
        pytest.skip("manifiestos históricos no disponibles en este árbol")
    filas = {rel: set(hashes) for rel, hashes, _ in _tabla_contrato()}
    r15_6 = {}
    for linea in manifest_r15_6.read_text(encoding="utf-8",
                                          errors="replace").splitlines():
        if re.match(r"^[0-9a-f]{64}\s+\S", linea):
            h, rel = linea.split(None, 1)
            r15_6[rel.strip()] = h
    comunes = set(r15_6) & set(filas)
    assert comunes, "el manifiesto R15.6 no solapa con el contrato"
    rechazados = [rel for rel in comunes if r15_6[rel] not in filas[rel]]
    assert rechazados, (
        "ALTO-02: el contrato acepta contenido R15.6 ⇒ no frenaría un árbol "
        "híbrido")


def test_alto02_la_tabla_se_evalua_antes_de_copiar():
    texto = _texto()
    principal = texto.split("\ntry {", 1)[-1]
    assert principal.index("Assert-BaseConocida") < principal.index("Assert-BaseIntegra")
    assert principal.index("Assert-BaseIntegra") < principal.index("Read-Manifest")
    assert principal.index("Assert-BaseIntegra") < principal.index("Copy-Verified $item.Src")


def test_alto02_bases_restringidas_a_r15_7_en_adelante():
    base = _funcion(_texto(), "Assert-BaseConocida")
    for vieja in ("15.10.1-r14", "'15.10.1-r15'", "15.10.1-r15.1",
                  "15.10.1-r15.2", "15.10.1-r15.3", "15.10.1-r15.4",
                  "15.10.1-r15.5", "15.10.1-r15.6"):
        assert vieja not in base, f"la base obsoleta {vieja} sigue aceptada"
    for valida in ("15.10.1-r15.7", "15.10.1-r15.8", "15.10.1-r15.9", BUILD):
        assert valida in base


# --------------------------------------------------------------------------
# BAJO-06 — metadatos limpios
# --------------------------------------------------------------------------

def test_bajo06_markers_y_bases_sin_duplicados():
    base = _funcion(_texto(), "Assert-BaseConocida")
    markers = re.search(r"\$markersBase = @\(([^)]*)\)", base).group(1)
    lista = re.findall(r"'([^']+)'", markers)
    assert len(lista) == len(set(lista)), (
        "BAJO-06: $markersBase contiene markers duplicados")
    bases = re.search(r"\$basesVersion = @\(([^)]*)\)", base).group(1)
    lista_bases = re.findall(r"'([^']+)'", bases)
    assert len(lista_bases) == len(set(lista_bases))


# --------------------------------------------------------------------------
# Contratos heredados + identidad del release vigente
# --------------------------------------------------------------------------

def test_bat_reenvia_argumentos_al_ps1():
    assert BAT.is_file()
    texto = BAT.read_text(encoding="utf-8", errors="replace")
    linea = next(l for l in texto.splitlines() if "INSTALAR_R15_9.ps1" in l)
    assert "%*" in linea


def test_identidad_r15_9_coherente_en_todo_el_paquete():
    if VERSION_ACTUAL.startswith("16."):
        pytest.skip("Identidad del instalador histórico; V16 se valida con test_v16_identidad")
    texto = _texto()
    for patron in ("MANIFEST_SHA256_R15_9.txt",
                   "PATCH_INSTALLED_V15_10_1_R15_9.json",
                   f"'{BUILD}'", "_BACKUP_PRE_R15_9_",
                   "PARCHE_R15_9_COPIADO_Y_VERIFICADO_OK",
                   "R15_9_VERIFICADO_OK"):
        assert patron in texto, f"falta {patron} en INSTALAR_R15_9.ps1"
    version = (RAIZ / "VERSION.txt").read_text(encoding="utf-8").strip()
    assert version == BUILD, f"VERSION.txt={version!r}"
    app = (RAIZ / "dashboard" / "backend" / "app.py").read_text(encoding="utf-8")
    assert f'PATCH_BUILD = "{BUILD}"' in app
    assert 'version=PATCH_BUILD' in app
    index = (RAIZ / "dashboard" / "frontend" / "index.html").read_text(encoding="utf-8")
    assert index.count(f"v={BUILD}") >= 5


def test_postflight_verifica_version_txt():
    texto = _texto()
    postflight = texto.split("Verificacion SHA-256 en destino", 1)[-1]
    assert "VERSION.txt" in postflight
    assert re.search(re.escape(BUILD), postflight) or \
        "[regex]::Escape($PatchBuild)" in postflight


def test_marker_previo_y_rollback_intactos():
    texto = _texto()
    assert "_MARKER_PREVIO.json" in texto
    assert "_MARKER_PREVIO.json" in _funcion(texto, "Rollback-Transaction")
    assert "ConvertFrom-Json" in _funcion(texto, "Assert-BaseConocida")


def test_runbook_documenta_verifyonly_solo_post_instalacion():
    """Evita repetir MEDIO-A: VerifyOnly verifica el payload final y no la base."""
    runbook = (RAIZ / "validacion_campo" / "VALIDACION_CAMPO_R15_9.md").read_text(
        encoding="utf-8")
    assert "VerifyOnly post-instalación" in runbook
    assert "Tras completar el escenario 6" in runbook
    assert "No ejecutarlo sobre una base R15.7/R15.8 previa" in runbook
