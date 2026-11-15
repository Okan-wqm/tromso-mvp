"""The fifth built-in template, Big (owner decisions 4, 10, 11, 12, 2026-11-12: the card of one tank, its Deffeyes chart
dominant; monitoring/cards/builtin.py says the same layout, a test keeps the two equal).

As 0005 made Small: the CHECK on the built-in ids is widened to the fifth before its row is made; the trigger of 0002 is
BEFORE UPDATE OR DELETE, so the insert passes it, and the row is made whole in one statement (a later update of it would
be refused). Back, the row is deleted with the trigger off for that statement alone (boards, rows and rules that point
at it are detached or deleted by the ORM, as when any template is deleted)."""

import uuid
from django.db import migrations, models

BIG = '5f1c2a6e-0000-4000-8000-00000000c005'
DETAILED = '5f1c2a6e-0000-4000-8000-00000000c002'
# {id: [name, layout, the template its flip link shows, (width, height) in card units]}
BUILTINS = {
    BIG: ['Big', {'schema': 1, 'widgets': [
        {'id': 'w1', 'type': 'value', 'x': 0, 'y': 0, 'w': 3, 'h': 2, 'bind': {'parameter': 'oxygen_mg_l'}},
        {'id': 'w2', 'type': 'value', 'x': 3, 'y': 0, 'w': 3, 'h': 2, 'bind': {'parameter': 'temperature_c'}},
        {'id': 'w3', 'type': 'value', 'x': 6, 'y': 0, 'w': 3, 'h': 2, 'bind': {'parameter': 'ph'}},
        {'id': 'w4', 'type': 'value', 'x': 9, 'y': 0, 'w': 3, 'h': 2, 'bind': {'parameter': 'co2_calc_mg_l'}},
        {'id': 'w5', 'type': 'chart', 'x': 0, 'y': 2, 'w': 12, 'h': 12},
        {'id': 'w6', 'type': 'water_table', 'x': 0, 'y': 14, 'w': 12, 'h': 5,
         'opts': {'points': 'middle', 'parameters': 'all'}},
        {'id': 'w7', 'type': 'dosing', 'x': 0, 'y': 19, 'w': 4, 'h': 2},
        {'id': 'w8', 'type': 'points', 'x': 4, 'y': 19, 'w': 4, 'h': 2},
        {'id': 'w9', 'type': 'stock', 'x': 8, 'y': 19, 'w': 4, 'h': 2},
    ]}, DETAILED, [48, 61]],
}
TRIGGER = 'ALTER TABLE monitor_card_templates {} TRIGGER trg_monitor_card_templates_builtin'
EARLIER = tuple(uuid.UUID(f'5f1c2a6e-0000-4000-8000-00000000c00{number}') for number in (1, 2, 3, 4))


def make_big(apps, schema_editor):
    Template = apps.get_model('monitoring', 'CardTemplate')
    for pk, (name, layout, expanded, (width, height)) in BUILTINS.items():
        Template.objects.create(id=pk, name=name, layout=layout, is_builtin=True, schema_version=layout['schema'],
                                expanded_id=expanded, measure_w=width, measure_h=height)


def remove_big(apps, schema_editor):
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


def _builtin(ids):
    return models.CheckConstraint(
        condition=models.Q(('is_builtin', False), models.Q(('id__in', ids), ('is_deleted', False)), _connector='OR'),
        name='chk_monitor_card_templates_builtin')


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0005_small_template'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='cardtemplate',
            name='chk_monitor_card_templates_builtin',
        ),
        migrations.AddConstraint(
            model_name='cardtemplate',
            constraint=_builtin((*EARLIER, uuid.UUID(BIG))),
        ),
        migrations.RunPython(make_big, remove_big),
    ]
