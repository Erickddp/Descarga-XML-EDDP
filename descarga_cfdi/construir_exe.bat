@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================
echo   DESCARGA XML EDDP  -  compilar a .exe
echo ==========================================
echo.
echo [1/3] Instalando dependencias...
python -m pip install -q -r requirements.txt pyinstaller
if errorlevel 1 (echo ERROR instalando dependencias. Revisa que Python este instalado. & pause & exit /b 1)
echo [2/3] Compilando (tarda 1-3 minutos)...
python -m PyInstaller --noconfirm --clean DESCARGA_XML_EDDP.spec
if errorlevel 1 (echo ERROR al compilar. & pause & exit /b 1)
echo [3/3] Creando acceso directo en el Escritorio...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\DESCARGA XML EDDP.lnk'); $s.TargetPath='%~dp0dist\DESCARGA XML EDDP.exe'; $s.WorkingDirectory='%~dp0dist'; $s.Save()"
echo.
echo LISTO:  dist\DESCARGA XML EDDP.exe
echo         y un acceso directo "DESCARGA XML EDDP" en tu Escritorio.
echo Tus datos viven en %APPDATA%\DESCARGA XML EDDP  (no se pierden al recompilar).
pause
