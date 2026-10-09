"""Preparación CPU acotada para mantener ocupada la inferencia sin saturar RAM."""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from gestor_recursos import obtener_gestor_recursos


class PreparadorImagenes:
    """Prefetch de lectura/decodificación con una cola acotada y backpressure.

    No ejecuta OCR ni crea modelos CUDA. La GPU sigue teniendo un único propietario.
    """

    def __init__(self, cargar, workers: int = 2, max_pendientes: int = 4):
        self._cargar = cargar
        self._workers = max(1, int(workers))
        self._max = max(1, int(max_pendientes))
        self._pool = ThreadPoolExecutor(max_workers=self._workers, thread_name_prefix="ocr-prep")
        self._futuros: dict[str, Future] = {}
        self._bytes: dict[str, int] = {}
        self._lock = threading.RLock()
        self._gestor = obtener_gestor_recursos()

    def _actualizar(self) -> None:
        self._gestor.actualizar_cola(len(self._futuros), sum(self._bytes.values()), self._workers)


    def _cargar_medido(self, clave: str):
        inicio = time.monotonic()
        try:
            return self._cargar(clave)
        finally:
            self._gestor.registrar_etapa("carga_preparacion_cpu", time.monotonic() - inicio)

    def preparar(self, ruta: str | Path) -> bool:
        clave = str(ruta)
        with self._lock:
            if clave in self._futuros:
                return True
            if (len(self._futuros) >= self._max or self._gestor.ram_bajo_presion()
                    or self._gestor.cpu_bajo_presion()):
                self._actualizar()
                return False
            try:
                self._bytes[clave] = max(0, Path(clave).stat().st_size * 4)
            except OSError:
                self._bytes[clave] = 0
            futuro = self._pool.submit(self._cargar_medido, clave)
            self._futuros[clave] = futuro

            def medir_decodificada(terminado, _clave=clave):
                try:
                    imagen = terminado.result()
                    bytes_reales = int(getattr(imagen, "nbytes", 0) or 0)
                except Exception:
                    bytes_reales = 0
                if bytes_reales:
                    with self._lock:
                        if self._futuros.get(_clave) is terminado:
                            self._bytes[_clave] = bytes_reales
                            self._actualizar()

            futuro.add_done_callback(medir_decodificada)
            self._actualizar()
            return True

    def obtener(self, ruta: str | Path):
        clave = str(ruta)
        with self._lock:
            futuro = self._futuros.pop(clave, None)
            self._bytes.pop(clave, None)
            self._actualizar()
        if futuro is None:
            return None
        inicio_espera = time.monotonic()
        try:
            return futuro.result()
        except Exception:
            # El flujo OCR normal volverá a cargar la imagen y expondrá el error real.
            return None
        finally:
            self._gestor.registrar_etapa(
                "espera_cola_preparacion", time.monotonic() - inicio_espera)

    def descartar(self, ruta: str | Path) -> None:
        clave = str(ruta)
        with self._lock:
            futuro = self._futuros.pop(clave, None)
            self._bytes.pop(clave, None)
            if futuro is not None:
                futuro.cancel()
            self._actualizar()

    def cerrar(self, cancelar: bool = False) -> None:
        with self._lock:
            if cancelar:
                for futuro in self._futuros.values():
                    futuro.cancel()
            self._futuros.clear()
            self._bytes.clear()
            self._actualizar()
        self._pool.shutdown(wait=True, cancel_futures=cancelar)

    def __del__(self):
        try:
            self.cerrar(cancelar=True)
        except Exception:
            pass
