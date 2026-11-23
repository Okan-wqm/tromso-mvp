#!/bin/sh
# The backup agent (deploy/compose.yml service `backup`, docs/ops/backup-and-restore.md). Runs as postgres in the
# image of deploy/db/Dockerfile (target backup): the database server's own pg_dump, pg_basebackup, pg_archivecleanup,
# pg_restore and psql, and restic.
#
#   agent.sh [run]            the loop: every BACKUP_TICK_SECONDS it does what is due:
#                               dump  pg_dump of the farm's database (custom format), checked by pg_restore --list,
#                                     with the row count of every table beside it, every BACKUP_DUMP_HOURS (24)
#                               base  pg_basebackup (tar, gzip, the WAL it needs streamed in), every BACKUP_BASE_DAYS (7);
#                                     with the WAL the server archives into /wal-archive (archive_command,
#                                     archive_timeout, 15 min) it restores the database to any moment since
#                               ship  restic backup of the dumps, the base backups, the archived WAL and the uploaded
#                                     files (media) to RESTIC_REPOSITORY: encrypted (the repository's password,
#                                     RESTIC_PASSWORD_FILE) and off the server, every BACKUP_SHIP_MINUTES (15)
#                               forget  the retention below, then prune, once a day: only with BACKUP_PRUNE_ON_FARM=1.
#                                     Off by default: the farm's key is append-only (it can add, never delete), so
#                                     a stolen server cannot remove its own backups; the owner prunes from another
#                                     machine with a key of their own (docs/ops/backup-and-restore.md)
#                               check   restic check with a 5 % sample of the data read back, once a week
#                               prunecheck  once a day: red when the owner's monthly prune is overdue (too many
#                                     snapshots older than BACKUP_PRUNE_AGE_DAYS, 35)
#                             each success is written to /backups/state/<job>.ok, each failure to <job>.failed;
#                             `health` (the container's health check) fails when a job is overdue or failed last
#   agent.sh init             makes the restic repository (once, at installation; never automatic: a mistyped
#                             address must not silently become a new, empty repository)
#   agent.sh now              dump, base, ship, in that order, now (installation check, before an upgrade)
#   agent.sh dump|base|ship|forget|check|prunecheck   one job now
#   agent.sh snapshots        the repository's snapshots of this installation
#   agent.sh restic ARGS...   any restic command on the repository (key add, key list, check, ...)
#   agent.sh fetch SNAPSHOT DIR             restores a snapshot (`latest` or an id) from the repository into DIR
#   agent.sh restore-dump FILE              pg_restore of a dump into PGDATABASE (an empty farm database made by the
#                                           database image's first start): as the superuser, `restore` service
#   agent.sh counts           the row count of every table of PGDATABASE, and its chunks, one "name count" a line
#   agent.sh verify-counts FILE             compares `counts` now with FILE (a dump's .counts): exit 1 on a difference
#   agent.sh prepare-pitr BASEDIR WALDIR PGDATA [TARGET_TIME]
#                             a data folder for a point-in-time restore: the base backup of BASEDIR, the WAL of WALDIR
#                             replayed up to TARGET_TIME (UTC, "2026-11-23 14:05:00+00") or to the end of the WAL
#
# Environment (deploy/compose.yml, deploy/farm.env): PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD_FILE;
# RESTIC_REPOSITORY, RESTIC_PASSWORD_FILE and the repository's own credentials (SECRETS_DIR/backup.env);
# BACKUP_HOST_TAG (this installation's name in the repository); the intervals above; the retention
# BACKUP_KEEP_HOURLY (48), BACKUP_KEEP_DAILY (14), BACKUP_KEEP_WEEKLY (8), BACKUP_KEEP_MONTHLY (12);
# BACKUP_LOCAL_DUMPS (3) and BACKUP_LOCAL_BASES (1): how many stay on the server as well. The archived WAL stays on the
# server from the oldest local base backup on, and only until it is shipped: every ship removes what it has shipped
# and the base backups kept here no longer need (docs/ops/backup-and-restore.md, the disk budget).
set -eu

