from datetime import date

from django.core.management.base import BaseCommand, CommandError

from farm.management import guard
from farm.models import Tank
from farm.water import degree_days, services


class Command(BaseCommand):
    help = ('The actions of a person on the closed days of the temperature probes, each through the withdrawal guard '
            '(it shows the question of the guard and writes nothing until --acknowledge carries its fingerprint): '
            '"backfill" writes the probe days of some units for days before they were closed, from the readings and '
            'the bindings as they stand now; "correct" voids one closed day and works it out again; "list" shows the '
            'days of some units.')

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest='action', required=True)
        backfill = actions.add_parser('backfill')
        backfill.add_argument('--units', nargs='+', required=True, help='The codes of the units.')
        backfill.add_argument('--first', type=date.fromisoformat, required=True, help='The first day, YYYY-MM-DD.')
        backfill.add_argument('--last', type=date.fromisoformat, required=True, help='The last day, YYYY-MM-DD.')
        guard.add_arguments(backfill)
        correct = actions.add_parser('correct')
        correct.add_argument('--id', type=int, required=True, help='The id of the probe day (see "list").')
        guard.add_arguments(correct)
        listing = actions.add_parser('list')
        listing.add_argument('--units', nargs='+', required=True, help='The codes of the units.')

    def units(self, codes):
        found = list(Tank.objects.filter(code__in=codes).select_related('production_department__site'))
        missing = sorted(set(codes) - {unit.code for unit in found})
        if missing:
            raise CommandError(f'No unit with the code {", ".join(missing)}.')
        return found

    def handle(self, *args, **options):
        action = options['action']
        if action == 'list':
            for row in degree_days.probe_days_of(self.units(options["units"])):
                state = 'voided' if row.voided_at else 'counts' if row.counts else 'does not count'
                self.stdout.write(f'{row.pk}\t{row.day.isoformat()}\t{row.point or row.system}\t#{row.channel_no}\t'
                                  f'{row.mean_c} °C\t{row.hours} h\t{row.how}\t{state}')
            return
        user = guard.person(options['by'])
        if action == 'backfill':
            rows = guard.asked(self, lambda: services.backfill_probe_days(
                user, units=self.units(options['units']), first=options['first'], last=options['last'],
                reason=options['reason'], withdrawal_ack=options['acknowledge']))
            self.stdout.write(f'{len(rows)} probe day rows written, {sum(row.counts for row in rows)} that count.')
            return
        row = degree_days.probe_day(options["id"])
        if row is None:
            raise CommandError(f'No probe day with the id {options["id"]}.')
        made = guard.asked(self, lambda: services.correct_probe_day(user, row, options['reason'],
                                                                    withdrawal_ack=options['acknowledge']))
        if made is None:
            self.stdout.write('Voided; the channel answers nothing for that day now.')
        else:
            self.stdout.write(f'Voided; the day is now {made.mean_c} °C '
                              f'({"counts" if made.counts else "does not count"}).')
