"""The acknowledgement of batches of very different sizes in one unit (StockOperation.size_mix_ack), stored on the
operation that brought the fish in, as the over-capacity one is; the database keeps it to such operations. A new column,
false for every operation recorded before: none was asked. The check is added NOT VALID, then validated in a step
of its own, so the table is not scanned under the lock that adds it (the cross review, F10)."""
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
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name='stockoperation',
                    constraint=models.CheckConstraint(condition=models.Q(('size_mix_ack', False), ('kind__in', ('input', 'transfer', 'grading', 'adjustment')), _connector='OR'), name='chk_stock_operations_size_mix_ack_on_arrival'),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE stock_operations ADD CONSTRAINT chk_stock_operations_size_mix_ack_on_arrival "
                    "CHECK (NOT size_mix_ack OR kind IN ('input', 'transfer', 'grading', 'adjustment')) NOT VALID",
                    'ALTER TABLE stock_operations DROP CONSTRAINT chk_stock_operations_size_mix_ack_on_arrival',
                ),
                migrations.RunSQL(
                    'ALTER TABLE stock_operations VALIDATE CONSTRAINT chk_stock_operations_size_mix_ack_on_arrival',
                    migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
