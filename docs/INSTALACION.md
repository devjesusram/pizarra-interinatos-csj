# Guía de instalación (servidor sin internet)

Esta guía está pensada para alguien que instala esto por primera vez. Siga los pasos en orden.

## ¿Cómo funciona la instalación sin internet?

El servidor no tiene internet, así que no puede descargar nada. Por eso el trabajo se divide en dos partes:

```
 PC CON internet                                Servidor SIN internet
 ┌───────────────────────────┐   pendrive o     ┌──────────────────────────────┐
 │ 1. Descarga el código     │   carpeta de     │ 3. Carga el paquete          │
 │ 2. Arma el "paquete"      │ ───────────────▶ │ 4. Inicia el sistema         │
 │    (un archivo .tar.gz)   │   red            │ 5. Se usa desde el navegador │
 └───────────────────────────┘                  └──────────────────────────────┘
```

El paquete trae todo lo necesario: la aplicación y la base de datos PostgreSQL, ya listas, dentro de "imágenes" de Docker.

> **¿Va a usarlo en una sola computadora ("localhost")?** Los pasos son los mismos. La única diferencia es que el
> sistema se abre en esa misma computadora, en `http://localhost:8080`, y nadie más de la red puede verlo.

---

## Parte 1 · En una PC con internet: armar el paquete

### 1.1 Instalar Docker en la PC con internet

- **Windows 10/11:** instale **Docker Desktop** desde <https://www.docker.com/products/docker-desktop/> y reinicie.
  Abra Docker Desktop y espere a que diga *"Engine running"*.
- **Ubuntu:** siga <https://docs.docker.com/engine/install/ubuntu/>.

### 1.2 Descargar el código

En GitHub, abra el repositorio y use **Code → Download ZIP**, o bien con git:

```bash
git clone https://github.com/devjesusram/pizarra-interinatos-csj.git
```

### 1.3 Armar el paquete

**En Ubuntu o en macOS** (dentro de la carpeta del proyecto):

```bash
./scripts/preparar-paquete-offline.sh
```

Esto crea `paquete-offline/pizarra-offline-AAAAMMDD.tar.gz`, de unos 200 MB.

**En Windows (PowerShell)**, dentro de la carpeta del proyecto, ejecute estas tres órdenes una por una:

```bash
docker build --platform linux/amd64 -t pizarra-interinatos:1.0 backend
```
```bash
docker pull --platform linux/amd64 postgres:16
```
```bash
docker save pizarra-interinatos:1.0 postgres:16 -o imagenes.tar
```

Después arme una carpeta llamada `pizarra` con este contenido:

```
pizarra/
├── imagenes.tar
├── docker-compose.yml
├── .env.example
├── docs/
└── scripts/   (instalar-offline.sh, crear-admin.sh, respaldo.sh, restaurar.sh)
```

### 1.4 Descargar Docker para el servidor (solo la primera vez)

El servidor también necesita Docker. Como no tiene internet, hay que descargar los instaladores desde la PC con
internet. Para **Ubuntu Server 24.04** entre a:

<https://download.docker.com/linux/ubuntu/dists/noble/pool/stable/amd64/>

y descargue **la versión más reciente** de estos 5 archivos `.deb`:

| Archivo | Para qué sirve |
|---|---|
| `containerd.io_…_amd64.deb` | El motor de contenedores |
| `docker-ce_…_amd64.deb` | Docker |
| `docker-ce-cli_…_amd64.deb` | El comando `docker` |
| `docker-buildx-plugin_…_amd64.deb` | Complemento de Docker |
| `docker-compose-plugin_…_amd64.deb` | El comando `docker compose` |

Copie al pendrive la carpeta `pizarra` (o el `.tar.gz`) y los 5 archivos `.deb`.

---

## Parte 2 · En el servidor sin internet

### 2.1 Instalar Ubuntu Server 24.04 LTS

Durante la instalación:
- Configure una **IP fija**.
- Marque ✅ **Install OpenSSH server**, para poder administrarlo desde su PC.
- En la pantalla de paquetes adicionales (*snaps*), **no marque "docker"**: se instala aparte en el paso 2.3.

### 2.2 Configurar la zona horaria (importante para las fechas)

```bash
sudo timedatectl set-timezone America/Asuncion
```

### 2.3 Instalar Docker desde el pendrive

Monte el pendrive o copie los `.deb` a una carpeta, por ejemplo `~/docker-debs`, y ejecute:

```bash
cd ~/docker-debs && sudo apt install -y ./*.deb
```

Permita que su usuario use Docker sin `sudo`. Después cierre la sesión y vuelva a entrar:

```bash
sudo usermod -aG docker $USER
```

Verifique la instalación:

```bash
docker compose version
```

> Si `apt` dice que falta alguna dependencia (es raro en Ubuntu Server, pero posible), anote su nombre, descárguela
> desde <https://packages.ubuntu.com/noble/> en la PC con internet e instálela de la misma manera.

