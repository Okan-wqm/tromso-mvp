"""What the growth plan's schema (0052) needs of the rows that were there before it:

- the weight source a weighing takes when it names none, "Manual sample" (code `manual`), and that source on every
  weighing line already in the ledger (they were all samples weighed by hand: there was no other way to enter one);
- on every feeding protocol that exists, the day the FCR began to be read between the bands: the day this migration
  runs. The days before it keep each band's own FCR, so nothing a protocol gave for a past day changes (owner decision
  Q3); a protocol made afterwards has no such day and is read between the bands throughout.

Backwards: the day and the lines' source are emptied, the seeded source removed."""
import uuid

from django.db import migrations
from django.utils import timezone

MANUAL = 'manual'
NAME = 'Manual sample'
NOTES = 'Fish netted and weighed by hand: the number weighed and their weight together, or the average.'


def write(apps, schema_editor):
    WeightSource = apps.get_model('farm', 'WeightSource')
    source = WeightSource.objects.filter(code=MANUAL).first()
    if source is None:
        source = WeightSource.objects.create(id=uuid.uuid4(), code=MANUAL, name=NAME, notes=NOTES)
    apps.get_model('farm', 'StockMovement').objects.filter(kind='weighing', weight_source__isnull=True).update(
        weight_source=source)
    apps.get_model('farm', 'FeedingProtocol').objects.filter(interpolated_from__isnull=True).update(
        interpolated_from=timezone.localdate())


def remove(apps, schema_editor):
    apps.get_model('farm', 'FeedingProtocol').objects.update(interpolated_from=None)
    apps.get_model('farm', 'StockMovement').objects.filter(weight_source__code=MANUAL).update(weight_source=None)
    apps.get_model('farm', 'WeightSource').objects.filter(code=MANUAL, created_by__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0052_production_plan_growth'),
    ]

    operations = [migrations.RunPython(write, remove)]
