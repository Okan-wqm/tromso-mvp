#!/bin/sh
# Gives a database role a new random password (docs/ops/rotate-secrets.md), in this order: the role's password in the
# database (as the superuser, inside the database container; the new password goes on stdin, never on a command line),
# then its secret file in SECRETS_DIR (replaced in one step, the old one kept as <name>.old until you delete it), then
# the services that sign in as that role are recreated so that they read the new file. Run from deploy/:
#
#   SECRETS_DIR=/etc/balik/farm-a/secrets sh scripts/rotate-db-password.sh balik_app
#
# Roles: balik_app (web, jobs), balik_owner (release), sensors_ingest (ingest), balik_backup (backup), postgres (the
# superuser: the restore service and maintenance). Between the change and the recreation (seconds) a new connection
# of an old container is refused; the connections already open stay.
set -eu
cd "$(dirname "$0")/.."
DIR=${SECRETS_DIR:-./secrets}
COMPOSE=${COMPOSE:-docker compose --env-file ${ENV_FILE:-farm.env}}
case "${1:-}" in
  balik_app) secret=db_app_password services="web jobs" ;;
  balik_owner) secret=db_owner_password services="" ;;
  sensors_ingest) secret=db_ingest_password services="ingest" ;;
  balik_backup) secret=db_backup_password services="backup" ;;
  postgres) secret=postgres_password services="" ;;
  *) echo "usage: rotate-db-password.sh balik_app|balik_owner|sensors_ingest|balik_backup|postgres" >&2; exit 2 ;;
esac
role=$1
umask 077
new=$(openssl rand -base64 64 | tr -d '\n+/=' | cut -c1-42)
[ "${#new}" -ge 32 ] || { echo "openssl gave too little" >&2; exit 1; }

printf '%s\n' "$new" | $COMPOSE exec -T -e ROLE="$role" db sh -c '
  set -eu
  umask 077
  read -r password
  printf "%s\n" "$password" > /tmp/rotate-password
  PGPASSWORD=$(head -n 1 /run/secrets/postgres_password) psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres \
    -d "$POSTGRES_DB" -v role="$ROLE" <<"SQL"
\set password `head -n 1 /tmp/rotate-password`
ALTER ROLE :"role" PASSWORD :'"'"'password'"'"';
SQL
  rm -f /tmp/rotate-password'
echo "the database has the new password of $role"

cp -p "$DIR/$secret" "$DIR/$secret.old"
printf '%s\n' "$new" > "$DIR/.$secret.new"
chmod 0444 "$DIR/.$secret.new"
mv -f "$DIR/.$secret.new" "$DIR/$secret"
echo "$DIR/$secret replaced (the old one is $DIR/$secret.old: delete it once everything runs)"

if [ -n "$services" ]; then
  # shellcheck disable=SC2086 # the services are words
  $COMPOSE up -d --no-deps --force-recreate $services
fi
echo "done. The release step reads balik_owner's at the next upgrade; postgres's is read by the restore service."
