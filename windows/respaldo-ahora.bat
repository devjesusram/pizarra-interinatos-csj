@echo off
title Pizarra de Interinatos - Respaldo
cd /d "%~dp0"
echo.
echo  Haciendo un respaldo de la base de datos y de los adjuntos...
echo  (se puede hacer con el sistema en uso)
echo.
"%~dp0python\python.exe" -m app.cli respaldo "%~dp0respaldos"
echo.
echo  IMPORTANTE: copie la carpeta "respaldos" a otro equipo o a un disco externo.
echo.
pause
