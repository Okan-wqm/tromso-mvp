#!/usr/bin/env bash
# S0e live: Mosquitto 2.0.20 (max_inflight_messages 5000) and the rumqttc manual-ack example on one docker network.
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
win() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
W=$(mktemp -d)
trap 'docker rm -f s0e-broker >/dev/null 2>&1 || true; docker network rm s0e-net >/dev/null 2>&1 || true; rm -rf "$W"' EXIT
printf 'listener 1883\nallow_anonymous true\nmax_inflight_messages 5000\nmax_queued_messages 100000\n' > "$W/mosquitto.conf"
docker network create s0e-net >/dev/null
docker run -d --name s0e-broker --network s0e-net -v "$(win "$W"):/mosquitto/config" eclipse-mosquitto:2.0.20 >/dev/null
sleep 1
docker run --rm --network s0e-net -v "$(win "$PWD"):/w" -v si-cargo:/usr/local/cargo/registry -v si-target:/t \
  -e CARGO_TARGET_DIR=/t/target -e BROKER=s0e-broker -w /w rust:1.88.0-slim-bookworm \
  cargo run -q --example s0e_manual_ack
