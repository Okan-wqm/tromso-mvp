"""A card template's measure, and the fourth built-in template, Small (owner decision 7, 2026-11-12: a small card for the
overview of a wide monitor; monitoring/cards/builtin.py says the same layout, a test keeps the two equal).

A template with a measure is FITTED: its card is drawn at the size of its cell, `measure_w` units wide and `measure_h`
high (monitoring/cards/catalogue.py MEASURE_W, MEASURE_H); both empty, the card flows as cards always did. The CHECK
holds the pair whole and in range (with IS NOT NULL: a range test of a NULL is unknown, which a CHECK lets pass). The CHECK on the built-in ids is widened to the fourth before its row is made; the
trigger of 0002 is BEFORE UPDATE OR DELETE, so the insert passes it, and the row is made whole in one statement (a
later update of it would be refused). Back, the row is deleted with the trigger off for that statement alone (boards,
rows and rules that point at it are detached or deleted by the ORM, as when any template is deleted). A farm's own live
template called Small (in any case) is renamed first (`free_the_name`)."""

import django.core.validators
import uuid
from django.conf import settings
from django.db import migrations, models

SMALL = '5f1c2a6e-0000-4000-8000-00000000c004'
DETAILED = '5f1c2a6e-0000-4000-8000-00000000c002'
# {id: [name, layout, the template its flip link shows, (width, height) in card units]}
BUILTINS = {
    SMALL: ['Small', {'schema': 1, 'widgets': [
        {'id': 'w1', 'type': 'value', 'x': 0, 'y': 0, 'w': 3, 'h': 3, 'bind': {'parameter': 'oxygen_mg_l'}},
        {'id': 'w2', 'type': 'value', 'x': 3, 'y': 0, 'w': 3, 'h': 3, 'bind': {'parameter': 'temperature_c'}},
        {'id': 'w3', 'type': 'value', 'x': 6, 'y': 0, 'w': 3, 'h': 3, 'bind': {'parameter': 'ph'}},
        {'id': 'w4', 'type': 'value', 'x': 9, 'y': 0, 'w': 3, 'h': 3, 'bind': {'parameter': 'co2_calc_mg_l'}},
        {'id': 'w5', 'type': 'ph_window', 'x': 0, 'y': 3, 'w': 12, 'h': 2},
    ]}, DETAILED, [31, 12]],
}
TRIGGER = 'ALTER TABLE monitor_card_templates {} TRIGGER trg_monitor_card_templates_builtin'


def free_the_name(Template, name):
    """A farm may already have a live template of a built-in's name (in any case); a live name is unique, so the built-in
    could not be made and the deploy would stop on a raw IntegrityError (review R3). The built-in takes the name; the
    farm's template, with every board, row and rule that points at it, lives on under the same name with the first
    free number: "small" becomes "small (2)". Nothing guesses the name back when the migration is undone."""
    for clash in Template.objects.filter(name__iexact=name, is_deleted=False, is_builtin=False):
        number = 2
        while Template.objects.filter(name__iexact=f'{clash.name[:94]} ({number})', is_deleted=False).exists():
            number += 1
        Template.objects.filter(pk=clash.pk).update(name=f'{clash.name[:94]} ({number})')


def make_small(apps, schema_editor):
    Template = apps.get_model('monitoring', 'CardTemplate')
    for pk, (name, layout, expanded, (width, height)) in BUILTINS.items():
        free_the_name(Template, name)
        Template.objects.create(id=pk, name=name, layout=layout, is_builtin=True, schema_version=layout['schema'],
                                expanded_id=expanded, measure_w=width, measure_h=height)


def remove_small(apps, schema_editor):
    Template = apps.get_model('monitoring', 'CardTemplate')
    # The foreign keys are checked at the end of the transaction, and PostgreSQL refuses ALTER TABLE while a row's
    # check is pending: they are checked now, before the trigger is switched off and again after the delete, so the
    # table can be altered here and by the operations that follow.
    schema_editor.execute('SET CONSTRAINTS ALL IMMEDIATE')
    schema_editor.execute(TRIGGER.format('DISABLE'))
    Template.objects.filter(pk__in=list(BUILTINS)).delete()
    schema_editor.execute('SET CONSTRAINTS ALL IMMEDIATE')
    schema_editor.execute(TRIGGER.format('ENABLE'))
    schema_editor.execute('SET CONSTRAINTS ALL DEFERRED')


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0004_backfill_modes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='cardtemplate',
            name='chk_monitor_card_templates_builtin',
        ),
        migrations.AddField(
            model_name='cardtemplate',
            name='measure_h',
            field=models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(6), django.core.validators.MaxValueValidator(64)], verbose_name='Card height (units)'),
        ),
        migrations.AddField(
            model_name='cardtemplate',
            name='measure_w',
            field=models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(12), django.core.validators.MaxValueValidator(64)], verbose_name='Card width (units)'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplate',
            constraint=models.CheckConstraint(condition=models.Q(('is_builtin', False), models.Q(('id__in', (uuid.UUID('5f1c2a6e-0000-4000-8000-00000000c001'), uuid.UUID('5f1c2a6e-0000-4000-8000-00000000c002'), uuid.UUID('5f1c2a6e-0000-4000-8000-00000000c003'), uuid.UUID('5f1c2a6e-0000-4000-8000-00000000c004'))), ('is_deleted', False)), _connector='OR'), name='chk_monitor_card_templates_builtin'),
        ),
        migrations.AddConstraint(
            model_name='cardtemplate',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('measure_h__isnull', True), ('measure_w__isnull', True)), models.Q(('measure_h__isnull', False), ('measure_h__range', (6, 64)), ('measure_w__isnull', False), ('measure_w__range', (12, 64))), _connector='OR'), name='chk_monitor_card_templates_measure', violation_error_message='A fitted card needs both its width (12 to 64 units) and its height (6 to 64 units); leave both empty for a card that flows.'),
        ),
        migrations.RunPython(make_small, remove_small),
    ]
