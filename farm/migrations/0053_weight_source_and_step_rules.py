"""What the growth plan's schema (0052) needs of the rows that were there before it:

- the weight source a weighing takes when it names none, "Manual sample" (code `manual`), and that source on every
  weighing line already in the ledger (they were all samples weighed by hand: there was no other way to enter one);
- on every feeding protocol that exists, the between-band rule it has always followed: a step at the band's edge, for
  its FCR, its uneaten share and its SFR. So nothing an existing protocol gives changes, on any day (owner decision Q3:
  an assigned protocol is fixed); a protocol made afterwards is smooth between its bands unless its maker chooses
  otherwise, and an existing one is made smooth on a copy (Duplicate), or by its rule while it is not assigned.

Backwards: the lines' source is emptied and the seeded source removed; the rules go with their columns."""
import uuid

from django.db import migrations

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
    apps.get_model('farm', 'FeedingProtocol').objects.update(fcr_between='step', uneaten_between='step',
                                                             sfr_between='step')


def remove(apps, schema_editor):
    apps.get_model('farm', 'StockMovement').objects.filter(weight_source__code=MANUAL).update(weight_source=None)
    apps.get_model('farm', 'WeightSource').objects.filter(code=MANUAL, created_by__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0052_production_plan_growth'),
    ]

    operations = [migrations.RunPython(write, remove)]
