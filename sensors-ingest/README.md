# sensors-ingest

The MQTT ingest of the Sensors subsystem (plan: sensors/PLAN.md decisions 1-12; contract: sensors/CONTRACT.md). It
listens to the broker only (no edge software), decodes each device's messages with its payload format, stores device
time, calibrates, reduces (deadband plus heartbeat with run statistics) and writes to TimescaleDB. Django owns every
table, view and page; this service reads the view `sensors_ingest_config` and writes the readings and the runtime
tables as the role `sensors_ingest`. It refuses to write as anything else: on every connection it asks what it is
(`db::refused_role`), and a superuser or an owner of the schema's tables is refused with the reason in the log, so a DSN
that names the wrong role never writes (the data-layering audit, L-14).

## The guarantees, and where each is tested

| Rule | Where | Test |
|---|---|---|
| A message is acknowledged (PUBACK) only after the transaction holding its rows, states and dead letters is committed, in delivery order | `service.rs` `flush`/`applied` | tests/service.rs `messages_are_acknowledged_only_after...`; e2e crash drill (failpoint after COMMIT) |
| A database failure acknowledges nothing; the MQTT sessions restart when the database is back, so the broker redelivers in order | `service.rs` `fail`, `supervisor.rs` | tests/service.rs `a_database_failure...`; e2e "database sessions killed" |
| Redelivery and duplicates store nothing twice: key `(channel_no, ts)`, the same instant again is a duplicate (no row), an older time a LATE row | `reduce.rs`, `db.rs` | reduce property `redelivered_batch...`; tests/db.rs; e2e duplicates and crash drill |
| Device time is stored; no time path: receive time (flag 2); clock ahead beyond `future_skew_s`: receive time (flag 4); older than `late_limit_days`: dead letter `too_old` | `timerule.rs` | timerule unit and property tests; e2e late and skew switches |
| One timestamp type, UTC, no local time zone: a device's ISO 8601 time needs its offset (RFC 3339, second 60 is the next second), epoch s/ms is a time only in -262143..262142, everything is cut to microseconds; `/decode`'s `received_at` is read in the relaxed RFC 3339 form; times are written back as RFC 3339 with `Z`. On the `time` crate since chrono became unmaintained (RUSTSEC-2026-0543), with chrono's behaviour kept | `ts.rs`, `decode.rs` | `time_pins.rs` (written on chrono, unchanged on `time`); ts unit and property tests; tests/db.rs `timestamps_round_trip...` |
| Nothing is dropped silently: undecodable, unmatched or refused content becomes a dead letter (sha256, first 4 KiB, full length, count); a flood folds into one `overflow` row per topic and reason after 1000 new keys per connection and hour; readings are never capped | `pipeline.rs` | pipeline tests; tests/db.rs flood; e2e garbage; bench poison |
| A message the database refuses (an unforeseen rule) is isolated, dead-lettered `bad_value` and acknowledged, so it can never block the stream | `service.rs` `isolate` | tests/service.rs `a_message_that_breaks_its_batch...` |
| Statistics are exact: rollup sums over clean rows plus the open run equal the unreduced stream; a sample is counted at a row less than two heartbeats after it | `reduce.rs` | property `oracle`; tests/db.rs `statistics_oracle_through_the_database` |
| Bounded memory under backpressure: the broker's in-flight window (20000) brakes QoS 1; the queue (40000) is larger; a QoS 0 message finding the queue full is dropped and counted (`qos0_dropped`) | `mqtt.rs` `forward` | mqtt unit tests; spike S0e |
| One writer: `pg_advisory_lock` held on the writing session; a second ingest stands by | `db.rs`, `service.rs` | tests/db.rs, tests/service.rs `a_second_ingest_stands_by...` |
| Clean stop on SIGTERM: readers stop queueing, the queue is committed and acknowledged, then DISCONNECT (session kept) | `supervisor.rs` | tests/service.rs `shutdown...`; tests/live.rs; e2e SIGTERM (0 redelivered rows) |
| Restart safety: the state row is all the reducer needs | `reduce.rs`, `db.rs` | property `resume_from_saved_state`; tests/service.rs `a_restarted_ingest...` |
| Configuration changes apply live: NOTIFY `sensors_config` plus a 30 s epoch poll; topics re-subscribed on the live session | `service.rs`, `supervisor.rs` | tests/service.rs `a_configuration_change...`; tests/live.rs |
| No runtime path unwraps or panics (clippy denies `unwrap`, `expect`, `panic`, indexing) | Cargo.toml `[lints]` | `cargo clippy -D warnings` |

## Running

- Compose (repository root): `docker compose --profile sensors up -d` starts `mosquitto`, `sensors-ingest` and the
  `node-red` field simulator. Files it needs under `.sensors/` are listed at the top of docker-compose.yml.
