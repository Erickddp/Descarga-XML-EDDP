# -*- coding: utf-8 -*-
import json
from datetime import datetime
from pathlib import Path

import pytest

from conftest import ClienteFalso, cfdi_xml, zip_b64
from sat_descarga.config import Config, Opciones, Perfil
from sat_descarga.ejecutor import ejecutar_varios, probar_efirma, resumen_global

D, H = datetime(2026, 1, 1), datetime(2026, 1, 31)


def _paq():
    return {"P1": zip_b64({"a.xml": cfdi_xml("2026-01-10T00:00:00")})}


def _perfil(tmp_path, rfc, nombre=""):
    cer = tmp_path / f"{rfc}.cer"; cer.write_bytes(b"x")
    key = tmp_path / f"{rfc}.key"; key.write_bytes(b"x")
    return Perfil(rfc=rfc, cer_path=str(cer), key_path=str(key), key_password="p", nombre=nombre)


# ---------------------------------------------------------------- config
def test_rfc_se_normaliza_a_mayusculas():
    assert Perfil(rfc=" xaxx010101000 ").rfc == "XAXX010101000"


def test_nombre_default_es_el_rfc():
    assert Perfil(rfc="XAXX010101000").nombre == "XAXX010101000"


def test_perfil_reporta_errores_utiles(tmp_path):
    e = Perfil(rfc="CORTO", cer_path="/no/existe.cer", key_path="", key_password="").errores()
    assert len(e) == 4
    assert any("RFC debe tener" in x for x in e)
    assert any("no existe el .cer" in x for x in e)


def test_guardar_y_releer_varios_rfcs(tmp_path):
    c = Config(ruta=str(tmp_path / "config.json"))
    c.agregar(_perfil(tmp_path, "AAA010101AAA", "Cliente A"))
    c.agregar(_perfil(tmp_path, "BBB020202BBB", "Cliente B"))
    c.guardar()
    c2 = Config.desde_archivo(str(tmp_path / "config.json"))
    assert [p.nombre for p in c2.perfiles] == ["Cliente A", "Cliente B"]
    assert c2.por_rfc("bbb020202bbb").rfc == "BBB020202BBB"


def test_agregar_mismo_rfc_conserva_ambos(tmp_path):
    """Antes esto BORRABA el perfil anterior. Ahora conviven."""
    c = Config()
    c.agregar(_perfil(tmp_path, "AAA010101AAA", "viejo"))
    c.agregar(_perfil(tmp_path, "AAA010101AAA", "nuevo"))
    assert [p.nombre for p in c.perfiles] == ["viejo", "nuevo"]


def test_eliminar(tmp_path):
    c = Config(perfiles=[_perfil(tmp_path, "AAA010101AAA")])
    assert c.eliminar("AAA010101AAA") is True
    assert c.perfiles == [] and c.eliminar("AAA010101AAA") is False


def test_activos_filtra(tmp_path):
    a = _perfil(tmp_path, "AAA010101AAA"); b = _perfil(tmp_path, "BBB020202BBB"); b.activo = False
    assert [p.rfc for p in Config(perfiles=[a, b]).activos()] == ["AAA010101AAA"]


def test_cada_rfc_tiene_archivos_de_estado_separados(tmp_path):
    op = Opciones(archivo_estado="estado.json", archivo_contador="cont.json")
    a, b = _perfil(tmp_path, "AAA010101AAA"), _perfil(tmp_path, "BBB020202BBB")
    assert a.archivo_estado(op) != b.archivo_estado(op)
    assert "AAA0" in Path(a.archivo_estado(op)).name and a.id in Path(a.archivo_estado(op)).name
    assert "BBB0" in Path(b.archivo_contador(op)).name


def test_lee_formato_viejo_de_un_solo_rfc(tmp_path):
    viejo = {"rfc": "XAXX010101000", "cer_path": "a.cer", "key_path": "a.key",
             "key_password": "p", "carpeta_salida": "salida", "max_solicitudes_dia": 7}
    ruta = tmp_path / "config.json"; ruta.write_text(json.dumps(viejo))
    c = Config.desde_archivo(str(ruta))
    assert len(c.perfiles) == 1 and c.perfiles[0].rfc == "XAXX010101000"
    assert c.opciones.max_solicitudes_dia == 7


def test_config_inexistente_no_truena(tmp_path):
    c = Config.desde_archivo(str(tmp_path / "no_existe.json"))
    assert c.perfiles == []


