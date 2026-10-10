# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from sat_descarga.lector import leer_detalle
from sat_descarga.pdf import cfdi_a_pdf

from test_lector import cfdi33, cfdi40, RETENCIONES


# ---------------------------------------------------------------- detalle
def test_detalle_campos_principales(tmp_path):
    x = tmp_path / "f.xml"; x.write_bytes(cfdi40(conceptos=2))
    d = leer_detalle(x)
    assert d["emisor_rfc"] == "AAA010101AAA"
    assert d["receptor_nombre"] == "RAQUEL HILARIO"
    assert d["total"] == 1160.0 and d["subtotal"] == 1000.0
    assert d["iva_trasladado"] == 160.0
    assert len(d["conceptos"]) == 2
    assert d["uuid"]


def test_detalle_conceptos_con_importe(tmp_path):
    x = tmp_path / "f.xml"; x.write_bytes(cfdi40(conceptos=3))
    d = leer_detalle(x)
    c = d["conceptos"][0]
    assert c["descripcion"] == "Servicio 1"
    assert c["valor_unitario"] == 1000.0 and c["importe"] == 1000.0
    assert c["cantidad"] == 1


def test_detalle_retenciones(tmp_path):
    x = tmp_path / "f.xml"; x.write_bytes(cfdi40(retenciones=RETENCIONES))
    d = leer_detalle(x)
    assert d["iva_retenido"] == 106.67 and d["isr_retenido"] == 100.0


def test_detalle_version_33(tmp_path):
    x = tmp_path / "v.xml"; x.write_bytes(cfdi33())
    d = leer_detalle(x)
    assert d["version"] == "3.3" and d["total"] == 580.0


def test_detalle_no_cfdi_regresa_none(tmp_path):
    (tmp_path / "b.xml").write_text("<otra/>")
    assert leer_detalle(tmp_path / "b.xml") is None
    assert leer_detalle(tmp_path / "no.xml") is None


# ---------------------------------------------------------------- PDF
def test_pdf_se_genera(tmp_path):
    x = tmp_path / "f.xml"; x.write_bytes(cfdi40(conceptos=3))
    d = leer_detalle(x)
    out = cfdi_a_pdf(d, str(tmp_path / "sal" / "factura.pdf"))
    p = Path(out)
    assert p.exists() and p.stat().st_size > 1000
    assert p.read_bytes()[:5] == b"%PDF-"


def test_pdf_con_retenciones_no_truena(tmp_path):
    x = tmp_path / "f.xml"; x.write_bytes(cfdi40(retenciones=RETENCIONES))
    out = cfdi_a_pdf(leer_detalle(x), str(tmp_path / "f.pdf"))
    assert Path(out).read_bytes()[:5] == b"%PDF-"


def test_pdf_sin_conceptos_no_truena(tmp_path):
    x = tmp_path / "f.xml"; x.write_bytes(cfdi40(conceptos=1))
    d = leer_detalle(x)
    d["conceptos"] = []
    out = cfdi_a_pdf(d, str(tmp_path / "f.pdf"))
    assert Path(out).exists()


def test_pdf_crea_carpeta_si_no_existe(tmp_path):
    x = tmp_path / "f.xml"; x.write_bytes(cfdi40())
    out = cfdi_a_pdf(leer_detalle(x), str(tmp_path / "a" / "b" / "c.pdf"))
    assert Path(out).exists()


# ---- pagos y relacionados en el visor/PDF ----
def test_pdf_de_pago_incluye_monto(tmp_path):
    from test_lector import cfdi_pago
    from sat_descarga.lector import leer_detalle
    x = tmp_path / "p.xml"; x.write_bytes(cfdi_pago(monto="2320.00"))
    out = cfdi_a_pdf(leer_detalle(x), str(tmp_path / "pago.pdf"))
    assert Path(out).read_bytes()[:5] == b"%PDF-"
    assert Path(out).stat().st_size > 1500


def test_pdf_con_relacionados(tmp_path):
    from test_lector import cfdi_con_relacionado
    from sat_descarga.lector import leer_detalle
    x = tmp_path / "r.xml"; x.write_bytes(cfdi_con_relacionado())
    out = cfdi_a_pdf(leer_detalle(x), str(tmp_path / "rel.pdf"))
    assert Path(out).read_bytes()[:5] == b"%PDF-"


