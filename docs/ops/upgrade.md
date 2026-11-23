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
dc stop web jobs ingest                                            # 5. nothing writes while the schema changes
dc up -d                                                           # 6. release runs: check --deploy, migrate,
                                                                   #    rights, static files; then everything starts
dc logs release                                                    #    "release: done"
dc ps                                                              # 7. every service healthy
sh scripts/check-roles.sh                                          # 8. the roles hold on the new tables
dc run --rm --no-deps web python manage.py check --database default   #  quiet
```

Then sign in, open the pages of what the release changed, record one thing and look at it, and check that new sensor
readings arrive (Sensors). Write the release and the date in the farm's record.

## When it fails

- **`release` exits with an error before `migrate`** (the deploy check): a setting is unsafe or missing (its id says
  which). Fix `farm.env` or the secret, `dc up -d` again. Nothing has changed in the database.
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

**Where it stands (23.11.2026):** production runs **2.32.1** (`deploy/db/Dockerfile`, PostgreSQL 17 of its build); the
development database and `scripts/test.sh` still run 2.17.2 (PostgreSQL 17.2, never rebuilt by Timescale). What
changed between them, found by running the whole suite on each release with CI's `pg_image` input:

- from 2.18 on, a conflicting row of a multi-row `INSERT ... ON CONFLICT DO NOTHING` into a compressed chunk no longer
  drops the rest of the statement (the 2.17.2 fault the ingest works around by writing late rows one per statement;
  the workaround stays, it is right on both): `sensors.tests.test_timescale.CompressedChunkInsertTests` pins each;
- later releases list a continuous aggregate's jobs under the aggregate's own name as well: the tests find them by
  either (`AGGREGATE_JOBS`);
- the extension version test accepts exactly the versions the repository pins (test image and production image).

The whole suite passes on both (the go-live hand-back names the runs). **Owned plan for the rest:** the coordinator
moves the shared development database to the production release at the landing of `wip/go-live`, after its backup,
with `ALTER EXTENSION timescaledb UPDATE`, and then moves `docker-compose.yml`, `scripts/test.sh` and CI's `rust` job to
the same image, so that one release is tested everywhere again (by 30.11.2026). After that, a TimescaleDB release
reaches production like any image: Dependabot, the whole suite with `pg_image`, then `deploy/db/Dockerfile`.

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
