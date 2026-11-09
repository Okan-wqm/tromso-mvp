"""How long a value of a water parameter says something about the water now, one row per parameter: the user's reference
data (cross review F10, alarm plan §7c), seeded with the hours the code held (farm/water/parameters.py until now)."""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


SEEDS = {'temperature_c': 24, 'oxygen_mg_l': 24, 'oxygen_saturation_pct': 24, 'ph': 72, 'alkalinity_mg_l': 336,
         'co2_mg_l': 72, 'tan_mg_l': 168, 'nitrite_n_mg_l': 168, 'nitrate_n_mg_l': 336, 'tgp_pct': 168,
         'salinity_ppt': 168, 'turbidity_ntu': 168, 'nh3_n_mg_l': 168, 'nh4_n_mg_l': 168}


def seed(apps, schema_editor):
    Freshness = apps.get_model('farm', 'WaterFreshness')
    Freshness.objects.bulk_create([Freshness(parameter=code, fresh_hours=hours) for code, hours in SEEDS.items()])


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0036_opening_balances'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='WaterFreshness',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('parameter', models.CharField(choices=[('temperature_c', 'Temperature (°C)'), ('oxygen_mg_l', 'Dissolved oxygen (mg/L O₂)'), ('oxygen_saturation_pct', 'Oxygen saturation (% of air saturation)'), ('ph', 'pH (NBS scale)'), ('alkalinity_mg_l', 'Alkalinity (mg/L as CaCO₃)'), ('co2_mg_l', 'Carbon dioxide (mg/L free CO₂)'), ('tan_mg_l', 'Total ammonia nitrogen (mg/L TAN as N)'), ('nitrite_n_mg_l', 'Nitrite (mg/L NO₂ as N)'), ('nitrate_n_mg_l', 'Nitrate (mg/L NO₃ as N)'), ('tgp_pct', 'Total gas pressure (% of barometric pressure)'), ('salinity_ppt', 'Salinity (‰, g/kg)'), ('turbidity_ntu', 'Turbidity (NTU)'), ('nh3_n_mg_l', 'Un-ionised ammonia (mg/L NH₃ as N)'), ('nh4_n_mg_l', 'Ammonium (mg/L NH₄⁺ as N)')], editable=False, max_length=30, verbose_name='Parameter')),
                ('fresh_hours', models.PositiveIntegerField(verbose_name='Fresh for (hours)')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
            options={
                'verbose_name': 'water freshness',
                'verbose_name_plural': 'water freshness',
                'db_table': 'water_freshness',
                'ordering': ['parameter'],
                'constraints': [models.UniqueConstraint(fields=('parameter',), name='uq_water_freshness_parameter'), models.CheckConstraint(condition=models.Q(('fresh_hours__gte', 1), ('fresh_hours__lte', 8760)), name='chk_water_freshness_hours', violation_error_message='From 1 hour to a year (8760 hours).'), models.CheckConstraint(condition=models.Q(('is_deleted', False)), name='chk_water_freshness_kept')],
            },
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
