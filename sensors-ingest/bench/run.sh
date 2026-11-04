#!/usr/bin/env bash
# S10 extreme bench: the production ingest image and broker configuration against the database sensors_bench of the
# existing database container. One heavy phase at a time (the machine is shared):
#   bench/run.sh throughput [RATE] [SECONDS]   QoS 1 at RATE msg/s (default 10000) over 100 devices x 5 channels
#   bench/run.sh brokerkill                    broker SIGKILL under load, acknowledged-but-lost messages counted
#   bench/run.sh poison                        50 000 distinct garbage messages beside a normal stream
# Results are appended to bench/.state/results.txt. Containers are removed at the end (KEEP=1 keeps them).
set -uo pipefail
cd "$(dirname "$0")/../.."
export MSYS_NO_PATHCONV=1
win() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
REPO=$(win "$PWD")
STATE=sensors-ingest/bench/.state
DB=sensors_bench
NET=sensors-bench
PG_IMAGE=timescale/timescaledb:2.17.2-pg17
MOSQ=eclipse-mosquitto:2.0.20@sha256:21421af7b32bf9ce508e9090c8eb13bb81f410ca778dc205506180a6f862d0eb
PHASE=${1:-throughput}
sql() { docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik "$PG_IMAGE" psql -h db -U balik -d "$DB" -Atq -c "$1"; }
out() { echo "$*"; echo "[$PHASE] $*" >> "$STATE/results.txt"; }
cleanup() {
  [ "${KEEP:-0}" = 1 ] && return
  docker rm -f bench-ingest bench-broker >/dev/null 2>&1
  docker network rm "$NET" >/dev/null 2>&1
  docker volume rm bench-broker-data >/dev/null 2>&1
}
trap cleanup EXIT
publish() { # env assignments as arguments, e.g. RATE=10000 SECONDS=60
  docker run --rm --network "$NET" -v "$REPO:/w" -v si-cargo:/usr/local/cargo/registry -v si-target:/t \
    -e CARGO_TARGET_DIR=/t/target -e BROKER=bench-broker -e MQTT_USER=bench -e MQTT_PASSWORD="$BPW" \
    $(for kv in "$@"; do printf -- '-e %s ' "$kv"; done) -w /w/sensors-ingest sensors-ingest-dev:1.88 \
    /t/target/release/examples/bench_publish
}
healthz() { docker exec bench-ingest bash -c 'exec 3<>/dev/tcp/127.0.0.1/8080; printf "GET /healthz HTTP/1.0\r\n\r\n" >&3; tail -n1 <&3'; }
accepted() { sql "SELECT coalesce(sum(accepted_total + dead_total), 0) FROM sensors_device_state"; }

mkdir -p "$STATE/secrets" "$STATE/auth"
rand() { head -c 18 /dev/urandom | base64 | tr -d '/+='; }
DBPW=$(rand); IPW=$(rand); BPW=$(rand)
printf '%s\n' "$DBPW" > "$STATE/secrets/sensors_ingest_db"
printf '%s\n' "$IPW" > "$STATE/secrets/mqtt_ingest"
HASH="docker run --rm -v $(win "$PWD/sensors-ingest/spikes"):/s python:3.12-slim python -I /s/s0f_mosquitto_hash.py line"
{ $HASH ingest "$IPW"; $HASH bench "$BPW"; } > "$STATE/auth/passwd"
printf 'user ingest\ntopic read bench/#\nuser bench\ntopic write bench/#\n' > "$STATE/auth/acl"

cleanup
docker network create "$NET" >/dev/null
docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik "$PG_IMAGE" psql -h db -U balik -d postgres -q \
  -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)" -c "CREATE DATABASE $DB" >/dev/null
docker run --rm --network balik-ciftligi_default -v "$REPO:/app" -w /app -e DB_HOST=db -e DB_PORT=5432 -e DB_NAME=$DB \
  balik-testrunner:latest python manage.py migrate --no-input >/dev/null 2>&1 || { echo "migrate failed"; exit 1; }
sql "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sensors_ingest_e2e') THEN
  CREATE ROLE sensors_ingest_e2e LOGIN IN ROLE sensors_ingest; END IF; END \$\$;
  ALTER ROLE sensors_ingest_e2e PASSWORD '$DBPW'" >/dev/null
docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik -v "$(win "$PWD/sensors-ingest/bench"):/b:ro" "$PG_IMAGE" \
  psql -h db -U balik -d $DB -q -f /b/seed.sql >/dev/null || { echo "seed failed"; exit 1; }

docker build -q -t sensors-ingest:bench sensors-ingest >/dev/null || exit 1
docker run -d --name bench-broker --network "$NET" -v "$REPO/sensors-ingest/mosquitto:/mosquitto/config:ro" \
  -v "$(win "$PWD/$STATE/auth"):/mosquitto/auth" -v bench-broker-data:/mosquitto/data --entrypoint sh "$MOSQ" \
  /mosquitto/config/entrypoint.sh >/dev/null
