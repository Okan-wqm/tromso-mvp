"""The conductivity at 25 °C and the hardness, formula 3's ionic-strength inputs, get their water freshness rows (the
user's reference data since farm 0037): 7 days and 14 days, as formula 3 has read them (farm/water/freshness.py SEEDS).
Back, only these two rows go."""
from django.db import migrations, models


SEEDS = {'conductivity_25_us_cm': 168, 'hardness_mg_l': 336}


def seed(apps, schema_editor):
    Freshness = apps.get_model('farm', 'WaterFreshness')
    Freshness.objects.bulk_create([Freshness(parameter=code, fresh_hours=hours) for code, hours in SEEDS.items()],
                                  ignore_conflicts=True)


def unseed(apps, schema_editor):
    apps.get_model('farm', 'WaterFreshness').objects.filter(parameter__in=list(SEEDS)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0041_water_origin'),
    ]

    operations = [
        migrations.AlterField(
            model_name='waterfreshness',
            name='parameter',
            field=models.CharField(choices=[('temperature_c', 'Temperature (°C)'), ('oxygen_mg_l', 'Dissolved oxygen (mg/L O₂)'), ('oxygen_saturation_pct', 'Oxygen saturation (% of air saturation)'), ('ph', 'pH (NBS scale)'), ('alkalinity_mg_l', 'Alkalinity (mg/L as CaCO₃)'), ('hardness_mg_l', 'Total hardness (mg/L as CaCO₃)'), ('co2_mg_l', 'Carbon dioxide (mg/L free CO₂)'), ('tan_mg_l', 'Total ammonia nitrogen (mg/L TAN as N)'), ('nitrite_n_mg_l', 'Nitrite (mg/L NO₂ as N)'), ('nitrate_n_mg_l', 'Nitrate (mg/L NO₃ as N)'), ('tgp_pct', 'Total gas pressure (% of barometric pressure)'), ('salinity_ppt', 'Salinity (‰, g/kg)'), ('conductivity_25_us_cm', 'Conductivity at 25 °C (µS/cm, temperature-compensated)'), ('turbidity_ntu', 'Turbidity (NTU)'), ('nh3_n_mg_l', 'Un-ionised ammonia (mg/L NH₃ as N)'), ('nh4_n_mg_l', 'Ammonium (mg/L NH₄⁺ as N)')], editable=False, max_length=30, verbose_name='Parameter'),
        ),
        migrations.RunPython(seed, unseed),
    ]
