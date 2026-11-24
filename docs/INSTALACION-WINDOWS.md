# Instalación en Windows

La Pizarra se instala en **una sola PC**, que hace de servidor. Los compañeros entran desde el navegador de su propia
PC, sin instalar nada.

**No hace falta:** internet en el servidor, Docker, WSL, virtualización ni instalar Python.
**Sí hace falta:** una PC con Windows 10 u 11, de 64 bits.

```
   PCs de la oficina                             PC servidor (ej.: 172.31.60.254)
 ┌──────┐ ┌──────┐ ┌──────┐   http://…:8080   ┌───────────────────────────────┐
 │ PC 1 │ │ PC 2 │ │ PC 3 │ ────────────────▶ │ C:\Pizarra                    │
 └──────┘ └──────┘ └──────┘   (navegador)     │  · se inicia sola al encender │
                                              │  · datos en un solo archivo   │
                                              │  · respaldo cada noche        │
                                              └───────────────────────────────┘
```

---

## Paso 1 · Descargar el paquete (en una PC con internet)

Descargue el archivo **`Pizarra-Windows-X.Y.Z.zip`**, de unos 25 MB, desde la sección **Releases** del repositorio
en GitHub.

Si ya se lo enviaron por otro medio, use ese archivo y siga con el Paso 2.

> **Antes de descomprimir:** haga clic derecho en el ZIP → **Propiedades** → si abajo aparece la casilla
> **"Desbloquear"**, márquela → **Aceptar**. Así Windows no muestra advertencias de seguridad con cada archivo.

Copie el ZIP a la PC servidor (pendrive o carpeta compartida).

## Paso 2 · Descomprimir en `C:\Pizarra`

1. En la PC servidor, haga clic derecho en el ZIP → **Extraer todo…**.
2. Elija **`C:\`** como destino. Va a quedar la carpeta **`C:\Pizarra`**.
3. Compruebe que dentro de `C:\Pizarra` estén los archivos `1-crear-administrador.bat`, `LEAME.txt` y la carpeta
   `python`.

No la ponga en "Archivos de programa" ni en el Escritorio: el sistema necesita poder escribir en su carpeta.

## Paso 3 · Crear el administrador

Haga doble clic en **`1-crear-administrador.bat`** y complete lo que pide:

- **Usuario**, por ejemplo `admin`.
- **Nombre y apellido.**
- **Contraseña**, dos veces, de al menos 8 caracteres. Al escribirla no se ve nada en pantalla; es normal.

> Si Windows muestra **"Windows protegió su PC"**, haga clic en **Más información → Ejecutar de todas formas**.
> Pasa la primera vez con archivos descargados de internet (evítelo con el paso "Desbloquear" del Paso 1).

## Paso 4 · Probar (opcional, recomendado)

Haga doble clic en **`2-probar-en-esta-ventana.bat`**. Se abre una ventana negra y el navegador con la Pizarra.

- Entre con el usuario que creó.
- Si quiere practicar, cierre la ventana negra, haga doble clic en **`cargar-datos-de-ejemplo.bat`** y vuelva a
  abrir **`2-probar-en-esta-ventana.bat`**.

El sistema funciona **mientras la ventana negra esté abierta**. Ciérrela antes de seguir con el Paso 5.

## Paso 5 · Dejarlo funcionando siempre

Haga clic derecho en **`3-instalar-como-servicio.bat`** → **Ejecutar como administrador**.

Eso hace cuatro cosas:
1. Registra la Pizarra para que **se inicie sola al encender la PC, aunque nadie inicie sesión**. Si por algún motivo
   se detiene, se vuelve a iniciar sola en pocos minutos.
2. Programa un **respaldo automático todas las noches a las 23:30** en `C:\Pizarra\respaldos`.
3. **Abre el puerto 8080** en el Firewall de Windows.
4. Inicia la Pizarra y muestra las direcciones para entrar.

Si la ventana dice **"LISTO: la Pizarra está funcionando"**, ya está.

## Paso 6 · Entrar desde las otras PCs

En cualquier PC de la red, abra el navegador (Chrome, Edge o Firefox) y escriba:

**`http://172.31.60.254:8080`**

(Use la IP de su PC servidor; la ventana del Paso 5 la muestra.)

---

## Primeros pasos dentro del sistema

Entre como administrador y abra **👤 → ⚙ Administración**:

