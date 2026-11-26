# Access: people to the console, sensors to the broker

Templates (placeholders only) are in `deploy/cloudflare/` and `deploy/wireguard/`. Nothing in this repository calls
the Cloudflare API or touches DNS: a person sets these up per farm. Django's own sign-in, roles and rights stay in
force whatever is in front (defence in depth).

## People: the recommendation, and the other ways

**For the pilot: WireGuard for people and sensors alike (B).** The console's sign-in has a password and nothing more
(no second factor, no lockout: [first-admin.md](first-admin.md)), so the network in front is the second lock. With
WireGuard nobody outside the VPN even reaches the sign-in page, no third party sees the traffic, and one mechanism
serves the staff and the sensors. Cloudflare Access (A) is the option for staff who cannot run a VPN app, with a second
factor required there. Public HTTPS (C) is not for this console.

| | B. WireGuard (recommended) | A. Cloudflare Tunnel + Access (option) | C. Public HTTPS (not recommended) |
|---|---|---|---|
| Open inbound port | 51820/udp | none (`cloudflared` dials out) | 443, 80 |
| `HTTPS_BIND` / `HTTP_BIND` | the server's VPN address | 127.0.0.1 (the default) | 0.0.0.0 |
| Who reaches the sign-in page | only devices with a VPN key | only people Access lets through, **with a second factor** | everyone on the internet |
| `PROXY_ADMIN_ALLOW` (`/admin/`) | the VPN range (`10.8.0.0/24`) | `all`, Access's second factor in front | 127.0.0.1/32 (nobody) |
| TLS ends at | the farm's proxy | Cloudflare, then again at the farm's proxy | the farm's proxy |
| Who can see the traffic | nobody but the farm | Cloudflare (it ends TLS) | nobody but the farm |
| Phones and tablets on site | a WireGuard app on each (a QR code per device) | the Cloudflare login in the browser | the browser |
| Cost | free | free up to 50 users | free |

**Owner decision for A:** Cloudflare ends TLS, so it can read the traffic (confidential experiments, regulatory
reports, personal data). EU-only processing is a paid option.

### B. WireGuard (recommended)

1. On the server: `deploy/wireguard/wg0-server.conf.example` as `/etc/wireguard/wg0.conf` (mode 0600), the farm's
   range (`10.8.<n>.0/24`, [per-farm.md](per-farm.md)); `systemctl enable --now wg-quick@wg0`; Docker started after it
   (the reboot test, [upgrade.md](upgrade.md)).
2. One peer per person's device and per site gateway (`wg genkey`, `wg pubkey`, `wg genpsk`), each with its own
   `/32`; a person's laptop or phone gets its configuration as a file or a QR code (`qrencode -t ansiutf8 < peer.conf`),
   and the private key never leaves that device. The peer list is the access list: removing a peer ends that access.
3. `farm.env`: `HTTPS_BIND` and `HTTP_BIND` = the server's VPN address (`10.8.<n>.1`), `MQTT_BIND_ADDRESS` the same,
   `PROXY_ADMIN_ALLOW` the VPN range.
4. The console's name `SITE_HOST` resolves, for the VPN's users, to the server's VPN address (an internal DNS name, or
   a public DNS record pointing to the private address). Its certificate: Let's Encrypt with DNS-01 when the name is
   public, otherwise `sh scripts/certs.sh proxy-internal <SITE_HOST>` with `proxy-ca/ca.crt` installed in the browsers.
5. Check: from a VPN peer the sign-in page opens; from outside the VPN nothing answers (the nmap check below).

### A. Cloudflare Tunnel + Access (option)

1. Zero Trust dashboard (by a person): Networks › Tunnels › create a tunnel (cloudflared); copy its token into
   `SECRETS_DIR/cloudflared.env` as `TUNNEL_TOKEN=...`.
