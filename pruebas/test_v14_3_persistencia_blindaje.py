from __future__ import annotations

import tempfile
import time
from pathlib import Path

from aprendizaje import GestorAprendizaje
from configuracion import cargar_config
from utilidades.cola_excel import ColaExcel


def test_cola_reinicio_automatico_recupera_tres_pendientes():
    """Reproduce el caso real: 3 pendientes + TypeError + reinicio del dashboard."""
    with tempfile.TemporaryDirectory() as td:
        raiz = Path(td)
        db = raiz / "cola.sqlite3"

        def falla_none():
            raise TypeError("'NoneType' object is not iterable")

        primera = ColaExcel(db, falla_none, demora=0.01, reintento=0.02)
        primera.solicitar("corr-1")
        primera.solicitar("corr-2")
        primera.solicitar("corr-3")
        assert primera.procesar() is False
        assert primera.estado()["pendientes"] == 3
        assert primera.estado()["error_tipo"] == "datos_invalidos"

        llamadas = []
        reiniciada = ColaExcel(
            db,
            lambda: llamadas.append(1) or str(raiz / "resultado.xlsx"),
            demora=0.01,
            reintento=0.02,
        )
        reiniciada.iniciar()
        try:
            limite = time.monotonic() + 2.0
            while time.monotonic() < limite and reiniciada.estado()["pendientes"]:
                time.sleep(0.02)
            estado = reiniciada.estado()
            assert estado["pendientes"] == 0
            assert estado["error"] is None
            assert estado["estado_persistencia"] == "guardado"
            # Las tres revisiones pertenecen a una sola instantánea Excel.
            assert llamadas == [1]
        finally:
            reiniciada.detener()


def test_aprendizaje_incremental_acepta_tokens_y_lineas_none():
    with tempfile.TemporaryDirectory() as td:
        raiz = Path(td)
        imagen = raiz / "IMG_NONE.JPG"
        imagen.write_bytes(b"imagen-controlada")
        cfg = cargar_config()
        gestor = GestorAprendizaje(cfg, directorio=raiz / ".aprendizaje")
        resultado = gestor.registrar_observacion_incremental({
            "imagen": str(imagen),
            "motor": "prueba",
            "tokens": None,
            "lineas_texto": None,
        }, ejecucion_id="exec-none")
        assert resultado["registrada"] is True
        assert resultado["tokens"] == 0


def test_aprendizaje_ejecucion_completa_acepta_colecciones_none():
    with tempfile.TemporaryDirectory() as td:
        raiz = Path(td)
        imagen = raiz / "IMG_NONE_2.JPG"
        imagen.write_bytes(b"imagen-controlada-2")
        cfg = cargar_config()
        gestor = GestorAprendizaje(cfg, directorio=raiz / ".aprendizaje")
        resultado = gestor.registrar_ejecucion([{
            "imagen": str(imagen),
            "motor": "prueba",
            "tokens": None,
            "lineas_texto": None,
        }], raiz=str(raiz))
        assert resultado["registrada"] is True
        assert resultado["tokens"] == 0
