#!/usr/bin/env bash
# The production stack's proof (.github/workflows/go-live-stack.yml): deploy/compose.yml built and started as a farm's
# server would run it, on a throwaway GitHub runner, with throwaway secrets made here and synthetic data only. Never on
# a farm's server, never with farm data. One step per argument, in this order:
#
#   prepare  throwaway secrets (scripts/make-secrets.sh), the certificates (scripts/certs.sh), the settings file, the
#            host name farm.ci.invalid on 127.0.0.1
#   up       the restic repository made, the stack started; every service healthy (the release step ran to its end)
#   roles    scripts/check-roles.sh: the app role refused DDL and TRUNCATE, the ingest and backup roles their bounds
#   data     synthetic data: the first admin (createsuperuser); a development tool (seed_hr_demo) refused; the database
#            marked as the stack's and the HR demonstration company written by the stack's seeder (seed_stack_proof,
#            the app role, DEBUG off); 60 days of readings written as the ingest role, the old chunks compressed
#   smoke    deploy/ci/smoke.py: HTTPS, redirects, headers, hashed static files and their cache, the sign-in, every page
#            reachable from the home page answered without a server error, the sign-in rate limit
#   mqtt     the broker's TLS listener: refused without a client certificate, refused with a certificate and a wrong
#            password, accepted with a certificate and the right one
#   backup   a dump, a base backup and a ship now; then a marker row, its WAL archived and shipped (for the PITR step)
#   restore  a second, empty installation (project farm-restore): the latest snapshot fetched from the repository,
#            the dump restored, every table's row count equal to the backup's, the application's migrations all applied,
#            the stack's mark not carried (its seeder refused there)
#   pitr     the base backup and the archived WAL of that snapshot replayed into a third server: the marker row is there
#   network  who reaches whom, outside names, the way out of every service, and no packet out of the proxy's and the
#            broker's networks (a capture on the runner's uplink)
#   rotate   the app role's password rotated
#   tsmove, tsback, tshalf, tsearly   the TimescaleDB move of docs/ops/upgrade.md on the project's real schema (below)
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
RC=(env EDGE_SUBNET=172.31.251.0/24 WEB_FRONT_ADDRESS=172.31.251.10 MQTT_EDGE_SUBNET=172.31.253.0/24 docker compose -p farm-restore --env-file "$ENV_FILE" -f "$ROOT/deploy/compose.yml"
    -f "$ROOT/deploy/ci/compose.ci.yml" --profile ops)
SERVICES=(db web jobs proxy mosquitto ingest backup)
ADMIN_PASSWORD_FILE=$T/admin_password

say() { echo "== $*"; }
psql_as() {  # psql_as ROLE SECRET SQL: in the database container, as ROLE with its own password
  "${DC[@]}" exec -T -e ROLE="$1" -e SECRET="$2" -e SQL="$3" db sh -c \
    'PGPASSWORD=$(head -n 1 "/run/secrets/$SECRET") psql -X -h db -U "$ROLE" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At -c "$SQL"'
}
refused() {  # refused REASON COMMAND...: COMMAND must fail and say REASON; its output is printed as expected, not a failure
  local reason=$1 out
  shift
  if out=$("$@" 2>&1); then echo "$out"; echo "FAIL: it ran; expected a refusal saying: $reason"; exit 1; fi
  case "$out" in
    *"$reason"*) echo "$out" | grep -v '^$' | tail -n 3 | sed 's/^/expected: /'; echo "ok    refused: $reason" ;;
    *) echo "$out"; echo "FAIL: it failed, but not with a refusal saying: $reason"; exit 1 ;;
  esac
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

