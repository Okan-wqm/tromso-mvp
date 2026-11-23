# Backup and restore

`dc` is `docker compose --env-file farm.env` in `deploy/`. The agent is `deploy/backup/agent.sh` (its head lists
every command); it runs in the `backup` service as the read-only role `balik_backup`.

## What is backed up, how often, how long

| What | How | When | Kept on the server | Kept off the server |
|---|---|---|---|---|
| The database, logically | `pg_dump` (custom format), checked by `pg_restore --list`, with every table's row count beside it (`.counts`) and a sha256 | every `BACKUP_DUMP_HOURS` (24) | the last 3 | by the retention below |
| The database, physically | `pg_basebackup` (tar, gzip, the WAL it needs streamed in) | every `BACKUP_BASE_DAYS` (7) | the last 2 | by the retention |
| Every change since | the WAL, archived by the database (`archive_command`, at most every 5 minutes: `archive_timeout`) | continuously | from the oldest base backup kept on the server | by the retention |
| Uploaded files | the `media` volume (the library's PDFs) | with every ship | (the volume itself) | by the retention |
| Shipped | `restic backup` of all of the above to `RESTIC_REPOSITORY`: encrypted (AES-256, the repository's password), deduplicated | every `BACKUP_SHIP_MINUTES` (15) | | |

**Retention off the server** (`restic forget --prune`, daily): 48 hourly, 14 daily, 8 weekly, 12 monthly snapshots
(`BACKUP_KEEP_*`). **A weekly `restic check`** reads 5 % of the data back.

**What can be lost:** at most the last 5 minutes on the server (the WAL not yet archived), at most ~20 minutes off the
server (the last ship). A server lost with its disks loses no more than that.

**Not backed up, on purpose:** the broker's users and topics (written again from the database every minute), the
broker's queue (devices resend), the static files (in the image), the secrets (`SECRETS_DIR`: kept by the owner, see
[rotate-secrets.md](rotate-secrets.md); **without `restic_password` no backup can be read**).

## Is it working?

- `dc ps`: `backup` is healthy only when the last dump, base backup and ship succeeded and none is overdue
  (`agent.sh health`).
- `dc exec backup sh /usr/local/lib/balik-backup/agent.sh snapshots`: the newest snapshot is minutes old.
- `dc logs backup`: one line per job; `ERROR:` lines say what failed. A failed job is tried again after 15 minutes.
- The database's own side: `SELECT * FROM pg_stat_archiver` (`failed_count` stays 0, `last_archived_time` is recent).

## The target (owner decision, placeholders in farm.env.example)

`RESTIC_REPOSITORY` is any restic backend: S3-compatible object storage (`s3:https://...`), SFTP to a second server
(`sftp:user@host:/path`), a restic REST server (`rest:https://...`). Its access keys go in `SECRETS_DIR/backup.env`.
Requirements: in another location (another provider or data centre) than the server, in the EU/EEA for personal
data, and, where the storage offers it, object lock or an append-only key so that a stolen server cannot delete its
own backups. MinIO is banned (AGPL); use the provider's own storage.

## Restore a dump (the usual restore)

Onto a new or rebuilt server, or into a throwaway server to test (do this at installation and then on schedule).

1. Install the server as in [install.md](install.md) steps 1 to 5, with the **same** `restic_password` and
   `backup.env` (from the owner's safe) and the same `COMPOSE_PROJECT_NAME`, or set `RESTORE_FROM_HOST_TAG` to the
   original's name.
2. Start only the database (an empty farm database is made by its first start, with the roles):
   ```
   dc up -d db
   ```
3. Fetch the snapshot (`latest`, or an id from `agent.sh snapshots`) and pick the dump:
   ```
   dc --profile ops run --rm restore snapshots
   dc --profile ops run --rm restore fetch latest /backups/restore
   dc --profile ops run --rm --entrypoint sh restore -c 'ls -l /backups/restore/backups/dumps/'
   ```
4. Restore it (as the superuser: `timescaledb_pre_restore()`, `pg_restore --exit-on-error`, `timescaledb_post_restore()`,
   `ANALYZE`; refused unless the database is empty), then compare every table's row count with the backup's:
   ```
   dc --profile ops run --rm restore restore-dump /backups/restore/backups/dumps/balik-<time>.dump
   dc --profile ops run --rm restore verify-counts /backups/restore/backups/dumps/balik-<time>.dump.counts
   ```
5. The uploaded files, owned by the web server's user (uid 10002):
   ```
   dc --profile ops run --rm -u root --entrypoint sh restore -c \
     'cp -a /backups/restore/media-ro/. /srv/media/ && chown -R 10002:10002 /srv/media'
   ```
6. Start everything: `dc up -d`. The release step finds every migration applied (or applies the newer release's).
   Then `sh scripts/check-roles.sh`, sign in, look at the newest records.

On a busy database the counts were taken a moment before the dump: a few rows of the busiest tables may differ, and
the differences are printed. A restore test on a quiet copy must show none.

## Restore to a moment (point in time)

When the dump is too old (a fault an hour ago, a deletion this morning): the newest base backup before the moment,
plus the archived WAL up to it.

1. Steps 1 to 3 above, with a snapshot taken **after** the moment (its WAL reaches past it).
2. A data folder replaying to the moment (UTC), in a volume of its own (it also sets `max_connections` to the farm's
   `DB_MAX_CONNECTIONS`: recovery refuses a server with fewer connections than the one the WAL came from):
   ```
   docker volume create farm-pitr
   dc --profile ops run --rm -u root -v farm-pitr:/pitr --entrypoint sh restore -c '
     sh /usr/local/lib/balik-backup/agent.sh prepare-pitr /backups/restore/backups/base/balik-<time> \
       /backups/restore/wal-archive /pitr/data "2026-11-23 09:55:00+00" && chown -R postgres:postgres /pitr/data'
   ```
3. Start a database server on it, with the restored WAL at the same path:
   ```
   docker run -d --name farm-pitr -e PGDATA=/var/lib/postgresql/data/data \
     -v farm-pitr:/var/lib/postgresql/data -v <project>_backups:/backups:ro balik-db:local
   docker logs -f farm-pitr      # "recovery stopping before ..." then "database system is ready to accept connections"
   ```
4. Check the data at that moment (`docker exec farm-pitr psql -U postgres -d balik ...`), then either take a dump of it
   (`pg_dump -Fc`) and restore that dump as above into the farm's empty database, or, for a whole server, stop the
   stack and make this data folder the `pgdata` volume's content.
5. Remove the helpers: `docker rm -f farm-pitr`, `docker volume rm farm-pitr`.

## Proved

`.github/workflows/go-live-stack.yml` does all of this on every run, with synthetic data: a backup shipped to a
repository folder, restored into a second installation with every table's row count equal and every migration
applied, and a point-in-time restore that finds a row written after the base backup (`deploy/ci/stack.sh`, steps
`backup`, `restore`, `pitr`).
