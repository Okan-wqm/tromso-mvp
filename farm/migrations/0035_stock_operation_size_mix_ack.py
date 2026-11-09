"""The acknowledgement of batches of very different sizes in one unit (StockOperation.size_mix_ack), stored on the
operation that brought the fish in, as the over-capacity one is; the database keeps it to such operations. A new column,
false for every operation recorded before: none was asked."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0034_species_max_weight_ratio'),
    ]

    operations = [
        migrations.AddField(
            model_name='stockoperation',
            name='size_mix_ack',
            field=models.BooleanField(default=False, verbose_name='Batches of different sizes, accepted'),
        ),
        migrations.AddConstraint(
            model_name='stockoperation',
            constraint=models.CheckConstraint(condition=models.Q(('size_mix_ack', False), ('kind__in', ('input', 'transfer', 'grading', 'adjustment')), _connector='OR'), name='chk_stock_operations_size_mix_ack_on_arrival'),
        ),
    ]
