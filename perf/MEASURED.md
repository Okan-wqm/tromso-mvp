# Performance plan: risks with what was measured

A copy of section 8 of the performance plan (PLAN.md, 2026-11-06), followed by what the NOW part of the work measured
or decided by spike. Every figure below was produced on the shared developer machine (Windows 10, Docker Desktop,
TimescaleDB 2.17.2-pg17 in the `balik-ciftligi-db-1` container, several other test suites running at the same time):
counts, shapes and ratios are meaningful there, absolute times only as an order of magnitude (the plan's absolute p95
runs belong to the dedicated server).

## 8. Risks and open questions

Risks: deferred-trigger deadlock or hot-row contention on key 0 (decided by the step-3 tests; table-level keys are limited to report sources); a `Share` field added without a state field (the test); a checkpoint horizon off by one (grid test at the exact floor); the three in-flight migration trees colliding (renumber at landing); a digest key omitting a printed value (oracle fails closed); the sealing filter adding queries to folds (twin budget runs); the dev server running without persistent connections (so dev numbers include connect cost; `DB_CONN_MAX_AGE` default stays 0 because runserver threads leak persistent connections, and the server run sets it); `lice_weeks` unbounded and the `Reader.treated` triple loop are known weak points left for the domain step 12 review. Unverified by every expert and by me: where the 3.1 s goes (step 0), `django.tasks` 6.1 contents and the DB package licence (spike), gapfill versus bucket on compressed chunks (harness), whether every record-changing service writes an audit row (irrelevant after this plan: nothing relies on it).

Open questions only the owner can answer:
1. **Raw sensor retention**: policy of 730 days exists in the contract; research may need years. Recommended default: no deletion policy enabled until the owner states a period; keep compression only.
2. **Wall cap**: accept `MONITOR_MAX_CARDS` 240 with a visible "showing N of M" and an attention strip that never cuts alarms? Recommended: yes.
3. **Freshness wording**: may the university accept "figures as of HH:MM" and a clock-figure refresh of at most 60 s on the wall? Recommended: yes (it is today's bucket).
4. **Second process**: may production run a `worker` service from the same image (and a Windows process for dev), needed for PDF extraction and checkpoint builds? Recommended: yes.
5. **Dedicated server run**: who provides the server and time for the absolute-p95 and 200-poller run before launch? Recommended: a half-day slot after step 8.


## Measured and decided (NOW part)

### core_rev (step 3)
- **Deadlock and hot rows, settled by test.** The plan's bump function (`rev + 1` in each row trigger, locks in firing
  order) would deadlock two writers that touch the same keys in opposite order (the reliability expert's objection).
  Built instead: each row trigger only NOTES the key and earliest day in a transaction-local setting (no write, no
  lock); the deferred constraint trigger applies all noted keys at COMMIT, sorted, each once. Measured with two real
  connections: 15 rounds of opposite-order commits started on a barrier, **0 deadlocks**; an open (uncommitted) writer
  does **not block** a second writer of the same batch (its bump waited for no one, statement_timeout 3 s).
- A 5,000-line operation writes **one** core_rev row update per batch (once per key per transaction), so no dead-tuple
  storm; fillfactor 50 keeps them HOT.
- **Plan correction: keys are text.** `core_rev.key bigint` (plan 2.1) cannot hold a batch id: batches are UUIDs
  (`AuditedModel`). Key is `varchar(64)`, a table-level scope's key is `'0'`.
- **Plan correction: a restore can move revisions backwards.** If `core_rev` comes from an older dump than a stored
  figure, a later write could bring a key back to the figure's stamp and validate stale data. `rebuild()` moves every
  revision past every stored stamp (consumers register their `max(built_rev)` query in `core.rev.STAMPED`) and sets a
  floor row `('*','0')` so a key first seen later starts above it. A key without a row is "unknown", never valid.
- Builder's compare-and-set also clears the transaction's note of the key, so a write later in the same transaction
  moves the revision again (otherwise the once-per-transaction skip could validate a checkpoint built mid-transaction).
- Trigger presence: `core.rev.missing()`; its wiring into `farm/stock/integrity.py` waits for wip/fix-integrity.

### Jobs (step 11 spike): FAIL for the third-party queue, own backend built
- Django 6.1.2's `django.tasks` ships only `immediate` and `dummy` backends (read from the installed package).
- `django-tasks` 0.12.0 and `django-tasks-db` 0.13.0: BSD-3-Clause (read from the wheels' METADATA). The database backend
  has no retries, no lease or heartbeat (a killed worker leaves its task RUNNING for ever), and no unique active job
  (read from `django_tasks_db/backend.py`, `models.py`, `db_worker.py`). Fails three of the five criteria.
- Built `core.jobs.DatabaseBackend` behind `django.tasks` (`@task`, `enqueue`, `get_result`): enqueue inside the
  caller's transaction (tested: a rolled-back caller leaves no job), partial unique indexes for one WAITING and one
  RUNNING job per key (deviation from the plan's single `('queued','running')` unique: folding a new request into a
  RUNNING job could lose an update; the new one now waits behind it), lease 5 min extended by a thread, reaper, retries
  30 s doubling to 1 h, `dead` after 5, unknown kind `failed` at once, periodic kinds keyed per period, `/healthz`.
- The worker as a Docker service: repository `Dockerfile` (python:3.12-slim + requirements, the test runner's recipe)
  and the compose service `worker` (profile `worker`). There was no app image before.

### Storage tiers (D1/D2 spike)
- Parquet writer and reader: **DuckDB 1.5.6, MIT** (wheel classifier), no required dependencies; one package does
  both, no pyarrow. Released 2026-09-28 (PyPI). Fetching a TIMESTAMPTZ into Python needs pytz, so the code never does:
  times cross the boundary as microseconds since 1970.
- TimescaleDB 2.17.2 has `move_chunk`, `drop_chunks`, `compress_chunk`, `refresh_continuous_aggregate` (pg_proc),
  licence `timescale` (community TSL) as already used by migrations 0002/0003.
- **Found while designing the drop**: (1) the hourly rollup is real time: hours not yet materialized are computed from
  the raw rows on read, so dropping a chunk before its hours are stored loses them; the drop checks the rollup's
  watermark and the invalidation logs for the range. (2) The existing retention policy (`add_retention_policy 730
  days`, sensors 0002) drops chunks WITHOUT export; with the cold tier on it must be replaced by the tier job (waits
  for the owner-settings wiring). (3) The contract's default late limit is 728 days, and the rollup's refresh policy
  reaches back 75 days: a chunk may go cold only when older than both (plus a day); with today's defaults nothing goes
  cold before 2 years, which matches D1's default.
