import django.core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models

# The history of an alarm is never edited (alarms/models.py): one trigger function refuses UPDATE and DELETE on each of the
# six append-only tables, as core 0003 does for the activity log. TRUNCATE (the test runner's flush) is not a row trigger.
TABLES = ('alarms', 'alarm_clearances', 'alarm_notifications', 'alarm_delivery_attempts', 'alarm_escalations',
          'alarm_acknowledgements')
APPEND_ONLY = """
CREATE FUNCTION alarms_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: rows cannot be changed or deleted', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
""" + ''.join(f"""
CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table}
    FOR EACH ROW EXECUTE FUNCTION alarms_append_only();
""" for table in TABLES)
DROP = (''.join(f'DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}; ' for table in TABLES)
        + 'DROP FUNCTION IF EXISTS alarms_append_only();')


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('farm', '0026_production_form_other'),
        ('sensors', '0006_ingest_requests'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Alarm',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('source', models.CharField(choices=[('sensor_rule', 'Sensor alarm rule'), ('water_limit', 'Water limit')], max_length=12, verbose_name='Source')),
                ('parameter', models.CharField(blank=True, max_length=30, verbose_name='Parameter')),
                ('severity', models.CharField(choices=[('warning', 'Warning'), ('critical', 'Critical')], max_length=10, verbose_name='Severity')),
                ('opened_at', models.DateTimeField(db_index=True, verbose_name='Opened at')),
                ('summary', models.CharField(max_length=300, verbose_name='What')),
                ('point', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='alarms', to='farm.samplingpoint', verbose_name='Sampling point')),
                ('production_department', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='alarms', to='farm.productiondepartment', verbose_name='Production department')),
                ('sensor_event', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='alarm', to='sensors.alarmevent', verbose_name='Sensor alarm event')),
                ('site', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='alarms', to='farm.site', verbose_name='Site')),
            ],
            options={
                'verbose_name': 'alarm',
                'verbose_name_plural': 'alarms',
                'db_table': 'alarms',
                'ordering': ['-opened_at', '-id'],
            },
        ),
        migrations.CreateModel(
            name='AlarmClearance',
            fields=[
                ('alarm', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, primary_key=True, related_name='clearance', serialize=False, to='alarms.alarm', verbose_name='Alarm')),
                ('cleared_at', models.DateTimeField(verbose_name='Cleared at')),
            ],
            options={
                'verbose_name': 'alarm clearance',
                'verbose_name_plural': 'alarm clearances',
                'db_table': 'alarm_clearances',
            },
        ),
        migrations.CreateModel(
            name='Escalation',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('level', models.PositiveSmallIntegerField(verbose_name='Level')),
                ('escalated_at', models.DateTimeField(verbose_name='Escalated at')),
                ('alarm', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='escalations', to='alarms.alarm', verbose_name='Alarm')),
            ],
            options={
                'verbose_name': 'alarm escalation',
                'verbose_name_plural': 'alarm escalations',
                'db_table': 'alarm_escalations',
                'ordering': ['escalated_at', 'id'],
            },
        ),
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('channel', models.CharField(choices=[('push', 'Push')], max_length=10, verbose_name='Channel')),
                ('level', models.PositiveSmallIntegerField(verbose_name='Level')),
                ('queued_at', models.DateTimeField(verbose_name='Queued at')),
                ('alarm', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='notifications', to='alarms.alarm', verbose_name='Alarm')),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='alarm_notifications', to=settings.AUTH_USER_MODEL, verbose_name='Recipient')),
            ],
            options={
                'verbose_name': 'alarm notification',
                'verbose_name_plural': 'alarm notifications',
                'db_table': 'alarm_notifications',
                'ordering': ['queued_at', 'id'],
            },
        ),
        migrations.CreateModel(
            name='DeliveryAttempt',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('attempted_at', models.DateTimeField(verbose_name='Attempted at')),
                ('outcome', models.CharField(choices=[('sent', 'Sent'), ('failed', 'Failed')], max_length=10, verbose_name='Outcome')),
                ('detail', models.CharField(blank=True, max_length=300, verbose_name='Detail')),
                ('notification', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='attempts', to='alarms.notification', verbose_name='Notification')),
            ],
            options={
                'verbose_name': 'alarm delivery attempt',
                'verbose_name_plural': 'alarm delivery attempts',
                'db_table': 'alarm_delivery_attempts',
                'ordering': ['attempted_at', 'id'],
            },
        ),
        migrations.CreateModel(
            name='Acknowledgement',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('acknowledged_at', models.DateTimeField(verbose_name='Acknowledged at')),
                ('device', models.CharField(blank=True, max_length=100, verbose_name='Device')),
                ('app', models.CharField(max_length=100, verbose_name='App')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='alarm_acknowledgements', to=settings.AUTH_USER_MODEL, verbose_name='Acknowledged by')),
                ('alarm', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='acknowledgements', to='alarms.alarm', verbose_name='Alarm')),
                ('notification', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='acknowledgements', to='alarms.notification', verbose_name='Notification answered')),
            ],
            options={
                'verbose_name': 'alarm acknowledgement',
                'verbose_name_plural': 'alarm acknowledgements',
                'db_table': 'alarm_acknowledgements',
                'ordering': ['acknowledged_at', 'id'],
            },
        ),
        migrations.CreateModel(
            name='RecipientRule',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('min_severity', models.CharField(choices=[('warning', 'Warning'), ('critical', 'Critical')], default='warning', max_length=10, verbose_name='At least')),
                ('level', models.PositiveSmallIntegerField(default=0, validators=[django.core.validators.MaxValueValidator(9)], verbose_name='Level')),
                ('on_shift_only', models.BooleanField(default=False, verbose_name='Only while on shift')),
                ('channel', models.CharField(choices=[('push', 'Push')], default='push', max_length=10, verbose_name='Channel')),
                ('is_active', models.BooleanField(default=True, verbose_name='Active')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('production_department', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='alarm_recipients', to='farm.productiondepartment', verbose_name='Production department')),
                ('role', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='alarm_rules', to='auth.group', verbose_name='Role')),
                ('site', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='alarm_recipients', to='farm.site', verbose_name='Site')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='alarm_rules', to=settings.AUTH_USER_MODEL, verbose_name='Person')),
            ],
            options={
                'verbose_name': 'alarm recipient rule',
                'verbose_name_plural': 'alarm recipient rules',
                'db_table': 'alarm_recipient_rules',
                'ordering': ['level', 'site__name', 'production_department__name'],
            },
        ),
        migrations.AddField(
            model_name='notification',
            name='rule',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='notifications', to='alarms.recipientrule', verbose_name='Recipient rule'),
        ),
        migrations.AddConstraint(
            model_name='alarm',
            constraint=models.CheckConstraint(condition=models.Q(('source__in', ['sensor_rule', 'water_limit'])), name='chk_alarms_source'),
        ),
        migrations.AddConstraint(
            model_name='alarm',
            constraint=models.CheckConstraint(condition=models.Q(('severity__in', ['warning', 'critical'])), name='chk_alarms_severity'),
        ),
        migrations.AddConstraint(
            model_name='alarm',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('parameter', ''), ('point__isnull', True), ('sensor_event__isnull', False), ('source', 'sensor_rule')), models.Q(('point__isnull', False), ('sensor_event__isnull', True), ('source', 'water_limit'), models.Q(('parameter', ''), _negated=True)), _connector='OR'), name='chk_alarms_shape'),
        ),
        migrations.AddConstraint(
            model_name='escalation',
            constraint=models.UniqueConstraint(fields=('alarm', 'level'), name='uq_alarm_escalations_level'),
        ),
        migrations.AddConstraint(
            model_name='escalation',
            constraint=models.CheckConstraint(condition=models.Q(('level__gte', 1), ('level__lte', 9)), name='chk_alarm_escalations_level'),
        ),
        migrations.AddConstraint(
            model_name='deliveryattempt',
            constraint=models.CheckConstraint(condition=models.Q(('outcome__in', ['sent', 'failed'])), name='chk_alarm_delivery_attempts_outcome'),
        ),
        migrations.AddConstraint(
            model_name='deliveryattempt',
            constraint=models.UniqueConstraint(condition=models.Q(('outcome', 'sent')), fields=('notification',), name='uq_alarm_delivery_attempts_sent_once'),
        ),
        migrations.AddConstraint(
            model_name='acknowledgement',
            constraint=models.UniqueConstraint(fields=('alarm', 'user'), name='uq_alarm_acknowledgements_once'),
        ),
        migrations.AddConstraint(
            model_name='acknowledgement',
            constraint=models.CheckConstraint(condition=models.Q(('app', ''), _negated=True), name='chk_alarm_acknowledgements_app'),
        ),
        migrations.AddConstraint(
            model_name='recipientrule',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('role__isnull', False), ('user__isnull', True)), models.Q(('role__isnull', True), ('user__isnull', False)), _connector='OR'), name='chk_alarm_recipient_rules_who', violation_error_message='Choose a role or a person.'),
        ),
        migrations.AddConstraint(
            model_name='recipientrule',
            constraint=models.CheckConstraint(condition=models.Q(('level__lte', 9)), name='chk_alarm_recipient_rules_level'),
        ),
        migrations.AddConstraint(
            model_name='recipientrule',
            constraint=models.CheckConstraint(condition=models.Q(('min_severity__in', ['warning', 'critical'])), name='chk_alarm_recipient_rules_severity'),
        ),
        migrations.AddConstraint(
            model_name='recipientrule',
            constraint=models.CheckConstraint(condition=models.Q(('channel__in', ['push'])), name='chk_alarm_recipient_rules_channel'),
        ),
        migrations.AddConstraint(
            model_name='notification',
            constraint=models.UniqueConstraint(fields=('alarm', 'recipient', 'channel', 'level'), name='uq_alarm_notifications_once'),
        ),
        migrations.AddConstraint(
            model_name='notification',
            constraint=models.CheckConstraint(condition=models.Q(('channel__in', ['push'])), name='chk_alarm_notifications_channel'),
        ),
        migrations.AddConstraint(
            model_name='notification',
            constraint=models.CheckConstraint(condition=models.Q(('level__lte', 9)), name='chk_alarm_notifications_level'),
        ),
        migrations.RunSQL(APPEND_ONLY, reverse_sql=DROP),
    ]
