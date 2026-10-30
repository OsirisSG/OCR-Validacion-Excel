"""Alternativas OCR por campo según regex aportada, sin autocorrección ciega.

No asume que EDAG=VW, ni que fabricante=laboratorio, ni inventa campos.
La validación de formato reduce candidatos, NO demuestra identidad.
"""
from __future__ import annotations
from collections import deque
import re

VERSION='15.10.1-shadow'
ALTERNATIVAS={'0':'O','O':'0','1':'I','I':'1','l':'1','5':'S','S':'5','8':'B','B':'8'}


def proponer_lecturas(texto: str, *, expresion_campo: str | None = None,
                      max_alternativas: int=12) -> dict:
    if not isinstance(texto,str):raise TypeError('texto debe ser str')
    if not 1<=max_alternativas<=128:raise ValueError('límite inválido')
    patron = re.compile(expresion_campo) if expresion_campo else None
    vistos={texto}
    cola=deque([(texto,0)])
    salida=[]
    while cola and len(salida)<max_alternativas:
        s,cambios=cola.popleft()
        salida.append({'texto':s,'cambios':cambios,
                       'formato_compatible':bool(patron.fullmatch(s)) if patron else None,
                       'origen':'ocr_original' if cambios==0 else 'variante_ambiguedad'})
        if cambios>=2:continue
        for i,ch in enumerate(s):
            alt=ALTERNATIVAS.get(ch)
            if alt:
                nuevo=s[:i]+alt+s[i+1:]
                if nuevo not in vistos:
                    vistos.add(nuevo)
                    cola.append((nuevo,cambios+1))
    salida.sort(key=lambda x: (x['formato_compatible'] is not True,x['cambios'],x['texto']))
    return {'version':VERSION,'lectura_original':texto,'hipotesis':salida,
            'auto_confirmada':False,'motivos':['formato_no_es_verificacion_de_identidad']}
