"""The health event's own "Mattilsynet notified at" goes (D-4): that Mattilsynet was told is the filing of a disease
notice, which the regulatory reports keep (docs/regulatory-reports.md, section 6). The times already recorded were moved
into filed notices by reports migration 0005, which runs before this one (its `run_before`); the reverse brings the
column back empty and reports' reverse copies the times into it."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0021_reports_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='healthevent',
            name='authority_notified_at',
        ),
    ]