B=/backups
STATE=$B/state
DUMPS=$B/dumps
BASES=$B/base
WAL=/wal-archive
MEDIA=/media-ro
HOST_TAG=${BACKUP_HOST_TAG:-farm}
export RESTIC_CACHE_DIR=${RESTIC_CACHE_DIR:-$B/.restic-cache}
umask 077

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup: $*"; }
die() { log "ERROR: $*"; exit 1; }
num() {  # num NAME DEFAULT: a whole number of 1 or more from the environment
  value=$(printenv "$1" || true)
  value=${value:-$2}
  case "$value" in ''|*[!0-9]*) die "$1=$value is not a whole number" ;; esac
  [ "$value" -ge 1 ] || die "$1 must be 1 or more"
  echo "$value"
}

TICK=$(num BACKUP_TICK_SECONDS 60)
DUMP_HOURS=$(num BACKUP_DUMP_HOURS 24)
BASE_DAYS=$(num BACKUP_BASE_DAYS 7)
SHIP_MINUTES=$(num BACKUP_SHIP_MINUTES 15)
DUMP_EVERY=$(( DUMP_HOURS * 3600 ))
BASE_EVERY=$(( BASE_DAYS * 86400 ))
SHIP_EVERY=$(( SHIP_MINUTES * 60 ))
FORGET_EVERY=86400
PRUNE_ON_FARM=$(printenv BACKUP_PRUNE_ON_FARM || echo 0)
CHECK_EVERY=604800
LOCAL_DUMPS=$(num BACKUP_LOCAL_DUMPS 3)
LOCAL_BASES=$(num BACKUP_LOCAL_BASES 1)
KEEP_HOURLY=$(num BACKUP_KEEP_HOURLY 48)
KEEP_DAILY=$(num BACKUP_KEEP_DAILY 14)
KEEP_WEEKLY=$(num BACKUP_KEEP_WEEKLY 8)
KEEP_MONTHLY=$(num BACKUP_KEEP_MONTHLY 12)

# No CA of the REST server's own (a public certificate): restic must not be handed an empty one.
if [ -z "${RESTIC_CACERT:-}" ] || [ ! -s "${RESTIC_CACERT:-}" ]; then unset RESTIC_CACERT; fi
PRUNECHECK_EVERY=86400
PRUNE_AGE_DAYS=$(num BACKUP_PRUNE_AGE_DAYS 35)

if [ -n "${PGPASSWORD_FILE:-}" ]; then
  [ -r "$PGPASSWORD_FILE" ] || die "PGPASSWORD_FILE $PGPASSWORD_FILE cannot be read"
  PGPASSWORD=$(head -n 1 "$PGPASSWORD_FILE")
  export PGPASSWORD
fi

now() { date -u +%s; }
stamp() { date -u +%Y%m%dT%H%M%SZ; }
last() { if [ -f "$STATE/$1.ok" ]; then cat "$STATE/$1.ok"; else echo 0; fi; }
mark() {  # mark JOB ok|failed
  mkdir -p "$STATE"
  if [ "$2" = ok ]; then now > "$STATE/$1.ok"; rm -f "$STATE/$1.failed"; else now > "$STATE/$1.failed"; fi
}
keep_newest() {  # keep_newest DIR COUNT SUFFIX: removes all but the COUNT newest finished balik-<time>Z<SUFFIX>
  ls -1d "$1"/balik-*Z"$3" 2>/dev/null | sort -r | tail -n +"$(( $2 + 1 ))" | while read -r old; do
    rm -rf "$old" "$old.counts" "$old.sha256"
    log "removed the local copy $old (the repository keeps it by its own retention)"
  done
}

