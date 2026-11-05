#!/bin/sh
# Starts Mosquitto and reloads it (SIGHUP) when /mosquitto/auth/passwd or acl changes: `manage.py sensor_broker_sync`
# rewrites them (atomically: temp file plus rename) and has no way to signal another container. Spike S0f: a reload
# keeps connected clients whose credential is unchanged and cuts off a removed one.
set -eu
AUTH=/mosquitto/auth
mkdir -p "$AUTH" /mosquitto/data
[ -f "$AUTH/passwd" ] || : > "$AUTH/passwd"
[ -f "$AUTH/acl" ] || printf '# written by manage.py sensor_broker_sync\n' > "$AUTH/acl"
chown -R mosquitto:mosquitto /mosquitto/data 2>/dev/null || true
owned() { chown mosquitto:mosquitto "$AUTH/passwd" "$AUTH/acl" 2>/dev/null || true; chmod 0700 "$AUTH/passwd" "$AUTH/acl" 2>/dev/null || true; }
owned

mosquitto -c /mosquitto/config/mosquitto.conf &
PID=$!
trap 'kill -TERM "$PID" 2>/dev/null; wait "$PID"; exit $?' TERM INT

sig() { cat "$AUTH/passwd" "$AUTH/acl" 2>/dev/null | md5sum; }
last=$(sig)
while kill -0 "$PID" 2>/dev/null; do
  sleep 5 &
  wait $! || true
  now=$(sig)
  if [ "$now" != "$last" ]; then
    echo "entrypoint: passwd or acl changed, reloading"
    owned
    kill -HUP "$PID" 2>/dev/null || true
    last=$now
  fi
done
wait "$PID"
