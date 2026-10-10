# DESCARGA XML EDDP

Descarga masiva de XML CFDI del SAT (servicio oficial, con e.firma) para varios RFC,
y extracción de **todos** sus datos a tabla, Excel, SQL y PDF, con inteligencia que
relaciona facturas, complementos de pago y notas de crédito.

---

## Abrir con un clic

**Opción A — sin compilar (inmediato):**
1. Una sola vez: `pip install -r requirements.txt`
2. Doble clic a **`crear_acceso_directo.bat`** → aparece **DESCARGA XML EDDP** en tu Escritorio.
3. Desde ahí, doble clic y abre (sin ventana negra).
   También puedes dar doble clic directo a `DESCARGA XML EDDP.pyw`.

**Opción B — programa .exe (no necesita Python para usarse):**
1. Doble clic a **`construir_exe.bat`** (tarda 1–3 minutos, solo la primera vez).
2. Queda `dist\DESCARGA XML EDDP.exe` y un acceso directo en tu Escritorio.
3. Ese `.exe` lo puedes copiar a cualquier carpeta o a otra compu.

`Abrir app.bat` sigue funcionando; úsalo si quieres ver errores en consola.

## Tus datos están a salvo

Todo lo que la app recuerda vive en una carpeta fija:

```
%APPDATA%\DESCARGA XML EDDP
```

Ahí quedan tus RFC, rutas de e.firma, contraseñas, historial de solicitudes al SAT,
la última carpeta, fechas, tema, zoom, la configuración del PDF, logos y la memoria
de pagos. No se pierde aunque muevas la app, la actualices o la compiles.

**Si vienes de la versión anterior:** la primera vez que la abras desde tu carpeta de
siempre, copia sola tu `config.json` (con todos tus RFC y contraseñas) a esa carpeta.
Nunca sobreescribe nada.

### Respaldar y restaurar (cambiar de computadora)

Arriba a la derecha:

- **⇧ Respaldar** → un `.zip` con todo: RFC, contraseñas, copias de los `.cer/.key`,
  configuración del PDF, logos, memoria e historial.
- **⇩ Restaurar** → en la otra compu, eliges el `.zip` y listo. Las e.firmas se
  reubican solas; no hay que volver a buscarlas. Si ya tenías RFC, se fusionan.

> ⚠ El respaldo contiene tus llaves privadas y contraseñas. Guárdalo como documento
> confidencial; no lo mandes por correo.

---

## Pestaña Descargar

Sin cambios: agregas tus RFC (el RFC lo lee del certificado), eliges periodo, tipo y
carpeta, y **▶ Descargar XML**. Reintenta solo, retoma si se corta y no repite
solicitudes al SAT.

Carpetas de salida: `{AAAAMM} {4 letras del RFC}/emitidos|recibidos/{UUID}.xml`

## Pestaña Datos y Excel

Trabaja con los XML que ya tienes en disco. **Cero requerimientos al SAT.**

**Arriba, siempre visibles:** Exportar a Excel · **Generar PDFs** · Copiar tabla ·
Copiar selección · Exportar CSV · Elegir columnas.

**Copiar tabla** sale en el **formato EDDP de 65 columnas** (Tipo … RFC PAC), siempre en
el mismo orden. **Exportar a Excel** lleva las 73 (incluye Clase, inteligencia y
Archivo). En *Elegir columnas…* puedes personalizar el copiado; se guarda al presionar
Guardar o al cerrar la ventana, y se recuerda al reabrir. "Formato EDDP (65)" lo regresa
al estándar.

**Tarjetas:** comprobantes (y duplicados ignorados), ingresos, gastos, IVA en
ingresos, IVA en gastos, saldo PPD pendiente y pagos REP.

**Letra por clase** — qué es cada comprobante *para quien lo lee*:

| Letra | Significa | Color |
|---|---|---|
| **I** | Ingreso (tú lo emitiste) | verde |
| **G** | Gasto (te lo emitieron) | rojo |
| **N** | Nómina | morado |
| **P** | Pago (complemento REP) | azul |
| **E** | Nota de crédito / egreso | naranja |
| **T** | Traslado | gris |

Las filas de la tabla salen del color de su clase. Clic en una letra de la franja
filtra por esa clase (otro clic quita el filtro).

