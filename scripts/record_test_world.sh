#!/usr/bin/env bash
# scripts/record_test_world.sh: records the browser tests' fixtures from the test world (scripts/record_test_world.py) in a
# THROWAWAY database: a TimescaleDB server of its own on a network of its own (no host port, its data in memory), migrated,
# the recorder run against it in the test runner's image, then everything removed on every way out. Never the dev database.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && { pwd -W 2>/dev/null || pwd; })
RUN=world-$$
NET=balik-$RUN DB=balik-$RUN-db
IMAGE=${IMAGE:-$(sh "$(dirname "$0")/testrunner/image.sh" | sed -n "s/^tag=//p")}
PG_IMAGE=timescale/timescaledb:2.17.2-pg17
cleanup() { docker rm -f -v "$DB" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM HUP
export MSYS_NO_PATHCONV=1
docker network create "$NET" >/dev/null
docker run -d --name "$DB" --network "$NET" --tmpfs /var/lib/postgresql/data:rw,size=2g \
  -e POSTGRES_USER=balik -e POSTGRES_PASSWORD=world -e POSTGRES_DB=test_world "$PG_IMAGE" >/dev/null
until docker exec "$DB" pg_isready -U balik -d test_world >/dev/null 2>&1; do sleep 1; done
sleep 2
docker run --rm --network "$NET" -v "$REPO:/app" -w /app -e PYTHONDONTWRITEBYTECODE=1 \
  -e DB_HOST="$DB" -e DB_PORT=5432 -e DB_NAME=test_world -e DB_USER=balik -e DB_PASSWORD=world \
  "$IMAGE" sh -c 'python manage.py migrate --noinput >/dev/null && python scripts/record_test_world.py'
