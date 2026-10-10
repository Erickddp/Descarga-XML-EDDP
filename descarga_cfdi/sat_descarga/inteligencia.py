# -*- coding: utf-8 -*-
"""Inteligencia sobre los CFDI leídos (sin SAT, sin base de datos).

- Perspectiva: si un XML no dice si es emitido o recibido (no viene de las
  carpetas de descarga), se deduce comparando con TUS RFCs.
- Duplicados: el mismo comprobante leído dos veces se cuenta una sola vez.
- Relaciones: factura <-> complemento de pago (REP) <-> nota de crédito.
  Calcula cuánto se ha pagado de cada factura PPD, qué notas le aplican y
  cuánto queda pendiente.
- Memoria: recuerda pagos y facturas entre lecturas (memoria.json), así una
  factura leída hoy encuentra el pago que leíste la semana pasada en otra
  carpeta.

Todo son HECHOS del XML; no hay criterio fiscal aquí.
"""
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .lector import CODIGO_POR_COMPROBANTE, EFECTO, Renglon, clase_de

TOL = 0.01          # tolerancia de centavos


def _r(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


# ======================================================================= perspectiva
def asignar_perspectiva(filas: List[Renglon], mis_rfcs: Iterable[str]) -> int:
    """Llena Tipo/Clase/Efecto de las filas que no lo traen, usando tus RFCs."""
    mios = {r.strip().upper() for r in mis_rfcs if r}
    n = 0
    for f in filas:
        d = f.datos
        if d.get("Tipo"):
            continue
        tipo = ""
        if d.get("RFC Emisor", "").upper() in mios:
            tipo = "Emitido"
        elif d.get("RFC Receptor", "").upper() in mios:
            tipo = "Recibido"
        if not tipo:
            continue
        codigo = CODIGO_POR_COMPROBANTE.get(d.get("Comprobante", ""), "")
        d["Tipo"] = tipo
        d["Clase"] = clase_de(codigo, tipo)
        d["Efecto"] = EFECTO.get((codigo, tipo), d.get("Efecto", ""))
        n += 1
    return n


def _id_cfdi(d: Dict) -> str:
    return (d.get("UUID") or d.get("Archivo") or "").upper()


def sin_perspectiva(filas: List[Renglon]) -> int:
    """Cuántos comprobantes (no renglones) no saben si son emitidos o recibidos."""
    return len({_id_cfdi(f.datos) for f in filas if not f.datos.get("Tipo")})


def candidatos_dueno(filas: List[Renglon], limite: int = 12) -> List[Tuple[str, str, int]]:
    """[(rfc, nombre, n)] de los RFC que más aparecen (como emisor o receptor) en
    los comprobantes sin perspectiva, del más frecuente al menos."""
    from collections import Counter
    cuenta, nombres, vistos = Counter(), {}, set()
    for f in filas:
        d = f.datos
        k = _id_cfdi(d)
        if d.get("Tipo") or k in vistos:
            continue
        vistos.add(k)
        en_este = set()
        for campo_rfc, campo_nom in (("RFC Emisor", "Nombre Emisor"),
                                     ("RFC Receptor", "Nombre Receptor")):
            rfc = (d.get(campo_rfc) or "").strip().upper()
            if rfc and rfc not in en_este:
                en_este.add(rfc)
                nombres.setdefault(rfc, d.get(campo_nom, ""))
                cuenta[rfc] += 1
    orden = sorted(cuenta.items(), key=lambda kv: (-kv[1], kv[0]))[:limite]
    return [(r, nombres.get(r, ""), n) for r, n in orden]


def rfc_sugerido(filas: List[Renglon]) -> Optional[Tuple[str, str, int]]:
    """El RFC más frecuente sin perspectiva: casi siempre es el dueño de la carpeta."""
    c = candidatos_dueno(filas, 1)
    return c[0] if c else None


# ======================================================================= duplicados
def _clave(d: Dict) -> Optional[Tuple]:
    uuid = (d.get("UUID") or "").upper()
    if not uuid:
        return None                     # sin UUID no se puede afirmar que es duplicado
    return (uuid, d.get("Tipo", ""), (d.get("Doc Pagado UUID") or "").upper(),
            str(d.get("Parcialidad", "")))


def deduplicar(filas: List[Renglon]) -> Tuple[List[Renglon], List[Renglon]]:
    """(únicas, duplicadas). Conserva la primera aparición."""
    vistos, unicas, dups = set(), [], []
    for f in filas:
        k = _clave(f.datos)
        if k is not None and k in vistos:
            dups.append(f)
            continue
        if k is not None:
            vistos.add(k)
        unicas.append(f)
    return unicas, dups


# ======================================================================= memoria
class Memoria:
    """Pagos y facturas vistos en lecturas anteriores. JSON en la carpeta de datos."""

    def __init__(self, ruta: str):
        self.ruta = Path(ruta)
        self.pagos: Dict[str, Dict] = {}
        self.facturas: Dict[str, Dict] = {}
        self.cargar()

    def cargar(self) -> None:
        if not self.ruta.exists():
            return
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
            self.pagos = dict(datos.get("pagos", {}))
            self.facturas = dict(datos.get("facturas", {}))
        except (OSError, ValueError):
            self.pagos, self.facturas = {}, {}

    def guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "pagos": self.pagos,
                                   "facturas": self.facturas},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.ruta)               # escritura atómica: nunca queda a medias

    def registrar(self, filas: List[Renglon]) -> None:
        for f in filas:
            d = f.datos
            if d.get("Es Pago") == "Sí" and d.get("Doc Pagado UUID"):
                e = _pago_de_fila(d)
                self.pagos[e["clave"]] = e
            elif d.get("Comprobante") == "Ingreso" and d.get("UUID"):
                self.facturas[d["UUID"].upper()] = {
                    "total": _r(d.get("Total")), "metodo": d.get("Método Pago", ""),
                    "fecha": d.get("Fecha", ""), "serie": d.get("Serie", ""),
                    "folio": d.get("Folio", ""), "rfc_emisor": d.get("RFC Emisor", ""),
                    "nombre_emisor": d.get("Nombre Emisor", ""),
                    "rfc_receptor": d.get("RFC Receptor", ""),
                }

    def __len__(self) -> int:
        return len(self.pagos) + len(self.facturas)


