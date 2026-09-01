"""Detección conservadora de CPU/GPU para inferencia OCR local."""

from __future__ import annotations

import os
import platform
from functools import lru_cache

# En Apple Silicon, operaciones aún no implementadas en MPS regresan a CPU en
# vez de abortar todo el lote. Debe definirse antes de importar torch.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


@lru_cache(maxsize=8)
def detectar_recursos(dispositivo_solicitado: str = "auto") -> dict:
    solicitado = str(dispositivo_solicitado or "auto").lower()
    if solicitado not in {"auto", "cpu", "cuda", "mps"}:
        solicitado = "auto"
    info = {
        "solicitado": solicitado,
        "seleccionado": "cpu",
        "acelerador_disponible": False,
        "cuda_disponible": False,
        "mps_disponible": False,
        "cpu_hilos": max(1, int(os.cpu_count() or 1)),
        "plataforma": platform.system(),
        "motivo": "CPU disponible",
        "warning": None,
    }
    try:
        import torch
        info["torch"] = torch.__version__
        info["cuda_disponible"] = bool(torch.cuda.is_available())
        mps = getattr(torch.backends, "mps", None)
        info["mps_disponible"] = bool(mps and mps.is_available())
        disponibles = [d for d in ("cuda", "mps") if info[f"{d}_disponible"]]
        elegido = (disponibles[0] if solicitado == "auto" and disponibles else
                   solicitado if solicitado in disponibles else "cpu")
        if solicitado in {"cuda", "mps"} and elegido == "cpu":
            info["warning"] = (
                f"Se solicitó {solicitado.upper()}, pero PyTorch no puede usarlo; se usará CPU.")
        if elegido != "cpu":
            tensor = torch.ones(1, device=elegido)
            del tensor
            if elegido == "cuda":
                torch.cuda.synchronize()
                info["nombre_acelerador"] = torch.cuda.get_device_name(0)
            else:
                torch.mps.synchronize()
                info["nombre_acelerador"] = "Apple Metal (MPS)"
            info["seleccionado"] = elegido
            info["acelerador_disponible"] = True
            info["motivo"] = "OCR neuronal en GPU; preprocesamiento y QR en CPU"
    except Exception as exc:
        info["seleccionado"] = "cpu"
        info["acelerador_disponible"] = False
        info["warning"] = f"La prueba del acelerador falló ({type(exc).__name__}: {exc}); se usará CPU."
        info["motivo"] = "Fallback seguro a CPU"
    return info


def configurar_cpu(hilos: int | None = None) -> int:
    """Reserva un hilo para UI/SO y configura OpenCV sin afectar la precisión."""
    disponibles = max(1, int(os.cpu_count() or 1))
    elegidos = int(hilos) if hilos else max(1, disponibles - 1)
    elegidos = max(1, min(elegidos, disponibles))
    try:
        import cv2
        cv2.setNumThreads(elegidos)
    except Exception:
        pass
    return elegidos
