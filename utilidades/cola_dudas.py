"""Cola de dudas sobre un libro abierto: qué falta, qué opciones hay y qué se decide.

Aquí vive el estado del panel (filas del libro, dudas, decisiones y silencios) sin nada de
web, para que se pueda usar desde la consola, desde las pruebas o desde la página.
`panel_confirmacion.py` es sólo la cara visible.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from utilidades import cabeceras_excel as ce
from utilidades.dudas_y_opciones import (CAMPOS_RELLENABLES, aplicar_decisiones,
                                         construir_dudas, resumen_dudas)


class DudaDesconocida(LookupError):
    """Se pidió decidir sobre una duda que no está en la lista."""


class NadaQueGuardar(ValueError):
    """No hay ninguna decisión pendiente que escribir."""


COLUMNAS_LECTURA = {
    "week": 1, "test_reason": 2, "test_number": 3, "test_date": 4, "test_place": 5,
    "temperature_condition": 6, "module_part_number": 7, "module_version": 8,
    "module_serial_number": 9, "module_date": 10, "engineering_level": 11, "delay_ms": 12,
    "inflator_type": 13, "inflator_supplier": 14, "dashboard_part_number": 15,
    "dashboard_serial_number": 16, "dashboard_date": 17,
    "dashboard_engineering_level": 18, "dashboard_supplier": 20, "laser_opening": 19,
}


class Estado:
    """Todo lo que el panel sabe del libro abierto: filas, dudas y decisiones."""

    def __init__(self, libro: Path, lecturas: dict, hoja: str | None = None,
                 mapa: dict[str, int] | None = None):
        self.libro = libro
        self.lecturas = lecturas
        self.hoja = hoja
        self.mapa = mapa or {}
        self.decisiones: dict[str, dict] = {}
        self.ultimo_guardado: dict | None = None
        self.sin_numero: list[int] = []
        # «no lo tengo» se recuerda entre sesiones: la duda no vuelve a preguntar
        self.archivo_silencio = libro.with_suffix(libro.suffix + ".silencio.json")
        self.silenciadas: dict[str, dict] = (
            json.loads(self.archivo_silencio.read_text(encoding="utf-8"))
            if self.archivo_silencio.is_file() else {})
        self._cargar()

    def _cargar(self) -> None:
        from openpyxl import load_workbook

        wb = load_workbook(self.libro, data_only=True)
        ws = wb[self.hoja] if self.hoja else wb[wb.sheetnames[0]]
        self.hoja = ws.title
        self.filas: dict[str, dict] = {}
        por_fila = {fila: caso for caso, fila in self.mapa.items()}
        # el bloque de casos va de la primera a la última fila con número; lo de debajo
        # (promedios, evaluaciones) no es un caso y no se toca
        numeradas = [f for f in range(8, ws.max_row + 1)
                     if isinstance(ws.cell(f, 3).value, (int, float))
                     or (isinstance(ws.cell(f, 3).value, str)
                         and ws.cell(f, 3).value.strip().isdigit())]
        limites = numeradas + list(por_fila)
        inicio, fin = (min(limites), max(limites)) if limites else (8, 7)
        self.sin_numero = []
        for fila in range(inicio, fin + 1):
            numero = ws.cell(fila, 3).value
            if numero in (None, "") and fila not in por_fila:
                self.sin_numero.append(fila)
                continue
            if numero in (None, ""):
                caso = str(por_fila[fila])
            else:
                caso = str(int(numero)) if isinstance(numero, (int, float)) else str(numero).strip()
            self.filas[caso] = {"fila": fila,
                                **{campo: ws.cell(fila, col).value
                                   for campo, col in COLUMNAS_LECTURA.items()}}
        self.columnas = {e.clave: e.columna for e in
                         ce.resolver_cabeceras(ce.leer_cabeceras(ws)).encabezados
                         if e.estado == "resuelta"}
        self.recalcular()

    def recalcular(self) -> None:
        self.dudas = construir_dudas(self.filas, self.lecturas, columnas=self.columnas,
                                     campos=tuple(c for c in CAMPOS_RELLENABLES
                                                  if c in self.columnas))
        self.por_id = {d["id"]: d for d in self.dudas}
        self.silenciadas_visibles = [i for i in self.silenciadas if i in self.por_id]
        self.dudas = [d for d in self.dudas if d["id"] not in self.silenciadas]

    def decidir(self, id_duda: str, valor) -> dict:
        duda = self.por_id.get(id_duda)
        if not duda:
            raise DudaDesconocida(f"no existe la duda {id_duda}")
        if valor in (None, ""):
            self.silenciadas[id_duda] = {"caso": duda["caso"], "campo": duda["campo"],
                                         "motivo": duda["motivo"],
                                         "cuando": datetime.now().isoformat(timespec="seconds")}
            self.archivo_silencio.write_text(json.dumps(self.silenciadas, ensure_ascii=False,
                                                        indent=1), encoding="utf-8")
            self.recalcular()
            return {"id": id_duda, "valor": None, "silenciada": True}
        self.decisiones[id_duda] = {
            "id": id_duda, "caso": duda["caso"], "fila": self.filas[duda["caso"]]["fila"],
            "campo": duda["campo"], "valor": valor,
            "fuente": next((o["fuente"] for o in duda["opciones"]
                            if str(o["valor"]) == str(valor)), "manual"),
            "opciones_descartadas": [o["valor"] for o in duda["opciones"]
                                     if str(o["valor"]) != str(valor)],
            "motivo_de_la_duda": duda["motivo"],
        }
        return self.decisiones[id_duda]

    def guardar(self) -> dict:
        pendientes = [d for i, d in self.decisiones.items() if i in self.por_id]
        if not pendientes:
            raise NadaQueGuardar("no hay ninguna decisión que guardar")
        salida = self.libro.with_name(f"{self.libro.stem}_CONFIRMADO{self.libro.suffix}")
        diario = (self.libro.parent / ".panel" /
                  f"decisiones_{datetime.now():%Y%m%d_%H%M%S}.json")
        registro = aplicar_decisiones(self.libro, pendientes, ruta_salida=salida,
                                      hoja=self.hoja, diario=diario)
        self.ultimo_guardado = {"salida": str(salida), "diario": str(diario),
                                "escritos": len(registro["escritos"]),
                                "omitidos": len(registro["omitidos"]),
                                "detalle_escritos": registro["escritos"],
                                "detalle_omitidos": registro["omitidos"]}
        # el libro guardado pasa a ser el que se sigue editando, para no perder lo hecho
        shutil.copy2(salida, self.libro)
        self._cargar()
        self.decisiones.clear()
        self.ultimo_guardado["dudas_restantes"] = len(self.dudas)
        return self.ultimo_guardado
