"""Consolidación idempotente de ejecuciones OCR empresariales."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from utilidades.identidad import identidad_caso, proyecto_id


def _clave(fila: dict, documento: dict) -> str:
    """Canonicaliza también documentos V7 para una migración sin duplicados."""
    raiz = documento.get("raiz") or fila.get("raiz") or "proyecto"
    proyecto = fila.get("project_id") or documento.get("project_id") or proyecto_id(Path(str(raiz)))
    etapa = fila.get("tipo_st") or "SIN_ST"
    numero = fila.get("test_number") or (fila.get("metadata_ruta") or {}).get("test_number")
    nombre = fila.get("nombre") or fila.get("identificador") or numero or "caso"
    relativa = fila.get("ruta_relativa") or (fila.get("caso") or {}).get("ruta_relativa") or nombre
    if numero or relativa:
        return identidad_caso(str(proyecto), str(etapa), str(numero or ""), str(nombre), str(relativa))
    return str(fila.get("case_key") or f"{proyecto}|{etapa}|{nombre}")


def _marca(fila: dict) -> str:
    return str(fila.get("ultima_ejecucion") or fila.get("actualizado_en") or fila.get("generado_en") or "")


def _fusionar_historial(destino: dict, nuevo: dict) -> None:
    for campo in ("historial_ejecuciones", "historial_acciones"):
        vistos, salida = set(), []
        for item in [*(destino.get(campo) or []), *(nuevo.get(campo) or [])]:
            firma = repr(sorted(item.items())) if isinstance(item, dict) else repr(item)
            if firma not in vistos:
                vistos.add(firma); salida.append(deepcopy(item))
        if salida:
            destino[campo] = salida




def _marca_correccion(corr: dict | None) -> str:
    if not isinstance(corr, dict):
        return ""
    return str(corr.get("corregido_en") or corr.get("actualizado_en") or corr.get("creado_en") or "")


def _fusionar_correcciones_manuales(anterior: dict, nuevo: dict, preferir_nuevo: bool) -> tuple[dict, list[dict]]:
    """Fusiona por campo usando la fecha de la corrección, no la fecha de ejecución.

    Si dos correcciones tienen exactamente la misma marca temporal y valores distintos,
    conserva una de forma determinista pero registra el conflicto para revisión manual.
    """
    a = anterior.get("correcciones_manual_campos") or {}
    b = nuevo.get("correcciones_manual_campos") or {}
    salida, conflictos = {}, []
    for campo in sorted(set(a) | set(b)):
        ca, cb = a.get(campo), b.get(campo)
        if ca is None:
            salida[campo] = deepcopy(cb); continue
        if cb is None:
            salida[campo] = deepcopy(ca); continue
        ma, mb = _marca_correccion(ca), _marca_correccion(cb)
        if mb > ma:
            elegido = cb
        elif ma > mb:
            elegido = ca
        else:
            va, vb = ca.get("valor"), cb.get("valor")
            if va != vb:
                conflictos.append({"campo": campo, "marca": ma, "valor_anterior": va, "valor_nuevo": vb})
            elegido = cb if preferir_nuevo else ca
        salida[campo] = deepcopy(elegido)
    return salida, conflictos

def consolidar_documentos(documentos: list[dict]) -> dict:
    if not documentos:
        raise ValueError("No se proporcionaron ejecuciones para consolidar.")
    por_clave, orden = {}, []
    for doc in documentos:
        for fila in doc.get("resultados", []):
            clave = _clave(fila, doc)
            if clave not in por_clave:
                por_clave[clave] = deepcopy(fila); orden.append(clave); continue
            anterior = por_clave[clave]
            preferir_nuevo = _marca(fila) >= _marca(anterior)
            elegido, otro = (fila, anterior) if preferir_nuevo else (anterior, fila)
            combinado = deepcopy(elegido)
            _fusionar_historial(combinado, otro)
            manuales, conflictos = _fusionar_correcciones_manuales(anterior, fila, preferir_nuevo)
            if manuales:
                combinado["correcciones_manual_campos"] = manuales
                combinado.setdefault("campos", {})
                for campo, corr in manuales.items():
                    dato = deepcopy((combinado.get("campos") or {}).get(campo) or {})
                    dato.update({"valor": corr.get("valor"), "fuente": "correccion_manual_confirmada",
                                 "corregido_en": corr.get("corregido_en"), "corregido_por": corr.get("corregido_por")})
                    combinado["campos"][campo] = dato
            if conflictos:
                combinado["conflictos_correcciones_manual"] = conflictos
                for conflicto in conflictos:
                    campo = conflicto["campo"]
                    if campo in (combinado.get("campos") or {}):
                        combinado["campos"][campo]["requiere_revision"] = True
                        combinado["campos"][campo]["estado"] = "conflicto"
            por_clave[clave] = combinado
    base = deepcopy(documentos[-1])
    base["resultados"] = [por_clave[k] for k in orden]
    base["generado_en"] = datetime.now().isoformat(timespec="seconds")
    base["consolidacion"] = {"documentos": len(documentos), "casos": len(base["resultados"]),
                              "idempotente": True, "creada_en": base["generado_en"]}
    base["tipos_st"] = sorted({str(f.get("tipo_st")) for f in base["resultados"] if f.get("tipo_st")})
    return base
