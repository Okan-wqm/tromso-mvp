# The contract between Django and the ingest service

Django owns every table, view, trigger, role and grant (migrations `sensors/0001_config` and `sensors/0002_readings`);
the ingest service (`sensors-ingest/`, Rust) reads the configuration and writes the readings and the runtime tables.
This file describes what both sides rely on. The authority is the database itself: `sensors/tests/test_contract.py`
fails when a column, a grant, a default or a rule below changes, and the ingest's own tests read the same objects.
A change of anything here is a contract change: `sensors_contract.schema_version` goes up and both sides change together.

## Signing in

- Role `sensors_ingest` (made NOLOGIN by migration 0001; `manage.py sensors_ingest_role --password-file FILE` makes it
  able to sign in). It may only:
  - `SELECT` `sensors_ingest_config`, `sensors_contract`, `sensors_quality_flag`;
  - `SELECT, INSERT, UPDATE` `sensors_channel_state`, `sensors_device_state`, `sensors_ingest_status`,
    `sensors_dead_letter` (never `DELETE`);
  - `INSERT` `sensors_reading` (nothing else: not even `SELECT`).
  It has no right on any configuration table, on credentials, users or the activity log.
- One active ingest per database: it holds `pg_advisory_lock(1397050963)` (the bytes of `SENS`) on its connection for
  as long as it writes. A second instance waits for the lock.

## The configuration: view `sensors_ingest_config`

One row per (channel, calibration epoch) of the live, active configuration, columns in this order:

| Column | Type | Meaning |
|---|---|---|
| `connection_id` | uuid | the broker connection (`sensors_connection.id`) |
| `host`, `port`, `use_tls` | varchar, int, bool | where the broker is |
| `username`, `secret_file` | varchar | the service's own sign-in at the broker; `secret_file` is a file name under `/run/secrets`, never the secret |
| `client_id`, `keepalive_s` | varchar, int | MQTT client id (unique among live connections), keep-alive 5..600 s |
| `device_id`, `device_code` | uuid, varchar | the device (`sensors_device.id`) |
| `topic` | varchar | the topic the device publishes on: no `#`, no leading `$`, at most one `+` and only as a whole level; the device is this row whatever the `+` level holds |
| `expected_interval_s` | int | how often the device sends (1..86400) |
| `encoding` | varchar | `json` |
| `shape` | varchar | `object` (a value per channel at `value_path`) or `array` (items at `items_path`, each naming its channel by `name_key`, value at `value_key`) |
| `time_path`, `time_unit` | varchar | a JSON pointer to the device time (blank: receive time, flag 2) and how it is written: `iso8601`, `epoch_s`, `epoch_ms` |
| `seq_path` | varchar | JSON pointer to the sequence number, blank for none (monitoring only, never a key) |
| `items_path`, `name_key`, `value_key` | varchar | array shape only (blank `items_path`: the message is the array) |
| `channel_no` | int | the channel's number: the key readings are stored under, never reused |
| `channel_code`, `quantity` | varchar | the channel and what it measures (`sensors/quantities.py`) |
| `value_path` / `item_name` | varchar | exactly one is non-blank: the JSON pointer (object shape) or the item's name (array shape) |
| `reduction` | varchar | `all` (store every value) or `deadband` |
| `deadband` | float8 | absolute, in the engineering unit (after calibration and conversion); > 0 unless `reduction = 'all'` |
| `heartbeat_s` | int | store at least once per this many seconds (10..86400) |
| `range_min`, `range_max` | float8 or NULL | both or neither; a value outside is stored with flag 16 |
| `channel_state` | varchar | `active` or `maintenance` (store flagged 64); retired channels are not in the view |
| `valid_from`, `valid_to` | timestamptz or NULL | the calibration epoch `[valid_from, valid_to)` by DEVICE time; `valid_from` NULL is "from the beginning" (the first epoch, never `-infinity`: client libraries cannot hold it), `valid_to` NULL is open |
| `a`, `b` | float8 | stored value = `a * raw + b` (calibration first, then the unit conversion: `a = unit_factor * gain`, `b = unit_factor * offset + unit_offset`) |
| `is_simulated` | bool | the device is a simulator or a test device: store its values flagged 128 (used nowhere) |

