"""Corrección auditable del libro: cirugía sobre el XML, no re-guardado.

Motivo: `openpyxl` reescribe el paquete completo (pierde matices de estilos, imágenes y
formato condicional). Aquí se cambia **solo** la celda indicada dentro de
`xl/worksheets/sheet1.xml` y se copian el resto de las partes byte a byte, de modo que
el diff del libro es exactamente lo declarado y se puede revisar.

Uso:
    python corregir_libro.py entrada.xlsx salida.xlsx correcciones.json [--aplicar]
    (sin --aplicar: solo enseña qué cambiaría)
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

HOJA = "xl/worksheets/sheet1.xml"


def _leer_shared(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    xml = z.read("xl/sharedStrings.xml").decode("utf-8")
    return [re.sub(r"<[^>]+>", "", trozo) for trozo in re.findall(r"<si>(.*?)</si>", xml, re.S)]


def _celda(xml: str, ref: str) -> re.Match | None:
    return re.search(r'<c r="%s"(?P<atributos>[^>]*?)(?:/>|>(?P<interior>.*?)</c>)' % ref, xml, re.S)


def _valor_actual(xml: str, ref: str, shared: list[str]):
    m = _celda(xml, ref)
    if not m:
        return None
    interior = m.group("interior") or ""
    v = re.search(r"<v>(.*?)</v>", interior)
    if not v:
        return None
    if 't="s"' in m.group("atributos"):
        return shared[int(v.group(1))]
    return v.group(1)


def _escribir(xml: str, ref: str, nuevo, shared: list[str]) -> tuple[str, str]:
    m = _celda(xml, ref)
    if not m:
        raise SystemExit(f"la celda {ref} no existe en {HOJA}")
    atributos = m.group("atributos") or ""
    if isinstance(nuevo, (int, float)) and not isinstance(nuevo, bool):
        reemplazo = f'<c r="{ref}"{atributos.replace(chr(32)+chr(116)+chr(61)+chr(34)+chr(115)+chr(34), "")}><v>{nuevo}</v></c>'
    else:
        if nuevo not in shared:
            raise SystemExit(f"'{nuevo}' no está en sharedStrings: se añadiría una cadena nueva y "
                             "eso cambia el paquete; se aborta a propósito")
        if 't="s"' not in atributos:
            atributos += ' t="s"'
        reemplazo = f'<c r="{ref}"{atributos}><v>{shared.index(nuevo)}</v></c>'
    return xml[:m.start()] + reemplazo + xml[m.end():], reemplazo


def corregir(entrada: str, salida: str, correcciones: list[dict], aplicar: bool) -> dict:
    with zipfile.ZipFile(entrada) as z:
        shared = _leer_shared(z)
        xml = z.read(HOJA).decode("utf-8")
        cambios = []
        for c in correcciones:
            antes = _valor_actual(xml, c["celda"], shared)
            if str(antes) != str(c["antes"]):
                raise SystemExit(f"{c['celda']}: el libro dice {antes!r} y se esperaba "
                                 f"{c['antes']!r}. El libro ha cambiado: no se toca.")
            xml, _ = _escribir(xml, c["celda"], c["despues"], shared)
            cambios.append({"celda": c["celda"], "antes": antes, "despues": c["despues"],
                            "motivo": c["motivo"], "evidencia": c["evidencia"]})
        if aplicar:
            with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as out:
                for item in z.infolist():
                    datos = xml.encode("utf-8") if item.filename == HOJA else z.read(item.filename)
                    out.writestr(item, datos)
    return {"cambios": cambios, "aplicado": bool(aplicar), "salida": salida if aplicar else None}


def verificar(original: str, corregido: str, cambios: list[dict]) -> dict:
    """Comprueba que el diff sea exactamente el declarado."""
    from openpyxl import load_workbook

    def celdas(ruta):
        hoja = load_workbook(ruta)["Versuchsmatrix"]
        return {c.coordinate: c.value for fila in hoja.iter_rows() for c in fila if c.value is not None}

    a, b = celdas(original), celdas(corregido)
    distintas = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
    esperadas = {c["celda"] for c in cambios}

    with zipfile.ZipFile(original) as z1, zipfile.ZipFile(corregido) as z2:
        partes_iguales = {n: z1.read(n) == z2.read(n) for n in z1.namelist()}
        faltan = set(z1.namelist()) ^ set(z2.namelist())
    formulas_a = sum(1 for v in a.values() if isinstance(v, str) and v.startswith("="))
    formulas_b = sum(1 for v in b.values() if isinstance(v, str) and v.startswith("="))
    return {
        "celdas_distintas": sorted(distintas),
        "coincide_con_lo_declarado": distintas == esperadas,
        "partes_byte_a_byte_iguales_excepto_la_hoja": all(
            v for n, v in partes_iguales.items() if n != HOJA),
        "partes_añadidas_o_perdidas": sorted(faltan),
        "formulas_antes": formulas_a, "formulas_despues": formulas_b,
        "imagenes_conservadas": all(n in z2.namelist() for n in
                                    ("xl/media/image1.png", "xl/media/image2.png")),
        "formato_condicional_conservado": len(load_workbook(corregido)["Versuchsmatrix"]
                                              .conditional_formatting._cf_rules) == 3,
    }


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 3:
        raise SystemExit(__doc__)
    correcciones = json.loads(Path(args[2]).read_text(encoding="utf-8"))
    resultado = corregir(args[0], args[1], correcciones, "--aplicar" in sys.argv)
    print(json.dumps(resultado, ensure_ascii=False, indent=1))
    if "--aplicar" in sys.argv:
        print(json.dumps(verificar(args[0], args[1], resultado["cambios"]),
                         ensure_ascii=False, indent=1))
