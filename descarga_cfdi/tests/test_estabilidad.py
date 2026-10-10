# -*- coding: utf-8 -*-
"""Estabilidad: carpeta de datos fija, migración, respaldo/restauración entre
computadoras, zoom y lanzadores de un clic."""
import json
import os
import py_compile
import zipfile
from pathlib import Path

import pytest

from sat_descarga import config as cfgmod
from sat_descarga.config import Config, Perfil, carpeta_datos, en_datos, migrar_datos_viejos
from sat_descarga.respaldo import crear_respaldo, restaurar_respaldo

RAIZ = Path(__file__).parent.parent


@pytest.fixture
def datos(tmp_path, monkeypatch):
    d = tmp_path / "datos"
    monkeypatch.setenv("DESCARGA_XML_EDDP_DATOS", str(d))
    return d


def _efirma(carpeta, nombre):
    carpeta.mkdir(parents=True, exist_ok=True)
    cer = carpeta / f"{nombre}.cer"; cer.write_bytes(b"CER-" + nombre.encode())
    key = carpeta / f"{nombre}.key"; key.write_bytes(b"KEY-" + nombre.encode())
    return str(cer), str(key)


# ---------------------------------------------------------------- carpeta de datos
def test_carpeta_de_datos_se_crea_y_respeta_override(datos):
    assert carpeta_datos() == datos and datos.exists()
    assert Config().ruta == str(datos / "config.json")


def test_rutas_relativas_van_a_la_carpeta_de_datos(datos):
    assert en_datos("log.txt") == str(datos / "log.txt")
    absoluta = str(Path("/tmp/otro/log.txt").resolve())
    assert en_datos(absoluta) == absoluta


def test_estado_de_solicitudes_vive_en_datos(datos):
    p = Perfil(rfc="FODA920130KD4", nombre="A")
    assert Path(p.archivo_estado(Config().opciones)).parent == datos


