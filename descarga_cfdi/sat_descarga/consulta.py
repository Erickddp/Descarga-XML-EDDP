# -*- coding: utf-8 -*-
"""Consultas SQL sobre los CFDI leídos, sin base de datos en disco.

Carga los renglones en un SQLite en memoria (tabla `cfdi`) y deja correr
SELECT libres. También agrupa/resume para el dashboard.
"""
import sqlite3
from typing import Dict, List, Optional, Tuple

from .lector import COLUMNAS, NUMERICAS, Renglon

# nombre de columna visible -> nombre seguro para SQL
def _col_sql(nombre: str) -> str:
    tabla = {
        "Tipo": "tipo",
        "Fecha": "fecha",
        "Año": "anio",
        "Mes": "mes",
        "Día": "dia",
        "Hora": "hora",
        "Comprobante": "comprobante",
        "Efecto": "efecto",
        "Versión": "version",
        "Serie": "serie",
        "Folio": "folio",
        "RFC Emisor": "rfc_emisor",
        "Nombre Emisor": "nombre_emisor",
        "Régimen Emisor": "regimen_emisor",
        "RFC Receptor": "rfc_receptor",
        "Nombre Receptor": "nombre_receptor",
        "Régimen Receptor": "regimen_receptor",
        "Uso CFDI": "uso_cfdi",
        "Domicilio Receptor": "domicilio_receptor",
        "SubTotal": "subtotal",
        "Descuento": "descuento",
        "IVA Trasladado": "iva_trasladado",
        "IEPS Trasladado": "ieps_trasladado",
        "IVA Retenido": "iva_retenido",
        "ISR Retenido": "isr_retenido",
        "Ret. Total": "ret_total",
        "Total": "total",
        "Base IVA 16": "base_iva_16",
        "Base IVA 8": "base_iva_8",
        "Base IVA 0": "base_iva_0",
        "Base Exento": "base_exento",
        "Moneda": "moneda",
        "Tipo Cambio": "tipo_cambio",
        "Método Pago": "metodo_pago",
        "Forma Pago": "forma_pago",
        "Condiciones Pago": "condiciones_pago",
        "Exportación": "exportacion",
        "Es Pago": "es_pago",
        "Monto Total Pago": "monto_total_pago",
        "Fecha Pago": "fecha_pago",
        "Forma Pago P": "forma_pago_p",
        "Moneda Pago": "moneda_pago",
        "TC Pago": "tc_pago",
        "Num Operación": "num_operacion",
        "Doc Pagado UUID": "doc_pagado_uuid",
        "Doc Serie": "doc_serie",
        "Doc Folio": "doc_folio",
        "Parcialidad": "parcialidad",
        "Saldo Anterior": "saldo_anterior",
        "Imp Pagado": "imp_pagado",
        "Saldo Insoluto": "saldo_insoluto",
        "Base Doc": "base_doc",
        "IVA Doc": "iva_doc",
        "Tasa Doc": "tasa_doc",
        "Objeto Imp Doc": "objeto_imp_doc",
        "Relacionados": "relacionados",
        "Tipo Relación": "tipo_relacion",
        "Conceptos": "conceptos",
        "Descripción": "descripcion",
        "Claves ProdServ": "claves_prodserv",
        "No Identificación": "no_identificacion",
        "Complementos": "complementos",
        "UUID": "uuid",
        "Fecha Timbrado": "fecha_timbrado",
        "RFC PAC": "rfc_pac",
        "Archivo": "archivo",
    }
    return tabla.get(nombre, nombre.lower().replace(" ", "_"))


SQL_A_VISIBLE = {_col_sql(c): c for c in COLUMNAS}
VISIBLE_A_SQL = {c: _col_sql(c) for c in COLUMNAS}