docker run -d --name bench-ingest --network "$NET" -v "$(win "$PWD/$STATE/secrets"):/run/secrets:ro" \
  -e INGEST_DB="host=db port=5432 dbname=$DB user=sensors_ingest_e2e" -e RUST_LOG=warn sensors-ingest:bench >/dev/null
docker network connect balik-ciftligi_default bench-ingest
for _ in $(seq 1 60); do healthz 2>/dev/null | grep -q '"status":"ok"' && break; sleep 2; done
healthz | grep -q '"status":"ok"' || { echo "ingest not healthy"; docker logs bench-ingest | tail; exit 1; }

case "$PHASE" in
throughput)
  RATE=${2:-10000}; SECS=${3:-120}
  WAL0=$(sql "SELECT wal_bytes FROM pg_stat_wal"); A0=$(accepted)
  ( for _ in $(seq 1 $((SECS / 5 + 30))); do docker stats --no-stream --format '{{.MemUsage}} {{.CPUPerc}}' bench-ingest; sleep 4; done ) > "$STATE/stats.txt" 2>/dev/null &
  STATS=$!
  START=$(date +%s)
  P=$(publish RATE="$RATE" SECONDS="$SECS" DEVICES=100 CHANNELS=5 CLIENT_ID=bench-pub)
  PUB_END=$(date +%s)
  SENT=$(echo "$P" | sed -n 's/.*sent=\([0-9]*\).*/\1/p')
  for _ in $(seq 1 600); do [ "$(( $(accepted) - A0 ))" -ge "$SENT" ] && break; sleep 1; done
  DONE=$(date +%s); kill $STATS 2>/dev/null
  WAL1=$(sql "SELECT wal_bytes FROM pg_stat_wal")
  out "publisher: $P"
  out "messages stored (accepted on their device): $(( $(accepted) - A0 )) of $SENT; ingest done $(( DONE - START )) s after start, $(( DONE - PUB_END )) s after the last publish"
  out "rows $(sql "SELECT count(*) FROM sensors_reading") for $((SENT * 5)) samples; samples accounted $(sql "SELECT sum(n) FROM sensors_reading") in rows + $(sql "SELECT sum(run_n) FROM sensors_channel_state") in open runs"
  out "WAL $(( (WAL1 - WAL0) / 1048576 )) MiB in $(( DONE - START )) s (cluster-wide), $(( (WAL1 - WAL0) / 1048576 / (DONE - START + 1) )) MiB/s"
  out "healthz: $(healthz)"
  out "ingest memory/cpu samples: $(tr '\n' ';' < "$STATE/stats.txt" | cut -c1-400)"
  ;;
brokerkill)
  ( sleep 10; docker kill -s KILL bench-broker >/dev/null; sleep 3; docker start bench-broker >/dev/null ) &
  P=$(publish RATE=500 SECONDS=40 DEVICES=1 CHANNELS=1 TOPIC_PREFIX=bench/kill- CLIENT_ID=bench-kill ACKED_FILE=/w/sensors-ingest/bench/.state/acked.txt)
  wait
  sleep 15
  BASE=$(echo "$P" | sed -n 's/.*base_ms=\([0-9]*\).*/\1/p'); STEP=$(echo "$P" | sed -n 's/.*step_ms=\([0-9]*\).*/\1/p')
  docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik -v "$(win "$PWD/$STATE"):/s:ro" "$PG_IMAGE" \
    psql -h db -U balik -d $DB -Atq -c "CREATE TEMP TABLE acked(d int, s bigint)" -c "\copy acked FROM '/s/acked.txt' DELIMITER ' '" \
    -c "SELECT count(*) || ' acknowledged by the broker, ' || count(*) FILTER (WHERE r.ts IS NULL) || ' of them never stored' FROM acked a LEFT JOIN sensors_reading r ON r.channel_no = (SELECT channel_no FROM sensors_channel WHERE code = 'K0') AND r.ts = to_timestamp(($BASE + a.s * $STEP) / 1000.0)" > "$STATE/kill.txt"
  out "publisher: $(echo "$P" | tail -1)"
  out "broker SIGKILL 10 s into a 500 msg/s QoS 1 stream, restarted 3 s later: $(cat "$STATE/kill.txt")"
  out "healthz: $(healthz)"
  ;;
poison)
  A0=$(accepted)
  publish RATE=2000 SECONDS=25 DEVICES=10 GARBAGE=1 CLIENT_ID=bench-poison > "$STATE/poison.txt" &
  N=$(publish RATE=1000 SECONDS=25 DEVICES=10 CHANNELS=5 CLIENT_ID=bench-normal)
  wait
  sleep 10
  out "garbage publisher: $(tail -1 "$STATE/poison.txt"); normal publisher: $N"
  out "dead letters: $(sql "SELECT count(*) || ' rows, ' || sum(count) || ' messages, ' || count(*) FILTER (WHERE payload_sha256 = 'overflow') || ' overflow rows' FROM sensors_dead_letter")"
  out "normal stream beside the flood: $(sql "SELECT sum(accepted_total) FROM sensors_device_state") messages accepted of 25000"
  out "healthz: $(healthz)"
  ;;
esac
