# `documentos/logicas/` — copias de consulta

Estos `.py` son **copias** de los módulos que funcionan, puestas aquí para leerlas y reusarlas sin
abrir el árbol de código. **La versión viva es la del proyecto**, en su ruta normal:

| copia | módulo vivo |
|---|---|
| `protocolo_campos.py` | `utilidades/protocolo_campos.py` |
| `grabado_punteado.py` | `utilidades/grabado_punteado.py` |
| `tablero_campos.py` | `utilidades/tablero_campos.py` |
| `consenso_valores.py` | `utilidades/consenso_valores.py` |
| `lector_etiquetas.py` | `utilidades/lector_etiquetas.py` |
| `codigos_modulo.py` | `utilidades/codigos_modulo.py` |
| `pizarra.py` | `utilidades/pizarra.py` |
| `evidencia_tablero.py` | `evidencia_tablero.py` |
| `rellenar_desde_referencia.py` | `rellenar_desde_referencia.py` |
| `medir_contra_referencia.py` | `medir_contra_referencia.py` |
| `leer_parte_foto.py`, `leer_parte_por_parecido.py`, `fotos_parecidas.py`, `agregar_parte.py` | igual, en la raíz |

**No edites las copias**: no las importa nadie y los cambios se perderían en el siguiente parche.
Si hay que cambiar una lógica, se cambia en el módulo vivo y se vuelve a copiar.
`probar_parche_sobre_28.sh` comprueba el parche aplicándolo a un proyecto nacido en V16.0.28.
