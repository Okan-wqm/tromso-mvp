"""Card templates and their rules (monitoring/models.py): the two tables with every constraint the database can hold, the
three built-in templates frozen as they were made (monitoring/cards/builtin.py says the same; a test keeps them equal),
the global rule (every unit gets Simple), and the trigger that keeps any writer from changing or deleting a built-in
(an insert of one is the CHECK's: only the three ids, so a database emptied and loaded again gets them back). A later
change to a built-in is a migration that disables the trigger around its own update.

A refusal of the trigger is `check_violation`, so the ORM raises it as IntegrityError like a constraint. A change of the
bookkeeping columns alone (who made, changed or deleted it, and when) is let through."""

import django.db.models.deletion
import django.db.models.fields.json
import django.db.models.functions.comparison
import django.db.models.functions.text
import django.db.models.lookups
import uuid
from django.conf import settings
from django.db import migrations, models

BUILTINS = {
    '5f1c2a6e-0000-4000-8000-00000000c001': ['Simple', {'schema': 1, 'widgets': [
        {'id': 'w1', 'type': 'experiment', 'x': 0, 'y': 0, 'w': 12, 'h': 1},
        {'id': 'w2', 'type': 'fish', 'x': 0, 'y': 1, 'w': 12, 'h': 5, 'opts': {'figures': 'brief'}},
        {'id': 'w3', 'type': 'feeding', 'x': 0, 'y': 6, 'w': 12, 'h': 3},
        {'id': 'w4', 'type': 'water_table', 'x': 0, 'y': 9, 'w': 12, 'h': 4, 'opts': {'points': 'middle', 'parameters': 'key'}},
        {'id': 'w5', 'type': 'deffeyes', 'x': 0, 'y': 13, 'w': 4, 'h': 1},
    ]}, '5f1c2a6e-0000-4000-8000-00000000c002'],
    '5f1c2a6e-0000-4000-8000-00000000c002': ['Detailed', {'schema': 1, 'widgets': [
        {'id': 'w1', 'type': 'experiment', 'x': 0, 'y': 0, 'w': 12, 'h': 1},
        {'id': 'w2', 'type': 'fish', 'x': 0, 'y': 1, 'w': 12, 'h': 7, 'opts': {'figures': 'full'}},
        {'id': 'w3', 'type': 'feeding', 'x': 0, 'y': 8, 'w': 12, 'h': 4, 'opts': {'week': True}},
        {'id': 'w4', 'type': 'water_table', 'x': 0, 'y': 12, 'w': 12, 'h': 8, 'opts': {'points': 'all', 'parameters': 'all'}},
        {'id': 'w5', 'type': 'health', 'x': 0, 'y': 20, 'w': 12, 'h': 4},
        {'id': 'w6', 'type': 'tasks', 'x': 0, 'y': 24, 'w': 12, 'h': 2},
        {'id': 'w7', 'type': 'deffeyes', 'x': 0, 'y': 26, 'w': 4, 'h': 1},
    ]}, '5f1c2a6e-0000-4000-8000-00000000c001'],
    '5f1c2a6e-0000-4000-8000-00000000c003': ['Operator view', {'schema': 1, 'widgets': [
        {'id': 'w1', 'type': 'value', 'x': 0, 'y': 0, 'w': 6, 'h': 3, 'bind': {'parameter': 'oxygen_mg_l'}, 'opts': {'size': 'large'}},
        {'id': 'w2', 'type': 'value', 'x': 6, 'y': 0, 'w': 6, 'h': 3, 'bind': {'parameter': 'temperature_c'}, 'opts': {'size': 'large'}},
        {'id': 'w3', 'type': 'value', 'x': 0, 'y': 3, 'w': 4, 'h': 2, 'bind': {'parameter': 'oxygen_saturation_pct'}},
        {'id': 'w4', 'type': 'value', 'x': 4, 'y': 3, 'w': 4, 'h': 2, 'bind': {'parameter': 'ph'}},
        {'id': 'w5', 'type': 'value', 'x': 8, 'y': 3, 'w': 4, 'h': 2, 'bind': {'parameter': 'tan_mg_l'}},
        {'id': 'w6', 'type': 'experiment', 'x': 0, 'y': 5, 'w': 12, 'h': 1},
        {'id': 'w7', 'type': 'fish', 'x': 0, 'y': 6, 'w': 12, 'h': 5, 'opts': {'figures': 'brief'}},
        {'id': 'w8', 'type': 'feeding', 'x': 0, 'y': 11, 'w': 12, 'h': 3},
        {'id': 'w9', 'type': 'deffeyes', 'x': 0, 'y': 14, 'w': 4, 'h': 1},
    ]}, '5f1c2a6e-0000-4000-8000-00000000c002'],
}
GLOBAL_RULE = '5f1c2a6e-0000-4000-8000-00000000a001'

