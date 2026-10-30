"""Auditoría READ-ONLY de copia coherente SQLite; ninguna reparación automática."""
from __future__ import annotations
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

VERSION = "15.10.1"


def sha256_archivo(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fd:
        for chunk in iter(lambda:fd.read(2**20),b''):
            h.update(chunk)
    return h.hexdigest()


def auditar(carpeta: str | Path) -> dict:
    ruta = Path(carpeta).resolve()
    if not ruta.is_dir():
        raise FileNotFoundError(ruta)
    archivos = sorted(x for x in ruta.rglob('*') if x.is_file() and not x.is_symlink())
    resultado = {"auditor":"vmatrix_v1510_readonly","version":VERSION,
                 "ruta_analizada":str(ruta),"archivos":[],"sqlite":[],"advertencias":[]}
    for p in archivos:
        rel=str(p.relative_to(ruta))
        resultado["archivos"].append({"ruta_relativa":rel,"bytes":p.stat().st_size,
                                      "sha256":sha256_archivo(p)})
        if p.name.endswith(('.sqlite3','.sqlite','.db')):
            report={"ruta_relativa":rel,"tablas":[],"integridad":None}
            # mode=ro NO crea ni actualiza WAL ni archivos de producción.
            # Si hay WAL vivo, se recomienda detener el proceso antes de copiar.
            uri=p.as_uri()+'?mode=ro'
            try:
                con=sqlite3.connect(uri,uri=True,timeout=1)
                try:
                    report["integridad"]=con.execute('PRAGMA integrity_check').fetchone()[0]
                    tablas=con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
                    for (t,) in tablas:
                        quoted='"'+t.replace('"','""')+'"'
                        try: n=con.execute(f'SELECT COUNT(*) FROM {quoted}').fetchone()[0]
                        except sqlite3.Error: n=None
                        report['tablas'].append({"tabla":t,"registros":n})
                finally: con.close()
            except sqlite3.Error as exc:
                report['error_lectura']=str(exc)
                resultado['advertencias'].append(f'{rel}: SQLite no evaluable')
            resultado['sqlite'].append(report)
    if not resultado['sqlite']:
        resultado['advertencias'].append('No se encontró SQLite: la carpeta puede estar incompleta')
    return resultado


def main():
    pa=argparse.ArgumentParser()
    pa.add_argument('carpeta',help='Copia local de .aprendizaje, no el original activo')
    pa.add_argument('--salida',help='Archivo JSON de diagnóstico FUERA de .aprendizaje')
    a=pa.parse_args()
    r=auditar(a.carpeta)
    data=json.dumps(r,indent=2,ensure_ascii=False)
    if a.salida:
        p=Path(a.salida).resolve()
        if p.is_relative_to(Path(a.carpeta).resolve()):
            pa.error('La salida no puede estar dentro de .aprendizaje')
        p.write_text(data,encoding='utf-8')
    print(data)

if __name__=='__main__':
    main()
