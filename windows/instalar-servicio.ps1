# Pizarra de Interinatos - instala el inicio automatico en Windows.
# (Se ejecuta desde 3-instalar-como-servicio.bat, como administrador.)
#
# Crea dos tareas programadas de Windows que corren como SYSTEM:
#   1. "Pizarra de Interinatos": inicia el sistema al encender la PC, aunque nadie
#      inicie sesion, y lo vuelve a levantar cada 5 minutos si se detuvo.
#   2. "Pizarra de Interinatos - Respaldo": respaldo automatico todas las noches.
# Ademas abre el puerto en el Firewall de Windows.
#
# Este archivo usa solo caracteres ASCII a proposito (PowerShell 5.1).

$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $PSScriptRoot
$python = Join-Path $base 'python\python.exe'
$pythonw = Join-Path $base 'python\pythonw.exe'
$tarea = 'Pizarra de Interinatos'
$tareaRespaldo = 'Pizarra de Interinatos - Respaldo'
$reglaFirewall = 'Pizarra de Interinatos'

function Paso($texto) { Write-Host ''; Write-Host "  >> $texto" -ForegroundColor Cyan }

if (-not (Test-Path $pythonw)) {
    Write-Host "  No se encuentra $pythonw" -ForegroundColor Red
    Write-Host '  Verifique que descomprimio el ZIP completo.'
    exit 1
}

# Puerto configurado
$puerto = 8080
$config = Join-Path $base 'configuracion.txt'
if (Test-Path $config) {
    foreach ($linea in Get-Content $config) {
        if ($linea -match '^\s*PUERTO\s*=\s*(\d+)\s*$') { $puerto = [int]$Matches[1] }
    }
}

Write-Host ''
Write-Host '  =========================================================='
Write-Host '   Pizarra de Interinatos - Instalacion como servicio'
Write-Host '  =========================================================='
Write-Host "   Carpeta: $base"
Write-Host "   Puerto:  $puerto"

# Si habia una instalacion anterior, se detiene y se reemplaza
Paso 'Deteniendo una instalacion anterior (si existe)...'
Stop-ScheduledTask -TaskName $tarea -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Paso 'Creando la tarea de inicio automatico...'
$accion = New-ScheduledTaskAction -Execute $pythonw -Argument '-m app.servidor' -WorkingDirectory $base
$alIniciar = New-ScheduledTaskTrigger -AtStartup
# Vigilancia: cada 5 minutos intenta iniciarlo; si ya esta corriendo, no hace nada
$vigilancia = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $tarea -Action $accion -Trigger @($alIniciar, $vigilancia) `
    -Principal $principal -Settings $ajustes -Force `
    -Description 'Pizarra digital de interinatos y licencias (servidor web).' | Out-Null

Paso 'Creando el respaldo automatico (todas las noches a las 23:30)...'
$destino = Join-Path $base 'respaldos'
$accionR = New-ScheduledTaskAction -Execute $python -Argument "-m app.cli respaldo `"$destino`"" -WorkingDirectory $base
$nocturno = New-ScheduledTaskTrigger -Daily -At '23:30'
$ajustesR = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $tareaRespaldo -Action $accionR -Trigger $nocturno `
    -Principal $principal -Settings $ajustesR -Force `
    -Description 'Respaldo nocturno de la Pizarra de interinatos.' | Out-Null

Paso "Abriendo el puerto $puerto en el Firewall de Windows..."
Get-NetFirewallRule -DisplayName $reglaFirewall -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $reglaFirewall -Direction Inbound -Protocol TCP -LocalPort $puerto `
    -Action Allow -Profile Any | Out-Null

Paso 'Iniciando la Pizarra...'
Start-ScheduledTask -TaskName $tarea
$ok = $false
# Se consulta directo a esta PC, SIN pasar por el proxy institucional (si lo hay)
$cliente = New-Object System.Net.WebClient
$cliente.Proxy = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    try {
        $respuesta = $cliente.DownloadString("http://127.0.0.1:$puerto/salud")
        if ($respuesta -match 'ok') { $ok = $true; break }
    } catch { }
}

Write-Host ''
if ($ok) {
    Write-Host '  LISTO: la Pizarra esta funcionando.' -ForegroundColor Green
    Write-Host ''
    Write-Host "   En esta PC:          http://localhost:$puerto"
    $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -ExpandProperty IPAddress
    foreach ($ip in $ips) { Write-Host "   Desde otras PCs:     http://${ip}:$puerto" }
    Write-Host ''
    Write-Host '  Se iniciara sola cada vez que se encienda la PC.'
} else {
    Write-Host '  La Pizarra no respondio todavia.' -ForegroundColor Yellow
    Write-Host "  Revise el archivo de registro: $base\datos\registros\pizarra.log"
    Write-Host '  Si el puerto esta ocupado por otro programa, cambie PUERTO en configuracion.txt'
    Write-Host '  y vuelva a ejecutar este instalador.'
}
