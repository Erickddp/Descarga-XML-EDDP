# -*- coding: utf-8 -*-
"""Respaldo y restauración: mueve TODO a otra computadora en un solo .zip.

Incluye: RFCs (nombre, contraseña de la llave), copias de los .cer/.key,
historial de solicitudes al SAT, configuración del PDF, perfiles de reporte,
logos y la memoria de pagos. Al restaurar, las rutas de las e.firmas se reescriben a la carpeta de
datos de la nueva computadora: no hay que volver a buscarlas.

OJO: el respaldo contiene tus llaves privadas y contraseñas. Trátalo como un
documento confidencial.
"""
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .config import Config, Perfil, carpeta_datos
from .perfiles import ARCHIVO as ARCHIVO_PERFILES, Perfiles

FORMATO = 1


def _seguro(nombre: str) -> str:
    """Solo el nombre base: impide que un zip escriba fuera de la carpeta destino."""
    return Path(str(nombre).replace("\\", "/")).name


def crear_respaldo(destino_zip: str, cfg: Config, incluir_efirmas: bool = True) -> Dict:
    datos = carpeta_datos()
    destino = Path(destino_zip)
    destino.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"app": "DESCARGA XML EDDP", "formato": FORMATO,
                "creado": datetime.now().isoformat(timespec="seconds"), "perfiles": []}
    res = {"perfiles": 0, "efirmas": 0, "archivos": 0, "ruta": str(destino), "faltantes": []}

    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("config.json", json.dumps(cfg.a_dict(), indent=2, ensure_ascii=False))
        for p in cfg.perfiles:
            entrada = {"id": p.id, "rfc": p.rfc, "nombre": p.nombre, "cer": "", "key": ""}
            if incluir_efirmas:
                for campo, ruta in (("cer", p.cer_path), ("key", p.key_path)):
                    if ruta and Path(ruta).exists():
                        arc = f"efirmas/{p.id}/{_seguro(ruta)}"
                        z.write(ruta, arc)
                        entrada[campo] = arc
                        res["efirmas"] += 1
                    elif ruta:
                        res["faltantes"].append(f"{p.nombre}: {ruta}")
            manifest["perfiles"].append(entrada)
            res["perfiles"] += 1

        # configuración del PDF, perfiles de reporte y TODOS los logos que usan
        logos = set()
        pdf_cfg = datos / "pdf_config.json"
        if pdf_cfg.exists():
            z.write(pdf_cfg, "pdf_config.json"); res["archivos"] += 1
            try:
                pc = json.loads(pdf_cfg.read_text(encoding="utf-8"))
                logos.add(pc.get("general", {}).get("logo", ""))
                logos |= {v.get("logo", "") for v in (pc.get("por_rfc") or {}).values()
                          if isinstance(v, dict)}
            except (OSError, ValueError):
                pass
        perfiles = datos / ARCHIVO_PERFILES
        if perfiles.exists():
            z.write(perfiles, ARCHIVO_PERFILES); res["archivos"] += 1
            logos |= set(Perfiles.cargar(str(perfiles)).logos())
        ya = set()
        for lg in sorted(x for x in logos if x):
            if Path(lg).exists() and _seguro(lg) not in ya:
                ya.add(_seguro(lg))
                z.write(lg, f"logos/{_seguro(lg)}"); res["archivos"] += 1

        # memoria, historial de solicitudes
        for patron in ("memoria.json", "estado_solicitudes_*.json", "contador_solicitudes_*.json"):
            for f in datos.glob(patron):
                z.write(f, f"datos/{f.name}"); res["archivos"] += 1

        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    return res