# ---------------------------------------------------------------- ejecutor
def test_varios_rfcs_se_descargan_en_secuencia(tmp_path, opciones, logger, no_dormir):
    perfiles = [_perfil(tmp_path, "AAA010101AAA", "A"), _perfil(tmp_path, "BBB020202BBB", "B")]
    cfg = Config(opciones=opciones, perfiles=perfiles)
    clientes = {}

    def fabrica(p):
        clientes[p.rfc] = ClienteFalso(_paq(), verificaciones_en_proceso=0)
        return clientes[p.rfc]

    res = ejecutar_varios(perfiles, cfg, D, H, "emitidos", logger,
                          dormir=no_dormir, fabrica_cliente=fabrica)
    assert len(res) == 2
    assert all(r.errores == [] and r.xml_nuevos == 1 for r in res)
    assert [r.rfc for r in res] == ["AAA010101AAA", "BBB020202BBB"]
    from pathlib import Path
    assert (Path(opciones.carpeta_salida) / "202601 AAA0").exists()
    assert (Path(opciones.carpeta_salida) / "202601 BBB0").exists()


def test_un_rfc_roto_no_detiene_a_los_demas(tmp_path, opciones, logger, no_dormir):
    bueno = _perfil(tmp_path, "AAA010101AAA", "Bueno")
    roto = Perfil(rfc="BBB020202BBB", cer_path="/no/existe.cer", key_path="/no/existe.key",
                  key_password="", nombre="Roto")
    cfg = Config(opciones=opciones, perfiles=[roto, bueno])
    res = ejecutar_varios([roto, bueno], cfg, D, H, "emitidos", logger, dormir=no_dormir,
                          fabrica_cliente=lambda p: ClienteFalso(_paq(), verificaciones_en_proceso=0))
    assert res[0].errores and res[0].xml_nuevos == 0
    assert res[1].errores == [] and res[1].xml_nuevos == 1


def test_efirma_que_no_abre_se_reporta_sin_tronar(tmp_path, opciones, logger, no_dormir):
    p = _perfil(tmp_path, "AAA010101AAA")
    cfg = Config(opciones=opciones, perfiles=[p])

    def fabrica(_p):
        raise ValueError("contraseña incorrecta")

    res = ejecutar_varios([p], cfg, D, H, "emitidos", logger, dormir=no_dormir, fabrica_cliente=fabrica)
    assert len(res[0].errores) == 1 and "e.firma" in res[0].errores[0]


def test_cancelar_detiene_antes_del_siguiente_rfc(tmp_path, opciones, logger, no_dormir):
    perfiles = [_perfil(tmp_path, "AAA010101AAA"), _perfil(tmp_path, "BBB020202BBB")]
    cfg = Config(opciones=opciones, perfiles=perfiles)
    bandera = {"cancelar": False}
    res = ejecutar_varios(
        perfiles, cfg, D, H, "emitidos", logger,
        cancelado=lambda: bandera["cancelar"],
        al_terminar_perfil=lambda r: bandera.__setitem__("cancelar", True),  # cancela tras el 1ro
        dormir=no_dormir,
        fabrica_cliente=lambda p: ClienteFalso(_paq(), verificaciones_en_proceso=0))
    assert res[0].xml_nuevos == 1                      # el primero sí bajó
    assert len(res) == 1 or res[1].tramos == 0         # el segundo no trabajó


def test_callback_por_rfc_se_llama(tmp_path, opciones, logger, no_dormir):
    perfiles = [_perfil(tmp_path, "AAA010101AAA"), _perfil(tmp_path, "BBB020202BBB")]
    cfg = Config(opciones=opciones, perfiles=perfiles)
    vistos = []
    ejecutar_varios(perfiles, cfg, D, H, "emitidos", logger, dormir=no_dormir,
                    al_terminar_perfil=lambda r: vistos.append(r.rfc),
                    fabrica_cliente=lambda p: ClienteFalso(_paq(), verificaciones_en_proceso=0))
    assert vistos == ["AAA010101AAA", "BBB020202BBB"]


def test_probar_efirma_ok_y_fallo(tmp_path, logger):
    p = _perfil(tmp_path, "AAA010101AAA")
    ok, msg = probar_efirma(p, logger, fabrica_cliente=lambda _p: ClienteFalsoToken())
    assert ok and "OK" in msg
    malo = Perfil(rfc="X", cer_path="", key_path="", key_password="")
    ok2, msg2 = probar_efirma(malo, logger)
    assert not ok2 and "RFC" in msg2


class ClienteFalsoToken:
    def token(self):
        return "T" * 42


def test_resumen_global_suma_todo(tmp_path, opciones, logger, no_dormir):
    perfiles = [_perfil(tmp_path, "AAA010101AAA"), _perfil(tmp_path, "BBB020202BBB")]
    cfg = Config(opciones=opciones, perfiles=perfiles)
    res = ejecutar_varios(perfiles, cfg, D, H, "emitidos", logger, dormir=no_dormir,
                          fabrica_cliente=lambda p: ClienteFalso(_paq(), verificaciones_en_proceso=0))
    t = resumen_global(res)
    assert "2 XML nuevos" in t and "2 RFC(s)" in t
