"""`core_rev` (core.rev) and its functions. A tracked table's triggers (core.operations.TrackRev) call:
- core_rev_note(scope, key, day): remembers for the transaction that the key changed, and the earliest day; it writes
  nothing (a transaction-local setting per key, and the list of pending keys). A change without a day (a table-level
  scope, a sample of a point) counts for the whole history: 0001-01-01 (core.rev.EVERYTHING);
- core_rev_apply(): the deferred trigger's function; at COMMIT it calls core_rev_flush(), which applies the pending
  keys in sorted order, each once: `rev + 1` and `dirty_from = LEAST(dirty_from, day)`. A key seen for the first time
  starts above the floor row ('*', 0) a rebuild sets. A second note of a key already pending is skipped unless its day
  is earlier, so a 5,000-line operation writes one row per key;
- core_rev_truncated(): a TRUNCATE fires no row trigger, so the statement trigger moves every key of its scope at once.
core_rev_ensure(scopes, keys) gives every key without a row one (the key's history unknown: its day the whole history),
above the floor, in sorted order; a key with a row is left as it is. The farm's and the sensors' migrations call it for
the keys that exist when they add their triggers, so a stored figure can be stamped for any key, touched or not.
core_rev_mark_built(scope, key, rev0) is a builder's compare-and-set. The table is rewritten often: fillfactor 50 keeps
its updates HOT.

The platform settings are one of the inputs of the water's judgement (the clock tolerance, farm/water/freshness.py):
their table is tracked here, as scope 'platform_settings'; the farm's and the sensors' tables are tracked by their own
apps' migrations (farm 0050, sensors 0014)."""
from django.db import migrations, models

from core.operations import TrackRev

FUNCTIONS = r"""
CREATE FUNCTION core_rev_marker(p_scope text, p_key text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT 'core_rev.k_' || md5(p_scope || '|' || p_key)
$$;

CREATE FUNCTION core_rev_note(p_scope text, p_key text, p_day date) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    marker text := core_rev_marker(p_scope, p_key);
    seen text := coalesce(current_setting(marker, true), '');
    v_day text := to_char(coalesce(p_day, DATE '0001-01-01'), 'YYYY-MM-DD');
BEGIN
    IF p_scope !~ '^[a-z_*]+$' OR p_key ~ '[|;]' THEN
        RAISE EXCEPTION 'core_rev: bad scope % or key %', p_scope, p_key;
    END IF;
    IF seen = '' OR v_day < seen THEN
        PERFORM set_config(marker, v_day, true);
        PERFORM set_config('core_rev.pending', coalesce(current_setting('core_rev.pending', true), '')
                           || p_scope || '|' || p_key || '|' || v_day || ';', true);
    END IF;
END
$$;

CREATE FUNCTION core_rev_flush() RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    pending text := coalesce(current_setting('core_rev.pending', true), '');
    r record;
BEGIN
    IF pending = '' THEN
        RETURN;
    END IF;
    PERFORM set_config('core_rev.pending', '', true);
    FOR r IN
        SELECT split_part(e, '|', 1) AS scope, split_part(e, '|', 2) AS key,
               min(to_date(split_part(e, '|', 3), 'YYYY-MM-DD')) AS day
        FROM unnest(string_to_array(pending, ';')) AS e
        WHERE e <> ''
        GROUP BY 1, 2
        ORDER BY 1, 2
    LOOP
        PERFORM set_config(core_rev_marker(r.scope, r.key), '', true);
        INSERT INTO core_rev AS c (scope, key, rev, dirty_epoch, dirty_from)
        VALUES (r.scope, r.key, coalesce((SELECT f.rev FROM core_rev f WHERE f.scope = '*' AND f.key = '0'), 0) + 1, 0,
                r.day)
        ON CONFLICT (scope, key) DO UPDATE SET rev = c.rev + 1, dirty_from = LEAST(c.dirty_from, EXCLUDED.dirty_from);
    END LOOP;
END
$$;

CREATE FUNCTION core_rev_apply() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM core_rev_flush();
    RETURN NULL;
END
$$;

CREATE FUNCTION core_rev_truncated() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- locked in key order, as a flush locks them
    PERFORM 1 FROM core_rev WHERE scope = TG_ARGV[0] ORDER BY key FOR UPDATE;
    UPDATE core_rev SET rev = rev + 1, dirty_from = DATE '0001-01-01' WHERE scope = TG_ARGV[0];
    RETURN NULL;
END
$$;

CREATE FUNCTION core_rev_ensure(p_scopes text[], p_keys text[]) RETURNS integer LANGUAGE sql AS $$
    WITH made AS (
        INSERT INTO core_rev (scope, key, rev, dirty_epoch, dirty_from)
        SELECT u.scope, u.key, coalesce((SELECT f.rev FROM core_rev f WHERE f.scope = '*' AND f.key = '0'), 0) + 1, 0,
               DATE '0001-01-01'
        FROM (SELECT DISTINCT * FROM unnest(p_scopes, p_keys) AS u(scope, key)) AS u
        ORDER BY 1, 2
        ON CONFLICT (scope, key) DO NOTHING
        RETURNING 1
    )
    SELECT count(*)::integer FROM made
$$;

CREATE FUNCTION core_rev_mark_built(p_scope text, p_key text, p_rev bigint) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
    done boolean;
BEGIN
    PERFORM set_config(core_rev_marker(p_scope, p_key), '', true);
    UPDATE core_rev SET dirty_epoch = p_rev, dirty_from = NULL WHERE scope = p_scope AND key = p_key AND rev = p_rev;
    GET DIAGNOSTICS done = ROW_COUNT;
    RETURN done;
END
$$;
"""

# The keys that exist now get a row (core_rev_ensure): the platform settings' table.
BACKFILL = "SELECT core_rev_ensure(ARRAY['platform_settings'], ARRAY['0'])"

DROP = """
DROP FUNCTION IF EXISTS core_rev_mark_built(text, text, bigint);
DROP FUNCTION IF EXISTS core_rev_ensure(text[], text[]);
DROP FUNCTION IF EXISTS core_rev_truncated();
DROP FUNCTION IF EXISTS core_rev_apply();
DROP FUNCTION IF EXISTS core_rev_flush();
DROP FUNCTION IF EXISTS core_rev_note(text, text, date);
DROP FUNCTION IF EXISTS core_rev_marker(text, text);
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_unknown_withdrawal_ceiling'),
    ]

    operations = [
        migrations.CreateModel(
            name='Rev',
            fields=[
                ('pk', models.CompositePrimaryKey('scope', 'key', blank=True, editable=False, primary_key=True,
                                                  serialize=False)),
                ('scope', models.CharField(max_length=40)),
                ('key', models.CharField(max_length=64, db_default='0')),
                ('rev', models.BigIntegerField(db_default=0)),
                ('dirty_epoch', models.BigIntegerField(db_default=0)),
                ('dirty_from', models.DateField(null=True)),
            ],
            options={
                'db_table': 'core_rev',
                'constraints': [models.CheckConstraint(condition=models.Q(('rev__gte', 0)), name='chk_core_rev_rev')],
            },
        ),
        migrations.RunSQL('ALTER TABLE core_rev SET (fillfactor = 50)', 'ALTER TABLE core_rev RESET (fillfactor)'),
        migrations.RunSQL(FUNCTIONS, DROP),
        TrackRev('platform_settings', 'platform_settings'),
        migrations.RunSQL(BACKFILL, migrations.RunSQL.noop),
    ]