def test_pdf_sin_reportlab_da_mensaje_util(tmp_path, monkeypatch):
    """Si falta reportlab, el error debe decir cómo instalarlo (no un ImportError crudo)."""
    import sat_descarga.pdf as mod
    import builtins
    real_import = builtins.__import__
    def fake(name, *a, **k):
        if name.startswith("reportlab"):
            raise ImportError("no reportlab")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    from test_lector import cfdi40
    from sat_descarga.lector import leer_detalle
    x = tmp_path / "f.xml"; x.write_bytes(cfdi40())
    det = leer_detalle(x)
    import pytest as _pt
    with _pt.raises(RuntimeError, match="pip install reportlab"):
        mod.cfdi_a_pdf(det, str(tmp_path / "x.pdf"))


def test_pdf_rep_real_dos_documentos(tmp_path):
    """El PDF del REP de 133k debe generar bien con sus 2 facturas y bases/tasas."""
    from pathlib import Path as _P
    from sat_descarga.lector import leer_detalle
    ruta = _P(__file__).parent / "xml_reales" / "pago_133k.xml"
    det = leer_detalle(ruta)
    assert len(det["pago_docs"]) == 2
    assert det["pago_docs"][0]["base"] == 8796.30
    assert det["pago_docs"][1]["base"] == 115175.04
    out = cfdi_a_pdf(det, str(tmp_path / "rep.pdf"))
    assert _P(out).read_bytes()[:5] == b"%PDF-"
    assert _P(out).stat().st_size > 2000


# ============================================================ PDF personalizable / masivo
import json as _json
import shutil as _shutil

from sat_descarga.pdf import (CONFIG_DEFAULT, cargar_config_pdf, config_para, generar_pdfs,
                              guardar_config_pdf, nombre_pdf)

_REALES = Path(__file__).parent / "xml_reales"
_LOGO = Path(__file__).parent.parent / "recursos" / "logo_ejemplo.png"


from conftest import texto_pdf as _texto_pdf  # noqa: E402  (pypdf; pdftotext solo si existe)


def test_config_se_crea_con_ejemplo_si_no_existe(tmp_path):
    ruta = tmp_path / "pdf_config.json"
    cfg = cargar_config_pdf(str(ruta))
    assert ruta.exists()
    assert cfg["general"]["mostrar_letra_clase"] is True
    assert "_ayuda" in _json.loads(ruta.read_text(encoding="utf-8"))


def test_config_json_roto_no_truena(tmp_path):
    ruta = tmp_path / "pdf_config.json"; ruta.write_text("{roto", encoding="utf-8")
    cfg = cargar_config_pdf(str(ruta))
    assert cfg["general"]["color_primario"] == CONFIG_DEFAULT["general"]["color_primario"]


def test_config_a_medias_se_completa(tmp_path):
    ruta = tmp_path / "pdf_config.json"
    ruta.write_text(_json.dumps({"general": {"titulo": "MI DESPACHO"}}), encoding="utf-8")
    cfg = cargar_config_pdf(str(ruta))
    assert cfg["general"]["titulo"] == "MI DESPACHO"
    assert cfg["general"]["pie"]                     # el resto viene de defaults


def test_por_rfc_sobreescribe_general():
    cfg = {"general": {"titulo": "GENERAL", "logo": "a.png", "pie": "x"},
           "por_rfc": {"FODA920130KD4": {"titulo": "ADRIANA", "logo": ""}}}
    c = config_para(cfg, "foda920130kd4")
    assert c["titulo"] == "ADRIANA"
    assert c["logo"] == "a.png"                      # vacío en por_rfc = hereda general
    assert config_para(cfg, "OTRO")["titulo"] == "GENERAL"


def test_guardar_y_releer_config(tmp_path):
    ruta = tmp_path / "c.json"
    cfg = cargar_config_pdf(str(ruta))
    cfg["general"]["pie"] = "EDDP Servicios"
    cfg["por_rfc"]["HIHR900307P61"] = {"titulo": "RAQUEL", "logo": ""}
    guardar_config_pdf(cfg, str(ruta))
    otra = cargar_config_pdf(str(ruta))
    assert otra["general"]["pie"] == "EDDP Servicios"
    assert otra["por_rfc"]["HIHR900307P61"]["titulo"] == "RAQUEL"


