from pathlib import Path
import math
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utilidades.validacion_entradas import (  # noqa: E402
    es_raiz_codigo_seleccionada,
    validar_bbox_normalizado,
    validar_nombre_excel,
)


def test_nombre_excel_normaliza_extension():
    assert validar_nombre_excel("resultado") == "resultado.xlsx"
    assert validar_nombre_excel("resultado.XLSX") == "resultado.XLSX"


def test_nombre_excel_rechaza_errores_windows_y_rutas():
    malos = ["../x.xlsx", "sub/x.xlsx", "CON.xlsx", "aux.xlsx", "a?.xlsx", "x. ", "NUL"]
    for valor in malos:
        try:
            validar_nombre_excel(valor)
        except ValueError:
            pass
        else:
            raise AssertionError(f"debio rechazarse: {valor}")


def test_bbox_video_valida_geometria_real():
    assert validar_bbox_normalizado([0.1, 0.2, 0.8, 0.9]) == [0.1, 0.2, 0.8, 0.9]
    for bbox in ([0.8, 0.2, 0.1, 0.9], [0.1, 0.9, 0.8, 0.2],
                 [-0.1, 0.2, 0.8, 0.9], [0.1, 0.2, 1.1, 0.9],
                 [0.1, 0.2, 0.100001, 0.9], [0.1, 0.2, math.inf, 0.9]):
        try:
            validar_bbox_normalizado(bbox)
        except ValueError:
            pass
        else:
            raise AssertionError(f"debio rechazarse: {bbox}")


def test_no_procesar_raiz_del_programa(tmp_path):
    assert es_raiz_codigo_seleccionada(tmp_path, tmp_path)
    assert not es_raiz_codigo_seleccionada(tmp_path / "datos", tmp_path)


def test_instalador_r14_es_transaccional_y_hace_preflight():
    instalador = ROOT / "INSTALAR_R14.ps1"
    if not instalador.is_file():
        pytest.skip("El instalador sólo existe en el paquete distribuible, no en el árbol instalado.")
    texto = instalador.read_text(encoding="utf-8-sig")
    for patron in (
        "Rollback-Transaction", "Assert-VMatrixStopped", "Assert-TargetWritable",
        "Assert-FreeSpace", "Assert-SafeRelative", "Copy-Verified",
        "PATCH_INSTALLED_V15_10_1_R14.json", "15.10.1-r14",
    ):
        assert patron in texto
    assert "Rollback-Transaction" in texto.split("catch", 1)[-1]


def test_backend_publica_salud_y_persistencia_segura():
    # R15.5 (SUPERSEDE documentado): el pin de versión sigue el release. La
    # auditoría preventiva R14 fijaba PATCH_BUILD = "15.10.1-r14"; R15 publicó
    # "15.10.1-r15", R15.1 "15.10.1-r15.1", R15.2 "15.10.1-r15.2", R15.3
    # "15.10.1-r15.3", R15.4 "15.10.1-r15.4", R15.5 "15.10.1-r15.5" y R15.6
    # publica "15.10.1-r15.6".
    # Todo lo demás del contrato R14 se conserva.
    texto = (ROOT / "dashboard/backend/app.py").read_text(encoding="utf-8")
    assert '@app.get("/api/salud")' in texto
    assert '"persistencia_segura"' in texto
    assert "validar_bbox_normalizado" in texto
    assert "validar_nombre_excel" in texto
    assert "es_raiz_codigo_seleccionada" in texto
    # R15.8: el build publicado avanza con el paquete vigente (antes r15.7);
    # se lee de la fuente única de identidad para no acoplar el contrato R14
    # a un literal que cambia en cada release.
    build = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    assert f'PATCH_BUILD = "{build}"' in texto


def test_frontend_cache_r14():
    # R15.7 (SUPERSEDE documentado): el busteo de caché del frontend sigue el
    # release (r14 -> ... -> r15.7 -> r15.8) y no debe quedar ningún asset con
    # versión vieja. La versión esperada se lee de VERSION.txt (fuente única).
    build = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    index = (ROOT / "dashboard/frontend/index.html").read_text(encoding="utf-8")
    assert index.count(build) >= 5
    assert 'v=15.10.1-r15"' not in index
    assert "15.10.1-r14" not in index
    assert "15.10.1-r15.1" not in index
    assert "15.10.1-r15.2" not in index
    assert "15.10.1-r15.3" not in index
    assert "15.10.1-r15.4" not in index
    assert "v=15.10.1-r15.6" not in index
    assert "v=15.10.1-r15.7" not in index
