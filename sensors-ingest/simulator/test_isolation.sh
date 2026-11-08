#!/usr/bin/env bash
# Two simulator checks at the same time (a second run started while an earlier one is still going, e.g. one left
# behind by an interrupted shell): each must use only its own broker, simulator and MQTT session, so both pass.
set -uo pipefail
cd "$(dirname "$0")"
T=$(mktemp -d)
bash check.sh > "$T/a.log" 2>&1 &
A=$!
sleep 20
bash check.sh > "$T/b.log" 2>&1 &
B=$!
wait $A; RA=$?
wait $B; RB=$?
for r in a b; do echo "== run $r"; grep -E '^FAIL|ALL PASS' "$T/$r.log"; done
rm -rf "$T"
if [ $RA = 0 ] && [ $RB = 0 ]; then echo "PASS: two concurrent checks both green"; else echo "FAIL: concurrent checks interfere"; exit 1; fi
