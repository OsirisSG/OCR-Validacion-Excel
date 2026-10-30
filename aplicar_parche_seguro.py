#!/usr/bin/env python3
"""Instalador verificable V-Matrix V15.10.1 R6.

Copia únicamente los archivos del manifiesto, crea respaldo de los reemplazados,
verifica hashes EN DESTINO y comprueba que Python resuelva los módulos críticos
desde el árbol indicado. No borra .aprendizaje, .agents ni AGENTS.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROHIBIDOS = ('.aprendizaje', '.agents')
PROHIBIDOS_EXACTOS = {'AGENTS.md'}
MANIFEST = 'MANIFEST_SHA256_ACUMULADO.txt'
PATCH_BUILD = '15.10.1-r6'
CRITICOS = [
    'video_airbag.py',
    'utilidades/verificador_apertura.py',
    'utilidades/politica_apertura.py',
    'utilidades/sincronizacion_video.py',
    'utilidades/evidencia_apertura.py',
    'utilidades/matriz_apertura.py',
    'utilidades/resultado_caso.py',
    'dashboard/backend/app.py',
    'dashboard/frontend/index.html',
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def ruta_segura(rel: str) -> bool:
    p = Path(rel)
    if p.is_absolute() or '..' in p.parts:
        return False
    if rel in PROHIBIDOS_EXACTOS:
        return False
    return not any(p.parts and p.parts[0] == x for x in PROHIBIDOS)


def leer_manifest(pkg: Path):
    manifest = pkg / MANIFEST
    if not manifest.is_file():
        raise RuntimeError(f'No se encontró {MANIFEST} junto al instalador. Extrae TODO el ZIP antes de ejecutar.')
    items=[]
    for line in manifest.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        digest, rel = line.split(None, 1)
        rel = rel.strip().lstrip('*')
        if not ruta_segura(rel):
            raise RuntimeError(f'Ruta prohibida en manifiesto: {rel}')
        src = pkg / rel
        if not src.is_file():
            raise RuntimeError(f'Falta archivo del paquete: {rel}. Extrae el ZIP completo.')
        got = sha256(src)
        if got.lower() != digest.lower():
            raise RuntimeError(f'Hash incorrecto en paquete: {rel}\n esperado={digest}\n obtenido={got}')
        items.append((rel, src, digest.lower()))
    return items


def verificar_destino(proyecto: Path, items) -> list[str]:
    errores=[]
    mapa={rel:digest for rel,_,digest in items}
    for rel in CRITICOS:
        dst=proyecto/rel
        if not dst.is_file():
            errores.append(f'NO_EXISTE: {rel}')
            continue
        if dst.stat().st_size <= 0:
            errores.append(f'VACIO: {rel}')
            continue
        esperado=mapa.get(rel)
        if esperado and sha256(dst).lower()!=esperado:
            errores.append(f'HASH_DESTINO_DISTINTO: {rel}')
    return errores


def diagnostico_resolucion(proyecto: Path) -> tuple[int,str]:
    codigo = r'''
import importlib.util, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
mods = ['video_airbag','utilidades.verificador_apertura','utilidades.politica_apertura','utilidades.sincronizacion_video']
out = {}
for name in mods:
    spec = importlib.util.find_spec(name)
    out[name] = None if spec is None else str(pathlib.Path(spec.origin).resolve()) if spec.origin else str(spec.submodule_search_locations)
print(json.dumps(out, ensure_ascii=False))
for name, origin in out.items():
    if not origin:
        raise SystemExit(31)
    if str(root).casefold() not in str(origin).casefold():
        raise SystemExit(32)
'''
    p=subprocess.run([sys.executable,'-c',codigo,str(proyecto)],cwd=proyecto,text=True,capture_output=True)
    salida=(p.stdout or '') + (('\n'+p.stderr) if p.stderr else '')
    return p.returncode, salida.strip()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('proyecto', nargs='?', default=(r'C:\Programas Base\OCR-Validacion-Excel-ocr-gpu-produccion' if os.name=='nt' else '.'))
    args=ap.parse_args()
    pkg=Path(__file__).resolve().parent
    proyecto=Path(args.proyecto).expanduser().resolve()
    if not proyecto.is_dir():
        raise SystemExit(f'No existe la carpeta del proyecto: {proyecto}')

    requeridos_base=[
        'configuracion.py','flujo_empresarial.py','aprendizaje_video_airbag.py',
        'dashboard/frontend/estilos.css','dashboard/frontend/i18n.js',
        'dashboard/frontend/vendor/htm.umd.js',
    ]
    faltan=[r for r in requeridos_base if not (proyecto/r).is_file()]
    if faltan:
        print('BASE INCOMPLETA. No se modificó nada.')
        for r in faltan: print('  -',r)
        return 2

    items=leer_manifest(pkg)
    sello=datetime.now().strftime('%Y%m%d_%H%M%S')
    backup=proyecto.parent/f'{proyecto.name}_BACKUP_V15_10_1_R6_{sello}'
    creados=[]; reemplazados=[]

    # Copia explícita, no sincronización destructiva.
    for rel,src,_digest in items:
        dst=proyecto/rel
        if dst.exists():
            b=backup/rel
            b.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(dst,b)
            reemplazados.append(rel)
        else:
            creados.append(rel)
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)

    backup.mkdir(parents=True,exist_ok=True)
    (backup/'CREADOS_POR_PARche.txt').write_text('\n'.join(creados)+'\n',encoding='utf-8')
    (backup/'REEMPLAZADOS_POR_PARche.txt').write_text('\n'.join(reemplazados)+'\n',encoding='utf-8')

    errores=verificar_destino(proyecto,items)
    if errores:
        print('ERROR_POSTCOPIA: los archivos del destino NO coinciden con R6:')
        for e in errores: print('  -',e)
        print('Backup:',backup)
        return 12

    rc,salida=diagnostico_resolucion(proyecto)
    print('Resolución Python:')
    print(salida or '(sin salida)')
    if rc:
        print('ERROR_RESOLUCION_PYTHON: Python no está resolviendo los módulos desde el árbol parcheado.')
        print('Cierra completamente el servidor/dashboard y revisa si estás lanzando otra copia del proyecto.')
        print('Backup:',backup)
        return rc

    marca={
        'patch_build': PATCH_BUILD,
        'instalado_en': datetime.now().isoformat(timespec='seconds'),
        'proyecto': str(proyecto),
        'python': sys.executable,
        'criticos': {rel: sha256(proyecto/rel) for rel in CRITICOS if (proyecto/rel).is_file()},
    }
    (proyecto/'PATCH_INSTALLED_V15_10_1_R6.json').write_text(json.dumps(marca,ensure_ascii=False,indent=2),encoding='utf-8')

    print('\nPARCHE_R6_APLICADO_Y_VERIFICADO_OK')
    print('Proyecto:',proyecto)
    print('Backup:',backup)
    print('IMPORTANTE: cierra cualquier ventana CMD/PowerShell que siga ejecutando el dashboard y vuelve a iniciarlo.')
    print(f'Después abre /api/estado y confirma: "patch_build": "{PATCH_BUILD}"')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
