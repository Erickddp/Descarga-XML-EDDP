# -*- coding: utf-8 -*-
"""PDF de representación visual del CFDI (no es el CFDI fiscal: es para leerlo
cómodo, imprimir o compartir).

Personalizable con pdf_config.json (en la carpeta de datos):
  - título / subtítulo / pie de página
  - logo (PNG o JPG)
  - color principal
  - ajustes por RFC (cada cliente con su nombre y su logo)

Cada PDF lleva una LETRA GRANDE según qué es para quien lo lee:
  I ingreso · G gasto · N nómina · P pago · E nota de crédito · T traslado
"""
import copy
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Dict, List, Optional
from xml.sax.saxutils import escape

from .lector import CLASES
from .perfiles import completar_diseno

# ---------------------------------------------------------------- configuración
CONFIG_DEFAULT = {
    "_ayuda": [
        "Configuración del PDF de DESCARGA XML EDDP.",
        "general: aplica a todos. por_rfc: sobreescribe para un RFC (tu cliente).",
        "titulo vacío = se usa el nombre del contribuyente que viene en el XML.",
        "logo: ruta a un PNG/JPG (ej. C:/Users/Erick/logos/eddp.png). Vacío = sin logo.",
        "color_primario: color hexadecimal, ej. #1F4E78.",
        "nombre_archivo admite: {fecha} {clase} {tipo} {rfc_contraparte} {serie} {folio} {uuid8} {uuid}",
    ],
    "general": {
        "titulo": "",
        "subtitulo": "Representación impresa de CFDI",
        "logo": "",
        "color_primario": "#1F4E78",
        "pie": "Generado con DESCARGA XML EDDP",
        "mostrar_letra_clase": True,
        "mostrar_inteligencia": True,
        "mostrar_sello_sat": False,
        "nombre_archivo": "{fecha}_{clase}_{rfc_contraparte}_{serie}{folio}_{uuid8}",
    },
    "por_rfc": {
        "XAXX010101000": {"titulo": "EJEMPLO: NOMBRE DE TU CLIENTE", "logo": ""}
    },
}


def ruta_config_pdf() -> Path:
    from .config import carpeta_datos
    return carpeta_datos() / "pdf_config.json"


