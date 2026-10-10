# -*- coding: utf-8 -*-
"""Lee CFDIs (3.2 / 3.3 / 4.0) y los convierte en renglones planos para tabla,
Excel o portapapeles. No toca el SAT: trabaja sobre los XML ya descargados.
"""
import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from lxml import etree

NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"
NS_NOMINA = ("http://www.sat.gob.mx/nomina12", "http://www.sat.gob.mx/nomina")
NS_PAGOS = ("http://www.sat.gob.mx/Pagos20", "http://www.sat.gob.mx/Pagos")

TIPO_COMPROBANTE = {
    "I": "Ingreso", "E": "Egreso", "T": "Traslado", "N": "Nómina", "P": "Pago",
}
IMPUESTO = {"001": "ISR", "002": "IVA", "003": "IEPS"}

# Orden de las columnas en tabla, Excel y portapapeles.
# Todas las columnas útiles para análisis masivo y clasificación.
# Nada de sellos, certificados ni cadenas (no aportan).
COLUMNAS = [
    # identidad
    "Clase", "Tipo", "Fecha", "Año", "Mes", "Día", "Hora",
    "Comprobante", "Efecto", "Versión",
    "Serie", "Folio",
    # partes
    "RFC Emisor", "Nombre Emisor", "Régimen Emisor",
    "RFC Receptor", "Nombre Receptor", "Régimen Receptor",
    "Uso CFDI", "Domicilio Receptor",
    # importes
    "SubTotal", "Descuento", "IVA Trasladado", "IEPS Trasladado",
    "IVA Retenido", "ISR Retenido", "Ret. Total", "Total",
    "Base IVA 16", "Base IVA 8", "Base IVA 0", "Base Exento",
    # pago del comprobante
    "Moneda", "Tipo Cambio", "Método Pago", "Forma Pago",
    "Condiciones Pago", "Exportación",
    # complemento de pago (una fila por doc pagado)
    "Es Pago", "Monto Total Pago", "Fecha Pago", "Forma Pago P",
    "Moneda Pago", "TC Pago", "Num Operación",
    "Doc Pagado UUID", "Doc Serie", "Doc Folio", "Parcialidad",
    "Saldo Anterior", "Imp Pagado", "Saldo Insoluto",
    "Base Doc", "IVA Doc", "Tasa Doc", "Objeto Imp Doc",
    # relacionados
    "Relacionados", "Tipo Relación",
    # inteligencia (se calcula al leer: factura <-> complemento <-> notas)
    "Estatus Pago", "Pagado REP", "Num REP", "NC Aplicadas", "Saldo Pendiente",
    "Factura Encontrada",
    # conceptos
    "Conceptos", "Descripción", "Claves ProdServ", "No Identificación",
    "Complementos",
    # timbre / archivo
    "UUID", "Fecha Timbrado", "RFC PAC", "Archivo",
]

# Formato EXACTO de 'Copiar tabla' (EDDP): 65 columnas, en este orden.
# Las demás (Clase, inteligencia, Archivo) van al Excel y a otros reportes.
COLUMNAS_COPIADO = ['Tipo', 'Fecha', 'Año', 'Mes', 'Día', 'Hora', 'Comprobante', 'Efecto', 'Versión', 'Serie', 'Folio', 'RFC Emisor', 'Nombre Emisor', 'Régimen Emisor', 'RFC Receptor', 'Nombre Receptor', 'Régimen Receptor', 'Uso CFDI', 'Domicilio Receptor', 'SubTotal', 'Descuento', 'IVA Trasladado', 'IEPS Trasladado', 'IVA Retenido', 'ISR Retenido', 'Ret. Total', 'Total', 'Base IVA 16', 'Base IVA 8', 'Base IVA 0', 'Base Exento', 'Moneda', 'Tipo Cambio', 'Método Pago', 'Forma Pago', 'Condiciones Pago', 'Exportación', 'Es Pago', 'Monto Total Pago', 'Fecha Pago', 'Forma Pago P', 'Moneda Pago', 'TC Pago', 'Num Operación', 'Doc Pagado UUID', 'Doc Serie', 'Doc Folio', 'Parcialidad', 'Saldo Anterior', 'Imp Pagado', 'Saldo Insoluto', 'Base Doc', 'IVA Doc', 'Tasa Doc', 'Objeto Imp Doc', 'Relacionados', 'Tipo Relación', 'Conceptos', 'Descripción', 'Claves ProdServ', 'No Identificación', 'Complementos', 'UUID', 'Fecha Timbrado', 'RFC PAC']

# Columnas numéricas (para Excel y SQL)
NUMERICAS = {
    "SubTotal", "Descuento", "IVA Trasladado", "IEPS Trasladado",
    "IVA Retenido", "ISR Retenido", "Ret. Total", "Total",
    "Base IVA 16", "Base IVA 8", "Base IVA 0", "Base Exento",
    "Tipo Cambio", "Conceptos",
    "Monto Total Pago", "TC Pago", "Parcialidad",
    "Saldo Anterior", "Imp Pagado", "Saldo Insoluto",
    "Base Doc", "IVA Doc",
    "Pagado REP", "Num REP", "NC Aplicadas", "Saldo Pendiente",
}

# Clase: una letra que dice qué es el comprobante PARA QUIEN LO ESTÁ LEYENDO.
#   I = Ingreso (yo lo emití)        G = Gasto (me lo emitieron)
#   N = Nómina   P = Pago (REP)       E = Nota de crédito / egreso   T = Traslado
CLASES = {
    "I": ("Ingreso", "#1F9D57"),
    "G": ("Gasto", "#C7402F"),
    "N": ("Nómina", "#7B4BC4"),
    "P": ("Pago", "#2D6CDF"),
    "E": ("Nota de crédito", "#D9822B"),
    "T": ("Traslado", "#6B7686"),
}
CODIGO_POR_COMPROBANTE = {"Ingreso": "I", "Egreso": "E", "Pago": "P",
                          "Nómina": "N", "Traslado": "T"}


