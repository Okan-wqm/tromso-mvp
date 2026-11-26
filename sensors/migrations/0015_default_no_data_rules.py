"""A default "No fresh value" rule for every quantity the water limits judge (owner decision of 2026-11-20; the second
review of the water-chemistry audit, question 3): a probe that stops sending is warned of whatever its pH scale, at the
channel's own freshness. One rule per quantity, on every channel of it (sensors.AlarmRule.is_default), so the channels
there are and every channel made later are covered by the rule's scope, not by a row per channel. The database keeps
them: a check holds a default rule to what it is (no time past the freshness, no threshold, never soft-deleted, switched
off only with a reason) and one per quantity, a trigger refuses deleting one, unmarking it or moving it to another
quantity (as alarms 0006 keeps the severity rules).

Seeded as alarms 0002 seeds the severity rules, from here on the farm's row: critical for the dissolved oxygen (mg/L
and %), a warning for every other quantity (owner decision of 2026-11-20, quantities.default_severity). A quantity that
has an active, live "No fresh value" rule of the same shape already (every channel of it, nothing past the freshness)
gets that one marked as its default instead of a second (two alarms for one probe), keeping its own severity (the
farm's setting), but for the dissolved oxygen, raised to critical where it was a warning (the owner's decision of
2026-11-20, applied on the review of 2026-11-23, F4), a row of the activity log (by 'system') saying so, as alarms
0008 says a changed row. The quantities and the critical ones are written here as they are when this migration is made
(quantities.JUDGED_CODES and DEFAULT_CRITICAL; a migration never reads live code: sensors/tests/test_fresh_rule.py
holds them together, and a quantity added later seeds its own in its migration).

Going back removes the rules this made (every default rule but those it marked, read from its own log rows), so a
migration further back that narrows the quantities a rule may name (sensors 0011, 0012) finds none of them; except one
with events (its alarms are history, append-only) or changed by a person since (a severity, a switch-off: the farm's
setting), which stays as an ordinary "No fresh value" rule of its quantity, each said in the activity log. A rule it
marked keeps its row (the mark goes with the column) and gets back the severity it raised, said in the log too. Going forward again marks a kept rule the default once more (no
second rule)."""
from django.conf import settings
from django.db import migrations, models

from core.migrations._log import SYSTEM, entries, system_entry

JUDGED = ['temperature_c', 'oxygen_mg_l', 'oxygen_saturation_pct', 'ph', 'alkalinity_mg_l', 'hardness_mg_l', 'co2_mg_l',
          'tan_mg_l', 'nitrite_n_mg_l', 'nitrate_n_mg_l', 'tgp_pct', 'salinity_ppt', 'conductivity_25_us_cm',
          'turbidity_ntu', 'phosphate_p_mg_l']
CRITICAL = ['oxygen_mg_l', 'oxygen_saturation_pct']   # seeded critical; every other a warning
ENTITY = 'alarm rule'                   # the activity log's name of the record (AlarmRuleResource.entity_type)
MARKED = 'sensors 0015: made the default "No fresh value" rule of its quantity (owner decision of 2026-11-20).'
RAISED = ('sensors 0015: made the default "No fresh value" rule of its quantity, and critical as the default of the '
          'dissolved oxygen is (owner decision of 2026-11-20).')
LOWERED = 'sensors 0015 reversed: its severity as it was before sensors 0015 raised it.'
SEVERITY = {'warning': 'Warning', 'critical': 'Critical'}         # as the log shows a severity (its choice's label)
KEPT = 'sensors 0015 reversed: kept as an ordinary "No fresh value" rule, {why}.'

KEEP = """
CREATE FUNCTION sensors_alarm_rule_default_kept() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'The default "No fresh value" rule of % is switched off with a reason, never deleted.',
            OLD.quantity USING ERRCODE = 'restrict_violation';
    END IF;
    IF NOT NEW.is_default OR NEW.quantity IS DISTINCT FROM OLD.quantity THEN
        RAISE EXCEPTION 'The default "No fresh value" rule of % stays the default rule of its quantity.',
            OLD.quantity USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_sensors_alarm_rule_default_kept BEFORE DELETE OR UPDATE ON sensors_alarm_rule
    FOR EACH ROW WHEN (OLD.is_default) EXECUTE FUNCTION sensors_alarm_rule_default_kept();
"""
DROP = """
DROP TRIGGER IF EXISTS trg_sensors_alarm_rule_default_kept ON sensors_alarm_rule;
DROP FUNCTION IF EXISTS sensors_alarm_rule_default_kept();
"""


