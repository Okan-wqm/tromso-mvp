# Upgrade to a new release, with its migrations

`dc` is `docker compose --env-file farm.env` in `deploy/`. One farm at a time ([per-farm.md](per-farm.md)).

## Before

- The release passed CI and the go-live stack (`go-live-stack.yml`) on its commit.
- Read the release's notes for migrations that need the old code stopped first (e.g. `core/0011`, which converts the
  activity log: a server still running the old code would write plain values behind it, README, Security in the
  pages) or a step of their own. When in doubt, stop first (below): it costs a few minutes of downtime.
- Tell the farm: the console is away for 5 to 15 minutes. Sensor readings are not lost meanwhile: the broker keeps
  the ingest's session and its queue (README, Sensors), and the devices keep publishing.
- Pick a quiet hour (not feeding time, not a harvest).

## Steps

```
cd /opt/balik/deploy
dc exec backup sh /usr/local/lib/balik-backup/agent.sh now        # 1. a dump, a base backup and a ship, now
dc exec backup sh /usr/local/lib/balik-backup/agent.sh snapshots  #    the new snapshot is there
git fetch --tags && git checkout <new release tag>                 # 2. the new code
diff farm.env.example <(git show <old tag>:deploy/farm.env.example)   # 3. new settings? add them to farm.env
WEB_IMAGE=balik-web:<new tag> dc build                             # 4. the new images (tag them by release:
                                                                   #    set WEB_IMAGE etc. in farm.env)
dc run --rm manage python manage.py check_pending_constraints   # 4b. the new CHECK constraints against the
                                                                   #    rows there are: a broken row is named now
dc stop web jobs ingest                                            # 5. nothing writes while the schema changes
dc up -d                                                           # 6. release runs: check --deploy, migrate,
                                                                   #    rights, static files; then everything starts
dc logs release                                                    #    "release: done"
dc ps                                                              # 7. every service healthy
sh scripts/check-roles.sh                                          # 8. the roles hold on the new tables
dc run --rm manage python manage.py check --database default   #  quiet
```

Then sign in, open the pages of what the release changed, record one thing and look at it, and check that new sensor
readings arrive (Sensors). Write the release and the date in the farm's record.

## When it fails

- **`release` exits with an error before `migrate`**: the deploy check (a setting is unsafe or missing, its id says
  which: fix `farm.env` or the secret), or `check_pending_constraints` (rows that a new CHECK constraint would refuse,
  named by migration and constraint: correct them with the old release running, or as the release notes say). Then
  `dc up -d` again. Nothing has changed in the database.
- **`migrate` fails half-way**: PostgreSQL runs each migration in a transaction, so the failed one left nothing; the
  ones before it are applied. Do not start the old code on the new schema. Either fix forward (a corrected release),
  or go back:
  1. `dc down` (volumes stay);
  2. `git checkout <old tag>`, build the old images (or set the old `WEB_IMAGE` tags);
  3. restore the dump taken in step 1 into an empty database ([backup-and-restore.md](backup-and-restore.md),
     "Restore a dump");
  4. `dc up -d`.
  Migrations are not run backwards on a farm's database: going back is always a restore.
- **A service stays unhealthy**: `dc logs <service>`; the web server's start runs the deploy check too and names
  what it refuses.

## Afterwards

- Old images: `docker image ls balik-web` and remove the release before last (`docker image rm balik-web:<tag>`);
  never `docker system prune` or `docker volume prune` on a farm's server: they remove what nobody named, and a
  stopped service's volume can be the database's.
- The old static files stay in the `static` volume (pages still open in a browser load their own); they are small.

## Patch cadence

What is patched, by whom, how often. Every patch that reaches a farm goes through CI and the go-live stack workflow
first, like a release.

| What | Where it is pinned | Watched by | Applied |
|---|---|---|---|
| The server's OS (kernel, OpenSSL, Docker Engine) | the host | unattended-upgrades (security), the provider's notices | security updates daily by themselves; a reboot in the monthly window (the reboot test below) |
| PostgreSQL and TimescaleDB | `deploy/db/Dockerfile` (`timescale/timescaledb:<version>-pg17@sha256:...`) | Dependabot (docker, `/deploy/db`), the PostgreSQL quarterly minor releases, TimescaleDB's releases | a minor/patch within the month; a TimescaleDB release needs `ALTER EXTENSION timescaledb UPDATE` (below) |
| nginx, Mosquitto, cloudflared | `deploy/compose.yml` | Dependabot (docker-compose, `/deploy`) | within the month; a security fix within the week |
| Python packages (Django, gunicorn, psycopg, ...) | `requirements.txt`, `docker/requirements.lock` | Dependabot (pip), the `security` CI job (pip-audit) | as for the images; a Django security release within the week |
| Rust crates (ingest, chemistry core) | `Cargo.lock` | Dependabot (cargo), cargo deny advisories in CI | with the next release |
| restic | `deploy/db/Dockerfile` (version and sha256) | restic's releases (not covered by Dependabot) | checked monthly by a person |

