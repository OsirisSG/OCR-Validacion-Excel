#!/usr/bin/env python3
"""P29 · El proveedor del generador se lee en el texto vertical, y la sintaxis del nivel.

Lo que pidió el usuario:

1. Saber si `Autoliv` «se pone automático» o «se lee de alguna parte». Se lee: en la etiqueta grande
   va **girado 90°** y en cuerpo diminuto (`Autoliv B.V.& Co.KG`). Se busca en la mitad derecha de la
   foto, en los tres giros y ampliada.
2. La sintaxis del nivel es **`##K` cuando el módulo lleva estampa** y **`##S` cuando no la lleva**.
   Se comprueba en cada caso y, si no cuadra, sale la duda.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utilidades.codigos_modulo import (leer_proveedor, nivel_correcto_por_sintaxis,
                                       normalizar_proveedor)


def test_el_proveedor_se_normaliza_como_lo_escribe_el_libro():
    assert normalizar_proveedor("Autoliv B.V.&Co.KG") == "Autoliv"
    assert normalizar_proveedor("AUTOLIV") == "Autoliv"
    assert normalizar_proveedor("Autoliv Product Safety") == "Autoliv"
    assert normalizar_proveedor("FORVIA") == "Forvia"
    assert normalizar_proveedor("RJMM") is None
    assert normalizar_proveedor("") is None


def test_la_sintaxis_del_nivel_k_con_estampa_s_sin_ella():
    assert nivel_correcto_por_sintaxis("69K", True)
    assert nivel_correcto_por_sintaxis("66K", True)
    assert nivel_correcto_por_sintaxis("01S", False)
    assert not nivel_correcto_por_sintaxis("01S", True), "con estampa el nivel es de la familia K"
    assert not nivel_correcto_por_sintaxis("69K", False), "sin estampa el nivel es de la familia S"
    assert not nivel_correcto_por_sintaxis("", True)


def test_el_proveedor_se_encuentra_en_una_foto_sintetica_girada():
    """La etiqueta simulada lleva el proveedor girado 90°, como en las fotos reales."""
    imagen = np.full((900, 1400, 3), 30, np.uint8)
    cv2.rectangle(imagen, (700, 200), (1350, 700), (240, 240, 240), -1)
    texto = np.full((120, 520, 3), 240, np.uint8)
    cv2.putText(texto, "Autoliv", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 2.6, (20, 20, 20), 6, cv2.LINE_AA)
    girado = cv2.rotate(texto, cv2.ROTATE_90_CLOCKWISE)
    imagen[240:240 + girado.shape[0], 1120:1120 + girado.shape[1]] = girado
    lectura = leer_proveedor(imagen)
    assert lectura.get("inflator_supplier") == "Autoliv", lectura
