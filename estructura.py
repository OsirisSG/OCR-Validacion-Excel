"""
estructura.py — Fase 0: auto-descubrimiento de la estructura de carpetas.

Propósito
---------
Recorre recursivamente una raíz de lotes fotográficos (jerarquía de profundidad
variable y no uniforme), descubre el patrón dominante de nombres de carpeta y
clasifica cada carpeta como conforme o anómala. El resultado se serializa en
`estructura_detectada.json` para que las Fases 2 y 3 no vuelvan a recorrer disco.

API principal
-------------
mapear_estructura(ruta_raiz) -> dict   # retorna datos, no imprime
guardar_estructura(estructura, ruta)   # serializa a JSON (UTF-8, sin escapes)
carpetas_hoja(estructura) -> list      # carpetas que la Fase 2 debe procesar

Heurística de patrones (decisión de diseño documentada en docs/fase0_autodescubrimiento.md)
------------------------------------------------------------------------------------------
1. Cada nombre de carpeta se separa en tokens por `_`, `-` o espacios, conservando
   los separadores literales.
2. Cada token se generaliza a un fragmento de regex:
   - solo dígitos            -> \\d{k}      (conserva el ancho, p.ej. 01 -> \\d{2})
   - MAYÚSCULAS con dígitos  -> [A-Z0-9]+   (la "nomenclatura" del lote)
   - palabra + dígitos       -> palabra\\d+ (p.ej. variante2 -> variante\\d+)
   - palabra pura            -> literal     (p.ej. notas, sueltas)
   - cualquier otra cosa     -> re.escape(token)
3. El patrón dominante es el regex generalizado compartido por más carpetas,
   siempre que alcance `fase0.min_carpetas_para_patron` (default 2, configurable).
4. Una carpeta es CONFORME si su nombre cumple `re.fullmatch` contra el patrón
   dominante; cualquier otra es ANÓMALA (con motivo explícito).

El ejemplo de referencia del Documento Maestro se reproduce exactamente:
"01_A1_variante2" y "02_A1_variante3" -> \\d{2}_[A-Z0-9]+_variante\\d+ (dominante);
"notas_sueltas" -> patrón propio con 1 sola ocurrencia -> anómala.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from configuracion import RAIZ_PROYECTO, cargar_config

_RE_SOLO_DIGITOS = re.compile(r"^\d+$")
_RE_MAYUS_DIGITOS = re.compile(r"^[A-Z0-9]+$")
_RE_PALABRA_DIGITO = re.compile(r"^([A-Za-z]+)(\d+)$")


def _generalizar_patron(nombre: str) -> str:
    """Convierte un nombre de carpeta en su regex generalizada (ver docstring del módulo)."""
    partes = re.split(r"([_\-\s]+)", nombre)
    fragmentos = []
    for parte in partes:
        if not parte:
            continue
        if re.fullmatch(r"[_\-\s]+", parte):
            fragmentos.append(re.escape(parte[0]))  # separador literal normalizado a 1 carácter
        elif _RE_SOLO_DIGITOS.match(parte):
            fragmentos.append(rf"\d{{{len(parte)}}}")
        elif _RE_MAYUS_DIGITOS.match(parte) and any(c.isalpha() for c in parte):
            fragmentos.append(r"[A-Z0-9]+")
        elif (m := _RE_PALABRA_DIGITO.match(parte)):
            fragmentos.append(rf"{m.group(1)}\d+")
        else:
            fragmentos.append(re.escape(parte))
    return "".join(fragmentos)


def _categorizar(nombre_archivo: str, ext_imagen: set, ext_video: set) -> str:
    ext = Path(nombre_archivo).suffix.lower()
    if ext in ext_imagen:
        return "imagenes"
    if ext in ext_video:
        return "videos"
    return "otros"


def mapear_estructura(ruta_raiz: str | Path, config: dict | None = None) -> dict:
    """
    Recorre recursivamente `ruta_raiz` y retorna el mapa de estructura.

    Retorna un dict (no imprime nada) con:
      raiz, generado_en, total_carpetas, patron_dominante, estadisticas_patrones,
      carpetas[...], anomalias[...].
    Cada carpeta incluye: ruta, nombre, profundidad, es_hoja, conforme,
    patron_generalizado, motivo_anomalia, sigue_patron_prefijo_numerico,
    archivos por categoría y conteos.
    """
    config = config or cargar_config()
    f0 = config.get("fase0", {})
    ext_imagen = {e.lower() for e in f0.get("extensiones_imagen", [])}
    ext_video = {e.lower() for e in f0.get("extensiones_video", [])}
    min_patron = int(f0.get("min_carpetas_para_patron", 2))

    ruta_raiz = Path(ruta_raiz).resolve()
    if not ruta_raiz.is_dir():
        raise FileNotFoundError(f"La ruta raíz no existe o no es directorio: {ruta_raiz}")

    carpetas: list[dict] = []
    for dirpath, dirnames, filenames in os_walk_ordenado(ruta_raiz):
        rel = Path(dirpath).relative_to(ruta_raiz)
        profundidad = len(rel.parts)  # raíz = 0, sus hijas = 1, ...
        archivos = {"imagenes": [], "videos": [], "otros": []}
        for nombre in sorted(filenames):
            archivos[_categorizar(nombre, ext_imagen, ext_video)].append(nombre)

        carpetas.append({
            "ruta": str(dirpath),
            "ruta_relativa": rel.as_posix(),
            "nombre": Path(dirpath).name,
            "profundidad": profundidad,
            "es_raiz": profundidad == 0,
            # Patrón "prefijo numérico + nomenclatura" pedido por el Documento Maestro.
            "sigue_patron_prefijo_numerico": bool(re.match(r"^\d+", Path(dirpath).name)),
            "patron_generalizado": _generalizar_patron(Path(dirpath).name),
            "conforme": None,  # se resuelve tras conocer el patrón dominante
            "motivo_anomalia": None,
            "es_hoja": None,  # se resuelve tras el recorrido completo
            "archivos": archivos,
            "conteos": {k: len(v) for k, v in archivos.items()},
        })

    # --- Patrón dominante: regex generalizado más frecuente entre SUBcarpetas --
    estadisticas: dict[str, int] = {}
    for c in carpetas:
        if not c["es_raiz"]:
            estadisticas[c["patron_generalizado"]] = estadisticas.get(c["patron_generalizado"], 0) + 1

    patron_dominante, conteo_dominante = None, 0
    if estadisticas:
        patron_dominante, conteo_dominante = sorted(
            estadisticas.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    if conteo_dominante < min_patron:
        patron_dominante = None  # ninguna familia alcanza el mínimo: sin patrón fiable

    # --- Clasificación conforme / anómala --------------------------------------
    anomalias = []
    for c in carpetas:
        if c["es_raiz"]:
            c["conforme"] = True
            c["motivo_anomalia"] = None
            continue
        if patron_dominante is None:
            c["conforme"] = False
            c["motivo_anomalia"] = "sin_patron_dominante"
        elif re.fullmatch(patron_dominante, c["nombre"]):
            c["conforme"] = True
        else:
            c["conforme"] = False
            c["motivo_anomalia"] = "no_cumple_patron_dominante"
        if not c["conforme"]:
            anomalias.append({"ruta": c["ruta"], "motivo": c["motivo_anomalia"]})

    # --- Hojas: carpeta con archivos y sin descendientes con archivos -----------
    con_archivos = {c["ruta"] for c in carpetas if sum(c["conteos"].values()) > 0}
    for c in carpetas:
        prefijo = c["ruta"].rstrip("\\/") + "/"
        tiene_descendiente_con_archivos = any(
            otra.startswith(prefijo) for otra in con_archivos if otra != c["ruta"])
        c["es_hoja"] = (sum(c["conteos"].values()) > 0) and not tiene_descendiente_con_archivos

    return {
        "raiz": str(ruta_raiz),
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "total_carpetas": len(carpetas),
        "patron_dominante": patron_dominante,
        "min_carpetas_para_patron": min_patron,
        "estadisticas_patrones": estadisticas,
        "carpetas": carpetas,
        "anomalias": anomalias,
    }


def os_walk_ordenado(ruta: Path):
    """os.walk determinista (dirnames y filenames ordenados alfabéticamente)."""
    import os
    for dirpath, dirnames, filenames in os.walk(ruta):
        dirnames.sort()
        filenames.sort()
        yield dirpath, dirnames, filenames


def carpetas_hoja(estructura: dict) -> list[dict]:
    """Carpetas hoja (las que la Fase 2 procesa): tienen archivos y nadie debajo tiene."""
    return [c for c in estructura["carpetas"] if c["es_hoja"]]


def guardar_estructura(estructura: dict, ruta: str | Path | None = None) -> Path:
    """Serializa el mapa a JSON UTF-8 (ruta por defecto de config.yaml)."""
    if ruta is None:
        ruta = RAIZ_PROYECTO / cargar_config().get("fase0", {}).get(
            "archivo_salida", "estructura_detectada.json")
    ruta = Path(ruta)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(estructura, f, ensure_ascii=False, indent=2)
    return ruta


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fase 0: auto-descubrimiento de estructura.")
    parser.add_argument("ruta_raiz", help="Carpeta raíz del lote a mapear.")
    parser.add_argument("--salida", default=None, help="Ruta del JSON de salida (default: config).")
    args = parser.parse_args()

    estructura = mapear_estructura(args.ruta_raiz)
    ruta_json = guardar_estructura(estructura, args.salida)

    conformes = sum(1 for c in estructura["carpetas"] if not c["es_raiz"] and c["conforme"])
    print(f"Raíz: {estructura['raiz']}")
    print(f"Patrón dominante: {estructura['patron_dominante']!r} "
          f"(estadísticas: {estructura['estadisticas_patrones']})")
    print(f"Carpetas: {estructura['total_carpetas']} | conformes: {conformes} | "
          f"anómalas: {len(estructura['anomalias'])} | hoja: {len(carpetas_hoja(estructura))}")
    for a in estructura["anomalias"]:
        print(f"  ANÓMALA [{a['motivo']}]: {a['ruta']}")
    print(f"JSON guardado en: {ruta_json}")
