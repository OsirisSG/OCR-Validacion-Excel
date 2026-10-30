"""Diagnóstico de los casos grises y consistencia de clasificación por ejecución."""
from __future__ import annotations
from collections import Counter


def diagnosticar(filas: list[dict], *, criterio: dict | None = None) -> dict:
    """Devuelve estadísticas SIN cambiar resultados ni inferir tiempos faltantes."""
    total = 0
    por_motivo: Counter = Counter()
    por_estado: Counter = Counter()
    ids = set()
    duplicados = []
    sin_identidad = []
    casos = []
    for idx, fila in enumerate(filas):
        if not isinstance(fila, dict):
            continue
        total += 1
        k = (fila.get('project_id'), fila.get('id') or fila.get('case_key'))
        if k[1] is None:
            sin_identidad.append(idx)
        elif k in ids:
            duplicados.append({'indice':idx,'identidad':repr(k)})
        ids.add(k)
        motivo = str(fila.get('apertura_motivo') or fila.get('motivo_estado') or 'sin_diagnostico')
        estado = str(fila.get('semaforo_apertura') or fila.get('estado') or 'gris')
        por_estado[estado]+=1
        if estado == 'gris':
            por_motivo[motivo]+=1
            casos.append({'id': k[1], 'test_number': fila.get('test_number'),
                          'motivo':motivo,'tiempo_pendiente_ms':fila.get('opening_time_pendiente_ms')})
    return {'total_casos_entrada':total,'estados':dict(por_estado),
            'motivos_gris':dict(por_motivo),'casos_grises':casos,
            'identidades_duplicadas':duplicados,'casos_sin_id':sin_identidad,
            'publicacion_confiable':not duplicados and not sin_identidad}
