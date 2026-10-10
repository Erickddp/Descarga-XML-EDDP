# -*- mode: python ; coding: utf-8 -*-
# Compila DESCARGA XML EDDP en UN solo .exe (sin consola). Se usa desde construir_exe.bat
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []
d, b, h = collect_all("cfdiclient")          # trae sus plantillas XML del SAT
datas += d; binaries += b; hiddenimports += h
datas += collect_data_files("reportlab")
datas += [("recursos", "recursos")]
hiddenimports += ["openpyxl", "lxml.etree", "lxml._elementpath", "OpenSSL", "Crypto",
                  "sqlite3", "tkinter", "tkinter.ttk"]

a = Analysis(["app.py"], pathex=[], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
             excludes=["pytest", "_pytest", "matplotlib", "numpy", "pandas", "IPython"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
          name="DESCARGA XML EDDP", debug=False, strip=False, upx=False,
          console=False, icon="recursos/icono.ico")