# What a built-in may still change: who made, changed or deleted it (SET NULL when a person is removed) and when it
# was made or changed (a test run's serialized rollback writes the times back at millisecond precision).
BOOKKEEPING = "'created_by_id' - 'updated_by_id' - 'deleted_by_id' - 'created_at' - 'updated_at'"

FROZEN = f"""
CREATE FUNCTION monitor_card_template_builtin() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.is_builtin THEN
            RAISE EXCEPTION 'card template %: a built-in is never deleted', OLD.name USING ERRCODE = 'check_violation';
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.is_builtin AND NOT OLD.is_builtin THEN
        RAISE EXCEPTION 'card template %: a template is never made a built-in', OLD.name
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.is_builtin
       AND (to_jsonb(NEW) - {BOOKKEEPING})
           IS DISTINCT FROM (to_jsonb(OLD) - {BOOKKEEPING}) THEN
        RAISE EXCEPTION 'card template %: a built-in is never changed; copy it', OLD.name
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_monitor_card_templates_builtin
    BEFORE UPDATE OR DELETE ON monitor_card_templates
    FOR EACH ROW EXECUTE FUNCTION monitor_card_template_builtin();
"""

UNFROZEN = """
DROP TRIGGER trg_monitor_card_templates_builtin ON monitor_card_templates;
DROP FUNCTION monitor_card_template_builtin();
"""


