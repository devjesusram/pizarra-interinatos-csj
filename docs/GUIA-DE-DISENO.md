# Guía de diseño y base técnica — sistemas de la Sección de Servicios Informáticos

Esta guía describe el diseño y la base técnica de la **Pizarra de Interinatos**, para que los sistemas "hermanos"
(por ejemplo, el sistema de Tickets) se vean y se instalen igual. Un sistema hermano **copia** estos archivos y
convenciones en su propio repositorio; no importa código de la Pizarra en tiempo de ejecución.

## 1. Principios

- **Sin internet.** El servidor es una PC con Windows en la red interna (hoy `172.31.60.254`) sin salida a internet.
  Nada de CDN, fuentes web, librerías JS externas ni llamadas a servicios en la nube. Todo va dentro del paquete.
- **Liviano.** Python + FastAPI + uvicorn + SQLite (módulo `sqlite3` de la biblioteca estándar). Frontend en HTML,
  CSS y JavaScript sin frameworks ni compilación.
- **Paralelo e independiente.** Usuarios propios (sin Active Directory), su propia base, su propia carpeta y su
  propio puerto.
- **Todo en español** (Paraguay): textos, mensajes de error, nombres de tablas y funciones. Fechas `dd/mm/aaaa` en
  pantalla, ISO `aaaa-mm-dd` en la base. Zona horaria `America/Asuncion`.
- **Auditoría de todo.** Cada alta, edición, anulación o cambio de estado queda registrado con usuario y hora.
- **No se borra, se anula.** El borrado físico solo se permite si el registro no tiene nada asociado.
- **Créditos visibles:** *Desarrollado por la Sección de Servicios Informáticos · Circunscripción Judicial de
  Cordillera · con la asistencia de Claude (IA de Anthropic)*, en la pantalla de ingreso, al pie de la pantalla
  principal, en la ventana «Acerca de», en el manual, en el README y en el LEAME.txt.

## 2. Paleta de colores

Definida como variables CSS en `app/static/estilos.css` (`:root`). Un sistema hermano usa **los mismos nombres y
valores** para la base, y agrega los suyos para sus estados.

| Variable | Valor | Uso |
|---|---|---|
| `--fondo` | `#f4f5f7` | Fondo general, cabecera de tablas |
| `--panel` | `#ffffff` | Tarjetas, ventanas, formularios |
| `--texto` | `#1d2330` | Texto principal |
| `--texto-suave` | `#5b6475` | Etiquetas, ayudas, créditos |
| `--borde` | `#d9dde5` | Bordes finos |
| `--borde-fuerte` | `#b9c0cc` | Bordes de campos |
| `--primario` | `#1f4e8c` | Barra superior, botón principal, pestaña activa, enlaces |
| `--primario-hover` | `#183f72` | Hover del botón principal |
| `--licencia` / `--licencia-fondo` | `#c62828` / `#fde8e8` | Rojo: peligro, eliminar, urgente |
| `--interino` / `--interino-fondo` | `#1565c0` / `#e3eefb` | Azul: en curso |
| `--cubierto` / `--cubierto-fondo` | `#2e7d32` / `#e6f4e7` | Verde: correcto, resuelto |
| `--sin-cubrir` / `--sin-cubrir-fondo` | `#b26a00` / `#fff3d6` | Ámbar: advertencia, pendiente |
| `--conflicto` | `#6a1b9a` (fondo `#f3e5f5`) | Violeta: conflicto, escalado |
| `--inhabil` | `#eceef2` | Gris: anulado, cerrado, deshabilitado |
| `--hoy` | `#fff8c5` | Resaltado del día actual |
| `--radio` | `6px` | Radio de bordes |
| `--sombra` | `0 6px 24px rgba(20,30,50,.18)` | Ventanas modales |

Tipografía: `14px/1.4 system-ui, -apple-system, "Segoe UI", Roboto, Ubuntu, sans-serif` (sin fuentes externas).
Solo tema claro (`color-scheme: light`).

Sugerencia de equivalencias para estados de un ticket: **Nuevo** = ámbar, **En curso** = azul, **En espera** =
violeta, **Resuelto** = verde, **Cerrado/Anulado** = gris, **Urgente** = rojo.

## 3. Componentes (clases CSS)

