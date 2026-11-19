"""A pH scale per sensor pH channel (owner decision 1 of 2026-11-17; the water-chemistry audit of 2026-11-19, F1): the
scale the probe's calibration puts its values on, NBS for every channel there is (and for every other quantity), and the
moment it was last changed (none yet). The database default keeps the ingest's own inserts working (they name their
columns); the check holds a scale other than NBS, and a change of scale, to pH channels."""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sensors', '0012_phosphate'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='ph_scale',
            field=models.CharField(choices=[('nbs', 'NBS (a meter calibrated with NBS/NIST buffers)'), ('total', 'Total scale (calibrated with TRIS)'), ('sws', 'Seawater scale (SWS)'), ('free', 'Free scale')], db_default='nbs', default='nbs', max_length=5, verbose_name='Scale the pH is measured on'),
        ),
        migrations.AddField(
            model_name='channel',
            name='ph_scale_from',
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name='When the pH scale was changed'),
        ),
        migrations.AddConstraint(
            model_name='channel',
            constraint=models.CheckConstraint(condition=models.Q(('ph_scale__in', ['nbs', 'total', 'sws', 'free']), models.Q(('quantity', 'ph'), models.Q(('ph_scale', 'nbs'), ('ph_scale_from__isnull', True)), _connector='OR')), name='chk_sensors_channel_ph_scale', violation_error_message='Only a pH channel has a pH scale other than NBS.'),
        ),
    ]
