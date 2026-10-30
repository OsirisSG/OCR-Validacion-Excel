"""Evaluación ciega por caso, NO por frame ni cámara.

JSONL: {case_key, split, referencia_frame, prediccion_frame,
        etiqueta_evento, predice_evento, camara}. Los splits son FIJOS;
no se optimiza ninguna política con datos de test_sellado.
"""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from pathlib import Path

SPLITS={'train','dev','test_sellado'}


def percentil(v, q):
    v=sorted(v)
    return v[min(len(v)-1,max(0,round((len(v)-1)*q)))] if v else None


def evaluar(registros: list[dict]) -> dict:
    por_split=defaultdict(list)
    grupos=defaultdict(set)
    incidencias=[]
    for i,r in enumerate(registros):
        try:
            k=str(r['case_key']); split=str(r['split'])
            if not k or split not in SPLITS:raise ValueError('split/caso inválido')
            por_split[split].append(r)
            grupos[k].add(split)
        except (KeyError,TypeError,ValueError) as e:
            incidencias.append({'fila':i,'motivo':str(e)})
    fuga={k:sorted(v) for k,v in grupos.items() if len(v)>1}
    if fuga:
        return {'valido':False,'bloqueo':'fuga_de_casos_entre_splits',
                'casos':fuga,'incidencias':incidencias}
    salida={'valido':not incidencias,'incidencias':incidencias,'splits':{}}
    for split,items in sorted(por_split.items()):
        # Múltiples cámaras de un caso nunca cuentan como ensayos independientes.
        por_caso=defaultdict(list)
        for r in items:por_caso[str(r['case_key'])].append(r)
        absolutos=[]; falsos_pos=0; falsos_neg=0; coincidencia=0; evaluables=0
        for case,rows in por_caso.items():
            truth={r.get('etiqueta_evento') for r in rows}
            if len(truth)!=1 or None in truth:
                incidencias.append({'caso':case,'motivo':'etiquetas_incompatibles'});continue
            if truth=={False}:
                if any(r.get('predice_evento') is True for r in rows):falsos_pos+=1
                continue
            predicciones=[r.get('prediccion_frame') for r in rows if r.get('prediccion_frame') is not None]
            ref={r.get('referencia_frame') for r in rows}
            if len(ref)!=1 or None in ref:
                incidencias.append({'caso':case,'motivo':'referencia_ambigua'});continue
            if not predicciones:
                falsos_neg+=1;continue
            # Evaluación por caso: un único resultado compartido, no 4 votos.
            pred=max(set(predicciones),key=predicciones.count)
            try: err=float(pred)-float(next(iter(ref)))
            except (TypeError,ValueError):
                incidencias.append({'caso':case,'motivo':'frame_no_numerico'});continue
            evaluables+=1; absolutos.append(abs(err))
            coincidencia+=int(abs(err)<=1)
        salida['splits'][split]={'casos':len(por_caso),'evaluables':evaluables,
                                 'error_abs_mediana_frames':percentil(absolutos,.5),
                                 'error_abs_p95_frames':percentil(absolutos,.95),
                                 'coincidencia_mas_menos_1_frame':coincidencia/evaluables if evaluables else None,
                                 'falsos_eventos':falsos_pos,'eventos_no_detectados':falsos_neg}
    if incidencias:salida['valido']=False
    return salida


def main():
    p=argparse.ArgumentParser()
    p.add_argument('anotaciones',help='Archivo JSONL con referencias humanas aprobadas')
    p.add_argument('--salida',help='Informe JSON distinto del dataset')
    a=p.parse_args()
    arr=[json.loads(t) for t in Path(a.anotaciones).read_text(encoding='utf-8').splitlines() if t.strip()]
    result=evaluar(arr)
    contenido=json.dumps(result,ensure_ascii=False,indent=2)
    print(contenido)
    if a.salida:
        dest=Path(a.salida)
        if dest.resolve()==Path(a.anotaciones).resolve():p.error('No sobrescribir anotaciones')
        if dest.exists():p.error('La salida ya existe')
        dest.write_text(contenido,encoding='utf-8')

if __name__=='__main__': main()
