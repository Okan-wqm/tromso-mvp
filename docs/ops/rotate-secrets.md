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
| Database roles | `db_app_password`, `db_owner_password`, `db_ingest_password`, `db_backup_password`, `postgres_password` | web and jobs; release; ingest; backup; restore | `sh scripts/rotate-db-password.sh <role>` (below) | seconds: a new connection of a container not yet recreated is refused |
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
sh scripts/rotate-db-password.sh balik_app        # SECRETS_DIR from the environment, else from farm.env
```

It checks that the role's secret file exists and its folder is writable before anything changes, writes the new
password beside it, gives the database only the password's SCRAM-SHA-256 verifier (made in the web image from the
password on stdin: the plain password never reaches the database server, its logs or its activity view), replaces the
secret file in one step (no copy of the old password is kept) and recreates the services that sign in as the role.
The new password is never lost: it is written beside the secret file (`.<name>.new`) before anything can fail and kept
until it has replaced the file; a failure says whether the database has it and what to do with that file. The
database container keeps the old copies of the files it was started with, but nothing reads them after its first
start: `scripts/check-roles.sh` reads the passwords from `SECRETS_DIR`, so it holds right after a rotation, and the
container needs no recreation. The go-live stack workflow rotates the app role's password this way and checks that the
new one signs in, the old one is refused, no copy is left, the database's log never holds it and `check-roles.sh`
passes at once.

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

## What must also live off the server (the owner's safe)

A server lost with its disks takes its `SECRETS_DIR` with it. What can be made again, and what cannot:

| Secret | Off the server? | Why |
|---|---|---|
| `restic_password` | **yes, always** | without it no backup can ever be read |
| `django_audit_digest_key` | **yes, always** | the activity log's private values are digested under it; a new key cannot be compared with the old digests |
| The repository's credentials (`backup.env`) | yes | the restore service needs them on the new server (or the owner makes a new append-only user) |
| The MQTT CA key (`mqtt-ca/ca.key`) | **only there**: it leaves the server once the devices have their certificates | a new CA means a new certificate on every device |
| The proxy CA key (`proxy-ca/ca.key`, VPN-only consoles) | yes | a new CA means installing it again in every browser |
| The WireGuard server's private key | yes | a new key means a new configuration on every peer |
| `postgres_password`, the role passwords, `django_secret_key`, `mqtt_ingest` | no | made again by `make-secrets.sh` on the new server (the restored dump holds no role passwords; sessions and links are lost) |
| `email_password`, `cloudflared.env` | no | at the provider |
| The break-glass items ([incident.md](incident.md)) | yes | they are for when the server cannot be reached the usual way |

The safe holds each with the farm's name and the date it was made; a rotation replaces the entry.

## MQTT certificates: renewal

The broker's and the devices' certificates live 825 days, the CA ten years (`scripts/certs.sh`).

- **The broker's certificate:** the heartbeat turns red 21 days before it ends ([monitoring.md](monitoring.md)).
  Renew it as in the table above (the devices keep theirs: the CA is unchanged).
- **A device's certificate:** write each device's end date in the farm's record when it is made
  (`openssl x509 -enddate -noout -in client.crt`) and renew it a month before: remove its folder
  (`SECRETS_DIR/mqtt-devices/<device>`), `sh scripts/certs.sh mqtt-device <device>` (with the CA key brought back for
  the purpose), load the new files into the device, remove them from the server again.
- **There is no revocation list:** a certificate stays valid until it ends. A lost or stolen device is cut off by its
  Credential (disable it on the Sensors pages: the broker refuses its user within a minute) and by removing its site's
  WireGuard peer if the gateway went with it.
