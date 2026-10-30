"""Política *aditiva* de apertura V15.10: sin auto-publicación por defecto.

El consenso legado de V15.9.10 permanece sin modificaciones. Este módulo
produce una segunda evaluación auditable que puede compararse en modo sombra.
"""
from __future__ import annotations
from collections import defaultdict
from statistics import median
from .sincronizacion_v1510 import numero_positivo, alinear_camara

VERSION = "15.10.1-shadow"
GRAVES = {"fps_incierto", "evento_al_inicio", "roi_incierta", "oclusion",
          "codec_corrupto", "overlay_contradictorio", "onset_ambiguo", "flash", "reflejo"}


def evaluar_camaras(camaras: list[dict], *, autoaceptacion_habilitada: bool = False,
                     soporte_minimo: int = 3) -> dict:
    """Exige 3 cámaras independientes con tiempo común verificado y mismo evento."""
    base = {"version_politica": VERSION, "estado": "propuesta_revisar", "tiempo_ms": None,
            "tiempo_propuesto_ms": None, "camaras_elegibles": [], "excluidas": [],
            "razones": [], "soporte": 0, "auto_confirmable": False,
            "publicable": False, "modo_sombra": True}
    if not isinstance(camaras, list):
        return {**base, "razones": ["entrada_invalida"]}
    vistas = []
    por_hash = set()
    por_id = set()
    referencias = set()
    for idx, c in enumerate(camaras):
        if not isinstance(c, dict):
            base["excluidas"].append({"indice": idx, "motivo": "registro_invalido"});continue
        cid = str(c.get("camara_id") or "").strip()
        huella = str(c.get("video_sha256") or "").strip()
        # Sin huella no sabemos si se está contando dos veces el mismo AVI.
        if not cid or not huella or cid in por_id or huella in por_hash:
            base["excluidas"].append({"indice": idx, "motivo": "camara_o_contenido_duplicado_o_sin_identidad"});continue
        por_id.add(cid); por_hash.add(huella)
        referencia = str((c.get("calibracion_temporal") or {}).get("referencia_id") or "").strip()
        if not referencia:
            base["excluidas"].append({"camara": cid, "motivo": "sin_referencia_comun_demostrada"});continue
        referencias.add(referencia)
        if c.get("misma_fase_evento") is not True or c.get("visibilidad") != "visible":
            base["excluidas"].append({"camara": cid, "motivo": "evento_no_comparable_o_no_visible"}); continue
        problemas = sorted(set(c.get("alertas") or ()) & GRAVES)
        t = c.get("tiempo_local_ms")
        if numero_positivo(c.get("fps_adquisicion")) is None or t is None or problemas:
            base["excluidas"].append({"camara": cid, "motivo": "calidad_no_aprobada", "alertas": problemas}); continue
        try:
            t = float(t)
            if t < 0: raise ValueError("t negativo")
        except (ValueError, TypeError):
            base["excluidas"].append({"camara": cid, "motivo": "tiempo_local_invalido"});continue
        al = alinear_camara(t, c.get("calibracion_temporal"))
        if not al["valido"]:
            base["excluidas"].append({"camara": cid, "motivo": al["motivo"]});continue
        fms = 1000.0 / float(c["fps_adquisicion"])
        try:
            inci = max(0.0, float(c.get("incertidumbre_ms", fms/2)))
            ajuste = max(0.0, float(al["incertidumbre_alineacion_ms"]))
        except (TypeError, ValueError):
            base["excluidas"].append({"camara": cid, "motivo": "incertidumbre_invalida"});continue
        vistas.append({"camara": cid, "tiempo": al["tiempo_global_ms"],
                       "resolucion": fms, "error": inci+ajuste})
    base["camaras_elegibles"] = [c["camara"] for c in vistas]
    if len(referencias) != 1:
        base["estado"] = "revisar_conflicto"
        base["razones"] = ["referencias_de_reloj_distintas"]
        return base
    if len(vistas) < max(3, soporte_minimo):
        base["razones"] = ["menos_de_tres_camaras_independientes_y_sincronizadas"]
        if vistas: base["tiempo_propuesto_ms"] = min(c["tiempo"] for c in vistas)
        return base
    # Compara intervalos de incertidumbre (no ventana mágica de 0.15 ms).
    candidatos = sorted(vistas, key=lambda c:c["tiempo"])
    for primero in candidatos:
        compatibles = [c for c in candidatos if abs(c["tiempo"]-primero["tiempo"]) <=
                       max(c["error"]+primero["error"], max(c["resolucion"],primero["resolucion"])/2)]
        if len(compatibles) >= max(3, soporte_minimo):
            base["soporte"] = len(compatibles)
            base["tiempo_propuesto_ms"] = min(c["tiempo"] for c in compatibles)
            base["intervalo_conjunto_ms"] = [min(c["tiempo"]-c["error"] for c in compatibles),
                                              max(c["tiempo"]+c["error"] for c in compatibles)]
            base["soporte_camaras"] = [c["camara"] for c in compatibles]
            base["auto_confirmable"] = len(compatibles) >= 3
            base["razones"] = ["tres_vistas_elegibles_y_relojes_verificados"]
            if autoaceptacion_habilitada:
                # REQUIERE adicionalmente calibración real de la política;
                # feature flag solo NO autoriza publicación en el piloto.
                base["razones"].append("publicacion_bloqueada_hasta_validacion_ciega")
            return base
    base["estado"] = "revisar_conflicto"
    base["tiempo_propuesto_ms"] = min(c["tiempo"] for c in vistas)
    base["razones"] = ["discordancia_temporal_fuera_de_incertidumbre"]
    return base
