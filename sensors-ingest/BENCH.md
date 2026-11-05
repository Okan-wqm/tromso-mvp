# Measured numbers (plan section 8, risks, and the S10 extreme suite)

Measured 2026-11-04/05 on the development machine: Windows 10, Docker Desktop (WSL 2), 31 GiB, the shared
`timescale/timescaledb:2.17.2-pg17` container (other agents' test databases active at the same time), Mosquitto
2.0.20 with the repository configuration, the release ingest image. Scripts: `bench/run.sh <phase>`,
`e2e/run.sh`; raw output in `bench/.state/results.txt` (not committed). These are numbers of THIS machine; a
production server with a dedicated database disk will differ and should be re-measured with the same scripts.

## Plan risks, as measured

| Plan risk | Measured | Verdict |
|---|---|---|
| (1) State upsert per touched channel per batch is the bottleneck at 10k msg/s | 500 channels x 5 samples per message. With the plan's broker window of 5000 the ingest drains **5278 msg/s** (26 391 samples/s), commit p50 315 ms, p99 767 ms. With a window of **20000** it drains **9074 msg/s** (45 370 samples/s, start-up included), commit p50 529 ms, p99 1294 ms, 29 commits for 294 000 messages. In a live 6.5k msg/s stream (two publishers; one publisher tops out near 7k msg/s here) the ingest kept up within 4 s; 1.2 M messages, 6 M samples all accounted (rows + open runs = 6 000 000 exactly), ingest memory 12-18 MiB, CPU 15-75 % of one core | The commit-before-ack rule held throughout. 10k msg/s sustained is NOT shown on this machine: 9.1k drained with the larger window. The repository now ships window 20000 / queue 40000 / batch max 20000 (the change the plan names: larger batches, never a weaker ack rule). A dedicated database would be the next lever; overlapping the next batch's decode with the current commit is a possible optimisation not built |
| (2) A redelivered suppressed message adds one LATE sample | Crash right after a COMMIT and before its PUBACKs (failpoint, e2e): **0** extra LATE rows, 3 duplicates ignored, nothing stored twice, no second lost. SIGKILL of the ingest: 0 extra rows. Since the duplicate rule (a sample at exactly the newest time writes nothing) the redelivered batch's newest samples cost nothing; older suppressed ones would still cost one LATE row each (property test `redelivered_batch_costs_only_its_suppressed_samples`) | Within the plan; smaller than stated |
| (3) Broker hard crash loses up to the autosave interval (5 s) | Ingest running: broker SIGKILL in a 500 msg/s QoS 1 stream, restarted after 3 s: **19 995 acknowledged by the broker, 0 lost** (messages pass the broker in milliseconds). Ingest stopped (backlog in the session): 12 s at 500 msg/s queued, broker SIGKILL right after the last PUBACK: **6000 acknowledged, 1049 lost (2.1 s of data)** | As accepted by the owner: the loss window is the autosave interval and only bites while messages wait in the broker (ingest down). Shown honestly on the overview, never claimed zero |
| (4) The 1 m tier may be as large as raw after reduction | Two years, 20 channels, one row per minute (a 1 Hz channel stored by its 60 s heartbeat): raw 21 024 020 rows, **1 m tier 21 024 020 rows = 100 % of raw** (gate: 40 %); 1 h tier 350 420 rows. Refreshing the 1 m tier over two years took 58 min | **Gate exceeded: owner decision needed** (plan 2.4: then build 1 h from raw, a one-migration change in Django's 0003). A heartbeat-bound channel stores about one row per minute, so a 1 m tier repeats raw |
| Compression | 2496 MB raw before, 731 MB after compressing chunks older than 14 days: **ratio 3.7** (synthetic noisy values; real plateaus compress better) | |

## Read paths on two years (20 channels, 21 M raw rows, compressed)

| Query | Plan target | Measured |
|---|---|---|
| one channel, two years, local days from the 1 h tier (731 points) | < 150 ms | **32 ms** |
| ten channels, seven days, 15 min buckets from the 1 m tier (6670 points) | < 300 ms | **59 ms** |
| latest of 500 channels (state table) | < 20 ms | **1.3 ms** |
| value at a moment a year ago (step-after, compressed chunk) | | **79 ms** |
| one channel, one day of raw rows a year ago (compressed) | | **20 ms** |

Not measured: 500 channels x two years (about 525 M rows at one per minute: beyond this shared machine's disk and
memory) and the viewer page (Django side).

## Failure drills (e2e/run.sh: Node-RED -> Mosquitto -> ingest image -> TimescaleDB)

| Drill | Result |
|---|---|
| steady stream 60 s | `all` channels: 62 rows, no gap; deadband TEMP-IN: 2 rows for 81 samples |
| duplicates switch (6 s) | no key twice; 0 extra rows (after the duplicate rule; 62 before) |
| garbage switch | dead letters `bad_value`, `missing_time`, `not_json`, `oversize` (full length kept, 4 KiB stored); unknown topic never subscribed |
| late (3 and 20 days) | stored on the late path |
| clock 10 min ahead | stored at receive time, flagged 4; the channel's newest time never in the future |
| outage 12 s then replay | every second stored at its device time |
| ingest SIGTERM, 10 s down | no second lost, 0 rows redelivered |
| ingest SIGKILL | no second lost |
| crash after COMMIT before PUBACK | no second lost, nothing stored twice, 0 extra LATE rows, 3 duplicates ignored |
| database sessions killed | recovered, no second lost |
| broker restart / SIGKILL | the simulator (Node-RED) does not buffer while the broker is down: 6 s / 11 s gaps are publisher-side; the broker-side loss is measured above with the accounting publisher |

## Poison flood

50 000 distinct garbage messages at 2000 msg/s beside a normal 1000 msg/s stream: **1010 dead-letter rows** (1000
own + 10 overflow rows, one per topic), all 50 000 counted; the normal stream: **25 000 of 25 000 accepted**; commit
p99 274 ms.

## TimescaleDB finding

TimescaleDB 2.17.2 silently drops the remaining rows of a multi-row `INSERT ... ON CONFLICT DO NOTHING` once one row
conflicts inside a compressed chunk. Found by tests/db.rs; the ingest writes late and old rows one per statement
(CONTRACT-REQUESTS.md item 13).

## Many sources (owner requirement: about 500 msg/s in total from many devices)

`bench/multisource.sh 1800 500`, 2026-11-05: **500 devices, each its own MQTT connection, credential and topic**,
1 msg/s with a jittered start, three payload formats (PLC object with ISO time, probe array with epoch ms, flow meter
ISO UTC), 10 devices with clocks 10 min ahead, **two brokers and two Connection rows** in the one ingest (400 + 100
devices), 50 devices (25 per broker) disconnected together for 120 s at minute 20 and back with their backlog.
30 minutes sustained:

| Measured | Result |
|---|---|
| messages | 900 000 sent, 900 000 acknowledged by the brokers |
| per device | acknowledged = accepted + dead-lettered + ignored on all 500 devices; 0 dead letters, 0 duplicates, 0 late rows |
| per channel | samples in rows + open run = messages sent on all 1168 channels (2 102 400 samples, 625 759 rows after the deadband) |
| clock skew | the 10 devices 10 min ahead stored at receive time, flagged clock_suspect; no channel's newest time in the future |
| 50 devices out 120 s, back with a backlog | every second stored at its device time (0 gaps) |
| commit latency, device time to committed (state table polled every 100 ms, so +-100 ms) | p50 350 ms, p95 953 ms, p99 1829 ms, max 3890 ms |
| commits | 4797, p50 90 ms, p99 858 ms, max 2891 ms |
| ingest | peak 12.1 MiB, CPU median 7.1 %, max 19.1 % of one core; no QoS 0 drop, no poison |
| brokers | peak 6.2 MiB and 4.3 MiB; up to 401 and 101 connected clients (devices, the ingest, a monitor) |

Several connections are supported by the design and were measured here: one MQTT session per Connection row, one
writer and one transaction for all of them.
