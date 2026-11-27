# Pizarra digital de interinatos y licencias

Sistema web interno que reemplaza la pizarra física donde se controlan las **licencias** y los **interinatos**
del personal judicial (Juez, Actuario/a, Secretario/a, Ujier) de la **Circunscripción Judicial de Cordillera**.

> **Decisión manual, control digital.** El sistema **no** decide reemplazos. El operador carga lo que llega por correo
> (licencias aprobadas por el Consejo de Administración o por RRHH) y asigna los interinos. El sistema ordena,
> muestra en un calendario y **valida** que no haya cruces de fechas.

Es un proyecto **experimental e independiente**: tiene sus propios usuarios y no usa Active Directory.

**Desarrollado por la Sección de Servicios Informáticos** de la Circunscripción Judicial de Cordillera, con la asistencia
de **Claude** (inteligencia artificial de Anthropic).

**Liviano:** corre en cualquier PC con Windows 10/11, sin internet, sin Docker y sin instalar Python. La base de
datos es un solo archivo (SQLite). Se instala en una PC que hace de servidor y el resto entra desde el navegador.

👉 **Instalación: [docs/INSTALACION-WINDOWS.md](docs/INSTALACION-WINDOWS.md)**

## Qué hace

- **Tablero de interinazgos (pantalla principal):** reproduce la pizarra acrílica "INTERINAZGOS JUZGADOS 2026" con
  un recuadro por interinazgo: TITULAR, INTERINO, FECHA, DESPACHO (texto libre) y DESVINCULAR (puede quedar en
  blanco). El interino cubre las 24 horas de su último día («Hasta») y se lo desvincula **al día siguiente**.
  Con los botones **Vincular** y **Desvincular** se confirma, con auditoría del usuario, que el interino asumió y que terminó. Colores por estado (vigente, se desvincula en ≤ 3 días, por empezar, en conflicto, desvinculado), filtro
  por año, cargo y búsqueda, botón «Desvincular hoy» e impresión.
- **Pizarra / planner:** una fila por funcionario y una columna por día, agrupada por cargo o por despacho.
  - 🟥 **Licencia** (con 📎 si tiene adjunto)
  - 🟦 **Cubriendo un interinato** (jueces, actuarios y secretarios pueden cubrir varios despachos a la vez)
  - 🟩 **Cubierto por…**
  - 🟨 **⚠ Sin cubrir** (clic para asignar un interino)
  - 🟪 **⚡ En conflicto** (el interino recibió una licencia)
- **Alertas:** ausentes sin interino en días hábiles e interinatos en conflicto.
- **Validación anti-errores:** se aplica en la aplicación y además en la base de datos (triggers). Ver las reglas abajo.
- **Registro de licencias desde el correo:** se adjunta el PDF o el `.eml`. Si se arrastra un `.eml`, el sistema
  completa remitente, fecha y asunto.
- **Selector de interinos:** muestra solo personas del mismo cargo, con su disponibilidad y el motivo cuando no
  están disponibles. Sugiere primero a los compañeros del mismo despacho o turno.
- **Turnos:** cada despacho puede tener su turno, y la pizarra se puede filtrar por turno.
- **Secretarías y puestos vacantes:** cada funcionario puede tener su Secretaría (Nº 1, Nº 2…). Un puesto sin
  titular se carga como **vacante**, y quien queda a cargo se asigna como un interinato de puesto vacante. Si un
  puesto vacante se queda sin nadie a cargo, aparece en las alertas.
- **Titular de más de un juzgado:** un juez (o actuario/a, secretario/a) puede ser titular de dos o más despachos sin
  cambiar de despacho principal. Un solo interino cubre todos sus juzgados.
- **Juez responsable:** en la vista por despacho, cada encabezado muestra el juez y, si está ausente, quién está a
  cargo ese día.
- **Exportación `.ics`:** archivo descargable y enlace de suscripción por funcionario.
- **Modo TV:** pantalla de solo lectura para un monitor en la oficina.
- **Manual de usuario incluido:** en `/manual` (menú 👤 → 📖 Manual de usuario, o desde la pantalla de ingreso),
  con capturas de pantalla y sin necesidad de internet. Se puede imprimir o guardar como PDF.
