# -*- coding: utf-8 -*-
"""Hook de clasificación. Se llama automáticamente por cada XML NUEVO guardado.

Por ahora no hace nada. Aquí es donde después metes tu lógica (tipo de
comprobante, proveedor, cuenta contable, subir a Supabase, etc.).
"""
from pathlib import Path


def clasificar_cfdi(xml_path: Path) -> None:
    # TODO: implementar clasificación. Recibe la ruta del XML ya guardado.
    pass
