# -*- coding: utf-8 -*-
"""Fase 2 — perfiles de reporte (multi-cliente)."""
import json
import shutil
import time
from pathlib import Path

import pytest

from sat_descarga.perfiles import (DISENO_DEFAULT, PerfilReporte, Perfiles, completar_diseno)
from test_lector import cfdi40

RAQUEL, GMH = "HIHR900307P61", "GMH260603UR5"
_LOGO = Path(__file__).parent.parent / "recursos" / "logo_ejemplo.png"


# ================================================================ modelo
def test_crear_duplicar_renombrar_borrar(tmp_path):
    ps = Perfiles(str(tmp_path / "p.json"))
    a = ps.crear("Raquel Hilario", rfcs=[RAQUEL])
    b = ps.duplicar(a.id)
    assert b.nombre == "Raquel Hilario (copia)" and b.rfcs == [RAQUEL] and b.id != a.id
    assert ps.crear("Raquel Hilario").nombre == "Raquel Hilario (2)"      # nombres únicos
    assert ps.renombrar(b.id, "GMH") and ps.por_id(b.id).nombre == "GMH"
    assert not ps.renombrar(b.id, "  ")
    ps.activar(b.id)
    assert ps.borrar(b.id) and ps.activo is None and ps.por_id(b.id) is None


def test_guardar_y_releer(tmp_path):
    ruta = tmp_path / "p.json"
    ps = Perfiles(str(ruta))
    p = ps.crear("GMH", rfcs="gmh260603ur5; ", carpeta_xml="C:/x", carpeta_pdf="C:/pdf",
                 columnas_copiado=["UUID", "Total"], filtros={"tipo": "Recibido", "raro": 1})
    p.diseno["titulo"] = "GMH SA"
    p.diseno["secciones"]["qr"] = False
    ps.activar(p.id); ps.guardar()
    otra = Perfiles.cargar(str(ruta))
    q = otra.activo
    assert q.nombre == "GMH" and q.rfcs == [GMH] and q.carpeta_pdf == "C:/pdf"
    assert q.columnas_copiado == ["UUID", "Total"]
    assert q.filtros == {"tipo": "Recibido", "mes": "todos", "clase": "", "texto": ""}
    assert q.diseno["titulo"] == "GMH SA" and q.diseno["secciones"]["qr"] is False


def test_json_roto_no_truena(tmp_path):
    ruta = tmp_path / "p.json"; ruta.write_text("{no es json", encoding="utf-8")
    ps = Perfiles.cargar(str(ruta))
    assert ps.lista == [] and ps.general == completar_diseno({})


def test_diseno_a_medias_se_completa_y_traduce_claves_viejas():
    d = completar_diseno({"pie": "X", "mostrar_sello_sat": True, "mostrar_letra_clase": False,
                          "subcarpetas": "inventada"})
    assert d["pie"] == "X" and d["subcarpetas"] == ""
    assert d["secciones"]["sellos"] is True and d["secciones"]["letra_clase"] is False
    assert d["nombre_archivo"] == DISENO_DEFAULT["nombre_archivo"]


def test_migra_pdf_config_sin_perder_nada(tmp_path):
    pc = {"general": {"titulo": "", "pie": "Despacho EDDP", "color_primario": "#112233",
                      "logo": "C:/logos/eddp.png", "mostrar_sello_sat": True,
                      "nombre_archivo": "{uuid}"},
          "por_rfc": {"XAXX010101000": {"titulo": "EJEMPLO", "logo": ""},
                      RAQUEL: {"titulo": "RAQUEL HILARIO", "logo": "C:/logos/raquel.png"},
                      GMH: {"titulo": "", "logo": "C:/logos/gmh.png"}}}
    (tmp_path / "pdf_config.json").write_text(json.dumps(pc), encoding="utf-8")
    ps = Perfiles.cargar(str(tmp_path / "perfiles_reporte.json"))
    assert ps.migrado_de_pdf_config and (tmp_path / "perfiles_reporte.json").exists()
    assert (tmp_path / "pdf_config.json").exists()                     # el original se queda
    assert ps.general["pie"] == "Despacho EDDP" and ps.general["logo"] == "C:/logos/eddp.png"
    assert ps.general["secciones"]["sellos"] is True and ps.general["nombre_archivo"] == "{uuid}"
    assert sorted(ps.nombres()) == [GMH, "RAQUEL HILARIO"]               # sin el ejemplo
    r = ps.por_rfc(RAQUEL)
    assert r.diseno["titulo"] == "RAQUEL HILARIO" and r.diseno["logo"] == "C:/logos/raquel.png"
    assert r.diseno["pie"] == "Despacho EDDP"                            # hereda lo general
    assert ps.por_rfc(GMH).diseno["logo"] == "C:/logos/gmh.png"
    # una segunda carga ya NO vuelve a migrar
    assert len(Perfiles.cargar(str(tmp_path / "perfiles_reporte.json")).lista) == 2


