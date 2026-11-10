# V16.0.52 · P42 r3 — actualización pendiente de validación general

Origen: diagnóstico 20261109_091659 y SUPER_PARCHE_P42_V16_0_52_r3.zip.
El VERSION.txt original del motor declara 16.0.20; el parche P42 se identifica como 16.0.52 r3. No se ha renumerado el motor por suposición.

Aplicado el plan del instalador P42, incluida la corrección de conservación de celdas en reporte_bmg.py. El libro de muestra del parche se conserva como versionV16_0_52_P42_r3.xlsx para no sobrescribir el libro anterior.

## Verificación ejecutada
- Manifiesto del parche en modo estricto: 66 archivos íntegros.
- python3 -m pytest pruebas/test_p42_datamatrix.py -q: 38 aprobadas.
- python3 -m pytest pruebas/ -q: detenida en colección por imports ausentes leer_proveedor (utilidades.codigos_modulo) y normalizar_por_campo (utilidades.protocolo_campos).
- node --test pruebas/*.cjs: 52 aprobadas y 2 fallidas: tooltip accesible de matriz y texto abrir en Listado.

No se declara esta actualización validada para producción. Pendiente resolver compatibilidad y ejecutar la suite general en verde antes de fusionar según Evaluation Lab.

## Conservación
Las bases SQLite, cachés, correcciones humanas, resultados locales, respaldos automáticos y capturas no se incorporan al árbol de código. El diagnóstico original completo continúa en Releases.

## Reversión
La rama nace de 16f6b18f0c91c36540922598eee2bd6b3924f1d0. Antes de fusionar puede abandonarse sin afectar main. Si se fusiona mediante PR, revertir el commit de fusión con git revert -m 1 SHA_DEL_MERGE; las bases de datos quedan fuera de esa reversión.