def cargar_config_pdf(ruta: Optional[str] = None) -> Dict:
    """Lee pdf_config.json (lo crea con valores de ejemplo si no existe).
    Campos faltantes se completan con los defaults: un JSON a medias no truena."""
    p = Path(ruta) if ruta else ruta_config_pdf()
    cfg = copy.deepcopy(CONFIG_DEFAULT)
    if not p.exists():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(CONFIG_DEFAULT, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return cfg
    try:
        leido = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg                                    # JSON roto: defaults, sin tronar
    cfg["general"].update({k: v for k, v in (leido.get("general") or {}).items()})
    cfg["por_rfc"] = {str(k).upper(): v for k, v in (leido.get("por_rfc") or {}).items()
                      if isinstance(v, dict)}
    return cfg


def guardar_config_pdf(cfg: Dict, ruta: Optional[str] = None) -> str:
    p = Path(ruta) if ruta else ruta_config_pdf()
    p.parent.mkdir(parents=True, exist_ok=True)
    salida = {"_ayuda": CONFIG_DEFAULT["_ayuda"], "general": cfg.get("general", {}),
              "por_rfc": cfg.get("por_rfc", {})}
    p.write_text(json.dumps(salida, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(p)


def config_para(cfg: Dict, rfc: str) -> Dict:
    """General + lo específico del RFC (lo del RFC gana si no está vacío)."""
    final = dict(cfg.get("general", {}))
    for k, v in (cfg.get("por_rfc", {}).get((rfc or "").upper(), {}) or {}).items():
        if v not in ("", None):
            final[k] = v
    return final


def dueno_de(detalle: Dict, tipo: str):
    """(rfc, nombre) del contribuyente desde cuya perspectiva se lee el CFDI."""
    if tipo == "Emitido":
        return detalle.get("emisor_rfc", ""), detalle.get("emisor_nombre", "")
    return detalle.get("receptor_rfc", ""), detalle.get("receptor_nombre", "")


def _money(v) -> str:
    try:
        return f"$ {float(v):,.2f}"
    except (TypeError, ValueError):
        return "$ 0.00"


def _hex_valido(c: str, defecto: str = "#1F4E78") -> str:
    return c if isinstance(c, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", c) else defecto


# ---------------------------------------------------------------- importe con letra
_UNIDADES = ["CERO", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE",
             "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISÉIS", "DIECISIETE",
             "DIECIOCHO", "DIECINUEVE", "VEINTE", "VEINTIUNO", "VEINTIDÓS", "VEINTITRÉS",
             "VEINTICUATRO", "VEINTICINCO", "VEINTISÉIS", "VEINTISIETE", "VEINTIOCHO",
             "VEINTINUEVE"]
_DECENAS = {3: "TREINTA", 4: "CUARENTA", 5: "CINCUENTA", 6: "SESENTA", 7: "SETENTA",
            8: "OCHENTA", 9: "NOVENTA"}
_CENTENAS = {1: "CIENTO", 2: "DOSCIENTOS", 3: "TRESCIENTOS", 4: "CUATROCIENTOS",
             5: "QUINIENTOS", 6: "SEISCIENTOS", 7: "SETECIENTOS", 8: "OCHOCIENTOS",
             9: "NOVECIENTOS"}
_MONEDAS = {"MXN": ("PESO", "PESOS", "M.N."), "USD": ("DÓLAR", "DÓLARES", "USD"),
            "EUR": ("EURO", "EUROS", "EUR")}


def _menor_mil(n: int) -> str:
    if n == 100:
        return "CIEN"
    c, r = divmod(n, 100)
    partes = [_CENTENAS[c]] if c else []
    if r:
        if r < 30:
            partes.append(_UNIDADES[r])
        else:
            d, u = divmod(r, 10)
            partes.append(_DECENAS[d] + (f" Y {_UNIDADES[u]}" if u else ""))
    return " ".join(partes)


def _apocope(txt: str) -> str:
    """UNO -> UN y VEINTIUNO -> VEINTIÚN cuando va antes de un sustantivo."""
    return re.sub(r"VEINTIUNO$", "VEINTIÚN", re.sub(r"(?<!\w)UNO$", "UN", txt))


def _entero_a_letras(n: int) -> str:
    if n == 0:
        return "CERO"
    partes = []
    millones, resto = divmod(n, 1_000_000)
    if millones:
        partes.append("UN MILLÓN" if millones == 1
                      else f"{_apocope(_entero_a_letras(millones))} MILLONES")
    miles, unidades = divmod(resto, 1000)
    if miles:
        partes.append("MIL" if miles == 1 else f"{_apocope(_menor_mil(miles))} MIL")
    if unidades:
        partes.append(_menor_mil(unidades))
    return " ".join(partes)


def importe_con_letra(total, moneda: str = "MXN") -> str:
    """'MIL CIENTO SESENTA PESOS 00/100 M.N.' (importe con letra del comprobante)."""
    try:
        centavos = int((abs(Decimal(str(total))) * 100).quantize(Decimal("1"), ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        centavos = 0
    entero, cen = divmod(centavos, 100)
    sing, plur, sufijo = _MONEDAS.get((moneda or "MXN").upper(),
                                      (moneda, moneda, (moneda or "").upper()))
    letras = _apocope(_entero_a_letras(entero))
    de = " DE" if entero and entero % 1_000_000 == 0 else ""
    return f"{letras}{de} {sing if entero == 1 else plur} {cen:02d}/100 {sufijo}".strip()


# ---------------------------------------------------------------- utilidades de formato
def _p(txt) -> str:
    """Texto seguro para Paragraph (el XML trae &, <, > en descripciones)."""
    return escape(str(txt if txt is not None else ""))


def _cortar(txt: str, n: int) -> str:
    txt = " ".join(str(txt or "").split())
    return txt if len(txt) <= n else txt[:max(n - 1, 1)].rstrip() + "…"


def _num(v) -> str:
    try:
        return f"{float(v):,.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(v or "")


def _tasa(factor: str, tasa: str) -> str:
    try:
        if factor == "Exento":
            return "Exento"
        if factor == "Cuota":
            return f"Cuota {float(tasa):,.6f}"
        return f"Tasa {float(tasa) * 100:.2f}%"
    except (TypeError, ValueError):
        return f"{factor} {tasa}".strip()


def _impuestos_linea(c: Dict) -> str:
    """Desglose por concepto: Impuesto · Base · Factor/Tasa · Importe."""
    partes = []
    for tipo, lista in (("Traslado", c.get("traslados", [])), ("Retención", c.get("retenciones", []))):
        for t in lista:
            imp = t.get("impuesto_desc") or t.get("impuesto", "")
            txt = f"{imp} {tipo}: Base {_money(t.get('base'))} · {_tasa(t.get('tipo_factor', ''), t.get('tasa', ''))}"
            if t.get("tipo_factor") != "Exento":
                txt += f" · Importe {_money(t.get('importe'))}"
            partes.append(txt)
    if c.get("descuento"):
        partes.append(f"Descuento {_money(c['descuento'])}")
    return "  |  ".join(partes)


# ---------------------------------------------------------------- PDF individual
# Rejilla (puntos, carta 612 x 792). El PDF es de UNA sola hoja por construcción:
#   - Márgenes fijos y un PIE de altura calculada (QR + sellos + cadena + leyenda)
#     dibujado en coordenadas absolutas pegado al borde inferior.
#   - El cuerpo (encabezado, partes, conceptos, totales) vive en un Frame que ocupa
#     lo que queda entre el margen superior y el pie.
#   - Si el cuerpo no cabe se reintenta, en este orden: (1) reducir fuentes hasta
#     ESCALA_MIN, (2) truncar descripciones, (3) mostrar menos conceptos ("y N más"),
#     (4) red de seguridad: KeepInFrame(shrink). Cada intento se mide renderizando.
_BASE_PIE = 10 * (72 / 25.4)           # el pie de página (config) va a esta altura
_ESCALAS = (1.0, 0.92, 0.85, 0.78, 0.72)
_ESCALA_MIN = _ESCALAS[-1]
LEYENDA_SAT = "Este documento es una representación impresa de un CFDI"


def cfdi_a_pdf(detalle: Dict, destino: str, config: Optional[Dict] = None,
               clase: str = "", tipo: str = "", inteligencia: Optional[Dict] = None) -> str:
    """Representación impresa del CFDI en UNA sola hoja carta. Recibe el dict ya
    procesado por lector.leer_detalle (no toca el XML)."""
    try:
        from reportlab.graphics.barcode import qrencoder
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas as lienzo
        from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepInFrame,
                                        PageTemplate, Paragraph, Spacer, Table, TableStyle)
    except ImportError as e:
        raise RuntimeError(
            "Falta la librería 'reportlab' para generar PDF. Instálala con:\n\n"
            "    pip install reportlab\n\n"
            "(o: pip install -r requirements.txt)"
        ) from e

    d = Path(destino)
    d.parent.mkdir(parents=True, exist_ok=True)

    if config is None:
        config = cargar_config_pdf()
    rfc_dueno, nombre_dueno = dueno_de(detalle, tipo)
    conf = config_para(config, rfc_dueno) if "general" in config else dict(config)
    conf = completar_diseno(conf)              # diseño de perfil o config vieja: lo mismo
    sec = conf["secciones"]

    PRIMARIO = colors.HexColor(_hex_valido(conf.get("color_primario", "")))
    GRIS = colors.HexColor("#5A6577")
    GRIS_CLARO = colors.HexColor("#EEF1F6")
    ancho_p, alto_p = letter
    ML, MS = 12 * mm, 10 * mm
    W = ancho_p - 2 * ML

    # ---------------------------------------------------------- PIE fijo (seguridad)
    est_sello = ParagraphStyle("sello", fontName="Helvetica", fontSize=5.6, leading=6.6,
                               textColor=colors.HexColor("#2B3340"), wordWrap="CJK")
    est_leyenda = ParagraphStyle("ley", fontName="Helvetica-Bold", fontSize=7.5, leading=9,
                                 textColor=PRIMARIO, alignment=1)
    qr_lado = 30 * mm
    gap = 3 * mm
    ancho_txt = W - qr_lado - gap
    cadena = detalle.get("cadena_original_timbre", "")
    ts = detalle.get("fecha_timbrado", "").replace("T", " ")
    tecnico = (f"<b>Certificación:</b> {ts or '—'} &nbsp;·&nbsp; "
               f"<b>CSD emisor:</b> {_p(detalle.get('no_certificado')) or '—'} &nbsp;·&nbsp; "
               f"<b>Certificado SAT:</b> {_p(detalle.get('no_certificado_sat')) or '—'} &nbsp;·&nbsp; "
               f"<b>PAC:</b> {_p(detalle.get('rfc_pac')) or '—'} &nbsp;·&nbsp; "
               f"<b>CFDI</b> {_p(detalle.get('version', '4.0'))}")
    pie_pars = [Paragraph(tecnico, est_sello)]
    for etiqueta, valor in (("Sello digital del CFDI", detalle.get("sello_emisor") or detalle.get("sello_cfd")),
                            ("Sello digital del SAT", detalle.get("sello_sat")),
                            ("Cadena original del complemento de certificación digital del SAT", cadena)):
        pie_pars.append(Paragraph(f"<b>{etiqueta}:</b> {_p(valor) or '—'}", est_sello))
    alturas = [p.wrap(ancho_txt, 10000)[1] for p in pie_pars]
    texto_h = sum(alturas) + 2.5 * (len(pie_pars) - 1)
    bloque_h = max(qr_lado, texto_h)
    leyenda = Paragraph(LEYENDA_SAT, est_leyenda)
    ley_h = leyenda.wrap(W, 100)[1]
    base_bloque = _BASE_PIE + ley_h + 4 * mm / 2          # el bloque queda sobre la leyenda
    tope_pie = base_bloque + bloque_h + 3                 # línea separadora del pie
    qr_url = detalle.get("qr_url") or ""

    def dibujar_pie(c, _doc):
        c.saveState()
        c.setStrokeColor(PRIMARIO)
        c.setLineWidth(0.8)
        c.line(ML, tope_pie, ancho_p - ML, tope_pie)
        if qr_url:
            # el QR se pinta directo como rectángulos (el widget de reportlab tarda ~10x más)
            cod = qrencoder.QRCode(None, qrencoder.QRErrorCorrectLevel.M)
            cod.addData(qr_url)
            cod.make()
            n_mod = cod.getModuleCount()
            lado = qr_lado / n_mod
            y_sup = base_bloque + bloque_h
            c.setFillColor(colors.black)
            ruta_qr = c.beginPath()
            for fila in range(n_mod):
                col = 0
                while col < n_mod:
                    if cod.isDark(fila, col):
                        ini = col
                        while col < n_mod and cod.isDark(fila, col):
                            col += 1
                        ruta_qr.rect(ML + ini * lado, y_sup - (fila + 1) * lado,
                                     (col - ini) * lado, lado)
                    else:
                        col += 1
            c.drawPath(ruta_qr, stroke=0, fill=1)
        y = base_bloque + bloque_h
        for p, h in zip(pie_pars, alturas):
            p.drawOn(c, ML + qr_lado + gap, y - h)
            y -= h + 2.5
        leyenda.drawOn(c, ML, _BASE_PIE + 1)
        c.setFont("Helvetica", 6.5)
        c.setFillColor(GRIS)
        pie_txt = conf.get("pie", "")
        if pie_txt:
            c.drawString(ML, _BASE_PIE - 5, str(pie_txt)[:140])
        c.drawRightString(ancho_p - ML, _BASE_PIE - 5, "Página 1 de 1")
        c.restoreState()

    frame_y0 = tope_pie + 2 * mm
    frame_h = alto_p - MS - frame_y0

    # ---------------------------------------------------------- CUERPO (reescalable)
    def construir(escala, max_desc, max_filas, max_aux):
        def fs(x):
            return round(x * escala, 2)

        est_empresa = ParagraphStyle("emp", fontName="Helvetica-Bold", fontSize=fs(13),
                                     textColor=PRIMARIO, leading=fs(15))
        est_titulo = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=fs(11),
                                    textColor=colors.HexColor("#1C2430"), leading=fs(13))
        est_sub = ParagraphStyle("s", fontName="Helvetica", fontSize=fs(7.5), textColor=GRIS,
                                 leading=fs(9))
        est_lbl = ParagraphStyle("l", fontName="Helvetica-Bold", fontSize=fs(6.5),
                                 textColor=GRIS, leading=fs(8))
        est_val = ParagraphStyle("v", fontName="Helvetica", fontSize=fs(8), leading=fs(9.5))
        est_val_b = ParagraphStyle("vb", fontName="Helvetica-Bold", fontSize=fs(8.5),
                                   leading=fs(10))
        est_con = ParagraphStyle("c", fontName="Helvetica", fontSize=fs(7.5), leading=fs(8.8),
                                 wordWrap="CJK")
        est_imp = ParagraphStyle("ci", fontName="Helvetica", fontSize=fs(6.3), leading=fs(7.4),
                                 textColor=GRIS, wordWrap="CJK")
        est_mini = ParagraphStyle("m", fontName="Helvetica", fontSize=fs(6.3), textColor=GRIS,
                                  wordWrap="CJK", leading=fs(7.6))
        est_letra = ParagraphStyle("letra", fontName="Helvetica-Bold", fontSize=fs(68),
                                   textColor=colors.white, alignment=1, leading=fs(70))
        est_letra_lbl = ParagraphStyle("letral", fontName="Helvetica-Bold", fontSize=fs(13),
                                       textColor=colors.white, alignment=1, leading=fs(15))
        pad = max(2, round(3 * escala, 1))
        el = []

        def celda(lbl, val):
            return [Paragraph(_p(lbl).upper(), est_lbl), Paragraph(_p(val) or "—", est_val)]

        def rejilla(filas, anchos=None, span_primera=False):
            n = len(filas[0])
            t = Table(filas, colWidths=anchos or [W / n] * n)
            est = [("VALIGN", (0, 0), (-1, -1), "TOP"),
                   ("LINEBELOW", (0, -1), (-1, -1), 0.4, GRIS_CLARO),
                   ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                   ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad)]
            if span_primera:
                est.append(("SPAN", (0, 0), (-1, 0)))
            t.setStyle(TableStyle(est))
            return t

        # ---- encabezado: logo | empresa | LETRA
        logo_cell = ""
        logo = conf.get("logo") or ""
        if logo and Path(logo).exists():
            try:
                from reportlab.lib.utils import ImageReader
                iw, ih = ImageReader(logo).getSize()
                alto = 16 * mm * escala
                ancho = min(38 * mm, alto * iw / max(ih, 1))
                logo_cell = Image(logo, width=ancho, height=ancho * ih / max(iw, 1))
            except Exception:  # noqa: BLE001 — un logo roto no debe impedir el PDF
                logo_cell = ""

        titulo_emp = conf.get("titulo") or nombre_dueno or detalle.get("receptor_nombre", "")
        bloque_emp = [Paragraph(_p(titulo_emp) or "&nbsp;", est_empresa)]
        if rfc_dueno:
            bloque_emp.append(Paragraph(f"RFC {_p(rfc_dueno)}", est_sub))
        if conf.get("subtitulo") and "representación impresa" not in conf["subtitulo"].lower():
            bloque_emp.append(Paragraph(_p(conf["subtitulo"]), est_sub))

        letra_cell = ""
        if sec["letra_clase"] and clase in CLASES:
            nombre_clase, color_clase = CLASES[clase]
            letra_cell = Table([[Paragraph(clase, est_letra)],
                                [Paragraph(nombre_clase.upper(), est_letra_lbl)]],
                               colWidths=[44 * mm], rowHeights=[24 * mm * escala, 7 * mm * escala])
            letra_cell.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(color_clase)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]))
        # la zona del logo se reserva SIEMPRE (esquina superior izquierda)
        enc = Table([[logo_cell, bloque_emp, letra_cell]],
                    colWidths=[40 * mm, W - 40 * mm - 44 * mm, 44 * mm])
        enc.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("LINEBELOW", (0, 0), (-1, 0), 1.2, PRIMARIO), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        el += [enc, Spacer(1, 5 * escala)]

        # ---- título + datos de emisión y certificación
        folio = " ".join(x for x in [detalle.get("serie", ""), detalle.get("folio", "")] if x)
        el.append(Paragraph(f"Comprobante de {_p(detalle.get('tipo_comprobante_desc', ''))} "
                            f"&nbsp;<font size='{fs(9)}' color='#5A6577'>{_p(folio or '')}</font>",
                            est_titulo))
        el.append(Spacer(1, 3 * escala))
        exp = detalle.get("exportacion", "")
        exp_txt = f"{exp} – {detalle.get('exportacion_desc')}" if detalle.get("exportacion_desc") else exp
        el.append(rejilla([[celda("Fecha y hora de emisión", detalle.get("fecha", "")),
                            celda("C.P. de expedición", detalle.get("lugar", "")),
                            celda("Exportación", exp_txt),
                            celda("Folio fiscal (UUID)", detalle.get("uuid", ""))]],
                          anchos=[0.19 * W, 0.17 * W, 0.17 * W, 0.47 * W]))
        el.append(Spacer(1, 4 * escala))

        # ---- emisor / receptor
        def bloque(titulo, rfc, nombre, regimen, desc_reg, cp_lbl, cp, extra=()):
            reg = f"{regimen} – {desc_reg}" if desc_reg else regimen
            filas = [Paragraph(titulo, est_lbl), Paragraph(_p(nombre) or "—", est_val_b),
                     Paragraph(f"<b>RFC:</b> {_p(rfc) or '—'} &nbsp; <b>{cp_lbl}:</b> {_p(cp) or '—'}", est_val),
                     Paragraph(f"<b>Régimen fiscal:</b> {_p(reg) or '—'}", est_val)]
            for lbl, val in extra:
                if val:
                    filas.append(Paragraph(f"<b>{lbl}:</b> {_p(val)}", est_val))
            return filas

        uso = detalle.get("uso_cfdi", "")
        uso_txt = f"{uso} – {detalle['uso_cfdi_desc']}" if detalle.get("uso_cfdi_desc") else uso
        ce = bloque("EMISOR", detalle.get("emisor_rfc"), detalle.get("emisor_nombre"),
                    detalle.get("emisor_regimen", ""), detalle.get("emisor_regimen_desc", ""),
                    "C.P. de expedición", detalle.get("lugar", ""))
        cr = bloque("RECEPTOR", detalle.get("receptor_rfc"), detalle.get("receptor_nombre"),
                    detalle.get("receptor_regimen", ""), detalle.get("receptor_regimen_desc", ""),
                    "C.P. domicilio fiscal", detalle.get("receptor_domicilio", ""),
                    extra=[("Uso del CFDI", uso_txt),
                           ("Residencia fiscal", detalle.get("receptor_residencia")),
                           ("Núm. reg. id. trib.", detalle.get("receptor_num_reg_id_trib"))])
        if len(cr) == 4:                              # sin extras: Uso del CFDI siempre se muestra
            cr.append(Paragraph(f"<b>Uso del CFDI:</b> {_p(uso_txt) or '—'}", est_val))
        el.append(rejilla([[ce, cr]], anchos=[W / 2, W / 2]))
        el.append(Spacer(1, 4 * escala))

        # ---- comercial: moneda / forma / método / condiciones
        moneda = detalle.get("moneda", "") or "MXN"
        tc = detalle.get("tipo_cambio", "")
        mon_txt = moneda if moneda in ("MXN", "") else f"{moneda}  (T.C. {tc})"
        fp, mp = detalle.get("forma_pago", ""), detalle.get("metodo_pago", "")
        fp_txt = f"{fp} – {detalle['forma_pago_desc']}" if detalle.get("forma_pago_desc") else fp
        mp_txt = f"{mp} – {detalle['metodo_pago_desc']}" if detalle.get("metodo_pago_desc") else mp
        extra4 = detalle.get("condiciones_pago", "")
        lbl4 = "Condiciones de pago"
        ig = detalle.get("informacion_global") or {}
        if ig and not extra4:
            lbl4, extra4 = "Información global", f"{ig.get('periodicidad', '')} · mes {ig.get('meses', '')} · {ig.get('anio', '')}"
        el.append(rejilla([[celda("Moneda", mon_txt), celda("Forma de pago", fp_txt),
                            celda("Método de pago", mp_txt), celda(lbl4, extra4)]]))
        el.append(Spacer(1, 4 * escala))

        # ---- conceptos (clave prod/serv, cantidad, clave unidad, descripción, V.U., importe)
        filas = [["Clave\nProd/Serv", "Cant.", "Clave\nunidad", "Descripción / impuestos del concepto",
                  "Valor unitario", "Importe"]]
        conceptos = detalle.get("conceptos", [])
        mostrados = conceptos if max_filas is None else conceptos[:max_filas]
        for c in mostrados:
            celda_desc = [Paragraph(_p(_cortar(c.get("descripcion", ""), max_desc)), est_con)]
            linea = _impuestos_linea(c)
            if linea:
                celda_desc.append(Paragraph(_p(linea), est_imp))
            filas.append([c.get("clave_prod", ""), _num(c.get("cantidad")),
                          c.get("clave_unidad", "") or c.get("unidad", ""), celda_desc,
                          _money(c.get("valor_unitario")), _money(c.get("importe"))])
        if len(mostrados) < len(conceptos):
            resto = len(conceptos) - len(mostrados)
            filas.append(["", "", "", Paragraph(
                f"<i>… y {resto} concepto(s) más. Se muestran {len(mostrados)} de "
                f"{len(conceptos)}; el detalle completo está en el XML.</i>", est_imp), "", ""])
        anchos = [0.095 * W, 0.075 * W, 0.075 * W, 0.465 * W, 0.145 * W, 0.145 * W]
        t_con = Table(filas, colWidths=anchos, repeatRows=1)
        t_con.setStyle(TableStyle([
            ("TEXTCOLOR", (0, 0), (-1, 0), GRIS), ("LINEBELOW", (0, 0), (-1, 0), 1, PRIMARIO),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, 0), fs(6.8)),
            ("LEADING", (0, 0), (-1, 0), fs(8)),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 1), (-1, -1), fs(7.5)),
            ("ALIGN", (1, 0), (2, -1), "CENTER"), ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, GRIS_CLARO),
            ("TOPPADDING", (0, 0), (-1, -1), pad - 1), ("BOTTOMPADDING", (0, 0), (-1, -1), pad - 1),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        el += [t_con, Spacer(1, 4 * escala)]

        # ---- importe con letra (izq) | totales (der)
        iva_t, ieps_t = detalle.get("iva_trasladado"), detalle.get("ieps_trasladado")
        iva_r, isr_r = detalle.get("iva_retenido"), detalle.get("isr_retenido")
        tot = [["Subtotal", _money(detalle.get("subtotal"))]]
        if detalle.get("descuento"):
            tot.append(["Descuento", "- " + _money(detalle["descuento"])])
        traslados = [(n, v) for n, v in (("IVA trasladado", iva_t), ("IEPS trasladado", ieps_t)) if v]
        retenciones = [(n, v) for n, v in (("IVA retenido", iva_r), ("ISR retenido", isr_r)) if v]
        tot += [[n, _money(v)] for n, v in traslados]
        if len(traslados) > 1:
            tot.append(["Total impuestos trasladados", _money(sum(v for _, v in traslados))])
        tot += [[n, "- " + _money(v)] for n, v in retenciones]
        if len(retenciones) > 1:
            tot.append(["Total impuestos retenidos", "- " + _money(sum(v for _, v in retenciones))])
        tot.append(["TOTAL", _money(detalle.get("total"))])
        t_tot = Table(tot, colWidths=[0.22 * W, 0.15 * W])
        t_tot.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), fs(8)), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("TEXTCOLOR", (0, 0), (0, -2), GRIS),
            ("LINEABOVE", (0, -1), (-1, -1), 1, PRIMARIO),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, -1), (-1, -1), fs(13)),
            ("TEXTCOLOR", (0, -1), (-1, -1), PRIMARIO),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ]))
        letras = [Paragraph("IMPORTE CON LETRA", est_lbl),
                  Paragraph(_p(importe_con_letra(detalle.get("total"), moneda)), est_val_b)]
        rels = detalle.get("relacionados", [])
        if rels:
            letras.append(Spacer(1, 3 * escala))
            letras.append(Paragraph("CFDI RELACIONADOS", est_lbl))
            for r in rels[:max_aux]:
                letras.append(Paragraph(f"{_p(r['uuid'])} – {_p(r.get('tipo_desc', ''))}", est_mini))
            if len(rels) > max_aux:
                letras.append(Paragraph(f"… y {len(rels) - max_aux} más", est_mini))
        bajo = Table([[letras, t_tot]], colWidths=[0.60 * W, 0.40 * W])
        bajo.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                  ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
        el += [bajo, Spacer(1, 5 * escala)]

        # ---- complemento de pago
        if detalle.get("es_pago") or detalle.get("pago_monto"):
            el.append(Paragraph("COMPLEMENTO DE PAGO", est_lbl))
            el.append(Paragraph(f"Monto pagado: {_money(detalle.get('pago_monto'))} &nbsp;·&nbsp; "
                                f"Fecha: {_p(detalle.get('pago_fecha', ''))} &nbsp;·&nbsp; "
                                f"Forma: {_p(detalle.get('pago_forma', ''))}", est_val_b))
            extra = []
            if detalle.get("pago_iva"):
                extra.append(f"IVA del pago: {_money(detalle.get('pago_iva'))}")
            if detalle.get("pago_num_operacion"):
                extra.append(f"Núm. operación: {_p(detalle.get('pago_num_operacion'))}")
            if extra:
                el.append(Paragraph(" &nbsp;·&nbsp; ".join(extra), est_sub))
            docs = detalle.get("pago_docs", [])
            if docs:
                fd = [["UUID (factura pagada)", "Serie·Folio", "Parc.", "Base", "Tasa",
                       "IVA", "Pagado", "Saldo ins."]]
                for dd in docs[:max_aux]:
                    sf = "·".join(x for x in [dd.get("serie", ""), dd.get("folio", "")] if x)
                    tasa = f"{float(dd['tasa']) * 100:.0f}%" if dd.get("tasa") else ""
                    fd.append([Paragraph(_p(dd["uuid"]), est_mini), sf, dd.get("parcialidad", ""),
                               _money(dd.get("base", 0)), tasa, _money(dd.get("iva", 0)),
                               _money(dd["pagado"]), _money(dd["saldo_insoluto"])])
                if len(docs) > max_aux:
                    fd.append([Paragraph(f"… y {len(docs) - max_aux} documento(s) más (ver XML)", est_mini),
                               "", "", "", "", "", "", ""])
                t_d = Table(fd, colWidths=[0.30 * W, 0.10 * W, 0.05 * W, 0.12 * W, 0.06 * W,
                                           0.11 * W, 0.13 * W, 0.13 * W], repeatRows=1)
                t_d.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), GRIS), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), fs(6.5)),
                    ("ALIGN", (3, 0), (-1, -1), "RIGHT"), ("ALIGN", (2, 0), (2, -1), "CENTER"),
                    ("ALIGN", (4, 0), (4, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS_CLARO]),
                    ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ]))
                el += [Spacer(1, 2), t_d]
            el.append(Spacer(1, 5 * escala))

        # ---- inteligencia (estatus de pago calculado con lo leído)
        if inteligencia and sec["inteligencia"] and inteligencia.get("estatus"):
            el.append(Paragraph("SEGUIMIENTO DE PAGO (calculado con los XML leídos)", est_lbl))
            filas_i = [["Estatus", inteligencia.get("estatus", ""),
                        "Pagado con REP", _money(inteligencia.get("pagado_rep", 0))],
                       ["Notas de crédito aplicadas", _money(inteligencia.get("nc_aplicadas", 0)),
                        "Saldo pendiente", _money(inteligencia.get("saldo_pendiente", 0))]]
            t_i = Table(filas_i, colWidths=[0.26 * W, 0.20 * W, 0.20 * W, 0.20 * W], hAlign="LEFT")
            t_i.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), fs(7.5)),
                ("TEXTCOLOR", (0, 0), (0, -1), GRIS), ("TEXTCOLOR", (2, 0), (2, -1), GRIS),
                ("FONTNAME", (1, 0), (1, 0), "Helvetica-Bold"), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("ALIGN", (3, 0), (3, -1), "RIGHT"), ("LINEBELOW", (0, -1), (-1, -1), 0.5, GRIS_CLARO),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ]))
            el.append(t_i)
            pagos = inteligencia.get("pagos", [])
            if pagos:
                fpg = [["REP (UUID)", "Fecha pago", "Parc.", "Pagado", "Saldo insoluto"]]
                for e in pagos[:max_aux]:
                    fpg.append([Paragraph(_p(e.get("rep_uuid", "")), est_mini), e.get("fecha_pago", "")[:10],
                                e.get("parcialidad", ""), _money(e.get("imp_pagado")),
                                _money(e.get("saldo_insoluto"))])
                t_p = Table(fpg, colWidths=[0.40 * W, 0.15 * W, 0.08 * W, 0.18 * W, 0.18 * W], hAlign="LEFT")
                t_p.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), GRIS_CLARO), ("FONTSIZE", (0, 0), (-1, -1), fs(6.5)),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]))
                el += [Spacer(1, 2), t_p]
        return el

    # ---------------------------------------------------------- render + ajuste
    def renderizar(salida, params, forzar=False):
        paginas = [0]

        def al_pagina(c, documento):
            paginas[0] += 1
            dibujar_pie(c, documento)

        doc = BaseDocTemplate(salida, pagesize=letter, leftMargin=ML, rightMargin=ML,
                              topMargin=MS, bottomMargin=frame_y0,
                              title=f"CFDI {detalle.get('uuid', '')}",
                              author=conf.get("titulo") or nombre_dueno or "")
        frame = Frame(ML, frame_y0, W, frame_h, leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0, id="cuerpo")
        doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=al_pagina)])
        cuerpo = construir(*params)
        if forzar:
            cuerpo = [KeepInFrame(W, frame_h, cuerpo, mode="shrink")]
        doc.build(cuerpo)
        return paginas[0]

    def cabe(params):
        """Mide el cuerpo sin generar el PDF (sumando el alto de cada bloque)."""
        alto = 0.0
        for f in construir(*params):
            alto += f.wrap(W, 100000)[1] + f.getSpaceBefore() + f.getSpaceAfter()
        return alto <= frame_h - 2

    n = len(detalle.get("conceptos", []))
    etapas = [(e, 100000, None, 12) for e in _ESCALAS]
    etapas += [(_ESCALA_MIN, 160, None, 8), (_ESCALA_MIN, 90, None, 4)]
    elegido, forzar = next((p for p in etapas if cabe(p)), None), False
    if elegido is None:                    # mostrar menos conceptos: el mayor N que cabe
        lo, hi, mejor = 1, max(n - 1, 1), None
        while lo <= hi:
            mid = (lo + hi) // 2
            if cabe((_ESCALA_MIN, 90, mid, 3)):
                mejor, lo = mid, mid + 1
            else:
                hi = mid - 1
        elegido = (_ESCALA_MIN, 90, mejor or 1, 3)
        forzar = mejor is None             # ni con 1 concepto cabe: red de seguridad
    if renderizar(str(d), elegido, forzar) > 1:     # la medición falló por poco: encoger
        renderizar(str(d), elegido, True)
    return str(d)


