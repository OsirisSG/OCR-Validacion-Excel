# Error 002 — Node.js no disponible: el frontend no puede compilarse con Vite/Tremor

- **Fecha:** 2026-08-23
- **Fase:** 4 (dashboard)
- **Qué se intentó:** construir el frontend definitivo con el stack recomendado por el Documento Maestro (React + Tremor vía Vite/npm).
- **Síntoma:** `node` y `npm` no existen en el equipo (verificado con `where node` / `where npm`). Sin gestor de paquetes JS no hay cadena de build (Vite, Tailwind CLI, etc.).
- **Por qué falló:** entorno de ejecución sin Node instalado. Instalarlo es una decisión de sistema que no corresponde tomar en silencio durante la construcción.
- **Nuevo enfoque adoptado:** frontend React **sin paso de compilación**:
  - React 18 UMD + `htm` (JSX vía template literals, sin Babel) vendorizados localmente en `dashboard/frontend/vendor/` para funcionar sin internet.
  - Hoja de estilos propia (`estilos.css`) que replica los tokens visuales de Tremor (tarjetas con borde sutil, jerarquía tipográfica, semáforo, modo claro/oscuro con variables CSS).
  - Gráficas (dona y barras apiladas) dibujadas como SVG inline, sin librería externa.
  - El backend FastAPI sirve el frontend como estáticos, de modo que un solo servidor local levanta todo el dashboard.
- **Ruta de migración (documentada en `docs/fase4_dashboard.md`):** cuando Node esté disponible, `npm create vite` + Tailwind + Tremor Raw y portar los componentes (la lógica de vistas ya está aislada por componente).
- **Nota:** no es un bloqueo funcional: todos los requisitos visuales del Documento Maestro (responsivo real, modo claro/oscuro sin recarga, paleta unificada con el Excel, accesibilidad, estados vacío/carga) se cubren con este enfoque.
