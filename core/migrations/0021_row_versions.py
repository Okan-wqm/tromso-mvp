"""`core_row_versions` (core.versions) and the functions a kept table's triggers call (core.operations.KeepVersions):
- core_row_version(key): an AFTER ROW trigger's function. A delete or an update closes the row's version open (its
  `valid_to`, the moment of the change: clock_timestamp(), never before the version's own start); an insert or an update
  opens the next, with the row's values whole (to_jsonb). `key` names the primary key's column;
- core_row_versions_truncated(): a TRUNCATE fires no row trigger, so the statement trigger closes every version open of
  its table.
Both run as their owner (SECURITY DEFINER, with a fixed search path), so the app's role keeps the versions although it
may not write them (deploy/db/sql/grants.sql): a page, a script or a compromise cannot rewrite what a row was."""
from django.db import migrations, models

FUNCTIONS = r"""
CREATE FUNCTION core_row_version() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
    at timestamptz := clock_timestamp();
    began timestamptz;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        UPDATE core_row_versions SET valid_to = GREATEST(at, valid_from)
         WHERE table_name = TG_TABLE_NAME AND row_id = to_jsonb(OLD) ->> TG_ARGV[0] AND valid_to IS NULL
        RETURNING valid_to INTO began;
        at := GREATEST(at, began);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        INSERT INTO core_row_versions (table_name, row_id, valid_from, data)
        VALUES (TG_TABLE_NAME, to_jsonb(NEW) ->> TG_ARGV[0], at, to_jsonb(NEW));
    END IF;
    RETURN NULL;
END
$$;

CREATE FUNCTION core_row_versions_truncated() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
BEGIN
    UPDATE core_row_versions SET valid_to = GREATEST(clock_timestamp(), valid_from)
     WHERE table_name = TG_TABLE_NAME AND valid_to IS NULL;
    RETURN NULL;
END
$$;
"""

DROP = """
DROP FUNCTION IF EXISTS core_row_versions_truncated();
DROP FUNCTION IF EXISTS core_row_version();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0020_production_plan_growth'),
    ]

    operations = [
        migrations.CreateModel(
            name='RowVersion',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('table_name', models.CharField(max_length=63, verbose_name='Table')),
                ('row_id', models.CharField(max_length=64, verbose_name='Row')),
                ('valid_from', models.DateTimeField(verbose_name='Valid from')),
                ('valid_to', models.DateTimeField(blank=True, null=True, verbose_name='Valid to')),
                ('data', models.JSONField(verbose_name='Values')),
            ],
            options={
                'verbose_name': 'row version',
                'verbose_name_plural': 'row versions',
                'db_table': 'core_row_versions',
                'indexes': [models.Index(fields=['table_name', 'row_id', 'valid_from'],
                                         name='idx_core_row_versions_row')],
                'constraints': [
                    models.CheckConstraint(condition=models.Q(('valid_to__isnull', True),
                                                              ('valid_to__gte', models.F('valid_from')),
                                                              _connector='OR'),
                                           name='chk_core_row_versions_span'),
                    models.UniqueConstraint(condition=models.Q(('valid_to__isnull', True)),
                                            fields=('table_name', 'row_id'), name='uq_core_row_versions_open'),
                ],
            },
        ),
        migrations.RunSQL(FUNCTIONS, DROP),
    ]
