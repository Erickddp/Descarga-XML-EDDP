# -*- coding: utf-8 -*-
"""Perfiles de reporte (multi-cliente) para la pestaña "Datos y Excel".

Un perfil = un cliente: nombre, RFC(s) dueño(s), carpeta de XML, carpeta de
salida de los PDF, diseño del PDF (logo, títulos, color, plantilla de nombre,
secciones visibles, subcarpetas), columnas de "Copiar tabla" y filtros por
defecto. Se guardan en carpeta_datos()/perfiles_reporte.json.

Además existe el diseño GENERAL: el que se usa cuando no hay perfil activo
(y para los RFC que no tienen perfil). Es lo que antes era "general" en
pdf_config.json; los "por_rfc" de ese archivo se migran a perfiles.

OJO: no confundir con config.Perfil (un RFC con su e.firma para descargar).
"""
import copy
import json
import uuid as _uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

ARCHIVO = "perfiles_reporte.json"
RFC_EJEMPLO = "XAXX010101000"

# Secciones del PDF que se activan/desactivan por perfil: clave -> (etiqueta, default)
SECCIONES = {
    "letra_clase": ("Letra grande de clase (I/G/N/P/E/T)", True),
    "datos_fiscales": ("Datos fiscales (régimen, domicilio, lugar, exportación…)", True),
    "conceptos_detalle": ("Conceptos con claves, unidad, objeto e impuestos", True),
    "complementos": ("Complementos de concepto y otros complementos", True),
    "complemento_pago": ("Complemento de pago (REP)", True),
    "relacionados": ("CFDI relacionados", True),
    "inteligencia": ("Seguimiento de pago (calculado)", True),
    "timbre": ("Timbre fiscal completo", True),
    "sellos": ("Sellos y cadena original del timbre", False),
    "qr": ("Código QR de verificación del SAT", True),
}

# Cómo organizar los PDF en subcarpetas: clave -> etiqueta
SUBCARPETAS = {"": "Todo en la misma carpeta", "mes": "Por mes (202609/…)",
               "mes/clase": "Por mes y clase (202609/G/…)"}

DISENO_DEFAULT = {
    "titulo": "",
    "subtitulo": "Representación impresa de CFDI",
    "logo": "",
    "color_primario": "#1F4E78",
    "pie": "Generado con DESCARGA XML EDDP",
    "nombre_archivo": "{fecha}_{clase}_{rfc_contraparte}_{serie}{folio}_{uuid8}",
    "subcarpetas": "",
    "secciones": {k: v[1] for k, v in SECCIONES.items()},
}

# claves viejas de pdf_config.json -> sección nueva
_LEGADO = {"mostrar_letra_clase": "letra_clase", "mostrar_inteligencia": "inteligencia",
           "mostrar_sello_sat": "sellos"}

FILTROS_DEFAULT = {"tipo": "todos", "mes": "todos", "clase": "", "texto": ""}


def _nuevo_id() -> str:
    return _uuid.uuid4().hex[:8]


def completar_diseno(d: Optional[Dict]) -> Dict:
    """Diseño completo: lo que falte se llena con los defaults (un JSON a medias
    no truena) y las claves viejas mostrar_* se traducen a secciones."""
    final = copy.deepcopy(DISENO_DEFAULT)
    d = dict(d or {})
    secciones = dict(d.pop("secciones", None) or {})
    for viejo, nuevo in _LEGADO.items():
        if viejo in d:
            secciones.setdefault(nuevo, bool(d.pop(viejo)))
    for k, v in d.items():
        if k in final and v is not None:
            final[k] = v
    for k, v in secciones.items():
        if k in final["secciones"]:
            final["secciones"][k] = bool(v)
    if final["subcarpetas"] not in SUBCARPETAS:
        final["subcarpetas"] = ""
    return final


def _limpiar_rfcs(rfcs) -> List[str]:
    if isinstance(rfcs, str):
        rfcs = rfcs.replace(";", ",").replace(" ", ",").split(",")
    vistos = []
    for r in rfcs or []:
        r = str(r).strip().upper()
        if r and r not in vistos:
            vistos.append(r)
    return vistos


