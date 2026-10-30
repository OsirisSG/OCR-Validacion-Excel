"""Gestión dinámica de recursos para OCR V14.

No reserva recursos de forma artificial: observa presión real de CPU/RAM/GPU,
registra tiempos del pipeline y ofrece límites conservadores por perfil.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

PERFILES = {
    "estable": {
        "gpu_objetivo": (70, 85), "vram_limite": 75, "ram_limite": 65,
        "cpu_objetivo": (60, 75), "workers_cpu": 2, "cola_max": 4,
    },
    "alto": {
        "gpu_objetivo": (85, 95), "vram_limite": 85, "ram_limite": 80,
        "cpu_objetivo": (75, 90), "workers_cpu": 3, "cola_max": 8,
    },
    "maximo": {
        "gpu_objetivo": (90, 100), "vram_limite": 90, "ram_limite": 85,
        "cpu_objetivo": (85, 95), "workers_cpu": 4, "cola_max": 12,
    },
}


def normalizar_perfil(perfil: str | None) -> str:
    valor = str(perfil or "alto").strip().lower().replace("á", "a")
    aliases = {"stable": "estable", "high": "alto", "maximum": "maximo", "max": "maximo"}
    valor = aliases.get(valor, valor)
    return valor if valor in PERFILES else "alto"


@dataclass
class MuestraEtapa:
    nombre: str
    segundos: float
    momento: float


class GestorRecursos:
    """Monitor ligero, seguro para hilos y sin dependencia obligatoria de psutil."""

    def __init__(self, perfil: str = "alto", ventana: int = 64):
        self._lock = threading.RLock()
        self.perfil = normalizar_perfil(perfil)
        self._inicio = time.monotonic()
        self._completadas = 0
        self._oom = 0
        self._fallback_cpu = 0
        self._batch_actual: int | None = None
        self._workers_activos = 0
        self._cola_pendiente = 0
        self._cola_bytes = 0
        self._etapas: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=ventana))
        self._inferencias: deque[float] = deque(maxlen=ventana)
        self._ultimo_snapshot = 0.0
        self._snapshot_cache: dict[str, Any] = {}

    def configurar(self, perfil: str | None = None) -> dict:
        with self._lock:
            if perfil is not None:
                self.perfil = normalizar_perfil(perfil)
            return dict(PERFILES[self.perfil])

    def iniciar_ejecucion(self, perfil: str | None = None) -> None:
        """Reinicia únicamente métricas efímeras al comenzar un lote nuevo."""
        with self._lock:
            if perfil is not None:
                self.perfil = normalizar_perfil(perfil)
            self._inicio = time.monotonic()
            self._completadas = 0
            self._oom = 0
            self._fallback_cpu = 0
            self._batch_actual = None
            self._workers_activos = 0
            self._cola_pendiente = 0
            self._cola_bytes = 0
            self._etapas.clear()
            self._inferencias.clear()
            self._ultimo_snapshot = 0.0
            self._snapshot_cache = {}

    @property
    def limites(self) -> dict:
        return dict(PERFILES[self.perfil])

    def registrar_etapa(self, nombre: str, segundos: float) -> None:
        if segundos < 0:
            return
        with self._lock:
            self._etapas[str(nombre)].append(float(segundos))
            if nombre in {"inferencia_gpu", "inferencia_cpu", "ocr"}:
                self._inferencias.append(float(segundos))

    def registrar_completada(self, cantidad: int = 1) -> None:
        with self._lock:
            self._completadas += max(0, int(cantidad))

    def registrar_oom(self) -> None:
        with self._lock:
            self._oom += 1

    def registrar_fallback_cpu(self) -> None:
        with self._lock:
            self._fallback_cpu += 1

    def actualizar_batch(self, batch: int) -> None:
        with self._lock:
            self._batch_actual = max(1, int(batch))

    def actualizar_cola(self, pendientes: int, bytes_estimados: int = 0, workers_activos: int | None = None) -> None:
        with self._lock:
            self._cola_pendiente = max(0, int(pendientes))
            self._cola_bytes = max(0, int(bytes_estimados))
            if workers_activos is not None:
                self._workers_activos = max(0, int(workers_activos))

    def _percentiles(self) -> dict:
        valores = sorted(self._inferencias)
        if not valores:
            return {"media_ms": None, "p50_ms": None, "p95_ms": None}
        def pct(p: float) -> float:
            idx = min(len(valores) - 1, max(0, round((len(valores) - 1) * p)))
            return valores[idx] * 1000
        return {
            "media_ms": round(sum(valores) / len(valores) * 1000, 1),
            "p50_ms": round(pct(.50), 1),
            "p95_ms": round(pct(.95), 1),
        }

    def _uso_sistema(self) -> dict:
        cpu = ram = ram_disponible = None
        try:
            import psutil  # opcional
            cpu = float(psutil.cpu_percent(interval=None))
            memoria = psutil.virtual_memory()
            ram = float(memoria.percent)
            ram_disponible = int(memoria.available)
        except Exception:
            pass

        gpu = vram = vram_usada = vram_total = vram_libre = None
        gpu_fuente = None
        try:
            import torch
            if torch.cuda.is_available():
                indice_gpu = int(torch.cuda.current_device())
                libre, total = torch.cuda.mem_get_info(indice_gpu)
                reservado = int(torch.cuda.memory_reserved(indice_gpu))
                usado = max(0, int(total - libre))
                vram = (usado / total * 100.0) if total else None
                vram_usada, vram_total, vram_libre = usado, int(total), int(libre)
                # PyTorch no expone utilización SM. Primero usamos NVML si ya está
                # instalado; en Windows hacemos fallback a nvidia-smi, incluido con
                # el driver NVIDIA, sin agregar una dependencia Python obligatoria.
                try:
                    import pynvml
                    pynvml.nvmlInit()
                    h = pynvml.nvmlDeviceGetHandleByIndex(indice_gpu)
                    gpu = float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
                    gpu_fuente = "nvml"
                except Exception:
                    ejecutable = shutil.which("nvidia-smi")
                    if ejecutable:
                        try:
                            salida = subprocess.check_output(
                                [ejecutable, "-i", str(indice_gpu),
                                 "--query-gpu=utilization.gpu",
                                 "--format=csv,noheader,nounits"],
                                text=True, stderr=subprocess.DEVNULL, timeout=1.0,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            ).strip().splitlines()
                            if salida:
                                gpu = float(salida[0].strip())
                                gpu_fuente = "nvidia-smi"
                        except Exception:
                            gpu = None
                # reservado se conserva para diagnóstico aunque no equivalga a usado.
                reserved_pct = reservado / total * 100.0 if total else None
            else:
                reserved_pct = None
        except Exception:
            reserved_pct = None
        return {
            "cpu_porcentaje": round(cpu, 1) if cpu is not None else None,
            "ram_porcentaje": round(ram, 1) if ram is not None else None,
            "ram_disponible_bytes": ram_disponible,
            "gpu_porcentaje": round(gpu, 1) if gpu is not None else None,
            "gpu_fuente": gpu_fuente,
            "vram_porcentaje": round(vram, 1) if vram is not None else None,
            "vram_usada_bytes": vram_usada,
            "vram_total_bytes": vram_total,
            "vram_libre_bytes": vram_libre,
            "vram_reservada_porcentaje": round(reserved_pct, 1) if reserved_pct is not None else None,
        }

    def snapshot(self, forzar: bool = False) -> dict:
        ahora = time.monotonic()
        with self._lock:
            if not forzar and self._snapshot_cache and ahora - self._ultimo_snapshot < .75:
                return dict(self._snapshot_cache)
            transcurrido = max(.001, ahora - self._inicio)
            etapas = {
                nombre: round(sum(vals) / len(vals), 4)
                for nombre, vals in self._etapas.items() if vals
            }
            base = {
                "perfil": self.perfil,
                "limites": self.limites,
                "imagenes_completadas": self._completadas,
                "imagenes_por_minuto": round(self._completadas / transcurrido * 60.0, 2),
                "batch_actual": self._batch_actual,
                "workers_activos": self._workers_activos,
                "cola_pendiente": self._cola_pendiente,
                "cola_mb": round(self._cola_bytes / (1024 ** 2), 1),
                "reintentos_cuda_oom": self._oom,
                "derivaciones_cpu": self._fallback_cpu,
                "tiempos_medios_seg": etapas,
                "inferencia": self._percentiles(),
            }
            base.update(self._uso_sistema())
            self._snapshot_cache = base
            self._ultimo_snapshot = ahora
            return dict(base)

    def ram_bajo_presion(self) -> bool:
        snap = self.snapshot()
        uso = snap.get("ram_porcentaje")
        return uso is not None and uso >= float(self.limites["ram_limite"])

    def cpu_bajo_presion(self) -> bool:
        snap = self.snapshot()
        uso = snap.get("cpu_porcentaje")
        limite_superior = float(self.limites["cpu_objetivo"][1])
        return uso is not None and uso >= limite_superior

    def vram_bajo_presion(self) -> bool:
        snap = self.snapshot()
        uso = snap.get("vram_porcentaje")
        return uso is not None and uso >= float(self.limites["vram_limite"])


_GESTOR = GestorRecursos(os.environ.get("OCR_PERFIL_RENDIMIENTO", "alto"))


def obtener_gestor_recursos(perfil: str | None = None) -> GestorRecursos:
    if perfil is not None:
        _GESTOR.configurar(perfil)
    return _GESTOR
