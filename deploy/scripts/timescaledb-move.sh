#!/bin/sh
# Moves a database server's TimescaleDB to the release of its new image, the way docs/ops/upgrade.md says, and checks
# it. Written once, used twice: by the coordinator on the shared development database at the landing of wip/go-live,
# and by the go-live stack workflow on a database made by the project's own migrations, with real data
# (deploy/ci/stack.sh, steps tsmove, tsback, tshalf, tsearly), so the sequence is tested on the real schema.
#
# Settings (environment):
#   DB_EXEC    how to run a command in the database container (`docker compose exec -T db`)
#   RECREATE   how to start the same data volume on the new image (`docker compose up -d db`)
#   MANAGE     how to run the project's manage.py, of the code whose migrations the database holds, against it as a role
#              that owns its tables: the revision triggers are taken off and made again by the project's own commands
#   DB_USER    a superuser (balik); DB_NAME (balik); TARGET_VERSION (2.32.1)
#   JOB_WAIT_SECONDS  how long step 8 waits for every job to run again with Success (300)
#
#   sh timescaledb-move.sh move BACKUP_DIR LABEL
#     First it lists every database that holds the extension. Refused, with nothing done or written, when DB_NAME
#     already holds TARGET_VERSION; when another of those databases has a constraint trigger on a hypertable or a chunk
#     (the revision triggers of a stale copy: the update would stop on it, and only DB_NAME's are taken off here); when
#     BACKUP_DIR holds an unfinished move of LABEL; when a migration is not applied; or when
#     `manage.py check --database default` is not quiet. A server already recreated on the new image while the
#     extension is still the old one (a `docker compose up` before the move) is no reason to stop: the image carries
#     the old release's library too, so the dump below is still a dump of the old release. Then, stopping at the first
#     failure:
#       1. facts before (TimescaleDB version, every hypertable's rows and chunks and compressed chunks, the jobs)
#                                                            -> BACKUP_DIR/LABEL-before-<time>.facts
#       2. pg_dump of DB_NAME on the old release            -> BACKUP_DIR/LABEL-before-<time>.dump
#          the cluster's roles (pg_dumpall --roles-only, with their password hashes: keep it as the dump is kept)
#                                                            -> BACKUP_DIR/LABEL-before-<time>.roles.sql
#          Each is written as <name>.partial and renamed when all three are whole: a dump that failed is never left
#          under a name that looks whole. <time> is to the second, and no file is ever overwritten. From here until the
#          end, BACKUP_DIR/LABEL.unfinished records the move and the step it is at.
#       3. manage.py core_rev_drop_hypertable_triggers: the revision triggers off every tracked hypertable (core/rev.py's
#          registry). A TimescaleDB update renames every chunk's constraints and cannot rename a constraint trigger
#          ("constraint ... does not exist"): it would stop half-way.
#       4. RECREATE: the same data volume on the new image (the same PostgreSQL major: the data folder moves as it is)
#       5. ALTER EXTENSION timescaledb UPDATE in every database that holds it (postgres, template1 and DB_NAME on the
#          image's own), each as the plain first command of a new session: a DO block, or anything that loads the
#          extension first, makes PostgreSQL refuse the update ("the old version has already been loaded")
#       6. manage.py core_rev_repair: the triggers made again as their migrations made them, every revision rebuilt;
#          then manage.py check --database default must be quiet (core.W005 would name a missing trigger)
#       7. pg_dump on the new release                       -> BACKUP_DIR/LABEL-after-<time>.dump (a way back on the
#          same release from now on)
#       8. the checks (below); BACKUP_DIR/LABEL.unfinished removed
#     A move that stops after step 2 says where, and the command that goes on:
#   sh timescaledb-move.sh resume BACKUP_DIR LABEL
#     Goes on with the unfinished move of LABEL from step 3 (each step is safe to run again: a trigger already off, the
#     new image already running, a database already on TARGET_VERSION are passed over), to the checks against that
#     move's facts from before. The other way is back (below).
#   sh timescaledb-move.sh close BACKUP_DIR LABEL
#     For a move that stopped in step 8 only (the database is moved; a job had not run again with Success in time):
#     the checks again against that move's facts, and only when they pass, the record removed. Logged, with the record,
#     in BACKUP_DIR/LABEL-before-<time>.closed-<now>.log.
#   sh timescaledb-move.sh back DUMP FACTS_BEFORE OLD_IMAGE NEW_IMAGE VOLUME
#     (also BACK_NETWORK, BACK_ALIAS, MANAGE; BACK_ROOM_FACTOR, DOCKER_HOST_DRIVE)
#     For the development stack only. A farm goes back by the restore of its backup on the old images
#     (docs/ops/upgrade.md, "When it fails"; docs/ops/backup-and-restore.md): this one runs the plain TimescaleDB
#     image, without the farm database image's first-start settings (its pg_hba replication line, its roles' script).
#     The way back from the dump taken on the OLD release: a NEW volume running the OLD image (a dump restores only
#     into its own release), the cluster's roles first, from the .roles.sql beside the dump (the dump's grants name
#     them, and they keep their passwords), the restore, then the new image on that volume and steps 3, 5, 6 and 8.
#     It needs room for a second whole copy of the database on Docker's disk: refused first, with nothing made, when
#     Docker's disk (and DOCKER_HOST_DRIVE, the host drive that holds Docker's disk image, e.g. /c) has less free than
#     BACK_ROOM_FACTOR (10) times the dump's size. The container `timescaledb-back` joins BACK_NETWORK as BACK_ALIAS,
#     the host name MANAGE reaches the database at (stop the old database first). On a failure the container is
#     removed, and the new volume is left and named.
#   sh timescaledb-move.sh update             step 5 alone
#   sh timescaledb-move.sh checks FACTS_BEFORE  step 8 alone:
#       - the version is TARGET_VERSION in every database that holds the extension;
#       - every hypertable has the rows, chunks and compressed chunks it had, and its compressed chunks are read;
#       - every job is there (by procedure), every continuous aggregate's jobs are listed under its own name;
#       - each scheduled job fails ONCE at the update ("cannot drop portal ... while it is being set up", SQLSTATE
#         24000: expected), then recovers: every job is made due now and must run with Success within JOB_WAIT_SECONDS.
#
# What it deletes: no data of its own. Making every job due runs the retention job (policy_retention) too, which drops
# what the retention policy drops anyway (sensors_reading's chunks older than 730 days); the revision triggers are
# dropped and made again (steps 3 and 6). Its files (facts, dumps, roles, the logs) go to BACKUP_DIR, or beside the dump
# for `back`: nothing goes to a temporary folder.
set -eu
: "${DB_EXEC:?DB_EXEC: how to run a command in the database container}"
DB_USER=${DB_USER:-balik}
DB_NAME=${DB_NAME:-balik}
TARGET_VERSION=${TARGET_VERSION:-2.32.1}
SCRIPT="sh $0"                                     # as it was called: the commands it prints run from the same folder
psql_() { db=$1; shift; $DB_EXEC psql -X -q -U "$DB_USER" -d "$db" -v ON_ERROR_STOP=1 -At -F ' ' "$@"; }
say() { echo "== $*"; }
die() { echo "FAIL: $*" >&2; exit 1; }
now() { date +%Y%m%d-%H%M%S; }
manage() {
  [ -n "${MANAGE:-}" ] || die "MANAGE: how to run the project's manage.py against this database"
  sh -c "$MANAGE \"\$@\"" manage "$@"
}
quiet_check() { manage check --database default --fail-level WARNING; }

