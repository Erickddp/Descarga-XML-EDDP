# -*- coding: utf-8 -*-
"""Inteligencia: perspectiva por RFC, duplicados, factura <-> REP <-> nota, memoria.
La cadena real de INSIGNIA (factura Kangoo PPD 320k, nota de crédito de anticipo
150,610.96 y REP que paga 124,389.04 dejando 45,000) es la prueba de fuego."""
import shutil
from pathlib import Path

import pytest

from sat_descarga.inteligencia import (Memoria, asignar_perspectiva, deduplicar, procesar,
                                       relacionar)
from sat_descarga.lector import leer_carpeta, leer_xml_filas

from test_lector import cfdi40, cfdi_pago

REALES = Path(__file__).parent / "xml_reales"
ADRIANA = "FODA920130KD4"


def _copiar(dest, *nombres):
    dest.mkdir(parents=True, exist_ok=True)
    for n in nombres:
        shutil.copy(REALES / f"{n}.xml", dest / f"{n}.xml")
    return dest


def _por_folio(filas):
    return {f.datos["Folio"]: f.datos for f in filas}


# ---------------------------------------------------------------- cadena real
def test_cadena_real_factura_nota_pago(tmp_path):
    src = _copiar(tmp_path / "x", "factura_kangoo_4237", "nc_anticipo_464", "pago_133k")
    filas, res = procesar(leer_carpeta(str(src)), [ADRIANA])
    fac = _por_folio(filas)["4237"]
    assert fac["Clase"] == "G"
    assert fac["Estatus Pago"] == "Parcial"
    assert fac["Pagado REP"] == 124389.04
    assert fac["NC Aplicadas"] == 150610.96
    assert fac["Saldo Pendiente"] == 45000.0            # = saldo insoluto real del SAT
    assert res["ppd"] == 1 and res["ppd_parciales"] == 1
    assert res["saldo_pendiente"] == 45000.0


def test_rep_sabe_si_su_factura_fue_leida(tmp_path):
    src = _copiar(tmp_path / "x", "factura_kangoo_4237", "pago_133k")
    filas, res = procesar(leer_carpeta(str(src)), [ADRIANA])
    reps = {f.datos["Doc Folio"]: f.datos for f in filas if f.datos["Es Pago"] == "Sí"}
    assert reps["4237"]["Factura Encontrada"] == "Sí"
    assert reps["15761"]["Factura Encontrada"] == "No leída"   # esa factura no estaba
    assert reps["15761"]["Estatus Pago"] == "Liquida factura"
    assert reps["4237"]["Estatus Pago"] == "Pago parcial"
    assert res["reps_sin_factura"] == 1


def test_nota_de_credito_se_liga_a_su_factura(tmp_path):
    src = _copiar(tmp_path / "x", "factura_kangoo_4237", "nc_anticipo_464")
    filas, res = procesar(leer_carpeta(str(src)), [ADRIANA])
    nc = _por_folio(filas)["464"]
    assert nc["Clase"] == "E" and nc["Factura Encontrada"] == "Sí"
    assert res["nc_ligadas"] == 1
    # sin REP: saldo = total - nota
    assert _por_folio(filas)["4237"]["Saldo Pendiente"] == round(320000 - 150610.96, 2)
    assert _por_folio(filas)["4237"]["Estatus Pago"] == "Sin pago"


# ---------------------------------------------------------------- duplicados
def test_mismo_xml_dos_veces_se_cuenta_una(tmp_path):
    src = _copiar(tmp_path / "x", "factura_kangoo_4237")
    shutil.copy(REALES / "factura_kangoo_4237.xml", src / "otra_copia.xml")
    otra = src / "sub"; otra.mkdir()
    shutil.copy(REALES / "factura_kangoo_4237.xml", otra / "tercera.xml")
    filas, res = procesar(leer_carpeta(str(src)), [ADRIANA])
    assert len(filas) == 1
    assert res["duplicados"] == 2 and len(res["duplicados_archivos"]) == 2


