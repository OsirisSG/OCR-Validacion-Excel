from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]


def test_identidad_visual_usa_activos_derivados_del_logo():
    frontend = RAIZ / "dashboard" / "frontend"
    html = (frontend / "index.html").read_text(encoding="utf-8")
    js = (frontend / "app.js").read_text(encoding="utf-8")
    for nombre in ("logo_original.jpeg", "logo_claro.png", "logo_oscuro.png", "logo_icono.png", "favicon.png"):
        assert (frontend / "assets" / nombre).is_file()
    assert 'assets/favicon.png' in html
    assert 'assets/logo_oscuro.png' in js
    assert 'assets/logo_claro.png' in js


def test_configuracion_persistencia_rapida_preserva_limites():
    import yaml
    cfg = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
    persistencia = cfg["persistencia"]
    assert 0.05 <= float(persistencia["checkpoint_debounce_segundos"]) <= 1.0
    assert 0.1 <= float(persistencia["excel_debounce_segundos"]) <= 2.0
    assert float(persistencia["excel_latencia_max_segundos"]) >= float(persistencia["excel_debounce_segundos"])


def test_hash_archivo_reutiliza_resultado_si_archivo_no_cambio(monkeypatch, tmp_path):
    import builtins
    import aprendizaje

    imagen = tmp_path / "imagen.bin"
    imagen.write_bytes(b"OCR" * 1024 * 64)
    primero = aprendizaje.hash_archivo(imagen)
    abrir_real = builtins.open
    lecturas = {"n": 0}

    def contar_open(*args, **kwargs):
        if Path(args[0]) == imagen:
            lecturas["n"] += 1
        return abrir_real(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", contar_open)
    segundo = aprendizaje.hash_archivo(imagen)
    assert segundo == primero
    assert lecturas["n"] == 0
