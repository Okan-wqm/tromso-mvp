#!/usr/bin/env bash
# The ingest's one test script (plan section 6): a test database migrated by Django, then cargo test (unit, property and
# database tests), clippy with warnings as errors, rustfmt and the licence gate (cargo deny). Everything runs in
# containers on the network of the development database; nothing touches the dev database `balik`.
#
#   sensors-ingest/tests/run.sh            all of the above
#   TEST_DB=other_name tests/run.sh        another test database
#   DB_NETWORK=net DB_HOST=name tests/run.sh   another database server (its docker network and host name)
#
# Needs: docker, the image `timescale/timescaledb:2.32.1-pg17@sha256:2f5e6969faa5cd7f4b075d65f124e30dc50d456b7b807e5c1acd9d51ba7df51c` (psql), the Django image that migrates the schema
# (DJANGO_IMAGE, default the test runner's image as scripts/testrunner/image.sh defines it, the one CI migrates in,
# built when missing: no server starts without the water-chemistry core in it), and the Rust image (RUST_IMAGE,
# default sensors-ingest-dev:1.88 = rust:1.88.0-slim-bookworm plus clippy and rustfmt, built by this script when
# missing).
set -euo pipefail
cd "$(dirname "$0")/../.."
export MSYS_NO_PATHCONV=1
win() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
NET=${DB_NETWORK:-balik-ciftligi_default}
DB_HOST=${DB_HOST:-db}
TEST_DB=${TEST_DB:-sensors_ingest_test}
[ "$TEST_DB" != balik ] || { echo "refusing to use the dev database"; exit 2; }
DJANGO_IMAGE=${DJANGO_IMAGE:-$(sh scripts/testrunner/image.sh build)}
RUST_IMAGE=${RUST_IMAGE:-sensors-ingest-dev:1.88}
REPO=$(win "$PWD")

if ! docker image inspect "$RUST_IMAGE" >/dev/null 2>&1; then
  printf 'FROM rust:1.88.0-slim-bookworm\nRUN rustup component add clippy rustfmt\n' | docker build -q -t "$RUST_IMAGE" -
fi

psql() { docker run --rm --network "$NET" -e PGPASSWORD="${DB_PASSWORD:-balik}" timescale/timescaledb:2.32.1-pg17@sha256:2f5e6969faa5cd7f4b075d65f124e30dc50d456b7b807e5c1acd9d51ba7df51c \
  psql -h "$DB_HOST" -U "${DB_USER:-balik}" "$@"; }
# a fresh database each run: the unlanded migrations may still change
psql -d postgres -qc "DROP DATABASE IF EXISTS $TEST_DB WITH (FORCE)" >/dev/null
psql -d postgres -qc "CREATE DATABASE $TEST_DB" >/dev/null
docker run --rm --network "$NET" -v "$REPO:/app" -w /app -e DB_HOST="$DB_HOST" -e DB_PORT=5432 -e DB_NAME="$TEST_DB" \
  "$DJANGO_IMAGE" python manage.py migrate --no-input >/dev/null

# a broker with the production configuration (users ingest/ingest-pw and dev/dev-pw) for the live tests
MOSQ=eclipse-mosquitto:2.0.23@sha256:6a332cc7a8dbe011cbc076180cbb76b37c6f0f55809682ea08e7980ef0112ad9
BROKER=sensors-ingest-test-broker
cleanup() { docker rm -f -v "$BROKER" >/dev/null 2>&1 || true; docker volume rm si-test-broker-auth >/dev/null 2>&1 || true; }
cleanup
trap cleanup EXIT
docker run --rm -v si-test-broker-auth:/mosquitto/auth "$MOSQ" sh -c '
  mosquitto_passwd -c -b /mosquitto/auth/passwd ingest ingest-pw 2>/dev/null
  mosquitto_passwd -b /mosquitto/auth/passwd dev dev-pw 2>/dev/null
  printf "user ingest\ntopic read #\nuser dev\ntopic write #\n" > /mosquitto/auth/acl
  chown -R mosquitto:mosquitto /mosquitto/auth && chmod 0700 /mosquitto/auth/passwd /mosquitto/auth/acl'
docker run -d --name "$BROKER" --network "$NET" -v "$REPO/sensors-ingest/mosquitto:/mosquitto/config:ro" \
  -v si-test-broker-auth:/mosquitto/auth --tmpfs /mosquitto/data --entrypoint sh "$MOSQ" \
  /mosquitto/config/entrypoint.sh >/dev/null

docker run --rm --network "$NET" -v "$REPO:/w" -v si-cargo:/usr/local/cargo/registry -v si-target:/t \
  -e CARGO_TARGET_DIR=/t/target -e PATH=/t/tools/bin:/usr/local/cargo/bin:/usr/bin:/bin \
  -e TEST_DATABASE_URL="host=$DB_HOST port=5432 user=${DB_USER:-balik} password=${DB_PASSWORD:-balik} dbname=$TEST_DB" \
  -e REQUIRE_DB=1 -e TEST_MQTT_HOST="$BROKER" -w /w/sensors-ingest "$RUST_IMAGE" sh -ec '
    cargo fmt --check
    cargo test --all-targets
    cargo clippy --all-targets -- -D warnings
    if command -v cargo-deny >/dev/null; then cargo deny --locked check; else cargo install --locked cargo-deny --root /t/tools && cargo deny --locked check; fi
  '

# THIRD_PARTY must equal what Cargo.lock says
META=$(mktemp)
docker run --rm -v "$REPO:/w" -v si-cargo:/usr/local/cargo/registry -w /w/sensors-ingest "$RUST_IMAGE" \
  cargo metadata --format-version 1 --locked --filter-platform x86_64-unknown-linux-gnu > "$META"
cp "$META" sensors-ingest/target-meta.json.tmp
docker run --rm -v "$REPO:/w" python:3.12-slim python -I /w/sensors-ingest/tests/third_party.py \
  /w/sensors-ingest/target-meta.json.tmp > "$META.out"
rm -f sensors-ingest/target-meta.json.tmp
diff -u sensors-ingest/THIRD_PARTY "$META.out" || { echo "THIRD_PARTY is out of date: regenerate it"; exit 1; }
echo "sensors-ingest: THIRD_PARTY current"
echo "sensors-ingest: all green"