def test_rep_duplicado_no_duplica_pagos(tmp_path):
    src = _copiar(tmp_path / "x", "factura_kangoo_4237", "pago_133k")
    shutil.copy(REALES / "pago_133k.xml", src / "pago_copia.xml")
    filas, _ = procesar(leer_carpeta(str(src)), [ADRIANA])
    assert _por_folio(filas)["4237"]["Pagado REP"] == 124389.04     # no 248,778.08


def test_mismo_uuid_en_perspectivas_distintas_se_conserva():
    """Si emites a otro RFC tuyo, el CFDI es ingreso para uno y gasto para el otro."""
    from sat_descarga.lector import Renglon
    a = Renglon({"UUID": "U1", "Tipo": "Emitido", "Doc Pagado UUID": "", "Parcialidad": 0})
    b = Renglon({"UUID": "U1", "Tipo": "Recibido", "Doc Pagado UUID": "", "Parcialidad": 0})
    unicas, dups = deduplicar([a, b])
    assert len(unicas) == 2 and not dups


def test_sin_uuid_nunca_se_toma_como_duplicado():
    from sat_descarga.lector import Renglon
    unicas, dups = deduplicar([Renglon({"UUID": ""}), Renglon({"UUID": ""})])
    assert len(unicas) == 2


# ---------------------------------------------------------------- perspectiva
def test_perspectiva_por_rfc(tmp_path):
    src = tmp_path / "plano"; src.mkdir()
    (src / "e.xml").write_bytes(cfdi40(uuid="E0000000-2222-3333-4444-555555555555",
                                       emisor=ADRIANA, receptor="XAXX010101000"))
    (src / "r.xml").write_bytes(cfdi40(uuid="R0000000-2222-3333-4444-555555555555",
                                       emisor="AAA010101AAA", receptor=ADRIANA))
    filas = leer_carpeta(str(src))
    assert all(f.datos["Tipo"] == "" for f in filas)
    n = asignar_perspectiva(filas, [ADRIANA])
    clases = {f.datos["UUID"][0]: (f.datos["Tipo"], f.datos["Clase"], f.datos["Efecto"]) for f in filas}
    assert n == 2
    assert clases["E"] == ("Emitido", "I", "Ingreso (+)")
    assert clases["R"] == ("Recibido", "G", "Gasto (-)")


def test_carpeta_emitidos_manda_sobre_rfc(tmp_path):
    em = tmp_path / "202608 FODA" / "emitidos"; em.mkdir(parents=True)
    (em / "e.xml").write_bytes(cfdi40(emisor="OTRO010101AAA", receptor=ADRIANA))
    filas = leer_carpeta(str(tmp_path))
    asignar_perspectiva(filas, [ADRIANA])
    assert filas[0].datos["Tipo"] == "Emitido"          # la carpeta ya lo decía


# ---------------------------------------------------------------- estatus
def test_pue_se_marca_pagada(tmp_path):
    (tmp_path / "p.xml").write_bytes(cfdi40(emisor="AAA010101AAA", receptor=ADRIANA))
    filas, _ = procesar(leer_carpeta(str(tmp_path)), [ADRIANA])
    assert filas[0].datos["Estatus Pago"] == "PUE · pagada"
    assert filas[0].datos["Saldo Pendiente"] == 0.0


def test_ppd_liquidada_con_rep(tmp_path):
    fac = cfdi40(uuid="F1111111-2222-3333-4444-555555555555", total="2320.00",
                 emisor="AAA010101AAA", receptor=ADRIANA).replace(b'MetodoPago="PUE"', b'MetodoPago="PPD"')
    (tmp_path / "f.xml").write_bytes(fac)
    (tmp_path / "p.xml").write_bytes(cfdi_pago(docto_uuid="F1111111-2222-3333-4444-555555555555",
                                               monto="2320.00", imp_pagado="2320.00",
                                               saldo_ant="2320.00", saldo_insoluto="0.00"))
    filas, res = procesar(leer_carpeta(str(tmp_path)), [ADRIANA, "FODA920130KD4"])
    f = next(x.datos for x in filas if x.datos["Comprobante"] == "Ingreso")
    assert f["Estatus Pago"] == "Pagada" and f["Saldo Pendiente"] == 0.0
    assert res["ppd_pagadas"] == 1