def make_builtins(apps, schema_editor):
    Template = apps.get_model('monitoring', 'CardTemplate')
    Rule = apps.get_model('monitoring', 'CardTemplateAssignment')
    for pk, (name, layout, _expanded) in BUILTINS.items():
        Template.objects.create(id=pk, name=name, layout=layout, is_builtin=True, schema_version=layout['schema'])
    for pk, (_name, _layout, expanded) in BUILTINS.items():
        Template.objects.filter(pk=pk).update(expanded_id=expanded)
    Rule.objects.create(id=GLOBAL_RULE, template_id='5f1c2a6e-0000-4000-8000-00000000c001')


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0025_escape_and_delivery'),
        ('monitoring', '0001_boards'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CardTemplateAssignment',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('system_type', models.CharField(blank=True, choices=[('ras', 'RAS (recirculating)'), ('flow_through', 'Flow-through'), ('pond', 'Pond'), ('cage', 'Cage'), ('raceway', 'Raceway'), ('hatchery', 'Hatchery'), ('nursery', 'Nursery'), ('biofloc', 'Biofloc'), ('aquaponics', 'Aquaponics'), ('other', 'Other')], max_length=20, null=True, verbose_name='System type')),
                ('kind', models.CharField(blank=True, choices=[('tank', 'Tank'), ('pond', 'Pond'), ('cage', 'Cage')], max_length=10, null=True, verbose_name='Unit kind')),
            ],
            options={
                'verbose_name': 'card template rule',
                'verbose_name_plural': 'card template rules',
                'db_table': 'monitor_card_assignments',
                'ordering': ['created_at'],
            },
        ),
        migrations.CreateModel(
            name='CardTemplate',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('name', models.CharField(max_length=100, verbose_name='Name')),
                ('description', models.CharField(blank=True, default='', max_length=300, verbose_name='Description')),
                ('is_builtin', models.BooleanField(default=False, editable=False, verbose_name='Built in')),
                ('schema_version', models.PositiveSmallIntegerField(default=1, editable=False, verbose_name='Layout version')),
                ('layout', models.JSONField(verbose_name='Layout')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('expanded', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='expanded_by', to='monitoring.cardtemplate', verbose_name='Flip link shows')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
            options={
                'verbose_name': 'card template',
                'verbose_name_plural': 'card templates',
                'db_table': 'monitor_card_templates',
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='cardtemplateassignment',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by'),
        ),
        migrations.AddField(
            model_name='cardtemplateassignment',
            name='deleted_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by'),
        ),
        migrations.AddField(
            model_name='cardtemplateassignment',
            name='species',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='card_assignments', to='farm.species', verbose_name='Species'),
        ),
        migrations.AddField(
            model_name='cardtemplateassignment',
            name='system',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='card_assignments', to='farm.system', verbose_name='System'),
        ),
        migrations.AddField(
            model_name='cardtemplateassignment',
            name='template',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='monitoring.cardtemplate', verbose_name='Template'),
        ),
        migrations.AddField(
            model_name='cardtemplateassignment',
            name='unit',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='card_assignments', to='farm.tank', verbose_name='Unit'),
        ),
        migrations.AddField(
            model_name='cardtemplateassignment',
            name='updated_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplate',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('name'), condition=models.Q(('is_deleted', False)), name='uq_monitor_card_templates_name_live', violation_error_message='Another card template already has this name.'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplate',
            constraint=models.CheckConstraint(condition=models.Q(('name', ''), _negated=True), name='chk_monitor_card_templates_name', violation_error_message='Give the template a name.'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplate',
            constraint=models.CheckConstraint(condition=models.Q(('schema_version__gte', 1), ('schema_version__lte', 1)), name='chk_monitor_card_templates_schema'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplate',
            constraint=models.CheckConstraint(condition=django.db.models.lookups.Exact(models.Func(models.F('layout'), function='jsonb_typeof', output_field=models.CharField()), models.Value('object')), name='chk_monitor_card_templates_object'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplate',
            constraint=models.CheckConstraint(condition=django.db.models.lookups.Exact(django.db.models.functions.comparison.Coalesce(models.Func(django.db.models.fields.json.KeyTransform('widgets', 'layout'), function='jsonb_typeof', output_field=models.CharField()), models.Value('')), models.Value('array')), name='chk_monitor_card_templates_widgets'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplate',
            constraint=models.CheckConstraint(condition=django.db.models.lookups.LessThanOrEqual(models.Case(models.When(django.db.models.lookups.Exact(django.db.models.functions.comparison.Coalesce(models.Func(django.db.models.fields.json.KeyTransform('widgets', 'layout'), function='jsonb_typeof', output_field=models.CharField()), models.Value('')), models.Value('array')), then=models.Func(django.db.models.fields.json.KeyTransform('widgets', 'layout'), function='jsonb_array_length', output_field=models.IntegerField())), default=models.Value(0)), models.Value(40)), name='chk_monitor_card_templates_count'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplate',
            constraint=models.CheckConstraint(condition=django.db.models.lookups.LessThanOrEqual(models.Func(django.db.models.functions.comparison.Cast('layout', models.TextField()), function='octet_length', output_field=models.IntegerField()), models.Value(32768)), name='chk_monitor_card_templates_bytes'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplate',
            constraint=models.CheckConstraint(condition=django.db.models.lookups.Exact(django.db.models.functions.comparison.Coalesce(django.db.models.fields.json.KeyTransform('schema', 'layout'), models.Func(models.Value(-1), function='to_jsonb', output_field=models.JSONField())), models.Func(models.F('schema_version'), function='to_jsonb', output_field=models.JSONField())), name='chk_monitor_card_templates_stamp'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplate',
            constraint=models.CheckConstraint(condition=models.Q(('expanded', models.F('id')), _negated=True), name='chk_monitor_card_templates_expanded', violation_error_message='A template cannot flip to itself.'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplate',
            constraint=models.CheckConstraint(condition=models.Q(('is_builtin', False), models.Q(('id__in', (uuid.UUID('5f1c2a6e-0000-4000-8000-00000000c001'), uuid.UUID('5f1c2a6e-0000-4000-8000-00000000c002'), uuid.UUID('5f1c2a6e-0000-4000-8000-00000000c003'))), ('is_deleted', False)), _connector='OR'), name='chk_monitor_card_templates_builtin'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplateassignment',
            constraint=models.CheckConstraint(condition=django.db.models.lookups.LessThanOrEqual(models.Func(models.F('unit'), models.F('system'), models.F('system_type'), models.F('species'), models.F('kind'), function='num_nonnulls', output_field=models.IntegerField()), models.Value(1)), name='chk_monitor_card_assignments_one_scope', violation_error_message='A rule is for one unit, system, system type, species or kind, or for every unit.'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplateassignment',
            constraint=models.UniqueConstraint(condition=models.Q(('is_deleted', False)), fields=('unit', 'system', 'system_type', 'species', 'kind'), name='uq_monitor_card_assignments_scope', nulls_distinct=False, violation_error_message='There is already a rule for this.'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplateassignment',
            constraint=models.CheckConstraint(condition=models.Q(('system_type__isnull', True), ('system_type__in', ['ras', 'flow_through', 'pond', 'cage', 'raceway', 'hatchery', 'nursery', 'biofloc', 'aquaponics', 'other']), _connector='OR'), name='chk_monitor_card_assignments_system_type'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplateassignment',
            constraint=models.CheckConstraint(condition=models.Q(('kind__isnull', True), ('kind__in', ['tank', 'pond', 'cage']), _connector='OR'), name='chk_monitor_card_assignments_kind'),
        ),
        migrations.RunPython(make_builtins, migrations.RunPython.noop),     # back: the tables go with their rows
        migrations.RunSQL(FROZEN, UNFROZEN),
    ]
