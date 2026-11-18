#!/usr/bin/env bash
# The Django test suite in Docker, in parallel, on a PostgreSQL server of its own (README, Tests).
#
#   scripts/test.sh                                   the whole suite, WORKERS processes (default 6)
#   scripts/test.sh farm.tests.test_stock core        only these labels (any `manage.py test` argument passes through)
#   WORKERS=1 scripts/test.sh                         one process, as `manage.py test` without --parallel
#   KEEP_DB=1 scripts/test.sh ...                     leave the database server running afterwards (for a look inside)
#   CHECKS=1 scripts/test.sh                          the project checks first, as CI runs them (in-container.sh)
#   CHECKS=1 SUITE=0 scripts/test.sh                  the project checks only, no tests (CI on a pull request)
#   TEST_CLOCK=2026-11-10T23:30:00+00:00 scripts/test.sh hr   the run's clock starts at that moment (core/testing.py)
#
# Deprecation warnings and naive datetimes are errors (scripts/testrunner/in-container.sh, config/test_runner.py).
# Each run starts its own database server (the development database's image, timescale/timescaledb:2.17.2-pg17) in a
# container named balik-test-db-<run>, on a network of its own, with its data in memory, and removes both at the end:
# on every way out of this script (a pass, a failure, a step that could not start, Ctrl-C, a TERM or HUP signal), the
# containers with any anonymous volume of theirs (`docker rm -f -v`; the server's data is a tmpfs in the place of the
# image's volume, so it leaves none). The tests' container runs behind a `wait`, so a signal is answered at once and
# not when the tests end. Only a script killed outright (SIGKILL, its console closed) cleans nothing: its
# balik-test-db-<run> and balik-test-run-<run> containers and its network balik-test-<run> are then removed by name.
# Old images of the test runner are scripts/testrunner/prune.sh's to remove.
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
# The tests run in the test runner's image, built when missing: the `tests` stage of docker/testrunner.Dockerfile, with
# the project's requirements (hashed), the water-chemistry core built from this checkout (chemcore/: no server starts
# without it, README, Water-chemistry core) and tblib. What it is built from and its tag (a hash of all of that, so a
# change to the core or to a requirement builds a new one) are scripts/testrunner/image.sh's, which CI builds it by too.
# CI gives the run names and an image of its own (TEST_NAME_PREFIX in the place of balik-test, TEST_IMAGE an image it has
# just built by image.sh's definition under its own name): on the machine its runner shares with the developers, nobody
# takes a CI run's containers for a developer's, and CI replaces nobody's image (README, CI and dependency updates).
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
win() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
REPO=$(win "$PWD")
WORKERS=${WORKERS:-6}
CHECKS=${CHECKS:-0}
SUITE=${SUITE:-1}
DB_PASSWORD=${TEST_DB_PASSWORD:-balik}
PG_IMAGE=timescale/timescaledb:2.17.2-pg17
RUN=${RUN_ID:-$(date +%Y%m%d%H%M%S)-$$}
NAMES=${TEST_NAME_PREFIX:-balik-test}
DB=$NAMES-db-$RUN
NET=$NAMES-$RUN
TESTS=$NAMES-run-$RUN

IMAGE=${TEST_IMAGE:-$(sh scripts/testrunner/image.sh build)}

cleanup() {
  trap '' INT TERM HUP                      # a second signal does not cut the cleaning short
  docker rm -f -v "$TESTS" >/dev/null 2>&1 || true
  if [ "${KEEP_DB:-0}" != 1 ]; then
    docker rm -f -v "$DB" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
  else
    echo "database server kept: $DB (docker rm -f -v $DB; docker network rm $NET)"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

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
# In the background, behind `wait`: bash runs a trap only when the command in front has ended, and `wait` ends at once
# on a signal, so an interrupted run is cleaned up then and not when the tests are over.
docker run --rm --name "$TESTS" --network "$NET" -v "$REPO:/app" -w /app \
  -e DB_HOST="$DB" -e DB_PORT=5432 -e DB_NAME=balik -e DB_USER=balik -e DB_PASSWORD="$DB_PASSWORD" \
  -e DB_TEST_NAME=test_balik -e CHECKS="$CHECKS" -e SUITE="$SUITE" -e TEST_CLOCK="${TEST_CLOCK:-}" \
  "$IMAGE" sh scripts/testrunner/in-container.sh "${parallel[@]}" "$@" &
wait $! || status=$?
echo "scripts/test.sh: workers $WORKERS, checks $CHECKS, suite $SUITE, $(( $(date +%s) - start )) s, exit $status"
exit $status
