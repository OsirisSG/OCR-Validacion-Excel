# V-Matrix V15.10.1 · Parche acumulable + módulos piloto

**Fecha:** 13-10-2026 · **Estado:** PILOTO. No liberado para producción.

## Versiones y fuentes verificadas

- Código base del usuario: `OsirisSG/OCR-Validacion-Excel`, rama
  `codex/ocr-v15-8-1-organizacion`, commit `5fbef43bb4c2c9142327afd3f88e89b460aed6c5`.
- Referencia acumulada: `OsirisSG79/Parche_Temp`, subcarpeta
  `codigo_final_referencia`, commit `2aa4fc3a5c1f987572952cca17c14a17e7cc6cd4`.
- Los archivos de la referencia se verifican mediante SHA de blob Git ANTES
  de cualquier sustitución. Los datos de las carpetas de trabajo no se
  redistribuyen ni se abren durante la instalación.

## Instalación Windows — usar copia o rama nueva

1. **Cerrar V-Matrix y cualquier proceso OCR.** Crear backup completo de
   `.aprendizaje` y de las salidas usando SQLite backup si hay WAL activo;
   este instalador no crea respaldos de datos productivos.
2. Descomprimir este ZIP en carpeta temporal fuera de la raíz del código.
3. Si la base YA es V15.9.10 exacta, ejecutar:

   ```powershell
   python .\APLICAR_PARCHE_V15_10.py "C:\ruta\OCR-Validacion-Excel"
   python .\APLICAR_PARCHE_V15_10.py "C:\ruta\OCR-Validacion-Excel" --aplicar
   ```

   La primera ejecución es **simulación**; la segunda verifica todo, crea
   respaldo de código fuera de la raíz del repositorio y luego instala.

4. Si se usa la rama original V15.8.1, obtener la carpeta
   `codigo_final_referencia` del repositorio **Parche_Temp** (descargando
   manualmente su ZIP desde GitHub a un equipo autorizado) y ejecutar:

   ```powershell
   python .\APLICAR_PARCHE_V15_10.py "C:\ruta\OCR-Validacion-Excel" --base-ref "C:\descargas\Parche_Temp-main\codigo_final_referencia"
   python .\APLICAR_PARCHE_V15_10.py "C:\ruta\OCR-Validacion-Excel" --base-ref "C:\descargas\Parche_Temp-main\codigo_final_referencia" --aplicar
   ```

   Si no se dispone del ZIP de Parche_Temp y existe conexión autorizada,
   ejecutar primero `DESCARGAR_BASE_ONLINE.bat`. Esto descarga únicamente
   los 21 archivos publicados, desde un commit fijo, con hashes verificados;
   después emplear `--base-ref ".\BASE_REFERENCIA_V15910"`.

5. Pruebas una vez instalado en el **repo destino**:

   ```powershell
   python -m pytest pruebas/test_v1510_piloto.py -q
   python -m pytest pruebas/ -q
   node --test pruebas/*.cjs
   ```

   La última suite requiere Node instalado. El proyecto original puede
   requerir paquetes adicionales; no deben instalarse sin revisión offline.

## Revertir, sin perder el trabajo de ayer

El instalador imprime la carpeta `RESPALDO_VMATRIX_V1510_fecha` creada al
lado del repositorio. Para recuperar archivos de código:

```powershell
python .\APLICAR_PARCHE_V15_10.py "C:\ruta\OCR-Validacion-Excel" --revertir "C:\ruta\RESPALDO_VMATRIX_V1510_fecha"
```

Si algún archivo cambió después de instalar, se bloquea la reversión
hasta revisar manualmente las diferencias; no se pisan modificaciones nuevas.
Nunca se sobrescriben `.aprendizaje`, AVI, imágenes, SQLite, `.pth`, JSON de
validación, salidas Excel ni la plantilla institucional BMG.

## Qué se instala y qué ya está activo

| Componente | Cambio | ¿Conectado al flujo productivo? |
|---|---|---|
| Matriz dashboard | Sólo celdas de casos reales, sin cupos vacantes | **Sí**, tras aplicar |
| Matriz BMG | Se conserva su formato institucional existente | **Sí**, sin cambio |
| Hoja dinámica Excel | Utilidad aditiva para nueva salida sin alterar plantilla | **Solo ejecución explícita** |
| OCR por campo | Lecturas alternativas y conciliación por procedencia/fecha humana | **Sombra**, no altera Excel |
| Detección primer frame | Exploración de microindicios, continuidad, anti-flash | **Sombra**, no altera tiempos |
| Política multicámara | Duplicados, 3 cámaras, reloj común, incertidumbre y abstención | **Sombra**, no sustituye V15.9.10 |
| Auditoría `.aprendizaje` | Hash, integridad, tablas, recuentos read-only | **Solo ejecución explícita** |
| Evaluación | Métrica por caso y protección de test_sellado | **Solo ejecución explícita** |
| Skills | Seis procedimientos de control y verificación | Referencia para siguientes iteraciones |

## Pruebas funcionales opcionales de los módulos nuevos

Desde la raíz del repositorio:

```powershell
python -m utilidades.evidencia_apertura_v1510 "C:\datos\copia\camara.avi" --fps-adquisicion 5000 --roi 200 150 400 280 --salida "C:\informes\apertura_sombra.json"
python -m utilidades.auditoria_aprendizaje_v1510 "C:\copias\.aprendizaje" --salida "C:\informes\auditoria.json"
python -m utilidades.evaluacion_apertura_v1510 "C:\informes\etiquetas_sin_fuga.jsonl" --salida "C:\informes\precision.json"
python -m utilidades.matriz_excel_dinamica_v1510 --casos "C:\informes\filas_dashboard.json" --salida "C:\informes\matriz_dinamica.xlsx"
```

**No usar el primer tiempo que propone `evidencia_apertura_v1510` como tiempo
oficial.** Es una hipótesis que requiere contraste con frames humanos reales,
y el parámetro `--fps-adquisicion` debe provenir de evidencia externa válida,
no del FPS de reproducción de AVI.

## Qué queda pendiente del plan maestro V15.10

No se recibió la carpeta `.aprendizaje` ni los AVI/etiquetas humanas reservados;
por tanto **no hay auditoría real**, prueba ciega de exactitud, capacitación
OCR, modelo global validado ni verificación sobre el equipo Windows corporativo.
La integración automática del nuevo reconciliador de OCR en el pipeline,
verificador de videos en el frontend y autollenado oficial NO está habilitada:
activar esas funciones sin calibración humana falsearía la seguridad requerida.

Esta entrega es un avance verificable para V15.10.1 y prototipos de V15.10.2/3,
no las seis fases concluidas ni una promesa de precisión física 0.1 ms.
