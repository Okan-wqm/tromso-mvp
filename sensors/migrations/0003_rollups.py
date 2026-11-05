"""The rollup: one continuous aggregate, derived from the readings and never written by the ingest.

`sensors_rollup_1h`: per channel and hour, over the CLEAN readings only (`quality & 240 = 0`, the bad mask of
sensors/quality.py): the messages (`n`, sum of the rows' n), their sum (`sum_v`, each row's run sum or its value), lowest
and highest (`vmin`, `vmax`, each row's run extremes or its value), the last value (`vlast`), the first and last row time
and the number of rows. A mean over any range is sum(sum_v) / sum(n): exact, never a mean of means. Local days are made
from it on read, in the site's time zone (sensors/read.py); no day tier is stored, so a changed zone never leaves a wrong
day behind. Charts below an hour bucket the readings themselves.

No minute tier: the plan's gate 2.4 triggered. A channel stored by its heartbeat keeps about one row a minute, so a minute
rollup measured 100 % of the raw rows (two years, 20 channels: 21 M rows each) and its two-year refresh took 58 min
(sensors-ingest/BENCH.md); the hour is built straight from the readings instead.

It is real time (`materialized_only = false`: what is not refreshed yet is worked out from the readings on read) and made
WITH NO DATA. Its refresh policy runs every hour over the last 75 days (ending an hour back), so a late reading in an
already refreshed region is taken in by the next run. The window cannot start at NULL: TimescaleDB refuses a compression
policy on an aggregate whose refresh window reaches the region it compresses. A reading later than the window is taken
in by the daily job `sensors_refresh_late`, which refreshes from the window back to the contract's late limit and a day,
never further: dropping raw chunks invalidates their region (TimescaleDB 2.17) and a refresh over it would empty the
rollup there. A refresh recomputes only invalidated buckets, so the job costs nothing on a day without late readings, and
it refreshes into compressed buckets (checked on 2.17.2). The hours are compressed after 90 days and kept. Continuous
aggregates and their policies are TSL features of the community build (README, Sensors). They cannot be made inside a
transaction: this migration is not atomic, and each statement is its own step, with its reverse."""
from django.db import migrations

HOUR = """
CREATE MATERIALIZED VIEW sensors_rollup_1h
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT channel_no,
       time_bucket(INTERVAL '1 hour', ts) AS bucket,
       sum(n)::bigint AS n,
       sum(coalesce(run_sum, value)) AS sum_v,
       min(coalesce(run_min, value)) AS vmin,
       max(coalesce(run_max, value)) AS vmax,
       last(value, ts) AS vlast,
       min(ts) AS first_ts,
       max(ts) AS last_ts,
       count(*) AS rows
FROM sensors_reading
WHERE (quality & 240) = 0
GROUP BY channel_no, time_bucket(INTERVAL '1 hour', ts)
WITH NO DATA
"""

WINDOW = '75 days'
POLICIES = [
    f"SELECT add_continuous_aggregate_policy('sensors_rollup_1h', start_offset => INTERVAL '{WINDOW}', "
    f"end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour')",
    "ALTER MATERIALIZED VIEW sensors_rollup_1h SET (timescaledb.compress = true)",
    "SELECT add_compression_policy('sensors_rollup_1h', compress_after => INTERVAL '90 days')",
]
POLICIES_BACK = [
    "SELECT remove_compression_policy('sensors_rollup_1h', if_exists => true)",
    "SELECT remove_continuous_aggregate_policy('sensors_rollup_1h', if_exists => true)",
]
# What lies before the policy's window, back to the contract's late limit and a day (a message older than the limit is
# refused as too old; the raw data, two days further back, may be dropped, and a refresh over a dropped region would
# empty the rollup). Refresh runs outside a transaction block: a job's procedure is called that way.
LATE_JOB = [
    f"""CREATE PROCEDURE sensors_refresh_late(job_id integer, config jsonb) LANGUAGE plpgsql AS $$
DECLARE
    since timestamptz := now() - make_interval(days => (SELECT late_limit_days + 1 FROM sensors_contract WHERE id = 1));
BEGIN
    IF since < now() - INTERVAL '{WINDOW}' THEN
        CALL refresh_continuous_aggregate('sensors_rollup_1h', since, now() - INTERVAL '{WINDOW}');
    END IF;
END
$$""",
    "SELECT add_job('sensors_refresh_late', INTERVAL '1 day')",
]
LATE_JOB_BACK = [
    "SELECT delete_job(job_id) FROM timescaledb_information.jobs WHERE proc_name = 'sensors_refresh_late'",
    'DROP PROCEDURE IF EXISTS sensors_refresh_late(integer, jsonb)',
]


class Migration(migrations.Migration):
    atomic = False

    dependencies = [('sensors', '0002_readings')]

    operations = [
        migrations.RunSQL(HOUR, reverse_sql='DROP MATERIALIZED VIEW IF EXISTS sensors_rollup_1h'),
        *[migrations.RunSQL(sql, reverse_sql=migrations.RunSQL.noop) for sql in POLICIES[:-1]],
        migrations.RunSQL(POLICIES[-1], reverse_sql=POLICIES_BACK),
        migrations.RunSQL(LATE_JOB, reverse_sql=LATE_JOB_BACK),
    ]
