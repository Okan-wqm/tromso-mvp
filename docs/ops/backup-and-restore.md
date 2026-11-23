# Backup and restore

`dc` is `docker compose --env-file farm.env` in `deploy/`. The agent is `deploy/backup/agent.sh` (its head lists
every command); it runs in the `backup` service as the read-only role `balik_backup`.

## What is backed up, how often, how long

| What | How | When | Kept on the server | Kept off the server |
|---|---|---|---|---|
| The database, logically | `pg_dump` (custom format), checked by `pg_restore --list`, with every table's row count beside it (`.counts`) and a sha256 | every `BACKUP_DUMP_HOURS` (24) | the last 3 | by the retention below |
| The database, physically | `pg_basebackup` (tar, gzip, the WAL it needs streamed in) | every `BACKUP_BASE_DAYS` (7) | the last one (`BACKUP_LOCAL_BASES`, 1) | by the retention |
| Every change since | the WAL, archived by the database (`archive_command`, at most every `DB_ARCHIVE_TIMEOUT`, 15 minutes) | continuously | from the base backup kept on the server on; what is older is removed after the ship that took it | by the retention (every snapshot holds the WAL from its base backup on) |
| Uploaded files | the `media` volume (the library's PDFs) | with every ship | (the volume itself) | by the retention |
| Shipped | `restic backup` of all of the above to `RESTIC_REPOSITORY`: encrypted (AES-256, the repository's password), deduplicated | every `BACKUP_SHIP_MINUTES` (15) | | |

**Retention off the server** (`restic forget --prune`): 48 hourly, 14 daily, 8 weekly, 12 monthly snapshots
(`BACKUP_KEEP_*`), applied **by the owner, not by the farm's server** (below). **A weekly `restic check`** on the
farm's server reads 5 % of the data back (reading only).

**What can be lost (RPO):** a crash of the database alone loses nothing committed (the WAL on the server's disk). A
server lost with its disks loses at most `DB_ARCHIVE_TIMEOUT` + `BACKUP_SHIP_MINUTES`: **30 minutes** by default
(the WAL not yet archived, plus the archive not yet shipped). Lower both for less (each halving of `DB_ARCHIVE_TIMEOUT`
doubles the quiet database's WAL, below).

## The disk budget

What the server holds besides the database itself (D: the database's size on disk; its dumps and base backups are
compressed to roughly a third to a half of D):

| What | Size |
|---|---|
| The database | D (two years of readings, compressed after 14 days: README, Sensors) |
| WAL in the database (`pg_wal`) | about 1 GB |
| Archived WAL on the server | from the last base backup on: at most `BACKUP_BASE_DAYS` × (86400 / `DB_ARCHIVE_TIMEOUT` × 16 MB + the day's writes). A quiet database: 1.5 GB a day, **10.5 GB** a week; each GB the database writes a day adds 7 GB |
| Dumps | 3 × about D / 3 |
| Base backup | 1 × about D / 2 |
| The restic cache | about 5 % of the repository |
| Images, build cache, logs | about 15 GB (logs are rotated: 50 MB a service) |

For one farm in its first two years (D up to about 40 GB): 40 + 1 + 20 + 40 + 20 + 3 + 15 ≈ 140 GB, so **200 GB** of
SSD, with the heartbeat alerting at 80 % ([monitoring.md](monitoring.md)). Measure D and the WAL a day after the first
month (`docker system df -v`, `du -sh` of the volumes) and write them in the farm's record.

**Not backed up, on purpose:** the broker's users and topics (written again from the database every minute), the
broker's queue (devices resend), the static files (in the image), the secrets (`SECRETS_DIR`: kept by the owner, see
[rotate-secrets.md](rotate-secrets.md); **without `restic_password` no backup can be read**).

## Is it working?

- `dc ps`: `backup` is healthy only when the last dump, base backup and ship succeeded and none is overdue
  (`agent.sh health`).
- `dc exec backup sh /usr/local/lib/balik-backup/agent.sh snapshots`: the newest snapshot is minutes old.
- `dc logs backup`: one line per job; `ERROR:` lines say what failed. A failed job is tried again after 15 minutes.
- The database's own side: `SELECT * FROM pg_stat_archiver` (`failed_count` stays 0, `last_archived_time` is recent).

## The target, and who may delete (one design)

**The farm's server can add backups, never delete them.** Whoever takes the server (or its root) takes its backup key
too; if that key could delete, the attacker could destroy the backups with the data. So:

- **The repository:** a restic REST server (`rest-server`, BSD-2-Clause), run by the owner on a machine elsewhere (the
  backup machine, below), started append-only with private repositories: each farm's user may add to its own
  repositories and remove its own lock files, nothing else. MinIO is banned (AGPL).
- **On the farm's server:** `BACKUP_PRUNE_ON_FARM=0` (the default): the agent backs up, ships and checks; it never runs
  `forget`/`prune` (they would be refused anyway). Its daily `prunecheck` turns the backup's health, and with it the
  heartbeat, red when the owner's prune is overdue: more snapshots older than `BACKUP_PRUNE_AGE_DAYS` (35) than the
  retention keeps (`BACKUP_KEEP_WEEKLY` + `BACKUP_KEEP_MONTHLY` + 5).

### The backup machine (the owner's)

One small server for all farms, at another provider or data centre than any farm, in the EU/EEA, run by the owner.

1. **Its disk:** a volume of its own for `/srv/restic` (encrypted at rest where the provider offers it), sized for every
   farm's repository with a year's growth (a farm's repository: about its dumps and base backups of a month, plus the
   WAL: measure after the first month), an alert at 80 %.
2. **rest-server** (the release binary, its sha256 checked, as the backup image checks restic's), as a systemd service
   of a user of its own:
   ```
   rest-server --path /srv/restic --listen :8000 --append-only --private-repos \
     --htpasswd-file /srv/restic/.htpasswd --tls --tls-cert /etc/rest-server/server.crt \
     --tls-key /etc/rest-server/server.key --max-size <bytes for all farms>
   ```
   `--private-repos`: the user `farm-a` reaches `/farm-a/...` only, so a farm's repository is
   `RESTIC_REPOSITORY=rest:https://<backup host>:8000/farm-a/main/` (the path starts with the farm's user name, which is
   the farm's `COMPOSE_PROJECT_NAME`). `--max-size` stops a runaway farm before it fills the disk.
   Its firewall lets in 8000 from the farms' servers' addresses only (and ssh from the owner's).
3. **TLS:** a public certificate (Let's Encrypt, then remove `RESTIC_CACERT` from the farms' `farm.env`), or one from the
   owner's own CA (`sh scripts/certs.sh proxy-internal <backup host>` on the owner's machine makes both): its CA
   certificate goes into each farm's `SECRETS_DIR/backup-ca.crt`, which compose hands to the backup and restore services
   as `/run/secrets/backup_ca`, and `RESTIC_CACERT=/run/secrets/backup_ca` in `farm.env`.
4. **A farm's user:** on the backup machine, `create_user farm-a` (rest-server's script: it asks for a password and
   writes a bcrypt line into `.htpasswd`; `htpasswd -B /srv/restic/.htpasswd farm-a` does the same), then
   `systemctl reload rest-server` (SIGHUP: the server reads `.htpasswd` again). The farm gets that user and password as
   `RESTIC_REST_USERNAME`/`RESTIC_REST_PASSWORD` in its `backup.env`; then `dc run --rm backup init` on the farm.
5. **Its own backup:** the repositories are encrypted (each farm's restic password, which the backup machine never holds
   but the owner's safe), so they can be copied anywhere: weekly, `rclone sync /srv/restic <a second, cold location>`
   (object storage with versioning), and its own monitoring (disk, the service, the certificate's expiry).
6. **The owner prunes, monthly**, on the backup machine itself, directly on the repository's folder (never through the
   append-only server), with the farm's repository password from the owner's safe:
   ```
   export RESTIC_REPOSITORY=/srv/restic/farm-a/main RESTIC_PASSWORD_FILE=<the farm's restic_password, from the safe>
   restic forget --host farm-a --tag balik --keep-hourly 48 --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune
   restic check --read-data-subset=10%
   restic snapshots --host farm-a --latest 3          # the newest is minutes old
   ```
   and writes the date in the farm's record. Until it runs the repository only grows; after 35 days the farm's
   `prunecheck` turns its backup health red (the heartbeat alerts) until the prune has been done.
- **Not used, not tested:** S3 object lock (immutable versions for a period). If a provider's object lock is chosen
  instead, it must be tested before go-live (a delete with the farm's key must fail).

The go-live stack workflow dates 30 snapshots two months back (a month without the owner's prune): the farm's
`prunecheck` turns red; then it runs the owner's `forget --prune` and `check` from a second machine stand-in (the
restore project), checks the latest snapshot is still there and the `prunecheck` green again. The REST server itself
(append-only refusals, `--private-repos`, its TLS) is not part of the workflow: test it once on the backup machine with
a farm's user (a `restic forget` with that user must be refused) and write the result in the owner's record.

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
