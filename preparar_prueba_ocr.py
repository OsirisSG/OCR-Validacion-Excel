"""Respaldo y reinicio recuperable del progreso; nunca elimina aprendizaje.

python preparar_prueba_ocr.py             # solo informa
python preparar_prueba_ocr.py --preparar  # con el servidor cerrado
"""
import argparse
import json
import shutil
import socket
import sqlite3
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from configuracion import cargar_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparar', action='store_true')
    parser.add_argument('--puerto', type=int, default=8000)
    args = parser.parse_args()
    raiz = Path(__file__).resolve().parent
    config = cargar_config()
    def local(nombre):
        ruta = (raiz / nombre).resolve()
        if not ruta.is_relative_to(raiz):
            raise ValueError(f'La ruta está fuera del proyecto: {ruta}. Haz un respaldo manual.')
        return ruta
    aprendizaje = local(config.get('aprendizaje', {}).get('directorio', '.aprendizaje'))
    avances = local(config.get('empresarial', {}).get('archivo_avance_ids', '.cache_ocr/avances_ids.json'))
    checkpoint = local('.cache_ocr/estado_pipeline.json')
    conocimientos = local(config.get('empresarial', {}).get('base_conocimiento', 'base_conocimiento.json'))
    progreso = [p for p in (checkpoint, avances) if p.is_file()]
    fuentes = [p for p in (raiz/'validacion_resultados.json', raiz/'estructura_detectada.json',
                           conocimientos, raiz/'config.yaml', *progreso) if p.is_file()]
    if aprendizaje.is_dir():
        fuentes.extend(p for p in aprendizaje.rglob('*') if p.is_file())
    fuentes.extend(raiz.glob('*.xlsx'))
    fuentes = list(dict.fromkeys(fuentes))
    print('Aprendizaje que se conservará:', aprendizaje)
    print('Archivos para respaldo:', len(fuentes))
    print('Progreso que se archivará:', ', '.join(str(p.relative_to(raiz)) for p in progreso) or 'ninguno')
    if not args.preparar:
        print('Solo diagnóstico. Cierra el servidor y usa --preparar para crear el respaldo y archivar el progreso.')
        return
    with socket.socket() as conexion:
        conexion.settimeout(1)
        if conexion.connect_ex(('127.0.0.1', args.puerto)) == 0:
            raise RuntimeError('El servidor sigue abierto. Detén el OCR conservando el avance y cierra el servidor.')
    cola = raiz/'.cache_ocr/cola_excel.sqlite3'
    if cola.is_file():
        with sqlite3.connect(cola.as_uri()+'?mode=ro', uri=True) as con:
            fila = con.execute('SELECT solicitada,completada FROM cola WHERE id=1').fetchone()
        if fila and fila[0] > fila[1]:
            raise RuntimeError('Hay Excel pendientes. Abre el servidor, espera a que termine la cola y vuelve a cerrarlo.')
    carpeta = raiz/'respaldos_pruebas'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    carpeta.mkdir(parents=True, exist_ok=False)
    archivo = carpeta/'antes_de_prueba.zip'
    with ZipFile(archivo, 'x', ZIP_DEFLATED) as z:
        for fuente in fuentes:
            z.write(fuente, fuente.relative_to(raiz).as_posix())
    with ZipFile(archivo) as z:
        if z.testzip() is not None:
            raise RuntimeError('Falló la comprobación del respaldo. No se modificó el progreso.')
    for fuente in progreso:
        destino = carpeta/'progreso_anterior'/fuente.relative_to(raiz)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(fuente), str(destino))
    print('Respaldo comprobado:', archivo)
    print('Progreso archivado, no eliminado. Aprendizaje y caché OCR conservados.')
    print('Inicia el servidor y elige un procesamiento COMPLETO de tus carpetas de prueba, no Reanudar.')
    print('Usa un nombre nuevo para el Excel. No hay entrenamiento automático.')


if __name__ == '__main__':
    main()