def clase_de(tipo_c: str, tipo: str) -> str:
    """tipo_c: I/E/P/N/T del XML. tipo: Emitido/Recibido (perspectiva)."""
    if tipo_c in ("N", "P", "E", "T"):
        return tipo_c
    if tipo_c == "I":
        if tipo == "Emitido":
            return "I"
        if tipo == "Recibido":
            return "G"
    return ""


# "Efecto" describe cómo pega el comprobante en tus números, SIN opinar de fiscal:
# es un hecho del CFDI (tipo + si tú lo emites o lo recibes), no un criterio.
EFECTO = {
    ("I", "Emitido"): "Ingreso (+)",
    ("I", "Recibido"): "Gasto (-)",
    ("E", "Emitido"): "Nota crédito emitida (-)",
    ("E", "Recibido"): "Nota crédito recibida (+)",
    ("P", "Emitido"): "Pago cobrado",
    ("P", "Recibido"): "Pago realizado",
    ("N", "Emitido"): "Nómina pagada (-)",
    ("N", "Recibido"): "Nómina",
    ("T", "Emitido"): "Traslado",
    ("T", "Recibido"): "Traslado",
}


def _dec(v) -> Decimal:
    if v in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _f(v) -> float:
    return float(_dec(v))


def _hijo(nodo, local: str):
    """Busca un hijo por nombre local, sin importar el prefijo/namespace."""
    for h in nodo:
        if isinstance(h.tag, str) and etree.QName(h).localname == local:
            return h
    return None


def _hijos(nodo, local: str) -> List:
    return [h for h in nodo
            if isinstance(h.tag, str) and etree.QName(h).localname == local]


def _buscar_todos(raiz, local: str) -> List:
    return [n for n in raiz.iter()
            if isinstance(n.tag, str) and etree.QName(n).localname == local]


@dataclass
class Renglon:
    datos: Dict[str, object] = field(default_factory=dict)

    def como_lista(self) -> List:
        return [self.datos.get(c, "") for c in COLUMNAS]


def _impuestos(root) -> Dict[str, Decimal]:
    """Suma traslados y retenciones del nodo Impuestos del comprobante.
    Si no existe (algunos CFDI viejos), suma los de los conceptos.
    También separa las bases de IVA por tasa (16/8/0/exento)."""
    res = {"IVA_T": Decimal("0"), "IEPS_T": Decimal("0"),
           "IVA_R": Decimal("0"), "ISR_R": Decimal("0"),
           "BASE_16": Decimal("0"), "BASE_8": Decimal("0"),
           "BASE_0": Decimal("0"), "BASE_EX": Decimal("0")}

    nodo_imp = _hijo(root, "Impuestos")
    fuentes = []
    if nodo_imp is not None:
        fuentes.append(nodo_imp)
    else:
        conceptos = _hijo(root, "Conceptos")
        if conceptos is not None:
            for c in _hijos(conceptos, "Concepto"):
                ci = _hijo(c, "Impuestos")
                if ci is not None:
                    fuentes.append(ci)

    # bases por tasa: recorrer todos los traslados de IVA de los conceptos
    conceptos_nodo = _hijo(root, "Conceptos")
    if conceptos_nodo is not None:
        for c in _hijos(conceptos_nodo, "Concepto"):
            objeto = c.get("ObjetoImp") or ""
            ci = _hijo(c, "Impuestos")
            if ci is None:
                if objeto == "01":            # no objeto de impuesto -> exento/base
                    res["BASE_EX"] += _dec(c.get("Importe"))
                continue
            for t in _buscar_todos(ci, "Traslado"):
                if (t.get("Impuesto") or "") != "002":
                    continue
                base = _dec(t.get("Base"))
                tasa = t.get("TasaOCuota") or ""
                factor = t.get("TipoFactor") or ""
                if factor == "Exento":
                    res["BASE_EX"] += base
                elif tasa.startswith("0.16"):
                    res["BASE_16"] += base
                elif tasa.startswith("0.08"):
                    res["BASE_8"] += base
                elif tasa.startswith("0.00") or tasa == "0":
                    res["BASE_0"] += base

    for f in fuentes:
        for grupo, sufijo in (("Traslados", "T"), ("Retenciones", "R")):
            g = _hijo(f, grupo)
            if g is None:
                continue
            singular = "Traslado" if grupo == "Traslados" else "Retencion"
            for t in _hijos(g, singular):
                clave = IMPUESTO.get(t.get("Impuesto") or t.get("impuesto"), "")
                imp = t.get("Importe") or t.get("importe")
                llave = f"{clave}_{sufijo}"
                if llave in res:
                    res[llave] += _dec(imp)
    return res


def _raiz(ruta: Path, contenido: Optional[bytes] = None):
    """Raíz del XML (desde bytes ya leídos o desde el archivo). None si no se puede."""
    try:
        if contenido is not None:
            return etree.fromstring(contenido)
        return etree.parse(str(ruta)).getroot()
    except (etree.XMLSyntaxError, OSError, ValueError):
        return None


