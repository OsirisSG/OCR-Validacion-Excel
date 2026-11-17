#!/usr/bin/env python3
"""P43 · Validación LOCAL con las fotos del cliente (las fotos no salen del equipo).

    python validar_corrida_p43.py --fotos "D:\\Pruebas\\Jetta_Gran_Turismo_1ST" ^
        --libro "D:\\Libros\\versionV16_0_51.xlsx" --salida "D:\\Validaciones P43" ^
        [--referencia "D:\\Libros\\Book-10-Examples_CORREGIDO.xlsx"] [--tipo-st 1ST] ^
        [--perfil-edag] [--sin-segunda-pasada] [--presupuesto-s 300]

Recorre la RUTA NORMAL (`estructura.mapear_estructura` → `validacion.validar_lote_empresarial`
con el tablero P42 activo → `consolidar_caso` → `reporte_bmg.generar_reporte_bmg`) en un
directorio ÚNICO creado dentro de --salida:

- el --libro se usa como partida y NO se modifica (se comprueba su SHA-256 antes y después);
- el JSON de validación de esta corrida se escribe en el directorio único; si existe el
  `validacion_resultados.json` del proyecto, se COPIA allí antes de empezar para que las
  correcciones humanas ya guardadas sigan mandando, y el del proyecto queda intacto;
- el caché OCR genérico es el del proyecto (mismo comportamiento que una corrida normal);
- la lectura del tablero es SIEMPRE fresca: no se lee ningún JSON de evidencia anterior.

Al final: `verificacion.json` + `informe_tablero_p42.txt` (fotos examinadas, descartadas con
motivo, con error y pendientes) y, con --referencia, la EVALUACIÓN (sólo medición).
Código de salida: 0 si la verificación obligatoria pasa; 1 si no; 2 si faltan entradas.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from copy import deepcopy
from pathlib import Path

AQUI = Path(__file__).resolve().parent
if str(AQUI) not in sys.path:
    sys.path.insert(0, str(AQUI))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Corrida local de validación P43 (tablero integrado)")
    ap.add_argument("--fotos", required=True, help="carpeta raíz del lote (como en pipeline.py)")
    ap.add_argument("--libro", required=True, help="libro de partida; NO se modifica")
    ap.add_argument("--salida", required=True, help="carpeta donde crear el directorio único")
    ap.add_argument("--referencia", default="", help="Book corregido: SÓLO para evaluar")
    ap.add_argument("--tipo-st", choices=["1ST", "2ST"], default=None)
    ap.add_argument("--perfil-edag", action="store_true",
                    help="declara perfil EDAG para ESTA corrida (habilita la semana WWYYNN corroborada)")
    ap.add_argument("--sin-segunda-pasada", action="store_true")
    ap.add_argument("--presupuesto-s", type=float, default=None,
                    help="presupuesto de la segunda pasada por caso (s)")
    ap.add_argument("--limpiar-recortes", action="store_true",
                    help="borra los recortes al terminar (conserva informes)")
    args = ap.parse_args(argv)

    fotos, libro = Path(args.fotos.strip().strip('"')), Path(args.libro.strip().strip('"'))
    if not fotos.is_dir() or not libro.is_file():
        print(f"falta la carpeta de fotos o el libro: {fotos} · {libro}", file=sys.stderr)
        return 2
    import validacion
    import verificar_salida_p43 as V
    from configuracion import RAIZ_PROYECTO, cargar_config, cargar_reglas
    from estructura import guardar_estructura, mapear_estructura
    from reporte_bmg import generar_reporte_bmg

    huella = hashlib.sha256(libro.read_bytes()).hexdigest()
    Path(args.salida).mkdir(parents=True, exist_ok=True)
    marca = time.strftime("%Y%m%d_%H%M%S")
    trabajo = Path(tempfile.mkdtemp(prefix=f"validacion_p43_{marca}_", dir=str(Path(args.salida).resolve())))
    print(f"directorio de la corrida: {trabajo}", flush=True)

    config = deepcopy(cargar_config())
    emp = config.setdefault("empresarial", {})
    tablero = emp.setdefault("tablero_p42", {})
    tablero["activar"] = True
    if args.sin_segunda_pasada:
        tablero["segunda_pasada"] = False
    if args.presupuesto_s is not None:
        tablero["presupuesto_segunda_s"] = float(args.presupuesto_s)
    if args.perfil_edag:
        emp.setdefault("perfil_extraccion", {})["laboratorio"] = "EDAG"
    emp["archivo_avance_ids"] = str(trabajo / "avances_ids.json")

    json_validacion = trabajo / "validacion_p43.json"
    previo = RAIZ_PROYECTO / "validacion_resultados.json"
    if previo.is_file():
        shutil.copy2(previo, json_validacion)        # correcciones humanas vigentes, sin tocar el original

    def progreso(_procesadas, _total, ruta, eta):
        print(f"  imagen {_procesadas}/{_total} · {Path(ruta).name} · eta {eta:.0f} s", flush=True)

    estructura = mapear_estructura(fotos, config, tipo_st=args.tipo_st)
    ruta_estructura = guardar_estructura(estructura, trabajo / "estructura.json")
    if not estructura.get("casos_empresariales"):
        print("no se detectaron casos empresariales en la carpeta de fotos", file=sys.stderr)
        return 2
    resultado = validacion.validar_lote_empresarial(
        ruta_estructura, config, archivo_salida=json_validacion,
        dir_corrida=trabajo / "artefactos", al_imagen=progreso,
        ejecucion_id_aprendizaje=None)
    salida = generar_reporte_bmg(
        libro, trabajo / f"{libro.stem}_OCR_{marca}.xlsx", resultado["resultados"], config,
        cargar_reglas(), identidad_proyecto=estructura.get("proyecto"))
    informe_ruta = trabajo / "artefactos" / "informe_tablero_p42.json"
    informe = json.loads(informe_ruta.read_text(encoding="utf-8")) if informe_ruta.is_file() else None
    verificacion = V.verificar(libro, salida, resultado, informe, huella)
    if args.referencia:
        verificacion["evaluacion"] = V.evaluar(salida, Path(args.referencia.strip().strip('"')))
    verificacion.update({"libro": str(libro), "salida": str(salida), "fotos": str(fotos),
                         "huella_libro": huella, "directorio": str(trabajo)})
    # P45 · lecturas para el panel de dudas (formulario de propuestas) de ESTA corrida
    from utilidades.dudas_y_opciones import lecturas_desde_validacion
    from utilidades.vocabulario_libro import rutas_configuradas, vocabulario
    lecturas_panel, ambiguos = lecturas_desde_validacion(
        resultado, vocabulario(rutas_configuradas(config, RAIZ_PROYECTO)))
    (trabajo / "lecturas_panel.json").write_text(
        json.dumps(lecturas_panel, ensure_ascii=False, indent=1), encoding="utf-8")
    verificacion["panel_dudas"] = {"lecturas": str(trabajo / "lecturas_panel.json"),
                                   "numeros_ambiguos": ambiguos}
    (trabajo / "verificacion.json").write_text(
        json.dumps(verificacion, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if args.limpiar_recortes:
        shutil.rmtree(trabajo / "artefactos" / "tablero_p42", ignore_errors=True)
    print(V.texto(verificacion))
    print(f"\nsalida:       {salida}\ninforme:      {trabajo / 'artefactos' / 'informe_tablero_p42.txt'}"
          f"\ndudas:        {trabajo / 'artefactos' / 'dudas_tablero_p42.json'}"
          f"\nverificación: {trabajo / 'verificacion.json'}"
          f"\npanel dudas:  ABRIR_DUDAS.bat \"{salida}\" \"{trabajo / 'lecturas_panel.json'}\"")
    return 0 if verificacion["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
