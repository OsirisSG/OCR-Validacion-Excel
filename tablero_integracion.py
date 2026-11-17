"""P43 · Lectura P42 del TABLERO dentro de la corrida normal.

Por qué existe
--------------
Medido en FE.z (V16.0.52): la hoja Trazabilidad tiene 513 filas y NINGUNA `dashboard_*`. La
causa está en el código, no en las fotos: `validacion.validar_lote_empresarial()` sólo junta
candidatos de `extraer_candidatos_texto` (OCR genérico), `candidatos_desde_barra` y
`evidencias_desde_qr`; ningún módulo del tablero (`evidencia_tablero`, `buscar_mas`,
`utilidades.tablero_campos`) se importa desde `pipeline.py`, `validacion.py`,
`flujo_empresarial.py`, `generar_excel.py` ni `reporte_bmg.py`. La lectura P42 sólo existía
como herramientas sueltas (`leer_tablero_lote.py` → JSON) que nadie devolvía a la corrida.

Qué hace
--------
Para CADA caso del flujo normal (identidad = `case_key`: proyecto + etapa + carpeta; nunca el
número solo) y con las fotos que ese caso ya tiene (`caso["fotos"]`, rutas NACH/VOR):

1. primera pasada P42: `tablero_campos.pista_de_tablero` + `evidencia_tablero.elegir_candidatas`
   (mismos cupos) + `tablero_campos.leer_foto_de_tablero`;
2. cierre P42 por caso con `evidencia_tablero.cerrar_registro` (filtrar_fechas, `_solo_clase`,
   regla de la foto única del sticker, `consensuar_completo`, `motivos_de_duda`) — en memoria,
   SIN fundir con ningún JSON anterior;
3. si `dashboard_date` no queda cerrada sin duda: segunda pasada `buscar_mas.fechas_de_una_imagen`
   sobre las fotos que no dieron lectura, hasta dos lecturas iguales de clase `tablero`;
4. convierte el cierre en candidatos con el contrato de `extraer_candidatos_texto` para que
   `consolidar_caso` decida con sus reglas de siempre (forma, NUNCA_AUTOMATICO, autoridad manual).
   Sólo los valores cerrados SIN duda entran como candidatos publicables; el resto entra con
   `requiere_confirmacion_manual=True` (visible en trazabilidad y dudas, nunca publicado);
5. cobertura por ruta relativa completa: presentes, examinadas, descartadas con motivo,
   con error y pendientes. Un campo sólo puede quedar «sin dato tras búsqueda» si TODAS las
   fotos presentes se examinaron sin error para ese campo.

Qué NO hace
-----------
- No cambia ninguna regla de lectura, clase o consenso P42 (sólo las llama).
- No lee el Book corregido ni ningún JSON de evidencia anterior.
- No toca vídeo.
- No publica dudas como hechos ni rellena celdas: eso sigue siendo `consolidar_caso` +
  `reporte_bmg` (que no sobrescribe celdas ocupadas).
"""
from __future__ import annotations

import gc
import hashlib
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

CAMPOS = ("dashboard_part_number", "dashboard_serial_number", "dashboard_date",
          "dashboard_engineering_level")
FUENTE = "tablero_p42"
VERSION = "p47-tablero-4"
# Mismos formatos que lee la herramienta P42 (`evidencia_tablero.EXTENSIONES`).
EXTENSIONES = (".jpg", ".jpeg", ".png")
LADO_PISTA = 1000          # `evidencia_tablero.lista_de_candidatas` usa 1000 px
LADO_LECTURA = 1280        # `evidencia_tablero.leer_tramo` usa 1280 px
AVISO_SEGUNDA = 2          # `buscar_mas.AVISO`: lecturas iguales de clase tablero para parar

# Estados de una foto (cobertura). Sólo las «examinadas» cuentan para cerrar «sin dato».
EXAMINADA_PRIMERA = {"leida_con_lectura", "leida_sin_lectura"}
EXAMINADA_SEGUNDA = {"segunda_con_fecha", "segunda_sin_fecha"}
DESCARTADA = {"formato_no_soportado"}
ERROR = {"no_legible", "error_lector", "error_ocr"}


class _Interrumpido(BaseException):
    """Envuelve la excepción del `control()` (pausa/cancelación) para que no se trague."""

    def __init__(self, original: BaseException):
        super().__init__(str(original))
        self.original = original


@dataclass
class OpcionesTablero:
    activar: bool = False
    catalogo: tuple[str, ...] = ()
    cupos: dict | None = None
    segunda_pasada: bool = True
    maximo_extra_serie: int = 12
    serie_control: str = "preguntar"
    maximo_fotos_segunda: int = 400
    presupuesto_segunda_s: float = 900.0
    guardar_recortes: bool = True
    cache: bool = True
    ruta_cache: str = ""

    @classmethod
    def desde_config(cls, config: dict | None) -> "OpcionesTablero":
        cfg = ((config or {}).get("empresarial") or {}).get("tablero_p42") or {}
        catalogo = cfg.get("catalogo") or ()
        if isinstance(catalogo, str):
            catalogo = [c.strip() for c in catalogo.split(",") if c.strip()]
        return cls(activar=bool(cfg.get("activar", False)),
                   catalogo=tuple(str(c) for c in catalogo),
                   cupos=dict(cfg["cupos"]) if isinstance(cfg.get("cupos"), dict) else None,
                   segunda_pasada=bool(cfg.get("segunda_pasada", True)),
                   maximo_extra_serie=int(cfg.get("maximo_extra_serie", 12)),
                   serie_control=str(cfg.get("serie_control", "preguntar")),
                   maximo_fotos_segunda=int(cfg.get("maximo_fotos_segunda", 400)),
                   presupuesto_segunda_s=float(cfg.get("presupuesto_segunda_s", 900.0)),
                   guardar_recortes=bool(cfg.get("guardar_recortes", True)),
                   cache=bool(cfg.get("cache", True)),
                   ruta_cache=str(cfg.get("ruta_cache") or ""))


class MotorVigilado:
    """Envuelve el motor OCR y CUENTA sus errores.

    `tablero_campos._textos` atrapa cualquier excepción del motor y devuelve `[]`: un OCR roto
    parecía «foto sin texto». Aquí se cuenta cada fallo y se vuelve a lanzar, para que
    `_textos` siga comportándose igual pero la cobertura sepa que la foto NO se examinó bien.
    """

    def __init__(self, motor):
        self._motor = motor
        self.errores = 0
        self.ultimo_error = ""

    def __call__(self, *args, **kwargs):
        try:
            return self._motor(*args, **kwargs)
        except Exception as exc:                          # noqa: BLE001
            self.errores += 1
            self.ultimo_error = f"{type(exc).__name__}: {exc}"[:300]
            raise


