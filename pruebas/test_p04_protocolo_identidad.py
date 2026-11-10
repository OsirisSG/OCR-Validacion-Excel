"""P04 · Identidad del caso desde la barra del vídeo, la carpeta y el diagrama.

Los textos de las pruebas son los REALES: la barra inferior es la cadena del fotograma
del caso 222509 (`VW316/5 222509 RdW NT NOM 0ms EDAG Mex BMG 28 MAY 25 Rec5000 fps`), y
los nombres de carpeta, los que usa el taller.
"""
import pytest


@pytest.fixture()
def pi():
    from utilidades import protocolo_identidad
    return protocolo_identidad


BARRA_222509 = ("VW316/5   222509   RdW   NT   NOM   0ms   EDAG Mex   BMG   28 MAY 25   "
                "Rec5000 fps, Schutter 80us")


def test_lee_la_barra_inferior_del_video(pi):
    """El RDW que no se ve en el diagrama SÍ está quemado en el vídeo."""
    r = pi.leer_barra_video(BARRA_222509)
    assert r["test_number"] == "222509"
    assert r["module_version"] == "RDW"          # el vídeo lo escribe "RdW"
    assert r["temperature_condition"] == "NT"
    assert r["inflator_type"] == "NOM"
    assert r["proyecto"] == "VW316/5"
    assert r["video_ms"] == 0
    assert r["fecha_video"] == "28 MAY 25"
    assert r["test_place"] == "EDAG"
    assert r["fuente"] == "barra_video"


def test_la_barra_con_dos_numeros_no_elige(pi):
    r = pi.leer_barra_video("VW316/5 222509 RdW NT NOM 0ms 232561 HT OGL")
    assert "test_number" not in r
    assert r["conflicto_numero"] == ["222509", "232561"]


def test_la_barra_vacia_o_basura_no_inventa(pi):
    assert pi.leer_barra_video("") == {}
    assert pi.leer_barra_video("Rec5000 fps, Schutter 80us") == {}


def test_lee_el_nombre_de_la_carpeta_del_caso(pi):
    r = pi.leer_nombre_carpeta("232550 RDW NOM HT")
    assert (r["test_number"], r["module_version"], r["temperature_condition"],
            r["inflator_type"]) == ("232550", "RDW", "HT", "NOM")
    # desde la ruta completa de Windows, que es como la guarda la base
    r2 = pi.leer_nombre_carpeta(r"C:\Programas Base\1st\HT\232550 RDW NOM HT\PHOTOS\NACH\IMG_4157.JPG")
    assert r2["test_number"] == "232550"


def test_la_carpeta_mal_escrita_no_se_acepta_a_medias(pi):
    for nombre in ("232550", "232550 RDW NOM", "232550 RDW NOM HT viejo", "caso suelto",
                   "232550 RDW NOM XX", "23255 RDW NOM HT"):
        assert pi.leer_nombre_carpeta(nombre) == {}, nombre


def test_lee_el_titulo_del_diagrama(pi):
    r = pi.leer_titulo_diagrama("VW316/5 222521 RdW NT OGL")
    assert (r["test_number"], r["module_version"], r["temperature_condition"],
            r["inflator_type"]) == ("222521", "RDW", "NT", "OGL")
    # sin RdW el diagrama no da la versión, pero sí el resto: se aporta lo que hay
    parcial = pi.leer_titulo_diagrama("VW316 252590 RT NOM Oms")
    assert parcial["test_number"] == "252590" and parcial["temperature_condition"] == "RT"
    assert "module_version" not in parcial        # el RdW se lo pondrá la carpeta
    assert pi.leer_titulo_diagrama("RdW NT OGL") == {}   # sin número no hay identidad


def test_la_serie_detecta_la_errata_del_libro(pi):
    """222550 marcado HT es imposible: 22xxxx es NT en los 7 000 fotogramas de la base."""
    assert pi.revisar_serie(222550, "HT", "NOM")["estado"] == "incoherente"
    assert pi.revisar_serie(222550, "HT", "NOM")["temperatura_esperada"] == "NT"
    assert pi.revisar_serie(232550, "HT", "NOM")["estado"] == "coherente"
    assert pi.revisar_serie(232561, "HT", "OGL")["estado"] == "coherente"
    assert pi.revisar_serie(232566, "HT", "UGL")["estado"] == "coherente"
    # el bloque 232561-232565 es OGL: decir NOM ahí es incoherente
    assert pi.revisar_serie(232564, "HT", "NOM")["estado"] == "incoherente"
    # un número que la base no tiene no es un error: es un caso nuevo
    assert pi.revisar_serie(299999, "NT", "NOM")["estado"] == "fuera_de_serie"


def test_tres_fuentes_de_acuerdo_confirman(pi):
    c = pi.identidad_del_caso(carpeta="232561 RDW OGL HT",
                              barra="VW316/5 232561 RdW HT OGL 0ms",
                              diagrama="VW316/5 232561 RdW HT OGL")
    assert c.valores["inflator_type"] == "OGL"
    assert "barra_video + carpeta + diagrama" in c.procedencia["inflator_type"]
    assert c.conflictos == {}
    assert c.serie["estado"] == "coherente"


def test_si_discrepan_manda_la_serie_antes_que_nadie(pi):
    """Carpeta NOM contra vídeo OGL en el bloque 232561-232565: la serie decide OGL."""
    c = pi.identidad_del_caso(carpeta="232561 RDW NOM HT", barra="VW316/5 232561 RdW HT OGL 0ms")
    assert c.valores["inflator_type"] == "OGL"
    assert c.procedencia["inflator_type"].startswith("resuelto_por_serie")
    assert c.conflictos["inflator_type"]["descartado"] == {"NOM": ["carpeta"]}


def test_sin_serie_que_decida_manda_la_carpeta_y_queda_registrado(pi):
    """En un número fuera de serie, la carpeta es determinante (instrucción del usuario)."""
    c = pi.identidad_del_caso(carpeta="299999 RDW UGL NT", barra="VW316/5 299999 RdW NT NOM 0ms")
    assert c.valores["inflator_type"] == "UGL"
    assert c.procedencia["inflator_type"] == "resuelto_por_determinante (carpeta)"
    assert c.conflictos["inflator_type"]["descartado"] == {"NOM": ["barra_video"]}


def test_sin_carpeta_y_con_discrepancia_no_se_escribe(pi):
    c = pi.identidad_del_caso(barra="VW316/5 299999 RdW NT OGL 0ms",
                              diagrama="VW316/5 299999 RdW NT UGL")
    assert "inflator_type" not in c.valores
    assert c.escribible("inflator_type") is False
    assert "confirmación manual" in " ".join(c.avisos)


def test_dos_numeros_distintos_nunca_se_resuelven_solos(pi):
    c = pi.identidad_del_caso(carpeta="222550 RDW NOM NT",
                              barra="VW316/5 232550 RdW HT NOM 0ms")
    assert "test_number" not in c.valores
    assert c.conflictos["test_number"]["dice"] == {"232550": ["barra_video"], "222550": ["carpeta"]}


def test_la_franja_inferior_recorta_solo_la_barra(pi):
    from PIL import Image
    imagen = Image.new("RGB", (480, 400), "black")
    recorte = pi.franja_inferior(imagen, 0.90)
    assert recorte.size == (480, 40)
