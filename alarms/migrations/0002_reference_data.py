import django.core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


# The owner's defaults (alarm plan §7a, Q3, Q4, Q7), written once as the user's rows: from here on they are the user's to
# change (Company › Alarms), never the code's. (severity, raise after s, clear after s, escalate after min, attempts)
POLICIES = [('critical', 0, 30, 5, 5), ('warning', 30, 30, 30, 5)]
DEADBANDS = [('oxygen_mg_l', '0.2'), ('oxygen_saturation_pct', '2'), ('temperature_c', '0.3'), ('ph', '0.05'),
             ('co2_mg_l', '1'), ('tan_mg_l', '0.05'), ('nh3_n_mg_l', '0.002'), ('nitrite_n_mg_l', '0.05'),
             ('salinity_ppt', '0.5')]


def seed(apps, schema_editor):
    from decimal import Decimal
    Policy = apps.get_model('alarms', 'SeverityPolicy')
    Deadband = apps.get_model('alarms', 'ParameterDeadband')
    for severity, on_delay, off_delay, escalation, attempts in POLICIES:
        Policy.objects.get_or_create(severity=severity, defaults={
            'on_delay_seconds': on_delay, 'off_delay_seconds': off_delay, 'escalation_minutes': escalation,
            'delivery_attempts': attempts})
    for parameter, deadband in DEADBANDS:
        Deadband.objects.get_or_create(parameter=parameter, is_deleted=False, defaults={'deadband': Decimal(deadband)})


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ParameterDeadband',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('parameter', models.CharField(choices=[('temperature_c', 'Temperature (°C)'), ('oxygen_mg_l', 'Dissolved oxygen (mg/L O₂)'), ('oxygen_saturation_pct', 'Oxygen saturation (% of air saturation)'), ('ph', 'pH (NBS scale)'), ('alkalinity_mg_l', 'Alkalinity (mg/L as CaCO₃)'), ('co2_mg_l', 'Carbon dioxide (mg/L free CO₂)'), ('tan_mg_l', 'Total ammonia nitrogen (mg/L TAN as N)'), ('nitrite_n_mg_l', 'Nitrite (mg/L NO₂ as N)'), ('nitrate_n_mg_l', 'Nitrate (mg/L NO₃ as N)'), ('tgp_pct', 'Total gas pressure (% of barometric pressure)'), ('salinity_ppt', 'Salinity (‰, g/kg)'), ('turbidity_ntu', 'Turbidity (NTU)'), ('nh3_n_mg_l', 'Un-ionised ammonia (mg/L NH₃ as N)')], max_length=30, verbose_name='Parameter')),
                ('deadband', models.DecimalField(decimal_places=4, max_digits=8, verbose_name='Deadband')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
            options={
                'verbose_name': 'alarm deadband',
                'verbose_name_plural': 'alarm deadbands',
                'db_table': 'alarm_deadbands',
                'ordering': ['parameter'],
                'constraints': [models.UniqueConstraint(condition=models.Q(('is_deleted', False)), fields=('parameter',), name='uq_alarm_deadbands_parameter_live', violation_error_message='This parameter has a deadband already.'), models.CheckConstraint(condition=models.Q(('parameter__in', ['temperature_c', 'oxygen_mg_l', 'oxygen_saturation_pct', 'ph', 'alkalinity_mg_l', 'co2_mg_l', 'tan_mg_l', 'nitrite_n_mg_l', 'nitrate_n_mg_l', 'tgp_pct', 'salinity_ppt', 'turbidity_ntu', 'nh3_n_mg_l'])), name='chk_alarm_deadbands_parameter'), models.CheckConstraint(condition=models.Q(('deadband__gte', 0)), name='chk_alarm_deadbands_not_negative', violation_error_message='A deadband is not negative.')],
            },
        ),
        migrations.CreateModel(
            name='SeverityPolicy',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('severity', models.CharField(choices=[('warning', 'Warning'), ('critical', 'Critical')], editable=False, max_length=10, verbose_name='Severity')),
                ('on_delay_seconds', models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(3600)], verbose_name='Raise after (seconds)')),
                ('off_delay_seconds', models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(3600)], verbose_name='Clear after (seconds)')),
                ('escalation_minutes', models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(1440)], verbose_name='Escalate after (minutes)')),
                ('delivery_attempts', models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(20)], verbose_name='Delivery attempts')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
            options={
                'verbose_name': 'alarm severity rule',
                'verbose_name_plural': 'alarm severity rules',
                'db_table': 'alarm_severity_policies',
                'ordering': ['severity'],
                'constraints': [models.UniqueConstraint(fields=('severity',), name='uq_alarm_severity_policies_severity'), models.CheckConstraint(condition=models.Q(('severity__in', ['warning', 'critical'])), name='chk_alarm_severity_policies_severity'), models.CheckConstraint(condition=models.Q(('off_delay_seconds__gte', 0), ('off_delay_seconds__lte', 3600), ('on_delay_seconds__gte', 0), ('on_delay_seconds__lte', 3600)), name='chk_alarm_severity_policies_delays'), models.CheckConstraint(condition=models.Q(('escalation_minutes__gte', 1), ('escalation_minutes__lte', 1440)), name='chk_alarm_severity_policies_escalation'), models.CheckConstraint(condition=models.Q(('delivery_attempts__gte', 1), ('delivery_attempts__lte', 20)), name='chk_alarm_severity_policies_attempts')],
            },
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
