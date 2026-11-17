from django.core.management.base import BaseCommand
from django.utils import translation

from farm.health import withdrawal
from farm.handling.withdrawal import harvest_from, source_key
from farm.models import Batch, HandlingAcknowledgement, Tank, WithdrawalAcknowledgement
from farm.models.handling import AcknowledgedWarning
from farm.stock import read


def _end(until, approximate=False):
    """A withdrawal's end in the one wording of every page (harvest_from), the day written as this command writes
    days: harvest from 2026-11-25, harvest from about 2026-11-25, end unknown."""
    return harvest_from(until, approximate, shown=lambda day: day.isoformat())


class Command(BaseCommand):
    help = ('Works out the medicine withdrawal of the fish in every unit from scratch (the treatments, the stock '
            'ledger and the water samples) and lists the fish a withdrawal holds today, unit by unit, with the end and '
            'why (the fish that were exposed, where they were moved, and the fish that shared a unit with them); then '
            'every harvest already recorded inside a withdrawal (medicated fish that may have gone to food), however it '
            'came to, and whether someone acknowledged it.')

    def add_arguments(self, parser):
        parser.add_argument('--listing', action='store_true', help=(
            'Write the same two lists as stable, sorted, tab-separated lines and nothing else: "held" (unit, batch, '
            'end, about, the withdrawal\'s source, why) and "inside" (the harvest\'s day, unit, batch, fish, the '
            'batch the withdrawal is of, end, about, source). Made to be compared with a diff: run it before and '
            'after a change of the rule (a landing) on the same data and keep both files with the landing.'))

    def handle(self, *args, **options):
        with translation.override('en'):
            if options['listing']:
                return self.listing()
            self.held_now()
            self.unresolved()
            self.harvested_inside()

    def unresolved(self):
        """The old courses whose end is unknown and which hold nobody any more (withdrawal rule 8)."""
        found = withdrawal.unresolved()
        for batch, held in found:
            self.stdout.write(self.style.WARNING(f'Unresolved old course · {withdrawal.unresolved_text(batch, held)}'))
        if found:
            self.stdout.write(self.style.WARNING(
                f'{len(found)} unresolved old course{"" if len(found) == 1 else "s"}: the end is unknown and the '
                'fish are no longer held (Platform settings: an unknown withdrawal end holds for a number of days). '
                'Give each an end.'))

    def listing(self):
        """The two lists as lines that say the same for the same facts whatever the wording of the pages: ids are not
        written (codes and days are), the lines are sorted, and only what both the batch rule and the lots rule
        have is read (`of_units`, `harvests_inside`), so this file runs unchanged on a checkout of the rule before
        S-03 for the "before" listing."""
        units = list(Tank.objects.select_related('production_department__site').order_by('code'))
        stocked = [unit for unit in units if unit.pk in read.stock_of(units)]
        held = withdrawal.of_units(stocked)
        codes = dict(Batch.all_objects.values_list('pk', 'code'))

        def end(until):
            return until.isoformat() if until is not None else 'unknown'

        def source(item):
            found = item.source
            day = found.start_date if hasattr(found, 'start_date') else found.date
            return f'{found._meta.model_name} of {day.isoformat()}'

        lines = [('held', unit.code, codes[item.batch_id], end(item.until), 'about' if item.estimated else '',
                  source(item), withdrawal.describe(item))
                 for unit in stocked for item in held.get(unit.pk, [])]
        lines += [('inside', each.line.operation.date.isoformat(), each.line.unit.code, each.line.batch.code,
                   str(each.fish), each.batch.code, end(each.until), 'about' if each.approximate else '',
                   source(each.withdrawal))
                  for each in withdrawal.harvests_inside()]
        # The old courses of unknown end that hold nobody any more (rule 8): on a checkout that has them.
        lines += [('unresolved', codes[held.batch_id], source(held), withdrawal.describe(held))
                  for _batch, held in getattr(withdrawal, 'unresolved', lambda: [])()]
        for line in sorted(lines):
            self.stdout.write('\t'.join(line))

    def held_now(self):
        units = list(Tank.objects.select_related('production_department__site').order_by('code'))
        stock = read.stock_of(units)                     # one fold for every unit
        stocked = [unit for unit in units if unit.pk in stock]
        held = withdrawal.of_units(stocked)
        batches = Batch.all_objects.in_bulk({item.batch_id for items in held.values() for item in items})
        for unit in stocked:
            for item in held.get(unit.pk, []):
                self.stdout.write(f'{unit.code} · {batches[item.batch_id].code}: {_end(item.until, item.estimated)}. '
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
            facility = each.facility.name if each.facility is not None else 'an unknown facility'
            # The acknowledgements name the batch that is held: the harvested one, or one that shared its unit (S-02).
            # ... or the harvested batch itself, when its fish are held because they shared a unit before (S-03: the
            # harvest's warning named them, the unit's line).
            source = source_key(each.withdrawal.source)
            rows = [row for batch_id in dict.fromkeys((each.batch.pk, line.batch_id))
                    for row in given.get((each.operation_id, batch_id, source), [])]
            acknowledged = self.acknowledged(rows, each.until)
            if each.own:
                whose = ''
            elif each.beside:
                whose = f' of {each.batch.code}, in the same unit'
            else:                # the fish harvested met it, or fish held with it, in another unit before (S-03)
                whose = f' of {each.batch.code}, through {each.hold.via_unit} shared with {each.hold.via_batch}'
            self.stdout.write(self.style.ERROR(
                f'Harvest of {line.operation.date.isoformat()} from {line.unit.code} · {line.batch.code} '
                f'({each.fish} fish to {facility}) lies inside a withdrawal{whose} ({_end(each.until, each.approximate)}): '
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
            return f'Not acknowledged (acknowledged for {_end(latest)}; now {_end(until)}).'
        return 'Not acknowledged.'
