@echo off
title Pizarra de Interinatos - Datos de ejemplo
cd /d "%~dp0"
echo.
echo  Carga datos FICTICIOS para practicar (10 despachos, 40 funcionarios,
echo  algunas licencias e interinatos). Solo funciona con la base vacia.
echo.
echo  Para empezar despues con los datos reales: detenga la Pizarra y borre
echo  la carpeta "datos" (se pierden TODOS los datos), luego vuelva a crear
echo  el administrador.
echo.
set /p "OK=Escriba SI para cargar los datos de ejemplo: "
if /i not "%OK%"=="SI" exit /b 0
"%~dp0python\python.exe" -m app.cli demo
echo.
pause
