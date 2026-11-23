#!/usr/bin/env bash
# The production stack's proof (.github/workflows/go-live-stack.yml): deploy/compose.yml built and started as a farm's
# server would run it, on a throwaway GitHub runner, with throwaway secrets made here and synthetic data only. Never on
# a farm's server, never with farm data. One step per argument, in this order:
#
#   prepare  throwaway secrets (scripts/make-secrets.sh), the certificates (scripts/certs.sh), the settings file, the
#            host name farm.ci.invalid on 127.0.0.1
#   up       the restic repository made, the stack started; every service healthy (the release step ran to its end)
#   roles    scripts/check-roles.sh: the app role refused DDL and TRUNCATE, the ingest and backup roles their bounds
#   data     synthetic data: the first admin (createsuperuser), the HR demonstration company (seed_hr_demo, run
#            with DEBUG on as a developer would), 60 days of readings written as the ingest role, the old chunks compressed
#   smoke    deploy/ci/smoke.py: HTTPS, redirects, headers, hashed static files and their cache, the sign-in, every page
#            reachable from the home page answered without a server error, the sign-in rate limit
#   mqtt     the broker's TLS listener: refused without a client certificate, refused with a certificate and a wrong
#            password, accepted with a certificate and the right one
#   backup   a dump, a base backup and a ship now; then a marker row, its WAL archived and shipped (for the PITR step)
#   restore  a second, empty installation (project farm-restore): the latest snapshot fetched from the repository,
#            the dump restored, every table's row count equal to the backup's, the application's migrations all applied
#   pitr     the base backup and the archived WAL of that snapshot replayed into a third server: the marker row is there
#   logs     every service's last lines (on a failure)
#   down     everything removed: containers, volumes, networks (both projects and the PITR server)
set -euo pipefail
cd "$(dirname "$0")/../.."
T=${RUNNER_TEMP:?RUNNER_TEMP: this runs on a CI runner only}
ENV_FILE=$T/ci.env
export SECRETS_DIR=$T/secrets OFFSITE_DIR=$T/offsite
HOST=farm.ci.invalid
ROOT=$PWD
DC=(docker compose --env-file "$ENV_FILE" -f "$ROOT/deploy/compose.yml" -f "$ROOT/deploy/ci/compose.ci.yml")
RC=(env EDGE_SUBNET=172.31.251.0/24 docker compose -p farm-restore --env-file "$ENV_FILE" -f "$ROOT/deploy/compose.yml"
    -f "$ROOT/deploy/ci/compose.ci.yml" --profile ops)
SERVICES=(db web jobs proxy mosquitto ingest backup)
ADMIN_PASSWORD_FILE=$T/admin_password

