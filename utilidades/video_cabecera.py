#!/usr/bin/env python3
"""Cabecera del vídeo: el **lugar de prueba** está arriba, no en la barra.

Los vídeos de EDAG llevan dos zonas con texto:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ▮ EDAG México                                        EDAG Testlab      75.0 │  ← cabecera
│                                                                            │
│                            (imagen del ensayo)                             │
│                                                                            │
│ VW 316/5  232541  RdW  HT  NOM  0ms  EDAG Mex  04 JUN 25  Rec5000 fps …    │  ← barra
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Cabecera (arriba)**: el logotipo del laboratorio (`EDAG México`) y, a la derecha, **`EDAG Testlab`**.
  Eso es el **lugar de prueba** que pide el libro (`EDAG`).
- **Barra (abajo)**: número de prueba y **fecha de prueba** (`04 JUN 25`), que ya lee `barra_estado`.

La cabecera se lee por OCR porque no tiene banco de glifos propio: se recortan **sólo las esquinas**
(el logotipo a la izquierda y el nombre del laboratorio a la derecha), se amplían ×3 y se prueban gris,
Otsu e invertido. Nunca se lee la franja entera ampliada: eso agota la memoria.

Si la cabecera y la barra no dicen lo mismo del lugar, no se escribe: queda en duda con la captura al lado.
"""
from __future__ import annotations

from pathlib import Path

import cv2

LUGARES = {"EDAG": ("EDAGTESTLAB", "EDAGMEXICO", "EDAGMEX", "EDAG"), "VW": ("VWTESTLAB", "VW")}
ZONAS = {"izquierda": (0.00, 0.26), "derecha": (0.70, 1.00)}
ALTO_RELATIVO = 0.07


def normalizar(texto: str) -> str:
    return "".join(c for c in str(texto or "").upper() if c.isalnum())


def lugar_de_texto(texto: str) -> str:
    """`EDAG Testlab` / `EDAG México` → `EDAG`; `VW …` → `VW`. Nada más."""
    limpio = normalizar(texto)
    if not limpio:
        return ""
    if "EDAG" in limpio:
        return "EDAG"
    if limpio.startswith("VW") or "VWTESTLAB" in limpio:
        return "VW"
    return ""


def _variantes(recorte):
    """Sólo dos preparaciones: gris e invertido (bastan y tardan la mitad)."""
    gris = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
    return [cv2.cvtColor(gris, cv2.COLOR_GRAY2BGR),
            cv2.cvtColor(cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1],
                         cv2.COLOR_GRAY2BGR)]