def restaurar_respaldo(zip_path: str, ruta_config: Optional[str] = None) -> Dict:
    datos = carpeta_datos()
    res = {"nuevos": 0, "actualizados": 0, "efirmas": 0, "pdf_config": False,
           "memoria": 0, "archivos": 0, "perfiles_reporte": 0}
    with zipfile.ZipFile(zip_path) as z:
        nombres = set(z.namelist())
        if "manifest.json" not in nombres or "config.json" not in nombres:
            raise ValueError("Ese archivo no es un respaldo de DESCARGA XML EDDP.")
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        respaldo_cfg = Config.desde_dict(json.loads(z.read("config.json").decode("utf-8")),
                                         ruta_config)
        actual = Config.desde_archivo(ruta_config)
        era_nueva = not actual.perfiles

        # e.firmas -> carpeta de datos, reescribiendo rutas
        rutas = {}
        for e in manifest.get("perfiles", []):
            carpeta = datos / "efirmas" / f"{_seguro(e.get('rfc', 'RFC'))}_{_seguro(e.get('id', 'x'))}"
            for campo in ("cer", "key"):
                arc = e.get(campo) or ""
                if arc and arc in nombres:
                    carpeta.mkdir(parents=True, exist_ok=True)
                    destino = carpeta / _seguro(arc)
                    destino.write_bytes(z.read(arc))
                    rutas.setdefault(e.get("id"), {})[campo] = str(destino)
                    res["efirmas"] += 1

        for p in respaldo_cfg.perfiles:
            r = rutas.get(p.id, {})
            nuevo = Perfil(rfc=p.rfc, cer_path=r.get("cer", p.cer_path),
                           key_path=r.get("key", p.key_path), key_password=p.key_password,
                           nombre=p.nombre, activo=p.activo, id=p.id)
            if actual.por_id(p.id):
                res["actualizados"] += 1
            else:
                res["nuevos"] += 1
            actual.agregar(nuevo)
        if era_nueva:
            actual.opciones = respaldo_cfg.opciones
        actual.guardar()

        # logos
        logos_dir = datos / "logos"
        mapa_logos = {}
        for n in nombres:
            if n.startswith("logos/") and not n.endswith("/"):
                logos_dir.mkdir(parents=True, exist_ok=True)
                destino = logos_dir / _seguro(n)
                destino.write_bytes(z.read(n))
                mapa_logos[_seguro(n)] = str(destino)
                res["archivos"] += 1

        # configuración del PDF (la local queda como .bak)
        if "pdf_config.json" in nombres:
            pc = json.loads(z.read("pdf_config.json").decode("utf-8"))

            def _remap(v):
                return mapa_logos.get(_seguro(v), v) if v else v
            if isinstance(pc.get("general"), dict):
                pc["general"]["logo"] = _remap(pc["general"].get("logo", ""))
            for v in (pc.get("por_rfc") or {}).values():
                if isinstance(v, dict):
                    v["logo"] = _remap(v.get("logo", ""))
            local = datos / "pdf_config.json"
            if local.exists():
                shutil.copy2(local, local.with_suffix(".json.bak"))
            local.write_text(json.dumps(pc, indent=2, ensure_ascii=False), encoding="utf-8")
            res["pdf_config"] = True

        # perfiles de reporte: se FUSIONAN por id (la versión local queda como .bak)
        if ARCHIVO_PERFILES in nombres:
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                t = Path(tmp) / ARCHIVO_PERFILES
                t.write_bytes(z.read(ARCHIVO_PERFILES))
                entrantes = Perfiles.cargar(str(t))
            local = datos / ARCHIVO_PERFILES
            if local.exists():
                shutil.copy2(local, local.with_suffix(".json.bak"))
            # sin perfiles locales: NO migrar el pdf_config recién restaurado (duplicaría)
            actuales = Perfiles.cargar(str(local)) if local.exists() else Perfiles(str(local))
            r = actuales.fusionar(entrantes, remap_logo=lambda v: mapa_logos.get(_seguro(v), v) if v else v)
            if not actuales.activo_id and entrantes.activo_id:
                actuales.activar(entrantes.activo_id)
            actuales.guardar()
            res["perfiles_reporte"] = r["nuevos"] + r["actualizados"]

        # memoria (se FUSIONA, no se pisa) e historial (solo si no existe)
        for n in nombres:
            if not n.startswith("datos/") or n.endswith("/"):
                continue
            nombre = _seguro(n)
            destino = datos / nombre
            if nombre == "memoria.json":
                entrante = json.loads(z.read(n).decode("utf-8"))
                existente = {}
                if destino.exists():
                    try:
                        existente = json.loads(destino.read_text(encoding="utf-8"))
                    except ValueError:
                        existente = {}
                fusion = {"version": 1,
                          "pagos": {**entrante.get("pagos", {}), **existente.get("pagos", {})},
                          "facturas": {**entrante.get("facturas", {}), **existente.get("facturas", {})}}
                destino.write_text(json.dumps(fusion, ensure_ascii=False), encoding="utf-8")
                res["memoria"] = len(fusion["pagos"]) + len(fusion["facturas"])
            elif not destino.exists():
                destino.write_bytes(z.read(n))
                res["archivos"] += 1
    return res
