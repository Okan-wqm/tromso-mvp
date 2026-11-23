#!/usr/bin/env bash
# End to end (owner amendment A2) and the failure drills of S10: the compose services of the profile `sensors`
# (Mosquitto, the ingest image, the Node-RED field simulator) under the project name sensors-e2e, writing to the
# database sensors_e2e of the existing database container. Prints PASS/FAIL and the measured numbers, and writes them
# to e2e/.state/results.txt. Never touches the dev database `balik`; removes its containers at the end
# (KEEP=1 keeps them).
set -uo pipefail
cd "$(dirname "$0")/../.."
export MSYS_NO_PATHCONV=1
win() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
REPO=$(win "$PWD")
# The Django image that migrates the schema: the test runner's, as scripts/testrunner/image.sh names it (the one name,
# tests/run.sh's and CI's too), built when missing; no server starts without the water-chemistry core in it.
DJANGO_IMAGE=${DJANGO_IMAGE:-$(sh scripts/testrunner/image.sh build)}
STATE=sensors-ingest/e2e/.state
DB=sensors_e2e
PG_IMAGE=timescale/timescaledb:2.17.2-pg17
NODERED=nodered/node-red:4.0.9@sha256:0b295b3a14c512548567ca99db631bc37b23bfc79fd009ee8248a610fafdb4b5
COMPOSE=(docker compose -p sensors-e2e -f docker-compose.yml -f sensors-ingest/e2e/compose.e2e.yml --profile sensors)
FAILS=0
RESULTS=()

pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; FAILS=$((FAILS + 1)); }
check() { if [ "$1" = 1 ]; then pass "$2"; else fail "$2"; fi; }
note() { echo "  $*"; RESULTS+=("$*"); }
sql() { docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik "$PG_IMAGE" psql -h db -U balik -d "$DB" -Atq -c "$1"; }
press() { docker run --rm --network sensors-e2e_e2e --entrypoint node "$NODERED" -e \
  "fetch('http://node-red:1880/inject/$1',{method:'POST'}).then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"; }
ch() { sql "SELECT channel_no FROM sensors_channel WHERE code = '$1'"; }
now() { sql "SELECT now()"; }
# gaps of more than 1.5 s between clean rows of an `all` channel in [from, to): count, longest, rows
gaps() { sql "SELECT count(*) FILTER (WHERE d > interval '1.5 s'), coalesce(extract(epoch FROM max(d)), 0)::numeric(10,1), count(*)
  FROM (SELECT ts - lag(ts) OVER (ORDER BY ts) AS d FROM sensors_reading WHERE channel_no = $1 AND ts >= '$2' AND ts < '$3'
  AND quality & 8 = 0) s"; }
late_rows() { sql "SELECT count(*) FROM sensors_reading WHERE quality & 8 <> 0"; }
cleanup() { [ "${KEEP:-0}" = 1 ] || "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1; }
trap cleanup EXIT

echo "== setup"
mkdir -p "$STATE/secrets" "$STATE/broker-auth"
rand() { head -c 18 /dev/urandom | base64 | tr -d '/+='; }
DBPW=$(rand); INGPW=$(rand); SIMPW=$(rand)
printf '%s\n' "$DBPW" > "$STATE/secrets/sensors_ingest_db"
printf '%s\n' "$INGPW" > "$STATE/secrets/mqtt_ingest"
printf '%s\n' "$SIMPW" > "$STATE/secrets/sim_mqtt"
: > "$STATE/secrets/sim_farm"   # no farm in this run: the farm tab idles
# what manage.py sensor_broker_sync writes (spike S0f: the $7$ lines from hashlib)
HASH="docker run --rm -v $(win "$PWD/sensors-ingest/spikes"):/s python:3.12-slim python -I /s/s0f_mosquitto_hash.py line"
{ $HASH ingest "$INGPW"; $HASH simulator "$SIMPW"; } > "$STATE/broker-auth/passwd"
printf 'user ingest\ntopic read sim/#\nuser simulator\ntopic write sim/#\n' > "$STATE/broker-auth/acl"
"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1
docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik "$PG_IMAGE" psql -h db -U balik -d postgres -q \
  -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)" -c "CREATE DATABASE $DB" >/dev/null
docker run --rm --network balik-ciftligi_default -v "$REPO:/app" -w /app -e DB_HOST=db -e DB_PORT=5432 -e DB_NAME=$DB \
  "$DJANGO_IMAGE" python manage.py migrate --no-input >/dev/null || { echo "migrate failed"; exit 1; }
sql "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sensors_ingest_e2e') THEN
  CREATE ROLE sensors_ingest_e2e LOGIN IN ROLE sensors_ingest; END IF; END \$\$;
  ALTER ROLE sensors_ingest_e2e PASSWORD '$DBPW'" >/dev/null
docker run --rm --network balik-ciftligi_default -e PGPASSWORD=balik -v "$(win "$PWD/sensors-ingest/e2e"):/e2e:ro" "$PG_IMAGE" \
  psql -h db -U balik -d $DB -q -f /e2e/seed.sql >/dev/null || { echo "seed failed"; exit 1; }

echo "== build and start"
"${COMPOSE[@]}" build -q sensors-ingest || exit 1
"${COMPOSE[@]}" up -d --no-deps mosquitto sensors-ingest node-red >/dev/null 2>&1 || { "${COMPOSE[@]}" logs | tail -30; exit 1; }
ING=$("${COMPOSE[@]}" ps -q sensors-ingest)
for _ in $(seq 1 90); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$ING")" = healthy ] && break
  sleep 2