def leer_xml_filas(ruta: Path, tipo: str = "", contenido: Optional[bytes] = None) -> list:
    """Convierte un CFDI en una o más filas. Un comprobante de Pago devuelve una
    fila por documento pagado; los demás, una sola. Lista vacía si no es CFDI.
    contenido: bytes del archivo si ya se leyeron (lectura en paralelo)."""
    ruta = Path(ruta)
    root = _raiz(ruta, contenido)
    if root is None:
        return []
    if etree.QName(root).localname != "Comprobante":
        return []

    g = root.get
    emisor = _hijo(root, "Emisor")
    receptor = _hijo(root, "Receptor")
    conceptos_nodo = _hijo(root, "Conceptos")
    conceptos = _hijos(conceptos_nodo, "Concepto") if conceptos_nodo is not None else []

    tfd = next(iter(_buscar_todos(root, "TimbreFiscalDigital")), None)
    fecha = g("Fecha") or g("fecha") or ""
    imp = _impuestos(root)

    descripciones = [c.get("Descripcion") or c.get("descripcion") or "" for c in conceptos]
    desc = descripciones[0] if descripciones else ""
    if len(descripciones) > 1:
        desc = f"{desc} (+{len(descripciones) - 1} más)"

    tipo_c = g("TipoDeComprobante") or g("tipoDeComprobante") or ""
    efecto = EFECTO.get((tipo_c, tipo), "")
    pagos = _pagos_del_cfdi(root) if tipo_c == "P" else None
    relacionados = _relacionados_del_cfdi(root)
    rel_txt = ", ".join(r["uuid"] for r in relacionados)
    rel_tipo = ", ".join(sorted({r["tipo_desc"] for r in relacionados if r["tipo_desc"]}))

    fecha_limpia = fecha.replace("T", " ") if fecha else ""
    claves_ps = sorted({c.get("ClaveProdServ") or c.get("claveProdServ") or ""
                        for c in conceptos if c.get("ClaveProdServ") or c.get("claveProdServ")})
    no_ident = sorted({c.get("NoIdentificacion") or "" for c in conceptos if c.get("NoIdentificacion")})
    # complementos presentes (nombre de cada nodo bajo Complemento, sin timbre)
    comps = set()
    for comp in _buscar_todos(root, "Complemento"):
        for h in comp:
            if isinstance(h.tag, str):
                ln = etree.QName(h).localname
                if ln != "TimbreFiscalDigital":
                    comps.add(ln)
    ret_total = float(imp["IVA_R"] + imp["ISR_R"])

    base = {
        "Clase": clase_de(tipo_c, tipo),
        "Tipo": tipo,
        "Fecha": fecha_limpia,
        "Año": fecha[0:4] if len(fecha) >= 4 else "",
        "Mes": fecha[5:7] if len(fecha) >= 7 else "",
        "Día": fecha[8:10] if len(fecha) >= 10 else "",
        "Hora": fecha[11:16] if len(fecha) >= 16 else "",
        "Comprobante": TIPO_COMPROBANTE.get(tipo_c, tipo_c),
        "Efecto": efecto,
        "Versión": g("Version") or g("version") or "",
        "Serie": g("Serie") or g("serie") or "",
        "Folio": g("Folio") or g("folio") or "",
        "RFC Emisor": (emisor.get("Rfc") or emisor.get("rfc") or "") if emisor is not None else "",
        "Nombre Emisor": (emisor.get("Nombre") or emisor.get("nombre") or "") if emisor is not None else "",
        "Régimen Emisor": (emisor.get("RegimenFiscal") or "") if emisor is not None else "",
        "RFC Receptor": (receptor.get("Rfc") or receptor.get("rfc") or "") if receptor is not None else "",
        "Nombre Receptor": (receptor.get("Nombre") or receptor.get("nombre") or "") if receptor is not None else "",
        "Régimen Receptor": (receptor.get("RegimenFiscalReceptor") or "") if receptor is not None else "",
        "Uso CFDI": (receptor.get("UsoCFDI") or receptor.get("usoCFDI") or "") if receptor is not None else "",
        "Domicilio Receptor": (receptor.get("DomicilioFiscalReceptor") or "") if receptor is not None else "",
        "SubTotal": _f(g("SubTotal") or g("subTotal")),
        "Descuento": _f(g("Descuento") or g("descuento")),
        "IVA Trasladado": float(imp["IVA_T"]),
        "IEPS Trasladado": float(imp["IEPS_T"]),
        "IVA Retenido": float(imp["IVA_R"]),
        "ISR Retenido": float(imp["ISR_R"]),
        "Ret. Total": ret_total,
        "Total": _f(g("Total") or g("total")),
        "Base IVA 16": float(imp["BASE_16"]),
        "Base IVA 8": float(imp["BASE_8"]),
        "Base IVA 0": float(imp["BASE_0"]),
        "Base Exento": float(imp["BASE_EX"]),
        "Moneda": g("Moneda") or g("moneda") or "",
        "Tipo Cambio": _f(g("TipoCambio") or 1),
        "Método Pago": g("MetodoPago") or g("metodoDePago") or "",
        "Forma Pago": g("FormaPago") or g("formaDePago") or "",
        "Condiciones Pago": g("CondicionesDePago") or "",
        "Exportación": g("Exportacion") or "",
        # pago: se llena abajo por doc; aquí defaults
        "Es Pago": "Sí" if tipo_c == "P" else "",
        "Monto Total Pago": float(pagos["monto"]) if pagos else 0.0,
        "Fecha Pago": pagos.get("fecha_pago", "") if pagos else "",
        "Forma Pago P": pagos.get("forma_pago", "") if pagos else "",
        "Moneda Pago": pagos.get("moneda", "") if pagos else "",
        "TC Pago": _f(pagos.get("tipo_cambio") or 0) if pagos else 0.0,
        "Num Operación": pagos.get("num_operacion", "") if pagos else "",
        "Doc Pagado UUID": "", "Doc Serie": "", "Doc Folio": "", "Parcialidad": 0.0,
        "Saldo Anterior": 0.0, "Imp Pagado": 0.0, "Saldo Insoluto": 0.0,
        "Base Doc": 0.0, "IVA Doc": 0.0, "Tasa Doc": "", "Objeto Imp Doc": "",
        "Relacionados": rel_txt,
        "Tipo Relación": rel_tipo,
        "Estatus Pago": "", "Pagado REP": 0.0, "Num REP": 0.0, "NC Aplicadas": 0.0,
        "Saldo Pendiente": 0.0, "Factura Encontrada": "",
        "Conceptos": len(conceptos),
        "Descripción": desc,
        "Claves ProdServ": ", ".join(claves_ps),
        "No Identificación": ", ".join(no_ident),
        "Complementos": ", ".join(sorted(comps)),
        "UUID": (tfd.get("UUID") if tfd is not None else "") or "",
        "Fecha Timbrado": (tfd.get("FechaTimbrado") if tfd is not None else "") or "",
        "RFC PAC": (tfd.get("RfcProvCertif") if tfd is not None else "") or "",
        "Archivo": str(ruta),
    }

    # Un CFDI de Pago con documentos: una fila por documento pagado.
    if pagos and pagos["docs"]:
        filas = []
        for doc in pagos["docs"]:
            d = dict(base)
            d["Doc Pagado UUID"] = doc["uuid"]
            d["Doc Serie"] = doc.get("serie", "")
            d["Doc Folio"] = doc.get("folio", "")
            d["Parcialidad"] = _f(doc.get("parcialidad") or 0)
            d["Saldo Anterior"] = doc["saldo_ant"]
            d["Imp Pagado"] = doc["pagado"]
            d["Saldo Insoluto"] = doc["saldo_insoluto"]
            d["Base Doc"] = doc.get("base", 0.0)
            d["IVA Doc"] = doc.get("iva", 0.0)
            d["Tasa Doc"] = doc.get("tasa", "")
            d["Objeto Imp Doc"] = doc.get("objeto_imp", "")
            filas.append(Renglon(d))
        return filas

    return [Renglon(base)]


