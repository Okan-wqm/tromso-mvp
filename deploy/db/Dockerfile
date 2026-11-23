# The farm's database server and its backup agent (deploy/compose.yml services `db` and `backup`).
#   db      PostgreSQL 17 with TimescaleDB 2.32.1 (pinned by digest; CI runs the whole suite on it: pg_image), the roles' first-start
#           script (init/, sql/roles.sql) and the folder the WAL is archived to, owned by postgres so that a new volume
#           mounted there is writable by the server
#   backup  the same image (its pg_dump, pg_basebackup and pg_archivecleanup are the server's own version) with restic,
#           which encrypts and copies the backups off the server (docs/ops/backup-and-restore.md); runs as postgres
# Build context: deploy/.
# The development database still runs 2.17.2 (docker-compose.yml, scripts/test.sh); docs/ops/upgrade.md, patch cadence.
FROM timescale/timescaledb:2.32.1-pg17@sha256:2f5e6969faa5cd7f4b075d65f124e30dc50d456b7b807e5c1acd9d51ba7df51c AS db
RUN mkdir -p /wal-archive /etc/balik/sql \
 && chown postgres:postgres /wal-archive \
 && chmod 0700 /wal-archive
COPY db/sql/ /etc/balik/sql/
COPY db/init/ /docker-entrypoint-initdb.d/
# run in a shell of its own, never sourced into the entrypoint's
RUN chmod 0755 /docker-entrypoint-initdb.d/100-balik-roles.sh

FROM db AS backup
# restic (BSD-2-Clause), the release binary checked against the sha256 its release lists.
ARG RESTIC_VERSION=0.19.1
ARG RESTIC_SHA256=f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c
RUN wget -q -O /tmp/restic.bz2 \
      "https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_amd64.bz2" \
 && echo "${RESTIC_SHA256}  /tmp/restic.bz2" | sha256sum -c - \
 && bunzip2 /tmp/restic.bz2 \
 && install -m 0755 /tmp/restic /usr/local/bin/restic \
 && rm -f /tmp/restic \
 && restic version \
 && mkdir -p /backups \
 && chown postgres:postgres /backups
COPY backup/ /usr/local/lib/balik-backup/
USER postgres
ENTRYPOINT ["sh", "/usr/local/lib/balik-backup/agent.sh"]
