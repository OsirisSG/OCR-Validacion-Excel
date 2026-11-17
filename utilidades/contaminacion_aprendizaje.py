"""P47 · Revisión de SOLO LECTURA de lo que puede «contaminar» una corrida.

Qué mira (sin modificar nada):

* `imagenes_sin_datos`: cada fila hace que esa foto (por huella del archivo) NO pase por OCR.
  Las que no tienen motivo son sospechosas: no dicen por qué se marcaron.
* `regiones_no_texto`: descartes por región (por huella). Si el texto descartado parece un dato
  del libro (fecha, ZRZ, 2GJ, N/P, serie), el descarte tapa justo lo que buscamos.
* `correcciones_texto` / `anotaciones_regiones`: se cuentan, no se juzgan (son decisiones humanas).
* `.cache_ocr`: archivos parciales o temporales de corridas anteriores (`*.tmp`, parcial de
  validación, estado del pipeline pausado) y su fecha.
* Raíces de ejecución registradas: si la base mezcla corridas de carpetas distintas.

Uso:
    python -m utilidades.contaminacion_aprendizaje --proyecto "C:\\...\\proyecto" [--salida carpeta]

Las políticas que decide la corrida están en `config.yaml › aprendizaje.imagenes_sin_datos` y
`aprendizaje.regiones_no_texto` (P47). Este informe dice cuántas filas afecta cada una.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

PATRONES_DATO = (
    re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b"),            # fecha dd.mm.aa
    re.compile(r"\b20\d{2}[./-]\d{1,2}[./-]\d{1,2}\b"),             # fecha aaaa-mm-dd
    re.compile(r"\bZRZ\b|\bZRZ\s*\d", re.I),                       # nivel del módulo
    re.compile(r"\b2GJ\b|2GJ[\s.]*\d{3}", re.I),                    # número de parte VW
    re.compile(r"\bN\s*/\s*P\b", re.I),
    re.compile(r"\b\d{3}\s?[0-9A-Z]{10,}\b"),                       # serie del tablero
    re.compile(r"\bAUTOLIV\b|\bAIRBAG\b|\bPROTOTYPE", re.I),
)


def parece_dato(texto) -> bool:
    """¿El texto de un descarte «no es texto» parece un dato del libro?"""
    t = str(texto or "").strip()
    if len(t) < 2:
        return False
    return any(p.search(t) for p in PATRONES_DATO)


def _tablas(con) -> set[str]:
    return {f[0] for f in con.execute("select name from sqlite_master where type='table'")}


def _columnas(con, tabla) -> set[str]:
    return {f[1] for f in con.execute(f"pragma table_info({tabla})")}


def auditar_base(ruta_db: Path, tope: int = 15) -> dict:
    if not ruta_db.is_file():
        return {"existe": False, "ruta": str(ruta_db)}
    # Se lee una COPIA (con su -wal si existe): abrir en solo lectura una base WAL que el
    # dashboard tiene abierta puede fallar o, peor, tocar el -shm del original.
    import shutil
    import tempfile
    temporal = Path(tempfile.mkdtemp(prefix="revision_aprendizaje_"))
    copia = temporal / ruta_db.name
    shutil.copy2(ruta_db, copia)
    for sufijo in ("-wal",):
        extra = ruta_db.with_name(ruta_db.name + sufijo)
        if extra.is_file():
            shutil.copy2(extra, temporal / extra.name)
    try:
        return _auditar_copia(ruta_db, copia, tope)
    finally:
        shutil.rmtree(temporal, ignore_errors=True)


def _auditar_copia(ruta_db: Path, copia: Path, tope: int) -> dict:
    con = sqlite3.connect(str(copia))
    con.row_factory = sqlite3.Row
    tablas = _tablas(con)
    informe: dict = {"existe": True, "ruta": str(ruta_db),
                     "tamano_mb": round(ruta_db.stat().st_size / 1e6, 1),
                     "modificado": time.strftime("%Y-%m-%d %H:%M", time.localtime(ruta_db.stat().st_mtime))}
    if "imagenes_sin_datos" in tablas:
        filas = [dict(f) for f in con.execute("select * from imagenes_sin_datos")]
        sin_motivo = [f for f in filas if not str(f.get("motivo") or "").strip()]
        informe["imagenes_sin_datos"] = {
            "total": len(filas), "sin_motivo": len(sin_motivo),
            "sin_motivo_por_caso": dict(Counter(str(f.get("caso_id")) for f in sin_motivo).most_common()),
            "ejemplos_sin_motivo": [str(f.get("ruta_imagen"))[-120:] for f in sin_motivo[:tope]],
            "efecto": "cada fila hace que la foto NO pase por OCR (con P47 por defecto solo las que tienen motivo)"}
    if "regiones_no_texto" in tablas:
        cols = _columnas(con, "regiones_no_texto")
        filas = [dict(f) for f in con.execute("select * from regiones_no_texto order by id desc")]
        vigentes: dict = {}
        for f in filas:
            vigentes.setdefault((f.get("imagen_hash"), f.get("bbox_json")), f)
        activas = [f for f in vigentes.values() if ("activo" not in cols) or f.get("activo")]
        sospechosas = [f for f in activas if parece_dato(f.get("texto_ocr"))]
        informe["regiones_no_texto"] = {
            "total_filas": len(filas), "activas": len(activas),
            "activas_que_parecen_dato": len(sospechosas),
            "ejemplos": [{"id": f.get("id"), "texto": str(f.get("texto_ocr") or "")[:60],
                          "usuario": f.get("usuario"), "fecha": f.get("actualizado_en")}
                         for f in sospechosas[:tope]],
            "efecto": "borran esa región del OCR de esa foto (con P47 por defecto no se aplican las que parecen dato)"}
    for tabla in ("correcciones_texto", "anotaciones_regiones", "observaciones"):
        if tabla in tablas:
            informe.setdefault("conteos", {})[tabla] = con.execute(f"select count(*) from {tabla}").fetchone()[0]
    if "ejecuciones" in tablas:
        cols = _columnas(con, "ejecuciones")
        col = next((c for c in ("raiz", "ruta_raiz", "ruta", "carpeta") if c in cols), None)
        if col:
            informe["raices_de_ejecucion"] = dict(Counter(
                str(f[0]) for f in con.execute(f"select {col} from ejecuciones")).most_common(10))
    con.close()
    return informe


def auditar_cache(dir_cache: Path) -> dict:
    if not dir_cache.is_dir():
        return {"existe": False, "ruta": str(dir_cache)}
    archivos = []
    for f in sorted(dir_cache.iterdir()):
        if not f.is_file():
            continue
        nota = ""
        if f.suffix == ".tmp":
            nota = "temporal huérfano de una escritura interrumpida (no se usa; se puede mover)"
        elif f.name == "validacion_excel_parcial.json":
            nota = "parcial de validación: una corrida reanudada lo reutiliza"
        elif f.name == "estado_pipeline.json":
            try:
                estado = json.loads(f.read_text(encoding="utf-8"))
                nota = f"estado={estado.get('estado')} ruta={estado.get('ruta')}"
            except (OSError, ValueError):
                nota = "ilegible"
        elif f.name == "imagenes.sqlite3":
            nota = "caché OCR por foto + configuración: legítima, acelera repeticiones"
        archivos.append({"archivo": f.name, "mb": round(f.stat().st_size / 1e6, 1),
                         "modificado": time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime)),
                         "nota": nota})
    return {"existe": True, "ruta": str(dir_cache), "archivos": archivos}


def politicas(proyecto: Path) -> dict:
    ruta = proyecto / "config.yaml"
    try:
        import yaml
        cfg = (yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}).get("aprendizaje") or {}
    except Exception:                                      # noqa: BLE001
        cfg = {}
    return {"imagenes_sin_datos": cfg.get("imagenes_sin_datos", "(sin clave: P47 no instalado o valor por defecto)"),
            "regiones_no_texto": cfg.get("regiones_no_texto", "(sin clave: P47 no instalado o valor por defecto)")}


def auditar(proyecto: Path) -> dict:
    return {"proyecto": str(proyecto), "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
            "politicas_config": politicas(proyecto),
            "base_aprendizaje": auditar_base(proyecto / ".aprendizaje" / "aprendizaje.sqlite3"),
            "cache_ocr": auditar_cache(proyecto / ".cache_ocr")}


def texto(informe: dict) -> str:
    l = [f"Revisión de aprendizaje y caché · {informe['proyecto']} · {informe['fecha']}", ""]
    p = informe["politicas_config"]
    l.append(f"Políticas: imagenes_sin_datos={p['imagenes_sin_datos']} · regiones_no_texto={p['regiones_no_texto']}")
    b = informe["base_aprendizaje"]
    if not b.get("existe"):
        l.append(f"Base de aprendizaje: no existe ({b['ruta']})")
    else:
        l.append(f"Base: {b['ruta']} ({b['tamano_mb']} MB, {b['modificado']})")
        s = b.get("imagenes_sin_datos")
        if s:
            l.append(f"- Fotos marcadas «sin datos» (saltan OCR): {s['total']}; SIN motivo: {s['sin_motivo']}")
            for caso, n in list(s["sin_motivo_por_caso"].items())[:10]:
                l.append(f"    caso {caso}: {n}")
        r = b.get("regiones_no_texto")
        if r:
            l.append(f"- Descartes de región activos: {r['activas']}; parecen DATO: {r['activas_que_parecen_dato']}")
            for e in r["ejemplos"]:
                l.append(f"    id {e['id']}: «{e['texto']}» ({e['usuario']}, {e['fecha']})")
        for k, v in (b.get("conteos") or {}).items():
            nota = "decisiones humanas: no se tocan" if k != "observaciones" else "historial de lecturas OCR"
            l.append(f"- {k}: {v} ({nota})")
        if b.get("raices_de_ejecucion"):
            l.append("- Carpetas raíz de corridas registradas: " +
                     "; ".join(f"{k} ({v})" for k, v in b["raices_de_ejecucion"].items()))
    c = informe["cache_ocr"]
    if c.get("existe"):
        l.append(f"Caché: {c['ruta']}")
        for a in c["archivos"]:
            l.append(f"- {a['archivo']}: {a['mb']} MB, {a['modificado']} {('· ' + a['nota']) if a['nota'] else ''}")
    l.append("")
    l.append("Nada de esto se modificó. Para decidir qué se usa en la corrida: config.yaml › aprendizaje.")
    return "\n".join(l)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--proyecto", required=True)
    ap.add_argument("--salida", default="")
    a = ap.parse_args(argv)
    proyecto = Path(a.proyecto.strip().strip('"'))
    informe = auditar(proyecto)
    print(texto(informe))
    if a.salida:
        destino = Path(a.salida.strip().strip('"'))
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "revision_aprendizaje.json").write_text(
            json.dumps(informe, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        (destino / "revision_aprendizaje.txt").write_text(texto(informe), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
