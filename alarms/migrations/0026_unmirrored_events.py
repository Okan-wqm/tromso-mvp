"""The sensor events no alarm mirrors yet, in their own queue (`alarm_unmirrored_events`, alarms.UnmirroredEvent; review
3, M1): the pass's mirror (alarms/sources.py `sensor_events`) asked "every sensor event without an alarm", which reads
every sensor alarm event and every alarm's link to one ever recorded, on every pass of the worker with the owner's 10 s.
It now reads the queue, so a whole pass reads what is open and what is still to mirror, however long the history
(alarms/tests/test_open_alarms.py, with the sensor events in the history).

The database keeps it, whoever writes, as alarms 0025 keeps the open alarms: a statement trigger on
`sensors_alarm_event` adds the events it inserted that no alarm names (an alarm may come first in one transaction: the
keys are checked at its end), one on `alarms` removes the events its alarms mirror, and one on `sensors_alarm_event`
removes the events deleted (none are: an event is its alarm's history; the queue's link does nothing of its own). An
alarm never changes its event, so nothing else changes what is mirrored. The three are core.operations.DefinerTrigger:
the app role needs no right on the table and has none (deploy/db/sql/grants.sql). `manage.py check --database default`
compares the queue with "no alarm" both ways (alarms.W002); the case of alarms 0025's docstring (a row written while
the one it names is uncommitted in another transaction, by raw SQL with an explicit id) is the same here, and W002
names it.

The triggers are made first, then the queue is filled, for the reason 0025 gives. Going back drops the triggers, their
functions and the table."""
import django.db.models.deletion
from django.db import migrations, models

from core.operations import DefinerTrigger, On

# After the triggers: every event no alarm names. ON CONFLICT: one the trigger has added since is not added twice.
FILL = """
INSERT INTO public.alarm_unmirrored_events (event_id)
SELECT e.id FROM public.sensors_alarm_event e
WHERE NOT EXISTS (SELECT 1 FROM public.alarms a WHERE a.sensor_event_id = e.id)
ON CONFLICT DO NOTHING
"""


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0025_open_alarms'),
    ]

    operations = [
        migrations.CreateModel(
            name='UnmirroredEvent',
            fields=[
                ('event', models.OneToOneField(on_delete=django.db.models.deletion.DO_NOTHING, primary_key=True, related_name='unmirrored', serialize=False, to='sensors.alarmevent', verbose_name='Sensor alarm event')),
            ],
            options={
                'verbose_name': 'sensor event to mirror',
                'verbose_name_plural': 'sensor events to mirror',
                'db_table': 'alarm_unmirrored_events',
            },
        ),
        DefinerTrigger('alarm_unmirrored_written', on=[On('sensors_alarm_event', 'trg_sensors_alarm_event_unmirrored',
                                                          new_table='written')], body="""
    INSERT INTO public.alarm_unmirrored_events (event_id) SELECT w.id FROM written w
    WHERE NOT EXISTS (SELECT 1 FROM public.alarms a WHERE a.sensor_event_id = w.id);"""),
        DefinerTrigger('alarm_unmirrored_mirrored', on=[On('alarms', 'trg_alarms_mirrored', new_table='mirrored')],
                       body="""
    DELETE FROM public.alarm_unmirrored_events u USING mirrored m WHERE u.event_id = m.sensor_event_id;"""),
        DefinerTrigger('alarm_unmirrored_deleted', on=[On('sensors_alarm_event', 'trg_sensors_alarm_event_deleted',
                                                          events=('DELETE',), old_table='deleted')], body="""
    DELETE FROM public.alarm_unmirrored_events u USING deleted d WHERE u.event_id = d.id;"""),
        migrations.RunSQL(FILL, migrations.RunSQL.noop),
    ]