- Settings (environment, see src/env.rs): `INGEST_DB` (libpq string WITHOUT password), `INGEST_DB_PASSWORD_FILE`,
  `INGEST_SECRETS_DIR`, `INGEST_MQTT_CA_FILE`, `INGEST_HTTP`, `INGEST_BATCH_MS`, `INGEST_BATCH_MAX`, `INGEST_QUEUE`.
- `GET /healthz` (container health check): 200 when the writer holds the lock, wrote to the database within 60 s and
  every broker connection is up; the body has the counters and commit percentiles. `POST /decode` with
  `{format, channels, payload, received_at?}` returns what the ingest would decode (the payload-format page's test box).
- The broker reloads `passwd`/`acl` within 5 s of `manage.py sensor_broker_sync` rewriting them
  (mosquitto/entrypoint.sh). A TLS listener for field devices goes in `mosquitto/conf.d/tls.conf`.

## Tests

- `tests/run.sh`: a fresh test database migrated by Django, a broker with the production configuration, then
  `cargo fmt --check`, `cargo test` (unit, property, database as role `sensors_ingest`, live MQTT), `cargo clippy -D
  warnings`, `cargo deny check` (licences: permissive only, `rodbus` banned; advisories; sources) and THIRD_PARTY
  freshness. CI runs the same on every pull request (the root README, CI and dependency updates), on the toolchain
  pinned in `rust-toolchain.toml` (1.88.0, as the Dockerfile and `tests/run.sh`'s image).
- `simulator/check.sh`: the Node-RED simulator's devices and switches; every run has its own containers, network and
  MQTT client id, so runs at the same time never disturb each other (`simulator/test_isolation.sh`).
- `simulator/farm-check.sh`: the farm flow on its own database with Django's demo sensors; per parameter code, values
  sent = samples stored or suppressed, rows stored for all 12 codes, nothing dead-lettered.
- `bench/run.sh throughput|drain|brokerkill|brokerkill-queued|poison|twoyears`: the S10 numbers in BENCH.md.
- `bench/multisource.sh [SECONDS] [N]`: N devices (500), each with its own connection, credential and topic, 1 msg/s,
  three payload formats, two brokers and two Connection rows, 50 devices out and back with a backlog; per device and
  per channel accounting, latency, CPU, memory, connections (BENCH.md).
- `e2e/run.sh`: Node-RED -> Mosquitto -> ingest image -> TimescaleDB with every switch, SIGTERM, SIGKILL, a crash right
  after a COMMIT, database sessions killed, broker restart and SIGKILL.
- Spikes S0e/S0f (rumqttc manual acks, Mosquitto `$7$` from hashlib): spikes/SPIKES.md.

## Field simulator (owner amendment A2)

`simulator/flows.json` is generated by `simulator/build-flows.js` (`docker run --rm -v "$PWD/simulator:/sim" -w /sim
node:22-bookworm-slim node build-flows.js`). Devices: `sim/plc-1/tags` (object of tags, ISO time +01:00),
`sim/o2-probe-1/data` (array of items, epoch ms), `sim/flow-meter-1/state` (ISO UTC). The editor (127.0.0.1:1880) has
one inject node per switch: outage start / end and replay, duplicates on / off, out of order, late messages, garbage,
clock skew ahead / behind / off. The broker login comes from `SIM_MQTT_USER` and the secret `sim_mqtt`, never the
flows.

## Licences

Every dependency and its licence: THIRD_PARTY (generated from Cargo.lock, checked by tests/run.sh). The gate:
deny.toml.

## Farm flow (owner scenario)

The tab "Farm" publishes for the water devices of the configuration view (the demo sensors `manage.py
sensors_demo_setup` makes for the tanks and systems of a database): `simulator/farm-config.sh DB FILE` writes the device
list (topics, payload formats, channels) from the view, the Node-RED container reads it at start
(`FARM_DEVICES_FILE`, compose mounts `.sensors/farm`). It behaves like real transmitters: its own MQTT connection and
credential (`SIM_FARM_USER`, default `demo-simulator`, secret file `sim_farm` from `sensors_demo_setup
--secret-file`), QoS 1, a persistent session, every device on its own timer with 15 % jitter, 40 messages per second in
total, each message carrying all the device's water values (7-8). Values come from a model, not a table: the day's
temperature curve, oxygen falling after feeding at 08, 12 and 16 and recovering, CO2 and turbidity rising with it, pH
following CO2, ammonia and nitrite peaks later, nitrate rising through the week and alkalinity used up until the Monday
water exchange, saturation from oxygen and temperature. Switches: farm on, farm off.

To run it on a database: `manage.py sensors_demo_setup --confirm --secret-file <file>` (Django), copy that secret to
`.sensors/secrets/sim_farm` readable by uid 1000 (the Node-RED container user; the file Django writes is mode 600 and
the simulator says "cannot read" in its log otherwise), `manage.py sensor_broker_sync`, then
`sensors-ingest/simulator/farm-config.sh <database> .sensors/farm/farm-devices.json` and restart `node-red`.