def leer_xml(ruta: Path, tipo: str = "") -> Optional[Renglon]:
    """Compatibilidad: devuelve el primer renglón (o None)."""
    filas = leer_xml_filas(ruta, tipo)
    return filas[0] if filas else None


def _tipo_por_ruta(ruta: Path) -> str:
    """La carpeta dice si fue emitido o recibido."""
    for parte in reversed(ruta.parts):
        p = parte.lower()
        if p == "emitidos":
            return "Emitido"
        if p == "recibidos":
            return "Recibido"
    return ""


class LecturaCancelada(Exception):
    """El usuario canceló la lectura de la carpeta."""


HILOS_LECTURA = 16       # abrir archivos es lo lento (antivirus, Google Drive): en paralelo
VENTANA_LECTURA = 256    # archivos leídos por adelantado (memoria acotada)


def listar_xml(carpeta: str, recursivo: bool = True) -> List[Path]:
    base = Path(carpeta)
    if not base.exists():
        return []
    return sorted(base.glob("**/*.xml" if recursivo else "*.xml"))


def _bytes_de(a: Path):
    """(bytes, firma) de un archivo; firma = (mtime, tamaño) para el índice.
    Solo E/S: corre en hilos (abrir es lo lento con antivirus o Google Drive)."""
    try:
        with open(a, "rb") as fh:
            datos = fh.read()
            st = os.fstat(fh.fileno())
        return datos, (str(int(st.st_mtime)), str(st.st_size))
    except OSError:
        return None, None


def leer_archivos(archivos: List[Path], progreso=None, cancelado=None):
    """Lee una lista de XML conservando el orden: los archivos se abren en
    paralelo y se interpretan en este hilo (así no pelean por el GIL).
    Devuelve (filas, firmas{ruta: (mtime, tamaño)}). Lanza LecturaCancelada."""
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor
    filas: List[Renglon] = []
    firmas: Dict[str, tuple] = {}
    total = len(archivos)
    if progreso:
        progreso(0, total)
    with ThreadPoolExecutor(max_workers=HILOS_LECTURA) as ex:
        # ventana deslizante: los hilos siempre van adelantados, sin cargar todo a memoria
        pendientes = deque()
        siguiente = 0
        for i in range(total):
            while siguiente < total and len(pendientes) < VENTANA_LECTURA:
                pendientes.append(ex.submit(_bytes_de, archivos[siguiente]))
                siguiente += 1
            if cancelado and i % 32 == 0 and cancelado():
                for f in pendientes:
                    f.cancel()
                raise LecturaCancelada()
            datos, firma = pendientes.popleft().result()
            a = archivos[i]
            if datos is not None:
                firmas[str(a)] = firma
                filas.extend(leer_xml_filas(a, _tipo_por_ruta(a), contenido=datos))
            if progreso and ((i + 1) % 50 == 0 or i + 1 == total):
                progreso(i + 1, total)
    return filas, firmas


def leer_carpeta(carpeta: str, recursivo: bool = True,
                 progreso=None, cancelado=None) -> List[Renglon]:
    """Lee todos los XML de una carpeta (y subcarpetas). Ignora lo que no sea CFDI."""
    filas, _ = leer_archivos(listar_xml(carpeta, recursivo), progreso, cancelado)
    return filas


def a_matriz(filas: List[Renglon]) -> List[List]:
    return [r.como_lista() for r in filas]


def totales(filas: List[Renglon]) -> Dict[str, float]:
    """Sumas rápidas para mostrar debajo de la tabla."""
    s = {c: 0.0 for c in ("SubTotal", "Descuento", "IVA Trasladado",
                          "IVA Retenido", "ISR Retenido", "Total")}
    for r in filas:
        for c in s:
            s[c] += float(r.datos.get(c) or 0)
    return {k: round(v, 2) for k, v in s.items()}


# ---------------------------------------------------------------- pagos y relacionados
TIPO_RELACION = {
    "01": "Nota de crédito", "02": "Nota de débito", "03": "Devolución mercancía",
    "04": "Sustitución CFDI previo", "05": "Traslados de mercancía facturados",
    "06": "Factura por traslados", "07": "CFDI por aplicación de anticipo",
}


