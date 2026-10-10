# -*- coding: utf-8 -*-
"""Interfaz gráfica para la descarga masiva de XML del SAT.

Arranca con:  python app.py
No requiere instalar nada extra: tkinter viene incluido con Python en Windows.
"""
import logging
import queue
import threading
import traceback
from datetime import date, datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from sat_descarga.almacen import migrar_estructura_vieja
from sat_descarga.exportar import (Indice, a_csv, a_csv_cols, a_excel, a_tsv, a_tsv_cols,
                                   leer_carpeta_con_indice, matriz_a_csv, matriz_a_tsv)
from sat_descarga.lector import (CLASES, COLUMNAS, COLUMNAS_COPIADO, leer_detalle, totales,
                                 volcado_xml)
from sat_descarga.certificado import datos_del_cer, rfc_de_nombre_archivo
from sat_descarga.config import (NOMBRE_APP, Config, Perfil, carpeta_datos, en_datos,
                                 migrar_datos_viejos)
from sat_descarga.consulta import CONSULTAS_EJEMPLO, MotorSQL
from sat_descarga.ejecutor import ejecutar_varios, probar_efirma, resumen_global
from sat_descarga.inteligencia import (Memoria, asignar_perspectiva, candidatos_dueno, procesar,
                                       rfc_sugerido, sin_perspectiva)
from sat_descarga.lectura import LecturaCancelada, leer_y_procesar
from sat_descarga.pdf import cfdi_a_pdf, dueno_de, generar_pdfs, nombre_pdf, plantilla_de
from sat_descarga.perfiles import (FILTROS_DEFAULT, SECCIONES, SUBCARPETAS, PerfilReporte,
                                   Perfiles, completar_diseno)
from sat_descarga.respaldo import crear_respaldo, restaurar_respaldo
from sat_descarga.tema import Tema

APP = "DESCARGA XML EDDP"
APP_TITULO = "DESCARGA XML EDDP"
MAX_FILAS_TABLA = 3000          # la tabla muestra hasta esto; exporta todo
NUMERICAS_UI = {"SubTotal", "Descuento", "IVA Trasladado", "IEPS Trasladado",
                "IVA Retenido", "ISR Retenido", "Total", "Conceptos", "Tipo Cambio"}


