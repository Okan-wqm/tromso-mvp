#!/bin/bash
# Node-RED container start for the field simulator: the flows come from the repository (read-only /sim), the broker
# login from SIM_MQTT_USER and the secret file (never from the flows), written to /data/flows_cred.json in clear text
# inside the container only (credentialSecret false: nothing to decrypt, nothing stored in the repository).
set -euo pipefail
: "${SIM_MQTT_HOST:?SIM_MQTT_HOST}" "${SIM_MQTT_USER:?SIM_MQTT_USER}"
SECRET_FILE=${SIM_MQTT_PASSWORD_FILE:-/run/secrets/sim_mqtt}
cp /sim/flows.json /data/flows.json
cp /sim/settings.js /data/settings.js
SECRET_FILE="$SECRET_FILE" node -e '
const fs = require("fs");
const pw = fs.readFileSync(process.env.SECRET_FILE, "utf8").split("\n")[0];
fs.writeFileSync("/data/flows_cred.json", JSON.stringify({ sim_broker: { user: process.env.SIM_MQTT_USER, password: pw } }), { mode: 0o600 });
'
cd /usr/src/node-red
exec ./entrypoint.sh
