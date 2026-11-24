#!/usr/bin/env bash
# Many sources (owner requirement: about 500 msg/s in total from many devices at once): N devices (default 500),
# each its own MQTT connection, credential and topic, 1 msg/s, three payload formats, some clocks 10 min ahead, two
# brokers and two Connection rows in the ingest, 50 devices dropping out together and returning with a backlog.
# Asserts that every message and every sample is accounted for, per device and per channel, and reports latency,
# ingest CPU and memory, broker memory and connections.
#   bench/multisource.sh [SECONDS=1800] [N=500]
# Own database sensors_ms, own containers ms-*; removed at the end (KEEP=1 keeps them).
set -uo pipefail
cd "$(dirname "$0")/../.."
export MSYS_NO_PATHCONV=1
win() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
REPO=$(win "$PWD")
# The Django image that migrates the schema: the test runner's, as scripts/testrunner/image.sh names it (the one name,
# tests/run.sh's and CI's too), built when missing; no server starts without the water-chemistry core in it.
DJANGO_IMAGE=${DJANGO_IMAGE:-$(sh scripts/testrunner/image.sh build)}
SECS=${1:-1800}; N=${2:-500}
OUTAGE_AT=$(( SECS * 2 / 3 )); OUTAGE_S=${OUTAGE_S:-120}
ST=sensors-ingest/bench/.state/ms
DB=sensors_ms
PG_IMAGE=timescale/timescaledb:2.32.1-pg17@sha256:2f5e6969faa5cd7f4b075d65f124e30dc50d456b7b807e5c1acd9d51ba7df51c
MOSQ=eclipse-mosquitto:2.0.23@sha256:6a332cc7a8dbe011cbc076180cbb76b37c6f0f55809682ea08e7980ef0112ad9
FAILS=0
pass() { echo "PASS: $*"; echo "PASS: $*" >> "$ST/results.txt"; }
fail() { echo "FAIL: $*"; echo "FAIL: $*" >> "$ST/results.txt"; FAILS=$((FAILS + 1)); }
check() { if [ "$1" = 1 ]; then pass "$2"; else fail "$2"; fi; }
note() { echo "  $*"; echo "  $*" >> "$ST/results.txt"; }
sql() { docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik "$PG_IMAGE" psql -h db -U balik -d "$DB" -Atq -c "$1"; }
cleanup() {
  [ "${KEEP:-0}" = 1 ] && return
  docker rm -f -v ms-ingest ms-broker1 ms-broker2 ms-pub >/dev/null 2>&1
  docker network rm ms-net >/dev/null 2>&1
}
trap cleanup EXIT
healthz() { docker exec ms-ingest bash -c 'exec 3<>/dev/tcp/127.0.0.1/8080; printf "GET /healthz HTTP/1.0\r\n\r\n" >&3; tail -n1 <&3'; }
connected() { docker run --rm --network ms-net "$MOSQ" mosquitto_sub -h "$1" -u monitor -P "$MONPW" -C 1 -W 15 \
  -t '$SYS/broker/clients/connected' 2>/dev/null; }

rm -rf "$ST"; mkdir -p "$ST/secrets"
rand() { head -c 18 /dev/urandom | base64 | tr -d '/+='; }
DBPW=$(rand); MONPW=$(rand)
printf '%s\n' "$DBPW" > "$ST/secrets/sensors_ingest_db"
printf '%s\n' "$(rand)" > "$ST/secrets/mqtt_ingest"
printf '%s\n' "$MONPW" > "$ST/monitor_pw"
cp "$ST/secrets/mqtt_ingest" "$ST/mqtt_ingest"
docker run --rm -v "$REPO:/w" python:3.12-slim python -I /w/sensors-ingest/bench/multisource_setup.py \
  /w/$ST "$N" || exit 1

cleanup
docker network create ms-net >/dev/null
docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik "$PG_IMAGE" psql -h db -U balik -d postgres -q \
  -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)" -c "CREATE DATABASE $DB" >/dev/null
docker run --rm --network balik-ciftligi_default -v "$REPO:/app" -w /app -e DB_HOST=db -e DB_PORT=5432 -e DB_NAME=$DB \
  "$DJANGO_IMAGE" python manage.py migrate --no-input >/dev/null 2>&1 || { echo "migrate failed"; exit 1; }
