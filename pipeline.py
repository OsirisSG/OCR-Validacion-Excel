"""
pipeline.py — Orquestador de las Fases 0 a 3 en una sola ejecución.

Uso:
    python pipeline.py <ruta_raiz>

Ejecuta: mapeo de estructura → validación cruzada → Excel maestro, usando los
artefactos y rutas de config.yaml. Retorna/imprime un resumen por fase (doc §11).
"""

from __future__ import annotations

import argparse
import functools
import inspect
import json
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Callable

from configuracion import RAIZ_PROYECTO, cargar_config
from estructura import carpetas_hoja, guardar_estructura, mapear_estructura
from generar_excel import generar_excel
from inventario import cargar_inventario, crear_inventario, estructura_desde_inventario
from recursos import detectar_recursos
from validacion import validar_lote, validar_lote_empresarial


def _bloqueo_pipeline(func):
    """Impide que dos procesos escriban simultáneamente el mismo caché/salida."""
    @functools.wraps(func)
    def protegido(*args, **kwargs):
        ruta_bloqueo = RAIZ_PROYECTO / ".cache_ocr" / "pipeline.lock"
        ruta_bloqueo.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(ruta_bloqueo, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            try:
                pid = int(ruta_bloqueo.read_text(encoding="ascii").strip())
                os.kill(pid, 0)
            except (OSError, ValueError):
                ruta_bloqueo.unlink(missing_ok=True)
                descriptor = os.open(ruta_bloqueo, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            else:
                raise RuntimeError(
                    "Ya existe otro pipeline activo sobre este proyecto. Espera a que termine.") from exc
        try:
            os.write(descriptor, str(os.getpid()).encode())
            os.close(descriptor)
            return func(*args, **kwargs)
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
            ruta_bloqueo.unlink(missing_ok=True)
    return protegido


@_bloqueo_pipeline
def ejecutar_pipeline(ruta_raiz: str | Path, config: dict | None = None,
                      al_progreso: Callable[[str, str, dict | None], None] | None = None,
                      nombre_excel: str | None = None,
                      sobrescribir_excel: bool = False,
                      control: Callable[[], None] | None = None,
                      tipo_st: str | None = None,
                      ruta_plantilla: str | Path | None = None,
                      plantilla_id: str | None = None,
                      casos_filtrados: set[str] | None = None,
                      imagenes_filtradas: set[str] | None = None,
                      casos_omitidos: set[str] | None = None,
                      solo_errores: bool = False,
                      modo_recorte: str | None = None,
                      roi_manual: dict[str, float] | None = None,
                      modo_ejecucion: str = "completo",
                      ruta_inventario: str | Path | None = None,
                      zoom_forzado: float | None = None) -> dict:
    """Corre las Fases 0-3 y retorna un dict con artefactos y resumen por fase."""
    config = config or cargar_config()
    recursos = detectar_recursos(config.get("fase1", {}).get("dispositivo", "auto"))
    resumen: dict = {"raiz": str(ruta_raiz), "fases": {}, "recursos": recursos}

    def progreso(fase: str, mensaje: str, detalle: dict | None = None) -> None:
        if al_progreso:
            al_progreso(fase, mensaje, detalle)

    modo_ejecucion = str(modo_ejecucion or "completo").lower()
    if modo_ejecucion not in {"completo", "inventario", "reanudar"}:
        raise ValueError("Modo inválido: usa completo, inventario o reanudar.")
    t0 = time.time()
    if control:
        control()
    progreso("fase_a", "Analizando la estructura de carpetas", {
        "porcentaje": 2, "recursos": recursos})
    casos_detectados = []

    def caso_detectado(caso: dict) -> None:
        casos_detectados.append(caso)
        progreso("fase_a", f"Caso detectado: {caso.get('nombre')}", {
            "porcentaje": 4, "caso_detectado": caso,
            "casos_detectados": len(casos_detectados),
        })

    inventario = None
    if modo_ejecucion == "reanudar":
        ruta_inventario = ruta_inventario or RAIZ_PROYECTO / "inventario_proyecto.json"
        inventario = cargar_inventario(ruta_inventario, ruta_raiz)
        estructura = estructura_desde_inventario(inventario)
        progreso("fase_a", "Inventario existente recuperado", {
            "porcentaje": 7, "casos_detectados": inventario["casos_encontrados"],
            "imagenes_total": inventario["fotografias"],
        })
    else:
        parametros_mapeo = inspect.signature(mapear_estructura).parameters
        extras_mapeo = {}
        if "tipo_st" in parametros_mapeo:
            extras_mapeo["tipo_st"] = tipo_st
        if "al_descubrir_caso" in parametros_mapeo:
            extras_mapeo["al_descubrir_caso"] = caso_detectado
        estructura = mapear_estructura(ruta_raiz, config, **extras_mapeo)
    ruta_estructura = guardar_estructura(estructura)
    if estructura.get("casos_empresariales") and estructura.get("requiere_seleccion_tipo_st"):
        raise ValueError(
            "No fue posible determinar si el proyecto corresponde a 1ST o 2ST. "
            "Selecciona 1ST, 2ST o usa el recorrido tradicional.")
    usar_empresarial = bool(estructura.get("casos_empresariales"))
    if usar_empresarial and inventario is None:
        ruta_inv = ruta_inventario or RAIZ_PROYECTO / "inventario_proyecto.json"
        total_inv = max(len(estructura.get("casos_empresariales", [])), 1)
        vistos_inv = 0

        def caso_inventariado(caso: dict) -> None:
            nonlocal vistos_inv
            vistos_inv += 1
            progreso("fase_a", f"Inventariando {caso.get('nombre')}", {
                "porcentaje": round(4 + (vistos_inv / total_inv) * 3, 1),
                "casos_detectados": vistos_inv,
            })

        inventario = crear_inventario(
            estructura, ruta_inv,
            calcular_hash=bool(config.get("empresarial", {}).get("inventario_hash", False)),
            al_caso=caso_inventariado,
        )
    from plantilla_empresarial import detectar_plantilla_automatica
    seleccion_plantilla = detectar_plantilla_automatica(
        ruta_raiz, estructura, config, explicita=ruta_plantilla,
        plantilla_id=plantilla_id)
    ruta_plantilla = seleccion_plantilla.get("ruta")
    if usar_empresarial and ruta_plantilla:
        from plantilla_empresarial import cargar_contrato
        contrato = cargar_contrato(Path(ruta_plantilla))
        config = deepcopy(config)
        requeridos = [clave for clave, regla in contrato["esquema"].items()
                      if str(regla.get("requerido") or "").lower() in {"sí", "si"}]
        config.setdefault("empresarial", {})["campos_requeridos"] = requeridos
        config.setdefault("empresarial", {})["claves_plantilla"] = list(
            contrato["claves"])
        config.setdefault("fase3", {})["plantilla_empresarial"] = str(ruta_plantilla)
    total_hojas = (len(estructura.get("casos_empresariales", [])) if usar_empresarial
                   else len(carpetas_hoja(estructura)))
    resumen["fases"]["fase0"] = {
        "artifacto": str(ruta_estructura),
        "total_carpetas": estructura["total_carpetas"],
        "patron_dominante": estructura["patron_dominante"],
        "anomalias": len(estructura["anomalias"]),
        "hojas": total_hojas,
        "perfil": "empresarial" if usar_empresarial else "legacy",
        "tipo_st": estructura.get("tipo_st"),
        "tipos_st": estructura.get("tipos_st", []),
        "casos_validos": estructura.get("casos_validos", 0),
        "casos_incompletos": estructura.get("casos_incompletos", 0),
        "plantilla": seleccion_plantilla,
    }
    resumen["fases"]["fase_a"] = {
        "artifacto": inventario.get("archivo_salida") if inventario else str(ruta_estructura),
        "casos": inventario.get("casos_encontrados", total_hojas) if inventario else total_hojas,
        "fotografias": inventario.get("fotografias") if inventario else None,
        "modo": modo_ejecucion,
    }
    if modo_ejecucion == "inventario":
        resumen["duracion_segundos"] = round(time.time() - t0, 1)
        progreso("completado", "Inventario terminado; OCR no ejecutado", {
            "porcentaje": 100, "eta_segundos": 0, "restantes": 0,
        })
        return resumen

    progreso("fase2", "Ejecutando OCR y validación cruzada", {
        "porcentaje": 8, "procesadas": 0, "total": total_hojas,
        "restantes": total_hojas,
    })

    def resultado_listo(procesadas: int, total: int, fila: dict,
                        eta_segundos: float | None) -> None:
        progreso(
            "fase2",
            f"Carpeta {procesadas} de {total} terminada",
            {
                "procesadas": procesadas,
                "total": total,
                "restantes": max(total - procesadas, 0),
                "resultado": fila,
            },
        )

    def imagen_lista(procesadas: int, total: int, ruta_imagen: str,
                     eta_segundos: float | None) -> None:
        avance = procesadas / total if total else 1.0
        progreso(
            "fase2", f"Imagen {procesadas} de {total}: {Path(ruta_imagen).name}",
            {
                "porcentaje": round(8 + avance * 84, 1),
                "imagenes_procesadas": procesadas,
                "imagenes_total": total,
                "imagenes_restantes": max(total - procesadas, 0),
                "eta_segundos": eta_segundos,
                "imagen_actual": Path(ruta_imagen).name,
            },
        )

    argumentos_validacion = {
        "al_resultado": resultado_listo,
        "al_imagen": imagen_lista,
    }
    if control is not None:
        argumentos_validacion["control"] = control
    if usar_empresarial:
        argumentos_validacion["al_caso"] = lambda caso: progreso(
            "fase2", f"Procesando ID {caso.get('nombre')}", {"caso_actualizado": caso})
        argumentos_validacion.update({
            "casos_filtrados": casos_filtrados,
            "casos_omitidos": casos_omitidos,
            "imagenes_filtradas": imagenes_filtradas,
            "solo_errores": solo_errores,
            "modo_recorte": modo_recorte,
            "roi_manual": roi_manual,
            "zoom_forzado": zoom_forzado,
        })
    if usar_empresarial:
        validacion = validar_lote_empresarial(
            ruta_estructura, config, **argumentos_validacion)
    else:
        # Conserva compatibilidad con integraciones/pruebas que sustituyen el
        # validador legacy con la firma anterior.
        if (casos_omitidos and
                "casos_omitidos" in inspect.signature(validar_lote).parameters):
            argumentos_validacion["casos_omitidos"] = casos_omitidos
        validacion = validar_lote(ruta_estructura, config, **argumentos_validacion)
    conteo: dict[str, int] = {}
    for fila in validacion["resultados"]:
        conteo[fila["comparacion"]["resultado"]] = conteo.get(fila["comparacion"]["resultado"], 0) + 1
    resumen["fases"]["fase2"] = {
        "artifacto": validacion["archivo_salida"],
        "carpetas_procesadas": validacion["carpetas_procesadas"],
        "resultados": conteo,
        "aprendizaje": validacion.get("aprendizaje"),
    }

    progreso("fase3", "Generando el Excel maestro", {"porcentaje": 95, "eta_segundos": None})
    if control:
        control()
    nombre = str(nombre_excel or config.get("fase3", {}).get(
        "archivo_salida", "resultado_maestro.xlsx")).strip()
    if Path(nombre).name != nombre or nombre in {".", ".."}:
        raise ValueError("El nombre del Excel no debe contener carpetas.")
    if not nombre.lower().endswith(".xlsx"):
        nombre = (Path(nombre).with_suffix(".xlsx").name if Path(nombre).suffix
                  else nombre + ".xlsx")
    ruta_destino = RAIZ_PROYECTO / nombre
    if ruta_destino.exists() and not sobrescribir_excel:
        base, extension = ruta_destino.stem, ruta_destino.suffix
        indice = 1
        while True:
            candidata = ruta_destino.with_name(f"{base}_{indice}{extension}")
            if not candidata.exists():
                ruta_destino = candidata
                break
            indice += 1
    ruta_excel = (generar_excel(None, ruta_destino, config, ruta_plantilla=ruta_plantilla)
                  if ruta_plantilla else generar_excel(None, ruta_destino, config))
    if validacion.get("perfil") == "empresarial":
        validacion["archivo_excel"] = str(ruta_excel)
        validacion["ruta_plantilla"] = str(ruta_plantilla) if ruta_plantilla else None
        with open(validacion["archivo_salida"], "w", encoding="utf-8") as archivo:
            json.dump(validacion, archivo, ensure_ascii=False, indent=2)
    resumen["fases"]["fase3"] = {
        "artifacto": str(ruta_excel), "plantilla": seleccion_plantilla}
    resumen["duracion_segundos"] = round(time.time() - t0, 1)
    progreso("completado", "Resultados y Excel actualizados", {
        "porcentaje": 100, "eta_segundos": 0, "restantes": 0,
    })
    return resumen


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline completo Fases 0-3.")
    parser.add_argument("ruta_raiz", help="Carpeta raíz del lote a procesar.")
    parser.add_argument("--excel", default=None, help="Nombre del Excel de salida.")
    parser.add_argument("--sobrescribir", action="store_true",
                        help="Reemplaza el Excel si ya existe.")
    parser.add_argument("--tipo-st", choices=["1ST", "2ST", "LEGACY"], default=None,
                        help="Fuerza el tipo de proyecto o el recorrido tradicional.")
    parser.add_argument("--plantilla", default=None,
                        help="Plantilla .xlsx empresarial con las 36 claves estables.")
    parser.add_argument("--modo", choices=["completo", "inventario", "reanudar"],
                        default="completo", help="Ejecuta ambas fases, solo inventario o lo reanuda.")
    parser.add_argument("--inventario", default=None,
                        help="Ruta del inventario persistente de Fase A.")
    parser.add_argument("--zoom", type=float, default=None,
                        help="Fuerza el zoom OCR dentro de los límites configurados.")
    args = parser.parse_args()
    resumen = ejecutar_pipeline(
        args.ruta_raiz.strip().strip('"\''), nombre_excel=args.excel,
        sobrescribir_excel=args.sobrescribir, tipo_st=args.tipo_st,
        ruta_plantilla=args.plantilla, modo_ejecucion=args.modo,
        ruta_inventario=args.inventario, zoom_forzado=args.zoom)
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
