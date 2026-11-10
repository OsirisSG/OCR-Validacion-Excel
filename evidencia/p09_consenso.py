"""Medición del motor de consenso (P09) sobre las lecturas reales de los 10 casos.

Compara TRES formas de decidir, con la misma evidencia y el mismo libro de referencia:

  1. **V16.0.21** (lo que hay): lo que el Excel publicado dice.
  2. **P08**: forma obligatoria, corroboración de niveles y conflictos simétricos. No rescata
     nada: sólo deja de publicar.
  3. **P09 (consenso ponderado)**: decide desde cero con todas las lecturas, pesos por
     procedencia, reparación estructural y unanimidad en los niveles.

La evidencia sale de la hoja `Trazabilidad` del libro publicado (527 filas) más el nombre de
la carpeta de cada caso. El libro de referencia es `Book-10-Examples.xlsx`.

Uso: python3 evidencia/p09_consenso.py [--json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from evidencia.p08_replay_reglas import (CAMPOS, CANDIDATOS_LIBRO, LIBRO_RESULTADO,
                                         _norm, leer_evidencias, leer_libro,
                                         leer_publicado)
from utilidades.consenso_valores import consensuar

EQUIVALENCIAS = {"232550": "222550"}
# La carpeta de cada caso, tal como la escribió el usuario (de ahí salen test_number,
# temperatura, versión e inflador).
CARPETAS = {
    "222504": "222504 RDW NOM NT", "222509": "222509 RDW NOM NT",
    "222521": "222521 RDW OGL NT", "222530": "222530 RDW UGL NT",
    "252581": "252581 RDW NOM RT", "252590": "252590 RDW NOM RT",
    "232550": "232550 RDW NOM HT", "232561": "232561 RDW OGL HT",
    "232564": "232564 RDW OGL HT", "232566": "232566 RDW UGL HT",
}


def evidencias_de_carpeta(numero: str) -> list[dict]:
    """Convierte el nombre de la carpeta en evidencia, como hace el pipeline."""
    partes = (CARPETAS.get(numero) or "").split()
    if len(partes) < 4:
        return []
    return [
        {"clave": "test_number", "valor_normalizado": partes[0], "fuente": "ruta_carpeta",
         "imagen": None},
        {"clave": "module_version", "valor_normalizado": partes[1], "fuente": "ruta_carpeta",
         "imagen": None},
        {"clave": "inflator_type", "valor_normalizado": partes[2], "fuente": "ruta_carpeta",
         "imagen": None},
        {"clave": "temperature_condition", "valor_normalizado": partes[3],
         "fuente": "ruta_carpeta", "imagen": None},
    ]


def medir(numero: str, evidencias: list[dict], libro: dict, publicado: dict) -> dict:
    """Devuelve, por campo, lo que publica cada una de las tres formas."""
    fila = {}
    for campo in CAMPOS:
        del_campo = [e for e in evidencias if e["clave"] == campo]
        decision = consensuar(campo, del_campo)
        fila[campo] = {
            "libro": (libro.get(campo) or "").strip(),
            "v16": (publicado.get(campo) or "").strip(),
            "p09": decision["valor"] or "",
            "p09_estado": decision["estado"],
            "p09_motivo": decision["motivo"],
            "p09_opciones": decision["opciones"][:3],
        }
    return fila


def puntuar(filas: dict, clave_columna: str) -> dict:
    publicados = correctos = 0
    errores = []
    for numero, fila in filas.items():
        for campo, dato in fila.items():
            valor = (dato.get(clave_columna) or "").strip()
            if not valor:
                continue
            publicados += 1
            if dato["libro"] and _norm(valor) == _norm(dato["libro"]):
                correctos += 1
            else:
                errores.append({"caso": numero, "campo": campo, "publicado": valor,
                                "libro": dato["libro"]})
    return {"publicados": publicados, "correctos": correctos,
            "errores": errores,
            "precision": round(100 * correctos / publicados, 1) if publicados else 0.0}


def main(argv: list[str] | None = None) -> int:
    referencia = next((r for r in CANDIDATOS_LIBRO if r.is_file()), None)
    if referencia is None:
        raise SystemExit("No encuentro Book-10-Examples.xlsx para comparar")
    evidencias = leer_evidencias(LIBRO_RESULTADO)
    libro_por_numero = leer_libro(referencia)
    publicado_por_numero = leer_publicado(LIBRO_RESULTADO)

    filas = {}
    for numero_libro in sorted(libro_por_numero):
        clave_caso = next((a for a, real in EQUIVALENCIAS.items() if real == numero_libro),
                          numero_libro)
        clave_publicado = clave_caso if clave_caso in publicado_por_numero else numero_libro
        todas = [*evidencias_de_carpeta(clave_caso), *evidencias.get(clave_caso, [])]
        filas[numero_libro] = medir(numero_libro, todas, libro_por_numero[numero_libro],
                                    publicado_por_numero.get(clave_publicado, {}))

    informe = {
        "celdas": len(filas) * len(CAMPOS),
        "v16": puntuar(filas, "v16"),
        "p09": puntuar(filas, "p09"),
    }
    if "--json" in (argv or sys.argv[1:]):
        print(json.dumps(informe, ensure_ascii=False, indent=2))
        return 0

    print("=" * 80)
    print(" MOTOR DE CONSENSO PONDERADO (P09) SOBRE LAS LECTURAS REALES · 10 CASOS")
    print("=" * 80)
    for etiqueta, clave in (("V16.0.21 (lo publicado)", "v16"), ("P09 (consenso)", "p09")):
        datos = informe[clave]
        cobertura = 100 * datos["publicados"] / informe["celdas"]
        print(f" {etiqueta:<26} publicados {datos['publicados']:3d} ({cobertura:.0f} % de las "
              f"celdas) · correctos {datos['correctos']:3d} · "
              f"MALOS {len(datos['errores']):2d} · precisión {datos['precision']:.1f} %")
    print("-" * 80)
    print(" Errores de P09:")
    for error in informe["p09"]["errores"]:
        print(f"   {error['caso']} {error['campo']:<26} publicó {error['publicado']:<16}"
              f" libro {error['libro'] or '—'}")
    print("-" * 80)
    print(" Lo que P09 publica y V16.0.21 no (rescates):")
    for numero, fila in filas.items():
        for campo, dato in fila.items():
            if dato["p09"] and not dato["v16"]:
                acierta = dato["libro"] and _norm(dato["p09"]) == _norm(dato["libro"])
                marca = "OK " if acierta else "NO "
                extra = f" [{dato['p09_estado']}]" if dato["p09_estado"] != "consenso" else ""
                print(f"   {marca}{numero} {campo:<26} {dato['p09']:<18}"
                      f" libro {dato['libro'] or '—':<18}{extra}")
    print("-" * 80)
    print(" Lo que V16.0.21 publicó y P09 deja en blanco (a consulta):")
    for numero, fila in filas.items():
        for campo, dato in fila.items():
            if dato["v16"] and not dato["p09"]:
                acierta = dato["libro"] and _norm(dato["v16"]) == _norm(dato["libro"])
                marca = "era correcto" if acierta else "era ERROR"
                print(f"   {numero} {campo:<26} {dato['v16']:<18} ({marca})"
                      f" → {dato['p09_estado']}: {dato['p09_motivo'][:70]}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
