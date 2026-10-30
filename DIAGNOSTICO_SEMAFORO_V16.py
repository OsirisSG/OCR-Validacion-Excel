# -*- coding: utf-8 -*-
"""Diagnostico V2 de solo lectura: no modifica archivos de V-Matrix.
Se ejecuta junto a DIAGNOSTICO_SEMAFORO_V16.bat en la raiz del proyecto.
"""
from __future__ import annotations
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime
from urllib.request import urlopen

EXPECTED = {
    'dashboard/backend/app.py': '3f628fd41a3aa70d11f68fa4d687a46fafaa7a9f4b79e236282afeadea243eff',
    'utilidades/matriz_apertura.py': 'dcba3b51bf161428ebecba99e2bb55eb92774235c6b6dd2c4638efe5bdd6e915',
    'utilidades/resultado_caso.py': '80af5dde9aa3c1116df820752e0033ab4b5845694b2be6dfc522ff1484dc73cb',
    'VERSION.txt': 'ac8df41b864690dfb4f4354ae01dbebd999e2524c84a231029b3018083a4b4ad',
}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, ValueError) as exc:
        return {'_error': str(exc)}


def _api(url):
    try:
        with urlopen(url, timeout=2) as r:
            return json.loads(r.read(15_000_000).decode('utf-8'))
    except Exception:
        return None


def _short(value):
    if isinstance(value, dict):
        value = value.get('valor', value.get('value', ''))
    if value is None:
        return '--'
    return re.sub(r'[\r\n]+', ' ', str(value))[:110]


def _codigo_fila(f, pos):
    return _short(f.get('test_number') or f.get('identificador') or f.get('id') or ('#'+str(pos)))


def _detalle_entrada(f):
    if not isinstance(f, dict):
        return {}
    r = f.get('resultado_caso_canonico') or {}
    ap = r.get('apertura') if isinstance(r, dict) else {}
    if not isinstance(ap, dict):
        ap = {}
    return ap


def _matriz_items(res):
    matriz = res.get('matriz_apertura') or {}
    if not isinstance(matriz, dict):
        return []
    out = []
    for etapa in matriz.get('etapas') or []:
        if not isinstance(etapa, dict):
            continue
        for col in etapa.get('columnas') or []:
            if isinstance(col, dict):
                out.extend(x for x in col.get('celdas', []) if isinstance(x, dict) and x.get('tipo') == 'caso')
    out.extend(x for x in matriz.get('sin_clasificar', []) if isinstance(x, dict))
    return out


