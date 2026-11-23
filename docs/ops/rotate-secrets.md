# Rotate secrets

Every secret of a farm's server is a file in `SECRETS_DIR` (folder 0700, files 0444, never in git), made by
`scripts/make-secrets.sh` or `scripts/certs.sh`. A container reads its own at `/run/secrets/<name>` and sees the file
it was started with: after replacing a file, **recreate** the services that read it
(`dc up -d --no-deps --force-recreate <services>`); a restart is not enough. `dc` is
`docker compose --env-file farm.env` in `deploy/`.

Rotate on a schedule (yearly), when a person who could read a secret leaves, and at once on any suspicion
([incident.md](incident.md)). Write each rotation in the farm's record.

| Secret | File | Read by | How to rotate | What it costs |
|---|---|---|---|---|
| Database roles | `db_app_password`, `db_owner_password`, `db_ingest_password`, `db_backup_password`, `postgres_password` | web and jobs; release; ingest; backup; restore | `sh scripts/rotate-db-password.sh <role>` (below) | seconds: a new connection of an old container is refused until it is recreated |
| Django's secret key | `django_secret_key` | web, jobs, release | new value (below), recreate web and jobs | everyone is signed out; links in invitations and reset mails already sent stop working (send again) |
| The log's digest key | `django_audit_digest_key` | web, jobs, release | **only on suspicion** (below) | the private values logged before can no longer be compared with new ones |
| SMTP password | `email_password` | web, jobs, release | change it at the mail provider, write the file, recreate web and jobs | mails between the two steps fail and show on the user's row |
| Backup repository password | `restic_password` | backup, restore | `restic key add` / `key remove` (below) | none; the old password stops opening the repository |
| Backup repository access keys | `backup.env` | backup, restore | new key at the provider, write the file, recreate backup, delete the old key at the provider | none |
| The ingest's broker password | `mqtt_ingest`, `mqtt_passwd_extra` | ingest; jobs (writes the broker's users) | delete both files, `sh scripts/make-secrets.sh`, recreate jobs, then ingest | the ingest reconnects; the broker keeps its queue |
| A device's broker password | the device's Credential (Sensors pages) | the device | new secret on the Credential's page, then on the device | that device is cut off until it has the new one |
| Console certificate | `tls/fullchain.pem`, `tls/privkey.pem` | proxy | replace both, `dc exec proxy nginx -s reload` | none |
| MQTT server certificate | `mqtt/server.crt`, `mqtt/server.key` | mosquitto | remove both, `sh scripts/certs.sh mqtt-server ...`, `dc up -d --no-deps --force-recreate mosquitto` (the files are mounted one by one) | devices reconnect |
| A device's client certificate | `mqtt-devices/<device>/` (then on the device) | the device | `certs.sh mqtt-device` again after removing its folder; a lost device: also disable its Credential (the certificate alone does not let it in) | that device only |
| The MQTT CA | `mqtt/ca.crt`, `mqtt-ca/ca.key` | mosquitto, every device | only if its key leaked: new CA, new server certificate, new certificate on every device | every device until it has its new certificate |
| Cloudflare Tunnel token | `cloudflared.env` | cloudflared | rotate in the Zero Trust dashboard, write the file, `dc --profile cloudflare up -d --force-recreate cloudflared` | seconds |

## A database role

```
SECRETS_DIR=/etc/balik/<farm>/secrets sh scripts/rotate-db-password.sh balik_app
```

It sets the new password in the database (as the superuser, inside the database container, the password on stdin),
replaces the secret file (the old one is kept as `<name>.old` until you delete it) and recreates the services that
sign in as the role. The database container itself still holds the old copies of the files it was started with (it
reads them at its first start only); `scripts/check-roles.sh` reads them there, so recreate it in the next
maintenance window: `dc up -d --no-deps --force-recreate db` (a database restart: a minute).

## Django's secret key

```
cd "$SECRETS_DIR" && openssl rand -base64 96 | tr -d '\n+/=' | cut -c1-64 > .k && chmod 0444 .k && mv -f .k django_secret_key
dc up -d --no-deps --force-recreate web jobs
```

## The activity log's digest key

The private values in the activity log are stored as digests under this key (README, Security in the pages). A new
key makes new digests that cannot be compared with the old ones (the log still shows that a value changed). Rotate it
only when it may have leaked, and record the date: digests before it are under the old key, which is then destroyed.
Same commands as the secret key, with `django_audit_digest_key` (48 characters or more).

## The backup repository's password

```
dc run --rm --no-deps -v "$SECRETS_DIR/restic_password.new:/run/new:ro" backup restic key add --new-password-file /run/new
dc run --rm --no-deps backup restic key list                   # two keys now
mv -f "$SECRETS_DIR/restic_password.new" "$SECRETS_DIR/restic_password"
dc up -d --no-deps --force-recreate backup
dc run --rm --no-deps backup restic key list                   # note the old key's id (not marked current)
dc run --rm --no-deps backup restic key remove <old key id>
```

(`restic_password.new` made first like any other: `openssl rand -base64 96 | tr -d '\n+/=' | cut -c1-64`, mode 0444.)
Put the new password in the owner's safe **before** removing the old key.
