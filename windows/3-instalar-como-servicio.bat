@echo off
title Pizarra de Interinatos - Instalar como servicio
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Este paso necesita permisos de ADMINISTRADOR.
  echo  Cierre esta ventana, haga clic derecho en 3-instalar-como-servicio.bat
  echo  y elija "Ejecutar como administrador".
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\instalar-servicio.ps1"
echo.
pause
