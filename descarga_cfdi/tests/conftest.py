# -*- coding: utf-8 -*-
import base64
import io
import sys
import uuid as uuidlib
import zipfile
from pathlib import Path

import os
import tempfile

import pytest

# Las pruebas NUNCA escriben en la carpeta real de datos ni en la del programa.
os.environ["DESCARGA_XML_EDDP_DATOS"] = tempfile.mkdtemp(prefix="dxe_test_")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sat_descarga.config import Config, Opciones, Perfil  # noqa: E402


def _tk_con_reintento():
    """En Windows, crear Tk() muchas veces seguidas a veces falla al leer
    init.tcl/tk.tcl ("Can't find a usable ..." / "tcl_findLibrary": el archivo
    está ocupado un instante). Pasaba desde antes de estos cambios; en pruebas se reintenta."""
    try:
        import tkinter
    except ImportError:
        return
    original = tkinter.Tk.__init__

    def init(self, *a, **k):
        import time
        for intento in range(6):
            try:
                return original(self, *a, **k)
            except tkinter.TclError as e:
                if not any(x in str(e) for x in ("usable", "tcl_findLibrary")) or intento == 5:
                    raise
                time.sleep(0.25)
    tkinter.Tk.__init__ = init


_tk_con_reintento()


# ---------------------------------------------------------------- utilerías portables
def texto_pdf(ruta) -> str:
    """Texto plano de un PDF. Usa pypdf (va en requirements); si no está, cae a
    pdftotext (Linux/Git for Windows). Sin ninguno de los dos, la prueba se salta."""
    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = None
    if PdfReader is not None:
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(ruta)).pages)
    import shutil
    import subprocess
    if not shutil.which("pdftotext"):
        pytest.skip("sin pypdf ni pdftotext para leer el PDF")
    return subprocess.run(["pdftotext", "-layout", str(ruta), "-"],
                          capture_output=True, text=True).stdout


def openssl(*args) -> None:
    """Corre openssl o salta la prueba limpio si no está o falla (p. ej. un openssl
    de MSYS que convierte '/CN=...' en ruta de Windows)."""
    import shutil
    import subprocess
    if not shutil.which("openssl"):
        pytest.skip("openssl no disponible")
    env = dict(os.environ, MSYS_NO_PATHCONV="1", MSYS2_ARG_CONV_EXCL="*")
    try:
        subprocess.run(["openssl", *map(str, args)], check=True, capture_output=True, env=env)
    except (OSError, subprocess.CalledProcessError) as e:
        pytest.skip(f"openssl no funcionó: {e}")


def cfdi_xml(fecha="2026-03-15T10:22:01", uuid=None) -> bytes:
    uuid = uuid or str(uuidlib.uuid4()).upper()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
  Version="4.0" Fecha="{fecha}" Total="116.00" TipoDeComprobante="I">
  <cfdi:Emisor Rfc="AAA010101AAA" Nombre="EMISOR" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="XAXX010101000" Nombre="RECEPTOR" UsoCFDI="G03" DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="612"/>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid}" FechaTimbrado="{fecha}"/>
  </cfdi:Complemento>
</cfdi:Comprobante>""".encode("utf-8")


def zip_b64(archivos: dict) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for nombre, contenido in archivos.items():
            zf.writestr(nombre, contenido)
    return base64.b64encode(buf.getvalue()).decode()


class ClienteFalso:
    """Simula el SAT: acepta, tarda N verificaciones en 'EnProceso', y entrega paquetes."""

    def __init__(self, paquetes: dict, verificaciones_en_proceso=2, cod_solicitud="5000"):
        self.paquetes = paquetes                  # id_paquete -> zip base64
        self.n_proceso = verificaciones_en_proceso
        self.cod_solicitud = cod_solicitud
        self.solicitudes = []
        self.verificaciones = 0
        self.descargas = []
        self.fallas_red_pendientes = 0            # para probar reintentos
        self._contador_id = 0

    def solicitar(self, rfc, tipo, desde, hasta):
        self._fallar_si_toca()
        self._contador_id += 1
        self.solicitudes.append((rfc, tipo, desde, hasta))
        if self.cod_solicitud != "5000":
            return {"id_solicitud": None, "cod_estatus": self.cod_solicitud, "mensaje": "simulado"}
        return {"id_solicitud": f"SOL-{self._contador_id}", "cod_estatus": "5000", "mensaje": "Solicitud Aceptada"}

    def verificar(self, rfc, id_solicitud):
        self._fallar_si_toca()
        self.verificaciones += 1
        if self.verificaciones <= self.n_proceso:
            return {"cod_estatus": "5000", "estado_solicitud": "2", "numero_cfdis": "0", "mensaje": "", "paquetes": []}
        return {"cod_estatus": "5000", "estado_solicitud": "3", "numero_cfdis": "3", "mensaje": "",
                "paquetes": list(self.paquetes.keys())}

    def descargar_paquete(self, rfc, id_paquete):
        self._fallar_si_toca()
        self.descargas.append(id_paquete)
        return {"cod_estatus": "5000", "mensaje": "", "paquete_b64": self.paquetes[id_paquete]}

    def _fallar_si_toca(self):
        if self.fallas_red_pendientes > 0:
            self.fallas_red_pendientes -= 1
            raise ConnectionError("red caída (simulado)")


@pytest.fixture
def perfil(tmp_path) -> Perfil:
    cer = tmp_path / "a.cer"; cer.write_bytes(b"x")
    key = tmp_path / "a.key"; key.write_bytes(b"x")
    return Perfil(rfc="XAXX010101000", cer_path=str(cer), key_path=str(key),
                  key_password="p", nombre="Prueba")


@pytest.fixture
def opciones(tmp_path) -> Opciones:
    return Opciones(
        carpeta_salida=str(tmp_path / "salida"),
        poll_intervalo_seg=0, poll_max_intentos=5, reintentos=3, backoff_base_seg=0,
        archivo_estado=str(tmp_path / "estado.json"),
        archivo_contador=str(tmp_path / "contador.json"),
        archivo_log=str(tmp_path / "log.txt"),
    )


@pytest.fixture
def cfg(opciones, perfil) -> Config:
    return Config(opciones=opciones, perfiles=[perfil])


@pytest.fixture
def logger(tmp_path):
    import logging
    lg = logging.getLogger(f"test-{tmp_path.name}")
    lg.setLevel(logging.DEBUG)
    lg.addHandler(logging.NullHandler())
    return lg


@pytest.fixture
def no_dormir():
    return lambda s: None


@pytest.fixture(autouse=True)
def _recolectar_basura_de_tk():
    """Recolecta en el hilo PRINCIPAL lo que dejó cada prueba (ventanas Tk ya
    destruidas). Si no, el recolector puede correr dentro del hilo de otra
    prueba, tocar Tk desde ahí y bloquearse (igual que la regla de la app:
    gc.collect() antes de lanzar hilos)."""
    yield
    import gc
    gc.collect()
