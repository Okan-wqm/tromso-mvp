import django.db.models.deletion
import django.db.models.manager
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0033_oxygen_basis'),
    ]

    operations = [
        migrations.CreateModel(
            name='OpeningBalance',
            fields=[
                ('operation', models.OneToOneField(limit_choices_to={'kind': 'input'}, on_delete=django.db.models.deletion.PROTECT, primary_key=True, related_name='opening_balance', serialize=False, to='farm.stockoperation', verbose_name='Operation')),
                ('document', models.CharField(max_length=300, verbose_name='Source document')),
            ],
            options={
                'verbose_name': 'opening balance',
                'verbose_name_plural': 'opening balances',
                'db_table': 'opening_balances',
                'base_manager_name': 'all_objects',
                'constraints': [models.CheckConstraint(condition=models.Q(('document', ''), _negated=True), name='chk_opening_balances_document')],
            },
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
    ]