class LectorP42:
    """Adaptador de las funciones P42 reales. Las pruebas lo sustituyen por uno sintético."""

    def __init__(self, catalogo=(), motor=None):
        import cv2  # noqa: F401  (falla aquí si no hay OpenCV)

        import buscar_mas as B
        from utilidades import codigos_modulo as CM
        from utilidades import tablero_campos as T
        self._B, self._T = B, T
        # `motor_compartido` usa RapidOCR o, sin él, el motor del proyecto (P47); si no hay ninguno, la excepción sube y la
        # corrida marca el tablero como «OCR no disponible» (nunca como «sin dato»).
        self.motor = MotorVigilado(motor if motor is not None else CM.motor_compartido())
        self.catalogo = list(catalogo)

    @property
    def errores_ocr(self) -> int:
        return self.motor.errores

    @property
    def ultimo_error(self) -> str:
        return self.motor.ultimo_error

    def cargar(self, ruta: str):
        return self._B.cargar_foto(Path(ruta))

    @staticmethod
    def reducir(imagen, lado: int):
        import cv2
        alto, ancho = imagen.shape[:2]
        if max(alto, ancho) <= lado:
            return imagen
        factor = lado / max(alto, ancho)
        return cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)

    def pista(self, imagen) -> dict:
        return self._T.pista_de_tablero(self.reducir(imagen, LADO_PISTA))

    def leer(self, imagen, pista: dict) -> dict:
        return self._T.leer_foto_de_tablero(self.reducir(imagen, LADO_LECTURA), self.motor,
                                            self.catalogo, pista=pista)

    def fechas(self, imagen) -> list[dict]:
        return self._B.fechas_de_una_imagen(imagen, self.motor)

    @staticmethod
    def guardar_recorte(destino: Path, recorte) -> bool:
        import cv2
        try:
            ok, datos = cv2.imencode(".jpg", recorte, [cv2.IMWRITE_JPEG_QUALITY, 88])
        except Exception:                                 # noqa: BLE001
            return False
        if not ok:
            return False
        destino.parent.mkdir(parents=True, exist_ok=True)
        datos.tofile(str(destino))                        # seguro con rutas no ASCII en Windows
        return True


class CacheLecturasP42:
    """Caché de lecturas P42 por CONTENIDO de foto (SHA-256 de los bytes) y versión del lector.

    P44 · la 1.ª/2.ª pasada cuestan 0,4–4 s por foto (medido con las fotos de la guía); una
    re-corrida sobre las mismas fotos repetía todo. La clave incluye la firma del código que lee
    (`tablero_campos`, `buscar_mas`, `tablero_anclas`, `lector_etiquetas`, `codigos_modulo`,
    `evidencia_tablero` y esta versión): si cambia una regla, la caché deja de valer sola. Sólo se
    guardan llamadas SIN error de OCR. Cada uso queda contado en la cobertura (`desde_cache`), así
    que no es reutilización silenciosa. Se desactiva con `tablero_p42.cache: false`.
    """

    ARCHIVOS_FIRMA = ("utilidades/tablero_campos.py", "buscar_mas.py", "utilidades/tablero_anclas.py",
                      "utilidades/lector_etiquetas.py", "utilidades/codigos_modulo.py",
                      "evidencia_tablero.py")

    def __init__(self, ruta: str | Path):
        import sqlite3
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        raiz = Path(__file__).resolve().parent
        from utilidades.motor_ocr_local import nombre_motor
        firma = hashlib.sha256(f"{VERSION}|{nombre_motor()}".encode())
        for relativo in self.ARCHIVOS_FIRMA:
            archivo = raiz / relativo
            firma.update(archivo.read_bytes() if archivo.is_file() else relativo.encode())
        self.firma = firma.hexdigest()[:16]
        self._con = sqlite3.connect(str(self.ruta), timeout=30)
        self._con.execute("create table if not exists lecturas (clave text primary key, valor text)")
        self.aciertos = 0

    @staticmethod
    def huella_archivo(ruta: str) -> str | None:
        try:
            return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()
        except OSError:
            return None

    def obtener(self, huella: str | None, operacion: str):
        if not huella:
            return None
        fila = self._con.execute("select valor from lecturas where clave=?",
                                 (f"{self.firma}:{operacion}:{huella}",)).fetchone()
        if fila is None:
            return None
        self.aciertos += 1
        return json.loads(fila[0])

    def guardar(self, huella: str | None, operacion: str, valor) -> None:
        if not huella:
            return
        self._con.execute("insert or replace into lecturas values (?, ?)",
                          (f"{self.firma}:{operacion}:{huella}", json.dumps(_serializable(valor))))
        self._con.commit()

    def cerrar(self) -> None:
        try:
            self._con.close()
        except Exception:                                 # noqa: BLE001
            pass


def _serializable(valor):
    """Copia JSON de una lectura: sin recortes (imágenes) y con números de numpy convertidos."""
    if isinstance(valor, dict):
        return {k: _serializable(v) for k, v in valor.items() if k != "recorte"}
    if isinstance(valor, (list, tuple)):
        return [_serializable(v) for v in valor]
    if hasattr(valor, "item") and not isinstance(valor, (str, bytes)):
        try:
            return valor.item()
        except Exception:                                 # noqa: BLE001
            return str(valor)
    return valor


def lecturas_desde_ocr_generico(candidatos: list[dict], textos_por_foto: dict[str, str]) -> dict:
    """Lecturas P42 «gratis» a partir del OCR genérico que la corrida YA hizo. Pura.

    P44 · medido con la guía: el OCR genérico de la foto entera lee el sticker del tablero
    («N/P:… dd/mm/aaaa h:mm:ssPM … IP Part»), y en `REF_04` el filtro barato P42 no ve ninguna
    ancla. Hasta ahora esas lecturas quedaban como `_fecha_por_identificar`. Aquí cada candidato
    genérico `dashboard_*` entra al cierre P42 como una lectura más (`pasada 0`), con la CLASE de
    pegatina calculada sobre el texto completo de su foto (`buscar_mas.clase_de_pegatina`). No
    cuesta OCR y decide con las mismas reglas P42 (una por foto, `_solo_clase`, valor completo).
    """
    try:
        from buscar_mas import clase_de_pegatina
    except Exception:                                     # noqa: BLE001
        def clase_de_pegatina(_texto):
            return ""
    salida: dict[str, list[dict]] = {}
    for candidato in candidatos:
        campo = candidato.get("clave")
        valor = candidato.get("valor_normalizado")
        if campo not in CAMPOS or valor in (None, "") or candidato.get("fuente") not in {"ocr", None}:
            continue
        ruta = str(candidato.get("imagen") or "")
        texto = textos_por_foto.get(ruta, "")
        lectura = {"valor": str(valor), "confianza": round(float(candidato.get("confianza_ocr") or 0), 3),
                   "foto": Path(ruta).name, "carpeta": Path(ruta).parent.as_posix(),
                   "ruta_relativa": ruta, "origen": "ocr_generico:" + str(candidato.get("regla_aplicada") or "")[:40],
                   "ancla": "", "texto": str(candidato.get("valor_original") or "")[:200], "pasada": 0}
        if campo == "dashboard_date":
            lectura["clase"] = clase_de_pegatina(texto)
        salida.setdefault(campo, []).append(lectura)
    return salida


# ----------------------------------------------------------------------------- utilidades puras
def _clave_foto(foto: dict) -> str:
    return str(foto.get("ruta_relativa") or Path(str(foto.get("ruta"))).name).replace("\\", "/")


def _carpeta_relativa(foto: dict) -> str:
    padre = Path(_clave_foto(foto)).parent.as_posix()
    return "" if padre == "." else padre


def _huella(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12]


def _dir_caso(dir_corrida: Path | None, case_key: str) -> Path | None:
    if dir_corrida is None:
        return None
    return Path(dir_corrida) / "tablero_p42" / _huella(case_key)


def _resumen_cobertura(por_foto: dict[str, dict]) -> dict:
    estados = Counter(d["estado"] for d in por_foto.values())
    def lista(conjunto):
        # un error de la 1.ª pasada sigue siendo error aunque la 2.ª (sólo fechas) la mirase
        return [{"ruta": r, "estado": d["estado"] if d["estado"] in conjunto else d["primera"],
                 "motivo": d.get("motivo", "") if d["estado"] in conjunto else d.get("motivo_primera", "")}
                for r, d in sorted(por_foto.items())
                if d["estado"] in conjunto or d.get("primera") in conjunto]
    pendientes = [{"ruta": r, "estado": d["estado"], "motivo": d.get("motivo", "")}
                  for r, d in sorted(por_foto.items())
                  if d["estado"] not in EXAMINADA_PRIMERA | EXAMINADA_SEGUNDA | DESCARTADA | ERROR]
    return {"presentes": len(por_foto),
            "examinadas": sum(estados[e] for e in EXAMINADA_PRIMERA | EXAMINADA_SEGUNDA),
            "con_lectura": estados["leida_con_lectura"] + estados["segunda_con_fecha"],
            "descartadas": lista(DESCARTADA), "errores": lista(ERROR),
            "pendientes": pendientes, "por_estado": dict(sorted(estados.items())),
            "por_foto": por_foto}


