# -*- coding: utf-8 -*-
"""Fase 1 — regresión del bug "la tabla se queda estática y las tarjetas en $0":
a) filtros que sobreviven a otra lectura, b) lectura en hilo con avance y
cancelar, c) comprobantes sin perspectiva, d) rendimiento con 5,000 XML.
"""
import os
import time
from pathlib import Path

import pytest

from sat_descarga.inteligencia import candidatos_dueno, rfc_sugerido, sin_perspectiva
from sat_descarga.lector import LecturaCancelada, leer_carpeta
from test_lector import cfdi40

DUENO = "HIHR900307P61"


def _carpeta_plana(base: Path, n_gasto=3, n_ingreso=2, mes="08", prefijo="1"):
    """XML sueltos (sin subcarpetas emitidos/recibidos), como en Google Drive."""
    base.mkdir(parents=True, exist_ok=True)
    for i in range(n_gasto):
        (base / f"g{i}.xml").write_bytes(cfdi40(
            uuid=f"{prefijo}{i:07d}-0000-0000-0000-000000000001",
            fecha=f"2026-{mes}-1{i}T10:00:00", emisor="PRO010101AAA", receptor=DUENO))
    for i in range(n_ingreso):
        (base / f"i{i}.xml").write_bytes(cfdi40(
            uuid=f"{prefijo}{i:07d}-0000-0000-0000-000000000002",
            fecha=f"2026-{mes}-2{i}T10:00:00", emisor=DUENO, receptor="CLI020202BBB"))
    return str(base)


def _bombear(app, condicion, limite=30):
    fin = time.time() + limite
    while not condicion() and time.time() < fin:
        app._procesar_cola(); app.update(); time.sleep(0.01)
    app._procesar_cola(); app.update()


# ================================================================ c) lógica pura
def test_rfc_sugerido_es_el_mas_frecuente(tmp_path):
    filas = leer_carpeta(_carpeta_plana(tmp_path / "x"))
    assert sin_perspectiva(filas) == 5
    rfc, nombre, n = rfc_sugerido(filas)
    assert rfc == DUENO and n == 5
    assert [c[0] for c in candidatos_dueno(filas)][0] == DUENO


def test_sin_perspectiva_cuenta_comprobantes_no_renglones(tmp_path):
    filas = leer_carpeta(_carpeta_plana(tmp_path / "x", n_gasto=1, n_ingreso=0))
    filas = filas + filas                        # mismo CFDI dos veces
    assert sin_perspectiva(filas) == 1


def test_rfc_sugerido_sin_filas():
    assert rfc_sugerido([]) is None


# ================================================================ b) lector cancelable
def test_lector_se_puede_cancelar(tmp_path):
    carpeta = _carpeta_plana(tmp_path / "x", n_gasto=40, n_ingreso=0)
    with pytest.raises(LecturaCancelada):
        leer_carpeta(carpeta, cancelado=lambda: True)


def test_lector_reporta_avance_con_total(tmp_path):
    carpeta = _carpeta_plana(tmp_path / "x", n_gasto=7, n_ingreso=0)
    vistos = []
    leer_carpeta(carpeta, progreso=lambda i, t: vistos.append((i, t)))
    assert vistos[0] == (0, 7) and vistos[-1] == (7, 7)


def test_lector_en_paralelo_conserva_el_orden(tmp_path):
    carpeta = _carpeta_plana(tmp_path / "x", n_gasto=300, n_ingreso=0)
    archivos = [Path(r.datos["Archivo"]).name for r in leer_carpeta(carpeta)]
    assert archivos == sorted(archivos)


# ================================================================ UI
tk = pytest.importorskip("tkinter")


@pytest.fixture
def app(tmp_path, monkeypatch):
    try:
        r = tk.Tk(); r.withdraw(); r.destroy()
    except tk.TclError as e:
        pytest.skip(f"sin display: {e}")
    monkeypatch.chdir(tmp_path)
    import app as modulo
    monkeypatch.setattr(modulo.messagebox, "showinfo", lambda *a, **k: None)
    a = modulo.App(ruta_config=str(tmp_path / "config.json"))
    a.withdraw()
    yield a
    a._cancelar_lectura.set()
    if a._hilo_lectura is not None:
        a._hilo_lectura.join(10)
    try:
        a.after_cancel(a._after_cola)
    except tk.TclError:
        pass
    try:
        a.destroy()
    except tk.TclError:
        pass


