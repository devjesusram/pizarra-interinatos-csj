@echo off
title Pizarra de Interinatos - Modo prueba
cd /d "%~dp0"
echo.
echo  ==========================================================
echo   Pizarra de Interinatos - MODO PRUEBA
echo  ==========================================================
echo.
echo  El sistema funciona MIENTRAS ESTA VENTANA ESTE ABIERTA.
echo  Abra el navegador en:  http://localhost:8080
echo.
echo  Para dejarlo funcionando siempre (aunque nadie inicie sesion),
echo  cierre esta ventana y use 3-instalar-como-servicio.bat
echo.
echo  Para detenerlo: cierre esta ventana o presione Ctrl+C.
echo  ----------------------------------------------------------
echo.
start "" http://localhost:8080
"%~dp0python\python.exe" -m app.servidor
echo.
echo  El servidor se detuvo. Si aparece un error arriba, copielo.
pause
