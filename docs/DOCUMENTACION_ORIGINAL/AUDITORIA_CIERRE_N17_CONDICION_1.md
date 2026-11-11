# Auditoría de evidencia — Cierre N17 / Condición 1 · V-Matrix V15.9.10

**Fecha:** 13 de octubre de 2026  
**Entrada auditada:** `CIERRE_N17_CONDICION_1.zip` (4 elementos ZIP: carpeta, dos documentos y manifiesto).  
**Ámbito:** comprobación documental de la condición 1 del informe `AUDITORIA_ESTRICTA_V_MATRIX_V15_9_10_CIERRE_N17.md`.  
**Dictamen:** **evidencia documental íntegra; condición 1 documentada y parcialmente corroborada, pendiente de réplica independiente sobre el árbol exacto.** La corrección N17 sigue cerrada y V15.9.10 continúa como candidata a piloto, **no aprobada para producción**.

## 1. Qué fue verificado de forma independiente

| Comprobación | Resultado | Interpretación |
|---|---|---|
| Integridad de los dos documentos del nuevo ZIP contra `SHA256SUMS.txt` | **2/2 coinciden** | No hay diferencia de bytes frente al manifiesto suministrado. Esto no certifica que las ejecuciones narradas hayan ocurrido. |
| SHA-256 del ZIP V15.9.10 previamente auditado | `470ca12424ddc00123b0b12e0c07eeb60b221e2f7840c84c4d15c998b254427c` | Coincide con la referencia indicada en el cierre. ZIP de V15.9.10 inalterado en esta sesión. |
| SHA-256 de la plantilla BMG en la copia de integración disponible | `399ae03a99e79a0f54ad1a748c584f3843f96ff7a35b5a4eaa6e598675adf877` | Coincide con el valor del informe. Comprueba el estado de esa copia, no la integridad de libros empresariales reales. |
| Base de GitHub `5fbef43` | **Commit localizado** | Existe el commit V15.8.1 en el repositorio `OsirisSG/OCR-Validacion-Excel`. |
| Referencia GitHub `1222be6` | **No localizada desde el conector en esta revisión** | Puede ser un commit local/no publicado. No se verificó la equivalencia del árbol final con ese commit desde GitHub. No constituye por sí solo un fallo del parche. |
| Pruebas Python dirigidas sobre copia de integración disponible | **54 passed, 1 deselected** | La prueba excluida es precisamente la BMG que necesita `maximos_video.py`, ausente de esta **copia histórica**, no del repositorio base exacto. |
| Pruebas Node globales sobre la misma copia histórica | **39/42** | Tres fallos en tests heredados de caché V15 y presencia de panel de videos. La copia no reproduce el árbol de Git del desarrollador: el resultado **no debe atribuirse a la V15.9.10 exacta** ni mezclarse con su cifra de 43. |

**Limitación de la evidencia:** el ZIP entregado ahora contiene informes escritos y hashes de esos informes, **no** el checkout exacto, logs íntegros originales, XML JUnit ni un bundle reproducible del commit final. En consecuencia, **752 Python aprobadas + 43 Node aprobadas** quedan como **resultados declarados por el desarrollador**, no como verificación independiente nuestra. El texto declara además que la prueba BMG antes excluida pasó en ese entorno (1/1).

## 2. Revisión del alcance

1. El nuevo archivo **no contiene cambios de código ni otro parche**. No corresponde solicitar V15.9.11 por este cierre.
2. El informe declara una reconstrucción desde el commit base `5fbef43bb4c2c9142327afd3f88e89b460aed6c5`, la aplicación de `V15_9_10_completo.patch` y una comparación sin cambios con el árbol `1222be6`. Esta comparación **no pudo repetirse de manera independiente** con el material adjunto.
3. La aritmética documentada de las pruebas dirigidas es consistente: `61` aprobadas en nuestra selección anterior, menos `7` pruebas duplicadas, más `1` BMG antes excluida = `55` aprobadas declaradas.
4. **N17 se considera corregido en las pruebas dirigidas anteriores**, con protección estructural de cabeceras y sin una regresión adicional demostrada en el presente paquete documental.

## 3. Dictamen y siguiente paso

**Aceptación limitada:** podemos aceptar el documento como **constancia de ejecución aportada por el desarrollador** para la condición 1. No es una réplica independiente de la suite integral. Para cerrar la condición 1 con trazabilidad completa, conservar el acceso al commit/árbol exacto o un archivo fuente reproducible y adjuntar `pytest` con JUnit XML y salida completa de `node --test`.

**No existe un bloqueo nuevo de código demostrado que justifique otro parche.** Continúa el piloto controlado, no la instalación directa en producción.

**Condiciones 2–6 pendientes:** (2) dos plantillas Excel empresariales reales y hashes antes/después; (3) ventana «Procesar carpeta» y selección de proyecto, tiempos, matriz, exportación y reanudación en navegador; (4) AVI reales anotados con precisión nativa, falsos positivos/negativos y consenso 3/4; (5) zoom/ROI y reversión en Windows corporativo, rendimiento y rollback; (6) respaldos, separación de datos piloto y preservación de `.aprendizaje`, `.cache_ocr` y resultados.

### Evidencia reproducible ideal para cerrar formalmente la condición 1

En el árbol exacto V15.9.10, antes de las pruebas, conservar `git rev-parse HEAD`, `git rev-parse HEAD^{tree}`, `git status --porcelain=v1` y el SHA-256 del archivo original V15.9.10; después ejecutar:

```bash
PYTHONPATH=. python -m pytest pruebas/ -q --junitxml=resultado_pytest_v15_9_10.xml
node --test pruebas/*.cjs > resultado_node_v15_9_10.log 2>&1
```

Adjuntar el XML y el log completos, así como la salida de la prueba individual `test_n17_bmg_real_tabla_formal_genera_borrador_intacto`, sin modificar criterios ni datos reales. Una prueba satisfactoria en el entorno empresarial del piloto será evidencia todavía más útil.

**Nota sobre exactitud temporal:** las pruebas sintéticas y de software no demuestran precisión física de 0.1 ms; depende de los FPS de adquisición y la validación temporal con videos reales.
