#!/bin/sh
# chemcore's gates, run in the chemcore-tools stage of docker/testrunner.Dockerfile (README, chemcore):
#   docker build -f docker/testrunner.Dockerfile --target chemcore-tools -t chemcore-tools .
#   docker run --rm -v "$PWD:/repo" -w /repo chemcore-tools sh chemcore/scripts/test.sh
# Every gate must pass; the first failure stops the run with its name.
set -eu
cd "$(dirname "$0")/.."
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$PWD/target}"
fail() { echo "GATE FAILED: $1" >&2; exit 1; }

echo "== format";  cargo fmt --check || fail "rustfmt"
echo "== lint";    cargo clippy --locked --all-targets -- -D warnings || fail "clippy"
echo "== tests";   cargo test --locked || fail "cargo test"

echo "== the chemistry depends on libm only"
deps=$(cargo tree --locked -p chemcore-core --edges normal --prefix none --format '{p}' | sed 's/ (.*//' | sort -u | tr '\n' ' ')
[ "$deps" = "chemcore-core v0.1.0 libm v0.2.16 " ] || fail "chemcore-core depends on: $deps"

echo "== no WebAssembly anywhere (owner amendment B2)"
if cargo metadata --locked --format-version 1 | grep -qE '"name":"(wasm-bindgen|js-sys|web-sys)"'; then fail "a wasm crate is in the graph"; fi
if grep -qiE 'wasm' rust-toolchain.toml; then fail "a wasm target in rust-toolchain.toml"; fi

echo "== licences and sources";  cargo deny --locked check licenses bans sources || fail "cargo deny"
if [ "${CHEMCORE_OFFLINE:-0}" != 1 ]; then
  echo "== advisories"; cargo deny --locked check advisories || fail "cargo deny advisories"
fi

echo "== THIRD_PARTY is current"
sh scripts/third_party.sh | diff -u THIRD_PARTY - || fail "THIRD_PARTY is stale: sh chemcore/scripts/third_party.sh > chemcore/THIRD_PARTY"

echo "== the runner's lock names the pins of requirements.txt"
python3 - <<'PY' || fail "docker/requirements.lock and requirements.txt disagree"
import re
pins = lambda path: {m.group(1).lower().replace('_', '-'): m.group(2) for m in
                     (re.match(r'^([A-Za-z0-9_.-]+)==([^ \]+)', line) for line in open(path)) if m}
wanted, locked = pins('../requirements.txt'), pins('../docker/requirements.lock')
wrong = {name: (version, locked.get(name)) for name, version in wanted.items() if locked.get(name) != version}
assert not wrong, wrong
PY
echo "ALL GATES PASSED"
