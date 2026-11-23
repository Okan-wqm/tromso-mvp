# Incident checklist

For anything that threatens the fish, the farm's data or the server: the console down, wrong or missing water
values, alarms not arriving, a suspected break-in, a lost laptop with access, a backup that stopped. Work down the
list; write every step with its time in the farm's record as you go. `dc` is `docker compose --env-file farm.env` in
`deploy/`.

## 0. The fish first

- [ ] If water values or alarms may be wrong or missing, tell the farm **now**: the site watches the tanks by hand and
      relies on the local, hard-wired alarms until the console is confirmed right again. The console never shows a
      stale value as current (it says "no recent data"), but a person must know the console is in doubt.

## Break glass (prepared at installation, used only when the normal way is gone)

When ssh, the VPN or the platform admin's own account cannot be used (a lost key, the only admin away, an account
locked out), these are the way in. They are made at installation and kept sealed in the owner's safe, apart from the
daily credentials:

- an **ssh key** for the server, of its own (`ssh-keygen -t ed25519`), its public half in root's `authorized_keys`
  with a comment naming it the break-glass key; the provider's out-of-band console login as the second way;
- a **WireGuard peer** of its own (a configuration file), not on any daily device;
- the server's `postgres_password` and the repository's `restic_password` (they are in the inventory anyway,
  [rotate-secrets.md](rotate-secrets.md));
- for the console: no standing account. A new platform admin is made when needed:
  `dc run --rm --no-deps web python manage.py createsuperuser`.

**Using it:** two people agree (the owner and the person on call), the opening is written in the farm's record with
the time and the reason, and afterwards every item used is replaced (a new key, a new peer, the passwords rotated)
and the temporary admin deactivated. A break-glass key found in daily use is an incident.

## 1. What is happening

- [ ] `dc ps`: which service is not healthy? `dc logs --since 1h <service>`.
- [ ] The proxy's access log (`dc logs proxy`): errors (5xx), refused sign-ins (429), unusual addresses.
- [ ] The web server's log (`dc logs web`): `ERROR`, `django.security` lines (a refused host, a bad signature).
- [ ] The database: `dc exec db pg_isready`; disk space `df -h`; `docker system df` (never prune).
- [ ] Sensors: the ingest's health (`dc exec ingest` has no shell: `docker inspect --format '{{json .State.Health}}'
      <project>-ingest-1`), the Sensors overview page, dead letters.
- [ ] Backups: `dc exec backup sh /usr/local/lib/balik-backup/agent.sh health`, `... snapshots`.
- [ ] The activity log (Company › Administration › Activity log): who did what, since when.

## 2. Contain (a suspected break-in or a leaked secret)

- [ ] Cut access at the edge: disable the Cloudflare Access application or the person's access (or stop
      `cloudflared`), or remove the VPN peer. On a public server: `dc stop proxy`.
- [ ] Deactivate the affected accounts (Users). A platform admin account: deactivate it from another admin, or with
      `dc run --rm --no-deps web python manage.py shell` (`User.objects.filter(username=...).update(is_active=False)`).
- [ ] Sign everyone out: rotate `django_secret_key` ([rotate-secrets.md](rotate-secrets.md)).
- [ ] Rotate every secret the attacker may have read (server access: all of `SECRETS_DIR`; a device: its credential
      and certificate). The digest key and the backup password only if they may have left the server.
- [ ] Keep the evidence before changing more: `dc logs --since 72h > /root/incident-<date>.log` (copy it off the
      server), the activity log export, the list of accounts and their last sign-in.
- [ ] Do not restore over the evidence: restore into a new server if the data must be checked.

## 3. Recover

- [ ] A service down: `dc up -d <service>`; a release gone wrong: [upgrade.md](upgrade.md), "When it fails".
- [ ] Data damaged or deleted: restore into a **new** installation first, compare, then decide
      ([backup-and-restore.md](backup-and-restore.md); to a moment before the damage: "Restore to a moment").
- [ ] The server lost: a new server ([install.md](install.md)), the secrets from the owner's safe, restore.
- [ ] After any restore: `sh scripts/check-roles.sh`, `check --database default`, the newest records checked against
      the farm's paper or the devices' own logs; sensor readings are re-sent by devices that queue (QoS 1).

## 4. Tell

- [ ] The farm's contact and the owner, from the first step.
- [ ] Personal data involved (accounts, the HR area, contact details): the data-protection officer **at once**. Under
      the GDPR (Art. 33) a breach is reported to the supervisory authority (in Norway Datatilsynet) within 72 hours of
      becoming aware of it, unless it is unlikely to result in a risk; the people affected are told when the risk is
      high (Art. 34). The DPO decides; the record of what happened and when is the evidence.
- [ ] Regulatory reports affected (e.g. a filing based on wrong numbers): the farm decides on a correction (Reports).

## 5. Afterwards

- [ ] What failed, why, what changes (a check, an alarm, a runbook line); the change made and tested.
- [ ] The incident, its timeline and its end in the farm's record.