def _no_examinadas_para(campo: str, por_foto: dict[str, dict]) -> tuple[int, int]:
    """(pendientes, errores) que impiden decir «sin dato» para ese campo. Pura."""
    validas = EXAMINADA_PRIMERA | (EXAMINADA_SEGUNDA if campo == "dashboard_date" else set())
    pendientes = errores = 0
    for dato in por_foto.values():
        # la 2.ª pasada sólo busca fechas: para los demás campos manda el estado de la 1.ª
        estado = dato["estado"] if campo == "dashboard_date" else dato.get("primera", dato["estado"])
        if estado in validas or estado in DESCARTADA:
            continue
        if estado in ERROR:
            errores += 1
        else:
            pendientes += 1
    return pendientes, errores


def estado_de_campos(cierre: dict, lecturas: dict, por_foto: dict[str, dict],
                     motivo_global: str = "") -> dict[str, dict]:
    """Estado P43 de cada campo del tablero a partir del cierre P42. Pura.

    `consenso`                       valor cerrado por P42 sin ninguna duda → candidato publicable
    `en_duda`                        P42 cerró con duda o descartó todo → pendiente con motivo
    `pendiente_busqueda_incompleta`  sin lectura y quedan fotos sin examinar o con error
    `sin_dato_tras_busqueda`         sin lectura y TODAS las fotos se examinaron sin error
    `sin_fotos` / `ocr_no_disponible` / `error`  el paso no pudo ejecutarse (motivo_global)
    """
    salida: dict[str, dict] = {}
    for campo in CAMPOS:
        valor = cierre.get(campo)
        dudoso = bool((cierre.get("dudoso") or {}).get(campo))
        motivo = str((cierre.get("por_que_dudoso") or {}).get(campo) or "")
        votos = dict((cierre.get("votos") or {}).get(campo) or {})
        pendientes, errores = _no_examinadas_para(campo, por_foto)
        n_lecturas = len(lecturas.get(campo) or [])
        if motivo_global:
            estado, motivo = motivo_global.split(":", 1)[0], motivo_global
        elif valor not in (None, "") and not dudoso:
            estado = "consenso"
        elif campo in cierre or n_lecturas:
            estado = "en_duda"
            motivo = motivo or "lecturas sin consenso P42"
        elif pendientes or errores:
            estado = "pendiente_busqueda_incompleta"
            motivo = (f"sin lectura; {pendientes} foto(s) sin examinar para este campo"
                      + (f" y {errores} con error" if errores else "")
                      + ": no se puede cerrar como «sin dato»")
        else:
            estado = "sin_dato_tras_busqueda"
            motivo = f"las {len(por_foto)} foto(s) presentes se examinaron sin lectura"
        salida[campo] = {"estado": estado, "valor": valor if estado == "consenso" else None,
                         "valor_propuesto": valor if estado == "en_duda" else None,
                         "motivo": motivo, "votos": votos, "lecturas": n_lecturas,
                         "fotos_pendientes": pendientes, "fotos_con_error": errores,
                         "regla": ((cierre.get("fuente") or {}).get(campo) or {}).get("origen", "")}
    return salida


SIMBOLO_A_LETRA = {"$": "S", "§": "S", "|": "I", "!": "I"}
# P52 · la serie del tablero es Code 39 con DÍGITO DE CONTROL módulo 43 al final (medido el 13/11:
# las 10 lecturas DataMatrix de tu corrida lo cumplen; p. ej. «052 3KVJ008R6E» + «1»).
CODE39 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-. $/+%"


def control_code39(cuerpo: str) -> str | None:
    try:
        return CODE39[sum(CODE39.index(c) for c in str(cuerpo).upper()) % 43]
    except ValueError:
        return None


def valida_code39(serie: str) -> bool:
    serie = str(serie or "").upper()
    return len(serie) > 4 and control_code39(serie[:-1]) == serie[-1]


def sin_simbolo_final(valor: str) -> str:
    """P51 · una serie no lleva símbolos: «…R69$» → «…R69S»; otro símbolo final se quita («…R5D%» → «…R5D»)."""
    valor = str(valor or "").rstrip()
    if valor and not valor[-1].isalnum():
        return (valor[:-1] + SIMBOLO_A_LETRA[valor[-1]]) if valor[-1] in SIMBOLO_A_LETRA else valor[:-1].rstrip()
    return valor


def _ordenar_variantes(variantes: list[str]) -> list[str]:
    """Sin repetir; la forma sin símbolo va delante de la que lo trae (un símbolo no se imprime)."""
    salida = []
    for v in variantes:
        for w in ((sin_simbolo_final(v), v) if sin_simbolo_final(v) != v else (v,)):
            if w and w not in salida:
                salida.append(w)
    return salida


def _regla_impreso_con_control(estado: dict, propias: list[dict], es_dm, politica: str) -> bool:
    """P53 · sin DataMatrix: la serie IMPRESA también termina en el dígito de control Code 39.

    El control verifica justo lo que la regla del usuario pone en duda (el último carácter). Para
    no fiarse de una lectura suelta, se exige además que el CUERPO (todo menos el último carácter)
    esté leído igual en ≥2 fotos y que ninguna lectura impresa traiga otro cuerpo:

    - UNA sola serie impresa cumple el control, cuerpo en ≥2 fotos, sin cuerpo contrario
      → se publica según la política (`completa` / `sin_control`), regla `impreso_control_mod43`;
    - cumple el control pero el cuerpo sólo está en 1 foto, o hay otro cuerpo → duda con esa
      serie como propuesta verificada (★ en el formulario);
    - ninguna o varias cumplen el control → no se toca nada (sigue la regla anterior).
    Si hay CUALQUIER lectura DataMatrix (aquí ya se sabe que no cumple el control) tampoco se
    decide: dos tecnologías en desacuerdo se resuelven en el formulario. Devuelve True si actuó.
    """
    if any(es_dm(l) for l in propias):
        return False
    impresas = [(str(l["valor"]).upper().strip(), str(l.get("ruta_relativa") or l.get("foto") or ""))
                for l in propias if not l.get("descartada")]
    validas = list(dict.fromkeys(v for v, _ in impresas if valida_code39(v)))
    if len(validas) != 1:
        return False
    serie = validas[0]
    cuerpo = serie[:-1].rstrip()
    mismo_cuerpo = lambda v: v == cuerpo or (len(v) == len(serie) and v[:-1].rstrip() == cuerpo)  # noqa: E731
    fotos_cuerpo = {f for v, f in impresas if mismo_cuerpo(v)}
    contrarias = sorted({v for v, _ in impresas if not mismo_cuerpo(v)})
    completa = sin_simbolo_final(serie)
    estado["verificada_control"] = {"impreso": serie, "completa": completa, "sin_control": cuerpo,
                                    "fotos_cuerpo": len(fotos_cuerpo)}
    if politica in {"completa", "sin_control"} and len(fotos_cuerpo) >= 2 and not contrarias:
        estado.update(estado="consenso", valor=completa if politica == "completa" else cuerpo,
                      valor_propuesto=None, variantes=[], regla="impreso_control_mod43",
                      motivo=(f"serie impresa con dígito de control Code 39 válido ({serie}); cuerpo "
                              f"leído igual en {len(fotos_cuerpo)} fotos; política «{politica}»"))
        return True
    porque = ("falta decidir si se escribe completa o sin el dígito de control"
              if politica not in {"completa", "sin_control"} else
              f"otra lectura impresa trae otro cuerpo ({', '.join(contrarias[:3])})" if contrarias else
              "el cuerpo sólo se leyó en 1 foto")
    estado.update(estado="en_duda", valor=None, valor_propuesto=completa,
                  variantes=list(dict.fromkeys([completa, cuerpo] + list(estado.get("variantes") or []))),
                  motivo=f"serie impresa verificada por dígito de control ({serie}); {porque}")
    return True