# ---------------------------------------------------------------- logging a la UI
class ColaHandler(logging.Handler):
    def __init__(self, cola: queue.Queue):
        super().__init__()
        self.cola = cola

    def emit(self, record):
        try:
            self.cola.put(self.format(record))
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- diálogo de perfil
class DialogoPerfil(tk.Toplevel):
    """Alta/edición de un RFC. Aquí están los botones 'Buscar...' para el .cer y .key."""

    def __init__(self, padre, perfil: Perfil = None, titulo="Agregar RFC"):
        super().__init__(padre)
        self.title(titulo)
        self.resultado = None
        self.transient(padre)
        self.resizable(False, False)

        tema = getattr(padre, "tema", None)
        if tema is not None:
            self.configure(bg=tema.color("surface"))

        p = perfil or Perfil()
        self.v_nombre = tk.StringVar(value=p.nombre if p.rfc else "")
        self.v_rfc = tk.StringVar(value=p.rfc)
        self.v_cer = tk.StringVar(value=p.cer_path)
        self.v_key = tk.StringVar(value=p.key_path)
        self.v_pass = tk.StringVar(value=p.key_password)
        self.v_ver = tk.BooleanVar(value=False)

        m = ttk.Frame(self, padding=20, style="Surface.TFrame")
        m.grid(sticky="nsew")

        ttk.Label(m, text=titulo, style="Sub.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))

        def etiqueta(txt, r):
            ttk.Label(m, text=txt, style="SuaveSurface.TLabel").grid(
                row=r, column=0, columnspan=3, sticky="w", pady=(6, 2))

        etiqueta("Nombre  ·  como lo quieras ver en la lista", 1)
        ttk.Entry(m, textvariable=self.v_nombre, width=54).grid(
            row=2, column=0, columnspan=3, sticky="we", pady=(0, 4))

        etiqueta("RFC  ·  lo detecta del certificado", 3)
        e_rfc = ttk.Entry(m, textvariable=self.v_rfc, width=54)
        e_rfc.grid(row=4, column=0, columnspan=3, sticky="we", pady=(0, 4))

        etiqueta("Certificado de la e.firma  (.cer)", 5)
        ttk.Entry(m, textvariable=self.v_cer, width=44).grid(row=6, column=0, columnspan=2, sticky="we")
        ttk.Button(m, text="Buscar…", command=self._buscar_cer).grid(row=6, column=2, sticky="we", padx=(8, 0))

        etiqueta("Llave privada de la e.firma  (.key)", 7)
        ttk.Entry(m, textvariable=self.v_key, width=44).grid(row=8, column=0, columnspan=2, sticky="we")
        ttk.Button(m, text="Buscar…", command=self._buscar_key).grid(row=8, column=2, sticky="we", padx=(8, 0))

        etiqueta("Contraseña de la LLAVE PRIVADA  ·  no es tu CIEC del portal", 9)
        self.e_pass = ttk.Entry(m, textvariable=self.v_pass, width=44, show="•")
        self.e_pass.grid(row=10, column=0, columnspan=2, sticky="we")
        ttk.Checkbutton(m, text="Ver", variable=self.v_ver, command=self._toggle,
                        style="Surface.TCheckbutton").grid(row=10, column=2, sticky="w", padx=(8, 0))

        b = ttk.Frame(m, style="Surface.TFrame")
        b.grid(row=11, column=0, columnspan=3, sticky="e", pady=(18, 0))
        ttk.Button(b, text="Cancelar", style="Ghost.TButton",
                   command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(b, text="Guardar", style="Primary.TButton",
                   command=self._guardar).grid(row=0, column=1)

        m.columnconfigure(0, weight=1)
        e_rfc.focus_set()
        self.bind("<Return>", lambda _e: self._guardar())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    def _toggle(self):
        self.e_pass.config(show="" if self.v_ver.get() else "•")

    def _buscar_cer(self):
        r = filedialog.askopenfilename(
            title="Selecciona el certificado .cer de la e.firma",
            filetypes=[("Certificado", "*.cer"), ("Todos", "*.*")], parent=self)
        if r:
            self.v_cer.set(r)
            self._leer_certificado(r)

    def _buscar_key(self):
        r = filedialog.askopenfilename(
            title="Selecciona la llave .key de la e.firma",
            filetypes=[("Llave privada", "*.key"), ("Todos", "*.*")], parent=self)
        if r:
            self.v_key.set(r)
            if not self.v_cer.get():
                cand = Path(r).with_suffix(".cer")
                if cand.exists():
                    self.v_cer.set(str(cand))
                    self._leer_certificado(str(cand))
            if not self.v_rfc.get().strip():
                rfc = rfc_de_nombre_archivo(r)
                if rfc:
                    self.v_rfc.set(rfc)

    def _leer_certificado(self, ruta: str):
        """El RFC lo dicta el certificado, no el usuario: así no se confunden
        dos e.firmas distintas."""
        rfc = nombre = None
        try:
            rfc, nombre = datos_del_cer(ruta)
        except Exception:  # noqa: BLE001
            pass
        if not rfc:
            rfc = rfc_de_nombre_archivo(ruta)
        if rfc:
            anterior = self.v_rfc.get().strip().upper()
            self.v_rfc.set(rfc)
            if anterior and anterior != rfc:
                messagebox.showwarning(
                    "RFC corregido",
                    f"El certificado pertenece a {rfc}, no a {anterior}.\n"
                    "Se corrigió el RFC para que no se mezclen dos contribuyentes.",
                    parent=self)
        if nombre and not self.v_nombre.get().strip():
            self.v_nombre.set(nombre)

    def _guardar(self):
        p = Perfil(
            rfc=self.v_rfc.get(), cer_path=self.v_cer.get().strip(),
            key_path=self.v_key.get().strip(), key_password=self.v_pass.get(),
            nombre=self.v_nombre.get().strip(),
        )
        errs = p.errores()
        if errs:
            messagebox.showerror("Faltan datos", "\n• " + "\n• ".join(errs), parent=self)
            return
        self.resultado = p
        self.destroy()


# ---------------------------------------------------------------- ventana principal
class App(tk.Tk):
    def __init__(self, ruta_config=None):
        super().__init__()
        self.title(APP)
        self.geometry("1180x820")
        self.minsize(940, 600)
        # arrancar maximizado para que todo quepa; si el gestor no lo soporta, no pasa nada
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                pass

        # datos de versiones anteriores (junto al programa) -> carpeta fija del usuario
        self._migrados = migrar_datos_viejos() if ruta_config is None else []
        self.cfg = Config.desde_archivo(ruta_config)
        self.cola = queue.Queue()
        self.hilo = None
        self._cancelar = threading.Event()
        self._orden_rev = {}
        self.resumen_intel = {}
        self.memoria = Memoria(str(Path(self.cfg.ruta).parent / "memoria.json"))
        # perfiles de reporte (multi-cliente); la 1a vez migra pdf_config.json
        self.perfiles_rep = Perfiles.cargar(str(Path(self.cfg.ruta).parent / "perfiles_reporte.json"))

        self.tema = Tema(self, self.cfg.opciones.tema or "claro")
        self._poner_icono()
        self._construir()
        self._configurar_log()
        self._refrescar_lista()
        self.tema.aplicar_zoom(self.cfg.opciones.zoom or 1.0)
        for seq, delta in (("<Control-plus>", 0.1), ("<Control-equal>", 0.1),
                           ("<Control-minus>", -0.1), ("<Control-KP_Add>", 0.1),
                           ("<Control-KP_Subtract>", -0.1)):
            self.bind_all(seq, lambda _e, d=delta: self._zoom(d))
        self.bind_all("<Control-0>", lambda _e: self._zoom(None))
        if self._migrados:
            self.log.info("Se trajeron tus datos anteriores a %s: %s",
                          carpeta_datos(), ", ".join(self._migrados))
        self._after_cola = self.after(120, self._vaciar_cola)
        self.protocol("WM_DELETE_WINDOW", self._cerrar)

    # ---------------- UI
    def _construir(self):
        cont = ttk.Frame(self, style="TFrame")
        cont.pack(fill="both", expand=True)

        self._construir_encabezado(cont)

        self.nb = ttk.Notebook(cont)
        self.nb.pack(fill="both", expand=True, padx=16, pady=(4, 12))

        raiz_tab = ttk.Frame(self.nb, padding=(4, 8))
        self.nb.add(raiz_tab, text="   Descargar   ")
        raiz = self._area_scroll(raiz_tab)

        self.tab_datos = ttk.Frame(self.nb, padding=(4, 12))
        self.nb.add(self.tab_datos, text="   Datos y Excel   ")
        self._construir_datos(self.tab_datos)

        self._construir_descarga(raiz)

    def _area_scroll(self, padre):
        """Devuelve un frame interior con scroll vertical, para que el contenido
        largo (lista + periodo + registro) siempre se alcance aunque la ventana
        sea chica."""
        c = self.tema.color
        canvas = tk.Canvas(padre, bg=c("bg"), highlightthickness=0, bd=0)
        vs = ttk.Scrollbar(padre, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vs.set)
        canvas.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")

        interior = ttk.Frame(canvas, style="TFrame")
        ventana = canvas.create_window((0, 0), window=interior, anchor="nw")

        def _ajustar(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(ventana, width=canvas.winfo_width())
        interior.bind("<Configure>", _ajustar)
        canvas.bind("<Configure>", _ajustar)

        # rueda del mouse: local al canvas (no bind_all, que es global y deja
        # bindings colgando entre ventanas)
        def _rueda(e):
            if not canvas.winfo_exists():
                return
            paso = -1 if getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4 else 1
            canvas.yview_scroll(paso, "units")

        def _al_entrar(_e):
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.bind_all(seq, _rueda)

        def _al_salir(_e):
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.unbind_all(seq)

        canvas.bind("<Enter>", _al_entrar)
        canvas.bind("<Leave>", _al_salir)
        canvas.bind("<Destroy>", lambda _e: _al_salir(_e))
        return interior

    def _construir_encabezado(self, cont):
        c = self.tema.color
        barra = tk.Frame(cont, bg=c("surface"), height=58)
        barra.pack(fill="x", side="top")
        barra.pack_propagate(False)
        linea = tk.Frame(cont, bg=c("border"), height=1)
        linea.pack(fill="x", side="top")

        tk.Label(barra, text="◆", bg=c("surface"), fg=c("primary"),
                 font=self.tema.fuente("titulo")).pack(side="left", padx=(18, 8))
        tk.Label(barra, text=APP_TITULO, bg=c("surface"), fg=c("text"),
                 font=self.tema.fuente("titulo")).pack(side="left")

        self.v_tema = tk.StringVar(value=self.cfg.opciones.tema or "claro")

        def boton(texto, cmd, tip=""):
            b = tk.Button(barra, text=texto, bd=0, relief="flat", padx=8, highlightthickness=0,
                          bg=c("surface"), fg=c("text_soft"), activebackground=c("surface_alt"),
                          activeforeground=c("text"), cursor="hand2",
                          font=self.tema.fuente("chico"), command=cmd)
            b.pack(side="right", padx=2)
            return b

        boton("◐  Tema", self._alternar_tema)
        boton("A+", lambda: self._zoom(0.1))
        boton("A−", lambda: self._zoom(-0.1))
        tk.Frame(barra, bg=c("border"), width=1, height=22).pack(side="right", padx=8)
        boton("⇩  Restaurar", self._restaurar)
        boton("⇧  Respaldar", self._respaldar)
        boton("▤  PDF", self._config_pdf)
        tk.Frame(barra, bg=c("border"), width=1, height=22).pack(side="right", padx=8)
        self.lbl_ident = tk.Label(barra, text="", bg=c("surface"), fg=c("text_mute"),
                                  font=self.tema.fuente("chico"))
        self.lbl_ident.pack(side="right", padx=6)

    # ============================================== pestaña Descargar
    def _construir_descarga(self, raiz):
        # --- RFCs
        cajaR = ttk.LabelFrame(raiz, text="  Contribuyentes  ", style="Card.TLabelframe",
                               padding=12)
        cajaR.pack(fill="both", expand=False, padx=12)

        cuerpoR = ttk.Frame(cajaR, style="Surface.TFrame")
        cuerpoR.pack(fill="both", expand=True)

        cols = ("usar", "nombre", "rfc", "cer", "key", "estado")
        self.tabla = ttk.Treeview(cuerpoR, columns=cols, show="headings",
                                  height=5, selectmode="browse")
        for c, txt, w, anc in [("usar", "Usar", 54, "center"), ("nombre", "Nombre", 210, "w"),
                               ("rfc", "RFC", 140, "w"), ("cer", "Certificado", 180, "w"),
                               ("key", "Llave", 180, "w"), ("estado", "Estado", 130, "w")]:
            self.tabla.heading(c, text=txt)
            self.tabla.column(c, width=w, anchor=anc)
        self.tabla.pack(side="left", fill="both", expand=True)
        self.tabla.bind("<Button-1>", self._click_tabla)
        self.tabla.bind("<Double-1>", lambda _e: self._editar())
        self.tema.zebra(self.tabla)
        self.tabla.tag_configure("revisar", foreground=self.tema.color("danger"))

        bts = ttk.Frame(cajaR, style="Surface.TFrame")
        bts.pack(side="left", fill="y", padx=(12, 0))
        ttk.Button(bts, text="＋  Agregar", style="Primary.TButton", width=16,
                   command=self._agregar).pack(pady=(0, 8), fill="x")
        for txt, cmd in [("Editar", self._editar), ("Quitar", self._quitar),
                         ("Probar e.firma", self._probar)]:
            ttk.Button(bts, text=txt, width=16, command=cmd).pack(pady=3, fill="x")
        sel = ttk.Frame(bts, style="Surface.TFrame"); sel.pack(pady=(8, 0), fill="x")
        ttk.Button(sel, text="Todos", style="Ghost.TButton", width=7,
                   command=lambda: self._marcar(True)).pack(side="left")
        ttk.Button(sel, text="Ninguno", style="Ghost.TButton", width=8,
                   command=lambda: self._marcar(False)).pack(side="left")

        # --- Parámetros
        cajaP = ttk.LabelFrame(raiz, text="  Periodo a descargar  ",
                               style="Card.TLabelframe", padding=12)
        cajaP.pack(fill="x", pady=(14, 0), padx=12)

        op = self.cfg.opciones
        hoy = date.today()
        self.v_desde = tk.StringVar(value=op.ultimo_desde or f"{hoy.year}-01-01")
        self.v_hasta = tk.StringVar(value=op.ultimo_hasta or hoy.isoformat())
        self.v_tipo = tk.StringVar(value=op.ultimo_tipo or "ambos")
        self.v_salida = tk.StringVar(value=op.carpeta_salida)

        fila = ttk.Frame(cajaP, style="Surface.TFrame"); fila.pack(fill="x")
        self._campo(fila, "Desde", self.v_desde, 0, ancho=13)
        self._campo(fila, "Hasta", self.v_hasta, 1, ancho=13)
        col = ttk.Frame(fila, style="Surface.TFrame"); col.grid(row=0, column=2, sticky="w", padx=(0, 16))
        ttk.Label(col, text="Tipo", style="SuaveSurface.TLabel").pack(anchor="w")
        ttk.Combobox(col, textvariable=self.v_tipo, values=["ambos", "emitidos", "recibidos"],
                     state="readonly", width=12).pack(anchor="w", pady=(2, 0))

        col2 = ttk.Frame(fila, style="Surface.TFrame")
        col2.grid(row=0, column=3, sticky="we"); fila.columnconfigure(3, weight=1)
        ttk.Label(col2, text="Carpeta de salida", style="SuaveSurface.TLabel").pack(anchor="w")
        f = ttk.Frame(col2, style="Surface.TFrame"); f.pack(fill="x", pady=(2, 0))
        ttk.Entry(f, textvariable=self.v_salida).pack(side="left", fill="x", expand=True)
        ttk.Button(f, text="⋯", width=3, command=self._elegir_salida).pack(side="left", padx=(6, 0))

        atajos = ttk.Frame(cajaP, style="Surface.TFrame"); atajos.pack(fill="x", pady=(10, 0))
        ttk.Label(atajos, text="Rápido", style="MuteSurface.TLabel").pack(side="left", padx=(0, 8))
        for txt, fn in [("Mes pasado", self._mes_pasado), ("Este año", self._este_anio),
                        ("Año pasado", self._anio_pasado)]:
            ttk.Button(atajos, text=txt, style="Ghost.TButton", command=fn).pack(side="left", padx=2)

        # --- Acciones
        acc = ttk.Frame(raiz, style="TFrame"); acc.pack(fill="x", pady=(14, 0), padx=12)
        self.btn_desc = ttk.Button(acc, text="▶   Descargar XML", style="Primary.TButton",
                                   command=self._descargar)
        self.btn_desc.pack(side="left")
        self.btn_stop = ttk.Button(acc, text="Detener", command=self._detener, state="disabled")
        self.btn_stop.pack(side="left", padx=8)
        ttk.Button(acc, text="Abrir carpeta", style="Ghost.TButton",
                   command=self._abrir_carpeta).pack(side="left")
        self.barra = ttk.Progressbar(acc, mode="indeterminate", length=200)
        self.barra.pack(side="right")
        self.v_estado = tk.StringVar(value="Listo")
        ttk.Label(acc, textvariable=self.v_estado, style="Suave.TLabel").pack(side="right", padx=12)

        # --- Log
        cajaL = ttk.LabelFrame(raiz, text="  Registro  ", style="Card.TLabelframe", padding=8)
        cajaL.pack(fill="both", expand=True, pady=(14, 0), padx=12)
        self.txt = tk.Text(cajaL, height=7, wrap="none", state="disabled", bd=0,
                           bg=self.tema.color("log_bg"), fg=self.tema.color("log_text"),
                           insertbackground=self.tema.color("log_text"),
                           font=self.tema.fuente("mono"), padx=10, pady=8)
        sb = ttk.Scrollbar(cajaL, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); self.txt.pack(fill="both", expand=True)

    def _campo(self, padre, etiqueta, var, col, ancho=14):
        c = ttk.Frame(padre, style="Surface.TFrame")
        c.grid(row=0, column=col, sticky="w", padx=(0, 16))
        ttk.Label(c, text=etiqueta, style="SuaveSurface.TLabel").pack(anchor="w")
        ttk.Entry(c, textvariable=var, width=ancho).pack(anchor="w", pady=(2, 0))
        return c

    def _poner_icono(self):
        import sys as _sys
        from sat_descarga.config import carpeta_programa
        bases = [carpeta_programa(), Path(__file__).resolve().parent]
        if getattr(_sys, "_MEIPASS", None):                 # dentro del .exe
            bases.insert(0, Path(_sys._MEIPASS))
        for cand in (b / "recursos" / "icono.png" for b in bases):
            if cand.exists():
                try:
                    self._icono = tk.PhotoImage(file=str(cand))
                    self.iconphoto(True, self._icono)
                except tk.TclError:
                    pass
                break

    def _zoom(self, delta):
        actual = getattr(self.tema, "zoom", 1.0)
        nuevo = 1.0 if delta is None else actual + delta
        self.cfg.opciones.zoom = self.tema.aplicar_zoom(nuevo)
        self._guardar_cfg()
        if hasattr(self, "v_totales"):
            self.v_totales.set(f"Zoom {int(round(self.cfg.opciones.zoom * 100))}%  ·  Ctrl + / Ctrl − / Ctrl 0")

    def _alternar_tema(self):
        nuevo = "oscuro" if self.tema.nombre == "claro" else "claro"
        self.cfg.opciones.tema = nuevo
        self._guardar_cfg()
        messagebox.showinfo(APP, "El tema se aplicará al volver a abrir la app.")


    # ================================================== pestaña Datos / Excel
    def _construir_datos(self, tab):
        self.filas = []                 # renglones leídos (ya sin duplicados)
        self.filas_vista = []           # tras filtrar
        self.motor = None               # MotorSQL
        self._hilo_lectura = None       # lectura en segundo plano
        self._cancelar_lectura = threading.Event()
        self._carpeta_leida = None      # para saber si la siguiente lectura es OTRA carpeta
        self._rfcs_dueno_extra = set()  # dueños confirmados en esta sesión

        # ---- fila 0: perfil de reporte (cliente)
        fp = ttk.Frame(tab, style="TFrame"); fp.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Label(fp, text="Perfil", style="Suave.TLabel").pack(side="left")
        self.v_perfil = tk.StringVar()
        self.cb_perfil = ttk.Combobox(fp, textvariable=self.v_perfil, state="readonly", width=30)
        self.cb_perfil.pack(side="left", padx=(8, 6))
        self.cb_perfil.bind("<<ComboboxSelected>>", lambda _e: self._perfil_elegido())
        ttk.Button(fp, text="Editar…", command=self._config_pdf).pack(side="left")
        for texto, cmd in (("Nuevo", self._perfil_nuevo), ("Duplicar", self._perfil_duplicar),
                           ("Renombrar", self._perfil_renombrar), ("Borrar", self._perfil_borrar)):
            ttk.Button(fp, text=texto, style="Ghost.TButton", command=cmd).pack(side="left", padx=(4, 0))
        self.v_perfil_info = tk.StringVar(value="")
        ttk.Label(fp, textvariable=self.v_perfil_info, style="Suave.TLabel").pack(side="right")

        # ---- fila 1: carpeta + leer
        top = ttk.Frame(tab, style="TFrame"); top.pack(fill="x", padx=12, pady=(0, 6))
        self.v_carpeta_datos = tk.StringVar(
            value=self.cfg.opciones.ultima_carpeta_datos or self.cfg.opciones.carpeta_salida)
        ttk.Label(top, text="Carpeta de XML", style="Suave.TLabel").pack(anchor="w")
        f1 = ttk.Frame(top, style="TFrame"); f1.pack(fill="x", pady=(2, 0))
        ttk.Entry(f1, textvariable=self.v_carpeta_datos).pack(side="left", fill="x", expand=True)
        ttk.Button(f1, text="⋯", width=3, command=self._elegir_carpeta_datos).pack(side="left", padx=(6, 0))
        self.btn_leer = ttk.Button(f1, text="Leer XML", style="Primary.TButton",
                                   command=self._leer_datos)
        self.btn_leer.pack(side="left", padx=(8, 0))
        self.v_forzar = tk.BooleanVar(value=False)
        ttk.Checkbutton(f1, text="Releer todo", variable=self.v_forzar).pack(side="left", padx=(10, 0))
        # avance de la lectura (solo visible mientras lee)
        self.f_lectura = ttk.Frame(top, style="TFrame")
        self.barra_lectura = ttk.Progressbar(self.f_lectura, mode="determinate", maximum=1)
        self.barra_lectura.pack(side="left", fill="x", expand=True)
        self.btn_cancelar_lectura = ttk.Button(self.f_lectura, text="Cancelar", style="Ghost.TButton",
                                               command=self._cancelar_leer)
        self.btn_cancelar_lectura.pack(side="left", padx=(8, 0))

        # ---- fila 2: ACCIONES ARRIBA (siempre visibles, en cualquier pantalla)
        barra = ttk.Frame(tab, style="TFrame"); barra.pack(fill="x", padx=12, pady=(2, 0))
        ttk.Button(barra, text="Exportar a Excel", style="Primary.TButton",
                   command=self._exportar_excel).pack(side="left")
        ttk.Button(barra, text="▤  Generar PDFs", style="Primary.TButton",
                   command=self._generar_pdfs).pack(side="left", padx=(8, 0))
        ttk.Button(barra, text="Copiar tabla", command=self._copiar_tabla).pack(side="left", padx=(8, 0))
        ttk.Button(barra, text="Copiar selección", style="Ghost.TButton",
                   command=self._copiar_seleccion).pack(side="left", padx=(4, 0))
        ttk.Button(barra, text="Exportar CSV…", style="Ghost.TButton",
                   command=self._exportar_csv_config).pack(side="left")
        ttk.Button(barra, text="Elegir columnas…", style="Ghost.TButton",
                   command=self._elegir_columnas).pack(side="left")
        self.v_totales = tk.StringVar(value="Sin datos leídos")
        ttk.Label(barra, textvariable=self.v_totales, style="Suave.TLabel").pack(side="right")

        # ---- KPIs informativos
        self.kpis = ttk.Frame(tab, style="TFrame"); self.kpis.pack(fill="x", padx=12)
        self._chips, self._chips_sub = {}, {}
        c = self.tema.color
        for i, (clave, etiqueta, acento) in enumerate([
                ("cfdi", "Comprobantes", c("primary")),
                ("ingresos", "Ingresos  ·  I", "#1F9D57"),
                ("gastos", "Gastos  ·  G", "#C7402F"),
                ("iva_i", "IVA en ingresos", c("text_soft")),
                ("iva_g", "IVA en gastos", c("text_soft")),
                ("saldo", "PPD saldo pendiente", "#D9822B")]):
            self._chips[clave], self._chips_sub[clave] = self._chip(self.kpis, etiqueta, i, acento)
        self.kpis.columnconfigure(tuple(range(6)), weight=1, uniform="k")

        # ---- franja de inteligencia: letras por clase + resumen de relaciones
        self.franja = tk.Frame(tab, bg=c("bg")); self.franja.pack(fill="x", padx=12, pady=(8, 0))
        self._badges = {}
        for letra, (nombre, _col) in CLASES.items():
            b = tk.Label(self.franja, text=f" {letra}  0 ", bg=self._color_clase(letra),
                         fg="#FFFFFF", font=self.tema.fuente("fuerte"), padx=4, pady=1)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda _e, L=letra: self._filtrar_clase(L))
            b.configure(cursor="hand2")
            self._badges[letra] = b
        self.lbl_intel = tk.Label(self.franja, text="Lee una carpeta para ver relaciones factura ↔ pago ↔ nota.",
                                  bg=c("bg"), fg=c("text_soft"), font=self.tema.fuente("chico"),
                                  anchor="w")
        self.lbl_intel.pack(side="left", padx=(8, 0), fill="x", expand=True)
        self.franja.bind("<Configure>", lambda e: self.lbl_intel.configure(
            wraplength=max(200, e.width - 380), justify="left"))

        # ---- aviso: comprobantes sin perspectiva (nunca dejar Clase vacía en silencio)
        self.aviso_persp = tk.Frame(tab, bg=c("surface"), highlightbackground="#D9822B",
                                    highlightthickness=1)
        self.lbl_persp = tk.Label(self.aviso_persp, text="", bg=c("surface"), fg=c("text"),
                                  font=self.tema.fuente("chico"), anchor="w", justify="left")
        self.lbl_persp.pack(side="left", padx=10, pady=6, fill="x", expand=True)
        self.btn_persp_asignar = ttk.Button(self.aviso_persp, text="Asignar perspectiva…",
                                            command=self._dialogo_dueno)
        self.btn_persp_asignar.pack(side="right", padx=(4, 8), pady=4)
        self.btn_persp_si = ttk.Button(self.aviso_persp, text="Sí, es el dueño", style="Primary.TButton",
                                       command=lambda: self._aplicar_dueno(self._rfc_sugerido))
        self._rfc_sugerido = ""

        # ---- sub-pestañas (lo único que se encoge si la pantalla es chica)
        self.sub = ttk.Notebook(tab); self.sub.pack(fill="both", expand=True, padx=12, pady=(8, 8))
        tab_tabla = ttk.Frame(self.sub, padding=(2, 8)); self.sub.add(tab_tabla, text="  Tabla  ")
        tab_panel = ttk.Frame(self.sub, padding=(2, 8)); self.sub.add(tab_panel, text="  Panel  ")
        tab_sql = ttk.Frame(self.sub, padding=(2, 8)); self.sub.add(tab_sql, text="  Consulta SQL  ")
        self._construir_sub_tabla(tab_tabla)
        self._construir_sub_panel(tab_panel)
        self._construir_sub_sql(tab_sql)

        # columnas para Copiar tabla / CSV: las del perfil, tu selección guardada o EDDP (65)
        self.cols_export = self._columnas_vigentes()
        self._refrescar_perfiles()
        activo = self.perfiles_rep.activo
        if activo and activo.carpeta_xml:
            self.v_carpeta_datos.set(activo.carpeta_xml)

    def _color_clase(self, letra):
        oscuro = {"I": "#2E9E62", "G": "#D2503F", "N": "#8A5FD0", "P": "#3F7BE6",
                  "E": "#D88A36", "T": "#6B7686"}
        if self.tema.nombre == "oscuro":
            return oscuro.get(letra, "#6B7686")
        return CLASES.get(letra, ("", "#6B7686"))[1]

    def _color_texto_clase(self, letra):
        """Color del TEXTO de la fila en la tabla (más suave en tema oscuro)."""
        oscuro = {"I": "#5FD397", "G": "#FF8A7A", "N": "#C3A2FF", "P": "#8DB4FF",
                  "E": "#FFB86B", "T": "#AEB8C7"}
        if self.tema.nombre == "oscuro":
            return oscuro.get(letra, self.tema.color("text"))
        return CLASES.get(letra, ("", self.tema.color("text")))[1]

    def _filtrar_clase(self, letra):
        """Clic en una letra de la franja = filtrar la tabla por esa clase."""
        self._clase_filtro = None if getattr(self, "_clase_filtro", None) == letra else letra
        self._aplicar_filtros()
        self.sub.select(0)

    # ------------------------------------------------ sub: Tabla
    def _construir_sub_tabla(self, tab):
        filtros = ttk.Frame(tab, style="TFrame"); filtros.pack(fill="x")
        self.v_buscar = tk.StringVar()
        self.v_f_tipo = tk.StringVar(value="todos")
        self.v_f_mes = tk.StringVar(value="todos")

        c0 = ttk.Frame(filtros, style="TFrame"); c0.grid(row=0, column=0, sticky="we", padx=(0, 12))
        ttk.Label(c0, text="Buscar  ·  RFC, nombre, UUID, folio", style="Suave.TLabel").pack(anchor="w")
        e = ttk.Entry(c0, textvariable=self.v_buscar); e.pack(fill="x", pady=(2, 0))
        e.bind("<KeyRelease>", lambda _e: self._aplicar_filtros())
        filtros.columnconfigure(0, weight=1)

        c1 = ttk.Frame(filtros, style="TFrame"); c1.grid(row=0, column=1, sticky="w", padx=(0, 12))
        ttk.Label(c1, text="Tipo", style="Suave.TLabel").pack(anchor="w")
        self.cb_tipo = ttk.Combobox(c1, textvariable=self.v_f_tipo, state="readonly",
                                    width=12, values=["todos", "Emitido", "Recibido"])
        self.cb_tipo.pack(pady=(2, 0)); self.cb_tipo.bind("<<ComboboxSelected>>", lambda _e: self._aplicar_filtros())

        c2 = ttk.Frame(filtros, style="TFrame"); c2.grid(row=0, column=2, sticky="w", padx=(0, 12))
        ttk.Label(c2, text="Mes", style="Suave.TLabel").pack(anchor="w")
        self.cb_mes = ttk.Combobox(c2, textvariable=self.v_f_mes, state="readonly",
                                   width=12, values=["todos"])
        self.cb_mes.pack(pady=(2, 0)); self.cb_mes.bind("<<ComboboxSelected>>", lambda _e: self._aplicar_filtros())

        c3 = ttk.Frame(filtros, style="TFrame"); c3.grid(row=0, column=3, sticky="e")
        ttk.Label(c3, text=" ", style="Suave.TLabel").pack(anchor="w")
        ttk.Button(c3, text="Limpiar", style="Ghost.TButton",
                   command=self._limpiar_filtros).pack(pady=(2, 0))
        self.v_filtros = tk.StringVar(value="Sin filtros")
        ttk.Label(filtros, textvariable=self.v_filtros, style="Suave.TLabel").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        cont = ttk.Frame(tab, style="TFrame"); cont.pack(fill="both", expand=True, pady=(10, 0))
        self.tabla_datos = ttk.Treeview(cont, columns=COLUMNAS, show="headings", height=12)
        anchos = {"Descripción": 240, "Nombre Emisor": 200, "Nombre Receptor": 200,
                  "UUID": 260, "Archivo": 300, "Fecha": 168, "Fecha Timbrado": 168,
                  "Efecto": 160, "Comprobante": 110, "Uso CFDI": 78, "Mes": 50,
                  "Año": 56, "Tipo": 82, "Serie": 60, "Folio": 66, "Moneda": 66}
        for c in COLUMNAS:
            self.tabla_datos.heading(c, text=c, command=lambda cc=c: self._ordenar_por(cc))
            self.tabla_datos.column(c, width=anchos.get(c, 96),
                                    anchor="e" if c in NUMERICAS_UI else "w", stretch=False)
        sy = ttk.Scrollbar(cont, orient="vertical", command=self.tabla_datos.yview)
        sx = ttk.Scrollbar(cont, orient="horizontal", command=self.tabla_datos.xview)
        self.tabla_datos.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tabla_datos.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns"); sx.grid(row=1, column=0, sticky="we")
        cont.rowconfigure(0, weight=1); cont.columnconfigure(0, weight=1)
        self.tema.zebra(self.tabla_datos)
        self.tabla_datos.bind("<Double-1>", self._abrir_visor)

    # ------------------------------------------------ sub: Panel (dashboard)
    def _construir_sub_panel(self, tab):
        self.panel = ttk.Frame(tab, style="TFrame"); self.panel.pack(fill="both", expand=True)
        self.panel_vacio = ttk.Label(self.panel, style="Suave.TLabel",
                                     text="Lee los XML para ver el panel.")
        self.panel_vacio.pack(pady=40)

    # ------------------------------------------------ sub: Consulta SQL
    def _construir_sub_sql(self, tab):
        arriba = ttk.Frame(tab, style="TFrame"); arriba.pack(fill="x")
        ttk.Label(arriba, text="Consulta SQL sobre la tabla  cfdi", style="Suave.TLabel").pack(side="left")
        self.v_consulta = tk.StringVar(value=CONSULTAS_EJEMPLO[0][0])
        cb = ttk.Combobox(arriba, textvariable=self.v_consulta, state="readonly", width=32,
                          values=[n for n, _ in CONSULTAS_EJEMPLO])
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", self._cargar_consulta_ejemplo)
        ttk.Label(arriba, text="Plantillas:", style="Suave.TLabel").pack(side="right", padx=(0, 6))

        # constructor guiado
        guia = ttk.LabelFrame(tab, text="  Armar consulta sin escribir  ",
                              style="Card.TLabelframe", padding=10)
        guia.pack(fill="x", pady=(8, 0))
        gf = ttk.Frame(guia, style="Surface.TFrame"); gf.pack(fill="x")

        self.gv_tipo = tk.StringVar(value="todos")
        self.gv_campo = tk.StringVar(value="Total")
        self.gv_op = tk.StringVar(value="≥")
        self.gv_valor = tk.StringVar(value="")
        self.gv_orden = tk.StringVar(value="Total ↓")

        def _cmp(padre, etiqueta, var, valores, w=12):
            col = ttk.Frame(padre, style="Surface.TFrame"); col.pack(side="left", padx=(0, 10))
            ttk.Label(col, text=etiqueta, style="SuaveSurface.TLabel").pack(anchor="w")
            ttk.Combobox(col, textvariable=var, values=valores, state="readonly",
                         width=w).pack(pady=(2, 0))

        _cmp(gf, "Tipo", self.gv_tipo, ["todos", "Emitido", "Recibido"])
        _cmp(gf, "Campo", self.gv_campo,
             ["Total", "SubTotal", "IVA Trasladado", "Imp Pagado", "IVA Doc", "Fecha"], 14)
        _cmp(gf, "Operador", self.gv_op, ["≥", "≤", "=", "contiene"], 10)
        colv = ttk.Frame(gf, style="Surface.TFrame"); colv.pack(side="left", padx=(0, 10))
        ttk.Label(colv, text="Valor", style="SuaveSurface.TLabel").pack(anchor="w")
        ttk.Entry(colv, textvariable=self.gv_valor, width=14).pack(pady=(2, 0))
        _cmp(gf, "Ordenar por", self.gv_orden,
             ["Total ↓", "Total ↑", "Fecha ↓", "Fecha ↑", "sin orden"], 12)
        ttk.Button(gf, text="Construir  →", style="Primary.TButton",
                   command=self._construir_consulta).pack(side="left", padx=(6, 0), pady=(14, 0))

        self.txt_sql = tk.Text(tab, height=5, wrap="word", bd=1, relief="solid",
                               bg=self.tema.color("surface"), fg=self.tema.color("text"),
                               insertbackground=self.tema.color("text"),
                               font=self.tema.fuente("mono"), padx=8, pady=6)
        self.txt_sql.pack(fill="x", pady=(8, 0))
        self.txt_sql.insert("1.0", CONSULTAS_EJEMPLO[0][1])

        bar = ttk.Frame(tab, style="TFrame"); bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="▶  Ejecutar", style="Primary.TButton",
                   command=self._ejecutar_sql).pack(side="left")
        ttk.Button(bar, text="Copiar resultado", style="Ghost.TButton",
                   command=self._copiar_sql).pack(side="left", padx=8)
        ttk.Button(bar, text="Exportar resultado…", style="Ghost.TButton",
                   command=self._exportar_sql).pack(side="left")
        self.v_sql_estado = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.v_sql_estado, style="Suave.TLabel").pack(side="right")

        cont = ttk.Frame(tab, style="TFrame"); cont.pack(fill="both", expand=True, pady=(8, 0))
        self.tabla_sql = ttk.Treeview(cont, show="headings", height=8)
        sy = ttk.Scrollbar(cont, orient="vertical", command=self.tabla_sql.yview)
        sx = ttk.Scrollbar(cont, orient="horizontal", command=self.tabla_sql.xview)
        self.tabla_sql.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tabla_sql.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns"); sx.grid(row=1, column=0, sticky="we")
        cont.rowconfigure(0, weight=1); cont.columnconfigure(0, weight=1)
        self.tema.zebra(self.tabla_sql)
        self._sql_cols, self._sql_filas = [], []

    def _chip(self, padre, etiqueta, col, acento=None):
        c = self.tema.color
        marco = tk.Frame(padre, bg=c("surface"), highlightbackground=c("border"),
                         highlightthickness=1, bd=0)
        marco.grid(row=0, column=col, sticky="we", padx=(0 if col == 0 else 6, 0), pady=(8, 0))
        tk.Frame(marco, bg=acento or c("primary"), height=3).pack(fill="x")
        tk.Label(marco, text=etiqueta.upper(), bg=c("surface"), fg=c("text_mute"),
                 font=self.tema.fuente("chico")).pack(anchor="w", padx=12, pady=(7, 0))
        val = tk.Label(marco, text="—", bg=c("surface"), fg=c("text"),
                       font=self.tema.fuente("subtitulo"))
        val.pack(anchor="w", padx=12)
        sub = tk.Label(marco, text=" ", bg=c("surface"), fg=c("text_mute"),
                       font=self.tema.fuente("chico"))
        sub.pack(anchor="w", padx=12, pady=(0, 7))
        return val, sub

    def _pintar_panel(self):
        for w in self.panel.winfo_children():
            w.destroy()
        if not self.filas or self.motor is None:
            ttk.Label(self.panel, text="Lee los XML para ver el panel.",
                      style="Suave.TLabel").pack(pady=40)
            return
        r = self.motor.resumen()
        c = self.tema.color

        # fila de mini-tarjetas: emitido vs recibido
        top = ttk.Frame(self.panel, style="TFrame"); top.pack(fill="x")
        emi = r["por_tipo"].get("Emitido", {"n": 0, "total": 0})
        rec = r["por_tipo"].get("Recibido", {"n": 0, "total": 0})
        self._tarjeta_panel(top, 0, "Ingresos (emitido)", emi["total"], emi["n"], c("ok"))
        self._tarjeta_panel(top, 1, "Gastos (recibido)", rec["total"], rec["n"], c("danger"))
        self._tarjeta_panel(top, 2, "IVA trasladado", r["iva_tras"], None, c("primary"))
        self._tarjeta_panel(top, 3, "IVA retenido", r["iva_ret"], None, c("text_soft"))
        top.columnconfigure((0, 1, 2, 3), weight=1, uniform="p")

        cuerpo = ttk.Frame(self.panel, style="TFrame"); cuerpo.pack(fill="both", expand=True, pady=(12, 0))
        # barras por mes (canvas)
        izq = ttk.LabelFrame(cuerpo, text="  Total por mes  ", style="Card.TLabelframe", padding=10)
        izq.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._barras_mes(izq, r["por_mes"])
        # top proveedores
        der = ttk.LabelFrame(cuerpo, text="  Principales proveedores (gasto)  ",
                             style="Card.TLabelframe", padding=10)
        der.grid(row=0, column=1, sticky="nsew")
        self._lista_top(der, r["top_emisores"])
        cuerpo.columnconfigure(0, weight=3); cuerpo.columnconfigure(1, weight=2)
        cuerpo.rowconfigure(0, weight=1)

    def _tarjeta_panel(self, padre, col, titulo, monto, n, acento):
        c = self.tema.color
        m = tk.Frame(padre, bg=c("surface"), highlightbackground=c("border"),
                     highlightthickness=1, bd=0)
        m.grid(row=0, column=col, sticky="we", padx=(0 if col == 0 else 8, 0))
        tk.Frame(m, bg=acento, height=3).pack(fill="x")
        tk.Label(m, text=titulo.upper(), bg=c("surface"), fg=c("text_mute"),
                 font=self.tema.fuente("chico")).pack(anchor="w", padx=12, pady=(10, 0))
        tk.Label(m, text=f"$ {monto:,.2f}", bg=c("surface"), fg=c("text"),
                 font=self.tema.fuente("subtitulo")).pack(anchor="w", padx=12)
        sub = f"{n:,} comprobantes" if n is not None else " "
        tk.Label(m, text=sub, bg=c("surface"), fg=c("text_mute"),
                 font=self.tema.fuente("chico")).pack(anchor="w", padx=12, pady=(0, 10))

    def _barras_mes(self, padre, por_mes):
        c = self.tema.color
        cv = tk.Canvas(padre, bg=c("surface"), highlightthickness=0, height=240)
        cv.pack(fill="both", expand=True)
        if not por_mes:
            cv.create_text(20, 20, text="sin datos", anchor="w", fill=c("text_mute"))
            return

        def redibujar(_e=None):
            cv.delete("all")
            W = cv.winfo_width() or 400
            H = cv.winfo_height() or 240
            pad = 30
            datos = por_mes[-12:]                 # últimos 12 meses
            maxv = max((max(m["emitido"], m["recibido"]) for m in datos), default=1) or 1
            n = len(datos)
            ancho_grupo = (W - 2 * pad) / max(n, 1)
            bw = min(ancho_grupo / 3, 16)
            base = H - 24
            for i, m in enumerate(datos):
                x = pad + i * ancho_grupo + ancho_grupo / 2
                he = (m["emitido"] / maxv) * (base - 20)
                hr = (m["recibido"] / maxv) * (base - 20)
                cv.create_rectangle(x - bw - 1, base - he, x - 1, base,
                                    fill=c("ok"), width=0)
                cv.create_rectangle(x + 1, base - hr, x + bw + 1, base,
                                    fill=c("danger"), width=0)
                cv.create_text(x, base + 12, text=m["periodo"][-2:], anchor="n",
                               fill=c("text_mute"), font=self.tema.fuente("chico"))
            cv.create_text(pad, 10, text="■ emitido", anchor="w", fill=c("ok"),
                           font=self.tema.fuente("chico"))
            cv.create_text(pad + 70, 10, text="■ recibido", anchor="w", fill=c("danger"),
                           font=self.tema.fuente("chico"))
        cv.bind("<Configure>", redibujar)
        redibujar()

    def _lista_top(self, padre, top):
        c = self.tema.color
        if not top:
            ttk.Label(padre, text="sin recibidos", style="MuteSurface.TLabel").pack()
            return
        maxv = max((t["total"] for t in top), default=1) or 1
        for t in top:
            fila = tk.Frame(padre, bg=c("surface")); fila.pack(fill="x", pady=3)
            tk.Label(fila, text=(t["nombre"] or t["rfc"] or "—")[:28], bg=c("surface"),
                     fg=c("text"), font=self.tema.fuente("chico"), anchor="w",
                     width=26).pack(side="left")
            barra = tk.Frame(fila, bg=c("surface_alt"), height=14, width=120)
            barra.pack(side="left", fill="x", expand=True, padx=6)
            barra.pack_propagate(False)
            ancho = max(2, int((t["total"] / maxv) * 100))
            tk.Frame(barra, bg=c("primary"), width=ancho).place(relheight=1, x=0, y=0)
            tk.Label(fila, text=f"$ {t['total']:,.0f}", bg=c("surface"),
                     fg=c("text_soft"), font=self.tema.fuente("chico"),
                     width=12, anchor="e").pack(side="right")

    # ------------------------------------------------ SQL
    def _construir_consulta(self):
        from sat_descarga.consulta import VISIBLE_A_SQL
        campo = VISIBLE_A_SQL.get(self.gv_campo.get(), "total")
        op_map = {"≥": ">=", "≤": "<=", "=": "=", "contiene": "LIKE"}
        op = op_map.get(self.gv_op.get(), ">=")
        valor = self.gv_valor.get().strip()

        condiciones = []
        if self.gv_tipo.get() != "todos":
            condiciones.append(f"tipo = '{self.gv_tipo.get()}'")
        if valor:
            if op == "LIKE":
                condiciones.append(f"{campo} LIKE '%{valor}%'")
            elif campo == "fecha":
                condiciones.append(f"{campo} {op} '{valor}'")
            else:
                try:
                    float(valor)
                    condiciones.append(f"{campo} {op} {valor}")
                except ValueError:
                    condiciones.append(f"{campo} {op} '{valor}'")

        where = ("\nWHERE " + " AND ".join(condiciones)) if condiciones else ""
        orden_map = {"Total ↓": "ORDER BY total DESC", "Total ↑": "ORDER BY total ASC",
                     "Fecha ↓": "ORDER BY fecha DESC", "Fecha ↑": "ORDER BY fecha ASC",
                     "sin orden": ""}
        orden = orden_map.get(self.gv_orden.get(), "")
        sql = ("SELECT fecha, tipo, comprobante, nombre_emisor, nombre_receptor, "
               "subtotal, iva_trasladado, total, imp_pagado\nFROM cfdi" + where +
               ("\n" + orden if orden else ""))
        self.txt_sql.delete("1.0", "end")
        self.txt_sql.insert("1.0", sql)
        self._ejecutar_sql()

    def _cargar_consulta_ejemplo(self, _e=None):
        nombre = self.v_consulta.get()
        for n, sql in CONSULTAS_EJEMPLO:
            if n == nombre:
                self.txt_sql.delete("1.0", "end")
                self.txt_sql.insert("1.0", sql)
                break

    def _ejecutar_sql(self):
        if self.motor is None:
            messagebox.showinfo(APP, "Lee los XML primero."); return
        sql = self.txt_sql.get("1.0", "end")
        try:
            cols, filas = self.motor.consultar(sql)
        except Exception as e:  # noqa: BLE001
            self.v_sql_estado.set("Error")
            messagebox.showerror(APP, f"Consulta inválida:\n{e}"); return
        self._sql_cols, self._sql_filas = cols, filas
        self.tabla_sql.delete(*self.tabla_sql.get_children())
        self.tabla_sql.config(columns=cols)
        for c in cols:
            self.tabla_sql.heading(c, text=c)
            self.tabla_sql.column(c, width=max(80, min(260, len(c) * 12)), anchor="w")
        for i, f in enumerate(filas[:5000]):
            self.tabla_sql.insert("", "end", values=f,
                                  tags=("par" if i % 2 == 0 else "impar",))
        self.v_sql_estado.set(f"{len(filas):,} filas")

    def _copiar_sql(self):
        if not self._sql_filas:
            messagebox.showinfo(APP, "Ejecuta una consulta primero."); return
        self._al_portapapeles(matriz_a_tsv(self._sql_cols, self._sql_filas), len(self._sql_filas))

    def _exportar_sql(self):
        if not self._sql_filas:
            messagebox.showinfo(APP, "Ejecuta una consulta primero."); return
        r = filedialog.asksaveasfilename(title="Guardar resultado", defaultextension=".csv",
                                         initialfile="consulta.csv",
                                         filetypes=[("CSV", "*.csv")], parent=self)
        if not r:
            return
        matriz_a_csv(self._sql_cols, self._sql_filas, r)
        messagebox.showinfo(APP, f"{len(self._sql_filas):,} filas\n{r}")

    # ------------------------------------------------ columnas / export config
    def _elegir_columnas(self):
        DialogoColumnas(self, self.cols_export, self._set_columnas)

    def _set_columnas(self, cols):
        self.cols_export = cols or list(COLUMNAS_COPIADO)
        es_formato = self.cols_export == list(COLUMNAS_COPIADO)
        activo = self.perfiles_rep.activo
        if activo is not None:                  # cada cliente con sus columnas
            activo.columnas_copiado = [] if es_formato else list(self.cols_export)
            self._guardar_perfiles()
        else:
            self.cfg.opciones.columnas_copiado = [] if es_formato else list(self.cols_export)
            self._guardar_cfg()
        if hasattr(self, "v_totales"):
            self.v_totales.set(f"Copiar tabla: {len(self.cols_export)} columnas"
                               + ("  (formato EDDP)" if es_formato else "  (personalizado)"))

    def _exportar_csv_config(self):
        if not self.filas_vista:
            messagebox.showinfo(APP, "No hay datos. Dale 'Leer XML' primero."); return
        r = filedialog.asksaveasfilename(title="Guardar CSV", defaultextension=".csv",
                                         initialfile="cfdi.csv",
                                         filetypes=[("CSV", "*.csv")], parent=self)
        if not r:
            return
        try:
            a_csv_cols(self.filas_vista, self.cols_export, r)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP, f"No se pudo guardar: {e}"); return
        messagebox.showinfo(APP, f"{len(self.filas_vista):,} renglones · "
                                 f"{len(self.cols_export)} columnas\n{r}")

    def _mis_rfcs(self):
        """RFCs que la app considera 'tuyos' para decidir emitido/recibido."""
        activo = self.perfiles_rep.activo
        del_perfil = set(activo.rfcs) if activo else set()
        return sorted({p.rfc for p in self.cfg.perfiles if p.rfc} | self._rfcs_dueno_extra | del_perfil)

    def _leer_datos(self, esperar: bool = False):
        """Lee la carpeta en un hilo (lectura + inteligencia + SQL) con avance y
        cancelar; la ventana nunca se congela. esperar=True: bloquea hasta terminar
        (pruebas y usos programáticos)."""
        carpeta = self.v_carpeta_datos.get().strip()
        if not carpeta or not Path(carpeta).exists():
            messagebox.showerror(APP, "Esa carpeta no existe."); return
        if self._hilo_lectura is not None and self._hilo_lectura.is_alive():
            self.v_totales.set("Ya se está leyendo una carpeta…"); return
        self._cancelar_lectura = threading.Event()
        cancelar = self._cancelar_lectura
        mis_rfcs = self._mis_rfcs()
        forzar = self.v_forzar.get()
        ruta_indice = str(Path(self.cfg.ruta).parent / "indice_xml.csv")
        memoria = self.memoria
        self._estado_lectura(True)
        self.v_totales.set("Buscando XML…")

        def progreso(i, total):
            self.cola.put(("__prog_lectura__", i, total))

        def tarea():
            try:
                res = leer_y_procesar(carpeta, ruta_indice, mis_rfcs, memoria, forzar=forzar,
                                      progreso=progreso, cancelado=cancelar.is_set)
            except LecturaCancelada:
                res = {"cancelado": True, "carpeta": carpeta}
            except Exception as e:  # noqa: BLE001
                res = {"error": str(e), "carpeta": carpeta}
            self.cola.put(("__fin_lectura__", res))

        # igual que en PDFs: recolectar basura de Tk AQUÍ, no dentro del hilo
        import gc
        gc.collect()
        self._hilo_lectura = threading.Thread(target=tarea, daemon=True)
        self._hilo_lectura.start()
        if esperar:
            self._hilo_lectura.join()
            self._procesar_cola()

    def _cancelar_leer(self):
        self._cancelar_lectura.set()
        self.v_totales.set("Cancelando lectura…")

    def _estado_lectura(self, leyendo: bool):
        if leyendo:
            self.btn_leer.config(state="disabled")
            self.barra_lectura.config(value=0, maximum=1)
            self.f_lectura.pack(fill="x", pady=(4, 0))
        else:
            self.btn_leer.config(state="normal")
            self.f_lectura.pack_forget()

    def _progreso_lectura(self, i, total):
        self.barra_lectura.config(maximum=max(total, 1), value=i)
        self.v_totales.set(f"Leyendo {i:,} / {total:,} XML…")

    def _fin_lectura(self, res):
        self._estado_lectura(False)
        if res.get("cancelado"):
            self.v_totales.set("Lectura cancelada · se conservan los datos anteriores")
            return
        if res.get("error"):
            self.v_totales.set("Error")
            messagebox.showerror(APP, f"No se pudo leer: {res['error']}")
            return
        if res.get("error_intel"):
            self.log.warning("Relaciones no calculadas: %s", res["error_intel"])
        carpeta = res["carpeta"]
        otra_carpeta = self._carpeta_leida is None or \
            Path(carpeta).resolve() != Path(self._carpeta_leida).resolve()
        filas = res["filas"]
        self.filas = filas
        self.resumen_intel = res.get("resumen") or {}
        dups = self.resumen_intel.get("duplicados", 0)
        self.log.info("Leídos %d renglones de %s (%d nuevos, %d ya conocidos, %d duplicados ignorados)",
                      len(filas), carpeta, res.get("nuevos", 0), res.get("reusados", 0), dups)
        if self.motor is not None:
            self.motor.cerrar()
        self.motor = res["motor"]
        self._pintar_panel()
        meses = sorted({f"{r.datos.get('Año','')}-{r.datos.get('Mes','')}"
                        for r in filas if r.datos.get("Año")})
        self.cb_mes.config(values=["todos"] + meses)
        # filtros: otra carpeta = empezar limpio; misma carpeta = solo lo que siga existiendo
        if otra_carpeta:
            self._resetear_filtros()
            self._filtros_del_perfil(meses)
        else:
            self._validar_filtros(meses)
        self._carpeta_leida = carpeta
        self.cfg.opciones.ultima_carpeta_datos = carpeta
        self._guardar_cfg()
        self._pintar_perspectiva()
        self._aplicar_filtros()
        if not filas:
            messagebox.showinfo(APP, "No se encontraron CFDI en esa carpeta.")

    # ------------------------------------------------ filtros
    def _resetear_filtros(self):
        self._clase_filtro = None
        self.v_buscar.set(""); self.v_f_tipo.set("todos"); self.v_f_mes.set("todos")

    def _filtros_del_perfil(self, meses):
        """Filtros por defecto del perfil activo (solo los que existan en lo leído)."""
        activo = self.perfiles_rep.activo
        if activo is None:
            return
        f = activo.filtros
        if f.get("tipo") in ("Emitido", "Recibido"):
            self.v_f_tipo.set(f["tipo"])
        if f.get("mes") in meses:
            self.v_f_mes.set(f["mes"])
        if f.get("clase") in CLASES:
            self._clase_filtro = f["clase"]
        if f.get("texto"):
            self.v_buscar.set(f["texto"])

    def _validar_filtros(self, meses):
        """Quita los filtros que ya no tienen sentido con lo recién leído."""
        if self.v_f_mes.get() not in ["todos"] + list(meses):
            self.v_f_mes.set("todos")
        if self.v_f_tipo.get() not in ("todos", "Emitido", "Recibido"):
            self.v_f_tipo.set("todos")
        clase = getattr(self, "_clase_filtro", None)
        if clase and not any(r.datos.get("Clase") == clase for r in self.filas):
            self._clase_filtro = None

    def _filtros_activos(self):
        activos = []
        if getattr(self, "_clase_filtro", None):
            activos.append(f"Clase {self._clase_filtro}")
        if self.v_f_tipo.get() != "todos":
            activos.append(f"Tipo {self.v_f_tipo.get()}")
        if self.v_f_mes.get() != "todos":
            activos.append(f"Mes {self.v_f_mes.get()}")
        if self.v_buscar.get().strip():
            activos.append(f"Texto “{self.v_buscar.get().strip()}”")
        return activos

    # ------------------------------------------------ perspectiva (emitido / recibido)
    def _pintar_perspectiva(self):
        n = sin_perspectiva(self.filas)
        if not n:
            self.aviso_persp.pack_forget()
            return
        sug = rfc_sugerido(self.filas)
        self._rfc_sugerido = sug[0] if sug else ""
        texto = (f"⚠ {n:,} comprobante{'s' if n != 1 else ''} sin perspectiva: no se sabe si "
                 f"son emitidos o recibidos, así que Tipo, Clase y las tarjetas quedan incompletas.")
        if sug:
            texto += f"\n¿El dueño de esta carpeta es {sug[0]}" + \
                (f" · {sug[1]}" if sug[1] else "") + f"? (aparece en {sug[2]:,} de ellos)"
            self.btn_persp_si.pack(side="right", padx=4, pady=4, before=self.btn_persp_asignar)
        else:
            self.btn_persp_si.pack_forget()
        self.lbl_persp.config(text=texto)
        self.aviso_persp.pack(fill="x", padx=12, pady=(8, 0), before=self.sub)

    def _aplicar_dueno(self, rfc: str):
        """El usuario confirma de quién es la carpeta: se recalcula todo sin releer."""
        rfc = (rfc or "").strip().upper()
        if not rfc or not self.filas:
            return
        self._rfcs_dueno_extra.add(rfc)
        self._recordar_dueno(rfc)
        previo = self.resumen_intel or {}
        asignar_perspectiva(self.filas, [rfc])
        try:
            self.filas, resumen = procesar(self.filas, self._mis_rfcs(), self.memoria)
            for k in ("duplicados", "duplicados_archivos"):
                resumen[k] = previo.get(k, resumen.get(k))
            self.resumen_intel = resumen
        except Exception as e:  # noqa: BLE001
            self.log.warning("Relaciones no calculadas: %s", e)
        if self.motor is not None:
            self.motor.cerrar()
        self.motor = MotorSQL(self.filas)
        self._pintar_panel()
        self._pintar_perspectiva()
        self._aplicar_filtros()
        self.log.info("Perspectiva asignada con el RFC dueño %s", rfc)

    def _recordar_dueno(self, rfc):
        """El dueño confirmado se guarda en el perfil activo; sin perfil, se crea uno
        con esa carpeta para que la próxima vez ya lo sepa."""
        activo = self.perfiles_rep.activo
        if activo is not None:
            if rfc not in activo.rfcs:
                activo.rfcs.append(rfc)
        else:
            nombre = next((n for r, n, _ in candidatos_dueno(self.filas) if r == rfc and n), rfc)
            nuevo = self.perfiles_rep.crear(nombre, rfcs=[rfc],
                                            carpeta_xml=self.v_carpeta_datos.get().strip())
            self.perfiles_rep.activar(nuevo.id)
            self.log.info("Se creó el perfil de reporte '%s' (RFC dueño %s)", nuevo.nombre, rfc)
        self._guardar_perfiles()
        self._refrescar_perfiles()

    # ------------------------------------------------ perfiles de reporte
    SIN_PERFIL = "— Sin perfil —"

    def _guardar_perfiles(self):
        try:
            self.perfiles_rep.guardar()
        except OSError as e:
            self.log.warning("No se pudieron guardar los perfiles: %s", e)

    def _refrescar_perfiles(self):
        self.cb_perfil.config(values=[self.SIN_PERFIL] + self.perfiles_rep.nombres())
        activo = self.perfiles_rep.activo
        self.v_perfil.set(activo.nombre if activo else self.SIN_PERFIL)
        if activo:
            rfcs = ", ".join(activo.rfcs) or "sin RFC dueño"
            self.v_perfil_info.set(f"{rfcs}  ·  PDF en: {activo.carpeta_pdf or '(preguntar)'}")
        else:
            self.v_perfil_info.set("Diseño general · RFC dueño = tus RFC registrados")

    def _columnas_vigentes(self):
        activo = self.perfiles_rep.activo
        propias = activo.columnas_copiado if activo else self.cfg.opciones.columnas_copiado
        return [c for c in (propias or []) if c in COLUMNAS] or list(COLUMNAS_COPIADO)

    def _perfil_elegido(self):
        nombre = self.v_perfil.get()
        p = self.perfiles_rep.por_nombre(nombre)
        self._cambiar_perfil(p.id if p else "")

    def _cambiar_perfil(self, pid, leer=True):
        """Activa un perfil: su carpeta, sus columnas y sus filtros; y lee solo."""
        self.perfiles_rep.activar(pid)
        self._guardar_perfiles()
        self._refrescar_perfiles()
        self.cols_export = self._columnas_vigentes()
        activo = self.perfiles_rep.activo
        self._carpeta_leida = None              # se aplican los filtros del perfil
        if activo and activo.carpeta_xml:
            self.v_carpeta_datos.set(activo.carpeta_xml)
        carpeta = self.v_carpeta_datos.get().strip()
        if leer and carpeta and Path(carpeta).exists():
            self._leer_datos()

    def _perfil_nuevo(self):
        nombre = simpledialog.askstring(APP, "Nombre del perfil (cliente):", parent=self)
        if not nombre or not nombre.strip():
            return
        sug = rfc_sugerido(self.filas) if self.filas else None
        rfcs = sorted({r.datos.get("RFC Emisor") if r.datos.get("Tipo") == "Emitido"
                       else r.datos.get("RFC Receptor") for r in self.filas if r.datos.get("Tipo")})
        nuevo = self.perfiles_rep.crear(nombre, carpeta_xml=self.v_carpeta_datos.get().strip(),
                                        rfcs=[x for x in rfcs if x][:1] or ([sug[0]] if sug else []))
        self._guardar_perfiles()
        self._cambiar_perfil(nuevo.id, leer=False)
        DialogoPerfilReporte(self, nuevo)

    def _perfil_duplicar(self):
        activo = self.perfiles_rep.activo
        if activo is None:
            messagebox.showinfo(APP, "Elige primero el perfil que quieres duplicar."); return
        nombre = simpledialog.askstring(APP, "Nombre de la copia:", initialvalue=f"{activo.nombre} (copia)",
                                        parent=self)
        if not nombre or not nombre.strip():
            return
        copia = self.perfiles_rep.duplicar(activo.id, nombre)
        self._guardar_perfiles()
        self._cambiar_perfil(copia.id, leer=False)

    def _perfil_renombrar(self):
        activo = self.perfiles_rep.activo
        if activo is None:
            messagebox.showinfo(APP, "Elige primero el perfil que quieres renombrar."); return
        nombre = simpledialog.askstring(APP, "Nuevo nombre:", initialvalue=activo.nombre, parent=self)
        if nombre and self.perfiles_rep.renombrar(activo.id, nombre):
            self._guardar_perfiles()
            self._refrescar_perfiles()

    def _perfil_borrar(self):
        activo = self.perfiles_rep.activo
        if activo is None:
            return
        if not messagebox.askyesno(APP, f"¿Borrar el perfil '{activo.nombre}'?\n\n"
                                        "No se borra ningún XML ni PDF, solo la configuración."):
            return
        self.perfiles_rep.borrar(activo.id)
        self._guardar_perfiles()
        self._cambiar_perfil("", leer=False)

    def diseno_de_fila(self, d):
        """Diseño del PDF para una fila: perfil activo, o el del RFC dueño, o general."""
        rfc, _ = dueno_de({"emisor_rfc": d.get("RFC Emisor", ""),
                           "receptor_rfc": d.get("RFC Receptor", "")}, d.get("Tipo", ""))
        return self.perfiles_rep.diseno_para(rfc)

    def _dialogo_dueno(self):
        DialogoDueno(self, candidatos_dueno(self.filas), self._aplicar_dueno)

    # ------------------------------------------------ PDFs en masa
    def _generar_pdfs(self):
        if not self.filas_vista:
            messagebox.showinfo(APP, "No hay datos. Dale 'Leer XML' primero."); return
        if getattr(self, "_hilo_pdf", None) and self._hilo_pdf.is_alive():
            messagebox.showinfo(APP, "Ya se están generando PDFs, espera a que termine."); return
        sel = self.tabla_datos.selection()
        if sel:
            fuente = [self.filas_vista[int(i)] for i in sel if int(i) < len(self.filas_vista)]
            origen = "seleccionados"
        else:
            fuente = list(self.filas_vista)
            origen = "a la vista (con el filtro actual)"
        n = len({((r.datos.get("UUID") or r.datos.get("Archivo")), r.datos.get("Tipo")) for r in fuente})
        if not messagebox.askyesno(APP, f"Generar {n:,} PDF de los comprobantes {origen}?\n\n"
                                        "Los que ya existan en la carpeta no se vuelven a generar."):
            return
        activo = self.perfiles_rep.activo
        if activo is not None and activo.carpeta_pdf:
            carpeta = activo.carpeta_pdf             # el perfil ya sabe dónde van
        else:
            inicial = self.cfg.opciones.ultima_carpeta_pdf or self.v_carpeta_datos.get()
            carpeta = filedialog.askdirectory(title="¿Dónde guardo los PDF?", initialdir=inicial or None,
                                              parent=self)
            if not carpeta:
                return
            self.cfg.opciones.ultima_carpeta_pdf = carpeta
            self._guardar_cfg()
        diseno_de = self.diseno_de_fila
        self.v_totales.set(f"Generando 0/{n:,} PDF…")

        def progreso(i, total):
            self.cola.put(f"__pdf__{i}/{total}")

        def tarea():
            try:
                res = generar_pdfs(fuente, carpeta, inteligencia_de=self._intel_de,
                                   progreso=progreso, diseno_de=diseno_de)
            except Exception as e:  # noqa: BLE001
                res = {"generados": 0, "omitidos": 0, "errores": [("", str(e))], "carpeta": carpeta}
            self.cola.put(("__fin_pdfs__", res))

        # Limpia la basura de ventanas cerradas AQUÍ (hilo principal): si el recolector
        # corre dentro del hilo de trabajo, cada objeto de Tk lo frena ~1 s.
        import gc
        gc.collect()
        self._hilo_pdf = threading.Thread(target=tarea, daemon=True)
        self._hilo_pdf.start()

    def _fin_pdfs(self, res):
        msg = (f"PDF generados: {res.get('generados', 0):,}\n"
               f"Ya existían (no se tocaron): {res.get('omitidos', 0):,}\n"
               f"Con error: {len(res.get('errores', [])):,}\n\n{res.get('carpeta','')}")
        self.v_totales.set(f"{res.get('generados', 0):,} PDF generados")
        for archivo, err in res.get("errores", [])[:20]:
            self.log.warning("PDF no generado %s: %s", archivo, err)
        if res.get("errores"):
            messagebox.showwarning(APP, msg + "\n\nLos errores están en el registro.")
        else:
            messagebox.showinfo(APP, msg)
        if res.get("generados") or res.get("omitidos"):
            self._abrir_ruta(res.get("carpeta", ""))

    def _abrir_ruta(self, ruta):
        import os
        import subprocess
        import sys
        if not ruta:
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(ruta)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.run(["open", ruta], check=False)
            else:
                subprocess.run(["xdg-open", ruta], check=False)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------ respaldo / restauración
    def _respaldar(self):
        from datetime import date as _d
        r = filedialog.asksaveasfilename(
            title="Guardar respaldo", defaultextension=".zip",
            initialfile=f"Respaldo DESCARGA XML EDDP {_d.today().isoformat()}.zip",
            filetypes=[("Respaldo", "*.zip")], parent=self)
        if not r:
            return
        self._guardar_cfg()
        try:
            res = crear_respaldo(r, self.cfg)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP, f"No se pudo crear el respaldo: {e}"); return
        extra = ""
        if res["faltantes"]:
            extra = "\n\nNo se encontraron (revisa las rutas):\n• " + "\n• ".join(res["faltantes"][:6])
        messagebox.showinfo(APP, f"Respaldo listo: {res['perfiles']} RFC, {res['efirmas']} archivos de "
                                 f"e.firma, {res['archivos']} archivos de configuración.\n\n{r}\n\n"
                                 "⚠ Contiene tus llaves privadas y contraseñas: guárdalo en un lugar "
                                 "seguro y no lo mandes por correo." + extra)

    def _restaurar(self):
        r = filedialog.askopenfilename(title="Elegir respaldo", filetypes=[("Respaldo", "*.zip")],
                                       parent=self)
        if not r:
            return
        if not messagebox.askyesno(APP, "Se agregarán los RFC del respaldo (los que ya tienes con el "
                                        "mismo perfil se actualizan). Tu configuración de PDF actual "
                                        "queda guardada como .bak.\n\n¿Continuar?"):
            return
        try:
            res = restaurar_respaldo(r, self.cfg.ruta)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP, f"No se pudo restaurar: {e}"); return
        self.cfg = Config.desde_archivo(self.cfg.ruta)
        self.memoria = Memoria(str(Path(self.cfg.ruta).parent / "memoria.json"))
        self.perfiles_rep = Perfiles.cargar(str(Path(self.cfg.ruta).parent / "perfiles_reporte.json"))
        self._refrescar_perfiles()
        self.cols_export = self._columnas_vigentes()
        op = self.cfg.opciones
        self.v_salida.set(op.carpeta_salida)
        if op.ultima_carpeta_datos:
            self.v_carpeta_datos.set(op.ultima_carpeta_datos)
        self._refrescar_lista()
        messagebox.showinfo(APP, f"Restaurado: {res['nuevos']} RFC nuevos, {res['actualizados']} "
                                 f"actualizados, {res['efirmas']} archivos de e.firma reubicados en "
                                 f"{carpeta_datos()}.")

    def _config_pdf(self):
        """Editor del perfil activo (o del diseño general si no hay perfil)."""
        DialogoPerfilReporte(self, self.perfiles_rep.activo)

    def _abrir_visor(self, _e=None):
        sel = self.tabla_datos.selection()
        if not sel:
            return
        i = int(sel[0])
        if i >= len(self.filas_vista):
            return
        ruta = self.filas_vista[i].datos.get("Archivo", "")
        detalle = leer_detalle(ruta)
        if not detalle:
            messagebox.showerror(APP, "No se pudo leer este comprobante."); return
        VisorCFDI(self, detalle, self.filas_vista[i].datos)

    def _elegir_carpeta_datos(self):
        r = filedialog.askdirectory(title="Carpeta con los XML", parent=self)
        if r:
            self.v_carpeta_datos.set(r)

    def _aplicar_filtros(self):
        texto = self.v_buscar.get().strip().lower()
        tipo = self.v_f_tipo.get()
        mes = self.v_f_mes.get()
        campos = ("RFC Emisor", "Nombre Emisor", "RFC Receptor", "Nombre Receptor",
                  "UUID", "Folio", "Serie", "Descripción")
        clase = getattr(self, "_clase_filtro", None)
        vista = []
        for r in self.filas:
            d = r.datos
            if clase and d.get("Clase") != clase:
                continue
            if tipo != "todos" and d.get("Tipo") != tipo:
                continue
            if mes != "todos" and f"{d.get('Año','')}-{d.get('Mes','')}" != mes:
                continue
            if texto and not any(texto in str(d.get(c, "")).lower() for c in campos):
                continue
            vista.append(r)
        self.filas_vista = vista
        self._pintar_tabla()

    def _limpiar_filtros(self):
        self._resetear_filtros()
        self._aplicar_filtros()

    def _pintar_tabla(self):
        self.tabla_datos.delete(*self.tabla_datos.get_children())
        for letra in CLASES:
            self.tabla_datos.tag_configure(f"cls_{letra}", foreground=self._color_texto_clase(letra))
        for i, r in enumerate(self.filas_vista[:MAX_FILAS_TABLA]):
            letra = r.datos.get("Clase", "")
            tags = ["par" if i % 2 == 0 else "impar"]
            if letra:
                tags.append(f"cls_{letra}")
            self.tabla_datos.insert("", "end", iid=str(i), values=r.como_lista(), tags=tuple(tags))
        self._pintar_kpis()
        aviso = ""
        if len(self.filas_vista) > MAX_FILAS_TABLA:
            aviso = f"  ·  se muestran {MAX_FILAS_TABLA:,}, se exportan todos"
        activos = self._filtros_activos()
        filtro = f"  ·  filtros: {', '.join(activos)}" if activos else ""
        self.v_totales.set(f"{len(self.filas_vista):,} renglones{filtro}{aviso}")
        self.v_filtros.set(("Filtros activos: " + "  ·  ".join(activos)) if activos else "Sin filtros")

    def _pintar_kpis(self):
        """Tarjetas y franja de inteligencia, calculadas sobre lo que está a la vista."""
        if not hasattr(self, "_chips"):
            return
        vista = self.filas_vista
        unicos, por_clase = set(), {k: 0 for k in CLASES}
        ing = gas = iva_i = iva_g = saldo = 0.0
        pagos_rep = 0.0
        for r in vista:
            d = r.datos
            k = ((d.get("UUID") or d.get("Archivo") or ""), d.get("Tipo", ""))
            if k in unicos:
                pagos_rep += float(d.get("Imp Pagado") or 0) if d.get("Es Pago") == "Sí" else 0
                continue
            unicos.add(k)
            letra = d.get("Clase", "")
            if letra in por_clase:
                por_clase[letra] += 1
            if letra == "I":
                ing += float(d.get("Total") or 0); iva_i += float(d.get("IVA Trasladado") or 0)
            elif letra == "G":
                gas += float(d.get("Total") or 0); iva_g += float(d.get("IVA Trasladado") or 0)
            if d.get("Método Pago") == "PPD" and d.get("Comprobante") == "Ingreso":
                saldo += float(d.get("Saldo Pendiente") or 0)
            if d.get("Es Pago") == "Sí":
                pagos_rep += float(d.get("Imp Pagado") or 0)
        ri = self.resumen_intel or {}
        self._chips["cfdi"].config(text=f"{len(unicos):,}")
        n_dup = len(ri.get("duplicados_archivos", []) or [])
        self._chips_sub["cfdi"].config(
            text=(f"{n_dup} archivo{'s' if n_dup != 1 else ''} duplicado{'s' if n_dup != 1 else ''} ignorado{'s' if n_dup != 1 else ''}"
                  if n_dup else "sin duplicados"))
        self._chips["ingresos"].config(text=f"$ {ing:,.2f}")
        self._chips_sub["ingresos"].config(text=f"{por_clase['I']} facturas emitidas")
        self._chips["gastos"].config(text=f"$ {gas:,.2f}")
        self._chips_sub["gastos"].config(text=f"{por_clase['G']} facturas recibidas")
        self._chips["iva_i"].config(text=f"$ {iva_i:,.2f}")
        self._chips_sub["iva_i"].config(text="trasladado en lo que emites")
        self._chips["iva_g"].config(text=f"$ {iva_g:,.2f}")
        self._chips_sub["iva_g"].config(text="trasladado en lo que recibes")
        self._chips["saldo"].config(text=f"$ {saldo:,.2f}")
        self._chips_sub["saldo"].config(text=f"pagos REP: $ {pagos_rep:,.2f}")
        for letra, b in self._badges.items():
            b.config(text=f" {letra}  {por_clase[letra]:,} ",
                     relief="sunken" if getattr(self, "_clase_filtro", None) == letra else "flat")
        if ri:
            partes = []
            if ri.get("ppd"):
                partes.append(f"PPD: {ri['ppd_pagadas']} pagadas · {ri['ppd_parciales']} parciales · "
                              f"{ri['ppd_sin_pago']} sin pago")
            if ri.get("reps"):
                partes.append(f"REP: {ri['reps']} docs pagados"
                              + (f" ({ri['reps_sin_factura']} sin su factura leída)" if ri.get("reps_sin_factura") else ""))
            if ri.get("nc_ligadas"):
                partes.append(f"{ri['nc_ligadas']} notas ligadas a su factura")
            if ri.get("perspectiva_asignada"):
                partes.append(f"emitido/recibido por RFC: {ri['perspectiva_asignada']}")
            self.lbl_intel.config(text="  ·  ".join(partes) or "Sin relaciones que reportar.")

    def _intel_de(self, d):
        """Datos de seguimiento de pago para el visor y el PDF."""
        if not d or not d.get("Estatus Pago") or d.get("Comprobante") != "Ingreso":
            return None
        pagos = (self.resumen_intel or {}).get("pagos_por_factura", {}).get(
            (d.get("UUID") or "").upper(), [])
        return {"estatus": d.get("Estatus Pago"), "pagado_rep": d.get("Pagado REP", 0),
                "nc_aplicadas": d.get("NC Aplicadas", 0),
                "saldo_pendiente": d.get("Saldo Pendiente", 0), "pagos": pagos}

    def _ordenar_por(self, columna):
        rev = getattr(self, "_orden_rev", {}).get(columna, False)
        def clave(r):
            v = r.datos.get(columna, "")
            return (0, v) if isinstance(v, (int, float)) else (1, str(v).lower())
        self.filas_vista = sorted(self.filas_vista, key=clave, reverse=rev)
        if not hasattr(self, "_orden_rev"):
            self._orden_rev = {}
        self._orden_rev[columna] = not rev
        self._pintar_tabla()

    def _al_portapapeles(self, texto: str, cuantos: int):
        self.clipboard_clear(); self.clipboard_append(texto); self.update()
        self.v_totales.set(f"Copiado: {cuantos} renglones — pégalo en Excel con Ctrl+V")

    def _copiar_tabla(self):
        if not self.filas_vista:
            messagebox.showinfo(APP, "No hay datos. Dale 'Leer XML' primero."); return
        self._al_portapapeles(a_tsv_cols(self.filas_vista, self.cols_export), len(self.filas_vista))

    def _copiar_seleccion(self):
        sel = self.tabla_datos.selection()
        if not sel:
            messagebox.showinfo(APP, "Selecciona renglones de la tabla."); return
        elegidas = [self.filas_vista[int(i)] for i in sel if int(i) < len(self.filas_vista)]
        self._al_portapapeles(a_tsv_cols(elegidas, self.cols_export), len(elegidas))

    def _exportar_excel(self):
        if not self.filas_vista:
            messagebox.showinfo(APP, "No hay datos. Dale 'Leer XML' primero."); return
        r = filedialog.asksaveasfilename(
            title="Guardar Excel", defaultextension=".xlsx",
            initialfile="cfdi.xlsx", filetypes=[("Excel", "*.xlsx")], parent=self)
        if not r:
            return
        try:
            a_excel(self.filas_vista, r)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP, f"No se pudo guardar: {e}"); return
        self.log.info("Excel generado: %s (%d renglones)", r, len(self.filas_vista))
        messagebox.showinfo(APP, f"Listo: {len(self.filas_vista)} renglones\n{r}")

    def _exportar_csv(self):
        if not self.filas_vista:
            messagebox.showinfo(APP, "No hay datos. Dale 'Leer XML' primero."); return
        r = filedialog.asksaveasfilename(
            title="Guardar CSV", defaultextension=".csv",
            initialfile="cfdi.csv", filetypes=[("CSV", "*.csv")], parent=self)
        if not r:
            return
        try:
            a_csv(self.filas_vista, r)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP, f"No se pudo guardar: {e}"); return
        messagebox.showinfo(APP, f"Listo: {len(self.filas_vista)} renglones\n{r}")

    def _configurar_log(self):
        self.log = logging.getLogger("sat_descarga")
        self.log.setLevel(logging.INFO)
        self.log.handlers.clear()
        fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S")
        h = ColaHandler(self.cola); h.setFormatter(fmt); self.log.addHandler(h)
        try:
            fh = logging.FileHandler(en_datos(self.cfg.opciones.archivo_log), encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
            self.log.addHandler(fh)
        except OSError:
            pass

    # ---------------- tabla
    def _refrescar_lista(self):
        self.tabla.delete(*self.tabla.get_children())
        for i, p in enumerate(self.cfg.perfiles):
            ok = p.valido()
            base = "par" if i % 2 == 0 else "impar"
            tags = (base,) if ok else (base, "revisar")
            self.tabla.insert("", "end", iid=p.id, tags=tags, values=(
                "☑" if p.activo else "☐", p.nombre, p.rfc,
                Path(p.cer_path).name or "—", Path(p.key_path).name or "—",
                "listo" if ok else "revisar datos"))
        n = len(self.cfg.perfiles)
        if hasattr(self, "lbl_ident"):
            self.lbl_ident.config(text=f"{n} RFC{'s' if n != 1 else ''}" if n else "")

    def _click_tabla(self, ev):
        if self.tabla.identify_region(ev.x, ev.y) != "cell":
            return
        if self.tabla.identify_column(ev.x) != "#1":
            return
        iid = self.tabla.identify_row(ev.y)
        p = self.cfg.por_id(iid)
        if p:
            p.activo = not p.activo
            self._guardar_cfg()
            self._refrescar_lista()

    def _marcar(self, valor: bool):
        for p in self.cfg.perfiles:
            p.activo = valor
        self._guardar_cfg(); self._refrescar_lista()

    def _sel(self):
        s = self.tabla.selection()
        return self.cfg.por_id(s[0]) if s else None

    def _agregar(self):
        d = DialogoPerfil(self); self.wait_window(d)
        if not d.resultado:
            return
        repetido = self.cfg.por_rfc(d.resultado.rfc)
        if repetido:
            if not messagebox.askyesno(
                APP,
                f"Ya tienes el RFC {d.resultado.rfc} guardado como '{repetido.nombre}'.\n\n"
                f"¿Agregar '{d.resultado.nombre}' de todos modos como perfil aparte?\n"
                "(El anterior NO se borra.)"):
                return
        self.cfg.agregar(d.resultado)
        self._guardar_cfg(); self._refrescar_lista()
        self.log.info("RFC agregado: %s (%s)", d.resultado.rfc, d.resultado.nombre)

    def _editar(self):
        p = self._sel()
        if not p:
            messagebox.showinfo(APP, "Selecciona un RFC de la lista."); return
        d = DialogoPerfil(self, p, "Editar RFC"); self.wait_window(d)
        if d.resultado:
            d.resultado.id = p.id            # conserva identidad: edita, no duplica
            self.cfg.agregar(d.resultado)
            self._guardar_cfg(); self._refrescar_lista()

    def _quitar(self):
        p = self._sel()
        if not p:
            messagebox.showinfo(APP, "Selecciona un RFC de la lista."); return
        if messagebox.askyesno(APP, f"¿Quitar {p.nombre} ({p.rfc})?\nNo se borran los XML ya descargados."):
            self.cfg.eliminar(p.id); self._guardar_cfg(); self._refrescar_lista()

    def _probar(self):
        p = self._sel()
        if not p:
            messagebox.showinfo(APP, "Selecciona un RFC de la lista."); return
        self.v_estado.set(f"Probando {p.rfc}…"); self.barra.start(12)

        def tarea():
            ok, msg = probar_efirma(p, self.log)
            self.cola.put(("__fin_prueba__", p.rfc, ok, msg))

        threading.Thread(target=tarea, daemon=True).start()

    # ---------------- fechas / carpeta
    def _mes_pasado(self):
        hoy = date.today()
        fin_ant = hoy.replace(day=1) - __import__("datetime").timedelta(days=1)
        self.v_desde.set(fin_ant.replace(day=1).isoformat()); self.v_hasta.set(fin_ant.isoformat())

    def _este_anio(self):
        hoy = date.today()
        self.v_desde.set(f"{hoy.year}-01-01"); self.v_hasta.set(hoy.isoformat())

    def _anio_pasado(self):
        a = date.today().year - 1
        self.v_desde.set(f"{a}-01-01"); self.v_hasta.set(f"{a}-12-31")

    def _elegir_salida(self):
        r = filedialog.askdirectory(title="¿Dónde guardo los XML?", parent=self)
        if r:
            self.v_salida.set(r)

    def _abrir_carpeta(self):
        ruta = Path(self.v_salida.get()).resolve()
        ruta.mkdir(parents=True, exist_ok=True)
        import subprocess, sys
        try:
            if sys.platform.startswith("win"):
                import os
                os.startfile(ruta)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.run(["open", str(ruta)], check=False)
            else:
                subprocess.run(["xdg-open", str(ruta)], check=False)
        except Exception as e:  # noqa: BLE001
            messagebox.showinfo(APP, f"Carpeta: {ruta}\n({e})")

    # ---------------- descarga
    def _validar_fechas(self):
        try:
            d = datetime.strptime(self.v_desde.get().strip(), "%Y-%m-%d")
            h = datetime.strptime(self.v_hasta.get().strip(), "%Y-%m-%d")
        except ValueError:
            messagebox.showerror(APP, "Fechas en formato AAAA-MM-DD, por ejemplo 2026-01-31."); return None
        if d > h:
            messagebox.showerror(APP, "La fecha 'Desde' no puede ser mayor que 'Hasta'."); return None
        return d, h

    def _descargar(self):
        if self.hilo and self.hilo.is_alive():
            return
        rango = self._validar_fechas()
        if not rango:
            return
        desde, hasta = rango
        activos = [p for p in self.cfg.activos() if p.valido()]
        invalidos = [p for p in self.cfg.activos() if not p.valido()]
        for p in invalidos:
            self.log.warning("%s se omite: %s", p.nombre, "; ".join(p.errores()))
        if not activos:
            messagebox.showwarning(APP, "No hay RFCs marcados con datos completos.\n"
                                        "Agrega uno con 'Agregar RFC…' y márcalo en la columna 'Usar'.")
            return

        self.cfg.opciones.carpeta_salida = self.v_salida.get().strip() or "descargas_cfdi"
        self._guardar_cfg()
        try:
            movidos = migrar_estructura_vieja(self.cfg.opciones.carpeta_salida)
            if movidos:
                self.log.info("Se reacomodaron %d XML de descargas anteriores al formato nuevo", movidos)
        except Exception as e:  # noqa: BLE001
            self.log.warning("No se pudo reacomodar lo anterior: %s", e)
        self._cancelar.clear()
        self.btn_desc.config(state="disabled"); self.btn_stop.config(state="normal")
        self.barra.start(12)
        self.v_estado.set(f"Descargando… ({len(activos)} RFC)")
        tipo = self.v_tipo.get()

        def tarea():
            try:
                res = ejecutar_varios(
                    activos, self.cfg, desde, hasta, tipo, self.log,
                    cancelado=self._cancelar.is_set,
                    al_terminar_perfil=lambda r: self.cola.put(r.texto()),
                )
                self.cola.put(("__fin__", resumen_global(res),
                               sum(r.xml_nuevos for r in res), sum(len(r.errores) for r in res)))
            except Exception:  # noqa: BLE001
                self.cola.put(("__fin__", "Error inesperado:\n" + traceback.format_exc(), 0, 1))

        self.hilo = threading.Thread(target=tarea, daemon=True)
        self.hilo.start()

    def _detener(self):
        self._cancelar.set()
        self.v_estado.set("Deteniendo… (termina el paso en curso)")
        self.btn_stop.config(state="disabled")

    # ---------------- cola -> UI
    def _vaciar_cola(self):
        if not self.winfo_exists():
            return
        self._procesar_cola()
        if self.winfo_exists():
            self._after_cola = self.after(120, self._vaciar_cola)

    def _procesar_cola(self):
        """Pinta lo que mandaron los hilos (solo desde el hilo principal)."""
        try:
            while True:
                item = self.cola.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__fin__":
                    _, resumen, xml, errores = item
                    self._escribir(resumen)
                    self.barra.stop()
                    self.btn_desc.config(state="normal"); self.btn_stop.config(state="disabled")
                    self.v_estado.set(f"Terminado — {xml} XML nuevos")
                    self.v_carpeta_datos.set(self.cfg.opciones.carpeta_salida)
                    if errores:
                        messagebox.showwarning(APP, resumen + "\n\nRevisa el registro.")
                    else:
                        messagebox.showinfo(APP, resumen)
                elif isinstance(item, tuple) and item and item[0] == "__fin_pdfs__":
                    self._fin_pdfs(item[1])
                elif isinstance(item, str) and item.startswith("__pdf__"):
                    self.v_totales.set(f"Generando {item[7:]} PDF…")
                elif isinstance(item, tuple) and item and item[0] == "__prog_lectura__":
                    self._progreso_lectura(item[1], item[2])
                elif isinstance(item, tuple) and item and item[0] == "__fin_lectura__":
                    self._fin_lectura(item[1])
                elif isinstance(item, tuple) and item and item[0] == "__fin_prueba__":
                    _, rfc, ok, msg = item
                    self.barra.stop(); self.v_estado.set("Listo")
                    self._escribir(f"[{rfc}] {msg}")
                    (messagebox.showinfo if ok else messagebox.showerror)(APP, f"{rfc}\n\n{msg}")
                else:
                    self._escribir(str(item))
        except queue.Empty:
            pass

    def _escribir(self, texto: str):
        self.txt.config(state="normal")
        self.txt.insert("end", texto + "\n")
        self.txt.see("end")
        self.txt.config(state="disabled")

    # ---------------- misc
    def _guardar_cfg(self):
        op = self.cfg.opciones
        try:
            op.carpeta_salida = self.v_salida.get().strip() or op.carpeta_salida
            op.ultimo_desde = self.v_desde.get().strip()
            op.ultimo_hasta = self.v_hasta.get().strip()
            op.ultimo_tipo = self.v_tipo.get()
        except Exception:  # noqa: BLE001
            pass
        self.cfg.guardar()

    def _cerrar(self):
        if self.hilo and self.hilo.is_alive():
            if not messagebox.askyesno(APP, "Hay una descarga en curso. ¿Salir de todos modos?"):
                return
            self._cancelar.set()
        self._cancelar_lectura.set()
        if getattr(self, "motor", None) is not None:
            self.motor.cerrar()
        aid = getattr(self, "_after_cola", None)
        if aid:
            try:
                self.after_cancel(aid)
            except tk.TclError:
                pass
        self._guardar_cfg()
        self.destroy()


class DialogoDueno(tk.Toplevel):
    """Elegir de quién es la carpeta (el RFC dueño) para saber qué es emitido y qué
    recibido. Lista los RFC más frecuentes; también se puede escribir uno."""

    def __init__(self, padre, candidatos, callback):
        super().__init__(padre)
        self.title("Asignar perspectiva")
        self.transient(padre); self.resizable(False, False)
        self.configure(bg=padre.tema.color("surface"))
        self.callback = callback
        self.candidatos = list(candidatos)
        m = ttk.Frame(self, padding=18, style="Surface.TFrame"); m.grid(sticky="nsew")
        ttk.Label(m, text="¿De quién es esta carpeta?", style="Sub.TLabel").pack(anchor="w")
        ttk.Label(m, text="Lo que ese RFC emitió será Emitido (I) y lo que recibió, Recibido (G).",
                  style="SuaveSurface.TLabel").pack(anchor="w", pady=(2, 8))
        self.lista = tk.Listbox(m, height=min(10, max(3, len(self.candidatos))), width=64,
                                exportselection=False)
        for rfc, nombre, n in self.candidatos:
            self.lista.insert("end", f"{rfc}  ·  {nombre or '—'}  ·  {n:,} comprobantes")
        self.lista.pack(fill="x")
        if self.candidatos:
            self.lista.selection_set(0)
        self.lista.bind("<<ListboxSelect>>", lambda _e: self._al_elegir())
        ttk.Label(m, text="RFC dueño", style="SuaveSurface.TLabel").pack(anchor="w", pady=(10, 2))
        self.v_rfc = tk.StringVar(value=self.candidatos[0][0] if self.candidatos else "")
        ttk.Entry(m, textvariable=self.v_rfc, width=24).pack(anchor="w")
        b = ttk.Frame(m, style="Surface.TFrame"); b.pack(fill="x", pady=(14, 0))
        ttk.Button(b, text="Cancelar", style="Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(b, text="Aplicar", style="Primary.TButton", command=self._aplicar).pack(side="right",
                                                                                         padx=6)
        self.bind("<Return>", lambda _e: self._aplicar())
        self.bind("<Escape>", lambda _e: self.destroy())

    def _al_elegir(self):
        sel = self.lista.curselection()
        if sel:
            self.v_rfc.set(self.candidatos[sel[0]][0])

    def _aplicar(self):
        rfc = self.v_rfc.get().strip().upper()
        self.destroy()
        if rfc:
            self.callback(rfc)


class DialogoColumnas(tk.Toplevel):
    """Elegir qué columnas salen en Copiar tabla / Exportar CSV.
    Cabe en pantallas de laptop (4 columnas), botones arriba, y se GUARDA al
    presionar Guardar o al cerrar con la X."""

    COLS_POR_FILA = 4

    def __init__(self, padre, seleccionadas, callback):
        super().__init__(padre)
        self.title("Columnas para Copiar tabla / CSV")
        self.transient(padre); self.resizable(True, True)
        self.callback = callback
        tema = getattr(padre, "tema", None)
        if tema is not None:
            self.configure(bg=tema.color("surface"))

        m = ttk.Frame(self, padding=14, style="Surface.TFrame")
        m.pack(fill="both", expand=True)

        # --- arriba: título, contador y TODOS los botones (siempre visibles)
        top = ttk.Frame(m, style="Surface.TFrame"); top.pack(fill="x")
        ttk.Label(top, text="Columnas que salen al copiar la tabla", style="Sub.TLabel").pack(side="left")
        self.v_cuenta = tk.StringVar()
        ttk.Label(top, textvariable=self.v_cuenta, style="SuaveSurface.TLabel").pack(side="left", padx=12)
        acc = ttk.Frame(m, style="Surface.TFrame"); acc.pack(fill="x", pady=(8, 10))
        ttk.Button(acc, text="Formato EDDP (65)", style="Ghost.TButton",
                   command=self._preset_eddp).pack(side="left")
        ttk.Button(acc, text="Solo lo fiscal", style="Ghost.TButton",
                   command=self._preset_fiscal).pack(side="left")
        ttk.Button(acc, text="Todas", style="Ghost.TButton",
                   command=lambda: self._marcar(True)).pack(side="left")
        ttk.Button(acc, text="Ninguna", style="Ghost.TButton",
                   command=lambda: self._marcar(False)).pack(side="left")
        ttk.Button(acc, text="Guardar", style="Primary.TButton",
                   command=self._aplicar).pack(side="right")

        # --- rejilla de casillas en 4 columnas (cabe en 1366x768)
        rej = ttk.Frame(m, style="Surface.TFrame"); rej.pack(fill="both", expand=True)
        self.vars = {}
        por_col = -(-len(COLUMNAS) // self.COLS_POR_FILA)
        for i, col in enumerate(COLUMNAS):
            v = tk.BooleanVar(value=col in seleccionadas)
            v.trace_add("write", lambda *_: self._contar())
            self.vars[col] = v
            ttk.Checkbutton(rej, text=col, variable=v, style="Surface.TCheckbutton").grid(
                row=i % por_col, column=i // por_col, sticky="w", padx=(0, 18), pady=0)
        ttk.Label(m, text="Se guarda al presionar Guardar o al cerrar esta ventana.",
                  style="MuteSurface.TLabel").pack(anchor="w", pady=(8, 0))

        self._contar()
        self.protocol("WM_DELETE_WINDOW", self._aplicar)       # cerrar con X = guardar
        self.bind("<Escape>", lambda _e: self._aplicar())
        self.bind("<Return>", lambda _e: self._aplicar())
        self.update_idletasks()
        alto = min(self.winfo_reqheight(), max(400, self.winfo_screenheight() - 80))
        self.geometry(f"{self.winfo_reqwidth()}x{alto}+40+20")
        self.grab_set()

    def _contar(self):
        n = sum(1 for v in self.vars.values() if v.get())
        self.v_cuenta.set(f"{n} de {len(COLUMNAS)} seleccionadas")

    def _marcar(self, val):
        for v in self.vars.values():
            v.set(val)

    def _preset_eddp(self):
        for col, v in self.vars.items():
            v.set(col in COLUMNAS_COPIADO)

    def _preset_fiscal(self):
        fiscales = {"Tipo", "Fecha", "RFC Emisor", "Nombre Emisor", "RFC Receptor",
                    "Nombre Receptor", "SubTotal", "IVA Trasladado", "IVA Retenido",
                    "ISR Retenido", "Total", "Uso CFDI", "Método Pago", "Efecto", "UUID"}
        for col, v in self.vars.items():
            v.set(col in fiscales)

    def _aplicar(self):
        cols = [c for c in COLUMNAS if self.vars[c].get()]
        self.callback(cols)
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class VisorCFDI(tk.Toplevel):
    """Ventana que muestra un CFDI presentado como factura, con botones para
    generar PDF y abrir el XML."""

    def __init__(self, padre, detalle, fila=None):
        super().__init__(padre)
        self.det = detalle
        self.fila = fila or {}
        self.padre = padre
        self.tema = padre.tema
        c = self.tema.color
        self.title(f"CFDI  ·  {detalle.get('uuid','')[:8]}…")
        self.geometry("720x760")
        self.configure(bg=c("bg"))
        self.transient(padre)

        cont = tk.Frame(self, bg=c("bg")); cont.pack(fill="both", expand=True)

        # área con scroll
        cv = tk.Canvas(cont, bg=c("bg"), highlightthickness=0)
        vs = ttk.Scrollbar(cont, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=vs.set)
        cv.pack(side="left", fill="both", expand=True); vs.pack(side="right", fill="y")
        cuerpo = tk.Frame(cv, bg=c("bg"))
        win = cv.create_window((0, 0), window=cuerpo, anchor="nw")
        cuerpo.bind("<Configure>", lambda _e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))

        self._contenido(cuerpo)

        # barra de acciones fija
        barra = tk.Frame(self, bg=c("surface"), height=56)
        barra.pack(fill="x", side="bottom"); barra.pack_propagate(False)
        ttk.Button(barra, text="Descargar PDF", style="Primary.TButton",
                   command=self._pdf).pack(side="left", padx=(14, 6), pady=10)
        ttk.Button(barra, text="Abrir XML", style="Ghost.TButton",
                   command=self._abrir_xml).pack(side="left")
        ttk.Button(barra, text="Cerrar", style="Ghost.TButton",
                   command=self.destroy).pack(side="right", padx=14)

    def _tarjeta(self, padre, titulo):
        c = self.tema.color
        marco = tk.Frame(padre, bg=c("surface"), highlightbackground=c("border"),
                         highlightthickness=1)
        marco.pack(fill="x", padx=16, pady=(0, 12))
        if titulo:
            tk.Label(marco, text=titulo.upper(), bg=c("surface"), fg=c("text_mute"),
                     font=self.tema.fuente("chico")).pack(anchor="w", padx=14, pady=(10, 2))
        return marco

    def _kv(self, padre, k, v, grande=False):
        c = self.tema.color
        f = tk.Frame(padre, bg=c("surface")); f.pack(fill="x", padx=14, pady=1)
        tk.Label(f, text=k, bg=c("surface"), fg=c("text_soft"),
                 font=self.tema.fuente("chico"), width=16, anchor="w").pack(side="left")
        tk.Label(f, text=v or "—", bg=c("surface"), fg=c("text"),
                 font=self.tema.fuente("subtitulo" if grande else "cuerpo"),
                 anchor="w", justify="left", wraplength=460).pack(side="left", fill="x", expand=True)

    def _contenido(self, cuerpo):
        c = self.tema.color
        d = self.det

        # encabezado: título a la izquierda, LETRA GRANDE a la derecha
        enc = tk.Frame(cuerpo, bg=c("bg")); enc.pack(fill="x", padx=16, pady=(14, 10))
        letra = self.fila.get("Clase", "")
        if letra in CLASES:
            nombre_clase = CLASES[letra][0]
            caja = tk.Frame(enc, bg=self.padre._color_clase(letra), width=86, height=78)
            caja.pack(side="right", padx=(10, 0)); caja.pack_propagate(False)
            tk.Label(caja, text=letra, bg=self.padre._color_clase(letra), fg="#FFFFFF",
                     font=(self.tema.familia, 34, "bold")).pack(pady=(4, 0))
            tk.Label(caja, text=nombre_clase.upper(), bg=self.padre._color_clase(letra), fg="#FFFFFF",
                     font=(self.tema.familia, 7, "bold")).pack()
        izq = tk.Frame(enc, bg=c("bg")); izq.pack(side="left", fill="x", expand=True)
        folio = " ".join(x for x in [d.get("serie", ""), d.get("folio", "")] if x)
        tk.Label(izq, text=f"Comprobante de {d.get('tipo_comprobante_desc','')}",
                 bg=c("bg"), fg=c("text"), font=self.tema.fuente("titulo")).pack(anchor="w")
        tk.Label(izq, text=f"CFDI {d.get('version','4.0')}  ·  {folio or 's/folio'}  ·  {d.get('fecha','')}",
                 bg=c("bg"), fg=c("text_soft"), font=self.tema.fuente("chico")).pack(anchor="w")
        if self.fila.get("Tipo"):
            tk.Label(izq, text=f"{self.fila.get('Tipo')}  ·  {self.fila.get('Efecto','')}",
                     bg=c("bg"), fg=c("text_mute"), font=self.tema.fuente("chico")).pack(anchor="w")

        # seguimiento de pago (inteligencia)
        intel = self.padre._intel_de(self.fila)
        if intel:
            m = self._tarjeta(cuerpo, "◆  Seguimiento de pago  (calculado con lo leído)")
            colores = {"Pagada": c("ok"), "Parcial": c("warn"), "Sin pago": c("danger")}
            f = tk.Frame(m, bg=c("surface")); f.pack(fill="x", padx=14, pady=(2, 4))
            tk.Label(f, text=intel["estatus"], bg=c("surface"),
                     fg=colores.get(intel["estatus"], c("text")),
                     font=self.tema.fuente("titulo")).pack(side="left")
            tk.Label(f, text=f"Saldo pendiente  $ {intel['saldo_pendiente']:,.2f}", bg=c("surface"),
                     fg=c("text"), font=self.tema.fuente("subtitulo")).pack(side="right")
            self._kv(m, "Pagado con REP", f"$ {intel['pagado_rep']:,.2f}")
            self._kv(m, "Notas de crédito", f"$ {intel['nc_aplicadas']:,.2f}")
            for e in intel.get("pagos", []):
                self._kv(m, f"REP parc. {e.get('parcialidad','')}",
                         f"{e.get('fecha_pago','')[:10]}  ·  $ {e.get('imp_pagado',0):,.2f}  ·  "
                         f"saldo $ {e.get('saldo_insoluto',0):,.2f}  ·  {e.get('rep_uuid','')[:8]}…"
                         + ("  (memoria)" if e.get("origen") == "memoria" else ""))
            tk.Frame(m, bg=c("surface"), height=8).pack()
        elif self.fila.get("Factura Encontrada"):
            m = self._tarjeta(cuerpo, "◆  Relación con su factura")
            self._kv(m, "Factura", self.fila.get("Factura Encontrada"))
            if self.fila.get("Estatus Pago"):
                self._kv(m, "Este pago", self.fila.get("Estatus Pago"))
            tk.Frame(m, bg=c("surface"), height=8).pack()

        # emisor
        m = self._tarjeta(cuerpo, "Emisor")
        self._kv(m, "Nombre", d.get("emisor_nombre"), grande=True)
        self._kv(m, "RFC", d.get("emisor_rfc"))
        self._kv(m, "Régimen", d.get("emisor_regimen"))
        tk.Frame(m, bg=c("surface"), height=8).pack()

        # receptor
        m = self._tarjeta(cuerpo, "Receptor")
        self._kv(m, "Nombre", d.get("receptor_nombre"), grande=True)
        self._kv(m, "RFC", d.get("receptor_rfc"))
        self._kv(m, "Uso CFDI", d.get("uso_cfdi"))
        tk.Frame(m, bg=c("surface"), height=8).pack()

        # pago
        m = self._tarjeta(cuerpo, "Pago")
        self._kv(m, "Método", d.get("metodo_pago"))
        self._kv(m, "Forma", d.get("forma_pago"))
        self._kv(m, "Moneda", d.get("moneda"))
        tk.Frame(m, bg=c("surface"), height=8).pack()

        # conceptos
        m = self._tarjeta(cuerpo, "Conceptos")
        cab = tk.Frame(m, bg=c("header_bg")); cab.pack(fill="x", padx=1)
        for txt, w, a in [("Cant.", 6, "w"), ("Descripción", 40, "w"),
                          ("V. unit.", 12, "e"), ("Importe", 12, "e")]:
            tk.Label(cab, text=txt, bg=c("header_bg"), fg=c("header_text"),
                     font=self.tema.fuente("chico"), width=w, anchor=a).pack(side="left", padx=4, pady=5)
        for i, con in enumerate(d.get("conceptos", [])):
            bg = c("surface") if i % 2 == 0 else c("surface_alt")
            f = tk.Frame(m, bg=bg); f.pack(fill="x", padx=1)
            tk.Label(f, text=f"{con['cantidad']:g}", bg=bg, fg=c("text"),
                     font=self.tema.fuente("chico"), width=6, anchor="w").pack(side="left", padx=4, pady=3)
            tk.Label(f, text=con.get("descripcion", ""), bg=bg, fg=c("text"),
                     font=self.tema.fuente("chico"), width=40, anchor="w",
                     justify="left", wraplength=280).pack(side="left", padx=4)
            tk.Label(f, text=f"$ {con['valor_unitario']:,.2f}", bg=bg, fg=c("text_soft"),
                     font=self.tema.fuente("chico"), width=12, anchor="e").pack(side="left", padx=4)
            tk.Label(f, text=f"$ {con['importe']:,.2f}", bg=bg, fg=c("text"),
                     font=self.tema.fuente("chico"), width=12, anchor="e").pack(side="left", padx=4)
        tk.Frame(m, bg=c("surface"), height=6).pack()

        # totales
        m = self._tarjeta(cuerpo, "")
        def total(k, v, fuerte=False, neg=False):
            f = tk.Frame(m, bg=c("surface")); f.pack(fill="x", padx=14, pady=2)
            tk.Label(f, text=k, bg=c("surface"),
                     fg=c("primary") if fuerte else c("text_soft"),
                     font=self.tema.fuente("fuerte" if fuerte else "cuerpo")).pack(side="left")
            signo = "- " if neg else ""
            tk.Label(f, text=f"{signo}$ {v:,.2f}", bg=c("surface"),
                     fg=c("primary") if fuerte else c("text"),
                     font=self.tema.fuente("titulo" if fuerte else "cuerpo")).pack(side="right")
        tk.Frame(m, bg=c("surface"), height=6).pack()
        total("SubTotal", d.get("subtotal", 0))
        if d.get("descuento"): total("Descuento", d["descuento"], neg=True)
        if d.get("iva_trasladado"): total("IVA trasladado", d["iva_trasladado"])
        if d.get("iva_retenido"): total("IVA retenido", d["iva_retenido"], neg=True)
        if d.get("isr_retenido"): total("ISR retenido", d["isr_retenido"], neg=True)
        tk.Frame(m, bg=c("border"), height=1).pack(fill="x", padx=14, pady=4)
        total("TOTAL", d.get("total", 0), fuerte=True)
        tk.Frame(m, bg=c("surface"), height=8).pack()

        # pago (complemento de pagos)
        if d.get("es_pago") or d.get("pago_monto"):
            m = self._tarjeta(cuerpo, "◆  Complemento de pago")
            f = tk.Frame(m, bg=c("surface")); f.pack(fill="x", padx=14, pady=(2, 4))
            tk.Label(f, text="Monto pagado", bg=c("surface"), fg=c("text_soft"),
                     font=self.tema.fuente("cuerpo")).pack(side="left")
            tk.Label(f, text=f"$ {d.get('pago_monto', 0):,.2f}", bg=c("surface"),
                     fg=c("ok"), font=self.tema.fuente("titulo")).pack(side="right")
            self._kv(m, "Fecha de pago", d.get("pago_fecha"))
            self._kv(m, "Forma de pago", d.get("pago_forma"))
            if d.get("pago_iva"):
                self._kv(m, "IVA del pago", f"$ {d.get('pago_iva', 0):,.2f}")
            if d.get("pago_moneda"):
                self._kv(m, "Moneda", d.get("pago_moneda"))
            if d.get("pago_num_operacion"):
                self._kv(m, "Núm. operación", d.get("pago_num_operacion"))
            docs = d.get("pago_docs", [])
            if docs:
                tk.Label(m, text="DOCUMENTOS PAGADOS", bg=c("surface"), fg=c("text_mute"),
                         font=self.tema.fuente("chico")).pack(anchor="w", padx=14, pady=(8, 2))
                cab = tk.Frame(m, bg=c("header_bg")); cab.pack(fill="x", padx=14)
                for txt, w, a in [("UUID (factura)", 22, "w"), ("Serie·Folio", 12, "w"),
                                  ("Parc.", 5, "center"), ("Base", 11, "e"),
                                  ("Tasa", 7, "center"), ("IVA", 10, "e"),
                                  ("Pagado", 11, "e"), ("Saldo", 11, "e")]:
                    tk.Label(cab, text=txt, bg=c("header_bg"), fg=c("header_text"),
                             font=self.tema.fuente("chico"), width=w, anchor=a).pack(side="left", padx=2, pady=4)
                for i, doc in enumerate(docs):
                    bg = c("surface") if i % 2 == 0 else c("surface_alt")
                    fr = tk.Frame(m, bg=bg); fr.pack(fill="x", padx=14)
                    sf = "·".join(x for x in [doc.get("serie", ""), doc.get("folio", "")] if x)
                    tasa = f"{float(doc['tasa'])*100:.0f}%" if doc.get("tasa") else ""
                    for val, w, a, col in [
                        (doc["uuid"], 22, "w", c("primary")),
                        (sf, 12, "w", c("text_soft")),
                        (doc.get("parcialidad", ""), 5, "center", c("text")),
                        (f"$ {doc.get('base', 0):,.2f}", 11, "e", c("text_soft")),
                        (tasa, 7, "center", c("text_soft")),
                        (f"$ {doc.get('iva', 0):,.2f}", 10, "e", c("warn")),
                        (f"$ {doc['pagado']:,.2f}", 11, "e", c("text")),
                        (f"$ {doc['saldo_insoluto']:,.2f}", 11, "e", c("text_soft")),
                    ]:
                        fnt = self.tema.fuente("fuerte") if a == "e" and col == c("text") else self.tema.fuente("chico")
                        tk.Label(fr, text=val, bg=bg, fg=col, font=fnt,
                                 width=w, anchor=a).pack(side="left", padx=2, pady=2)
            tk.Frame(m, bg=c("surface"), height=8).pack()

        # cfdi relacionados
        rels = d.get("relacionados", [])
        if rels:
            m = self._tarjeta(cuerpo, "◆  CFDI relacionados")
            for r in rels:
                fr = tk.Frame(m, bg=c("surface")); fr.pack(fill="x", padx=14, pady=2)
                tk.Label(fr, text=r["uuid"], bg=c("surface"), fg=c("primary"),
                         font=self.tema.fuente("chico"), anchor="w").pack(side="left")
                tk.Label(fr, text=r.get("tipo_desc", ""), bg=c("surface"), fg=c("warn"),
                         font=self.tema.fuente("chico"), anchor="e").pack(side="right")
            tk.Frame(m, bg=c("surface"), height=8).pack()

        # timbre
        m = self._tarjeta(cuerpo, "Timbre fiscal")
        self._kv(m, "UUID", d.get("uuid"))
        self._kv(m, "Timbrado", d.get("fecha_timbrado"))
        tk.Frame(m, bg=c("surface"), height=8).pack()

        # volcado completo del XML (todos los campos, menos sellos)
        filas = volcado_xml(d.get("archivo", ""))
        if filas:
            m = self._tarjeta(cuerpo, f"◆  Todos los datos del XML  ({len(filas)} campos)")
            cab = tk.Frame(m, bg=c("header_bg")); cab.pack(fill="x", padx=14)
            for txt, w in [("Nodo", 34), ("Campo", 26), ("Valor", 40)]:
                tk.Label(cab, text=txt, bg=c("header_bg"), fg=c("header_text"),
                         font=self.tema.fuente("chico"), width=w, anchor="w").pack(side="left", padx=3, pady=4)
            for i, (nodo, campo, valor) in enumerate(filas):
                bg = c("surface") if i % 2 == 0 else c("surface_alt")
                fr = tk.Frame(m, bg=bg); fr.pack(fill="x", padx=14)
                tk.Label(fr, text=nodo, bg=bg, fg=c("text_soft"),
                         font=self.tema.fuente("chico"), width=34, anchor="w").pack(side="left", padx=3, pady=1)
                tk.Label(fr, text=campo, bg=bg, fg=c("text"),
                         font=self.tema.fuente("chico"), width=26, anchor="w").pack(side="left", padx=3)
                tk.Label(fr, text=valor, bg=bg, fg=c("text"),
                         font=self.tema.fuente("chico"), width=40, anchor="w").pack(side="left", padx=3)
            tk.Frame(m, bg=c("surface"), height=8).pack()

    def _pdf(self):
        config = self.padre.diseno_de_fila(self.fila or {})
        sugerido = nombre_pdf(plantilla_de(config), self.fila) \
            if self.fila else f"CFDI_{self.det.get('uuid','factura')[:8]}.pdf"
        r = filedialog.asksaveasfilename(title="Guardar PDF", defaultextension=".pdf",
                                         initialfile=sugerido,
                                         filetypes=[("PDF", "*.pdf")], parent=self)
        if not r:
            return
        try:
            cfdi_a_pdf(self.det, r, config=config, clase=self.fila.get("Clase", ""),
                       tipo=self.fila.get("Tipo", ""), inteligencia=self.padre._intel_de(self.fila))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP, f"No se pudo generar el PDF: {e}"); return
        messagebox.showinfo(APP, f"PDF generado:\n{r}")
        self._abrir_archivo(r)

    def _abrir_xml(self):
        self._abrir_archivo(self.det.get("archivo", ""))

    def _abrir_archivo(self, ruta):
        import subprocess
        import sys
        if not ruta:
            return
        try:
            if sys.platform.startswith("win"):
                import os
                os.startfile(ruta)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.run(["open", ruta], check=False)
            else:
                subprocess.run(["xdg-open", ruta], check=False)
        except Exception:  # noqa: BLE001
            pass


class DialogoPerfilReporte(tk.Toplevel):
    """Editor de un perfil de reporte (cliente) o del diseño general.
    Izquierda: datos del perfil (RFC dueño, carpetas, filtros, columnas).
    Derecha: diseño del PDF (textos, color, logo, nombre, subcarpetas, secciones)."""

    def __init__(self, padre, perfil=None):
        super().__init__(padre)
        self.padre = padre
        self.perfil = perfil                       # None = diseño general
        es_general = perfil is None
        self.title("Diseño general del PDF" if es_general else f"Perfil · {perfil.nombre}")
        self.transient(padre); self.resizable(False, False)
        self.configure(bg=padre.tema.color("surface"))
        diseno = completar_diseno(padre.perfiles_rep.general if es_general else perfil.diseno)

        m = ttk.Frame(self, padding=16, style="Surface.TFrame"); m.grid(sticky="nsew")
        izq = ttk.Frame(m, style="Surface.TFrame"); izq.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        der = ttk.Frame(m, style="Surface.TFrame"); der.grid(row=0, column=1, sticky="nsew")

        def campo(padre_f, etiqueta, var, ancho=40, boton=None):
            ttk.Label(padre_f, text=etiqueta, style="SuaveSurface.TLabel").pack(anchor="w", pady=(6, 1))
            fila = ttk.Frame(padre_f, style="Surface.TFrame"); fila.pack(fill="x")
            ttk.Entry(fila, textvariable=var, width=ancho).pack(side="left", fill="x", expand=True)
            if boton:
                ttk.Button(fila, text="…", width=3, command=boton).pack(side="left", padx=(6, 0))

        # ---------- izquierda: el perfil
        self.v_nombre = tk.StringVar(value="" if es_general else perfil.nombre)
        self.v_rfcs = tk.StringVar(value="" if es_general else ", ".join(perfil.rfcs))
        self.v_xml = tk.StringVar(value="" if es_general else perfil.carpeta_xml)
        self.v_pdf = tk.StringVar(value="" if es_general else perfil.carpeta_pdf)
        filtros = FILTROS_DEFAULT if es_general else perfil.filtros
        self.v_f = {k: tk.StringVar(value=str(filtros.get(k, ""))) for k in FILTROS_DEFAULT}
        self.columnas = [] if es_general else list(perfil.columnas_copiado)
        if es_general:
            ttk.Label(izq, text="Diseño general", style="Sub.TLabel").pack(anchor="w")
            ttk.Label(izq, text="Se usa cuando no hay perfil activo y para los RFC\n"
                                "que no tienen perfil propio.", style="SuaveSurface.TLabel",
                      justify="left").pack(anchor="w", pady=(4, 0))
        else:
            ttk.Label(izq, text="Perfil", style="Sub.TLabel").pack(anchor="w")
            campo(izq, "Nombre", self.v_nombre)
            campo(izq, "RFC(s) dueño(s)  ·  separados por coma", self.v_rfcs)
            campo(izq, "Carpeta de XML", self.v_xml, boton=lambda: self._carpeta(self.v_xml))
            campo(izq, "Carpeta de salida de PDFs", self.v_pdf, boton=lambda: self._carpeta(self.v_pdf))
            ttk.Label(izq, text="Filtros por defecto", style="Sub.TLabel").pack(anchor="w", pady=(12, 0))
            ff = ttk.Frame(izq, style="Surface.TFrame"); ff.pack(fill="x")
            for i, (k, et, vals) in enumerate((("tipo", "Tipo", ["todos", "Emitido", "Recibido"]),
                                               ("clase", "Clase", [""] + list(CLASES)))):
                ttk.Label(ff, text=et, style="SuaveSurface.TLabel").grid(row=0, column=i, sticky="w")
                ttk.Combobox(ff, textvariable=self.v_f[k], values=vals, state="readonly",
                             width=10).grid(row=1, column=i, sticky="w", padx=(0, 8))
            ttk.Label(ff, text="Mes (AAAA-MM)", style="SuaveSurface.TLabel").grid(row=0, column=2, sticky="w")
            ttk.Entry(ff, textvariable=self.v_f["mes"], width=10).grid(row=1, column=2, sticky="w")
            campo(izq, "Texto a buscar", self.v_f["texto"])
            ttk.Label(izq, text="Columnas de Copiar tabla", style="Sub.TLabel").pack(anchor="w", pady=(12, 0))
            fc = ttk.Frame(izq, style="Surface.TFrame"); fc.pack(fill="x", pady=(4, 0))
            self.v_cols = tk.StringVar()
            ttk.Label(fc, textvariable=self.v_cols, style="SuaveSurface.TLabel").pack(side="left")
            ttk.Button(fc, text="Elegir…", command=self._elegir_columnas).pack(side="right")
            self._contar_columnas()

        # ---------- derecha: diseño del PDF
        ttk.Label(der, text="Diseño del PDF", style="Sub.TLabel").pack(anchor="w")
        self.v = {k: tk.StringVar(value=str(diseno.get(k, ""))) for k in
                  ("titulo", "subtitulo", "pie", "color_primario", "logo", "nombre_archivo")}
        campo(der, "Título (vacío = nombre del contribuyente)", self.v["titulo"])
        campo(der, "Subtítulo", self.v["subtitulo"])
        campo(der, "Pie de página", self.v["pie"])
        campo(der, "Color principal (#RRGGBB)", self.v["color_primario"])
        campo(der, "Logo (PNG o JPG)", self.v["logo"], boton=lambda: self._logo(self.v["logo"]))
        campo(der, "Nombre de archivo  ·  {fecha} {clase} {tipo} {rfc_contraparte} {serie} {folio} {uuid8}",
              self.v["nombre_archivo"])
        ttk.Label(der, text="Organizar PDFs", style="SuaveSurface.TLabel").pack(anchor="w", pady=(6, 1))
        self.v_sub = tk.StringVar(value=SUBCARPETAS.get(diseno.get("subcarpetas", ""), SUBCARPETAS[""]))
        ttk.Combobox(der, textvariable=self.v_sub, values=list(SUBCARPETAS.values()), state="readonly",
                     width=32).pack(anchor="w")
        ttk.Label(der, text="Secciones del PDF", style="Sub.TLabel").pack(anchor="w", pady=(12, 2))
        sec = ttk.Frame(der, style="Surface.TFrame"); sec.pack(fill="x")
        self.b = {k: tk.BooleanVar(value=bool(diseno["secciones"].get(k, v[1])))
                  for k, v in SECCIONES.items()}
        for i, (k, (etiqueta, _d)) in enumerate(SECCIONES.items()):
            ttk.Checkbutton(sec, text=etiqueta, variable=self.b[k], style="Surface.TCheckbutton").grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 10), pady=1)

        acc = ttk.Frame(m, style="Surface.TFrame")
        acc.grid(row=1, column=0, columnspan=2, sticky="we", pady=(16, 0))
        ttk.Button(acc, text="Abrir JSON", style="Ghost.TButton",
                   command=lambda: padre._abrir_ruta(str(padre.perfiles_rep.ruta))).pack(side="left")
        ttk.Button(acc, text="Cancelar", style="Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(acc, text="Guardar", style="Primary.TButton", command=self._guardar).pack(side="right",
                                                                                         padx=6)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    def _carpeta(self, var):
        r = filedialog.askdirectory(title="Elegir carpeta", parent=self, initialdir=var.get() or None)
        if r:
            var.set(r)

    def _logo(self, var):
        r = filedialog.askopenfilename(title="Logo", filetypes=[("Imagen", "*.png *.jpg *.jpeg")],
                                       parent=self)
        if r:
            var.set(r)

    def _contar_columnas(self):
        n = len(self.columnas)
        self.v_cols.set(f"{n} columnas (personalizado)" if n
                        else f"{len(COLUMNAS_COPIADO)} columnas (formato EDDP)")

    def _elegir_columnas(self):
        def poner(cols):
            self.columnas = [] if (not cols or cols == list(COLUMNAS_COPIADO)) else list(cols)
            self._contar_columnas()
        DialogoColumnas(self, self.columnas or list(COLUMNAS_COPIADO), poner)

    def diseno(self):
        """El diseño tal como está en el formulario."""
        sub = next((k for k, v in SUBCARPETAS.items() if v == self.v_sub.get()), "")
        d = {k: var.get().strip() for k, var in self.v.items()}
        d["subcarpetas"] = sub
        d["secciones"] = {k: bool(var.get()) for k, var in self.b.items()}
        return completar_diseno(d)

    def _guardar(self):
        padre = self.padre
        if self.perfil is None:
            padre.perfiles_rep.general = self.diseno()
        else:
            if not self.v_nombre.get().strip():
                messagebox.showerror(APP, "El perfil necesita un nombre.", parent=self); return
            editado = PerfilReporte(
                id=self.perfil.id, nombre=self.v_nombre.get(), rfcs=self.v_rfcs.get(),
                carpeta_xml=self.v_xml.get().strip(), carpeta_pdf=self.v_pdf.get().strip(),
                diseno=self.diseno(), columnas_copiado=self.columnas,
                filtros={k: v.get().strip() for k, v in self.v_f.items()})
            padre.perfiles_rep.reemplazar(editado)
        padre._guardar_perfiles()
        padre._refrescar_perfiles()
        padre.cols_export = padre._columnas_vigentes()
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
