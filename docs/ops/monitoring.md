# Monitoring: nothing fails silently

A container's health check only changes a word in `docker compose ps`: nobody reads it at night. Each farm's server
therefore reports to a monitor **outside** the server, which alerts a person. `dc` is
`docker compose --env-file farm.env` in `deploy/`.

## What is watched, and by what

| What | Seen by | Turns red when |
|---|---|---|
| Every service of the stack | its health check (`deploy/compose.yml`) | a service stops, restarts in a loop, or answers wrong (web: the sign-in page; jobs: a job's last run failed, or the loop hung; backup: below; ingest: no database write for 60 s or a broker connection down) |
| Backups | `agent.sh health` (the backup service's health check) | a dump, base backup or ship failed last or is overdue; the weekly check or the retention failed; **the database's WAL archiver is failing** (`pg_stat_archiver`) |
| The disk | `scripts/heartbeat.sh` | the disk Docker keeps the volumes on is over `HEARTBEAT_DISK_PERCENT` (80 %): the database and the WAL archive stop when it is full |
| Certificates | `scripts/heartbeat.sh` | the console's or the broker's certificate ends within `HEARTBEAT_CERT_DAYS` (21) days |
| Sensors | `scripts/heartbeat.sh` | no reading stored for `HEARTBEAT_SILENCE_MINUTES` (30; `0` before the farm has sensors) |
| The server itself, its network, Docker | the outside monitor | the heartbeat stops arriving |
| The console from outside | the outside monitor (an HTTP check) | `https://<SITE_HOST>/accounts/login/` does not answer 200 (only where the monitor can reach it: on the VPN, or through Cloudflare with a service token) |

## The heartbeat

`deploy/scripts/heartbeat.sh` runs every 5 minutes on the host, checks all of the above and:

- all well: requests `HEARTBEAT_URL`; the monitor alerts when these requests **stop** (a dead-man switch: a dead
  server, a dead network, a stopped Docker or a broken script all end them);
- something wrong: requests `HEARTBEAT_FAIL_URL` at once, with the failing lines as the body.

The requests go from the server straight to the monitor: not through the proxy, not through Cloudflare, so an outage
of either is reported too. Any monitor with heartbeat ("cron job") checks works (a hosted one such as healthchecks.io,
or a self-hosted one on another machine, e.g. Uptime Kuma); pick one outside the farm's own network and hosting.
Its alerts go to two people by two channels (e-mail and SMS or a phone app).

```
# farm.env
HEARTBEAT_URL=https://<monitor>/ping/<check id>
HEARTBEAT_FAIL_URL=https://<monitor>/ping/<check id>/fail
HEARTBEAT_DISK_PERCENT=80
HEARTBEAT_CERT_DAYS=21
HEARTBEAT_SILENCE_MINUTES=30
```

The monitor's check: period 5 minutes, grace 10 minutes.

systemd units on the host (as root):

```
# /etc/systemd/system/balik-heartbeat.service
[Unit]
Description=Farm server heartbeat
After=docker.service
[Service]
Type=oneshot
WorkingDirectory=/opt/balik/deploy
ExecStart=/bin/sh scripts/heartbeat.sh

# /etc/systemd/system/balik-heartbeat.timer
[Unit]
Description=Farm server heartbeat every 5 minutes
[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
```

`systemctl enable --now balik-heartbeat.timer`; `journalctl -u balik-heartbeat` shows each run's lines.

## Proved

The go-live stack workflow runs the heartbeat on the running stack (all green), then makes the WAL archive
unwritable: the backup turns unhealthy ("the WAL archiver is failing") and the heartbeat fails; with the archive
writable again the archiver catches up and both are green again (`deploy/ci/stack.sh heartbeat`).

## What it does not cover

- **The fish.** The alarm worker (not yet landed) raises water alarms; until it runs, the console is a monitoring and
  record system only, and the site's own alarms are the alarms ([GO-LIVE-CHECKLIST.md](GO-LIVE-CHECKLIST.md)).
- A wrong value that looks right: the integrity commands (`check_stock`, `check_inventory`, ...) are run by a person.