**Monthly window** (one per farm, the farm's quiet day): apply what CI has passed, reboot the host if the OS asks for
it, then the checks of "Steps" 7 and 8 above and `sh scripts/heartbeat.sh`.

**A new TimescaleDB:** the image carries the new extension files; each database moves with
`dc exec db psql -U postgres -d balik -X -c 'ALTER EXTENSION timescaledb UPDATE'` as the first statement of a new
session, after a backup, with web, jobs and ingest stopped.

**One release everywhere (24.11.2026):** TimescaleDB **2.32.1**, the same image by the same digest
(`timescale/timescaledb:2.32.1-pg17@sha256:2f5e6969...`), in production (`deploy/db/Dockerfile`), development
(`docker-compose.yml`), the tests (`scripts/test.sh`) and every CI job that starts a database; this branch
(`wip/go-live`) made the move, and `sensors.tests.test_timescale` fails when any of them pins another image. What
changed from 2.17.2, found by running the whole suite on each release with CI's `pg_image` input (kept for the next
bisect): a conflicting row of a multi-row `INSERT ... ON CONFLICT DO NOTHING` into a compressed chunk no longer drops
the rest of the statement (the ingest keeps writing one row per statement); a continuous aggregate's jobs are listed
under the aggregate's own name. The tests pin 2.32.1's behaviour only.

**Moving the shared development database at the landing of `wip/go-live`** (the coordinator, nobody else). The same
PostgreSQL major, so the data volume moves as it is: only the container (the new image) and the extension change.
`deploy/scripts/timescaledb-move.sh` holds the exact steps; the go-live stack workflow runs the same script on a
synthetic database (a hypertable with compressed chunks, a continuous aggregate, policies and a job, made on 2.17.2;
step `tsmove`), so the sequence is tested, not only written. From the main checkout (`F:\dev\balik-ciftligi`, Git Bash),
after `main` holds this branch:

```
docker stop balik-dev-web                                     # nothing writes
docker compose --profile sensors stop sensors-ingest node-red
DB_EXEC="docker compose exec -T db" RECREATE="docker compose up -d db" \
  sh deploy/scripts/timescaledb-move.sh move "/j/İCLOUD/iCloudDrive/suderra/Programlar/db-backups" balik-timescaledb-2.32.1
```

What it does, in order, stopping at the first failure:

1. the facts before: the version, every hypertable's rows, chunks and compressed chunks, the jobs;
2. `pg_dump` of `balik` on 2.17.2 (`...-before-<time>.dump`);
3. `docker compose up -d db`: the same volume on the new image;
4. in every database that holds the extension (`postgres`, `template1` and `balik`: the image makes it in
   `template1`, so every database has it), the plain statement as the **first command of a new session**:
   `psql -X -U balik -d <database> -c "ALTER EXTENSION timescaledb UPDATE"`. Not inside a `DO` block and not after
   any other statement: once the old library is loaded in the session, PostgreSQL refuses the update;
5. a second `pg_dump`, now on 2.32.1 (`...-after-<time>.dump`): from here on a way back restores on the same release;
6. the checks:
   - the version is 2.32.1 in each of those databases;
   - every hypertable has the rows and chunks it had and at least as many compressed chunks (a compression job may run
     meanwhile), and every compressed chunk is read;
   - every job is still there, and every continuous aggregate's refresh job is listed under the aggregate's own name;
   - **each scheduled job fails once at the update** (`cannot drop portal "" while it is being set up`, SQLSTATE
     24000, in `timescaledb_information.job_errors`): that is expected. The script then makes every job due now and
     waits until each has run again with `Success` (`timescaledb_information.job_stats`): that is the recovery.

Then the landing's own steps (`migrate`, `compile_catalogs`, `npm run build`, the dev server started again,
`manage.py check --database default` quiet), `docker compose --profile sensors up -d`, and **the ingest writing**:
after two minutes `SELECT max(ts) FROM sensors_reading` is within the last minutes and the ingest's health is ok
(`docker inspect --format '{{json .State.Health}}' balik-ciftligi-sensors-ingest-1`); then the crawl of the pages
(`F:\dev\balik-notes\tools\crawl.py`) in EN, NB and TR.

**The way back**, if the update or a check fails. A dump restores only into its own release (restored into 2.32.1, the
2.17.2 dump fails on the catalog and leaves the data partial), so: the 2.17.2 dump onto a **new** volume running the
**old** image, then the new image on that volume and the update, then the same checks:

```
docker compose stop db
DB_EXEC=unused sh deploy/scripts/timescaledb-move.sh back <the ...-before-<time>.dump> <the ...-before-<time>.facts> \
  timescale/timescaledb:2.17.2-pg17@sha256:3324f81ca7f84cdc2dc4497863b3798ababa8ce130c5b59d73f0b40e3a34148e \
  timescale/timescaledb:2.32.1-pg17@sha256:2f5e6969faa5cd7f4b075d65f124e30dc50d456b7b807e5c1acd9d51ba7df51c \
  balik-ciftligi_pgdata-restored
```

then point the compose project at the restored volume (`docker-compose.override.yml`, not committed:
`volumes: {pgdata: {external: true, name: balik-ciftligi_pgdata-restored}}`), `docker compose up -d db`, and keep the
old volume until the dev server and the crawl are right on the restored one. The stack workflow runs this way back too.

After that, a TimescaleDB release moves like any image: Dependabot, the whole suite with `pg_image`, then every pin
together in one change.

**The reboot test** (at installation, then after every kernel update): `reboot`, then without touching anything:
WireGuard up (`wg show`), every service healthy (`dc ps`), the broker listening on the VPN address
(`ss -ltn | grep 8883`), the heartbeat green. The broker publishes its port on the WireGuard address, which exists
only once WireGuard is up: Docker must start after it. On the host:

```
# /etc/systemd/system/docker.service.d/after-wireguard.conf
[Unit]
Wants=wg-quick@wg0.service
After=wg-quick@wg0.service
```

then `systemctl daemon-reload`.