def informe(raiz):
    l = []
    p = lambda s='': l.append(str(s))
    p('V-MATRIX | DIAGNOSTICO DE SEMAFORO Y VERSION (SOLO LECTURA)')
    p('Fecha: ' + datetime.now().isoformat(timespec='seconds'))
    p('Raiz detectada: ' + str(raiz))
    p('Archivo iniciar.py presente: ' + ('SI' if (raiz/'iniciar.py').is_file() else 'NO'))
    p('Backend app.py presente: ' + ('SI' if (raiz/'dashboard'/'backend'/'app.py').is_file() else 'NO'))
    p('El script no modifica V-Matrix ni datos de analisis.')
    p('')
    version = raiz / 'VERSION.txt'
    p('VERSION.txt: ' + (version.read_text(encoding='utf-8-sig',errors='replace').strip() if version.exists() else 'AUSENTE'))
    app = raiz / 'dashboard/backend/app.py'
    if app.exists():
        raw = app.read_text(encoding='utf-8-sig',errors='replace')
        m = re.search(r'^PATCH_BUILD\s*=\s*[\"\']([^\"\']+)',raw,re.MULTILINE)
        p('PATCH_BUILD en backend: ' + (m.group(1) if m else 'NO LOCALIZADO'))
    p('')
    p('INTEGRIDAD DE ARCHIVOS CLAVE COMPARADOS CON V16.0.1 ENTREGADA:')
    for name, hash_expected in EXPECTED.items():
        target = raiz / name
        if not target.exists():
            status = 'AUSENTE'
        else:
            status = 'COINCIDE' if hashlib.sha256(target.read_bytes()).hexdigest() == hash_expected else 'DISTINTO'
        p('  %s: %s' % (name, status))
    p('Una coincidencia de hash confirma archivo instalado, NO precisión del algoritmo.')
    p('')

    # El navegador usa por defecto el puerto 8000; el script consulta solo localhost.
    base = None
    salud = None
    for port in (8000, 8001, 8080, 8765):
        tentative = f'http://127.0.0.1:{port}'
        sal = _api(tentative + '/api/salud')
        if isinstance(sal, dict) and sal.get('patch_build'):
            salud = sal
            base = tentative
            break
    if base:
        p('BACKEND ACTIVO: ' + base)
        p('Version reportada por el proceso ACTIVO: ' + _short(salud.get('patch_build')))
        estado = _api(base+'/api/estado') or {}
        p('Resultado cargado: %s | total: %s | generado_en: %s' % (estado.get('hay_datos'), estado.get('total'), estado.get('generado_en')))
        res = _api(base+'/api/resumen')
        pruebas = _api(base+'/api/pruebas?limit=1000&offset=0&incluir_ocultos=true')
        if isinstance(res, dict):
            p('')
            p('RESUMEN ACTIVO:')
            p('  Total: %s | procesadas: %s | en_vivo: %s' % (res.get('total_carpetas'),res.get('total_procesadas'),res.get('resumen_en_vivo')))
            p('  Semaforo de apertura: %s' % json.dumps(res.get('semaforo_apertura') or {},ensure_ascii=False))
            p('  Calidad decision: %s' % json.dumps(res.get('calidad_decision_apertura') or {},ensure_ascii=False))
            matriz = _matriz_items(res)
            p('  Celdas de matriz: %s' % len(matriz))
        else:
            matriz = []
            p('No se pudo leer /api/resumen. Comprueba el registro de errores de la aplicación.')
        filas = pruebas.get('items') if isinstance(pruebas, dict) else None
        if isinstance(filas, list):
            p('')
            p('DETALLE POR PRUEBA (identificador, semaforo resumen, razon y estado):')
            causas = collections.Counter()
            por_id = {str(c.get('id')):c for c in matriz if c.get('id') is not None}
            diferencias = []
            for i, f in enumerate(filas, 1):
                ap = _detalle_entrada(f)
                color = _short(f.get('semaforo_apertura') or 'gris')
                motivo = _short(f.get('apertura_motivo'))
                decision = _short(ap.get('estado'))
                estado_tiempo = _short(ap.get('estado_tiempo'))
                causas[(color,motivo,decision)] += 1
                x = por_id.get(str(f.get('id')))
                color_matriz = _short(x.get('estado')) if x else '?'
                elegible = ap.get('auto_color_elegible') is True
                estimado = ap.get('tiempo_estimado_auto_ms')
                p('  %s: resumen=%s; matriz=%s; motivo=%s; decision=%s; tiempo=%s; auto_elegible=%s; estimado=%s; estado_tiempo=%s' % (
                    _codigo_fila(f,i),color,color_matriz,motivo,decision,_short(f.get('opening_time_ms')),
                    elegible,_short(estimado),estado_tiempo))
                if x and color_matriz != color:
                    diferencias.append(_codigo_fila(f,i))
                if elegible and color in {'gris','sin_clasificar'}:
                    p('    >>> REVISAR: evidencia elegible para color estimado, resumen se abstiene')
                if color in {'gris','sin_clasificar'}:
                    razones = ap.get('motivos') or []
                    if isinstance(razones, list):
                        p('    Razones de apertura: '+_short('; '.join(str(t) for t in razones[:5])))
            p('')
            p('DISTRIBUCION DE MOTIVOS:')
            for (col,mot,dec),count in sorted(causas.items()):
                p('  %d caso(s) %s / %s / %s' % (count,col,mot,dec))
            p('')
            p('DIFERENCIAS MATRIZ - RESUMEN: '+ (', '.join(diferencias) if diferencias else 'No detectadas en los items comparables'))
            if len(filas) >= 1000:
                p('ADVERTENCIA: solo se leyeron 1000 casos; hay que consultar otra pagina.')
        else:
            p('No se pudo leer /api/pruebas para explicar los grises.')
    else:
        p('No se detecto API V-Matrix activa en localhost:8000/8001/8080/8765.')
        p('Abre V-Matrix y ejecuta el BAT otra vez mientras el dashboard esté abierto.')
        ruta = raiz / 'validacion_resultados.json'
        if ruta.is_file():
            datos = _read_json(ruta)
            if isinstance(datos,dict) and isinstance(datos.get('resultados'),list):
                p('El archivo local contiene %d casos. Estados canónicos persistidos (podrían ser obsoletos):' %len(datos['resultados']))
                for i,f in enumerate(datos['resultados'],1):
                    ap=_detalle_entrada(f)
                    p('  %s: %s (%s)' %(_codigo_fila(f,i),_short(ap.get('estado')),_short('; '.join(ap.get('motivos') or [])[:150])))
    p('')
    p('Interpretacion: este diagnostico confirma causas y version, NO certifica precision del video.')
    return '\n'.join(l)+'\n'


def _detectar_raiz():
    # El BAT no pasa argumentos para evitar problemas de Windows con rutas
    # entrecomilladas que terminan en una barra invertida.
    origen = Path(__file__).resolve().parent
    candidatas = [origen, Path.cwd(), origen.parent]
    if len(sys.argv) > 1:
        candidatas.insert(0, Path(sys.argv[1].strip('\"')).expanduser())
    for c in candidatas:
        try:
            c = c.resolve()
            if (c/'iniciar.py').is_file() or (c/'dashboard'/'backend'/'app.py').is_file():
                return c
        except (OSError, ValueError):
            continue
    # Aun si faltan ambos archivos, generar un reporte de diagnostico,
    # en vez de decir erroneamente que el BAT esta mal colocado.
    return origen


def main():
    raiz = _detectar_raiz()
    print('Directorio de diagnostico: ' + str(raiz))
    if not (raiz/'dashboard'/'backend'/'app.py').is_file():
        print('AVISO: No se encontro dashboard\\backend\\app.py. Se generara el reporte de todos modos.')
    try:
        texto = informe(raiz)
        destino = Path(os.environ.get('TEMP') or tempfile.gettempdir()) / ('V_MATRIX_DIAGNOSTICO_COLORES_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.txt')
        destino.write_text(texto, encoding='utf-8')
    except Exception as exc:
        print('ERROR al crear informe: '+repr(exc))
        return 4
    print(texto)
    print('\nREPORTE GUARDADO EN: '+str(destino))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
