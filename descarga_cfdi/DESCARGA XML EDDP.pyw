# -*- coding: utf-8 -*-
"""Doble clic aquí para abrir DESCARGA XML EDDP (sin ventana negra de consola).
Si algo falla al arrancar, se muestra el error y se guarda en arranque_error.txt
dentro de la carpeta de datos."""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app import main
    main()
except Exception:  # noqa: BLE001
    detalle = traceback.format_exc()
    try:
        from sat_descarga.config import carpeta_datos
        (carpeta_datos() / "arranque_error.txt").write_text(detalle, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw()
        messagebox.showerror("DESCARGA XML EDDP",
                             "No pudo arrancar. Casi siempre falta instalar dependencias:\n\n"
                             "    pip install -r requirements.txt\n\n" + detalle[-900:])
    except Exception:  # noqa: BLE001
        pass
