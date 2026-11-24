#!/bin/sh
# Gives a database role a new random password (docs/ops/rotate-secrets.md). Run from deploy/:
#
#   sh scripts/rotate-db-password.sh balik_app
#
# SECRETS_DIR comes from the environment, else from farm.env (ENV_FILE). In this order, stopping at the first failure:
#   1. the role's secret file must exist and its folder be writable (nothing is changed otherwise);
#   2. the new password is written next to it (.<name>.new, readable by its owner only) before the database is touched;
#   3. the database is given the password's SCRAM-SHA-256 verifier, made in the web image from the password on stdin:
#      the plain password never reaches the database server, so no statement, log line or activity view holds it;
#   4. the secret file is replaced in one step (no copy of the old password is kept), mode 0444 like the others;
#   5. the services that sign in as the role are recreated, so they read the new file.
# The new password is never lost: it is written (.<name>.new) before any step that can fail and kept until it has
# replaced the secret file; each failure says whether the database has it and what to do with that file.
#
# Roles: balik_app (web, jobs), balik_owner (the release step), sensors_ingest (ingest), balik_backup (backup),
# postgres (the superuser: the restore service). The database container keeps the copies it was started with (it reads
# them at its first start only); scripts/check-roles.sh reads the passwords from SECRETS_DIR, so it holds right after.
set -eu
cd "$(dirname "$0")/.."
ENV_FILE=${ENV_FILE:-farm.env}
COMPOSE=${COMPOSE:-docker compose --env-file $ENV_FILE}
if [ -z "${SECRETS_DIR:-}" ] && [ -f "$ENV_FILE" ]; then
  SECRETS_DIR=$(sed -n 's/^SECRETS_DIR=//p' "$ENV_FILE" | tail -n 1)
fi
DIR=${SECRETS_DIR:-./secrets}
case "${1:-}" in
  balik_app) secret=db_app_password services="web jobs" ;;
  balik_owner) secret=db_owner_password services="" ;;
  sensors_ingest) secret=db_ingest_password services="ingest" ;;
  balik_backup) secret=db_backup_password services="backup" ;;
  postgres) secret=postgres_password services="" ;;
  *) echo "usage: rotate-db-password.sh balik_app|balik_owner|sensors_ingest|balik_backup|postgres" >&2; exit 2 ;;
esac
role=$1
if [ -n "$services" ]; then recreate=", then recreate: dc up -d --no-deps --force-recreate $services"; else recreate=" (no service signs in as $role: nothing to recreate)"; fi
[ -f "$DIR/$secret" ] || { echo "$DIR/$secret does not exist: is SECRETS_DIR right ($DIR)?" >&2; exit 1; }
[ -w "$DIR" ] || { echo "$DIR is not writable: run as the user who owns the secrets" >&2; exit 1; }
umask 077
new=$(openssl rand -base64 64 | tr -d '\n+/=' | cut -c1-42)
[ "${#new}" -ge 32 ] || { echo "openssl gave too little" >&2; exit 1; }
pending=$DIR/.$secret.new
[ ! -e "$pending" ] || { echo "$pending exists: a rotation before did not finish; read its message, or remove the file" >&2; exit 1; }
printf '%s\n' "$new" > "$pending" && [ "$(head -n 1 "$pending")" = "$new" ] \
  || { echo "the new password could not be written to $pending: nothing was changed" >&2; exit 1; }
before() { echo "$1. The database was NOT changed: the old password still works; remove $pending." >&2; exit 1; }
unsure() {
  echo "$1. The database MAY have the new password, which is kept in $pending: sign in with it (psql -h db -U $role)." \
       "If it works, finish by hand: chmod 0444 $pending && mv $pending $DIR/$secret$recreate." \
       "If not, remove $pending." >&2
  exit 1
}
after() {
  echo "$1. The database HAS the new password, kept in $pending: finish by hand:" \
       "chmod 0444 $pending && mv $pending $DIR/$secret$recreate." >&2
  exit 1
}

verifier=$(printf '%s\n' "$new" | $COMPOSE run --rm -T --entrypoint python manage -c '
import base64, hashlib, hmac, os, sys
password = sys.stdin.readline().rstrip("\n").encode()
salt, rounds = os.urandom(16), 4096
salted = hashlib.pbkdf2_hmac("sha256", password, salt, rounds)
client = hmac.new(salted, b"Client Key", "sha256").digest()
server = hmac.new(salted, b"Server Key", "sha256").digest()
b64 = lambda raw: base64.b64encode(raw).decode()
print(f"SCRAM-SHA-256${rounds}:{b64(salt)}${b64(hashlib.sha256(client).digest())}:{b64(server)}")') || before "the web image could not make the verifier"
case "$verifier" in 'SCRAM-SHA-256$4096:'*) ;; *) before "no SCRAM verifier was made" ;; esac

printf '%s\n' "$verifier" | $COMPOSE exec -T -e ROLE="$role" db sh -c '
  set -eu
  read -r verifier
  PGPASSWORD=$(head -n 1 /run/secrets/postgres_password) psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres \
    -d "$POSTGRES_DB" -v role="$ROLE" -v verifier="$verifier" <<"SQL"
ALTER ROLE :"role" PASSWORD :'"'"'verifier'"'"';
SQL' || unsure "the database did not confirm the change"
echo "the database has the new password of $role (as its verifier)"

chmod 0444 "$pending" || after "the new file's mode could not be set"
mv -f "$pending" "$DIR/$secret" || after "the secret file could not be replaced"
echo "$DIR/$secret replaced"

if [ -n "$services" ]; then
  # shellcheck disable=SC2086 # the services are words
  $COMPOSE up -d --no-deps --force-recreate $services
fi
echo "done."
