"""Writes THIRD_PARTY from `cargo metadata --format-version 1 --locked` JSON (argument). tests/run.sh compares."""
import json, sys
m = json.load(open(sys.argv[1]))
pk = {p['id']: p for p in m['packages']}
nodes = {n['id']: n for n in m['resolve']['nodes']}
root = m['resolve']['root']
# normal (non-dev, non-build) dependencies reachable from the crate: what ships in the binary
seen, todo = set(), [root]
while todo:
    i = todo.pop()
    for d in nodes[i]['deps']:
        if any(k['kind'] in (None, 'normal') for k in d['dep_kinds']) and d['pkg'] not in seen:
            seen.add(d['pkg']); todo.append(d['pkg'])
build = set()
todo = [root]; allseen = set()
while todo:
    i = todo.pop()
    for d in nodes[i]['deps']:
        if d['pkg'] not in allseen:
            allseen.add(d['pkg']); todo.append(d['pkg'])
rows = sorted((pk[i]['name'], pk[i]['version'], pk[i].get('license') or pk[i].get('license_file') or '?') for i in seen)
other = sorted((pk[i]['name'], pk[i]['version'], pk[i].get('license') or '?') for i in allseen - seen)
print("# Third-party components of the Sensors ingest and its services")
print("#")
print("# Generated from Cargo.lock by `cargo metadata` (Linux target); the licence gate is `cargo deny --locked check`")
print("# (deny.toml: permissive licences only, rodbus banned). Where a crate offers a choice (\"MIT OR Apache-2.0\")")
print("# the ingest uses it under a permissive option. Regenerate after any dependency change (tests/run.sh checks it).")
print()
print("## Services (docker images, digest-pinned in docker-compose.yml)")
print("eclipse-mosquitto 2.0.23        EPL-2.0 OR EDL-1.0 (BSD-3-Clause)   broker")
print("nodered/node-red 4.0.9          Apache-2.0                          field simulator (development only)")
print("rust 1.88.0-slim-bookworm       MIT OR Apache-2.0 (toolchain); Debian packages, build stage only")
print("debian bookworm-slim            Debian free software (DFSG); ca-certificates MPL-2.0 data   runtime base")
print("timescale/timescaledb 2.17.2    Apache-2.0 core; compression, continuous aggregates and policies under the")
print("                                Timescale License (TSL), allowed for self-hosted use inside our application")
print()
print("## Crates compiled into the ingest binary (%d)" % len(rows))
w = max(len(n) + len(v) for n, v, _ in rows) + 3
for n, v, l in rows:
    print(("%s %s" % (n, v)).ljust(w) + l)
print()
print("## Crates used only to build or test (%d)" % len(other))
for n, v, l in other:
    print(("%s %s" % (n, v)).ljust(w) + l)
