# -*- coding: utf-8 -*-
"""Orquestación completa de una descarga."""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List

from .almacen import Almacen
from .clasificador import clasificar_cfdi
from .config import Config, Opciones, Perfil
from .utilerias import ContadorDiario, Estado, con_reintentos, partir_por_mes

# Códigos del SAT (CodEstatus)
COD_OK = "5000"
COD_SIN_INFO = "5004"          # no hay CFDIs en ese rango
COD_AGOTADA = "5002"           # misma solicitud repetida demasiadas veces
COD_DUPLICADA = "5005"         # ya existe una solicitud igual en proceso
COD_MAX_CFDIS = "5008"         # > tope de CFDIs; hay que partir el rango

# EstadoSolicitud
EST_ACEPTADA, EST_PROCESO, EST_TERMINADA = "1", "2", "3"
EST_ERROR, EST_RECHAZADA, EST_VENCIDA = "4", "5", "6"
ESTADOS_CONOCIDOS = {EST_ACEPTADA, EST_PROCESO, EST_TERMINADA,
                     EST_ERROR, EST_RECHAZADA, EST_VENCIDA}
# El SAT a veces responde estado=0 con cod=404 (respuesta no documentada). Es
# pasajero: se sigue esperando, pero NO se gasta presupuesto de verificaciones.
MAX_RESPUESTAS_RARAS = 12


@dataclass
class Resumen:
    rfc: str = ""
    nombre: str = ""
    tramos: int = 0
    solicitudes_nuevas: int = 0
    xml_nuevos: int = 0
    xml_duplicados: int = 0
    paquetes: int = 0
    errores: List[str] = field(default_factory=list)

    def texto(self) -> str:
        s = (f"{self.nombre or self.rfc}: Tramos: {self.tramos} | Solicitudes nuevas: {self.solicitudes_nuevas} | "
             f"Paquetes: {self.paquetes} | XML nuevos: {self.xml_nuevos} | "
             f"Ya existían: {self.xml_duplicados} | Errores: {len(self.errores)}")
        if self.errores:
            s += "\n  - " + "\n  - ".join(self.errores)
        return s