def aplicar_regla_ultimo_caracter(estados: dict, lecturas: dict,
                                  campo: str = "dashboard_serial_number", politica: str = "preguntar") -> None:
    """P45 · REGLA DEL USUARIO (11/11/2026): «el último dígito o carácter a veces no se imprime
    correctamente; por eso existe el formulario de dudas y propuestas». Pura (modifica `estados`).

    La serie del tablero sólo se publica si dos fuentes INDEPENDIENTES coinciden carácter a
    carácter hasta el final: DataMatrix + texto impreso, o ≥2 fotos de texto impreso sin un
    DataMatrix que diga otra cosa. Si no, pasa a duda con el valor leído y, como opción aparte,
    la variante sin el último carácter (rotulada como tal). Ejemplo medido: el DataMatrix de 222504
    trae «…R6E1» y no hay texto impreso que confirme ese «1».
    """
    estado = estados.get(campo) or {}
    propias = [l for l in lecturas.get(campo) or [] if l.get("valor")]
    es_dm = lambda l: str(l.get("origen", "")).lower().startswith("datamatrix")  # noqa: E731
    # P52 · serie VERIFICADA: lectura DataMatrix cuyo último carácter es el control Code 39 de lo
    # anterior (probabilidad de acertarlo por azar: 1/43). Una sola serie verificada en el caso.
    verificadas = list(dict.fromkeys(str(l["valor"]).upper() for l in propias if es_dm(l) and valida_code39(l["valor"])))
    if len(verificadas) == 1:
        dm = verificadas[0]
        completa, base = sin_simbolo_final(dm), dm[:-1].rstrip()
        estado["verificada_control"] = {"datamatrix": dm, "completa": completa, "sin_control": base}
        impreso_igual = any(not es_dm(l) and str(l["valor"]).upper() in {completa, dm} for l in propias)
        if politica not in {"completa", "sin_control"} and estado.get("estado") == "consenso" and \
                str(estado.get("valor") or "").upper() in {completa, dm} and impreso_igual:
            return                        # DataMatrix + impreso iguales: ya confirmado, no se reabre
        if politica in {"completa", "sin_control"}:
            valor = completa if politica == "completa" else base
            estado.update(estado="consenso", valor=valor, valor_propuesto=None, variantes=[],
                          regla="datamatrix_control_mod43", motivo=f"DataMatrix con dígito de control Code 39 válido ({dm}); política «{politica}»")
            return
        estado.update(estado="en_duda", valor=None, valor_propuesto=completa,
                      variantes=list(dict.fromkeys([completa, base] + list(estado.get("variantes") or []))),
                      motivo=(f"serie verificada por dígito de control ({dm}); falta decidir si se escribe "
                              "completa o sin el dígito de control"))
        return
    if not verificadas and _regla_impreso_con_control(estado, propias, es_dm, politica):
        return
    if estado.get("estado") == "en_duda":
        # ya es duda (p. ej. DataMatrix «…R6E1» frente a impreso «…R6ET»): se añade como opción
        # la lectura del DataMatrix sin su último carácter, que es el caso que describe el usuario
        codigos = list(dict.fromkeys(str(l["valor"]) for l in propias if es_dm(l)))
        variantes = codigos + [c[:-1].rstrip() for c in codigos if len(c) > 4]
        if variantes or estado.get("valor_propuesto"):
            estado["variantes"] = _ordenar_variantes([estado.get("valor_propuesto") or variantes[0]] + [
                v for v in variantes if v != estado.get("valor_propuesto")])
            if estado.get("valor_propuesto") and sin_simbolo_final(estado["valor_propuesto"]) != estado["valor_propuesto"]:
                estado["valor_propuesto"] = sin_simbolo_final(estado["valor_propuesto"])
        return
    if estado.get("estado") != "consenso":
        return
    valor = str(estado.get("valor") or "")
    impresas = {str(l.get("ruta_relativa") or l.get("foto")) for l in propias
                if not es_dm(l) and str(l["valor"]) == valor}
    dm_iguales = [l for l in propias if es_dm(l) and str(l["valor"]) == valor]
    dm_distintos = [l for l in propias if es_dm(l) and str(l["valor"]) != valor]
    confirmado = (dm_iguales and impresas) or (len(impresas) >= 2 and not dm_distintos)
    if confirmado:
        return
    variantes = _ordenar_variantes([valor] + ([valor[:-1].rstrip()] if len(valor) > 4 else []))
    estado.update(
        estado="en_duda", valor=None, valor_propuesto=variantes[0], variantes=variantes,
        motivo=("último carácter sin verificar: " +
                ("sólo lo sostiene el DataMatrix (no hay texto impreso igual)" if dm_iguales and not impresas
                 else "una sola fuente impresa" if len(impresas) < 2 else "el DataMatrix dice otra cosa") +
                "; confirmar en el panel de dudas"))


