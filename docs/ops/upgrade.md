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
- **`migrate` fails half-way**: a migration runs in a transaction unless it says `atomic = False`, and then the
  failed one left nothing; the ones before it are applied. A migration that is not atomic runs each of its steps on
  its own, and a step that failed may have left what it made: `sensors/migrations/0003_rollups.py` is one (its
  continuous aggregate and its policies, each its own step). An index built CONCURRENTLY that failed is left invalid,
  and the next run of the same migration stops at "already exists": `dc run --rm manage python manage.py check
  --database default` names each invalid index (core.W006) with the `DROP INDEX CONCURRENTLY IF EXISTS ...` that
  removes it. Do not start the old code on the new schema. Either fix forward (a corrected release), or go back:
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

**A new TimescaleDB:** the image carries the new extension files, and each database's extension moves to them with
`deploy/scripts/timescaledb-move.sh` (below), after the backup of Steps 1 and with web, jobs and ingest stopped. Never
with a bare `ALTER EXTENSION timescaledb UPDATE`: an update step renames the constraints of every hypertable chunk and
cannot rename a constraint trigger, which every revision trigger's `_apply` is (`water_measurements`, README,
Revisions); the update stops with `constraint "..." does not exist` and leaves the database half-moved (seen from
2.17.2 to 2.32.1). The script takes those triggers off with the project's own
`manage.py core_rev_drop_hypertable_triggers` (found from `core/rev.py`'s registry), updates every database, makes
them again with `manage.py core_rev_repair` and needs `manage.py check --database default` quiet; a stop half-way is
recorded and is finished with `resume`. On a farm's server, from `deploy/`, after `dc build` with the new
`deploy/db/Dockerfile` (`dc` as above; the superuser `postgres`; `manage.py` as the owner role, in the `release`
service):

```
DB_EXEC="$dc exec -T db" DB_USER=postgres RECREATE="$dc up -d db" MANAGE="$dc run --rm -T --no-deps release python manage.py" \
  sh scripts/timescaledb-move.sh move /var/backups/balik-timescaledb <the new TimescaleDB release>
```

(with `dc="docker compose --env-file farm.env"`). Its way back on a farm is the restore of Steps 1's backup on the old
images ([backup-and-restore.md](backup-and-restore.md)). The go-live stack workflow tests the script on the development
database's setup (below), not yet on a farm's stack: the first farm to move does it on a restored copy first.

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
`deploy/scripts/timescaledb-move.sh` holds the exact steps. The go-live stack workflow runs the same script, with the
same settings, on the development database's setup (steps `tsmove`, `tsback`, `tshalf`, `tsearly`): the 2.17.2 image as
`docker-compose.yml` starts it (role, database and password `balik`), every migration of the project run on it by the
project's own image, readings for 60 days with compressed chunks, every continuous aggregate refreshed, and water
samples by the write path (a hypertable whose chunks carry the revision triggers). So the sequence is tested on the real
schema, not only written.

**The day before (read only, the dev server still up).** From the main checkout (`F:\dev\balik-ciftligi`, Git Bash):

```
export MSYS_NO_PATHCONV=1
IMG=$(sh scripts/testrunner/image.sh build)                   # this checkout's image, built now, never :latest
MANAGE="docker run --rm -i --network balik-ciftligi_default -e DB_HOST=db -e DB_PORT=5432 -v F:/dev/balik-ciftligi:/app -w /app $IMG python manage.py"
$MANAGE check --database default --fail-level WARNING        # quiet, as the move will ask
docker compose exec -T db psql -X -U balik -d postgres -At -c "SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database WHERE datallowconn"
docker compose exec -T db psql -X -U balik -d balik -At -c "SELECT job_id, last_run_status, last_successful_finish FROM timescaledb_information.job_stats"
docker compose exec -T db psql -X -U balik -d postgres -At -c "SHOW timescaledb.max_background_workers"
docker pull timescale/timescaledb:2.32.1-pg17@sha256:2f5e6969faa5cd7f4b075d65f124e30dc50d456b7b807e5c1acd9d51ba7df51c
docker system df; df -h /c /f                                 # room (below)
```

- The jobs must be running. Every database with the extension takes one background worker for its scheduler, plus one
  launcher: with `timescaledb.max_background_workers` 16 and 15 leftover `test_*` databases no worker is left for a job,
  the jobs never run (the db log says `out of background workers`), and the move's step 8 can never pass. Drop the
  leftover databases (or raise the limit) and let the job backlog (compression, aggregates) finish on 2.17.2 first.
- The new image is pulled by its digest the day before, so the move never pulls it with the revision triggers off.
- Nothing else may touch the server on the day: no agent's test run (`sensors-ingest/tests/run.sh` drops and
  recreates `sensors_ingest_test` on this server), no other container on `balik-ciftligi_default`
  (`docker network inspect balik-ciftligi_default`), and `pg_stat_activity` shows no client but the move's.