| Clase | Qué es |
|---|---|
| `.barra` | Barra superior azul (`--primario`) con título `h1` + `.sub`, navegación a la derecha y menú del usuario 👤 |
| `.btn`, `.btn.primario`, `.btn.peligro`, `.btn.chico` | Botones: normal (blanco con borde), principal (azul), eliminar (rojo), chico |
| `.modal`, `.modal-cab`, `.modal-cuerpo`, `.modal-pie` | Ventana modal (`#modal`, y `#modal2` para una segunda encima). Botones en el pie, el principal a la derecha |
| `.form` | Formulario en grilla de 2 columnas: `160px minmax(0,1fr)` (etiqueta / campo); `.full` ocupa todo el ancho |
| `.pestanas` | Pestañas con borde inferior; la activa en azul y negrita |
| `.tabla`, `.tabla-contenedor` | Tablas con cabecera fija y desplazamiento vertical |
| `.chip.<ESTADO>` | Etiqueta redondeada de estado (fondo claro + texto del color fuerte) |
| `.toast` | Aviso breve abajo (éxito o error) |
| `.creditos` | Línea de créditos centrada, 12 px, `--texto-suave` |

Patrones de interacción:
- El menú 👤 tiene: Administración (solo ADMIN), Cambiar contraseña, 📖 Manual de usuario, ℹ Acerca de, Salir y la
  versión.
- Errores de validación: **bloqueo** (HTTP 409, mensaje en rojo) y **advertencia** (HTTP 428, se muestra y se pide
  confirmar). Si dos usuarios editan lo mismo, el segundo recibe un aviso (control por `version`).
- Administración en una ventana con pestañas: una tabla por catálogo con botones Editar / Eliminar y Auditoría.

## 4. Base técnica a copiar

| Archivo en la Pizarra | Qué aporta |
|---|---|
| `app/config.py` | Lee `configuracion.txt` (CLAVE=VALOR) y variables de entorno: carpetas, puerto, zona horaria |
| `app/db.py` | Conexión SQLite (WAL, autocommit), `escritura()` con `BEGIN IMMEDIATE`, migraciones numeradas con respaldo previo automático |
| `app/auth.py` | Usuarios propios, contraseñas con scrypt, sesiones con cookie, roles |
| `app/servidor.py` | Arranque de uvicorn (1 proceso) y registro en `datos/registros/*.log` |
| `app/cli.py` | `crear-admin`, `demo` (datos ficticios), `respaldo` (con retención) y `restaurar` |
| `app/main.py` | Patrón de API: middleware de caché (`no-cache` en páginas y estáticos, `no-store` en `/api`), `/salud`, `/manual` |
| `app/static/login.html`, `estilos.css`, `manual.html` | Pantalla de ingreso, estilos y manual sin internet |
| `windows/*` | `.bat`/`.ps1` de instalación como servicio (Programador de tareas como SYSTEM, vigilancia cada 5 min, respaldo diario 23:30, regla de firewall), `configuracion.txt`, `LEAME.txt` |
| `scripts/armar_paquete_windows.py` | Arma el ZIP con Python portátil 3.13 (NuGet) y librerías para `win_amd64` |
| `.gitattributes` | `.bat`/`.ps1` con CRLF y solo caracteres ASCII |
| `tests/` | Pruebas con pytest, una base temporal por prueba |

## 5. Convivencia en el mismo servidor

| | Pizarra | Sistema hermano (ej. Tickets) |
|---|---|---|
| Carpeta | `C:\Pizarra` | `C:\Tickets` |
| Puerto | `8090` | `8091` (otro distinto; 80/443 los usa XAMPP) |
| Tarea programada | «Pizarra de Interinatos» | nombre propio, ej. «Tickets de Soporte» |
| Respaldo nocturno | 23:30 | otra hora, ej. 23:45 |
| Cookie de sesión | `pizarra_sesion` | nombre propio, ej. `tickets_sesion` |
| Base de datos | `datos\pizarra.db` | `datos\tickets.db` |

La cookie **debe** tener otro nombre: las cookies se comparten por IP aunque cambie el puerto, y con el mismo nombre
un sistema cerraría la sesión del otro.

## 6. Datos de ejemplo y capturas

Los datos de demostración y las capturas del manual usan **nombres ficticios**, nunca datos reales de funcionarios.