def _pago_de_fila(d: Dict) -> Dict:
    rep = (d.get("UUID") or "").upper()
    doc = (d.get("Doc Pagado UUID") or "").upper()
    parc_raw = d.get("Parcialidad", "")
    try:
        parc = str(int(float(parc_raw))) if float(parc_raw) == int(float(parc_raw)) else str(parc_raw)
    except (TypeError, ValueError):
        parc = str(parc_raw or "")
    return {
        "clave": f"{rep}|{doc}|{parc}",
        "rep_uuid": rep, "doc_uuid": doc, "parcialidad": parc,
        "imp_pagado": _r(d.get("Imp Pagado")), "iva": _r(d.get("IVA Doc")),
        "saldo_anterior": _r(d.get("Saldo Anterior")),
        "saldo_insoluto": _r(d.get("Saldo Insoluto")),
        "fecha_pago": d.get("Fecha Pago", ""), "forma": d.get("Forma Pago P", ""),
        "rfc_emisor": d.get("RFC Emisor", ""), "nombre_emisor": d.get("Nombre Emisor", ""),
        "serie": d.get("Serie", ""), "folio": d.get("Folio", ""),
    }


# ======================================================================= relaciones
def relacionar(filas: List[Renglon], memoria: Optional[Memoria] = None) -> Dict:
    """Llena las columnas de inteligencia y devuelve un resumen + mapas para el visor."""
    # --- índices de lo leído
    facturas_leidas = {}
    for f in filas:
        d = f.datos
        if d.get("Comprobante") == "Ingreso" and d.get("UUID"):
            facturas_leidas.setdefault(d["UUID"].upper(), []).append(f)

    pagos: Dict[str, Dict] = {}
    for f in filas:
        d = f.datos
        if d.get("Es Pago") == "Sí" and d.get("Doc Pagado UUID"):
            e = _pago_de_fila(d); e["origen"] = "lectura"
            pagos[e["clave"]] = e
    if memoria is not None:
        for k, e in memoria.pagos.items():
            if k not in pagos:
                pagos[k] = dict(e, origen="memoria")

    pagos_por_factura: Dict[str, List[Dict]] = {}
    for e in pagos.values():
        pagos_por_factura.setdefault(e["doc_uuid"], []).append(e)
    for lista in pagos_por_factura.values():
        lista.sort(key=lambda e: (_r(e.get("parcialidad")), e.get("fecha_pago", "")))

    nc_por_factura: Dict[str, List[Dict]] = {}
    for f in filas:
        d = f.datos
        if d.get("Comprobante") != "Egreso" or not d.get("Relacionados"):
            continue
        for rel in [u.strip().upper() for u in d["Relacionados"].split(",") if u.strip()]:
            nc_por_factura.setdefault(rel, []).append({
                "uuid": (d.get("UUID") or "").upper(), "total": _r(d.get("Total")),
                "fecha": d.get("Fecha", ""), "serie": d.get("Serie", ""),
                "folio": d.get("Folio", ""), "tipo_relacion": d.get("Tipo Relación", ""),
            })

    facturas_memoria = memoria.facturas if memoria is not None else {}

    def donde(uuid: str) -> str:
        if uuid in facturas_leidas:
            return "Sí"
        if uuid in facturas_memoria:
            return "En memoria"
        return "No leída"

    res = {"ppd": 0, "ppd_pagadas": 0, "ppd_parciales": 0, "ppd_sin_pago": 0,
           "saldo_pendiente": 0.0, "reps": 0, "reps_sin_factura": 0,
           "nc_ligadas": 0, "pagos_por_factura": pagos_por_factura,
           "nc_por_factura": nc_por_factura}

    # --- facturas
    for uuid, lista in facturas_leidas.items():
        ps = pagos_por_factura.get(uuid, [])
        ncs = nc_por_factura.get(uuid, [])
        pagado = round(sum(e["imp_pagado"] for e in ps), 2)
        nc_total = round(sum(n["total"] for n in ncs), 2)
        for f in lista:
            d = f.datos
            total = _r(d.get("Total"))
            metodo = d.get("Método Pago", "")
            d["Pagado REP"] = pagado
            d["Num REP"] = float(len(ps))
            d["NC Aplicadas"] = nc_total
            if metodo == "PUE":
                d["Estatus Pago"] = "PUE · pagada"
                d["Saldo Pendiente"] = 0.0
                continue
            if metodo != "PPD":
                d["Estatus Pago"] = ""
                d["Saldo Pendiente"] = 0.0
                continue
            if ps:
                ultimo = ps[-1]
                saldo = min(e["saldo_insoluto"] for e in ps if e["parcialidad"] == ultimo["parcialidad"])
            else:
                saldo = round(total - nc_total, 2)
            saldo = max(0.0, round(saldo, 2))
            d["Saldo Pendiente"] = saldo
            if saldo <= TOL:
                d["Estatus Pago"] = "Pagada"
            elif pagado > TOL:
                d["Estatus Pago"] = "Parcial"
            else:
                d["Estatus Pago"] = "Sin pago"
        # resumen (una vez por factura, no por perspectiva duplicada)
        d0 = lista[0].datos
        if d0.get("Método Pago") == "PPD":
            res["ppd"] += 1
            res["saldo_pendiente"] += d0["Saldo Pendiente"]
            res[{"Pagada": "ppd_pagadas", "Parcial": "ppd_parciales",
                 "Sin pago": "ppd_sin_pago"}[d0["Estatus Pago"]]] += 1

    # --- complementos de pago
    for f in filas:
        d = f.datos
        if d.get("Es Pago") != "Sí":
            continue
        res["reps"] += 1
        doc = (d.get("Doc Pagado UUID") or "").upper()
        if not doc:
            continue
        d["Factura Encontrada"] = donde(doc)
        if d["Factura Encontrada"] == "No leída":
            res["reps_sin_factura"] += 1
        d["Estatus Pago"] = ("Liquida factura" if _r(d.get("Saldo Insoluto")) <= TOL
                             else "Pago parcial")

    # --- notas de crédito
    for f in filas:
        d = f.datos
        if d.get("Comprobante") != "Egreso" or not d.get("Relacionados"):
            continue
        rels = [u.strip().upper() for u in d["Relacionados"].split(",") if u.strip()]
        estados = [donde(u) for u in rels]
        d["Factura Encontrada"] = ("Sí" if "Sí" in estados
                                   else "En memoria" if "En memoria" in estados else "No leída")
        if d["Factura Encontrada"] != "No leída":
            res["nc_ligadas"] += 1

    res["saldo_pendiente"] = round(res["saldo_pendiente"], 2)
    return res


# ======================================================================= todo junto
def procesar(filas: List[Renglon], mis_rfcs: Iterable[str] = (),
             memoria: Optional[Memoria] = None) -> Tuple[List[Renglon], Dict]:
    """Perspectiva -> duplicados -> relaciones -> memoria. Devuelve (filas, resumen)."""
    asignadas = asignar_perspectiva(filas, mis_rfcs)
    unicas, dups = deduplicar(filas)
    resumen = relacionar(unicas, memoria)
    if memoria is not None:
        memoria.registrar(unicas)
        memoria.guardar()
    resumen["duplicados"] = len(dups)
    resumen["duplicados_archivos"] = sorted({f.datos.get("Archivo", "") for f in dups})
    resumen["perspectiva_asignada"] = asignadas
    return unicas, resumen