def test_pdf_imprime_cliente_letra_y_seguimiento(tmp_path):
    det = leer_detalle(_REALES / "factura_kangoo_4237.xml")
    cfg = cargar_config_pdf(str(tmp_path / "c.json"))
    cfg["por_rfc"]["FODA920130KD4"] = {"titulo": "ADRIANA GUADALUPE FONSECA DOMINGUEZ"}
    cfg["general"]["pie"] = "Despacho EDDP"
    intel = {"estatus": "Parcial", "pagado_rep": 124389.04, "nc_aplicadas": 150610.96,
             "saldo_pendiente": 45000.0, "pagos": []}
    out = cfdi_a_pdf(det, str(tmp_path / "f.pdf"), config=cfg, clase="G", tipo="Recibido",
                     inteligencia=intel)
    txt = _texto_pdf(out)
    assert "ADRIANA GUADALUPE FONSECA DOMINGUEZ" in txt
    assert "GASTO" in txt                            # etiqueta bajo la letra
    assert "Parcial" in txt and "45,000.00" in txt
    assert "Despacho EDDP" in txt                    # pie de página


def test_pdf_con_logo(tmp_path):
    det = leer_detalle(_REALES / "factura_kangoo_4237.xml")
    cfg = cargar_config_pdf(str(tmp_path / "c.json"))
    cfg["general"]["logo"] = str(_LOGO)
    con = cfdi_a_pdf(det, str(tmp_path / "con.pdf"), config=cfg, clase="G", tipo="Recibido")
    cfg["general"]["logo"] = ""
    sin = cfdi_a_pdf(det, str(tmp_path / "sin.pdf"), config=cfg, clase="G", tipo="Recibido")
    assert Path(con).stat().st_size > Path(sin).stat().st_size     # trae la imagen


def test_logo_inexistente_o_roto_no_impide_el_pdf(tmp_path):
    det = leer_detalle(_REALES / "factura_kangoo_4237.xml")
    roto = tmp_path / "roto.png"; roto.write_bytes(b"no soy imagen")
    for logo in ("C:/no/existe.png", str(roto)):
        cfg = {"general": dict(CONFIG_DEFAULT["general"], logo=logo), "por_rfc": {}}
        out = cfdi_a_pdf(det, str(tmp_path / "x.pdf"), config=cfg, clase="G", tipo="Recibido")
        assert Path(out).read_bytes()[:5] == b"%PDF-"


def test_color_invalido_usa_el_default(tmp_path):
    det = leer_detalle(_REALES / "factura_kangoo_4237.xml")
    cfg = {"general": dict(CONFIG_DEFAULT["general"], color_primario="azulito"), "por_rfc": {}}
    assert Path(cfdi_a_pdf(det, str(tmp_path / "x.pdf"), config=cfg)).exists()


def test_sin_letra_si_se_desactiva(tmp_path):
    det = leer_detalle(_REALES / "factura_kangoo_4237.xml")
    cfg = {"general": dict(CONFIG_DEFAULT["general"], mostrar_letra_clase=False), "por_rfc": {}}
    txt = _texto_pdf(cfdi_a_pdf(det, str(tmp_path / "x.pdf"), config=cfg, clase="G", tipo="Recibido"))
    assert "GASTO" not in txt


def test_nombre_pdf_seguro_para_windows():
    d = {"Fecha": "2026-08-10 13:13:43", "Clase": "G", "Tipo": "Recibido",
         "RFC Emisor": "IMO011025RIA", "RFC Receptor": "FODA920130KD4",
         "Serie": "A/I:J", "Folio": "42*37", "UUID": "37274d22-2601-4fe7-a8c3-0a16516df76a"}
    n = nombre_pdf("{fecha}_{clase}_{rfc_contraparte}_{serie}{folio}_{uuid8}", d)
    assert n == "20260810_G_IMO011025RIA_AIJ4237_37274D22.pdf"
    assert not any(ch in n for ch in '<>:"/\\|?*')


def test_nombre_pdf_plantilla_mala_usa_default():
    d = {"Fecha": "2026-08-10", "Clase": "I", "Tipo": "Emitido", "RFC Receptor": "XAXX010101000",
         "UUID": "ABCDEF12-0000"}
    assert nombre_pdf("{inventado}_{fecha}", d).startswith("20260810_I_XAXX010101000")


