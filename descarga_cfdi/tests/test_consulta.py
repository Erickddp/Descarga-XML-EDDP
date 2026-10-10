# -*- coding: utf-8 -*-
import csv
from pathlib import Path

import pytest

from sat_descarga.consulta import CONSULTAS_EJEMPLO, MotorSQL
from sat_descarga.exportar import a_csv_cols, a_tsv_cols, matriz_a_csv, matriz_a_tsv
from sat_descarga.lector import leer_carpeta

from test_lector import cfdi40


@pytest.fixture
def filas(tmp_path):
    em = tmp_path / "202608 HIHR" / "emitidos"; em.mkdir(parents=True)
    rc = tmp_path / "202608 HIHR" / "recibidos"; rc.mkdir(parents=True)
    for i in range(4):
        (em / f"E{i}.xml").write_bytes(cfdi40(uuid=f"1111111{i}-2222-3333-4444-555555555555"))
    for i in range(2):
        (rc / f"R{i}.xml").write_bytes(cfdi40(uuid=f"2222222{i}-2222-3333-4444-555555555555",
                                              emisor="IMO011025RIA", total="580.00",
                                              subtotal="500.00", iva="80.00"))
    return leer_carpeta(str(tmp_path))


@pytest.fixture
def motor(filas):
    m = MotorSQL(filas)
    yield m
    m.cerrar()


# ---------------------------------------------------------------- consulta libre
def test_select_todo(motor):
    cols, rows = motor.consultar("SELECT * FROM cfdi")
    assert len(rows) == 6
    assert "UUID" in cols                         # nombres traducidos a visibles


def test_select_filtrado(motor):
    _, rows = motor.consultar("SELECT * FROM cfdi WHERE tipo='Recibido'")
    assert len(rows) == 2


def test_agregacion(motor):
    cols, rows = motor.consultar(
        "SELECT tipo, COUNT(*) n, SUM(total) t FROM cfdi GROUP BY tipo ORDER BY tipo")
    d = {r[0]: (r[1], r[2]) for r in rows}
    assert d["Emitido"][0] == 4
    assert d["Recibido"] == (2, 1160.0)           # 2 x 580


def test_with_cte_permitido(motor):
    cols, rows = motor.consultar(
        "WITH x AS (SELECT total FROM cfdi) SELECT COUNT(*) FROM x")
    assert rows[0][0] == 6


@pytest.mark.parametrize("sql", [
    "UPDATE cfdi SET total=0",
    "DELETE FROM cfdi",
    "DROP TABLE cfdi",
    "INSERT INTO cfdi (total) VALUES (1)",
    "SELECT * FROM cfdi; DROP TABLE cfdi",
    "ALTER TABLE cfdi ADD COLUMN x",
    "CREATE TABLE y (a)",
])
def test_bloquea_escritura(motor, sql):
    with pytest.raises(ValueError):
        motor.consultar(sql)


def test_consulta_vacia_avisa(motor):
    with pytest.raises(ValueError):
        motor.consultar("   ")


def test_error_de_sintaxis_se_propaga(motor):
    import sqlite3
    with pytest.raises(sqlite3.Error):
        motor.consultar("SELECT * FROM no_existe")


def test_consultas_ejemplo_todas_corren(motor):
    for nombre, sql in CONSULTAS_EJEMPLO:
        cols, rows = motor.consultar(sql)
        assert isinstance(cols, list)             # no truena ninguna


# ---------------------------------------------------------------- resumen dashboard
def test_resumen_totales(motor):
    r = motor.resumen()
    assert r["total_cfdi"] == 6
    assert r["por_tipo"]["Emitido"]["n"] == 4
    assert r["por_tipo"]["Recibido"]["n"] == 2
    assert round(r["total"], 2) == 4 * 1160.0 + 2 * 580.0


def test_resumen_por_mes(motor):
    r = motor.resumen()
    assert r["por_mes"] and r["por_mes"][0]["periodo"] == "2026-08"
    assert r["por_mes"][0]["n"] == 6


def test_resumen_top_emisores_solo_recibidos(motor):
    r = motor.resumen()
    assert r["top_emisores"]
    assert r["top_emisores"][0]["rfc"] == "IMO011025RIA"


def test_resumen_vacio_no_truena(tmp_path):
    m = MotorSQL([])
    r = m.resumen()
    assert r["total_cfdi"] == 0 and r["por_mes"] == []
    m.cerrar()


# ---------------------------------------------------------------- export por columnas
def test_tsv_solo_columnas_elegidas(filas):
    cols = ["Fecha", "RFC Emisor", "Total"]
    tsv = a_tsv_cols(filas, cols)
    lineas = tsv.split("\n")
    assert lineas[0].split("\t") == cols
    assert all(len(l.split("\t")) == 3 for l in lineas)


def test_csv_solo_columnas(filas, tmp_path):
    destino = a_csv_cols(filas, ["UUID", "Total"], str(tmp_path / "x.csv"))
    with open(destino, encoding="utf-8-sig") as f:
        r = list(csv.reader(f))
    assert r[0] == ["UUID", "Total"] and len(r) == 7


def test_matriz_tsv_y_csv(tmp_path):
    cols = ["a", "b"]; filas = [[1, 2], [3, 4]]
    assert matriz_a_tsv(cols, filas).split("\n")[0] == "a\tb"
    destino = matriz_a_csv(cols, filas, str(tmp_path / "m.csv"))
    with open(destino, encoding="utf-8-sig") as f:
        assert list(csv.reader(f)) == [["a", "b"], ["1", "2"], ["3", "4"]]


# ---- consultas nuevas de pagos/relacionados ----
def test_hay_muchas_consultas_prediseñadas():
    assert len(CONSULTAS_EJEMPLO) >= 12
    nombres = [n for n, _ in CONSULTAS_EJEMPLO]
    assert "Pagos recibidos (REP) con detalle" in nombres
    assert "Resumen de IVA para declaración" in nombres


def test_consulta_pagos(tmp_path):
    from test_lector import cfdi_pago
    from sat_descarga.lector import leer_carpeta
    r = tmp_path / "202608 HIHR" / "recibidos"; r.mkdir(parents=True)
    (r / "pago.xml").write_bytes(cfdi_pago(monto="2320.00"))
    m = MotorSQL(leer_carpeta(str(tmp_path)))
    cols, rows = m.consultar("SELECT nombre_emisor, imp_pagado FROM cfdi WHERE es_pago='Sí'")
    assert rows[0][1] == 2320.0
    m.cerrar()
