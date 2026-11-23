# Go-live checklist

Ticked by a person, for one farm, before the console is used with live fish. Copy it into the farm's record, tick
each line with the date and initials, and do not go live with a line open (write why if a line does not apply).

Farm: ____________________  Server: ____________________  Release: ____________  Date: __________

## Owner decisions (once, for all farms)

- [ ] Hosting target chosen (provider, country, size) and recorded.
- [ ] Backup destination chosen (provider, country, another location than the server, object lock or append-only key).
- [ ] Access method chosen per farm: Cloudflare Tunnel + Access, or VPN only ([access.md](access.md)); for
      Cloudflare, the owner accepted that Cloudflare ends TLS.

## The release

- [ ] CI green on the release's commit (the whole suite).
- [ ] The go-live stack workflow green on the same commit (`gh workflow run ci.yml --ref <tag> -f stack=true`).
- [ ] The release's notes read: migrations that need the old code stopped, new settings.

## Server

- [ ] Size as planned; OS supported and patched; unattended security upgrades on; clock synchronised.
- [ ] ssh: keys only, no root, no password login, from the operators' addresses only; who has access recorded.
- [ ] Firewall: only 22 (restricted), 51820/udp, and 443/80 only for direct access; checked from outside with nmap
      (1883, 8883, 5432, 8000 closed to the internet).
- [ ] Disk encryption where the hosting offers it.
- [ ] Docker Engine and compose versions as in [install.md](install.md).

## Settings and secrets

- [ ] `farm.env` filled in, no placeholder left (`grep -n 'example' farm.env` shows nothing), mode 600.
- [ ] `SECRETS_DIR` outside the checkout, folder 0700, made by `make-secrets.sh` on this server.
- [ ] `restic_password` and `django_audit_digest_key` in the owner's password safe (checked by opening them there).
- [ ] `DJANGO_HSTS_SECONDS` raised to `31536000` after https was confirmed.
- [ ] `email_password` and `backup.env` filled in; `cloudflared.env` only with Cloudflare.

## Running

- [ ] `dc ps`: every service healthy; `release` exited 0 with "release: done".
- [ ] `sh scripts/check-roles.sh`: "every role holds".
- [ ] `curl -sI https://<SITE_HOST>/accounts/login/`: 200, `Strict-Transport-Security`, `Content-Security-Policy`.
- [ ] `http://<SITE_HOST>/` answers 301 to https (or is closed, with Cloudflare).
- [ ] The certificate's name and expiry checked; its renewal set up (Let's Encrypt) or its date in the record.

## People

- [ ] The platform admin made for a named person (at most two) ([first-admin.md](first-admin.md)).
- [ ] An invitation and a password reset tested end to end; both mails arrived, not in spam (SPF/DKIM).
- [ ] Roles made; every user invited with their own account; no shared account.
- [ ] Access: the Cloudflare Access policy (staff, guests) or the VPN peers set, each person tested.
- [ ] Sign-in rate limit seen working (429 after repeated tries).

## Sensors

- [ ] WireGuard up between the server and each site gateway; the broker reachable on the VPN address only.
- [ ] The MQTT CA made for this farm; the CA key moved off the server.
- [ ] Each device: its own Credential and (clientcert) its own certificate; a device tested publishing; a device
      without its certificate refused.
- [ ] The broker connection on the Sensors pages (host `mosquitto`, port 1883, user `ingest`, secret `mqtt_ingest`);
      readings arriving for every channel; no dead letters piling up.

## Alarms

- [ ] The alarm worker running (when it has landed) and its notifications reaching the right people.
- [ ] The dead-man check reaching people by a path that does not depend on the proxy or Cloudflare.
- [ ] The site's local hard-wired alarms tested independently of the console.

## Backups

- [ ] The repository initialised; `agent.sh now` ran; `agent.sh snapshots` shows it; `backup` healthy.
- [ ] A **restore test** done into a throwaway server from the repository (not from the server's disk): row counts
      equal, the console opens on it ([backup-and-restore.md](backup-and-restore.md)); date and result recorded.
- [ ] Retention as decided (`BACKUP_KEEP_*`); the repository's storage alarms (quota) set at the provider.

## Records and people on call

- [ ] The farm's record complete ([per-farm.md](per-farm.md)).
- [ ] Who is called when the console is down, day and night; the [incident.md](incident.md) checklist printed on site.
- [ ] The data-protection officer named; the processing record covers this server and the backup location.

Signed: ____________________  Date: __________