@dataclass
class PerfilReporte:
    nombre: str = ""
    rfcs: List[str] = field(default_factory=list)
    carpeta_xml: str = ""
    carpeta_pdf: str = ""
    diseno: Dict = field(default_factory=dict)
    columnas_copiado: List[str] = field(default_factory=list)   # vacío = formato EDDP (65)
    filtros: Dict = field(default_factory=dict)
    id: str = ""

    def __post_init__(self):
        self.id = self.id or _nuevo_id()
        self.nombre = (self.nombre or "").strip() or "Perfil sin nombre"
        self.rfcs = _limpiar_rfcs(self.rfcs)
        self.diseno = completar_diseno(self.diseno)
        self.filtros = dict(FILTROS_DEFAULT, **{k: v for k, v in (self.filtros or {}).items()
                                                if k in FILTROS_DEFAULT})
        self.columnas_copiado = [str(c) for c in (self.columnas_copiado or [])]

    @classmethod
    def desde_dict(cls, d: Dict) -> "PerfilReporte":
        campos = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**campos)

    def logos(self) -> List[str]:
        return [self.diseno.get("logo", "")] if self.diseno.get("logo") else []


class Perfiles:
    """Colección de perfiles + diseño general + cuál está activo."""

    def __init__(self, ruta: Optional[str] = None):
        if ruta is None:
            from .config import carpeta_datos
            ruta = str(carpeta_datos() / ARCHIVO)
        self.ruta = Path(ruta)
        self.general: Dict = completar_diseno({})
        self.lista: List[PerfilReporte] = []
        self.activo_id: str = ""
        self.migrado_de_pdf_config = False

    # ------------------------------------------------------------ persistencia
    @classmethod
    def cargar(cls, ruta: Optional[str] = None, pdf_config: Optional[str] = None) -> "Perfiles":
        """Lee perfiles_reporte.json. Si no existe, migra pdf_config.json (general +
        por_rfc) sin perder nada y guarda el resultado. Nunca truena por un JSON roto."""
        p = cls(ruta)
        if p.ruta.exists():
            try:
                datos = json.loads(p.ruta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                datos = {}
            p.general = completar_diseno(datos.get("general"))
            p.lista = [PerfilReporte.desde_dict(x) for x in datos.get("perfiles", [])
                       if isinstance(x, dict)]
            p.activo_id = datos.get("activo", "") if p.por_id(datos.get("activo", "")) else ""
            return p
        origen = Path(pdf_config) if pdf_config else p.ruta.with_name("pdf_config.json")
        if origen.exists():
            p.migrar_pdf_config(origen)
            try:
                p.guardar()
            except OSError:
                pass
        return p

    def a_dict(self) -> Dict:
        return {"version": 1, "activo": self.activo_id, "general": self.general,
                "perfiles": [asdict(x) for x in self.lista]}

    def guardar(self) -> str:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.a_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.ruta)
        return str(self.ruta)

    def migrar_pdf_config(self, ruta_pdf_config) -> int:
        """general -> diseño general; cada por_rfc (menos el ejemplo) -> un perfil
        con el diseño general + lo propio de ese RFC. Devuelve perfiles creados."""
        try:
            pc = json.loads(Path(ruta_pdf_config).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        general = dict(pc.get("general") or {})
        self.general = completar_diseno(general)
        n = 0
        for rfc, extra in (pc.get("por_rfc") or {}).items():
            rfc = str(rfc).strip().upper()
            if not isinstance(extra, dict) or rfc == RFC_EJEMPLO:
                continue
            diseno = dict(general)
            diseno.update({k: v for k, v in extra.items() if v not in ("", None)})
            nombre = extra.get("titulo") or rfc
            self.lista.append(PerfilReporte(nombre=nombre, rfcs=[rfc], diseno=diseno))
            n += 1
        self.migrado_de_pdf_config = True
        return n

    # ------------------------------------------------------------ consulta
    def por_id(self, pid: str) -> Optional[PerfilReporte]:
        return next((x for x in self.lista if x.id == pid), None) if pid else None

    def por_nombre(self, nombre: str) -> Optional[PerfilReporte]:
        return next((x for x in self.lista if x.nombre == nombre), None)

    def por_rfc(self, rfc: str) -> Optional[PerfilReporte]:
        rfc = (rfc or "").strip().upper()
        return next((x for x in self.lista if rfc in x.rfcs), None) if rfc else None

    @property
    def activo(self) -> Optional[PerfilReporte]:
        return self.por_id(self.activo_id)

    def activar(self, pid: str) -> Optional[PerfilReporte]:
        self.activo_id = pid if self.por_id(pid) else ""
        return self.activo

    def diseno_para(self, rfc_dueno: str = "") -> Dict:
        """Diseño a usar para un CFDI: el del perfil activo; si no hay, el del perfil
        que tenga ese RFC (como antes 'por RFC'); si no, el general."""
        p = self.activo or self.por_rfc(rfc_dueno)
        return copy.deepcopy(p.diseno if p else self.general)

    def nombres(self) -> List[str]:
        return [x.nombre for x in self.lista]

    def logos(self) -> List[str]:
        todos = ([self.general.get("logo", "")] if self.general.get("logo") else [])
        for x in self.lista:
            todos += x.logos()
        return sorted(set(todos))

    # ------------------------------------------------------------ altas y bajas
    def _nombre_libre(self, base: str, excepto: str = "") -> str:
        base = (base or "").strip() or "Perfil"
        usados = {x.nombre for x in self.lista if x.id != excepto}
        if base not in usados:
            return base
        i = 2
        while f"{base} ({i})" in usados:
            i += 1
        return f"{base} ({i})"

    def crear(self, nombre: str, **campos) -> PerfilReporte:
        campos.setdefault("diseno", copy.deepcopy(self.general))
        p = PerfilReporte(nombre=self._nombre_libre(nombre), **campos)
        self.lista.append(p)
        return p

    def duplicar(self, pid: str, nombre: str = "") -> Optional[PerfilReporte]:
        orig = self.por_id(pid)
        if orig is None:
            return None
        d = copy.deepcopy(asdict(orig))
        d.pop("id")
        d["nombre"] = self._nombre_libre(nombre or f"{orig.nombre} (copia)")
        p = PerfilReporte.desde_dict(d)
        self.lista.append(p)
        return p

    def renombrar(self, pid: str, nombre: str) -> bool:
        p = self.por_id(pid)
        if p is None or not (nombre or "").strip():
            return False
        p.nombre = self._nombre_libre(nombre, excepto=pid)
        return True

    def borrar(self, pid: str) -> bool:
        p = self.por_id(pid)
        if p is None:
            return False
        self.lista.remove(p)
        if self.activo_id == pid:
            self.activo_id = ""
        return True

    def reemplazar(self, perfil: PerfilReporte) -> None:
        """Guarda una edición (mismo id) o agrega si es nuevo."""
        actual = self.por_id(perfil.id)
        perfil.nombre = self._nombre_libre(perfil.nombre, excepto=perfil.id)
        if actual is not None:
            self.lista[self.lista.index(actual)] = perfil
        else:
            self.lista.append(perfil)

    def fusionar(self, otro: "Perfiles", remap_logo=lambda x: x) -> Dict:
        """Trae los perfiles de un respaldo: mismo id = se actualiza; si no, se agrega."""
        res = {"nuevos": 0, "actualizados": 0}
        for p in otro.lista:
            p = copy.deepcopy(p)
            p.diseno["logo"] = remap_logo(p.diseno.get("logo", ""))
            if self.por_id(p.id):
                res["actualizados"] += 1
            else:
                res["nuevos"] += 1
            self.reemplazar(p)
        if self.general == completar_diseno({}):          # el local nunca se personalizó
            self.general = copy.deepcopy(otro.general)
            self.general["logo"] = remap_logo(self.general.get("logo", ""))
        return res
