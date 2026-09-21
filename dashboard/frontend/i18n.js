(() => {
  const KEY = "ocr_versuchsmatrix_idioma";
  const VALID = ["es", "en", "de"];
  const locale = {es:"es-MX", en:"en-US", de:"de-DE"};
  const lang = () => VALID.includes(localStorage.getItem(KEY)) ? localStorage.getItem(KEY) : "es";

  const D = {
    en: {
      "Resumen":"Summary", "Listado":"List", "Procesar carpeta":"Process folder",
      "Oscuro":"Dark", "Claro":"Light", "Cambiar tema claro/oscuro":"Change light/dark theme",
      "Matriz de tiempo de apertura":"Opening-time matrix", "Leyenda tiempo de apertura":"Opening-time legend",
      "Pruebas procesadas":"Processed tests", "Confianza OCR promedio":"Average OCR confidence",
      "Distribución del semáforo":"Status distribution", "Sin lotes para mostrar.":"No batches to display.",
      "Exportar Excel":"Export Excel", "Idioma de exportación":"Export language", "Los tres idiomas":"All three languages",
      "Elige el idioma independientemente de la interfaz. Los tres archivos usan la misma instantánea de datos.":"Choose the export language independently from the interface. All three files use the same data snapshot.",
      "Exportando…":"Exporting…", "Español":"Spanish", "Idiomas del Excel":"Excel languages",
      "Independientes del idioma de la interfaz. Si eliges varios, salen de la misma instantánea.":"Independent from the interface language. Multiple outputs come from the same snapshot.",
      "Direcciones guardadas":"Saved locations", "Quitar dirección":"Remove location",
      "Dirección de la carpeta raíz":"Root folder path", "Usar carpeta actual":"Use current folder",
      "Nombre del Excel de salida":"Output Excel name", "Tipo de proyecto":"Project type",
      "Detectar automáticamente":"Detect automatically", "Usar recorrido tradicional":"Use legacy workflow",
      "Modo de ejecución":"Execution mode", "Completo: inventario + OCR + Excel":"Full: inventory + OCR + Excel",
      "Solo inventario (sin OCR)":"Inventory only (no OCR)", "Contrato Excel":"Excel contract",
      "Detectar automáticamente / formato integrado":"Auto-detect / integrated format",
      "Registrar otra plantilla Excel":"Register another Excel template", "Nombre para identificarla":"Display name",
      "Ruta del archivo .xlsx":".xlsx file path", "Identificadores de carpeta (opcionales)":"Folder identifiers (optional)",
      "Registrar y seleccionar":"Register and select", "Sobrescribir el Excel si ya existe":"Overwrite Excel if it already exists",
      "Procesamiento activo":"Processing active", "Iniciando…":"Starting…", "Estado del procesamiento":"Processing status",
      "Fase actual":"Current phase", "Mensaje":"Message", "Carpeta":"Folder", "Excel":"Excel",
      "Idiomas Excel":"Excel languages", "Procesamiento":"Processing", "Plantilla":"Template", "Inicio":"Started",
      "Tiempo transcurrido":"Elapsed time", "Finalización":"Finished", "Continuar procesamiento":"Continue processing",
      "Pausar después de esta imagen":"Pause after this image", "Detener o cancelar…":"Stop or cancel…",
      "Reanudar avance guardado":"Resume saved progress", "Aún no se ha iniciado una ejecución.":"No execution has started yet.",
      "Aplicar supervisión":"Apply supervision", "Texto correcto (con espacios y saltos)":"Correct text (preserve spaces and line breaks)",
      "Acción":"Action", "Confirmar para el próximo lote":"Confirm for next batch", "Guardar sin entrenar":"Save without training",
      "Corregir y entrenar":"Correct and train", "Sin confirmar":"Unconfirmed", "Corregido / confirmado":"Corrected / confirmed",
      "Este bloque aún no tiene una corrección confirmada":"This block has no confirmed correction yet",
      "Borrador modificado · falta aplicar supervisión":"Draft changed · supervision not applied yet",
      "Imagen verificada":"Image verified", "Imagen sin datos de texto":"Image without text data", "Sí tiene texto":"It has text",
      "Anterior":"Previous", "Siguiente":"Next", "Mostrar todas las imágenes":"Show all images", "Ocultar imágenes verificadas":"Hide verified images",
      "Navegar imágenes":"Navigate images", "Selecciona una imagen":"Select an image", "No hay imágenes visibles":"No visible images",
      "Todas las imágenes están verificadas. Puedes mostrarlas nuevamente.":"All images are verified. You can show them again.",
      "Esta carpeta no contiene imágenes.":"This folder contains no images.", "Editar texto":"Edit text", "Cerrar edición":"Close editing",
      "Reabrir revisión":"Reopen review", "Completar revisión":"Complete review", "Revisión completada":"Review completed",
      "Revisión parcial":"Partial review", "Por revisar":"To review", "Casi listo":"Almost ready",
      "Imagen y variantes de la selección":"Selected image and variants", "Restablecer giro":"Reset rotation",
      "Preparando esta orientación":"Preparing this orientation", "Lectura no disponible":"Reading unavailable",
      "Variantes listas. Gira la imagen o toca una tarjeta para copiar esa lectura a Texto correcto como borrador.":"Variants ready. Rotate the image or tap a card to copy that reading into Correct text as a draft.",
      "Copiar esta lectura a Texto correcto como borrador":"Copy this reading to Correct text as a draft",
      "Usar este texto en la corrección":"Use this text in correction", "Relee o escribe el texto exacto de esta región":"Re-read or enter the exact text in this region",
      "Texto omitido":"Omitted text", "Texto de escena":"Scene text", "Sin texto legible":"No legible text",
      "Guardar región y actualizar Excel":"Save region and update Excel", "Arrastra para seleccionar la zona que contiene texto":"Drag to select the area containing text",
      "Ampliar imagen":"Zoom in image", "Alejar imagen":"Zoom out image", "Rotar imagen":"Rotate image",
      "Revisión":"Review", "Resultado":"Result", "Estado":"Status", "Imagen":"Image", "Motor OCR":"OCR engine",
      "Pruebas complejas y externas":"Complex and external tests", "Bandeja unificada de revisión":"Unified review inbox",
      "Filtrar por estado":"Filter by status", "Quitar del listado":"Remove from list", "Restaurar en listado":"Restore to list",
      "Tiempo de apertura aún no conocido":"Opening time not known yet", "Lectura propuesta; confirma su contenido.":"Proposed reading; confirm its content.",
      "Sin determinar":"Undetermined", "Sin lectura":"No reading", "Sin lectura previa":"No previous reading",
      "Corrección OCR":"OCR correction", "Escribe el texto correcto":"Enter the correct text",
      "Escribe todo el texto, respetando espacios y saltos":"Enter the full text, preserving spaces and line breaks",
      "Estado de revisión actualizado.":"Review status updated.", "Última edición deshecha.":"Last edit undone.",
      "Excel actualizado con los cambios de la cola.":"Excel updated with queued changes.",
      "No se pudo consultar la cola del Excel. Comprobando conexión…":"Could not read the Excel queue. Checking connection…",
      "Guardando cambios en el Excel…":"Saving changes to Excel…",
      "Cambios guardados · actualización del Excel pendiente.":"Changes saved · Excel update pending.",
      "Excel guardado con los cambios confirmados.":"Excel saved with confirmed changes.",
      "Error al actualizar el Excel.":"Error updating Excel.",
      "Excel parcial disponible.":"Partial Excel available.",
      "Abrir Excel parcial":"Open partial Excel",
      "actualizaciones pendientes. Puedes seguir corrigiendo.":"updates pending. You can keep correcting."
    },
    de: {
      "Resumen":"Übersicht", "Listado":"Liste", "Procesar carpeta":"Ordner verarbeiten",
      "Oscuro":"Dunkel", "Claro":"Hell", "Cambiar tema claro/oscuro":"Hell/Dunkel wechseln",
      "Matriz de tiempo de apertura":"Matrix der Öffnungszeit", "Leyenda tiempo de apertura":"Legende Öffnungszeit",
      "Pruebas procesadas":"Verarbeitete Versuche", "Confianza OCR promedio":"Mittlere OCR-Konfidenz",
      "Distribución del semáforo":"Statusverteilung", "Sin lotes para mostrar.":"Keine Lose vorhanden.",
      "Exportar Excel":"Excel exportieren", "Idioma de exportación":"Exportsprache", "Los tres idiomas":"Alle drei Sprachen",
      "Elige el idioma independientemente de la interfaz. Los tres archivos usan la misma instantánea de datos.":"Exportsprache unabhängig von der Oberfläche wählen. Alle drei Dateien verwenden denselben Datenstand.",
      "Exportando…":"Export wird erstellt…", "Español":"Spanisch", "Idiomas del Excel":"Excel-Sprachen",
      "Independientes del idioma de la interfaz. Si eliges varios, salen de la misma instantánea.":"Unabhängig von der Oberflächensprache. Mehrere Dateien stammen aus demselben Datenstand.",
      "Direcciones guardadas":"Gespeicherte Pfade", "Quitar dirección":"Pfad entfernen",
      "Dirección de la carpeta raíz":"Pfad zum Stammordner", "Usar carpeta actual":"Aktuellen Ordner verwenden",
      "Nombre del Excel de salida":"Name der Excel-Ausgabe", "Tipo de proyecto":"Projekttyp",
      "Detectar automáticamente":"Automatisch erkennen", "Usar recorrido tradicional":"Alten Ablauf verwenden",
      "Modo de ejecución":"Ausführungsmodus", "Completo: inventario + OCR + Excel":"Vollständig: Inventar + OCR + Excel",
      "Solo inventario (sin OCR)":"Nur Inventar (ohne OCR)", "Contrato Excel":"Excel-Vertrag",
      "Detectar automáticamente / formato integrado":"Automatisch erkennen / integriertes Format",
      "Registrar otra plantilla Excel":"Weitere Excel-Vorlage registrieren", "Nombre para identificarla":"Anzeigename",
      "Ruta del archivo .xlsx":"Pfad zur .xlsx-Datei", "Identificadores de carpeta (opcionales)":"Ordnerkennungen (optional)",
      "Registrar y seleccionar":"Registrieren und auswählen", "Sobrescribir el Excel si ya existe":"Excel überschreiben, falls vorhanden",
      "Procesamiento activo":"Verarbeitung läuft", "Iniciando…":"Startet…", "Estado del procesamiento":"Verarbeitungsstatus",
      "Fase actual":"Aktuelle Phase", "Mensaje":"Meldung", "Carpeta":"Ordner", "Excel":"Excel",
      "Idiomas Excel":"Excel-Sprachen", "Procesamiento":"Verarbeitung", "Plantilla":"Vorlage", "Inicio":"Start",
      "Tiempo transcurrido":"Vergangene Zeit", "Finalización":"Abschluss", "Continuar procesamiento":"Verarbeitung fortsetzen",
      "Pausar después de esta imagen":"Nach diesem Bild pausieren", "Detener o cancelar…":"Stoppen oder abbrechen…",
      "Reanudar avance guardado":"Gespeicherten Fortschritt fortsetzen", "Aún no se ha iniciado una ejecución.":"Noch keine Ausführung gestartet.",
      "Aplicar supervisión":"Korrektur übernehmen", "Texto correcto (con espacios y saltos)":"Korrekter Text (Leerzeichen und Zeilenumbrüche beibehalten)",
      "Acción":"Aktion", "Confirmar para el próximo lote":"Für den nächsten Lauf bestätigen", "Guardar sin entrenar":"Ohne Training speichern",
      "Corregir y entrenar":"Korrigieren und trainieren", "Sin confirmar":"Unbestätigt", "Corregido / confirmado":"Korrigiert / bestätigt",
      "Este bloque aún no tiene una corrección confirmada":"Dieser Block hat noch keine bestätigte Korrektur",
      "Borrador modificado · falta aplicar supervisión":"Entwurf geändert · Korrektur noch nicht übernommen",
      "Imagen verificada":"Bild geprüft", "Imagen sin datos de texto":"Bild ohne Textdaten", "Sí tiene texto":"Enthält Text",
      "Anterior":"Zurück", "Siguiente":"Weiter", "Mostrar todas las imágenes":"Alle Bilder anzeigen", "Ocultar imágenes verificadas":"Geprüfte Bilder ausblenden",
      "Navegar imágenes":"Bilder navigieren", "Selecciona una imagen":"Bild auswählen", "No hay imágenes visibles":"Keine sichtbaren Bilder",
      "Todas las imágenes están verificadas. Puedes mostrarlas nuevamente.":"Alle Bilder sind geprüft. Sie können wieder angezeigt werden.",
      "Esta carpeta no contiene imágenes.":"Dieser Ordner enthält keine Bilder.", "Editar texto":"Text bearbeiten", "Cerrar edición":"Bearbeitung schließen",
      "Reabrir revisión":"Prüfung wieder öffnen", "Completar revisión":"Prüfung abschließen", "Revisión completada":"Prüfung abgeschlossen",
      "Revisión parcial":"Teilprüfung", "Por revisar":"Zu prüfen", "Casi listo":"Fast fertig",
      "Imagen y variantes de la selección":"Ausgewähltes Bild und Varianten", "Restablecer giro":"Drehung zurücksetzen",
      "Preparando esta orientación":"Ausrichtung wird vorbereitet", "Lectura no disponible":"Erkennung nicht verfügbar",
      "Variantes listas. Gira la imagen o toca una tarjeta para copiar esa lectura a Texto correcto como borrador.":"Varianten bereit. Bild drehen oder eine Karte wählen, um die Erkennung als Entwurf in Korrekter Text zu übernehmen.",
      "Copiar esta lectura a Texto correcto como borrador":"Diese Erkennung als Entwurf in Korrekter Text übernehmen",
      "Usar este texto en la corrección":"Diesen Text für die Korrektur verwenden", "Relee o escribe el texto exacto de esta región":"Bereich erneut lesen oder exakten Text eingeben",
      "Texto omitido":"Fehlender Text", "Texto de escena":"Szenentext", "Sin texto legible":"Kein lesbarer Text",
      "Guardar región y actualizar Excel":"Bereich speichern und Excel aktualisieren", "Arrastra para seleccionar la zona que contiene texto":"Bereich mit Text durch Ziehen auswählen",
      "Acercar imagen":"Bild vergrößern", "Alejar imagen":"Bild verkleinern", "Rotar imagen":"Bild drehen",
      "Revisión":"Prüfung", "Resultado":"Ergebnis", "Estado":"Status", "Imagen":"Bild", "Motor OCR":"OCR-Engine",
      "Pruebas complejas y externas":"Komplexe und externe Versuche", "Bandeja unificada de revisión":"Gemeinsamer Prüfbereich",
      "Filtrar por estado":"Nach Status filtern", "Quitar del listado":"Aus Liste entfernen", "Restaurar en listado":"In Liste wiederherstellen",
      "Tiempo de apertura aún no conocido":"Öffnungszeit noch unbekannt", "Lectura propuesta; confirma su contenido.":"Vorgeschlagene Erkennung; Inhalt bestätigen.",
      "Sin determinar":"Unbestimmt", "Sin lectura":"Keine Erkennung", "Sin lectura previa":"Keine vorherige Erkennung",
      "Corrección OCR":"OCR-Korrektur", "Escribe el texto correcto":"Korrekten Text eingeben",
      "Escribe todo el texto, respetando espacios y saltos":"Gesamten Text mit Leerzeichen und Zeilenumbrüchen eingeben",
      "Estado de revisión actualizado.":"Prüfstatus aktualisiert.", "Última edición deshecha.":"Letzte Bearbeitung rückgängig gemacht.",
      "Excel actualizado con los cambios de la cola.":"Excel mit den Änderungen aus der Warteschlange aktualisiert.",
      "No se pudo consultar la cola del Excel. Comprobando conexión…":"Excel-Warteschlange konnte nicht gelesen werden. Verbindung wird geprüft…",
      "Guardando cambios en el Excel…":"Änderungen werden in Excel gespeichert…",
      "Cambios guardados · actualización del Excel pendiente.":"Änderungen gespeichert · Excel-Aktualisierung ausstehend.",
      "Excel guardado con los cambios confirmados.":"Excel mit den bestätigten Änderungen gespeichert.",
      "Error al actualizar el Excel.":"Fehler beim Aktualisieren der Excel-Datei.",
      "Excel parcial disponible.":"Teil-Excel verfügbar.",
      "Abrir Excel parcial":"Teil-Excel öffnen",
      "actualizaciones pendientes. Puedes seguir corrigiendo.":"Aktualisierungen ausstehend. Sie können weiter korrigieren."
    }
  };

  function translateValue(value) {
    const dic = D[lang()];
    if (!dic || !value) return value;
    const trimmed = String(value).trim();
    return dic[trimmed] || value;
  }

  function traducirTexto(root=document.body) {
    const codigo = lang();
    document.documentElement.lang = codigo;
    const dic=D[codigo]; if (!dic || !root) return;
    const walker=document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodos=[]; while(walker.nextNode()) nodos.push(walker.currentNode);
    for(const n of nodos){
      if(!n.parentElement || n.parentElement.closest("pre,code,textarea,.mono,.texto-detectado,.token-texto,.lectura-ocr-original,[data-no-translate]") ) continue;
      const raw=n.nodeValue, t=raw.trim(); if(dic[t]) n.nodeValue=raw.replace(t,dic[t]);
    }
    root.querySelectorAll?.("[title],[placeholder],[aria-label]").forEach(el=>{
      if (el.closest(".mono,.texto-detectado,.token-texto,[data-no-translate]")) return;
      for(const a of ["title","placeholder","aria-label"]){ const v=el.getAttribute(a); if(v&&dic[v]) el.setAttribute(a,dic[v]); }
    });
  }
  window.OCR_I18N={
    get:lang, locale:()=>locale[lang()]||locale.es, t:translateValue,
    set:(v)=>{if(VALID.includes(v)){localStorage.setItem(KEY,v);location.reload();}}, apply:traducirTexto
  };
  addEventListener("DOMContentLoaded",()=>{
    traducirTexto();
    new MutationObserver(ms=>ms.forEach(m=>m.addedNodes.forEach(n=>n.nodeType===1&&traducirTexto(n))))
      .observe(document.body,{childList:true,subtree:true});
  });
})();