sql "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sensors_ingest_e2e') THEN
  CREATE ROLE sensors_ingest_e2e LOGIN IN ROLE sensors_ingest; END IF; END \$\$;
  ALTER ROLE sensors_ingest_e2e PASSWORD '$DBPW'" >/dev/null
docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik -v "$(win "$PWD/$ST"):/s:ro" "$PG_IMAGE" \
  psql -h db -U balik -d $DB -q -f /s/seed.sql >/dev/null || { echo "seed failed"; exit 1; }

docker build -q -t sensors-ingest:bench sensors-ingest >/dev/null || exit 1
for b in ms-broker1 ms-broker2; do
  docker run -d --name $b --network ms-net -v "$REPO/sensors-ingest/mosquitto:/mosquitto/config:ro" \
    -v "$(win "$PWD/$ST/$b"):/mosquitto/auth" --tmpfs /mosquitto/data --entrypoint sh "$MOSQ" \
    /mosquitto/config/entrypoint.sh >/dev/null
done
docker run -d --name ms-ingest --network ms-net -v "$(win "$PWD/$ST/secrets"):/run/secrets:ro" \
  -e INGEST_DB="host=db port=5432 dbname=$DB user=sensors_ingest_e2e" -e RUST_LOG=warn sensors-ingest:bench >/dev/null
docker network connect balik-ciftligi_default ms-ingest
for _ in $(seq 1 60); do healthz 2>/dev/null | grep -q '"status":"ok"' && break; sleep 2; done
check "$(healthz | grep -q '"status":"ok"' && echo 1)" "ingest healthy with two broker connections"

# resource samples every 30 s: ingest and broker memory and CPU, connected clients
( while true; do
    echo "$(date +%H:%M:%S) $(docker stats --no-stream --format '{{.Name}}={{.MemUsage}}@{{.CPUPerc}}' ms-ingest ms-broker1 ms-broker2 | tr -d ' ' | tr '\n' ' ') clients1=$(connected ms-broker1) clients2=$(connected ms-broker2)"
    sleep 30
  done ) > "$ST/samples.txt" 2>/dev/null &
SAMPLER=$!

docker create --name ms-pub --network ms-net -v "$REPO:/w" -v si-cargo:/usr/local/cargo/registry -v si-target:/t \
  -e DEVICES=/w/$ST/devices.txt -e SECONDS="$SECS" -e OUTAGE_AT="$OUTAGE_AT" -e OUTAGE_S="$OUTAGE_S" \
  -e STATS_FILE=/w/$ST/stats.txt -e DB="host=db port=5432 user=balik password=balik dbname=$DB" \
  sensors-ingest-dev:1.88 /t/target/release/examples/multisource >/dev/null
docker network connect balik-ciftligi_default ms-pub
docker start ms-pub >/dev/null
docker wait ms-pub >/dev/null
PUB=$(docker logs ms-pub 2>&1 | tail -1)
kill $SAMPLER 2>/dev/null
sleep 20
note "publisher: $PUB"

# ---- accounting -----------------------------------------------------------------------------------------------
docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik -v "$(win "$PWD/$ST"):/s:ro" "$PG_IMAGE" \
  psql -h db -U balik -d $DB -Atq -c "CREATE TABLE ms_stats(i int, sent bigint, acked bigint)" \
  -c "\copy ms_stats FROM '/s/stats.txt' DELIMITER ' '" >/dev/null