# ---------------------------------------------------------------- generación masiva
_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def nombre_pdf(plantilla: str, datos: Dict) -> str:
    """Nombre de archivo seguro para Windows a partir de la plantilla."""
    fecha = (datos.get("Fecha") or "")[:10].replace("-", "")
    tipo = datos.get("Tipo", "")
    contraparte = datos.get("RFC Receptor") if tipo == "Emitido" else datos.get("RFC Emisor")
    uuid = (datos.get("UUID") or "SINUUID").upper()
    valores = {"fecha": fecha or "SINFECHA", "clase": datos.get("Clase") or "X", "tipo": tipo,
               "rfc_contraparte": contraparte or "", "serie": datos.get("Serie", ""),
               "folio": datos.get("Folio", ""), "uuid8": uuid[:8], "uuid": uuid}
    try:
        nombre = plantilla.format(**valores)
    except (KeyError, IndexError, ValueError):
        nombre = CONFIG_DEFAULT["general"]["nombre_archivo"].format(**valores)
    nombre = _INVALIDOS.sub("", nombre).strip(" ._") or uuid
    nombre = re.sub(r"_{2,}", "_", nombre)
    return nombre[:150] + ".pdf"


def plantilla_de(conf: Dict) -> str:
    """Plantilla de nombre de archivo de un diseño (plano o config vieja con 'general')."""
    return (conf.get("nombre_archivo") or (conf.get("general") or {}).get("nombre_archivo")
            or CONFIG_DEFAULT["general"]["nombre_archivo"])


