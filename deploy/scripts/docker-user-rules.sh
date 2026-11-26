#!/bin/sh
# The two DOCKER-USER rules that close the way out of the proxy's and the broker's networks (docs/ops/install.md, "No way
# out for the proxy and the broker"). Those networks are not masqueraded, which stops only the return path: their
# packets would still leave the server with their private source address. These rules drop every NEW connection from
# them to anywhere outside their own subnet; answers to connections coming in are not NEW, so the published ports keep
# working.
#
#   sh docker-user-rules.sh [FARM_ENV]           put in each rule that is not there (iptables -C before -I: never a
#                                                duplicate, so it runs at every Docker start)
#   sh docker-user-rules.sh --check [FARM_ENV]   exit 1, naming it, when a rule is missing (the reboot test, the
#                                                go-live checklist)
#
# The subnets are farm.env's EDGE_SUBNET and MQTT_EDGE_SUBNET (FARM_ENV, default /opt/balik/deploy/farm.env), else the
# defaults of deploy/compose.yml. As root, on the host. The go-live stack workflow runs it (step network).
set -eu
check=0
if [ "${1:-}" = --check ]; then check=1; shift; fi
env=${1:-/opt/balik/deploy/farm.env}
setting() { [ -f "$env" ] && sed -n "s/^$1=//p" "$env" | tail -n 1; }
front=$(setting EDGE_SUBNET || true)
edge=$(setting MQTT_EDGE_SUBNET || true)
front=${front:-172.31.250.0/24}
edge=${edge:-172.31.252.0/24}
missing=0
for net in "$front" "$edge"; do
  if iptables -C DOCKER-USER -s "$net" ! -d "$net" -m conntrack --ctstate NEW -j DROP 2> /dev/null; then
    echo "ok    DOCKER-USER drops new connections from $net to outside it"
  elif [ "$check" = 1 ]; then
    echo "FAIL  DOCKER-USER has no rule for $net: the way out of its network is open"
    missing=1
  else
    iptables -I DOCKER-USER -s "$net" ! -d "$net" -m conntrack --ctstate NEW -j DROP
    echo "added DOCKER-USER drops new connections from $net to outside it"
  fi
done
exit "$missing"
