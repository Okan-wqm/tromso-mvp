-- Two years of readings for :channels channels at one row per minute (a 1 Hz channel stored by its 60 s heartbeat:
-- each row closes a run of 60 samples), written straight into a freshly migrated database (sensors_bench), then
-- compressed and rolled up as the policies would, and the read paths timed. Run by bench/run.sh twoyears.
\set ON_ERROR_STOP on
\timing on
-- latest values of 500 channels come from the state table only
INSERT INTO sensors_channel_state (channel_no, last_seen_at, last_good_at, last_value, last_value_ts, last_quality, high_ts)
SELECT c, now(), now(), 10, now(), 0, now() FROM generate_series(1, 500) c;

\echo == generate
INSERT INTO sensors_reading (channel_no, ts, value, n, quality, run_sum, run_min, run_max)
SELECT c, ts, v, 60, 0, v * 60, v - 0.05, v + 0.05
FROM generate_series(1, :channels) c,
     generate_series(date_trunc('minute', now()) - interval '730 days', date_trunc('minute', now()), interval '1 minute') ts,
     LATERAL (SELECT round((10 + 2 * sin(extract(epoch FROM ts) / 86400.0 * 2 * pi()) + c * 0.1
                           + (random() - 0.5) * 0.2)::numeric, 3)::float8 AS v) x;
SELECT 'raw rows', count(*) FROM sensors_reading;
SELECT 'raw size before compression', pg_size_pretty(hypertable_size('sensors_reading'));

\echo == compress (chunks older than 14 days, as the policy)
SELECT count(compress_chunk(ch, if_not_compressed => true)) AS chunks_compressed
FROM show_chunks('sensors_reading', older_than => now() - interval '14 days') ch;
SELECT 'raw size after compression', pg_size_pretty(hypertable_size('sensors_reading')),
       round(sum(before_compression_total_bytes)::numeric / nullif(sum(after_compression_total_bytes), 0), 1) AS ratio
FROM chunk_compression_stats('sensors_reading');

\echo == roll up (the refresh policies, whole range)
CALL refresh_continuous_aggregate('sensors_rollup_1m', NULL, now() - interval '1 minute');
CALL refresh_continuous_aggregate('sensors_rollup_1h', NULL, now() - interval '1 hour');
SELECT '1m rows', count(*) FROM sensors_rollup_1m;
SELECT '1h rows', count(*) FROM sensors_rollup_1h;
SELECT '1m rows / raw rows (plan gate 40 %)',
       round(100.0 * (SELECT count(*) FROM sensors_rollup_1m) / (SELECT count(*) FROM sensors_reading), 1);
ANALYZE;

\echo == q1: one channel, two years, local days from the 1 h tier
SELECT count(*) FROM (
  SELECT time_bucket('1 day', bucket, 'Europe/Oslo') d, sum(sum_v) / sum(n), min(vmin), max(vmax)
  FROM sensors_rollup_1h WHERE channel_no = 1 AND bucket >= now() - interval '730 days' GROUP BY d) q;
\echo == q2: ten channels, seven days, 15 minute buckets from the 1 m tier
SELECT count(*) FROM (
  SELECT channel_no, time_bucket('15 minutes', bucket) b, sum(sum_v) / sum(n), min(vmin), max(vmax)
  FROM sensors_rollup_1m WHERE channel_no BETWEEN 1 AND 10 AND bucket >= now() - interval '7 days' GROUP BY 1, 2) q;
\echo == q3: latest of 500 channels (state table)
SELECT count(*) FROM sensors_channel_state WHERE channel_no = ANY (ARRAY(SELECT generate_series(1, 500)));
\echo == q4: value at a moment a year ago (step-after, inside a compressed chunk)
SELECT ts, value FROM sensors_reading WHERE channel_no = 3 AND ts <= now() - interval '365 days' ORDER BY ts DESC LIMIT 1;
\echo == q5: one channel, one day of raw rows a year ago (compressed)
SELECT count(*) FROM sensors_reading WHERE channel_no = 5
  AND ts >= now() - interval '366 days' AND ts < now() - interval '365 days';
