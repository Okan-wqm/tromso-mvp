#!/usr/bin/env bash
# The farm flow end to end on its OWN database: 2 systems and 38 tanks (farm_fixture.py), the demo sensors made by
# Django (manage.py sensors_demo_setup, sensor_broker_sync), the device list written from the configuration view
# (farm-config.sh), the compose
# services (broker, ingest, Node-RED) under the project sensors-farm, and farm-check.js on the MQTT side. Proves for
# each parameter code: values sent in the window = samples the database accounts for (rows + open runs), and nothing
# dead-lettered. Own database sensors_farm; everything removed at the end (KEEP=1 keeps it).
#   simulator/farm-check.sh [SECONDS=60]
set -uo pipefail
cd "$(dirname "$0")/../.."
export MSYS_NO_PATHCONV=1
win() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
REPO=$(win "$PWD")
SECS=${1:-60}
export E2E_STATE=./sensors-ingest/simulator/.farmcheck E2E_DB=sensors_farm
ST=sensors-ingest/simulator/.farmcheck
PG_IMAGE=timescale/timescaledb:2.17.2-pg17
NODERED=nodered/node-red:4.0.9@sha256:0b295b3a14c512548567ca99db631bc37b23bfc79fd009ee8248a610fafdb4b5
COMPOSE=(docker compose -p sensors-farm -f docker-compose.yml -f sensors-ingest/e2e/compose.e2e.yml --profile sensors)
FAILS=0
check() { if [ "$1" = 1 ]; then echo "PASS: $2"; else echo "FAIL: $2"; FAILS=$((FAILS + 1)); fi; }
sql() { docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik "$PG_IMAGE" psql -h db -U balik -d $E2E_DB -Atq -c "$1"; }
cleanup() {
  [ "${KEEP:-0}" = 1 ] && return
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1
  docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik "$PG_IMAGE" psql -h db -U balik -d postgres -q \
    -c "DROP DATABASE IF EXISTS $E2E_DB WITH (FORCE)" >/dev/null 2>&1
}
trap cleanup EXIT

rm -rf "$ST"; mkdir -p "$ST/secrets" "$ST/broker-auth" "$ST/farm"
rand() { head -c 18 /dev/urandom | base64 | tr -d '/+='; }
DBPW=$(rand); INGPW=$(rand); SIMPW=$(rand)
printf '%s\n' "$DBPW" > "$ST/secrets/sensors_ingest_db"; printf '%s\n' "$INGPW" > "$ST/secrets/mqtt_ingest"
printf '%s\n' "$SIMPW" > "$ST/secrets/sim_mqtt"
# the passwd lines operations keep themselves (sensor_broker_sync --extra): the ingest, and the A2 field simulator
HASH="docker run --rm -v $(win "$PWD/sensors-ingest/spikes"):/s python:3.12-slim python -I /s/s0f_mosquitto_hash.py line"
{ $HASH ingest "$INGPW"; $HASH simulator "$SIMPW"; } > "$ST/extra_passwd"

"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1
docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik "$PG_IMAGE" psql -h db -U balik -d postgres -q \
  -c "DROP DATABASE IF EXISTS $E2E_DB WITH (FORCE)" -c "CREATE DATABASE $E2E_DB" >/dev/null
docker run --rm --network balik-ciftligi_default -v "$REPO:/app" -w /app -e DB_HOST=db -e DB_PORT=5432 -e DB_NAME=$E2E_DB \
  balik-testrunner:latest python manage.py migrate --no-input >/dev/null 2>&1 || { echo "migrate failed"; exit 1; }
sql "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sensors_ingest_e2e') THEN
  CREATE ROLE sensors_ingest_e2e LOGIN IN ROLE sensors_ingest; END IF; END \$\$;
  ALTER ROLE sensors_ingest_e2e PASSWORD '$DBPW'" >/dev/null
# the farm and its demo sensors, as the live run makes them: tanks and systems, then Django's own setup and broker sync
DJ=(docker run --rm --network balik-ciftligi_default -v "$REPO:/app" -w /app -e DB_HOST=db -e DB_PORT=5432
  -e DB_NAME=$E2E_DB -e SENSORS_BROKER_AUTH_DIR=/app/$ST/broker-auth balik-testrunner:latest)
