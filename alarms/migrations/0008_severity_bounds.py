"""Per-severity bounds of the alarm rules and a deadband ceiling, held by the database (cross review F9; alarms/models.py).
A row the earlier bounds allowed but these do not is first brought to the nearest bound, each change logged in the
activity log, so `migrate` never stops on old data (round-2 review N4). The bounds are written here as they stood."""
import json
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models

ON_DELAY = {'critical': (0, 10), 'warning': (0, 900)}
ESCALATION = {'critical': (1, 30), 'warning': (1, 1440)}
LABELS = {'on_delay_seconds': 'Raise after (seconds)', 'escalation_minutes': 'Escalate after (minutes)',
          'deadband': 'Deadband'}


def _log(cursor, entity_type, row, label, changes):
    cursor.execute(
        "INSERT INTO audit_log (id, created_at, user_name, action, entity_type, entity_id, entity_label, changes, "
        "severity) VALUES (gen_random_uuid(), now(), 'system', 'update', %s, %s, %s, %s::jsonb, 'critical')",
        [entity_type, str(row.pk), label, json.dumps({
            **changes, 'Note': [None, 'alarms 0008: outside the new bounds, brought to the nearest one']})])


def clamp(apps, schema_editor):
    """Every severity rule and deadband outside the new bounds, brought to the nearest bound, logged."""
    from farm.water import parameters
    Policy = apps.get_model('alarms', 'SeverityPolicy')
    Deadband = apps.get_model('alarms', 'ParameterDeadband')
    with schema_editor.connection.cursor() as cursor:
        for row in Policy.objects.all():
            changes = {}
            for field, bounds in (('on_delay_seconds', ON_DELAY), ('escalation_minutes', ESCALATION)):
                low, high = bounds.get(row.severity, (None, None))
                value = getattr(row, field)
                if low is not None and not low <= value <= high:
                    fitted = min(max(value, low), high)
                    changes[LABELS[field]] = [str(value), str(fitted)]
                    setattr(row, field, fitted)
            if changes:
                Policy.objects.filter(pk=row.pk).update(on_delay_seconds=row.on_delay_seconds,
                                                        escalation_minutes=row.escalation_minutes)
                _log(cursor, 'alarm severity rule', row, row.severity.capitalize(), changes)
        for row in Deadband.objects.all():
            if row.parameter not in parameters.BY_CODE:
                continue
            measure = parameters.get(row.parameter)
            ceiling = measure.high - measure.low
            if row.deadband > ceiling:
                Deadband.objects.filter(pk=row.pk).update(deadband=ceiling)
                _log(cursor, 'alarm deadband', row, row.parameter,
                     {LABELS['deadband']: [str(row.deadband.normalize()), str(ceiling.normalize())]})


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0007_subjects_by_unit'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(clamp, migrations.RunPython.noop),
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
