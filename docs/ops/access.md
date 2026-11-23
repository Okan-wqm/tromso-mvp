# Access: people to the console, sensors to the broker

Templates (placeholders only) are in `deploy/cloudflare/` and `deploy/wireguard/`. Nothing in this repository calls
the Cloudflare API or touches DNS: a person sets these up per farm. Django's own sign-in, roles and rights stay in
force whatever is in front (defence in depth).

## People: three ways, one per farm

| | A. Cloudflare Tunnel + Access (recommended for remote staff) | B. WireGuard VPN only | C. Public HTTPS |
|---|---|---|---|
| Open inbound port | none (`cloudflared` dials out) | 51820/udp | 443, 80 |
| Who reaches the sign-in page | only people Access lets through (e-mail one-time code or the farm's SSO, per-person rules, time-limited guests) | only devices with a VPN key | everyone on the internet |
| TLS ends at | Cloudflare, then again at the farm's proxy (origin certificate) | the farm's proxy | the farm's proxy |
| Who can see the traffic | Cloudflare (it ends TLS) | nobody but the farm | nobody but the farm |
| Phones and tablets on site | the Cloudflare login in the browser | a VPN app on each | the browser |
| Cost | free up to 50 users | free | free |

**Owner decision for A:** Cloudflare ends TLS, so it can read the traffic (confidential experiments, regulatory
reports, personal data). Acceptable for the pilot? EU-only processing is a paid option. If not acceptable: B.

### A. Cloudflare Tunnel + Access

1. Zero Trust dashboard (by a person): Networks › Tunnels › create a tunnel (cloudflared); copy its token into
   `SECRETS_DIR/cloudflared.env` as `TUNNEL_TOKEN=...`.
2. The tunnel's public hostname: `SITE_HOST` → `https://proxy:443`, origin server name `SITE_HOST`
   (`deploy/cloudflare/config.yml.example` shows the same as a file). The proxy's certificate: a Cloudflare origin
   certificate for `SITE_HOST` in `SECRETS_DIR/tls/`.
3. Access › Applications › self-hosted, domain `SITE_HOST` (`deploy/cloudflare/access-application.example.json`):
   a policy for the farm's staff (their e-mail domain or a list, one-time PIN or SSO), a separate one for named guests
   with a short session; nothing else allowed.
4. `farm.env`: `HTTPS_BIND=127.0.0.1`, `HTTP_BIND=127.0.0.1` (nothing published to the internet),
   `PROXY_REAL_IP_FROM=<EDGE_SUBNET>`, `PROXY_REAL_IP_HEADER=CF-Connecting-IP` (the rate limits then count each real
   client, not the tunnel).
5. `dc --profile cloudflare up -d`. The firewall keeps 443 and 80 closed.
6. Check from outside: the address shows Cloudflare's login first; after it, the farm's sign-in page.

Kept outside Cloudflare: the sensors (B below), the alarm worker and the site's hard-wired alarms. The alarm worker's
dead-man signal must reach people by a path that does not depend on Cloudflare (a Cloudflare outage must raise it).

### B. WireGuard only

`deploy/wireguard/wg0-server.conf.example` on the server, one peer per person or device (`wg genkey`), the console
reached at `https://SITE_HOST` resolving to the server's VPN address (an internal DNS name or a hosts entry). The
proxy's certificate from `sh scripts/certs.sh proxy-internal <SITE_HOST>`; `proxy-ca/ca.crt` installed in the
browsers. `HTTPS_BIND` and `HTTP_BIND` = the VPN address.

### C. Public HTTPS

Only with a strong reason: the sign-in page faces the internet. Let's Encrypt (DNS-01) certificate, the proxy's rate
limit, an IP allowlist in the server's firewall where the farm's addresses are fixed.

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

- From the internet: `nmap -p 1883,8883,5432,8000 <public address>` shows them closed (and 443/80 too with A).
- From a gateway on the VPN: `mosquitto_sub -h <vpn address> -p 8883 --cafile ca.crt --cert client.crt --key
  client.key -u <user> -P <password> -t '#' -W 3`: connected, but receives nothing (a device may not read).
- Without the client certificate, or with a wrong password: refused (the stack workflow proves both).