def test_diseno_para_activo_luego_rfc_luego_general(tmp_path):
    ps = Perfiles(str(tmp_path / "p.json"))
    ps.general["titulo"] = "GENERAL"
    r = ps.crear("Raquel", rfcs=[RAQUEL]); r.diseno["titulo"] = "RAQUEL"
    g = ps.crear("GMH", rfcs=[GMH]); g.diseno["titulo"] = "GMH"
    assert ps.diseno_para(RAQUEL)["titulo"] == "RAQUEL"
    assert ps.diseno_para("OTRO010101AAA")["titulo"] == "GENERAL"
    ps.activar(g.id)
    assert ps.diseno_para(RAQUEL)["titulo"] == "GMH"


def test_pdf_usa_el_diseno_del_perfil(tmp_path):
    from conftest import texto_pdf
    from sat_descarga.lector import leer_detalle
    from sat_descarga.pdf import cfdi_a_pdf
    det = leer_detalle(Path(__file__).parent / "xml_reales" / "factura_kangoo_4237.xml")
    p = PerfilReporte(nombre="Adriana", rfcs=["FODA920130KD4"],
                      diseno={"titulo": "ADRIANA CONTADORA", "pie": "Pie del perfil",
                              "secciones": {"letra_clase": False}})
    txt = texto_pdf(cfdi_a_pdf(det, str(tmp_path / "x.pdf"), config=p.diseno, clase="G",
                               tipo="Recibido"))
    assert "ADRIANA CONTADORA" in txt and "Pie del perfil" in txt and "GASTO" not in txt


# ================================================================ respaldo
def test_respaldo_lleva_perfiles_y_logos_y_restaura_en_otra_compu(tmp_path, monkeypatch):
    from sat_descarga.config import Config
    from sat_descarga.respaldo import crear_respaldo, restaurar_respaldo
    a = tmp_path / "compu_a"; b = tmp_path / "compu_b"
    logo = tmp_path / "logos_raquel" / "raquel.png"; logo.parent.mkdir()
    shutil.copy(_LOGO, logo)
    monkeypatch.setenv("DESCARGA_XML_EDDP_DATOS", str(a))
    ps = Perfiles.cargar(str(a / "perfiles_reporte.json"))
    r = ps.crear("Raquel Hilario", rfcs=[RAQUEL]); r.diseno["logo"] = str(logo)
    ps.activar(r.id); ps.guardar()
    zip_ = tmp_path / "r.zip"
    crear_respaldo(str(zip_), Config(ruta=str(a / "config.json")))
    import zipfile
    nombres = zipfile.ZipFile(zip_).namelist()
    assert "perfiles_reporte.json" in nombres and "logos/raquel.png" in nombres

    monkeypatch.setenv("DESCARGA_XML_EDDP_DATOS", str(b))
    res = restaurar_respaldo(str(zip_), str(b / "config.json"))
    assert res["perfiles_reporte"] == 1
    otra = Perfiles.cargar(str(b / "perfiles_reporte.json"))
    nuevo_logo = Path(otra.por_rfc(RAQUEL).diseno["logo"])
    assert nuevo_logo.parent == b / "logos" and nuevo_logo.exists()
    assert otra.activo.nombre == "Raquel Hilario"


# ================================================================ UI
tk = pytest.importorskip("tkinter")


def _carpeta(base: Path, dueno: str, n=2, mes="09", prefijo="1"):
    base.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (base / f"g{i}.xml").write_bytes(cfdi40(
            uuid=f"{prefijo}{i:07d}-0000-0000-0000-00000000000A",
            fecha=f"2026-{mes}-1{i}T10:00:00", emisor="PRO010101AAA", receptor=dueno))
    (base / "i0.xml").write_bytes(cfdi40(
        uuid=f"{prefijo}9999999-0000-0000-0000-00000000000B",
        fecha=f"2026-{mes}-20T10:00:00", emisor=dueno, receptor="CLI020202BBB"))
    return str(base)


