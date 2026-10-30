from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
required = [
    root / 'utilidades' / 'evidencia_apertura.py',
    root / 'dashboard' / 'frontend' / 'visor_precision.js',
    root / 'dashboard' / 'frontend' / 'index.html',
]
missing = [str(p.relative_to(root)) for p in required if not p.is_file()]
if missing:
    print('FALTAN ARCHIVOS: ' + ', '.join(missing))
    raise SystemExit(1)
html = required[2].read_text(encoding='utf-8')
pos_visor = html.find('visor_precision.js')
pos_app = html.find('app.js')
if pos_visor < 0 or pos_app < 0 or pos_visor > pos_app:
    print('ORDEN INCORRECTO: visor_precision.js debe cargarse antes de app.js')
    raise SystemExit(2)
print('DEPENDENCIAS_PRESENTES_Y_ORDEN_OK')
