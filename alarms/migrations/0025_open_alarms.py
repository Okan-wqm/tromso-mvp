"""The open alarms' own queue (`alarm_open`, alarms.OpenAlarm): one row for each alarm that has not cleared, so what
reads the open alarms (the pass's notify step, its supervision of the criticals told to nobody, the sensor events'
mirror closing the alarms of closed events, the pages' floods, the open list, the overview's attention) reads what is
open, however long the history. Before it each of them asked "every alarm without a clearance", which reads every
alarm and every clearance ever recorded, on every pass of the worker with the owner's 10 s (review 1, F1;
core.testing.reads, alarms/tests/test_open_alarms.py). The mirror's other read, the sensor events no alarm mirrors
yet, has its own queue (alarms 0026).

The database keeps it, whoever writes (review 2, H2): a statement trigger on `alarms` adds the alarms it inserted that
have no clearance (a clearance may come first in one transaction: the keys are checked at its end), one on
`alarm_clearances` removes the alarms it cleared; both tables are append-only, so nothing else changes openness, and
raw SQL, a bulk insert or a fixture keep it as the services do. Both are core.operations.DefinerTrigger: their
functions run as their owner, so the app role needs no right on the table and has none (deploy/db/sql/grants.sql);
no other role may call them, they run for their own table only, and a table they name is always the public one.
`manage.py check --database default` compares the queue with "no clearance" both ways (alarms.W001).

One case the triggers cannot see (review 3, L1): a clearance written while the alarm it names is still uncommitted in
another transaction (raw SQL that knew the alarm's id in advance; the foreign keys are checked only at the commit)
finds no queue row to remove, and the alarm stays queued after both commit. No service writes that way: raw SQL that
writes alarms or clearances by an explicit id (a repair, a hand-made restore) runs with the alarm worker stopped
(docs/ops/database-roles.md), and alarms.W001 names an alarm left so, with its repair.

The triggers are made first, then the queue is filled (review 2, H1): CREATE TRIGGER waits for the writers of `alarms`
and `alarm_clearances` under way and keeps every later one out until this migration commits, so the fill sees every
alarm and clearance there is, and none is written between the two. Going back drops the triggers, their functions and
the table."""
import django.db.models.deletion
from django.db import migrations, models

from core.operations import DefinerTrigger, On

# After the triggers: every alarm without a clearance. ON CONFLICT: one the trigger has added since is not added twice.
FILL = """
INSERT INTO public.alarm_open (alarm_id)
SELECT a.id FROM public.alarms a WHERE NOT EXISTS (SELECT 1 FROM public.alarm_clearances c WHERE c.alarm_id = a.id)
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
        DefinerTrigger('alarm_open_opened', on=[On('alarms', 'trg_alarms_open', new_table='opened')], body="""
    INSERT INTO public.alarm_open (alarm_id) SELECT o.id FROM opened o
    WHERE NOT EXISTS (SELECT 1 FROM public.alarm_clearances c WHERE c.alarm_id = o.id);"""),
        DefinerTrigger('alarm_open_cleared', on=[On('alarm_clearances', 'trg_alarm_clearances_open',
                                                    new_table='cleared')], body="""
    DELETE FROM public.alarm_open o USING cleared c WHERE o.alarm_id = c.alarm_id;"""),
        migrations.RunSQL(FILL, migrations.RunSQL.noop),
    ]
