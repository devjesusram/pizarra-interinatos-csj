# Pizarra digital de interinatos y licencias

Sistema web interno que reemplaza la pizarra física donde se controlan las **licencias** y los **interinatos**
del personal judicial (Juez, Actuario/a, Secretario/a, Ujier) de la **Circunscripción Judicial de Cordillera**.

> **Decisión manual, control digital.** El sistema **no** decide reemplazos. El operador carga lo que llega por correo
> (licencias aprobadas por el Consejo de Administración o por RRHH) y asigna los interinos. El sistema ordena,
> muestra en un calendario y **valida** que no haya cruces de fechas.

Es un proyecto **experimental e independiente**: tiene sus propios usuarios y no usa Active Directory. Funciona
**sin internet**.

## Qué hace

- **Pizarra / planner:** una fila por funcionario y una columna por día, agrupada por cargo o por despacho.
  - 🟥 **Licencia** (con 📎 si tiene adjunto)
  - 🟦 **Cubriendo un interinato** (los jueces pueden cubrir varios despachos a la vez)
  - 🟩 **Cubierto por…**
  - 🟨 **⚠ Sin cubrir** (clic para asignar un interino)
  - 🟪 **⚡ En conflicto** (el interino recibió una licencia)
- **Alertas:** ausentes sin interino en días hábiles e interinatos en conflicto.
- **Validación anti-errores:** se aplica en el backend y además en la base de datos. Ver las reglas abajo.
- **Registro de licencias desde el correo:** se adjunta el PDF o el `.eml`. Si se arrastra un `.eml`, el sistema
  completa remitente, fecha y asunto.
- **Selector de interinos:** muestra solo personas del mismo cargo, con su disponibilidad y el motivo cuando no
  están disponibles.
- **Exportación `.ics`:** archivo descargable y enlace de suscripción por funcionario, para Google, Outlook o el
  teléfono.
- **Modo TV:** pantalla de solo lectura para un monitor en la oficina.
- **Usuarios y roles:** OPERADOR / ADMIN. Hay **auditoría** completa: quién cargó qué y qué avisos confirmó.
- **Control de concurrencia:** si dos operadores editan el mismo registro, el segundo recibe un aviso en lugar de
  pisar el cambio del primero.

### Reglas de validación

| Regla | Qué controla | Resultado |
|---|---|---|
| R1 | La fecha de fin no puede ser anterior a la de inicio | ⛔ Bloquea |
| R2 | Nadie puede cubrirse a sí mismo | ⛔ Bloquea |
| R3 | Funcionario dado de baja | ⛔ Bloquea |
| R4 | El interino está de licencia | ⛔ Bloquea |
| R5 | El interino ya cubre otro despacho (salvo jueces, que pueden acumular) | ⛔ Bloquea · ℹ️ informa en jueces |
| R6 | El titular ya tiene interino en esas fechas | ⛔ Bloquea |
| R7 | El interino está ausente y cubierto por otro | ⛔ Bloquea |
| R8 | El titular no tiene licencia registrada en parte del período | ⚠ Pide confirmación |
| R9 | Solo entre pares (Juez↔Juez, Actuario↔Actuario…) | ⛔ Bloquea (también en la BD) |
| R10 | Otro operador modificó el registro mientras se editaba | ⛔ Bloquea |
| L1 | Dos licencias de la misma persona se cruzan | ⛔ Bloquea (también en la BD) |
| L2 | La licencia de alguien que está cubriendo un despacho | ✔ Se guarda y el interinato pasa a **EN CONFLICTO** |

## Instalación

👉 **[docs/INSTALACION.md](docs/INSTALACION.md)**: guía paso a paso para un servidor sin internet.

Resumen:

```bash
bash scripts/preparar-paquete-offline.sh        # en una PC con internet
```
```bash
bash scripts/instalar-offline.sh                # en el servidor, dentro de /opt/pizarra
```
```bash
bash scripts/crear-admin.sh admin "Nombre y Apellido"
```

## Estructura

```
├── docker-compose.yml        # PostgreSQL 16 + aplicación
├── .env.example              # configuración (copiar a .env)
├── backend/
│   ├── Dockerfile
│   ├── app/
│   │   ├── esquema.sql       # tablas, restricciones EXCLUDE y trigger "entre pares"
│   │   ├── validaciones.py   # reglas R1–R10 / L1
│   │   ├── servicios.py      # alta/edición/anulación con locks, auditoría y conflictos (L2)
│   │   ├── main.py           # API (FastAPI) y páginas
│   │   ├── auth.py           # usuarios propios (contraseñas con scrypt) y sesiones
│   │   ├── ics.py            # exportación iCalendar
│   │   ├── cli.py            # crear-admin, datos de ejemplo
│   │   └── static/           # interfaz (HTML + CSS + JavaScript, sin dependencias externas)
│   └── tests/                # pruebas con PostgreSQL real
├── scripts/                  # paquete sin internet, instalación, respaldo, restauración
└── docs/INSTALACION.md
```

## Desarrollo

Requiere Python 3.12 o superior y un PostgreSQL 16 de pruebas.

Instale las dependencias:

```bash
cd backend && pip install -r requirements-dev.txt
```

Ejecute las pruebas. **¡Atención: borran por completo la base de datos indicada!**

```bash
TEST_DATABASE_URL=postgresql://usuario:clave@localhost:5432/pizarra_test python -m pytest -q
```

Para levantar la aplicación en modo desarrollo:

```bash
DATABASE_URL=postgresql://usuario:clave@localhost:5432/pizarra ADJUNTOS_DIR=./adjuntos uvicorn app.main:app --reload
```

La documentación de la API está en `/api/docs`.