counts() {
  # Every table of the application (a hypertable counts the rows of all its chunks), then each hypertable's chunks.
  # Not compared: what TimescaleDB's own jobs change on their schedule without changing a row (a chunk compressed, a
  # continuous aggregate refreshed into its internal table), which a restored database's jobs may do at once.
  psql -X -v ON_ERROR_STOP=1 -At -F ' ' <<'SQL'
SELECT format('SELECT %L, count(*) FROM %I.%I', c.relname, n.nspname, c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
ORDER BY c.relname
\gexec
SELECT 'chunks:' || hypertable_name, count(*) FROM timescaledb_information.chunks
WHERE hypertable_schema = 'public' GROUP BY hypertable_name ORDER BY hypertable_name;
SQL
}

dump() {
  mkdir -p "$DUMPS"
  name=$DUMPS/balik-$(stamp).dump
  log "dump of $PGDATABASE into $name"
  # The counts first, then the dump: on a quiet database (a restore check) they agree row for row; on a busy one they
  # show what the dump holds within the minutes it took.
  counts > "$name.counts.part"
  pg_dump --format=custom --compress=6 --file="$name.part" "$PGDATABASE"
  pg_restore --list "$name.part" > /dev/null
  mv "$name.counts.part" "$name.counts"
  mv "$name.part" "$name"
  (cd "$DUMPS" && sha256sum "$(basename "$name")" > "$(basename "$name").sha256")
  keep_newest "$DUMPS" "$LOCAL_DUMPS" .dump
  log "dump done: $(du -h "$name" | cut -f1)"
}

base() {
  mkdir -p "$BASES"
  name=$BASES/balik-$(stamp)
  log "base backup into $name"
  pg_basebackup --pgdata="$name.part" --format=tar --gzip --wal-method=stream --checkpoint=fast \
    --label="$(basename "$name")" --no-password
  mv "$name.part" "$name"
  keep_newest "$BASES" "$LOCAL_BASES" ""
  cleanup_wal
  log "base backup done: $(du -sh "$name" | cut -f1)"
}

start_wal() {  # start_wal BASEDIR: the first WAL file a base backup needs (its backup_label)
  tar -xzOf "$1/base.tar.gz" backup_label | sed -n 's/^START WAL LOCATION: .*(file \([0-9A-F]*\))$/\1/p'
}

cleanup_wal() {  # cleanup_wal [SHIPPED]: SHIPPED the time of a ship that just succeeded (default: the last recorded)
  # The archived WAL older than the oldest base backup kept here is no longer needed on the server, once it has been
  # shipped: never while the last ship is older than that base backup.
  oldest=$(ls -1d "$BASES"/balik-*Z 2>/dev/null | sort | head -n 1)
  [ -n "$oldest" ] || return 0
  shipped=${1:-$(last ship)}
  made=$(stat -c %Y "$oldest")
  if [ "$shipped" -le "$made" ]; then
    log "archived WAL kept: the last ship is older than the oldest base backup $oldest"
    return 0
  fi
  first=$(start_wal "$oldest")
  [ -n "$first" ] || die "no START WAL LOCATION in $oldest/base.tar.gz"
  pg_archivecleanup "$WAL" "$first"
  log "archived WAL before $first removed from the server"
}

wal_whole() {
  # Every archived WAL segment is a whole one (16 MiB): a shorter file is a copy cut short, and shipped it would end a
  # point-in-time restore there. The history and backup-label files (.history, .backup) and the copies under way
  # (.tmp) are other files.
  short=""
  for segment in "$WAL"/*; do
    name=$(basename "$segment")
    case "$name" in *.history|*.backup|*.tmp|'*') continue ;; esac
    size=$(stat -c %s "$segment")
    if [ "$size" != 16777216 ]; then short="$short $name ($size bytes)"; fi
  done
  if [ -n "$short" ]; then die "archived WAL segment(s) not 16 MiB, nothing shipped:$short"; fi
}

ship() {
  mkdir -p "$DUMPS" "$BASES"
  started=$(now)
  wal_whole
  log "ship to the repository (host $HOST_TAG)"
  restic backup --retry-lock 10m --no-scan --host "$HOST_TAG" --tag balik --exclude '*.part' --exclude '*.tmp' \
    "$DUMPS" "$BASES" "$WAL" "$MEDIA"
  log "ship done"
  cleanup_wal "$started"
}

forget() {
  log "retention: hourly $KEEP_HOURLY, daily $KEEP_DAILY, weekly $KEEP_WEEKLY, monthly $KEEP_MONTHLY"
  restic forget --retry-lock 10m --host "$HOST_TAG" --tag balik --prune --keep-hourly "$KEEP_HOURLY" --keep-daily "$KEEP_DAILY" \
    --keep-weekly "$KEEP_WEEKLY" --keep-monthly "$KEEP_MONTHLY"
}

check() {
  log "repository check (5 % of the data read back)"
  restic check --retry-lock 10m --read-data-subset=5%
}

prunecheck() {
  # The owner prunes the repository monthly from another machine (the farm's key may only add). Whether it happened is
  # seen from here: a pruned repository keeps at most the weekly and monthly snapshots (and a few more) older than
  # BACKUP_PRUNE_AGE_DAYS (35); an unpruned one keeps every ship's, about a hundred a day.
  cutoff=$(date -u -d "@$(( $(now) - PRUNE_AGE_DAYS * 86400 ))" +%Y-%m-%dT%H:%M:%S)
  limit=$(( KEEP_WEEKLY + KEEP_MONTHLY + 5 ))
  old=$(restic snapshots --retry-lock 10m --host "$HOST_TAG" --tag balik --json \
    | grep -o '"time":"[^"]*"' | cut -d'"' -f4 | cut -c1-19 | awk -v cutoff="$cutoff" '$0 < cutoff' | wc -l)
  if [ "$old" -gt "$limit" ]; then
    die "the owner's prune is overdue: $old snapshots older than $PRUNE_AGE_DAYS days (a pruned repository keeps $limit at most; docs/ops/backup-and-restore.md)"
  fi
  log "prune check: $old snapshot(s) older than $PRUNE_AGE_DAYS days, $limit allowed"
}

job() {  # job NAME: runs it in a shell of its own, so that its first failing command ends it (inside a condition a
         # function would run on past a failure: errexit is off there), and records the outcome
  if sh "$0" "_$1"; then mark "$1" ok; else mark "$1" failed; log "ERROR: $1 failed"; return 1; fi
}

due() {  # due JOB EVERY
  [ ! -f "$STATE/$1.failed" ] || [ "$(cat "$STATE/$1.failed")" -le "$(( $(now) - 900 ))" ] || return 1  # retry after 15 min
  [ "$(( $(now) - $(last "$1") ))" -ge "$2" ]
}

health() {
  # Unhealthy when a job failed last (each is retried after 15 minutes), when one is overdue, or when the database's
  # WAL archiver is failing: a WAL segment that cannot be archived is a backup that silently stops.
  slack=3600
  for job in forget check prunecheck; do
    if [ -f "$STATE/$job.failed" ]; then echo "$job failed last"; exit 1; fi
  done
  if [ "$(( $(now) - $(last check) ))" -gt "$(( CHECK_EVERY + 86400 ))" ] && [ -f "$STATE/ship.ok" ]; then
    echo "check overdue"; exit 1
  fi
  for spec in "dump $DUMP_EVERY" "ship $SHIP_EVERY" "base $BASE_EVERY"; do
    set -- $spec
    if [ -f "$STATE/$1.failed" ]; then echo "$1 failed last"; exit 1; fi
    age=$(( $(now) - $(last "$1") ))
    if [ "$age" -gt "$(( $2 + slack ))" ]; then echo "$1 overdue ($age s since the last success)"; exit 1; fi
  done
  archiver=$(psql -X -At -c "SELECT CASE WHEN last_failed_time IS NOT NULL AND (last_archived_time IS NULL
      OR last_failed_time > last_archived_time) THEN 'failing: ' || last_failed_wal ELSE 'ok' END FROM pg_stat_archiver") \
    || { echo "the database cannot be asked for its WAL archiver"; exit 1; }
  if [ "$archiver" != ok ]; then echo "the WAL archiver is $archiver (pg_stat_archiver)"; exit 1; fi
  echo ok
}

restore_dump() {
  file=$1
  [ -f "$file" ] || die "$file does not exist"
  if [ -f "$file.sha256" ]; then (cd "$(dirname "$file")" && sha256sum -c "$(basename "$file").sha256"); fi
  tables=$(psql -X -At -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
  [ "$tables" = 0 ] || die "$PGDATABASE already holds $tables tables: restore into an empty farm database only"
  log "restore of $file into $PGDATABASE"
  psql -X -v ON_ERROR_STOP=1 -c 'SELECT timescaledb_pre_restore()' > /dev/null
  status=0
  pg_restore --dbname="$PGDATABASE" "$file" 2> /tmp/restore.log || status=$?
  psql -X -v ON_ERROR_STOP=1 -c 'SELECT timescaledb_post_restore()' > /dev/null
  # Every statement pg_restore could not run is an error here, but one: the database's first start already wrote
  # TimescaleDB's own installation row (metadata, key exported_uuid), which the dump holds too. Anything else stops.
  grep '^pg_restore: error' /tmp/restore.log | grep -v 'unique constraint "metadata_pkey"' > /tmp/restore.errors || true
  if [ -s /tmp/restore.errors ] || { [ "$status" != 0 ] && ! grep -q 'metadata_pkey' /tmp/restore.log; }; then
    cat /tmp/restore.log
    die "pg_restore failed ($status)"
  fi
  if [ "$status" != 0 ]; then log "pg_restore: TimescaleDB's installation row was already there (kept the new one)"; fi
  psql -X -v ON_ERROR_STOP=1 -c 'ANALYZE' > /dev/null
  log "restore done"
}

verify_counts() {
  expected=$1
  [ -f "$expected" ] || die "$expected does not exist"
  counts > /tmp/counts.now
  if diff -u "$expected" /tmp/counts.now; then
    log "row counts agree: $(wc -l < /tmp/counts.now) tables and chunk counts, $(awk '{s += $2} END {print s}' /tmp/counts.now) rows and chunks"
  else
    die "row counts differ from $expected (above: - in the backup, + restored)"
  fi
}

prepare_pitr() {
  basedir=$1 waldir=$2 pgdata=$3 target=${4:-}
  [ -f "$basedir/base.tar.gz" ] || die "$basedir/base.tar.gz does not exist"
  [ ! -e "$pgdata/PG_VERSION" ] || die "$pgdata already holds a database"
  mkdir -p "$pgdata"
  chmod 0700 "$pgdata"
  tar -xzf "$basedir/base.tar.gz" -C "$pgdata"
  mkdir -p "$pgdata/pg_wal"
  tar -xzf "$basedir/pg_wal.tar.gz" -C "$pgdata/pg_wal"
  touch "$pgdata/recovery.signal"
  {
    echo "restore_command = 'cp $waldir/%f %p'"
    # Recovery refuses a server with fewer connections than the one the WAL came from: the farm's server sets it on
    # its command line (DB_MAX_CONNECTIONS in farm.env, 100), which the base backup does not carry.
    echo "max_connections = $(num DB_MAX_CONNECTIONS 100)"
    if [ -n "$target" ]; then echo "recovery_target_time = '$target'"; echo "recovery_target_action = 'promote'"; fi
  } >> "$pgdata/postgresql.auto.conf"
  log "data folder $pgdata ready: start the database image on it; it replays the WAL of $waldir${target:+ up to $target} and opens"
}

case "${1:-run}" in
  run)
    log "started: dump every $DUMP_EVERY s, base every $BASE_EVERY s, ship every $SHIP_EVERY s"
    while :; do
      if due dump "$DUMP_EVERY"; then job dump || true; fi
      if due base "$BASE_EVERY"; then job base || true; fi
      if due ship "$SHIP_EVERY"; then job ship || true; fi
      if [ "$PRUNE_ON_FARM" = 1 ] && due forget "$FORGET_EVERY"; then job forget || true; fi
      if due prunecheck "$PRUNECHECK_EVERY"; then job prunecheck || true; fi
      if due check "$CHECK_EVERY"; then job check || true; fi
      sleep "$TICK" &
      wait $! || true
    done ;;
  init) restic init ;;
  now) job dump && job base && job ship ;;
  dump|base|ship|forget|check|prunecheck) job "$1" ;;
  _dump|_base|_ship|_forget|_check|_prunecheck) "${1#_}" ;;
  health) health ;;
  snapshots) restic snapshots --host "$HOST_TAG" ;;
  restic) shift; exec restic "$@" ;;
  fetch) [ $# = 3 ] || die "usage: agent.sh fetch SNAPSHOT DIR"; restic restore "$2" --host "$HOST_TAG" --target "$3" ;;
  restore-dump) [ $# = 2 ] || die "usage: agent.sh restore-dump FILE"; restore_dump "$2" ;;
  counts) counts ;;
  verify-counts) [ $# = 2 ] || die "usage: agent.sh verify-counts FILE"; verify_counts "$2" ;;
  prepare-pitr) [ $# -ge 4 ] || die "usage: agent.sh prepare-pitr BASEDIR WALDIR PGDATA [TARGET_TIME]"
    prepare_pitr "$2" "$3" "$4" "${5:-}" ;;
  *) die "unknown command $1 (see the head of this file)" ;;
esac
