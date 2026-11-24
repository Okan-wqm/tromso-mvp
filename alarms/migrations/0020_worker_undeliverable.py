"""The alarm worker's row says how many critical notifications of open, unacknowledged alarms cannot be delivered
(alarms/outbox.py) and since when the oldest waits: the pages' notice and the health check read it (alarms/watch.py).
Back: the columns go."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0019_outbox_queue'),
    ]

    operations = [
        migrations.AddField(
            model_name='alarmworkerstatus',
            name='undeliverable',
            field=models.PositiveIntegerField(default=0, verbose_name='Critical notifications undeliverable'),
        ),
        migrations.AddField(
            model_name='alarmworkerstatus',
            name='undeliverable_since',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Undeliverable since'),
        ),
    ]