**Tres vistas:** Tabla (73 columnas, sin sellos ni cadenas), Panel (gráficas) y
Consulta SQL (17 plantillas y un constructor guiado).

### Inteligencia

Al leer una carpeta, la app:

- **Ignora duplicados:** el mismo CFDI leído dos veces cuenta una sola vez.
- **Sabe si es emitido o recibido** aunque los XML no estén en carpetas
  emitidos/recibidos, comparando con tus RFC.
- **Relaciona factura ↔ complemento de pago ↔ nota de crédito.** Para cada factura
  PPD calcula lo pagado con REP, las notas aplicadas, el saldo pendiente y su estatus
  (Pagada / Parcial / Sin pago). Para cada REP te dice si leíste su factura.
- **Recuerda entre lecturas:** si hoy lees un REP y la semana que entra su factura en
  otra carpeta, la factura encuentra su pago igual.

Ejemplo real verificado: factura PPD de $320,000 − nota de crédito por anticipo
$150,610.96 − pago REP $124,389.04 = **saldo $45,000**, igual al saldo insoluto
que reporta el SAT.

Todo son hechos del XML. La deducibilidad según régimen es criterio profesional y no
la decide la app.

### Visor

Doble clic en una fila: la factura presentada con su **letra grande**, el
**seguimiento de pago**, el complemento de pago por documento (base, tasa, IVA,
pagado, saldo), los CFDI relacionados y, hasta abajo, **todos los datos del XML**
(menos sellos). Desde ahí: Descargar PDF o Abrir XML.

### PDF

- **Uno:** desde el visor.
- **En masa:** botón **Generar PDFs**. Si seleccionas filas, solo esas; si no, todo lo
  filtrado. Un PDF por CFDI (un REP que paga 3 facturas = 1 PDF). Los que ya existen
  no se regeneran. Nombres ordenables:
  `20260810_G_IMO011025RIA_AIJ4237_37274D22.pdf`

**Personalizar** (botón ▤ PDF arriba, o el archivo `pdf_config.json`):
título, subtítulo, pie de página, color, **logo**, nombre de archivo, letra de clase,
seguimiento de pago y sello SAT. En "Por cliente (RFC)" cada cliente lleva su propio
nombre y logo.

El PDF es una representación informativa; el documento con validez es el XML.

## Zoom

Botones **A− / A+** arriba, o **Ctrl + / Ctrl − / Ctrl 0**. Se recuerda.

---

## Terminal (opcional)

```
python descargar.py --desde 2026-01-01 --hasta 2026-09-30 --tipo ambos
python descargar.py --probar-fiel
```

## Pruebas

```
python -m pytest -q
```

292 pruebas: descarga y reintentos con el SAT simulado, firma XMLDSig verificada,
lectura de CFDI 4.0/3.3 con pagos y relacionados, inteligencia con XML reales
(factura + nota de crédito + REP), duplicados, memoria entre sesiones, PDF (texto
impreso verificado), generación masiva, respaldo entre dos computadoras (incluido un
zip manipulado que intenta escribir fuera), migración de datos, zoom, compilación y
la interfaz real (botones visibles a 1000×600, filtros, visor, configuración).

## Estructura

```
DESCARGA XML EDDP.pyw         abrir con doble clic (sin consola)
construir_exe.bat             compila el .exe + acceso directo
crear_acceso_directo.bat      acceso directo al .pyw
app.py                        interfaz
sat_descarga/config.py        RFC, opciones, carpeta de datos, migración
sat_descarga/cliente.py       conexión con el SAT
sat_descarga/flujo.py         solicitar → verificar → descargar
sat_descarga/lector.py        CFDI → filas (73 columnas, pagos por documento)
sat_descarga/inteligencia.py  duplicados, perspectiva, relaciones, memoria
sat_descarga/pdf.py           PDF personalizable y generación masiva
sat_descarga/respaldo.py      respaldar / restaurar
sat_descarga/consulta.py      SQL y plantillas
sat_descarga/exportar.py      Excel, CSV, portapapeles, índice
sat_descarga/tema.py          diseño, temas y zoom
recursos/                     ícono y logo de ejemplo
tests/                        292 pruebas (+ XML reales en tests/xml_reales)
```
