from django.db import migrations


class Migration(migrations.Migration):
    """The event's own acknowledgement columns, carried over to the alarms app by 0007."""

    dependencies = [('sensors', '0008_alarm_acknowledgements_moved')]

    operations = [
        migrations.RemoveField(model_name='alarmevent', name='acknowledged_at'),
        migrations.RemoveField(model_name='alarmevent', name='acknowledged_by'),
    ]
