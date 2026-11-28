"""The open alarms' own queue (`alarm_open`, alarms.OpenAlarm): one row for each alarm that has not cleared, so what
reads the open alarms (the pass's notify step, its supervision of the criticals told to nobody, the sensor events'
mirror, the pages' floods, the open list, the overview's attention) reads what is open, however long the history.
Before it each of them asked "every alarm without a clearance", which reads every alarm and every clearance ever
recorded, on every pass of the worker with the owner's 10 s (review 1, F1; core.testing.reads,
alarms/tests/test_open_alarms.py).

The database keeps it, whoever writes (review 2, H2): a statement trigger on `alarms` adds the alarms it inserted that
have no clearance (a clearance may come first in one transaction: the keys are checked at its end), one on
`alarm_clearances` removes the alarms it cleared; both tables are append-only, so nothing else changes openness, and
raw SQL, a bulk insert or a fixture keep it as the services do. The two functions run as their owner (SECURITY
DEFINER), so the app role needs no right on the table and has none (deploy/db/sql/grants.sql): only they write it.
`manage.py check --database default` compares it with "no clearance" both ways (alarms.W001).

The triggers are made first, then the queue is filled (review 2, H1): CREATE TRIGGER waits for the writers of `alarms`
and `alarm_clearances` under way and keeps every later one out until this migration commits, so the fill sees every
alarm and clearance there is, and none is written between the two. Going back drops the triggers, their functions and
the table."""
import django.db.models.deletion
from django.db import migrations, models

TRIGGERS = """
CREATE FUNCTION alarm_open_opened() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = public, pg_catalog AS $$
BEGIN
    INSERT INTO alarm_open (alarm_id) SELECT o.id FROM opened o
    WHERE NOT EXISTS (SELECT 1 FROM alarm_clearances c WHERE c.alarm_id = o.id);
    RETURN NULL;
END $$;
CREATE TRIGGER trg_alarms_open AFTER INSERT ON alarms REFERENCING NEW TABLE AS opened
    FOR EACH STATEMENT EXECUTE FUNCTION alarm_open_opened();
CREATE FUNCTION alarm_open_cleared() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = public, pg_catalog AS $$
BEGIN
    DELETE FROM alarm_open o USING cleared c WHERE o.alarm_id = c.alarm_id;
    RETURN NULL;
END $$;
CREATE TRIGGER trg_alarm_clearances_open AFTER INSERT ON alarm_clearances REFERENCING NEW TABLE AS cleared
    FOR EACH STATEMENT EXECUTE FUNCTION alarm_open_cleared();
"""

DROP = """
DROP TRIGGER IF EXISTS trg_alarm_clearances_open ON alarm_clearances;
DROP FUNCTION IF EXISTS alarm_open_cleared();
DROP TRIGGER IF EXISTS trg_alarms_open ON alarms;
DROP FUNCTION IF EXISTS alarm_open_opened();
"""

# After the triggers: every alarm without a clearance. ON CONFLICT: one the trigger has added since is not added twice.
FILL = """
INSERT INTO alarm_open (alarm_id)
SELECT a.id FROM alarms a WHERE NOT EXISTS (SELECT 1 FROM alarm_clearances c WHERE c.alarm_id = a.id)
ON CONFLICT DO NOTHING
"""


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0024_attempts_sent_at_index'),
    ]

    operations = [
        migrations.CreateModel(
            name='OpenAlarm',
            fields=[
                ('alarm', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='open_entry', serialize=False, to='alarms.alarm', verbose_name='Alarm')),
            ],
            options={
                'verbose_name': 'open alarm',
                'verbose_name_plural': 'open alarms',
                'db_table': 'alarm_open',
            },
        ),
        migrations.RunSQL(TRIGGERS, DROP),
        migrations.RunSQL(FILL, migrations.RunSQL.noop),
    ]
