#!/bin/sh
# The database image's first start (an empty data volume) runs this after TimescaleDB's own set-up, as the superuser:
# the roles, the extensions and the ownership of deploy/db/sql/roles.sql, and the one replication line the backup
# needs (pg_basebackup as balik_backup, password required). Never again on that volume: a role's password is changed
# by docs/ops/rotate-secrets.md. Executable, so the image's entrypoint runs it in a shell of its own (a sourced
# script would change the entrypoint's own shell options).
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f /etc/balik/sql/roles.sql || exit 1
echo "host replication balik_backup all scram-sha-256" >> "$PGDATA/pg_hba.conf" || exit 1
