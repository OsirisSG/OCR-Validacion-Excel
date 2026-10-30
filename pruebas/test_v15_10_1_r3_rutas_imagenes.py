from pathlib import Path

from utilidades.rutas_recursos import resolver_raiz_datos, reubicar_ruta


def test_raiz_configurada_obsoleta_no_oculta_raiz_valida(tmp_path):
    raiz_valida = tmp_path / "lote"
    raiz_valida.mkdir()
    datos = {"raiz": str(raiz_valida), "resultados": []}
    resuelta = resolver_raiz_datos(datos, configurada=tmp_path / "ruta_vieja",
                                   raiz_proyecto=tmp_path)
    assert resuelta == raiz_valida.resolve()


def test_ruta_relativa_registrada_se_resuelve_dentro_del_lote(tmp_path):
    raiz = tmp_path / "lote"
    imagen = raiz / "PHOTOS" / "NACH" / "IMG_0001.JPG"
    imagen.parent.mkdir(parents=True)
    imagen.write_bytes(b"jpg")
    datos = {"raiz": str(raiz), "resultados": []}
    assert reubicar_ruta("PHOTOS/NACH/IMG_0001.JPG", datos, raiz) == imagen.resolve()


def test_lote_movido_conserva_sufijo_de_ruta(tmp_path):
    raiz = tmp_path / "nuevo_lote"
    imagen = raiz / "PHOTOS" / "VOR" / "IMG_0002.JPG"
    imagen.parent.mkdir(parents=True)
    imagen.write_bytes(b"jpg")
    datos = {"raiz": r"C:\\Servidor\\LoteViejo", "resultados": []}
    vieja = r"C:\\Servidor\\LoteViejo\\PHOTOS\\VOR\\IMG_0002.JPG"
    assert reubicar_ruta(vieja, datos, raiz) == imagen.resolve()