done
check "$([ "$(docker inspect -f '{{.State.Health.Status}}' "$ING")" = healthy ] && echo 1)" "ingest container healthy (/healthz: database, lock, broker)"
O2=$(ch O2-SUMP); DO=$(ch DO); TEMP=$(ch TEMP-IN); FLOW=$(ch FLOW)

# the simulator may start later than the ingest on a loaded machine: the window opens once the field is publishing
for _ in $(seq 1 60); do [ "$(sql "SELECT count(*) FROM sensors_reading WHERE channel_no = $O2")" -gt 5 ] && break; sleep 3; done
echo "== steady stream (60 s)"
T0=$(now); sleep 60; T1=$(now)
read -r G MAXG N <<<"$(gaps "$O2" "$T0" "$T1" | tr '|' ' ')"
check "$([ "$G" = 0 ] && [ "$N" -ge 55 ] && echo 1)" "O2-SUMP (reduction all): $N rows in 60 s, no gap (longest ${MAXG} s)"
read -r G MAXG N <<<"$(gaps "$DO" "$T0" "$T1" | tr '|' ' ')"
check "$([ "$G" = 0 ] && [ "$N" -ge 55 ] && echo 1)" "DO from the array probe: $N rows, no gap"
EMPTY=$(sql "SELECT string_agg(code, ',') FROM sensors_channel c WHERE NOT EXISTS (SELECT 1 FROM sensors_reading r WHERE r.channel_no = c.channel_no)")
check "$([ -z "$EMPTY" ] && echo 1)" "every channel of the three devices has readings ${EMPTY:+(missing: $EMPTY)}"
RED=$(sql "SELECT count(*) || ' rows for ' || (sum(n) + max(s.run_n)) || ' samples' FROM sensors_reading r, sensors_channel_state s WHERE r.channel_no = $TEMP AND s.channel_no = $TEMP AND r.quality & 240 = 0")
note "TEMP-IN deadband 0.1 C, heartbeat 60 s: $RED"
check "$(sql "SELECT (count(*) FILTER (WHERE quality & 240 <> 0) = 0)::int FROM sensors_reading WHERE ts >= '$T0'")" "no bad quality in the normal stream"