def test_generacion_masiva_un_pdf_por_cfdi(tmp_path):
    from sat_descarga.inteligencia import procesar
    from sat_descarga.lector import leer_carpeta
    src = tmp_path / "x"; src.mkdir()
    for n in ("factura_kangoo_4237", "nc_anticipo_464", "pago_133k"):
        _shutil.copy(_REALES / f"{n}.xml", src / f"{n}.xml")
    filas, _ = procesar(leer_carpeta(str(src)), ["FODA920130KD4"])
    assert len(filas) == 4                           # el REP trae 2 filas...
    avances = []
    r = generar_pdfs(filas, str(tmp_path / "pdf"), cargar_config_pdf(str(tmp_path / "c.json")),
                     progreso=lambda i, n: avances.append((i, n)))
    assert r["generados"] == 3 and not r["errores"]  # ...pero es 1 solo PDF
    nombres = sorted(p.name for p in (tmp_path / "pdf").glob("*.pdf"))
    assert [n.split("_")[1] for n in nombres] == ["E", "G", "P"]
    assert avances[-1] == (3, 3)


def test_generacion_masiva_no_regenera_lo_existente(tmp_path):
    from sat_descarga.inteligencia import procesar
    from sat_descarga.lector import leer_carpeta
    src = tmp_path / "x"; src.mkdir()
    _shutil.copy(_REALES / "factura_kangoo_4237.xml", src / "f.xml")
    filas, _ = procesar(leer_carpeta(str(src)), ["FODA920130KD4"])
    cfg = cargar_config_pdf(str(tmp_path / "c.json"))
    assert generar_pdfs(filas, str(tmp_path / "pdf"), cfg)["generados"] == 1
    r2 = generar_pdfs(filas, str(tmp_path / "pdf"), cfg)
    assert r2["generados"] == 0 and r2["omitidos"] == 1
    assert generar_pdfs(filas, str(tmp_path / "pdf"), cfg, sobrescribir=True)["generados"] == 1


def test_generacion_masiva_un_xml_malo_no_detiene_el_lote(tmp_path):
    from sat_descarga.lector import Renglon
    buenos = [Renglon({"UUID": "37274D22", "Tipo": "Recibido", "Clase": "G", "Fecha": "2026-08-10",
                       "Archivo": str(_REALES / "factura_kangoo_4237.xml")})]
    malo = Renglon({"UUID": "MALO0000", "Tipo": "Recibido", "Clase": "G", "Fecha": "2026-08-11",
                    "Archivo": str(tmp_path / "no_existe.xml")})
    r = generar_pdfs([malo] + buenos, str(tmp_path / "pdf"), cargar_config_pdf(str(tmp_path / "c.json")))
    assert r["generados"] == 1 and len(r["errores"]) == 1


def test_generacion_masiva_se_puede_cancelar(tmp_path):
    from sat_descarga.lector import Renglon
    filas = [Renglon({"UUID": f"U{i}", "Tipo": "Recibido", "Clase": "G", "Fecha": "2026-08-10",
                      "Archivo": str(_REALES / "factura_kangoo_4237.xml")}) for i in range(5)]
    r = generar_pdfs(filas, str(tmp_path / "pdf"), cargar_config_pdf(str(tmp_path / "c.json")),
                     cancelado=lambda: True)
    assert r["cancelado"] and r["generados"] == 0


