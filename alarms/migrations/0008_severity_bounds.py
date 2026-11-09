"""Per-severity bounds of the alarm rules and a deadband ceiling, held by the database (cross review F9; alarms/models.py)."""

from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0007_subjects_by_unit'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='severitypolicy',
            name='chk_alarm_severity_policies_delays',
        ),
        migrations.RemoveConstraint(
            model_name='severitypolicy',
            name='chk_alarm_severity_policies_escalation',
        ),
        migrations.AlterField(
            model_name='severitypolicy',
            name='escalation_minutes',
            field=models.PositiveIntegerField(verbose_name='Escalate after (minutes)'),
        ),
        migrations.AlterField(
            model_name='severitypolicy',
            name='on_delay_seconds',
            field=models.PositiveIntegerField(verbose_name='Raise after (seconds)'),
        ),
        migrations.AddConstraint(
            model_name='parameterdeadband',
            constraint=models.CheckConstraint(condition=models.Q(('pk__in', []), models.Q(('deadband__lte', Decimal('43')), ('parameter', 'temperature_c')), models.Q(('deadband__lte', Decimal('50')), ('parameter', 'oxygen_mg_l')), models.Q(('deadband__lte', Decimal('400')), ('parameter', 'oxygen_saturation_pct')), models.Q(('deadband__lte', Decimal('10')), ('parameter', 'ph')), models.Q(('deadband__lte', Decimal('1000')), ('parameter', 'alkalinity_mg_l')), models.Q(('deadband__lte', Decimal('200')), ('parameter', 'co2_mg_l')), models.Q(('deadband__lte', Decimal('100')), ('parameter', 'tan_mg_l')), models.Q(('deadband__lte', Decimal('100')), ('parameter', 'nitrite_n_mg_l')), models.Q(('deadband__lte', Decimal('1000')), ('parameter', 'nitrate_n_mg_l')), models.Q(('deadband__lte', Decimal('150')), ('parameter', 'tgp_pct')), models.Q(('deadband__lte', Decimal('50')), ('parameter', 'salinity_ppt')), models.Q(('deadband__lte', Decimal('4000')), ('parameter', 'turbidity_ntu')), models.Q(('deadband__lte', Decimal('100')), ('parameter', 'nh3_n_mg_l')), _connector='OR'), name='chk_alarm_deadbands_ceiling', violation_error_message='Wider than the parameter’s whole range.'),
        ),
        migrations.AddConstraint(
            model_name='severitypolicy',
            constraint=models.CheckConstraint(condition=models.Q(('off_delay_seconds__gte', 0), ('off_delay_seconds__lte', 3600)), name='chk_alarm_severity_policies_delays'),
        ),
        migrations.AddConstraint(
            model_name='severitypolicy',
            constraint=models.CheckConstraint(condition=models.Q(('pk__in', []), models.Q(('on_delay_seconds__gte', 0), ('on_delay_seconds__lte', 10), ('severity', 'critical')), models.Q(('on_delay_seconds__gte', 0), ('on_delay_seconds__lte', 900), ('severity', 'warning')), _connector='OR'), name='chk_alarm_severity_policies_on_delay'),
        ),
        migrations.AddConstraint(
            model_name='severitypolicy',
            constraint=models.CheckConstraint(condition=models.Q(('pk__in', []), models.Q(('escalation_minutes__gte', 1), ('escalation_minutes__lte', 30), ('severity', 'critical')), models.Q(('escalation_minutes__gte', 1), ('escalation_minutes__lte', 1440), ('severity', 'warning')), _connector='OR'), name='chk_alarm_severity_policies_escalation'),
        ),
    ]
