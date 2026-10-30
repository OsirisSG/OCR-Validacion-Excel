"""Inventario del árbol DESTINO después de una actualización (R15.7, P2).

Auditoría R15.6, BAJO-06: el inventario de pruebas se tomaba del *staging*
canónico (39 `.cjs`) mientras la base instalada conservaba un test legado
adicional (40). Las simulaciones de actualización deben inventariar el árbol
REAL de destino para no confundir «lo que entrega el paquete» con «lo que
queda instalado».

Este módulo es de sólo lectura: no modifica nada. Uso como biblioteca
(``inventariar_destino``) y como utilidad de línea de comandos:

    python -m utilidades.inventario_destino --destino <ruta> --staging <ruta>
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

__all__ = ["inventariar_destino", "inventariar_paquetes"]

_PATCH_BUILD_RE = re.compile(
    r"""PATCH_BUILD\s*=\s*["'](?P<version>[^"']+)["']""")


def _leer_version(destino: Path) -> "str | None":
    archivo = destino / "VERSION.txt"
    if not archivo.is_file():
        return None
    try:
        return archivo.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _leer_patch_build(destino: Path) -> "str | None":
    app = destino / "dashboard" / "backend" / "app.py"
    if not app.is_file():
        return None
    try:
        contenido = app.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    coincidencia = _PATCH_BUILD_RE.search(contenido)
    return coincidencia.group("version") if coincidencia else None


def _listar(directorio: Path, sufijo: str) -> list[str]:
    if not directorio.is_dir():
        return []
    return sorted(archivo.name for archivo in directorio.iterdir()
                  if archivo.is_file() and archivo.name.endswith(sufijo))


def inventariar_destino(destino: str | Path,
                        staging: str | Path | None = None) -> dict:
    """Inventaría el árbol destino y lo compara con el staging del paquete.

    Devuelve identidad (VERSION.txt / PATCH_BUILD), conteo de pruebas `.py` y
    `.cjs`, los tests EXTRA presentes en destino y ausentes del staging
    (legado heredado) y si la identidad es coherente entre VERSION.txt y
    `PATCH_BUILD`.
    """
    destino = Path(destino)
    pruebas_dir = destino / "pruebas"
    pruebas_py = _listar(pruebas_dir, ".py")
    pruebas_cjs = _listar(pruebas_dir, ".cjs")

    staging_info = {"cjs": 0, "py": 0, "extras_en_destino": [],
                    "faltantes_en_destino": [], "staging": None}
    if staging is not None:
        staging = Path(staging)
        staging_info["staging"] = str(staging)
        staging_py = _listar(staging / "pruebas", ".py")
        staging_cjs = _listar(staging / "pruebas", ".cjs")
        staging_info["cjs"] = len(staging_cjs)
        staging_info["py"] = len(staging_py)
        staging_info["extras_en_destino"] = sorted(
            set(pruebas_cjs) - set(staging_cjs))
        staging_info["faltantes_en_destino"] = sorted(
            set(staging_cjs) - set(pruebas_cjs))

    version = _leer_version(destino)
    patch_build = _leer_patch_build(destino)
    return {
        "destino": str(destino),
        "identidad": {"version": version, "patch_build": patch_build,
                      "patch_build_en_app": patch_build is not None},
        "pruebas": {
            "py": len(pruebas_py),
            "cjs": len(pruebas_cjs),
            "extras_heredados": staging_info["extras_en_destino"],
            "faltantes": staging_info["faltantes_en_destino"],
            "staging": {"cjs": staging_info["cjs"], "py": staging_info["py"]},
            "staging_ruta": staging_info["staging"],
        },
        "coherente": bool(version) and version == patch_build,
    }


def inventariar_paquetes(raiz: str | Path) -> dict:
    """Inventaría todos los paquetes de parche presentes en una carpeta de
    entrega (subcarpetas con MANIFEST_SHA256_*.txt)."""
    raiz = Path(raiz)
    paquetes = []
    for manifiesto in sorted(raiz.glob("**/MANIFEST_SHA256_*.txt")):
        paquetes.append({"manifiesto": str(manifiesto),
                         "directorio": str(manifiesto.parent),
                         "entradas": sum(
                             1 for linea in manifiesto.read_text(
                                 encoding="utf-8", errors="replace").splitlines()
                             if linea.strip())})
    return {"raiz": str(raiz), "paquetes": paquetes}


def _main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventario del árbol destino de una actualización V-Matrix.")
    parser.add_argument("--destino", required=True)
    parser.add_argument("--staging", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    informe = inventariar_destino(args.destino, staging=args.staging)
    if args.json:
        print(json.dumps(informe, ensure_ascii=False, indent=2))
        return 0
    identidad = informe["identidad"]
    pruebas = informe["pruebas"]
    print(f"Destino : {informe['destino']}")
    print(f"Versión : {identidad['version']} (PATCH_BUILD: "
          f"{identidad['patch_build']})")
    print(f"Pruebas : {pruebas['py']} .py / {pruebas['cjs']} .cjs "
          f"(staging: {pruebas['staging']['py']} .py / "
          f"{pruebas['staging']['cjs']} .cjs)")
    if pruebas["extras_heredados"]:
        print("Extras heredados en destino: "
              + ", ".join(pruebas["extras_heredados"]))
    if pruebas["faltantes"]:
        print("Faltantes en destino: " + ", ".join(pruebas["faltantes"]))
    print(f"Coherente: {'sí' if informe['coherente'] else 'NO'}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI
    raise SystemExit(_main())
