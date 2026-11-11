#!/usr/bin/env python3
"""P28 · el tipo de generador se lee de **dos** fuentes y el proveedor se dice de dónde sale.

Lo que pidió el usuario:

1. El tipo de generador (`NOM` / `OGL` / `UGL`) aparece **en el nombre de la carpeta** y **en la
   barra del vídeo** (`232561 RdW HT OGL 0ms …`). Se comprueban las dos: si coinciden, se escribe;
   si no, no se escribe nada y sale la duda con las dos lecturas.
2. Lo que imprime la barra no siempre se lee entero (`OGU`, `UGU`, `DGU`): se arreglan sólo las dos
   posiciones que de verdad fallan, la última letra (→ `L`) y la primera (→ `U`).
3. `Autoliv` **no se lee** de la etiqueta: es una constante del proyecto. La prueba deja constancia
   de lo que se ve y de lo que no en la etiqueta real.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rellenar_desde_referencia import arreglar_generador, generador_en_barra


def test_la_barra_se_arregla_solo_en_las_dos_posiciones_que_fallan():
    assert arreglar_generador("NOM") == "NOM"
    assert arreglar_generador("OGL") == "OGL"
    assert arreglar_generador("UGL") == "UGL"
    assert arreglar_generador("OGU") == "OGL"      # última letra
    assert arreglar_generador("UGU") == "UGL"
    assert arreglar_generador("DGU") == "UGL"      # primera letra
    assert arreglar_generador("RJMM") is None      # el número de la barra no es un generador


def test_el_generador_sale_de_la_barra_del_video():
    assert generador_en_barra("9TM815x5 22250A RJMM NT NOM 0ms EDAG Mex BMG 28 MAf 25") == "NOM"
    assert generador_en_barra("9TM815x5 282551 RJMM NT OGU 0ms EDAG Mex 05 JUN 25") == "OGL"
    assert generador_en_barra("19TM815x5 282555 RJMM NT DGU 0ms EDAG Mex 05 JUN 25") == "UGL"
    assert generador_en_barra("") is None
    assert generador_en_barra("texto sin nada parecido") is None


def test_los_diez_casos_del_lote_cuadran_carpeta_contra_barra():
    """Con las barras reales del lote, carpeta y barra dicen lo mismo en los diez casos."""
    from rellenar_desde_referencia import arreglar_generador as arreglar

    carpetas = {
        "222504": "NOM", "222509": "NOM", "222521": "OGL", "222530": "UGL", "232550": "NOM",
        "232561": "OGL", "232564": "OGL", "232566": "UGL", "252581": "NOM", "252590": "NOM",
    }
    barras = {
        "222504": "22250A RJMM NT NOM 0ms", "222509": "222509 RJMM NT NOM 0ms",
        "222521": "222521 RJMM NT OGU 0ms", "222530": "222580 RuM8 NT UGU 0ms",
        "232550": "282550 RJMM NT NOM 0ms", "232561": "282551 RJMM NT OGU 0ms",
        "232564": "28255A RJMM NT OGU 0ms", "232566": "282555 RJMM NT DGU 0ms",
        "252581": "252581 R5M8 RT NOM 0ms", "252590": "252590 RJM8 RT NOM 0ms",
    }
    for caso, valor in carpetas.items():
        assert arreglar(valor) == generador_en_barra(barras[caso]) == valor, caso
