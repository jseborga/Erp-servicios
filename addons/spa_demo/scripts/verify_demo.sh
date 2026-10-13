#!/bin/bash
# Part of ERP Servicios Spa. License LGPL-3.
# Verifica una base con spa_demo instalado: contabilidad, KPIs y estados (odoo shell, solo lectura) e
# ingreso al portal por HTTP con un servidor temporal que se detiene al terminar.
#
# Uso: ODOO="odoo" PYTHON="python3" verify_demo.sh <config> <base> [puerto]
set -u
CONF=$1
DB=$2
PORT=${3:-8069}
ODOO=${ODOO:-odoo}
PYTHON=${PYTHON:-python3}
HERE=$(cd "$(dirname "$0")" && pwd)
STATUS=0

echo "== Verificación de la demo en la base $DB =="
REPORT=$($ODOO shell -c "$CONF" -d "$DB" --log-level=error < "$HERE/verify_shell.py" 2>&1 | grep -E "^(OK|FAIL|RESULT)")
echo "$REPORT"
echo "$REPORT" | grep -q "RESULT OK" || STATUS=1

echo "== Portal por HTTP (servidor temporal en el puerto $PORT) =="
$ODOO -c "$CONF" -d "$DB" --db-filter="^$DB\$" --http-port="$PORT" --workers=0 --max-cron-threads=0 \
  > "/tmp/spa_demo_verify_$DB.log" 2>&1 &
SERVER=$!
for _ in $(seq 1 120); do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/web/login" && break
  sleep 1
done
$PYTHON "$HERE/verify_portal.py" "http://127.0.0.1:$PORT" || STATUS=1
kill $SERVER
wait $SERVER 2>/dev/null
echo "Servidor temporal detenido. Resultado: $([ $STATUS -eq 0 ] && echo OK || echo FAIL)"
exit $STATUS
