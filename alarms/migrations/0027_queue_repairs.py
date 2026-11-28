"""The repairs of the alarms' two queues (`alarm_queue_repairs`, alarms.AlarmQueueRepair; review 3 follow-up): the alarm
worker checks both queues on its schedule (alarms/worker.py QUEUE_CHECK_EVERY, the check of alarms.W001 and W002) and,
when one is out of step, writes a row here. Its trigger repairs both from what they stand for, as the database's owner
(a core.operations.DefinerTrigger), with exactly the statements W001 and W002 print, so the app role, which may not
write the queues (deploy/db/sql/grants.sql), repairs them without a right on them and without a function of its own to
call. Each statement only adds what is missing or removes what is wrong, so a repair written when nothing is out of
step changes nothing. Going back drops the trigger, its function and the table."""
from django.db import migrations, models

from core.operations import DefinerTrigger, On

REPAIR = """
    INSERT INTO public.alarm_open (alarm_id) SELECT a.id FROM public.alarms a WHERE NOT EXISTS (SELECT 1 FROM public.alarm_clearances c WHERE c.alarm_id = a.id) ON CONFLICT DO NOTHING;
    DELETE FROM public.alarm_open o USING public.alarm_clearances c WHERE c.alarm_id = o.alarm_id;
    INSERT INTO public.alarm_unmirrored_events (event_id) SELECT e.id FROM public.sensors_alarm_event e WHERE NOT EXISTS (SELECT 1 FROM public.alarms a WHERE a.sensor_event_id = e.id) ON CONFLICT DO NOTHING;
    DELETE FROM public.alarm_unmirrored_events u USING public.alarms a WHERE a.sensor_event_id = u.event_id;"""


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0026_unmirrored_events'),
    ]

    operations = [
        migrations.CreateModel(
            name='AlarmQueueRepair',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('repaired_at', models.DateTimeField(verbose_name='Repaired at')),
                ('rows_repaired', models.PositiveIntegerField(verbose_name='Rows repaired')),
                ('found', models.CharField(max_length=300, verbose_name='What was out of step')),
            ],
            options={
                'verbose_name': 'alarm queue repair',
                'verbose_name_plural': 'alarm queue repairs',
                'db_table': 'alarm_queue_repairs',
                'constraints': [models.CheckConstraint(condition=models.Q(('rows_repaired__gte', 1)), name='chk_alarm_queue_repairs_rows')],
            },
        ),
        DefinerTrigger('alarm_queues_repair', REPAIR, [On('alarm_queue_repairs', 'trg_alarm_queue_repairs_repair')]),
    ]