def candidatos_desde_cierre(caso: dict, estados: dict[str, dict], lecturas: dict,
                            fotos_por_clave: dict[str, dict]) -> list[dict]:
    """Candidatos con el contrato de `extraer_candidatos_texto`. Pura.

    - campo en `consenso`: cada lectura que sostiene el valor es un candidato publicable (una
      por FOTO: dos giros de la misma foto no son dos votos);
    - toda otra lectura entra con `requiere_confirmacion_manual=True`: aparece en trazabilidad
      y como opción de duda, pero `consolidar_caso` no la consolida;
    - campo sin lecturas: una fila marcador (valor vacío) con el estado y el motivo, para que
      el pendiente se vea en la Trazabilidad.
    """
    salida: list[dict] = []
    contexto = {"proyecto": caso.get("project_id"), "etapa": caso.get("tipo_st"),
                "caso": caso.get("case_key")}
    for campo in CAMPOS:
        estado = estados[campo]
        propias = list(lecturas.get(campo) or [])
        if not propias:
            salida.append({**contexto, "componente": "tablero", "clave": campo,
                           "valor_original": "", "valor_normalizado": None, "fuente": FUENTE,
                           "imagen": None, "imagen_absoluta": None, "bbox_original": None,
                           "orientacion_grados": 0, "transformaciones": [], "fase": None,
                           "tor": None, "confianza_ocr": 0.0, "valido_catalogo": False,
                           "valido_regex": False, "regla_aplicada": f"p42:{estado['estado']}",
                           "confirmacion_manual": False, "requiere_confirmacion_manual": True,
                           "votos": 0, "version_procesamiento": VERSION,
                           "estado_p42": estado["estado"], "motivo_p42": estado["motivo"],
                           "fotos_pendientes": estado["fotos_pendientes"],
                           "fotos_con_error": estado["fotos_con_error"]})
            continue
        ganador = str(estado["valor"]) if estado["estado"] == "consenso" else None
        verificada = ((estado.get("verificada_control") or {})
                      if estado.get("regla") in {"datamatrix_control_mod43", "impreso_control_mod43"} else {})
        usadas_por_foto: set[str] = set()
        for lectura in propias:
            valor = lectura.get("valor")
            es_codigo = str(lectura.get("origen", "")).lower().startswith("datamatrix")
            if verificada and ganador is not None and (
                    (es_codigo and str(valor or "").upper() == verificada.get("datamatrix")) or
                    (not es_codigo and str(valor or "").upper().strip() == verificada.get("impreso"))):
                valor = ganador           # P52/P53 · serie verificada → la forma elegida por la política
            foto = fotos_por_clave.get(str(lectura.get("ruta_relativa") or ""), {})
            sostiene = (ganador is not None and valor not in (None, "")
                        and str(valor) == ganador and not lectura.get("descartada"))
            clave_foto = str(lectura.get("ruta_relativa") or "")
            if sostiene and clave_foto in usadas_por_foto:
                sostiene = False          # misma foto ya votó: no es una fuente independiente
            if sostiene:
                usadas_por_foto.add(clave_foto)
            if sostiene:
                estado_lectura, motivo = "consenso", ""
            elif ganador is not None:
                estado_lectura = "no_elegida"
                motivo = ("lectura descartada por el lector" if lectura.get("descartada") else
                          f"no coincide con el consenso P42 «{ganador}»")
            else:
                estado_lectura, motivo = estado["estado"], estado["motivo"]
            salida.append({
                **contexto, "componente": "tablero", "clave": campo,
                "valor_original": str(lectura.get("texto") or lectura.get("origen") or valor or "")[:200],
                "valor_normalizado": valor if valor not in (None, "") else None,
                "fuente": FUENTE, "imagen": foto.get("ruta_relativa") or clave_foto or None,
                "imagen_absoluta": foto.get("ruta") or lectura.get("ruta_absoluta"),
                "bbox_original": None, "orientacion_grados": int(lectura.get("giro") or 0),
                "transformaciones": [], "fase": foto.get("fase"), "tor": foto.get("tor"),
                "confianza_ocr": round(float(lectura.get("confianza") or 0.0), 4),
                "valido_catalogo": True, "valido_regex": True,
                "regla_aplicada": "p42:" + ("consenso_valor_completo" if sostiene else estado_lectura),
                "confirmacion_manual": False, "requiere_confirmacion_manual": not sostiene,
                "votos": int((estado.get("votos") or {}).get(str(valor), 0) or 0),
                "version_procesamiento": VERSION, "estado_p42": estado_lectura,
                "motivo_p42": motivo, "origen_lector": str(lectura.get("origen") or "")[:60],
                "clase": str(lectura.get("clase") or ""), "ancla": str(lectura.get("ancla") or ""),
                "pasada": lectura.get("pasada", 1), "recorte": lectura.get("recorte") or "",
                "payload_hex": str(lectura.get("payload_hex") or "")[:400],
                "conflicto": list(lectura.get("conflicto") or []),
                "reparto": dict(estado.get("votos") or {}),
            })
    return salida


def dudas_finales(caso: dict, resultado: dict, campos_consolidados: dict) -> list[dict]:
    """Dudas del tablero DESPUÉS de consolidar: todo campo del tablero que no quedó publicado.

    Incluye los cerrados por P42 que `consolidar_caso` no publicó (p. ej. el nivel, que nunca
    se publica sólo con lecturas automáticas). Nunca propone un valor que no esté en lecturas.
    """
    from utilidades.dudas_y_opciones import DONDE_BUSCAR
    dudas = []
    estados = resultado.get("campos") or {}
    for campo in CAMPOS:
        consolidado = campos_consolidados.get(campo) or {}
        if consolidado.get("valor") not in (None, ""):
            continue
        estado = estados.get(campo) or {"estado": resultado.get("estado"), "motivo": resultado.get("motivo"), "votos": {}}
        motivo = estado.get("motivo") or ""
        if estado.get("estado") == "consenso":
            motivo = (consolidado.get("motivo") or
                      f"P42 cerró «{estado.get('valor')}» pero la consolidación no lo publicó "
                      f"(estado {consolidado.get('estado')})")
        votos = estado.get("votos") or {}
        opciones = [{"valor": valor, "fuente": FUENTE,
                     "detalle": f"{n} lectura(s) del tablero en este caso"}
                    for valor, n in sorted(votos.items(), key=lambda p: -p[1]) if valor]
        for variante in (estado.get("variantes") or [])[1:]:
            if variante and variante not in {o["valor"] for o in opciones}:
                opciones.append({"valor": variante, "fuente": "variante_sin_ultimo_caracter",
                                 "detalle": "la misma lectura sin el último carácter (puede ser de control)"})
        opciones.append({"valor": None, "fuente": "no_lo_tengo",
                         "detalle": "dejar la celda vacía a propósito"})
        recortes = sorted({l.get("recorte") for l in (resultado.get("lecturas") or {}).get(campo, [])
                           if l.get("recorte")})
        dudas.append({
            "id": f"{caso.get('case_key')}::{campo}", "caso": caso.get("case_key"),
            "test_number": (caso.get("metadata_ruta") or {}).get("test_number"),
            "etapa": caso.get("tipo_st"), "campo": campo,
            "motivo": estado.get("estado"), "detalle": motivo,
            "estado_consolidado": consolidado.get("estado"),
            "fotos_pendientes": estado.get("fotos_pendientes", 0),
            "fotos_con_error": estado.get("fotos_con_error", 0),
            "opciones": opciones, "recortes": recortes[:6],
            "donde_mirar": DONDE_BUSCAR.get(campo, []),
        })
    return dudas


def anotar_consolidado(campos_consolidados: dict, resultado: dict) -> None:
    """Deja en cada campo del tablero el estado P43 (sin tocar valor ni estado de publicación)."""
    for campo in CAMPOS:
        estado = (resultado.get("campos") or {}).get(campo)
        if estado and campo in campos_consolidados:
            campos_consolidados[campo]["tablero_p42"] = {
                k: estado.get(k) for k in ("estado", "motivo", "votos", "lecturas", "variantes",
                                           "fotos_pendientes", "fotos_con_error", "regla")}


# ----------------------------------------------------------------------------- orquestación
def _resultado_vacio(caso: dict, estado: str, motivo: str, por_foto: dict) -> dict:
    estados = estado_de_campos({}, {}, por_foto, motivo_global=f"{estado}: {motivo}")
    fotos = {}
    return {"version": VERSION, "case_key": caso.get("case_key"), "estado": estado,
            "motivo": motivo, "cobertura": _resumen_cobertura(por_foto),
            "segunda_pasada": {"ejecutada": False, "motivo": motivo},
            "cierre": {}, "lecturas": {}, "campos": estados,
            "candidatos": candidatos_desde_cierre(caso, estados, {}, fotos),
            "alertas": [{"codigo": "TABLERO_P42_" + estado.upper(), "nivel": "warning",
                         "mensaje": f"Tablero P42 no leído: {motivo}"}]}


