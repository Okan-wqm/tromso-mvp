"""The open alarms' own queue (`alarm_open`, alarms.OpenAlarm): one row for each alarm that has not cleared, so what
reads the open alarms (the pass's notify step and its supervision, the sensor events' mirror, the pages' floods, the
open list, the overview's attention) reads what is open, however long the history. Before it each of them asked
"every alarm without a clearance", which reads every alarm and every clearance ever recorded, on every pass of the
worker with the owner's 10 s (review 1, F1; core.testing.reads, alarms/tests/test_open_alarms.py).

The database keeps it, whoever writes: a statement trigger on `alarms` adds the alarms it inserted, one on
`alarm_clearances` removes the ones it cleared (both tables are append-only, so nothing else changes openness), and
raw SQL, a bulk insert or a fixture keep it as the services do. Filled here with every alarm that has no clearance.
Going back drops the triggers, their functions and the table."""
import django.db.models.deletion
from django.db import migrations, models

FILL = """
INSERT INTO alarm_open (alarm_id)
SELECT a.id FROM alarms a WHERE NOT EXISTS (SELECT 1 FROM alarm_clearances c WHERE c.alarm_id = a.id)
"""

TRIGGERS = """
CREATE FUNCTION alarm_open_opened() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO alarm_open (alarm_id) SELECT id FROM opened ON CONFLICT DO NOTHING;
    RETURN NULL;
END $$;
CREATE TRIGGER trg_alarms_open AFTER INSERT ON alarms REFERENCING NEW TABLE AS opened
    FOR EACH STATEMENT EXECUTE FUNCTION alarm_open_opened();
CREATE FUNCTION alarm_open_cleared() RETURNS trigger LANGUAGE plpgsql AS $$
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
        migrations.RunSQL(FILL, migrations.RunSQL.noop),
        migrations.RunSQL(TRIGGERS, DROP),
    ]
