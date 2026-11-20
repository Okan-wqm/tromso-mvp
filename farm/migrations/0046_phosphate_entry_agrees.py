"""A phosphate entered as PO4 and the phosphorus stored for it agree (the verification of 2026-11-18, V-F): the check of
0045 held the unit and the entry together but not the two numbers (15.35 as PO4 stood beside a P of 99). Now the entry
divided by the unit's factor (3.0661887, PO4 over P at seven decimals) is the stored P within its rounding (0.0051:
half a step of the column and a hundredth of a step to spare), as farm/water/services.as_p writes it. Every row 0045's
doors wrote passes (the stored P is that quotient rounded half up). The check is dropped and added again, validated:
as 0045, an ACCESS EXCLUSIVE lock on water_measurements and its chunks while they are scanned (land with the server
stopped). Back, 0045's check returns."""

import django.db.models.expressions
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0045_phosphate_unit'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='watermeasurement',
            name='chk_water_measurements_phosphate_unit',
        ),
        migrations.AddConstraint(
            model_name='watermeasurement',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('phosphate_as_measured__isnull', True), ('phosphate_unit', '')), models.Q(('phosphate_as_measured__gte', 0), ('phosphate_as_measured__isnull', False), ('phosphate_p_mg_l__gte', django.db.models.expressions.CombinedExpression(django.db.models.expressions.CombinedExpression(models.F('phosphate_as_measured'), '/', models.Value(Decimal('3.0661887'))), '-', models.Value(Decimal('0.0051')))), ('phosphate_p_mg_l__isnull', False), ('phosphate_p_mg_l__lte', django.db.models.expressions.CombinedExpression(django.db.models.expressions.CombinedExpression(models.F('phosphate_as_measured'), '/', models.Value(Decimal('3.0661887'))), '+', models.Value(Decimal('0.0051')))), ('phosphate_unit', 'po4')), _connector='OR'), name='chk_water_measurements_phosphate_unit'),
        ),
    ]
