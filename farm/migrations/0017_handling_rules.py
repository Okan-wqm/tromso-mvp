"""The starting handling rules: one for every species per kind of handling, each saying where its value comes
from and that the farm's veterinarian is to check it (Setup › Reference data › Handling rules). They are the
farm's own rules from then on: edited, deleted or overridden per species on that tab, every change logged
there. Like the equipment type catalogue (0007), what a migration writes is not in the activity log.

The values (read 2026-11-02/03; the bug document's Harvest section has the sources):
- harvest 72 h: Mattilsynet asks for no feed left in the stomach and gut at slaughter (an outcome, no hours);
  gut-clearing feed withdrawal is typically 48-72 h (Hvas et al. 2024), slower in cold water; BIM and RSPCA
  advise no more than 72 h before harvest.
- transport 24 h, grading 24 h: BIM, feed withdrawal at least 24 to 48 h before crowding or grading; RSPCA
  caps it at 48 h (a maximum, not a minimum).
- treatment 24 h: BIM, commonly 24 to 48 h; RSPCA 2024 caps it at 48 h before physical delousing and 72 h
  before a freshwater bath; the medicine's own product information wins."""
import uuid

from django.db import migrations

VERIFY = 'Starting value: check it with your veterinarian. '
RULES = [
    ('harvest', 72, VERIFY + 'Mattilsynet asks that no feed is left in stomach and gut at slaughter (an outcome, no '
                    'hours). Gut-clearing feed withdrawal is typically 48–72 h (Hvas et al. 2024, Reviews in '
                    'Aquaculture, doi:10.1111/raq.12898), longer in cold water. BIM (2024) and RSPCA (2015) advise '
                    'no more than 72 h before harvest.'),
    ('transport', 24, VERIFY + 'BIM (2024, Fish Welfare During Handling): feed withdrawal at least 24 to 48 h before '
                      'crowding, by water temperature and fish size. RSPCA (2015, T 2.9): pre-transport fasting '
                      'never above 48 h unless a vet specifies it.'),
    ('grading', 24, VERIFY + 'BIM (2024): feed withdrawal at least 24 to 48 h before grading, by water temperature '
                    'and fish size. RSPCA (2015, FW 6.2): not above 48 h before grading. A grading is also checked '
                    'against the transport rule; the longer applies.'),
    ('treatment', 24, VERIFY + 'BIM (2024): withdrawal periods commonly 24 to 48 h before handling. RSPCA (2024): '
                      'as short as possible, at most 48 h before physical delousing and 72 h before a freshwater '
                      'bath. The medicine’s product information wins.'),
]


def write(apps, schema_editor):
    HandlingRule = apps.get_model('farm', 'HandlingRule')
    for kind, hours, note in RULES:
        if HandlingRule.objects.filter(kind=kind, species__isnull=True, is_deleted=False).exists():
            continue
        HandlingRule.objects.create(id=uuid.uuid4(), kind=kind, min_fasting_hours=hours, note=note)


def remove(apps, schema_editor):
    apps.get_model('farm', 'HandlingRule').objects.filter(
        species__isnull=True, created_by__isnull=True, note__in=[note for _kind, _hours, note in RULES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0016_harvest'),
    ]

    operations = [migrations.RunPython(write, remove)]
