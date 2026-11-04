"""The rollups: two continuous aggregates, derived from the readings and never written by the ingest.

- `sensors_rollup_1m`: per channel and minute, over the CLEAN readings only (`quality & 240 = 0`, the bad mask of
  sensors/quality.py): the messages (`n`, sum of the rows' n), their sum (`sum_v`, each row's run sum or its value),
  lowest and highest (`vmin`, `vmax`, each row's run extremes or its value), the last value (`vlast`), the first and last
  row time and the number of rows. A mean over any range is sum(sum_v) / sum(n): exact, never a mean of means.
- `sensors_rollup_1h`: the same per hour, built on the minutes (a hierarchical aggregate), so wider buckets regroup
  exactly by sums. Local days are made from it on read, in the site's time zone (sensors/read.py); no day tier is stored,
  so a changed zone never leaves a wrong day behind.

Both are real time (`materialized_only = false`: what is not refreshed yet is worked out from the source on read) and
made WITH NO DATA (nothing to backfill on a new database). Their refresh policies run every minute and every hour over
the last 35 and 75 days (ending one minute and one hour back), so a late reading in an already refreshed region is taken
in by the next run. The window cannot start at NULL (the plan's first choice): TimescaleDB refuses a compression policy
on an aggregate whose refresh window reaches the region it compresses (compress_after must be past the window's start).
A reading later than the window is taken in by the daily job `sensors_refresh_late`, which refreshes from the windows
back to the contract's late limit and a day, never further: dropping raw chunks invalidates their region (TimescaleDB
2.17), and a refresh over it would empty the rollups there (the plan's NULL start would have done that on every run). A
refresh recomputes only invalidated buckets, so the job costs nothing on a day without late readings, and it refreshes
into compressed buckets (checked on 2.17.2). The minutes are compressed after 60 days and dropped with the raw readings
after 730 (so they are kept at least as long); the hours are compressed after 90 days and kept. Continuous aggregates and their policies are TSL
features of the community build (README, Sensors: licences). They cannot be made inside a transaction: this migration
is not atomic, and each statement is its own step, with its reverse."""
from django.db import migrations

MINUTE = """
CREATE MATERIALIZED VIEW sensors_rollup_1m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT channel_no,
       time_bucket(INTERVAL '1 minute', ts) AS bucket,
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
GROUP BY channel_no, time_bucket(INTERVAL '1 minute', ts)
WITH NO DATA
"""
HOUR = """
CREATE MATERIALIZED VIEW sensors_rollup_1h
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT channel_no,
       time_bucket(INTERVAL '1 hour', bucket) AS bucket,
       sum(n)::bigint AS n,
       sum(sum_v) AS sum_v,
       min(vmin) AS vmin,
       max(vmax) AS vmax,
       last(vlast, last_ts) AS vlast,
       min(first_ts) AS first_ts,
       max(last_ts) AS last_ts,
       sum(rows)::bigint AS rows
FROM sensors_rollup_1m
GROUP BY channel_no, time_bucket(INTERVAL '1 hour', bucket)
WITH NO DATA
"""

MINUTE_WINDOW, HOUR_WINDOW = '35 days', '75 days'
# What lies before the policies' windows, back to the contract's late limit and a day (a message older than the limit is
# refused as too old; the raw data, two days further back, may be dropped, and a refresh over a dropped region would empty
# the rollups), minutes first (the hours are built on them). Refresh needs to be outside a transaction
# block: a job's procedure is called that way by the scheduler and by run_job.
LATE_JOB = [
    f"""CREATE PROCEDURE sensors_refresh_late(job_id integer, config jsonb) LANGUAGE plpgsql AS $$
DECLARE
    since timestamptz := now() - make_interval(days => (SELECT late_limit_days + 1 FROM sensors_contract WHERE id = 1));
BEGIN
    IF since < now() - INTERVAL '{MINUTE_WINDOW}' THEN
        CALL refresh_continuous_aggregate('sensors_rollup_1m', since, now() - INTERVAL '{MINUTE_WINDOW}');
    END IF;
    -- The hours see the minutes' changes only once they are committed.
    COMMIT;
    IF since < now() - INTERVAL '{HOUR_WINDOW}' THEN
        CALL refresh_continuous_aggregate('sensors_rollup_1h', since, now() - INTERVAL '{HOUR_WINDOW}');
    END IF;
END
$$""",
    "SELECT add_job('sensors_refresh_late', INTERVAL '1 day')",
]
LATE_JOB_BACK = [
    "SELECT delete_job(job_id) FROM timescaledb_information.jobs WHERE proc_name = 'sensors_refresh_late'",
    'DROP PROCEDURE IF EXISTS sensors_refresh_late(integer, jsonb)',
]


def policies(view, start_offset, end_offset, schedule, compress_after, drop_after=None):
    """The statements that give a rollup its policies, and their reverses."""
    forward = [
        f"SELECT add_continuous_aggregate_policy('{view}', start_offset => INTERVAL '{start_offset}', "
        f"end_offset => INTERVAL '{end_offset}', schedule_interval => INTERVAL '{schedule}')",
        f"ALTER MATERIALIZED VIEW {view} SET (timescaledb.compress = true)",
        f"SELECT add_compression_policy('{view}', compress_after => INTERVAL '{compress_after}')",
    ]
    if drop_after:
        forward.append(f"SELECT add_retention_policy('{view}', drop_after => INTERVAL '{drop_after}')")
    backward = [f"SELECT remove_retention_policy('{view}', if_exists => true)",
                f"SELECT remove_compression_policy('{view}', if_exists => true)",
                f"SELECT remove_continuous_aggregate_policy('{view}', if_exists => true)"]
    return [migrations.RunSQL(sql, reverse_sql=migrations.RunSQL.noop) for sql in forward[:-1]] + [
        migrations.RunSQL(forward[-1], reverse_sql=backward)]


class Migration(migrations.Migration):
    atomic = False

    dependencies = [('sensors', '0002_readings')]

    operations = [
        migrations.RunSQL(MINUTE, reverse_sql='DROP MATERIALIZED VIEW IF EXISTS sensors_rollup_1m'),
        migrations.RunSQL(HOUR, reverse_sql='DROP MATERIALIZED VIEW IF EXISTS sensors_rollup_1h'),
        *policies('sensors_rollup_1m', MINUTE_WINDOW, '1 minute', '1 minute', '60 days', drop_after='730 days'),
        *policies('sensors_rollup_1h', HOUR_WINDOW, '1 hour', '1 hour', '90 days'),
        migrations.RunSQL(LATE_JOB, reverse_sql=LATE_JOB_BACK),
    ]
