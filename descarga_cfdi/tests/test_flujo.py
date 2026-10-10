# -*- coding: utf-8 -*-
from datetime import datetime

import pytest

from conftest import ClienteFalso, cfdi_xml, zip_b64
from sat_descarga.flujo import Descargador

D, H = datetime(2026, 1, 1), datetime(2026, 2, 28)


def _paquetes():
    return {
        "PAQ-1": zip_b64({"a.xml": cfdi_xml("2026-01-10T00:00:00"), "b.xml": cfdi_xml("2026-01-20T00:00:00")}),
        "PAQ-2": zip_b64({"c.xml": cfdi_xml("2026-02-02T00:00:00"), "leeme.txt": b"ignorar"}),
    }


def test_flujo_completo_ambos_tipos(perfil, opciones, logger, no_dormir):
    cli = ClienteFalso(_paquetes(), verificaciones_en_proceso=1)
    clasificados = []
    d = Descargador(perfil, opciones, cli, logger, dormir=no_dormir, clasificar=clasificados.append)
    res = d.ejecutar(D, H, "ambos")

    assert res.errores == []
    assert res.tramos == 4                      # 2 meses x 2 tipos
    assert res.solicitudes_nuevas == 4
    # el cliente falso regresa los mismos 2 paquetes por solicitud; los XML son
    # únicos por uuid por tipo, pero repetidos entre tramos del mismo tipo -> dup
    assert res.xml_nuevos == 6                  # 3 xml x 2 tipos
    assert res.xml_duplicados == 6
    assert len(clasificados) == 6               # hook llamado por cada XML nuevo
    salida = opciones.carpeta_salida
    from pathlib import Path
    assert (Path(salida) / "202601 XAXX" / "emitidos").exists()
    assert (Path(salida) / "202602 XAXX" / "recibidos").exists()


def cfg_path(base, rfc):
    from pathlib import Path
    return Path(base) / rfc


def test_reanuda_sin_volver_a_solicitar(perfil, opciones, logger, no_dormir):
    """Simula corte: primera corrida solicita y muere en el polling; la
    segunda debe retomar el id existente sin gastar solicitud nueva."""
    cli = ClienteFalso(_paquetes(), verificaciones_en_proceso=99)   # nunca termina
    opciones.poll_max_intentos = 2
    d = Descargador(perfil, opciones, cli, logger, dormir=no_dormir)
    res = d.ejecutar(datetime(2026, 1, 1), datetime(2026, 1, 31), "emitidos")
    assert len(res.errores) == 1 and "sigue en proceso" in res.errores[0]
    assert cli.solicitudes and len(cli.solicitudes) == 1

    cli.n_proceso = 0                            # ahora el SAT ya terminó
    d2 = Descargador(perfil, opciones, cli, logger, dormir=no_dormir)
    res2 = d2.ejecutar(datetime(2026, 1, 1), datetime(2026, 1, 31), "emitidos")
    assert res2.errores == []
    assert len(cli.solicitudes) == 1             # NO volvió a solicitar
    assert res2.xml_nuevos == 3

    d3 = Descargador(perfil, opciones, cli, logger, dormir=no_dormir)   # tercera: ya completado
    res3 = d3.ejecutar(datetime(2026, 1, 1), datetime(2026, 1, 31), "emitidos")
    assert res3.solicitudes_nuevas == 0 and res3.xml_nuevos == 0


def test_sin_cfdis_5004_no_es_error(perfil, opciones, logger, no_dormir):
    cli = ClienteFalso({}, cod_solicitud="5004")
    res = Descargador(perfil, opciones, cli, logger, dormir=no_dormir).ejecutar(D, D, "recibidos")
    assert res.errores == [] and res.xml_nuevos == 0


def test_codigo_desconocido_se_reporta_como_error_sin_tronar(perfil, opciones, logger, no_dormir):
    cli = ClienteFalso({}, cod_solicitud="5001")
    res = Descargador(perfil, opciones, cli, logger, dormir=no_dormir).ejecutar(D, D, "recibidos")
    assert len(res.errores) == 1 and "cod=5001" in res.errores[0]


def test_reintenta_ante_fallas_de_red(perfil, opciones, logger, no_dormir):
    cli = ClienteFalso(_paquetes(), verificaciones_en_proceso=0)
    cli.fallas_red_pendientes = 2                # las 2 primeras llamadas truenan
    res = Descargador(perfil, opciones, cli, logger, dormir=no_dormir).ejecutar(D, D, "emitidos")
    assert res.errores == [] and res.xml_nuevos == 3


def test_respeta_tope_diario(perfil, opciones, logger, no_dormir):
    opciones.max_solicitudes_dia = 1
    cli = ClienteFalso(_paquetes(), verificaciones_en_proceso=0)
    res = Descargador(perfil, opciones, cli, logger, dormir=no_dormir).ejecutar(D, H, "emitidos")   # 2 meses
    assert len(cli.solicitudes) == 1
    assert len(res.errores) == 1 and "tope diario" in res.errores[0]


