"""The site's altitude gets its physical range (F-089): -500 .. 5000 m, held by the database. An altitude outside it on an
existing site is a slip (a minus sign, two zeros too many) that would set an impossible pressure for the oxygen's
saturation: it is moved into the site's notes with the day, as 0023 did with an organisation number that was not one, and
emptied, so the oxygen is worked out at sea-level pressure and the pages say so until someone enters the right one."""
import django.core.validators
from django.db import migrations, models

LOW, HIGH = -500, 5000


def out_of_range(apps, schema_editor):
    Site = apps.get_model('farm', 'Site')
    for site in Site._base_manager.filter(models.Q(altitude__lt=LOW) | models.Q(altitude__gt=HIGH)):
        note = f'Altitude before 2026-11-06, outside {LOW} .. {HIGH} m: {site.altitude}'
        site.notes = f'{site.notes}\n{note}' if site.notes else note
        site.altitude = None
        site.save(update_fields=['altitude', 'notes'])


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0026_production_form_other'),
    ]

    operations = [
        migrations.RunPython(out_of_range, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='site',
            name='altitude',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True, validators=[django.core.validators.MinValueValidator(-500, 'Between -500 and 5000 m: the shore of the Dead Sea to the highest farms.'), django.core.validators.MaxValueValidator(5000, 'Between -500 and 5000 m: the shore of the Dead Sea to the highest farms.')], verbose_name='Altitude (m)'),
        ),
        migrations.AddConstraint(
            model_name='site',
            constraint=models.CheckConstraint(condition=models.Q(('altitude__isnull', True), models.Q(('altitude__gte', -500), ('altitude__lte', 5000)), _connector='OR'), name='chk_sites_altitude_range', violation_error_message='Between -500 and 5000 m: the shore of the Dead Sea to the highest farms.'),
        ),
    ]
