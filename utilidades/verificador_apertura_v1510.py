"""Verificación adversarial sobre métricas independientes, no certificación de IA.

La salida es apta para modo sombra: evidencia a favor/en contra y candidatos.
"""
from __future__ import annotations
VERSION = "15.10.1"


def verificar_candidatos(metricas: list[dict], indices: list[int], *,
                        max_candidatos: int = 3, minimo_futuro: int = 2) -> dict:
    if not isinstance(metricas, list):
        raise TypeError("metricas debe ser una secuencia de diccionarios")
    resultados = []
    for idx in sorted(set(i for i in indices if isinstance(i, int) and not isinstance(i,bool))):
        favor, contra = [], []
        if idx <= 0 or idx >= len(metricas):
            contra.append("sin_frame_previo_o_fuera_de_clip")
            resultados.append({"frame": idx, "estado": "rechazado", "razones_a_favor": [],
                               "razones_en_contra": contra, "version_verificador": VERSION});continue
        item = metricas[idx]
        if item.get("novedad_local", 0) > 0:
            favor.append("aparicion_local_nueva")
        else:
            contra.append("sin_novedad_local")
        if item.get("flash_global"):
            contra.append("flash_global_fuera_de_roi")
        if item.get("registro_deficiente"):
            contra.append("registro_escena_no_confiable")
        if item.get("overlay"):
            contra.append("coincide_con_texto_overlay")
        if item.get("baseline_contaminado"):
            contra.append("baseline_con_evento_preexistente")
        if idx >= 2 and any(metricas[j].get("novedad_local", 0) > item.get("novedad_local", 0) * 0.65
                            for j in range(max(0,idx-2),idx)):
            contra.append("posible_indicio_anterior")
        futuras = metricas[idx+1:idx+1+minimo_futuro]
        if len(futuras) < minimo_futuro:
            contra.append("video_truncado_sin_confirmacion")
        elif all(x.get("persistencia_local", 0) > 0 for x in futuras):
            favor.append("continuidad_en_fotogramas_posteriores")
        else:
            contra.append("cambio_transitorio_o_sin_continuidad")
        estado = "corroborado_en_sombra" if len(favor) == 2 and not contra else "propuesta_revisar"
        resultados.append({"frame": idx, "estado": estado, "razones_a_favor": favor,
                           "razones_en_contra": contra, "version_verificador": VERSION})
    corroborados = [r for r in resultados if r["estado"]=="corroborado_en_sombra"]
    pendientes = [r for r in resultados if r["estado"]!="corroborado_en_sombra"]
    ordenados = corroborados + pendientes
    return {"version_verificador": VERSION, "modo_sombra": True,
            "top_candidatos": ordenados[:max_candidatos],
            "inicio_sugerido_frame": (corroborados[0]["frame"] if corroborados else None),
            "intervalo_frames": ([min(r["frame"] for r in resultados),max(r["frame"] for r in resultados)]
                                 if resultados else None),
            "auto_publicable": False}
