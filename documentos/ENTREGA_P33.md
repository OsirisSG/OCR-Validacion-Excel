# Entrega P33 · V16.0.46 — qué hay y dónde

## El parche (lo que se aplica sobre tu V16.0.28)

| | |
|---|---|
| archivo | `vmatrix/VMATRIX_PARCHE_V16_0_46.zip` |
| tamaño | 9 656 227 B · 228 archivos |
| sha256 | `f19cecc93798a26118fd2bbdc81c6dc2623cd295eb99eb6c13f694a6b0f7bd7b` |
| se aplica sobre | **V16.0.28** (lo instalado), sin pasos intermedios |
| instalador | `INSTALAR_V16_0_46.bat` · o `INSTALADOR_V16_0_46.ps1 -Accion instalar -Proyecto <carpeta>` |
| deshacer | `INSTALADOR_V16_0_46.ps1 -Accion restaurar -Proyecto <carpeta>` |

### Probado sobre un proyecto realmente en V16.0.28

```
proyecto base → instalar V16.0.28 ......... INSTALACION CORRECTA V16.0.28 | VERIFICADO 63/63
diagnosticar el parche sobre 28 ........... INSTALABLE | NUEVO 60 / PREVIO 3 / AUSENTE 39 / DESCONOCIDO 0 / BLOQUEADO 0 de 102
instalar .................................. INSTALACION CORRECTA V16.0.46 | VERIFICADO 102/102 | Escritos: 42
verificar ................................. VERIFICADO 102/102
volver a instalar ......................... Ya instalada V16.0.46
ensayo completo del paquete ............... 10/10 bloques correctos
```

Para repetirlo: `bash documentos/logicas/probar_parche_sobre_28.sh`.

## Los documentos

| archivo | para qué |
|---|---|
| `documentos/PROMPT_P33.md` | **el prompt**: contexto, reglas de campo, cómo devolver las cosas, cómo se construye el parche, qué falta |
| `documentos/LOGICAS_QUE_FUNCIONAN.md` | las 10 lógicas que ya funcionan, con archivo y prueba |
| `documentos/logicas/` | copia de los módulos que funcionan + `probar_parche_sobre_28.sh` |
| `documentos/VARIANTES_motivo_y_PAB.md` | **la respuesta a tu duda**: variantes en motivo de prueba y en N/P del PAB |

Los cuatro viajan también dentro del zip, en `documentos/`.

## La duda de las variantes, en tres líneas

- **Número de parte del PAB**: ahora admite **1 o 2** caracteres finales y se normaliza
  (`2GJ 880 204 J` → `2GJ.880.204.J`). Antes, `2GJ.880.204.AB` se rechazaba.
- **Motivo de prueba**: no es catálogo; se pasa a mayúsculas y sin acentos y admite paréntesis
  (`bmg` → `BMG`, `BMG (NOM)` tal cual).
- **No se afloja el permiso**: `2GJ.880.204` (sin sufijo), `BMG_1` o 45 caracteres siguen rechazados
  y siguen yendo a dudas con recorte. 29 pruebas lo fijan en `pruebas/test_p33_variantes.py`.

## Lo que no cambia

El libro del lote sigue siendo `versionV16_0_45.xlsx`: **154/180 llenas · 149 coinciden · 5 discrepan**.
Tablero: N/P 5/9 · nivel 7/9 · fecha 5/9 · serie 1/9. Este parche **no inventa celdas nuevas** (la
lectura de fotos no se ha vuelto a correr); arregla las reglas para que la próxima corrida no tire
lecturas buenas, y deja la documentación y el paquete aplicable a tu versión.