def _pagos_del_cfdi(root) -> Dict:
    """Extrae el complemento de pagos (2.0 o 1.0) con todo el detalle útil:
    monto, forma, moneda, num. de operación, IVA del pago, y los documentos
    que cubre con su IVA por documento."""
    res = {
        "monto": Decimal("0"), "fecha_pago": "", "forma_pago": "", "moneda": "",
        "tipo_cambio": "", "num_operacion": "",
        "iva_trasladado": Decimal("0"), "iva_retenido": Decimal("0"),
        "num_pagos": 0, "docs": [],
    }
    nodo_pagos = next((n for n in root.iter()
                       if isinstance(n.tag, str) and etree.QName(n).localname == "Pagos"), None)
    if nodo_pagos is None:
        return res

    totales = _hijo(nodo_pagos, "Totales")
    if totales is not None:
        res["monto"] = _dec(totales.get("MontoTotalPagos"))
        res["iva_trasladado"] = _dec(
            totales.get("TotalTrasladosImpuestoIVA16")
            or totales.get("TotalTrasladosBaseIVA16") and totales.get("TotalTrasladosImpuestoIVA16")
            or 0)
        res["iva_retenido"] = _dec(totales.get("TotalRetencionesIVA") or 0)

    pagos = _hijos(nodo_pagos, "Pago")
    res["num_pagos"] = len(pagos)
    for pago in pagos:
        monto_p = _dec(pago.get("Monto") or pago.get("monto"))
        if res["monto"] == 0:
            res["monto"] += monto_p
        if not res["fecha_pago"]:
            res["fecha_pago"] = (pago.get("FechaPago") or pago.get("fechaPago") or "").replace("T", " ")
            res["forma_pago"] = pago.get("FormaDePagoP") or pago.get("formaDePagoP") or ""
            res["moneda"] = pago.get("MonedaP") or pago.get("monedaP") or ""
            res["tipo_cambio"] = pago.get("TipoCambioP") or pago.get("tipoCambioP") or ""
            res["num_operacion"] = pago.get("NumOperacion") or pago.get("numOperacion") or ""

        # IVA a nivel pago (si no venía en Totales)
        for imp_p in _buscar_todos(pago, "TrasladoP"):
            if res["iva_trasladado"] == 0:
                res["iva_trasladado"] += _dec(imp_p.get("ImporteP") or imp_p.get("ImporteDR") or 0)

        for dr in _hijos(pago, "DoctoRelacionado"):
            iva_dr = Decimal("0")
            base_dr = Decimal("0")
            tasa_dr = ""
            for t in _buscar_todos(dr, "TrasladoDR"):
                if (t.get("ImpuestoDR") or "") == "002":
                    iva_dr += _dec(t.get("ImporteDR") or 0)
                    base_dr += _dec(t.get("BaseDR") or 0)
                    tasa_dr = t.get("TasaOCuotaDR") or tasa_dr
            if res["iva_trasladado"] == 0:
                res["iva_trasladado"] += iva_dr
            res["docs"].append({
                "uuid": dr.get("IdDocumento") or dr.get("idDocumento") or "",
                "serie": dr.get("Serie") or "",
                "folio": dr.get("Folio") or "",
                "moneda": dr.get("MonedaDR") or "",
                "parcialidad": dr.get("NumParcialidad") or dr.get("numParcialidad") or "",
                "saldo_ant": _f(dr.get("ImpSaldoAnt") or 0),
                "pagado": _f(dr.get("ImpPagado") or 0),
                "saldo_insoluto": _f(dr.get("ImpSaldoInsoluto") or 0),
                "iva": float(iva_dr),
                "base": float(base_dr),
                "tasa": tasa_dr,
                "objeto_imp": dr.get("ObjetoImpDR") or "",
            })
    return res


def _relacionados_del_cfdi(root):
    """Lista de (uuid, tipo_relacion_codigo, tipo_relacion_desc)."""
    out = []
    for nodo in root.iter():
        if not isinstance(nodo.tag, str):
            continue
        if etree.QName(nodo).localname != "CfdiRelacionados":
            continue
        tipo = nodo.get("TipoRelacion") or nodo.get("tipoRelacion") or ""
        for rel in _hijos(nodo, "CfdiRelacionado"):
            uuid = rel.get("UUID") or rel.get("uuid") or ""
            if uuid:
                out.append({"uuid": uuid, "tipo": tipo,
                            "tipo_desc": TIPO_RELACION.get(tipo, tipo)})
    return out


