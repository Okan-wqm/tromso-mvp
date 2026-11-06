"""`core_rev` (core.rev) and its functions. A tracked table's triggers (core.operations.TrackRev) call:
- core_rev_note(scope, key, day): remembers for the transaction that the key changed, and the earliest day; it writes
  nothing (a transaction-local setting per key, and the list of pending keys);
- core_rev_apply(): the deferred trigger's function; at COMMIT it calls core_rev_flush(), which applies the pending
  keys in sorted order, each once: `rev + 1` and `dirty_from = LEAST(dirty_from, day)`. A key seen for the first time
  starts above the floor row ('*', 0) a rebuild sets. A second note of a key already pending is skipped unless its day
  is earlier, so a 5,000-line operation writes one row per batch.
core_rev_mark_built(scope, key, rev0) is a builder's compare-and-set. The table is rewritten often: fillfactor 50 keeps
its updates HOT."""
from django.db import migrations, models

FUNCTIONS = r"""
CREATE FUNCTION core_rev_marker(p_scope text, p_key text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT 'core_rev.k_' || md5(p_scope || '|' || p_key)
$$;

CREATE FUNCTION core_rev_note(p_scope text, p_key text, p_day date) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    marker text := core_rev_marker(p_scope, p_key);
    seen text := coalesce(current_setting(marker, true), '');
    v_day text := coalesce(to_char(p_day, 'YYYY-MM-DD'), '');
BEGIN
    IF p_scope !~ '^[a-z_*]+$' OR p_key ~ '[|;]' THEN
        RAISE EXCEPTION 'core_rev: bad scope % or key %', p_scope, p_key;
    END IF;
    IF seen = '' OR (v_day <> '' AND (seen = '-' OR v_day < seen)) THEN
        PERFORM set_config(marker, CASE WHEN v_day = '' THEN '-' ELSE v_day END, true);
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
               min(to_date(nullif(split_part(e, '|', 3), ''), 'YYYY-MM-DD')) AS day
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

DROP = """
DROP FUNCTION IF EXISTS core_rev_mark_built(text, text, bigint);
DROP FUNCTION IF EXISTS core_rev_apply();
DROP FUNCTION IF EXISTS core_rev_flush();
DROP FUNCTION IF EXISTS core_rev_note(text, text, date);
DROP FUNCTION IF EXISTS core_rev_marker(text, text);
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_audit_severity'),
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
    ]
