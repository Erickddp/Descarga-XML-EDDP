# -*- coding: utf-8 -*-
"""Guardado de XML en carpetas planas (sin base de datos).

Estructura:
  {carpeta_salida}/{AAAAMM} {4 primeras del RFC}/{emitidos|recibidos}/{uuid}.xml

Ejemplo:  descargas_cfdi/202608 HIHR/emitidos/ABC...xml
"""
import base64
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from lxml import etree

NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"
RE_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


@dataclass
class DatosCFDI:
    uuid: str
    anio: str
    mes: str


def extraer_datos(xml_bytes: bytes, nombre_archivo: str = "") -> DatosCFDI:
    """Saca UUID (TimbreFiscalDigital) y año/mes (Comprobante@Fecha)."""
    uuid = None
    anio = mes = None
    try:
        root = etree.fromstring(xml_bytes)
        tfd = root.find(f".//{{{NS_TFD}}}TimbreFiscalDigital")
        if tfd is not None:
            uuid = tfd.get("UUID")
        fecha = root.get("Fecha")  # 2026-03-15T10:22:01
        if fecha and len(fecha) >= 7:
            anio, mes = fecha[0:4], fecha[5:7]
    except etree.XMLSyntaxError:
        pass

    if not uuid:
        m = RE_UUID.search(nombre_archivo) or RE_UUID.search(xml_bytes.decode("utf-8", "ignore"))
        uuid = m.group(0) if m else Path(nombre_archivo).stem or "SIN_UUID"
    if not anio:
        anio, mes = "sin_fecha", "00"
    return DatosCFDI(uuid=uuid.upper(), anio=anio, mes=mes)


def iterar_xml_de_zip(paquete_b64: str) -> Iterator[Tuple[str, bytes]]:
    """Decodifica el paquete base64 del SAT y regresa solo los .xml."""
    raw = base64.b64decode(paquete_b64)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if not info.filename.lower().endswith(".xml"):
                continue
            yield info.filename, zf.read(info)


class Almacen:
    def __init__(self, carpeta_salida: str, rfc: str):
        self.base = Path(carpeta_salida)
        self.rfc = (rfc or "").upper()
        self.clave = (self.rfc[:4] or "XXXX")

    def carpeta_periodo(self, datos: DatosCFDI) -> Path:
        """202608 HIHR"""
        periodo = "sin_fecha" if datos.anio == "sin_fecha" else f"{datos.anio}{datos.mes}"
        return self.base / f"{periodo} {self.clave}"

    def ruta_para(self, datos: DatosCFDI, tipo: str) -> Path:
        return self.carpeta_periodo(datos) / tipo / f"{datos.uuid}.xml"

    def guardar(self, xml_bytes: bytes, tipo: str, nombre_archivo: str = "") -> Tuple[Path, bool]:
        """Guarda el XML. Regresa (ruta, es_nuevo). No sobreescribe."""
        datos = extraer_datos(xml_bytes, nombre_archivo)
        ruta = self.ruta_para(datos, tipo)
        if ruta.exists():
            return ruta, False
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(xml_bytes)
        return ruta, True

    def guardar_paquete(self, paquete_b64: str, tipo: str) -> Tuple[List[Path], int]:
        """Guarda todos los XML del paquete. Regresa (rutas_nuevas, duplicados)."""
        nuevos: List[Path] = []
        dup = 0
        for nombre, contenido in iterar_xml_de_zip(paquete_b64):
            ruta, es_nuevo = self.guardar(contenido, tipo, nombre)
            if es_nuevo:
                nuevos.append(ruta)
            else:
                dup += 1
        return nuevos, dup


# ---------------------------------------------------------------- migración
def migrar_estructura_vieja(carpeta_salida: str) -> int:
    """Mueve descargas del formato viejo ({RFC}/{año}/{mes}/{tipo}) al nuevo
    ({AAAAMM} {RFC4}/{tipo}). Es idempotente: si no hay nada viejo, no hace nada.
    Regresa cuántos archivos movió."""
    base = Path(carpeta_salida)
    if not base.exists():
        return 0
    movidos = 0
    for dir_rfc in [d for d in base.iterdir() if d.is_dir()]:
        rfc = dir_rfc.name.upper()
        if len(rfc) not in (12, 13) or " " in rfc:
            continue                                   # ya es carpeta nueva
        for dir_anio in [d for d in dir_rfc.iterdir() if d.is_dir()]:
            for dir_mes in [d for d in dir_anio.iterdir() if d.is_dir()]:
                for dir_tipo in [d for d in dir_mes.iterdir() if d.is_dir()]:
                    if dir_anio.name == "sin_fecha":
                        periodo = "sin_fecha"
                    else:
                        periodo = f"{dir_anio.name}{dir_mes.name}"
                    destino = base / f"{periodo} {rfc[:4]}" / dir_tipo.name
                    destino.mkdir(parents=True, exist_ok=True)
                    for x in dir_tipo.glob("*.xml"):
                        final = destino / x.name
                        if final.exists():
                            x.unlink()
                        else:
                            x.replace(final)
                        movidos += 1
        # limpiar carpetas vacías que quedaron
        for d in sorted(dir_rfc.rglob("*"), key=lambda q: len(q.parts), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        if not any(dir_rfc.iterdir()):
            dir_rfc.rmdir()
    return movidos
