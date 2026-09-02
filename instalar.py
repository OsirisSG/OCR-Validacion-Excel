"""Instalador multiplataforma con selección automática de PyTorch.

Instala una sola distribución de PyTorch: CUDA cuando hay NVIDIA compatible,
Metal/MPS en Apple Silicon y CPU como respaldo. Las distribuciones aceleradas
también pueden ejecutar operaciones en CPU; no deben coexistir dos ruedas de
``torch`` distintas dentro del mismo entorno.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import venv
from dataclasses import asdict, dataclass
from pathlib import Path


RAIZ = Path(__file__).resolve().parent
GRUPOS_COMPLETOS = (
    "requirements.txt",
    "requirements-formats.txt",
    "requirements-quality.txt",
    "requirements-training.txt",
    "requirements-production.txt",
)
INDICES_CUDA = (
    (13, 0, "cu130"),
    (12, 9, "cu129"),
    (12, 8, "cu128"),
    (12, 6, "cu126"),
    (12, 4, "cu124"),
    (12, 1, "cu121"),
    (11, 8, "cu118"),
)


@dataclass(frozen=True)
class PlanTorch:
    acelerador: str
    indices: tuple[str | None, ...]
    motivo: str
    gpu: str | None = None
    cuda_controlador: str | None = None


def _salida(comando: list[str]) -> str:
    try:
        proceso = subprocess.run(
            comando, check=False, capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (proceso.stdout or "") + "\n" + (proceso.stderr or "")


def detectar_plan_torch() -> PlanTorch:
    """Elige el tipo de rueda; la disponibilidad real se verifica al final."""
    sistema = platform.system()
    maquina = platform.machine().lower()
    if sistema == "Darwin" and maquina in {"arm64", "aarch64"}:
        return PlanTorch(
            "mps", (None,),
            "Apple Silicon detectado: PyTorch para macOS incluye Metal/MPS y CPU.",
            gpu="Apple Silicon")

    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        texto = _salida([nvidia_smi])
        version = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", texto)
        nombre = _salida([
            nvidia_smi, "--query-gpu=name", "--format=csv,noheader"]
        ).strip().splitlines()
        if version:
            maxima = (int(version.group(1)), int(version.group(2)))
            compatibles = tuple(
                f"https://download.pytorch.org/whl/{etiqueta}"
                for mayor, menor, etiqueta in INDICES_CUDA
                if (mayor, menor) <= maxima)
            if compatibles:
                return PlanTorch(
                    "cuda", compatibles,
                    "GPU NVIDIA y controlador CUDA detectados; se probará la rueda "
                    "oficial más nueva compatible.",
                    gpu=nombre[0].strip() if nombre else "NVIDIA",
                    cuda_controlador=f"{maxima[0]}.{maxima[1]}")
    return PlanTorch(
        "cpu", ("https://download.pytorch.org/whl/cpu",),
        "No se detectó un acelerador compatible; se instalará PyTorch para CPU.")


def _python_entorno(ruta: Path) -> Path:
    return ruta / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def preparar_python(entorno: Path | None, simulacion: bool) -> Path:
    if entorno is None and sys.prefix != sys.base_prefix:
        return Path(sys.executable).resolve()
    destino = (entorno or (RAIZ / ".venv_ocr")).resolve()
    interprete = _python_entorno(destino)
    if not interprete.is_file():
        print(f"Preparando entorno aislado: {destino}")
        if not simulacion:
            venv.EnvBuilder(with_pip=True, clear=False).create(destino)
    return interprete


def ejecutar(comando: list[str], simulacion: bool = False,
             permitir_error: bool = False) -> bool:
    print("  $ " + " ".join(f'\"{parte}\"' if " " in parte else parte
                             for parte in comando))
    if simulacion:
        return True
    resultado = subprocess.run(comando, check=False)
    if resultado.returncode and not permitir_error:
        raise RuntimeError(
            f"El comando terminó con código {resultado.returncode}: {comando[0]}")
    return resultado.returncode == 0


def instalar_torch(python: Path, plan: PlanTorch, simulacion: bool,
                    reinstalar: bool = False) -> PlanTorch:
    base = [str(python), "-m", "pip", "install", "--upgrade"]
    if reinstalar:
        base.append("--force-reinstall")
    paquetes = ["torch", "torchvision"]
    for indice in plan.indices:
        comando = [*base, *paquetes]
        if indice:
            comando.extend(["--index-url", indice])
        if ejecutar(comando, simulacion, permitir_error=True):
            return plan
        print(f"ADVERTENCIA: PyTorch no estuvo disponible desde {indice or 'PyPI'}.")
    if plan.acelerador != "cpu":
        print("Se usará el respaldo CPU para conservar una instalación funcional.")
        cpu = PlanTorch(
            "cpu", ("https://download.pytorch.org/whl/cpu",),
            "La instalación acelerada falló; se activó el respaldo oficial para CPU.")
        comando = [*base, *paquetes, "--index-url", cpu.indices[0]]
        ejecutar(comando, simulacion)
        return cpu
    raise RuntimeError("No fue posible instalar PyTorch para CPU.")


def verificar(python: Path, simulacion: bool) -> dict:
    codigo = """