def subcarpeta_pdf(modo: str, datos: Dict) -> str:
    """'' | 'mes' -> 202609 | 'mes/clase' -> 202609/G (para ordenar los PDF)."""
    if not modo:
        return ""
    fecha = (datos.get("Fecha") or "")[:7].replace("-", "") or "SINFECHA"
    if modo == "mes":
        return fecha
    return f"{fecha}/{datos.get('Clase') or 'X'}"


def generar_pdfs(filas: List, carpeta: str, config: Optional[Dict] = None,
                 inteligencia_de: Optional[Callable] = None,
                 progreso: Optional[Callable] = None,
                 cancelado: Callable[[], bool] = lambda: False,
                 sobrescribir: bool = False,
                 diseno_de: Optional[Callable[[Dict], Dict]] = None) -> Dict:
    """Genera un PDF por CFDI (no por fila: un REP con 3 facturas = 1 PDF).
    filas: renglones de la tabla (Renglon o dict). Devuelve un resumen.
    diseno_de(fila) -> diseño a usar (perfil); si no se da, se usa config.
    El diseño decide la plantilla del nombre y las subcarpetas (mes / mes y clase)."""
    from .lector import leer_detalle

    if config is None and diseno_de is None:
        config = cargar_config_pdf()
    destino = Path(carpeta)
    destino.mkdir(parents=True, exist_ok=True)

    unicos, vistos = [], set()
    for f in filas:
        d = f.datos if hasattr(f, "datos") else f
        k = ((d.get("UUID") or d.get("Archivo") or "").upper(), d.get("Tipo", ""))
        if k in vistos:
            continue
        vistos.add(k)
        unicos.append(d)

    res = {"generados": 0, "omitidos": 0, "errores": [], "carpeta": str(destino),
           "total": len(unicos), "cancelado": False}
    for i, d in enumerate(unicos, 1):
        if cancelado():
            res["cancelado"] = True
            break
        conf = diseno_de(d) if diseno_de else config
        plano = conf if "general" not in conf else conf["general"]
        sub = subcarpeta_pdf(plano.get("subcarpetas", ""), d)
        salida = (destino / sub if sub else destino) / nombre_pdf(plantilla_de(conf), d)
        try:
            if salida.exists() and not sobrescribir:
                res["omitidos"] += 1
            else:
                det = leer_detalle(d.get("Archivo", ""))
                if not det:
                    raise ValueError("no es un CFDI legible")
                intel = inteligencia_de(d) if inteligencia_de else None
                cfdi_a_pdf(det, str(salida), config=conf, clase=d.get("Clase", ""),
                           tipo=d.get("Tipo", ""), inteligencia=intel)
                res["generados"] += 1
        except Exception as e:  # noqa: BLE001 — un XML malo no detiene el lote
            res["errores"].append((d.get("Archivo", ""), str(e)))
        if progreso:
            progreso(i, len(unicos))
    return res


