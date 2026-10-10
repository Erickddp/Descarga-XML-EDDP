# -*- coding: utf-8 -*-
"""Envoltura delgada sobre cfdiclient.

Todo lo que toca al SAT vive aquí. El flujo (flujo.py) solo habla con esta
interfaz, así las pruebas inyectan un cliente falso y el código real queda
intacto.
"""
import time
from datetime import datetime
from typing import Dict, Optional

from cfdiclient import (
    Autenticacion,
    DescargaMasiva,
    Fiel,
    SolicitaDescargaEmitidos,
    SolicitaDescargaRecibidos,
    VerificaSolicitudDescarga,
)


def cargar_fiel(cer_path: str, key_path: str, password: str) -> Fiel:
    """Carga .cer y .key (formato DER tal como los entrega el SAT)."""
    with open(cer_path, "rb") as f:
        cer_der = f.read()
    with open(key_path, "rb") as f:
        key_der = f.read()
    return Fiel(cer_der, key_der, password)


class ClienteSAT:
    """Implementación real contra el servicio web del SAT."""

    def __init__(self, fiel: Fiel, timeout: int = 30):
        self.fiel = fiel
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_ts: Optional[float] = None

    # --- token -----------------------------------------------------------
    def token(self) -> str:
        """Token válido ~5 min. Renovamos si tiene más de 4 min."""
        if self._token and self._token_ts:
            if time.monotonic() - self._token_ts < 240:
                return self._token
        auth = Autenticacion(self.fiel, timeout=self.timeout)
        self._token = auth.obtener_token()
        self._token_ts = time.monotonic()
        return self._token

    # --- operaciones -----------------------------------------------------
    def solicitar(self, rfc: str, tipo: str, desde: datetime, hasta: datetime) -> Dict:
        """tipo: 'emitidos' | 'recibidos'. Devuelve dict con id_solicitud, cod_estatus, mensaje."""
        if tipo == "emitidos":
            svc = SolicitaDescargaEmitidos(self.fiel, timeout=self.timeout)
            return svc.solicitar_descarga(
                self.token(), rfc, desde, hasta, rfc_emisor=rfc, tipo_solicitud="CFDI"
            )
        if tipo == "recibidos":
            svc = SolicitaDescargaRecibidos(self.fiel, timeout=self.timeout)
            return svc.solicitar_descarga(
                self.token(), rfc, desde, hasta, rfc_receptor=rfc, tipo_solicitud="CFDI"
            )
        raise ValueError(f"tipo inválido: {tipo}")

    def verificar(self, rfc: str, id_solicitud: str) -> Dict:
        svc = VerificaSolicitudDescarga(self.fiel, timeout=self.timeout)
        return svc.verificar_descarga(self.token(), rfc, id_solicitud)

    def descargar_paquete(self, rfc: str, id_paquete: str) -> Dict:
        svc = DescargaMasiva(self.fiel, timeout=self.timeout)
        return svc.descargar_paquete(self.token(), rfc, id_paquete)
