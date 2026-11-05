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

## S0e: rumqttc 0.25.1 manual acks with Mosquitto 2.0.20, 5000 in-flight window (PASS)

Script: `s0e_live.sh` runs `examples/s0e_manual_ack.rs` against a broker with `max_inflight_messages 5000`
(6000 QoS 1 messages published, the subscriber has `clean_session=false`, `manual_acks=true`).

Results (all PASS):
- Without acks the broker delivers exactly 5000 messages and stops: the broker's in-flight window is the brake;
  the ingest's memory is bounded by it, so the internal queue only has to hold one window.
- Acking 2500 in order releases exactly the next 1000 (all that was left), in publish order.
- Crash without DISCONNECT, reconnect with the same client id: `session_present=true`; all 3500 unacked messages
  are redelivered, none of the 2500 acked; same order; DUP set on 3500 of 3500; same packet id on 3500 of 3500.
- A PUBACK for an already-acked packet id, and one for an unknown id, are ignored by the broker: the connection stays
  up and delivery continues. So a PUBACK left in rumqttc's request queue from before a reconnect is harmless.
- A QoS 0 publish reaches a QoS 1 subscriber at QoS 0: outside the window, not redelivered, no broker brake.

Consequences for the ingest:
- PUBACK only after COMMIT, in delivery order; the eventloop is polled on its own task at all times (PINGREQ and
  PUBACK leave through `poll`), never blocked by the writer.
- Internal queue capacity >= broker `max_inflight_messages` for QoS 1 traffic; QoS 0 traffic is not braked by the
  broker, so the reader never awaits a full queue: a QoS 0 message that finds the queue full is counted and logged as
  dropped (`qos0_dropped`), a QoS 1 message cannot find it full (window <= capacity), and if it ever does the ingest
  disconnects without acking (redelivery) instead of blocking the loop.
- Redelivered messages (DUP) are written again: rows are idempotent through the `(channel_no, ts)` key and a
  previously suppressed sample takes the late path (plan decision 4).
- rumqttc's default incoming packet limit is 10 KiB: the ingest raises it above the broker's `max_packet_size`, so
  a large message can never make the client drop the connection in a redelivery loop.
