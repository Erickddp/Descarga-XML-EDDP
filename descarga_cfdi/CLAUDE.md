# CLAUDE.md — DESCARGA XML EDDP

App de escritorio Windows (Python 3 + tkinter) para contadores:
- Pestaña **Descargar**: descarga masiva de CFDI del SAT con e.firma.
- Pestaña **Datos y Excel**: lee XML de disco → tabla / Excel / CSV / SQL / PDF, con
  inteligencia factura ↔ complemento de pago (REP) ↔ nota de crédito.

## Reglas (no negociables)
1. **No cambiar comportamiento ni diseño de "Descargar"**: `sat_descarga/cliente.py`,
   `flujo.py`, `ejecutor.py`, `almacen.py` y `App._construir_descarga` en `app.py`.
2. **"Copiar tabla"** sale con `COLUMNAS_COPIADO` (65 columnas, mismo orden) salvo que el
   perfil de reporte activo defina otras. El Excel conserva **todas** las columnas (`COLUMNAS`).
3. **Todo dato persistente vive en `carpeta_datos()`** (`%APPDATA%\DESCARGA XML EDDP`;
   en pruebas la fija `DESCARGA_XML_EDDP_DATOS`). Nunca escribir en la carpeta del programa.
4. **Cero criterio fiscal** (deducibilidad, etc.): solo hechos del XML.
5. **Nada de Tk desde hilos secundarios.** Los hilos sólo hacen `self.cola.put(...)`;
   `App._vaciar_cola` (hilo principal, cada 120 ms) pinta. Llamar `gc.collect()` en el
   hilo principal antes de lanzar un hilo (ver `_generar_pdfs`).
6. Al iniciar sesión: `python -m pytest -q` y reportar. Al cerrar cada fase: todo verde y
   pruebas nuevas para lo agregado. Si una prueba existente choca con un cambio pedido,
   actualizarla y explicar por qué.
7. Compilar con `python -m PyInstaller --noconfirm DESCARGA_XML_EDDP.spec`
   (no usar `construir_exe.bat`: tiene `pause`).

## Arquitectura
```
app.py                        UI completa (App, VisorCFDI, diálogos)
sat_descarga/config.py        Config/Opciones/Perfil (RFC + e.firma), carpeta_datos()
sat_descarga/lector.py        XML → Renglon (COLUMNAS, COLUMNAS_COPIADO, CLASES),
                              leer_detalle() para visor/PDF, volcado_xml()
sat_descarga/inteligencia.py  perspectiva, duplicados, relaciones, Memoria (memoria.json)
sat_descarga/exportar.py      Excel/CSV/TSV, Indice (indice_xml.csv)
sat_descarga/consulta.py      MotorSQL (sqlite en memoria) + plantillas
sat_descarga/pdf.py           cfdi_a_pdf(), generar_pdfs(), nombre_pdf(), config del PDF
sat_descarga/perfiles.py      perfiles de reporte (multi-cliente) → perfiles_reporte.json
sat_descarga/respaldo.py      respaldar/restaurar .zip
sat_descarga/tema.py          tema claro/oscuro, fuentes, zoom
```
- **Dos tipos de "perfil"**: `config.Perfil` = RFC con e.firma (pestaña Descargar).
  `perfiles.PerfilReporte` = cliente para reportes/PDF (pestaña Datos). No mezclarlos.
- Clase (letra) = qué es el CFDI para quien lo lee: I/G/N/P/E/T (`lector.clase_de`).
  Requiere perspectiva (Emitido/Recibido): por carpeta `emitidos|recibidos`, por RFC
  registrado, por RFC(s) del perfil de reporte activo, o asignada por el usuario.
- La lectura de XML corre en hilo (`App._leer_datos`): leer + inteligencia + MotorSQL;
  al terminar el hilo manda `("__fin_lectura__", ...)` a la cola. En pruebas usar
  `app._leer_datos(esperar=True)`.

## Pruebas
`python -m pytest -q` (UI real con Tk oculto). XML reales en `tests/xml_reales/`.
`tests/conftest.py` trae `texto_pdf()` (pypdf; pdftotext sólo si existe) y `openssl()`
(se salta limpio si no hay openssl). También reintenta `Tk()` cuando Windows falla al leer
init.tcl/tk.tcl (falla intermitente que ya existía) y hace `gc.collect()` tras cada prueba
para que la basura de Tk no se recolecte dentro del hilo de otra prueba.
