import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0004_system_alarms'),
    ]

    operations = [
        migrations.AlterField(
            model_name='alarmsubjectstate',
            name='open_alarm',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='alarms.alarm', verbose_name='Open alarm'),
        ),
    ]