network() {
  say "who reaches whom: a probe in each service's own network namespace (a throwaway container sharing it)"
  say "open: answered; closed: the host is reached, nothing listens; unreachable: no route, no name, no answer"
  local failures=0
  ask() {  # ask SERVICE tcp|udp|tcp6|name HOST PORT [DNS_ID]: prints open, closed ... or unreachable ...
    docker run --rm --network "container:farm-ci-$1-1" --entrypoint python balik-web:ci -c '
import socket, sys
kind, host, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
question_id = sys.argv[4] if len(sys.argv) > 4 else "abcd"
try:
    if kind == "name":                                    # a name, answered by the resolver of the service
        socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        print("open")
    elif kind == "udp":                                   # a DNS question (example.com, A) with its own id
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(4)
        s.sendto(bytes.fromhex(question_id + "01000001000000000000076578616d706c6503636f6d0000010001"), (host, port))
        s.recvfrom(512)
        print("open")
    else:
        family = socket.AF_INET6 if kind == "tcp6" else socket.AF_INET
        address = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)[0][4]
        s = socket.socket(family, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(address)
        print("open")
except ConnectionRefusedError:
    print("closed ConnectionRefusedError")
except OSError as error:                                  # no name, no route, no answer
    print("unreachable", type(error).__name__, getattr(error, "errno", ""))' "$2" "$3" "$4" ${5:+"$5"} 2>&1
  }
  probe() {  # probe SERVICE tcp|udp|tcp6|name HOST PORT open|closed|unreachable
    local got
    got=$(ask "$1" "$2" "$3" "$4")
    if [ "${got%% *}" = "$5" ]; then echo "ok    $1 -> $2 $3:$4 $got"
    else echo "FAIL  $1 -> $2 $3:$4 $got (expected $5)"; failures=$((failures + 1)); fi
  }
  # The UDP way out of a service that has one. An answer proves it, but whether one comes is up to the runner's own
  # network: on some GitHub hosts no answer from a public resolver comes back at all (run 45626819379, web and backup
  # alike, while TCP to the same address was answered). So the proof that does not hang on the world outside is the
  # question itself, seen leaving by the runner's uplink, picked out by a DNS id of its own (masqueraded, it carries
  # the runner's address). way=answered, sent (no answer, but the question left) or shut (no answer, nothing left).
  udp_way() {  # udp_way SERVICE HOST; sets way and way_line
    local id got cap=$T/udp-way.pcap pid sent
    id=$(od -An -N2 -tx1 /dev/urandom | tr -d ' \n')
    sudo tcpdump -i "$uplink" -n -U -w "$cap" "udp and dst host $2 and dst port 53 and udp[8:2] = 0x$id" \
      > "$cap.log" 2>&1 &
    pid=$!
    for _ in $(seq 1 20); do grep -q 'listening on' "$cap.log" && break; sleep 0.5; done
    grep -q 'listening on' "$cap.log" || { cat "$cap.log"; echo "FAIL: the capture of the UDP question did not start"; exit 1; }
    got=$(ask "$1" udp "$2" 53 "$id")
    sleep 1
    sudo kill -INT "$pid"
    wait "$pid" || true
    sent=$(sudo tcpdump -r "$cap" -n 2>/dev/null | wc -l)
    if [ "${got%% *}" = open ]; then way=answered
    elif [ "$sent" -gt 0 ]; then way=sent
    else way=shut; fi
    way_line="$1 -> udp $2:53 $way ($got; question id $id, $sent packet(s) of it left by $uplink)"
  }
  # The two DOCKER-USER rules, put in by deploy/scripts/docker-user-rules.sh as docs/ops/install.md has the host do it
  # (from the farm's settings; twice, as every Docker start does: never a duplicate; --check fails before, passes after),
  # then a capture on the runner's own uplink of everything sent from the proxy's and the broker's networks while every
  # probe runs. Those networks are not masqueraded, so a packet of theirs would leave with its own source address:
  # "unreachable" below says no answer came back, the empty capture says no packet even left.
  local uplink front edge capture=$T/egress.pcap
  uplink=$(ip -4 route show default | awk '{print $5; exit}')
  front=$(docker network inspect -f '{{(index .IPAM.Config 0).Subnet}}' farm-ci_front)
  edge=$(docker network inspect -f '{{(index .IPAM.Config 0).Subnet}}' farm-ci_mqtt-edge)
  if sudo sh deploy/scripts/docker-user-rules.sh --check "$ENV_FILE"; then echo "FAIL: --check passed with no rule"; exit 1; fi
  sudo sh deploy/scripts/docker-user-rules.sh "$ENV_FILE"
  sudo sh deploy/scripts/docker-user-rules.sh "$ENV_FILE"
  sudo sh deploy/scripts/docker-user-rules.sh --check "$ENV_FILE"
  sudo iptables -S DOCKER-USER
  for net in "$front" "$edge"; do
    [ "$(sudo iptables -S DOCKER-USER | grep -c -- "-s $net ")" = 1 ] || { echo "FAIL: the rule for $net is not there once"; exit 1; }
  done
  sudo tcpdump -i "$uplink" -n -U -w "$capture" "src net $front or src net $edge" > "$T/tcpdump.log" 2>&1 &
  local capturing=$!
  for _ in $(seq 1 20); do grep -q 'listening on' "$T/tcpdump.log" && break; sleep 0.5; done
  cat "$T/tcpdump.log"
  # between the services
  probe web tcp db 5432 open
  probe web tcp ingest 8080 closed
  probe web tcp mosquitto 1883 unreachable
  probe jobs tcp db 5432 open
  probe jobs tcp ingest 8080 closed
  probe jobs tcp web 8000 closed
  probe proxy tcp web 8000 open
  probe proxy tcp db 5432 unreachable
  probe proxy tcp ingest 8080 unreachable
  probe proxy tcp mosquitto 1883 unreachable
  probe mosquitto tcp db 5432 unreachable
  probe mosquitto tcp web 8000 unreachable
  probe ingest tcp mosquitto 1883 open
  probe ingest tcp db 5432 open
  probe ingest tcp web 8000 closed
  probe backup tcp db 5432 open
  probe backup tcp mosquitto 1883 unreachable
  probe backup tcp web 8000 closed
  # outside names: answered for the two with a way out; for the others, not even a name (DNS is a way out too)
  probe proxy name web 8000 open
  for service in web backup; do probe "$service" name example.com 443 open; done
  for service in db jobs proxy mosquitto ingest; do probe "$service" name example.com 443 unreachable; done
  # the way out, TCP, UDP and IPv6, for every running service: only the web server (mail) and the backup agent
  # (the repository) have one
  for service in web backup; do
    probe "$service" tcp 1.1.1.1 443 open
    udp_way "$service" 1.1.1.1
    if [ "$way" = shut ]; then echo "FAIL  $way_line (expected a way out)"; failures=$((failures + 1))
    else echo "ok    $way_line"; fi
    probe "$service" tcp6 2606:4700:4700::1111 443 unreachable
  done
  # udp_way itself, both ways, on the web server's network: with the answer dropped on its way back (what such a
  # runner's network does) it still finds the way out by the question that left; with the question dropped on its
  # way out, it finds none. Each rule is taken off again at once.
  local egress
  egress=$(docker network inspect -f '{{(index .IPAM.Config 0).Subnet}}' farm-ci_egress)
  sudo iptables -I DOCKER-USER -s 1.1.1.1 -d "$egress" -p udp --sport 53 -j DROP
  udp_way web 1.1.1.1
  sudo iptables -D DOCKER-USER -s 1.1.1.1 -d "$egress" -p udp --sport 53 -j DROP
  if [ "$way" = sent ]; then echo "ok    the answer dropped on its way back: $way_line"
  else echo "FAIL  the answer dropped on its way back: $way_line (expected sent)"; failures=$((failures + 1)); fi
  sudo iptables -I DOCKER-USER -s "$egress" -d 1.1.1.1 -p udp --dport 53 -j DROP
  udp_way web 1.1.1.1
  sudo iptables -D DOCKER-USER -s "$egress" -d 1.1.1.1 -p udp --dport 53 -j DROP
  if [ "$way" = shut ]; then echo "ok    the question dropped on its way out: $way_line"
  else echo "FAIL  the question dropped on its way out: $way_line (expected shut)"; failures=$((failures + 1)); fi
  for service in db jobs proxy mosquitto ingest; do
    probe "$service" tcp 1.1.1.1 443 unreachable
    probe "$service" udp 1.1.1.1 53 unreachable
    probe "$service" tcp6 2606:4700:4700::1111 443 unreachable
  done
  sleep 2
  sudo kill -INT "$capturing"
  wait "$capturing" || true
  local left
  left=$(sudo tcpdump -r "$capture" -n 2>/dev/null | wc -l)
  sudo tcpdump -r "$capture" -n 2>/dev/null | head -n 10
  if [ "$left" = 0 ]; then echo "ok    no packet from $front (proxy) or $edge (broker) left by $uplink"
  else echo "FAIL  $left packet(s) from $front (proxy) or $edge (broker) left by $uplink"; failures=$((failures + 1)); fi
  sudo iptables -L DOCKER-USER -v -n -x
  for net in "$front" "$edge"; do
    dropped=$(sudo iptables -L DOCKER-USER -v -n -x | awk -v net="$net" '$3 == "DROP" && $8 == net {print $1}')
    if [ "${dropped:-0}" -gt 0 ]; then echo "ok    the rule for $net dropped $dropped packet(s): the probes did try"
    else echo "FAIL  the rule for $net dropped nothing: the probes did not try"; failures=$((failures + 1)); fi
  done
  [ "$failures" = 0 ] || { echo "network: $failures probe(s) failed"; exit 1; }
  echo "network: every probe as expected"
}

