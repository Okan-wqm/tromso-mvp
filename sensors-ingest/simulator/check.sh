#!/usr/bin/env bash
# Runs the field simulator against a throwaway broker and checks it (simulator/check.js). Every name carries this
# run's own id (simcheck-<id>-*), so runs at the same time never share a broker, simulator or network,
# removed at the end. Needs docker.
set -euo pipefail
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1
win() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
MOSQ=eclipse-mosquitto:2.0.23@sha256:6a332cc7a8dbe011cbc076180cbb76b37c6f0f55809682ea08e7980ef0112ad9
NODERED=nodered/node-red:4.0.9@sha256:0b295b3a14c512548567ca99db631bc37b23bfc79fd009ee8248a610fafdb4b5
RUN=simcheck-$(head -c 6 /dev/urandom | od -An -tx1 | tr -d " \n")
NET=$RUN-net
cleanup() {
  docker rm -f -v $RUN-broker $RUN-sim >/dev/null 2>&1 || true
  docker volume rm $RUN-auth >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
cleanup
trap cleanup EXIT
docker network create "$NET" >/dev/null
docker run --rm -v $RUN-auth:/mosquitto/auth "$MOSQ" sh -c '
  mosquitto_passwd -c -b /mosquitto/auth/passwd simulator sim-pw 2>/dev/null
  mosquitto_passwd -b /mosquitto/auth/passwd observer obs-pw 2>/dev/null
  printf "user simulator\ntopic write sim/#\nuser observer\ntopic read sim/#\n" > /mosquitto/auth/acl
  chown -R mosquitto:mosquitto /mosquitto/auth && chmod 0700 /mosquitto/auth/passwd /mosquitto/auth/acl'
docker run -d --name $RUN-broker --network "$NET" -v "$(win "$PWD/../mosquitto"):/mosquitto/config:ro" \
  -v $RUN-auth:/mosquitto/auth --tmpfs /mosquitto/data --entrypoint sh "$MOSQ" /mosquitto/config/entrypoint.sh >/dev/null
printf 'sim-pw\n' > "$PWD/.check-secret-$RUN"
trap 'rm -f "$PWD/.check-secret-$RUN"; cleanup' EXIT
docker run -d --name $RUN-sim --network "$NET" -e SIM_MQTT_HOST=$RUN-broker -e SIM_MQTT_USER=simulator \
  -e SIM_MQTT_PASSWORD_FILE=/run/secrets/sim_mqtt -v "$(win "$PWD/.check-secret-$RUN"):/run/secrets/sim_mqtt:ro" \
  -v "$(win "$PWD"):/sim:ro" --entrypoint bash "$NODERED" /sim/start.sh >/dev/null
for _ in $(seq 1 90); do
  docker logs $RUN-sim 2>&1 | grep -q "Started flows" && break
  [ "$(docker inspect -f "{{.State.Running}}" $RUN-sim)" = true ] || { docker logs $RUN-sim 2>&1 | tail -20; exit 1; }
  sleep 1
done
sleep 3
docker run --rm --network "$NET" -v "$(win "$PWD"):/sim:ro" -e BROKER=mqtt://$RUN-broker:1883 -e MQTT_USER=observer \
  -e MQTT_PASSWORD=obs-pw -e NODE_RED=http://$RUN-sim:1880 --entrypoint node "$NODERED" /sim/check.js || {
  docker logs $RUN-sim 2>&1 | tail -30; echo "--- broker"; docker logs $RUN-broker 2>&1 | tail -40; exit 1; }
