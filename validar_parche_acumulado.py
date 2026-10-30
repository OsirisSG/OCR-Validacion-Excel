#!/usr/bin/env python3
"""Validación rápida V15.10.1 R6 dentro de un árbol V-Matrix completo."""
from __future__ import annotations
import argparse, hashlib, importlib.util, math, subprocess, sys
from pathlib import Path


def run(cmd, cwd):
    print('>', ' '.join(cmd))
    env = dict(__import__('os').environ)
    env['PYTHONPATH'] = str(cwd) + (((';' if __import__('os').name == 'nt' else ':') + env['PYTHONPATH']) if env.get('PYTHONPATH') else '')
    p=subprocess.run(cmd,cwd=cwd,text=True,capture_output=True, env=env)
    if p.stdout: print(p.stdout.rstrip())
    if p.stderr: print(p.stderr.rstrip())
    return p.returncode


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('proyecto', nargs='?', default='.')
    ap.add_argument('--full', action='store_true', help='Ejecutar pytest/node completos además de las regresiones focalizadas')
    args=ap.parse_args()
    root=Path(args.proyecto).resolve()
    req=[
      'configuracion.py','flujo_empresarial.py','aprendizaje_video_airbag.py',
      'video_airbag.py','reporte_bmg.py','utilidades/resultado_caso.py',
      'utilidades/evidencia_apertura.py','utilidades/verificador_apertura.py','utilidades/politica_apertura.py','utilidades/sincronizacion_video.py',
      'utilidades/rutas_recursos.py','utilidades/identidad_excel_publicacion.py','utilidades/identidad_excel.py',
      'dashboard/backend/app.py','dashboard/frontend/app.js','dashboard/frontend/visor_precision.js',
      'dashboard/frontend/index.html','dashboard/frontend/estilos.css','dashboard/frontend/i18n.js',
      'dashboard/frontend/vendor/htm.umd.js']
    missing=[x for x in req if not (root/x).is_file()]
    if missing:
      print('FALTAN_DEPENDENCIAS_BASE:')
      for x in missing: print(' -',x)
      return 2
    vacios=[x for x in req if (root/x).is_file() and (root/x).stat().st_size == 0]
    if vacios:
      print('ARCHIVOS_VACIOS_INVALIDOS:')
      for x in vacios: print(' -',x)
      return 21
    html=(root/'dashboard/frontend/index.html').read_text(encoding='utf-8')
    if html.find('visor_precision.js') < 0 or html.find('app.js') < 0 or html.find('visor_precision.js') > html.find('app.js'):
      print('ERROR: visor_precision.js debe cargarse antes de app.js')
      return 3
    if '15.10.1-r6' not in html:
      print('ERROR: index.html no corresponde a R6')
      return 22
    app_text=(root/'dashboard/backend/app.py').read_text(encoding='utf-8')
    if 'PATCH_BUILD = "15.10.1-r6"' not in app_text:
      print('ERROR: backend no corresponde a R6')
      return 23

    sys.path.insert(0,str(root))
    from utilidades.resultado_caso import resolver_apertura
    cases=[-122.8,0,float('nan'),float('inf')]
    for value in cases:
      r=resolver_apertura({'campos':{'opening_time_ms':{'valor':value,'raw_time_ms':value,'estado':'confirmado_manual','fuente':'revision_manual','confirmacion_manual':True}}})
      if r.get('tiempo_ms') is not None or r.get('tiempo_propuesto_ms') is not None:
        print('ERROR_H5: tiempo inválido publicado:',value,r)
        return 4
    ok=resolver_apertura({'videos':[{'id':'cam1','revision_manual':{'estado':'confirmado','frame_index':11,'tiempo_ms':2.2,'referencia_tiempo_valida':True,'estado_tiempo':'VALIDO'}}]})
    if ok.get('tiempo_ms') != 2.2:
      print('ERROR_H5: tiempo positivo válido no conservado:',ok)
      return 5

    checks=[
      ([sys.executable,'-m','py_compile','video_airbag.py','reporte_bmg.py','dashboard/backend/app.py','utilidades/resultado_caso.py','utilidades/evidencia_apertura.py','utilidades/verificador_apertura.py','utilidades/politica_apertura.py','utilidades/sincronizacion_video.py'], 'compile'),
      (['node','--check','dashboard/frontend/visor_precision.js'],'node visor'),
      (['node','--check','dashboard/frontend/app.js'],'node app'),
      (['node','pruebas/test_estado_texto.cjs'],'estado texto'),
      ([sys.executable,'-m','pytest','-q',
        'pruebas/test_v15_10_1_h5_tiempos.py',
        'pruebas/test_v15_10_1_r3_rutas_imagenes.py',
        'pruebas/test_v15_10_1_r3_identidad_publicacion.py',
        'pruebas/test_v15_10_1_r4_apertura_dependencias.py'],'H5 + R6'),
      (['node','pruebas/test_v15_10_1_r3_frontend_imagenes.cjs'],'frontend imágenes R3'),
    ]
    failures=[]
    for cmd,name in checks:
      try: rc=run(cmd,root)
      except FileNotFoundError:
        print(f'OMITIDO {name}: herramienta no instalada')
        continue
      if rc: failures.append((name,rc))
    if args.full:
      try:
        rc=run([sys.executable,'-m','pytest','-q','pruebas'],root)
        if rc: failures.append(('pytest completo',rc))
      except FileNotFoundError: pass
      try:
        rc=run(['node','--test','pruebas/*.cjs'],root)
        if rc: failures.append(('node completo',rc))
      except FileNotFoundError: pass
    if failures:
      print('VALIDACION_CON_FALLOS:',failures)
      return 10
    print('VALIDACION_FOCALIZADA_R6_OK')
    print('Nota: esto no sustituye piloto con AVI/fotografías reales ni navegador real.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
