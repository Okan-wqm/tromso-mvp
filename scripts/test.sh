#!/usr/bin/env bash
# The Django test suite in Docker, in parallel, on a PostgreSQL server of its own (README, Tests).
#
#   scripts/test.sh                                   the whole suite, WORKERS processes (default 6)
#   scripts/test.sh farm.tests.test_stock core        only these labels (any `manage.py test` argument passes through)
#   WORKERS=1 scripts/test.sh                         one process, as `manage.py test` without --parallel
#   KEEP_DB=1 scripts/test.sh ...                     leave the database server running afterwards (for a look inside)
#   CHECKS=1 scripts/test.sh                          the project checks first, as CI runs them (in-container.sh)
#
# Deprecation warnings and naive datetimes are errors (scripts/testrunner/in-container.sh, config/test_runner.py).
# Each run starts its own database server (the development database's image, timescale/timescaledb:2.17.2-pg17) in a
# container named balik-test-db-<run>, on a network of its own, with its data in memory, and removes both at the end.
# So a run never touches the development database `balik`, its server or its volume, never meets another run's test
# databases, roles or connections (the shared server's max_connections of 100 was the limit every overlapping run
# shared), and DB_TEST_NAME is not needed. The server's settings, each for the tests only:
#   timescaledb.max_background_workers=0  TimescaleDB's job scheduler keeps a connection open to every database with
#       the extension, and PostgreSQL copies a database (the workers' copies of the test database) only while nobody
#       is connected to it. No test needs the scheduler: the tests that check a job run it themselves (CALL run_job),
#       so no job runs behind a test's back either.
#   fsync, synchronous_commit, full_page_writes off  the data lives only as long as the run (crash safety buys nothing).
#   max_connections=200  one connection per worker and the few a test opens itself, far below it.
# Its password is TEST_DB_PASSWORD (default balik; CI passes a random one): the server has no host port either way.
# The tests run in the image built from scripts/testrunner/Dockerfile (the project's requirements and tblib), tagged
# by the hash of the requirements, built when missing.
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
win() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
REPO=$(win "$PWD")
WORKERS=${WORKERS:-6}
CHECKS=${CHECKS:-0}
DB_PASSWORD=${TEST_DB_PASSWORD:-balik}
PG_IMAGE=timescale/timescaledb:2.17.2-pg17
RUN=${RUN_ID:-$(date +%Y%m%d%H%M%S)-$$}
DB=balik-test-db-$RUN
NET=balik-test-$RUN
TESTS=balik-test-run-$RUN

HASH=$(cat requirements.txt scripts/testrunner/requirements.txt scripts/testrunner/Dockerfile | sha256sum | cut -c1-12)
IMAGE=balik-testrunner:req-$HASH
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  context=$(mktemp -d)
  cp requirements.txt "$context/requirements.txt"
  cp scripts/testrunner/requirements.txt "$context/test-requirements.txt"
  cp scripts/testrunner/Dockerfile "$context/Dockerfile"
  docker build -q -t "$IMAGE" "$(win "$context")" >/dev/null
  rm -rf "$context"
fi

cleanup() {
  docker rm -f "$TESTS" >/dev/null 2>&1 || true
  if [ "${KEEP_DB:-0}" != 1 ]; then
    docker rm -f "$DB" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
  else
    echo "database server kept: $DB (docker rm -f $DB; docker network rm $NET)"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

docker network create "$NET" >/dev/null
docker run -d --name "$DB" --network "$NET" --tmpfs /var/lib/postgresql/data:rw,size=${DB_TMPFS:-8g} \
  -e POSTGRES_USER=balik -e POSTGRES_PASSWORD="$DB_PASSWORD" -e POSTGRES_DB=postgres "$PG_IMAGE" \
  postgres -c timescaledb.telemetry_level=off -c timescaledb.max_background_workers=0 \
  -c fsync=off -c synchronous_commit=off -c full_page_writes=off -c max_connections=200 >/dev/null
# The image's first start runs its init scripts on a server that listens on no TCP port, then starts the real one.
for _ in $(seq 1 120); do
  docker exec "$DB" pg_isready -q -h 127.0.0.1 -U balik 2>/dev/null && break
  sleep 1
done
docker exec "$DB" pg_isready -q -h 127.0.0.1 -U balik || { docker logs --tail 30 "$DB"; exit 1; }

parallel=()
[ "$WORKERS" = 1 ] || parallel=(--parallel "$WORKERS")
start=$(date +%s)
status=0
docker run --rm --name "$TESTS" --network "$NET" -v "$REPO:/app" -w /app \
  -e DB_HOST="$DB" -e DB_PORT=5432 -e DB_NAME=balik -e DB_USER=balik -e DB_PASSWORD="$DB_PASSWORD" \
  -e DB_TEST_NAME=test_balik -e CHECKS="$CHECKS" \
  "$IMAGE" sh scripts/testrunner/in-container.sh "${parallel[@]}" "$@" || status=$?
echo "scripts/test.sh: workers $WORKERS, checks $CHECKS, $(( $(date +%s) - start )) s, exit $status"
exit $status
