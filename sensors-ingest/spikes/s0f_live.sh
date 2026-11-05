#!/usr/bin/env bash
# S0f live: a broker that reads a passwd file written by Python hashlib accepts the right password, refuses a wrong one,
# and after SIGHUP picks up an added and a removed user without dropping a connected client.
# Needs docker; uses its own network and container names (s0f-*), removes them at the end.
set -euo pipefail
cd "$(dirname "$0")"
W=$(mktemp -d)
trap 'docker rm -f s0f-broker s0f-sub >/dev/null 2>&1 || true; docker network rm s0f-net >/dev/null 2>&1 || true; rm -rf "$W"' EXIT
PY="docker run --rm -v $(cygpath -w "$PWD" 2>/dev/null || echo "$PWD"):/s python:3.12-slim python -I /s/s0f_mosquitto_hash.py"
export MSYS_NO_PATHCONV=1
{ $PY line ingest ingest-pw; $PY line dev1 dev1-pw; } > "$W/passwd"
cat > "$W/acl" <<ACL
user ingest
topic read #
user dev1
topic write farm/dev1/#
user dev2
topic write farm/dev2/#
ACL
cat > "$W/mosquitto.conf" <<CONF
listener 1883
allow_anonymous false
password_file /mosquitto/config/passwd
acl_file /mosquitto/config/acl
CONF
WIN=$(cygpath -w "$W" 2>/dev/null || echo "$W")
docker network create s0f-net >/dev/null
docker run -d --name s0f-broker --network s0f-net -v "$WIN:/mosquitto/config" eclipse-mosquitto:2.0.20 >/dev/null
sleep 1
PUB="docker run --rm --network s0f-net eclipse-mosquitto:2.0.20 mosquitto_pub -h s0f-broker -q 1"
docker run -d --name s0f-sub --network s0f-net eclipse-mosquitto:2.0.20 \
  mosquitto_sub -h s0f-broker -u ingest -P ingest-pw -i ingest -c -q 1 -t 'farm/#' -v >/dev/null
sleep 1
ok() { echo "PASS: $*"; }
$PUB -u dev1 -P dev1-pw -t farm/dev1/x -m one && ok "python-hashed password accepted"
if $PUB -u dev1 -P wrong -t farm/dev1/x -m bad 2>/dev/null; then echo "FAIL: wrong password accepted"; exit 1; fi
ok "wrong password refused"
if $PUB -u dev2 -P dev2-pw -t farm/dev2/x -m early 2>/dev/null; then echo "FAIL: unknown user accepted"; exit 1; fi
ok "user not yet in the file refused"
# add dev2, remove dev1, reload
{ $PY line ingest ingest-pw; $PY line dev2 dev2-pw; } > "$W/passwd"
docker kill -s HUP s0f-broker >/dev/null; sleep 1
$PUB -u dev2 -P dev2-pw -t farm/dev2/x -m two && ok "added user accepted after SIGHUP"
if $PUB -u dev1 -P dev1-pw -t farm/dev1/x -m gone 2>/dev/null; then echo "FAIL: removed user still accepted"; exit 1; fi
ok "removed user refused after SIGHUP"
sleep 1
OUT=$(docker logs s0f-sub)
echo "$OUT"
[ "$(docker inspect -f '{{.State.Running}}' s0f-sub)" = true ] && ok "subscriber still connected after SIGHUP"
echo "$OUT" | grep -q 'farm/dev1/x one' && echo "$OUT" | grep -q 'farm/dev2/x two' && ok "subscriber received before and after reload"
if echo "$OUT" | grep -q 'early\|bad\|gone'; then echo "FAIL: refused publish delivered"; exit 1; fi
# A client whose credential is removed while it is connected: is it cut off by the reload?
{ $PY line ingest ingest-pw; $PY line dev2 dev2-pw; $PY line dev3 dev3-pw; } > "$W/passwd"
printf 'user ingest\ntopic readwrite #\nuser dev3\ntopic readwrite farm/dev3/#\n' > "$W/acl"
docker kill -s HUP s0f-broker >/dev/null; sleep 1
docker run -d --name s0f-dev3 --network s0f-net eclipse-mosquitto:2.0.20 \
  mosquitto_sub -h s0f-broker -u dev3 -P dev3-pw -i dev3 -q 1 -t 'farm/dev3/#' -v >/dev/null
sleep 1
$PUB -u ingest -P ingest-pw -t farm/dev3/x -m before-removal
{ $PY line ingest ingest-pw; } > "$W/passwd"; printf 'user ingest\ntopic readwrite #\n' > "$W/acl"
docker kill -s HUP s0f-broker >/dev/null; sleep 1
$PUB -u ingest -P ingest-pw -t farm/dev3/x -m after-removal; sleep 1
D3=$(docker logs s0f-dev3); RUN=$(docker inspect -f '{{.State.Running}}' s0f-dev3); docker rm -f s0f-dev3 >/dev/null
echo "removed-while-connected client: running=$RUN, received: $(echo $D3)"
if [ "$RUN" = true ] && echo "$D3" | grep -q after-removal; then
  echo "FINDING: SIGHUP does not disconnect a client whose credential was removed; it keeps its session and ACL view"
else
  echo "FINDING: a client whose credential was removed loses access at SIGHUP (running=$RUN)"
fi