# ============================================================ entorno Windows (Fase 0)
def test_texto_pdf_funciona_sin_pdftotext(tmp_path, monkeypatch):
    """En Windows normalmente no hay pdftotext: el texto sale con pypdf."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    det = leer_detalle(_REALES / "factura_kangoo_4237.xml")
    out = cfdi_a_pdf(det, str(tmp_path / "x.pdf"), clase="G", tipo="Recibido")
    assert "GASTO" in _texto_pdf(out)


def test_pypdf_esta_en_requirements():
    req = (Path(__file__).parent.parent / "requirements.txt").read_text(encoding="utf-8")
    assert "pypdf" in req


# ============================================================ representación impresa SAT (1 hoja)
def _paginas(ruta):
    from pypdf import PdfReader
    return len(PdfReader(str(ruta)).pages)


def test_importe_con_letra():
    from sat_descarga.pdf import importe_con_letra
    assert importe_con_letra(1160) == "MIL CIENTO SESENTA PESOS 00/100 M.N."
    assert importe_con_letra(1) == "UN PESO 00/100 M.N."
    assert importe_con_letra(21) == "VEINTIÚN PESOS 00/100 M.N."
    assert importe_con_letra(1000000) == "UN MILLÓN DE PESOS 00/100 M.N."
    assert importe_con_letra(31000.5) == "TREINTA Y UN MIL PESOS 50/100 M.N."
    assert importe_con_letra(100, "USD") == "CIEN DÓLARES 00/100 USD"


def test_pdf_sat_trae_datos_obligatorios(tmp_path):
    det = leer_detalle(_REALES / "factura_kangoo_4237.xml")
    out = cfdi_a_pdf(det, str(tmp_path / "f.pdf"), clase="G", tipo="Recibido")
    txt = _texto_pdf(out)
    for esperado in ("37274D22-2601-4FE7-A8C3-0A16516DF76A", "00001000000711037500",
                     "00001000000705928441", "32618", "32546", "I03", "626", "601",
                     "Sello digital del CFDI", "Sello digital del SAT",
                     "Cadena original del complemento", "25101500", "XVN", "Tasa 8.00%",
                     "TRESCIENTOS VEINTE MIL PESOS 00/100 M.N.",
                     "Este documento es una representación impresa de un CFDI"):
        assert esperado in txt, esperado
    assert _paginas(out) == 1


def test_pdf_nunca_pasa_de_una_hoja(tmp_path):
    import copy
    det = leer_detalle(_REALES / "factura_kangoo_4237.xml")
    for n in (15, 60, 250):
        d2 = copy.deepcopy(det)
        d2["conceptos"] = [dict(det["conceptos"][0], descripcion=f"Concepto & <{i}> " * 12)
                           for i in range(n)]
        assert _paginas(cfdi_a_pdf(d2, str(tmp_path / f"{n}.pdf"))) == 1


def test_pdf_pago_con_muchos_documentos_una_hoja(tmp_path):
    import copy
    det = leer_detalle(_REALES / "pago_133k.xml")
    det["pago_docs"] = [copy.deepcopy(det["pago_docs"][0]) for _ in range(80)]
    assert _paginas(cfdi_a_pdf(det, str(tmp_path / "p.pdf"))) == 1


def test_qr_usa_url_de_verificacion_del_sat():
    det = leer_detalle(_REALES / "factura_kangoo_4237.xml")
    assert det["qr_url"].startswith("https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?id=37274D22")
    assert "&re=IMO011025RIA&rr=FODA920130KD4&tt=320000.00&fe=" in det["qr_url"]


# ============================================================ paquete para enviar a clientes
def test_nombre_envio_serie_folio_uuid():
    from sat_descarga.pdf import nombre_envio
    d = {"Serie": "C", "Folio": "1", "UUID": "37274d22-2601-4fe7-a8c3-0a16516df76a"}
    assert nombre_envio(d) == "C-1 37274D22-2601-4FE7-A8C3-0A16516DF76A"
    assert nombre_envio(dict(d, Serie="")) == "1 37274D22-2601-4FE7-A8C3-0A16516DF76A"
    assert nombre_envio(dict(d, Serie="", Folio="")) == "37274D22-2601-4FE7-A8C3-0A16516DF76A"


def test_paquete_envio_xml_y_pdf_mismo_nombre_por_cliente(tmp_path):
    from sat_descarga.lector import leer_carpeta
    from sat_descarga.pdf import paquete_envio
    src = tmp_path / "emitidos"; src.mkdir()
    _shutil.copy(_REALES / "factura_kangoo_4237.xml", src / "37274d22.xml")
    filas = leer_carpeta(str(src))
    cfg = cargar_config_pdf(str(tmp_path / "c.json"))
    r = paquete_envio(filas, str(tmp_path / "envio"), config=cfg)
    assert r["generados"] == 1 and not r["errores"]
    carpetas = [p for p in (tmp_path / "envio").iterdir()]
    assert len(carpetas) == 1 and carpetas[0].name.startswith("FODA920130KD4")   # el cliente
    nombres = sorted(p.name for p in carpetas[0].iterdir())
    base = "AIJ-4237 37274D22-2601-4FE7-A8C3-0A16516DF76A"
    assert nombres == [base + ".pdf", base + ".xml"]
    assert (src / "37274d22.xml").exists()                    # el original no se mueve
    assert paquete_envio(filas, str(tmp_path / "envio"), config=cfg)["omitidos"] == 1
