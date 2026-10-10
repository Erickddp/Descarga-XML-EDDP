# -*- coding: utf-8 -*-
"""Configuración: varios perfiles (uno por RFC) en un solo archivo.

Formato de config.json:
{
  "opciones": { ...globales... },
  "perfiles": [
     {"nombre":"EDDP", "rfc":"...", "cer_path":"...", "key_path":"...", "key_password":"...", "activo": true},
     ...
  ]
}

Compatibilidad: si el archivo trae el formato viejo (un solo RFC en la raíz),
se convierte solo a un perfil.
"""
import json
import os
import uuid as _uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


def _nuevo_id() -> str:
    return _uuid.uuid4().hex[:8]


NOMBRE_APP = "DESCARGA XML EDDP"
ENV_DATOS = "DESCARGA_XML_EDDP_DATOS"      # override (pruebas / instalaciones portátiles)


def carpeta_programa() -> Path:
    """Donde vive el código (o el .exe). NO se guardan datos aquí."""
    import sys
    if getattr(sys, "frozen", False):             # compilado con PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _es_windows() -> bool:
    import os
    return os.name == "nt"


def carpeta_datos() -> Path:
    """Carpeta fija del usuario para TODO lo que se guarda: config (RFCs, rutas,
    contraseñas), historial de solicitudes, índice, memoria de pagos, config del
    PDF, logos y log. Sobrevive a mover la app, actualizarla o compilarla.

    Windows: %APPDATA%\\DESCARGA XML EDDP     Otros: ~/.descarga_xml_eddp
    """
    import os
    forzada = os.environ.get(ENV_DATOS)
    if forzada:
        d = Path(forzada)
    elif _es_windows() and os.environ.get("APPDATA"):
        d = Path(os.environ["APPDATA"]) / NOMBRE_APP
    else:
        d = Path.home() / ".descarga_xml_eddp"
    d.mkdir(parents=True, exist_ok=True)
    return d


# compatibilidad con código anterior
def carpeta_app() -> Path:
    return carpeta_datos()


def migrar_datos_viejos() -> list:
    """Si existen datos en la carpeta del programa (versiones anteriores),
    los copia UNA vez a la carpeta de datos del usuario. Nunca sobreescribe."""
    import shutil
    origen, destino = carpeta_programa(), carpeta_datos()
    if origen.resolve() == destino.resolve():
        return []
    copiados = []
    patrones = ["config.json", "indice_xml.csv", "estado_solicitudes_*.json",
                "contador_solicitudes_*.json", "pdf_config.json", "memoria_pagos.csv"]
    for patron in patrones:
        for f in origen.glob(patron):
            final = destino / f.name
            if not final.exists():
                shutil.copy2(f, final)
                copiados.append(f.name)
    return copiados


def ruta_config_default() -> str:
    return str(carpeta_datos() / "config.json")


def en_datos(nombre: str) -> str:
    """Rutas relativas (log.txt, etc.) se resuelven dentro de la carpeta de datos."""
    q = Path(nombre)
    return str(q if q.is_absolute() else carpeta_datos() / q)


@dataclass
class Opciones:
    carpeta_salida: str = "descargas_cfdi"
    max_solicitudes_dia: int = 200
    poll_intervalo_seg: int = 30
    poll_max_intentos: int = 40
    reintentos: int = 4
    backoff_base_seg: float = 3.0
    dividir_por_mes: bool = True
    archivo_estado: str = "estado_solicitudes.json"
    archivo_contador: str = "contador_solicitudes.json"
    archivo_log: str = "log.txt"
    zoom: float = 1.0
    ultima_carpeta_pdf: str = ""
    columnas_copiado: list = field(default_factory=list)   # vacío = formato EDDP
    # memoria de la última sesión (para que al abrir ya sepa dónde están los XML)
    ultima_carpeta_datos: str = ""
    ultimo_desde: str = ""
    ultimo_hasta: str = ""
    ultimo_tipo: str = "ambos"
    tema: str = "claro"


