# -*- coding: utf-8 -*-
import json
from datetime import date, datetime

import pytest

from conftest import cfdi_xml, zip_b64
from sat_descarga.almacen import Almacen, extraer_datos, iterar_xml_de_zip
from sat_descarga.utilerias import ContadorDiario, Estado, con_reintentos, partir_por_mes


# ------------------------------------------------------------------ almacén
def test_extraer_uuid_y_fecha_del_xml():
    d = extraer_datos(cfdi_xml("2026-07-04T09:00:00", "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"))
    assert d.uuid == "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    assert (d.anio, d.mes) == ("2026", "07")


def test_extraer_uuid_desde_nombre_si_xml_no_tiene_tfd():
    d = extraer_datos(b"<basura/>", "12345678-1234-1234-1234-123456789ABC.xml")
    assert d.uuid == "12345678-1234-1234-1234-123456789ABC"
    assert d.anio == "sin_fecha"


def test_estructura_de_carpetas_exacta(tmp_path):
    alm = Almacen(str(tmp_path), "xaxx010101000")
    ruta, nuevo = alm.guardar(cfdi_xml("2026-03-15T10:22:01", "11111111-2222-3333-4444-555555555555"), "recibidos")
    assert nuevo is True
    esperado = tmp_path / "202603 XAXX" / "recibidos" / "11111111-2222-3333-4444-555555555555.xml"
    assert ruta == esperado and esperado.exists()


def test_no_sobreescribe_duplicados(tmp_path):
    alm = Almacen(str(tmp_path), "XAXX010101000")
    x = cfdi_xml(uuid="11111111-2222-3333-4444-555555555555")
    _, n1 = alm.guardar(x, "emitidos")
    _, n2 = alm.guardar(x, "emitidos")
    assert (n1, n2) == (True, False)


def test_zip_solo_extrae_xml():
    b64 = zip_b64({"a.xml": cfdi_xml(), "b.XML": cfdi_xml(), "leeme.txt": b"no", "sub/c.pdf": b"no"})
    nombres = [n for n, _ in iterar_xml_de_zip(b64)]
    assert sorted(nombres) == ["a.xml", "b.XML"]


def test_guardar_paquete_cuenta_nuevos_y_duplicados(tmp_path):
    alm = Almacen(str(tmp_path), "XAXX010101000")
    x1 = cfdi_xml(uuid="11111111-1111-1111-1111-111111111111")
    x2 = cfdi_xml(uuid="22222222-2222-2222-2222-222222222222")
    nuevos, dup = alm.guardar_paquete(zip_b64({"1.xml": x1, "2.xml": x2}), "recibidos")
    assert len(nuevos) == 2 and dup == 0
    nuevos, dup = alm.guardar_paquete(zip_b64({"1.xml": x1, "3.xml": cfdi_xml()}), "recibidos")
    assert len(nuevos) == 1 and dup == 1


# ------------------------------------------------------------------ utilerías
def test_partir_por_mes_cubre_todo_sin_huecos():
    tramos = list(partir_por_mes(datetime(2026, 1, 15), datetime(2026, 4, 10)))
    assert [(a.date(), b.date()) for a, b in tramos] == [
        (date(2026, 1, 15), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 3, 1), date(2026, 3, 31)),
        (date(2026, 4, 1), date(2026, 4, 10)),
    ]
    assert tramos[0][0].hour == 0 and tramos[-1][1].strftime("%H:%M:%S") == "23:59:59"


def test_partir_por_mes_un_solo_dia():
    tramos = list(partir_por_mes(datetime(2026, 9, 5), datetime(2026, 9, 5)))
    assert len(tramos) == 1


def test_contador_diario(tmp_path):
    hoy = [date(2026, 9, 5)]
    c = ContadorDiario(str(tmp_path / "c.json"), maximo=2, hoy=lambda: hoy[0])
    assert c.disponibles() == 2
    c.registrar(); c.registrar()
    assert c.disponibles() == 0
    hoy[0] = date(2026, 9, 6)          # al día siguiente se reinicia
    assert c.disponibles() == 2


def test_reintentos_con_backoff(logger):
    esperas = []
    intentos = {"n": 0}

    def fn():
        intentos["n"] += 1
        if intentos["n"] < 3:
            raise ConnectionError("x")
        return "ok"

    assert con_reintentos(fn, 4, 1.0, logger, "t", dormir=esperas.append) == "ok"
    assert esperas == [1.0, 2.0]       # exponencial


def test_reintentos_agota_y_levanta(logger):
    with pytest.raises(RuntimeError, match="tras 2 intentos"):
        con_reintentos(lambda: 1 / 0, 2, 0, logger, "t", dormir=lambda s: None)


def test_estado_persiste_en_archivo(tmp_path):
    ruta = tmp_path / "e.json"
    e = Estado(str(ruta))
    e.marcar("emitidos", datetime(2026, 1, 1), datetime(2026, 1, 31), id_solicitud="S1")
    e2 = Estado(str(ruta))                      # reabrir
    assert e2.obtener("emitidos", datetime(2026, 1, 1), datetime(2026, 1, 31))["id_solicitud"] == "S1"
    assert json.loads(ruta.read_text())["emitidos|2026-01-01|2026-01-31"]["id_solicitud"] == "S1"
