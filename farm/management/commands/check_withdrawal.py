from django.core.management.base import BaseCommand
from django.utils import translation

from farm.health import withdrawal
from farm.models import Batch, Tank
from farm.stock import read


class Command(BaseCommand):
    help = ('Works out the medicine withdrawal of the fish in every unit from scratch (the treatments, the stock '
            'ledger and the water samples) and lists every batch a withdrawal holds today, with its end and why.')

    def handle(self, *args, **options):
        with translation.override('en'):
            units = list(Tank.objects.select_related('production_department__site').order_by('code'))
            stocked = [unit for unit in units if unit.pk in read.stock_of(units)]
            held = withdrawal.of_units(stocked)
            batches = Batch.all_objects.in_bulk({item.batch_id for items in held.values() for item in items})
            for unit in stocked:
                for item in held.get(unit.pk, []):
                    end = (item.until.isoformat() if item.until else 'unknown') + (' (estimated)' if item.estimated
                                                                                    else '')
                    self.stdout.write(f'{unit.code} · {batches[item.batch_id].code}: until {end}. '
                                      f'{withdrawal.describe(item)}')
            self.stdout.write(self.style.SUCCESS(f'{len(held)} of {len(stocked)} units with fish are under a '
                                                 f'medicine withdrawal.'))
