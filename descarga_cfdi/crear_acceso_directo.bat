@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\DESCARGA XML EDDP.lnk'); $s.TargetPath='%~dp0DESCARGA XML EDDP.pyw'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0recursos\icono.ico'; $s.Save()"
echo Acceso directo creado en tu Escritorio: DESCARGA XML EDDP
pause
