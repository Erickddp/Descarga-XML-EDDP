# -*- coding: utf-8 -*-
"""Lee datos del certificado (.cer) de la e.firma.

Sirve para que el RFC lo ponga el certificado y no el dedo del usuario: así no
se puede dar de alta un RFC con el certificado de otro.
"""
import re
from pathlib import Path
from typing import Optional, Tuple

# Ojo: NO usar \b — el guion bajo cuenta como caracter de palabra y los archivos
# del SAT se llaman "Claveprivada_FIEL_FODA920130KD4_2026...", lo que rompía la
# detección. Se delimita explícitamente con separadores o inicio/fin.
_SEP = r"(?:^|[^A-Z0-9ÑÑ&])"
RE_RFC = re.compile(r"(?:^|[^A-Z0-9Ñ&])([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})(?![A-Z0-9])")


def _valores_del_sujeto(cer_der: bytes):
    """Todos los valores del subject, sin importar la librería disponible."""
    try:
        from cryptography import x509
        cert = x509.load_der_x509_certificate(cer_der)
        return [str(a.value) for a in cert.subject]
    except Exception:  # noqa: BLE001
        from OpenSSL import crypto
        cert = crypto.load_certificate(crypto.FILETYPE_ASN1, cer_der)
        return [v.decode("utf-8", "ignore") for _k, v in cert.get_subject().get_components()]


def datos_del_cer(ruta_cer: str) -> Tuple[Optional[str], Optional[str]]:
    """(rfc, nombre_del_titular). Cualquiera de los dos puede venir None."""
    cer_der = Path(ruta_cer).read_bytes()
    valores = _valores_del_sujeto(cer_der)
    rfc = None
    for v in valores:
        m = RE_RFC.search(v.upper().strip())
        if m:
            rfc = m.group(1)
            break
    nombre = None
    for v in valores:
        limpio = v.strip()
        # el nombre es el valor largo que NO es puro RFC/CURP
        if limpio and len(limpio) > 3 and " " in limpio and not RE_RFC.search(limpio.upper()):
            nombre = limpio
            break
    return rfc, nombre


def rfc_de_nombre_archivo(ruta: str) -> Optional[str]:
    """Respaldo: saca el RFC del nombre del archivo (los del SAT lo traen)."""
    m = RE_RFC.search(Path(ruta).stem.upper())
    return m.group(1) if m else None