- **Icono personalizable:** la pestaña del navegador muestra una balanza azul; para usar otro basta con copiar un
  `icono.ico` (o `icono.png`) a la carpeta `datos/`, sin reiniciar y sin perderlo al actualizar.
- **Usuarios y roles:** OPERADOR / ADMIN, con **auditoría** completa.
- **Actualización automática:** cada 15 segundos cada pantalla busca cambios de los demás usuarios y se redibuja
  sola (sin F5), sin interrumpir a quien tiene un formulario abierto. Indicador «● Actualizado hace…» en la barra.
- **Varios operadores a la vez:** las escrituras se atienden de a una (`BEGIN IMMEDIATE`), así que dos personas
  guardando al mismo tiempo no pueden generar cruces. Si dos editan el mismo registro, el segundo recibe un aviso.
- **Respaldo automático nocturno** y restauración con un doble clic.
- **Actualizaciones sin perder datos:** al instalar una versión nueva, la base se actualiza sola al iniciar y antes
  se guarda un respaldo en `respaldos/antes-de-actualizar`.

### Reglas de validación

| Regla | Qué controla | Resultado |
|---|---|---|
| R1 | La fecha de fin no puede ser anterior a la de inicio | ⛔ Bloquea |
| R2 | Nadie puede cubrirse a sí mismo | ⛔ Bloquea |
| R3 | Funcionario dado de baja | ⛔ Bloquea |
| R4 | El interino está de licencia | ⛔ Bloquea |
| R5 | El interino supera el límite de despachos a la vez de su cargo (configurable en Administración → Cargos; por defecto jueces, actuarios y secretarios sin límite, ujieres de a uno) | ⛔ Bloquea · ℹ️ informa cuántos despachos acumula |
| R6 | El titular (o el puesto vacante) ya tiene a alguien a cargo en esas fechas | ⛔ Bloquea (también en la BD) |
| R7 | El interino está ausente y cubierto por otro | ⛔ Bloquea |
| R8 | El titular no tiene licencia registrada en parte del período (o, si es un puesto vacante, el período queda fuera de la vacancia) | ⚠ Pide confirmación |
| R9 | Solo entre pares (Juez↔Juez, Actuario↔Actuario…) | ⛔ Bloquea (también en la BD) |
| R10 | Otro operador modificó el registro mientras se editaba | ⛔ Bloquea |
| L1 | Dos licencias de la misma persona se cruzan | ⛔ Bloquea (también en la BD) |
| L2 | La licencia de alguien que está cubriendo un despacho | ✔ Se guarda y el interinato pasa a **EN CONFLICTO** |

## Estructura

```
├── app/
│   ├── esquema.sql        # tablas SQLite y triggers (sin cruces, solo entre pares)
│   ├── validaciones.py    # reglas R1–R10 / L1
│   ├── servicios.py       # alta/edición/anulación con auditoría y conflictos (L2)
│   ├── main.py            # API (FastAPI) y páginas
│   ├── servidor.py        # arranque del servidor web (python -m app.servidor)
│   ├── auth.py            # usuarios propios (contraseñas con scrypt) y sesiones
│   ├── ics.py             # exportación iCalendar
│   ├── cli.py             # crear-admin, demo, respaldo, restaurar
│   ├── config.py          # configuración (configuracion.txt / variables de entorno)
│   └── static/            # interfaz (HTML + CSS + JavaScript, sin dependencias externas)
├── windows/               # archivos .bat y .ps1 que van en el paquete de Windows
├── scripts/armar_paquete_windows.py   # arma dist/Pizarra-Windows-<versión>.zip
├── tests/                 # pruebas automáticas
└── docs/INSTALACION-WINDOWS.md
```

## Armar el paquete para Windows

En cualquier computadora con internet y Python 3.12 o superior (Linux, macOS o Windows):

```bash
python scripts/armar_paquete_windows.py
```

Genera `dist/Pizarra-Windows-<versión>.zip` (unos 20 MB), con Python portátil y todas las librerías incluidas.

## Desarrollo

Instale las dependencias:

```bash
pip install -r requirements-dev.txt
```

Ejecute las pruebas (cada una usa una base temporal):

```bash
python -m pytest -q
```

Inicie el servidor. Los datos quedan en la carpeta `datos/`:

```bash
python -m app.servidor
```

Abra `http://localhost:8080`. La documentación de la API está en `/api/docs`. Funciona igual en Linux.
