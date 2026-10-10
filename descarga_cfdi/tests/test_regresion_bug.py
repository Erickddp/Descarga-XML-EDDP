# -*- coding: utf-8 -*-
"""Pruebas del bug real reportado: al agregar un RFC se borraba el anterior,
más el RFC leído del certificado y la estructura de carpetas nueva.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import cfdi_xml, zip_b64
from sat_descarga.almacen import Almacen, extraer_datos, migrar_estructura_vieja
from sat_descarga.certificado import datos_del_cer, rfc_de_nombre_archivo
from sat_descarga.config import Config, Opciones, Perfil


# ============================================================ EL BUG
def test_agregar_segundo_perfil_no_borra_al_primero(tmp_path):
    """Exactamente lo que pasó: dos e.firmas distintas terminaron con el mismo
    RFC capturado y Raquel desapareció."""
    c = Config(ruta=str(tmp_path / "c.json"))
    raquel = Perfil(rfc="HIHR900307P61", nombre="RAQUEL HILARIO H")
    adriana = Perfil(rfc="HIHR900307P61", nombre="ADRIANA FONSECA")   # RFC mal capturado
    c.agregar(raquel)
    c.agregar(adriana)
    assert [p.nombre for p in c.perfiles] == ["RAQUEL HILARIO H", "ADRIANA FONSECA"]
    assert len(c.perfiles) == 2


def test_editar_no_duplica_conserva_identidad(tmp_path):
    c = Config(ruta=str(tmp_path / "c.json"))
    p = Perfil(rfc="AAA010101AAA", nombre="viejo")
    c.agregar(p)
    editado = Perfil(rfc="BBB020202BBB", nombre="nuevo", id=p.id)
    c.agregar(editado)
    assert len(c.perfiles) == 1 and c.perfiles[0].nombre == "nuevo"


def test_perfiles_del_mismo_rfc_no_comparten_estado(tmp_path):
    """Por eso Adriana decía 'ya completado antes, se omite'."""
    op = Opciones()
    a = Perfil(rfc="HIHR900307P61", nombre="Raquel")
    b = Perfil(rfc="HIHR900307P61", nombre="Adriana")
    assert a.archivo_estado(op) != b.archivo_estado(op)
    assert a.archivo_contador(op) != b.archivo_contador(op)


def test_ids_son_unicos_y_persisten(tmp_path):
    c = Config(ruta=str(tmp_path / "c.json"))
    c.agregar(Perfil(rfc="AAA010101AAA", nombre="A"))
    c.agregar(Perfil(rfc="BBB020202BBB", nombre="B"))
    ids = [p.id for p in c.perfiles]
    assert len(set(ids)) == 2
    c.guardar()
    c2 = Config.desde_archivo(str(tmp_path / "c.json"))
    assert [p.id for p in c2.perfiles] == ids       # el id sobrevive al reinicio


def test_eliminar_por_id_no_toca_al_gemelo(tmp_path):
    c = Config(ruta=str(tmp_path / "c.json"))
    a = Perfil(rfc="HIHR900307P61", nombre="Raquel")
    b = Perfil(rfc="HIHR900307P61", nombre="Adriana")
    c.agregar(a); c.agregar(b)
    c.eliminar(b.id)
    assert [p.nombre for p in c.perfiles] == ["Raquel"]


# ============================================================ RFC del certificado
@pytest.fixture(scope="module")
def cer_de(tmp_path_factory):
    from conftest import openssl

    def hacer(rfc, nombre="RAQUEL HILARIO HERNANDEZ"):
        d = tmp_path_factory.mktemp(f"c{rfc}")
        openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", d / "k.pem", "-out", d / "c.pem", "-days", "1",
                "-subj", f"/CN={nombre}/serialNumber={rfc}")
        cer = d / "archivo_sin_pistas.cer"
        openssl("x509", "-in", d / "c.pem", "-outform", "DER", "-out", cer)
        return str(cer)
    return hacer


def test_rfc_se_lee_del_certificado_aunque_el_archivo_no_lo_diga(cer_de):
    ruta = cer_de("HIHR900307P61")
    rfc, nombre = datos_del_cer(ruta)
    assert rfc == "HIHR900307P61"
    assert nombre and "RAQUEL" in nombre.upper()
    assert rfc_de_nombre_archivo(ruta) is None      # el nombre del archivo no ayudaba


def test_dos_certificados_dan_rfcs_distintos(cer_de):
    assert datos_del_cer(cer_de("HIHR900307P61"))[0] == "HIHR900307P61"
    assert datos_del_cer(cer_de("FODA920130KD4", "ADRIANA FONSECA"))[0] == "FODA920130KD4"


def test_rfc_de_nombre_archivo_como_respaldo():
    assert rfc_de_nombre_archivo("C:/x/Claveprivada_FIEL_FODA920130KD4_20260401.key") == "FODA920130KD4"
    assert rfc_de_nombre_archivo("C:/x/foda920130kd4.cer") == "FODA920130KD4"
    assert rfc_de_nombre_archivo("C:/x/mi_llave.key") is None


# ============================================================ carpetas nuevas
def test_estructura_corta_aaaamm_mas_4_letras(tmp_path):
    alm = Almacen(str(tmp_path), "HIHR900307P61")
    ruta, _ = alm.guardar(cfdi_xml("2026-08-14T10:00:00", "11111111-2222-3333-4444-555555555555"), "emitidos")
    assert ruta == tmp_path / "202608 HIHR" / "emitidos" / "11111111-2222-3333-4444-555555555555.xml"
    assert ruta.exists()


def test_otro_rfc_otra_carpeta_mismo_mes(tmp_path):
    Almacen(str(tmp_path), "HIHR900307P61").guardar(cfdi_xml("2026-08-01T00:00:00"), "emitidos")
    Almacen(str(tmp_path), "FODA920130KD4").guardar(cfdi_xml("2026-08-01T00:00:00"), "emitidos")
    assert sorted(d.name for d in tmp_path.iterdir()) == ["202608 FODA", "202608 HIHR"]


def test_solo_dos_niveles_no_anidamiento_infinito(tmp_path):
    alm = Almacen(str(tmp_path), "HIHR900307P61")
    ruta, _ = alm.guardar(cfdi_xml("2026-08-14T10:00:00"), "recibidos")
    assert len(ruta.relative_to(tmp_path).parts) == 3      # carpeta / tipo / archivo


def test_meses_distintos_carpetas_distintas(tmp_path):
    alm = Almacen(str(tmp_path), "HIHR900307P61")
    alm.guardar(cfdi_xml("2026-07-31T23:00:00"), "emitidos")
    alm.guardar(cfdi_xml("2026-08-01T01:00:00"), "emitidos")
    assert sorted(d.name for d in tmp_path.iterdir()) == ["202607 HIHR", "202608 HIHR"]


def test_xml_sin_fecha_no_truena(tmp_path):
    alm = Almacen(str(tmp_path), "HIHR900307P61")
    ruta, _ = alm.guardar(b"<basura/>", "emitidos", "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE.xml")
    assert ruta.parent.parent.name == "sin_fecha HIHR"


def test_dedupe_sigue_funcionando_en_la_estructura_nueva(tmp_path):
    alm = Almacen(str(tmp_path), "HIHR900307P61")
    x = cfdi_xml("2026-08-14T10:00:00", "11111111-2222-3333-4444-555555555555")
    assert alm.guardar(x, "emitidos")[1] is True
    assert alm.guardar(x, "emitidos")[1] is False


# ============================================================ migración
def test_migra_descargas_anteriores(tmp_path):
    viejo = tmp_path / "HIHR900307P61" / "2026" / "08"
    (viejo / "emitidos").mkdir(parents=True)
    (viejo / "recibidos").mkdir(parents=True)
    for i in range(35):
        (viejo / "emitidos" / f"E{i}.xml").write_text("<x/>")
    for i in range(3):
        (viejo / "recibidos" / f"R{i}.xml").write_text("<x/>")

    assert migrar_estructura_vieja(str(tmp_path)) == 38
    assert len(list((tmp_path / "202608 HIHR" / "emitidos").glob("*.xml"))) == 35
    assert len(list((tmp_path / "202608 HIHR" / "recibidos").glob("*.xml"))) == 3
    assert not (tmp_path / "HIHR900307P61").exists()


def test_migracion_es_idempotente_y_no_toca_lo_nuevo(tmp_path):
    nueva = tmp_path / "202608 HIHR" / "emitidos"
    nueva.mkdir(parents=True)
    (nueva / "A.xml").write_text("<x/>")
    assert migrar_estructura_vieja(str(tmp_path)) == 0
    assert (nueva / "A.xml").exists()


def test_migracion_sin_carpeta_no_truena(tmp_path):
    assert migrar_estructura_vieja(str(tmp_path / "no_existe")) == 0


def test_migracion_no_duplica_si_ya_estaba_migrado(tmp_path):
    viejo = tmp_path / "HIHR900307P61" / "2026" / "08" / "emitidos"
    viejo.mkdir(parents=True)
    (viejo / "A.xml").write_text("<x/>")
    (tmp_path / "202608 HIHR" / "emitidos").mkdir(parents=True)
    (tmp_path / "202608 HIHR" / "emitidos" / "A.xml").write_text("<x/>")
    migrar_estructura_vieja(str(tmp_path))
    assert len(list((tmp_path / "202608 HIHR" / "emitidos").glob("*.xml"))) == 1
    assert not (tmp_path / "HIHR900307P61").exists()