echo "== switches"
B=$(late_rows); press sw_dup_on; sleep 6; press sw_dup_off; sleep 2
DUPKEYS=$(sql "SELECT count(*) FROM (SELECT channel_no, ts FROM sensors_reading GROUP BY 1, 2 HAVING count(*) > 1) d")
check "$([ "$DUPKEYS" = 0 ] && echo 1)" "duplicates: no key stored twice"
note "duplicates for 6 s: $(( $(late_rows) - B )) extra LATE rows (copies of suppressed samples), device late_total $(sql "SELECT late_total FROM sensors_device_state WHERE device_id = '00000000-0000-0000-0000-0000000d0001'")"

press sw_garbage; sleep 3
REASONS=$(sql "SELECT string_agg(DISTINCT reason, ',' ORDER BY reason) FROM sensors_dead_letter")
check "$([ "$REASONS" = "bad_value,missing_time,not_json,oversize" ] && echo 1)" "garbage dead-lettered: $REASONS"
note "a message on a topic no device has (sim/unknown/device-9) never reaches the ingest: it subscribes to device topics only (no_route needs a broader subscription)"
check "$(sql "SELECT (max(payload_len) > 65536 AND max(octet_length(payload)) <= 4096)::int FROM sensors_dead_letter")" "oversize: full length kept, payload cut to 4 KiB"

press sw_late; sleep 3
check "$(sql "SELECT (count(*) = 2)::int FROM sensors_reading WHERE channel_no = $O2 AND quality & 8 <> 0 AND ts < now() - interval '2 days'")" "late messages (3 and 20 days) stored on the late path"

press sw_skew_ahead; sleep 5; press sw_skew_off
check "$(sql "SELECT (count(*) >= 1 AND bool_and(ts <= now()))::int FROM sensors_reading WHERE channel_no = $FLOW AND quality & 4 <> 0")" "clock running 10 min ahead: stored at receive time, flagged clock_suspect (deadband: the first of the run stored)"
check "$(sql "SELECT (high_ts <= now() + interval '60 s')::int FROM sensors_channel_state WHERE channel_no = $FLOW")" "clock running ahead never pushed the channel newest time into the future"

T0=$(now); press sw_outage_start; sleep 12; press sw_outage_replay; sleep 6; T1=$(now)
read -r G MAXG N <<<"$(gaps "$O2" "$T0" "$T1" | tr '|' ' ')"
check "$([ "$G" = 0 ] && [ "$N" -ge 16 ] && echo 1)" "outage 12 s then replay: every second stored at its device time ($N rows, longest step ${MAXG} s)"

B=$(late_rows); press sw_ooo; sleep 8
note "out of order (5 PLC messages reversed): $(( $(late_rows) - B )) LATE rows"

echo "== ingest stop (SIGTERM) and start"
T0=$(now); B=$(late_rows)
"${COMPOSE[@]}" stop -t 60 sensors-ingest >/dev/null 2>&1; sleep 10; "${COMPOSE[@]}" start sensors-ingest >/dev/null 2>&1; sleep 20; T1=$(now)
read -r G MAXG N <<<"$(gaps "$O2" "$T0" "$T1" | tr '|' ' ')"
check "$([ "$G" = 0 ] && echo 1)" "SIGTERM, 10 s down, restart: no O2 second lost ($N rows, longest step ${MAXG} s)"
note "clean stop: $(( $(late_rows) - B )) LATE rows from redelivery (0 expected: everything acknowledged)"

echo "== ingest SIGKILL and start (crash between COMMIT and PUBACK possible)"
T0=$(now); B=$(late_rows)
docker kill -s KILL "$ING" >/dev/null; sleep 5; "${COMPOSE[@]}" start sensors-ingest >/dev/null 2>&1; sleep 20; T1=$(now)
read -r G MAXG N <<<"$(gaps "$O2" "$T0" "$T1" | tr '|' ' ')"
check "$([ "$G" = 0 ] && echo 1)" "SIGKILL: no O2 second lost ($N rows, longest step ${MAXG} s)"
note "SIGKILL: $(( $(late_rows) - B )) extra LATE rows (redelivered suppressed samples; bounded by the unacked window)"

