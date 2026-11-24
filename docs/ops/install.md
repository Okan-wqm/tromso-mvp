# Install on a fresh server

From an empty server to the sign-in page of one farm. Each farm gets its own server and goes through this once
([per-farm.md](per-farm.md) lists what differs per farm). Commands run as root on the server unless said otherwise;
`dc` is `docker compose --env-file farm.env`, run in the `deploy/` folder.

## 1. The server

- **Size:** 4 vCPU, 8 GB RAM, **200 GB SSD** is the starting point for one farm with two years of sensor readings
  (the disk budget: [backup-and-restore.md](backup-and-restore.md)). The database's memory and CPU limits are in `farm.env` (`DB_MEMORY`, `DB_CPUS`, ...).
- **System:** Ubuntu 24.04 LTS or Debian 12, unattended security upgrades on, the clock synchronised (chrony or
  systemd-timesyncd: sensor times and alarm times depend on it).
- **Docker:** Docker Engine 27 or later with the compose plugin 2.24 or later, from Docker's own repository. Docker's
  data on a disk with room (`/var/lib/docker`).
- **Firewall** (ufw or nftables), default deny inbound:
  - ssh (22) from the operators' addresses only, keys only, no password login, no root login;
  - 51820/udp for WireGuard ([access.md](access.md));
  - nothing else: the database, the web server and the plain MQTT listener are published nowhere.
- **Docker and the firewall:** a port Docker publishes is let in by Docker's own iptables rules, **before ufw sees
  it**: a ufw rule cannot close it. Exposure is therefore chosen where the port is published, in `farm.env`:
  `HTTPS_BIND`/`HTTP_BIND` (default `127.0.0.1`: nobody outside the server) and `MQTT_BIND_ADDRESS` (the WireGuard
  address). Set `HTTPS_BIND` to the WireGuard address for VPN access, and to `0.0.0.0` only for public access
  ([access.md](access.md), C). Rules that must hold whatever Docker does go in the `DOCKER-USER` chain.
- **No way out for the proxy and the broker.** Their networks (`front`, `mqtt-edge`) are not masqueraded
  (`deploy/compose.yml`), so a packet from them to the internet has no return path; the web server's mail and the
  backup leave by `egress`. A second lock, so that they cannot even send a packet out (with the subnets of `farm.env`):
  ```
  iptables -I DOCKER-USER -s 172.31.250.0/24 ! -d 172.31.250.0/24 -m conntrack --ctstate NEW -j DROP   # front
  iptables -I DOCKER-USER -s 172.31.252.0/24 ! -d 172.31.252.0/24 -m conntrack --ctstate NEW -j DROP   # mqtt-edge
  ```
  (answers to connections coming in are not NEW, so the published ports keep working), made permanent with
  `iptables-persistent` (`netfilter-persistent save`). The networks have no IPv6. The go-live stack workflow probes
  every service's way out (TCP, UDP and IPv6): only the web server and the backup agent have one.
- **Check from outside** after the start (another machine, not on the VPN):
  `nmap -Pn -p 22,80,443,1883,5432,8000,8080,8883 <public address>`: only 22 (from the operators' addresses) is
  open, and 80/443 only when public access was chosen.
- **Disk encryption** of the server's volumes where the hosting offers it (the database holds personal data).

## 2. The code

```
git clone <the repository's URL> /opt/balik                         # a read-only deploy key if the repository is private
cd /opt/balik
git checkout <release tag>                                          # never an unreleased branch
cd deploy
```

## 3. The farm's settings

```
cp farm.env.example farm.env
chmod 600 farm.env
```

Fill in every value (they are placeholders): the installation's name, `SITE_HOST`, `SECRETS_DIR` (outside the
checkout, e.g. `/etc/balik/<farm>/secrets`), the mail server, `MQTT_BIND_ADDRESS` (the server's WireGuard address),
`RESTIC_REPOSITORY` (the off-server backup target), the sizes. On a first installation set `DJANGO_HSTS_SECONDS=3600`
and raise it to `31536000` once https is confirmed (browsers remember it).

## 4. The secrets

```
export SECRETS_DIR=/etc/balik/<farm>/secrets
sh scripts/make-secrets.sh
```

It makes every password and key (random, never printed) and leaves three files for a person:

- `email_password`: the SMTP account's password (leave it empty and remove `EMAIL_HOST_PASSWORD_FILE` from `farm.env`
  when the mail server takes no sign-in);
- `backup.env`: the backup repository's access keys (S3: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`);
- `cloudflared.env`: only with Cloudflare Tunnel (`TUNNEL_TOKEN=`).

**Copy `restic_password` and `django_audit_digest_key` into the owner's password safe now.** Without the first no
backup can ever be read; without the second the activity log's private values can no longer be compared.

## 5. Certificates

- The console's certificate, `SECRETS_DIR/tls/fullchain.pem` and `privkey.pem`, one of ([access.md](access.md)):
  - Cloudflare Tunnel: a Cloudflare origin certificate for `SITE_HOST` (or `sh scripts/certs.sh proxy-internal
    <SITE_HOST>` with the tunnel's `caPool`);
  - public DNS without Cloudflare: Let's Encrypt with a DNS-01 challenge (certbot on the host, renewal hook copies the
    two files and runs `dc exec proxy nginx -s reload`);
  - VPN only: `sh scripts/certs.sh proxy-internal <SITE_HOST>` and install `proxy-ca/ca.crt` in the browsers.
- The MQTT broker:
  ```
  sh scripts/certs.sh mqtt-ca
  sh scripts/certs.sh mqtt-server <vpn address> <vpn host name>
  sh scripts/certs.sh mqtt-device <device user>        # one per device or gateway (MQTT_DEVICE_AUTH=clientcert)
  ```
  Move `SECRETS_DIR/mqtt-ca/ca.key` off the server once the devices have their certificates.

## 6. Build, then start

```
dc build                         # the first time 20-30 minutes (the chemistry core and the ingest are compiled)
dc run --rm backup init          # the backup repository, once
dc up -d
dc ps                            # every service "healthy"; release "exited (0)"
dc logs release                  # check --deploy, migrate, rights, static files: "release: done"
```

`release` stops the start when a production setting is unsafe or missing (it names the check, e.g. `core.E009`):
fix `farm.env` or the secret, then `dc up -d` again.

## 7. Check the installation

```
sh scripts/check-roles.sh                                     # every database role holds
dc exec backup sh /usr/local/lib/balik-backup/agent.sh now    # a dump, a base backup and a ship now
dc exec backup sh /usr/local/lib/balik-backup/agent.sh snapshots
curl -sI https://<SITE_HOST>/accounts/login/                  # 200, Strict-Transport-Security, Content-Security-Policy
```

Then open `https://<SITE_HOST>` in a browser: the sign-in page.

## 8. Then

1. The first admin and the first invitations: [first-admin.md](first-admin.md).
2. Access for people and sensors: [access.md](access.md). The sensors' broker connection is made on the Sensors
   pages: host `mosquitto`, port `1883`, no TLS (inside the stack), user `ingest` (`MQTT_INGEST_USER`), secret file
   `mqtt_ingest`. Each device gets its own credential there; the broker's users and topics follow within a minute.
3. A restore test into a throwaway server ([backup-and-restore.md](backup-and-restore.md)) before real data arrives.
4. The [GO-LIVE-CHECKLIST.md](GO-LIVE-CHECKLIST.md), ticked and kept with the farm's record.