def test_estado_error_del_sat_limpia_id_para_reintentar(perfil, opciones, logger, no_dormir):
    class CliError(ClienteFalso):
        def verificar(self, rfc, id_solicitud):
            return {"cod_estatus": "5000", "estado_solicitud": "5", "numero_cfdis": "0",
                    "mensaje": "Rechazada", "paquetes": []}
    cli = CliError(_paquetes())
    d = Descargador(perfil, opciones, cli, logger, dormir=no_dormir)
    res = d.ejecutar(D, D, "emitidos")
    assert "estado 5" in res.errores[0]
    assert d.estado.obtener("emitidos", D, D.replace(hour=23, minute=59, second=59))["id_solicitud"] is None


def test_hook_clasificar_que_truena_no_detiene_descarga(perfil, opciones, logger, no_dormir):
    def hook(p):
        raise ValueError("bug del usuario")
    cli = ClienteFalso(_paquetes(), verificaciones_en_proceso=0)
    res = Descargador(perfil, opciones, cli, logger, dormir=no_dormir, clasificar=hook).ejecutar(D, D, "emitidos")
    assert res.errores == [] and res.xml_nuevos == 3


# ============================================ respuestas raras del SAT (estado=0 cod=404)
class ClienteRaro(ClienteFalso):
    """Simula lo que le pasó a Rick: el SAT contesta estado=0 cod=404 varias
    veces y luego se compone."""
    def __init__(self, paquetes, raras=3, **kw):
        super().__init__(paquetes, **kw)
        self.raras_restantes = raras
        self.raras_servidas = 0

    def verificar(self, rfc, id_solicitud):
        if self.raras_restantes > 0:
            self.raras_restantes -= 1
            self.raras_servidas += 1
            return {"cod_estatus": "404", "estado_solicitud": "0",
                    "numero_cfdis": "0", "mensaje": "", "paquetes": []}
        return super().verificar(rfc, id_solicitud)


def test_estado_no_documentado_no_rompe_y_se_recupera(perfil, opciones, logger, no_dormir):
    cli = ClienteRaro(_paquetes(), raras=5, verificaciones_en_proceso=0)
    res = Descargador(perfil, opciones, cli, logger, dormir=no_dormir).ejecutar(D, D, "emitidos")
    assert res.errores == [] and res.xml_nuevos == 3
    assert cli.raras_servidas == 5


def test_estado_raro_no_consume_el_presupuesto_de_verificaciones(perfil, opciones, logger, no_dormir):
    """Antes, un 404 gastaba un intento y agotaba los 40 sin avanzar."""
    opciones.poll_max_intentos = 3
    cli = ClienteRaro(_paquetes(), raras=6, verificaciones_en_proceso=2)
    res = Descargador(perfil, opciones, cli, logger, dormir=no_dormir).ejecutar(D, D, "emitidos")
    assert res.errores == [] and res.xml_nuevos == 3


def test_estado_raro_persistente_se_rinde_con_mensaje_claro(perfil, opciones, logger, no_dormir):
    cli = ClienteRaro(_paquetes(), raras=999)
    res = Descargador(perfil, opciones, cli, logger, dormir=no_dormir).ejecutar(D, D, "emitidos")
    assert len(res.errores) == 1
    assert "no documentadas" in res.errores[0] and "se retoma sola" in res.errores[0]


def test_tras_rendirse_conserva_el_id_para_retomar(perfil, opciones, logger, no_dormir):
    cli = ClienteRaro(_paquetes(), raras=999)
    d = Descargador(perfil, opciones, cli, logger, dormir=no_dormir)
    d.ejecutar(D, D, "emitidos")
    st = d.estado.obtener("emitidos", D, D.replace(hour=23, minute=59, second=59))
    assert st.get("id_solicitud"), "debe guardar el id para no volver a solicitar"

    cli.raras_restantes = 0                     # el SAT se compone
    d2 = Descargador(perfil, opciones, cli, logger, dormir=no_dormir)
    res = d2.ejecutar(D, D, "emitidos")
    assert res.errores == [] and res.solicitudes_nuevas == 0 and res.xml_nuevos == 3


def test_espera_crece_para_no_martillar_al_sat(perfil, opciones, logger):
    esperas = []
    cli = ClienteFalso(_paquetes(), verificaciones_en_proceso=12)
    opciones.poll_intervalo_seg = 30
    opciones.poll_max_intentos = 14
    Descargador(perfil, opciones, cli, logger, dormir=esperas.append).ejecutar(D, D, "emitidos")
    assert esperas[0] == 30                      # al principio pregunta seguido
    assert esperas[-1] > esperas[0]              # después se calma
    assert max(esperas) <= 120                   # con tope


def test_cancelar_funciona_tambien_durante_respuestas_raras(perfil, opciones, logger, no_dormir):
    cli = ClienteRaro(_paquetes(), raras=999)
    res = Descargador(perfil, opciones, cli, logger, dormir=no_dormir,
                      cancelado=lambda: True).ejecutar(D, D, "emitidos")
    assert res.tramos == 0                        # ni siquiera empezó
