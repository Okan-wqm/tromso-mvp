from django.core.management.base import BaseCommand, CommandError

from farm.health import services, withdrawal
from farm.management import guard


class Command(BaseCommand):
    help = ('The floors that keep a withdrawal from ending earlier than it was shown to (farm.models.WithdrawalFloor): '
            '"list" shows the live ones with the end the days counted give now; "lift" lifts one through the '
            'withdrawal guard (it shows the question of the guard and writes nothing until --acknowledge carries its '
            'fingerprint).')

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest='action', required=True)
        actions.add_parser('list')
        lift = actions.add_parser('lift')
        lift.add_argument('--id', type=int, required=True, help='The id of the floor (see "list").')
        guard.add_arguments(lift)

    def handle(self, *args, **options):
        if options['action'] == 'list':
            for floor in withdrawal.floors():
                held = withdrawal.end_of(floor.treatment, floor.batch_id)
                worked = held.worked_out.isoformat() if held is not None and held.worked_out else 'unknown'
                day = floor.not_before.isoformat() if floor.not_before else 'unknown'
                self.stdout.write(f'{floor.pk}\t{floor.batch.code}\t{floor.treatment.medicine}\tnot before {day}\t'
                                  f'the days give {worked}\t{floor.origin}\t{floor.reason}')
            return
        floor = next((each for each in withdrawal.floors() if each.pk == options['id']), None)
        if floor is None:
            raise CommandError(f'No live floor with the id {options["id"]}.')
        user = guard.person(options['by'])
        guard.asked(self, lambda: services.lift_floor(user, floor, options['reason'],
                                                      withdrawal_ack=options['acknowledge']))
        self.stdout.write('Lifted.')