Read it by column name, ordered by `channel_no, valid_from NULLS FIRST`. Left out: deleted or retired channels, deleted
or inactive devices and connections, deleted payload formats. No credential is in the view.

## Change notification

Every statement that changes `sensors_connection`, `sensors_payload_format`, `sensors_device`, `sensors_channel` or
`sensors_calibration` increments `sensors_contract.config_epoch` (once per statement) and sends
`NOTIFY sensors_config, '<new epoch>'` on commit. The service `LISTEN`s on `sensors_config` and also compares
`config_epoch` every 30 s, so a notification lost while it was disconnected only delays a reload.

## `sensors_contract` (one row, id = 1)

`schema_version` (1), `config_epoch` bigint, `future_skew_s` (60: a device time further in the future than this is
replaced by the receive time and flagged 4), `retention_days` (730: how long raw readings are kept; equal to the
retention policy of `sensors_reading`, a test keeps them equal), `late_limit_days` (728: a message whose device time is
older than this many days is dead-lettered `too_old`; a CHECK keeps it at least two days inside the retention, so every
message taken in also reaches the rollups, whose late refresh never reaches the dropped region).

## Quality bits (`sensors_quality_flag`, `sensors/quality.py`)

| Bit | Name | Bad |
|---|---|---|
| 1 | heartbeat | no |
| 2 | receive_time | no |
| 4 | clock_suspect | no |
| 8 | late | no |
| 16 | out_of_range | yes |
| 32 | device_bad | yes |
| 64 | maintenance | yes |
| 128 | simulated | yes |

Bad = `quality & 240 <> 0`. A bad reading is stored and is left out of the rollups, the latest value and the charts.

## `sensors_reading` (hypertable, 7-day chunks, compressed after 14 days, dropped after 730)

| Column | Type | Rule |
|---|---|---|
| `channel_no` | int4 NOT NULL | |
| `ts` | timestamptz NOT NULL | the device time (receive time when flagged 2 or 4) |
| `value` | float8 NOT NULL | finite, the stored (calibrated, converted) value |
| `n` | int4 NOT NULL DEFAULT 1 | how many messages the row stands for, itself included |
| `quality` | int2 NOT NULL DEFAULT 0 | 0..255 |
| `run_sum`, `run_min`, `run_max` | float8 NULL | all NULL when `n = 1`; all set and finite when `n > 1`, and then `run_min <= value <= run_max` |

Primary key `(channel_no, ts)`: write with `INSERT ... ON CONFLICT DO NOTHING` WITHOUT a conflict target (the primary
key is the only unique index, so the effect is the same; a target would need SELECT on the key columns, which the role
does not have), so a redelivered message is not stored twice. **Late rows and any row older than 13 days are written ONE
PER STATEMENT**: TimescaleDB 2.17.2 silently drops the rest of a multi-row `INSERT ... ON CONFLICT DO NOTHING` once one
row conflicts inside a compressed chunk (`sensors/tests/test_timescale.py` `CompressedChunkInsertTests` pins it). The run
columns cover the `n` messages the row closes (the good values not stored since the previous stored row, and this one),
so a mean is `sum(coalesce(run_sum, value)) / sum(n)` over clean rows, exactly. A run is closed at its own last sample,
on a quality change, after a gap longer than a heartbeat, or before its sum would overflow: a sample is counted less
than two heartbeats after it, never across a gap or a quality change. Bad rows always have `n = 1`. No other index, no
foreign key. The ingest never updates or deletes a reading.

## Runtime tables