1. **Despachos:** cargue los juzgados de la circunscripción, con su fuero y localidad.
2. **Personal:** cargue a cada funcionario con su cargo y su despacho.
3. **Usuarios:** cree un usuario para cada compañero.
   - **Operador:** carga licencias e interinatos.
   - **Administrador:** además gestiona el personal, los usuarios y la auditoría.
4. **Días inhábiles:** cargue los feriados y la feria judicial del año.

### Si cargó datos de ejemplo y quiere empezar con los datos reales

1. Haga clic derecho en **`desinstalar-servicio.bat`** → **Ejecutar como administrador**. Si estaba usando el modo
   prueba, cierre la ventana negra.
2. **Borre la carpeta `C:\Pizarra\datos`.** Se pierden todos los datos de ejemplo.
3. Repita los pasos 3 y 5.

---

## Respaldos

- **Automático:** todas las noches a las 23:30, en `C:\Pizarra\respaldos`. Se guardan los últimos 30 días.
- **Manual:** doble clic en **`respaldo-ahora.bat`**. Se puede hacer con el sistema en uso.
- Cada respaldo son dos archivos con la fecha y la hora: `pizarra-db-AAAAMMDD-HHMM.db` (los datos) y
  `pizarra-adjuntos-AAAAMMDD-HHMM.zip` (los PDF y correos).

⚠ **Copie la carpeta `respaldos` a otro equipo o a un disco externo con frecuencia.** Si la PC servidor se daña,
los respaldos que están en ella se pierden con ella.

### Restaurar un respaldo

1. Haga clic derecho en **`restaurar-respaldo.bat`** → **Ejecutar como administrador**.
2. Arrastre a la ventana el archivo `pizarra-db-….db` que quiere recuperar y presione Enter.
3. Escriba **SI** para confirmar.

Los adjuntos del mismo respaldo se restauran solos. Antes de restaurar, se guarda una copia de los datos actuales en
`respaldos\antes-de-restaurar`, por si se equivoca de archivo.

### Mudar la Pizarra a otra PC

1. En la PC vieja, haga un respaldo con `respaldo-ahora.bat`.
2. En la PC nueva, siga los pasos 2 y 5 de esta guía.
3. Restaure el respaldo en la PC nueva.

---

## Actualizar a una versión nueva

1. Haga un respaldo con `respaldo-ahora.bat`.
2. Ejecute `desinstalar-servicio.bat` como administrador.
3. Descomprima el ZIP nuevo en una carpeta aparte y copie a `C:\Pizarra` **solo** las carpetas `app` y `python` y
   los archivos `.bat`, reemplazando los anteriores. **No toque** las carpetas `datos` y `respaldos` ni el archivo
   `configuracion.txt`.
4. Ejecute `3-instalar-como-servicio.bat` como administrador.

---

## Recomendaciones para la PC servidor

| Qué | Cómo |
|---|---|
| Que no se suspenda | Configuración → Sistema → Inicio/apagado y suspensión → Suspender: **Nunca**. |
| Que no se reinicie en horario laboral | Configuración → Windows Update → Opciones avanzadas → **Horas activas**. |
| IP fija | Pídasela a quien administra la red, para que la dirección no cambie. |

Si la PC se reinicia por una actualización, la Pizarra vuelve a funcionar sola. No hace falta que nadie inicie
sesión.

---

## Problemas frecuentes

| Problema | Solución |
|---|---|
| Desde otra PC no abre | Pruebe `http://localhost:8080` **en el servidor**. Si ahí funciona, el problema es la red o el firewall: desde la otra PC ejecute `ping 172.31.60.254`. Si hay un antivirus institucional, puede estar bloqueando el puerto. |
| No abre ni en el servidor | Abra `C:\Pizarra\datos\registros\pizarra.log` con el Bloc de notas y fíjese en las últimas líneas. |
| "Address already in use" o el puerto está ocupado | Otro programa usa el puerto 8080. Cambie `PUERTO=8090` en `configuracion.txt` y vuelva a ejecutar `3-instalar-como-servicio.bat`. |
| Olvidé la contraseña del administrador | Ejecute `1-crear-administrador.bat` con el mismo usuario y elija una contraseña nueva. |
| Un operador olvidó su contraseña | Un administrador entra en Administración → Usuarios → Editar y le pone una nueva. |
| Detener la Pizarra un momento | Programador de tareas → "Pizarra de Interinatos" → Finalizar. Para quitarla del todo, use `desinstalar-servicio.bat`. |
