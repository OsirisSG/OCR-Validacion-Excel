from pathlib import Path

from aprendizaje import GestorAprendizaje


def _gestor(tmp_path):
    return GestorAprendizaje({"aprendizaje": {"activar": True}}, directorio=tmp_path / "modelo")


def test_aceptar_lectura_es_muestra_entrenable_incluso_al_reconfirmar(tmp_path):
    import cv2
    import numpy as np

    imagen = tmp_path / "aceptada.png"
    assert cv2.imwrite(str(imagen), np.zeros((50, 120, 3), dtype=np.uint8))
    gestor = _gestor(tmp_path)

    primera = gestor.registrar_muestra_visual(
        imagen, "ID-1", "S4054664", "S4054664", [10, 10, 90, 20],
        accion="aceptar", entrenable=True)
    segunda = gestor.registrar_muestra_visual(
        imagen, "ID-1", "S4054664", "S4054664", [10, 10, 90, 20],
        accion="aceptar", entrenable=True)

    assert primera["entrenable"] is True
    assert segunda["duplicada"] is True
    assert segunda["entrenable"] is True
    assert gestor.estado()["muestras_entrenables"] == 1


def test_frontend_supervision_simple_y_aviso_desglosado():
    src = Path("dashboard/frontend/app.js").read_text(encoding="utf-8")
    css = Path("dashboard/frontend/estilos.css").read_text(encoding="utf-8")

    assert '"Aceptar lectura"' in src
    assert '"Aplicar corrección"' in src
    assert 'style=${{display:"none"}}' in src  # selector histórico no visible
    assert 'Aprendizaje automático' in src
    assert 'ⓘ' in src
    assert 'Corrección de texto: modificaste' in src
    assert 'Texto nuevo: escribiste contenido' in src
    assert 'Unir bloques: hay una propuesta preparada sin confirmar' in src
    assert 'Ajustar/dividir bloque: hay cambios de geometría o texto pendientes de guardar' in src
    assert 'caja-union-seleccionada' in src
    assert 'vuelve a pulsar uno para quitarlo' in src
    assert '.ayuda-inline-popover' in css


def test_compatibilidad_guardar_sin_entrenar_ahora_es_evidencia_positiva(tmp_path):
    import cv2
    import numpy as np
    imagen = tmp_path / "legacy.png"
    assert cv2.imwrite(str(imagen), np.zeros((40, 100, 3), dtype=np.uint8))
    gestor = _gestor(tmp_path)
    muestra = gestor.registrar_muestra_visual(
        imagen, "ID-LEGACY", "ABC123", "ABC123", [4, 4, 80, 20],
        accion="guardar_sin_entrenar", entrenable=True)
    assert muestra["entrenable"] is True


def test_backend_fuerza_aprendizaje_en_ediciones_positivas():
    src = Path("dashboard/backend/app.py").read_text(encoding="utf-8")
    assert 'entrenable=True' in src
    assert 'if hasattr(gestor, "registrar_muestra_visual"):' in src
    assert 'if hasattr(gestor, "registrar_union_visual"):' in src
    assert 'Región externa confirmada:' in src