import json, torch
x = torch.ones(2, device='cpu')
mps = bool(getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available())
cuda = bool(torch.cuda.is_available())
dispositivo = 'cuda' if cuda else 'mps' if mps else 'cpu'
if dispositivo != 'cpu':
    y = torch.ones(1, device=dispositivo)
print(json.dumps({'torch': torch.__version__, 'cpu_ok': bool(x.sum().item() == 2),
                  'cuda': cuda, 'mps': mps, 'seleccionado': dispositivo}))
"""
    if simulacion:
        return {"simulacion": True}
    proceso = subprocess.run(
        [str(python), "-c", codigo], check=True, capture_output=True, text=True)
    return json.loads(proceso.stdout.strip().splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Instala el proyecto OCR y selecciona PyTorch para este equipo.")
    parser.add_argument("--perfil", choices=("base", "completo"), default="completo")
    parser.add_argument("--entorno", type=Path, default=None,
                        help="Ruta del entorno virtual; por defecto .venv_ocr.")
    parser.add_argument("--incluir-desarrollo", action="store_true")
    parser.add_argument("--reinstalar-torch", action="store_true")
    parser.add_argument("--simular", action="store_true",
                        help="Muestra el plan sin modificar el equipo.")
    parser.add_argument("--solo-diagnostico", action="store_true")
    args = parser.parse_args()

    print(f"Sistema: {platform.system()} {platform.machine()}")
    print(f"Python de arranque: {platform.python_version()}")
    if sys.version_info < (3, 10):
        print("ERROR: se requiere Python 3.10 o posterior; se recomienda 3.12.")
        return 2
    plan = detectar_plan_torch()
    print("Plan PyTorch: " + json.dumps(asdict(plan), ensure_ascii=False))
    if args.solo_diagnostico:
        return 0

    python = preparar_python(args.entorno, args.simular)
    print(f"Python de destino: {python}")
    if not args.simular and not python.is_file():
        print("ERROR: no se pudo crear el intérprete del entorno virtual.")
        return 2
    try:
        ejecutar([str(python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
                 args.simular)
        instalado = instalar_torch(
            python, plan, args.simular, args.reinstalar_torch)
        grupos = ("requirements.txt",) if args.perfil == "base" else GRUPOS_COMPLETOS
        if args.incluir_desarrollo:
            grupos = (*grupos, "requirements-dev.txt")
        for nombre in grupos:
            ejecutar([str(python), "-m", "pip", "install", "-r", str(RAIZ / nombre)],
                     args.simular)
        resultado = verificar(python, args.simular)
    except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR DE INSTALACIÓN: {exc}")
        return 1

    print("Instalación verificada: " + json.dumps(resultado, ensure_ascii=False))
    if not args.simular and resultado.get("seleccionado") != instalado.acelerador:
        print(
            "ADVERTENCIA: se instaló el paquete previsto, pero el acelerador no quedó "
            "disponible. El programa usará CPU de forma segura.")
    print(f"Para iniciar: {python} {RAIZ / 'iniciar.py'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
