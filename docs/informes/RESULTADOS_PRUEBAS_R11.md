# Resultados de pruebas R11

Fecha: 2026-10-14

Validaciones ejecutadas sobre una copia completa del proyecto con R11 aplicada:

- `test_ruptura_real.py` + protocolos R9/R10: **34 passed**.
  - primer píxel claro: onset conservado;
  - fisura oscura antes de tela clara: onset temprano conservado;
  - ruido cercano: no adelanta apertura;
  - cuadro limpio intermedio: corta una señal vieja;
  - hot-pixel persistente lejano: no secuestra el onset real;
  - indicio en último cuadro: no se inventa confirmación.
- Bloque Python crítico acumulado de ruptura/H5/tiempos/matriz/Excel/proyecto/idiomas/imágenes: **139 passed**.
- Frontend Node completo: **53 passed**.
- Resumen vivo R11: **3 passed**.
- `py_compile` de módulos cambiados y `node --check` de `app.js`: OK.

Limitación: estas pruebas validan contratos y escenas sintéticas. La exactitud física final debe calibrarse con AVI reales etiquetados; R11 no declara una probabilidad calibrada ni sustituye esa validación.
