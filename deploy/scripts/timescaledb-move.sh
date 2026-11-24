#!/bin/sh
# Moves a database server's TimescaleDB to the release of its new image, the way docs/ops/upgrade.md says, and checks
# it. Written once, used twice: by the coordinator on the shared development database at the landing of wip/go-live,
# and by the go-live stack workflow on a synthetic one (deploy/ci/stack.sh, step tsmove), so the sequence is tested.
#
#   DB_EXEC="docker compose exec -T db" RECREATE="docker compose up -d db" sh deploy/scripts/timescaledb-move.sh \
#     move BACKUP_DIR LABEL
#       1. facts before (TimescaleDB version, every hypertable's rows and chunks and compressed chunks, the jobs)
#       2. pg_dump of DB_NAME on the old release            -> BACKUP_DIR/LABEL-before-<time>.dump
#       3. RECREATE: the same data volume on the new image (the same PostgreSQL major: the data folder moves as it is)
#       4. ALTER EXTENSION timescaledb UPDATE in every database that holds it (postgres, template1 and DB_NAME on the
#          image's own), each as the plain first command of a new session: a DO block, or anything that loads the
#          extension first, makes PostgreSQL refuse the update ("the old version has already been loaded")
#       5. pg_dump on the new release                       -> BACKUP_DIR/LABEL-after-<time>.dump (a way back on the
#          same release from now on)
#       6. the checks (below)
#   DB_EXEC=... sh timescaledb-move.sh update             step 4 alone
#   DB_EXEC=... sh timescaledb-move.sh checks FACTS_BEFORE  step 6 alone:
#       - the version is TARGET_VERSION (2.32.1) in every database that holds the extension;
#       - every hypertable has the rows, chunks and compressed chunks it had, and its compressed chunks are read;
#       - every job is there (by procedure), every continuous aggregate's jobs are listed under its own name;
#       - each scheduled job fails ONCE at the update ("cannot drop portal ... while it is being set up", SQLSTATE
#         24000: expected), then recovers: every job is made due now and must run with Success.
#
# DB_USER (balik) must be a superuser; DB_NAME (balik). Nothing here deletes anything.
set -eu
: "${DB_EXEC:?DB_EXEC: how to run a command in the database container}"
DB_USER=${DB_USER:-balik}
DB_NAME=${DB_NAME:-balik}
TARGET_VERSION=${TARGET_VERSION:-2.32.1}
psql_() { db=$1; shift; $DB_EXEC psql -X -q -U "$DB_USER" -d "$db" -v ON_ERROR_STOP=1 -At -F ' ' "$@"; }
say() { echo "== $*"; }
die() { echo "FAIL: $*" >&2; exit 1; }

databases() {  # every database that accepts connections and holds the extension (each asked in a session of its own)
  for d in $(psql_ postgres -c "SELECT datname FROM pg_database WHERE datallowconn ORDER BY datname"); do
    [ "$(psql_ "$d" -c "SELECT count(*) FROM pg_extension WHERE extname = 'timescaledb'")" = 1 ] && echo "$d"
  done
  return 0
}

facts() {
  psql_ "$DB_NAME" <<'SQL'
SELECT 'version', extversion FROM pg_extension WHERE extname = 'timescaledb';
SELECT format('SELECT %L, count(*) FROM %I.%I', 'rows:' || hypertable_name, hypertable_schema, hypertable_name)
FROM timescaledb_information.hypertables WHERE hypertable_schema = 'public' ORDER BY hypertable_name
\gexec
SELECT 'chunks:' || hypertable_name, count(*)
FROM timescaledb_information.chunks WHERE hypertable_schema = 'public' GROUP BY hypertable_name ORDER BY 1;
SELECT 'compressed:' || hypertable_name, count(*) FILTER (WHERE is_compressed)
FROM timescaledb_information.chunks WHERE hypertable_schema = 'public' GROUP BY hypertable_name ORDER BY 1;
SELECT 'job:' || proc_name, count(*) FROM timescaledb_information.jobs WHERE job_id >= 1000 GROUP BY proc_name ORDER BY 1;
SQL
}