# ---------------------------------------------------------------- a) filtros
def test_filtros_se_resetean_al_leer_otra_carpeta(app, tmp_path):
    """El bug real: Mes quedaba en 2026-09 de la lectura anterior y la tabla
    nueva salía vacía."""
    app._rfcs_dueno_extra.add(DUENO)
    app.v_carpeta_datos.set(_carpeta_plana(tmp_path / "sept", mes="09", prefijo="9"))
    app._leer_datos(esperar=True)
    app.v_f_mes.set("2026-09"); app.v_f_tipo.set("Recibido"); app.v_buscar.set("PRO")
    app._filtrar_clase("G")
    assert len(app.filas_vista) == 3

    app.v_carpeta_datos.set(_carpeta_plana(tmp_path / "ago", mes="08", prefijo="8"))
    app._leer_datos(esperar=True)
    assert app.v_f_mes.get() == "todos" and app.v_f_tipo.get() == "todos"
    assert app.v_buscar.get() == "" and app._clase_filtro is None
    assert len(app.filas_vista) == 5
    assert len(app.tabla_datos.get_children()) == 5
    assert app._chips["gastos"].cget("text") != "$ 0.00"


def test_misma_carpeta_valida_filtros_que_ya_no_existen(app, tmp_path):
    app._rfcs_dueno_extra.add(DUENO)
    app.v_carpeta_datos.set(_carpeta_plana(tmp_path / "x", mes="08"))
    app._leer_datos(esperar=True)
    app.v_f_mes.set("2026-09")                    # mes que ya no está en la carpeta
    app.v_f_tipo.set("Recibido")                  # sigue siendo válido
    app._leer_datos(esperar=True)
    assert app.v_f_mes.get() == "todos"
    assert app.v_f_tipo.get() == "Recibido"
    assert len(app.filas_vista) == 3


def test_barra_de_estado_muestra_filtros_activos(app, tmp_path):
    app._rfcs_dueno_extra.add(DUENO)
    app.v_carpeta_datos.set(_carpeta_plana(tmp_path / "x"))
    app._leer_datos(esperar=True)
    assert app.v_filtros.get() == "Sin filtros"
    app.v_f_mes.set("2026-08"); app._filtrar_clase("I")
    assert "Mes 2026-08" in app.v_totales.get() and "Clase I" in app.v_totales.get()
    assert "Mes 2026-08" in app.v_filtros.get()
    app._limpiar_filtros()
    assert "filtros" not in app.v_totales.get()


# ---------------------------------------------------------------- b) hilo
def test_leer_no_congela_la_ventana(app, tmp_path):
    app._rfcs_dueno_extra.add(DUENO)
    app.v_carpeta_datos.set(_carpeta_plana(tmp_path / "x", n_gasto=1500, n_ingreso=0))
    latidos = []

    def latir():
        latidos.append(time.time())
        app.after(20, latir)
    app.after(20, latir)
    t0 = time.time()
    app._leer_datos()                              # regresa de inmediato
    assert time.time() - t0 < 1.0
    assert str(app.btn_leer.cget("state")) == "disabled"
    _bombear(app, lambda: not app._hilo_lectura.is_alive() and len(app.filas) == 1500, 60)
    assert len(app.filas) == 1500 and len(latidos) > 3       # el bucle de Tk siguió vivo
    assert str(app.btn_leer.cget("state")) == "normal"
    assert len(app.tabla_datos.get_children()) == 1500


def test_cancelar_lectura_conserva_lo_anterior(app, tmp_path, monkeypatch):
    app._rfcs_dueno_extra.add(DUENO)
    app.v_carpeta_datos.set(_carpeta_plana(tmp_path / "a"))
    app._leer_datos(esperar=True)
    assert len(app.filas) == 5
    import sat_descarga.lector as lector
    monkeypatch.setattr(lector, "VENTANA_LECTURA", 1)
    app.v_carpeta_datos.set(_carpeta_plana(tmp_path / "b", n_gasto=400, n_ingreso=0, prefijo="7"))
    app._leer_datos()
    app._cancelar_leer()
    _bombear(app, lambda: not app._hilo_lectura.is_alive())
    assert "cancelada" in app.v_totales.get()
    assert len(app.filas) == 5
    assert str(app.btn_leer.cget("state")) == "normal"