- The check must be quiet. core.W003 (a role that holds Read only from the old matrix rule), core.W004 (plain private
  values in the activity log) and farm.W001 (water samples whose pH was put on NBS by an older formula) depend on the
  data: each needs its own decision (a role review, `private_log_values`, `rederive_ph`), possibly the owner's, before
  the day. core.W002 and core.W001 (catalogs and scripts older than their sources) are expected until the landing's
  build below.
- The databases: `postgres`, `template1` and `balik`. Any other (a `test_balik...` left by a killed test run) holds the
  revision triggers too: the move refuses while it is there, naming it. Drop it the day before.

**Room, and where everything goes.** Per move, in the backup folder (the script's first argument; for the development
database `F:/dev/balik-backups/timescaledb`, outside iCloud, so a sync never takes half a dump): two dumps, each about
the size of the landing backup (`pg_dump -Fc`; the dev `balik` database itself is about 5.7 GB on 25.11.2026,
almost all `sensors_reading`), the facts and check records (a few KB) and
the roles (a few KB, with password hashes: mode 600, never committed or synced). The way back needs more: a second whole
copy of the database in a new Docker volume (about `pg_database_size('balik')` above) and the old image (about 1 GB)
on Docker's disk, which on this PC is the WSL disk image on drive C. `back` measures Docker's disk, and with
`DOCKER_HOST_DRIVE=/c` drive C too, and refuses, making nothing, when there is less free than `BACK_ROOM_FACTOR` (10)
times the dump. That factor can pass without room for the database's whole size: check `pg_database_size` against the
free room yourself. `back` restores onto 2.32.1, it is not a return to 2.17.2: an exact way back is a cold copy of the
data volume taken before the merge (`docker compose stop db`, copy the volume, `docker compose start db`, never `up`).

**The day: order.** No `docker compose up` (of anything) between the merge into `main` and the move: it would recreate
`db` on the new image (the merge changes its image line) with the old extension. The move still handles that (the image
carries the old release's library, so its dump is still one of the old release; `tsearly` shows it, the way back
included), but nothing gains from it. In this order, in Git Bash, from the main checkout:

```
git merge-base --is-ancestor main wip/go-live                 # main must fast-forward: merge main into the branch first
docker stop balik-dev-web                                     # nothing writes from here to the end of the move:
docker compose --profile alarms stop alarms                   #   between its steps 3 and 6 the revision triggers are off
docker compose --profile sensors stop sensors-ingest node-red # (mosquitto and db stay up; step 4 recreates db)
git merge --ff-only wip/go-live                               # main holds this branch (CLAUDE.md, How work lands)
export MSYS_NO_PATHCONV=1
IMG=$(sh scripts/testrunner/image.sh build)                   # built the day before: requirements.txt changed (gunicorn)
MANAGE="docker run --rm -i --network balik-ciftligi_default -e DB_HOST=db -e DB_PORT=5432 -v F:/dev/balik-ciftligi:/app -w /app $IMG python manage.py"
$MANAGE migrate && $MANAGE compile_catalogs && npm run build  # before the move: its check is refused by core.W002
                                                              # (catalogs older than the merged .po files) otherwise
export DB_EXEC="docker compose exec -T db" RECREATE="docker compose up -d db" MANAGE DOCKER_HOST_DRIVE=/c JOB_WAIT_SECONDS=1800
sh deploy/scripts/timescaledb-move.sh move F:/dev/balik-backups/timescaledb balik-timescaledb-2.32.1
```

