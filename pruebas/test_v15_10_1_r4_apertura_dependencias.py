from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utilidades.evidencia_apertura import generar_candidatos
from utilidades.politica_apertura import decidir_apertura
from utilidades.sincronizacion_video import sincronizar_vistas
from utilidades.verificador_apertura import verificar_candidato


def _metricas():
    datos = []
    for i in range(7):
        tiene = i in {3, 4, 5}
        datos.append({
            "evidencia_debil": tiene,
            "detectado": tiene,
            "pixeles_ruptura": 3 if tiene else 0,
            "pixeles_grieta_nueva": 3 if tiene else 0,
            "pixeles_blanco_nuevo": 0,
            "componente_ruptura_px": 3 if tiene else 0,
            "min_pixeles_debil": 1,
            "min_componente_debil": 1,
            "centro_componente_norm": [0.55, 0.45] if tiene else None,
            "bbox_componente_norm": [0.54, 0.44, 0.56, 0.46] if tiene else None,
            "scores_fuentes": {"fisura": 0.02 if tiene else 0.0,
                               "tela_clara": 0.0, "reflejo": 0.0,
                               "abombamiento": 0.0, "bordes_nuevos": 0.001 if tiene else 0.0},
        })
    return datos


def test_dependencias_apertura_importables_y_no_vacias():
    for rel in [
        'utilidades/verificador_apertura.py',
        'utilidades/politica_apertura.py',
        'utilidades/sincronizacion_video.py',
    ]:
        path = ROOT / rel
        assert path.is_file(), rel
        assert path.stat().st_size > 0, rel


def test_verificador_y_politica_operan_en_modo_conservador():
    candidato = generar_candidatos(_metricas(), nbase=2, fps_adquisicion=5000)[0]
    revision = verificar_candidato(candidato, _metricas(), nbase=2)
    assert revision["auto_confirmable"] is False
    assert revision["probabilidad_calibrada"] is None
    decision = decidir_apertura(
        candidato=candidato,
        verificacion=revision,
        tiempo_verificado=False,
        auto_publicacion_habilitada=True,
        calibracion_validada=True,
        politica_aprobada=True,
    )
    assert decision["estado"] in {"propuesta_alta_confianza", "propuesta_revisar", "evidencia_corrobora"}
    assert decision["tiempo_ms"] is None
    assert decision["auto_confirmable"] is False


def _vista(camara: str, sha: str, onset: float, offset: float = 10.0):
    return {
        "camara_id": camara, "sha256": sha, "tiempo_video_ms": onset,
        "puntos_calibracion": [
            {"tiempo_video_ms": 0, "tiempo_referencia_ms": offset},
            {"tiempo_video_ms": 100, "tiempo_referencia_ms": 100 + offset},
            {"tiempo_video_ms": 200, "tiempo_referencia_ms": 200 + offset},
        ],
    }


def test_sincronizacion_conserva_consenso_y_excluye_duplicados():
    ok = sincronizar_vistas([_vista('A','a',90), _vista('B','b',90), _vista('C','c',90)])
    assert ok['estado'] == 'consenso_sincronizado'
    assert ok['soporte_independiente'] == 3
    dup = sincronizar_vistas([_vista('A','same',90), _vista('B','same',90), _vista('C','c',90)])
    assert dup['soporte_independiente'] == 2
    assert dup['consenso_sincronizado'] is False


def test_colores_validos_se_mantienen_para_tiempos_confirmados(monkeypatch):
    fake = types.ModuleType('configuracion')
    def evaluar_criterio(criterio, numero):
        verde = float(str(criterio['verde']).replace('<=','').strip())
        rojo = float(str(criterio['rojo']).replace('>','').strip())
        if numero <= verde:
            return 'verde'
        if numero > rojo:
            return 'rojo'
        return 'amarillo'
    fake.evaluar_criterio = evaluar_criterio
    monkeypatch.setitem(sys.modules, 'configuracion', fake)
    matriz = importlib.import_module('utilidades.matriz_apertura')
    criterio = matriz.criterio_desde_limites(6, 7)
    def celda(valor, ident):
        fila = {
            'id': ident, 'test_number': ident,
            'campos': {'opening_time_ms': {'valor': valor, 'estado': 'confirmado_manual', 'fuente_preferida': 'manual', 'confirmacion_manual': True, 'referencia_tiempo_valida': True, 'estado_tiempo': 'VALIDO'}},
        }
        return matriz.celda_caso(fila, criterio)
    assert celda(5.8, 'v')['estado'] == 'verde'
    assert celda(6.4, 'a')['estado'] == 'amarillo'
    assert celda(7.2, 'r')['estado'] == 'rojo'


def test_consenso_automatico_3_camaras_recupera_color_sin_relajar_conflictos(monkeypatch):
    from utilidades.resultado_caso import resolver_resultado_caso
    fila = {
        'id': 'auto-1', 'test_number': '1',
        'video_apertura': {
            'estado': 'primera_aparicion', 'estado_consenso': 'confirmado',
            'tiempo_ms': 5.8, 'soporte': 3, 'total_principales': 4,
            'referencia_tiempo_valida': True, 'estado_tiempo': 'VALIDO',
            'requiere_revision': False, 'revision_no_clasificada': False,
            'causas_revision_consolidado': [],
        },
        'campos': {'opening_time_ms': {
            'valor': '5.8', 'estado': 'extraido_video', 'fuente': 'video_airbag_consenso',
            'referencia_tiempo_valida': True, 'estado_tiempo': 'VALIDO',
        }},
    }
    canon = resolver_resultado_caso(fila)
    assert canon['apertura']['estado'] == 'AUTO_VERIFICABLE'
    assert canon['apertura']['tiempo_ms'] == 5.8
    assert canon['apertura']['auto_publicable'] is True

    fake = types.ModuleType('configuracion')
    def evaluar_criterio(criterio, numero):
        verde = float(str(criterio['verde']).replace('<=','').strip())
        rojo = float(str(criterio['rojo']).replace('>','').strip())
        if numero <= verde:
            return 'verde'
        if numero > rojo:
            return 'rojo'
        return 'amarillo'
    fake.evaluar_criterio = evaluar_criterio
    monkeypatch.setitem(sys.modules, 'configuracion', fake)
    matriz = importlib.import_module('utilidades.matriz_apertura')
    celda = matriz.celda_caso(fila, matriz.criterio_desde_limites(6, 7))
    assert celda['estado'] == 'verde'
    assert celda['opening_time_ms'] == 5.8


def test_consenso_incompleto_permanece_gris():
    from utilidades.resultado_caso import resolver_resultado_caso
    fila = {
        'id': 'auto-2', 'test_number': '2',
        'video_apertura': {
            'estado': 'primera_aparicion', 'estado_consenso': 'propuesto',
            'tiempo_ms': 5.8, 'soporte': 2, 'total_principales': 4,
            'referencia_tiempo_valida': True, 'estado_tiempo': 'VALIDO',
            'requiere_revision': True,
        },
        'campos': {'opening_time_ms': {
            'valor': '5.8', 'estado': 'extraido_video', 'fuente': 'video_airbag_consenso',
            'referencia_tiempo_valida': True, 'estado_tiempo': 'VALIDO',
            'requiere_revision': True,
        }},
    }
    canon = resolver_resultado_caso(fila)
    assert canon['apertura']['estado'] == 'PROPUESTA'
    assert canon['apertura']['tiempo_ms'] is None
    assert canon['apertura']['auto_publicable'] is False
