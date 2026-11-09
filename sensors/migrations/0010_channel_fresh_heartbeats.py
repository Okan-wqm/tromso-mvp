"""How many heartbeats a channel's value stays fresh is the channel's own (cross review F10, alarm plan §7c), 3 as the code
held; `fresh_s` is worked out from it. A generated column's expression is not altered in place: it is dropped and made
again (nothing else reads the column in the database)."""

import django.core.validators
import django.db.models.expressions
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sensors', '0009_alarm_event_acknowledgement_columns_removed'),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='fresh_heartbeats',
            field=models.PositiveSmallIntegerField(default=3, help_text='How many heartbeats a value stays fresh without a new one; then the place shows no recent data.', validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(20)], verbose_name='Fresh for (heartbeats)'),
        ),
        migrations.RemoveField(
            model_name='channel',
            name='fresh_s',
        ),
        migrations.AddField(
            model_name='channel',
            name='fresh_s',
            field=models.GeneratedField(db_persist=True, expression=django.db.models.expressions.CombinedExpression(models.F('heartbeat_s'), '*', models.F('fresh_heartbeats')), output_field=models.IntegerField(), verbose_name='Fresh for (seconds)'),
        ),
        migrations.AddConstraint(
            model_name='channel',
            constraint=models.CheckConstraint(condition=models.Q(('fresh_heartbeats__gte', 1), ('fresh_heartbeats__lte', 20)),
                                              name='chk_sensors_channel_fresh_heartbeats'),
        ),
    ]
