# V-Matrix V15.10.1 — incremental H5 / aperturas censuradas

**Tipo:** actualización incremental; no es un paquete autónomo.  
**Base requerida:** paquete acumulado V15.10.0 con `V-Matrix-V15.10.1_Patch.zip` ya aplicado, o un árbol equivalente a ese estado.  
**ZIP nuevo:** `V-Matrix-V15.10.1_H5_Censura_Incremental_20261014.zip`.  
**SHA-256 del ZIP:** consultar el sidecar `V-Matrix-V15.10.1_H5_Censura_Incremental_20261014_SHA256.txt`.  
**Integridad interna:** `MANIFEST_SHA256_V15_10_1_H5_CENSURA.txt` en la raíz del ZIP.

## Alcance

Cierra H5 para la publicación de tiempos finales de apertura. Sólo se permite publicar/proponer un tiempo final si es finito, estrictamente mayor que `0 ms`, su referencia temporal está validada y el evento no está censurado a la izquierda. Raw, estado y motivo de rechazo se conservan en auditoría. No se usa `abs()`, no se fuerza el valor a cero y no se recalculan negativos históricos desde frame/FPS. Los tiempos de overlay/offset pueden conservar signo porque no equivalen por sí solos al tiempo final de apertura.

El endpoint de detalle sanea el resumen, `campos.opening_time_ms`, los videos y su `revision_manual` anidada; también sanea el resumen previo de apertura. La interfaz presenta `CENSURADO`, deshabilita la confirmación y evita que el flujo combinado de ROI + apertura eluda el bloqueo. La ruta manual del servidor sigue rechazando una confirmación censurada con HTTP 422. Excel conserva raw/estado/motivo y no publica el tiempo censurado.

## Archivos del delta

Los archivos que se reemplazan o agregan están enumerados, con SHA-256, en el manifiesto del ZIP. Incluyen los módulos de resolución/detección, API/dashboard e informe Excel, pruebas unitarias/regresión y esta documentación. El ZIP no incluye datos de casos, libros Excel de usuario, `.aprendizaje`, adjuntos del usuario, `AGENTS.md` ni skills.

## Aplicación conservadora

1. Cierra V-Matrix, el dashboard y Excel. Confirma que ya aplicaste el parche V15.10.1 anterior; si no, detente y aplica primero ese parche.
2. Desde la carpeta que contiene el ZIP y su sidecar, verifica el SHA-256 del ZIP (`sha256sum -c V-Matrix-V15.10.1_H5_Censura_Incremental_20261014_SHA256.txt`, o `shasum -a 256 -c ...`). Extrae a una carpeta temporal nueva, no directamente sobre el proyecto, y comprueba el manifiesto interno (`sha256sum -c` o `shasum -a 256 -c`).
3. Haz respaldo **archivo por archivo** de cada ruta del manifiesto, conservando la estructura relativa. Registra por separado las rutas nuevas que no existían.
4. Copia explícitamente sólo las rutas del manifiesto desde staging al proyecto. No uses `robocopy /MIR`, `rsync --delete`, extracción espejo ni borrado de carpetas.
5. Ejecuta las pruebas indicadas en `docs/informes/INFORME_PATCH_V15_10_1_H5_CENSURA_INCREMENTAL.md`. Conserva el ZIP, sidecar y respaldo.

### Ejemplo macOS/Linux

Ajusta `PROJECT`, `STAGE` y `BACKUP`. `MANIFEST` vive en la raíz de lo extraído. El bucle aborta ante rutas absolutas o con traversal, respalda los archivos existentes y copia sólo las rutas listadas.

```sh
set -eu
PROJECT="/ruta/al/V-Matrix-V15.10.0"
STAGE="/ruta/temporal/V15.10.1-H5"
BACKUP="/ruta/respaldos/V15.10.1-H5-$(date +%Y%m%d-%H%M%S)"
MANIFEST="$STAGE/MANIFEST_SHA256_V15_10_1_H5_CENSURA.txt"
mkdir -p "$BACKUP"
: > "$BACKUP/creados_por_parche.txt"

while read -r hash rel; do
  case "$rel" in
    .aprendizaje|.aprendizaje/*|AGENTS.md|.agents/*|/*|../*|*/../*|*/..) echo "Ruta prohibida: $rel" >&2; exit 1 ;;
  esac
  test -f "$STAGE/$rel"
  mkdir -p "$PROJECT/$(dirname "$rel")"
  if test -f "$PROJECT/$rel"; then
    mkdir -p "$BACKUP/$(dirname "$rel")"
    cp -p "$PROJECT/$rel" "$BACKUP/$rel"
  else
    printf '%s\n' "$rel" >> "$BACKUP/creados_por_parche.txt"
  fi
  cp -p "$STAGE/$rel" "$PROJECT/$rel"
done < "$MANIFEST"
```

### Rollback conservador

Cierra la aplicación. Restaura desde el respaldo sólo las rutas existentes que enumera el manifiesto. Para rutas que el parche agregó, muévelas a una carpeta de cuarentena/rollback; no borres directorios ni otros archivos. Guarda una copia del estado actual antes de restaurar cualquier archivo. No uses herramientas de sincronización espejo.

```sh
set -eu
PROJECT="/ruta/al/V-Matrix-V15.10.0"
BACKUP="/ruta/al/respaldo-V15.10.1-H5-AAAAMMDD-HHMMSS"
MANIFEST="/ruta/temporal/V15.10.1-H5/MANIFEST_SHA256_V15_10_1_H5_CENSURA.txt"
CREADOS="$BACKUP/creados_por_parche.txt"
CAPTURA="$BACKUP/estado_actual_pre_rollback"
RETIRADOS="$BACKUP/archivos_nuevos_movidos"
while read -r hash rel; do
  case "$rel" in .aprendizaje|.aprendizaje/*|AGENTS.md|.agents/*|/*|../*|*/../*|*/..) echo "Ruta prohibida: $rel" >&2; exit 1 ;; esac
  if test -f "$BACKUP/$rel"; then
    if test -f "$PROJECT/$rel"; then
      mkdir -p "$CAPTURA/$(dirname "$rel")"
      cp -p "$PROJECT/$rel" "$CAPTURA/$rel"
    fi
    mkdir -p "$PROJECT/$(dirname "$rel")"
    cp -p "$BACKUP/$rel" "$PROJECT/$rel"
  elif grep -Fxq "$rel" "$CREADOS" && test -f "$PROJECT/$rel"; then
    mkdir -p "$RETIRADOS/$(dirname "$rel")"
    mv "$PROJECT/$rel" "$RETIRADOS/$rel"
  fi
done < "$MANIFEST"
```

El procedimiento no inspecciona, abre, copia, instala ni modifica `.aprendizaje`. No modifica skills ni `AGENTS.md`; no cambia datos reales. La actualización no constituye aprobación de producción: falta piloto autorizado y validación con evidencia real autorizada.