def procesar_caso_tablero(caso: dict, fotos: list[dict], opciones: OpcionesTablero,
                          dir_corrida: str | Path | None = None,
                          fabrica_lector: Callable[[], object] | None = None,
                          control: Callable[[], None] | None = None,
                          reloj: Callable[[], float] = time.monotonic,
                          lecturas_genericas: dict | None = None,
                          prioridad_segunda: dict[str, int] | None = None,
                          cache: "CacheLecturasP42 | None" = None,
                          textos_por_foto: dict[str, str] | None = None) -> dict:
    """Lee el tablero de UN caso con las reglas P42 y devuelve candidatos + cobertura + estado.

    Nunca lanza por un fallo de lectura: cada foto que falla queda con su error y cuenta como
    NO examinada. Sí deja pasar la excepción de `control()` (pausa/cancelación).
    """
    import evidencia_tablero as E

    def vigilar():
        if control:
            try:
                control()
            except Exception as exc:                        # noqa: BLE001
                raise _Interrumpido(exc) from exc

    por_foto: dict[str, dict] = {}
    fotos_por_clave = {_clave_foto(f): f for f in fotos}
    for clave in sorted(fotos_por_clave):
        if Path(clave).suffix.lower() not in EXTENSIONES:
            por_foto[clave] = {"estado": "formato_no_soportado",
                               "motivo": f"el lector P42 sólo abre {', '.join(EXTENSIONES)}"}
        else:
            por_foto[clave] = {"estado": "sin_examinar", "motivo": "aún no se ha mirado"}
    if not fotos_por_clave:
        return _resultado_vacio(caso, "sin_fotos", "el caso no tiene fotos NACH/VOR", por_foto)
    try:
        lector = (fabrica_lector or (lambda: LectorP42(opciones.catalogo)))()
    except Exception as exc:                                # noqa: BLE001
        for dato in por_foto.values():
            if dato["estado"] == "sin_examinar":
                dato.update(estado="pendiente_ocr_no_disponible",
                            motivo=f"{type(exc).__name__}: {exc}"[:200])
        return _resultado_vacio(caso, "ocr_no_disponible",
                                f"no se pudo iniciar el lector P42 ({type(exc).__name__}: {exc})"[:300],
                                por_foto)

    carpeta_caso = _dir_caso(dir_corrida, str(caso.get("case_key") or caso.get("nombre")))
    lecturas: dict[str, list[dict]] = {}
    for campo, propias in (lecturas_genericas or {}).items():
        if campo in CAMPOS:
            lecturas.setdefault(campo, []).extend(
                dict(l) for l in propias if str(l.get("ruta_relativa") or "") in fotos_por_clave)
    desde_cache = 0
    huellas: dict[str, str | None] = {}

    def huella(clave: str) -> str | None:
        if cache is None:
            return None
        if clave not in huellas:
            huellas[clave] = cache.huella_archivo(fotos_por_clave[clave]["ruta"])
        return huellas[clave]

    # ---- primera pasada: pista barata y cupos P42
    candidatas = []
    for indice, clave in enumerate(sorted(fotos_por_clave)):
        vigilar()
        if por_foto[clave]["estado"] != "sin_examinar":
            continue
        foto = fotos_por_clave[clave]
        guardada = cache.obtener(huella(clave), "pista") if cache is not None else None
        if guardada is not None:
            pista = guardada
            desde_cache += 1
            if pista.get("algo"):
                candidatas.append({"ruta": clave, "pista": pista})
                por_foto[clave] = {"estado": "fuera_de_cupo",
                                   "motivo": "tiene pista pero no entró en los cupos P42"}
            else:
                por_foto[clave] = {"estado": "sin_pista",
                                   "motivo": "el filtro barato no vio ancla del tablero (no es examen OCR)"}
            continue
        try:
            imagen = lector.cargar(foto["ruta"])
        except Exception as exc:                            # noqa: BLE001
            por_foto[clave] = {"estado": "no_legible", "motivo": f"{type(exc).__name__}: {exc}"[:200]}
            continue
        if imagen is None:
            por_foto[clave] = {"estado": "no_legible", "motivo": "no se pudo decodificar la imagen"}
            continue
        try:
            pista = lector.pista(imagen)
        except Exception as exc:                            # noqa: BLE001
            por_foto[clave] = {"estado": "error_lector", "motivo": f"pista: {type(exc).__name__}: {exc}"[:200]}
            continue
        finally:
            imagen = None
        if cache is not None:
            cache.guardar(huella(clave), "pista", pista)
        if indice % 25 == 24:
            gc.collect()
        if pista.get("algo"):
            candidatas.append({"ruta": clave, "pista": pista})
            por_foto[clave] = {"estado": "fuera_de_cupo",
                               "motivo": "tiene pista pero no entró en los cupos P42"}
        else:
            por_foto[clave] = {"estado": "sin_pista",
                               "motivo": "el filtro barato no vio ancla del tablero (no es examen OCR)"}

    def leer_candidata(candidata: dict, pasada: int = 1) -> None:
        vigilar()
        clave = candidata["ruta"]
        foto = fotos_por_clave[clave]
        antes = lector.errores_ocr
        campos = cache.obtener(huella(clave), "leer") if cache is not None else None
        if campos is not None:
            desde_cache += 1
        else:
            try:
                imagen = lector.cargar(foto["ruta"])
                if imagen is None:
                    por_foto[clave] = {"estado": "no_legible", "motivo": "no se pudo decodificar la imagen"}
                    return
                campos = lector.leer(imagen, candidata["pista"]) or {}
            except Exception as exc:                        # noqa: BLE001
                por_foto[clave] = {"estado": "error_lector", "motivo": f"{type(exc).__name__}: {exc}"[:200]}
                return
            imagen = None
            if cache is not None and lector.errores_ocr == antes:
                cache.guardar(huella(clave), "leer", campos)
        errores = lector.errores_ocr - antes
        for campo, dato in campos.items():
            if campo not in CAMPOS:
                continue
            lectura = {
                "valor": dato.get("valor"), "confianza": round(float(dato.get("confianza") or 0), 3),
                "foto": Path(clave).name, "carpeta": _carpeta_relativa(foto), "ruta_relativa": clave,
                "origen": str(dato.get("origen", ""))[:60], "ancla": str(dato.get("ancla", "") or ""),
                "descartada": bool(dato.get("descartada")), "dudoso": bool(dato.get("dudoso")),
                "texto": str(dato.get("texto", ""))[:200], "cola_cruda": str(dato.get("cola_cruda", "")),
                "clase_cola": str(dato.get("clase_cola", "")),
                "conflicto": list(dato.get("conflicto") or []),
                "payload_hex": str(dato.get("payload_hex", ""))[:400],
                "formato": str(dato.get("formato", "")),
                "version_decode": str(dato.get("version_decode", "")),
                "giro": dato.get("giro") or 0, "pasada": pasada}
            if campo == "dashboard_date" and textos_por_foto and textos_por_foto.get(clave):
                # P44 · H3: la 1.ª pasada no sabía de qué pegatina venía su fecha y `_solo_clase`
                # sólo actuaba tras la 2.ª. La clase sale del texto COMPLETO de esa misma foto
                # (OCR genérico ya hecho) con la misma regla P42 `clase_de_pegatina`.
                try:
                    from buscar_mas import clase_de_pegatina
                    lectura["clase"] = clase_de_pegatina(textos_por_foto[clave])
                except Exception:                           # noqa: BLE001
                    pass
            recorte = dato.get("recorte")
            if (opciones.guardar_recortes and carpeta_caso is not None and recorte is not None
                    and getattr(recorte, "size", 0)):
                destino = carpeta_caso / f"{campo}_{_huella(clave)}_{Path(clave).stem}.jpg"
                if lector.guardar_recorte(destino, recorte):
                    lectura["recorte"] = str(destino)
            lecturas.setdefault(campo, []).append(lectura)
            impreso = dato.get("impreso") if isinstance(dato.get("impreso"), dict) else None
            if impreso and impreso.get("valor"):
                lecturas[campo].append({**{k: v for k, v in lectura.items() if k != "recorte"},
                                        "valor": impreso["valor"],
                                        "confianza": round(float(impreso.get("confianza") or 0), 3),
                                        "origen": "impreso_junto_a_datamatrix",
                                        "texto": str(impreso.get("texto") or "")[:200],
                                        "dudoso": bool(impreso.get("dudoso"))})
        con_lectura = any(l["ruta_relativa"] == clave and l.get("pasada") == pasada
                          for ls in lecturas.values() for l in ls)
        if con_lectura:
            por_foto[clave] = {"estado": "leida_con_lectura",
                               "motivo": (f"{errores} error(es) de OCR en la foto" if errores else "")}
        elif errores:
            por_foto[clave] = {"estado": "error_ocr",
                               "motivo": f"{errores} error(es) de OCR: {lector.ultimo_error}"[:240]}
        else:
            por_foto[clave] = {"estado": "leida_sin_lectura", "motivo": ""}
        gc.collect()

    for candidata in E.elegir_candidatas(candidatas, opciones.cupos):
        leer_candidata(candidata, 1)

    def cerrar() -> dict:
        registro = {"caso": caso.get("nombre", ""), "fotos": len(fotos_por_clave),
                    "con_pista": len(candidatas), "lecturas": lecturas}
        resultado, _ = E.cerrar_registro(registro, str(caso.get("case_key")), None)
        return resultado

    cierre = cerrar()
    # P51 · BÚSQUEDA EXTRA DE LA SERIE: si la serie no cerró, se leen más fotos con pista que
    # quedaron fuera de los cupos (primero las de código/etiqueta), hasta `maximo_extra_serie`.
    extra_serie = {"examinadas": 0, "motivo": ""}
    serie_cerrada = (cierre.get("dashboard_serial_number") not in (None, "")
                     and not (cierre.get("dudoso") or {}).get("dashboard_serial_number"))
    if not serie_cerrada and opciones.maximo_extra_serie > 0:
        def prioridad(c):
            pista = c["pista"]
            area_codigo = (pista.get("codigos") or [{}])[0].get("area", 0) if pista.get("codigos") else 0
            return (0 if pista.get("datamatrix") else 1 if pista.get("codigos") else
                    2 if pista.get("etiqueta") or pista.get("etiquetas") else 3, -float(area_codigo or 0), c["ruta"])
        pendientes = sorted((c for c in candidatas if por_foto[c["ruta"]]["estado"] == "fuera_de_cupo"),
                            key=prioridad)
        for candidata in pendientes[:opciones.maximo_extra_serie]:
            vigilar()
            leer_candidata(candidata, 3)
            extra_serie["examinadas"] += 1
        if extra_serie["examinadas"]:
            cierre = cerrar()
        extra_serie["motivo"] = "serie sin cerrar en la primera pasada"
    segunda = {"ejecutada": False, "motivo": "", "examinadas": 0, "lecturas": 0,
               "presupuesto_agotado": False, "consenso_alcanzado": False}
    fecha_cerrada = (cierre.get("dashboard_date") not in (None, "")
                     and not (cierre.get("dudoso") or {}).get("dashboard_date"))
    if fecha_cerrada:
        segunda["motivo"] = "dashboard_date ya cerrada sin duda en la primera pasada"
    elif not opciones.segunda_pasada:
        segunda["motivo"] = "segunda pasada desactivada en la configuración"
    else:
        # `buscar_mas`: se miran las fotos que NO dieron ninguna lectura (por ruta relativa).
        con_lectura = {l["ruta_relativa"] for ls in lecturas.values() for l in ls}
        pendientes = [c for c in sorted(fotos_por_clave)
                      if c not in con_lectura and por_foto[c]["estado"] not in DESCARTADA
                      and por_foto[c]["estado"] != "no_legible"]
        # P44 · ORDEN, no exclusión: primero las fotos cuyo OCR genérico ya vio algo con forma de
        # fecha o de sticker (llega antes a dos lecturas iguales y para); todas siguen en la lista.
        if prioridad_segunda:
            pendientes.sort(key=lambda c: -int(prioridad_segunda.get(c, 0)))
        segunda.update(ejecutada=True, motivo="dashboard_date sin cierre seguro: ante duda, buscar más",
                       candidatas=len(pendientes))
        for clave in pendientes:
            por_foto[clave]["primera"] = por_foto[clave]["estado"]
            por_foto[clave]["motivo_primera"] = por_foto[clave].get("motivo", "")

        def marcar(clave: str, estado: str, motivo: str) -> None:
            por_foto[clave].update(estado=estado, motivo=motivo)
        inicio = reloj()
        nuevas: list[dict] = []
        for posicion, clave in enumerate(pendientes):
            vigilar()
            if posicion >= opciones.maximo_fotos_segunda:
                break
            if reloj() - inicio > opciones.presupuesto_segunda_s:
                segunda["presupuesto_agotado"] = True
                break
            foto = fotos_por_clave[clave]
            antes = lector.errores_ocr
            datos = cache.obtener(huella(clave), "fechas") if cache is not None else None
            if datos is not None:
                desde_cache += 1
            else:
                try:
                    imagen = lector.cargar(foto["ruta"])
                    if imagen is None:
                        marcar(clave, "no_legible", "no se pudo decodificar la imagen")
                        continue
                    datos = lector.fechas(imagen) or []
                    imagen = None
                except Exception as exc:                    # noqa: BLE001
                    marcar(clave, "error_lector", f"segunda pasada: {type(exc).__name__}: {exc}"[:200])
                    continue
                if cache is not None and lector.errores_ocr == antes:
                    cache.guardar(huella(clave), "fechas", datos)
            errores = lector.errores_ocr - antes
            segunda["examinadas"] += 1
            dato = datos[0] if datos else None            # igual que `buscar_mas.main`
            if dato and dato.get("valor"):
                lectura = {"valor": dato["valor"], "confianza": 0.8, "foto": Path(clave).name,
                           "carpeta": _carpeta_relativa(foto), "ruta_relativa": clave,
                           "origen": "busqueda_exhaustiva", "giro": dato.get("giro", 0),
                           "ancla": dato.get("ancla", ""), "clase": dato.get("clase", ""),
                           "texto": str(dato.get("texto", ""))[:200], "pasada": 2}
                lecturas.setdefault("dashboard_date", []).append(lectura)
                nuevas.append(lectura)
                marcar(clave, "segunda_con_fecha", f"clase {lectura['clase'] or '?'}")
            elif errores:
                marcar(clave, "error_ocr", f"segunda pasada: {errores} error(es) de OCR: {lector.ultimo_error}"[:240])
            else:
                marcar(clave, "segunda_sin_fecha", "")
            conteo = Counter(l["valor"] for l in nuevas if l.get("clase") == "tablero")
            if conteo and max(conteo.values()) >= AVISO_SEGUNDA:
                segunda["consenso_alcanzado"] = True
                break
        segunda["lecturas"] = len(nuevas)
        for clave in pendientes:
            # lo que la segunda pasada no llegó a mirar sigue PENDIENTE (con el porqué);
            # `leida_sin_lectura` ya cuenta como examinada por la primera pasada.
            if por_foto[clave]["estado"] in {"sin_pista", "fuera_de_cupo"}:
                if segunda["consenso_alcanzado"]:
                    marcar(clave, "no_examinada_consenso_alcanzado",
                           "la segunda pasada paró al llegar a dos lecturas iguales del sticker")
                else:
                    marcar(clave, "pendiente_limite_segunda",
                           "presupuesto de tiempo agotado" if segunda["presupuesto_agotado"]
                           else f"máximo de {opciones.maximo_fotos_segunda} fotos")
        cierre = cerrar()

    estados = estado_de_campos(cierre, lecturas, por_foto)
    aplicar_regla_ultimo_caracter(estados, lecturas, politica=opciones.serie_control)
    alertas = []
    cobertura = _resumen_cobertura(por_foto)
    if cobertura["errores"]:
        alertas.append({"codigo": "TABLERO_P42_ERRORES", "nivel": "warning",
                        "mensaje": f"Tablero P42: {len(cobertura['errores'])} foto(s) con error de lectura; "
                                   "no cuentan como examinadas."})
    pendientes_campo = [c for c, e in estados.items() if e["estado"] != "consenso"]
    if pendientes_campo:
        alertas.append({"codigo": "TABLERO_P42_PENDIENTE", "nivel": "info",
                        "mensaje": "Tablero P42 sin cierre seguro en: " + ", ".join(pendientes_campo)})
    cobertura["desde_cache"] = desde_cache
    cobertura["lecturas_ocr_generico"] = sum(1 for ls in lecturas.values() for l in ls
                                             if l.get("pasada") == 0)
    return {"version": VERSION, "case_key": caso.get("case_key"), "estado": "procesado",
            "motivo": "", "cobertura": cobertura, "segunda_pasada": segunda, "extra_serie": extra_serie,
            "cierre": cierre, "lecturas": lecturas, "campos": estados,
            "candidatos": candidatos_desde_cierre(caso, estados, lecturas, fotos_por_clave),
            "alertas": alertas, "carpeta_recortes": str(carpeta_caso) if carpeta_caso else ""}


