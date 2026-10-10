# -*- coding: utf-8 -*-
"""Motor visual: paleta, tipografía y estilos ttk.

Un solo lugar define cómo se ve toda la app. Cambiar de tema (claro/oscuro)
es cambiar un diccionario. Sin dependencias externas: solo ttk.
"""
from tkinter import font as tkfont
from tkinter import ttk

# --------------------------------------------------------------- paletas
CLARO = {
    "bg": "#F5F6F8",           # fondo general
    "surface": "#FFFFFF",      # tarjetas / paneles
    "surface_alt": "#F1F3F6",  # filas alternas / hover suave
    "border": "#E1E5EB",
    "text": "#12151C",
    "text_soft": "#535B69",
    "text_mute": "#8B93A1",
    "primary": "#2563EB",      # acción principal
    "primary_hover": "#1D4FC4",
    "primary_text": "#FFFFFF",
    "ok": "#1F9D57",
    "warn": "#C9781A",
    "danger": "#C7402F",
    "sel_bg": "#E3ECFD",       # selección en tablas
    "sel_text": "#12335F",
    "header_bg": "#171B24",    # encabezado de tabla
    "header_text": "#FFFFFF",
    "log_bg": "#0F1218",
    "log_text": "#D6E2EA",
    "brand_bg": "#0D0F14",     # barra superior (colores del logo: negro y blanco)
    "brand_text": "#FFFFFF",
    "brand_soft": "#9AA3B2",
    "brand_hover": "#232833",
}
OSCURO = {
    "bg": "#12151C",
    "surface": "#1A1E27",
    "surface_alt": "#212632",
    "border": "#2C3340",
    "text": "#E8ECF2",
    "text_soft": "#AEB6C4",
    "text_mute": "#7C8695",
    "primary": "#5B93FF",
    "primary_hover": "#4A80EA",
    "primary_text": "#FFFFFF",
    "ok": "#3FBA6E",
    "warn": "#E0A955",
    "danger": "#E5675A",
    "sel_bg": "#25344E",
    "sel_text": "#DCE8FB",
    "header_bg": "#0B0D12",
    "header_text": "#E8ECF2",
    "log_bg": "#0A0C11",
    "log_text": "#CBD6E2",
    "brand_bg": "#0A0C11",
    "brand_text": "#FFFFFF",
    "brand_soft": "#8E97A6",
    "brand_hover": "#1F242E",
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

        # lightcolor/darkcolor iguales al fondo: quita los biseles de "clam" (look plano)
        st.configure(".", background=c["bg"], foreground=c["text"],
                     fieldbackground=c["surface"], font=self.fuentes["base"],
                     bordercolor=c["border"], focuscolor=c["primary"],
                     lightcolor=c["bg"], darkcolor=c["bg"])

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
        st.configure("Card.TLabelframe", background=c["surface"], bordercolor=c["border"],
                     lightcolor=c["surface"], darkcolor=c["surface"], relief="solid",
                     borderwidth=1)
        st.configure("Card.TLabelframe.Label", background=c["surface"],
                     foreground=c["text_soft"], font=self.fuentes["subtitulo"])

        # botones
        st.configure("TButton", background=c["surface"], foreground=c["text"],
                     borderwidth=1, bordercolor=c["border"], focusthickness=0,
                     lightcolor=c["surface"], darkcolor=c["surface"], relief="raised",
                     focuscolor=c["primary"], padding=(12, 7), font=self.fuentes["cuerpo"])
        activo = [("pressed", c["border"]), ("active", c["surface_alt"])]
        st.map("TButton", background=activo, lightcolor=activo, darkcolor=activo,
               bordercolor=[("active", c["primary"])],
               foreground=[("disabled", c["text_mute"])])

        st.configure("Primary.TButton", background=c["primary"],
                     foreground=c["primary_text"], borderwidth=1, bordercolor=c["primary"],
                     lightcolor=c["primary"], darkcolor=c["primary"],
                     padding=(16, 7), font=self.fuentes["fuerte"])
        estados = [("disabled", c["surface_alt"]), ("pressed", c["primary_hover"]),
                   ("active", c["primary_hover"])]
        st.map("Primary.TButton", background=estados, lightcolor=estados, darkcolor=estados,
               bordercolor=[("disabled", c["border"]), ("active", c["primary_hover"])],
               foreground=[("disabled", c["text_mute"])])

        # Ghost: botón-enlace sobre tarjeta; GhostBg: lo mismo sobre el fondo general
        for est, fondo in (("Ghost.TButton", c["surface"]), ("GhostBg.TButton", c["bg"])):
            st.configure(est, background=fondo, foreground=c["primary"], borderwidth=0,
                         lightcolor=fondo, darkcolor=fondo, bordercolor=fondo, padding=(10, 6))
            activo = [("active", c["surface_alt"])]
            st.map(est, foreground=[("active", c["primary_hover"])], background=activo,
                   lightcolor=activo, darkcolor=activo, bordercolor=activo)

        st.configure("TMenubutton", background=c["surface"], foreground=c["text"],
                     borderwidth=1, bordercolor=c["border"], lightcolor=c["surface"],
                     darkcolor=c["surface"], arrowcolor=c["text_soft"], relief="raised",
                     padding=(12, 7), font=self.fuentes["cuerpo"])
        activo = [("active", c["surface_alt"])]
        st.map("TMenubutton", background=activo, lightcolor=activo, darkcolor=activo,
               bordercolor=[("active", c["primary"])])

        st.configure("Peligro.TButton", background=c["surface"], foreground=c["danger"],
                     borderwidth=1, bordercolor=c["border"], lightcolor=c["surface"],
                     darkcolor=c["surface"], padding=(12, 7))
        st.map("Peligro.TButton", background=[("active", "#F7E7E4")])

        # entradas / combos
        for est in ("TEntry", "TCombobox"):
            st.configure(est, fieldbackground=c["surface"], background=c["surface"],
                         foreground=c["text"], bordercolor=c["border"],
                         lightcolor=c["surface"], darkcolor=c["surface"],
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
        st.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=(0, 4, 0, 0),
                     bordercolor=c["border"], lightcolor=c["bg"], darkcolor=c["bg"])
        st.configure("TNotebook.Tab", background=c["bg"], foreground=c["text_soft"],
                     padding=(20, 9), font=self.fuentes["cuerpo"], borderwidth=0,
                     bordercolor=c["bg"], lightcolor=c["bg"], darkcolor=c["bg"])
        st.map("TNotebook.Tab",
               background=[("selected", c["surface"]), ("active", c["surface_alt"])],
               lightcolor=[("selected", c["surface"])],
               bordercolor=[("selected", c["border"])],
               foreground=[("selected", c["text"])],
               font=[("selected", self.fuentes["fuerte"])],
               expand=[("selected", (0, 0, 0, 0))])

        # tabla
        st.configure("Treeview", background=c["surface"], fieldbackground=c["surface"],
                     foreground=c["text"], borderwidth=0, rowheight=28,
                     bordercolor=c["border"], lightcolor=c["surface"], darkcolor=c["surface"],
                     font=self.fuentes["tabla"])
        st.configure("Treeview.Heading", background=c["header_bg"],
                     foreground=c["header_text"], relief="flat", borderwidth=0,
                     lightcolor=c["header_bg"], darkcolor=c["header_bg"],
                     bordercolor=c["header_bg"],
                     font=self.fuentes["tabla_head"], padding=(8, 8))
        st.map("Treeview.Heading", background=[("active", c["header_bg"])])
        st.map("Treeview",
               background=[("selected", c["sel_bg"])],
               foreground=[("selected", c["sel_text"])])

        # scrollbars
        for est in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            st.configure(est, background=c["border"], troughcolor=c["bg"],
                         bordercolor=c["bg"], lightcolor=c["border"], darkcolor=c["border"],
                         arrowcolor=c["text_soft"], borderwidth=0, relief="flat")
            st.map(est, background=[("active", c["text_mute"])])

        # barra de progreso
        st.configure("TProgressbar", background=c["primary"], troughcolor=c["border"],
                     bordercolor=c["border"], lightcolor=c["primary"], darkcolor=c["primary"],
                     borderwidth=0, thickness=6)

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
