# -*- coding: utf-8 -*-
"""Pruebas del motor visual y de la persistencia de la sesión."""
import json
import re
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from sat_descarga.config import Config
from sat_descarga.tema import OSCURO, CLARO, TEMAS, Tema


@pytest.fixture(scope="module")
def _display():
    try:
        r = tk.Tk(); r.withdraw(); r.destroy()
    except tk.TclError as e:
        pytest.skip(f"sin display: {e}")


# ---------------------------------------------------------------- paletas
def test_todas_las_paletas_tienen_colores_hex_validos():
    for nombre, pal in TEMAS.items():
        for clave, valor in pal.items():
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", valor), f"{nombre}.{clave}={valor}"


def test_claro_y_oscuro_tienen_las_mismas_claves():
    assert set(CLARO) == set(OSCURO)


def test_hay_claves_esenciales():
    for k in ("bg", "surface", "text", "primary", "border", "danger", "ok"):
        assert k in CLARO


# ---------------------------------------------------------------- Tema
def test_tema_se_aplica_sin_error(_display):
    r = tk.Tk(); r.withdraw()
    t = Tema(r, "claro")
    assert t.nombre == "claro"
    assert t.color("primary") == CLARO["primary"]
    r.destroy()


def test_tema_desconocido_cae_en_claro(_display):
    r = tk.Tk(); r.withdraw()
    t = Tema(r, "inventado")
    assert t.nombre == "claro"
    r.destroy()


def test_tema_oscuro(_display):
    r = tk.Tk(); r.withdraw()
    t = Tema(r, "oscuro")
    assert t.color("bg") == OSCURO["bg"]
    r.destroy()


def test_fuentes_definidas(_display):
    r = tk.Tk(); r.withdraw()
    t = Tema(r, "claro")
    for f in ("base", "titulo", "tabla", "mono", "fuerte"):
        assert t.fuente(f) is not None
    r.destroy()


def test_zebra_configura_tags(_display):
    from tkinter import ttk
    r = tk.Tk(); r.withdraw()
    t = Tema(r, "claro")
    tree = ttk.Treeview(r)
    t.zebra(tree)
    assert tree.tag_configure("par", "background")
    assert tree.tag_configure("impar", "background")
    r.destroy()


# ---------------------------------------------------------------- persistencia de sesión
def test_opciones_guardan_ultima_sesion(tmp_path):
    c = Config(ruta=str(tmp_path / "config.json"))
    c.opciones.ultima_carpeta_datos = "/mis/xml"
    c.opciones.ultimo_desde = "2026-01-01"
    c.opciones.ultimo_hasta = "2026-08-31"
    c.opciones.ultimo_tipo = "emitidos"
    c.opciones.tema = "oscuro"
    c.guardar()
    c2 = Config.desde_archivo(str(tmp_path / "config.json"))
    assert c2.opciones.ultima_carpeta_datos == "/mis/xml"
    assert c2.opciones.ultimo_desde == "2026-01-01"
    assert c2.opciones.ultimo_tipo == "emitidos"
    assert c2.opciones.tema == "oscuro"


def test_config_vieja_sin_campos_nuevos_no_truena(tmp_path):
    viejo = {"opciones": {"carpeta_salida": "x"}, "perfiles": []}
    ruta = tmp_path / "config.json"; ruta.write_text(json.dumps(viejo))
    c = Config.desde_archivo(str(ruta))
    assert c.opciones.tema == "claro"                 # default
    assert c.opciones.ultima_carpeta_datos == ""