SENT=$(sql "SELECT sum(sent) FROM ms_stats"); ACKED=$(sql "SELECT sum(acked) FROM ms_stats")
check "$([ "$SENT" = "$ACKED" ] && [ "$SENT" -gt 0 ] && echo 1)" "every message acknowledged by its broker: $ACKED of $SENT"
BAD=$(sql "SELECT count(*) FROM ms_stats s JOIN sensors_device d ON d.code = 'MS-' || s.i
  LEFT JOIN sensors_device_state x ON x.device_id = d.id
  WHERE coalesce(x.accepted_total, 0) + coalesce(x.dead_total, 0) + coalesce(x.ignored_total, 0) <> s.acked")
check "$([ "$BAD" = 0 ] && echo 1)" "per device: acknowledged = accepted + dead-lettered + ignored ($BAD of $N devices differ)"
check "$(sql "SELECT (coalesce(sum(dead_total), 0) = 0)::int FROM sensors_device_state")" "nothing dead-lettered"
BADCH=$(sql "SELECT count(*) FROM sensors_channel c JOIN sensors_device d ON d.id = c.device_id
  JOIN ms_stats s ON d.code = 'MS-' || s.i
  LEFT JOIN sensors_channel_state cs ON cs.channel_no = c.channel_no
  WHERE coalesce((SELECT sum(n) FROM sensors_reading r WHERE r.channel_no = c.channel_no), 0) + coalesce(cs.run_n, 0) <> s.acked")
check "$([ "$BADCH" = 0 ] && echo 1)" "per channel: samples in rows + open run = messages sent ($BADCH of $(sql "SELECT count(*) FROM sensors_channel") channels differ)"
note "rows $(sql "SELECT count(*) FROM sensors_reading") for $(sql "SELECT sum(s.acked * (SELECT count(*) FROM sensors_channel c WHERE c.device_id = d.id)) FROM ms_stats s JOIN sensors_device d ON d.code = 'MS-' || s.i") samples (deadband suppression), late rows $(sql "SELECT count(*) FROM sensors_reading WHERE quality & 8 <> 0"), duplicates ignored $(sql "SELECT sum(ignored_total) FROM sensors_device_state")"
SKEW=$(sql "SELECT count(DISTINCT d.id) FROM sensors_device d JOIN sensors_channel c ON c.device_id = d.id
  JOIN sensors_reading r ON r.channel_no = c.channel_no AND r.quality & 4 <> 0 WHERE d.note LIKE '%skew%'")
SKEWN=$(sql "SELECT count(*) FROM sensors_device WHERE note LIKE '%skew%'")
check "$([ "$SKEW" = "$SKEWN" ] && echo 1)" "clocks 10 min ahead: stored at receive time, flagged, on all $SKEWN such devices"
check "$(sql "SELECT (count(*) = 0)::int FROM sensors_channel_state WHERE high_ts > now() + interval '61 s'")" "no channel's newest time in the future"
GAPS=$(sql "SELECT count(*) FROM (SELECT ts - lag(ts) OVER (PARTITION BY r.channel_no ORDER BY ts) AS g
  FROM sensors_reading r JOIN sensors_channel c ON c.channel_no = r.channel_no JOIN sensors_device d ON d.id = c.device_id
  WHERE c.reduction = 'all' AND d.note LIKE '%outage%' AND d.note NOT LIKE '%skew%') x WHERE g > interval '1.9 s'")
check "$([ "$GAPS" = 0 ] && echo 1)" "50 devices out for ${OUTAGE_S} s, back with their backlog: every second stored at its device time ($GAPS gaps)"
H=$(healthz)
check "$(echo "$H" | grep -q '"qos0_dropped":0' && echo "$H" | grep -q '"poison":0' && echo 1)" "no QoS 0 drop, no poison"
note "healthz: $H"
note "resources (time ingest/broker1/broker2 memory/cpu, connected clients):"
sed 's/^/    /' "$ST/samples.txt" | awk 'NR % 6 == 1' >> "$ST/results.txt"
MAX1=$(grep -o 'clients1=[0-9]*' "$ST/samples.txt" | cut -d= -f2 | sort -n | tail -1)
MAX2=$(grep -o 'clients2=[0-9]*' "$ST/samples.txt" | cut -d= -f2 | sort -n | tail -1)
check "$([ "${MAX1:-0}" -ge $((N - 100)) ] && [ "${MAX2:-0}" -ge 100 ] && echo 1)" "connections at the brokers: up to $MAX1 and $MAX2 clients (devices, ingest, monitor)"
PEAK=$(grep -o 'ms-ingest=[0-9.]*MiB' "$ST/samples.txt" | grep -o '[0-9.]*' | sort -n | tail -1)
CPU=$(grep -o 'ms-ingest=[^ ]*' "$ST/samples.txt" | sed 's#.*@##; s/%//' | sort -n | awk '{a[NR]=$1} END {print "median " a[int((NR+1)/2)] "%, max " a[NR] "% of one core"}')
note "ingest peak memory ${PEAK} MiB, CPU $CPU; brokers peak $(grep -o 'ms-broker1=[0-9.]*MiB' "$ST/samples.txt" | grep -o '[0-9.]*' | sort -n | tail -1) / $(grep -o 'ms-broker2=[0-9.]*MiB' "$ST/samples.txt" | grep -o '[0-9.]*' | sort -n | tail -1) MiB"
echo "$FAILS failed" | tee -a "$ST/results.txt"
[ "$FAILS" = 0 ]