### 2.4 Copiar e instalar la Pizarra

Copie el paquete a `/opt` y descomprímalo (si trajo la carpeta `pizarra` en lugar del `.tar.gz`, simplemente cópiela a `/opt/pizarra`):

```bash
sudo mkdir -p /opt && sudo tar -xzf pizarra-offline-*.tar.gz -C /opt && sudo chown -R $USER:$USER /opt/pizarra
```

Instale el sistema:

```bash
cd /opt/pizarra && ./scripts/instalar-offline.sh
```

El script:
1. carga las imágenes;
2. crea el archivo `.env` con una contraseña de base de datos aleatoria;
3. inicia el sistema;
4. muestra la dirección donde quedó funcionando.

### 2.5 Crear el primer administrador

```bash
./scripts/crear-admin.sh admin "Su Nombre y Apellido"
```

El script le pide una contraseña de al menos 8 caracteres.

### 2.6 Abrir el sistema

- Desde el mismo servidor: `http://localhost:8080`
- Desde otra PC de la red: `http://IP-DEL-SERVIDOR:8080`

Si tiene el firewall activado, permita el puerto:

```bash
sudo ufw allow 8080/tcp
```

---

## Parte 3 · Primeros pasos dentro del sistema

Entre con el usuario administrador y abra **👤 → ⚙ Administración**:

1. **Despachos:** cargue los juzgados de la circunscripción, con su fuero y localidad.
2. **Personal:** cargue a cada funcionario con su cargo (Juez, Actuario, Secretario, Ujier) y su despacho.
3. **Usuarios:** cree un usuario para cada compañero de Servicios Informáticos.
   - **Operador:** carga licencias e interinatos.
   - **Administrador:** además gestiona el personal, los usuarios y la auditoría.
4. **Días inhábiles:** cargue los feriados y la feria judicial del año.

### ¿Quiere practicar antes con datos de ejemplo?

En una instalación **vacía** puede cargar datos ficticios: 10 despachos, 40 funcionarios y algunas licencias.

```bash
docker compose exec app python -m app.cli demo
```

Cuando termine de practicar y quiera empezar de cero con los datos reales, este comando **borra TODOS los datos**:

```bash
docker compose down -v
```

Después vuelva a ejecutar `./scripts/instalar-offline.sh` y `./scripts/crear-admin.sh`.

---

## Parte 4 · Respaldos (no lo deje para después)

Hacer un respaldo ahora:

```bash
./scripts/respaldo.sh /opt/pizarra-respaldos
```

Para que se haga solo cada noche a las 23:30, abra el programador de tareas:

```bash
crontab -e
```

y agregue esta línea al final:

```
30 23 * * * /opt/pizarra/scripts/respaldo.sh /opt/pizarra-respaldos >> /opt/pizarra-respaldos/respaldo.log 2>&1
```

- Se guardan los respaldos de los últimos 30 días.
- **Copie la carpeta `/opt/pizarra-respaldos` a otro equipo** con regularidad (NAS, servidor de archivos o disco
  externo). Si el servidor se rompe, un respaldo guardado en ese mismo servidor se pierde con él.
- **Pruebe una restauración** una vez al mes, mejor en un equipo de pruebas:

```bash
./scripts/restaurar.sh /opt/pizarra-respaldos/pizarra-db-AAAAMMDD-HHMM.dump /opt/pizarra-respaldos/pizarra-adjuntos-AAAAMMDD-HHMM.tar.gz
```

---

## Parte 5 · Actualizar a una versión nueva

1. En la PC con internet, descargue la versión nueva del código y vuelva a armar el paquete (Parte 1.3).
2. En el servidor, haga primero un respaldo (Parte 4).
3. Descomprima el paquete nuevo **sobre** `/opt/pizarra`. Su archivo `.env` se conserva porque el paquete no lo trae.
4. Ejecute:

```bash
cd /opt/pizarra && ./scripts/instalar-offline.sh
```

Los datos (base de datos y adjuntos) se conservan.

---

## Problemas frecuentes

| Problema | Solución |
|---|---|
| "port is already allocated" | Otro programa usa el puerto 8080. Cambie `PUERTO=8090` en `.env` y ejecute `docker compose up -d`. |
| Olvidé la contraseña del administrador | `./scripts/crear-admin.sh admin "Nombre"` vuelve a ponerle una contraseña. |
| Un operador olvidó su contraseña | Un administrador entra en Administración → Usuarios → Editar y le pone una nueva. |
| El sistema no abre | Revise si está corriendo con `docker compose ps` y mire los errores con `docker compose logs app --tail 50`. |
| Las fechas aparecen corridas | Revise la zona horaria del servidor (paso 2.2). |
| Reiniciar el sistema | `docker compose restart`. El sistema también arranca solo cuando se enciende el servidor. |