@pytest.fixture
def app(tmp_path, monkeypatch):
    try:
        r = tk.Tk(); r.withdraw(); r.destroy()
    except tk.TclError as e:
        pytest.skip(f"sin display: {e}")
    monkeypatch.chdir(tmp_path)
    import app as modulo
    monkeypatch.setattr(modulo.messagebox, "showinfo", lambda *a, **k: None)
    a = modulo.App(ruta_config=str(tmp_path / "config.json"))
    a.withdraw()
    yield a
    a._cancelar_lectura.set()
    if a._hilo_lectura is not None:
        a._hilo_lectura.join(10)
    for h in ("_hilo_pdf",):
        t = getattr(a, h, None)
        if t is not None:
            t.join(30)
    try:
        a.after_cancel(a._after_cola)
    except tk.TclError:
        pass
    try:
        a.destroy()
    except tk.TclError:
        pass


def _esperar_lectura(app):
    if app._hilo_lectura is not None:
        app._hilo_lectura.join(60)
    app._procesar_cola()


def _dos_clientes(app, tmp_path):
    ps = app.perfiles_rep
    r = ps.crear("Raquel Hilario", rfcs=[RAQUEL], carpeta_xml=_carpeta(tmp_path / "raquel", RAQUEL),
                 carpeta_pdf=str(tmp_path / "pdf_raquel"),
                 filtros={"tipo": "Recibido"})
    r.diseno["titulo"] = "RAQUEL HILARIO HERNANDEZ"; r.diseno["logo"] = str(_LOGO)
    g = ps.crear("GMH", rfcs=[GMH], carpeta_xml=_carpeta(tmp_path / "gmh", GMH, n=4, mes="08", prefijo="2"),
                 columnas_copiado=["UUID", "Total"])
    ps.guardar(); app._refrescar_perfiles()
    return r, g


def test_selector_lista_perfiles(app, tmp_path):
    _dos_clientes(app, tmp_path)
    assert list(app.cb_perfil.cget("values")) == [app.SIN_PERFIL, "Raquel Hilario", "GMH"]
    assert app.v_perfil.get() == app.SIN_PERFIL


def test_cambiar_de_perfil_carga_su_carpeta_y_lee_sola(app, tmp_path):
    r, g = _dos_clientes(app, tmp_path)
    app.v_perfil.set("Raquel Hilario"); app._perfil_elegido()
    _esperar_lectura(app)
    assert app.v_carpeta_datos.get() == r.carpeta_xml
    assert len(app.filas) == 3 and all(x.datos["Tipo"] for x in app.filas)  # RFC del perfil
    assert app.v_f_tipo.get() == "Recibido" and len(app.filas_vista) == 2    # filtro por defecto
    assert app.aviso_persp.winfo_manager() == ""

    app.v_perfil.set("GMH"); app._perfil_elegido()
    _esperar_lectura(app)
    assert app.v_carpeta_datos.get() == g.carpeta_xml
    assert len(app.filas) == 5 and app.v_f_tipo.get() == "todos"
    assert sorted({x.datos["Clase"] for x in app.filas}) == ["G", "I"]
    assert app._chips["gastos"].cget("text") == "$ 4,640.00"
    # se recuerda al reabrir
    assert Perfiles.cargar(str(app.perfiles_rep.ruta)).activo.nombre == "GMH"


def test_copiar_tabla_con_columnas_del_perfil(app, tmp_path):
    from sat_descarga.lector import COLUMNAS_COPIADO
    _dos_clientes(app, tmp_path)
    app.v_perfil.set("GMH"); app._perfil_elegido(); _esperar_lectura(app)
    app._copiar_tabla()
    assert app.clipboard_get().split("\n")[0] == "UUID\tTotal"
    app.v_perfil.set("Raquel Hilario"); app._perfil_elegido(); _esperar_lectura(app)
    app._copiar_tabla()
    assert app.clipboard_get().split("\n")[0].split("\t") == COLUMNAS_COPIADO


def test_elegir_columnas_se_guarda_en_el_perfil_activo(app, tmp_path):
    r, _ = _dos_clientes(app, tmp_path)
    app._cambiar_perfil(r.id, leer=False)
    app._set_columnas(["Fecha", "UUID"])
    assert Perfiles.cargar(str(app.perfiles_rep.ruta)).por_id(r.id).columnas_copiado == ["Fecha", "UUID"]
    assert app.cfg.opciones.columnas_copiado == []                 # lo global no se toca


