#!/bin/bash
# Arranque de ERP Servicios Spa sobre la imagen oficial de Odoo 19.
#
# 1. Genera /etc/odoo/odoo.conf a partir de variables de entorno.
# 2. Espera a PostgreSQL.
# 3. Si la base no existe (y ODOO_INIT=true), la crea en español de Bolivia,
#    con país Bolivia, e instala los módulos de ODOO_INIT_MODULES.
# 4. Opcional: actualiza los módulos de ODOO_UPDATE_MODULES.
# 5. Cede el control al entrypoint oficial de la imagen.
set -euo pipefail

: "${DB_HOST:=db}"
: "${DB_PORT:=5432}"
: "${DB_USER:=odoo}"
: "${DB_PASSWORD:=}"
: "${ODOO_DB:=spa}"
: "${ODOO_ADMIN_PASSWD:=}"
: "${ODOO_INIT:=true}"
: "${ODOO_LANG:=es_BO}"
: "${ODOO_COUNTRY:=BO}"
: "${ODOO_INIT_LOGIN:=admin}"
: "${ODOO_INIT_PASSWORD:=}"
: "${ODOO_INIT_MODULES:=l10n_bo_spa,account_financial_report,account_tax_balance,mis_builder,account_asset_management,account_fiscal_year}"
: "${ODOO_UPDATE_MODULES:=}"
: "${ODOO_WORKERS:=0}"
: "${ODOO_MAX_CRON_THREADS:=1}"
: "${ODOO_PROXY_MODE:=True}"
: "${ODOO_LIMIT_MEMORY_SOFT:=2147483648}"
: "${ODOO_LIMIT_MEMORY_HARD:=2684354560}"
: "${ODOO_LIMIT_TIME_CPU:=600}"
: "${ODOO_LIMIT_TIME_REAL:=1200}"
: "${ODOO_ADDONS_PATH:=/opt/odoo/custom-addons,/opt/odoo/oca-addons}"
: "${ODOO_DATA_DIR:=/var/lib/odoo}"
: "${ODOO_RC:=/etc/odoo/odoo.conf}"
: "${ODOO_BIN:=odoo}"
: "${ODOO_WAIT_FOR_PSQL:=wait-for-psql.py}"
: "${ODOO_ENTRYPOINT:=/entrypoint.sh}"
export ODOO_RC

fail() { echo "entrypoint-spa: ERROR: $*" >&2; exit 1; }
log() { echo "entrypoint-spa: $*"; }

[ -n "$DB_PASSWORD" ] || fail "defina DB_PASSWORD (contraseña del usuario de PostgreSQL)."
[ -n "$ODOO_ADMIN_PASSWD" ] || fail "defina ODOO_ADMIN_PASSWD (contraseña maestra de Odoo)."
case "$ODOO_DB" in
    *[!A-Za-z0-9_-]*|'') fail "ODOO_DB solo admite letras, números, '_' y '-'." ;;
esac

# ---------------------------------------------------------------- configuración
umask 077
cat > "$ODOO_RC" <<EOF
[options]
addons_path = ${ODOO_ADDONS_PATH}
data_dir = ${ODOO_DATA_DIR}
db_host = ${DB_HOST}
db_port = ${DB_PORT}
db_user = ${DB_USER}
db_password = ${DB_PASSWORD}
db_name = ${ODOO_DB}
dbfilter = ^${ODOO_DB}\$
list_db = False
admin_passwd = ${ODOO_ADMIN_PASSWD}
proxy_mode = ${ODOO_PROXY_MODE}
http_interface = 0.0.0.0
workers = ${ODOO_WORKERS}
max_cron_threads = ${ODOO_MAX_CRON_THREADS}
limit_memory_soft = ${ODOO_LIMIT_MEMORY_SOFT}
limit_memory_hard = ${ODOO_LIMIT_MEMORY_HARD}
limit_time_cpu = ${ODOO_LIMIT_TIME_CPU}
limit_time_real = ${ODOO_LIMIT_TIME_REAL}
EOF
umask 022

# Solo para el servidor web normal; otros comandos (shell, scaffold…) pasan directo.
if [ "${1:-odoo}" != "odoo" ] || [ -n "${2:-}" ]; then
    exec "$ODOO_ENTRYPOINT" "$@"
fi

# ------------------------------------------------------------------ PostgreSQL
"$ODOO_WAIT_FOR_PSQL" --db_host "$DB_HOST" --db_port "$DB_PORT" \
    --db_user "$DB_USER" --db_password "$DB_PASSWORD" --timeout=60

export PGPASSWORD="$DB_PASSWORD"
psql_q() {
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$1" -Atqc "$2" 2>/dev/null || true
}

db_exists="$(psql_q postgres "SELECT 1 FROM pg_database WHERE datname = '${ODOO_DB}'")"
modules_csv="${ODOO_INIT_MODULES// /}"

if [ "$ODOO_INIT" = "true" ]; then
    if [ "$db_exists" != "1" ]; then
        [ -n "$ODOO_INIT_PASSWORD" ] || fail "la base '${ODOO_DB}' no existe: defina ODOO_INIT_PASSWORD (contraseña del usuario ${ODOO_INIT_LOGIN})."
        log "creando la base '${ODOO_DB}' (idioma ${ODOO_LANG}, país ${ODOO_COUNTRY})…"
        "$ODOO_BIN" db -c "$ODOO_RC" init "$ODOO_DB" \
            --language "$ODOO_LANG" --country "$ODOO_COUNTRY" \
            --username "$ODOO_INIT_LOGIN" --password "$ODOO_INIT_PASSWORD"
    fi
    spa_state="$(psql_q "$ODOO_DB" "SELECT state FROM ir_module_module WHERE name = 'l10n_bo_spa'")"
    if [ "$spa_state" != "installed" ] && [ -n "$modules_csv" ]; then
        log "instalando módulos: ${modules_csv}"
        # shellcheck disable=SC2086
        "$ODOO_BIN" module install -c "$ODOO_RC" -d "$ODOO_DB" ${modules_csv//,/ }
    fi
fi

if [ -n "${ODOO_UPDATE_MODULES// /}" ]; then
    update_csv="${ODOO_UPDATE_MODULES// /}"
    log "actualizando módulos: ${update_csv}"
    # shellcheck disable=SC2086
    "$ODOO_BIN" module upgrade -c "$ODOO_RC" -d "$ODOO_DB" ${update_csv//,/ }
fi

unset PGPASSWORD
exec "$ODOO_ENTRYPOINT" "$@"
