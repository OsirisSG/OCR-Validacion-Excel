"""Cola durable e idempotente para exportaciones Excel del dashboard (V14.10)."""
from __future__ import annotations

import sqlite3
import threading
import time
import traceback
import uuid
from contextlib import closing
from datetime import datetime


class ColaExcel:
    """Agrupa correcciones rápidas sin perder durabilidad.

    ``demora`` representa el tiempo de silencio deseado antes de regenerar el
    Excel. Si siguen llegando correcciones, se reprograma de forma deslizante,
    pero ``latencia_maxima`` impide que el archivo espere indefinidamente.
    """

    def __init__(self, ruta, generar, demora=1.5, reintento=10, max_pendientes=10000,
                 latencia_maxima=3.0):
        self.ruta = ruta
        self.generar = generar
        self.demora = max(0.05, float(demora))
        self.reintento = float(reintento)
        self.max_pendientes = max(1, int(max_pendientes))
        self.latencia_maxima = max(self.demora, float(latencia_maxima))
        self.parar = threading.Event()
        self.despertar = threading.Event()
        self.lock = threading.Lock()
        self._solicitud_lock = threading.Lock()
        self.hilo = None
        self.activo = False
        self._ultima_solicitud_mono: float | None = None
        self._primera_pendiente_mono: float | None = None
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar()

    def _conectar(self):
        con = sqlite3.connect(self.ruta, timeout=15)
        con.row_factory = sqlite3.Row
        return con

    def _inicializar(self):
        with closing(self._conectar()) as con, con:
            con.execute('''CREATE TABLE IF NOT EXISTS cola (
                id INTEGER PRIMARY KEY CHECK(id=1), solicitada INTEGER NOT NULL,
                completada INTEGER NOT NULL, error TEXT, archivo TEXT)''')
            con.execute('''INSERT OR IGNORE INTO cola
                (id,solicitada,completada,error,archivo) VALUES (1,0,0,NULL,NULL)''')
            columnas = {r[1] for r in con.execute('PRAGMA table_info(cola)').fetchall()}
            extras = {
                'error_tipo': 'TEXT', 'traceback': 'TEXT',
                'reintentos': 'INTEGER NOT NULL DEFAULT 0',
                'actualizado_en': 'TEXT', 'ultima_actualizacion_id': 'TEXT',
            }
            for nombre, tipo in extras.items():
                if nombre not in columnas:
                    con.execute(f'ALTER TABLE cola ADD COLUMN {nombre} {tipo}')
            con.execute('''CREATE TABLE IF NOT EXISTS actualizaciones (
                id TEXT PRIMARY KEY, revision INTEGER NOT NULL UNIQUE,
                estado TEXT NOT NULL, creado_en TEXT NOT NULL, guardado_en TEXT,
                error TEXT, error_tipo TEXT, intentos INTEGER NOT NULL DEFAULT 0)''')

    @staticmethod
    def _ahora():
        return datetime.now().isoformat(timespec='milliseconds')

    @staticmethod
    def _clasificar_error(exc: Exception) -> str:
        if isinstance(exc, PermissionError):
            texto = str(exc).lower()
            return ('excel_bloqueado' if any(x in texto for x in ('excel', '.xlsx', 'used by another'))
                    else 'permisos')
        if isinstance(exc, (TypeError, ValueError, KeyError)):
            return 'datos_invalidos'
        if isinstance(exc, sqlite3.Error):
            return 'almacenamiento'
        if isinstance(exc, (OSError, IOError)):
            return 'almacenamiento'
        return 'exportacion'

    def solicitar(self, actualizacion_id=None):
        """Encola una actualización; repetir el mismo ID es idempotente."""
        uid = str(actualizacion_id or uuid.uuid4().hex)
        ahora_mono = time.monotonic()
        # Una sola instancia atiende las correcciones del dashboard. El lock hace
        # atómica la asignación de revisión y SQLite conserva durabilidad.
        with self._solicitud_lock:
            with closing(self._conectar()) as con, con:
                existente = con.execute(
                    'SELECT revision FROM actualizaciones WHERE id=?', (uid,)).fetchone()
                if existente:
                    revision = int(existente[0])
                else:
                    fila = con.execute(
                        'SELECT solicitada, completada FROM cola WHERE id=1').fetchone()
                    pendientes = int(fila['solicitada']) - int(fila['completada'])
                    if pendientes >= self.max_pendientes:
                        raise RuntimeError('COLA_SATURADA: demasiadas actualizaciones Excel pendientes')
                    revision = int(fila['solicitada']) + 1
                    con.execute(
                        'INSERT INTO actualizaciones (id,revision,estado,creado_en) VALUES (?,?,?,?)',
                        (uid, revision, 'pendiente', self._ahora()))
                    con.execute(
                        '''UPDATE cola SET solicitada=?, ultima_actualizacion_id=?,
                           actualizado_en=? WHERE id=1''',
                        (revision, uid, self._ahora()))
                    if pendientes <= 0 or self._primera_pendiente_mono is None:
                        self._primera_pendiente_mono = ahora_mono
                self._ultima_solicitud_mono = ahora_mono
        self.despertar.set()
        return revision

    def estado(self):
        with closing(self._conectar()) as con:
            fila = dict(con.execute('SELECT * FROM cola WHERE id=1').fetchone())
        pendientes = max(0, fila['solicitada'] - fila['completada'])
        estado = ('actualizando' if self.activo else
                  'error' if pendientes and fila.get('error') else
                  'pendiente' if pendientes else 'actualizado')
        estado_persistencia = {
            'actualizando': 'guardando', 'pendiente': 'pendiente',
            'actualizado': 'guardado', 'error': 'error',
        }[estado]
        traza = str(fila.get('traceback') or '')
        linea_error = ''
        if traza:
            lineas = [ln.strip() for ln in traza.splitlines() if ln.strip()]
            linea_error = ' | '.join(lineas[-2:])
        return {**fila, 'pendientes': pendientes, 'estado': estado,
                'estado_persistencia': estado_persistencia,
                'cola_saturada': pendientes >= self.max_pendientes,
                'detalle_error': linea_error,
                'demora_coalescencia_segundos': self.demora,
                'latencia_maxima_segundos': self.latencia_maxima}

    def _reiniciar_ventana_si_vacia(self):
        if self.estado()['pendientes']:
            return
        with self._solicitud_lock:
            self._primera_pendiente_mono = None
            self._ultima_solicitud_mono = None

    def procesar(self):
        """Exporta una instantánea y confirma únicamente las revisiones incluidas."""
        with self.lock:
            estado = self.estado()
            if not estado['pendientes']:
                self._reiniciar_ventana_si_vacia()
                return True
            revision = int(estado['solicitada'])
            self.activo = True
            try:
                with closing(self._conectar()) as con, con:
                    con.execute(
                        "UPDATE actualizaciones SET estado='guardando', intentos=intentos+1 "
                        "WHERE revision<=? AND estado!='guardado'", (revision,))
                generado = self.generar()
                if generado is None:
                    raise TypeError('El exportador Excel devolvió None; se esperaba una ruta de archivo')
                archivo = str(generado)
                ahora = self._ahora()
                with closing(self._conectar()) as con, con:
                    con.execute(
                        '''UPDATE cola SET completada=?, error=NULL, error_tipo=NULL,
                           traceback=NULL, reintentos=0, archivo=?, actualizado_en=? WHERE id=1''',
                        (revision, archivo, ahora))
                    con.execute(
                        "UPDATE actualizaciones SET estado='guardado', guardado_en=?, "
                        "error=NULL, error_tipo=NULL WHERE revision<=?",
                        (ahora, revision))
                return True
            except Exception as exc:
                tipo = self._clasificar_error(exc)
                traza = traceback.format_exc()
                error = f'{type(exc).__name__}: {exc}'
                with closing(self._conectar()) as con, con:
                    con.execute(
                        '''UPDATE cola SET error=?, error_tipo=?, traceback=?,
                           reintentos=COALESCE(reintentos,0)+1, actualizado_en=? WHERE id=1''',
                        (error, tipo, traza, self._ahora()))
                    con.execute(
                        "UPDATE actualizaciones SET estado='error', error=?, error_tipo=? "
                        "WHERE revision<=? AND estado!='guardado'",
                        (error, tipo, revision))
                return False
            finally:
                self.activo = False
                self._reiniciar_ventana_si_vacia()

    def _esperar_coalescencia(self) -> bool:
        """Espera hasta tener silencio suficiente o alcanzar la latencia máxima."""
        while not self.parar.is_set():
            ahora = time.monotonic()
            with self._solicitud_lock:
                ultima = self._ultima_solicitud_mono
                primera = self._primera_pendiente_mono
                if ultima is None:
                    ultima = ahora
                    self._ultima_solicitud_mono = ultima
                if primera is None:
                    primera = ahora
                    self._primera_pendiente_mono = primera
            silencio = ahora - ultima
            acumulado = ahora - primera
            if silencio >= self.demora or acumulado >= self.latencia_maxima:
                return True
            restante_silencio = max(0.0, self.demora - silencio)
            restante_maximo = max(0.0, self.latencia_maxima - acumulado)
            espera = max(0.01, min(restante_silencio, restante_maximo, 0.25))
            if self.parar.wait(espera):
                return False
        return False

    def _ejecutar(self):
        while not self.parar.is_set():
            self.despertar.wait(1)
            self.despertar.clear()
            try:
                estado = self.estado()
                if not estado['pendientes']:
                    self._reiniciar_ventana_si_vacia()
                    continue
                if not self._esperar_coalescencia():
                    break
                if not self.procesar():
                    reintentos = int(self.estado().get('reintentos') or 0)
                    espera = min(120.0, self.reintento * (2 ** min(max(reintentos - 1, 0), 4)))
                    if self.parar.wait(espera):
                        break
                if self.estado()['pendientes']:
                    # Si llegaron cambios mientras se generaba el Excel, abre una
                    # nueva ventana corta para agruparlos en una sola exportación.
                    with self._solicitud_lock:
                        if self._primera_pendiente_mono is None:
                            self._primera_pendiente_mono = time.monotonic()
                        if self._ultima_solicitud_mono is None:
                            self._ultima_solicitud_mono = self._primera_pendiente_mono
                    self.despertar.set()
            except Exception:
                if self.parar.wait(self.reintento):
                    break

    def iniciar(self):
        if self.hilo and self.hilo.is_alive():
            return
        self.parar.clear()
        if self.estado()['pendientes']:
            ahora = time.monotonic()
            with self._solicitud_lock:
                self._primera_pendiente_mono = ahora
                self._ultima_solicitud_mono = ahora
        self.hilo = threading.Thread(target=self._ejecutar, daemon=True, name='cola-excel')
        self.hilo.start()
        self.despertar.set()

    def detener(self):
        self.parar.set()
        self.despertar.set()
        if self.hilo:
            self.hilo.join(timeout=2)
