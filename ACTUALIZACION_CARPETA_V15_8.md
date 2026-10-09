# V15.8 aplicada al repositorio local

Fecha: 9 de octubre de 2026.

La versión validada del ZIP nuevo también quedó aplicada a
`/Users/osirissilvagarcia/proyecto_ocr`, a petición del usuario. Rama mantenida:
`ocr-v8-versuchsmatrix`; remoto: `OsirisSG/OCR-Validacion-Excel`. No se cambió de
rama ni se hizo commit/push/staging automático.

## Qué se aplicó y qué se conservó

- Se sincronizaron 33 archivos existentes y se añadieron 137 archivos del paquete:
  código V15.7.4/V15.8, pruebas, historial de documentación y recursos visuales.
  No se copió sólo el parche V15.8 sobre V8 porque faltarían módulos del ZIP nuevo.
- Las cuatro modificaciones locales anteriores quedaron respaldadas antes de
  sincronizar. No se eliminaron archivos previos ausentes del paquete nuevo.
- Se conservan todos los valores de configuración existentes, incluido
  `fase1.rendimiento.batch_gpu: 4`, junto con las opciones nuevas del paquete.
- No se copiaron SQLite/feedback, resultados, inventarios, checkpoints, Excel de
  salida, entornos virtuales ni capturas personales del ZIP. Se mantienen los
  datos de esta instalación, no se sustituyen por los del otro equipo.
- La plantilla oficial `plantillas/reporte_bmg_1st_2st.xlsx` ya existía y coincide
  con el paquete. Se añadió su excepción específica en `.gitignore` para que el
  push sí incluya la plantilla; los Excel de resultados siguen excluidos.
- Requisitos e instalador coinciden con la versión anterior: no se instalaron
  nuevas librerías ni se copió un entorno virtual.

## Respaldo recuperable

`/Users/osirissilvagarcia/respaldo_ocr_antes_v15_8_ReowV2qn`

Incluye los archivos reemplazados, un diff previo, manifiesto de aplicación y
copias de los 20 archivos locales de datos protegidos. Está fuera del repositorio
y no se envía a Git. Restaurar desde este respaldo debe hacerse con el programa
cerrado y sin sobrescribir correcciones posteriores.

## Validación desde la carpeta del proyecto

- `.venv_dashboard/bin/python -m pytest -q --tb=no`: **423 aprobadas**, 0 fallos,
  36.24 s. Una advertencia de deprecación Starlette/httpx del entorno de pruebas.
- Los **23** scripts `pruebas/*.cjs`, ejecutados individualmente con Node: correctos.
- Compilación de los 8 módulos Python y sintaxis `app.js` / `i18n.js`: correctas.
- Hashes de los 20 datos protegidos verificados antes de copiar y después de la
  validación. Las pruebas migraron el esquema de dos SQLite sin quitar registros;
  sus copias migradas se respaldaron y se devolvieron los archivos originales
  tras finalizar. El programa podrá migrar su esquema normalmente al iniciar.
- `.gitignore` excluye aprendizaje, cachés y resultados; admite la plantilla oficial.
- `git diff --check`: correcto tras quitar una línea vacía final de documentación.

No había un servidor en el puerto 8000 ni un procesamiento activo al aplicar.
Para ver la nueva versión, inicia de nuevo el programa y recarga el navegador.
No se inició un entrenamiento ni un análisis de tus fotos o vídeos para esta
actualización. La validación Windows/RTX A3000 y con vídeos reales sigue pendiente.

Consulta `RESULTADOS_PRUEBAS_V15_8.md` y `LEEME_V15_8_GUIA_RUPTURA_MAXIMO.md`
para las funciones, el flujo de máximo visible y los límites conocidos.
