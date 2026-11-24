@echo off
title Pizarra de Interinatos - Restaurar respaldo
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Este paso necesita permisos de ADMINISTRADOR.
  echo  Haga clic derecho en restaurar-respaldo.bat y elija "Ejecutar como administrador".
  echo.
  pause
  exit /b 1
)
set "ARCHIVO=%~1"
if "%ARCHIVO%"=="" (
  echo.
  echo  Arrastre el archivo pizarra-db-AAAAMMDD-HHMM.db desde la carpeta "respaldos"
  echo  y suelte el archivo aqui, luego presione Enter.
  echo.
  set /p "ARCHIVO=Archivo: "
)
set "ARCHIVO=%ARCHIVO:"=%"
if not exist "%ARCHIVO%" (
  echo  No se encuentra el archivo: %ARCHIVO%
  pause
  exit /b 1
)
echo.
echo  ATENCION: esto REEMPLAZA todos los datos actuales por los del respaldo:
echo    %ARCHIVO%
echo  (antes se guarda una copia de los datos actuales en respaldos\antes-de-restaurar)
echo.
set /p "OK=Escriba SI para continuar: "
if /i not "%OK%"=="SI" (
  echo  Cancelado.
  pause
  exit /b 1
)
echo.
echo  Deteniendo la Pizarra...
schtasks /end /tn "Pizarra de Interinatos" >nul 2>&1
timeout /t 3 /nobreak >nul
"%~dp0python\python.exe" -m app.cli restaurar "%ARCHIVO%"
echo.
echo  Iniciando la Pizarra...
schtasks /run /tn "Pizarra de Interinatos" >nul 2>&1
if errorlevel 1 echo  (No esta instalada como servicio: iniciela con 2-probar-en-esta-ventana.bat)
echo.
pause
