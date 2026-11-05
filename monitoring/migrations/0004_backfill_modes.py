"""A board's default mode and each card row's mode become the built-in templates that reproduce them (simple: Simple,
detailed: Detailed, a row's '' stays empty: the board decides). Back, a board or row on a built-in maps to its mode again
and one on a template of its own keeps the mode it has (the old columns stay for one release, so nothing is lost)."""
from django.db import migrations

SIMPLE = '5f1c2a6e-0000-4000-8000-00000000c001'
DETAILED = '5f1c2a6e-0000-4000-8000-00000000c002'
TEMPLATE_OF = {'simple': SIMPLE, 'detailed': DETAILED}
MODE_OF = {SIMPLE: 'simple', DETAILED: 'detailed'}


def forward(apps, schema_editor):
    Board, Row = apps.get_model('monitoring', 'MonitorBoard'), apps.get_model('monitoring', 'MonitorBoardUnit')
    for mode, template in TEMPLATE_OF.items():
        Board.objects.filter(default_mode=mode).update(default_template_id=template)
        Row.objects.filter(mode=mode).update(template_id=template)


def backward(apps, schema_editor):
    Board, Row = apps.get_model('monitoring', 'MonitorBoard'), apps.get_model('monitoring', 'MonitorBoardUnit')
    for template, mode in MODE_OF.items():
        Board.objects.filter(default_template_id=template).update(default_mode=mode)
        Row.objects.filter(template_id=template).update(mode=mode)


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0003_template_pointers'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