data() {
  say "the first admin (createsuperuser, as the app role)"
  "${DC[@]}" run --rm -T -e DJANGO_SUPERUSER_PASSWORD="$(cat "$ADMIN_PASSWORD_FILE")" manage \
    python manage.py createsuperuser --no-input --username ci-admin --email ci-admin@farm.ci.invalid
  # The synthetic data is the product's own, written as a farm's server writes (the app role, DEBUG off, through the
  # services) by the stack's seeder (manage.py seed_stack_proof, kind stack in README, Management commands), which runs
  # only on a database carrying the stack's mark. No development tool runs here: the stack is the production stack,
  # and the dev guard refusing on it is part of the proof.
  say "a development tool refused on the production stack: seed_hr_demo with DEBUG on, as the app role (no superuser)"
  refused "the database role is not a superuser" "${DC[@]}" run --rm -T -e DJANGO_DEBUG=1 manage python manage.py seed_hr_demo
  say "the stack's seeder refused on a database without the stack's mark"
  refused "does not carry the stack's mark" "${DC[@]}" run --rm -T manage python manage.py seed_stack_proof --by ci-admin
  say "the database marked as the stack's (its comment, core/management/stackproof.py): the app role may not, the owner may"
  local mark mark_sql
  mark=$(sed -n "s/^MARK = '\([^']*\)'$/\1/p" core/management/stackproof.py)
  [ -n "$mark" ] || { echo "FAIL: no MARK in core/management/stackproof.py"; exit 1; }
  mark_sql="DO \$\$ BEGIN EXECUTE format('COMMENT ON DATABASE %I IS %L', current_database(), '$mark'); END \$\$"
  refused "must be owner of database" psql_as balik_app db_app_password "$mark_sql"
  psql_as balik_owner db_owner_password "$mark_sql"
  say "synthetic data: the HR demonstration company, no sign-in (seed_stack_proof, as the app role, DEBUG off)"
  "${DC[@]}" run --rm -T manage python manage.py seed_stack_proof --by ci-admin
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

heartbeat() {
  say "the heartbeat's checks (scripts/heartbeat.sh): services, disk, certificates, backup, sensors"
  COMPOSE="${DC[*]}" ENV_FILE="$ENV_FILE" sh deploy/scripts/heartbeat.sh
  say "a WAL segment that cannot be archived turns the backup unhealthy and the heartbeat red"
  "${DC[@]}" exec -T -u root db chmod 0500 /wal-archive
  "${DC[@]}" exec -T db sh -c 'PGPASSWORD=$(head -n 1 /run/secrets/postgres_password) psql -X -h 127.0.0.1 -U postgres -d "$POSTGRES_DB" -At -c "CREATE TEMP TABLE heartbeat_wal AS SELECT 1" -c "SELECT pg_switch_wal()"' > /dev/null
  out=""
  for _ in $(seq 1 60); do
    out=$("${DC[@]}" exec -T backup sh /usr/local/lib/balik-backup/agent.sh health 2>&1 || true)
    case "$out" in *"archiver is failing"*) break ;; esac
    sleep 2
  done
  echo "backup health: $out"
  case "$out" in *"archiver is failing"*) ;; *) echo "FAIL: a failing archiver was not seen"; exit 1 ;; esac
  if COMPOSE="${DC[*]}" ENV_FILE="$ENV_FILE" sh deploy/scripts/heartbeat.sh > "$T/heartbeat.out"; then
    cat "$T/heartbeat.out"; echo "FAIL: the heartbeat passed with a failing archiver"; exit 1
  fi
  grep FAIL "$T/heartbeat.out"
  say "the archive writable again: the archiver catches up and the heartbeat is green"
  "${DC[@]}" exec -T -u root db chmod 0700 /wal-archive
  for _ in $(seq 1 60); do
    out=$("${DC[@]}" exec -T backup sh /usr/local/lib/balik-backup/agent.sh health 2>&1 || true)
    [ "$out" = ok ] && break
    sleep 3
  done
  echo "backup health: $out"
  [ "$out" = ok ] || { echo "FAIL: the archiver did not recover"; exit 1; }
  for _ in $(seq 1 60); do [ "$(health farm-ci-backup-1)" = healthy ] && break; sleep 5; done
  COMPOSE="${DC[*]}" ENV_FILE="$ENV_FILE" sh deploy/scripts/heartbeat.sh
}

