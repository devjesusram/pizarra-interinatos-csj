@echo off
title Pizarra de Interinatos - Desinstalar servicio
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Este paso necesita permisos de ADMINISTRADOR.
  echo  Haga clic derecho en desinstalar-servicio.bat y elija "Ejecutar como administrador".
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\desinstalar-servicio.ps1"
echo.
pause
