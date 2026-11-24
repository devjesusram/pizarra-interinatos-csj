@echo off
title Pizarra de Interinatos - Crear administrador
cd /d "%~dp0"
echo.
echo  ==========================================================
echo   Crear (o restablecer) un usuario ADMINISTRADOR
echo  ==========================================================
echo.
echo  Si el usuario ya existe, se le pone la nueva contrasena.
echo.
"%~dp0python\python.exe" -m app.cli crear-admin
echo.
pause
