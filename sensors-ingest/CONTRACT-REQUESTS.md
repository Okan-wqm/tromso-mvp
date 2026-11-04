# Contract requests from the ingest (to the owner of sensors/CONTRACT.md)

The ingest builds against sensors/CONTRACT.md as merged from wip/sensors (c525f0b). Nothing below is changed on the
Django side by the ingest branch; each item is either a mismatch found while building and testing, or a choice the
ingest had to make that the contract does not spell out. Evidence: the test named with each item.

## Mismatches (please correct the contract or the schema)

1. **Readings insert without a conflict target.** CONTRACT.md says `INSERT ... ON CONFLICT (channel_no, ts) DO
   NOTHING`; with a conflict target PostgreSQL needs SELECT on the key columns to infer the arbiter index, and the role
   has INSERT only (`permission denied for table sensors_reading`, found by tests/db.rs). The ingest writes
   `ON CONFLICT DO NOTHING` without a target: the primary key is the table's only unique index, so the effect is
   identical. Request: change the sentence in CONTRACT.md (preferred: no SELECT for the writer), or grant
   `SELECT (channel_no, ts)`.
2. **`high_ts` wording.** The model calls it "Newest stored time"; the reducer needs the newest FORWARD time processed,
   stored or suppressed (plan decision 4: a redelivered suppressed message must take the late path, not be counted
   again). Request: "Newest time processed (stored or not); an older or equal time is late or a duplicate".
3. **`last_value`, `last_value_ts`, `last_quality`, `last_good_at` meanings, as written by the ingest:**
   `last_value`/`last_value_ts` = the newest good forward sample (stored or suppressed) and its stored time (device
   time, or receive time when flagged 2 or 4); `last_quality` = that sample's quality without the row bits (heartbeat,
   late); `last_good_at` = the RECEIVE time of that sample; `last_seen_at` = receive time of the newest message carrying
   the channel (any quality, any path). Request: say this in CONTRACT.md.
4. **Freshness after a backlog replay.** `fresh = now - last_good_at <= fresh_s` judges by receive time: a gateway
   replaying two hours of backlog makes a two-hour-old value look fresh for three heartbeats. For a life-support value
   (oxygen) the safe rule is `now - least(last_good_at, last_value_ts) <= fresh_s` (a device clock running slightly
   behind then reads stale, which is the safe direction). Request: the Django freshness rule (one place:
   `evaluate.is_fresh` with `fresh_for`) takes `last_value_ts` into account.
5. **`ignored_total` now counts duplicates.** A sample at exactly the channel's newest time (a device publishing the
   same message twice, the last message of a batch redelivered after a crash) writes no row and adds one to the
   device's `ignored_total` (src/reduce.rs, test `an_older_or_equal_time_takes_the_late_path...`). Before this rule a
   duplicate of a suppressed sample became a LATE row that the rollups counted twice (found by the end-to-end
   duplicates switch: 62 extra rows in 6 s; after: 0). Request: name it in CONTRACT.md ("ignored: duplicates").
6. **`no_route` cannot occur** with the subscription the plan prescribes (one filter per device topic): a message on
   a topic no device has never reaches the ingest (end-to-end garbage switch). The reason stays valid in the list for
   a future wider subscription; the Dead letters page should not promise it.

## Choices the contract leaves open (please confirm or override)

7. **Run attribution bound.** Plan decision 3 says a suppressed sample is counted at the row closing its run "at most
   one heartbeat late". The ingest closes a run early, at its own last sample, on a quality change, after a data gap
   longer than a heartbeat, or before the run sum would overflow; so a sample is counted less than TWO heartbeats
   after it and never across a gap or a quality change (property test `oracle`, database test
   `statistics_oracle_through_the_database`: hour counts within the bound). The chart header text should say "less
   than two heartbeats".
8. **Bad samples are reduced but not counted.** Bad rows (bits 16..128) always have `n = 1`; a bad sample within the
   deadband of the previous bad row leaves no row (its evidence is that row). Rollups exclude bad rows anyway.
9. **Ingest counters not in the schema.** `qos0_dropped` (QoS 0 messages dropped on a full queue), `poison`
   (messages the database refused, dead-lettered as `bad_value`), `discarded_stale` (envelopes of an old session after
   a database failure) and the commit percentiles are only in `/healthz`. Request for contract v2: columns
   `qos0_dropped bigint`, `poison_total bigint` on `sensors_ingest_status`, so the Sensors overview can show them.
10. **Simulated and device-bad bits are never set.** Nothing in the view says a device is simulated (bit 128) or where
    a device reports its own quality (bit 32). The Node-RED simulator's values are therefore stored as clean. Request:
    `sensors_device.is_simulated` in the view (the ingest then sets 128), and, if wanted, a payload format
    `quality_path` with the list of good values (the ingest then sets 32).

## For `manage.py sensor_broker_sync` (not in the ingest branch)

11. Write `passwd` and `acl` into `SENSORS_BROKER_AUTH_DIR` (default `.sensors/broker-auth`, mounted at
    `/mosquitto/auth`), each atomically (temp file in the same directory, then rename). The broker's entrypoint
    (sensors-ingest/mosquitto/entrypoint.sh) reloads within 5 s; spike S0f: connected clients stay, a removed or
    rotated credential is cut off at the reload. Lines: `user <username>` then `topic write <topic>` for each device
    topic of that credential; for each active Connection's `username` (the ingest) `topic read <topic>` for every
    device topic of the connection. `sensors/credentials.py hash_secret` already writes the `$7$` line S0f verified.
12. The ingest's own broker password is the file named by its Connection's `secret_file` under `/run/secrets`
    (compose secret `mqtt_ingest`); the Connection page should say so next to the field.