# ---------------------------------------------------------------- detalle para el visor
def leer_detalle(ruta) -> Optional[Dict]:
    """Extrae TODO lo que el visor necesita de un CFDI: encabezado, conceptos
    (con importes), impuestos y timbre. Devuelve None si no es CFDI."""
    ruta = Path(ruta)
    try:
        root = etree.parse(str(ruta)).getroot()
    except (etree.XMLSyntaxError, OSError):
        return None
    if etree.QName(root).localname != "Comprobante":
        return None

    g = root.get
    emisor = _hijo(root, "Emisor")
    receptor = _hijo(root, "Receptor")
    conceptos_nodo = _hijo(root, "Conceptos")
    conceptos_xml = _hijos(conceptos_nodo, "Concepto") if conceptos_nodo is not None else []
    tfd = next(iter(_buscar_todos(root, "TimbreFiscalDigital")), None)

    def at(nodo, *nombres):
        if nodo is None:
            return ""
        for n in nombres:
            v = nodo.get(n)
            if v:
                return v
        return ""

    conceptos = []
    for c in conceptos_xml:
        ci = _hijo(c, "Impuestos")
        conceptos.append({
            "clave_prod": at(c, "ClaveProdServ", "claveProdServ"),
            "no_identificacion": at(c, "NoIdentificacion", "noIdentificacion"),
            "cantidad": _f(at(c, "Cantidad", "cantidad") or 0),
            "clave_unidad": at(c, "ClaveUnidad"),
            "unidad": at(c, "Unidad", "unidad"),
            "descripcion": at(c, "Descripcion", "descripcion"),
            "valor_unitario": _f(at(c, "ValorUnitario", "valorUnitario") or 0),
            "importe": _f(at(c, "Importe", "importe") or 0),
            "descuento": _f(at(c, "Descuento", "descuento") or 0),
            "objeto_imp": at(c, "ObjetoImp"),
            "objeto_imp_desc": OBJETO_IMP.get(at(c, "ObjetoImp"), ""),
            "traslados": _impuestos_concepto(ci, "Traslado"),
            "retenciones": _impuestos_concepto(ci, "Retencion"),
            "complementos": _complementos_concepto(c),
            "extras": _extras_concepto(c),
        })

    imp = _impuestos(root)
    tipo_c = at(root, "TipoDeComprobante", "tipoDeComprobante")
    pagos = _pagos_del_cfdi(root)
    relacionados = _relacionados_del_cfdi(root)
    timbre = {k: at(tfd, k) for k in ("Version", "UUID", "FechaTimbrado", "RfcProvCertif",
                                      "Leyenda", "SelloCFD", "NoCertificadoSAT", "SelloSAT")}
    sello_emisor = at(root, "Sello", "sello") or timbre["SelloCFD"]
    total_txt = at(root, "Total", "total") or "0"
    info_global = _hijo(root, "InformacionGlobal")
    complementos = []
    for comp in _hijos(root, "Complemento"):
        for h in comp:
            if isinstance(h.tag, str) and etree.QName(h).localname != "TimbreFiscalDigital":
                complementos.append(nombre_complemento(h))

    return {
        "version": at(root, "Version", "version"),
        "serie": at(root, "Serie", "serie"),
        "folio": at(root, "Folio", "folio"),
        "fecha": (g("Fecha") or g("fecha") or "").replace("T", " "),
        "tipo_comprobante": tipo_c,
        "tipo_comprobante_desc": TIPO_COMPROBANTE.get(tipo_c, tipo_c),
        "lugar": at(root, "LugarExpedicion", "LugarExpedicion"),
        "moneda": at(root, "Moneda", "moneda") or "MXN",
        "tipo_cambio": at(root, "TipoCambio") or "1",
        "metodo_pago": at(root, "MetodoPago", "metodoDePago"),
        "forma_pago": at(root, "FormaPago", "formaDePago"),
        "uso_cfdi": at(receptor, "UsoCFDI", "usoCFDI"),
        "emisor_rfc": at(emisor, "Rfc", "rfc"),
        "emisor_nombre": at(emisor, "Nombre", "nombre"),
        "emisor_regimen": at(emisor, "RegimenFiscal"),
        "receptor_rfc": at(receptor, "Rfc", "rfc"),
        "receptor_nombre": at(receptor, "Nombre", "nombre"),
        "receptor_uso": at(receptor, "UsoCFDI", "usoCFDI"),
        "subtotal": _f(at(root, "SubTotal", "subTotal") or 0),
        "descuento": _f(at(root, "Descuento", "descuento") or 0),
        "total": _f(at(root, "Total", "total") or 0),
        "iva_trasladado": float(imp["IVA_T"]),
        "ieps_trasladado": float(imp["IEPS_T"]),
        "iva_retenido": float(imp["IVA_R"]),
        "isr_retenido": float(imp["ISR_R"]),
        "conceptos": conceptos,
        "es_pago": tipo_c == "P",
        "pago_monto": float(pagos["monto"]),
        "pago_fecha": pagos.get("fecha_pago", ""),
        "pago_forma": pagos.get("forma_pago", ""),
        "pago_moneda": pagos.get("moneda", ""),
        "pago_tipo_cambio": pagos.get("tipo_cambio", ""),
        "pago_num_operacion": pagos.get("num_operacion", ""),
        "pago_iva": float(pagos.get("iva_trasladado", 0)),
        "pago_docs": pagos["docs"],
        "relacionados": relacionados,
        "uuid": (tfd.get("UUID") if tfd is not None else "") or "",
        "fecha_timbrado": (tfd.get("FechaTimbrado") if tfd is not None else "") or "",
        "sello_cfd": (tfd.get("SelloCFD") if tfd is not None else "") or "",
        "sello_sat": (tfd.get("SelloSAT") if tfd is not None else "") or "",
        "no_certificado_sat": (tfd.get("NoCertificadoSAT") if tfd is not None else "") or "",
        "archivo": str(ruta),
        # ---- datos fiscales
        "emisor_regimen_desc": REGIMEN.get(at(emisor, "RegimenFiscal"), ""),
        "receptor_regimen": at(receptor, "RegimenFiscalReceptor"),
        "receptor_regimen_desc": REGIMEN.get(at(receptor, "RegimenFiscalReceptor"), ""),
        "receptor_domicilio": at(receptor, "DomicilioFiscalReceptor"),
        "receptor_residencia": at(receptor, "ResidenciaFiscal"),
        "receptor_num_reg_id_trib": at(receptor, "NumRegIdTrib"),
        "exportacion": at(root, "Exportacion"),
        "exportacion_desc": EXPORTACION.get(at(root, "Exportacion"), ""),
        "condiciones_pago": at(root, "CondicionesDePago", "condicionesDePago"),
        "no_certificado": at(root, "NoCertificado", "noCertificado"),
        "metodo_pago_desc": METODO_PAGO.get(at(root, "MetodoPago", "metodoDePago"), ""),
        "forma_pago_desc": FORMA_PAGO.get(at(root, "FormaPago", "formaDePago"), ""),
        "uso_cfdi_desc": USO_CFDI.get(at(receptor, "UsoCFDI", "usoCFDI"), ""),
        "informacion_global": ({"periodicidad": at(info_global, "Periodicidad"),
                                "meses": at(info_global, "Meses"), "anio": at(info_global, "Año")}
                               if info_global is not None else {}),
        # ---- timbre completo
        "version_timbre": timbre["Version"],
        "rfc_pac": timbre["RfcProvCertif"],
        "leyenda_timbre": timbre["Leyenda"],
        "cadena_original_timbre": cadena_original_timbre(timbre) if tfd is not None else "",
        "sello_emisor": sello_emisor,
        "total_texto": total_txt,
        "qr_url": url_verificacion(timbre["UUID"], at(emisor, "Rfc", "rfc"),
                                   at(receptor, "Rfc", "rfc"), total_txt, sello_emisor)
        if tfd is not None else "",
        "complementos": complementos,
    }


