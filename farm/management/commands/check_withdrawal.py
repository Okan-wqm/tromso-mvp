from django.core.management.base import BaseCommand
from django.utils import translation

from farm.health import withdrawal
from farm.handling.withdrawal import source_key
from farm.models import Batch, HandlingAcknowledgement, Tank, WithdrawalAcknowledgement
from farm.models.handling import AcknowledgedWarning
from farm.stock import read


class Command(BaseCommand):
    help = ('Works out the medicine withdrawal of the fish in every unit from scratch (the treatments, the stock '
            'ledger and the water samples) and lists every batch a withdrawal holds today, with its end and why; then '
            'every harvest already recorded inside a withdrawal (medicated fish that may have gone to food), however it '
            'came to, and whether someone acknowledged it.')

    def handle(self, *args, **options):
        with translation.override('en'):
            self.held_now()
            self.harvested_inside()

    def held_now(self):
        units = list(Tank.objects.select_related('production_department__site').order_by('code'))
        stock = read.stock_of(units)                     # one fold for every unit
        stocked = [unit for unit in units if unit.pk in stock]
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

    def harvested_inside(self):
        found = withdrawal.harvests_inside()
        operations = {each.operation_id for each in found}
        # An acknowledgement counts for the harvest, the batch and the withdrawal it names, never for another one, and up
        # to the end it was given for: a withdrawal that ends later now is not acknowledged (cross-review 2, 8).
        given = {}
        for operation, batch, source, until in HandlingAcknowledgement.objects.filter(
                operation_id__in=operations, warning=AcknowledgedWarning.WITHDRAWAL, batch__isnull=False).values_list(
                'operation_id', 'batch_id', 'withdrawal_source', 'withdrawal_until'):
            given.setdefault((operation, batch, source), []).append(('the harvest', until))
        for row in WithdrawalAcknowledgement.objects.filter(harvest_id__in=operations):
            given.setdefault((row.harvest_id, row.batch_id, row.source), []).append((f'the {row.record_type}', row.until))
        for each in found:
            line = each.line
            end = (each.until.isoformat() if each.until else 'unknown') + (' (estimated)' if each.approximate else '')
            facility = each.facility.name if each.facility is not None else 'an unknown facility'
            # The acknowledgements name the batch that is held: the harvested one, or one that shared its unit (S-02).
            pair = (each.operation_id, each.batch.pk, source_key(each.withdrawal.source))
            acknowledged = self.acknowledged(given.get(pair, []), each.until)
            whose = '' if each.own else f' of {each.batch.code}, in the same unit,'
            self.stdout.write(self.style.ERROR(
                f'Harvest of {line.operation.date.isoformat()} from {line.unit.code} · {line.batch.code} '
                f'({each.fish} fish to {facility}) lies inside a withdrawal{whose} until {end}: '
                f'{withdrawal.describe(each.withdrawal)} {acknowledged}'))
        if found:
            count = len({each.same_harvest() for each in found})
            self.stdout.write(self.style.ERROR(f'{count} harvest{" lies" if count == 1 else "s lie"} inside a medicine '
                                               'withdrawal.'))
        else:
            self.stdout.write(self.style.SUCCESS('No harvest lies inside a medicine withdrawal.'))

    @staticmethod
    def acknowledged(rows, until):
        """How a harvest inside a withdrawal ending `until` (None: unknown) was acknowledged: by the acknowledgement that
        covers that end (given for an end as late or later), else not, with the end the latest one was given for."""
        covering = [(what, given) for what, given in rows if given is None or (until is not None and until <= given)]
        if covering:
            return f'Acknowledged when {covering[0][0]} was recorded.'
        if rows:
            latest = max((given for _what, given in rows), key=lambda day: day.toordinal())
            now = until.isoformat() if until else 'unknown'
            return f'Not acknowledged (acknowledged until {latest.isoformat()}; now {now}).'
        return 'Not acknowledged.'
