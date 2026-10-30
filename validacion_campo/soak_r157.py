"""Soak de 100–200 análisis en la máquina objetivo (R15.7, criterio §9-7).

Herramienta de CAMPO: se ejecuta junto al dashboard encendido y repite el
análisis completo del lote N veces, verificando después de CADA iteración los
invariantes de la serie R15:

1. identidad del build instalado (`patch_build`);
2. registro de inconsistencias vacío y SIN modo recuperación (fail-closed);
3. el pipeline terminó sin error;
4. `revision_documento` monótona (si se indica `--validacion`);
5. sin temporales huérfanos en `.cache_ocr` (si se indica `--cache-ocr`).

Es de SÓLO lectura sobre el proyecto: no toca el documento ni los almacenes;
únicamente lanza análisis (lo mismo que pulsar «Procesar carpeta» en la UI) y
escribe un reporte JSON con la evidencia.

Uso típico (Windows, con el dashboard corriendo):

    python validacion_campo/soak_r157.py --lote "C:\\Datos\\Lote_Real" ^
        --iteraciones 150 --validacion validacion_resultados.json ^
        --cache-ocr .cache_ocr --salida soak_r157_reporte.json

Sólo comprobar conectividad e invariantes sin lanzar análisis:

    python validacion_campo/soak_r157.py --simular
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ESTADOS_ACTIVOS = {"procesando", "pausando", "pausado", "cancelando", "reanudando"}
ESTADOS_TERMINADOS = {"inactivo", "detenido_con_avance", "completado"}
# Identidad por defecto del soak (criterio 1 de los invariantes).
PATCH_BUILD_R159 = "16.0.2"
# Compatibilidad R15.8/R15.7: los nombres históricos se mantienen como alias
# de lectura y apuntan SIEMPRE a la identidad vigente.
PATCH_BUILD_R158 = PATCH_BUILD_R159
PATCH_BUILD_R157 = PATCH_BUILD_R159


def _pedir_json(base: str, ruta: str, datos: "dict | None" = None,
                timeout: float = 30.0) -> dict:
    url = base.rstrip("/") + ruta
    cuerpo = json.dumps(datos).encode("utf-8") if datos is not None else None
    peticion = urllib.request.Request(
        url, data=cuerpo, method="POST" if cuerpo is not None else "GET",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


class ErrorSoak(RuntimeError):
    """Fallo de conectividad o de contrato de la API."""


def _leer_revision(ruta: Path) -> "int | None":
    try:
        with open(ruta, encoding="utf-8") as fh:
            documento = json.load(fh)
    except (OSError, ValueError):
        return None
    try:
        return int(documento.get("revision_documento") or 0)
    except (TypeError, ValueError):
        return None


def _temporales_huerfanos(directorio: Path) -> list[str]:
    if not directorio.is_dir():
        return []
    return sorted(p.name for p in directorio.iterdir()
                  if p.is_file() and p.name.endswith(".tmp"))


def _lanzar_analisis(base: str, lote: str, perfil: str) -> dict:
    try:
        respuesta = _pedir_json(base, "/api/pipeline", {
            "ruta": lote, "modo_ejecucion": "completo",
            "perfil_rendimiento": perfil})
    except urllib.error.HTTPError as exc:  # 409/423: hay algo en curso
        detalle = exc.read().decode("utf-8", errors="replace")[:400]
        raise ErrorSoak(f"no se pudo lanzar el análisis ({exc.code}): {detalle}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ErrorSoak(f"sin conexión con el dashboard ({base}): {exc}") from exc
    if not isinstance(respuesta, dict) or not respuesta.get("aceptado"):
        raise ErrorSoak(f"respuesta inesperada al lanzar el análisis: {respuesta!r}")
    return respuesta


def _esperar_pipeline(base: str, intervalo: float, arranque_max: float,
                      esperar_max: float,
                      ejecucion_objetivo: "str | None" = None) -> dict:
    """Espera arranque y fin del pipeline; devuelve el estado final.

    R15.8 (MEDIO-07): si el POST termina antes del primer sondeo, se acepta
    un terminal de ESA MISMA ejecución. R15.9 (MEDIO-05, auditoría R15.8):
    la identidad es ESTRICTA cuando el POST devolvió ``ejecucion_id`` — el
    inicio sólo se marca con un activo de ESA ejecución y el terminal sólo se
    acepta con el MISMO id; un activo/terminal de otra ejecución (o con id
    ausente) es evidencia INCONCLUSA y se sigue esperando (antes, un estado
    activo obsoleto hacía aceptar el terminal ajeno ``ANTERIOR``). Sin id en
    el POST, se conserva el criterio heredado activo→terminal (el servidor no
    expone identidad por ejecución).
    """
    inicio = time.monotonic()
    arrancado = False
    ultimo: dict = {}
    while True:
        ultimo = _pedir_json(base, "/api/pipeline/estado")
        estado = str(ultimo.get("estado") or "")
        transcurrido = time.monotonic() - inicio
        eid = ultimo.get("ejecucion_id")
        id_esperado = ejecucion_objetivo is not None
        id_coincide = ((not id_esperado)
                       or (eid not in (None, "")
                           and str(eid) == ejecucion_objetivo))
        if estado in ESTADOS_ACTIVOS and id_coincide:
            arrancado = True
        elif estado in ESTADOS_TERMINADOS and (
                id_coincide or (not id_esperado and arrancado)):
            return ultimo
        # id distinto o ausente con id esperado ⇒ inconcluso: no se acepta la
        # ejecución ajena (MEDIO-05) y se sigue esperando la nuestra.
        if not arrancado and transcurrido > arranque_max:
            raise ErrorSoak(
                "el pipeline no arrancó dentro de la ventana de admisión "
                f"({arranque_max:.0f}s); estado actual: {estado or 'desconocido'}"
                + ("" if not id_esperado else
                   f" (ejecución esperada {ejecucion_objetivo})"))
        if transcurrido > esperar_max:
            raise ErrorSoak(
                f"el análisis excedió la ventana máxima ({esperar_max:.0f}s); "
                f"estado actual: {estado or 'desconocido'}")
        time.sleep(intervalo)


def _invariantes(base: str, esperado: str, validacion: "Path | None",
                 cache_ocr: "Path | None", revision_previa: "int | None") -> dict:
    """(resultado, revision_actual, fallos) de los invariantes de la iteración."""
    fallos: list[str] = []
    detalle: dict = {}
    try:
        estado = _pedir_json(base, "/api/estado")
    except (urllib.error.URLError, OSError) as exc:
        return ({"patch_build": None, "recuperacion": None, "revision": None},
                revision_previa, [f"no se pudo leer /api/estado: {exc}"])
    detalle["patch_build"] = estado.get("patch_build")
    if esperado and estado.get("patch_build") != esperado:
        fallos.append(
            f"patch_build={estado.get('patch_build')!r} ≠ esperado {esperado!r}")

    try:
        recuperacion = _pedir_json(base, "/api/recuperacion/inconsistencias")
    except (urllib.error.URLError, OSError) as exc:
        recuperacion = {"error": f"{type(exc).__name__}: {exc}"}
    detalle["recuperacion"] = {
        "total": recuperacion.get("total"),
        "modo_recuperacion": recuperacion.get("modo_recuperacion"),
        "error": recuperacion.get("error"),
    }
    if recuperacion.get("error"):
        fallos.append(f"no se pudo leer el registro de recuperación: "
                      f"{recuperacion['error']}")
    else:
        if recuperacion.get("modo_recuperacion"):
            fallos.append("el sistema quedó en MODO RECUPERACIÓN")
        if int(recuperacion.get("total") or 0) != 0:
            fallos.append(
                f"quedaron {recuperacion.get('total')} inconsistencia(s) sin "
                "resolver (fail-closed: revisar antes de seguir)")

    revision = revision_previa
    if validacion is not None:
        revision = _leer_revision(validacion)
        detalle["revision"] = revision
        if revision is None:
            fallos.append(f"no se pudo leer revision_documento de {validacion}")
        elif revision_previa is not None and revision < revision_previa:
            fallos.append(
                f"revision_documento retrocedió ({revision_previa} → {revision})")
    if cache_ocr is not None:
        huerfanos = _temporales_huerfanos(cache_ocr)
        detalle["temporales_huerfanos"] = huerfanos
        if huerfanos:
            fallos.append("temporales huérfanos en .cache_ocr: "
                          + ", ".join(huerfanos))
    return detalle, revision, fallos


def ejecutar_soak(base: str, lote: str, iteraciones: int, perfil: str,
                  intervalo: float, arranque_max: float, esperar_max: float,
                  esperado: str, validacion: "Path | None",
                  cache_ocr: "Path | None", simular: bool = False,
                  log=print) -> dict:
    reporte: dict = {
        "herramienta": "soak_r157",
        "iniciado_en": datetime.now().isoformat(timespec="seconds"),
        "base_url": base, "lote": lote, "iteraciones_pedidas": iteraciones,
        "patch_build_esperado": esperado, "simular": simular,
        "iteraciones": [], "fallos": [],
    }
    if simular:
        detalle, revision, fallos = _invariantes(base, esperado, validacion,
                                                 cache_ocr, None)
        reporte["iteraciones"].append({
            "n": 0, "simulada": True, "invariantes": detalle, "fallos": fallos})
        reporte["fallos"].extend(fallos)
        reporte["ok"] = not reporte["fallos"]
        return reporte

    revision_previa = _leer_revision(validacion) if validacion else None
    for numero in range(1, iteraciones + 1):
        inicio = time.monotonic()
        fallos: list[str] = []
        estado_final: dict = {}
        # R15.8 (MEDIO-08, auditoría R15.7): el estado se REINICIA en cada
        # iteración; el ``ejecucion_id`` reportado es siempre el de ESTA
        # iteración (o None si el lanzamiento falló), nunca el heredado de la
        # anterior (antes la variable ``lanzado`` no se reiniciaba por ciclo).
        lanzado: "dict | None" = None
        ejecucion_objetivo: "str | None" = None
        try:
            lanzado = _lanzar_analisis(base, lote, perfil)
            ejecucion_objetivo = (str(lanzado.get("ejecucion_id"))
                                  if lanzado.get("ejecucion_id") else None)
            estado_final = _esperar_pipeline(base, intervalo, arranque_max,
                                             esperar_max, ejecucion_objetivo)
            if estado_final.get("error"):
                fallos.append(f"el pipeline terminó con error: "
                              f"{estado_final['error']}")
            if (ejecucion_objetivo is not None
                    and estado_final.get("ejecucion_id")
                    and estado_final.get("ejecucion_id") != ejecucion_objetivo):
                fallos.append(
                    "el estado final pertenece a otra ejecución "
                    f"({estado_final.get('ejecucion_id')} ≠ "
                    f"{ejecucion_objetivo})")
        except ErrorSoak as exc:
            fallos.append(str(exc))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            fallos.append(f"fallo de comunicación: {type(exc).__name__}: {exc}")
        duracion = time.monotonic() - inicio
        detalle, revision_previa, fallos_invariantes = _invariantes(
            base, esperado, validacion, cache_ocr, revision_previa)
        fallos.extend(fallos_invariantes)
        if validacion is None:
            revision_previa = None
        recursos = (estado_final.get("metricas_recursos")
                    if isinstance(estado_final, dict) else None)
        reporte["iteraciones"].append({
            "n": numero,
            "ejecucion_id": (str(lanzado.get("ejecucion_id"))
                             if isinstance(lanzado, dict)
                             and lanzado.get("ejecucion_id") else None),
            "duracion_s": round(duracion, 3),
            "estado_final": estado_final.get("estado"),
            "resumen": estado_final.get("resumen"),
            "metricas_recursos": recursos,
            "invariantes": detalle,
            "fallos": fallos,
        })
        reporte["fallos"].extend(f"iteración {numero}: {f}" for f in fallos)
        log(f"[soak] iteración {numero}/{iteraciones} · "
            f"{duracion:.1f}s · {'OK' if not fallos else 'FALLO'}")
        if fallos:
            log("[soak] se detiene en el primer fallo para no contaminar la "
                "evidencia; resuelve y vuelve a ejecutar.")
            break
    reporte["ok"] = not reporte["fallos"]
    reporte["finalizado_en"] = datetime.now().isoformat(timespec="seconds")
    return reporte


def main(argv: "list[str] | None" = None) -> int:
    analizador = argparse.ArgumentParser(
        description="Soak de análisis V-Matrix R15.7 con verificación de "
                    "invariantes (criterio §9-7 de la auditoría R15.6).")
    analizador.add_argument("--base-url", default="http://127.0.0.1:8000")
    analizador.add_argument("--lote", default=None,
                            help="Carpeta del lote a analizar (obligatoria si no es --simular).")
    analizador.add_argument("--iteraciones", type=int, default=1)
    analizador.add_argument("--perfil", default="alto",
                            choices=["estable", "alto", "maximo"])
    analizador.add_argument("--intervalo", type=float, default=2.0,
                            help="Segundos entre sondeos de /api/pipeline/estado.")
    analizador.add_argument("--arranque-max", type=float, default=120.0)
    analizador.add_argument("--esperar-max", type=float, default=3600.0)
    analizador.add_argument("--patch-build-esperado", default=PATCH_BUILD_R159)
    analizador.add_argument("--validacion", default=None,
                            help="Ruta a validacion_resultados.json (revisión monótona).")
    analizador.add_argument("--cache-ocr", default=None,
                            help="Directorio .cache_ocr (temporales huérfanos).")
    analizador.add_argument("--salida", default=None)
    analizador.add_argument("--simular", action="store_true",
                            help="No lanza análisis: sólo comprueba invariantes.")
    args = analizador.parse_args(argv)

    if not args.simular and not args.lote:
        print("Falta --lote (o usa --simular).", file=sys.stderr)
        return 2
    salida = Path(args.salida) if args.salida else Path(
        f"soak_r157_reporte_{datetime.now():%Y%m%d_%H%M%S}.json")
    reporte = ejecutar_soak(
        base=args.base_url, lote=args.lote or "", iteraciones=max(1, args.iteraciones),
        perfil=args.perfil, intervalo=args.intervalo,
        arranque_max=args.arranque_max, esperar_max=args.esperar_max,
        esperado=args.patch_build_esperado,
        validacion=Path(args.validacion) if args.validacion else None,
        cache_ocr=Path(args.cache_ocr) if args.cache_ocr else None,
        simular=args.simular)
    salida.write_text(json.dumps(reporte, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"[soak] reporte: {salida}")
    if reporte["ok"]:
        print(f"[soak] OK · {len(reporte['iteraciones'])} comprobación(es) sin fallos")
        return 0
    print("[soak] FALLOS:", file=sys.stderr)
    for fallo in reporte["fallos"]:
        print(f"  - {fallo}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover — CLI
    raise SystemExit(main())