def test_windows_usa_appdata(tmp_path, monkeypatch):
    monkeypatch.delenv("DESCARGA_XML_EDDP_DATOS", raising=False)
    monkeypatch.setattr(cfgmod, "_es_windows", lambda: True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    assert carpeta_datos() == tmp_path / "AppData" / "Roaming" / "DESCARGA XML EDDP"


# ---------------------------------------------------------------- migración
def test_migra_config_vieja_una_sola_vez(tmp_path, datos, monkeypatch):
    viejo = tmp_path / "programa"; viejo.mkdir()
    (viejo / "config.json").write_text('{"perfiles": [{"rfc": "HIHR900307P61"}]}', encoding="utf-8")
    (viejo / "indice_xml.csv").write_text("archivo\n", encoding="utf-8")
    (viejo / "estado_solicitudes_HIHR_ab12.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cfgmod, "carpeta_programa", lambda: viejo)
    copiados = migrar_datos_viejos()
    assert set(copiados) == {"config.json", "indice_xml.csv", "estado_solicitudes_HIHR_ab12.json"}
    assert Config.desde_archivo().perfiles[0].rfc == "HIHR900307P61"
    # segunda vez: nada (y nunca pisa lo que ya hay en datos)
    (viejo / "config.json").write_text('{"perfiles": []}', encoding="utf-8")
    assert migrar_datos_viejos() == []
    assert Config.desde_archivo().perfiles[0].rfc == "HIHR900307P61"


def test_migracion_sin_datos_viejos(tmp_path, datos, monkeypatch):
    monkeypatch.setattr(cfgmod, "carpeta_programa", lambda: tmp_path / "vacio")
    assert migrar_datos_viejos() == []


# ---------------------------------------------------------------- respaldo
def _config_con_dos(tmp_path):
    c1, k1 = _efirma(tmp_path / "efirmas_pc_a", "foda")
    c2, k2 = _efirma(tmp_path / "efirmas_pc_a", "hihr")
    cfg = Config()
    cfg.agregar(Perfil(rfc="FODA920130KD4", cer_path=c1, key_path=k1, key_password="pa", nombre="ADRIANA"))
    cfg.agregar(Perfil(rfc="HIHR900307P61", cer_path=c2, key_path=k2, key_password="pr", nombre="RAQUEL"))
    cfg.opciones.ultima_carpeta_datos = "C:/xml"
    cfg.guardar()
    return cfg


def test_respaldo_contiene_todo(tmp_path, datos):
    cfg = _config_con_dos(tmp_path)
    (datos / "memoria.json").write_text('{"version":1,"pagos":{},"facturas":{}}', encoding="utf-8")
    r = crear_respaldo(str(tmp_path / "r.zip"), cfg)
    assert r["perfiles"] == 2 and r["efirmas"] == 4 and not r["faltantes"]
    with zipfile.ZipFile(tmp_path / "r.zip") as z:
        n = set(z.namelist())
    assert {"manifest.json", "config.json", "datos/memoria.json"} <= n
    assert sum(1 for x in n if x.startswith("efirmas/")) == 4


def test_respaldo_avisa_efirmas_que_ya_no_existen(tmp_path, datos):
    cfg = Config()
    cfg.agregar(Perfil(rfc="FODA920130KD4", cer_path="C:/se/borro.cer", key_path="C:/se/borro.key",
                       key_password="x", nombre="A"))
    r = crear_respaldo(str(tmp_path / "r.zip"), cfg)
    assert len(r["faltantes"]) == 2 and r["efirmas"] == 0


def test_traspaso_completo_a_otra_computadora(tmp_path, monkeypatch):
    monkeypatch.setenv("DESCARGA_XML_EDDP_DATOS", str(tmp_path / "pc_a"))
    cfg = _config_con_dos(tmp_path)
    crear_respaldo(str(tmp_path / "r.zip"), cfg)

    monkeypatch.setenv("DESCARGA_XML_EDDP_DATOS", str(tmp_path / "pc_b"))   # compu nueva
    r = restaurar_respaldo(str(tmp_path / "r.zip"))
    assert r["nuevos"] == 2 and r["efirmas"] == 4
    nueva = Config.desde_archivo()
    raquel = nueva.por_rfc("HIHR900307P61")
    assert raquel.key_password == "pr" and raquel.nombre == "RAQUEL"
    assert raquel.cer_path.startswith(str(tmp_path / "pc_b"))      # rutas reubicadas
    assert Path(raquel.cer_path).read_bytes() == b"CER-hihr"
    assert raquel.valido()                                          # lista para descargar
    assert nueva.opciones.ultima_carpeta_datos == "C:/xml"          # compu vacía: trae opciones


def test_restaurar_sobre_config_existente_fusiona(tmp_path, monkeypatch):
    monkeypatch.setenv("DESCARGA_XML_EDDP_DATOS", str(tmp_path / "pc_a"))
    cfg = _config_con_dos(tmp_path)
    crear_respaldo(str(tmp_path / "r.zip"), cfg)

    monkeypatch.setenv("DESCARGA_XML_EDDP_DATOS", str(tmp_path / "pc_b"))
    c, k = _efirma(tmp_path / "pc_b_ef", "luis")
    local = Config()
    local.agregar(Perfil(rfc="LECL790321CN2", cer_path=c, key_path=k, key_password="l", nombre="LUIS"))
    local.opciones.ultima_carpeta_datos = "D:/mio"
    local.guardar()
    r = restaurar_respaldo(str(tmp_path / "r.zip"))
    final = Config.desde_archivo()
    assert len(final.perfiles) == 3 and r["nuevos"] == 2
    assert final.opciones.ultima_carpeta_datos == "D:/mio"          # no pisa tus opciones
    # restaurar dos veces no duplica
    r2 = restaurar_respaldo(str(tmp_path / "r.zip"))
    assert len(Config.desde_archivo().perfiles) == 3 and r2["actualizados"] == 2


def test_restaurar_fusiona_memoria_y_remapea_logo(tmp_path, monkeypatch):
    monkeypatch.setenv("DESCARGA_XML_EDDP_DATOS", str(tmp_path / "pc_a"))
    from sat_descarga.pdf import cargar_config_pdf, guardar_config_pdf
    cfg = _config_con_dos(tmp_path)
    logo = tmp_path / "mi_logo.png"; logo.write_bytes((RAIZ / "recursos" / "icono.png").read_bytes())
    pc = cargar_config_pdf(); pc["general"]["logo"] = str(logo); guardar_config_pdf(pc)
    (carpeta_datos() / "memoria.json").write_text(
        json.dumps({"version": 1, "pagos": {"A|B|1": {"x": 1}}, "facturas": {}}), encoding="utf-8")
    crear_respaldo(str(tmp_path / "r.zip"), cfg)

    monkeypatch.setenv("DESCARGA_XML_EDDP_DATOS", str(tmp_path / "pc_b"))
    (carpeta_datos() / "memoria.json").write_text(
        json.dumps({"version": 1, "pagos": {"C|D|1": {"y": 2}}, "facturas": {}}), encoding="utf-8")
    restaurar_respaldo(str(tmp_path / "r.zip"))
    mem = json.loads((carpeta_datos() / "memoria.json").read_text(encoding="utf-8"))
    assert set(mem["pagos"]) == {"A|B|1", "C|D|1"}                  # fusionada, no pisada
    nuevo_logo = cargar_config_pdf()["general"]["logo"]
    assert nuevo_logo.startswith(str(tmp_path / "pc_b")) and Path(nuevo_logo).exists()


def test_zip_que_no_es_respaldo_se_rechaza(tmp_path, datos):
    falso = tmp_path / "otro.zip"
    with zipfile.ZipFile(falso, "w") as z:
        z.writestr("hola.txt", "x")
    with pytest.raises(ValueError, match="no es un respaldo"):
        restaurar_respaldo(str(falso))


def test_respaldo_malicioso_no_escribe_fuera(tmp_path, datos):
    """Un zip manipulado con rutas '../' no puede escribir fuera de la carpeta de datos."""
    malo = tmp_path / "malo.zip"
    with zipfile.ZipFile(malo, "w") as z:
        z.writestr("manifest.json", json.dumps({"perfiles": [
            {"id": "../../escape", "rfc": "../../RFC", "cer": "efirmas/x/../../../../evil.cer", "key": ""}]}))
        z.writestr("config.json", json.dumps({"perfiles": []}))
        z.writestr("efirmas/x/../../../../evil.cer", "malo")
        z.writestr("datos/../../evil2.json", "{}")
    restaurar_respaldo(str(malo))
    assert not (tmp_path / "evil.cer").exists() and not (tmp_path / "evil2.json").exists()
    for f in tmp_path.rglob("evil*"):
        assert str(f).startswith(str(datos))


# ---------------------------------------------------------------- zoom
def test_zoom_escala_y_se_limita():
    tk = pytest.importorskip("tkinter")
    try:
        r = tk.Tk(); r.withdraw()
    except tk.TclError:
        pytest.skip("sin display")
    from sat_descarga.tema import Tema
    t = Tema(r, "claro")
    base = t.fuente("base").cget("size")
    assert t.aplicar_zoom(1.3) == 1.3
    assert t.fuente("base").cget("size") == round(base * 1.3)
    assert t.aplicar_zoom(9) == Tema.ZOOM_MAX
    assert t.aplicar_zoom(0.1) == Tema.ZOOM_MIN
    t.aplicar_zoom(1.0)
    assert t.fuente("base").cget("size") == base
    r.destroy()


# ---------------------------------------------------------------- lanzadores
def test_lanzador_pyw_compila():
    py_compile.compile(str(RAIZ / "DESCARGA XML EDDP.pyw"), doraise=True)


@pytest.mark.parametrize("bat", ["construir_exe.bat", "crear_acceso_directo.bat"])
def test_bat_bien_formados(bat):
    raw = (RAIZ / bat).read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")    # CRLF de Windows
    txt = raw.decode("utf-8")
    assert "\\x27" not in txt and "'Desktop'" in txt                  # comillas reales
    assert 'cd /d "%~dp0"' in txt


def test_spec_empaca_plantillas_del_sat_e_icono():
    spec = (RAIZ / "DESCARGA_XML_EDDP.spec").read_text(encoding="utf-8")
    assert 'collect_all("cfdiclient")' in spec
    assert "console=False" in spec and "icono.ico" in spec
    assert (RAIZ / "recursos" / "icono.ico").exists() and (RAIZ / "recursos" / "icono.png").exists()