2. The tunnel's public hostname: `SITE_HOST` → `https://proxy:443`, origin server name `SITE_HOST`
   (`deploy/cloudflare/config.yml.example` shows the same as a file). The proxy's certificate: a Cloudflare origin
   certificate for `SITE_HOST` in `SECRETS_DIR/tls/`.
3. Access › Applications › self-hosted, domain `SITE_HOST` (`deploy/cloudflare/access-application.example.json`):
   a policy for the farm's staff (their e-mail domain or a list) **requiring a second factor**: an identity provider
   that enforces MFA (the farm's Microsoft or Google accounts with MFA on), not the e-mail one-time PIN alone; a
   separate policy for named guests with a short session; nothing else allowed.
4. `farm.env`: `HTTPS_BIND=127.0.0.1`, `HTTP_BIND=127.0.0.1` (nothing published to the internet),
   `PROXY_REAL_IP_FROM=<EDGE_SUBNET>`, `PROXY_REAL_IP_HEADER=CF-Connecting-IP` (the rate limits then count each real
   client, not the tunnel), `PROXY_ADMIN_ALLOW=all`.
5. `dc --profile cloudflare up -d`. The firewall keeps 443 and 80 closed.
6. Check from outside: the address shows Cloudflare's login first, then the second factor, then the farm's sign-in.

Kept outside Cloudflare: the sensors (below), the heartbeat ([monitoring.md](monitoring.md)), the alarm worker and the
site's hard-wired alarms. The alarm worker's dead-man signal must reach people by a path that does not depend on
Cloudflare (a Cloudflare outage must raise it).

### C. Public HTTPS (not recommended)

The sign-in page faces the internet with a password as its only factor. If ever chosen: Let's Encrypt (DNS-01), the
proxy's rate limits, `PROXY_ADMIN_ALLOW` left at 127.0.0.1/32, and an allowlist of the farm's fixed addresses in the
`DOCKER-USER` chain (ufw does not see published ports: [install.md](install.md)).

## Sensors: MQTT over TLS inside the VPN

The recommended design (plan, owner question of 2026-11-08), and what the stack does:

- A site's gateway (an edge PC or the Node-RED box) connects to the server over **WireGuard**
  (`deploy/wireguard/wg0-gateway.conf.example`); the broker's TLS listener is published on the VPN address only
  (`MQTT_BIND_ADDRESS`), so **no MQTT port is open to the internet**.
- **TLS 1.2+ on 8883** even inside the VPN (`deploy/mosquitto/*/tls.conf`), with the farm's own CA
  (`scripts/certs.sh mqtt-ca`, `mqtt-server`).
- **Every device its own credential** (a Credential on the Sensors pages) and, with `MQTT_DEVICE_AUTH=clientcert`
  (the default), **its own client certificate** too (`scripts/certs.sh mqtt-device <user>`). A device that cannot
  hold a certificate: `MQTT_DEVICE_AUTH=password` (then the VPN and the password are its two locks).
- **Per-device topics:** `manage.py sensor_broker_sync` (every minute, the `jobs` service) writes the broker's acl from
  the database: a device may write only its own topics and read nothing; the ingest reads only the configured
  devices' topics.
- **Listen only:** the server never publishes to the field; no command path exists.
- The ingest validates payloads, dead-letters what it cannot use and counts per device (README, Sensors).
- An IP allowlist per site in the WireGuard peers (`AllowedIPs`) as an extra layer.
- Cloudflare is not used for MQTT (Tunnel TCP needs cloudflared on every client; Spectrum is enterprise-only).

The plain listener (1883) is inside the compose network only, for the ingest.

## Checks

- From the internet: `nmap -Pn -p 22,80,443,1883,5432,8000,8080,8883 <public address>` shows only 22 open (80 and
  443 too only with C).
- From a gateway on the VPN: `mosquitto_sub -h <vpn address> -p 8883 --cafile ca.crt --cert client.crt --key
  client.key -u <user> -P <password> -t '#' -W 3`: connected, but receives nothing (a device may not read).
- Without the client certificate, or with a wrong password: refused (the stack workflow proves both).
