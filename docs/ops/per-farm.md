# One installation per farm

Every farm runs its own copy of the stack on its own server, with its own database, secrets, certificates, backup
repository and access rules. Nothing is shared, so one farm's outage, breach or restore never touches another's.
Install each with [install.md](install.md); this page is what must differ, and the record kept for each farm.

## What differs per farm

| Setting | Where | Rule |
|---|---|---|
| Installation name | `COMPOSE_PROJECT_NAME` in `farm.env` | `farm-<short code>`, unique across farms; it also names the farm in the backup repository (`BACKUP_HOST_TAG`) |
| Console address | `SITE_HOST` | its own host name, its own TLS certificate |
| Secrets | `SECRETS_DIR` | made by `make-secrets.sh` on that server; never copied from another farm |
| Database | the server's `pgdata` volume, `DB_NAME` | one database per farm; never two farms in one database or on one server |
| Backup repository | `RESTIC_REPOSITORY`, `backup.env`, `restic_password` | its own path or bucket and its own password; a farm's backup key opens no other farm's backups |
| Company | `COMPANY_NAME`, `COMPANY_TIME_ZONE` | the farm's legal name and its time zone (a sea site in Norway: `Europe/Oslo`) |
| Mail | `EMAIL_*`, `DEFAULT_FROM_EMAIL` | a sender the farm's mail domain allows (SPF/DKIM) |
| Sensor VPN | WireGuard on the server, `MQTT_BIND_ADDRESS` | its own range (`10.8.<n>.0/24`, n per farm) and its own keys |
| MQTT CA | `SECRETS_DIR/mqtt`, `mqtt-ca` | its own CA: a device certificate of one farm is refused by every other |
| Access | Cloudflare Access application or VPN peers | its own application and policy (who may sign in), [access.md](access.md) |
| Sizes | `GUNICORN_*`, `DB_*`, `WEB_*`, `INGEST_*` | by the farm's users and sensors |

## The farm's record (kept by the owner, not in git)

One page per farm, filled in at installation and kept current:

- farm, contact person and phone, the data-protection officer;
- server: provider, location (country), size, IP addresses, who has ssh access;
- `SITE_HOST`, how people reach it (Cloudflare application name or VPN), certificate expiry date;
- release installed and when; the last upgrade;
- backup repository (address, not the keys), where `restic_password` and `django_audit_digest_key` are kept, the date
  of the last restore test and its result;
- the sensor VPN range and the site gateways' names;
- the go-live checklist, ticked, with the date and who ticked it.

## Many farms

- Release one farm at a time; start with the pilot, then the others after a day without incidents.
- Run `go-live-stack.yml` for the release before the first farm is upgraded.
- Restore tests rotate: one farm a month, every farm at least once a year.
