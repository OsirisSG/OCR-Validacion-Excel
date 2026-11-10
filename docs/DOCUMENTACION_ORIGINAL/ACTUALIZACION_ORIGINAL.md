# Actualización y reversión · V15.9.10 (correctiva de la auditoría N17)

**Rama:** `codex/ocr-v15-9-10-correctiva` · **Commits:** `b8bce1f` (código y
pruebas), `1222be6` (documentación y VERSION). Padre: `8c916ba` (V15.9.9).
**Entorno de verificación:** Python 3.13 / Node v20 / Linux (este sandbox);
pendientes de campo: Excel corporativos representativos (con tablas formales
reales), AVI anotados reales, GPU, Windows/macOS, navegador real.

| Parche | Base | Bytes | Archivos | SHA-256 |
|---|---|---|---|---|
| `V15_9_10_incremental.patch` | V15.9.9 (`8c916ba`) | 59,203 | 11 | `5fdadecf296dc1f8ff5f6d6c1149c56a302317d893814d271f400c8a4f2887e6` |
| `V15_9_10_completo.patch` | V15.8.1 exacta (`5fbef43`) | 859,337 | 93 | `a8fd758ffd5f9b8ef4be5a4c1f3aff1b28cfc8d718a650630e7f0dafda7247b7` |

Cambios de modo: **0** (los `.command` quedan 100755 — C5).

**No aplique los dos parches sobre el mismo árbol.** Elija según su punto de
partida:

- Tiene V15.9.9 aplicada ⇒ **incremental**.
- Tiene V15.8.1 exacta, o nada ⇒ **completo** (incluye V15.9.1 a V15.9.10).

## 1) Respaldo previo (obligatorio)

Copie FUERA del repo: `.aprendizaje/`, Excel generados, bases SQLite,
`video_airbag_datos.json`, `resultados_validacion_*.json`, cola de Excel,
checkpoints, `proyectos.json` y `plantillas/` personalizadas. Ningún parche
toca estos datos (el diff sólo modifica código, pruebas y documentación).

## 2) Aplicación

### Opción A — desde V15.9.9 (parche incremental)

```bash
cd repo-v1599            # árbol con V15.9.9 aplicada (8c916ba)
git status               # debe estar limpio
git apply --check /ruta/V15_9_10_incremental.patch
git apply /ruta/V15_9_10_incremental.patch
cat VERSION.txt          # 15.9.10
```

### Opción B — desde V15.8.1 exacta o árbol sin V15.9.x (parche completo)

```bash
cd repo-v1581            # árbol en 5fbef43
git status               # debe estar limpio
git apply --check /ruta/V15_9_10_completo.patch
git apply /ruta/V15_9_10_completo.patch
cat VERSION.txt          # 15.9.10
```

Si `git apply --check` falla, NO aplique a mano: el árbol de partida no es
la base declarada. Verifique su commit con `git log --oneline -1` y elija el
parche correcto (o use `archivos/`, que contiene los 93 archivos finales con
sus rutas relativas — copie sobre el repo y confirme con `git diff`).

Nota sobre el ZIP incremental: sólo aporta los módulos y pruebas cambiados.
Las pruebas de ampliación importan auxiliares del repo completo (p. ej.
`pruebas/test_plantilla_empresarial.py`, `pruebas/test_v15_9_6_ampliacion.py`
y `pruebas/test_reporte_bmg_v7.py`); si falta algún auxiliar al hacer
colección, es una limitación del ZIP incremental, no un fallo del programa
— ejecute sobre el árbol completo (o use el parche completo / `archivos/`).

### Verificación post-aplicación (recomendada)

```bash
PYTHONPATH=. python -m pytest pruebas/ -q      # 752 passed / 0 failed
node --test pruebas/*.cjs                      # 43 pass / 0 fail
PYTHONPATH=. python -m pytest \
  pruebas/test_v15_9_10_auditoria_regresiones.py \
  pruebas/test_v15_9_10_ampliacion.py -q       # 25 passed
```

Ambas secuencias se ejecutaron completas en fresh clones de las dos bases
(ver `evidencia_pruebas/FRESH_CLON_*.txt`), incluida la comparación byte a
byte de los 93 archivos contra `archivos/` (0 diferencias) y la equivalencia
del árbol incremental con el final (`git diff 1222be6` = 0 líneas).

## 3) Reversión segura

La reversión se ensayó en los dos fresh clones: tras `git apply -R`,
`git status --porcelain` queda vacío y `git diff <base>` no muestra cambios.

```bash
# Desde V15.9.10 hacia V15.9.9 (si aplicó el incremental):
git apply -R /ruta/V15_9_10_incremental.patch

# Desde V15.9.10 hacia V15.8.1 (si aplicó el completo):
git apply -R /ruta/V15_9_10_completo.patch

git status    # limpio; cat VERSION.txt vuelve a la versión anterior
```

Si hay datos de ejecución nuevos generados CON V15.9.10, consérvelos: son
compatibles con V15.9.9 (ningún formato de persistencia cambió en esta
versión). Borradores `.borrador_no_publicable` emitidos por V15.9.10 (p. ej.
plantillas cuya única «etiqueta» era la cabecera de una tabla registrada, o
pares desnudos sin evidencia positiva bloqueados fail-closed) pueden
eliminarse manualmente sin riesgo: nunca entran en `generados/` ni en la
cola oficial. Para publicarlos, añada un campo de proyecto inequívoco
(etiqueta explícita con separador, p. ej. «Proyecto:») a la plantilla o
declare la identidad por el contrato existente; NO mueva ni renombre las
cabeceras de las tablas registradas.

## 4) Comprobación de integridad del paquete

```bash
cd V15_9_10_CORRECTIVA_N17
sha256sum -c SHA256SUMS.txt          # todo OK (verificable desde el ZIP)
sha256sum V15_9_10_*.patch           # comparar con la tabla de arriba
```

## 5) Qué NO hace esta versión

- No declara aptitud para producción: faltan las pruebas de campo exigidas
  (Excel corporativos representativos del entorno del usuario, AVI reales
  anotados, GPU/RTX, Windows/macOS, navegador real).
- No modifica módulos de vídeo, ROI/zoom/detección, umbrales, consenso,
  aprendizaje/checkpoints, backend, pipeline ni frontend.
- No toca plantillas originales, `.aprendizaje/`, bases de datos ni
  persistencia humana; no altera fórmulas, números, celdas combinadas,
  históricos ni datos de usuario de los Excel.
- No introduce dependencias nuevas ni requiere red; no hace reemplazos
  globales en Excel; no amplía el diccionario de cabeceras como mecanismo
  de protección (queda sólo como segunda capa para tablas visuales).
