"""El instalador debe elegir un solo PyTorch óptimo y conservar CPU de respaldo."""

import instalar
from pathlib import Path


def test_apple_silicon_elige_mps_incluido_en_pypi(monkeypatch):
    monkeypatch.setattr(instalar.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(instalar.platform, "machine", lambda: "arm64")

    plan = instalar.detectar_plan_torch()

    assert plan.acelerador == "mps"
    assert plan.indices == (None,)


def test_nvidia_elige_indices_cuda_compatibles_en_orden(monkeypatch):
    monkeypatch.setattr(instalar.platform, "system", lambda: "Windows")
    monkeypatch.setattr(instalar.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(instalar.shutil, "which", lambda nombre: "nvidia-smi.exe")
    monkeypatch.setattr(instalar, "_salida", lambda comando: (
        "NVIDIA RTX 4070" if "--query-gpu=name" in comando
        else "CUDA Version: 12.8"))

    plan = instalar.detectar_plan_torch()

    assert plan.acelerador == "cuda"
    assert plan.indices[0].endswith("/cu128")
    assert all(not indice.endswith(("/cu129", "/cu130")) for indice in plan.indices)


def test_sin_acelerador_elige_rueda_cpu(monkeypatch):
    monkeypatch.setattr(instalar.platform, "system", lambda: "Linux")
    monkeypatch.setattr(instalar.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(instalar.shutil, "which", lambda nombre: None)

    plan = instalar.detectar_plan_torch()

    assert plan.acelerador == "cpu"
    assert plan.indices == ("https://download.pytorch.org/whl/cpu",)


def test_inicio_windows_usa_bypass_entorno_y_espera_api():
    raiz = Path(instalar.__file__).resolve().parent
    bat = (raiz / "Iniciar_OCR.bat").read_text(encoding="utf-8")
    ps1 = (raiz / "iniciar_ocr.ps1").read_text(encoding="utf-8")
    assert "-ExecutionPolicy Bypass" in bat
    assert "Set-ExecutionPolicy -Scope Process" in ps1
    assert ".venv_ocr" in ps1 and "instalar.py" in ps1
    assert "/api/estado" in ps1 and "SinAbrir" in ps1 and "Diagnostico" in ps1