# ---------------------------------------------------------------- catálogos (solo etiquetas)
OBJETO_IMP = {"01": "No objeto de impuesto", "02": "Sí objeto de impuesto",
              "03": "Sí objeto, no obligado al desglose", "04": "Sí objeto, no causa impuesto",
              "05": "Sí objeto, IVA crédito PODEBI", "06": "Sí objeto, IVA no traslado",
              "07": "No traslado del IVA, sí desglose IEPS", "08": "No traslado del IVA, no desglose IEPS"}
EXPORTACION = {"01": "No aplica", "02": "Definitiva con clave A1", "03": "Temporal",
               "04": "Definitiva con clave distinta a A1"}
METODO_PAGO = {"PUE": "Pago en una sola exhibición", "PPD": "Pago en parcialidades o diferido"}
FORMA_PAGO = {"01": "Efectivo", "02": "Cheque nominativo", "03": "Transferencia electrónica",
              "04": "Tarjeta de crédito", "05": "Monedero electrónico", "06": "Dinero electrónico",
              "08": "Vales de despensa", "12": "Dación en pago", "13": "Pago por subrogación",
              "14": "Pago por consignación", "15": "Condonación", "17": "Compensación",
              "23": "Novación", "24": "Confusión", "25": "Remisión de deuda",
              "26": "Prescripción o caducidad", "27": "A satisfacción del acreedor",
              "28": "Tarjeta de débito", "29": "Tarjeta de servicios",
              "30": "Aplicación de anticipos", "31": "Intermediario pagos", "99": "Por definir"}
USO_CFDI = {"G01": "Adquisición de mercancías", "G02": "Devoluciones, descuentos o bonificaciones",
            "G03": "Gastos en general", "I01": "Construcciones", "I02": "Mobiliario y equipo de oficina",
            "I03": "Equipo de transporte", "I04": "Equipo de cómputo", "I05": "Dados, troqueles, moldes",
            "I06": "Comunicaciones telefónicas", "I07": "Comunicaciones satelitales",
            "I08": "Otra maquinaria y equipo", "D01": "Honorarios médicos y hospitalarios",
            "D02": "Gastos médicos por incapacidad", "D03": "Gastos funerales", "D04": "Donativos",
            "D05": "Intereses reales por créditos hipotecarios", "D06": "Aportaciones voluntarias SAR",
            "D07": "Primas de seguros de gastos médicos", "D08": "Gastos de transportación escolar",
            "D09": "Depósitos para el ahorro", "D10": "Servicios educativos (colegiaturas)",
            "S01": "Sin efectos fiscales", "CP01": "Pagos", "CN01": "Nómina"}
REGIMEN = {"601": "General de Ley Personas Morales", "603": "Personas Morales con Fines no Lucrativos",
           "605": "Sueldos y Salarios", "606": "Arrendamiento", "607": "Enajenación o Adquisición de Bienes",
           "608": "Demás ingresos", "610": "Residentes en el Extranjero", "611": "Dividendos",
           "612": "Personas Físicas con Actividades Empresariales y Profesionales",
           "614": "Ingresos por intereses", "615": "Obtención de premios", "616": "Sin obligaciones fiscales",
           "620": "Sociedades Cooperativas de Producción", "621": "Incorporación Fiscal",
           "622": "Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras",
           "623": "Opcional para Grupos de Sociedades", "624": "Coordinados",
           "625": "Plataformas Tecnológicas", "626": "Régimen Simplificado de Confianza"}
TIPO_FACTOR = {"Tasa": "Tasa", "Cuota": "Cuota", "Exento": "Exento"}

# nombre legible de complementos (por nombre local del nodo)
COMPLEMENTOS_CONOCIDOS = {
    "Pagos": "Recepción de pagos", "Nomina": "Nómina", "VentaVehiculos": "Venta de vehículos",
    "ComercioExterior": "Comercio exterior", "CartaPorte": "Carta Porte",
    "ImpuestosLocales": "Impuestos locales", "Donatarias": "Donatarias",
    "LeyendasFiscales": "Leyendas fiscales", "INE": "INE", "Divisas": "Divisas",
    "EstadoDeCuentaCombustible": "Estado de cuenta de combustibles",
    "ConsumoDeCombustibles": "Consumo de combustibles", "Aerolineas": "Aerolíneas",
    "NotariosPublicos": "Notarios públicos", "ValesDeDespensa": "Vales de despensa",
    "PFintegranteCoordinado": "PF integrante coordinado", "TuristaPasajeroExtranjero": "Turista extranjero",
    "IedU": "Instituciones educativas privadas", "iedu": "Instituciones educativas privadas",
    "ServicioParcialConstruccion": "Servicios parciales de construcción",
    "RenovacionYSustitucionVehiculos": "Renovación y sustitución de vehículos",
    "CertificadoDeDestruccion": "Certificado de destrucción", "ObrasArteAntiguedades": "Obras de arte",
    "GastosHidrocarburos": "Gastos de hidrocarburos", "IngresosHidrocarburos": "Ingresos de hidrocarburos",
}


def nombre_complemento(nodo) -> str:
    local = etree.QName(nodo).localname
    version = nodo.get("Version") or nodo.get("version") or ""
    nombre = COMPLEMENTOS_CONOCIDOS.get(local, local)
    return f"{nombre} {version}".strip()