# ---------------------------------------------------------------- paquete para enviar
PLANTILLA_ENVIO = "{serie}-{folio} {uuid}"


def nombre_envio(datos: Dict, plantilla: str = PLANTILLA_ENVIO) -> str:
    """Nombre base (sin extensión) compartido por el XML y el PDF: 'C-1 UUID'.
    Sin serie o sin folio no deja guiones sueltos."""
    base = nombre_pdf(plantilla, datos)[:-4]
    return re.sub(r"\s{2,}", " ", base).strip(" -._") or (datos.get("UUID") or "SINUUID").upper()


def carpeta_cliente(datos: Dict) -> str:
    """'RFC Nombre' de la contraparte (el cliente si el CFDI es emitido)."""
    emitido = datos.get("Tipo") != "Recibido"
    rfc = datos.get("RFC Receptor" if emitido else "RFC Emisor") or "SIN RFC"
    nombre = datos.get("Nombre Receptor" if emitido else "Nombre Emisor") or ""
    return _INVALIDOS.sub("", f"{rfc} {nombre}").strip(" .")[:80]


def paquete_envio(filas: List, carpeta: str, inteligencia_de: Optional[Callable] = None,
                  progreso: Optional[Callable] = None,
                  cancelado: Callable[[], bool] = lambda: False,
                  diseno_de: Optional[Callable[[Dict], Dict]] = None,
                  config: Optional[Dict] = None, plantilla: str = PLANTILLA_ENVIO) -> Dict:
    """Deja listo lo que se le manda a cada cliente: una carpeta por cliente con el
    XML (copia) y su PDF, ambos con el mismo nombre. No toca los XML originales."""
    import shutil
    from .lector import leer_detalle

    if config is None and diseno_de is None:
        config = cargar_config_pdf()
    destino = Path(carpeta)
    destino.mkdir(parents=True, exist_ok=True)
    unicos, vistos = [], set()
    for f in filas:
        d = f.datos if hasattr(f, "datos") else f
        k = (d.get("UUID") or d.get("Archivo") or "").upper()
        if k not in vistos:
            vistos.add(k)
            unicos.append(d)

    res = {"generados": 0, "omitidos": 0, "errores": [], "carpeta": str(destino),
           "total": len(unicos), "cancelado": False, "clientes": {}}
    for i, d in enumerate(unicos, 1):
        if cancelado():
            res["cancelado"] = True
            break
        cliente = carpeta_cliente(d)
        base = destino / cliente / nombre_envio(d, plantilla)
        xml, pdf = Path(f"{base}.xml"), Path(f"{base}.pdf")
        try:
            origen = Path(d.get("Archivo", ""))
            det = leer_detalle(origen)
            if not det:
                raise ValueError("no es un CFDI legible")
            xml.parent.mkdir(parents=True, exist_ok=True)
            if xml.exists() and pdf.exists():
                res["omitidos"] += 1
            else:
                shutil.copyfile(origen, xml)
                cfdi_a_pdf(det, str(pdf), config=diseno_de(d) if diseno_de else config,
                           clase=d.get("Clase", ""), tipo=d.get("Tipo", ""),
                           inteligencia=inteligencia_de(d) if inteligencia_de else None)
                res["generados"] += 1
            res["clientes"][cliente] = res["clientes"].get(cliente, 0) + 1
        except Exception as e:  # noqa: BLE001 — un XML malo no detiene el lote
            res["errores"].append((d.get("Archivo", ""), str(e)))
        if progreso:
            progreso(i, len(unicos))
    return res