@dataclass
class Perfil:
    """Un RFC con su e.firma."""
    rfc: str = ""
    cer_path: str = ""
    key_path: str = ""
    key_password: str = ""
    nombre: str = ""
    activo: bool = True
    id: str = ""

    def __post_init__(self):
        self.rfc = (self.rfc or "").strip().upper()
        if not self.nombre:
            self.nombre = self.rfc
        if not self.id:
            self.id = _nuevo_id()

    @property
    def clave_carpeta(self) -> str:
        """Primeras 4 letras del RFC, para nombrar carpetas."""
        return (self.rfc[:4] or "XXXX").upper()

    def errores(self) -> List[str]:
        e = []
        if len(self.rfc) not in (12, 13):
            e.append("RFC debe tener 12 (moral) o 13 (fisica) caracteres")
        if not self.cer_path or not os.path.exists(self.cer_path):
            e.append("no existe el .cer: " + (self.cer_path or "(vacio)"))
        if not self.key_path or not os.path.exists(self.key_path):
            e.append("no existe el .key: " + (self.key_path or "(vacio)"))
        if not self.key_password:
            e.append("falta la contrasena de la llave")
        return e

    def valido(self) -> bool:
        return not self.errores()

    def archivo_estado(self, op: "Opciones") -> str:
        # por id, no por RFC: dos perfiles del mismo RFC no se pisan
        return str(carpeta_app() / _sufijo(op.archivo_estado, f"{self.clave_carpeta}_{self.id}"))

    def archivo_contador(self, op: "Opciones") -> str:
        return str(carpeta_app() / _sufijo(op.archivo_contador, f"{self.clave_carpeta}_{self.id}"))


def _sufijo(ruta: str, rfc: str) -> str:
    p = Path(ruta)
    return str(p.with_name("{}_{}{}".format(p.stem, rfc, p.suffix)))


@dataclass
class Config:
    opciones: Opciones = field(default_factory=Opciones)
    perfiles: List[Perfil] = field(default_factory=list)
    ruta: str = ""

    def __post_init__(self):
        if not self.ruta:
            self.ruta = ruta_config_default()

    @classmethod
    def desde_archivo(cls, ruta: str = None) -> "Config":
        ruta = ruta or ruta_config_default()
        p = Path(ruta)
        if not p.exists():
            return cls(ruta=str(p))
        datos = json.loads(p.read_text(encoding="utf-8"))
        return cls.desde_dict(datos, str(p))

    @classmethod
    def desde_dict(cls, datos: Dict, ruta: str = None) -> "Config":
        ruta = ruta or ruta_config_default()
        if "perfiles" in datos:
            op = Opciones(**datos.get("opciones", {}))
            perfiles = [Perfil(**x) for x in datos["perfiles"]]
        else:
            campos_op = {k: v for k, v in datos.items() if k in Opciones.__annotations__}
            op = Opciones(**campos_op)
            campos_p = {k: v for k, v in datos.items() if k in Perfil.__annotations__}
            perfiles = [Perfil(**campos_p)] if campos_p.get("rfc") else []
        return cls(opciones=op, perfiles=perfiles, ruta=ruta)

    def a_dict(self) -> Dict:
        return {"opciones": asdict(self.opciones), "perfiles": [asdict(p) for p in self.perfiles]}

    def guardar(self, ruta: str = None) -> str:
        destino = Path(ruta or self.ruta)
        destino.write_text(json.dumps(self.a_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(destino, 0o600)
        except OSError:
            pass
        return str(destino)

    def activos(self) -> List[Perfil]:
        return [p for p in self.perfiles if p.activo]

    def por_rfc(self, rfc: str) -> Optional[Perfil]:
        rfc = (rfc or "").strip().upper()
        return next((p for p in self.perfiles if p.rfc == rfc), None)

    def por_id(self, pid: str) -> Optional[Perfil]:
        return next((p for p in self.perfiles if p.id == pid), None)

    def agregar(self, perfil: Perfil) -> None:
        """Agrega SIEMPRE un perfil nuevo. Solo reemplaza si trae el mismo id
        (o sea, es una edición). Nunca borra a otro perfil por traer igual RFC."""
        existente = self.por_id(perfil.id)
        if existente:
            self.perfiles[self.perfiles.index(existente)] = perfil
        else:
            self.perfiles.append(perfil)

    def eliminar(self, id_o_rfc: str) -> bool:
        p = self.por_id(id_o_rfc) or self.por_rfc(id_o_rfc)
        if p:
            self.perfiles.remove(p)
            return True
        return False