- `sensors_channel_state` (channel_no pk; `run_n` defaults to 0, the rest NULL until written): `last_seen_at` (receive
  time of the newest message carrying the channel, any quality, any path), `last_good_at` (RECEIVE time of the newest
  good forward sample), `last_value` and `last_value_ts` (that sample, stored or suppressed, and its stored time: device
  time, or receive time when flagged 2 or 4), `last_quality` (its quality without the row bits heartbeat and late),
  `anchor_ts`, `anchor_value`, `anchor_quality` (the last STORED value the deadband is measured from), `run_n`,
  `run_sum`, `run_min`, `run_max` (the open run), `high_ts` (the newest time processed, stored or not: a sample at an
  older or equal time is late or a duplicate). Upserted in the same transaction as the readings it describes. Django's
  latest value reads `last_value`, `last_value_ts` and `last_good_at`: a value is fresh while
  `now - least(last_good_at, last_value_ts) <= sensors_channel.fresh_s` (`heartbeat_s` times the channel's
  `fresh_heartbeats`: 3 unless the farm set another, 1 to 20), so a replayed backlog, received now but measured long
  ago, is not fresh. Freshness is judged by Django when a value is read, never by the ingest, which stores whatever
  arrives: `fresh_heartbeats` and `fresh_s` are not in the view, and SQL that makes a channel itself (the ingest's test
  fixture and seeds) gives `fresh_heartbeats`, which has no database default (`IngestSqlTests` reads those statements).
- `sensors_device_state` (device_id pk): `last_message_at`, `last_seq`, `accepted_total`, `late_total`, `dead_total`,
  `ignored_total` (counters default 0; ignored counts duplicates: a sample at exactly the channel's newest time writes
  nothing).
- `sensors_ingest_status` (connection_id pk): `heartbeat_at` NOT NULL, `version` (default ''), `connected`
  (default false), `queue_depth` (default 0, never negative), `last_commit_at`, `qos0_dropped` (QoS 0 messages dropped
  on a full queue) and `poison_total` (messages the database refused, also dead-lettered `bad_value`), both default 0.
  Written at least every 30 s while the service runs; the Sensors overview calls the ingest dead after 90 s without a
  heartbeat and shows both counters.
- `sensors_dead_letter` (id bigint identity): `connection_id`, `device_id` (NULL when no device matched), `topic`,
  `reason` (one of `not_json, no_route, no_channel_match, missing_time, bad_time, too_old, missing_value, bad_value,
  oversize`), `payload_sha256` (64 lowercase hex, or `overflow`), `payload` (at most the first 4096 bytes),
  `payload_len` (the whole message's size, at least the stored bytes), `count` (default 1), `first_at`, `last_at`
  (`last_at >= first_at`), `resolved_at`, `resolved_by` (Django's, set by a person). Unique
  `(connection_id, topic, reason, payload_sha256)`: write with
  `ON CONFLICT (connection_id, topic, reason, payload_sha256) DO UPDATE SET count = sensors_dead_letter.count + 1,
  last_at = EXCLUDED.last_at`. Beyond 1000 new rows per connection and hour, further distinct messages are counted on
  the row with `payload_sha256 = 'overflow'` (empty payload). Readings are never capped. Django deletes rows older
  than 90 days (`manage.py sensors_housekeeping`). With one subscription per device topic, `no_route` cannot occur (a
  message on a topic no device has never reaches the ingest); the reason stays for a wider subscription later.

## The broker's files

`manage.py sensor_broker_sync` writes `passwd` and `acl` atomically into `SENSORS_BROKER_AUTH_DIR` (default
`.sensors/broker-auth`, mounted at `/mosquitto/auth`; the broker reloads them within 5 s). Lines: per enabled
credential `user <username>` then `topic write <topic>` for each of its devices' topics; per active connection its
`username` (the ingest) with `topic read <topic>` for every device topic of the connection. The ingest's own broker
password is the file its connection's `secret_file` names under `/run/secrets` (compose secret `mqtt_ingest`).

## Golden payload vectors

`sensors/tests/vectors.json` (made by the ingest branch, shared): a payload format, channels, a message and what
decoding gives. Django does not decode messages (no second decoder); its "test with a payload" box asks the ingest's
`POST /decode`.
