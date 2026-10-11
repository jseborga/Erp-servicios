# 14 · Despliegue con Docker y Easypanel

## Qué se despliega

| Servicio | Imagen | Datos persistentes |
|---|---|---|
| `odoo` | Construida con el `Dockerfile` del repositorio sobre `odoo:19.0` (oficial) + `addons/` + `third_party/oca/` | Volumen `odoo-data` → `/var/lib/odoo` (adjuntos, sesiones) |
| `db` | `postgres:16` (oficial) | Volumen `db-data` |

Odoo 19 exige PostgreSQL 13 o superior (`MIN_PG_VERSION = 13` en `odoo/release.py`).

> **No usar `odoo:latest`:** desde la publicación de Odoo 20, `latest` apunta a Odoo 20. El `Dockerfile` fija `odoo:19.0`. Para una compilación exacta: `--build-arg ODOO_IMAGE=odoo:19.0-20260926`.

## Primer arranque automático

El script `docker/entrypoint-spa.sh`:

1. Genera `/etc/odoo/odoo.conf` desde las variables de entorno: base única, `list_db = False` (gestor de bases deshabilitado), `proxy_mode = True`. El archivo se crea con permisos 600.
2. Espera a PostgreSQL.
3. Si la base `ODOO_DB` no existe, la crea con `odoo db init --language es_BO --country BO`, con el usuario y la contraseña de `ODOO_INIT_LOGIN` y `ODOO_INIT_PASSWORD`.
4. Si `l10n_bo_spa` no está instalado, instala `ODOO_INIT_MODULES`. Así se carga el plan `bo` con las cuentas del spa, en español de Bolivia y en moneda BOB.
5. En los arranques siguientes no hace nada de lo anterior; solo arranca Odoo.

Probado el 11-oct-2026 con Odoo 19.0 y PostgreSQL 16: creación de la base, instalación de los módulos, segundo arranque sin reinstalar, actualización por `ODOO_UPDATE_MODULES`, inicio de sesión del administrador y gestor de bases bloqueado. **No se pudo probar `docker build`** en el entorno de trabajo, que no tiene acceso a Docker Hub. La primera construcción en su servidor es la prueba de la imagen.

## Variables de entorno

Ver `.env.example`. Obligatorias: `DB_PASSWORD`, `ODOO_ADMIN_PASSWD` y, en la primera instalación, `ODOO_INIT_PASSWORD`.

| Variable | Por defecto | Uso |
|---|---|---|
| `DB_USER` / `DB_PASSWORD` | `odoo` / — | Usuario de PostgreSQL |
| `ODOO_DB` | `spa` | Nombre de la base |
| `ODOO_ADMIN_PASSWD` | — | Contraseña maestra (operaciones de base de datos) |
| `ODOO_INIT` | `true` | Crear e instalar si la base no existe |
| `ODOO_INIT_LOGIN` / `ODOO_INIT_PASSWORD` | `admin` / — | Usuario administrador inicial |
| `ODOO_LANG` / `ODOO_COUNTRY` | `es_BO` / `BO` | Idioma y país de la compañía |
| `ODOO_INIT_MODULES` | `l10n_bo_spa` + OCA contables | Módulos de la primera instalación |
| `ODOO_UPDATE_MODULES` | vacío | Módulos a actualizar en el próximo arranque |
| `ODOO_WORKERS` | `0` | 0 = modo hilos (simple). >0 requiere enrutar `/websocket` al puerto 8072 |

## Opción A — Easypanel con servicio Compose (recomendada)

1. En Easypanel: **Create project** → **+ Service** → **Compose**.
2. **Source: Git**. URL `https://github.com/jseborga/erp-servicios.git`, rama `main`, build path `/`, archivo `docker-compose.yml`. El repositorio es privado: agregue en GitHub la *deploy key* de solo lectura que muestra Easypanel.
3. **Environment**: Easypanel copia `.env.example`. **Cambie todas las contraseñas.**
4. **Deploy.** La primera vez tarda varios minutos: construye la imagen y crea la base. Siga el avance en **Logs** del servicio `odoo`.
5. **Domains**: agregue su dominio (por ejemplo `erp.suspa.bo`) → servicio `odoo`, puerto `8069`, HTTPS activado.
6. Entre a `https://erp.suspa.bo` con `ODOO_INIT_LOGIN` / `ODOO_INIT_PASSWORD`.

El `docker-compose.yml` no publica puertos ni fija `container_name`, que son las dos configuraciones que la verificación de compatibilidad de Easypanel señala.

## Opción B — Easypanel con servicio App + Postgres de Easypanel

1. Cree un servicio **Postgres** en el proyecto (versión 16) y anote host interno, usuario y contraseña.
2. Cree un servicio **App**: fuente GitHub `jseborga/erp-servicios`, rama `main`, build **Dockerfile** (ruta `Dockerfile`).
3. **Environment**: `DB_HOST=<host interno del Postgres>`, `DB_PORT=5432`, `DB_USER`, `DB_PASSWORD` y el resto de `.env.example`.
4. **Mounts**: un *Volume* en `/var/lib/odoo`.
5. **Domains**: puerto interno `8069`.
6. **Deploy.**

## Opción C — Cualquier servidor con Docker

```bash
git clone https://github.com/jseborga/erp-servicios.git && cd erp-servicios
cp .env.example .env && nano .env          # cambie las contraseñas
docker compose -f docker-compose.yml -f docker-compose.ports.yml up -d --build
docker compose logs -f odoo                # espere "HTTP service (werkzeug) running"
```

Odoo queda en `127.0.0.1:8069`. Póngalo detrás de un proxy con HTTPS (Nginx, Caddy o Traefik) y no lo exponga directamente a Internet.

## Actualizar el código

1. Haga push al repositorio (o cambie el SHA de un módulo OCA con `scripts/update_oca.sh`).
2. En el entorno ponga `ODOO_UPDATE_MODULES=l10n_bo_spa` (o los módulos cambiados) y redespliegue.
3. Al terminar, deje `ODOO_UPDATE_MODULES` vacío y redespliegue de nuevo, para que no se actualice en cada arranque.

Actualizar `l10n_bo_spa` no vuelve a cargar el plan contable. Si una versión nueva agrega cuentas o impuestos, recárguelo en Contabilidad → Configuración → Ajustes → Localización fiscal → botón **Recargar** (método `reload_template` de Odoo 19). Odoo agrega lo nuevo sin borrar lo existente.

## Copias de seguridad

- **Easypanel**: programe backups de los volúmenes `db-data` y `odoo-data` hacia un almacenamiento externo.
- **Manual**, desde la consola del servicio `odoo`:
  ```bash
  odoo db -c /etc/odoo/odoo.conf dump spa /var/lib/odoo/backup-$(date +%F).zip
  ```
  Este comando incluye los adjuntos (filestore). Copie el archivo fuera del servidor.
- Pruebe restaurar una copia al menos una vez antes de salir a producción.

## Recursos sugeridos

Para pocos usuarios simultáneos: 2 vCPU, 4 GB de RAM y 40 GB de disco. Es una estimación, no una medición: ajústela con el uso real (punto de venta, número de cajeros).

## Seguridad

- Contraseñas largas y distintas para `DB_PASSWORD`, `ODOO_ADMIN_PASSWD` y el administrador.
- El gestor de bases está deshabilitado (`list_db = False`).
- No suba `.env` al repositorio (está en `.gitignore`).
- Active la autenticación en dos pasos para los usuarios administradores (Odoo CE la incluye).