echo "== crash right after a COMMIT, before its acknowledgements (failpoint)"
T0=$(now); B=$(late_rows); BD=$(sql "SELECT sum(ignored_total) FROM sensors_device_state")
E2E_FAILPOINT=15 "${COMPOSE[@]}" up -d --no-deps sensors-ingest >/dev/null 2>&1
ING=$("${COMPOSE[@]}" ps -q sensors-ingest)
sleep 40; T1=$(now)
RESTARTS=$(docker inspect -f '{{.RestartCount}}' "$ING")
check "$([ "$RESTARTS" -ge 1 ] && echo 1)" "failpoint: the ingest aborted after a COMMIT and was restarted ($RESTARTS restart)"
read -r G MAXG N <<<"$(gaps "$O2" "$T0" "$T1" | tr '|' ' ')"
check "$([ "$G" = 0 ] && echo 1)" "crash between COMMIT and PUBACK: no O2 second lost ($N rows, longest step ${MAXG} s)"
DUPKEYS=$(sql "SELECT count(*) FROM (SELECT channel_no, ts FROM sensors_reading GROUP BY 1, 2 HAVING count(*) > 1) d")
check "$([ "$DUPKEYS" = 0 ] && echo 1)" "crash between COMMIT and PUBACK: the redelivered batch stored nothing twice"
note "crash between COMMIT and PUBACK: $(( $(late_rows) - B )) extra LATE rows (redelivered suppressed samples), $(( $(sql "SELECT sum(ignored_total) FROM sensors_device_state") - BD )) duplicates ignored"

echo "== database session killed"
T0=$(now)
sql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = 'sensors_ingest_e2e'" >/dev/null
sleep 25; T1=$(now)
read -r G MAXG N <<<"$(gaps "$O2" "$T0" "$T1" | tr '|' ' ')"
check "$([ "$G" = 0 ] && echo 1)" "database sessions killed: recovered, no O2 second lost ($N rows, longest step ${MAXG} s)"

echo "== broker graceful restart"
T0=$(now); "${COMPOSE[@]}" restart mosquitto >/dev/null 2>&1; sleep 25; T1=$(now)
read -r G MAXG N <<<"$(gaps "$O2" "$T0" "$T1" | tr '|' ' ')"
note "broker restart: O2 $G gaps, longest ${MAXG} s, $N rows in the window (the simulator's own reconnect buffering decides)"

echo "== broker SIGKILL"
T0=$(now); MOS=$("${COMPOSE[@]}" ps -q mosquitto)
docker kill -s KILL "$MOS" >/dev/null; sleep 3; "${COMPOSE[@]}" start mosquitto >/dev/null 2>&1; sleep 25; T1=$(now)
read -r G MAXG N <<<"$(gaps "$O2" "$T0" "$T1" | tr '|' ' ')"
note "broker SIGKILL: O2 $G gaps, longest ${MAXG} s, $N rows in the window (loss window of plan risk 3)"

H=$(docker run --rm --network sensors-e2e_e2e --entrypoint node "$NODERED" -e \
  "fetch('http://sensors-ingest:8080/healthz').then(r=>r.text()).then(t=>console.log(t))")
note "healthz at the end: $H"
check "$(sql "SELECT (count(*) = 0)::int FROM sensors_reading WHERE NOT (value = value) OR (n > 1 AND run_sum IS NULL)")" "rows well formed"
note "rows $(sql "SELECT count(*) FROM sensors_reading"), dead letters $(sql "SELECT count(*) || '/' || sum(count) FROM sensors_dead_letter"), devices $(sql "SELECT string_agg(accepted_total || '/' || late_total || '/' || dead_total, ' ') FROM sensors_device_state")"

printf '%s\n' "${RESULTS[@]}" > "$STATE/results.txt"
echo "${FAILS} failed"
[ "$FAILS" = 0 ]
