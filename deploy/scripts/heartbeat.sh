#!/bin/sh
# The farm server's heartbeat to an outside monitor (docs/ops/monitoring.md). Run on the host every 5 minutes by a
# systemd timer, from deploy/. It checks what must never fail silently, prints one line per check, and:
#   - every check passes: asks HEARTBEAT_URL (the monitor's ping address, kept in farm.env), so the monitor hears the
#     server is well; when the pings stop (the server, its network, Docker or this script are down) the monitor alerts;
#   - a check fails: asks HEARTBEAT_FAIL_URL if set (most monitors take <ping address>/fail), so the alert comes at once,
#     with the failing lines as the request's body.
# The ping goes from the server straight to the monitor, past neither the proxy nor Cloudflare. Exit 1 on a failure.
#
# Checks (each threshold from farm.env):
#   services    every service of the stack running and healthy (release: exited 0)
#   disk        the disk Docker keeps its volumes on below HEARTBEAT_DISK_PERCENT (80) %
#   certificates  the console's and the broker's certificate valid for HEARTBEAT_CERT_DAYS (21) days more
#   backup      the backup service healthy: its last dump, base backup and ship done and none overdue, its archiver ok
#   sensors     a reading stored within HEARTBEAT_SILENCE_MINUTES (30); 0 turns it off (a farm without sensors yet)
set -u
cd "$(dirname "$0")/.."
ENV_FILE=${ENV_FILE:-farm.env}
COMPOSE=${COMPOSE:-docker compose --env-file $ENV_FILE}
setting() {  # setting NAME DEFAULT: from the environment, else from farm.env, else the default
  value=$(printenv "$1" 2>/dev/null || true)
  if [ -z "$value" ] && [ -f "$ENV_FILE" ]; then value=$(sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1); fi
  echo "${value:-$2}"
}
SECRETS_DIR=$(setting SECRETS_DIR ./secrets)
DISK_PERCENT=$(setting HEARTBEAT_DISK_PERCENT 80)
CERT_DAYS=$(setting HEARTBEAT_CERT_DAYS 21)
SILENCE_MINUTES=$(setting HEARTBEAT_SILENCE_MINUTES 30)
URL=$(setting HEARTBEAT_URL '')
FAIL_URL=$(setting HEARTBEAT_FAIL_URL '')
report=""
failed=0
ok() { report="${report}ok    $*
"; }
bad() { report="${report}FAIL  $*
"; failed=1; }

states=$($COMPOSE ps -a --format '{{.Service}} {{.State}} {{.Health}} {{.ExitCode}}' 2>&1) || bad "compose: $states"
for service in db web jobs proxy mosquitto ingest backup; do
  line=$(echo "$states" | grep "^$service " | head -n 1)
  case "$line" in
    "$service running healthy"*) ok "$service healthy" ;;
    '') bad "$service is not there" ;;
    *) bad "$service: $line" ;;
  esac
done
case "$(echo "$states" | grep '^release ' | head -n 1)" in
  'release exited '*' 0') ok "release exited 0" ;;
  *) bad "release did not end well: $(echo "$states" | grep '^release ')" ;;
esac

root=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)
used=$(df -P "$root" | awk 'NR == 2 {sub("%", "", $5); print $5}')
if [ -n "$used" ] && [ "$used" -lt "$DISK_PERCENT" ]; then ok "disk $used % used ($root)"; else bad "disk ${used:-?} % used ($root), limit $DISK_PERCENT %"; fi

for cert in tls/fullchain.pem mqtt/server.crt; do
  if [ ! -r "$SECRETS_DIR/$cert" ]; then bad "certificate $cert cannot be read"; continue; fi
  if openssl x509 -checkend $(( CERT_DAYS * 86400 )) -noout -in "$SECRETS_DIR/$cert" > /dev/null; then
    ok "certificate $cert valid for $CERT_DAYS days more"
  else
    bad "certificate $cert ends within $CERT_DAYS days ($(openssl x509 -enddate -noout -in "$SECRETS_DIR/$cert"))"
  fi
done

backup=$($COMPOSE exec -T backup sh /usr/local/lib/balik-backup/agent.sh health 2>&1)
if [ "$backup" = ok ]; then ok "backup: last dump, base backup and ship done, archiver ok"; else bad "backup: $backup"; fi

if [ "$SILENCE_MINUTES" -gt 0 ]; then
  age=$($COMPOSE exec -T db sh -c 'PGPASSWORD=$(head -n 1 /run/secrets/db_backup_password) psql -X -At -h 127.0.0.1 \
    -U balik_backup -d "$POSTGRES_DB" -c "SELECT coalesce(floor(extract(epoch FROM now() - max(ts)) / 60)::int, -1)
    FROM sensors_reading WHERE ts > now() - interval '\''7 days'\''"' 2>&1)
  case "$age" in
    -1) bad "sensors: no reading stored for 7 days" ;;
    ''|*[!0-9]*) bad "sensors: the database could not be asked ($age)" ;;
    *) if [ "$age" -le "$SILENCE_MINUTES" ]; then ok "sensors: last reading $age min ago"
       else bad "sensors: last reading $age min ago, limit $SILENCE_MINUTES min"; fi ;;
  esac
fi

printf '%s' "$report"
if [ "$failed" = 0 ]; then
  [ -z "$URL" ] || curl -fsS -m 10 --retry 3 -o /dev/null "$URL" || echo "the heartbeat could not reach the monitor"
  echo "heartbeat: every check passed"
else
  [ -z "$FAIL_URL" ] || printf '%s' "$report" | curl -fsS -m 10 --retry 3 -o /dev/null --data-binary @- "$FAIL_URL" \
    || echo "the failure could not be reported to the monitor"
  echo "heartbeat: a check failed"
  exit 1
fi