def ejecutar_seguro(caso: dict, fotos: list[dict], opciones: OpcionesTablero,
                    dir_corrida: str | Path | None = None,
                    fabrica_lector: Callable[[], object] | None = None,
                    control: Callable[[], None] | None = None,
                    lecturas_genericas: dict | None = None,
                    prioridad_segunda: dict[str, int] | None = None,
                    cache: "CacheLecturasP42 | None" = None,
                    textos_por_foto: dict[str, str] | None = None) -> dict:
    """Como `procesar_caso_tablero`, pero un fallo inesperado deja el caso en `error` (con
    todas las fotos pendientes) en vez de tumbar la corrida. La pausa/cancelación sí sube."""
    try:
        return procesar_caso_tablero(caso, fotos, opciones, dir_corrida, fabrica_lector, control,
                                     lecturas_genericas=lecturas_genericas,
                                     prioridad_segunda=prioridad_segunda, cache=cache,
                                     textos_por_foto=textos_por_foto)
    except _Interrumpido as envuelta:
        raise envuelta.original
    except Exception as exc:                                # noqa: BLE001
        por_foto = {_clave_foto(f): {"estado": "pendiente_error_interno",
                                     "motivo": f"{type(exc).__name__}: {exc}"[:200]} for f in fotos}
        return _resultado_vacio(caso, "error", f"fallo interno del paso tablero: "
                                f"{type(exc).__name__}: {exc}"[:300], por_foto)


