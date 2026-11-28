#!/bin/sh
# Proves the database roles of an installed farm server (deploy/db/sql/roles.sql, docs/ops/database-roles.md): every
# statement below is run as the role named, from inside the database container to its network address `db` (so the
# password is asked: the image trusts 127.0.0.1 inside the container), with that role's own password, read from its file
# in SECRETS_DIR (the environment, else farm.env) and handed over on stdin, never on a command line: so it holds right
# after a password rotation too, without recreating the database container. Every statement must be refused or allowed
# as stated; every check is reported; exit 1 when one failed. Changes nothing: every allowed write is rolled back.
#
#   cd deploy && sh scripts/check-roles.sh                 (uses farm.env; ENV_FILE=... for another)
#   COMPOSE="docker compose -p x --env-file y" sh scripts/check-roles.sh
set -eu
cd "$(dirname "$0")/.."
ENV_FILE=${ENV_FILE:-farm.env}
COMPOSE=${COMPOSE:-docker compose --env-file $ENV_FILE}
if [ -z "${SECRETS_DIR:-}" ] && [ -f "$ENV_FILE" ]; then
  SECRETS_DIR=$(sed -n 's/^SECRETS_DIR=//p' "$ENV_FILE" | tail -n 1)
fi
DIR=${SECRETS_DIR:-./secrets}
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
  [ -r "$DIR/$secret" ] || { echo "$DIR/$secret cannot be read: is SECRETS_DIR right?" >&2; exit 2; }
  head -n 1 "$DIR/$secret" | $COMPOSE exec -T -e ROLE="$role" -e SQL="$sql" db sh -c \
    'read -r password; PGPASSWORD=$password psql -X -h db -U "$ROLE" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At -c "$SQL"' 2>&1
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
refused balik_app "DELETE FROM alarm_open WHERE false"
refused balik_app "INSERT INTO alarm_open (alarm_id) SELECT id FROM alarms WHERE false"
# A SECURITY DEFINER function (core.operations.DefinerTrigger) is called by its own trigger only: neither runtime role
# may call one, nor make the temporary table a trigger of its own would need to hand it a table of its choosing.
equals balik_app "SELECT count(*) FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace AND p.prosecdef AND (has_function_privilege('balik_app', p.oid, 'EXECUTE') OR has_function_privilege('sensors_ingest', p.oid, 'EXECUTE'))" 0
refused balik_app "CREATE TEMP TABLE check_roles (id int)"
refused sensors_ingest "CREATE TEMP TABLE check_roles (id int)"
refused balik_app "BEGIN; CREATE TEMP TABLE alarms (LIKE public.alarms INCLUDING DEFAULTS); CREATE TRIGGER forged AFTER INSERT ON pg_temp.alarms REFERENCING NEW TABLE AS opened FOR EACH STATEMENT EXECUTE FUNCTION public.alarm_open_opened(); ROLLBACK"
# Every other function stays the app's to call, as its triggers do (core_rev_note and the rest, deferred until the
# commit): a tracked table written as the app, its deferred triggers run at once (rolled back).
allowed balik_app "BEGIN; UPDATE platform_settings SET id = id; SET CONSTRAINTS ALL IMMEDIATE; SELECT 1 / count(*) FROM platform_settings; ROLLBACK"
allowed balik_app "BEGIN; INSERT INTO alarms (source, parameter, severity, opened_at, summary) VALUES ('system', 'check_roles', 'warning', now(), 'check-roles'); ROLLBACK"
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
