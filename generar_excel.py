"""
generar_excel.py — Fase 3: consolidación en Excel maestro + matriz de cumplimiento.

Propósito
---------
Lee `validacion_resultados.json` (Fase 2) y genera `resultado_maestro.xlsx`
con dos hojas:
  1. "Estructura completa": una fila por carpeta procesada con toda la evidencia.
  2. "Matriz de cumplimiento": el semáforo verde/amarillo/rojo.

El semáforo se construye DINÁMICAMENTE desde reglas_cumplimiento.yaml:
- criterios numéricos continuos (confianza_ocr) → ColorScaleRule con extremos
  en los umbrales del YAML;
- criterios categóricos (coincidencia_texto) → CellIsRule con relleno por valor;
- columna "Semáforo global" = el color más restrictivo entre criterios
  (evaluado con el mismo motor de reglas que usa el dashboard).

Ningún rango está fijo en el código: cambiar el YAML cambia Excel y dashboard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from configuracion import (RAIZ_PROYECTO, cargar_config, cargar_reglas,
                           clasificar, estructura_regla)
from aprendizaje import GestorAprendizaje, hash_archivo
from plantilla_empresarial import generar_desde_plantilla

COLUMNAS = [
    ("Ruta", 46), ("Identificador", 18), ("Variante", 9),
    ("Tipos de archivo", 30), ("Imágenes procesadas", 12),
    ("Texto de todas las imágenes (OCR)", 52), ("Texto etiqueta (OCR)", 34),
    ("Texto referencia (OCR)", 34), ("Resultado comparación", 20),
    ("Revisión", 15),
    ("Confianza OCR (%)", 12), ("QR detectado", 11),
    ("Anomalías Fase 0", 22), ("Observaciones", 34),
]

COLUMNAS_MATRIZ = [
    ("Ruta", 46), ("Identificador", 18), ("Confianza OCR (%)", 12),
    ("Coincidencia texto", 22), ("Semáforo global", 16),
]

COLUMNAS_TEXTOS = [
    ("Carpeta", 24), ("Ruta carpeta", 42), ("Imagen", 28), ("Rol", 20),
    ("Origen", 16), ("Revisión", 15), ("Orden", 8), ("Texto", 60), ("Confianza (%)", 13),
    ("X", 9), ("Y", 9), ("Ancho", 9), ("Alto", 9),
]

COLUMNAS_REVISION = [
    ("Tipo", 16), ("Grupo", 24), ("Elemento", 30), ("Resultado", 24),
    ("Revisión", 15), ("Quitado del listado", 18), ("Actualizado", 22),
]

ETIQUETAS_REVISION = {
    "por_revisar": "Por revisar",
    "parcial": "Revisión parcial",
    "casi_listo": "Casi listo",
    "completada": "Completada",
}


def _hex_a_fill(hex_color: str) -> PatternFill:
    """'#22c55e' -> PatternFill aRGB sólido (openpyxl exige canal alfa)."""
    return PatternFill(start_color="FF" + hex_color.lstrip("#"),
                       end_color="FF" + hex_color.lstrip("#"), fill_type="solid")


def _resumen_tipos(tipos: dict) -> str:
    partes = []
    for cat, archivos in sorted(tipos.items()):
        partes.append(f"{len(archivos)} {cat}")
    return ", ".join(partes) if partes else "—"


def _id_carpeta(fila: dict) -> str:
    return hashlib.sha256(
        str(fila.get("ruta") or fila.get("nombre") or "").encode("utf-8")).hexdigest()[:16]


def _estado_inicial_carpeta(fila: dict) -> str:
    resultado = fila.get("comparacion", {}).get("resultado")
    if resultado == "sin_procesar":
        return "por_revisar"
    return "casi_listo" if resultado == "coincidencia_total" else "parcial"


def _estado_inicial_externa(fila: dict) -> str:
    completa = (bool(fila.get("coincidencia_exacta")) if fila.get("tipo") == "codigo"
                else float(fila.get("cobertura") or 0) >= 1.0)
    if completa:
        return "casi_listo"
    return "parcial" if fila.get("tokens") or fila.get("lineas_texto") else "por_revisar"


def _revision_texto(estado: str) -> str:
    return ETIQUETAS_REVISION.get(estado, ETIQUETAS_REVISION["por_revisar"])


def _texto_fila(fila: dict, anotaciones_por_ruta: dict | None = None,
                revisiones: dict | None = None) -> dict:
    """Convierte una fila de validacion_resultados en valores de celda."""
    et = fila.get("etiqueta") or {}
    ref = fila.get("referencia") or {}
    et_ocr = et.get("resultado_ocr") or {}
    ref_ocr = ref.get("resultado_ocr") or {}
    et_tokens = et_ocr.get("texto_completo") or " | ".join(
        t["texto"] for t in et_ocr.get("tokens", []))
    ref_tokens = ref_ocr.get("texto_completo") or " | ".join(
        t["texto"] for t in ref_ocr.get("tokens", []))
    imagenes = fila.get("imagenes") or []
    anotaciones_por_ruta = anotaciones_por_ruta or {}
    bloques_imagen = []
    for item in imagenes:
        ruta_item = str(item["ruta"])
        texto = (item.get("resultado_ocr") or {}).get("texto_completo") or "—"
        manuales = anotaciones_por_ruta.get(ruta_item, [])
        if manuales:
            texto += "\n" + "\n".join(
                f"[REGIÓN MANUAL {a['bbox']}] {a['texto_correcto']}" for a in manuales)
        bloques_imagen.append(
            f"[{item.get('nombre') or Path(ruta_item).name} · {item.get('rol', 'imagen')}]\n{texto}")
    texto_imagenes = "\n\n".join(bloques_imagen)
    comparacion = fila["comparacion"]["resultado"]
    revision = (revisiones or {}).get(("carpeta", _id_carpeta(fila)))
    revision_estado = (revision or {}).get("estado", _estado_inicial_carpeta(fila))
    return {
        "Ruta": fila["ruta"],
        "Identificador": (f"{fila.get('prefijo_numerico')}_{fila.get('nomenclatura')}"
                          if fila.get("prefijo_numerico") and fila.get("nomenclatura")
                          else fila.get("identificador") or fila["nombre"]),
        "Variante": fila.get("variante") or "—",
        "Tipos de archivo": _resumen_tipos(fila.get("tipos_archivo", {})),
        "Imágenes procesadas": len(imagenes) if imagenes else int(bool(et)) + int(bool(ref)),
        "Texto de todas las imágenes (OCR)": texto_imagenes or et_tokens or ref_tokens or "—",
        "Texto etiqueta (OCR)": et_tokens or "—",
        "Texto referencia (OCR)": ref_tokens or "—",
        "Resultado comparación": comparacion,
        "Revisión": _revision_texto(revision_estado),
        "Confianza OCR (%)": fila.get("confianza_ocr_pct"),
        "QR detectado": "Sí" if fila.get("qr_detectado") else "No",
        "Anomalías Fase 0": fila.get("anomalia_fase0") or "",
        "Observaciones": "; ".join(fila.get("observaciones", [])),
    }


def generar_excel(ruta_validacion: str | Path | None = None,
                  ruta_salida: str | Path | None = None,
                  config: dict | None = None,
                  reglas: dict | None = None,
                  ruta_plantilla: str | Path | None = None) -> Path:
    """Genera resultado_maestro.xlsx. Retorna la ruta del archivo creado."""
    config = config or cargar_config()
    reglas = reglas or cargar_reglas()
    f3 = config.get("fase3", {})
    ruta_validacion = Path(ruta_validacion) if ruta_validacion else RAIZ_PROYECTO / "validacion_resultados.json"
    ruta_salida = Path(ruta_salida) if ruta_salida else RAIZ_PROYECTO / f3.get("archivo_salida", "resultado_maestro.xlsx")

    with open(ruta_validacion, "r", encoding="utf-8") as f:
        datos = json.load(f)

    plantilla_config = ruta_plantilla or f3.get("plantilla_empresarial")
    if datos.get("perfil") == "empresarial" and plantilla_config:
        plantilla = Path(str(plantilla_config).strip().strip('"\''))
        if not plantilla.is_absolute():
            plantilla = RAIZ_PROYECTO / plantilla
        if not plantilla.is_file():
            raise FileNotFoundError(f"No se encontró la plantilla Excel: {plantilla}")
        return generar_desde_plantilla(plantilla, ruta_salida, datos.get("resultados", []))

    try:
        from pruebas_externas import cargar as cargar_externas
        datos_externos = cargar_externas(config)
    except (FileNotFoundError, OSError, ValueError):
        datos_externos = {"resultados": []}

    rutas_imagen = [str(item["ruta"])
                    for fila in datos.get("resultados", [])
                    for item in fila.get("imagenes", [])]
    rutas_externas = [str(fila["ruta"])
                      for fila in datos_externos.get("resultados", [])
                      if fila.get("ruta") and Path(fila["ruta"]).is_file()]
    rutas_consulta = [*rutas_imagen, *rutas_externas]
    gestor = GestorAprendizaje(config)
    anotaciones = gestor.listar_anotaciones(rutas_consulta)
    revisiones = gestor.listar_revisiones()
    anotaciones_por_hash: dict[str, list[dict]] = {}
    for anotacion in anotaciones:
        anotaciones_por_hash.setdefault(anotacion["imagen_hash"], []).append(anotacion)
    anotaciones_por_ruta: dict[str, list[dict]] = {}
    for ruta in rutas_consulta:
        try:
            if Path(ruta).is_file():
                anotaciones_por_ruta[ruta] = anotaciones_por_hash.get(hash_archivo(ruta), [])
        except OSError:
            pass

    colores = config.get("colores", {})
    c_verde, c_amarillo, c_rojo = (colores.get("verde", "#22c55e"),
                                   colores.get("amarillo", "#f59e0b"),
                                   colores.get("rojo", "#ef4444"))
    criterios = reglas.get("criterios", {})

    wb = Workbook()

    # ---------------------------------------------------------------- Hoja 1
    ws = wb.active
    ws.title = f3.get("hoja_estructura", "Estructura completa")
    estilo_encabezado = Font(bold=True, color="FFFFFF")
    fill_encabezado = PatternFill(start_color="FF1F2937", end_color="FF1F2937", fill_type="solid")
    for col, (titulo, ancho) in enumerate(COLUMNAS, start=1):
        celda = ws.cell(row=1, column=col, value=titulo)
        celda.font = estilo_encabezado
        celda.fill = fill_encabezado
        ws.column_dimensions[get_column_letter(col)].width = ancho
    ws.freeze_panes = "A2"
    for fila_datos in datos.get("resultados", []):
        ws.append([_texto_fila(fila_datos, anotaciones_por_ruta, revisiones)[t]
                   for t, _ in COLUMNAS])
        ws.row_dimensions[ws.max_row].height = 60
        for celda in ws[ws.max_row]:
            celda.alignment = Alignment(vertical="top", wrap_text=True)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNAS))}{ws.max_row}"

    # ---------------------------------------------------------------- Hoja 2
    wm = wb.create_sheet(f3.get("hoja_matriz", "Matriz de cumplimiento"))
    for col, (titulo, ancho) in enumerate(COLUMNAS_MATRIZ, start=1):
        celda = wm.cell(row=1, column=col, value=titulo)
        celda.font = estilo_encabezado
        celda.fill = fill_encabezado
        wm.column_dimensions[get_column_letter(col)].width = ancho
    wm.freeze_panes = "A2"

    col_conf = next(i for i, (t, _) in enumerate(COLUMNAS_MATRIZ, start=1)
                    if "Confianza" in t)
    col_coinc = next(i for i, (t, _) in enumerate(COLUMNAS_MATRIZ, start=1)
                     if "Coincidencia" in t)
    col_semaforo = next(i for i, (t, _) in enumerate(COLUMNAS_MATRIZ, start=1)
                        if "Semáforo" in t)

    fila_excel = 2
    for fila_datos in datos.get("resultados", []):
        valores = _texto_fila(fila_datos, anotaciones_por_ruta, revisiones)
        conf = valores["Confianza OCR (%)"]
        coinc = valores["Resultado comparación"]
        clasif = clasificar(conf, coinc, reglas)
        semaforo = clasif.get("semaforo_global") or "sin clasificar"

        wm.cell(row=fila_excel, column=1, value=valores["Ruta"])
        wm.cell(row=fila_excel, column=2, value=valores["Identificador"])
        wm.cell(row=fila_excel, column=col_conf, value=conf if conf is not None else "—")
        wm.cell(row=fila_excel, column=col_coinc, value=coinc)
        celda_semaforo = wm.cell(row=fila_excel, column=col_semaforo, value=semaforo)
        if semaforo in ("verde", "amarillo", "rojo"):
            celda_semaforo.fill = _hex_a_fill(colores[semaforo])
            celda_semaforo.font = Font(bold=True, color="FFFFFF")
        celda_semaforo.alignment = Alignment(horizontal="center")
        fila_excel += 1

    ultima = fila_excel - 1

    # --- Semáforo NUMÉRICO continuo (ColorScaleRule) desde el YAML ------------
    regla_conf = estructura_regla(criterios["confianza_ocr"]["amarillo"])
    if regla_conf["tipo"] == "rango":
        lim_inferior, lim_superior = regla_conf["min"], regla_conf["max"] + 1
    else:  # fallback defensivo si el YAML cambia a operadores
        verde = estructura_regla(criterios["confianza_ocr"]["verde"])
        rojo = estructura_regla(criterios["confianza_ocr"]["rojo"])
        lim_superior = verde.get("valor", 90)
        lim_inferior = rojo.get("valor", 70)
    rango_conf = f"{get_column_letter(col_conf)}2:{get_column_letter(col_conf)}{max(ultima, 3)}"
    wm.conditional_formatting.add(rango_conf, ColorScaleRule(
        start_type="num", start_value=lim_inferior, start_color=c_rojo.lstrip("#"),
        mid_type="num", mid_value=(lim_inferior + lim_superior) / 2, mid_color=c_amarillo.lstrip("#"),
        end_type="num", end_value=lim_superior, end_color=c_verde.lstrip("#"),
    ))

    # --- Semáforo CATEGÓRICO (CellIsRule) desde el YAML ------------------------
    rango_coinc = f"{get_column_letter(col_coinc)}2:{get_column_letter(col_coinc)}{max(ultima, 3)}"
    for color in ("verde", "amarillo", "rojo"):
        estruct = estructura_regla(criterios["coincidencia_texto"][color])
        if estruct["tipo"] != "categorico":
            continue
        for valor in estruct["valores"]:
            wm.conditional_formatting.add(rango_coinc, CellIsRule(
                operator="equal", formula=[f'"{valor}"'], fill=_hex_a_fill(colores[color])))

    # ------------------------------------------------ Hoja 3: carpeta → imagen → región
    wt = wb.create_sheet(f3.get("hoja_textos", "Textos por imagen"))
    for col, (titulo, ancho) in enumerate(COLUMNAS_TEXTOS, start=1):
        celda = wt.cell(row=1, column=col, value=titulo)
        celda.font = estilo_encabezado
        celda.fill = fill_encabezado
        wt.column_dimensions[get_column_letter(col)].width = ancho
    wt.freeze_panes = "A2"
    for fila_datos in datos.get("resultados", []):
        inicio_grupo = wt.max_row + 1
        revision = revisiones.get(("carpeta", _id_carpeta(fila_datos))) or {}
        estado_revision = revision.get("estado", _estado_inicial_carpeta(fila_datos))
        revision_texto = _revision_texto(estado_revision)
        for item in fila_datos.get("imagenes", []):
            ruta_item = str(item["ruta"])
            nombre_imagen = item.get("nombre") or Path(ruta_item).name
            ocr = item.get("resultado_ocr") or {}
            lineas = ocr.get("lineas_texto") or []
            if not lineas and ocr.get("texto_completo"):
                lineas = [{"texto": ocr["texto_completo"], "bbox": None,
                           "confianza": ocr.get("confianza_media")}]
            for orden, linea in enumerate(lineas, start=1):
                bbox = linea.get("bbox") or [None] * 4
                conf = linea.get("confianza")
                wt.append([
                    fila_datos.get("nombre"), fila_datos.get("ruta"), nombre_imagen,
                    item.get("rol", "imagen"), "OCR", revision_texto, orden,
                    linea.get("texto_original") or linea.get("texto"),
                    round(conf * 100, 2) if conf is not None else None, *bbox,
                ])
            for orden, anotacion in enumerate(
                    anotaciones_por_ruta.get(ruta_item, []), start=1):
                wt.append([
                    fila_datos.get("nombre"), fila_datos.get("ruta"), nombre_imagen,
                    item.get("rol", "imagen"), "Manual", revision_texto, orden,
                    anotacion["texto_correcto"], 100.0, *anotacion["bbox"],
                ])
        for numero_fila in range(inicio_grupo, wt.max_row + 1):
            wt.row_dimensions[numero_fila].outlineLevel = 1
            for celda in wt[numero_fila]:
                celda.alignment = Alignment(vertical="top", wrap_text=True)
    wt.sheet_properties.outlinePr.summaryBelow = True
    wt.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNAS_TEXTOS))}{max(wt.max_row, 1)}"

    # Las pruebas complejas se agregan al mismo inventario de textos.
    for externa in datos_externos.get("resultados", []):
        revision = revisiones.get(("externa", externa["id"])) or {}
        estado_revision = revision.get("estado", _estado_inicial_externa(externa))
        lineas = externa.get("lineas_texto") or ([{"texto": externa.get("texto_completo")}]
                                                  if externa.get("texto_completo") else [])
        for orden, linea in enumerate(lineas, start=1):
            bbox = linea.get("bbox") or [None] * 4
            conf = linea.get("confianza")
            wt.append([
                "Pruebas complejas", "Banco externo", externa.get("imagen"),
                externa.get("tipo"), "OCR externo",
                _revision_texto(estado_revision),
                orden, linea.get("texto"),
                round(conf * 100, 2) if conf is not None else None, *bbox,
            ])
        for orden, anotacion in enumerate(
                anotaciones_por_ruta.get(str(externa.get("ruta") or ""), []), start=1):
            wt.append([
                "Pruebas complejas", "Banco externo", externa.get("imagen"),
                externa.get("tipo"), "Manual externo",
                _revision_texto(estado_revision), orden,
                anotacion["texto_correcto"], 100.0, *anotacion["bbox"],
            ])

    # ---------------------------------------------- Hoja 4: bandeja unificada
    wr = wb.create_sheet(f3.get("hoja_revision", "Bandeja de revisión"))
    for col, (titulo, ancho) in enumerate(COLUMNAS_REVISION, start=1):
        celda = wr.cell(row=1, column=col, value=titulo)
        celda.font = estilo_encabezado
        celda.fill = fill_encabezado
        wr.column_dimensions[get_column_letter(col)].width = ancho
    wr.freeze_panes = "A2"
    for fila_datos in datos.get("resultados", []):
        item_id = _id_carpeta(fila_datos)
        revision = revisiones.get(("carpeta", item_id)) or {}
        resultado = fila_datos["comparacion"]["resultado"]
        estado_revision = revision.get("estado", _estado_inicial_carpeta(fila_datos))
        wr.append(["Carpeta", fila_datos.get("nombre"),
                   fila_datos.get("identificador") or fila_datos.get("nombre"), resultado,
                   _revision_texto(estado_revision),
                   "Sí" if revision.get("oculto") else "No", revision.get("actualizado_en")])
    for externa in datos_externos.get("resultados", []):
        revision = revisiones.get(("externa", externa["id"])) or {}
        estado_revision = revision.get("estado", _estado_inicial_externa(externa))
        resultado = ("Código exacto" if externa.get("coincidencia_exacta") else
                     f"Cobertura {round(float(externa.get('cobertura') or 0) * 100, 1)}%")
        wr.append(["Prueba compleja", "Pruebas complejas", externa.get("imagen"), resultado,
                   _revision_texto(estado_revision),
                   "Sí" if revision.get("oculto") else "No", revision.get("actualizado_en")])
    wr.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNAS_REVISION))}{max(wr.max_row, 1)}"

    wb.save(ruta_salida)
    return ruta_salida


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fase 3: generar Excel maestro.")
    parser.add_argument("--validacion", default=None, help="Ruta de validacion_resultados.json.")
    parser.add_argument("--salida", default=None, help="Ruta del xlsx de salida.")
    args = parser.parse_args()
    ruta = generar_excel(args.validacion, args.salida)
    print(f"Excel maestro generado en: {ruta}")
