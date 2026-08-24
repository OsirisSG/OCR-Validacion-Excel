# Verificación incorrecta del CLI del dashboard

- Fecha: 2026-08-23
- Intento: ejecutar `python dashboard/backend/app.py --help` para comprobar el
  comando documentado.
- Resultado: `app.py` no define un CLI con `argparse`; ignoró `--help` e intentó
  iniciar FastAPI. La instancia existente ya ocupaba `127.0.0.1:8000`.
- Causa: se trató el punto de entrada del servidor como un CLI convencional.
- Nuevo enfoque: validar sintaxis por compilación, comprobar el servidor con
  `GET /api/estado` y reservar `python dashboard/backend/app.py` únicamente para
  iniciar el servicio.

