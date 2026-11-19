"""Whether the unit's own value holds a water limit level (the verification of FIX3, F3-7; alarms/sources.py, which value
can end a level): a level the unit's own value raised ends only on the unit's own evidence, never on another point's
value. The water levels open when this lands are taken as held by the unit's own value, the safe side (they end on the
unit's own evidence; the first pass whose own value is clear of them forgets it). Back: the column goes."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0013_phosphate'),
    ]

    operations = [
        migrations.AddField(
            model_name='alarmsubjectstate',
            name='own_held',
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.RunSQL(
            "UPDATE alarm_subject_state SET own_held = true WHERE open_alarm_id IS NOT NULL AND key LIKE 'water:%%'",
            migrations.RunSQL.noop,
        ),
    ]