It lists every database that holds the extension, then refuses, doing and writing nothing, when `balik` is already on
2.32.1, when another database has revision triggers on hypertable chunks (named, as above), when the folder holds an
unfinished move of that label, when a migration is not applied, or when the check is not quiet. Then, stopping at the
first failure:

1. the facts before: the version, every hypertable's rows, chunks and compressed chunks, the jobs
   (`...-before-<time>.facts`, `<time>` to the second);
2. `pg_dump` of `balik` on 2.17.2 (`...-before-<time>.dump`), and the cluster's roles with their password hashes
   (`pg_dumpall --roles-only`, `...-before-<time>.roles.sql`). Each is written as `.partial` and renamed only when all
   three are whole: a dump that failed is left as `.partial` (remove it), never under a name that looks whole. No file
   is ever overwritten. From here until the end `<label>.unfinished` in the folder records the move and its step;
3. `manage.py core_rev_drop_hypertable_triggers`: the revision triggers off `water_measurements` (every tracked
   hypertable, from `core/rev.py`): the update below renames every chunk's constraints and cannot rename a constraint
   trigger;
4. `docker compose up -d db`: the same volume on the new image (passed over when it already runs it);
5. in every database that holds the extension (`postgres`, `template1` and `balik`: the image makes it in
   `template1`, so every database has it), the plain statement as the **first command of a new session**:
   `psql -X -U balik -d <database> -c "ALTER EXTENSION timescaledb UPDATE"`. Not inside a `DO` block and not after
   any other statement: once the old library is loaded in the session, PostgreSQL refuses the update;
6. `manage.py core_rev_repair` (the triggers made again as their migrations made them, every revision rebuilt: every
   stored figure is built again on its next read), then `manage.py check --database default` must be quiet;
7. a second `pg_dump`, now on 2.32.1 (`...-after-<time>.dump`): from here on a way back restores on the same release;
8. the checks:
   - the version is 2.32.1 in each of those databases;
   - every hypertable has the rows and chunks it had and at least as many compressed chunks (a compression job may run
     meanwhile), and every compressed chunk is read;
   - every job is still there, and every continuous aggregate's refresh job is listed under the aggregate's own name;
   - **each scheduled job fails once at the update** (`cannot drop portal "" while it is being set up`, SQLSTATE
     24000, in `timescaledb_information.job_errors`): that is expected. The script then makes every job due now and
     waits until each has run again with `Success` (`timescaledb_information.job_stats`), up to `JOB_WAIT_SECONDS`
     (300): that is the recovery. The retention job is one of them: it drops what the retention policy drops anyway
     (readings older than 730 days).

Then `docker compose up -d db` is no longer harmful; start the dev server (CLAUDE.md), `docker compose --profile
sensors up -d`, `manage.py check --database default` quiet, and **the ingest writing**: after two minutes
`SELECT max(ts) FROM sensors_reading` is within the last minutes and the ingest's health is ok
(`docker inspect --format '{{json .State.Health}}' balik-ciftligi-sensors-ingest-1`); then the crawl of the pages
(`F:\dev\balik-notes\tools\crawl.py`) in EN, NB and TR. Time: the stack's copy (a few thousand readings, two samples)
moves in a minute or two; on the development database the dumps (about 7 minutes each), the rebuild of the revisions
in step 6 (one `UPDATE` of every `core_rev` row) and up to 5 minutes of step 8 come on top.

**A move that stops** after step 2 prints the step and the command that goes on, and every later `move` refuses and
prints it again until the move is finished:

```
sh deploy/scripts/timescaledb-move.sh resume F:/dev/balik-backups/timescaledb balik-timescaledb-2.32.1
```

with the same settings. `resume` runs steps 3 to 8 again from the start, each of them safe to repeat, and checks
against that move's own facts from before. Mend the cause first (the output above the stop names it); do not start
the dev server while a move is unfinished (the revision triggers may be off). **A stop in step 8** (the database is
moved; a job had not run again with `Success` in time, or failed for its own reasons) is closed instead, once the
cause is clear: `sh deploy/scripts/timescaledb-move.sh close F:/dev/balik-backups/timescaledb
balik-timescaledb-2.32.1` runs the checks again (`JOB_WAIT_SECONDS` for more time) and removes the record only when
they pass, logging it beside the facts (`...-before-<time>.closed-<time>.log`). The other way out is the way back
(below), from that move's `...-before-<time>.dump`.

**The way back** (the development stack only: a farm restores its backup on the old images, "When it fails" above), if
the update or a check fails and `resume` cannot mend it. A dump restores only into its own release (restored into
2.32.1, the 2.17.2 dump fails on the catalog and leaves the data partial), so: the 2.17.2 dump onto a **new** volume
running the **old** image, the roles first (from the `.roles.sql` beside the dump: the dump's grants name
`sensors_ingest`, and `balik` keeps its password, so the development stack signs in as before), the restore, then the
new image on that volume, steps 3, 5 and 6, and the same checks. It first checks the room (above). Its container
`timescaledb-back` joins the compose network as `db`, where `MANAGE` finds it, so the compose database is stopped first:

```
docker compose stop db
BACK_NETWORK=balik-ciftligi_default BACK_ALIAS=db DOCKER_HOST_DRIVE=/c DB_EXEC=unused \
  sh deploy/scripts/timescaledb-move.sh back <the ...-before-<time>.dump> <the ...-before-<time>.facts> \
  timescale/timescaledb:2.17.2-pg17@sha256:3324f81ca7f84cdc2dc4497863b3798ababa8ce130c5b59d73f0b40e3a34148e \
  timescale/timescaledb:2.32.1-pg17@sha256:2f5e6969faa5cd7f4b075d65f124e30dc50d456b7b807e5c1acd9d51ba7df51c \
  balik-ciftligi_pgdata-restored
```

(`MANAGE` and `MSYS_NO_PATHCONV` as for the move). The log of the roles and the restore goes beside the dump. A way back
that fails removes its container and leaves the new volume, which it names: `docker volume rm
balik-ciftligi_pgdata-restored` before another try (the old volume is never touched). When it succeeds, point the
compose project at the restored volume (`docker-compose.override.yml`, not committed:
`volumes: {pgdata: {external: true, name: balik-ciftligi_pgdata-restored}}`), `docker compose up -d db`, and keep the
old volume until the dev server and the crawl are right on the restored one; then remove the volume that is not used,
since drive C is short of room. The stack workflow runs this way back too, a refused and a failing one included, and
then signs in to the restored cluster as `balik` with the development stack's password.

After that, a TimescaleDB release moves like any image: Dependabot, the whole suite with `pg_image`, then every pin
together in one change.

**The reboot test** (at installation, then after every kernel update): `reboot`, then without touching anything:
WireGuard up (`wg show`), every service healthy (`dc ps`), the broker listening on the VPN address
(`ss -ltn | grep 8883`), the heartbeat green, both DOCKER-USER rules back (`sh scripts/docker-user-rules.sh --check
farm.env`: two "ok" lines; a reboot empties the chain and the `balik-docker-user` unit puts them in again, install.md).
The broker publishes its port on the WireGuard address, which exists
only once WireGuard is up: Docker must start after it. On the host:

```
# /etc/systemd/system/docker.service.d/after-wireguard.conf
[Unit]
Wants=wg-quick@wg0.service
After=wg-quick@wg0.service
```

then `systemctl daemon-reload`.
