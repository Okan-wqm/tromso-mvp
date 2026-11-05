"""The boards point at templates: a board's default template and card width, and a card row's own template. The old
modes stay for one release (a rollback must not lose data); 0004 copies them into the templates."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0002_card_templates'),
    ]

    operations = [
        migrations.AddField(
            model_name='monitorboard',
            name='card_width',
            field=models.PositiveSmallIntegerField(choices=[(1, 'Compact'), (2, 'Automatic'), (3, 'Comfortable')], default=2, verbose_name='Card width'),
        ),
        migrations.AddField(
            model_name='monitorboard',
            name='default_template',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='default_for_boards', to='monitoring.cardtemplate', verbose_name='Cards are drawn with'),
        ),
        migrations.AddField(
            model_name='monitorboardunit',
            name='template',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='board_rows', to='monitoring.cardtemplate', verbose_name='Template'),
        ),
        migrations.AddConstraint(
            model_name='monitorboard',
            constraint=models.CheckConstraint(condition=models.Q(('card_width__in', [1, 2, 3])), name='chk_monitor_boards_card_width'),
        ),
    ]
