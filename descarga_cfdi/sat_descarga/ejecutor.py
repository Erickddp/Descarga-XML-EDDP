# -*- coding: utf-8 -*-
"""Ejecuta la descarga para uno o varios perfiles (RFCs).

Lo usan igual el CLI y la interfaz gráfica, así no hay dos lógicas distintas.
"""
import logging
import time
from datetime import datetime
from typing import Callable, List, Optional

from .config import Config, Perfil
from .flujo import Descargador, Resumen


def ejecutar_perfil(
    perfil: Perfil,
    cfg: Config,
    desde: datetime,
    hasta: datetime,
    tipo: str,
    logger: logging.Logger,
    cancelado: Callable[[], bool] = lambda: False,
    dormir: Callable[[float], None] = time.sleep,
    fabrica_cliente: Optional[Callable] = None,
) -> Resumen:
    """Descarga para un solo RFC. Nunca levanta: los errores van en el Resumen."""
    res = Resumen(rfc=perfil.rfc, nombre=perfil.nombre)

    errs = perfil.errores()
    if errs:
        for e in errs:
            res.errores.append(f"{perfil.nombre}: {e}")
            logger.error("%s: %s", perfil.nombre, e)
        return res

    try:
        if fabrica_cliente is None:
            from .cliente import ClienteSAT, cargar_fiel
            fiel = cargar_fiel(perfil.cer_path, perfil.key_path, perfil.key_password)
            cliente = ClienteSAT(fiel)
        else:
            cliente = fabrica_cliente(perfil)
    except Exception as e:  # noqa: BLE001
        msg = f"{perfil.nombre}: no se pudo cargar la e.firma ({e}). Revisa .cer/.key y la contraseña."
        logger.error(msg)
        res.errores.append(msg)
        return res

    try:
        d = Descargador(perfil, cfg.opciones, cliente, logger, dormir=dormir, cancelado=cancelado)
        return d.ejecutar(desde, hasta, tipo)
    except Exception as e:  # noqa: BLE001
        msg = f"{perfil.nombre}: {e}"
        logger.error(msg)
        res.errores.append(msg)
        return res


def probar_efirma(perfil: Perfil, logger: logging.Logger,
                  fabrica_cliente: Optional[Callable] = None) -> tuple:
    """(ok, mensaje). Carga la e.firma y pide token al SAT."""
    errs = perfil.errores()
    if errs:
        return False, "; ".join(errs)
    try:
        if fabrica_cliente is None:
            from .cliente import ClienteSAT, cargar_fiel
            cliente = ClienteSAT(cargar_fiel(perfil.cer_path, perfil.key_path, perfil.key_password))
        else:
            cliente = fabrica_cliente(perfil)
    except Exception as e:  # noqa: BLE001
        return False, f"No abrió la e.firma: {e} (¿contraseña incorrecta o no es la FIEL?)"
    try:
        tok = cliente.token()
        return True, f"e.firma OK — el SAT dio token ({len(tok)} caracteres)"
    except Exception as e:  # noqa: BLE001
        return False, f"La e.firma abrió pero el SAT la rechazó: {e}"


def ejecutar_varios(
    perfiles: List[Perfil],
    cfg: Config,
    desde: datetime,
    hasta: datetime,
    tipo: str,
    logger: logging.Logger,
    cancelado: Callable[[], bool] = lambda: False,
    al_terminar_perfil: Callable[[Resumen], None] = lambda r: None,
    dormir: Callable[[float], None] = time.sleep,
    fabrica_cliente: Optional[Callable] = None,
) -> List[Resumen]:
    resultados = []
    for p in perfiles:
        if cancelado():
            logger.info("Cancelado; se detiene antes de %s", p.nombre)
            break
        r = ejecutar_perfil(p, cfg, desde, hasta, tipo, logger, cancelado, dormir, fabrica_cliente)
        resultados.append(r)
        al_terminar_perfil(r)
    return resultados


def resumen_global(resultados: List[Resumen]) -> str:
    xml = sum(r.xml_nuevos for r in resultados)
    dup = sum(r.xml_duplicados for r in resultados)
    err = sum(len(r.errores) for r in resultados)
    lineas = [f"TOTAL: {xml} XML nuevos, {dup} ya existían, {err} errores, {len(resultados)} RFC(s)"]
    for r in resultados:
        lineas.append("  " + r.texto())
    return "\n".join(lineas)
