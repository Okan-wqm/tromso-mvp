"""The pH window's scale as the farm's reference data, one row per water type (owner decision 15, 2026-11-16), seeded
with the 6.4 to 8.6 the code held (monitoring/cards/catalogue.py PH_WINDOW until now)."""

import uuid
from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

WATERS = ('freshwater', 'saltwater', 'brackish')
SEED = (Decimal('6.4'), Decimal('8.6'))


def seed(apps, schema_editor):
    Scale = apps.get_model('monitoring', 'PhWindowScale')
    Scale.objects.bulk_create([Scale(water_type=water, ph_low=SEED[0], ph_high=SEED[1]) for water in WATERS])


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0006_big_template'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PhWindowScale',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('water_type', models.CharField(choices=[('freshwater', 'Freshwater'), ('saltwater', 'Saltwater'), ('brackish', 'Brackish')], editable=False, max_length=20, verbose_name='Water type')),
                ('ph_low', models.DecimalField(decimal_places=1, max_digits=3, verbose_name='From pH')),
                ('ph_high', models.DecimalField(decimal_places=1, max_digits=3, verbose_name='To pH')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
            options={
                'verbose_name': 'pH window scale',
                'verbose_name_plural': 'pH window scales',
                'db_table': 'monitor_ph_window_scales',
                'ordering': ['water_type'],
                'constraints': [models.UniqueConstraint(fields=('water_type',), name='uq_monitor_ph_window_scales_water'), models.CheckConstraint(condition=models.Q(('water_type__in', ['freshwater', 'saltwater', 'brackish'])), name='chk_monitor_ph_window_scales_water'), models.CheckConstraint(condition=models.Q(('ph_high__lte', 14), ('ph_low__gte', 0)), name='chk_monitor_ph_window_scales_range', violation_error_message='A pH lies between 0 and 14.'), models.CheckConstraint(condition=models.Q(('ph_high__gte', models.expressions.CombinedExpression(models.F('ph_low'), '+', models.Value(Decimal('0.5'))))), name='chk_monitor_ph_window_scales_span', violation_error_message='The scale must span at least half a pH unit, from the lower end to the higher.'), models.CheckConstraint(condition=models.Q(('is_deleted', False)), name='chk_monitor_ph_window_scales_kept')],
            },
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
