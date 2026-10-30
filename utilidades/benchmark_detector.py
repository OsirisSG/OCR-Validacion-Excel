"""V15.9.1 (A8) · Benchmark del detector de apertura (V15.8.1 vs V15.9).

Mide el coste real del detector por video: fps de procesamiento, latencia
media y percentil 95 de la correlación de fase (``cv2.phaseCorrelate``),
CPU/RAM del proceso y exactitud frente al evento conocido del clip.

La auditoría señaló que el coste de ``phaseCorrelate`` por cuadro no estaba
medido. Este harness registra las métricas exigidas; para comparar versiones
se ejecuta el MISMO comando sobre V15.8.1 y V15.9 en el mismo hardware y se
contrastan los JSON de salida.

Uso:
    python utilidades/benchmark_detector.py video.avi [--repeticiones 3]
        [--salida informe.json] [--config config.yaml]
    python utilidades/benchmark_detector.py --sintetico [--frames 60]
        [--ancho 1280 --alto 720] ...

No necesita internet ni dependencias nuevas (sólo el entorno de producción).
"""
from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def _percentil(datos: list[float], q: float) -> float:
    if not datos:
        return 0.0
    orden = sorted(datos)
    return orden[max(0, min(len(orden) - 1, int(round(q * (len(orden) - 1)))))]


def _uso_recursos() -> dict:
    uso = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "cpu_usuario_s": round(uso.ru_utime, 3),
        "cpu_sistema_s": round(uso.ru_stime, 3),
        # ru_maxrss: KiB en Linux, bytes en macOS.
        "ram_max_mb": round(uso.ru_maxrss / (1024 if sys.platform != "darwin" else 1024 * 1024), 1),
    }


def medir_analisis(ruta_video: Path, config: dict | None, repeticiones: int) -> dict:
    from video_airbag import analizar_video
    duraciones = []
    ultimo = None
    for _ in range(max(1, repeticiones)):
        inicio = time.perf_counter()
        ultimo = analizar_video(str(ruta_video), config, usar_cache=False)
        duraciones.append(time.perf_counter() - inicio)
    frames = int(ultimo.get("frames_leidos") or 0)
    rend = ultimo.get("rendimiento_detector") or {}
    return {
        "video": str(ruta_video),
        "frames_leidos": frames,
        "repeticiones": len(duraciones),
        "tiempo_s": {
            "min": round(min(duraciones), 3),
            "media": round(statistics.mean(duraciones), 3),
            "p95": round(_percentil(duraciones, 0.95), 3),
            "max": round(max(duraciones), 3),
        },
        "fps_procesamiento": round(frames / min(duraciones), 2) if frames and min(duraciones) > 0 else None,
        "fase_correlate": {
            "ms_total": rend.get("fase_correlate_ms_total"),
            "ms_media_por_cuadro": rend.get("fase_correlate_ms_media"),
            "ms_p95_por_cuadro": rend.get("fase_correlate_ms_p95"),
            "pct_del_tiempo_total": (round(100.0 * rend["fase_correlate_ms_total"] / 1000.0
                                          / min(duraciones), 1)
                                     if rend.get("fase_correlate_ms_total") and min(duraciones) > 0
                                     else None),
        },
        "evento": {
            "estado": ultimo.get("estado_evento") or ultimo.get("estado"),
            "frame_evento": ultimo.get("frame_evento"),
            "tiempo_ms": ultimo.get("tiempo_ms"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark del detector de apertura V-Matrix.")
    parser.add_argument("video", nargs="?", help="Ruta del AVI real a medir.")
    parser.add_argument("--sintetico", action="store_true",
                        help="Genera un clip sintético de airbag y lo mide.")
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--ancho", type=int, default=1280)
    parser.add_argument("--alto", type=int, default=720)
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument("--config", default=None, help="config.yaml alternativo.")
    parser.add_argument("--salida", default=None, help="Escribe el informe JSON aquí.")
    args = parser.parse_args()

    from configuracion import cargar_config
    config = cargar_config(Path(args.config)) if args.config else cargar_config()

    if args.sintetico:
        sys.path.insert(0, str(RAIZ / "pruebas"))
        from sintetico_airbag import generar_video
        destino = RAIZ / "errores" / "benchmark_sintetico.avi"
        destino.parent.mkdir(parents=True, exist_ok=True)
        info = generar_video(destino, total=args.frames, ancho=args.ancho, alto=args.alto)
        ruta = Path(destino)
        print(f"Clip sintético generado: {ruta} (evento en frame {info.get('frame_bolsa')})")
    elif args.video:
        ruta = Path(args.video)
        if not ruta.is_file():
            parser.error(f"No existe el video: {ruta}")
    else:
        parser.error("Indica un video o usa --sintetico.")

    t0 = time.perf_counter()
    resultado = medir_analisis(ruta, config, args.repeticiones)
    informe = {
        "benchmark": "detector_apertura_v_matrix",
        "version_objetivo": (RAIZ / "VERSION.txt").read_text(encoding="utf-8").strip()
        if (RAIZ / "VERSION.txt").is_file() else None,
        "generado_en": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "equipo": {
            "python": platform.python_version(),
            "plataforma": platform.platform(),
            "cpu": platform.processor() or platform.machine(),
        },
        "recursos_despues": _uso_recursos(),
        "duracion_total_s": round(time.perf_counter() - t0, 2),
        "resultado": resultado,
        "nota": ("Comparar contra el mismo informe generado sobre V15.8.1 en este "
                 "mismo equipo. La exactitud ±1 cuadro y el acuerdo con revisión "
                 "humana requieren clips reales anotados (Evaluation Lab)."),
    }
    print(json.dumps(informe, ensure_ascii=False, indent=2))
    if args.salida:
        destino_json = Path(args.salida)
        destino_json.parent.mkdir(parents=True, exist_ok=True)
        destino_json.write_text(json.dumps(informe, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        print(f"\nInforme guardado en {destino_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
