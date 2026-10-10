# -*- coding: utf-8 -*-
"""Genera una e.firma sintética en el MISMO formato que entrega el SAT
(.cer DER, .key PKCS#8 DER cifrada con contraseña) y comprueba que:
  1. cargar_fiel la abre con la contraseña correcta y falla con la incorrecta
  2. El sobre SOAP de Autenticación se firma con XMLDSig válido (sin red)
  3. El CLI valida argumentos
"""
import base64
import shutil
import subprocess
from pathlib import Path

import pytest
from lxml import etree

import descargar
from sat_descarga.cliente import ClienteSAT, cargar_fiel

PASS = "Secreta123"


@pytest.fixture(scope="module")
def efirma(tmp_path_factory):
    from conftest import openssl
    d = tmp_path_factory.mktemp("efirma")
    key_pem, cer_pem = d / "k.pem", d / "c.pem"
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key_pem,
            "-out", cer_pem, "-days", "1", "-subj", "/CN=PRUEBA/serialNumber=XAXX010101000")
    cer_der, key_der = d / "prueba.cer", d / "prueba.key"
    openssl("x509", "-in", cer_pem, "-outform", "DER", "-out", cer_der)
    # Igual que el SAT: PKCS#8 DER cifrada (v2 des3 es el clásico del SAT)
    openssl("pkcs8", "-topk8", "-inform", "PEM", "-outform", "DER", "-in", key_pem,
            "-out", key_der, "-v2", "des3", "-passout", f"pass:{PASS}")
    return cer_der, key_der


def test_fiel_carga_y_extrae_serial(efirma):
    cer, key = efirma
    f = cargar_fiel(str(cer), str(key), PASS)
    assert f.cer_serial_number().isdigit()
    assert b"MII" in f.cer_to_base64()[:3]


def test_fiel_password_incorrecta_falla(efirma):
    cer, key = efirma
    with pytest.raises(Exception):
        cargar_fiel(str(cer), str(key), "mala")


def test_token_soap_se_firma_con_xmldsig_valido(efirma, monkeypatch):
    """Intercepta requests.post: valida que el XML enviado tiene firma RSA-SHA1
    correcta sobre SignedInfo, y regresa un token falso. Prueba TODO el
    pipeline criptográfico sin tocar al SAT."""
    cer, key = efirma
    fiel = cargar_fiel(str(cer), str(key), PASS)
    capturado = {}

    class Resp:
        status_code = 200
        headers = {}
        text = ('<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
                '<AutenticaResponse xmlns="http://DescargaMasivaTerceros.gob.mx">'
                '<AutenticaResult>TOKEN-FALSO-123</AutenticaResult></AutenticaResponse></s:Body></s:Envelope>')

    def post(url, data, headers, verify, timeout):
        capturado.update(url=url, data=data, headers=headers)
        return Resp()

    import cfdiclient.webservicerequest as wsr
    monkeypatch.setattr(wsr.requests, "post", post)

    tok = ClienteSAT(fiel).token()
    assert tok == "TOKEN-FALSO-123"
    assert "Autenticacion.svc" in capturado["url"]
    assert capturado["headers"]["SOAPAction"].endswith("IAutenticacion/Autentica")

    # --- verificar la firma criptográficamente ---
    from Crypto.Hash import SHA
    from Crypto.PublicKey import RSA
    from Crypto.Signature import PKCS1_v1_5
    from OpenSSL import crypto

    root = etree.fromstring(capturado["data"])
    ns = {"s": "http://schemas.xmlsoap.org/soap/envelope/",
          "o": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd",
          "u": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd",
          "ds": "http://www.w3.org/2000/09/xmldsig#"}
    signed_info = root.find("s:Header/o:Security/ds:Signature/ds:SignedInfo", ns)
    sig_val = root.find("s:Header/o:Security/ds:Signature/ds:SignatureValue", ns).text
    bst = root.find("s:Header/o:Security/o:BinarySecurityToken", ns).text
    assert signed_info is not None and sig_val and bst

    pub = crypto.load_certificate(crypto.FILETYPE_ASN1, base64.b64decode(bst))
    pub_pem = crypto.dump_publickey(crypto.FILETYPE_PEM, pub.get_pubkey())
    verifier = PKCS1_v1_5.new(RSA.importKey(pub_pem))
    si_bytes = etree.tostring(signed_info, method="c14n", exclusive=True)
    assert verifier.verify(SHA.new(si_bytes), base64.b64decode(sig_val)), "firma XMLDSig inválida"


def test_token_se_reutiliza_dentro_de_4_min(efirma, monkeypatch):
    cer, key = efirma
    cli = ClienteSAT(cargar_fiel(str(cer), str(key), PASS))
    llamadas = {"n": 0}

    def fake_token(self):
        llamadas["n"] += 1
        return "T"
    import cfdiclient.autenticacion as au
    monkeypatch.setattr(au.Autenticacion, "obtener_token", fake_token)
    assert cli.token() == "T" and cli.token() == "T"
    assert llamadas["n"] == 1


# ---------------------------------------------------------------- CLI
def test_cli_parsea_bien():
    a = descargar.parsear_args(["--desde", "2026-01-01", "--hasta", "2026-09-05", "--tipo", "ambos"])
    assert a.desde_dt.year == 2026 and a.tipo == "ambos"


@pytest.mark.parametrize("argv", [
    ["--desde", "2026-01-01"],                               # falta hasta
    ["--desde", "01/01/2026", "--hasta", "2026-09-05"],      # formato malo
    ["--desde", "2026-09-05", "--hasta", "2026-01-01"],      # invertido
    ["--desde", "2026-01-01", "--hasta", "2026-09-05", "--tipo", "todos"],
])
def test_cli_rechaza_argumentos_malos(argv):
    with pytest.raises(SystemExit):
        descargar.parsear_args(argv)


def test_cli_sin_config_regresa_2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert descargar.main(["--probar-fiel"]) == 2