mqtt() {
  local image=eclipse-mosquitto:2.0.23@sha256:6a332cc7a8dbe011cbc076180cbb76b37c6f0f55809682ea08e7980ef0112ad9
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
  say "the archive_command flushes each segment and its folder (sync) before the database counts it archived"
  "${DC[@]}" exec -T db sh -c 'PGPASSWORD=$(head -n 1 /run/secrets/postgres_password) psql -X -h 127.0.0.1 -U postgres -d "$POSTGRES_DB" -At -c "SHOW archive_command"' \
    | tee "$T/archive_command"
  grep -q 'sync /wal-archive/%f.tmp && mv' "$T/archive_command" && grep -q '&& sync /wal-archive;' "$T/archive_command" \
    || { echo "FAIL: the archive_command does not flush"; exit 1; }
  say "a WAL segment shorter than 16 MiB in the archive: the ship refuses it and ships nothing"
  "${DC[@]}" exec -T -u root db sh -c 'head -c 1000 /dev/zero > /wal-archive/0000000100000000000000FE && chown postgres /wal-archive/0000000100000000000000FE'
  if "${DC[@]}" exec -T backup sh /usr/local/lib/balik-backup/agent.sh ship > "$T/short.out" 2>&1; then
    cat "$T/short.out"; echo "FAIL: a short segment was shipped"; exit 1
  fi
  grep 'not 16 MiB' "$T/short.out"
  "${DC[@]}" exec -T -u root db rm -f /wal-archive/0000000100000000000000FE
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
  "${RC[@]}" run --rm -T manage python manage.py migrate --check
  say "the stack's mark not carried by the restore (pg_restore without --create applies no database comment): seeder refused"
  refused "does not carry the stack's mark" "${RC[@]}" run --rm -T manage python manage.py seed_stack_proof --by ci-admin
  say "a repository that cannot be read fails the prune check and records no success: missing, wrong password, no network"
  local agent=/usr/local/lib/balik-backup/agent.sh case_env
  for case_env in "RESTIC_REPOSITORY=/offsite/no-such-repository" "RESTIC_PASSWORD_FILE=/tmp/wrong-password" \
                  "RESTIC_REPOSITORY=rest:http://backup.invalid:8000/farm-ci/main/"; do
    before_ok=$("${DC[@]}" exec -T backup sh -c 'cat /backups/state/prunecheck.ok 2>/dev/null || echo none')
    if "${DC[@]}" exec -T -e "$case_env" -e BACKUP_LIST_TIMEOUT=60 backup sh -c \
        "echo wrong > /tmp/wrong-password && sh $agent prunecheck" > "$T/prunecase.out" 2>&1; then
      cat "$T/prunecase.out"; echo "FAIL: the prune check passed with $case_env"; exit 1
    fi
    grep -q "could not be read" "$T/prunecase.out" || { cat "$T/prunecase.out"; echo "FAIL: no reason with $case_env"; exit 1; }
    after_ok=$("${DC[@]}" exec -T backup sh -c 'cat /backups/state/prunecheck.ok 2>/dev/null || echo none')
    [ "$before_ok" = "$after_ok" ] || { echo "FAIL: $case_env recorded a success"; exit 1; }
    "${DC[@]}" exec -T backup test -f /backups/state/prunecheck.failed || { echo "FAIL: $case_env left no failure"; exit 1; }
    echo "ok    $case_env: refused, no success recorded ($(grep -o 'could not be read.*' "$T/prunecase.out" | head -c 120))"
  done
  "${DC[@]}" exec -T backup sh "$agent" prunecheck                           # readable again: green
  say "a month without the owner's prune: 30 snapshots dated two months back; the farm's prune check turns red"
  "${RC[@]}" run --rm -T --no-deps --entrypoint sh restore -c \
    'unset RESTIC_CACERT; for minute in $(seq 10 39); do restic backup -q --host farm-ci --tag balik --time "2026-09-01 00:$minute:00" /etc/hostname; done'
  if "${DC[@]}" exec -T backup sh /usr/local/lib/balik-backup/agent.sh prunecheck > "$T/prune.out" 2>&1; then
    cat "$T/prune.out"; echo "FAIL: an overdue prune was not seen"; exit 1
  fi
  grep "prune is overdue" "$T/prune.out"
  say "the owner's maintenance from another machine: the retention applied (forget --prune), the repository checked"
  "${RC[@]}" run --rm -T --no-deps restore restic forget --host farm-ci --tag balik --keep-hourly 48 --keep-daily 14 \
    --keep-weekly 8 --keep-monthly 12 --prune
  "${RC[@]}" run --rm -T --no-deps restore restic check --read-data-subset=10%
  latest=$("${RC[@]}" run --rm -T --no-deps restore restic snapshots --host farm-ci --latest 1 --json)
  echo "$latest" | grep -q '"short_id"' || { echo "FAIL: no snapshot left after the owner's prune"; exit 1; }
  "${DC[@]}" exec -T backup sh /usr/local/lib/balik-backup/agent.sh prunecheck
  "${DC[@]}" exec -T backup sh /usr/local/lib/balik-backup/agent.sh health
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

rotate() {
  say "the app role's password rotated (scripts/rotate-db-password.sh): verifier only, no old copy, services recreated"
  old=$(cat "$SECRETS_DIR/db_app_password")
  COMPOSE="${DC[*]}" ENV_FILE="$ENV_FILE" sh deploy/scripts/rotate-db-password.sh balik_app
  new=$(cat "$SECRETS_DIR/db_app_password")
  [ "$old" != "$new" ] || { echo "FAIL: the secret file did not change"; exit 1; }
  for leftover in "$SECRETS_DIR"/db_app_password.old "$SECRETS_DIR"/.db_app_password.new; do
    if [ -e "$leftover" ]; then echo "FAIL: $leftover was left"; exit 1; fi
  done
  # over the network, from the backup container (inside the database container 127.0.0.1 is trusted by the image's
  # pg_hba, so a password is never asked there)
  signin() { printf '%s\n' "$1" | "${DC[@]}" exec -T backup sh -c \
    'read -r p; PGPASSWORD=$p psql -X -h db -U balik_app -d "$PGDATABASE" -At -c "SELECT 1"' 2>&1; }
  [ "$(signin "$new")" = 1 ] || { echo "FAIL: the new password does not sign in"; exit 1; }
  if [ "$(signin "$old")" = 1 ]; then echo "FAIL: the old password still signs in"; exit 1; fi
  echo "the new password signs in, the old one is refused"
  if "${DC[@]}" logs db 2>&1 | grep -qF "$new"; then echo "FAIL: the new password is in the database's log"; exit 1; fi
  for _ in $(seq 1 40); do
    [ "$(health farm-ci-web-1)" = healthy ] && [ "$(health farm-ci-jobs-1)" = healthy ] && break
    sleep 5
  done
  echo "web $(health farm-ci-web-1), jobs $(health farm-ci-jobs-1)"
  [ "$(health farm-ci-web-1)" = healthy ] || { echo "FAIL: web is not healthy with the new password"; exit 1; }
  say "check-roles right after the rotation, with the database container as it was (no recreation)"
  COMPOSE="${DC[*]}" sh deploy/scripts/check-roles.sh
}

# docs/ops/upgrade.md's move of the shared development database, on a copy of it made the way it was made: the old
# image as docker-compose.yml starts it (role, database and password balik), every migration of the project run on it
# by the project's own image, as the development server ran them, and real data: readings with compressed chunks, the
# hour rollup refreshed, water samples (a hypertable whose chunks carry the revision triggers, core/rev.py). Steps:
#   tsmove  another database with a water chunk refused by name; a failed dump left as .partial; the move exactly as
#           upgrade.md runs it; a second move refused, nothing written
#   tsback  the way back: refused without room on Docker's disk; a failing one cleans up after itself; the real one
#           restores the roles first and leaves a cluster the development stack signs in to with its own password
#   tshalf  a move stopped half-way (on a copy taken before the move): the next move refuses and says how to go on,
#           `resume` finishes it; a stop at the jobs' wait is closed by `close`
#   tsearly the server recreated on the new image before the move (another copy): the move takes the dump on the
#           extension's own release, and the way back restores that dump on the old image
TS_OLD=timescale/timescaledb:2.17.2-pg17@sha256:3324f81ca7f84cdc2dc4497863b3798ababa8ce130c5b59d73f0b40e3a34148e
TS_NEW=timescale/timescaledb:2.32.1-pg17@sha256:2f5e6969faa5cd7f4b075d65f124e30dc50d456b7b807e5c1acd9d51ba7df51c
TS_MOVE=deploy/scripts/timescaledb-move.sh
ts_run() {  # ts_run NAME VOLUME IMAGE: the command that starts a database container as docker-compose.yml does
  echo "docker run -d --name $1 --network tsmove-net -e POSTGRES_USER=balik -e POSTGRES_DB=balik" \
    "-e POSTGRES_PASSWORD=balik -v $2:/var/lib/postgresql/data $3 postgres -c timescaledb.telemetry_level=off > /dev/null"
}
ts_manage() {  # ts_manage HOST: manage.py of the project's image against the database container HOST, as balik
  echo "docker run --rm -i --network tsmove-net -e DB_HOST=$1 -e DB_PORT=5432 -e DJANGO_DEBUG=1 balik-web:ci python manage.py"
}
ts_wait() {  # ts_wait NAME [first]: the server answers (a first start makes the database on a server of its own first)
  if [ "${2:-}" = first ]; then
    for _ in $(seq 1 120); do docker logs "$1" 2>&1 | grep -q 'init process complete' && break; sleep 2; done
  fi
  for _ in $(seq 1 60); do docker exec "$1" pg_isready -q -U balik && return 0; sleep 2; done
  echo "FAIL: $1 did not start"; docker logs --tail 30 "$1"; exit 1
}
ts_sql() { docker exec -i "$1" psql -X -q -U balik -d balik -v ON_ERROR_STOP=1 -At "${@:2}"; }
ts_files() { (cd "$1" && sha256sum -- * | sort); }

tsmove() {
  say "the development database as it is: the old image (2.17.2), every migration of the project, real data"
  docker network create tsmove-net > /dev/null
  docker volume create tsmove-data > /dev/null
  sh -c "$(ts_run tsmove tsmove-data "$TS_OLD")"
  ts_wait tsmove first
  sh -c "$(ts_manage tsmove) \"\$@\"" manage migrate --no-input -v 0
  say "water samples on two days (a chunk of a hypertable with the revision triggers), by the write path"
  sh -c "$(ts_manage tsmove) \"\$@\"" manage shell -c '
from datetime import timedelta
from decimal import Decimal as D
from django.contrib.auth import get_user_model
from django.utils import timezone
from farm.models import ProductionDepartment, Site
from farm.tests.helpers import point_of
from farm.tests.test_stock import make_unit
from farm.water import services
# the writer may record (farm/water/services.py asks who may since a039d48c): an account with every right, no password
user = get_user_model().objects.create_superuser("tsmove", "tsmove@farm.ci.invalid", None)
hall = ProductionDepartment.objects.create(site=Site.objects.create(name="Move", code="MV"), name="Hall A", code="HA")
point = point_of(make_unit("T-01", hall))
for days in (1, 20):
    services.record(user, point=point, measured_at=timezone.now() - timedelta(days=days), source="manual",
                    values={"temperature_c": D("12.0")})
'
  say "readings for 60 days, the chunks older than 14 days compressed, every continuous aggregate refreshed"
  ts_sql tsmove <<'SQL'
INSERT INTO sensors_reading (channel_no, ts, value)
  SELECT 1, ts, 7 + random() FROM generate_series(now() - interval '60 days', now(), interval '10 minutes') AS ts;
SELECT count(compress_chunk(c, if_not_compressed => true)) FROM show_chunks('sensors_reading', older_than => interval '14 days') AS c;
SELECT format('CALL refresh_continuous_aggregate(%L, NULL, NULL)', format('%I.%I', view_schema, view_name))
  FROM timescaledb_information.continuous_aggregates
\gexec
SQL
  ts_sql tsmove -c "SELECT 'chunk triggers', count(*) FROM pg_trigger t JOIN pg_inherits i ON i.inhrelid = t.tgrelid
    WHERE i.inhparent = 'water_measurements'::regclass AND t.tgname LIKE 'core\_rev\_%'"
  say "two copies of it, taken before the move: the stopped move (tshalf), the server recreated first (tsearly)"
  docker stop tsmove > /dev/null
  for copy in tsmove-half tsmove-early; do
    docker volume create "$copy" > /dev/null
    docker run --rm -v tsmove-data:/from:ro -v "$copy:/to" --entrypoint sh "$TS_OLD" -c 'cp -a /from/. /to/'
  done
  docker start tsmove > /dev/null
  ts_wait tsmove
  mkdir -p "$T/tsmove"
  local before
  export DB_EXEC="docker exec -i tsmove" MANAGE
  export RECREATE="docker rm -f tsmove > /dev/null && $(ts_run tsmove tsmove-data "$TS_NEW")"
  MANAGE=$(ts_manage tsmove)

  say "another database of the server with a water chunk (a stale copy): the move refuses it by name, writing nothing"
  # a template has no other session: none may come in (the job scheduler would), the ones there are ended
  ts_sql tsmove -d postgres -c 'ALTER DATABASE balik WITH ALLOW_CONNECTIONS false' \
    -c "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE datname = 'balik'" \
    -c 'CREATE DATABASE stale_copy TEMPLATE balik' -c 'ALTER DATABASE balik WITH ALLOW_CONNECTIONS true' > /dev/null
  if sh "$TS_MOVE" move "$T/tsmove" dev > "$T/tsmove-other.out" 2>&1; then
    cat "$T/tsmove-other.out"; echo "FAIL: a move ran with another database holding revision triggers"; exit 1
  fi
  cat "$T/tsmove-other.out"
  grep -q 'stale_copy' "$T/tsmove-other.out" || { echo "FAIL: the refusal does not name the database"; exit 1; }
  [ -z "$(ls "$T/tsmove")" ] || { echo "FAIL: the refused move wrote a file"; ls -l "$T/tsmove"; exit 1; }
  ts_sql tsmove -d postgres -c 'DROP DATABASE stale_copy WITH (FORCE)' > /dev/null

  say "a dump that fails half-way: its file is named .partial, no dump or facts that look whole, no record"
  printf '%s\n' 'if [ "$1" = pg_dump ]; then docker exec -i tsmove "$@" | head -c 100000; exit 1; fi' \
    'exec docker exec -i tsmove "$@"' > "$T/dump-fails.sh"
  if DB_EXEC="sh $T/dump-fails.sh" sh "$TS_MOVE" move "$T/tsmove" dev > "$T/tsmove-dump.out" 2>&1; then
    cat "$T/tsmove-dump.out"; echo "FAIL: a move ran over a failed dump"; exit 1
  fi
  tail -n 5 "$T/tsmove-dump.out"
  ls -l "$T/tsmove"
  ls "$T"/tsmove | grep -q '\.dump\.partial$' || { echo "FAIL: no .partial dump"; exit 1; }
  if ls "$T"/tsmove | grep -Eq '\.(dump|facts|roles\.sql)$|unfinished'; then
    echo "FAIL: a failed dump left a whole-looking file or a record"; exit 1
  fi
  rm -f "$T"/tsmove/*.partial

  say "the move, exactly as docs/ops/upgrade.md runs it (with this runner's container names)"
  sh "$TS_MOVE" move "$T/tsmove" dev
  ls -l "$T/tsmove"
  [ "$(ts_sql tsmove -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")" = 2.32.1 ] \
    || { echo "FAIL: not on 2.32.1"; exit 1; }
  ls "$T"/tsmove | grep -Eq '^dev-before-[0-9]{8}-[0-9]{6}\.dump$' || { echo "FAIL: the dump is not named to the second"; exit 1; }
  for kind in facts roles.sql; do
    ls "$T"/tsmove | grep -Eq "^dev-before-[0-9]{8}-[0-9]{6}\.$kind\$" || { echo "FAIL: no $kind beside the dump"; exit 1; }
  done
  ls "$T"/tsmove | grep -Eq '^dev-after-[0-9]{8}-[0-9]{6}\.dump$' || { echo "FAIL: no dump on the new release"; exit 1; }
  if ls "$T"/tsmove | grep -q unfinished; then echo "FAIL: a finished move left its record"; exit 1; fi
  say "the move again, on the moved database: refused, nothing written"
  local before
  before=$(ts_files "$T/tsmove")
  if DB_EXEC="docker exec -i tsmove" RECREATE=false MANAGE="$(ts_manage tsmove)" \
      sh "$TS_MOVE" move "$T/tsmove" dev > "$T/tsmove-again.out" 2>&1; then
    cat "$T/tsmove-again.out"; echo "FAIL: a second move ran"; exit 1
  fi
  cat "$T/tsmove-again.out"
  grep -q 'already' "$T/tsmove-again.out" || { echo "FAIL: the refusal does not say why"; exit 1; }
  [ "$before" = "$(ts_files "$T/tsmove")" ] || { echo "FAIL: the refused move wrote or changed a file"; exit 1; }
}

tsback() {
  local dump facts
  dump=$(ls "$T"/tsmove/dev-before-*.dump)
  facts="${dump%.dump}.facts"
  say "the way back, as upgrade.md says: the database stopped first"
  docker stop tsmove > /dev/null
  say "a way back without room for its copy on Docker's disk: refused first, no volume, no container"
  if DB_EXEC=unused MANAGE="$(ts_manage tsmove)" BACK_NETWORK=tsmove-net BACK_ALIAS=tsmove BACK_ROOM_FACTOR=100000000 \
      sh "$TS_MOVE" back "$dump" "$facts" "$TS_OLD" "$TS_NEW" tsmove-back-room > "$T/tsback-room.out" 2>&1; then
    cat "$T/tsback-room.out"; echo "FAIL: a way back ran without the room it needs"; exit 1
  fi
  cat "$T/tsback-room.out"
  grep -q 'room' "$T/tsback-room.out" || { echo "FAIL: the refusal does not say why"; exit 1; }
  if docker volume inspect tsmove-back-room > /dev/null 2>&1 || [ -n "$(docker ps -aq --filter name='^timescaledb-back$')" ]; then
    echo "FAIL: the refused way back made a volume or a container"; exit 1
  fi
  say "a way back that fails (a dump cut short) removes its container and says how to remove the new volume"
  mkdir -p "$T/tsback-bad"
  head -c 200000 "$dump" > "$T/tsback-bad/cut.dump"
  cp "${dump%.dump}.roles.sql" "$T/tsback-bad/cut.roles.sql" 2>/dev/null || true
  cp "$facts" "$T/tsback-bad/cut.facts"
  if DB_EXEC=unused MANAGE="$(ts_manage tsmove)" BACK_NETWORK=tsmove-net BACK_ALIAS=tsmove \
      sh "$TS_MOVE" back "$T/tsback-bad/cut.dump" "$T/tsback-bad/cut.facts" "$TS_OLD" "$TS_NEW" tsmove-back-bad \
      > "$T/tsback-bad.out" 2>&1; then
    cat "$T/tsback-bad.out"; echo "FAIL: a cut dump was restored"; exit 1
  fi
  tail -n 15 "$T/tsback-bad.out"
  [ -z "$(docker ps -aq --filter name='^timescaledb-back$')" ] || { echo "FAIL: timescaledb-back was left"; exit 1; }
  grep -q 'docker volume rm tsmove-back-bad' "$T/tsback-bad.out" || { echo "FAIL: no word on the new volume"; exit 1; }
  docker volume rm tsmove-back-bad > /dev/null
  say "the way back from the old release's dump: the roles first, the restore, the new image, the update, the checks"
  DB_EXEC=unused MANAGE="$(ts_manage tsmove)" BACK_NETWORK=tsmove-net BACK_ALIAS=tsmove \
    sh "$TS_MOVE" back "$dump" "$facts" "$TS_OLD" "$TS_NEW" tsmove-back
  say "the restored volume under the development stack's own settings: balik signs in with its own password"
  sh -c "$(ts_run tsmove-restored tsmove-back "$TS_NEW")"
  ts_wait tsmove-restored
  sh -c "$(ts_manage tsmove-restored) \"\$@\"" manage migrate --check
  sh -c "$(ts_manage tsmove-restored) \"\$@\"" manage check --database default --fail-level WARNING
  [ "$(ts_sql tsmove-restored -c "SELECT count(*) FROM pg_roles WHERE rolname = 'sensors_ingest'")" = 1 ] \
    || { echo "FAIL: sensors_ingest is not there"; exit 1; }
  echo "water samples: $(ts_sql tsmove-restored -c 'SELECT count(*) FROM water_measurements')"
  [ "$(ts_sql tsmove-restored -c 'SELECT count(*) FROM water_measurements')" = 2 ] || { echo "FAIL: samples lost"; exit 1; }
}

tshalf() {
  local manage broken before
  sh -c "$(ts_run tsmove-half tsmove-half "$TS_OLD")"
  ts_wait tsmove-half
  manage=$(ts_manage tsmove-half)
  broken="case \"\$1\" in core_rev_repair) echo 'injected: the repair stops here' >&2; exit 1;; esac; $manage"
  export DB_EXEC="docker exec -i tsmove-half"
  export RECREATE="docker rm -f tsmove-half > /dev/null && $(ts_run tsmove-half tsmove-half "$TS_NEW")"
  say "a move that stops half-way (after the update, at the repair of the revision triggers)"
  mkdir -p "$T/tshalf"
  if MANAGE="$broken" sh "$TS_MOVE" move "$T/tshalf" half > "$T/tshalf-1.out" 2>&1; then
    cat "$T/tshalf-1.out"; echo "FAIL: the injected stop did not stop the move"; exit 1
  fi
  tail -n 12 "$T/tshalf-1.out"
  grep -q "resume $T/tshalf half" "$T/tshalf-1.out" || { echo "FAIL: the stop does not say how to go on"; exit 1; }
  say "the next move sees the half-moved database, says how to go on, and writes nothing"
  before=$(ts_files "$T/tshalf")
  if MANAGE="$manage" sh "$TS_MOVE" move "$T/tshalf" half > "$T/tshalf-2.out" 2>&1; then
    cat "$T/tshalf-2.out"; echo "FAIL: a move ran over a half-moved database"; exit 1
  fi
  cat "$T/tshalf-2.out"
  grep -q "resume $T/tshalf half" "$T/tshalf-2.out" || { echo "FAIL: the refusal does not say how to go on"; exit 1; }
  [ "$before" = "$(ts_files "$T/tshalf")" ] || { echo "FAIL: the refused move wrote or changed a file"; exit 1; }
  say "resume, with no time for the jobs (JOB_WAIT_SECONDS=0): the move is done but its step 8 stops it"
  if JOB_WAIT_SECONDS=0 MANAGE="$manage" sh "$TS_MOVE" resume "$T/tshalf" half > "$T/tshalf-4.out" 2>&1; then
    cat "$T/tshalf-4.out"; echo "FAIL: the jobs were not waited for and the move passed"; exit 1
  fi
  tail -n 12 "$T/tshalf-4.out"
  grep -q "close $T/tshalf half" "$T/tshalf-4.out" || { echo "FAIL: the stop at the checks does not name close"; exit 1; }
  say "close: the checks again, with time; they pass, the record is removed and the closing is logged"
  MANAGE="$manage" sh "$TS_MOVE" close "$T/tshalf" half
  if ls "$T"/tshalf | grep -q unfinished; then echo "FAIL: a finished move left its record"; exit 1; fi
  ls "$T"/tshalf | grep -Eq '^half-before-[0-9]{8}-[0-9]{6}\.closed-[0-9]{8}-[0-9]{6}\.log$' \
    || { echo "FAIL: the closing is not logged"; ls -l "$T/tshalf"; exit 1; }
  sh -c "$manage \"\$@\"" manage check --database default --fail-level WARNING
  if MANAGE="$manage" sh "$TS_MOVE" resume "$T/tshalf" half > "$T/tshalf-3.out" 2>&1; then
    cat "$T/tshalf-3.out"; echo "FAIL: a second resume ran"; exit 1
  fi
  cat "$T/tshalf-3.out"
}

tsearly() {
  local manage dump
  say "the server recreated on the new image before the move (a docker compose up after the merge): old extension, no record"
  sh -c "$(ts_run tsmove-early tsmove-early "$TS_NEW")"
  ts_wait tsmove-early
  manage=$(ts_manage tsmove-early)
  [ "$(ts_sql tsmove-early -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")" = 2.17.2 ] \
    || { echo "FAIL: the setup is not the case"; exit 1; }
  say "the move handles it: the dump on the extension's own release, then the rest"
  mkdir -p "$T/tsearly"
  DB_EXEC="docker exec -i tsmove-early" MANAGE="$manage" \
    RECREATE="docker rm -f tsmove-early > /dev/null && $(ts_run tsmove-early tsmove-early "$TS_NEW")" \
    sh "$TS_MOVE" move "$T/tsearly" early | tee "$T/tsearly.out"
  grep -q 'already runs' "$T/tsearly.out" || { echo "FAIL: the case is not named"; exit 1; }
  if ls "$T"/tsearly | grep -q unfinished; then echo "FAIL: a finished move left its record"; exit 1; fi
  say "its dump is an old-release dump: the way back restores it on the old image"
  docker stop tsmove-early > /dev/null
  dump=$(ls "$T"/tsearly/early-before-*.dump)
  DB_EXEC=unused MANAGE="$manage" BACK_NETWORK=tsmove-net BACK_ALIAS=tsmove-early \
    sh "$TS_MOVE" back "$dump" "${dump%.dump}.facts" "$TS_OLD" "$TS_NEW" tsmove-early-back
}

logs() {
  "${DC[@]}" ps -a || true
  "${DC[@]}" logs --tail 60 || true
  "${RC[@]}" logs --tail 40 2>/dev/null || true
  docker logs --tail 40 farm-pitr 2>/dev/null || true
}

down() {
  docker rm -f -v tsmove tsmove-half tsmove-early tsmove-restored timescaledb-back > /dev/null 2>&1 || true
  docker volume rm tsmove-data tsmove-half tsmove-early tsmove-early-back tsmove-back tsmove-back-bad tsmove-back-room > /dev/null 2>&1 || true
  docker network rm tsmove-net > /dev/null 2>&1 || true
  docker rm -f -v farm-pitr > /dev/null 2>&1 || true
  docker volume rm farm-pitr-data > /dev/null 2>&1 || true
  "${RC[@]}" down -v --remove-orphans || true
  "${DC[@]}" --profile ops --profile cloudflare down -v --remove-orphans || true
}

for step in "$@"; do
  "$step"
done
