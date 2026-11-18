"""The unit a phosphate was entered in (the independent review of 2026-11-16, R3): a sample's phosphate_p_mg_l is always
as phosphorus; one entered as PO4 keeps its unit and the value as entered beside it (farm/water/services.as_p), and the
check holds the two together. Rows written before have neither (entered as P). Back, the two columns go."""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0044_phosphate'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='watermeasurement',
            name='phosphate_as_measured',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, verbose_name='Phosphate as entered, in its own unit'),
        ),
        migrations.AddField(
            model_name='watermeasurement',
            name='phosphate_unit',
            field=models.CharField(blank=True, choices=[('po4', 'as PO₄ (mg/L of phosphate)')], max_length=3, verbose_name='Unit the phosphate was entered in'),
        ),
        migrations.AddConstraint(
            model_name='watermeasurement',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('phosphate_as_measured__isnull', True), ('phosphate_unit', '')), models.Q(('phosphate_as_measured__gte', 0), ('phosphate_as_measured__isnull', False), ('phosphate_p_mg_l__isnull', False), ('phosphate_unit__in', ['po4'])), _connector='OR'), name='chk_water_measurements_phosphate_unit'),
        ),
    ]
