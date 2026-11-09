"""The clearance causes "the water limit was removed" (cross review F12; the column grows to hold it), and the cause of
the sensor events carried in by sensors 0008 (cross review F13): an event the sensors' check had closed was cleared with
the column's default, "back inside the limit"; it is "the sensor rule no longer holds". The clearances are append-only,
so their trigger is set aside for that one statement, in this migration's transaction, and set back."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0008_severity_bounds'),
        ('sensors', '0009_alarm_event_acknowledgement_columns_removed'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='alarmclearance',
            name='chk_alarm_clearances_cause',
        ),
        migrations.AlterField(
            model_name='alarmclearance',
            name='cause',
            field=models.CharField(choices=[('returned', 'Back inside the limit'), ('event_closed', 'The sensor rule no longer holds'), ('structural', 'No fish in the unit any more'), ('limit_removed', 'The water limit was removed'), ('restored', 'Restored'), ('unit_removed', 'The unit was removed'), ('merged', 'Merged into the unit’s one alarm of that level')], default='returned', max_length=20, verbose_name='Why'),
        ),
        migrations.AddConstraint(
            model_name='alarmclearance',
            constraint=models.CheckConstraint(condition=models.Q(('cause__in', ['returned', 'event_closed', 'structural', 'limit_removed', 'restored', 'unit_removed', 'merged'])), name='chk_alarm_clearances_cause'),
        ),
        migrations.RunSQL(
            "ALTER TABLE alarm_clearances DISABLE TRIGGER trg_alarm_clearances_append_only; "
            "UPDATE alarm_clearances SET cause = 'event_closed' WHERE cause = 'returned' "
            "AND alarm_id IN (SELECT id FROM alarms WHERE source = 'sensor_rule'); "
            "ALTER TABLE alarm_clearances ENABLE TRIGGER trg_alarm_clearances_append_only;",
            reverse_sql=migrations.RunSQL.noop),
    ]