def test_botones_nuevo_duplicar_renombrar_borrar(app, tmp_path, monkeypatch):
    import app as modulo
    r, _ = _dos_clientes(app, tmp_path)
    app._cambiar_perfil(r.id, leer=False)
    respuestas = iter(["Raquel 2027", "Raquel nueva"])
    monkeypatch.setattr(modulo.simpledialog, "askstring", lambda *a, **k: next(respuestas))
    app._perfil_duplicar()
    assert app.perfiles_rep.activo.nombre == "Raquel 2027"
    assert app.perfiles_rep.activo.rfcs == [RAQUEL]
    app._perfil_renombrar()
    assert app.v_perfil.get() == "Raquel nueva"
    monkeypatch.setattr(modulo.messagebox, "askyesno", lambda *a, **k: True)
    app._perfil_borrar()
    assert app.v_perfil.get() == app.SIN_PERFIL and "Raquel nueva" not in app.perfiles_rep.nombres()

    monkeypatch.setattr(modulo.simpledialog, "askstring", lambda *a, **k: "Cliente nuevo")
    abiertos = []
    monkeypatch.setattr(modulo, "DialogoPerfilReporte", lambda *a, **k: abiertos.append(a))
    app._perfil_nuevo()
    assert app.perfiles_rep.activo.nombre == "Cliente nuevo" and abiertos


def test_editor_de_perfil_guarda_todo(app, tmp_path):
    import app as modulo
    r, _ = _dos_clientes(app, tmp_path)
    dlg = modulo.DialogoPerfilReporte(app, r)
    dlg.v_rfcs.set(f"{RAQUEL}, hihr900307p62")
    dlg.v_pdf.set(str(tmp_path / "otra_salida"))
    dlg.v_f["clase"].set("G")
    dlg.v["color_primario"].set("#AA0000")
    dlg.v_sub.set("Por mes y clase (202609/G/…)")
    dlg.b["qr"].set(False)
    dlg._guardar()
    q = Perfiles.cargar(str(app.perfiles_rep.ruta)).por_id(r.id)
    assert q.rfcs == [RAQUEL, "HIHR900307P62"] and q.carpeta_pdf == str(tmp_path / "otra_salida")
    assert q.filtros["clase"] == "G" and q.diseno["color_primario"] == "#AA0000"
    assert q.diseno["subcarpetas"] == "mes/clase" and q.diseno["secciones"]["qr"] is False
    assert q.diseno["titulo"] == "RAQUEL HILARIO HERNANDEZ"


def test_confirmar_dueno_sin_perfil_crea_uno(app, tmp_path):
    app.v_carpeta_datos.set(_carpeta(tmp_path / "suelta", RAQUEL))
    app._leer_datos(esperar=True)
    assert app.aviso_persp.winfo_manager() == "pack"
    app.btn_persp_si.invoke()
    activo = app.perfiles_rep.activo
    assert activo is not None and activo.rfcs == [RAQUEL]
    assert activo.carpeta_xml == str(tmp_path / "suelta")
    assert app.v_perfil.get() == activo.nombre


def test_confirmar_dueno_con_perfil_lo_agrega_al_perfil(app, tmp_path):
    g = app.perfiles_rep.crear("GMH", carpeta_xml=_carpeta(tmp_path / "gmh", GMH))
    app._cambiar_perfil(g.id, leer=False)
    app._leer_datos(esperar=True)
    app._aplicar_dueno(GMH)
    assert app.perfiles_rep.activo.rfcs == [GMH] and len(app.perfiles_rep.lista) == 1


def test_generar_pdfs_usa_carpeta_y_diseno_del_perfil(app, tmp_path, monkeypatch):
    import app as modulo
    from conftest import texto_pdf
    r, _ = _dos_clientes(app, tmp_path)
    app.v_perfil.set("Raquel Hilario"); app._perfil_elegido(); _esperar_lectura(app)
    monkeypatch.setattr(modulo.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(modulo.filedialog, "askdirectory",
                        lambda **k: pytest.fail("no debe preguntar: el perfil ya sabe"))
    hecho = []
    monkeypatch.setattr(modulo.messagebox, "showinfo", lambda *a, **k: hecho.append(a))
    monkeypatch.setattr(app, "_abrir_ruta", lambda r: None)
    app._generar_pdfs()
    fin = time.time() + 60
    while not hecho and time.time() < fin:
        app._procesar_cola(); app.update(); time.sleep(0.02)
    pdfs = list(Path(r.carpeta_pdf).rglob("*.pdf"))
    assert len(pdfs) == 2                                     # filtro por defecto: Recibido
    assert "RAQUEL HILARIO HERNANDEZ" in texto_pdf(pdfs[0])
