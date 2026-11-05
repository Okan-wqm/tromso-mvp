#!/bin/bash
# Node-RED container start for the field simulator: the flows come from the repository (read-only /sim), the broker
# logins from the environment and secret files (never from the flows), written to /data/flows_cred.json in clear text
# inside the container only (credentialSecret false: nothing to decrypt, nothing stored in the repository).
#   field devices (tab "Field simulator"): SIM_MQTT_USER and SIM_MQTT_PASSWORD_FILE
#   farm (tab "Farm"), its own credential:  SIM_FARM_USER and SIM_FARM_PASSWORD_FILE (the demo-simulator secret that
#                                           manage.py sensors_demo_setup --secret-file wrote); absent: the farm idles
set -euo pipefail
: "${SIM_MQTT_HOST:?SIM_MQTT_HOST}" "${SIM_MQTT_USER:?SIM_MQTT_USER}"
cp /sim/flows.json /data/flows.json
cp /sim/settings.js /data/settings.js
SECRET_FILE=${SIM_MQTT_PASSWORD_FILE:-/run/secrets/sim_mqtt} FARM_FILE=${SIM_FARM_PASSWORD_FILE:-/run/secrets/sim_farm} node -e '
const fs = require("fs");
const first = (f) => {
  try { return fs.readFileSync(f, "utf8").split("\n")[0]; } catch (e) {
    if (e.code !== "ENOENT") console.error("simulator: cannot read " + f + " (" + e.code + "); the container runs as uid " + process.getuid() + " and must be able to read it");
    return null;
  }
};
const cred = { sim_broker: { user: process.env.SIM_MQTT_USER, password: first(process.env.SECRET_FILE) || "" } };
const farm = first(process.env.FARM_FILE);
if (farm) cred.farm_broker = { user: process.env.SIM_FARM_USER || "demo-simulator", password: farm };
fs.writeFileSync("/data/flows_cred.json", JSON.stringify(cred), { mode: 0o600 });
'
cd /usr/src/node-red
exec ./entrypoint.sh
