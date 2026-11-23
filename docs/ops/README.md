# Operations: running a farm's server

The go-live package: everything needed to put the fish-farm console on a farm's own server, and to keep it there.
Each farm has **its own server, its own installation and its own database**; nothing is shared between farms.

| Runbook | When |
|---|---|
| [install.md](install.md) | A fresh server, from nothing to the sign-in page |
| [per-farm.md](per-farm.md) | What is different for every farm, and the record kept per farm |
| [first-admin.md](first-admin.md) | The first platform admin, the company's roles, the first invitations |
| [upgrade.md](upgrade.md) | A new release, with its migrations |
| [backup-and-restore.md](backup-and-restore.md) | What is backed up, where, how long; restore a dump, restore to a moment |
| [rotate-secrets.md](rotate-secrets.md) | Every secret: where it lives, how it is changed |
| [incident.md](incident.md) | Something is wrong: the checklist |
| [access.md](access.md) | How people reach the console (Cloudflare Zero Trust or VPN) and how sensors reach the broker |
| [database-roles.md](database-roles.md) | The four database roles and what each may do |
| [GO-LIVE-CHECKLIST.md](GO-LIVE-CHECKLIST.md) | Ticked by a person before a real deployment |

## The pieces

```
              browsers                                   site sensors
                 |  https (Cloudflare Tunnel, VPN or public)    |  MQTT over TLS, inside WireGuard
            +----v-----+                                  +-----v-----+
            |  proxy   | nginx: TLS, static files,        | mosquitto | per-device user + certificate,
            |          | rate limits                      |           | per-device topics (acl)
            +----+-----+                                  +-----+-----+
                 | http (compose network only)                  | plain MQTT (compose network only)
            +----v-----+   +------+   +---------+         +-----v-----+
            |   web    |   | jobs |   | release |         |  ingest   | role sensors_ingest
            | gunicorn |   |      |   | one-shot|         |  (Rust)   | (listen only)
            +----+-----+   +--+---+   +----+----+         +-----+-----+
                 | balik_app  | balik_app  | balik_owner        |
            +----v------------v------------v--------------------v-----+
            |  db: PostgreSQL 17 + TimescaleDB (internal network)     |
            +----+----------------------------------------------------+
                 | balik_backup: pg_dump, pg_basebackup, archived WAL
            +----v-----+
            |  backup  | restic: encrypted, off the server
            +----------+
```

- The files: `deploy/` (compose stack, proxy, broker, database image, backup agent, scripts, templates), the web
  image is the `web` stage of `docker/testrunner.Dockerfile`, the production settings are `config/settings.py`'s
  production block (README, Starting a production server).
- The proof: `.github/workflows/go-live-stack.yml` builds and starts this stack on a throwaway runner and checks it
  from outside (`deploy/ci/stack.sh`): health, database roles, HTTPS and headers, the pages, MQTT over TLS, a backup
  shipped and restored with every table's row count, a point-in-time restore. Run it before every release:
  `gh workflow run ci.yml --ref <branch> -f stack=true` (or `gh workflow run go-live-stack.yml` once that file is on
  `main`).
- The commands below run from the `deploy/` folder of the checkout on the server, with `--env-file farm.env`; for
  short, `dc` stands for `docker compose --env-file farm.env`.