wait_ready() {
  for _ in $(seq 1 90); do
    psql_ postgres -c 'SELECT 1' > /dev/null 2>&1 && return 0
    sleep 2
  done
  die "the database server did not come back"
}

update() {
  for d in $(databases); do
    say "ALTER EXTENSION timescaledb UPDATE in $d (the first command of a new session)"
    $DB_EXEC psql -X -U "$DB_USER" -d "$d" -v ON_ERROR_STOP=1 -c 'ALTER EXTENSION timescaledb UPDATE'
  done
}

checks() {
  before=$1
  [ -f "$before" ] || die "$before: the facts from before the move are needed"
  say "the version in every database that holds the extension"
  for d in $(databases); do
    got=$(psql_ "$d" -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
    [ "$got" = "$TARGET_VERSION" ] || die "$d holds TimescaleDB $got, not $TARGET_VERSION"
    echo "ok    $d: $got"
  done
  say "rows, chunks and jobs as before; compressed chunks as many or more (a compression job may have run meanwhile)"
  after=$(mktemp)
  facts > "$after"
  grep -vE '^(version|compressed:)' "$before" > "$after.before"
  grep -vE '^(version|compressed:)' "$after" > "$after.now"
  diff -u "$after.before" "$after.now" || die "the data or the jobs differ (above)"
  cat "$after.now"
  grep '^compressed:' "$before" | while read -r name count; do
    now=$(grep "^$name " "$after" | cut -d' ' -f2)
    [ "${now:-0}" -ge "$count" ] || die "$name: $count compressed chunks before, ${now:-0} now"
    echo "$name $count before, $now now"
  done
  say "every compressed chunk is read"
  psql_ "$DB_NAME" <<'SQL' > /dev/null || die "a compressed chunk could not be read"
SELECT format('SELECT count(*) FROM %I.%I', chunk_schema, chunk_name)
FROM timescaledb_information.chunks WHERE is_compressed
\gexec
SQL
  echo "ok    $(psql_ "$DB_NAME" -c 'SELECT count(*) FROM timescaledb_information.chunks WHERE is_compressed') compressed chunk(s) read"
  say "every continuous aggregate's jobs are listed under its own name"
  missing=$(psql_ "$DB_NAME" -c "SELECT c.view_name FROM timescaledb_information.continuous_aggregates c
    WHERE NOT EXISTS (SELECT FROM timescaledb_information.jobs j WHERE j.hypertable_name = c.view_name
                      AND j.proc_name = 'policy_refresh_continuous_aggregate')")
  [ -z "$missing" ] || die "no refresh job listed under: $missing"
  echo "ok    every continuous aggregate has its refresh job"
  say "the jobs: one error each at the update is expected; every job made due now must run with Success"
  psql_ "$DB_NAME" -c "SELECT job_id, proc_name, sqlerrcode, left(err_message, 80) FROM timescaledb_information.job_errors
    ORDER BY start_time DESC LIMIT 20" || true
  start=$(psql_ "$DB_NAME" -c "SELECT now()")
  psql_ "$DB_NAME" -c "SELECT count(alter_job(job_id, next_start => now())) FROM timescaledb_information.jobs
    WHERE job_id >= 1000 AND scheduled" > /dev/null
  for _ in $(seq 1 60); do
    pending=$(psql_ "$DB_NAME" -c "SELECT count(*) FROM timescaledb_information.jobs j
      JOIN timescaledb_information.job_stats s USING (job_id)
      WHERE j.job_id >= 1000 AND j.scheduled
        AND (s.last_run_started_at IS NULL OR s.last_run_started_at < '$start' OR s.last_run_status IS DISTINCT FROM 'Success')")
    [ "$pending" = 0 ] && break
    sleep 5
  done
  psql_ "$DB_NAME" -c "SELECT j.job_id, j.proc_name, s.last_run_status, s.total_runs, s.total_failures
    FROM timescaledb_information.jobs j JOIN timescaledb_information.job_stats s USING (job_id)
    WHERE j.job_id >= 1000 ORDER BY j.job_id"
  [ "$pending" = 0 ] || die "$pending job(s) did not run with Success after the update"
  echo "ok    every job ran again with Success"
}

case "${1:-}" in
  move)
    [ $# = 3 ] || die "usage: timescaledb-move.sh move BACKUP_DIR LABEL"
    : "${RECREATE:?RECREATE: how to start the same data volume on the new image}"
    dir=$2 label=$3 stamp=$(date +%Y%m%d-%H%M)
    mkdir -p "$dir"
    say "facts before"
    facts > "$dir/$label-before-$stamp.facts"
    cat "$dir/$label-before-$stamp.facts"
    say "pg_dump on the old release"
    $DB_EXEC pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$dir/$label-before-$stamp.dump"
    [ -s "$dir/$label-before-$stamp.dump" ] || die "the dump is empty"
    say "the same volume on the new image"
    sh -c "$RECREATE"
    wait_ready
    update
    say "pg_dump on the new release"
    $DB_EXEC pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$dir/$label-after-$stamp.dump"
    [ -s "$dir/$label-after-$stamp.dump" ] || die "the dump is empty"
    checks "$dir/$label-before-$stamp.facts"
    say "moved: $dir/$label-before-$stamp.dump (old release), $dir/$label-after-$stamp.dump (new release)" ;;
  back)
    # The way back from the dump taken on the OLD release: onto a NEW volume running the OLD image (a dump restores
    # only into its own release: into the new one, pg_restore fails on the catalog and leaves the data partial), then
    # the new image on that volume and the update, then the checks against the facts from before the move.
    [ $# = 6 ] || die "usage: timescaledb-move.sh back DUMP FACTS_BEFORE OLD_IMAGE NEW_IMAGE VOLUME"
    dump=$2 facts_before=$3 old=$4 new=$5 volume=$6
    [ -s "$dump" ] && [ -f "$facts_before" ] || die "$dump and $facts_before are needed"
    ! docker volume inspect "$volume" > /dev/null 2>&1 || die "$volume exists: a new volume is restored into, never an old one"
    docker volume create "$volume" > /dev/null
    run() { docker run -d --name timescaledb-back -e POSTGRES_USER="$DB_USER" -e POSTGRES_DB="$DB_NAME" \
              -e POSTGRES_PASSWORD="$(openssl rand -hex 16)" -v "$volume:/var/lib/postgresql/data" "$1" > /dev/null; }
    say "the old image ($old) on the new volume $volume, the dump restored"
    run "$old"
    DB_EXEC="docker exec -i timescaledb-back"
    # the image's first start makes the database on a server of its own, then starts the real one
    for _ in $(seq 1 120); do
      docker logs timescaledb-back 2>&1 | grep -q 'init process complete' && break
      sleep 2
    done
    wait_ready
    psql_ "$DB_NAME" -c 'SELECT timescaledb_pre_restore()' > /dev/null
    $DB_EXEC pg_restore -U "$DB_USER" -d "$DB_NAME" < "$dump" 2> /tmp/timescaledb-back.log || true
    psql_ "$DB_NAME" -c 'SELECT timescaledb_post_restore()' > /dev/null
    if grep '^pg_restore: error' /tmp/timescaledb-back.log | grep -v 'unique constraint "metadata_pkey"'; then
      die "pg_restore failed (above)"
    fi
    docker rm -f timescaledb-back > /dev/null
    say "the new image ($new) on the same volume, the update"
    run "$new"
    wait_ready
    update
    checks "$facts_before"
    docker rm -f timescaledb-back > /dev/null
    say "back: $volume holds the database on the new release; point the stack at it (docs/ops/upgrade.md)" ;;
  update) update ;;
  checks) [ $# = 2 ] || die "usage: timescaledb-move.sh checks FACTS_BEFORE"; checks "$2" ;;
  facts) facts ;;
  *) die "usage: timescaledb-move.sh move BACKUP_DIR LABEL | update | checks FACTS_BEFORE | facts" ;;
esac
