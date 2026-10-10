# -*- coding: utf-8 -*-
"""Motor visual: paleta, tipografía y estilos ttk.

Un solo lugar define cómo se ve toda la app. Cambiar de tema (claro/oscuro)
es cambiar un diccionario. Sin dependencias externas: solo ttk.
"""
from tkinter import font as tkfont
from tkinter import ttk

# --------------------------------------------------------------- paletas
CLARO = {
    "bg": "#F4F6F9",           # fondo general
    "surface": "#FFFFFF",      # tarjetas / paneles
    "surface_alt": "#EEF1F6",  # filas alternas / hover suave
    "border": "#DCE1E8",
    "text": "#1C2430",
    "text_soft": "#5A6577",
    "text_mute": "#8A93A3",
    "primary": "#2D6CDF",      # acción principal
    "primary_hover": "#245BC0",
    "primary_text": "#FFFFFF",
    "ok": "#1F9D57",
    "warn": "#C9781A",
    "danger": "#C7402F",
    "sel_bg": "#E4EDFC",       # selección en tablas
    "sel_text": "#12335F",
    "header_bg": "#2A3342",    # encabezado de tabla
    "header_text": "#FFFFFF",
    "log_bg": "#0F1420",
    "log_text": "#D6E2EA",
}
OSCURO = {
    "bg": "#141922",
    "surface": "#1C2330",
    "surface_alt": "#232C3B",
    "border": "#2E3A4C",
    "text": "#E7ECF3",
    "text_soft": "#AEB8C7",
    "text_mute": "#7C889A",
    "primary": "#4C8DFF",
    "primary_hover": "#3D7BE8",
    "primary_text": "#FFFFFF",
    "ok": "#3FBA6E",
    "warn": "#E0A955",
    "danger": "#E5675A",
    "sel_bg": "#26364F",
    "sel_text": "#DCE8FB",
    "header_bg": "#0F1420",
    "header_text": "#E7ECF3",
    "log_bg": "#0B0F17",
    "log_text": "#CBD6E2",
}
TEMAS = {"claro": CLARO, "oscuro": OSCURO}


def _familia_disponible(root, preferidas):
    disp = set(tkfont.families(root))
    for f in preferidas:
        if f in disp:
            return f
    return "TkDefaultFont"


