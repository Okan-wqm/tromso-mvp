"""The site's altitude gets its range (F-089): 0 .. 5000 m, held by the database (owner decision 2026-11-06: no site lies
below sea level; a minus sign is a slip). An altitude outside it on an existing site, negative ones included, would set
the wrong pressure for the oxygen's saturation: it is moved into the site's notes with the day this migration runs and
emptied, so the oxygen is worked out at sea-level pressure and the pages say so until someone enters the right one.
Each such change is an entry of the activity log ("system", the old and the new altitude and notes), and going back
puts the altitude and the notes of each logged site back from it, where the site still holds what this migration left.

Numbered 0029 on top of main's 0028_site_timezone_required (renumbered at the merge of main, 2026-11-08); whoever lands
second renumbers again (one leaf per app)."""
import django.core.validators
from django.db import migrations, models
from django.utils import timezone

LOW, HIGH = 0, 5000
ALTITUDE, NOTES = 'Altitude (m)', 'Notes'
MESSAGE = 'Between 0 and 5000 m: sea level to the highest farms.'


def _logged(apps, site, before, after):
    apps.get_model('core', 'AuditLog').objects.create(
        user=None, user_name='system', action='update', entity_type='site', entity_id=str(site.pk),
        entity_label=site.name[:255], changes={ALTITUDE: [before[0], after[0]], NOTES: [before[1], after[1]]})


def out_of_range(apps, schema_editor):
    Site = apps.get_model('farm', 'Site')
    day = timezone.localdate().isoformat()
    for site in Site._base_manager.filter(models.Q(altitude__lt=LOW) | models.Q(altitude__gt=HIGH)):
        before = (str(site.altitude), site.notes)
        note = f'Altitude before migration 0029 ({day}), outside {LOW} .. {HIGH} m: {site.altitude}'
        site.notes = f'{site.notes}\n{note}' if site.notes else note
        site.altitude = None
        site.save(update_fields=['altitude', 'notes'])
        _logged(apps, site, before, (None, site.notes))


def back(apps, schema_editor):
    """Puts back what `out_of_range` moved, from its log entries (the newest per site), and logs that too: only on a site
    that still holds what the migration left (no altitude and the very notes it wrote); a site whose altitude or notes
    were changed since keeps them (a corrected altitude is never replaced by the old slip) and is named in the output."""
    Site, AuditLog = apps.get_model('farm', 'Site'), apps.get_model('core', 'AuditLog')
    entries = (AuditLog.objects.filter(entity_type='site', user_name='system', changes__has_key=ALTITUDE)
               .order_by('created_at'))
    restored = {}
    for entry in entries:
        old, new = entry.changes.get(ALTITUDE, [None, None]), entry.changes.get(NOTES, ['', ''])
        if old[0] is not None and old[1] is None and 'migration 0029' in (new[1] or ''):
            restored[entry.entity_id] = (old[0], new[0], new[1])
    for site in Site._base_manager.filter(pk__in=list(restored)):
        altitude, notes, left = restored[str(site.pk)]
        if site.altitude is not None or site.notes != left:
            print(f'\n  0029 back: {site.name} changed since the migration, kept as it is.')
            continue
        before = (None, site.notes)
        site.altitude, site.notes = altitude, notes
        site.save(update_fields=['altitude', 'notes'])
        _logged(apps, site, before, (altitude, notes))


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0028_site_timezone_required'),
        ('core', '0007_audit_severity'),
    ]

    operations = [
        migrations.RunPython(out_of_range, back),
        migrations.AlterField(
            model_name='site',
            name='altitude',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True, validators=[django.core.validators.MinValueValidator(0, MESSAGE), django.core.validators.MaxValueValidator(5000, MESSAGE)], verbose_name='Altitude (m)'),
        ),
        migrations.AddConstraint(
            model_name='site',
            constraint=models.CheckConstraint(condition=models.Q(('altitude__isnull', True), models.Q(('altitude__gte', 0), ('altitude__lte', 5000)), _connector='OR'), name='chk_sites_altitude_range', violation_error_message=MESSAGE),
        ),
    ]
