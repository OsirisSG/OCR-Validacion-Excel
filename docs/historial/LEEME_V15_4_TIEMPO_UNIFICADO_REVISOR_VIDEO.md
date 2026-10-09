# OCR Versuchsmatrix V15.4 — tiempo unificado y revisor de video

V15.4 corrige la contradicción observada entre el reloj impreso en la esquina
superior derecha del AVI y la casilla `Tiempo de apertura (ms)`. También impide
que una apertura pueda guardarse con tiempo negativo.

## Regla temporal nueva

El **frame confirmado** es la referencia del evento. Para ese mismo frame el
backend obtiene:

1. tasa real de grabación (`Rec5000 fps`, cuando está disponible),
2. timestamp visible de la esquina superior derecha,
3. timestamp inicial del video, si fue leído,
4. tiempo esperado por posición de frame.

El reloj visible tiene prioridad sólo cuando es coherente con la posición del
frame. Si OCR lee un valor imposible (por ejemplo `20.0` donde frame/FPS indican
`2.0`, o un valor negativo), esa lectura se descarta y el dashboard muestra una
advertencia. El valor erróneo nunca se guarda silenciosamente.

## Cambios del dashboard

- La casilla de tiempo queda sincronizada con el frame y ya no funciona como un
  segundo dato independiente.
- Al mover el frame se consulta al backend el reloj de ese cuadro concreto.
- Se muestra `Tiempo del cuadro actual` y `Reloj esquina superior derecha` uno
  junto al otro.
- Se indica `coincide` cuando ambos están validados.
- Se incorpora una línea de tiempo (slider), saltos ±1 y ±10 cuadros y atajos de
  teclado: flechas para 1 cuadro, Shift+flechas para 10, Inicio/Fin para extremos.
- `No hay apertura` tiene un estado visual propio y no se confunde con
  `Candidato automático`.

## Blindajes

- API de revisión: `tiempo_ms >= 0`.
- Persistencia: rechaza confirmaciones negativas incluso si llegan desde un
  cliente antiguo.
- Consenso 3/4: ignora revisiones negativas heredadas de versiones anteriores.
- Una calibración de overlay nunca puede convertir un tiempo positivo en
  negativo.
- Las zonas por nombre (`DETAIL`, `FRONTAL`, `LATERAL`, `SCHEIBE`) siguen siendo
  una pista fuerte, pero V15.4 exige además una similitud visual mínima para no
  aplicar una ROI vieja a una escena claramente distinta.

## Compatibilidad

El parche V15.4 es acumulativo: incluye V15.1, V15.2 y V15.3. No elimina
`.aprendizaje`, el dataset F-3…F+3, las zonas aprendidas ni los resultados del
usuario. Se invalida únicamente el caché de análisis de video para recalcular con
la lógica temporal nueva.