"${DJ[@]}" python manage.py shell -c "exec(open('sensors-ingest/simulator/farm_fixture.py').read())" || exit 1
"${DJ[@]}" python manage.py sensors_demo_setup --confirm --secret-file /app/$ST/secrets/sim_farm.django || exit 1
"${DJ[@]}" python manage.py sensor_broker_sync --extra /app/$ST/extra_passwd || exit 1
# the secret is written mode 600 inside the Django container; the Node-RED container runs as uid 1000 and must read
# it: a fresh copy made here has the ordinary mode
cat "$ST/secrets/sim_farm.django" > "$ST/secrets/sim_farm"
bash sensors-ingest/simulator/farm-config.sh $E2E_DB "$ST/farm/farm-devices.json"

"${COMPOSE[@]}" build -q sensors-ingest || exit 1
"${COMPOSE[@]}" up -d --no-deps mosquitto sensors-ingest node-red >/dev/null 2>&1 || exit 1
ING=$("${COMPOSE[@]}" ps -q sensors-ingest); NR=$("${COMPOSE[@]}" ps -q node-red)
for _ in $(seq 1 90); do [ "$(docker inspect -f '{{.State.Health.Status}}' "$ING")" = healthy ] && break; sleep 2; done
for _ in $(seq 1 60); do docker logs "$NR" 2>&1 | grep -q "Started flows" && break; sleep 2; done
check "$([ "$(docker inspect -f '{{.State.Health.Status}}' "$ING")" = healthy ] && echo 1)" "ingest healthy"

totals() { sql "SELECT c.quantity || ' ' || (coalesce(sum((SELECT sum(n) FROM sensors_reading r WHERE r.channel_no = c.channel_no)), 0)
  + coalesce(sum(cs.run_n), 0)) FROM sensors_channel c LEFT JOIN sensors_channel_state cs ON cs.channel_no = c.channel_no
  GROUP BY c.quantity ORDER BY 1"; }
LOG="$ST/check.log"
docker run --rm --network sensors-farm_e2e -v "$(win "$PWD/sensors-ingest/simulator"):/sim:ro" -v "$(win "$PWD/$ST/farm"):/farm:ro" \
  -e BROKER=mqtt://mosquitto:1883 -e MQTT_USER=ingest -e MQTT_PASSWORD="$INGPW" -e NODE_RED=http://node-red:1880 \
  -e FARM_FILE=/farm/farm-devices.json -e SECONDS="$SECS" --entrypoint node "$NODERED" /sim/farm-check.js > "$LOG" 2>&1 &
CHK=$!
until grep -q "MARK before" "$LOG" || ! kill -0 $CHK 2>/dev/null; do sleep 0.5; done
totals > "$ST/before.txt"; DL0=$(sql "SELECT count(*) FROM sensors_dead_letter")
until grep -q "MARK after" "$LOG" || ! kill -0 $CHK 2>/dev/null; do sleep 1; done
sleep 3
totals > "$ST/after.txt"; DL1=$(sql "SELECT count(*) FROM sensors_dead_letter")
wait $CHK; RC=$?
grep -E '^(PASS|FAIL)' "$LOG"
check "$([ $RC = 0 ] && echo 1)" "MQTT side (farm-check.js)"
COUNTS=$(grep '^COUNTS ' "$LOG" | sed 's/^COUNTS //')
echo "parameter            sent   accounted (rows + open runs, window delta)"
for q in $(echo "$COUNTS" | grep -o '"[a-z0-9_]*"' | tr -d '"'); do
  SENT=$(echo "$COUNTS" | grep -o "\"$q\":[0-9]*" | cut -d: -f2)
  B=$(grep "^$q " "$ST/before.txt" | cut -d' ' -f2); A=$(grep "^$q " "$ST/after.txt" | cut -d' ' -f2)
  D=$(( ${A:-0} - ${B:-0} ))
  printf '%-20s %6s %6s\n' "$q" "$SENT" "$D"
  check "$([ "$SENT" = "$D" ] && echo 1)" "$q: every value sent is stored or suppressed ($D of $SENT)"
done
for q in temperature_c oxygen_mg_l oxygen_saturation_pct ph alkalinity_mg_l co2_mg_l tan_mg_l nitrite_n_mg_l nitrate_n_mg_l tgp_pct salinity_ppt turbidity_ntu; do
  R=$(sql "SELECT count(*) FROM sensors_reading r JOIN sensors_channel c ON c.channel_no = r.channel_no WHERE c.quantity = '$q'")
  check "$([ "${R:-0}" -gt 0 ] && echo 1)" "$q: $R rows stored"
done
check "$([ "$DL0" = "$DL1" ] && [ "$DL1" = 0 ] && echo 1)" "nothing dead-lettered ($DL1)"
echo "$FAILS failed"
[ "$FAILS" = 0 ]