class Descargador:
    def __init__(
        self,
        perfil: Perfil,
        opciones: Opciones,
        cliente,                      # ClienteSAT o un doble para pruebas
        logger: logging.Logger,
        dormir: Callable[[float], None] = time.sleep,
        clasificar: Callable = clasificar_cfdi,
        cancelado: Callable[[], bool] = lambda: False,
    ):
        self.perfil = perfil
        self.rfc = perfil.rfc
        self.op = opciones
        self.cli = cliente
        self.log = logger
        self.dormir = dormir
        self.clasificar = clasificar
        self.cancelado = cancelado
        self.almacen = Almacen(opciones.carpeta_salida, perfil.rfc)
        self.estado = Estado(perfil.archivo_estado(opciones))
        self.contador = ContadorDiario(perfil.archivo_contador(opciones), opciones.max_solicitudes_dia)

    # ------------------------------------------------------------------ público
    def ejecutar(self, desde: datetime, hasta: datetime, tipo: str) -> Resumen:
        self.log.info("=== %s (%s) %s..%s [%s] ===", self.perfil.nombre, self.rfc,
                      desde.strftime("%Y-%m-%d"), hasta.strftime("%Y-%m-%d"), tipo)
        tipos = ["emitidos", "recibidos"] if tipo == "ambos" else [tipo]
        tramos = list(partir_por_mes(desde, hasta)) if self.op.dividir_por_mes else [
            (desde.replace(hour=0, minute=0, second=0),
             hasta.replace(hour=23, minute=59, second=59))
        ]
        res = Resumen(rfc=self.rfc, nombre=self.perfil.nombre)
        for t in tipos:
            for ini, fin in tramos:
                if self.cancelado():
                    self.log.info("Cancelado por el usuario")
                    return res
                res.tramos += 1
                try:
                    self._procesar_tramo(t, ini, fin, res)
                except Exception as e:  # noqa: BLE001
                    msg = f"{t} {ini:%Y-%m-%d}..{fin:%Y-%m-%d}: {e}"
                    self.log.error(msg)
                    res.errores.append(msg)
        self.log.info("RESUMEN -> %s", res.texto())
        return res

    # ------------------------------------------------------------------ interno
    def _procesar_tramo(self, tipo: str, ini: datetime, fin: datetime, res: Resumen) -> None:
        etiqueta = f"[{tipo} {ini:%Y-%m-%d}..{fin:%Y-%m-%d}]"
        st = self.estado.obtener(tipo, ini, fin)

        if st.get("completado"):
            self.log.info("%s ya completado antes, se omite", etiqueta)
            return

        id_sol = st.get("id_solicitud")
        if not id_sol:
            id_sol = self._solicitar(tipo, ini, fin, etiqueta, res)
            if not id_sol:
                return
        else:
            self.log.info("%s retomando solicitud pendiente %s", etiqueta, id_sol)

        paquetes = self._esperar_paquetes(tipo, ini, fin, id_sol, etiqueta)
        if paquetes is None:
            return  # ya se registró el motivo

        ya = set(st.get("paquetes_descargados", []))
        for idp in paquetes:
            if idp in ya:
                self.log.info("%s paquete %s ya descargado, se omite", etiqueta, idp)
                continue
            self._descargar_y_guardar(tipo, idp, etiqueta, res)
            ya.add(idp)
            self.estado.marcar(tipo, ini, fin, paquetes_descargados=sorted(ya))

        self.estado.marcar(tipo, ini, fin, completado=True)

    def _solicitar(self, tipo, ini, fin, etiqueta, res):
        if self.contador.disponibles() <= 0:
            raise RuntimeError(
                f"tope diario de {self.op.max_solicitudes_dia} solicitudes alcanzado; "
                f"corre mañana o sube max_solicitudes_dia en config.json"
            )
        r = con_reintentos(
            lambda: self.cli.solicitar(self.rfc, tipo, ini, fin),
            self.op.reintentos, self.op.backoff_base_seg, self.log,
            f"{etiqueta} solicitar", self.dormir,
        )
        self.contador.registrar()
        res.solicitudes_nuevas += 1
        cod, msg, id_sol = r.get("cod_estatus"), r.get("mensaje"), r.get("id_solicitud")
        self.log.info("%s solicitud -> cod=%s id=%s msg=%s", etiqueta, cod, id_sol, msg)

        if cod == COD_OK and id_sol:
            self.estado.marcar(tipo, ini, fin, id_solicitud=id_sol, cod_solicitud=cod)
            return id_sol
        if cod == COD_SIN_INFO:
            self.log.info("%s sin CFDIs en el rango", etiqueta)
            self.estado.marcar(tipo, ini, fin, completado=True, cod_solicitud=cod, mensaje=msg)
            return None
        if cod == COD_DUPLICADA and id_sol:
            # el SAT nos regresa el id de la solicitud ya existente
            self.estado.marcar(tipo, ini, fin, id_solicitud=id_sol, cod_solicitud=cod)
            return id_sol
        if cod == COD_MAX_CFDIS:
            raise RuntimeError("demasiados CFDIs en el tramo; parte el rango en semanas (--sin-meses y rangos cortos)")
        if cod == COD_AGOTADA:
            raise RuntimeError(f"SAT: solicitud agotada de por vida para este rango ({msg}); cambia ligeramente las fechas")
        raise RuntimeError(f"SAT rechazó la solicitud cod={cod} msg={msg}")

    def _espera_polling(self, intento: int) -> float:
        """Espera creciente: al principio pregunta seguido, luego se calma.
        Así no se agota el presupuesto cuando el SAT tarda 20+ minutos."""
        base = self.op.poll_intervalo_seg
        if intento <= 4:
            return base
        if intento <= 10:
            return base * 2
        return min(base * 4, 120)

    def _esperar_paquetes(self, tipo, ini, fin, id_sol, etiqueta):
        intento = 0
        raras = 0
        while intento < self.op.poll_max_intentos:
            intento += 1
            v = con_reintentos(
                lambda: self.cli.verificar(self.rfc, id_sol),
                self.op.reintentos, self.op.backoff_base_seg, self.log,
                f"{etiqueta} verificar", self.dormir,
            )
            est, cod, n = v.get("estado_solicitud"), v.get("cod_estatus"), v.get("numero_cfdis")
            self.log.info("%s verificar %d/%d -> estado=%s cod=%s cfdis=%s paquetes=%d",
                          etiqueta, intento, self.op.poll_max_intentos, est, cod, n, len(v.get("paquetes", [])))

            if est == EST_TERMINADA:
                if not v.get("paquetes"):
                    self.log.info("%s terminada sin paquetes (0 CFDIs)", etiqueta)
                    self.estado.marcar(tipo, ini, fin, completado=True, numero_cfdis=n)
                    return None
                self.estado.marcar(tipo, ini, fin, numero_cfdis=n, paquetes=v["paquetes"])
                return v["paquetes"]
            if cod == COD_SIN_INFO:
                self.log.info("%s sin CFDIs (5004)", etiqueta)
                self.estado.marcar(tipo, ini, fin, completado=True, numero_cfdis=0)
                return None
            if est in (EST_ERROR, EST_RECHAZADA, EST_VENCIDA):
                # borramos el id para que la próxima corrida vuelva a solicitar
                self.estado.marcar(tipo, ini, fin, id_solicitud=None, error=f"estado={est} cod={cod} {v.get('mensaje')}")
                raise RuntimeError(f"solicitud {id_sol} terminó en estado {est} ({v.get('mensaje')})")

            if est not in ESTADOS_CONOCIDOS:
                # p.ej. estado=0 cod=404: respuesta rara del SAT, no es un
                # estado real. Se espera, pero sin consumir el presupuesto.
                raras += 1
                intento -= 1
                self.log.warning("%s el SAT respondió algo no documentado (estado=%s cod=%s); "
                                 "reintento %d/%d", etiqueta, est, cod, raras, MAX_RESPUESTAS_RARAS)
                if raras >= MAX_RESPUESTAS_RARAS:
                    self.estado.marcar(tipo, ini, fin, error=f"estado={est} cod={cod}")
                    raise RuntimeError(
                        f"el SAT lleva {raras} respuestas no documentadas (estado={est} cod={cod}) "
                        f"para la solicitud {id_sol}; vuelve a correr más tarde, se retoma sola")
                if self.cancelado():
                    raise RuntimeError("cancelado por el usuario mientras se esperaba el paquete")
                self.dormir(self._espera_polling(raras))
                continue

            if self.cancelado():
                raise RuntimeError("cancelado por el usuario mientras se esperaba el paquete")
            # 1 o 2: seguimos esperando
            if intento < self.op.poll_max_intentos:
                self.dormir(self._espera_polling(intento))

        raise RuntimeError(
            f"solicitud {id_sol} sigue en proceso tras {self.op.poll_max_intentos} verificaciones; "
            f"vuelve a correr más tarde, se retomará sola"
        )

    def _descargar_y_guardar(self, tipo, id_paquete, etiqueta, res):
        d = con_reintentos(
            lambda: self.cli.descargar_paquete(self.rfc, id_paquete),
            self.op.reintentos, self.op.backoff_base_seg, self.log,
            f"{etiqueta} descargar {id_paquete}", self.dormir,
        )
        if d.get("cod_estatus") not in (COD_OK, None) or not d.get("paquete_b64"):
            raise RuntimeError(f"paquete {id_paquete} no descargó: cod={d.get('cod_estatus')} {d.get('mensaje')}")
        nuevos, dup = self.almacen.guardar_paquete(d["paquete_b64"], tipo)
        res.paquetes += 1
        res.xml_nuevos += len(nuevos)
        res.xml_duplicados += dup
        self.log.info("%s paquete %s -> %d XML nuevos, %d ya existían", etiqueta, id_paquete, len(nuevos), dup)
        for ruta in nuevos:
            try:
                self.clasificar(ruta)
            except Exception as e:  # noqa: BLE001 - el hook no debe tumbar la descarga
                self.log.warning("clasificar_cfdi falló para %s: %s", ruta, e)
