#!/usr/bin/env bash
# Runs the field simulator against a throwaway broker and checks it (simulator/check.js). Own names (simcheck-*),
# removed at the end. Needs docker.
set -euo pipefail
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1
win() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
MOSQ=eclipse-mosquitto:2.0.20@sha256:21421af7b32bf9ce508e9090c8eb13bb81f410ca778dc205506180a6f862d0eb
NODERED=nodered/node-red:4.0.9@sha256:0b295b3a14c512548567ca99db631bc37b23bfc79fd009ee8248a610fafdb4b5
NET=simcheck-net
cleanup() {
  docker rm -f simcheck-broker simcheck-sim >/dev/null 2>&1 || true
  docker volume rm simcheck-auth >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
cleanup
trap cleanup EXIT
docker network create "$NET" >/dev/null
docker run --rm -v simcheck-auth:/mosquitto/auth "$MOSQ" sh -c '
  mosquitto_passwd -c -b /mosquitto/auth/passwd simulator sim-pw 2>/dev/null
  mosquitto_passwd -b /mosquitto/auth/passwd observer obs-pw 2>/dev/null
  printf "user simulator\ntopic write sim/#\nuser observer\ntopic read sim/#\n" > /mosquitto/auth/acl
  chown -R mosquitto:mosquitto /mosquitto/auth && chmod 0700 /mosquitto/auth/passwd /mosquitto/auth/acl'
docker run -d --name simcheck-broker --network "$NET" -v "$(win "$PWD/../mosquitto"):/mosquitto/config:ro" \
  -v simcheck-auth:/mosquitto/auth --tmpfs /mosquitto/data --entrypoint sh "$MOSQ" /mosquitto/config/entrypoint.sh >/dev/null
printf 'sim-pw\n' > "$PWD/.check-secret"
trap 'rm -f "$PWD/.check-secret"; cleanup' EXIT
docker run -d --name simcheck-sim --network "$NET" -e SIM_MQTT_HOST=simcheck-broker -e SIM_MQTT_USER=simulator \
  -e SIM_MQTT_PASSWORD_FILE=/run/secrets/sim_mqtt -v "$(win "$PWD/.check-secret"):/run/secrets/sim_mqtt:ro" \
  -v "$(win "$PWD"):/sim:ro" --entrypoint bash "$NODERED" /sim/start.sh >/dev/null
for _ in $(seq 1 90); do
  docker logs simcheck-sim 2>&1 | grep -q "Started flows" && break
  [ "$(docker inspect -f "{{.State.Running}}" simcheck-sim)" = true ] || { docker logs simcheck-sim 2>&1 | tail -20; exit 1; }
  sleep 1
done
sleep 3
docker run --rm --network "$NET" -v "$(win "$PWD"):/sim:ro" -e BROKER=mqtt://simcheck-broker:1883 -e MQTT_USER=observer \
  -e MQTT_PASSWORD=obs-pw -e NODE_RED=http://simcheck-sim:1880 --entrypoint node "$NODERED" /sim/check.js || {
  docker logs simcheck-sim 2>&1 | tail -30; echo "--- broker"; docker logs simcheck-broker 2>&1 | tail -40; exit 1; }
