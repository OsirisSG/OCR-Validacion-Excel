"""Doctor OCR local (P08): por qué mi equipo no lee como la sandbox.

Uso, en Windows:

    python doctor_ocr.py
    python doctor_ocr.py --canario "datos_prueba\\232561 RDW NOM HT" --esperado test_number=232561
    python doctor_ocr.py --json

Qué hace
--------
1. **Entorno**: versión de Python, si EasyOCR y PyTorch están instalados, qué dispositivo
   se va a usar (CUDA/MPS/CPU), si los pesos del modelo están descargados y cuánta memoria
   hay. Sin esto, cualquier comparación con la sandbox es a ciegas.
2. **Parámetros efectivos**: idioma, cuantización, tamaño de lote y escalas de ROI. Aquí se
   ve si el equipo está cuantizando el modelo (más rápido, menos preciso) o no.
3. **Canario** (opcional): lee las fotos de un caso real y compara lo leído con lo que el
   usuario sabe que dice la etiqueta. Ésa es la única medida honesta de «leo igual que en
   la sandbox»: los aciertos sobre valores conocidos, no la sensación de velocidad.

Códigos de salida: 0 = todo listo, 2 = falta algo para poder medir (EasyOCR, modelo o
canario), 3 = el canario no alcanza lo esperado.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


# --------------------------------------------------------------------------- entorno
def _version(modulo: str):
    try:
        import importlib.metadata as md
        return md.version(modulo)
    except Exception:
        return None


def huella_entorno() -> dict:
    """Lo que hay instalado y con qué dispositivo se leerá. Sin efectos secundarios."""
    datos = {
        "python": platform.python_version(),
        "sistema": f"{platform.system()} {platform.release()}",
        "arquitectura": platform.machine(),
        "easyocr": _version("easyocr"),
        "torch": _version("torch"),
        "opencv": _version("opencv-python-headless") or _version("opencv-python"),
        "numpy": _version("numpy"),
        "dispositivo": "cpu",
        "cuda_disponible": False,
        "mps_disponible": False,
        "ruta_modelos": str(Path.home() / ".EasyOCR" / "model"),
        "modelos_descargados": [],
        "memoria_gb": None,
    }
    try:
        import torch
        datos["cuda_disponible"] = bool(torch.cuda.is_available())
        datos["mps_disponible"] = bool(getattr(torch.backends, "mps", None)
                                        and torch.backends.mps.is_available())
        if datos["cuda_disponible"]:
            datos["dispositivo"] = "cuda"
        elif datos["mps_disponible"]:
            datos["dispositivo"] = "mps"
    except Exception:
        pass
    modelos = Path(datos["ruta_modelos"])
    if modelos.is_dir():
        datos["modelos_descargados"] = sorted(p.name for p in modelos.glob("*.pth"))
    try:
        if platform.system() == "Windows":
            import ctypes

            class Memoria(ctypes.Structure):
                _fields_ = [("total", ctypes.c_ulonglong), ("libre", ctypes.c_ulonglong),
                            ("total_pagina", ctypes.c_ulonglong), ("libre_pagina", ctypes.c_ulonglong),
                            ("memoria_virtual", ctypes.c_ulonglong)]

            estado = Memoria()
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado))
            datos["memoria_gb"] = round(estado.total / 1024 ** 3, 1)
        else:
            datos["memoria_gb"] = round(
                (Path("/proc/meminfo").read_text().split()[1] if Path("/proc/meminfo").is_file() else 0)
                / 1024 ** 2, 1) or None
    except Exception:
        pass
    return datos


def parametros_efectivos(config: dict) -> dict:
    """Los parámetros de lectura que ESTE equipo va a usar, no los de la documentación."""
    fase1 = (config or {}).get("fase1") or {}
    rendimiento = fase1.get("rendimiento") or {}
    ocr = (config or {}).get("ocr") or {}
    return {
        "idioma": fase1.get("lang"),
        "cuantizar_cpu": bool(fase1.get("cuantizar_cpu", False)),
        "modelo_visual": fase1.get("_modelo_visual_activo"),
        "hilos_cpu": rendimiento.get("hilos_cpu") or "automático",
        "batch_cpu": rendimiento.get("batch_cpu"),
        "batch_gpu": rendimiento.get("batch_gpu"),
        "lado_maximo_deteccion": ocr.get("lado_maximo_deteccion"),
        "zoom_minimo": ocr.get("zoom_minimo"), "zoom_maximo": ocr.get("zoom_maximo"),
        "min_size": 10, "text_threshold": 0.55, "low_text": 0.30, "link_threshold": 0.35,
        "roi": ocr.get("roi_manual"),
    }


def avisos(entorno: dict, parametros: dict) -> list[str]:
    """Diferencias que explicarían una lectura peor que la de la sandbox."""
    lista: list[str] = []
    if not entorno.get("easyocr"):
        lista.append("EasyOCR no está instalado: no se puede leer nada. "
                     "Instálalo con: pip install easyocr")
    if entorno.get("easyocr") and not entorno.get("modelos_descargados"):
        lista.append(f"No hay pesos en {entorno.get('ruta_modelos')}: la primera lectura los "
                     "descargará. Sin red, el pipeline no puede leer.")
    if parametros.get("cuantizar_cpu"):
        lista.append("La cuantización en CPU está ACTIVADA: es más rápida y menos precisa. "
                     "Para el vaciado de datos, pon `fase1.cuantizar_cpu: false` en config.yaml.")
    if entorno.get("dispositivo") == "cpu":
        lista.append("Se leerá en CPU. No es un error, pero es más lento; el resultado puede "
                     "diferir del de una GPU si la imagen se reescala por memoria.")
    if entorno.get("memoria_gb") and entorno["memoria_gb"] < 8:
        lista.append(f"Memoria baja ({entorno['memoria_gb']} GB): conviene limitar las ROI "
                     "y no leer la foto completa (riesgo de quedarse sin memoria).")
    if not parametros.get("roi"):
        lista.append("No hay ROI configuradas: cada foto se leerá completa, que es más lento y, "
                     "si la imagen se reescala por memoria, menos preciso.")
    if str(parametros.get("idioma") or "").strip().lower() in {"en", "en-us", "en-gb"}:
        lista.append("El motor está configurado sólo en inglés, y las etiquetas del libro traen "
                     "palabras en alemán (Stand/Eng. Level, Prüfnummer). Los números se leen "
                     "igual, pero las palabras clave pueden fallar: valora `fase1.lang: en,de`.")
    if not parametros.get("lado_maximo_deteccion"):
        lista.append("No hay `ocr.lado_maximo_deteccion`: una foto grande puede reescalarse "
                     "internamente y perder los caracteres pequeños de la etiqueta.")
    return lista


# --------------------------------------------------------------------------- canario
def leer_canario(ruta_caso: Path, config: dict, maximo: int = 6) -> list[dict]:
    """Lee las primeras imágenes del caso con el motor real y devuelve el texto de cada una."""
    from ocr_engine import extraer_texto_empresarial

    fotos = sorted([p for p in Path(ruta_caso).rglob("*")
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}])[:maximo]
    lecturas = []
    for foto in fotos:
        try:
            salida = extraer_texto_empresarial(str(foto), config)
        except Exception as exc:  # una foto ilegible no debe tumbar el diagnóstico
            lecturas.append({"imagen": foto.name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        lecturas.append({
            "imagen": foto.name,
            "texto": " | ".join(str(salida.get("texto_completo") or "").split()),
            "confianza": salida.get("confianza_media"),
            "estado": salida.get("estado_imagen"),
        })
    return lecturas


def evaluar_canario(lecturas: list[dict], esperados: dict[str, str]) -> dict:
    """Compara lo leído con lo que el usuario dice que dice la etiqueta.

    El cotejo es por presencia del valor esperado dentro del texto leído de cada imagen.
    Se informa por campo: en cuántas imágenes aparece y en cuántas aparece una variante
    MALFORMADA (p. ej. `GJ.880.204.J` cuando se espera `2GJ.880.204.J`), que es justo el
    error que P08 quiere dejar de publicar.
    """
    from utilidades.validacion_formas import PATRONES, normalizar
    import re

    detalle = {}
    for clave, esperado in esperados.items():
        esperado_norm = normalizar(esperado)
        encontrado = sum(1 for l in lecturas if esperado_norm in normalizar(l.get("texto")))
        malformado = 0
        patron = PATRONES.get(clave)
        if patron:
            from difflib import SequenceMatcher

            expresion = re.compile(patron[0])
            for lectura in lecturas:
                for trozo in re.split(r"[|\n\s]+", normalizar(lectura.get("texto"))):
                    if not trozo or expresion.fullmatch(trozo):
                        continue
                    # «Parecido pero malformado»: se parece lo suficiente al esperado como
                    # para que un humano lo confunda, y aun así no cumple la forma.
                    if SequenceMatcher(None, trozo, esperado_norm).ratio() >= 0.8:
                        malformado += 1
                        break
        detalle[clave] = {"esperado": esperado, "imagenes_con_valor": encontrado,
                          "imagenes_con_variante_malformada": malformado,
                          "acierto": encontrado > 0}
    aciertos = sum(1 for d in detalle.values() if d["acierto"])
    return {"campos": detalle, "aciertos": aciertos, "total": len(detalle),
            "porcentaje": round(100 * aciertos / len(detalle), 1) if detalle else 0.0}


def _parsear_esperados(pares: list[str]) -> dict[str, str]:
    esperados = {}
    for par in pares or []:
        if "=" not in par:
            raise SystemExit(f"--esperado espera campo=valor, no «{par}»")
        clave, valor = par.split("=", 1)
        esperados[clave.strip()] = valor.strip()
    return esperados


def main(argv: list[str] | None = None) -> int:
    import yaml

    parser = argparse.ArgumentParser(description="Diagnóstico de lectura OCR local (P08)")
    parser.add_argument("--config", default=str(RAIZ / "config.yaml"))
    parser.add_argument("--canario", help="carpeta de un caso real con fotos")
    parser.add_argument("--esperado", action="append", default=[],
                        help="campo=valor que el usuario sabe que dice la etiqueta")
    parser.add_argument("--maximo", type=int, default=6, help="fotos a leer en el canario")
    parser.add_argument("--json", action="store_true", help="salida legible por máquina")
    args = parser.parse_args(argv)

    config = {}
    ruta_config = Path(args.config)
    if ruta_config.is_file():
        config = yaml.safe_load(ruta_config.read_text(encoding="utf-8")) or {}
    entorno = huella_entorno()
    parametros = parametros_efectivos(config)
    informe = {"entorno": entorno, "parametros": parametros,
               "avisos": avisos(entorno, parametros), "canario": None}

    codigo = 0 if entorno.get("easyocr") else 2
    esperados = _parsear_esperados(args.esperado)
    if args.canario:
        if not entorno.get("easyocr"):
            informe["canario"] = {"error": "sin EasyOCR no se puede leer"}
        elif not Path(args.canario).is_dir():
            informe["canario"] = {"error": f"no existe la carpeta {args.canario}"}
            codigo = 2
        else:
            lecturas = leer_canario(Path(args.canario), config, args.maximo)
            informe["canario"] = {"lecturas": lecturas,
                                  "cotejo": evaluar_canario(lecturas, esperados) if esperados else None}
            if esperados:
                cotejo = informe["canario"]["cotejo"]
                if cotejo["aciertos"] < cotejo["total"]:
                    codigo = 3

    if args.json:
        print(json.dumps(informe, ensure_ascii=False, indent=2, default=str))
        return codigo

    print("=" * 72)
    print(" DOCTOR OCR LOCAL · V-MATRIX V16.0.21")
    print("=" * 72)
    print(f" Python {entorno['python']} · {entorno['sistema']} · {entorno['arquitectura']}")
    print(f" EasyOCR {entorno['easyocr'] or 'NO INSTALADO'} · PyTorch {entorno['torch'] or 'NO INSTALADO'}")
    print(f" Dispositivo de lectura: {entorno['dispositivo'].upper()}"
          f" (CUDA {'sí' if entorno['cuda_disponible'] else 'no'},"
          f" MPS {'sí' if entorno['mps_disponible'] else 'no'})")
    print(f" Pesos del modelo: {entorno['ruta_modelos']} → "
          f"{len(entorno['modelos_descargados'])} archivo(s)")
    if entorno["memoria_gb"]:
        print(f" Memoria: {entorno['memoria_gb']} GB")
    print("-" * 72)
    print(" Parámetros efectivos de lectura")
    for clave, valor in parametros.items():
        print(f"   {clave:<18} {valor}")
    print("-" * 72)
    if informe["avisos"]:
        print(" AVISOS")
        for aviso in informe["avisos"]:
            print(f"   · {aviso}")
    else:
        print(" AVISOS: ninguno. La configuración es la de mayor precisión.")
    if informe["canario"]:
        print("-" * 72)
        canario = informe["canario"]
        if "error" in canario:
            print(f" CANARIO: {canario['error']}")
        else:
            print(f" CANARIO · {len(canario['lecturas'])} imagen(es) leída(s)")
            for lectura in canario["lecturas"]:
                if "error" in lectura:
                    print(f"   {lectura['imagen']}: {lectura['error']}")
                else:
                    confianza = lectura.get("confianza")
                    texto = lectura["texto"][:110]
                    print(f"   {lectura['imagen']}: {texto}"
                          + (f"  [{confianza:.2f}]" if isinstance(confianza, (int, float)) else ""))
            cotejo = canario.get("cotejo")
            if cotejo:
                print("-" * 72)
                print(f" COTEJO: {cotejo['aciertos']}/{cotejo['total']}"
                      f" campos encontrados ({cotejo['porcentaje']} %)")
                for clave, dato in cotejo["campos"].items():
                    marca = "OK " if dato["acierto"] else "NO "
                    print(f"   {marca}{clave:<26} esperado {dato['esperado']:<20}"
                          f" en {dato['imagenes_con_valor']} imagen(es)"
                          + (f" · variante malformada en {dato['imagenes_con_variante_malformada']}"
                             if dato["imagenes_con_variante_malformada"] else ""))
    print("=" * 72)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
