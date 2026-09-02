"""Aprendizaje incremental seguro para corregir resultados OCR.

El sistema registra observaciones automáticamente, pero solo aprende de texto
confirmado por una persona. Cada corrección genera un modelo candidato; este se
promueve únicamente cuando mejora la exactitud sobre las correcciones conocidas
sin introducir regresiones. SQLite mantiene historial, versiones y rollback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import uuid
from collections import Counter, defaultdict
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


def hash_archivo(ruta: str | Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def rotar_bbox(bbox, grados: int, ancho_imagen: int,
               alto_imagen: int) -> list[int] | None:
    """Rota una caja x/y/ancho/alto en el mismo sentido horario que la imagen."""
    if bbox is None:
        return None
    x, y, ancho, alto = (int(round(float(v))) for v in bbox)
    grados = int(grados) % 360
    if grados == 0:
        return [x, y, ancho, alto]
    if grados == 90:
        return [alto_imagen - y - alto, x, alto, ancho]
    if grados == 180:
        return [ancho_imagen - x - ancho, alto_imagen - y - alto, ancho, alto]
    if grados == 270:
        return [y, ancho_imagen - x - ancho, alto, ancho]
    raise ValueError("La rotación de coordenadas debe ser múltiplo de 90°.")


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

    @property
    def activado(self) -> bool:
        return bool(self.cfg.get("activar", True))

    def _conectar(self) -> sqlite3.Connection:
        self.directorio.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db, timeout=20)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS ejecuciones (
                id TEXT PRIMARY KEY, creado_en TEXT NOT NULL, raiz TEXT,
                imagenes INTEGER NOT NULL DEFAULT 0, tokens INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS observaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ejecucion_id TEXT NOT NULL,
                imagen_hash TEXT NOT NULL, ruta_imagen TEXT, texto_ocr TEXT NOT NULL,
                confianza REAL, bbox_json TEXT, motor TEXT, creado_en TEXT NOT NULL,
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
                grados INTEGER NOT NULL DEFAULT 0,
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
            CREATE INDEX IF NOT EXISTS idx_observaciones_hash ON observaciones(imagen_hash);
            CREATE INDEX IF NOT EXISTS idx_anotaciones_hash ON anotaciones_regiones(imagen_hash);
            CREATE INDEX IF NOT EXISTS idx_anotaciones_carpeta ON anotaciones_regiones(carpeta_id);
            CREATE INDEX IF NOT EXISTS idx_revisiones_estado ON revisiones(estado, oculto);
            CREATE INDEX IF NOT EXISTS idx_modelos_estado ON modelos(estado);
        """)
        return con

    def rotacion_preferida(self, ruta_imagen: str | Path | None) -> int:
        """Rotación humana, en sentido horario, para la próxima lectura OCR."""
        if not ruta_imagen or not self.db.exists() or not Path(ruta_imagen).is_file():
            return 0
        try:
            imagen_hash = hash_archivo(ruta_imagen)
        except OSError:
            return 0
        with self._conectar() as con:
            fila = con.execute(
                "SELECT grados FROM rotaciones_imagen WHERE imagen_hash=?", (imagen_hash,)).fetchone()
        return int(fila["grados"]) % 360 if fila else 0

    def actualizar_rotacion(self, ruta_imagen: str | Path, grados: int,
                            fuente: str = "dashboard") -> dict:
        if not Path(ruta_imagen).is_file():
            raise ValueError("La imagen ya no está disponible.")
        grados = int(grados) % 360
        if grados not in {0, 90, 180, 270}:
            raise ValueError("La rotación debe ser 0°, 90°, 180° o 270°.")
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

    def rotar_evidencias_imagen(self, ruta_imagen: str | Path, grados: int,
                                dimensiones: tuple[int, int]) -> dict:
        """Mantiene alineadas correcciones y regiones al girar su vista OCR."""
        grados = int(grados) % 360
        if grados == 0 or not self.db.exists():
            return {"evidencias_rotadas": 0}
        ancho, alto = (int(dimensiones[0]), int(dimensiones[1]))
        imagen_hash = hash_archivo(ruta_imagen)
        actualizadas = 0
        with self._conectar() as con:
            for tabla in ("correcciones_texto", "correcciones", "anotaciones_regiones"):
                filas = con.execute(
                    f"SELECT id, bbox_json FROM {tabla} WHERE imagen_hash=?",
                    (imagen_hash,)).fetchall()
                for fila in filas:
                    bbox = json.loads(fila["bbox_json"])
                    if bbox is None:
                        continue
                    girada = rotar_bbox(bbox, grados, ancho, alto)
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
            unidades = list(resultado.get("tokens", [])) + list(
                resultado.get("lineas_texto", []))
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
                             bbox=None, fuente: str = "humana") -> dict:
        crudo_original = str(texto_ocr).strip()
        correcto_original = str(texto_correcto).strip()
        crudo, correcto = normalizar_codigo(crudo_original), normalizar_codigo(correcto_original)
        if not crudo or not correcto:
            raise ValueError("La lectura OCR y la corrección deben contener texto válido.")
        if crudo_original == correcto_original:
            raise ValueError("La corrección es idéntica a la lectura OCR.")
        if imagen_hash is None:
            if not ruta_imagen or not Path(ruta_imagen).is_file():
                raise ValueError("Se requiere una imagen existente o su hash.")
            imagen_hash = hash_archivo(ruta_imagen)
        duplicada_texto = False
        duplicada_modelo = False
        with self._conectar() as con:
            try:
                con.execute("""
                    INSERT INTO correcciones_texto
                    (imagen_hash, ruta_imagen, texto_ocr, texto_correcto, bbox_json, fuente, creado_en)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (imagen_hash, ruta_imagen, crudo_original, correcto_original,
                      json.dumps(bbox), fuente, _ahora()))
            except sqlite3.IntegrityError:
                duplicada_texto = True

            # Cambios exclusivamente de espacios/saltos se conservan como
            # verdad de layout, pero no contaminan el modelo de códigos.
            if crudo != correcto:
                try:
                    con.execute("""
                        INSERT INTO correcciones
                        (imagen_hash, ruta_imagen, texto_ocr, texto_correcto, bbox_json, fuente, creado_en)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (imagen_hash, ruta_imagen, crudo, correcto,
                          json.dumps(bbox), fuente, _ahora()))
                except sqlite3.IntegrityError:
                    duplicada_modelo = True
            else:
                duplicada_modelo = True
        entrenamiento = self.entrenar_y_promover() if not duplicada_modelo else None
        return {
            "registrada": not duplicada_texto,
            "duplicada": duplicada_texto,
            "texto_ocr": crudo_original,
            "texto_correcto": correcto_original,
            "tipo": "layout" if crudo == correcto else "modelo_codigo",
            "entrenamiento": entrenamiento,
        }

    def registrar_region(self, texto_correcto: str, bbox,
                         ruta_imagen: str | None = None,
                         imagen_hash: str | None = None,
                         carpeta_id: str | None = None,
                         carpeta_nombre: str | None = None,
                         imagen_nombre: str | None = None,
                         fuente: str = "dashboard_region") -> dict:
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
        duplicada = False
        with self._conectar() as con:
            try:
                cursor = con.execute("""
                    INSERT INTO anotaciones_regiones
                    (carpeta_id, carpeta_nombre, imagen_hash, ruta_imagen,
                     imagen_nombre, bbox_json, texto_correcto, fuente, creado_en)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (carpeta_id, carpeta_nombre, imagen_hash, ruta_imagen,
                      imagen_nombre or (Path(ruta_imagen).name if ruta_imagen else None),
                      json.dumps(bbox_limpio), texto, fuente, _ahora()))
                anotacion_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                duplicada = True
                fila = con.execute("""
                    SELECT id FROM anotaciones_regiones
                    WHERE imagen_hash=? AND bbox_json=? AND texto_correcto=?
                """, (imagen_hash, json.dumps(bbox_limpio), texto)).fetchone()
                anotacion_id = fila["id"] if fila else None
        return {
            "registrada": not duplicada, "duplicada": duplicada,
            "anotacion": {"id": anotacion_id, "carpeta_id": carpeta_id,
                           "carpeta_nombre": carpeta_nombre,
                           "imagen_nombre": imagen_nombre,
                           "bbox": bbox_limpio, "texto_correcto": texto,
                           "fuente": fuente},
            "tipo": "region_manual",
        }

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
            salida.append(item)
        return salida

    def listar_correcciones_texto(self, rutas_imagen: list[str | Path]) -> list[dict]:
        """Correcciones humanas por hash; conserva duplicados espaciales por bbox."""
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
        salida = []
        for fila in filas:
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
                SELECT id, texto_ocr, texto_correcto, bbox_json, 'literal' AS origen, 0 AS prioridad
                FROM correcciones_texto WHERE imagen_hash=?
                UNION ALL
                SELECT id, texto_ocr, texto_correcto, bbox_json, 'codigo_legacy' AS origen, 1 AS prioridad
                FROM correcciones WHERE imagen_hash=?
                ORDER BY prioridad ASC, id DESC
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
                    "anotaciones_regiones": 0,
                    "modelos": 0, "modelo_activo": None,
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
            activo = self._modelo_activo(con)
            conteos["correcciones_modelo"] = conteos["correcciones"]
            conteos["correcciones"] = correcciones_texto
            conteos["anotaciones_regiones"] = anotaciones_regiones
            conteos["memorias_imagen"] = memorias_imagen
            conteos["rotaciones_confirmadas"] = rotaciones_confirmadas
            return {"activado": self.activado, **conteos,
                    "almacenamiento": almacenamiento,
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