class MotorSQL:
    """SQLite en memoria con los CFDI. Se reconstruye cada vez que se leen XML."""

    def __init__(self, filas: List[Renglon]):
        # se arma en el hilo de lectura y se consulta desde la ventana
        self.con = sqlite3.connect(":memory:", check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self._crear(filas)

    def _crear(self, filas: List[Renglon]) -> None:
        cols_sql = [_col_sql(c) for c in COLUMNAS]
        tipos = ["REAL" if c in NUMERICAS else "TEXT" for c in COLUMNAS]
        ddl = ", ".join(f'"{s}" {t}' for s, t in zip(cols_sql, tipos))
        self.con.execute(f"CREATE TABLE cfdi ({ddl})")
        marcas = ", ".join("?" for _ in COLUMNAS)
        datos = [[r.datos.get(c, "") for c in COLUMNAS] for r in filas]
        self.con.executemany(
            f'INSERT INTO cfdi ({", ".join(chr(34)+s+chr(34) for s in cols_sql)}) VALUES ({marcas})',
            datos)
        self.con.commit()

    def cerrar(self) -> None:
        try:
            self.con.close()
        except sqlite3.Error:
            pass

    # ---------------------------------------------------------- consulta libre
    def consultar(self, sql: str) -> Tuple[List[str], List[list]]:
        """Ejecuta un SELECT. Devuelve (encabezados, filas). Solo lectura."""
        limpio = sql.strip().rstrip(";").strip()
        if not limpio:
            raise ValueError("Escribe una consulta.")
        primera = limpio.split(None, 1)[0].lower()
        if primera not in ("select", "with"):
            raise ValueError("Solo se permiten consultas SELECT (lectura).")
        prohibidas = (";", " attach", " pragma ")
        bajo = " " + limpio.lower() + " "
        for p in ("insert", "update", "delete", "drop", "alter", "create", "replace", "attach"):
            if f" {p} " in bajo:
                raise ValueError(f"No se permite '{p.upper()}'. Solo consultas de lectura.")
        cur = self.con.execute(limpio)
        cols = [d[0] for d in cur.description]
        # traducir nombres sql -> visibles cuando aplique
        cols_vis = [SQL_A_VISIBLE.get(c, c) for c in cols]
        return cols_vis, [list(f) for f in cur.fetchall()]

    # ---------------------------------------------------------- resumen dashboard
    def resumen(self) -> Dict:
        """Numeros para el dashboard: por tipo, por mes, top emisores."""
        c = self.con
        def uno(sql, *a):
            r = c.execute(sql, a).fetchone()
            return r[0] if r and r[0] is not None else 0

        total_cfdi = uno("SELECT COUNT(*) FROM cfdi")
        por_tipo = {}
        for row in c.execute("SELECT tipo, COUNT(*) n, "
                             "COALESCE(SUM(total),0) t FROM cfdi GROUP BY tipo"):
            por_tipo[row["tipo"] or "—"] = {"n": row["n"], "total": row["t"]}

        por_mes = []
        for row in c.execute(
                "SELECT anio||'-'||mes periodo, "
                "SUM(CASE WHEN tipo='Emitido' THEN total ELSE 0 END) emitido, "
                "SUM(CASE WHEN tipo='Recibido' THEN total ELSE 0 END) recibido, "
                "COUNT(*) n FROM cfdi WHERE anio<>'' GROUP BY periodo ORDER BY periodo"):
            por_mes.append({"periodo": row["periodo"], "emitido": row["emitido"] or 0,
                            "recibido": row["recibido"] or 0, "n": row["n"]})

        top_emisores = []
        for row in c.execute(
                "SELECT nombre_emisor nom, rfc_emisor rfc, COUNT(*) n, "
                "COALESCE(SUM(total),0) t FROM cfdi WHERE tipo='Recibido' "
                "GROUP BY rfc_emisor ORDER BY t DESC LIMIT 8"):
            top_emisores.append({"nombre": row["nom"], "rfc": row["rfc"],
                                 "n": row["n"], "total": row["t"]})

        return {
            "total_cfdi": total_cfdi,
            "subtotal": uno("SELECT COALESCE(SUM(subtotal),0) FROM cfdi"),
            "iva_tras": uno("SELECT COALESCE(SUM(iva_trasladado),0) FROM cfdi"),
            "iva_ret": uno("SELECT COALESCE(SUM(iva_retenido),0) FROM cfdi"),
            "isr_ret": uno("SELECT COALESCE(SUM(isr_retenido),0) FROM cfdi"),
            "total": uno("SELECT COALESCE(SUM(total),0) FROM cfdi"),
            "por_tipo": por_tipo,
            "por_mes": por_mes,
            "top_emisores": top_emisores,
        }


# ---------------------------------------------------------------- consultas guardadas
CONSULTAS_EJEMPLO = [
    ("PPD con saldo pendiente (inteligencia)",
     "SELECT fecha, clase, nombre_emisor, nombre_receptor, serie, folio, total,\n"
     "       nc_aplicadas, pagado_rep, num_rep, saldo_pendiente, estatus_pago\n"
     "FROM cfdi WHERE metodo_pago='PPD' AND comprobante='Ingreso'\n"
     "ORDER BY saldo_pendiente DESC"),
    ("REP cuya factura no he leído",
     "SELECT fecha_pago, nombre_emisor, doc_serie, doc_folio, doc_pagado_uuid, imp_pagado, iva_doc\n"
     "FROM cfdi WHERE es_pago='Sí' AND factura_encontrada='No leída' ORDER BY fecha_pago"),
    ("Resumen por clase (I/G/N/P/E)",
     "SELECT clase, COUNT(DISTINCT uuid) AS comprobantes, ROUND(SUM(total),2) AS total,\n"
     "       ROUND(SUM(iva_trasladado),2) AS iva\n"
     "FROM cfdi GROUP BY clase ORDER BY clase"),
    ("Todo", "SELECT * FROM cfdi ORDER BY fecha"),
    ("Solo recibidos (gastos)",
     "SELECT fecha, rfc_emisor, nombre_emisor, subtotal, iva_trasladado, total\n"
     "FROM cfdi WHERE tipo='Recibido' ORDER BY total DESC"),
    ("Solo emitidos (ingresos)",
     "SELECT fecha, rfc_receptor, nombre_receptor, subtotal, iva_trasladado, total\n"
     "FROM cfdi WHERE tipo='Emitido' ORDER BY fecha"),
    ("Totales por mes",
     "SELECT anio||'-'||mes AS periodo, tipo, COUNT(*) AS comprobantes,\n"
     "       ROUND(SUM(subtotal),2) AS subtotal, ROUND(SUM(iva_trasladado),2) AS iva,\n"
     "       ROUND(SUM(total),2) AS total\n"
     "FROM cfdi GROUP BY periodo, tipo ORDER BY periodo, tipo"),
    ("Gasto por proveedor",
     "SELECT nombre_emisor, rfc_emisor, COUNT(*) AS facturas,\n"
     "       ROUND(SUM(total),2) AS total\n"
     "FROM cfdi WHERE tipo='Recibido'\n"
     "GROUP BY rfc_emisor ORDER BY total DESC"),
    ("IVA acreditable vs trasladado",
     "SELECT tipo, ROUND(SUM(iva_trasladado),2) AS iva_trasladado,\n"
     "       ROUND(SUM(iva_retenido),2) AS iva_retenido\n"
     "FROM cfdi GROUP BY tipo"),
    ("PPD sin pago (por revisar)",
     "SELECT fecha, nombre_emisor, total, metodo_pago\n"
     "FROM cfdi WHERE metodo_pago='PPD' ORDER BY fecha"),
    ("Pagos recibidos (REP) con detalle",
     "SELECT fecha, nombre_emisor, doc_serie, doc_folio, imp_pagado, iva_doc, saldo_insoluto\n"
     "FROM cfdi WHERE es_pago='Sí' ORDER BY fecha"),
    ("Comprobantes con relacionados",
     "SELECT fecha, comprobante, nombre_emisor, total, relacionados\n"
     "FROM cfdi WHERE relacionados<>'' ORDER BY fecha"),
    ("Notas de crédito (egresos)",
     "SELECT fecha, nombre_emisor, nombre_receptor, total, relacionados\n"
     "FROM cfdi WHERE comprobante='Egreso' ORDER BY fecha"),
    ("Facturas grandes (> 10 mil)",
     "SELECT fecha, tipo, nombre_emisor, nombre_receptor, total\n"
     "FROM cfdi WHERE total > 10000 ORDER BY total DESC"),
    ("Resumen de IVA para declaración",
     "SELECT tipo,\n"
     "  ROUND(SUM(CASE WHEN tipo='Emitido' THEN iva_trasladado ELSE 0 END),2) AS iva_causado,\n"
     "  ROUND(SUM(CASE WHEN tipo='Recibido' THEN iva_trasladado ELSE 0 END),2) AS iva_acreditable,\n"
     "  ROUND(SUM(iva_retenido),2) AS iva_retenido,\n"
     "  ROUND(SUM(isr_retenido),2) AS isr_retenido\n"
     "FROM cfdi GROUP BY tipo"),
    ("Conteo por tipo de comprobante",
     "SELECT comprobante, COUNT(*) AS cantidad, ROUND(SUM(total),2) AS total\n"
     "FROM cfdi GROUP BY comprobante ORDER BY cantidad DESC"),
    ("Actividad por día",
     "SELECT fecha, COUNT(*) AS comprobantes, ROUND(SUM(total),2) AS total\n"
     "FROM cfdi GROUP BY substr(fecha,1,10) ORDER BY fecha"),
]


def filas_desde_consulta(cols: List[str], filas: List[list]) -> Tuple[List[str], List[list]]:
    """Passthrough para exportar el resultado de una consulta tal cual."""
    return cols, filas