def informe_corrida(resultados: list[dict]) -> dict:
    """Resumen agregado de cobertura y estados para el informe local. Pura."""
    total = Counter()
    estados_campo = Counter()
    casos = []
    for fila in resultados:
        tablero = fila.get("tablero_p42") or {}
        if not tablero:
            continue
        cobertura = tablero.get("cobertura") or {}
        total["presentes"] += cobertura.get("presentes", 0)
        total["examinadas"] += cobertura.get("examinadas", 0)
        total["con_lectura"] += cobertura.get("con_lectura", 0)
        total["descartadas"] += len(cobertura.get("descartadas") or [])
        total["errores"] += len(cobertura.get("errores") or [])
        total["pendientes"] += len(cobertura.get("pendientes") or [])
        total["desde_cache"] += cobertura.get("desde_cache", 0)
        total["lecturas_ocr_generico"] += cobertura.get("lecturas_ocr_generico", 0)
        for campo, estado in (tablero.get("campos") or {}).items():
            estados_campo[f"{campo}:{estado.get('estado')}"] += 1
        casos.append({"case_key": fila.get("case_key"), "nombre": fila.get("nombre"),
                      "estado": tablero.get("estado"), "motivo": tablero.get("motivo"),
                      "presentes": cobertura.get("presentes", 0),
                      "examinadas": cobertura.get("examinadas", 0),
                      "descartadas": cobertura.get("descartadas") or [],
                      "errores": cobertura.get("errores") or [],
                      "pendientes": cobertura.get("pendientes") or [],
                      "segunda_pasada": tablero.get("segunda_pasada") or {},
                      "campos": {c: {k: e.get(k) for k in ("estado", "valor", "valor_propuesto",
                                                            "motivo", "votos")}
                                 for c, e in (tablero.get("campos") or {}).items()},
                      "dudas": tablero.get("dudas") or []})
    return {"version": VERSION, "totales": dict(total),
            "estados_por_campo": dict(sorted(estados_campo.items())), "casos": casos}


def informe_texto(informe: dict) -> str:
    """Informe legible para el cliente (fotos examinadas, descartadas, con error y pendientes)."""
    t = informe.get("totales") or {}
    lineas = [f"TABLERO P42 EN LA CORRIDA NORMAL · {informe.get('version')}",
              f"  fotos presentes ......... {t.get('presentes', 0)}",
              f"  examinadas (OCR) ........ {t.get('examinadas', 0)}  (con lectura {t.get('con_lectura', 0)})",
              f"  descartadas con motivo .. {t.get('descartadas', 0)}",
              f"  con error ............... {t.get('errores', 0)}",
              f"  pendientes .............. {t.get('pendientes', 0)}",
              f"  lecturas desde caché .... {t.get('desde_cache', 0)}",
              f"  lecturas del OCR genérico {t.get('lecturas_ocr_generico', 0)}", ""]
    for caso in informe.get("casos") or []:
        lineas.append(f"[{caso['estado']}] {caso.get('nombre') or caso['case_key']} · presentes "
                      f"{caso['presentes']} · examinadas {caso['examinadas']} · errores "
                      f"{len(caso['errores'])} · pendientes {len(caso['pendientes'])}"
                      + (f" · {caso['motivo']}" if caso.get("motivo") else ""))
        segunda = caso.get("segunda_pasada") or {}
        if segunda.get("ejecutada"):
            lineas.append(f"    segunda pasada: {segunda.get('examinadas', 0)} examinadas, "
                          f"{segunda.get('lecturas', 0)} fecha(s); consenso "
                          f"{'sí' if segunda.get('consenso_alcanzado') else 'no'}"
                          + ("; PRESUPUESTO AGOTADO" if segunda.get("presupuesto_agotado") else ""))
        for campo, estado in caso["campos"].items():
            valor = estado.get("valor") or estado.get("valor_propuesto") or ""
            lineas.append(f"    {campo:28s} {estado.get('estado'):30s} {valor!s:16s} {estado.get('motivo') or ''}"[:220])
        for error in caso["errores"][:10]:
            lineas.append(f"    ERROR {error['ruta']}: {error['motivo']}"[:220])
        for pendiente in caso["pendientes"][:10]:
            lineas.append(f"    PENDIENTE {pendiente['ruta']}: {pendiente['estado']}"[:220])
        if len(caso["pendientes"]) > 10:
            lineas.append(f"    … y {len(caso['pendientes']) - 10} pendiente(s) más (ver JSON)")
    return "\n".join(lineas) + "\n"


def escribir_informe(dir_corrida: str | Path, resultados: list[dict]) -> dict:
    """Escribe `informe_tablero_p42.json` y `.txt` en el directorio único de la corrida."""
    destino = Path(dir_corrida)
    destino.mkdir(parents=True, exist_ok=True)
    informe = informe_corrida(resultados)
    ruta_json = destino / "informe_tablero_p42.json"
    ruta_txt = destino / "informe_tablero_p42.txt"
    ruta_json.write_text(json.dumps(informe, ensure_ascii=False, indent=1, default=str),
                         encoding="utf-8")
    ruta_txt.write_text(informe_texto(informe), encoding="utf-8")
    dudas = [d for caso in informe["casos"] for d in caso.get("dudas") or []]
    (destino / "dudas_tablero_p42.json").write_text(
        json.dumps(dudas, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return {"json": str(ruta_json), "txt": str(ruta_txt),
            "dudas": str(destino / "dudas_tablero_p42.json"), "totales": informe["totales"]}
