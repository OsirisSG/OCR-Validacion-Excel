"""Validación de Tmax/semáforo con ground truth humano (R15.7, criterio §9-8).

DEFINICIÓN (R15.8, observación de la auditoría R15.7): en esta herramienta
«Tmax» significa el TIEMPO DE APERTURA PUBLICADO por el sistema — el valor de
``resultado_caso_canonico.apertura.tiempo_ms`` (o ``opening_time_ms`` en
documentos heredados), el mismo que colorea el semáforo del dashboard y del
Excel. NO es el «máximo inflado» del análisis de video ni ningún otro campo:
validar que la cifra publicada coincide con la observación humana es exactamente
el objetivo del criterio §9-8; la calibración del máximo inflado es un proceso
aparte (zona de apertura / aprendizaje de video).

Compara el tiempo de apertura PUBLICADO por el sistema (el mismo valor que
colorea el dashboard y el Excel) contra el tiempo medido por una persona, y
clasifica ambos con las reglas vigentes del proyecto
(`criterios_usuario.criterios_o_predeterminados()` → mismo motor que la UI).

Es de SÓLO lectura: no modifica el documento, ni los criterios, ni el Excel.

Entrada 1 — ground truth (CSV, plantilla incluida en esta carpeta):

    caso,tiempo_ms_humano,nota
    1001,5.9,"lectura cuadro a cuadro"
    A1_variante3,6.4,

`caso` se empareja por `case_key`, `nombre`, id corto (hash del caso), o por el
nombre de la carpeta de la fila.

Entrada 2 — documento del proyecto (`validacion_resultados.json`).

Salida — reporte JSON + tabla por consola con: valor humano, valor detectado,
delta, semáforo detectado vs humano, acuerdo y métricas agregadas (MAE, mediana,
% dentro de tolerancia, % de acuerdo de semáforo).

Uso:

    python validacion_campo/validar_tmax_semaforo.py ^
        --validacion validacion_resultados.json ^
        --ground-truth validacion_campo/ground_truth_tmax.csv ^
        --tolerancia-ms 1.0 --salida validacion_tmax_reporte.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from criterios_usuario import (criterios_o_predeterminados,  # noqa: E402
                              reglas_apertura)
from utilidades.matriz_apertura import evaluar_apertura  # noqa: E402

__all__ = ["validar", "main"]

_ESTADOS_CONFIRMADOS = {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"}


def _id_corto(fila: dict) -> str:
    clave = str(fila.get("case_key") or fila.get("ruta") or fila.get("nombre") or "")
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()[:16]


def _claves_de_fila(fila: dict) -> set:
    claves = {str(fila.get("case_key") or ""), str(fila.get("nombre") or ""),
              _id_corto(fila)}
    ruta = str(fila.get("ruta") or "")
    if ruta:
        claves.add(Path(ruta).name)
    return {clave.casefold() for clave in claves if clave}


def _apertura_detectada(fila: dict) -> tuple["float | None", str]:
    """(valor, estado) con la MISMA prioridad que publica el dashboard:
    resultado canónico (VERIFICADO_HUMANO/AUTO_VERIFICABLE → tiempo final;
    PROPUESTA/CONFLICTO → tiempo propuesto) y, si no, compatibilidad legacy."""
    canonico = fila.get("resultado_caso_canonico")
    if isinstance(canonico, dict):
        apertura = canonico.get("apertura") if isinstance(
            canonico.get("apertura"), dict) else {}
        estado = apertura.get("estado")
        if estado in _ESTADOS_CONFIRMADOS:
            valor = apertura.get("tiempo_ms")
            return (_positivo(valor), "confirmado")
        if estado in {"PROPUESTA", "CONFLICTO"}:
            return (_positivo(apertura.get("tiempo_propuesto_ms")), "propuesta")
        if estado in {"NO_OBSERVADO", "NO_APLICA"}:
            return (None, "sin_tiempo")
    dato = (fila.get("campos") or {}).get("opening_time_ms")
    if dato is None:
        dato = fila.get("opening_time_ms")
    if isinstance(dato, dict):
        if str(dato.get("decision") or "") in {"NO_OBSERVADO", "NO_APLICA"}:
            return (None, "sin_tiempo")
        valor = _positivo(dato.get("valor"))
        if valor is not None:
            return (valor, "legacy")
    else:
        valor = _positivo(dato)
        if valor is not None:
            return (valor, "legacy")
    return (None, "sin_dato")


def _positivo(valor) -> "float | None":
    try:
        numero = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return numero if numero > 0 else None


def _semaforo(valor: "float | None", criterio: dict) -> str:
    if valor is None:
        return "gris"
    estado, _valor, _motivo = evaluar_apertura(valor, criterio)
    return estado


def _leer_ground_truth(ruta: Path) -> list[dict]:
    texto = ruta.read_text(encoding="utf-8-sig")
    delimitador = ";" if texto.count(";") > texto.count(",") else ","
    filas = []
    for numero, fila in enumerate(csv.DictReader(texto.splitlines(),
                                                delimiter=delimitador), start=2):
        caso = str(fila.get("caso") or "").strip()
        if not caso:
            continue
        valor = _positivo(fila.get("tiempo_ms_humano"))
        if valor is None:
            raise ValueError(
                f"fila {numero}: 'tiempo_ms_humano' debe ser numérico y > 0")
        filas.append({"caso": caso, "tiempo_ms_humano": valor,
                      "nota": (fila.get("nota") or "").strip() or None,
                      "fila_csv": numero})
    if not filas:
        raise ValueError("el ground truth no contiene filas válidas")
    return filas


def validar(documento: dict, ground_truth: list[dict],
            tolerancia_ms: float = 1.0) -> dict:
    limites = criterios_o_predeterminados()
    # El motor del dashboard se alimenta del MISMO formato de reglas
    # (verde/amarillo/rojo como texto) que produce `reglas_apertura`.
    criterio = reglas_apertura(limites)
    filas = documento.get("resultados") if isinstance(documento, dict) else None
    filas = filas if isinstance(filas, list) else []
    indice: dict = {}
    for fila in filas:
        if isinstance(fila, dict):
            for clave in _claves_de_fila(fila):
                indice.setdefault(clave, fila)

    casos = []
    for objetivo in ground_truth:
        fila = indice.get(objetivo["caso"].casefold())
        humano = objetivo["tiempo_ms_humano"]
        registro = {
            "caso": objetivo["caso"], "nota": objetivo["nota"],
            "tiempo_ms_humano": humano,
            "semaforo_humano": _semaforo(humano, criterio),
            "encontrado": fila is not None,
        }
        if fila is None:
            registro.update({"tiempo_ms_detectado": None,
                             "estado_deteccion": "sin_caso",
                             "semaforo_detectado": "gris",
                             "delta_ms": None, "dentro_tolerancia": None})
            casos.append(registro)
            continue
        detectado, estado = _apertura_detectada(fila)
        registro.update({
            "tiempo_ms_detectado": detectado,
            "estado_deteccion": estado,
            "semaforo_detectado": _semaforo(detectado, criterio),
        })
        if detectado is None:
            registro.update({"delta_ms": None, "dentro_tolerancia": None})
        else:
            delta = round(detectado - humano, 3)
            registro.update({
                "delta_ms": delta,
                "delta_abs_ms": abs(delta),
                "dentro_tolerancia": abs(delta) <= float(tolerancia_ms),
            })
        registro["acuerdo_semaforo"] = (registro["semaforo_detectado"]
                                        == registro["semaforo_humano"])
        casos.append(registro)

    con_valor = [c for c in casos if c.get("delta_ms") is not None]
    deltas = [abs(c["delta_ms"]) for c in con_valor]
    acuerdos = [c for c in casos if c.get("acuerdo_semaforo") is not None]
    resumen = {
        "casos": len(casos),
        "encontrados": sum(1 for c in casos if c["encontrado"]),
        "con_valor_detectado": len(con_valor),
        "sin_valor": sum(1 for c in casos
                         if c["encontrado"] and c.get("delta_ms") is None),
        "sin_caso": sum(1 for c in casos if not c["encontrado"]),
        "mae_ms": round(statistics.fmean(deltas), 3) if deltas else None,
        "mediana_abs_ms": round(statistics.median(deltas), 3) if deltas else None,
        "max_abs_ms": round(max(deltas), 3) if deltas else None,
        "dentro_tolerancia": sum(1 for c in con_valor if c["dentro_tolerancia"]),
        "tolerancia_ms": float(tolerancia_ms),
        "acuerdo_semaforo": sum(1 for c in acuerdos if c["acuerdo_semaforo"]),
        "acuerdo_semaforo_pct": (round(100 * sum(1 for c in acuerdos
                                                if c["acuerdo_semaforo"])
                                      / len(acuerdos), 2) if acuerdos else None),
    }
    return {
        "herramienta": "validar_tmax_semaforo",
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "criterios_limites": limites,
        "criterio_apertura": criterio,
        "resumen": resumen,
        "casos": casos,
        "discrepancias": [c["caso"] for c in casos
                          if c.get("acuerdo_semaforo") is False],
    }


def _imprimir(reporte: dict) -> None:
    limites = reporte["criterios_limites"]
    criterio = reporte["criterio_apertura"]
    print(f"Criterio de apertura: verde {criterio.get('verde')} · "
          f"amarillo {criterio.get('amarillo')} · rojo {criterio.get('rojo')} "
          f"(verde_max={limites.get('verde_max')}, "
          f"amarillo_max={limites.get('amarillo_max')}, "
          f"origen {limites.get('origen')})")
    print(f"{'caso':<24}{'humano':>9}{'detectado':>11}{'Δ ms':>8}"
          f"{'semáforo':>18}{'ok':>5}")
    print("-" * 76)
    for caso in reporte["casos"]:
        detectado = caso.get("tiempo_ms_detectado")
        delta = caso.get("delta_ms")
        print(f"{caso['caso'][:23]:<24}{caso['tiempo_ms_humano']:>9.3f}"
              f"{(f'{detectado:.3f}' if detectado is not None else '—'):>11}"
              f"{(f'{delta:+.3f}' if delta is not None else '—'):>8}"
              f"{caso['semaforo_detectado'] + '/' + caso['semaforo_humano']:>18}"
              f"{('sí' if caso.get('acuerdo_semaforo') else 'NO' if caso.get('acuerdo_semaforo') is False else '—'):>5}")
    resumen = reporte["resumen"]
    print("-" * 76)
    print(f"casos={resumen['casos']} · con valor={resumen['con_valor_detectado']} "
          f"· sin valor={resumen['sin_valor']} · sin caso={resumen['sin_caso']}")
    print(f"MAE={resumen['mae_ms']} ms · mediana={resumen['mediana_abs_ms']} ms "
          f"· máx={resumen['max_abs_ms']} ms · dentro de "
          f"{resumen['tolerancia_ms']} ms: {resumen['dentro_tolerancia']}"
          f"/{resumen['con_valor_detectado']}")
    print(f"acuerdo de semáforo: {resumen['acuerdo_semaforo']}"
          f"/{len(reporte['casos']) - resumen['sin_caso']} "
          f"({resumen['acuerdo_semaforo_pct']}%)")
    if reporte["discrepancias"]:
        print("discrepancias de semáforo: " + ", ".join(reporte["discrepancias"]))


def main(argv: "list[str] | None" = None) -> int:
    analizador = argparse.ArgumentParser(
        description="Validación de Tmax/semáforo contra ground truth humano "
                    "(criterio §9-8 de la auditoría R15.6).")
    analizador.add_argument("--validacion", default="validacion_resultados.json")
    analizador.add_argument("--ground-truth", required=True)
    analizador.add_argument("--tolerancia-ms", type=float, default=1.0)
    analizador.add_argument("--salida", default="validacion_tmax_reporte.json")
    analizador.add_argument("--minimo-acuerdo", type=float, default=None,
                            help="Porcentaje mínimo de acuerdo de semáforo para "
                                 "salir con código 0 (p. ej. 90).")
    args = analizador.parse_args(argv)

    try:
        with open(args.validacion, encoding="utf-8") as fh:
            documento = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"No se pudo leer el documento {args.validacion}: {exc}",
              file=sys.stderr)
        return 2
    try:
        ground_truth = _leer_ground_truth(Path(args.ground_truth))
    except (OSError, ValueError) as exc:
        print(f"Ground truth inválido: {exc}", file=sys.stderr)
        return 2

    reporte = validar(documento, ground_truth, tolerancia_ms=args.tolerancia_ms)
    Path(args.salida).write_text(json.dumps(reporte, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    _imprimir(reporte)
    print(f"reporte: {args.salida}")
    if args.minimo_acuerdo is not None:
        valor = reporte["resumen"]["acuerdo_semaforo_pct"]
        if valor is None or valor < float(args.minimo_acuerdo):
            print(f"acuerdo de semáforo por debajo del mínimo "
                  f"({valor}% < {args.minimo_acuerdo}%)", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI
    raise SystemExit(main())