def leer_cabecera(fotograma, motor, escalas=(3,)) -> dict:
    """Lee las esquinas de arriba **en orden** y para en cuanto reconoce el laboratorio.

    Primero la derecha (`EDAG Testlab`), que es el nombre explícito del laboratorio; si ahí no hay
    nada, la izquierda (el logotipo `EDAG México`).
    """
    alto, ancho = fotograma.shape[:2]
    lineas: list[tuple[str, float]] = []
    orden = sorted(ZONAS.items(), key=lambda par: 0 if par[0] == "derecha" else 1)
    for _nombre, (x0, x1) in orden:
        recorte = fotograma[0:max(8, int(alto * ALTO_RELATIVO)), int(ancho * x0):int(ancho * x1)]
        if recorte.size == 0:
            continue
        for escala in escalas:
            grande = cv2.resize(recorte, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
            if grande.shape[1] > 1400:                     # no ampliar sin límite: memoria
                factor = 1400 / grande.shape[1]
                grande = cv2.resize(grande, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
            for variante in _variantes(grande):
                from utilidades.lector_etiquetas import leer_con_giros
                lectura, _ = leer_con_giros(variante, motor, modos=("original",))
                for texto, confianza in lectura.lineas:
                    limpio = " ".join(str(texto).split())
                    if len(limpio) >= 3:
                        lineas.append((limpio, float(confianza)))
        # en cuanto una esquina da el laboratorio, no se sigue gastando OCR
        if any(lugar_de_texto(texto) for texto, _ in lineas):
            break
    lugar, leido = "", ""
    for texto, _confianza in lineas:
        candidato = lugar_de_texto(texto)
        if candidato:
            lugar, leido = candidato, texto
            break
    return {"lugar": lugar, "lugar_leido": leido, "lineas": lineas}


def leer_cabecera_de_video(archivo, motor, muestras: int = 3) -> dict:
    """Vota el lugar entre varios fotogramas: un fotograma suelto puede perder el logotipo."""
    from collections import Counter
    captura = cv2.VideoCapture(str(archivo))
    if not captura.isOpened():
        return {"lugar": "", "lugar_leido": "", "muestras": 0, "fotograma": None}
    total = int(captura.get(cv2.CAP_PROP_FRAME_COUNT) or 0) or 1
    votos: Counter = Counter()
    leidos: Counter = Counter()
    mejor = None
    for indice in range(max(1, muestras)):
        posicion = int(total * (0.2 + 0.6 * (indice / max(1, muestras - 1))))
        captura.set(cv2.CAP_PROP_POS_FRAMES, min(posicion, total - 1))
        correcto, fotograma = captura.read()
        if not correcto or fotograma is None:
            continue
        lectura = leer_cabecera(fotograma, motor)
        if lectura["lugar"]:
            votos[lectura["lugar"]] += 1
            leidos[lectura["lugar_leido"]] += 1
            if mejor is None or max((c for _, c in lectura["lineas"]), default=0) > mejor[1]:
                mejor = (fotograma.copy(), max((c for _, c in lectura["lineas"]), default=0), lectura)
    captura.release()
    lugar = votos.most_common(1)[0][0] if votos else ""
    return {"lugar": lugar,
            "lugar_leido": leidos.most_common(1)[0][0] if leidos else "",
            "votos": dict(votos), "muestras": sum(votos.values()),
            "fotograma": mejor[0] if mejor else None,
            "lectura": mejor[2] if mejor else {}}


def captura_de_evidencia(fotograma, lectura_cabecera: dict, barra: dict, destino: Path) -> Path:
    """Guarda la captura con las **dos zonas** ampliadas y lo leído escrito debajo."""
    import numpy as np
    alto, ancho = fotograma.shape[:2]
    arriba = fotograma[0:max(8, int(alto * ALTO_RELATIVO)), :]
    abajo = fotograma[int(alto * 0.94):, :]
    pie = np.zeros((150, ancho, 3), np.uint8)
    lineas = [
        f"CABECERA (lugar): {lectura_cabecera.get('lugar_leido', '') or 'no legible'}"
        f"  ->  {lectura_cabecera.get('lugar', '') or '?'}",
        f"BARRA (numero): {barra.get('numero', '') or '?'}"
        f"   FECHA: {barra.get('fecha', '') or '?'}   SEMANA: {barra.get('semana', '') or '?'}",
        f"BARRA completa: {barra.get('texto', '')[:90]}",
    ]
    for indice, texto in enumerate(lineas):
        cv2.putText(pie, texto[:120], (8, 30 + indice * 34), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 220, 255) if indice == 0 else (230, 230, 230), 1, cv2.LINE_AA)
    def ajustar(imagen, referencia_ancho):
        if imagen.shape[1] != referencia_ancho:
            factor = referencia_ancho / imagen.shape[1]
            imagen = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
        return imagen
    arriba_grande = ajustar(arriba, ancho)
    abajo_grande = ajustar(abajo, ancho)
    compuesta = np.vstack([arriba_grande, fotograma, abajo_grande, pie])
    if compuesta.shape[0] > 2200:                          # capturas manejables
        factor = 2200 / compuesta.shape[0]
        compuesta = cv2.resize(compuesta, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    destino.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(destino), compuesta)
    return destino
