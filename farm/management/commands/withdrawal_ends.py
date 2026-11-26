"""manage.py withdrawal_ends: the ends of every open withdrawal and fast, before and after a change of the rule.

`dump` is written to run UNCHANGED on the code before the change as well (the landing copies this one file into the old
checkout): it reads only what both have (`withdrawal.of_units`, `stock.read.stock_of`, `fasting.fasts`)."""
import json
import uuid
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import translation

from farm.handling import fasting
from farm.health import withdrawal
from farm.models import Tank
from farm.stock import read
from farm.stock.dates import local_today

FASTS_AHEAD = timedelta(days=366)      # the planned handlings whose fast is dumped: a year ahead


def _day(value):
    return value.isoformat() if value is not None else None


def dump():
    """{'withdrawals': {"<treatment id>|<batch id>": {...}}, 'fasts': {"<plan item id>": {...}}} as the code that runs
    it works them out now: every withdrawal from a course that holds fish in a unit today (its end without a wait for
    a closing where the code knows one; `until` otherwise), and the first fasting day of every open planned handling
    from today on."""
    units = list(Tank.objects.select_related('production_department__site').order_by('code'))
    stocked = [unit for unit in units if unit.pk in read.stock_of(units)]
    withdrawals = {}
    for unit in stocked:
        for hold in withdrawal.of_units([unit]).get(unit.pk, []):
            held = getattr(hold, 'withdrawal', hold)
            if held.treatment is None:
                continue
            withdrawals[f'{held.treatment.pk}|{held.batch_id}'] = {
                'unit': unit.code, 'medicine': str(held.treatment.medicine),
                'last_day': _day(held.treatment.end_date), 'until': _day(getattr(held, 'settled', held.until)),
                'estimated': bool(held.estimated)}
    fasts = {}
    for unit in units:
        today = local_today(unit)
        for fast in set(fasting.fasts([unit], today, today + FASTS_AHEAD).values()):
            fasts[str(fast.item.pk)] = {'unit': unit.code, 'on': _day(fast.on), 'first_day': _day(fast.first_day)}
    return {'withdrawals': withdrawals, 'fasts': fasts}


class Command(BaseCommand):
    help = ('The landing step of a change of the withdrawal rule. "dump --out FILE": the end of every withdrawal that '
            'holds fish today and the first fasting day of every open planned handling, as this code works them out '
            '(run it on the code BEFORE the change, then again after). "compare FILE": against a dump made before, '
            'every withdrawal that would now end EARLIER or holds nobody any more, every one that ends later, and '
            'every fast that moved; it fails when an end moved earlier, unless --floor stores each such end as a '
            'floor (the withdrawal then ends no earlier than it did, said in its text, until a person lifts the '
            'floor through the withdrawal guard: manage.py withdrawal_floors).')

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest='action', required=True)
        made = actions.add_parser('dump')
        made.add_argument('--out', required=True, help='The file the dump is written to (JSON).')
        compared = actions.add_parser('compare')
        compared.add_argument('file', help='The dump made before the change.')
        compared.add_argument('--floor', action='store_true', help=(
            'Store every end that would move earlier as a floor, so that no withdrawal ends earlier than it did.'))
        compared.add_argument('--reason', default='', help='Why the rule changed: kept with each floor (with --floor).')

    def handle(self, *args, **options):
        with translation.override('en'):
            if options['action'] == 'dump':
                found = dump()
                with open(options['out'], 'w', encoding='utf-8') as file:
                    json.dump(found, file, indent=1, sort_keys=True)
                self.stdout.write(f'{len(found["withdrawals"])} withdrawals and {len(found["fasts"])} fasts written '
                                  f'to {options["out"]}.')
                return
            self.compare(options)

    def compare(self, options):
        from farm.health import services
        from farm.models.health import FloorOrigin
        if options['floor'] and not options['reason'].strip():
            raise CommandError('--floor needs --reason: what changed the rule (it is kept with every floor).')
        with open(options['file'], encoding='utf-8') as file:
            before = json.load(file)
        was = {}
        for key, row in before['withdrawals'].items():
            treatment_id, batch_id = key.split('|')
            was[(treatment_id, batch_id)] = date.fromisoformat(row['until']) if row['until'] else None
        now = withdrawal.ends_now()
        # the keys as the file holds them (text): the readers' are ids
        ends = {(str(treatment_id), str(batch_id)): held for (treatment_id, batch_id), held in now.items()}
        moved = withdrawal.earlier({(uuid.UUID(treatment_id), uuid.UUID(batch_id)): day
                                    for (treatment_id, batch_id), day in was.items()}, now)
        for each in moved:
            row = before['withdrawals'][f'{each.treatment.pk}|{each.batch_id}']
            after = ('no withdrawal of these fish any more' if each.now is None
                     else _day(each.now.settled) or 'unknown')
            self.stdout.write(self.style.ERROR(
                f'EARLIER\t{row["unit"]}\t{row["medicine"]}\tlast day {row["last_day"]}\twas {row["until"] or "unknown"}'
                f'\tnow {after}'))
        for key, day in sorted(was.items()):
            held = ends.get(key)
            if held is not None and day is not None and (held.settled is None or held.settled > day):
                row = before['withdrawals']['|'.join(key)]
                self.stdout.write(f'later\t{row["unit"]}\t{row["medicine"]}\tlast day {row["last_day"]}\t'
                                  f'was {row["until"]}\tnow {_day(held.settled) or "unknown"}')
        fasts = dump()['fasts']
        for key, row in sorted(before['fasts'].items()):
            if key in fasts and fasts[key]['first_day'] != row['first_day']:
                self.stdout.write(f'fast\t{row["unit"]}\thandling on {row["on"]}\tstarted {row["first_day"] or "unknown"}'
                                  f'\tnow {fasts[key]["first_day"] or "unknown"}')
        self.stdout.write(f'{len(was)} withdrawals compared: {len(moved)} would end earlier or hold nobody any more.')
        if not moved:
            return
        if not options['floor']:
            raise CommandError('An end moved EARLIER: stop the landing, or run it again with --floor and --reason so '
                               'that each such withdrawal ends no earlier than it did.')
        floors = services.set_floors(moved, FloorOrigin.LANDING, options['reason'].strip())
        self.stdout.write(self.style.WARNING(
            f'{len(floors)} floors set: each of those withdrawals ends no earlier than it did. Harvests a later end '
            'brought inside a withdrawal: manage.py check_withdrawal.'))