databases() {  # every database that accepts connections and holds the extension (each asked in a session of its own)
  for d in $(psql_ postgres -c "SELECT datname FROM pg_database WHERE datallowconn ORDER BY datname"); do
    [ "$(psql_ "$d" -c "SELECT count(*) FROM pg_extension WHERE extname = 'timescaledb'")" = 1 ] && echo "$d"
  done
  return 0
}
# Every constraint trigger on a TimescaleDB hypertable or one of its chunks (as core.rev.CONSTRAINT_TRIGGERS_ON_HYPERTABLES):
# the update cannot rename one. In DB_NAME the project's command takes the revision triggers off; in any other database
# of the server nothing here does.
CONSTRAINT_TRIGGERS="WITH h AS (SELECT format('%I.%I', hypertable_schema, hypertable_name)::regclass AS rel
    FROM timescaledb_information.hypertables)
  SELECT count(*) FROM pg_constraint c WHERE c.contype = 't'
    AND (c.conrelid IN (SELECT rel FROM h) OR c.conrelid IN (SELECT i.inhrelid FROM pg_inherits i JOIN h ON i.inhparent = h.rel))"
installed() { psql_ "$1" -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'"; }
image_version() { psql_ postgres -c "SELECT default_version FROM pg_available_extensions WHERE name = 'timescaledb'"; }

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

answers() { psql_ postgres -c 'SELECT 1' > /dev/null 2>&1; }
wait_ready() {
  for _ in $(seq 1 90); do
    answers && return 0
    sleep 2
  done
  die "the database server did not come back"
}

update() {
  for d in $(databases); do
    if [ "$(installed "$d")" = "$TARGET_VERSION" ]; then echo "ok    $d: already $TARGET_VERSION"; continue; fi
    say "ALTER EXTENSION timescaledb UPDATE in $d (the first command of a new session)"
    $DB_EXEC psql -X -U "$DB_USER" -d "$d" -v ON_ERROR_STOP=1 -c 'ALTER EXTENSION timescaledb UPDATE'
  done
}

checks() {
  before=$1
  [ -f "$before" ] || die "$before: the facts from before the move are needed"
  say "the version in every database that holds the extension"
  for d in $(databases); do
    got=$(installed "$d")
    [ "$got" = "$TARGET_VERSION" ] || die "$d holds TimescaleDB $got, not $TARGET_VERSION"
    echo "ok    $d: $got"
  done
  say "rows, chunks and jobs as before; compressed chunks as many or more (a compression job may have run meanwhile)"
  after="$before.checked-$(now)"                    # beside the facts from before: the record of these checks
  facts > "$after"
  grep -vE '^(version|compressed:)' "$before" > "$after.cmp-before"
  grep -vE '^(version|compressed:)' "$after" > "$after.cmp-now"
  diff -u "$after.cmp-before" "$after.cmp-now" || die "the data or the jobs differ (above)"
  rm -f "$after.cmp-before" "$after.cmp-now"
  grep -vE '^(version|compressed:)' "$after"
  grep '^compressed:' "$before" | while read -r name count; do
    got=$(grep "^$name " "$after" | cut -d' ' -f2)
    [ "${got:-0}" -ge "$count" ] || die "$name: $count compressed chunks before, ${got:-0} now"
    echo "$name $count before, $got now"
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
  psql_ "$DB_NAME" -c "SELECT count(*) FROM timescaledb_information.jobs j,
    LATERAL alter_job(j.job_id, next_start => now()) WHERE j.job_id >= 1000 AND j.scheduled" > /dev/null
  wait=${JOB_WAIT_SECONDS:-300}
  deadline=$(( $(date +%s) + wait ))
  while :; do
    pending=$(psql_ "$DB_NAME" -c "SELECT count(*) FROM timescaledb_information.jobs j
      JOIN timescaledb_information.job_stats s USING (job_id)
      WHERE j.job_id >= 1000 AND j.scheduled
        AND (s.last_run_started_at IS NULL OR s.last_run_started_at < '$start' OR s.last_run_status IS DISTINCT FROM 'Success')")
    [ "$pending" = 0 ] && break
    [ "$(date +%s)" -lt "$deadline" ] || break
    sleep 5
  done
  psql_ "$DB_NAME" -c "SELECT j.job_id, j.proc_name, s.last_run_status, s.total_runs, s.total_failures
    FROM timescaledb_information.jobs j JOIN timescaledb_information.job_stats s USING (job_id)
    WHERE j.job_id >= 1000 ORDER BY j.job_id"
  [ "$pending" = 0 ] || die "$pending job(s) did not run with Success within ${wait}s after the update (JOB_WAIT_SECONDS)"
  echo "ok    every job ran again with Success"
}

# ---- move and resume: BACKUP_DIR/LABEL.unfinished records a move from its first change to its end ----------------
step() {  # step NAME: what the move does now, recorded for the next run
  current=$1
  printf 'stamp=%s\nstep=%s\n' "$stamp" "$1" >| "$state.tmp"
  mv -f "$state.tmp" "$state"
  say "$1"
}

stopped() {  # the EXIT trap of move and resume
  code=$?
  [ "$code" = 0 ] && return 0
  [ -f "$state" ] || return "$code"
  case "$current" in
    8.*) cat >&2 <<EOF

FAIL: the move of $label stopped at: $current
  The database is moved (steps 1 to 7 are done); a check of step 8 failed, often a job that had not yet run again
  with Success (timescaledb_information.job_errors, job_stats, above). $state records it, and a new move is refused
  until it is closed. Find the cause; then the checks again, which remove the record only when they pass:
    $SCRIPT close $dir $label
  (JOB_WAIT_SECONDS gives the jobs more time; resume would do it too, but repeats steps 3 to 7.)
EOF
      return "$code" ;;
  esac
  cat >&2 <<EOF

FAIL: the move of $label stopped at: $current
  It is unfinished, and the database may be half-moved; $state records it, and a new move is refused
  until it is finished. Find the cause above, then go on with the same settings (DB_EXEC, RECREATE, MANAGE):
    $SCRIPT resume $dir $label
  or go back to the old release from $dir/$label-before-$stamp.dump (docs/ops/upgrade.md, "The way back").
EOF
  return "$code"
}

finish() {  # steps 3 to 8, each safe to run again
  if ! answers; then                               # the server is down (a RECREATE that stopped): start it on the new image
    step "4. the same volume on the new image (RECREATE)"
    sh -c "$RECREATE"
    wait_ready
  fi
  step "3. the revision triggers off the tracked hypertables (manage.py core_rev_drop_hypertable_triggers)"
  manage core_rev_drop_hypertable_triggers
  if [ "$(image_version)" != "$TARGET_VERSION" ]; then
    step "4. the same volume on the new image (RECREATE)"
    sh -c "$RECREATE"
    wait_ready
  fi
  [ "$(image_version)" = "$TARGET_VERSION" ] || die "the server's image carries TimescaleDB $(image_version), not $TARGET_VERSION"
  step "5. ALTER EXTENSION timescaledb UPDATE in every database that holds it"
  update
  step "6. the revision triggers made again (manage.py core_rev_repair), the project's check quiet"
  manage core_rev_repair
  quiet_check
  step "7. pg_dump on the new release"
  newdump="$dir/$label-after-$(now).dump"
  $DB_EXEC pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$newdump.partial"
  [ -s "$newdump.partial" ] || die "the dump is empty"
  mv "$newdump.partial" "$newdump"
  step "8. the checks"
  checks "$dir/$label-before-$stamp.facts"
  rm -f "$state"
  say "moved: $dir/$label-before-$stamp.dump (old release; .roles.sql and .facts beside it), $newdump (new release)"
}

refuse_unfinished() {
  [ -f "$state" ] || return 0
  if grep -q '^step=8\.' "$state"; then
    die "a move of $label is moved but not closed: its checks stopped ($(tr '\n' ' ' < "$state")): $state. Nothing
  was done now. The checks again, which remove the record when they pass:  $SCRIPT close $dir $label"
  fi
  die "a move of $label did not finish ($(tr '\n' ' ' < "$state")): $state. Nothing was done now.
  Go on with the same settings (DB_EXEC, RECREATE, MANAGE):  $SCRIPT resume $dir $label
  or go back to the old release (docs/ops/upgrade.md, \"The way back\")."
}

case "${1:-}" in
  move)
    [ $# = 3 ] || die "usage: timescaledb-move.sh move BACKUP_DIR LABEL"
    : "${RECREATE:?RECREATE: how to start the same data volume on the new image}"
    dir=$2 label=$3 state="$2/$3.unfinished" current="before the move"
    mkdir -p "$dir"
    refuse_unfinished
    say "where the database is"
    has=$(installed "$DB_NAME")
    image=$(image_version)
    echo "$DB_NAME holds TimescaleDB $has; the server's image carries $image; the move is to $TARGET_VERSION"
    say "every database that holds the extension"
    blocking=""
    for d in $(databases); do
      triggers=$(psql_ "$d" -c "$CONSTRAINT_TRIGGERS")
      echo "$d: TimescaleDB $(installed "$d"), $triggers constraint trigger(s) on hypertables and chunks"
      [ "$d" = "$DB_NAME" ] || [ "$triggers" = 0 ] || blocking="$blocking $d"
    done
    [ "$has" != "$TARGET_VERSION" ] || die "$DB_NAME already holds TimescaleDB $TARGET_VERSION: nothing to move, nothing
  was written. (A move of it that stopped half-way goes on with: $SCRIPT resume BACKUP_DIR LABEL, in the BACKUP_DIR it
  was started with.)"
    [ -z "$blocking" ] || die "the database(s)$blocking of this server hold constraint triggers on hypertable chunks
  (the project's revision triggers: a copy of the database, such as a test database left by a killed test run). The
  update would stop on them, and this move takes them off $DB_NAME only. Nothing was done. Drop each such database when
  it is a stale copy (DROP DATABASE ...), or take its revision triggers off first (manage.py
  core_rev_drop_hypertable_triggers against it), move, then make them again there (manage.py core_rev_repair)."
    manage migrate --check || die "a migration of this code is not applied (above): migrate first, then move"
    quiet_check || die "manage.py check --database default is not quiet (above): nothing was done. Mend that first. (A
  missing revision trigger, core.W005, can be a move that stopped half-way: its BACKUP_DIR holds LABEL.unfinished, and
  resume there goes on; otherwise manage.py core_rev_repair makes the triggers again.)"
    if [ "$image" != "$has" ]; then
      echo "note: the server already runs the image of TimescaleDB $image while $DB_NAME holds $has, and no move of
  $label is recorded here (the database was recreated on the new image before the move, e.g. by a docker compose up).
  The image carries the library of $has too, so the dump below is a dump of the old release; the move goes on."
    fi
    stamp=$(now)
    base="$dir/$label-before-$stamp"
    for f in "$base.facts" "$base.dump" "$base.roles.sql"; do [ ! -e "$f" ] || die "$f exists: never overwritten"; done
    set -C                                           # from here on no file is overwritten
    # each written as .partial and renamed once all three are whole: a failed dump never looks like one
    say "1. facts before"
    facts > "$base.facts.partial"
    cat "$base.facts.partial"
    say "2. pg_dump on the old release, and the cluster's roles"
    $DB_EXEC pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$base.dump.partial" \
      || die "pg_dump failed: $base.dump.partial is not a dump (remove it); nothing else was done"
    [ -s "$base.dump.partial" ] || die "the dump is empty"
    (umask 077 && $DB_EXEC pg_dumpall -U "$DB_USER" --roles-only > "$base.roles.sql.partial") \
      || die "pg_dumpall failed: $base.roles.sql.partial is not whole (remove it); nothing else was done"
    [ -s "$base.roles.sql.partial" ] || die "the roles are empty"
    for f in "$base.facts" "$base.dump" "$base.roles.sql"; do mv "$f.partial" "$f"; done
    trap stopped EXIT
    finish ;;
  resume)
    [ $# = 3 ] || die "usage: timescaledb-move.sh resume BACKUP_DIR LABEL"
    : "${RECREATE:?RECREATE: how to start the same data volume on the new image}"
    dir=$2 label=$3 state="$2/$3.unfinished" current="resume"
    [ -f "$state" ] || die "no unfinished move of $label in $dir ($state): nothing to resume"
    stamp=$(sed -n 's/^stamp=//p' "$state")
    [ -f "$dir/$label-before-$stamp.facts" ] || die "$dir/$label-before-$stamp.facts is missing"
    say "the move of $label from $stamp, which stopped at: $(sed -n 's/^step=//p' "$state")"
    set -C
    trap stopped EXIT
    finish ;;
  close)
    [ $# = 3 ] || die "usage: timescaledb-move.sh close BACKUP_DIR LABEL"
    dir=$2 label=$3 state="$2/$3.unfinished"
    [ -f "$state" ] || die "no unfinished move of $label in $dir ($state): nothing to close"
    grep -q '^step=8\.' "$state" || die "the move of $label stopped before its checks ($(tr '\n' ' ' < "$state")): it
  is not moved; go on with: $SCRIPT resume $dir $label"
    stamp=$(sed -n 's/^stamp=//p' "$state")
    log="$dir/$label-before-$stamp.closed-$(now).log"
    set -C
    echo "close of the move of $label ($(tr '\n' ' ' < "$state")), $(date)" > "$log"
    say "the checks again against $dir/$label-before-$stamp.facts (logged in $log)"
    # in a subshell (a failed check exits it, not the close) and into the log first, then shown
    if (checks "$dir/$label-before-$stamp.facts") >> "$log" 2>&1; then
      cat "$log"
      rm -f "$state"
      echo "closed: the checks passed, $state removed" | tee -a "$log"
    else
      cat "$log"
      echo "not closed: a check failed (above); $state is kept" | tee -a "$log"
      exit 1
    fi ;;
  back)
    [ $# = 6 ] || die "usage: timescaledb-move.sh back DUMP FACTS_BEFORE OLD_IMAGE NEW_IMAGE VOLUME"
    dump=$2 facts_before=$3 old=$4 new=$5 volume=$6
    roles="${dump%.dump}.roles.sql"
    : "${BACK_NETWORK:?BACK_NETWORK: the network MANAGE reaches the database on}"
    : "${BACK_ALIAS:?BACK_ALIAS: the host name MANAGE reaches the database at (its DB_HOST)}"
    [ -s "$dump" ] && [ -f "$facts_before" ] || die "$dump and $facts_before are needed"
    [ -s "$roles" ] || die "$roles is needed: the cluster's roles, saved by the move beside its dump"
    ! docker volume inspect "$volume" > /dev/null 2>&1 || die "$volume exists: a new volume is restored into, never an old one"
    [ -z "$(docker ps -aq --filter name='^timescaledb-back$')" ] || die "a container timescaledb-back exists: remove it first"
    say "room for a second whole copy of the database on Docker's disk"
    need=$(( $(wc -c < "$dump") / 1024 * ${BACK_ROOM_FACTOR:-10} ))
    docker_free=$(docker run --rm --entrypoint sh "$old" -c 'df -Pk / | tail -n 1' | awk '{print $4}')
    echo "needed about $need KB (BACK_ROOM_FACTOR ${BACK_ROOM_FACTOR:-10} times the dump); Docker's disk has $docker_free KB free"
    [ "$docker_free" -ge "$need" ] || die "not enough room on Docker's disk for the way back: $docker_free KB free,
  about $need KB needed. Nothing was made. Make room (docker system df shows what Docker holds), then try again."
    if [ -n "${DOCKER_HOST_DRIVE:-}" ]; then
      host_free=$(df -Pk "$DOCKER_HOST_DRIVE" | tail -n 1 | awk '{print $4}')
      echo "$DOCKER_HOST_DRIVE (the drive that holds Docker's disk image) has $host_free KB free"
      [ "$host_free" -ge "$need" ] || die "not enough room on $DOCKER_HOST_DRIVE, which holds Docker's disk image:
  $host_free KB free, about $need KB needed. Nothing was made."
    fi
    log="${dump%.dump}.back-$(now).log"
    set -C
    docker volume create "$volume" > /dev/null
    back_stopped() {
      code=$?
      [ "$code" = 0 ] && return 0
      docker rm -f timescaledb-back > /dev/null 2>&1 || true
      cat >&2 <<EOF

FAIL: the way back stopped (above; the messages of the roles and the restore: $log).
  The container timescaledb-back is removed. The new volume $volume is left as it is, to be looked at; remove it
  before another try:  docker volume rm $volume
  The old volume was not touched.
EOF
      return "$code"
    }
    trap back_stopped EXIT
    run() { docker run -d --name timescaledb-back --network "$BACK_NETWORK" --network-alias "$BACK_ALIAS" \
              -e POSTGRES_USER="$DB_USER" -e POSTGRES_DB="$DB_NAME" -e POSTGRES_PASSWORD="$(openssl rand -hex 16)" \
              -v "$volume:/var/lib/postgresql/data" "$1" postgres -c timescaledb.telemetry_level=off > /dev/null; }
    say "the old image ($old) on the new volume $volume"
    run "$old"
    DB_EXEC="docker exec -i timescaledb-back"
    # the image's first start makes the database on a server of its own, then starts the real one
    for _ in $(seq 1 120); do
      docker logs timescaledb-back 2>&1 | grep -q 'init process complete' && break
      sleep 2
    done
    wait_ready
    say "the cluster's roles as they were, with their passwords ($roles)"
    $DB_EXEC psql -X -U "$DB_USER" -d postgres < "$roles" > "$log" 2>&1 || die "the roles could not be applied ($log)"
    # the role the image made (DB_USER) is there already: its CREATE fails, its ALTER (with the password) holds
    if grep 'ERROR' "$log" | grep -v "role \"$DB_USER\" already exists"; then die "the roles could not be applied (above)"; fi
    say "the restore"
    psql_ "$DB_NAME" -c 'SELECT timescaledb_pre_restore()' > /dev/null
    $DB_EXEC pg_restore -U "$DB_USER" -d "$DB_NAME" < "$dump" >> "$log" 2>&1 || true
    psql_ "$DB_NAME" -c 'SELECT timescaledb_post_restore()' > /dev/null
    if grep '^pg_restore: error' "$log" | grep -v 'unique constraint "metadata_pkey"'; then
      die "pg_restore failed (above)"
    fi
    docker rm -f timescaledb-back > /dev/null
    say "the new image ($new) on the same volume"
    run "$new"
    wait_ready
    say "the revision triggers off the tracked hypertables, the update, the triggers made again, the checks"
    manage core_rev_drop_hypertable_triggers
    update
    manage core_rev_repair
    quiet_check
    checks "$facts_before"
    docker rm -f timescaledb-back > /dev/null
    trap - EXIT
    say "back: $volume holds the database on the new release, with its roles and their passwords; point the stack at it (docs/ops/upgrade.md)" ;;
  update) update ;;
  checks) [ $# = 2 ] || die "usage: timescaledb-move.sh checks FACTS_BEFORE"; checks "$2" ;;
  facts) facts ;;
  *) die "usage: timescaledb-move.sh move BACKUP_DIR LABEL | resume BACKUP_DIR LABEL | close BACKUP_DIR LABEL | back ... | update | checks FACTS_BEFORE | facts" ;;
esac
