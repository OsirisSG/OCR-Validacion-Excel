"""Agrupa exportaciones del dashboard. Una instancia por servidor local."""
import sqlite3
import threading
from contextlib import closing


class ColaExcel:
    def __init__(self, ruta, generar, demora=1.5, reintento=10):
        self.ruta = ruta
        self.generar = generar
        self.demora = demora
        self.reintento = reintento
        self.parar = threading.Event()
        self.despertar = threading.Event()
        self.lock = threading.Lock()
        self.hilo = None
        self.activo = False
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conectar()) as con, con:
            con.execute('''CREATE TABLE IF NOT EXISTS cola (
                id INTEGER PRIMARY KEY CHECK(id=1), solicitada INTEGER NOT NULL,
                completada INTEGER NOT NULL, error TEXT, archivo TEXT)''')
            con.execute('INSERT OR IGNORE INTO cola VALUES (1,0,0,NULL,NULL)')

    def _conectar(self):
        con = sqlite3.connect(self.ruta, timeout=15)
        con.row_factory = sqlite3.Row
        return con

    def solicitar(self):
        with closing(self._conectar()) as con, con:
            con.execute('UPDATE cola SET solicitada=solicitada+1 WHERE id=1')
            revision = con.execute('SELECT solicitada FROM cola WHERE id=1').fetchone()[0]
        self.despertar.set()
        return revision

    def estado(self):
        with closing(self._conectar()) as con:
            fila = dict(con.execute('SELECT * FROM cola WHERE id=1').fetchone())
        pendientes = fila['solicitada'] - fila['completada']
        estado = ('actualizando' if self.activo else
                  'error' if pendientes and fila['error'] else
                  'pendiente' if pendientes else 'actualizado')
        # Conserva `estado` para compatibilidad y expone el contrato de UI
        # pedido por el usuario: pendiente / guardando / guardado / error.
        estado_persistencia = {
            'actualizando': 'guardando', 'pendiente': 'pendiente',
            'actualizado': 'guardado', 'error': 'error',
        }[estado]
        return {**fila, 'pendientes': pendientes, 'estado': estado,
                'estado_persistencia': estado_persistencia}

    def procesar(self):
        # Nunca confirmar revisiones que llegaron durante la exportación.
        with self.lock:
            estado = self.estado()
            if not estado['pendientes']:
                return True
            revision = estado['solicitada']
            self.activo = True
            try:
                archivo = str(self.generar())
                with closing(self._conectar()) as con, con:
                    con.execute('UPDATE cola SET completada=?, error=NULL, archivo=? WHERE id=1',
                                (revision, archivo))
                return True
            except Exception as exc:
                with closing(self._conectar()) as con, con:
                    con.execute('UPDATE cola SET error=? WHERE id=1', (str(exc),))
                return False
            finally:
                self.activo = False

    def _ejecutar(self):
        while not self.parar.is_set():
            self.despertar.wait(1)
            self.despertar.clear()
            try:
                if not self.estado()['pendientes']:
                    continue
                if self.parar.wait(self.demora):
                    break
                if not self.procesar():
                    if self.parar.wait(self.reintento):
                        break
                if self.estado()['pendientes']:
                    self.despertar.set()
            except Exception:
                # Una indisponibilidad temporal de SQLite no debe matar el hilo.
                if self.parar.wait(self.reintento):
                    break

    def iniciar(self):
        if self.hilo and self.hilo.is_alive():
            return
        self.parar.clear()
        self.hilo = threading.Thread(target=self._ejecutar, daemon=True, name='cola-excel')
        self.hilo.start()
        self.despertar.set()

    def detener(self):
        self.parar.set()
        self.despertar.set()
        if self.hilo:
            self.hilo.join(timeout=2)
