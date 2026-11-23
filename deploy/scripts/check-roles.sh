#!/bin/sh
# Proves the database roles of an installed farm server (deploy/db/sql/roles.sql, docs/ops/database-roles.md): every
# statement below is run as the role named, from inside the database container to its network address `db` (so the
# password is asked: the image trusts 127.0.0.1 inside the container), with that role's own password read there from its
# secret file, never on a command line, and must be refused or allowed as stated. Every check is reported; exit 1 when
# one failed. Changes nothing: every allowed write is rolled back.
#
#   cd deploy && sh scripts/check-roles.sh                 (uses farm.env; ENV_FILE=... for another)
#   COMPOSE="docker compose -p x --env-file y" sh scripts/check-roles.sh
set -eu
cd "$(dirname "$0")/.."
COMPOSE=${COMPOSE:-docker compose --env-file ${ENV_FILE:-farm.env}}
failures=0

as() {  # as ROLE SQL: runs SQL as ROLE; prints psql's output and errors
  role=$1 sql=$2
  case $role in
    balik_app) secret=db_app_password ;;
    balik_owner) secret=db_owner_password ;;
    sensors_ingest) secret=db_ingest_password ;;
    balik_backup) secret=db_backup_password ;;
    *) echo "unknown role $role" >&2; exit 2 ;;
  esac
  $COMPOSE exec -T -e ROLE="$role" -e SECRET="$secret" -e SQL="$sql" db sh -c \
    'PGPASSWORD=$(head -n 1 "/run/secrets/$SECRET") psql -X -h db -U "$ROLE" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At -c "$SQL"' 2>&1
}

refused() {  # refused ROLE SQL: must fail for want of a right
  if out=$(as "$1" "$2"); then
    echo "FAIL  $1 was allowed: $2"; failures=$((failures + 1))
  elif echo "$out" | grep -qiE 'permission denied|must be owner|must be superuser|must have|not allowed'; then
    echo "ok    $1 refused: $2"
  else
    echo "FAIL  $1 failed for another reason: $2 -> $out"; failures=$((failures + 1))
  fi
}

allowed() {  # allowed ROLE SQL: must succeed
  if out=$(as "$1" "$2"); then
    echo "ok    $1 allowed: $2"
  else
    echo "FAIL  $1 was refused: $2 -> $out"; failures=$((failures + 1))
  fi
}

equals() {  # equals ROLE SQL EXPECTED
  out=$(as "$1" "$2" || true)
  if [ "$out" = "$3" ]; then echo "ok    $1: $2 = $3"; else echo "FAIL  $1: $2 gave '$out', not '$3'"; failures=$((failures + 1)); fi
}

echo "== the app role (balik_app): rows only, never the shape of the database"
allowed balik_app "SELECT count(*) FROM django_migrations"
allowed balik_app "BEGIN; INSERT INTO django_session (session_key, session_data, expire_date) VALUES ('check-roles', '', now()); DELETE FROM django_session WHERE session_key = 'check-roles'; ROLLBACK"
refused balik_app "TRUNCATE django_session"
refused balik_app "TRUNCATE audit_log"
refused balik_app "CREATE TABLE check_roles (id int)"
refused balik_app "CREATE SCHEMA check_roles"
refused balik_app "ALTER TABLE django_session ADD COLUMN check_roles int"
refused balik_app "ALTER TABLE audit_log DISABLE TRIGGER ALL"
refused balik_app "DROP TABLE django_session"
refused balik_app "CREATE INDEX check_roles ON django_session (expire_date)"
refused balik_app "CREATE ROLE check_roles"
refused balik_app "UPDATE audit_log SET id = id WHERE false"
refused balik_app "DELETE FROM audit_log WHERE false"
refused balik_app "DELETE FROM alarms WHERE false"
refused balik_app "UPDATE alarm_acknowledgements SET id = id WHERE false"
refused balik_app "DELETE FROM withdrawal_acknowledgements WHERE false"
refused balik_app "UPDATE regulatory_report_snapshots SET content = content WHERE false"
equals balik_app "SELECT count(*) FROM information_schema.table_privileges WHERE grantee = 'balik_app' AND privilege_type IN ('TRUNCATE', 'REFERENCES', 'TRIGGER')" 0

echo "== the ingest role (sensors_ingest): its contract and its rows, nothing else"
allowed sensors_ingest "SELECT count(*) FROM sensors_ingest_config"
allowed sensors_ingest "BEGIN; INSERT INTO sensors_reading (channel_no, ts, value) VALUES (-1, now(), 1); ROLLBACK"
refused sensors_ingest "SELECT count(*) FROM auth_user"
refused sensors_ingest "DELETE FROM sensors_reading"
refused sensors_ingest "UPDATE sensors_reading SET value = 0"
refused sensors_ingest "TRUNCATE sensors_reading"
refused sensors_ingest "CREATE TABLE check_roles (id int)"
refused sensors_ingest "DROP TABLE sensors_reading"

echo "== the backup role (balik_backup): reads everything, writes nothing"
allowed balik_backup "SELECT count(*) FROM auth_user"
allowed balik_backup "SELECT count(*) FROM sensors_reading"
refused balik_backup "INSERT INTO django_session (session_key, session_data, expire_date) VALUES ('check-roles', '', now())"
refused balik_backup "TRUNCATE django_session"
refused balik_backup "CREATE TABLE check_roles (id int)"

echo "== the owner role (balik_owner): owns the tables, is no superuser"
equals balik_owner "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner <> 'balik_owner'" 0
equals balik_owner "SELECT string_agg(rolname || ':' || rolsuper || rolcreaterole || rolcreatedb, ',' ORDER BY rolname) FROM pg_roles WHERE rolname IN ('balik_owner', 'balik_app', 'sensors_ingest', 'balik_backup')" \
  "balik_app:falsefalsefalse,balik_backup:falsefalsefalse,balik_owner:falsefalsefalse,sensors_ingest:falsefalsefalse"
refused balik_owner "CREATE ROLE check_roles"
refused balik_owner "ALTER ROLE balik_app SUPERUSER"

if [ "$failures" -gt 0 ]; then
  echo "check-roles: $failures check(s) failed"
  exit 1
fi
echo "check-roles: every role holds"