say() { echo "== $*"; }
psql_as() {  # psql_as ROLE SECRET SQL: in the database container, as ROLE with its own password
  "${DC[@]}" exec -T -e ROLE="$1" -e SECRET="$2" -e SQL="$3" db sh -c \
    'PGPASSWORD=$(head -n 1 "/run/secrets/$SECRET") psql -X -h 127.0.0.1 -U "$ROLE" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At -c "$SQL"'
}
health() { docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$1" 2>/dev/null || echo missing; }

prepare() {
  say "settings"
  cat > "$ENV_FILE" <<EOF
COMPOSE_PROJECT_NAME=farm-ci
SITE_HOST=$HOST
SECRETS_DIR=$SECRETS_DIR
OFFSITE_DIR=$OFFSITE_DIR
DB_NAME=balik
WEB_IMAGE=balik-web:ci
DB_IMAGE=balik-db:ci
BACKUP_IMAGE=balik-backup:ci
INGEST_IMAGE=balik-ingest:ci
EMAIL_HOST=smtp.ci.invalid
DEFAULT_FROM_EMAIL=console@farm.ci.invalid
DJANGO_HSTS_SECONDS=3600
HTTPS_BIND=127.0.0.1
HTTP_BIND=127.0.0.1
MQTT_BIND_ADDRESS=127.0.0.1
RESTIC_REPOSITORY=/offsite/repo
RESTORE_FROM_HOST_TAG=farm-ci
BACKUP_SHIP_MINUTES=600
DB_MEMORY=2g
DB_SHARED_BUFFERS=256MB
WEB_MEMORY=1g
GUNICORN_WORKERS=2
EOF
  mkdir -p "$OFFSITE_DIR"
  chmod 0777 "$OFFSITE_DIR"            # the backup agent writes it as postgres (uid 70)
  say "throwaway secrets and certificates"
  sh deploy/scripts/make-secrets.sh
  sh deploy/scripts/certs.sh proxy-internal "$HOST"
  sh deploy/scripts/certs.sh mqtt-ca
  sh deploy/scripts/certs.sh mqtt-server localhost 127.0.0.1
  sh deploy/scripts/certs.sh mqtt-device sensor-ci
  openssl rand -hex 16 > "$ADMIN_PASSWORD_FILE"
  echo "127.0.0.1 $HOST" | sudo tee -a /etc/hosts > /dev/null
}

up() {
  say "the backup repository (restic init)"
  "${DC[@]}" run --rm -T backup init
  say "start"
  "${DC[@]}" up -d
  say "wait for every service to be healthy (10 minutes at most)"
  for _ in $(seq 1 120); do
    states=""
    all=1
    for service in "${SERVICES[@]}"; do
      state=$(health "farm-ci-$service-1")
      states="$states $service=$state"
      [ "$state" = healthy ] || all=0
    done
    if [ "$all" = 1 ]; then echo "$states"; break; fi
    sleep 5
  done
  echo "$states"
  [ "$all" = 1 ] || { "${DC[@]}" ps -a; exit 1; }
  release=$(docker inspect -f '{{.State.ExitCode}}' farm-ci-release-1)
  [ "$release" = 0 ] || { echo "the release step ended with $release"; exit 1; }
  "${DC[@]}" logs release | tail -n 8
}

roles() {
  COMPOSE="${DC[*]}" sh deploy/scripts/check-roles.sh
}

data() {
  say "the first admin (createsuperuser, as the app role)"
  "${DC[@]}" run --rm -T --no-deps -e DJANGO_SUPERUSER_PASSWORD="$(cat "$ADMIN_PASSWORD_FILE")" web \
    python manage.py createsuperuser --no-input --username ci-admin --email ci-admin@farm.ci.invalid
  say "synthetic data: the HR demonstration company (seed_hr_demo, DEBUG on as on a developer's machine)"
  "${DC[@]}" run --rm -T --no-deps -e DJANGO_DEBUG=1 web python manage.py seed_hr_demo
  say "synthetic readings, written as the ingest role (new chunks made by a role that owns nothing)"
  psql_as sensors_ingest db_ingest_password "INSERT INTO sensors_reading (channel_no, ts, value)
    SELECT 1, ts, 7 + random() FROM generate_series(now() - interval '60 days', now(), interval '10 minutes') AS ts"
  say "the chunks older than 14 days compressed, as the owner (the compression policy's job, run now)"
  psql_as balik_owner db_owner_password "SELECT count(compress_chunk(c, if_not_compressed => true))
    FROM show_chunks('sensors_reading', older_than => interval '14 days') AS c"
  psql_as balik_owner db_owner_password "SELECT count(*), count(*) FILTER (WHERE is_compressed)
    FROM timescaledb_information.chunks WHERE hypertable_name = 'sensors_reading'"
}

smoke() {
  python3 deploy/ci/smoke.py --host "$HOST" --ca "$SECRETS_DIR/proxy-ca/ca.crt" --user ci-admin \
    --password-file "$ADMIN_PASSWORD_FILE"
}

mqtt() {
  local image=eclipse-mosquitto:2.0.20@sha256:21421af7b32bf9ce508e9090c8eb13bb81f410ca778dc205506180a6f862d0eb
  local device=$SECRETS_DIR/mqtt-devices/sensor-ci
  sub() {  # sub NAME USER PASSWORD [--cert ... --key ...]: what mosquitto_sub says in 3 s
    local name=$1 user=$2 password=$3
    shift 3
    docker run --rm --network host -v "$SECRETS_DIR/mqtt:/ca:ro" -v "$device:/device:ro" "$image" \
      mosquitto_sub -h 127.0.0.1 -p 8883 --cafile /ca/ca.crt -u "$user" -P "$password" -t "ci/$name" -C 1 -W 3 "$@" \
      2>&1 || true
  }
  local good
  good=$(cat "$SECRETS_DIR/mqtt_ingest")
  say "no client certificate: refused at the TLS handshake"
  out=$(sub nocert ingest "$good")
  echo "$out"
  if echo "$out" | grep -qi 'timed out'; then echo "FAIL: a client without a certificate was let in"; exit 1; fi
  say "a client certificate and a wrong password: refused by the broker"
  out=$(sub wrongpw ingest wrong-password --cert /device/client.crt --key /device/client.key)
  echo "$out"
  echo "$out" | grep -qi 'not authori' || { echo "FAIL: a wrong password was not refused"; exit 1; }
  say "a client certificate and the right password: connected (then 3 s of silence)"
  out=$(sub good ingest "$good" --cert /device/client.crt --key /device/client.key)
  echo "$out"
  echo "$out" | grep -qi 'timed out' || { echo "FAIL: a device with a certificate and its password was not let in"; exit 1; }
}

backup() {
  say "dump, base backup and ship now"
  "${DC[@]}" exec -T backup sh /usr/local/lib/balik-backup/agent.sh now
  say "a marker row after the base backup, its WAL archived, shipped (the point-in-time step looks for it)"
  psql_as sensors_ingest db_ingest_password "INSERT INTO sensors_reading (channel_no, ts, value) VALUES (424242, now(), 42)"
  segment=$("${DC[@]}" exec -T db sh -c 'PGPASSWORD=$(head -n 1 /run/secrets/postgres_password) psql -X -h 127.0.0.1 -U postgres -d "$POSTGRES_DB" -At -c "SELECT pg_walfile_name(pg_switch_wal())"')
  echo "switched out of $segment"
  for _ in $(seq 1 60); do
    archived=$("${DC[@]}" exec -T db sh -c 'PGPASSWORD=$(head -n 1 /run/secrets/postgres_password) psql -X -h 127.0.0.1 -U postgres -d "$POSTGRES_DB" -At -c "SELECT last_archived_wal FROM pg_stat_archiver"')
    if [ -n "$archived" ] && [[ ! "$archived" < "$segment" ]]; then break; fi
    sleep 2
  done
  echo "last archived: $archived"
  [[ ! "$archived" < "$segment" ]] || { echo "FAIL: $segment was not archived"; exit 1; }
  "${DC[@]}" exec -T backup sh /usr/local/lib/balik-backup/agent.sh ship
  "${DC[@]}" exec -T backup sh /usr/local/lib/balik-backup/agent.sh snapshots
  "${DC[@]}" exec -T backup sh /usr/local/lib/balik-backup/agent.sh health
}

restore() {
  say "a second, empty installation: its database made by the image's first start"
  "${RC[@]}" up -d --wait db
  say "the latest snapshot fetched from the repository (decrypted with the repository's password)"
  "${RC[@]}" run --rm -T --no-deps restore fetch latest /backups/restore
  dump=$("${RC[@]}" run --rm -T --no-deps --entrypoint sh restore -c 'ls -1 /backups/restore/backups/dumps/balik-*Z.dump | tail -n 1')
  echo "dump: $dump"
  say "the dump restored as the superuser, then every table's row count compared with the backup's"
  "${RC[@]}" run --rm -T --no-deps restore restore-dump "$dump"
  "${RC[@]}" run --rm -T --no-deps restore verify-counts "$dump.counts"
  say "the application on the restored database: every migration applied (migrate --check)"
  "${RC[@]}" run --rm -T --no-deps web python manage.py migrate --check
}

pitr() {
  base=$("${RC[@]}" run --rm -T --no-deps --entrypoint sh restore -c 'ls -1d /backups/restore/backups/base/balik-*Z | tail -n 1')
  echo "base backup: $base"
  docker volume create farm-pitr-data > /dev/null
  say "a data folder from the base backup, replaying the archived WAL of the snapshot"
  docker run --rm -u root --entrypoint sh -v farm-restore_backups:/backups:ro -v farm-pitr-data:/pitr balik-backup:ci \
    -c "sh /usr/local/lib/balik-backup/agent.sh prepare-pitr '$base' /backups/restore/wal-archive /pitr/data \
        && chown -R postgres:postgres /pitr/data"
  docker run -d --name farm-pitr -e PGDATA=/var/lib/postgresql/data/data -v farm-pitr-data:/var/lib/postgresql/data \
    -v farm-restore_backups:/backups:ro balik-db:ci > /dev/null
  for _ in $(seq 1 90); do
    if docker exec farm-pitr psql -X -U postgres -d balik -At -c 'SELECT pg_is_in_recovery()' 2>/dev/null | grep -qx f; then
      break
    fi
    sleep 2
  done
  docker logs --tail 15 farm-pitr
  found=$(docker exec farm-pitr psql -X -U postgres -d balik -At -c 'SELECT count(*) FROM sensors_reading WHERE channel_no = 424242')
  echo "marker rows after the point-in-time restore: $found"
  [ "$found" = 1 ] || { echo "FAIL: the marker written after the base backup is not there"; exit 1; }
  total=$(docker exec farm-pitr psql -X -U postgres -d balik -At -c 'SELECT count(*) FROM sensors_reading')
  echo "readings: $total"
}

logs() {
  "${DC[@]}" ps -a || true
  "${DC[@]}" logs --tail 60 || true
  "${RC[@]}" logs --tail 40 2>/dev/null || true
  docker logs --tail 40 farm-pitr 2>/dev/null || true
}

down() {
  docker rm -f -v farm-pitr > /dev/null 2>&1 || true
  docker volume rm farm-pitr-data > /dev/null 2>&1 || true
  "${RC[@]}" down -v --remove-orphans || true
  "${DC[@]}" --profile ops --profile cloudflare down -v --remove-orphans || true
}

for step in "$@"; do
  "$step"
done