class Tema:
    """Aplica una paleta a un root ttk y expone los colores usados por widgets
    que no son ttk (Text del log, filas del Treeview, etc.)."""

    def __init__(self, root, nombre="claro"):
        self.root = root
        self.nombre = nombre if nombre in TEMAS else "claro"
        self.c = dict(TEMAS[self.nombre])
        self.familia = _familia_disponible(
            root, ["Segoe UI", "Inter", "Helvetica Neue", "Arial", "DejaVu Sans"])
        self.familia_mono = _familia_disponible(
            root, ["Cascadia Code", "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"])
        self._definir_fuentes()
        self.style = ttk.Style(root)
        self.aplicar()

    # ---------------------------------------------------------- fuentes
    def _definir_fuentes(self):
        f = self.familia
        self.fuentes = {
            "base": tkfont.Font(family=f, size=10),
            "cuerpo": tkfont.Font(family=f, size=10),
            "fuerte": tkfont.Font(family=f, size=10, weight="bold"),
            "titulo": tkfont.Font(family=f, size=15, weight="bold"),
            "subtitulo": tkfont.Font(family=f, size=11, weight="bold"),
            "chico": tkfont.Font(family=f, size=9),
            "tabla": tkfont.Font(family=f, size=10),
            "tabla_head": tkfont.Font(family=f, size=10, weight="bold"),
            "mono": tkfont.Font(family=self.familia_mono, size=9),
        }

    # ---------------------------------------------------------- aplicar
    def aplicar(self):
        c = self.c
        st = self.style
        try:
            st.theme_use("clam")            # base neutra sobre la que pintamos
        except Exception:  # noqa: BLE001
            pass

        self.root.configure(bg=c["bg"])

        st.configure(".", background=c["bg"], foreground=c["text"],
                     fieldbackground=c["surface"], font=self.fuentes["base"],
                     bordercolor=c["border"], focuscolor=c["primary"])

        st.configure("TFrame", background=c["bg"])
        st.configure("Surface.TFrame", background=c["surface"])
        st.configure("TLabel", background=c["bg"], foreground=c["text"])
        st.configure("Surface.TLabel", background=c["surface"], foreground=c["text"])
        st.configure("Titulo.TLabel", background=c["bg"], foreground=c["text"],
                     font=self.fuentes["titulo"])
        st.configure("Sub.TLabel", background=c["surface"], foreground=c["text"],
                     font=self.fuentes["subtitulo"])
        st.configure("Suave.TLabel", background=c["bg"], foreground=c["text_soft"],
                     font=self.fuentes["chico"])
        st.configure("SuaveSurface.TLabel", background=c["surface"],
                     foreground=c["text_soft"], font=self.fuentes["chico"])
        st.configure("Mute.TLabel", background=c["surface"], foreground=c["text_mute"],
                     font=self.fuentes["chico"])
        st.configure("MuteSurface.TLabel", background=c["surface"], foreground=c["text_mute"],
                     font=self.fuentes["chico"])
        st.configure("Ok.TLabel", background=c["surface"], foreground=c["ok"],
                     font=self.fuentes["fuerte"])
        st.configure("Warn.TLabel", background=c["surface"], foreground=c["warn"],
                     font=self.fuentes["fuerte"])

        # tarjetas: LabelFrame con borde suave
        st.configure("Card.TLabelframe", background=c["surface"],
                     bordercolor=c["border"], relief="solid", borderwidth=1)
        st.configure("Card.TLabelframe.Label", background=c["surface"],
                     foreground=c["text_soft"], font=self.fuentes["subtitulo"])

        # botones
        st.configure("TButton", background=c["surface_alt"], foreground=c["text"],
                     borderwidth=1, bordercolor=c["border"], focusthickness=1,
                     focuscolor=c["primary"], padding=(12, 7), font=self.fuentes["cuerpo"])
        st.map("TButton",
               background=[("pressed", c["border"]), ("active", c["surface_alt"])],
               bordercolor=[("active", c["primary"])])

        st.configure("Primary.TButton", background=c["primary"],
                     foreground=c["primary_text"], borderwidth=0,
                     padding=(16, 8), font=self.fuentes["fuerte"])
        st.map("Primary.TButton",
               background=[("pressed", c["primary_hover"]), ("active", c["primary_hover"]),
                          ("disabled", c["surface_alt"])],
               foreground=[("disabled", c["text_mute"])])

        st.configure("Ghost.TButton", background=c["surface"], foreground=c["primary"],
                     borderwidth=0, padding=(10, 6))
        st.map("Ghost.TButton", foreground=[("active", c["primary_hover"])],
               background=[("active", c["surface_alt"])])

        st.configure("Peligro.TButton", background=c["surface"], foreground=c["danger"],
                     borderwidth=1, bordercolor=c["border"], padding=(12, 7))
        st.map("Peligro.TButton", background=[("active", "#F7E7E4")])

        # entradas / combos
        for est in ("TEntry", "TCombobox"):
            st.configure(est, fieldbackground=c["surface"], background=c["surface"],
                         foreground=c["text"], bordercolor=c["border"],
                         insertcolor=c["text"], padding=6, arrowcolor=c["text_soft"])
            st.map(est, bordercolor=[("focus", c["primary"])],
                   fieldbackground=[("readonly", c["surface"])])

        st.configure("TCheckbutton", background=c["bg"], foreground=c["text"],
                     focuscolor=c["primary"])
        st.map("TCheckbutton", background=[("active", c["bg"])],
               indicatorcolor=[("selected", c["primary"])])
        st.configure("Surface.TCheckbutton", background=c["surface"], foreground=c["text"])
        st.map("Surface.TCheckbutton", background=[("active", c["surface"])])

        # notebook (pestañas)
        st.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=(6, 6, 6, 0))
        st.configure("TNotebook.Tab", background=c["bg"], foreground=c["text_soft"],
                     padding=(20, 10), font=self.fuentes["cuerpo"], borderwidth=0)
        st.map("TNotebook.Tab",
               background=[("selected", c["surface"])],
               foreground=[("selected", c["primary"])],
               font=[("selected", self.fuentes["fuerte"])],
               expand=[("selected", (0, 0, 0, 0))])

        # tabla
        st.configure("Treeview", background=c["surface"], fieldbackground=c["surface"],
                     foreground=c["text"], borderwidth=0, rowheight=28,
                     font=self.fuentes["tabla"])
        st.configure("Treeview.Heading", background=c["header_bg"],
                     foreground=c["header_text"], relief="flat",
                     font=self.fuentes["tabla_head"], padding=(8, 8))
        st.map("Treeview.Heading", background=[("active", c["header_bg"])])
        st.map("Treeview",
               background=[("selected", c["sel_bg"])],
               foreground=[("selected", c["sel_text"])])

        # scrollbars
        for est in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            st.configure(est, background=c["surface_alt"], troughcolor=c["bg"],
                         bordercolor=c["bg"], arrowcolor=c["text_soft"], borderwidth=0)

        # barra de progreso
        st.configure("TProgressbar", background=c["primary"], troughcolor=c["surface_alt"],
                     borderwidth=0, thickness=8)

        # separadores
        st.configure("TSeparator", background=c["border"])

    # ---------------------------------------------------------- helpers
    # ---------------------------------------------------------- zoom
    ZOOM_MIN, ZOOM_MAX = 0.7, 1.6

    def aplicar_zoom(self, factor: float) -> float:
        """Escala TODAS las fuentes y el alto de las filas en vivo (Ctrl + / Ctrl -).
        Útil en pantallas chicas (laptop) o grandes (monitor externo)."""
        factor = max(self.ZOOM_MIN, min(self.ZOOM_MAX, round(float(factor or 1.0), 2)))
        if not hasattr(self, "_tamanos_base"):
            self._tamanos_base = {k: f.cget("size") for k, f in self.fuentes.items()}
        for k, f in self.fuentes.items():
            base = self._tamanos_base[k]
            f.configure(size=max(6, int(round(base * factor))))
        self.style.configure("Treeview", rowheight=max(18, int(round(28 * factor))))
        self.zoom = factor
        return factor

    def color(self, clave):
        return self.c[clave]

    def fuente(self, clave):
        return self.fuentes[clave]

    def zebra(self, tree):
        """Configura filas alternas en un Treeview."""
        tree.tag_configure("par", background=self.c["surface"])
        tree.tag_configure("impar", background=self.c["surface_alt"])