def _impuestos_concepto(nodo_imp, singular: str) -> List[Dict]:
    """Traslados o retenciones de un concepto: impuesto, base, factor, tasa, importe."""
    if nodo_imp is None:
        return []
    out = []
    for t in _buscar_todos(nodo_imp, singular):
        clave = t.get("Impuesto") or ""
        out.append({"impuesto": clave, "impuesto_desc": IMPUESTO.get(clave, clave),
                    "base": _f(t.get("Base") or 0), "tipo_factor": t.get("TipoFactor") or "",
                    "tasa": t.get("TasaOCuota") or "", "importe": _f(t.get("Importe") or 0)})
    return out


def _aplanar(nodo, prefijo="") -> List[tuple]:
    """(campo, valor) de un nodo y sus hijos, sin sellos ni certificados."""
    out = []
    for k, v in nodo.attrib.items():
        k = etree.QName(k).localname if k.startswith("{") else k
        if k.lower() in _ATRIBUTOS_OMITIR or k == "version" or k == "Version":
            continue
        out.append((f"{prefijo}{k}", v))
    for h in nodo:
        if isinstance(h.tag, str):
            out += _aplanar(h, f"{prefijo}{etree.QName(h).localname}.")
    return out


def _complementos_concepto(c) -> List[Dict]:
    """Complementos dentro de ComplementoConcepto. Venta de vehículos se presenta
    con nombres claros (NIV, clave vehicular, aduana); los demás, campo por campo."""
    out = []
    cc = _hijo(c, "ComplementoConcepto")
    if cc is None:
        return out
    for h in cc:
        if not isinstance(h.tag, str):
            continue
        local = etree.QName(h).localname
        if local == "VentaVehiculos":
            campos = [("Clave vehicular", h.get("ClaveVehicular") or ""),
                      ("NIV", h.get("Niv") or h.get("NIV") or "")]
            for ia in _buscar_todos(h, "InformacionAduanera"):
                datos = (("pedimento", ia.get("numero")), ("fecha", ia.get("fecha")),
                         ("aduana", ia.get("aduana")))
                campos.append(("Información aduanera",
                               " · ".join(f"{k} {v}" for k, v in datos if v)))
            for parte in _buscar_todos(h, "Parte"):
                campos.append(("Parte", f"{parte.get('cantidad') or ''} "
                                        f"{parte.get('descripcion') or ''}".strip()))
            out.append({"nombre": nombre_complemento(h), "campos": [x for x in campos if x[1]]})
        else:
            out.append({"nombre": nombre_complemento(h), "campos": _aplanar(h)})
    return out


def _extras_concepto(c) -> List[tuple]:
    """Otros datos del concepto: a cuenta de terceros, cuenta predial, pedimentos."""
    out = []
    terceros = _hijo(c, "ACuentaTerceros")
    if terceros is not None:
        out.append(("A cuenta de terceros", f"{terceros.get('RfcACuentaTerceros') or ''} "
                                            f"{terceros.get('NombreACuentaTerceros') or ''}".strip()))
    for cp in _hijos(c, "CuentaPredial"):
        out.append(("Cuenta predial", cp.get("Numero") or ""))
    for ia in _hijos(c, "InformacionAduanera"):
        out.append(("Pedimento", ia.get("NumeroPedimento") or ""))
    return [x for x in out if x[1]]


def cadena_original_timbre(t: Dict) -> str:
    """Cadena original del complemento de certificación digital del SAT:
    ||Version|UUID|FechaTimbrado|RfcProvCertif|[Leyenda|]SelloCFD|NoCertificadoSAT||"""
    partes = [t.get("Version") or "1.1", t.get("UUID", ""), t.get("FechaTimbrado", ""),
              t.get("RfcProvCertif", "")]
    if t.get("Leyenda"):
        partes.append(t["Leyenda"])
    partes += [t.get("SelloCFD", ""), t.get("NoCertificadoSAT", "")]
    return "||" + "|".join(partes) + "||"


URL_VERIFICACION = "https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx"


def url_verificacion(uuid: str, rfc_emisor: str, rfc_receptor: str, total: str, sello: str) -> str:
    """URL del QR de verificación del SAT (fe = últimos 8 caracteres del sello)."""
    from urllib.parse import quote
    return (f"{URL_VERIFICACION}?id={uuid}&re={quote(rfc_emisor or '')}"
            f"&rr={quote(rfc_receptor or '')}&tt={total}&fe={quote((sello or '')[-8:], safe='=/')}")


# ---------------------------------------------------------------- volcado completo
_ATRIBUTOS_OMITIR = {
    "sello", "sellocfd", "sellosat", "certificado", "nocertificado",
    "cadenaoriginal", "cadenaoriginalcc", "sellocfdi",
}


def volcado_xml(ruta) -> list:
    """Aplana TODO el XML a una lista de (ruta_nodo, atributo, valor), saltando
    sellos, certificados y cadenas originales (no aportan a la revisión)."""
    ruta = Path(ruta)
    try:
        root = etree.parse(str(ruta)).getroot()
    except (etree.XMLSyntaxError, OSError):
        return []
    filas = []

    def recorrer(nodo, prefijo=""):
        nombre = etree.QName(nodo).localname
        ruta_nodo = f"{prefijo}/{nombre}" if prefijo else nombre
        for k, v in nodo.attrib.items():
            attr = etree.QName(k).localname if k.startswith("{") else k
            if attr.lower() in _ATRIBUTOS_OMITIR:
                continue
            if v and len(v) > 300:            # cadenas larguísimas = sellos disfrazados
                continue
            filas.append((ruta_nodo, attr, v))
        for hijo in nodo:
            if isinstance(hijo.tag, str):
                recorrer(hijo, ruta_nodo)

    recorrer(root)
    return filas
