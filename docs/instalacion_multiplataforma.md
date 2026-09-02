# Instalación multiplataforma y selección de CPU/GPU

El método recomendado es ejecutar `instalar.command` en macOS/Linux o
`instalar.bat` en Windows. También funciona directamente:

```bash
python instalar.py --perfil completo
```

El instalador crea `.venv_ocr` cuando no se está dentro de un entorno virtual,
actualiza las herramientas de instalación, selecciona PyTorch, instala todos los
grupos funcionales y comprueba una operación real con tensores.

## Selección automática

- NVIDIA en Windows/Linux: prueba ruedas CUDA oficiales desde la más nueva que
  admite el controlador detectado. Si ninguna se instala, continúa con CPU.
- Apple Silicon: instala la rueda normal de macOS, que incluye Metal/MPS y CPU.
- Otros equipos: instala la rueda oficial para CPU.

PyTorch no permite mantener simultáneamente una rueda exclusiva de CPU y otra de
CUDA dentro del mismo entorno porque ambas proporcionan el mismo paquete
`torch`. La rueda acelerada ya ejecuta en CPU las operaciones correspondientes;
además, el programa conserva su fallback de CPU si CUDA/MPS no está disponible.

Antes de modificar el equipo se puede revisar el plan:

```bash
python instalar.py --solo-diagnostico
python instalar.py --simular
```

Para una instalación mínima use `--perfil base`. Las herramientas de desarrollo
se agregan solamente con `--incluir-desarrollo`.

## Verificación y solución de problemas

Al terminar debe aparecer `Instalación verificada` con `cpu_ok: true` y el
dispositivo seleccionado. Después ejecute:

```bash
.venv_ocr/bin/python iniciar.py          # macOS/Linux
.venv_ocr\Scripts\python.exe iniciar.py  # Windows
```

En NVIDIA, actualice primero el controlador si el diagnóstico detecta la tarjeta
pero PyTorch no consigue habilitar CUDA. No es necesario instalar manualmente el
CUDA Toolkit para usar las ruedas oficiales de PyTorch; sí se requiere un
controlador compatible.
