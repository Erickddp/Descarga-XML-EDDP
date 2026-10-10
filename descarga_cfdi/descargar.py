#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI (opcional). La forma normal de usar esto es la interfaz: python app.py

Ejemplos:
  python descargar.py --desde 2026-01-01 --hasta 2026-09-05 --tipo ambos
  python descargar.py --desde 2026-08-01 --hasta 2026-08-31 --rfc EDDP800101XXX
  python descargar.py --probar-fiel
"""
import argparse
import sys
from datetime import datetime

from sat_descarga.config import Config
from sat_descarga.ejecutor import ejecutar_varios, probar_efirma, resumen_global
from sat_descarga.utilerias import configurar_log


def parsear_args(argv=None):
    p = argparse.ArgumentParser(description="Descarga masiva de XML CFDI del SAT (e.firma).")
    p.add_argument("--desde", help="AAAA-MM-DD")
    p.add_argument("--hasta", help="AAAA-MM-DD")
    p.add_argument("--tipo", choices=["emitidos", "recibidos", "ambos"], default="ambos")
    p.add_argument("--rfc", action="append", help="Solo estos RFC (repetible). Default: los marcados como activos.")
    p.add_argument("--config", default="config.json")
    p.add_argument("--sin-meses", action="store_true", help="No partir el rango por mes")
    p.add_argument("--probar-fiel", action="store_true", help="Solo validar e.firma y pedir token")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)
    if not a.probar_fiel:
        if not a.desde or not a.hasta:
            p.error("--desde y --hasta son obligatorios (o usa --probar-fiel)")
        try:
            a.desde_dt = datetime.strptime(a.desde, "%Y-%m-%d")
            a.hasta_dt = datetime.strptime(a.hasta, "%Y-%m-%d")
        except ValueError:
            p.error("fechas en formato AAAA-MM-DD")
        if a.desde_dt > a.hasta_dt:
            p.error("--desde no puede ser mayor que --hasta")
    return a


def seleccionar(cfg: Config, rfcs):
    if rfcs:
        sel = []
        for r in rfcs:
            p = cfg.por_rfc(r)
            if not p:
                print(f"ERROR: RFC no configurado: {r}", file=sys.stderr)
                return None
            sel.append(p)
        return sel
    return cfg.activos()


def main(argv=None) -> int:
    a = parsear_args(argv)
    cfg = Config.desde_archivo(a.config)
    if not cfg.perfiles:
        print(f"ERROR: no hay RFCs en {a.config}. Abre la interfaz con: python app.py", file=sys.stderr)
        return 2
    if a.sin_meses:
        cfg.opciones.dividir_por_mes = False
    log = configurar_log(cfg.opciones.archivo_log, a.verbose)

    perfiles = seleccionar(cfg, a.rfc)
    if perfiles is None:
        return 2
    if not perfiles:
        print("ERROR: ningún RFC activo. Márcalos en la interfaz o usa --rfc.", file=sys.stderr)
        return 2

    if a.probar_fiel:
        malos = 0
        for p in perfiles:
            ok, msg = probar_efirma(p, log)
            log.info("%s (%s): %s", p.nombre, p.rfc, msg)
            malos += 0 if ok else 1
        return 0 if not malos else 4

    res = ejecutar_varios(perfiles, cfg, a.desde_dt, a.hasta_dt, a.tipo, log)
    log.info("\n%s", resumen_global(res))
    return 1 if any(r.errores for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
