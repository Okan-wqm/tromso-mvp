#!/usr/bin/env bash
# The farm flow end to end: a database with 40 water devices (farm_seed.py stands in for the devices the Sensors pages
# create for the live run), the device list written from the configuration view (farm-config.sh), the compose
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
DBPW=$(rand); INGPW=$(rand); SIMPW=$(rand); OBSPW=$(rand)
printf '%s\n' "$DBPW" > "$ST/secrets/sensors_ingest_db"; printf '%s\n' "$INGPW" > "$ST/secrets/mqtt_ingest"
printf '%s\n' "$SIMPW" > "$ST/secrets/sim_mqtt"
HASH="docker run --rm -v $(win "$PWD/sensors-ingest/spikes"):/s python:3.12-slim python -I /s/s0f_mosquitto_hash.py line"
{ $HASH ingest "$INGPW"; $HASH simulator "$SIMPW"; $HASH observer "$OBSPW"; } > "$ST/broker-auth/passwd"
printf 'user ingest\ntopic read farm/#\nuser simulator\ntopic write farm/#\ntopic write sim/#\nuser observer\ntopic read farm/#\n' > "$ST/broker-auth/acl"

"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1
docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik "$PG_IMAGE" psql -h db -U balik -d postgres -q \
  -c "DROP DATABASE IF EXISTS $E2E_DB WITH (FORCE)" -c "CREATE DATABASE $E2E_DB" >/dev/null
docker run --rm --network balik-ciftligi_default -v "$REPO:/app" -w /app -e DB_HOST=db -e DB_PORT=5432 -e DB_NAME=$E2E_DB \
  balik-testrunner:latest python manage.py migrate --no-input >/dev/null 2>&1 || { echo "migrate failed"; exit 1; }
sql "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sensors_ingest_e2e') THEN
  CREATE ROLE sensors_ingest_e2e LOGIN IN ROLE sensors_ingest; END IF; END \$\$;
  ALTER ROLE sensors_ingest_e2e PASSWORD '$DBPW'" >/dev/null
docker run --rm -v "$REPO:/w" python:3.12-slim python -I /w/sensors-ingest/simulator/farm_seed.py > "$ST/seed.sql"
docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik -v "$(win "$PWD/$ST"):/s:ro" "$PG_IMAGE" \
  psql -h db -U balik -d $E2E_DB -q -f /s/seed.sql >/dev/null || { echo "seed failed"; exit 1; }
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
  -e BROKER=mqtt://mosquitto:1883 -e MQTT_USER=observer -e MQTT_PASSWORD="$OBSPW" -e NODE_RED=http://node-red:1880 \
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
check "$([ "$DL0" = "$DL1" ] && [ "$DL1" = 0 ] && echo 1)" "nothing dead-lettered ($DL1)"
echo "$FAILS failed"
[ "$FAILS" = 0 ]