def test_avance_se_pinta_en_la_barra(app):
    app._estado_lectura(True)
    app._progreso_lectura(250, 1000)
    assert "250 / 1,000" in app.v_totales.get()
    assert float(app.barra_lectura.cget("value")) == 250
    app._estado_lectura(False)


# ---------------------------------------------------------------- c) perspectiva en la UI
def test_aviso_sin_perspectiva_y_asignar_dueno(app, tmp_path):
    """Sin subcarpetas emitidos/recibidos ni RFC registrado: nunca en silencio."""
    app.v_carpeta_datos.set(_carpeta_plana(tmp_path / "x"))
    app._leer_datos(esperar=True)
    assert app.aviso_persp.winfo_manager() == "pack"
    assert "5 comprobantes sin perspectiva" in app.lbl_persp.cget("text")
    assert DUENO in app.lbl_persp.cget("text")
    assert app._chips["ingresos"].cget("text") == "$ 0.00"

    app.btn_persp_si.invoke()                      # "Sí, es el dueño"
    assert app.aviso_persp.winfo_manager() == ""
    clases = sorted(r.datos["Clase"] for r in app.filas)
    assert clases == ["G", "G", "G", "I", "I"]
    assert app._chips["ingresos"].cget("text") == "$ 2,320.00"
    assert app._badges["G"].cget("text").split() == ["G", "3"]
    # la siguiente lectura ya sabe quién es el dueño
    app._leer_datos(esperar=True)
    assert sin_perspectiva(app.filas) == 0


def test_dialogo_para_elegir_otro_dueno(app, tmp_path):
    import app as modulo
    app.v_carpeta_datos.set(_carpeta_plana(tmp_path / "x"))
    app._leer_datos(esperar=True)
    elegidos = []
    dlg = modulo.DialogoDueno(app, candidatos_dueno(app.filas), elegidos.append)
    assert dlg.v_rfc.get() == DUENO
    dlg.lista.selection_clear(0, "end"); dlg.lista.selection_set(1); dlg._al_elegir()
    otro = dlg.v_rfc.get()
    dlg._aplicar()
    assert elegidos == [otro] and otro != DUENO


# ================================================================ d) rendimiento
@pytest.mark.skipif(os.environ.get("DXE_SIN_RENDIMIENTO") == "1", reason="rendimiento desactivado")
def test_rendimiento_5000_xml(tmp_path):
    """Lectura + inteligencia + SQL de 5,000 XML en < 10 s (archivos ya vistos
    por el sistema, como los que ya descargaste). La primera vez que el antivirus
    revisa archivos recién creados puede tardar más; ese tiempo se reporta."""
    from sat_descarga.inteligencia import Memoria
    from sat_descarga.lectura import leer_y_procesar
    base = tmp_path / "cinco_mil"; base.mkdir()
    for i in range(5000):
        (base / f"{i:05d}.xml").write_bytes(cfdi40(
            uuid=f"{i:08d}-2222-3333-4444-555555555555",
            fecha=f"2026-{(i % 12) + 1:02d}-15T10:00:00",
            emisor=DUENO if i % 3 == 0 else "PRO010101AAA",
            receptor="CLI020202BBB" if i % 3 == 0 else DUENO))
    mem = Memoria(str(tmp_path / "m.json"))
    t0 = time.time()
    leer_y_procesar(str(base), str(tmp_path / "i.csv"), [DUENO], mem)
    frio = time.time() - t0
    t0 = time.time()
    res = leer_y_procesar(str(base), str(tmp_path / "i.csv"), [DUENO], mem)
    tibio = time.time() - t0
    print(f"\n5,000 XML: primera lectura {frio:.1f}s · lectura normal {tibio:.1f}s")
    assert len(res["filas"]) == 5000 and res["sin_perspectiva"] == 0
    assert res["reusados"] == 5000
    assert tibio < 10
