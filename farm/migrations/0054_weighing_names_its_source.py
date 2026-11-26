from django.db import migrations, models


class Migration(migrations.Migration):
    """Every weighing line says how it was measured, and only a weighing does: held once 0053 has given the lines that
    were there their source."""

    dependencies = [
        ('farm', '0053_weight_source_and_step_rules'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='stockmovement',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('kind', 'weighing'), ('weight_source__isnull', False)), models.Q(models.Q(('kind', 'weighing'), _negated=True), ('weight_source__isnull', True)), _connector='OR'), name='chk_stock_movements_weight_source'),
        ),
    ]
