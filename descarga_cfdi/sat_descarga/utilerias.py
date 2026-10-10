# -*- coding: utf-8 -*-
"""Utilerías: contador diario de solicitudes, estado de solicitudes pendientes,
reintentos con backoff y logging. Todo en archivos planos."""
import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Tuple, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------- logging
def configurar_log(archivo_log: str, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("sat_descarga")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    from .config import en_datos
    fh = logging.FileHandler(en_datos(archivo_log), encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(sh)
    logger.addHandler(fh)
    return logger


# ---------------------------------------------------------------- reintentos
def con_reintentos(
    fn: Callable[[], T],
    intentos: int,
    backoff_base: float,
    logger: logging.Logger,
    descripcion: str = "operación",
    dormir: Callable[[float], None] = time.sleep,
) -> T:
    """Ejecuta fn(); si truena, reintenta con backoff exponencial. Nunca deja
    el script a medias por un error de red pasajero."""
    ultimo: Exception = RuntimeError("sin intentos")
    for i in range(1, intentos + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - queremos capturar todo lo de red/SOAP
            ultimo = e
            espera = backoff_base * (2 ** (i - 1))
            logger.warning("%s falló (intento %d/%d): %s", descripcion, i, intentos, e)
            if i < intentos:
                dormir(espera)
    raise RuntimeError(f"{descripcion} falló tras {intentos} intentos: {ultimo}") from ultimo


# ---------------------------------------------------------------- contador diario
class ContadorDiario:
    """Cuenta solicitudes hechas hoy para no pasarnos del tope configurado."""

    def __init__(self, archivo: str, maximo: int, hoy: Callable[[], date] = date.today):
        self.archivo = Path(archivo)
        self.maximo = maximo
        self._hoy = hoy

    def _leer(self) -> Dict:
        if not self.archivo.exists():
            return {}
        try:
            return json.loads(self.archivo.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def usadas_hoy(self) -> int:
        return int(self._leer().get(self._hoy().isoformat(), 0))

    def disponibles(self) -> int:
        return max(0, self.maximo - self.usadas_hoy())

    def registrar(self) -> None:
        datos = self._leer()
        k = self._hoy().isoformat()
        datos = {k: int(datos.get(k, 0)) + 1}  # solo guardamos hoy
        self.archivo.write_text(json.dumps(datos), encoding="utf-8")


# ---------------------------------------------------------------- estado
class Estado:
    """Solicitudes que ya pedimos al SAT pero aún no descargamos.
    Si el script se corta, la siguiente corrida retoma en vez de volver a
    pedir (el SAT castiga solicitudes repetidas)."""

    def __init__(self, archivo: str):
        self.archivo = Path(archivo)
        self.datos: Dict[str, Dict] = self._leer()

    def _leer(self) -> Dict:
        if not self.archivo.exists():
            return {}
        try:
            return json.loads(self.archivo.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _escribir(self) -> None:
        self.archivo.write_text(json.dumps(self.datos, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def clave(tipo: str, desde: datetime, hasta: datetime) -> str:
        return f"{tipo}|{desde:%Y-%m-%d}|{hasta:%Y-%m-%d}"

    def obtener(self, tipo: str, desde: datetime, hasta: datetime) -> Dict:
        return self.datos.get(self.clave(tipo, desde, hasta), {})

    def marcar(self, tipo: str, desde: datetime, hasta: datetime, **campos) -> None:
        k = self.clave(tipo, desde, hasta)
        actual = self.datos.get(k, {})
        actual.update(campos)
        actual["actualizado"] = datetime.now().isoformat(timespec="seconds")
        self.datos[k] = actual
        self._escribir()


# ---------------------------------------------------------------- rangos
def partir_por_mes(desde: datetime, hasta: datetime) -> Iterator[Tuple[datetime, datetime]]:
    """[desde, hasta] -> tramos mensuales inclusivos, con horas 00:00:00 / 23:59:59."""
    ini = desde.replace(hour=0, minute=0, second=0, microsecond=0)
    fin_total = hasta.replace(hour=23, minute=59, second=59, microsecond=0)
    while ini <= fin_total:
        # último día del mes de `ini`
        primero_sig = (ini.replace(day=1) + timedelta(days=32)).replace(day=1)
        fin_mes = (primero_sig - timedelta(seconds=1))
        fin = min(fin_mes, fin_total)
        yield ini, fin
        ini = fin + timedelta(seconds=1)
