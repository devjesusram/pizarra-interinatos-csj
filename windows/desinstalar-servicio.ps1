# Pizarra de Interinatos - quita el inicio automatico (NO borra los datos).
# Este archivo usa solo caracteres ASCII a proposito (PowerShell 5.1).

$tarea = 'Pizarra de Interinatos'
$tareaRespaldo = 'Pizarra de Interinatos - Respaldo'

Stop-ScheduledTask -TaskName $tarea -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $tarea -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $tareaRespaldo -Confirm:$false -ErrorAction SilentlyContinue
Get-NetFirewallRule -DisplayName 'Pizarra de Interinatos' -ErrorAction SilentlyContinue | Remove-NetFirewallRule

Write-Host ''
Write-Host '  Listo: se quito el inicio automatico, el respaldo nocturno y la regla del firewall.' -ForegroundColor Green
Write-Host '  Los datos (carpeta "datos") y los respaldos NO se borraron.'