def test_varias_parcialidades_toma_el_ultimo_saldo(tmp_path):
    uuid_f = "F2222222-2222-3333-4444-555555555555"
    fac = cfdi40(uuid=uuid_f, total="3000.00", emisor="AAA010101AAA",
                 receptor=ADRIANA).replace(b'MetodoPago="PUE"', b'MetodoPago="PPD"')
    (tmp_path / "f.xml").write_bytes(fac)
    (tmp_path / "p1.xml").write_bytes(cfdi_pago(uuid="P1111111-2222-3333-4444-555555555555",
                                                docto_uuid=uuid_f, monto="1000.00", imp_pagado="1000.00",
                                                parcialidad="1", saldo_ant="3000.00", saldo_insoluto="2000.00"))
    (tmp_path / "p2.xml").write_bytes(cfdi_pago(uuid="P2222222-2222-3333-4444-555555555555",
                                                docto_uuid=uuid_f, monto="1500.00", imp_pagado="1500.00",
                                                parcialidad="2", saldo_ant="2000.00", saldo_insoluto="500.00"))
    filas, _ = procesar(leer_carpeta(str(tmp_path)), [ADRIANA])
    f = next(x.datos for x in filas if x.datos["Comprobante"] == "Ingreso")
    assert f["Pagado REP"] == 2500.0 and f["Num REP"] == 2.0
    assert f["Saldo Pendiente"] == 500.0 and f["Estatus Pago"] == "Parcial"


# ---------------------------------------------------------------- memoria
def test_memoria_relaciona_entre_lecturas(tmp_path):
    """El REP se lee hoy en una carpeta; la factura la semana que entra en otra:
    la factura igual encuentra su pago."""
    mem_ruta = str(tmp_path / "memoria.json")
    c1 = _copiar(tmp_path / "semana1", "pago_133k")
    procesar(leer_carpeta(str(c1)), [ADRIANA], Memoria(mem_ruta))

    c2 = _copiar(tmp_path / "semana2", "factura_kangoo_4237")
    filas, res = procesar(leer_carpeta(str(c2)), [ADRIANA], Memoria(mem_ruta))
    fac = _por_folio(filas)["4237"]
    assert fac["Pagado REP"] == 124389.04
    assert fac["Saldo Pendiente"] == 45000.0
    assert res["pagos_por_factura"]["37274D22-2601-4FE7-A8C3-0A16516DF76A"][0]["origen"] == "memoria"


def test_memoria_marca_factura_vista_antes(tmp_path):
    mem_ruta = str(tmp_path / "m.json")
    procesar(leer_carpeta(str(_copiar(tmp_path / "a", "factura_kangoo_4237"))), [ADRIANA], Memoria(mem_ruta))
    filas, _ = procesar(leer_carpeta(str(_copiar(tmp_path / "b", "pago_133k"))), [ADRIANA], Memoria(mem_ruta))
    rep = next(f.datos for f in filas if f.datos.get("Doc Folio") == "4237")
    assert rep["Factura Encontrada"] == "En memoria"


def test_memoria_no_crece_al_releer(tmp_path):
    mem_ruta = str(tmp_path / "m.json")
    src = _copiar(tmp_path / "x", "factura_kangoo_4237", "pago_133k")
    for _ in range(3):
        procesar(leer_carpeta(str(src)), [ADRIANA], Memoria(mem_ruta))
    m = Memoria(mem_ruta)
    assert len(m.pagos) == 2 and len(m.facturas) == 1


def test_memoria_corrupta_no_truena(tmp_path):
    ruta = tmp_path / "m.json"; ruta.write_text("{esto no es json")
    m = Memoria(str(ruta))
    assert len(m) == 0
    procesar(leer_carpeta(str(_copiar(tmp_path / "x", "pago_133k"))), [ADRIANA], m)
    assert len(Memoria(str(ruta)).pagos) == 2          # se reescribió sana


def test_procesar_sin_memoria_ni_rfcs(tmp_path):
    src = _copiar(tmp_path / "x", "factura_kangoo_4237")
    filas, res = procesar(leer_carpeta(str(src)))
    assert len(filas) == 1 and res["duplicados"] == 0
