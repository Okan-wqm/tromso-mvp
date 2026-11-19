"""Whether the unit's own value holds a water limit level (the verification of FIX3, F3-7; alarms/sources.py, which value
can end a level): a level the unit's own value raised ends only on the unit's own evidence, never on another point's
value. Every row starts false: the rows cannot say who raised a level open when this lands (the verification's F3-8:
marking them all true kept a level the loop raised for a unit without a sample of its own open after the loop
recovered), so the first pass works it out from the values it judges (alarms.sources._note_own: the unit's own value
holding the level sets it; read.last_own keeps a stale own value's status). Back: the column goes."""

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
    ]
