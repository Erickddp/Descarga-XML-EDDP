# -*- coding: utf-8 -*-
"""Lectura completa de una carpeta para la pestaña "Datos y Excel":
XML -> filas -> inteligencia -> motor SQL. Sin Tk: corre en un hilo secundario
y reporta avance con callbacks (la ventana pinta desde su cola).
"""
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

from .consulta import MotorSQL
from .exportar import Indice, leer_carpeta_con_indice
from .inteligencia import Memoria, procesar, sin_perspectiva
from .lector import LecturaCancelada  # noqa: F401  (se re-exporta para la UI)


def leer_y_procesar(carpeta: str, ruta_indice: str, mis_rfcs: Iterable[str] = (),
                    memoria: Optional[Memoria] = None, forzar: bool = False,
                    progreso: Optional[Callable[[int, int], None]] = None,
                    cancelado: Optional[Callable[[], bool]] = None) -> Dict:
    """Todo lo pesado de 'Leer XML'. Lanza LecturaCancelada si se cancela."""
    idx = Indice(ruta_indice)
    filas, nuevos, reusados = leer_carpeta_con_indice(
        carpeta, idx, progreso=progreso, forzar=forzar, cancelado=cancelado)
    error_intel = ""
    try:
        filas, resumen = procesar(filas, list(mis_rfcs), memoria)
    except Exception as e:  # noqa: BLE001 — la inteligencia nunca debe impedir ver los datos
        resumen, error_intel = {}, str(e)
    motor = MotorSQL(filas)
    return {"carpeta": str(Path(carpeta)), "filas": filas, "resumen": resumen, "motor": motor,
            "nuevos": nuevos, "reusados": reusados, "error_intel": error_intel,
            "sin_perspectiva": sin_perspectiva(filas)}
