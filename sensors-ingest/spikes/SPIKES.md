# Ingest spikes (plan step S0 e and f)

Each spike is a script kept in this folder; the result below is what the script printed on 2026-11-04.

## S0f: Mosquitto `$7$` password lines from Python `hashlib` (PASS)

Scripts: `s0f_mosquitto_hash.py` (offline), `s0f_live.sh` (docker, `eclipse-mosquitto:2.0.20`).

Format (mosquitto 2.0.20): `USER:$7$ITER$B64(salt)$B64(hash)` where
`hash = hashlib.pbkdf2_hmac('sha512', password_utf8, salt, ITER, 64)`, `salt` 12 random bytes, standard base64
with padding, `ITER` 101 by default in `mosquitto_passwd` (`-I` changes it; the broker takes the count from the
line, so a higher count is accepted). The function to copy into `sensor_broker_sync` is `mosquitto_hash()` in
`s0f_mosquitto_hash.py` (stdlib only).

Results:
- `hashlib` reproduces two lines written by `mosquitto_passwd -b` (101 and 1000 iterations); a wrong password does
  not verify.
- Live broker reading a Python-written `passwd` plus `acl`: right password accepted, wrong refused, unknown user
  refused.
- `docker kill -s HUP` (SIGHUP) reloads `passwd` and `acl`: an added user is accepted, a removed user refused, and a
  connected client whose credential is unchanged (the ingest's persistent QoS 1 subscriber) stays connected and keeps
  receiving.
- A client that is connected when its credential is removed is disconnected at the reload (its reconnect is refused
  "not authorised"). So disabling or rotating a credential takes effect at the next SIGHUP; no broker restart and no
  admin connection are needed.

Consequences for `sensor_broker_sync` (Django side): write `passwd` and `acl` to the shared volume atomically
(write a temp file in the same directory, then rename), file mode 0700 or the broker warns (future versions refuse a
world-readable file), then signal the broker (SIGHUP). Rotating the ingest's own credential disconnects the ingest
once; it reconnects with its persistent session (no loss: unacked messages are redelivered).
