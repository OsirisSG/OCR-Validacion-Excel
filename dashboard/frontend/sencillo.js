/* =============================================================================
   sencillo.js — P54 · «Modo sencillo»: la pantalla de inicio del dashboard.

   Pide sólo lo imprescindible (carpeta, laboratorio, idioma, con o sin vídeo) y
   reutiliza TODO lo demás del dashboard: el mismo diálogo de rangos y proyecto
   (`DialogoRangosApertura`), el mismo POST /api/pipeline, el mismo sondeo serial
   y el mismo exportador de Excel. No hay lógica de negocio nueva aquí.

   Se carga ANTES de app.js y sólo publica `window.VistaSencilla`; usa los
   ayudantes globales de app.js (html, t, pedirJSON, enviarJSON, useApi…) en el
   momento de pintar, cuando app.js ya está cargado. Sin dependencias ni red.
   ============================================================================= */
(function () {
  "use strict";
  const { useState, useEffect, useRef, useCallback } = React;

  const CLAVE_BORRADOR = "ocr_sencillo_v1";
  const CLAVE_MODO = "ocr_modo";
  // Por ahora sólo EDAG. Añadir un laboratorio aquí lo muestra en el selector;
  // `disponible: false` lo deja visible pero sin poder elegirse.
  const LABORATORIOS = [
    { id: "EDAG", nombre: "EDAG", detalle: "Laboratorio actual", disponible: true },
    { id: "otro", nombre: "Otro laboratorio", detalle: "Próximamente", disponible: false },
  ];
  const IDIOMAS = [["es", "Español"], ["en", "English"], ["de", "Deutsch"]];
  // Etapa del lote. «Detectar» = lo que hace el programa: busca 1ST/2ST en el nombre de la
  // carpeta, de las superiores y de las subcarpetas. Si no lo encuentra, hay que elegirla.
  const ETAPAS = [["", "Detectar"], ["1ST", "1ST"], ["2ST", "2ST"]];
  const FALTA_ETAPA = /1ST o 2ST/i;

  function leerBorrador() {
    try {
      const dato = JSON.parse(localStorage.getItem(CLAVE_BORRADOR) || "{}");
      return dato && typeof dato === "object" ? dato : {};
    } catch (_) { return {}; }
  }
  function guardarBorrador(dato) {
    try { localStorage.setItem(CLAVE_BORRADOR, JSON.stringify(dato)); } catch (_) { /* modo privado */ }
  }
  function modoGuardado() {
    try { return localStorage.getItem(CLAVE_MODO) === "avanzado" ? "avanzado" : "sencillo"; }
    catch (_) { return "sencillo"; }
  }
  function fijarModo(modo) {
    try { localStorage.setItem(CLAVE_MODO, modo === "avanzado" ? "avanzado" : "sencillo"); } catch (_) { /* idem */ }
  }
  /** Ruta con la que abre el dashboard cuando la dirección no trae `#/…`. */
  function rutaInicial() { return modoGuardado() === "avanzado" ? "#/resumen" : "#/inicio"; }

  const svg = (d, extra) => html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ...${extra || {}}>${d.map((p, i) =>
      html`<path key=${i} d=${p} />`)}</svg>`;
  const ICONOS = {
    carpeta: ["M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"],
    flecha: ["M5 12h14", "M13 6l6 6-6 6"],
    pegar: ["M9 4h6v3H9z", "M8 5H6a1 1 0 0 0-1 1v13a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-2"],
    herramientas: ["M4 6h10", "M18 6h2", "M4 12h2", "M10 12h10", "M4 18h10", "M18 18h2",
      "M14 4v4h4V4z", "M6 10v4h4v-4z", "M14 16v4h4v-4z"],
    pausa: ["M9 5v14", "M15 5v14"],
    seguir: ["M7 5l12 7-12 7z"],
    alto: ["M6 6h12v12H6z"],
    palomita: ["M5 13l4 4L19 7"],
    video: ["M4 7a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z", "M16 10l5-3v10l-5-3"],
    lab: ["M9 3h6", "M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3", "M7.5 15h9"],
    idioma: ["M3 12h18", "M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z", "M12 3c2.5 3 2.5 15 0 18", "M12 3c-2.5 3-2.5 15 0 18"],
  };
  const Ico = ({ n }) => svg(ICONOS[n] || ICONOS.flecha);

  /** Interruptor día/noche (el tema lo maneja `usarTema` de app.js). */
  function InterruptorTema({ tema, alternarTema }) {
    const noche = tema === "oscuro";
    return html`<label class="sen-tema" title=${t("Cambiar tema claro/oscuro")}>
      <input type="checkbox" role="switch" checked=${noche} onChange=${alternarTema}
        aria-label=${t("Modo noche")} />
      <span class="sen-tema-pista" aria-hidden="true">
        <i class="sen-estrella e1"></i><i class="sen-estrella e2"></i><i class="sen-estrella e3"></i>
        <span class="sen-tema-astro"></span>
      </span>
    </label>`;
  }

  /** Cabecera del modo sencillo: logo, noche y el paso al análisis avanzado. */
  function CabeceraSencilla({ tema, alternarTema }) {
    return html`<header class="cabecera sen-cabecera">
      <div class="cabecera-inner">
        <span class="logo logo-identidad" aria-label="OCR Versuchsmatrix">
          <img class="logo-grafico" src=${tema === "oscuro" ? "assets/logo_oscuro.png" : "assets/logo_claro.png"}
            alt="OCR" loading="eager" decoding="async" />
          <span class="logo-texto"><strong>Versuchsmatrix</strong><small>${t("Validación y consolidación OCR")}</small></span>
        </span>
        <span class="espacio"></span>
        <${InterruptorTema} tema=${tema} alternarTema=${alternarTema} />
        <a class="sen-avanzado" href="#/resumen" onClick=${() => fijarModo("avanzado")}
          title=${t("Abre todas las herramientas: resumen, listado, revisión y opciones de procesamiento")}>
          <${Ico} n="herramientas" /><span>${t("Análisis avanzado")}</span>
        </a>
      </div>
    </header>`;
  }

  /** Animación de carga propia: una hoja que el escáner recorre mientras «lee». */
  function Escaner({ pausado }) {
    return html`<div class=${`sen-escaner ${pausado ? "pausado" : ""}`} aria-hidden="true">
      <span class="sen-hoja">
        <i></i><i></i><i></i><i></i>
        <b class="sen-haz"></b>
      </span>
      <span class="sen-chispa c1"></span><span class="sen-chispa c2"></span><span class="sen-chispa c3"></span>
    </div>`;
  }

  function VistaSencilla() {
    const borrador = useRef(leerBorrador()).current;
    const [recientes, setRecientes] = useState(cargarRutasRecientes);
    const [ruta, setRuta] = useState(() => borrador.ruta || cargarRutasRecientes()[0]?.ruta || "");
    const [laboratorio, setLaboratorio] = useState(() =>
      LABORATORIOS.some((l) => l.id === borrador.laboratorio && l.disponible) ? borrador.laboratorio : "EDAG");
    const [conVideo, setConVideo] = useState(() => borrador.conVideo !== false);
    const [etapa, setEtapa] = useState(() => (["1ST", "2ST"].includes(borrador.etapa) ? borrador.etapa : ""));
    const idioma = window.OCR_I18N?.get?.() || "es";
    const [estado, setEstado] = useState(undefined);
    const [errorEstado, setErrorEstado] = useState(null);
    const [capacidad, , errorCapacidad] = useApi("/api/pipeline/capacidad");
    const [enviando, setEnviando] = useState(false);
    const [errorEnvio, setErrorEnvio] = useState(null);
    const [dialogoRangos, setDialogoRangos] = useState(false);
    const [configRangos, setConfigRangos] = useState(null);
    const [proyectos, setProyectos] = useState([]);
    const [sugerencias, setSugerencias] = useState([]);
    const [dialogoDetencion, setDialogoDetencion] = useState(false);
    const [otraCarpeta, setOtraCarpeta] = useState(false);
    const [reloj, setReloj] = useState(Date.now());
    // P54 · formulario de dudas de la última corrida (dónde está y si se puede abrir)
    const [dudas, setDudas] = useState(null);
    const [abriendoDudas, setAbriendoDudas] = useState(false);

    useEffect(() => { guardarBorrador({ ruta, laboratorio, conVideo, etapa }); }, [ruta, laboratorio, conVideo, etapa]);

    const refrescarProyectos = useCallback(() => {
      pedirJSON("/api/proyectos")
        .then((dato) => { setProyectos(dato?.proyectos || []); setSugerencias(dato?.sugerencias || []); })
        .catch(() => { setProyectos([]); setSugerencias([]); });
    }, []);

    // Mismo sondeo serial y la misma guarda de secuencia que «Procesar carpeta».
    const guardaRef = useRef(null);
    if (!guardaRef.current) guardaRef.current = RedSegura.crearGuardaSecuencia();
    const refrescar = useCallback(() => {
      const guarda = guardaRef.current, token = guarda.siguiente();
      return pedirJSON("/api/pipeline/estado")
        .then((dato) => { if (guarda.esVigente(token)) { setEstado(dato); setErrorEstado(null); } })
        .catch((e) => { if (guarda.esVigente(token)) setErrorEstado(e); });
    }, []);
    useEffect(() => {
      refrescarProyectos();
      const sondeo = RedSegura.crearSondeoSerial({ intervaloMs: 1200, tarea: refrescar });
      sondeo.iniciar();
      return () => sondeo.detener();
    }, []);

    const procesando = estado?.estado === "procesando";
    const pausando = estado?.estado === "pausando";
    const pausado = estado?.estado === "pausado";
    const cancelando = estado?.estado === "cancelando";
    const activo = procesando || pausando || pausado || cancelando;
    const completado = estado?.estado === "completado";
    useEffect(() => {
      if (!procesando) return undefined;
      const id = setInterval(() => setReloj(Date.now()), 500);
      return () => clearInterval(id);
    }, [procesando]);
    useEffect(() => { if (activo) setOtraCarpeta(false); }, [activo]);
    useEffect(() => {
      if (!completado) { setDudas(null); return; }
      pedirJSON("/api/dudas/estado").then(setDudas).catch(() => setDudas(null));
    }, [completado]);

    /** Lleva al formulario de dudas en esta misma pestaña; si se había cerrado, lo vuelve a abrir. */
    async function revisarDudas() {
      setErrorEnvio(null);
      setAbriendoDudas(true);
      try {
        let dato = await enviarJSON("/api/dudas/abrir", {});
        for (let intento = 0; intento < 20 && !dato.vivo; intento += 1) {   // arranca en unos segundos
          await new Promise((listo) => setTimeout(listo, 700));
          dato = await pedirJSON("/api/dudas/estado");
        }
        if (!dato.vivo || !dato.url) throw new Error(t("El formulario de dudas tardó demasiado en abrir. Inténtalo de nuevo."));
        location.href = `${dato.url}/?volver=${encodeURIComponent(`${location.origin}/#/inicio`)}`;
      } catch (e) {
        setErrorEnvio(e.message);
        setAbriendoDudas(false);
      }
    }

    function cambiarIdioma(codigo) {
      if (codigo === idioma) return;
      guardarBorrador({ ruta, laboratorio, conVideo, etapa });   // `set` recarga la página
      window.OCR_I18N?.set?.(codigo);
    }
    async function pegar() {
      try {
        const texto = (await navigator.clipboard.readText()).trim().replace(/^"|"$/g, "");
        if (texto) setRuta(texto);
      } catch (_) {
        setErrorEnvio(t("El navegador no dejó leer el portapapeles. Pega la dirección con Ctrl + V."));
      }
    }

    const abrirRangos = async (ev) => {
      ev.preventDefault();
      setErrorEnvio(null);
      try {
        setConfigRangos(await pedirJSON("/api/config"));
      } catch (_) {
        setConfigRangos({ criterios_predeterminados: { verde_max: 6, amarillo_max: 7 },
          criterios_vigentes: null, colores: {} });
      }
      setDialogoRangos(true);
    };

    const confirmar = async (rango, proyecto) => {
      setDialogoRangos(false);
      setErrorEnvio(null);
      if (!proyecto) {
        setErrorEnvio(t("Elige el proyecto al que pertenecen las pruebas, o marca expresamente «Sin asignar»."));
        return;
      }
      setEnviando(true);
      try {
        await enviarJSON("/api/pipeline", {
          ruta: ruta.trim(), nombre_excel: null, sobrescribir_excel: false,
          tipo_st: etapa || null, ruta_plantilla: null, plantilla_id: null,
          modo_ejecucion: "completo", perfil_rendimiento: "alto",
          contenido: conVideo ? "todo" : "fotos",
          idiomas_exportacion: [idioma],
          ruta_inventario: null,
          rango_apertura: rango ? {
            verde_max: rango.verde_max, amarillo_max: rango.amarillo_max,
            origen: rango.origen, guardar_preferencia: !!rango.guardar_preferencia,
          } : null,
          proyecto: {
            nombre_proyecto: proyecto.nombre_proyecto || null,
            proyecto_id: proyecto.proyecto_id || null,
            sin_asignar: !!proyecto.sin_asignar,
            usuario: "dashboard",
          },
        });
        const nueva = { ruta: ruta.trim(), nombre_excel: "", idiomas_exportacion: [idioma],
          usado_en: new Date().toISOString() };
        const actualizadas = [nueva, ...recientes.filter((item) => item.ruta !== nueva.ruta)];
        setRecientes(actualizadas);
        persistirRutasRecientes(actualizadas);
        setOtraCarpeta(false);
        await refrescar();
        refrescarProyectos();
      } catch (e) {
        setErrorEnvio(e.message);
      } finally {
        setEnviando(false);
      }
    };

    const accion = async (url, cuerpo) => {
      setErrorEnvio(null);
      try { await enviarJSON(url, cuerpo || {}); await refrescar(); }
      catch (e) { setErrorEnvio(e.message); }
    };

    if (capacidad === undefined || estado === undefined) {
      return html`<section class="sen-escena"><div class="sen-tarjeta sen-cargando" aria-busy="true">
        <${Escaner} /><p>${t("Preparando…")}</p></div></section>`;
    }
    if (errorCapacidad || errorEstado) {
      return html`<section class="sen-escena"><div class="sen-tarjeta sen-aviso-error" role="alert">
        <h2>${t("No hay conexión con el programa")}</h2>
        <p>${t("Comprueba que la ventana negra del programa sigue abierta y vuelve a cargar esta página.")}</p>
        <button class="boton sen-boton" onClick=${() => location.reload()}>${t("Volver a cargar")}</button>
      </div></section>`;
    }

    const noLista = capacidad && !capacidad.listo;
    const porcentaje = Math.min(100, Math.max(0, Number(estado.porcentaje) || 0));
    const segundosDesde = estado.actualizado_en
      ? Math.max(0, (reloj - new Date(estado.actualizado_en).getTime()) / 1000) : 0;
    const eta = procesando && estado.eta_segundos != null
      ? Math.max(0, estado.eta_segundos - segundosDesde) : estado.eta_segundos;
    const textoEta = pausando ? t("Pausando…") : pausado ? t("En pausa")
      : eta == null ? (procesando ? t("Calculando…") : "—") : fmtDuracion(eta);
    const mostrarListo = completado && !otraCarpeta;

    const dialogos = html`
      ${dialogoRangos && html`<${DialogoRangosApertura} config=${configRangos}
        proyectos=${proyectos} sugerencias=${sugerencias}
        onCancelar=${() => { setDialogoRangos(false); setConfigRangos(null); }}
        onProcesar=${confirmar} />`}
      ${dialogoDetencion && html`<div class="modal-fondo" role="presentation"
        onClick=${(e) => { if (e.target === e.currentTarget) setDialogoDetencion(false); }}>
        <section class="modal-detencion" role="dialog" aria-modal="true" aria-labelledby="sen-titulo-detencion">
          <h3 id="sen-titulo-detencion">${t("¿Cómo deseas detener el análisis?")}</h3>
          <p>${t("Todo resultado terminado y el caché por imagen se conservarán para reanudar sin repetir OCR válido.")}</p>
          <div class="acciones-modal">
            <button type="button" class="boton" onClick=${() => setDialogoDetencion(false)}>${t("Continuar")}</button>
            <button type="button" class="boton boton-peligro" onClick=${() => {
              setDialogoDetencion(false); accion("/api/pipeline/cancelar", { accion: "conservar_avance" }); }}>
              ${t("Cancelar y conservar avance")}</button>
            <button type="button" class="boton boton-primario" onClick=${() => {
              setDialogoDetencion(false); accion("/api/pipeline/cancelar", { accion: "fin_id" }); }}>
              ${t("Detener al finalizar la carpeta/ID actual")}</button>
          </div>
        </section>
      </div>`}`;

    // ---------------------------------------------------------------- en marcha
    if (activo) {
      return html`<section class="sen-escena">
        <div class="sen-tarjeta sen-progreso" aria-live="polite">
          <${Escaner} pausado=${pausado || pausando} />
          <p class="sen-sobre">${pausado ? t("En pausa") : cancelando ? t("Deteniendo…") : t("Leyendo tu carpeta")}</p>
          <p class="sen-porcentaje"><strong>${porcentaje.toFixed(0)}</strong><span>%</span></p>
          <div class="sen-barra" role="progressbar" aria-label=${t("Avance total")}
            aria-valuemin="0" aria-valuemax="100" aria-valuenow=${Math.round(porcentaje)}>
            <span style=${{ transform: `scaleX(${porcentaje / 100})` }}></span>
          </div>
          <p class="sen-mensaje">${estado.mensaje || estado.fase || t("Preparando…")}</p>
          <dl class="sen-datos">
            <div><dt>${t("Carpetas")}</dt><dd>${estado.procesadas || 0} / ${estado.total || "—"}</dd></div>
            <div><dt>${t("Imágenes")}</dt><dd>${estado.imagenes_procesadas || 0} / ${estado.imagenes_total || "—"}</dd></div>
            <div><dt>${t("Falta")}</dt><dd>${textoEta}</dd></div>
          </dl>
          <div class="sen-acciones">
            ${(procesando || pausado) && html`<button class="boton sen-boton" onClick=${() =>
              accion(pausado ? "/api/pipeline/reanudar" : "/api/pipeline/pausar")}>
              <${Ico} n=${pausado ? "seguir" : "pausa"} />${pausado ? t("Continuar") : t("Pausar")}</button>`}
            ${pausando && html`<button class="boton sen-boton" disabled>${t("Pausando…")}</button>`}
            ${(procesando || pausando || pausado) && html`<button class="boton sen-boton sen-peligro"
              onClick=${() => setDialogoDetencion(true)}><${Ico} n="alto" />${t("Detener")}</button>`}
          </div>
          <p class="sen-nota">${t("Puedes dejar esta ventana abierta. Los archivos no salen de este equipo.")}</p>
          ${errorEnvio && html`<p class="mensaje-error" role="alert">${errorEnvio}</p>`}
        </div>
        ${dialogos}
      </section>`;
    }

    // -------------------------------------------------------------------- listo
    if (mostrarListo) {
      return html`<section class="sen-escena">
        <div class="sen-tarjeta sen-listo">
          <svg class="sen-palomita" viewBox="0 0 60 60" aria-hidden="true">
            <circle cx="30" cy="30" r="26" /><path d="M17 31l9 9 17-19" /></svg>
          <h2>${t("¡Listo!")}</h2>
          <p class="sen-mensaje">${estado.procesadas || 0} ${t("carpetas procesadas")}${estado.transcurrido_segundos
            ? ` · ${fmtDuracion(estado.transcurrido_segundos)}` : ""}</p>
          ${dudas?.disponible && html`<div class="sen-dudas">
            <p><strong>${t("Falta un paso: revisar las dudas.")}</strong> ${t("El sistema te enseña la foto y sus opciones; tú eliges el texto correcto.")}</p>
            <button class="boton boton-primario sen-boton sen-procesar sen-grande" onClick=${revisarDudas} disabled=${abriendoDudas}>
              <span>${abriendoDudas ? t("Abriendo…") : t("Revisar dudas")}</span><${Ico} n="flecha" /></button>
          </div>`}
          <div class="sen-acciones">
            <a class=${`boton sen-boton ${dudas?.disponible ? "" : "boton-primario sen-procesar"}`} href="#/resumen" onClick=${() => fijarModo("avanzado")}>
              <span>${t("Ver resultados")}</span><${Ico} n="flecha" /></a>
            <button class="boton sen-boton" onClick=${() => setOtraCarpeta(true)}>
              <${Ico} n="carpeta" />${t("Procesar otra carpeta")}</button>
          </div>
          ${errorEnvio && html`<p class="mensaje-error" role="alert">${errorEnvio}</p>`}
          <div class="sen-exportar"><${ExportadorExcel} /></div>
        </div>
      </section>`;
    }

    // --------------------------------------------------------------- formulario
    const listaRecientes = recientes.filter((item) => item.ruta !== ruta).slice(0, 3);
    // La última corrida se paró porque no supo si era 1ST o 2ST: se pide la etapa.
    const pideEtapa = !etapa && FALTA_ETAPA.test(String(estado.error || ""));
    return html`<section class="sen-escena">
      <div class="sen-hero">
        <h1>${t("¿Qué carpeta procesamos?")}</h1>
        <p>${t("Pega la dirección de la carpeta y pulsa Procesar. Lo demás ya está listo.")}</p>
      </div>

      ${noLista && html`<div class="sen-tarjeta sen-aviso-error" role="alert">
        <strong>${t("Todavía no se puede procesar.")}</strong>
        <span>${t("Falta instalar en este equipo:")} ${(capacidad.faltantes || []).join(", ")}.</span>
      </div>`}

      ${estado.reanudable && html`<div class="sen-tarjeta sen-reanudar">
        <span><strong>${t("Hay un avance guardado.")}</strong> ${t("Puedes continuar donde se quedó sin repetir lo ya leído.")}</span>
        <button class="boton sen-boton" onClick=${() => accion("/api/pipeline/reanudar")}>
          <${Ico} n="seguir" />${t("Reanudar")}</button>
      </div>`}

      <form class="sen-tarjeta sen-formulario" onSubmit=${abrirRangos}>
        <div class="sen-paso">
          <label class="sen-etiqueta" for="sen-ruta"><span class="sen-num">1</span>${t("Carpeta")}</label>
          <div class="sen-campo-ruta">
            <${Ico} n="carpeta" />
            <input id="sen-ruta" type="text" value=${ruta} onInput=${(e) => setRuta(e.target.value)}
              placeholder="C:\\Programas Base\\1st" autocomplete="off" spellcheck="false"
              aria-describedby="sen-ayuda-ruta" required />
            <button type="button" class="sen-pegar" onClick=${pegar}><${Ico} n="pegar" /><span>${t("Pegar")}</span></button>
          </div>
          <p id="sen-ayuda-ruta" class="sen-ayuda">${t("Cópiala de la barra del Explorador de Windows. Los archivos se quedan donde están.")}</p>
          ${listaRecientes.length > 0 && html`<div class="sen-recientes" aria-label=${t("Carpetas recientes")}>
            ${listaRecientes.map((item) => html`<button type="button" key=${item.ruta} class="sen-reciente"
              title=${item.ruta} onClick=${() => setRuta(item.ruta)}>${item.ruta}</button>`)}
          </div>`}
          <div class=${`sen-etapa ${pideEtapa ? "sen-falta" : ""}`}>
            <span class="sen-etapa-nombre" id="sen-etapa">${t("Etapa")}</span>
            <div class="sen-segmentos sen-mini" role="radiogroup" aria-labelledby="sen-etapa"
              data-sel=${ETAPAS.findIndex(([v]) => v === etapa)}>
              ${ETAPAS.map(([valor, nombre]) => html`<button type="button" key=${nombre} role="radio"
                aria-checked=${etapa === valor} class=${etapa === valor ? "sel" : ""}
                onClick=${() => setEtapa(valor)}>${t(nombre)}</button>`)}
            </div>
          </div>
          <p class="sen-ayuda">${pideEtapa
            ? t("La carpeta no dice si es 1ST o 2ST. Elige la etapa y vuelve a pulsar Procesar.")
            : t("Se detecta del nombre de la carpeta. Elígela sólo si el nombre no dice 1ST ni 2ST.")}</p>
        </div>

        <div class="sen-paso">
          <span class="sen-etiqueta" id="sen-lab"><span class="sen-num">2</span>${t("Laboratorio")}</span>
          <div class="sen-opciones" role="radiogroup" aria-labelledby="sen-lab">
            ${LABORATORIOS.map((lab) => html`<label key=${lab.id}
              class=${`sen-opcion ${laboratorio === lab.id ? "sel" : ""} ${lab.disponible ? "" : "no"}`}>
              <input type="radio" name="sen-laboratorio" value=${lab.id} checked=${laboratorio === lab.id}
                disabled=${!lab.disponible} onChange=${() => setLaboratorio(lab.id)} />
              <${Ico} n="lab" />
              <span><strong>${t(lab.nombre)}</strong><small>${t(lab.detalle)}</small></span>
            </label>`)}
          </div>
        </div>

        <div class="sen-paso sen-dos">
          <div>
            <span class="sen-etiqueta" id="sen-idioma"><span class="sen-num">3</span>${t("Idioma")}</span>
            <div class="sen-segmentos" role="radiogroup" aria-labelledby="sen-idioma" data-sel=${IDIOMAS.findIndex(([c]) => c === idioma)}>
              ${IDIOMAS.map(([codigo, nombre]) => html`<button type="button" key=${codigo} role="radio"
                aria-checked=${idioma === codigo} class=${idioma === codigo ? "sel" : ""}
                onClick=${() => cambiarIdioma(codigo)}>${nombre}</button>`)}
            </div>
            <p class="sen-ayuda">${t("Idioma de la pantalla y del Excel.")}</p>
          </div>
          <div>
            <span class="sen-etiqueta" id="sen-video"><span class="sen-num">4</span>${t("Vídeos")}</span>
            <label class="sen-interruptor">
              <input type="checkbox" role="switch" checked=${conVideo} aria-labelledby="sen-video"
                onChange=${(e) => setConVideo(e.target.checked)} />
              <span class="sen-pista" aria-hidden="true"><span class="sen-perilla"><${Ico} n="video" /></span></span>
              <span class="sen-interruptor-texto">${conVideo ? t("Con vídeo") : t("Sin vídeo")}</span>
            </label>
            <p class="sen-ayuda">${conVideo ? t("Lee las fotos y analiza los vídeos.") : t("Sólo las fotos. Termina antes.")}</p>
          </div>
        </div>

        <button class="boton boton-primario sen-boton sen-procesar sen-grande" type="submit"
          disabled=${enviando || !ruta.trim() || noLista}>
          <span>${enviando ? t("Iniciando…") : t("Procesar")}</span><${Ico} n="flecha" />
        </button>
        <p class="sen-nota">${t("Antes de empezar te pediremos el proyecto y los rangos de apertura.")}</p>
        ${errorEnvio && html`<p class="mensaje-error" role="alert">${errorEnvio}</p>`}
        ${estado.error && !pideEtapa && html`<p class="mensaje-error" role="alert"><strong>${t("La última ejecución terminó con error:")}</strong> ${estado.error}</p>`}
      </form>
      ${dialogos}
    </section>`;
  }

  window.VistaSencilla = VistaSencilla;
  window.OCRModoSencillo = { CabeceraSencilla, rutaInicial, fijarModo, modoGuardado, LABORATORIOS };
})();
