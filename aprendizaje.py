"""Aprendizaje incremental seguro para corregir resultados OCR.

El sistema registra observaciones automáticamente, pero solo aprende de texto
confirmado por una persona. Las correcciones pueden actualizar la capa ligera de
reglas; el reconocedor visual EasyOCR se entrena aparte, por lotes auditables, y
su candidato solo se activa cuando mejora validación y prueba sin regresiones.
SQLite mantiene historial, versiones y rollback de ambas capas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import threading
import uuid
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime
from pathlib import Path

from configuracion import RAIZ_PROYECTO, cargar_config


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalizar_codigo(texto: str) -> str:
    """Conserva únicamente el alfabeto operativo de los códigos."""
    return re.sub(r"[^A-Z0-9\-_/]", "", str(texto).upper())


def patron_codigo(texto: str) -> str:
    """AB-120 -> AA-999; permite aprender la forma sin memorizar el valor."""
    return "".join("A" if c.isalpha() else "9" if c.isdigit() else c
                   for c in normalizar_codigo(texto))


_HASH_ARCHIVO_CACHE: "OrderedDict[tuple[str, int, int], str]" = OrderedDict()
_HASH_ARCHIVO_LOCK = threading.Lock()
_HASH_ARCHIVO_CACHE_MAX = 2048


def hash_archivo(ruta: str | Path) -> str:
    """SHA-256 con caché segura por ruta+tamaño+mtime.

    El dashboard suele confirmar varias zonas de la misma fotografía. Releer
    varios MB de disco para calcular exactamente el mismo hash en cada clic era
    trabajo redundante. La firma se invalida automáticamente si cambia tamaño o
    ``mtime_ns`` y la caché está acotada para no crecer sin límite.
    """
    archivo = Path(ruta)
    stat = archivo.stat()
    clave = (str(archivo.resolve(strict=False)), int(stat.st_size), int(stat.st_mtime_ns))
    with _HASH_ARCHIVO_LOCK:
        previo = _HASH_ARCHIVO_CACHE.get(clave)
        if previo is not None:
            _HASH_ARCHIVO_CACHE.move_to_end(clave)
            return previo
    h = hashlib.sha256()
    with open(archivo, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    digest = h.hexdigest()
    with _HASH_ARCHIVO_LOCK:
        # Elimina entradas antiguas de la misma ruta si el archivo cambió.
        ruta_resuelta = clave[0]
        for antigua in [k for k in _HASH_ARCHIVO_CACHE if k[0] == ruta_resuelta and k != clave]:
            _HASH_ARCHIVO_CACHE.pop(antigua, None)
        _HASH_ARCHIVO_CACHE[clave] = digest
        _HASH_ARCHIVO_CACHE.move_to_end(clave)
        while len(_HASH_ARCHIVO_CACHE) > _HASH_ARCHIVO_CACHE_MAX:
            _HASH_ARCHIVO_CACHE.popitem(last=False)
    return digest


def dimensiones_rotadas(ancho: int, alto: int, grados: float) -> tuple[int, int]:
    """Dimensiones del lienzo expandido tras un giro horario sin recortar."""
    angulo = float(grados) % 360
    if abs(angulo) < 1e-6:
        return int(ancho), int(alto)
    if abs(angulo - 90) < 1e-6 or abs(angulo - 270) < 1e-6:
        return int(alto), int(ancho)
    if abs(angulo - 180) < 1e-6:
        return int(ancho), int(alto)
    radianes = math.radians(angulo)
    coseno, seno = abs(math.cos(radianes)), abs(math.sin(radianes))
    return (int(math.ceil(ancho * coseno + alto * seno)),
            int(math.ceil(ancho * seno + alto * coseno)))


def rotar_bbox(bbox, grados: float, ancho_imagen: int,
               alto_imagen: int) -> list[int] | None:
    """Rota una caja con la imagen y conserva todo en un lienzo expandido."""
    if bbox is None:
        return None
    x, y, ancho, alto = (int(round(float(v))) for v in bbox)
    grados = float(grados) % 360
    if abs(grados) < 1e-6:
        return [x, y, ancho, alto]
    if abs(grados - 90) < 1e-6:
        return [alto_imagen - y - alto, x, alto, ancho]
    if abs(grados - 180) < 1e-6:
        return [ancho_imagen - x - ancho, alto_imagen - y - alto, ancho, alto]
    if abs(grados - 270) < 1e-6:
        return [y, ancho_imagen - x - ancho, alto, ancho]

    radianes = math.radians(grados)
    coseno, seno = math.cos(radianes), math.sin(radianes)
    centro_x, centro_y = ancho_imagen / 2.0, alto_imagen / 2.0
    esquinas_imagen = ((0, 0), (ancho_imagen, 0),
                       (ancho_imagen, alto_imagen), (0, alto_imagen))

    def girar(punto_x: float, punto_y: float) -> tuple[float, float]:
        dx, dy = punto_x - centro_x, punto_y - centro_y
        return coseno * dx - seno * dy, seno * dx + coseno * dy

    limites = [girar(px, py) for px, py in esquinas_imagen]
    minimo_x = min(px for px, _ in limites)
    minimo_y = min(py for _, py in limites)
    puntos = [girar(px, py) for px, py in (
        (x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto))]
    xs = [px - minimo_x for px, _ in puntos]
    ys = [py - minimo_y for _, py in puntos]
    nuevo_ancho, nuevo_alto = dimensiones_rotadas(ancho_imagen, alto_imagen, grados)
    izquierda = max(0, int(math.floor(min(xs))))
    arriba = max(0, int(math.floor(min(ys))))
    derecha = min(nuevo_ancho, int(math.ceil(max(xs))))
    abajo = min(nuevo_alto, int(math.ceil(max(ys))))
    return [izquierda, arriba, max(1, derecha - izquierda), max(1, abajo - arriba)]


def transformar_bbox_entre_rotaciones(bbox, grados_desde: float, grados_hasta: float,
                                      ancho_fuente: int, alto_fuente: int) -> list[int] | None:
    """Proyecta una caja entre dos vistas giradas de la misma imagen fuente.

    A diferencia de encadenar giros sobre lienzos ya expandidos, esta conversión
    vuelve al sistema de la fotografía original. Así un giro libre puede cambiarse
    o restablecerse sin acumular márgenes ni desplazamientos.
    """
    if bbox is None:
        return None
    ancho_fuente, alto_fuente = int(ancho_fuente), int(alto_fuente)

    def parametros(grados: float):
        radianes = math.radians(float(grados) % 360)
        coseno, seno = math.cos(radianes), math.sin(radianes)
        centro_x, centro_y = ancho_fuente / 2.0, alto_fuente / 2.0
        esquinas = ((0, 0), (ancho_fuente, 0),
                    (ancho_fuente, alto_fuente), (0, alto_fuente))
        rotadas = [
            (coseno * (px - centro_x) - seno * (py - centro_y),
             seno * (px - centro_x) + coseno * (py - centro_y))
            for px, py in esquinas
        ]
        return coseno, seno, centro_x, centro_y, min(p[0] for p in rotadas), min(
            p[1] for p in rotadas)

    cos_desde, sen_desde, cx, cy, min_x_desde, min_y_desde = parametros(grados_desde)
    cos_hasta, sen_hasta, _, _, min_x_hasta, min_y_hasta = parametros(grados_hasta)

    def convertir(px: float, py: float) -> tuple[float, float]:
        # Coordenada de la vista inicial -> coordenada centrada de la fuente.
        rx, ry = px + min_x_desde, py + min_y_desde
        dx = cos_desde * rx + sen_desde * ry
        dy = -sen_desde * rx + cos_desde * ry
        # Fuente -> vista destino.
        destino_x = cos_hasta * dx - sen_hasta * dy - min_x_hasta
        destino_y = sen_hasta * dx + cos_hasta * dy - min_y_hasta
        return destino_x, destino_y

    x, y, ancho, alto = (float(valor) for valor in bbox)
    puntos = [convertir(px, py) for px, py in (
        (x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto))]
    xs, ys = [p[0] for p in puntos], [p[1] for p in puntos]
    ancho_destino, alto_destino = dimensiones_rotadas(
        ancho_fuente, alto_fuente, grados_hasta)
    izquierda = max(0, int(math.floor(min(xs))))
    arriba = max(0, int(math.floor(min(ys))))
    derecha = min(ancho_destino, int(math.ceil(max(xs))))
    abajo = min(alto_destino, int(math.ceil(max(ys))))
    return [izquierda, arriba, max(1, derecha - izquierda), max(1, abajo - arriba)]


def _alinear(a: str, b: str) -> list[tuple[str | None, str | None]]:
    """Alineación Levenshtein determinista para extraer confusiones OCR→real."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1,
                           dp[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
    pares: list[tuple[str | None, str | None]] = []
    i, j = n, m
    while i or j:
        if i and j and dp[i][j] == dp[i - 1][j - 1] + (a[i - 1] != b[j - 1]):
            pares.append((a[i - 1], b[j - 1]))
            i -= 1
            j -= 1
        elif i and dp[i][j] == dp[i - 1][j] + 1:
            pares.append((a[i - 1], None))
            i -= 1
        else:
            pares.append((None, b[j - 1]))
            j -= 1
    return list(reversed(pares))


def _estado_desde_correcciones(correcciones: list[sqlite3.Row]) -> dict:
    exactas: dict[str, Counter] = defaultdict(Counter)
    caracteres: dict[str, Counter] = defaultdict(Counter)
    patrones = Counter()
    for fila in correcciones:
        crudo = normalizar_codigo(fila["texto_ocr"])
        correcto = normalizar_codigo(fila["texto_correcto"])
        if not crudo or not correcto:
            continue
        exactas[crudo][correcto] += 1
        patrones[patron_codigo(correcto)] += 1
        for observado, real in _alinear(crudo, correcto):
            if observado and real and observado != real:
                caracteres[observado][real] += 1
    return {
        "exactas": {k: dict(v) for k, v in exactas.items()},
        "caracteres": {k: dict(v) for k, v in caracteres.items()},
        "patrones": dict(patrones),
        "num_correcciones": len(correcciones),
    }


def predecir_correccion(texto: str, estado: dict, cfg: dict) -> tuple[str, dict | None]:
    """Aplica solo reglas con soporte y dominancia configurados."""
    crudo = normalizar_codigo(texto)
    if not crudo or not any(c.isdigit() for c in crudo):
        return texto, None

    min_exacto = int(cfg.get("minimo_soporte_exacto", 2))
    min_caracter = int(cfg.get("minimo_soporte_caracter", 3))
    min_patron = int(cfg.get("minimo_soporte_patron", 2))
    dominancia = float(cfg.get("dominancia_minima", 0.80))

    destinos = estado.get("exactas", {}).get(crudo, {})
    if destinos:
        ganador, soporte = max(destinos.items(), key=lambda x: (x[1], x[0]))
        total = sum(destinos.values())
        if soporte >= min_exacto and soporte / total >= dominancia and ganador != crudo:
            return ganador, {"tipo": "exacta", "entrada": crudo, "soporte": soporte,
                             "dominancia": round(soporte / total, 4)}

    candidato = list(crudo)
    cambios = []
    for i, caracter in enumerate(candidato):
        destinos = estado.get("caracteres", {}).get(caracter, {})
        if not destinos:
            continue
        ganador, soporte = max(destinos.items(), key=lambda x: (x[1], x[0]))
        total = sum(destinos.values())
        if soporte >= min_caracter and soporte / total >= dominancia:
            candidato[i] = ganador
            cambios.append({"posicion": i, "de": caracter, "a": ganador, "soporte": soporte})
    candidato_texto = "".join(candidato)
    patrones = estado.get("patrones", {})
    soporte_nuevo = int(patrones.get(patron_codigo(candidato_texto), 0))
    soporte_viejo = int(patrones.get(patron_codigo(crudo), 0))
    if cambios and soporte_nuevo >= min_patron and soporte_nuevo > soporte_viejo:
        return candidato_texto, {"tipo": "caracteres", "entrada": crudo,
                                 "cambios": cambios, "soporte_patron": soporte_nuevo}
    return texto, None


def _metricas(estado: dict, correcciones: list[sqlite3.Row], cfg: dict) -> dict:
    aciertos = 0
    predicciones = []
    for fila in correcciones:
        esperado = normalizar_codigo(fila["texto_correcto"])
        predicho, _ = predecir_correccion(fila["texto_ocr"], estado, cfg)
        predicho = normalizar_codigo(predicho)
        ok = predicho == esperado
        aciertos += int(ok)
        predicciones.append((fila["id"], ok))
    total = len(correcciones)
    return {"total": total, "aciertos": aciertos,
            "exactitud": round(aciertos / total, 6) if total else 0.0,
            "predicciones": predicciones}


class GestorAprendizaje:
    """Repositorio local y modelo incremental. Una instancia no conserva conexión."""

    def __init__(self, config: dict | None = None, directorio: str | Path | None = None):
        self.config = config or cargar_config()
        self.cfg = self.config.get("aprendizaje", {})
        declarado = directorio or self.cfg.get("directorio", ".aprendizaje")
        self.directorio = Path(declarado)
        if not self.directorio.is_absolute():
            self.directorio = RAIZ_PROYECTO / self.directorio
        self.db = self.directorio / "aprendizaje.sqlite3"
        self._hash_cache: dict[str, tuple[int, int, str]] = {}
        self._estrategias_cache: list[dict] | None = None

    @property
    def activado(self) -> bool:
        return bool(self.cfg.get("activar", True))

    def _conectar(self) -> sqlite3.Connection:
        self.directorio.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db, timeout=20)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS regiones_no_texto (
                id INTEGER PRIMARY KEY AUTOINCREMENT, imagen_hash TEXT NOT NULL,
                bbox_json TEXT NOT NULL, texto_ocr TEXT NOT NULL, activo INTEGER NOT NULL,
                usuario TEXT NOT NULL, actualizado_en TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orientaciones_region (
                imagen_hash TEXT NOT NULL, marco TEXT NOT NULL,
                grados INTEGER NOT NULL CHECK(grados IN (0,90,180,270)),
                usuario TEXT NOT NULL, actualizado_en TEXT NOT NULL,
                PRIMARY KEY(imagen_hash, marco)
            );
            CREATE TABLE IF NOT EXISTS ejecuciones (
                id TEXT PRIMARY KEY, creado_en TEXT NOT NULL, raiz TEXT,
                imagenes INTEGER NOT NULL DEFAULT 0, tokens INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS observaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ejecucion_id TEXT NOT NULL,
                imagen_hash TEXT NOT NULL, ruta_imagen TEXT, texto_ocr TEXT NOT NULL,
                confianza REAL, bbox_json TEXT, motor TEXT, creado_en TEXT NOT NULL,
                firma TEXT,
                FOREIGN KEY(ejecucion_id) REFERENCES ejecuciones(id)
            );
            CREATE TABLE IF NOT EXISTS correcciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT, imagen_hash TEXT NOT NULL,
                ruta_imagen TEXT, texto_ocr TEXT NOT NULL, texto_correcto TEXT NOT NULL,
                bbox_json TEXT, fuente TEXT NOT NULL DEFAULT 'humana', creado_en TEXT NOT NULL,
                UNIQUE(imagen_hash, texto_ocr, texto_correcto)
            );
            CREATE TABLE IF NOT EXISTS correcciones_texto (
                id INTEGER PRIMARY KEY AUTOINCREMENT, imagen_hash TEXT NOT NULL,
                ruta_imagen TEXT, texto_ocr TEXT NOT NULL, texto_correcto TEXT NOT NULL,
                bbox_json TEXT, fuente TEXT NOT NULL DEFAULT 'humana', creado_en TEXT NOT NULL,
                UNIQUE(imagen_hash, texto_ocr, texto_correcto, bbox_json)
            );
            CREATE TABLE IF NOT EXISTS anotaciones_regiones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                carpeta_id TEXT, carpeta_nombre TEXT,
                imagen_hash TEXT NOT NULL, ruta_imagen TEXT,
                imagen_nombre TEXT, bbox_json TEXT NOT NULL,
                poligono_json TEXT,
                texto_correcto TEXT NOT NULL,
                fuente TEXT NOT NULL DEFAULT 'humana', creado_en TEXT NOT NULL,
                UNIQUE(imagen_hash, bbox_json, texto_correcto)
            );
            CREATE TABLE IF NOT EXISTS revisiones (
                tipo TEXT NOT NULL, item_id TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'por_revisar',
                oculto INTEGER NOT NULL DEFAULT 0,
                actualizado_en TEXT NOT NULL,
                PRIMARY KEY(tipo, item_id)
            );
            CREATE TABLE IF NOT EXISTS rotaciones_imagen (
                imagen_hash TEXT PRIMARY KEY, ruta_imagen TEXT,
                grados REAL NOT NULL DEFAULT 0,
                fuente TEXT NOT NULL DEFAULT 'dashboard', actualizado_en TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alertas_atendidas (
                tipo TEXT NOT NULL, item_id TEXT NOT NULL, alerta_id TEXT NOT NULL,
                atendida_en TEXT NOT NULL,
                PRIMARY KEY(tipo, item_id, alerta_id)
            );
            CREATE TABLE IF NOT EXISTS modelos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT UNIQUE NOT NULL,
                padre_id INTEGER, estado TEXT NOT NULL, modelo_json TEXT NOT NULL,
                metricas_json TEXT NOT NULL, creado_en TEXT NOT NULL,
                FOREIGN KEY(padre_id) REFERENCES modelos(id)
            );
            CREATE TABLE IF NOT EXISTS muestras_visuales (
                id TEXT PRIMARY KEY, caso_id TEXT NOT NULL, imagen_hash TEXT NOT NULL,
                ruta_imagen TEXT NOT NULL, ruta_recorte TEXT,
                bbox_json TEXT, texto_ocr TEXT, texto_correcto TEXT,
                accion TEXT NOT NULL, entrenable INTEGER NOT NULL DEFAULT 0,
                campo TEXT, fase TEXT, tor TEXT, confianza REAL,
                modelo_origen TEXT, usuario TEXT NOT NULL DEFAULT 'dashboard',
                confirmada INTEGER NOT NULL DEFAULT 1,
                metadatos_json TEXT, firma TEXT UNIQUE, creado_en TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS imagenes_sin_datos (
                imagen_hash TEXT PRIMARY KEY, ruta_imagen TEXT NOT NULL,
                caso_id TEXT NOT NULL, motivo TEXT, usuario TEXT NOT NULL,
                creado_en TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS modelos_visuales (
                id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT UNIQUE NOT NULL,
                estado TEXT NOT NULL, ruta_pesos TEXT NOT NULL,
                metricas_json TEXT NOT NULL, configuracion_json TEXT NOT NULL,
                creado_en TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS roi_preferidas (
                alcance TEXT NOT NULL, clave TEXT NOT NULL, fase TEXT,
                roi_json TEXT NOT NULL, zoom REAL, actualizado_en TEXT NOT NULL,
                PRIMARY KEY(alcance, clave, fase)
            );
            CREATE TABLE IF NOT EXISTS estrategias_ocr (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                imagen_hash TEXT NOT NULL, ruta_imagen TEXT, caso_id TEXT,
                grupo_ruta TEXT, bbox_firma TEXT NOT NULL, zona TEXT NOT NULL,
                project_id TEXT, tipo_st TEXT, module_version TEXT, fase TEXT,
                componente TEXT, campo TEXT,
                orientacion_base INTEGER NOT NULL, ajuste REAL NOT NULL DEFAULT 0,
                variante TEXT NOT NULL DEFAULT 'auto', tipo_esperado TEXT NOT NULL DEFAULT 'auto',
                texto_resultado TEXT, confianza REAL, congruencia REAL,
                origen TEXT NOT NULL DEFAULT 'revision_humana', usuario TEXT NOT NULL DEFAULT 'dashboard',
                creado_en TEXT NOT NULL, actualizado_en TEXT NOT NULL,
                UNIQUE(imagen_hash, bbox_firma, campo)
            );
            CREATE INDEX IF NOT EXISTS idx_observaciones_hash ON observaciones(imagen_hash);
            CREATE INDEX IF NOT EXISTS idx_anotaciones_hash ON anotaciones_regiones(imagen_hash);
            CREATE INDEX IF NOT EXISTS idx_anotaciones_carpeta ON anotaciones_regiones(carpeta_id);
            CREATE INDEX IF NOT EXISTS idx_revisiones_estado ON revisiones(estado, oculto);
            CREATE INDEX IF NOT EXISTS idx_modelos_estado ON modelos(estado);
            CREATE INDEX IF NOT EXISTS idx_muestras_visuales_caso
                ON muestras_visuales(caso_id, entrenable);
            CREATE INDEX IF NOT EXISTS idx_modelos_visuales_estado
                ON modelos_visuales(estado);
            CREATE INDEX IF NOT EXISTS idx_estrategias_ocr_zona
                ON estrategias_ocr(zona, fase, campo, tipo_st);
            CREATE INDEX IF NOT EXISTS idx_estrategias_ocr_imagen
                ON estrategias_ocr(imagen_hash);
        """)
        # Migración aditiva para instalaciones que ya abrieron la tabla v1.
        columnas_anot = {fila[1] for fila in con.execute("PRAGMA table_info(anotaciones_regiones)")}
        if "poligono_json" not in columnas_anot:
            con.execute("ALTER TABLE anotaciones_regiones ADD COLUMN poligono_json TEXT")
        columnas = {fila[1] for fila in con.execute("PRAGMA table_info(muestras_visuales)")}
        for nombre, definicion in {
            "campo": "TEXT", "fase": "TEXT", "tor": "TEXT", "confianza": "REAL",
            "modelo_origen": "TEXT", "confirmada": "INTEGER NOT NULL DEFAULT 1",
            "metadatos_json": "TEXT", "firma": "TEXT",
            "usuario": "TEXT NOT NULL DEFAULT 'dashboard'",
        }.items():
            if nombre not in columnas:
                con.execute(f"ALTER TABLE muestras_visuales ADD COLUMN {nombre} {definicion}")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_muestras_visuales_firma "
                    "ON muestras_visuales(firma)")
        # V13: observaciones incrementales e idempotentes. Una ejecución puede
        # reanudarse varias veces sin duplicar la misma lectura de una imagen.
        columnas_obs = {fila[1] for fila in con.execute("PRAGMA table_info(observaciones)")}
        if "firma" not in columnas_obs:
            con.execute("ALTER TABLE observaciones ADD COLUMN firma TEXT")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_observaciones_firma "
                    "ON observaciones(firma) WHERE firma IS NOT NULL")
        return con

    def guardar_roi_preferida(self, alcance: str, clave: str, fase: str | None,
                              roi: dict, zoom: float | None = None) -> dict:
        if alcance not in {"proyecto", "fase", "etiqueta"}:
            raise ValueError("El alcance ROI debe ser proyecto, fase o etiqueta.")
        valores = {k: float(roi[k]) for k in ("x", "y", "ancho", "alto")}
        if not (0 <= valores["x"] < 1 and 0 <= valores["y"] < 1 and
                0 < valores["ancho"] <= 1 and 0 < valores["alto"] <= 1 and
                valores["x"] + valores["ancho"] <= 1.0001 and
                valores["y"] + valores["alto"] <= 1.0001):
            raise ValueError("La ROI persistente debe estar expresada entre 0 y 1.")
        fase_db = str(fase or "") if alcance != "proyecto" else ""
        with self._conectar() as con:
            con.execute("""INSERT INTO roi_preferidas
                (alcance, clave, fase, roi_json, zoom, actualizado_en)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(alcance, clave, fase) DO UPDATE SET
                roi_json=excluded.roi_json, zoom=excluded.zoom,
                actualizado_en=excluded.actualizado_en""",
                (alcance, str(clave), fase_db, json.dumps(valores), zoom, _ahora()))
        return {"alcance": alcance, "clave": str(clave), "fase": fase_db,
                "roi": valores, "zoom": zoom}

    def roi_preferida(self, proyecto: str, fase: str, etiqueta: str) -> dict | None:
        if not self.db.exists():
            return None
        consultas = [("etiqueta", etiqueta, fase), ("fase", proyecto, fase),
                     ("proyecto", proyecto, "")]
        with self._conectar() as con:
            for alcance, clave, fase_db in consultas:
                fila = con.execute("""SELECT * FROM roi_preferidas
                    WHERE alcance=? AND clave=? AND fase=?""",
                    (alcance, clave, fase_db)).fetchone()
                if fila:
                    return {"alcance": fila["alcance"], "roi": json.loads(fila["roi_json"]),
                            "zoom": fila["zoom"], "actualizado_en": fila["actualizado_en"]}
        return None

    # R15.4 (HIGH-01): transacción compensable entre almacenes. Las rutas de
    # mutación que combinan efectos SQLite con commit del documento toman un
    # snapshot de las filas ligadas a la imagen ANTES de los efectos; si el
    # commit final falla, ``restaurar_evidencias_imagen`` devuelve el almacén
    # a su estado exacto previo (una sola transacción). La petición fallida
    # no deja efectos persistentes en NINGÚN almacén.
    _TABLAS_EVIDENCIA_IMAGEN = (
        "correcciones_texto", "correcciones", "muestras_visuales",
        "estrategias_ocr", "imagenes_sin_datos", "ediciones_zona",
        # R15.5 (HIGH-02): la rotación guardada es parte de la misma
        # transacción compensable que evidencias y documento.
        "rotaciones_imagen",
        # R15.6 (MEDIO-06): marcas no-texto, anotaciones de región y
        # orientaciones regionales entran en el snapshot común para que
        # TODOS los efectos humanos por imagen sean compensables.
        "regiones_no_texto", "anotaciones_regiones", "orientaciones_region",
    )

    @staticmethod
    def _tabla_existe(con: sqlite3.Connection, nombre: str) -> bool:
        return con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (nombre,)).fetchone() is not None

    def snapshot_evidencias_imagen(self, ruta_imagen: str | Path,
                                   caso_id: str | None = None,
                                   tipo_revision: str = "carpeta") -> dict:
        """Estado previo de las evidencias SQLite de una imagen (+ revisión).

        ``tipo_revision`` (R15.5): fila de ``revisiones`` capturada/restaurada
        junto al snapshot; ``carpeta`` o ``externa`` según el documento bajo
        el que se revisa la imagen.
        """
        ruta = Path(ruta_imagen)
        imagen_hash = hash_archivo(ruta) if ruta.is_file() else None
        snap = {"imagen_hash": imagen_hash, "caso_id": None if caso_id is None
                else str(caso_id), "tablas": {}, "revision": None,
                "tipo_revision": tipo_revision}
        if imagen_hash is None or not self.db.exists():
            return snap
        with self._conectar() as con:
            for tabla in self._TABLAS_EVIDENCIA_IMAGEN:
                if not self._tabla_existe(con, tabla):
                    continue
                filas = [dict(f) for f in con.execute(
                    f"SELECT * FROM {tabla} WHERE imagen_hash=?",
                    (imagen_hash,)).fetchall()]
                snap["tablas"][tabla] = filas
                if tabla == "ediciones_zona" and filas:
                    ids = [f["id"] for f in filas]
                    marcas = ",".join("?" * len(ids))
                    if self._tabla_existe(con, "ediciones_zona_detalle"):
                        # R15.6: la PK de ediciones_zona_detalle es
                        # ``edicion_id`` (no ``id``): con la columna equivocada
                        # el snapshot/restauración de zonas editadas fallaba.
                        snap["tablas"]["ediciones_zona_detalle"] = [
                            dict(f) for f in con.execute(
                                f"SELECT * FROM ediciones_zona_detalle "
                                f"WHERE edicion_id IN ({marcas})", ids).fetchall()]
            if snap["caso_id"] is not None and self._tabla_existe(con, "revisiones"):
                fila = con.execute(
                    "SELECT * FROM revisiones WHERE tipo=? AND item_id=?",
                    (snap.get("tipo_revision") or "carpeta",
                     snap["caso_id"])).fetchone()
                snap["revision"] = dict(fila) if fila else None
        return snap

    def restaurar_evidencias_imagen(self, snap: dict) -> bool:
        """Restaura fielmente el snapshot; True si el almacén quedó consistente.

        Best-effort con los recortes de muestras nuevas (archivos derivados):
        se eliminan los que no existían en el snapshot; si no se puede, las
        filas SQLite (la fuente autoritativa) sí quedan restauradas.
        """
        if not isinstance(snap, dict) or not snap.get("imagen_hash"):
            return False
        imagen_hash = snap["imagen_hash"]
        tablas_previas = snap.get("tablas") or {}
        try:
            con = self._conectar()
        except sqlite3.Error:
            return False
        try:
            recortes_previos = {f.get("id") for f in
                                tablas_previas.get("muestras_visuales", [])}
            recortes_nuevos = []
            if self._tabla_existe(con, "muestras_visuales"):
                recortes_nuevos = [
                    (f["id"], f["ruta_recorte"]) for f in con.execute(
                        "SELECT id, ruta_recorte FROM muestras_visuales "
                        "WHERE imagen_hash=?", (imagen_hash,)).fetchall()
                    if f["id"] not in recortes_previos]
            with con:  # una sola transacción
                for tabla in self._TABLAS_EVIDENCIA_IMAGEN:
                    if not self._tabla_existe(con, tabla):
                        continue
                    if tabla == "ediciones_zona":
                        ids = [f["id"] for f in con.execute(
                            "SELECT id FROM ediciones_zona WHERE imagen_hash=?",
                            (imagen_hash,)).fetchall()]
                        if ids and self._tabla_existe(con, "ediciones_zona_detalle"):
                            marcas = ",".join("?" * len(ids))
                            con.execute(
                                f"DELETE FROM ediciones_zona_detalle WHERE edicion_id IN ({marcas})",
                                ids)
                    con.execute(f"DELETE FROM {tabla} WHERE imagen_hash=?",
                                (imagen_hash,))
                for tabla, filas in tablas_previas.items():
                    if not self._tabla_existe(con, tabla):
                        continue
                    for fila in filas:
                        columnas = ",".join(fila.keys())
                        marcas = ",".join("?" * len(fila))
                        con.execute(
                            f"INSERT OR REPLACE INTO {tabla} ({columnas}) "
                            f"VALUES ({marcas})", tuple(fila.values()))
                if snap.get("caso_id") is not None and self._tabla_existe(con, "revisiones"):
                    tipo_rev = snap.get("tipo_revision") or "carpeta"
                    if snap.get("revision") is None:
                        con.execute(
                            "DELETE FROM revisiones WHERE tipo=? AND item_id=?",
                            (tipo_rev, snap["caso_id"]))
                    else:
                        fila = snap["revision"]
                        columnas = ",".join(fila.keys())
                        marcas = ",".join("?" * len(fila))
                        con.execute(
                            f"INSERT OR REPLACE INTO revisiones ({columnas}) "
                            f"VALUES ({marcas})", tuple(fila.values()))
            for _id, recorte in recortes_nuevos:
                if recorte:
                    try:
                        Path(str(recorte)).unlink(missing_ok=True)
                    except OSError:
                        pass
            return True
        except sqlite3.Error:
            return False
        finally:
            con.close()

    def registrar_muestra_visual(self, ruta_imagen: str | Path, caso_id: str,
                                 texto_ocr: str, texto_correcto: str, bbox=None,
                                 accion: str = "corregir",
                                 entrenable: bool = True, campo: str | None = None,
                                 fase: str | None = None, tor: str | None = None,
                                 confianza: float | None = None,
                                 modelo_origen: str | None = None,
                                 usuario: str = "dashboard",
                                 metadatos: dict | None = None) -> dict:
        """Guarda una evidencia y su recorte exacto para entrenamiento auditable."""
        acciones = {"aceptar", "corregir", "ilegible", "no_es_campo",
                    "guardar_sin_entrenar", "confirmar_entrenar"}
        if accion not in acciones:
            raise ValueError("Acción de supervisión no reconocida.")
        ruta = Path(ruta_imagen)
        if not ruta.is_file():
            raise ValueError("La imagen de entrenamiento ya no está disponible.")
        import cv2
        import numpy as np
        datos = np.fromfile(str(ruta), dtype=np.uint8)
        imagen = cv2.imdecode(datos, cv2.IMREAD_COLOR)
        if imagen is None:
            raise ValueError("La imagen de entrenamiento está corrupta o no se puede decodificar.")
        if (metadatos or {}).get("giro_foto"):
            from ocr_engine import rotar_imagen_libre
            imagen = rotar_imagen_libre(imagen, float(metadatos["giro_foto"]))
        alto_imagen, ancho_imagen = imagen.shape[:2]
        caja = None
        recorte = imagen
        if bbox is not None:
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                raise ValueError("La región de entrenamiento debe tener cuatro coordenadas.")
            x, y, ancho, alto = (int(round(float(v))) for v in bbox)
            x, y = max(0, x), max(0, y)
            ancho, alto = min(ancho, ancho_imagen - x), min(alto, alto_imagen - y)
            if ancho < 2 or alto < 2:
                raise ValueError("El recorte de entrenamiento está fuera de la imagen.")
            caja = [x, y, ancho, alto]
            recorte = imagen[y:y + alto, x:x + ancho]
        poligono = (metadatos or {}).get("poligono_lectura")
        if poligono is not None:
            # Las esquinas están en orden de lectura, no ordenadas por x/y:
            # esto conserva el giro local y la perspectiva en la muestra.
            puntos = np.asarray(poligono, dtype=np.float32)
            if puntos.shape != (4,2) or not np.isfinite(puntos).all():
                raise ValueError("Polígono de supervisión inválido; reprocesa la imagen.")
            rw = int(round(max(np.linalg.norm(puntos[1]-puntos[0]), np.linalg.norm(puntos[2]-puntos[3]))))
            rh = int(round(max(np.linalg.norm(puntos[3]-puntos[0]), np.linalg.norm(puntos[2]-puntos[1]))))
            if not (2 <= rw <= 2*max(imagen.shape[:2]) and 2 <= rh <= 2*max(imagen.shape[:2])):
                raise ValueError("Dimensiones de la muestra regional inválidas.")
            destino = np.array([[0,0],[rw-1,0],[rw-1,rh-1],[0,rh-1]],dtype=np.float32)
            matriz = cv2.getPerspectiveTransform(puntos, destino)
            recorte = cv2.warpPerspective(imagen, matriz, (rw,rh))
        imagen_hash = hash_archivo(ruta)
        firma = hashlib.sha256(json.dumps({
            "imagen_hash": imagen_hash, "caso_id": str(caso_id), "bbox": caja,
            "texto_ocr": str(texto_ocr), "texto_correcto": str(texto_correcto),
            "accion": accion, "campo": campo, "geometria_version": 2,
            "giro_foto": (metadatos or {}).get("giro_foto", 0),
            "poligono_lectura": poligono,
        }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._conectar() as con:
            existente = con.execute(
                "SELECT * FROM muestras_visuales WHERE firma=?", (firma,)).fetchone()
        if existente:
            vigente_entrenable = bool(entrenable and accion not in {"ilegible", "no_es_campo"}
                                      and str(texto_correcto).strip())
            with self._conectar() as con:
                con.execute("""UPDATE muestras_visuales SET entrenable=0, confirmada=0
                    WHERE imagen_hash=? AND bbox_json=? AND id<>?""",
                    (imagen_hash, json.dumps(caja), existente["id"]))
                con.execute("UPDATE muestras_visuales SET confirmada=1, entrenable=?, creado_en=? WHERE id=?",
                            (int(vigente_entrenable), datetime.now().isoformat(timespec="microseconds"), existente["id"]))
            return {"id": existente["id"], "ruta_recorte": existente["ruta_recorte"],
                    "bbox": caja, "accion": accion,
                    "entrenable": vigente_entrenable, "duplicada": True}
        muestra_id = uuid.uuid4().hex
        carpeta = self.directorio / "dataset_visual" / "recortes"
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta_recorte = carpeta / f"{muestra_id}.png"
        ok, codificada = cv2.imencode(".png", recorte)
        if not ok:
            raise ValueError("No fue posible serializar el recorte de entrenamiento.")
        codificada.tofile(str(ruta_recorte))
        entrenable = bool(entrenable and accion not in {"ilegible", "no_es_campo"}
                         and str(texto_correcto).strip())
        with self._conectar() as con:
            con.execute("""UPDATE muestras_visuales SET entrenable=0, confirmada=0
                WHERE imagen_hash=? AND bbox_json=?""", (imagen_hash, json.dumps(caja)))
            con.execute("""
                INSERT INTO muestras_visuales
                (id, caso_id, imagen_hash, ruta_imagen, ruta_recorte, bbox_json,
                 texto_ocr, texto_correcto, accion, entrenable, campo, fase, tor,
                 confianza, modelo_origen, usuario, confirmada, metadatos_json, firma, creado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (muestra_id, str(caso_id), imagen_hash, str(ruta), str(ruta_recorte),
                  json.dumps(caja), str(texto_ocr), str(texto_correcto), accion,
                  int(entrenable), campo, fase, tor, confianza, modelo_origen,
                  str(usuario or "dashboard"), 1,
                  json.dumps(metadatos or {}, ensure_ascii=False), firma, _ahora()))
        return {"id": muestra_id, "ruta_recorte": str(ruta_recorte),
                "bbox": caja, "accion": accion, "entrenable": entrenable}

    def preferencia_rotacion(self, ruta_imagen: str | Path | None) -> dict | None:
        """Devuelve la decisión humana, distinguiendo 0° de ausencia de decisión."""
        if not ruta_imagen or not self.db.exists() or not Path(ruta_imagen).is_file():
            return None
        try:
            imagen_hash = hash_archivo(ruta_imagen)
        except OSError:
            return None
        with self._conectar() as con:
            fila = con.execute(
                "SELECT * FROM rotaciones_imagen WHERE imagen_hash=?", (imagen_hash,)).fetchone()
        if not fila:
            return None
        salida = dict(fila)
        salida["grados"] = round(float(salida["grados"]) % 360, 3)
        return salida

    def rotacion_preferida(self, ruta_imagen: str | Path | None) -> float:
        """Rotación humana en sentido horario; conserva la interfaz histórica."""
        preferencia = self.preferencia_rotacion(ruta_imagen)
        return float(preferencia["grados"]) if preferencia else 0.0

    def orientaciones_regionales(self, ruta_imagen) -> dict:
        if not self.db.exists():
            return {}
        imagen_hash = hash_archivo(ruta_imagen)
        with self._conectar() as con:
            filas = con.execute("SELECT marco, grados FROM orientaciones_region WHERE imagen_hash=?",
                                (imagen_hash,)).fetchall()
        return {f["marco"]: f["grados"] for f in filas}

    def guardar_orientacion_regional(self, ruta_imagen, marco, grados, usuario="dashboard"):
        if not isinstance(marco, str) or len(marco) != 64:
            raise ValueError("El recorte no tiene una geometría válida; reprocesa la imagen.")
        if grados not in (None, 0, 90, 180, 270):
            raise ValueError("El giro debe ser 0, 90, 180 o 270 grados.")
        imagen_hash = hash_archivo(ruta_imagen)
        with self._conectar() as con:
            if grados is None:
                con.execute("DELETE FROM orientaciones_region WHERE imagen_hash=? AND marco=?",
                            (imagen_hash, marco))
            else:
                con.execute("""INSERT INTO orientaciones_region VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(imagen_hash,marco) DO UPDATE SET grados=excluded.grados,
                    usuario=excluded.usuario, actualizado_en=excluded.actualizado_en""",
                    (imagen_hash, marco, grados, usuario, _ahora()))
        return {"marco": marco, "grados": grados}

    @staticmethod
    def _grupo_ruta_estrategia(ruta_imagen) -> str:
        ruta = Path(str(ruta_imagen))
        padres = []
        for p in ruta.parents[:6]:
            nombre = p.name.strip().lower()
            if not nombre:
                continue
            compacta = re.sub(r"[^a-z0-9]", "", nombre)
            proporcion_digitos = (sum(c.isdigit() for c in compacta) / max(1, len(compacta)))
            # Evita que IDs de caso distintos impidan generalizar; conserva 1st/2st.
            if nombre not in {"1st", "2st"} and proporcion_digitos >= .50:
                continue
            padres.append(nombre)
            if len(padres) >= 3:
                break
        return "/".join(reversed(padres))[-240:]

    @staticmethod
    def _firma_bbox_estrategia(bbox, dimensiones) -> tuple[str, str]:
        if not bbox or not dimensiones or len(bbox) != 4 or len(dimensiones) < 2:
            return "sin_bbox", "global"
        x, y, w, h = [float(v) for v in bbox]
        ancho, alto = max(1.0, float(dimensiones[0])), max(1.0, float(dimensiones[1]))
        cx, cy = (x + w / 2) / ancho, (y + h / 2) / alto
        nw, nh = w / ancho, h / alto
        q = lambda v: round(max(0.0, min(1.0, v)) / 0.05) * 0.05
        firma = json.dumps([q(cx), q(cy), q(nw), q(nh)], separators=(",", ":"))
        bx, by = min(2, max(0, int(cx * 3))), min(2, max(0, int(cy * 3)))
        area = max(0.0, nw * nh)
        tam = "s" if area < .04 else "m" if area < .16 else "l"
        return firma, f"{bx}{by}:{tam}"

    def registrar_estrategia_ocr(self, ruta_imagen, bbox, dimensiones, estrategia: dict,
                                 caso_id: str | None = None, contexto: dict | None = None,
                                 usuario: str = "dashboard") -> dict:
        """Guarda una estrategia sólo después de una confirmación humana.

        Reconfirmar la misma caja reemplaza la evidencia anterior de esa imagen,
        por lo que hacer clic varias veces no infla artificialmente el soporte.
        """
        if not ruta_imagen or not Path(ruta_imagen).is_file():
            raise ValueError("La estrategia OCR requiere una imagen existente.")
        estrategia = dict(estrategia or {})
        base = int(round(float(estrategia.get("orientacion_base", 0)))) % 360
        if base not in (0, 90, 180, 270):
            raise ValueError("La orientación base de aprendizaje debe ser 0, 90, 180 o 270 grados.")
        ajuste = max(-45.0, min(45.0, float(estrategia.get("ajuste_manual", estrategia.get("ajuste", 0)) or 0)))
        variante = str(estrategia.get("variante") or "auto").lower()
        if variante not in {"auto", "original", "clahe", "adaptativa", "relieve"}:
            variante = "auto"
        tipo = str(estrategia.get("tipo_esperado") or "auto").lower()
        if tipo not in {"auto", "codigo", "fecha", "numero", "texto"}:
            tipo = "auto"
        contexto = dict(contexto or {})
        firma_bbox, zona = self._firma_bbox_estrategia(bbox, dimensiones)
        imagen_hash = hash_archivo(ruta_imagen)
        ahora = _ahora()
        valores = (
            imagen_hash, str(ruta_imagen), caso_id, self._grupo_ruta_estrategia(ruta_imagen),
            firma_bbox, zona, contexto.get("project_id"), contexto.get("tipo_st"),
            contexto.get("module_version"), contexto.get("fase"), contexto.get("componente"),
            contexto.get("campo"), base, round(ajuste, 2), variante, tipo,
            str(estrategia.get("texto_resultado") or "")[:2048],
            float(estrategia.get("confianza") or 0), float(estrategia.get("congruencia") or 0),
            str(estrategia.get("origen") or "revision_humana")[:64], usuario, ahora, ahora,
        )
        with self._conectar() as con:
            con.execute("""INSERT INTO estrategias_ocr
                (imagen_hash,ruta_imagen,caso_id,grupo_ruta,bbox_firma,zona,project_id,tipo_st,
                 module_version,fase,componente,campo,orientacion_base,ajuste,variante,tipo_esperado,
                 texto_resultado,confianza,congruencia,origen,usuario,creado_en,actualizado_en)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(imagen_hash,bbox_firma,campo) DO UPDATE SET
                  caso_id=excluded.caso_id, grupo_ruta=excluded.grupo_ruta, zona=excluded.zona,
                  project_id=excluded.project_id, tipo_st=excluded.tipo_st,
                  module_version=excluded.module_version, fase=excluded.fase,
                  componente=excluded.componente, orientacion_base=excluded.orientacion_base,
                  ajuste=excluded.ajuste, variante=excluded.variante,
                  tipo_esperado=excluded.tipo_esperado, texto_resultado=excluded.texto_resultado,
                  confianza=excluded.confianza, congruencia=excluded.congruencia,
                  origen=excluded.origen, usuario=excluded.usuario, actualizado_en=excluded.actualizado_en
            """, valores)
        self._estrategias_cache = None
        return {"guardada": True, "zona": zona, "orientacion_base": base,
                "ajuste": round(ajuste, 2), "variante": variante, "tipo_esperado": tipo}

    def sugerir_estrategia_ocr(self, ruta_imagen, bbox, dimensiones,
                               contexto: dict | None = None) -> dict | None:
        """Resume evidencia humana parecida sin dejar que un único caso mande."""
        if not self.db.exists():
            return None
        cfg = dict(self.cfg.get("estrategias_ocr") or {})
        if not bool(cfg.get("activar", True)):
            return None
        min_sugerir = max(1, int(cfg.get("minimo_soporte_sugerencia", 1)))
        min_auto = max(min_sugerir, int(cfg.get("minimo_soporte_automatico", 4)))
        dom_auto = float(cfg.get("dominancia_minima", .75))
        tolerancia = max(1.0, float(cfg.get("tolerancia_ajuste_grados", 4.0)))
        contexto = dict(contexto or {})
        firma_objetivo, zona = self._firma_bbox_estrategia(bbox, dimensiones)
        grupo = self._grupo_ruta_estrategia(ruta_imagen)
        if self._estrategias_cache is None:
            with self._conectar() as con:
                self._estrategias_cache = [dict(r) for r in con.execute(
                    "SELECT * FROM estrategias_ocr ORDER BY id DESC LIMIT 1000").fetchall()]
        filas = list(self._estrategias_cache or [])
        if not filas:
            return None

        def puntuacion_contexto(f):
            score = 0
            if f.get("zona") == zona: score += 6
            if f.get("grupo_ruta") == grupo: score += 2
            for clave, peso in (("project_id",4),("tipo_st",3),("module_version",2),("fase",3),
                                ("campo",2),("componente",1)):
                actual = contexto.get(clave)
                previo = f.get(clave)
                if actual and previo and str(actual) == str(previo): score += peso
                elif actual and previo and str(actual) != str(previo): score -= max(1, peso // 2)
            return score

        puntuadas = [(puntuacion_contexto(f), f) for f in filas]
        mejor_contexto = max((p for p,_ in puntuadas), default=-999)
        hay_contexto = any(contexto.get(k) for k in ("project_id","tipo_st","module_version","fase","campo","componente"))
        # Sin metadatos empresariales (pipeline OCR), sólo generaliza dentro del mismo
        # grupo estable de ruta. En el dashboard sí puede cruzar carpetas cuando fase/
        # proyecto/campo aportan suficiente contexto.
        candidatas = [f for p,f in puntuadas if f.get("zona") == zona
                      and (f.get("grupo_ruta") == grupo or hay_contexto)
                      and p >= max(4, mejor_contexto - 3)]
        if not candidatas:
            return None

        grupos = defaultdict(list)
        for f in candidatas:
            bucket_ajuste = round(float(f.get("ajuste") or 0) / tolerancia) * tolerancia
            clave = (int(f.get("orientacion_base") or 0), bucket_ajuste,
                     str(f.get("variante") or "auto"), str(f.get("tipo_esperado") or "auto"))
            grupos[clave].append(f)
        clave_ganadora, evidencias = max(grupos.items(), key=lambda kv: (
            len({r["imagen_hash"] for r in kv[1]}), sum(float(r.get("congruencia") or 0) for r in kv[1])))
        soporte = len({r["imagen_hash"] for r in evidencias})
        total = len({r["imagen_hash"] for r in candidatas})
        dominancia = soporte / max(1, total)
        base, _, variante, tipo = clave_ganadora
        ajustes = sorted(float(r.get("ajuste") or 0) for r in evidencias)
        ajuste = sum(ajustes) / len(ajustes)

        # V14.9: aprendizaje inmediato. Una sola evidencia humana puede ENSAYARSE
        # en la siguiente imagen si pertenece al mismo grupo estable de ruta y la
        # caja ocupa prácticamente la misma posición/tamaño normalizados. No se
        # impone el resultado: ocr_engine vuelve a compararlo contra la lectura normal.
        inmediato_cfg = bool(cfg.get("aplicar_inmediato_desde_primera_imagen", False))
        exigir_grupo = bool(cfg.get("inmediato_exigir_mismo_grupo_ruta", True))
        exigir_bbox = bool(cfg.get("inmediato_exigir_bbox_equivalente", True))
        evidencias_inmediatas = [r for r in evidencias
            if (not exigir_grupo or r.get("grupo_ruta") == grupo)
            and (not exigir_bbox or r.get("bbox_firma") == firma_objetivo)]
        soporte_inmediato = len({r["imagen_hash"] for r in evidencias_inmediatas})
        aplicacion_inmediata = bool(inmediato_cfg and soporte_inmediato >= 1)
        consolidada = bool(soporte >= min_auto and dominancia >= dom_auto)
        sugerida = bool(soporte >= min_sugerir)
        nivel = ("automatica" if consolidada else
                 "inmediata" if aplicacion_inmediata and soporte == 1 else
                 "sugerida" if sugerida else "recordada")
        return {
            "nivel": nivel,
            "orientacion_base": int(base), "ajuste": round(ajuste, 2),
            "variante": variante, "tipo_esperado": tipo,
            "soporte": soporte, "soporte_inmediato": soporte_inmediato,
            "evidencias_contexto": total,
            "dominancia": round(dominancia, 4),
            "auto_aplicable": bool(consolidada or aplicacion_inmediata),
            "aplicacion_inmediata": aplicacion_inmediata,
            "modo_aplicacion": "contextual_inmediata" if aplicacion_inmediata and not consolidada else
                               "consolidada" if consolidada else "sugerencia",
            "zona": zona,
            "bbox_firma": firma_objetivo,
            "confianza_media": round(sum(float(r.get("confianza") or 0) for r in evidencias)/len(evidencias),4),
            "congruencia_media": round(sum(float(r.get("congruencia") or 0) for r in evidencias)/len(evidencias),2),
        }

    def modelo_visual_activo(self) -> dict | None:
        if not self.db.exists():
            return None
        with self._conectar() as con:
            fila = con.execute(
                "SELECT * FROM modelos_visuales WHERE estado='activo' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(fila) if fila else None

    def activar_modelo_visual(self, version: str) -> dict:
        """Activa sólo un candidato cuya evaluación ya demostró mejora."""
        with self._conectar() as con:
            fila = con.execute(
                "SELECT * FROM modelos_visuales WHERE version=?", (version,)).fetchone()
            if not fila:
                raise ValueError("No existe la versión visual solicitada.")
            metricas = json.loads(fila["metricas_json"])
            base, candidata = metricas.get("base", {}), metricas.get("candidata", {})
            base_prueba, prueba = metricas.get("base_prueba", {}), metricas.get("prueba", {})
            segura = (candidata.get("exactitud", 0) >= base.get("exactitud", 0) and
                      candidata.get("cer", 1) <= base.get("cer", 1) and
                      prueba.get("exactitud", 0) >= base_prueba.get("exactitud", 0) and
                      prueba.get("cer", 1) <= base_prueba.get("cer", 1) and
                      (candidata.get("exactitud", 0) > base.get("exactitud", 0) or
                       candidata.get("cer", 1) < base.get("cer", 1)))
            if not segura:
                raise ValueError("El candidato no puede activarse porque no mejoró la evaluación.")
            con.execute("UPDATE modelos_visuales SET estado='historico' WHERE estado='activo'")
            con.execute("UPDATE modelos_visuales SET estado='activo' WHERE id=?", (fila["id"],))
        return {"activo": version, "metricas": metricas}

    def rollback_modelo_visual(self, version: str | None = None) -> dict:
        with self._conectar() as con:
            activo = con.execute(
                "SELECT * FROM modelos_visuales WHERE estado='activo' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if version:
                destino = con.execute(
                    "SELECT * FROM modelos_visuales WHERE version=?", (version,)).fetchone()
            else:
                destino = con.execute(
                    "SELECT * FROM modelos_visuales WHERE estado='historico' ORDER BY id DESC LIMIT 1"
                ).fetchone()
            if not destino or not Path(destino["ruta_pesos"]).is_file():
                raise ValueError("No existe una versión visual histórica utilizable.")
            con.execute("UPDATE modelos_visuales SET estado='historico' WHERE estado='activo'")
            con.execute("UPDATE modelos_visuales SET estado='activo' WHERE id=?", (destino["id"],))
        return {"anterior": activo["version"] if activo else None,
                "activo": destino["version"]}

    def actualizar_rotacion(self, ruta_imagen: str | Path, grados: float,
                            fuente: str = "dashboard") -> dict:
        if not Path(ruta_imagen).is_file():
            raise ValueError("La imagen ya no está disponible.")
        grados = round(float(grados) % 360, 3)
        imagen_hash = hash_archivo(ruta_imagen)
        with self._conectar() as con:
            con.execute("""
                INSERT INTO rotaciones_imagen
                    (imagen_hash, ruta_imagen, grados, fuente, actualizado_en)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(imagen_hash) DO UPDATE SET
                    ruta_imagen=excluded.ruta_imagen, grados=excluded.grados,
                    fuente=excluded.fuente, actualizado_en=excluded.actualizado_en
            """, (imagen_hash, str(ruta_imagen), grados, fuente, _ahora()))
        return {"imagen_hash": imagen_hash, "grados": grados,
                "aplicar_en_siguiente_ocr": True, "actualizado_en": _ahora()}

    def eliminar_rotacion(self, ruta_imagen: str | Path) -> dict:
        """Quita la prioridad manual para volver al análisis automático."""
        if not Path(ruta_imagen).is_file():
            raise ValueError("La imagen ya no está disponible.")
        imagen_hash = hash_archivo(ruta_imagen)
        with self._conectar() as con:
            eliminadas = con.execute(
                "DELETE FROM rotaciones_imagen WHERE imagen_hash=?", (imagen_hash,)).rowcount
        return {"imagen_hash": imagen_hash, "rotacion_manual_eliminada": bool(eliminadas),
                "aplicar_en_siguiente_ocr": True, "actualizado_en": _ahora()}

    def rotar_evidencias_imagen(self, ruta_imagen: str | Path, grados: float,
                                dimensiones: tuple[int, int], *,
                                grados_desde: float | None = None,
                                grados_hasta: float | None = None,
                                dimensiones_fuente: tuple[int, int] | None = None) -> dict:
        """Mantiene alineadas correcciones y regiones al girar su vista OCR."""
        grados = float(grados) % 360
        if abs(grados) < 1e-6 or not self.db.exists():
            return {"evidencias_rotadas": 0}
        ancho, alto = (int(dimensiones[0]), int(dimensiones[1]))
        imagen_hash = hash_archivo(ruta_imagen)
        actualizadas = 0
        with self._conectar() as con:
            for tabla in ("correcciones_texto", "correcciones", "anotaciones_regiones", "regiones_no_texto"):
                filas = con.execute(
                    f"SELECT id, bbox_json FROM {tabla} WHERE imagen_hash=?",
                    (imagen_hash,)).fetchall()
                for fila in filas:
                    bbox = json.loads(fila["bbox_json"])
                    if bbox is None:
                        continue
                    girada = (transformar_bbox_entre_rotaciones(
                        bbox, grados_desde, grados_hasta, *dimensiones_fuente)
                        if (grados_desde is not None and grados_hasta is not None
                            and dimensiones_fuente is not None)
                        else rotar_bbox(bbox, grados, ancho, alto))
                    con.execute(f"UPDATE {tabla} SET bbox_json=? WHERE id=?",
                                (json.dumps(girada), fila["id"]))
                    actualizadas += 1
        return {"evidencias_rotadas": actualizadas}

    def listar_rotaciones(self, rutas_imagen: list[str | Path]) -> dict[str, dict]:
        if not self.db.exists():
            return {}
        hashes = {}
        for ruta in rutas_imagen:
            try:
                if Path(ruta).is_file():
                    hashes[hash_archivo(ruta)] = str(ruta)
            except OSError:
                continue
        if not hashes:
            return {}
        marcadores = ",".join("?" for _ in hashes)
        with self._conectar() as con:
            filas = con.execute(f"""
                SELECT * FROM rotaciones_imagen
                WHERE imagen_hash IN ({marcadores})
            """, list(hashes)).fetchall()
        return {fila["imagen_hash"]: dict(fila) for fila in filas}

    def registrar_observacion_incremental(self, resultado_ocr: dict,
                                          raiz: str | None = None,
                                          ejecucion_id: str | None = None) -> dict:
        """Persiste una imagen terminada inmediatamente y sin duplicarla al reanudar.

        V13 usa una firma ligada a ``ejecucion_id`` + imagen + bbox + texto + motor.
        Así una reanudación conserva la misma ejecución y es idempotente, mientras
        una ejecución realmente nueva puede volver a registrar la observación.
        """
        if not self.activado or not self.cfg.get("registrar_observaciones", True):
            return {"registrada": False, "motivo": "aprendizaje desactivado"}
        ruta = str((resultado_ocr or {}).get("imagen") or "")
        if not ruta or not Path(ruta).is_file():
            return {"registrada": False, "motivo": "imagen no disponible"}
        ejecucion_id = str(ejecucion_id or uuid.uuid4().hex)
        try:
            stat = Path(ruta).stat()
            clave_hash = (int(stat.st_size), int(stat.st_mtime_ns))
            guardado = self._hash_cache.get(ruta)
            if guardado and guardado[:2] == clave_hash:
                imagen_hash = guardado[2]
            else:
                imagen_hash = hash_archivo(ruta)
                self._hash_cache[ruta] = (*clave_hash, imagen_hash)
        except OSError:
            return {"registrada": False, "motivo": "no se pudo calcular hash"}
        unidades = list((resultado_ocr or {}).get("tokens") or []) + list(
            (resultado_ocr or {}).get("lineas_texto") or [])
        filas = []
        vistas = set()
        creado = _ahora()
        motor = (resultado_ocr or {}).get("motor")
        for token in unidades:
            texto = str(token.get("texto_original") or token.get("texto", ""))
            bbox_json = json.dumps(token.get("bbox"), ensure_ascii=False)
            local = (texto, bbox_json)
            if not texto or local in vistas:
                continue
            vistas.add(local)
            firma = hashlib.sha256(json.dumps([
                ejecucion_id, imagen_hash, texto, bbox_json, motor
            ], ensure_ascii=False, sort_keys=False).encode("utf-8")).hexdigest()
            filas.append((ejecucion_id, imagen_hash, ruta, texto,
                          token.get("confianza"), bbox_json, motor, creado, firma))
        with self._conectar() as con:
            con.execute("""INSERT OR IGNORE INTO ejecuciones
                (id, creado_en, raiz, imagenes, tokens) VALUES (?, ?, ?, 0, 0)""",
                (ejecucion_id, creado, raiz))
            antes = con.total_changes
            con.executemany("""
                INSERT OR IGNORE INTO observaciones
                (ejecucion_id, imagen_hash, ruta_imagen, texto_ocr, confianza,
                 bbox_json, motor, creado_en, firma) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, filas)
            insertadas = max(0, con.total_changes - antes)
            conteos = con.execute("""SELECT COUNT(*) AS tokens,
                COUNT(DISTINCT imagen_hash) AS imagenes FROM observaciones
                WHERE ejecucion_id=?""", (ejecucion_id,)).fetchone()
            con.execute("UPDATE ejecuciones SET raiz=COALESCE(raiz, ?), imagenes=?, tokens=? "
                        "WHERE id=?",
                        (raiz, int(conteos["imagenes"]), int(conteos["tokens"]), ejecucion_id))
        return {"registrada": True, "ejecucion_id": ejecucion_id,
                "imagen": ruta, "tokens_nuevos": insertadas,
                "tokens": len(filas)}

    def finalizar_ejecucion_incremental(self, ejecucion_id: str) -> dict:
        """Devuelve conteos confirmados de una ejecución incremental ya persistida."""
        if not self.activado or not self.db.exists():
            return {"registrada": False, "motivo": "aprendizaje desactivado"}
        with self._conectar() as con:
            fila = con.execute("SELECT * FROM ejecuciones WHERE id=?",
                               (str(ejecucion_id),)).fetchone()
        if not fila:
            return {"registrada": False, "ejecucion_id": str(ejecucion_id),
                    "imagenes": 0, "tokens": 0}
        return {"registrada": True, "ejecucion_id": str(ejecucion_id),
                "imagenes": int(fila["imagenes"] or 0),
                "tokens": int(fila["tokens"] or 0)}

    def registrar_ejecucion(self, resultados_ocr: list[dict], raiz: str | None = None) -> dict:
        if not self.activado or not self.cfg.get("registrar_observaciones", True):
            return {"registrada": False, "motivo": "aprendizaje desactivado"}
        ejecucion_id = uuid.uuid4().hex
        observaciones = []
        hashes: dict[str, str] = {}
        for resultado in resultados_ocr:
            ruta = str(resultado.get("imagen") or "")
            if not ruta or not Path(ruta).is_file():
                continue
            try:
                imagen_hash = hashes.setdefault(ruta, hash_archivo(ruta))
            except OSError:
                continue
            unidades = list(resultado.get("tokens") or []) + list(
                resultado.get("lineas_texto") or [])
            vistas = set()
            for token in unidades:
                firma = (str(token.get("texto_original") or token.get("texto", "")),
                         json.dumps(token.get("bbox")))
                if firma in vistas:
                    continue
                vistas.add(firma)
                observaciones.append((
                    ejecucion_id, imagen_hash, ruta,
                    str(token.get("texto_original") or token["texto"]),
                    token.get("confianza"), json.dumps(token.get("bbox")),
                    resultado.get("motor"), _ahora(),
                ))
        with self._conectar() as con:
            con.execute("INSERT INTO ejecuciones VALUES (?, ?, ?, ?, ?)",
                        (ejecucion_id, _ahora(), raiz, len(hashes), len(observaciones)))
            con.executemany("""
                INSERT INTO observaciones
                (ejecucion_id, imagen_hash, ruta_imagen, texto_ocr, confianza,
                 bbox_json, motor, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, observaciones)
        return {"registrada": True, "ejecucion_id": ejecucion_id,
                "imagenes": len(hashes), "tokens": len(observaciones)}

    def registrar_correccion(self, texto_ocr: str, texto_correcto: str,
                             ruta_imagen: str | None = None, imagen_hash: str | None = None,
                             bbox=None, fuente: str = "humana", caso_id: str | None = None,
                             accion: str = "confirmar_entrenar",
                             entrenar_visual: bool = True, campo: str | None = None,
                             fase: str | None = None, tor: str | None = None,
                             confianza: float | None = None,
                             modelo_origen: str | None = None,
                             usuario: str = "dashboard",
                             metadatos: dict | None = None) -> dict:
        crudo_original = str(texto_ocr).strip()
        correcto_original = str(texto_correcto).strip()
        # La memoria textual debe aceptar cualquier lectura visible, incluso si el
        # OCR original contiene sólo signos (";", "|", ".", etc.).  La
        # normalización alfanumérica se usa únicamente para el modelo ligero de
        # códigos; no debe impedir guardar o sobrescribir la verdad humana.
        if not crudo_original or not correcto_original:
            raise ValueError("La lectura OCR y la corrección deben contener texto visible.")
        crudo, correcto = normalizar_codigo(crudo_original), normalizar_codigo(correcto_original)
        if imagen_hash is None:
            if not ruta_imagen or not Path(ruta_imagen).is_file():
                raise ValueError("Se requiere una imagen existente o su hash.")
            imagen_hash = hash_archivo(ruta_imagen)
        duplicada_texto = False
        duplicada_modelo = False
        confirmado_en = datetime.now().isoformat(timespec="microseconds")
        with self._conectar() as con:
            try:
                con.execute("""
                    INSERT INTO correcciones_texto
                    (imagen_hash, ruta_imagen, texto_ocr, texto_correcto, bbox_json, fuente, creado_en)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (imagen_hash, ruta_imagen, crudo_original, correcto_original,
                      json.dumps(bbox), fuente, confirmado_en))
            except sqlite3.IntegrityError:
                duplicada_texto = True
                con.execute("""UPDATE correcciones_texto SET creado_en=?, fuente=?
                    WHERE imagen_hash=? AND texto_ocr=? AND texto_correcto=? AND bbox_json=?""",
                    (confirmado_en, fuente, imagen_hash, crudo_original, correcto_original, json.dumps(bbox)))

            # Cambios exclusivamente de espacios/saltos y lecturas que no
            # contienen caracteres del alfabeto operativo se conservan como
            # verdad textual/layout, pero no contaminan el modelo de códigos.
            if crudo and correcto and crudo != correcto:
                try:
                    con.execute("""
                        INSERT INTO correcciones
                        (imagen_hash, ruta_imagen, texto_ocr, texto_correcto, bbox_json, fuente, creado_en)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (imagen_hash, ruta_imagen, crudo, correcto,
                          json.dumps(bbox), fuente, confirmado_en))
                except sqlite3.IntegrityError:
                    duplicada_modelo = True
                    con.execute("""UPDATE correcciones SET creado_en=? WHERE imagen_hash=?
                        AND texto_ocr=? AND texto_correcto=?""", (confirmado_en, imagen_hash, crudo, correcto))
            else:
                duplicada_modelo = True
        # Las correcciones quedan en cola. Tanto las reglas de normalización
        # como el reconocedor visual se evalúan por lote mediante una acción
        # explícita; nunca se entrena o promueve un modelo por cada edición.
        entrenamiento = None
        muestra_visual = None
        advertencia_visual = None
        if ruta_imagen and caso_id:
            try:
                muestra_visual = self.registrar_muestra_visual(
                    ruta_imagen, caso_id, crudo_original, correcto_original, bbox,
                    accion=accion, entrenable=entrenar_visual, campo=campo, fase=fase,
                    tor=tor, confianza=confianza, modelo_origen=modelo_origen,
                    usuario=usuario, metadatos=metadatos)
            except ValueError as exc:
                advertencia_visual = str(exc)
        return {
            "registrada": not duplicada_texto,
            "duplicada": duplicada_texto,
            "texto_ocr": crudo_original,
            "texto_correcto": correcto_original,
            "tipo": "modelo_codigo" if crudo and correcto and crudo != correcto else "layout",
            "entrenamiento": entrenamiento,
            "muestra_visual": muestra_visual,
            "advertencia_visual": advertencia_visual,
        }

    def registrar_region(self, texto_correcto: str, bbox, poligono=None,
                         ruta_imagen: str | None = None,
                         imagen_hash: str | None = None,
                         carpeta_id: str | None = None,
                         carpeta_nombre: str | None = None,
                         imagen_nombre: str | None = None,
                         fuente: str = "dashboard_region", fase: str | None = None,
                         tor: str | None = None, modelo_origen: str | None = None,
                         usuario: str = "dashboard", entrenable: bool = False,
                         metadatos: dict | None = None) -> dict:
        """Guarda texto humano localizado aunque el OCR no haya producido token."""
        texto = str(texto_correcto).strip()
        if not texto:
            raise ValueError("El texto confirmado de la región no puede estar vacío.")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise ValueError("La región debe contener x, y, ancho y alto.")
        try:
            x, y, ancho, alto = (int(round(float(v))) for v in bbox)
        except (TypeError, ValueError) as exc:
            raise ValueError("Las coordenadas de la región no son válidas.") from exc
        if x < 0 or y < 0 or ancho < 2 or alto < 2:
            raise ValueError("Selecciona una región visible de al menos 2 × 2 píxeles.")
        if imagen_hash is None:
            if not ruta_imagen or not Path(ruta_imagen).is_file():
                raise ValueError("Se requiere una imagen existente o su hash.")
            imagen_hash = hash_archivo(ruta_imagen)
        bbox_limpio = [x, y, ancho, alto]
        poligono_limpio = None
        if poligono is not None:
            import numpy as np
            puntos = np.asarray(poligono, dtype=float)
            if puntos.shape != (4, 2) or not np.isfinite(puntos).all():
                raise ValueError("El recorte inclinado debe tener cuatro esquinas válidas.")
            poligono_limpio = [[round(float(px), 3), round(float(py), 3)] for px, py in puntos]
        duplicada = False
        with self._conectar() as con:
            try:
                cursor = con.execute("""
                    INSERT INTO anotaciones_regiones
                    (carpeta_id, carpeta_nombre, imagen_hash, ruta_imagen,
                     imagen_nombre, bbox_json, poligono_json, texto_correcto, fuente, creado_en)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (carpeta_id, carpeta_nombre, imagen_hash, ruta_imagen,
                      imagen_nombre or (Path(ruta_imagen).name if ruta_imagen else None),
                      json.dumps(bbox_limpio),
                      json.dumps(poligono_limpio) if poligono_limpio is not None else None,
                      texto, fuente, _ahora()))
                anotacion_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                duplicada = True
                fila = con.execute("""
                    SELECT id FROM anotaciones_regiones
                    WHERE imagen_hash=? AND bbox_json=? AND texto_correcto=?
                """, (imagen_hash, json.dumps(bbox_limpio), texto)).fetchone()
                anotacion_id = fila["id"] if fila else None
                if anotacion_id is not None and poligono_limpio is not None:
                    con.execute("UPDATE anotaciones_regiones SET poligono_json=? WHERE id=?",
                                (json.dumps(poligono_limpio), anotacion_id))
        muestra_visual = None
        advertencia_visual = None
        if ruta_imagen and carpeta_id and entrenable:
            try:
                muestra_visual = self.registrar_muestra_visual(
                    ruta_imagen, carpeta_id, "", texto, bbox_limpio,
                    accion="confirmar_entrenar", entrenable=True, fase=fase, tor=tor,
                    modelo_origen=modelo_origen, usuario=usuario,
                    metadatos={**(metadatos or {}), "poligono_lectura": poligono_limpio})
            except ValueError as exc:
                advertencia_visual = str(exc)
        return {
            "registrada": not duplicada, "duplicada": duplicada,
            "anotacion": {"id": anotacion_id, "carpeta_id": carpeta_id,
                           "carpeta_nombre": carpeta_nombre,
                           "imagen_nombre": imagen_nombre,
                           "bbox": bbox_limpio, "poligono": poligono_limpio,
                           "texto_correcto": texto, "fuente": fuente},
            "tipo": "region_manual",
            "muestra_visual": muestra_visual,
            "advertencia_visual": advertencia_visual,
        }

    def registrar_union_visual(self, ruta_imagen: str | Path, caso_id: str,
                               texto_correcto: str, bbox, unidades_originales=None,
                               poligono=None, fase: str | None = None, tor: str | None = None,
                               modelo_origen: str | None = None,
                               usuario: str = "dashboard",
                               metadatos: dict | None = None) -> dict:
        """Convierte una unión humana confirmada en evidencia visual entrenable.

        Si el revisor conserva una línea por cada bloque original, se generan
        muestras por línea para no entrenar EasyOCR con un párrafo enorme.
        Si la unión reconstruye una sola cadena a partir de varios fragmentos,
        se guarda el recorte unido completo. Nunca se inventa una partición.
        """
        texto = str(texto_correcto or "").strip()
        if not texto:
            return {"muestras": [], "nuevas": 0, "duplicadas": 0}
        unidades_validas = [u for u in (unidades_originales or [])
                            if isinstance(u, dict) and isinstance(u.get("bbox"), (list, tuple))
                            and len(u.get("bbox")) == 4]
        lineas = [line.strip() for line in texto.splitlines() if line.strip()]
        especificaciones = []
        if len(lineas) > 1 and len(lineas) == len(unidades_validas):
            for indice, (linea, unidad) in enumerate(zip(lineas, unidades_validas), 1):
                especificaciones.append({
                    "bbox": list(unidad["bbox"]),
                    "texto_ocr": str(unidad.get("texto") or ""),
                    "texto_correcto": linea,
                    "campo": "union_manual_linea",
                    "metadatos": {"union_modo": "lineas", "union_linea": indice,
                                   "union_lineas": len(lineas),
                                   "poligono_lectura": unidad.get("poligono_lectura")},
                })
        else:
            original = "\n".join(str(u.get("texto") or "") for u in unidades_validas).strip()
            especificaciones.append({
                "bbox": list(bbox), "texto_ocr": original,
                "texto_correcto": texto, "campo": "union_manual",
                "metadatos": {"union_modo": "zona", "union_lineas": len(lineas) or 1,
                               "union_bloques": len(unidades_validas),
                               "poligono_lectura": poligono},
            })
        resultados, nuevas, duplicadas, advertencias = [], 0, 0, []
        base_meta = dict(metadatos or {})
        base_meta.update({"origen": "union_manual", "supervision": "humana"})
        for spec in especificaciones:
            try:
                muestra = self.registrar_muestra_visual(
                    ruta_imagen, caso_id, spec["texto_ocr"], spec["texto_correcto"],
                    spec["bbox"], accion="confirmar_entrenar", entrenable=True,
                    campo=spec["campo"], fase=fase, tor=tor, modelo_origen=modelo_origen,
                    usuario=usuario, metadatos={**base_meta, **spec["metadatos"]})
                resultados.append(muestra)
                if muestra.get("duplicada"):
                    duplicadas += 1
                else:
                    nuevas += 1
            except ValueError as exc:
                advertencias.append(str(exc))
        return {"muestras": resultados, "nuevas": nuevas, "duplicadas": duplicadas,
                "advertencias": advertencias}

    def incorporar_uniones_guardadas(self, ruta_imagen: str | Path, caso_id: str, ocr: dict,
                                     fase: str | None = None, tor: str | None = None,
                                     modelo_origen: str | None = None,
                                     usuario: str = "dashboard",
                                     metadatos: dict | None = None) -> dict:
        """Migra las uniones activas antiguas de una imagen al dataset visual.

        Se ejecuta de forma oportunista al verificar una imagen. De este modo
        las uniones creadas antes de V14.12 se recuperan sin recorrer miles de
        fotografías al arrancar el dashboard. La firma de muestras evita
        duplicados si la imagen se verifica otra vez.
        """
        ruta = Path(ruta_imagen)
        if not ruta.is_file():
            return {"muestras": [], "nuevas": 0, "duplicadas": 0,
                    "advertencias": ["La imagen ya no está disponible."]}
        from utilidades.edicion_zonas import uniones_activas
        imagen_hash = hash_archivo(ruta)
        with self._conectar() as con:
            uniones = uniones_activas(con, imagen_hash, ocr or {})
            visuales = con.execute("""SELECT campo, metadatos_json FROM muestras_visuales
                WHERE imagen_hash=? AND campo IN ('union_manual','union_manual_linea')""",
                (imagen_hash,)).fetchall()
        representadas = set()
        for visual in visuales:
            try:
                meta = json.loads(visual["metadatos_json"] or "{}")
                if meta.get("edicion_zona_id") is not None:
                    representadas.add(int(meta["edicion_zona_id"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        total = {"muestras": [], "nuevas": 0, "duplicadas": 0, "advertencias": []}
        for union in uniones:
            if int(union.get("id") or 0) in representadas:
                total["duplicadas"] += 1
                continue
            resultado = self.registrar_union_visual(
                ruta, caso_id, union.get("texto") or "", union.get("bbox") or [],
                unidades_originales=None, poligono=union.get("poligono"), fase=fase, tor=tor,
                modelo_origen=modelo_origen, usuario=usuario,
                metadatos={**(metadatos or {}), "edicion_zona_id": union.get("id"),
                           "migrada_union_historica": True})
            total["muestras"].extend(resultado.get("muestras") or [])
            total["nuevas"] += int(resultado.get("nuevas") or 0)
            total["duplicadas"] += int(resultado.get("duplicadas") or 0)
            total["advertencias"].extend(resultado.get("advertencias") or [])
        total["uniones_detectadas"] = len(uniones)
        return total

    def registrar_imagen_sin_datos(self, ruta_imagen: str | Path, caso_id: str,
                                   motivo: str | None = None,
                                   usuario: str = "dashboard") -> dict:
        ruta = Path(ruta_imagen)
        if not ruta.is_file():
            raise ValueError("La imagen ya no está disponible.")
        imagen_hash = hash_archivo(ruta)
        with self._conectar() as con:
            con.execute("""INSERT INTO imagenes_sin_datos
                (imagen_hash, ruta_imagen, caso_id, motivo, usuario, creado_en)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(imagen_hash) DO UPDATE SET
                ruta_imagen=excluded.ruta_imagen, caso_id=excluded.caso_id,
                motivo=excluded.motivo, usuario=excluded.usuario,
                creado_en=excluded.creado_en""",
                (imagen_hash, str(ruta), str(caso_id), str(motivo or "").strip(),
                 str(usuario or "dashboard"), _ahora()))
        return {"imagen_hash": imagen_hash, "caso_id": str(caso_id),
                "motivo": str(motivo or "").strip(), "usuario": usuario,
                "estado_imagen": "revisada_sin_datos"}

    def imagen_sin_datos(self, ruta_imagen: str | Path) -> dict | None:
        ruta = Path(ruta_imagen)
        if not self.db.exists() or not ruta.is_file():
            return None
        imagen_hash = hash_archivo(ruta)
        with self._conectar() as con:
            fila = con.execute(
                "SELECT * FROM imagenes_sin_datos WHERE imagen_hash=?", (imagen_hash,)).fetchone()
        return dict(fila) if fila else None

    def listar_anotaciones(self, rutas_imagen: list[str | Path] | None = None,
                           carpeta_id: str | None = None) -> list[dict]:
        """Devuelve regiones humanas; filtra por hash para tolerar rutas reubicadas."""
        if not self.db.exists():
            return []
        hashes = []
        for ruta in rutas_imagen or []:
            try:
                if Path(ruta).is_file():
                    hashes.append(hash_archivo(ruta))
            except OSError:
                continue
        condiciones, parametros = [], []
        if hashes:
            condiciones.append(f"imagen_hash IN ({','.join('?' for _ in hashes)})")
            parametros.extend(hashes)
        elif rutas_imagen:
            return []
        if carpeta_id:
            condiciones.append("carpeta_id=?")
            parametros.append(carpeta_id)
        where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
        with self._conectar() as con:
            filas = con.execute(f"""
                SELECT * FROM anotaciones_regiones {where}
                ORDER BY carpeta_nombre, imagen_nombre, id
            """, parametros).fetchall()
        salida = []
        for fila in filas:
            item = dict(fila)
            item["bbox"] = json.loads(item.pop("bbox_json"))
            poligono_json = item.pop("poligono_json", None)
            item["poligono"] = json.loads(poligono_json) if poligono_json else None
            salida.append(item)
        return salida

    def listar_muestras_visuales(self, rutas_imagen: list[str | Path] | None = None) -> list[dict]:
        if not self.db.exists():
            return []
        hashes = set()
        for ruta in rutas_imagen or []:
            try:
                if Path(ruta).is_file():
                    hashes.add(hash_archivo(ruta))
            except OSError:
                continue
        with self._conectar() as con:
            filas = con.execute("SELECT * FROM muestras_visuales ORDER BY creado_en").fetchall()
        return [dict(f) for f in filas if not hashes or f["imagen_hash"] in hashes]

    def listar_correcciones_texto(self, rutas_imagen: list[str | Path]) -> list[dict]:
        """Correcciones y aceptaciones guardadas por imagen y caja exactas."""
        if not self.db.exists():
            return []
        hashes = []
        for ruta in rutas_imagen:
            try:
                if Path(ruta).is_file():
                    hashes.append(hash_archivo(ruta))
            except OSError:
                continue
        if not hashes:
            return []
        marcadores = ",".join("?" for _ in hashes)
        with self._conectar() as con:
            filas = con.execute(f"""
                SELECT * FROM correcciones_texto
                WHERE imagen_hash IN ({marcadores}) ORDER BY id
            """, hashes).fetchall()
            aceptaciones = con.execute(f"""
                SELECT 'aceptada-' || id AS id, imagen_hash, ruta_imagen,
                       texto_ocr, texto_correcto, bbox_json,
                       'aceptar_ocr' AS fuente, creado_en
                FROM muestras_visuales
                WHERE imagen_hash IN ({marcadores}) AND accion='aceptar'
                      AND confirmada=1 AND texto_correcto=texto_ocr
                ORDER BY creado_en, rowid
            """, hashes).fetchall()
        salida = []
        # En igualdad de fecha, una corrección explícita prevalece sobre
        # la aceptación de la lectura original. No se modifica el historial.
        registros = sorted([*aceptaciones, *filas], key=lambda f: f["creado_en"])
        for fila in registros:
            item = dict(fila)
            item["bbox"] = json.loads(item.pop("bbox_json"))
            salida.append(item)
        return salida

    def estado_revision(self, tipo: str, item_id: str,
                        estado_inicial: str = "por_revisar") -> dict:
        if tipo not in {"carpeta", "externa"}:
            raise ValueError("Tipo de revisión no válido.")
        estados_validos = {"por_revisar", "parcial", "casi_listo", "completada"}
        if estado_inicial not in estados_validos:
            estado_inicial = "por_revisar"
        with self._conectar() as con:
            fila = con.execute(
                "SELECT * FROM revisiones WHERE tipo=? AND item_id=?",
                (tipo, item_id)).fetchone()
        return ({"tipo": tipo, "item_id": item_id, "estado": estado_inicial,
                 "oculto": False, "actualizado_en": None} if fila is None else
                {**dict(fila), "oculto": bool(fila["oculto"])})

    def actualizar_revision(self, tipo: str, item_id: str,
                            estado: str | None = None,
                            oculto: bool | None = None,
                            estado_inicial: str = "por_revisar") -> dict:
        actual = self.estado_revision(tipo, item_id, estado_inicial)
        nuevo_estado = estado or actual["estado"]
        if nuevo_estado not in {"por_revisar", "parcial", "casi_listo", "completada"}:
            raise ValueError(
                "El estado debe ser por_revisar, parcial, casi_listo o completada.")
        nuevo_oculto = actual["oculto"] if oculto is None else bool(oculto)
        ahora = _ahora()
        with self._conectar() as con:
            con.execute("""
                INSERT INTO revisiones(tipo, item_id, estado, oculto, actualizado_en)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tipo, item_id) DO UPDATE SET
                    estado=excluded.estado, oculto=excluded.oculto,
                    actualizado_en=excluded.actualizado_en
            """, (tipo, item_id, nuevo_estado, int(nuevo_oculto), ahora))
        return {"tipo": tipo, "item_id": item_id, "estado": nuevo_estado,
                "oculto": nuevo_oculto, "actualizado_en": ahora}

    def listar_revisiones(self) -> dict[tuple[str, str], dict]:
        if not self.db.exists():
            return {}
        with self._conectar() as con:
            filas = con.execute("SELECT * FROM revisiones").fetchall()
        return {(fila["tipo"], fila["item_id"]):
                {**dict(fila), "oculto": bool(fila["oculto"])} for fila in filas}

    def atender_alerta(self, tipo: str, item_id: str, alerta_id: str) -> dict:
        if tipo not in {"carpeta", "externa"}:
            raise ValueError("Tipo de alerta no válido.")
        ahora = _ahora()
        with self._conectar() as con:
            con.execute("""
                INSERT INTO alertas_atendidas(tipo, item_id, alerta_id, atendida_en)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tipo, item_id, alerta_id) DO UPDATE SET
                    atendida_en=excluded.atendida_en
            """, (tipo, item_id, alerta_id, ahora))
        return {"tipo": tipo, "item_id": item_id, "alerta_id": alerta_id,
                "atendida": True, "atendida_en": ahora}

    def listar_alertas_atendidas(self) -> set[tuple[str, str, str]]:
        if not self.db.exists():
            return set()
        with self._conectar() as con:
            filas = con.execute(
                "SELECT tipo, item_id, alerta_id FROM alertas_atendidas").fetchall()
        return {(fila["tipo"], fila["item_id"], fila["alerta_id"]) for fila in filas}

    def _modelo_activo(self, con: sqlite3.Connection | None = None) -> sqlite3.Row | None:
        if not self.db.exists() and con is None:
            return None
        if con is not None:
            return con.execute("SELECT * FROM modelos WHERE estado='activo' ORDER BY id DESC LIMIT 1").fetchone()
        with self._conectar() as propia:
            return propia.execute(
                "SELECT * FROM modelos WHERE estado='activo' ORDER BY id DESC LIMIT 1").fetchone()

    def aplicar(self, texto: str) -> tuple[str, dict | None]:
        if not self.activado or not self.cfg.get("aplicar_modelo", True) or not self.db.exists():
            return texto, None
        with self._conectar() as con:
            modelo = self._modelo_activo(con)
            if modelo is None:
                return texto, None
            corregido, evidencia = predecir_correccion(
                texto, json.loads(modelo["modelo_json"]), self.cfg)
            if evidencia:
                evidencia["version_modelo"] = modelo["version"]
            return corregido, evidencia

    def marcar_no_texto(self, ruta_imagen, bbox, texto, usuario="dashboard", activo=True) -> dict:
        """Supervisión negativa localizada; nunca entrena con una transcripción vacía."""
        if not bbox or len(bbox) != 4 or min(bbox[2:]) <= 0 or min(bbox[:2]) < 0:
            raise ValueError("Selecciona un bloque OCR con coordenadas válidas.")
        firma = hash_archivo(ruta_imagen)
        caja = json.dumps(list(bbox))
        with self._conectar() as con:
            # Se conserva historial; la última acción de cada caja es la vigente.
            con.execute("INSERT INTO regiones_no_texto (imagen_hash,bbox_json,texto_ocr,activo,usuario,actualizado_en) VALUES (?,?,?,?,?,?)",
                        (firma, caja, texto, int(activo), usuario, _ahora()))
        return {"guardado": True, "activo": activo, "entrenamiento": False}

    def filtrar_no_texto(self, ocr: dict, ruta_imagen) -> dict:
        """Filtra una copia; el OCR bruto sigue disponible para deshacer."""
        from copy import deepcopy
        salida = deepcopy(ocr or {})
        # Algunos resultados parciales/compatibles con versiones anteriores
        # conservan las claves OCR con None. Para estas colecciones opcionales,
        # None equivale a "aún sin elementos". Se hace antes de aplicar
        # ediciones/correcciones para que la exportación Excel sea recuperable.
        for clave in ("tokens", "lineas_texto", "codigos_detectados", "recortes", "qrs"):
            if salida.get(clave) is None:
                salida[clave] = []
        if not ruta_imagen or not Path(ruta_imagen).is_file():
            from utilidades.correcciones_ocr import aplicar_correcciones
            return aplicar_correcciones(salida, [])
        from utilidades.edicion_zonas import aplicar
        with self._conectar() as con:
            salida = aplicar(con, hash_archivo(ruta_imagen), salida)
        ocr = deepcopy(salida)
        with self._conectar() as con:
            filas = con.execute("SELECT * FROM regiones_no_texto WHERE imagen_hash=? ORDER BY id DESC",
                                (hash_archivo(ruta_imagen),)).fetchall()
        vigentes = {}
        for fila in filas:
            vigentes.setdefault(fila["bbox_json"], dict(fila))
        descartes = [{**fila, "bbox": json.loads(fila["bbox_json"])}
                     for fila in vigentes.values() if fila["activo"]]
        salida["regiones_no_texto"] = descartes
        if not descartes:
            from utilidades.correcciones_ocr import aplicar_correcciones
            return aplicar_correcciones(salida, self.listar_correcciones_texto([ruta_imagen]))
        salida["_ocr_bruto"] = deepcopy(ocr)
        def excluida(unidad):
            b = unidad.get("bbox")
            if not b or len(b) != 4 or b[2] <= 0 or b[3] <= 0:
                return False
            for d in descartes:
                x,y,w,h = d["bbox"]
                inter = max(0, min(b[0]+b[2], x+w)-max(b[0],x)) * max(0,min(b[1]+b[3],y+h)-max(b[1],y))
                if inter / (b[2]*b[3]) >= .85:
                    return True
            return False
        for clave in ("tokens", "lineas_texto", "codigos_detectados"):
            salida[clave] = [u for u in (salida.get(clave) or []) if not excluida(u)]
        quitados = [u for u in (ocr.get("tokens") or []) if excluida(u)]
        for linea in (salida.get("lineas_texto") or []):
            b = linea.get("bbox")
            if not b:
                continue
            def dentro(t):
                q = t.get("bbox")
                return q and b[0] <= q[0]+q[2]/2 <= b[0]+b[2] and b[1] <= q[1]+q[3]/2 <= b[1]+b[3]
            if any(dentro(t) for t in quitados):
                linea["texto"] = " ".join(t.get("texto", "") for t in (salida.get("tokens") or []) if dentro(t))
        salida["lineas_texto"] = [l for l in salida["lineas_texto"] if str(l.get("texto", "")).strip()]
        textos_quitados = {normalizar_codigo(t.get("texto", "")) for t in quitados}
        textos_vivos = {normalizar_codigo(t.get("texto", "")) for t in (salida.get("tokens") or [])}
        salida["codigos_detectados"] = [c for c in salida["codigos_detectados"]
            if normalizar_codigo(c.get("normalizado") or c.get("texto", "")) not in textos_quitados-textos_vivos]
        salida["texto_completo"] = "\n".join(str(u.get("texto", "")) for u in
                                               (salida.get("lineas_texto") or salida.get("tokens") or []))
        from utilidades.correcciones_ocr import aplicar_correcciones
        return aplicar_correcciones(salida, self.listar_correcciones_texto([ruta_imagen]))

    def aplicar_memoria_imagen(self, tokens: list[dict],
                               ruta_imagen: str | Path | None) -> list[dict]:
        """Reutiliza verdad humana solo en el mismo archivo y caja confirmados.

        Esta memoria exacta no generaliza a fotos nuevas y, por tanto, no relaja
        los umbrales conservadores del modelo global.
        """
        if not ruta_imagen or not self.db.exists() or not Path(ruta_imagen).is_file():
            return [dict(token) for token in tokens]
        try:
            imagen_hash = hash_archivo(ruta_imagen)
        except OSError:
            return [dict(token) for token in tokens]
        with self._conectar() as con:
            filas = con.execute("""
                SELECT id, texto_ocr, texto_correcto, bbox_json, creado_en, 'literal' AS origen, 0 AS prioridad
                FROM correcciones_texto WHERE imagen_hash=?
                UNION ALL
                SELECT id, texto_ocr, texto_correcto, bbox_json, creado_en, 'codigo_legacy' AS origen, 1 AS prioridad
                FROM correcciones WHERE imagen_hash=?
                ORDER BY prioridad ASC, creado_en DESC, id DESC
            """, (imagen_hash, imagen_hash)).fetchall()
        confirmadas = [{**dict(fila), "bbox": json.loads(fila["bbox_json"])}
                       for fila in filas]
        salida = []
        for token in tokens:
            nuevo = dict(token)
            texto = str(token.get("texto_original") or token.get("texto") or "")
            bbox = list(token["bbox"]) if token.get("bbox") is not None else None
            coincidencia = next((fila for fila in confirmadas
                                 if normalizar_codigo(fila["texto_ocr"]) == normalizar_codigo(texto)
                                 and fila["bbox"] == bbox), None)
            if coincidencia and coincidencia["texto_correcto"] != token.get("texto"):
                nuevo["texto_original"] = texto
                nuevo["texto"] = coincidencia["texto_correcto"]
                nuevo["correccion_modelo"] = {
                    "tipo": "memoria_imagen_confirmada",
                    "correccion_id": coincidencia["id"],
                    "origen": coincidencia["origen"],
                    "alcance": "misma_imagen_y_bbox",
                }
            salida.append(nuevo)
        return salida

    def entrenar_y_promover(self) -> dict:
        with self._conectar() as con:
            correcciones = con.execute("SELECT * FROM correcciones ORDER BY id").fetchall()
            activo = self._modelo_activo(con)
            estado_activo = json.loads(activo["modelo_json"]) if activo else {}
            minimo_validacion = int(self.cfg.get("minimo_correcciones_validacion", 20))
            if len(correcciones) >= minimo_validacion:
                validacion = [f for f in correcciones
                              if int(hashlib.sha256(f["imagen_hash"].encode()).hexdigest()[:8], 16) % 5 == 0]
                ids_validacion = {f["id"] for f in validacion}
                entrenamiento = [f for f in correcciones if f["id"] not in ids_validacion]
                if not validacion or not entrenamiento:
                    entrenamiento, validacion = correcciones, correcciones
                    modo_evaluacion = "resustitucion_conservadora"
                else:
                    modo_evaluacion = "holdout_por_imagen"
            else:
                entrenamiento, validacion = correcciones, correcciones
                modo_evaluacion = "resustitucion_conservadora"
            candidato = _estado_desde_correcciones(entrenamiento)
            metricas_activas = _metricas(estado_activo, validacion, self.cfg)
            metricas_candidato = _metricas(candidato, validacion, self.cfg)
            activas = dict(metricas_activas["predicciones"])
            regresiones = sum(1 for ident, ok in metricas_candidato["predicciones"]
                              if activas.get(ident) and not ok)
            mejora = metricas_candidato["exactitud"] > metricas_activas["exactitud"]
            promover = (mejora and regresiones == 0 and
                         bool(self.cfg.get("promocion_automatica", True)))
            serializado = json.dumps(candidato, ensure_ascii=False, sort_keys=True)
            firma = hashlib.sha256(serializado.encode()).hexdigest()[:8]
            version = f"{datetime.now():%Y%m%d-%H%M%S}-{firma}-{uuid.uuid4().hex[:4]}"
            metricas_guardadas = {
                "candidato": {k: v for k, v in metricas_candidato.items() if k != "predicciones"},
                "activo_previo": {k: v for k, v in metricas_activas.items() if k != "predicciones"},
                "regresiones": regresiones,
                "modo_evaluacion": modo_evaluacion,
                "casos_entrenamiento": len(entrenamiento),
                "casos_validacion": len(validacion),
            }
            if promover:
                con.execute("UPDATE modelos SET estado='historico' WHERE estado='activo'")
            cursor = con.execute("""
                INSERT INTO modelos(version, padre_id, estado, modelo_json, metricas_json, creado_en)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (version, activo["id"] if activo else None,
                  "activo" if promover else "descartado", serializado,
                  json.dumps(metricas_guardadas), _ahora()))
        return {"version": version, "modelo_id": cursor.lastrowid,
                "promovido": promover, **metricas_guardadas}

    def rollback(self, version: str | None = None) -> dict:
        with self._conectar() as con:
            activo = self._modelo_activo(con)
            if version:
                destino = con.execute("SELECT * FROM modelos WHERE version=?", (version,)).fetchone()
            else:
                destino = con.execute(
                    "SELECT * FROM modelos WHERE estado='historico' ORDER BY id DESC LIMIT 1").fetchone()
            if destino is None:
                raise ValueError("No existe una versión histórica disponible para rollback.")
            con.execute("UPDATE modelos SET estado='historico' WHERE estado='activo'")
            con.execute("UPDATE modelos SET estado='activo' WHERE id=?", (destino["id"],))
        return {"anterior": activo["version"] if activo else None, "activo": destino["version"]}

    def estado(self) -> dict:
        almacenamiento = {"directorio": str(self.directorio), "base_datos": str(self.db),
                          "tipo": "SQLite local", "fotografias_copiadas": False}
        if not self.db.exists():
            return {"activado": self.activado, "ejecuciones": 0, "observaciones": 0,
                    "correcciones": 0, "correcciones_modelo": 0,
                    "memorias_imagen": 0,
                    "rotaciones_confirmadas": 0,
                    "estrategias_ocr": 0,
                    "anotaciones_regiones": 0,
                    "modelos": 0, "modelo_activo": None,
                    "muestras_visuales": 0, "muestras_entrenables": 0,
                    "modelo_visual_activo": None,
                    "modelos_visuales": 0, "ultimo_modelo_visual": None,
                    "almacenamiento": almacenamiento}
        with self._conectar() as con:
            conteos = {tabla: con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
                       for tabla in ("ejecuciones", "observaciones", "correcciones", "modelos")}
            correcciones_texto = con.execute(
                "SELECT COUNT(*) FROM correcciones_texto").fetchone()[0]
            anotaciones_regiones = con.execute(
                "SELECT COUNT(*) FROM anotaciones_regiones").fetchone()[0]
            memorias_imagen = con.execute("""
                SELECT COUNT(*) FROM (
                    SELECT imagen_hash, bbox_json, texto_correcto FROM correcciones_texto
                    UNION
                    SELECT imagen_hash, bbox_json, texto_correcto FROM correcciones
                )
            """).fetchone()[0]
            rotaciones_confirmadas = con.execute(
                "SELECT COUNT(*) FROM rotaciones_imagen WHERE grados != 0").fetchone()[0]
            estrategias_ocr = con.execute(
                "SELECT COUNT(*) FROM estrategias_ocr").fetchone()[0]
            muestras_visuales = con.execute(
                "SELECT COUNT(*) FROM muestras_visuales").fetchone()[0]
            muestras_entrenables = con.execute(
                "SELECT COUNT(*) FROM muestras_visuales WHERE entrenable=1").fetchone()[0]
            modelo_visual = con.execute(
                "SELECT * FROM modelos_visuales WHERE estado='activo' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            ultimo_visual = con.execute(
                "SELECT * FROM modelos_visuales ORDER BY id DESC LIMIT 1").fetchone()
            total_visuales = con.execute("SELECT COUNT(*) FROM modelos_visuales").fetchone()[0]
            activo = self._modelo_activo(con)
            conteos["correcciones_modelo"] = conteos["correcciones"]
            conteos["correcciones"] = correcciones_texto
            conteos["anotaciones_regiones"] = anotaciones_regiones
            conteos["memorias_imagen"] = memorias_imagen
            conteos["rotaciones_confirmadas"] = rotaciones_confirmadas
            conteos["estrategias_ocr"] = estrategias_ocr
            conteos["muestras_visuales"] = muestras_visuales
            conteos["muestras_entrenables"] = muestras_entrenables
            conteos["modelos_visuales"] = total_visuales
            return {"activado": self.activado, **conteos,
                    "almacenamiento": almacenamiento,
                    "modelo_visual_activo": (dict(modelo_visual) if modelo_visual else None),
                    "ultimo_modelo_visual": ({"version": ultimo_visual["version"],
                        "estado": ultimo_visual["estado"],
                        "metricas": json.loads(ultimo_visual["metricas_json"]),
                        "creado_en": ultimo_visual["creado_en"]} if ultimo_visual else None),
                    "modelo_activo": ({"version": activo["version"],
                                       "metricas": json.loads(activo["metricas_json"]),
                                       "creado_en": activo["creado_en"]} if activo else None)}

    def exportar_dataset(self, destino: str | Path) -> Path:
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with self._conectar() as con, open(destino, "w", encoding="utf-8") as f:
            for fila in con.execute("SELECT * FROM correcciones_texto ORDER BY id"):
                item = {"tipo": "correccion_texto", **dict(fila)}
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            for fila in con.execute("SELECT * FROM anotaciones_regiones ORDER BY id"):
                item = {"tipo": "region_manual", **dict(fila)}
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            for fila in con.execute("SELECT * FROM estrategias_ocr ORDER BY id"):
                item = {"tipo": "estrategia_ocr", **dict(fila)}
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return destino


def aplicar_modelo_tokens(tokens: list[dict], config: dict | None = None,
                          ruta_imagen: str | Path | None = None) -> list[dict]:
    """Copia tokens y añade trazabilidad solo cuando una corrección se aplica."""
    gestor = GestorAprendizaje(config)
    tokens = gestor.aplicar_memoria_imagen(tokens, ruta_imagen)
    salida = []
    for token in tokens:
        nuevo = dict(token)
        if nuevo.get("correccion_modelo"):
            salida.append(nuevo)
            continue
        corregido, evidencia = gestor.aplicar(token["texto"])
        if evidencia and corregido != token["texto"]:
            nuevo["texto_original"] = token["texto"]
            nuevo["texto"] = corregido
            nuevo["correccion_modelo"] = evidencia
        salida.append(nuevo)
    return salida


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gestionar aprendizaje incremental del OCR.")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("estado")
    corregir = sub.add_parser("corregir")
    corregir.add_argument("imagen")
    corregir.add_argument("texto_ocr")
    corregir.add_argument("texto_correcto")
    sub.add_parser("entrenar")
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--version")
    exportar = sub.add_parser("exportar")
    exportar.add_argument("destino")
    args = parser.parse_args()
    gestor = GestorAprendizaje()
    if args.comando == "estado":
        resultado = gestor.estado()
    elif args.comando == "corregir":
        resultado = gestor.registrar_correccion(
            args.texto_ocr, args.texto_correcto, ruta_imagen=args.imagen)
    elif args.comando == "entrenar":
        resultado = gestor.entrenar_y_promover()
    elif args.comando == "rollback":
        resultado = gestor.rollback(args.version)
    else:
        resultado = {"dataset": str(gestor.exportar_dataset(args.destino))}
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
