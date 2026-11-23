"""The optional phosphate (farm/water/parameters.py phosphate_p_mg_l) among the parameters an alarm deadband can be
set for: the choices and the two CHECKs with the new list (no row is seeded: a deadband is set by the farm)."""

from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0012_parameters_hardness_conductivity'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='parameterdeadband',
            name='chk_alarm_deadbands_parameter',
        ),
        migrations.RemoveConstraint(
            model_name='parameterdeadband',
            name='chk_alarm_deadbands_ceiling',
        ),
        migrations.AlterField(
            model_name='parameterdeadband',
            name='parameter',
            field=models.CharField(choices=[('temperature_c', 'Temperature (°C)'), ('oxygen_mg_l', 'Dissolved oxygen (mg/L O₂)'), ('oxygen_saturation_pct', 'Oxygen saturation (% of air saturation)'), ('ph', 'pH (NBS scale)'), ('alkalinity_mg_l', 'Alkalinity (mg/L as CaCO₃)'), ('hardness_mg_l', 'Total hardness (mg/L as CaCO₃)'), ('co2_mg_l', 'Carbon dioxide (mg/L free CO₂)'), ('tan_mg_l', 'Total ammonia nitrogen (mg/L TAN as N)'), ('nitrite_n_mg_l', 'Nitrite (mg/L NO₂ as N)'), ('nitrate_n_mg_l', 'Nitrate (mg/L NO₃ as N)'), ('tgp_pct', 'Total gas pressure (% of barometric pressure)'), ('salinity_ppt', 'Salinity (‰, g/kg)'), ('conductivity_25_us_cm', 'Conductivity at 25 °C (µS/cm, temperature-compensated)'), ('turbidity_ntu', 'Turbidity (NTU)'), ('phosphate_p_mg_l', 'Phosphate (mg/L PO₄ as P)'), ('nh3_n_mg_l', 'Un-ionised ammonia (mg/L NH₃ as N)')], max_length=30, verbose_name='Parameter'),
        ),
        migrations.AddConstraint(
            model_name='parameterdeadband',
            constraint=models.CheckConstraint(condition=models.Q(('parameter__in', ['temperature_c', 'oxygen_mg_l', 'oxygen_saturation_pct', 'ph', 'alkalinity_mg_l', 'hardness_mg_l', 'co2_mg_l', 'tan_mg_l', 'nitrite_n_mg_l', 'nitrate_n_mg_l', 'tgp_pct', 'salinity_ppt', 'conductivity_25_us_cm', 'turbidity_ntu', 'phosphate_p_mg_l', 'nh3_n_mg_l'])), name='chk_alarm_deadbands_parameter'),
        ),
        migrations.AddConstraint(
            model_name='parameterdeadband',
            constraint=models.CheckConstraint(condition=models.Q(('pk__in', []), models.Q(('deadband__lte', Decimal('43')), ('parameter', 'temperature_c')), models.Q(('deadband__lte', Decimal('50')), ('parameter', 'oxygen_mg_l')), models.Q(('deadband__lte', Decimal('400')), ('parameter', 'oxygen_saturation_pct')), models.Q(('deadband__lte', Decimal('10')), ('parameter', 'ph')), models.Q(('deadband__lte', Decimal('1000')), ('parameter', 'alkalinity_mg_l')), models.Q(('deadband__lte', Decimal('10000')), ('parameter', 'hardness_mg_l')), models.Q(('deadband__lte', Decimal('200')), ('parameter', 'co2_mg_l')), models.Q(('deadband__lte', Decimal('100')), ('parameter', 'tan_mg_l')), models.Q(('deadband__lte', Decimal('100')), ('parameter', 'nitrite_n_mg_l')), models.Q(('deadband__lte', Decimal('1000')), ('parameter', 'nitrate_n_mg_l')), models.Q(('deadband__lte', Decimal('150')), ('parameter', 'tgp_pct')), models.Q(('deadband__lte', Decimal('50')), ('parameter', 'salinity_ppt')), models.Q(('deadband__lte', Decimal('100000')), ('parameter', 'conductivity_25_us_cm')), models.Q(('deadband__lte', Decimal('4000')), ('parameter', 'turbidity_ntu')), models.Q(('deadband__lte', Decimal('100')), ('parameter', 'phosphate_p_mg_l')), models.Q(('deadband__lte', Decimal('100')), ('parameter', 'nh3_n_mg_l')), _connector='OR'), name='chk_alarm_deadbands_ceiling', violation_error_message='Wider than the parameter’s whole range.'),
        ),
    ]
