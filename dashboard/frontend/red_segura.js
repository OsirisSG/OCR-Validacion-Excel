/* R15 (MEDIA-08/09/13): capa de red segura del frontend. Sin dependencias.
 *
 * - crearSondeoSerial: polling que NUNCA solapa peticiones (la siguiente
 *   consulta se programa sólo cuando la anterior terminó) y se detiene limpiamente.
 * - crearGuardaSecuencia: contador de versión por fuente de datos; una
 *   respuesta antigua jamás sobrescribe una nueva.
 * - lanzar404: política explícita de 404 — sólo los endpoints donde «sin
 *   datos todavía» es legítimo devuelven null; los recursos concretos lanzan.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.VMatrixRedSegura = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const dormirPorDefecto = (ms) => new Promise((resolver) => setTimeout(resolver, ms));

  /**
   * Sondeo serial: ejecuta `tarea` (async), espera `intervaloMs` y repite.
   * Garantiza como máximo UNA tarea en vuelo; `detener()` corta el bucle y
   * descarta resultados pendientes de aplicar por el consumidor (la tarea
   * debe consultar `activo()` antes de pintar si quiere esa garantía extra).
   */
  function crearSondeoSerial({ intervaloMs = 1200, tarea, dormir = dormirPorDefecto } = {}) {
    let activo = false;
    let enVuelo = 0;
    let cancelado = false;

    async function bucle() {
      while (!cancelado) {
        enVuelo += 1;
        try {
          await tarea({ activo: () => !cancelado });
        } catch (_) {
          // Error transitorio: el siguiente ciclo reintenta; nunca se solapa.
        } finally {
          enVuelo -= 1;
        }
        if (cancelado) break;
        await dormir(intervaloMs);
      }
    }

    return {
      iniciar() {
        if (activo || cancelado) return false;
        activo = true;
        bucle();
        return true;
      },
      detener() {
        cancelado = true;
        activo = false;
      },
      get enVuelo() { return enVuelo; },
      get detenido() { return cancelado; },
    };
  }

  /**
   * Guarda de secuencia: `siguiente()` devuelve un token monotónico;
   * `esVigente(token)` es true sólo para el último emitido. Las respuestas
   * rezagadas se descartan antes de setState.
   */
  function crearGuardaSecuencia() {
    let actual = 0;
    return {
      siguiente() { actual += 1; return actual; },
      esVigente(token) { return token === actual; },
      get valor() { return actual; },
    };
  }

  /**
   * MEDIA-13: 404 ⇒ null SOLO con permitir404 explícito (o por omisión en
   * endpoints de estado global, donde «sin datos todavía» es legítimo).
   * En recursos concretos (detalle, tiempo-frame) se lanza error y la
   * pantalla limpia su estado dependiente en lugar de mostrar datos viejos.
   */
  function lanzar404(opciones) {
    return Boolean(opciones) && opciones.permitir404 === false;
  }

  return { crearSondeoSerial, crearGuardaSecuencia, lanzar404 };
});