def seed(apps, schema_editor):
    Rule = apps.get_model('sensors', 'AlarmRule')
    for code in JUDGED:
        if Rule.objects.filter(quantity=code, is_default=True).exists():
            continue
        found = (Rule.objects.filter(quantity=code, channel__isnull=True, kind='no_data', is_active=True,
                                     is_deleted=False, threshold__isnull=True, for_s=0, hysteresis=0)
                 .order_by('created_at', 'id').first())
        if found is None:
            Rule.objects.create(quantity=code, kind='no_data', for_s=0, hysteresis=0, is_active=True, is_default=True,
                                severity='critical' if code in CRITICAL else 'warning')
            continue
        changes = {'Default rule': ['No', 'Yes'], 'Note': [None, MARKED]}
        if code in CRITICAL and found.severity != 'critical':
            Rule.objects.filter(pk=found.pk).update(is_default=True, severity='critical')
            changes = {'Default rule': ['No', 'Yes'], 'Severity': [SEVERITY[found.severity], 'Critical'],
                       'Note': [None, RAISED]}
        else:
            Rule.objects.filter(pk=found.pk).update(is_default=True)
        system_entry(schema_editor, ENTITY, found.pk, f'{code}: No fresh value', changes)


def unseed(apps, schema_editor):
    Rule = apps.get_model('sensors', 'AlarmRule')
    Event = apps.get_model('sensors', 'AlarmEvent')
    marked = {str(rule_id): changes for rule_id, who, _action, changes in entries(schema_editor, ENTITY)
              if who == SYSTEM and (changes.get('Note') or [None, None])[1] in (MARKED, RAISED)}
    labels = {label: value for value, label in SEVERITY.items()}
    for rule in Rule.objects.filter(is_default=True).order_by('quantity'):
        if str(rule.pk) in marked:
            before = (marked[str(rule.pk)].get('Severity') or [None])[0]
            if before in labels and rule.severity == 'critical':
                Rule.objects.filter(pk=rule.pk).update(severity=labels[before])
                system_entry(schema_editor, ENTITY, rule.pk, f'{rule.quantity}: No fresh value',
                             {'Severity': ['Critical', before], 'Note': [None, LOWERED]})
            continue
        why = ('its alarms are history' if Event.objects.filter(rule=rule).exists()
               else 'changed by a person since' if rule.version > 1 else '')
        if not why:
            Rule.objects.filter(pk=rule.pk).delete()
            continue
        system_entry(schema_editor, ENTITY, rule.pk, f'{rule.quantity}: No fresh value',
                     {'Default rule': ['Yes', None], 'Note': [None, KEPT.format(why=why)]})
    # The deletes' deferred foreign-key checks run now: the table is altered next in this transaction, which PostgreSQL
    # refuses while trigger events are pending (found by the rehearsal on the dev dump).
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        cursor.execute('SET CONSTRAINTS ALL DEFERRED')


class Migration(migrations.Migration):

    dependencies = [
        ('sensors', '0014_rev_triggers'),
        ('core', '0007_audit_severity'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='alarmrule',
            name='is_default',
            field=models.BooleanField(db_default=False, default=False, editable=False, verbose_name='Default rule'),
        ),
        migrations.AddField(
            model_name='alarmrule',
            name='off_reason',
            field=models.CharField(blank=True, max_length=300, verbose_name='Why it is switched off'),
        ),
        migrations.AddConstraint(
            model_name='alarmrule',
            constraint=models.CheckConstraint(condition=models.Q(('is_default', False), models.Q(('channel__isnull', True), ('for_s', 0), ('hysteresis', 0), ('is_deleted', False), ('kind', 'no_data'), ('quantity__in', ['temperature_c', 'oxygen_mg_l', 'oxygen_saturation_pct', 'ph', 'alkalinity_mg_l', 'hardness_mg_l', 'co2_mg_l', 'tan_mg_l', 'nitrite_n_mg_l', 'nitrate_n_mg_l', 'tgp_pct', 'salinity_ppt', 'conductivity_25_us_cm', 'turbidity_ntu', 'phosphate_p_mg_l']), ('threshold__isnull', True), models.Q(('is_active', True), models.Q(('off_reason', ''), _negated=True), _connector='OR')), _connector='OR'), name='chk_sensors_alarm_rule_default', violation_error_message='A default rule is the “No fresh value” of every channel of its quantity, at the channel’s own freshness; it is switched off with a reason, never deleted.'),
        ),
        migrations.AddConstraint(
            model_name='alarmrule',
            constraint=models.UniqueConstraint(condition=models.Q(('is_default', True)), fields=('quantity',), name='uq_sensors_alarm_rule_default', violation_error_message='This quantity has its default rule already.'),
        ),
        migrations.RunPython(seed, unseed),
        migrations.RunSQL(KEEP, reverse_sql=DROP),
    ]
