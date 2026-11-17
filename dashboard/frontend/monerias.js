/* monerias.js — P53 · chispas al tocar y luz que sigue al cursor.
   Sólo escucha eventos delegados en `document`: no toca el árbol de React, el visor ni el
   estado de la aplicación. Si falla, el dashboard sigue igual. Sin dependencias ni red. */
(function () {
  "use strict";
  if (typeof document === "undefined" || typeof window.matchMedia !== "function") return;
  var reducir = window.matchMedia("(prefers-reduced-motion: reduce)");

  document.addEventListener("pointerdown", function (evento) {
    try {
      if (reducir.matches || !evento.target || !evento.target.closest) return;
      var boton = evento.target.closest(".boton, .tab, .btn-tema");
      if (!boton || boton.disabled) return;
      var chispa = document.createElement("div");
      chispa.className = "p53-chispa";
      chispa.setAttribute("aria-hidden", "true");
      chispa.style.left = evento.clientX + "px";
      chispa.style.top = evento.clientY + "px";
      chispa.innerHTML = "<i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i>";
      document.body.appendChild(chispa);
      setTimeout(function () { chispa.remove(); }, 650);
    } catch (_) { /* una monería nunca rompe la interfaz */ }
  }, { passive: true });

  var pendiente = false, ultimo = null;
  document.addEventListener("pointermove", function (evento) {
    ultimo = evento;
    if (pendiente || reducir.matches) return;
    pendiente = true;
    requestAnimationFrame(function () {         // un solo cuadro por movimiento
      pendiente = false;
      try {
        var tarjeta = ultimo.target && ultimo.target.closest && ultimo.target.closest(".tarjeta");
        var anterior = document.querySelector(".tarjeta.p53-luz");
        if (anterior && anterior !== tarjeta) anterior.classList.remove("p53-luz");
        if (!tarjeta) return;
        var caja = tarjeta.getBoundingClientRect();
        tarjeta.style.setProperty("--mx", (ultimo.clientX - caja.left) + "px");
        tarjeta.style.setProperty("--my", (ultimo.clientY - caja.top) + "px");
        tarjeta.classList.add("p53-luz");
      } catch (_) { /* idem */ }
    });
  }, { passive: true });
})();
