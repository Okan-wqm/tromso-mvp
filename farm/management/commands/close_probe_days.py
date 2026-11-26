from django.core.management.base import BaseCommand, CommandError

from farm.water import services


def _count(number, word):
    return f'{number} {word}{"" if number == 1 else "s"}'


class Command(BaseCommand):
    help = ('Closes the days of the temperature probes that are over (farm.models.ProbeDay, what the degree-days of a '
            'medicine withdrawal and a purging fast read): for every clock, each day not closed yet, oldest first. '
            'A withdrawal in force whose end the closed days would move earlier keeps the end it had as a floor. '
            'The jobs of the server run it every hour; a day is closed once.')

    def handle(self, *args, **options):
        try:
            rows, closings, floors = services.close_probe_days()
        except services.SensorsUnread as error:
            raise CommandError(f'{error} The days stay not closed and are tried again at the next run.') from None
        for closing in closings:
            self.stdout.write(f'closed {closing.timezone} {closing.day.isoformat()}: '
                              f'{_count(closing.probe_days, "probe day")} that count')
        self.stdout.write(f'{_count(len(closings), "day")} closed, {_count(len(rows), "row")} written.')
        for floor in floors:
            day = floor.not_before.isoformat() if floor.not_before else 'unknown'
            self.stdout.write(self.style.WARNING(
                f'Floor set: {floor.batch.code} is held to {day} (the closed days would have ended its withdrawal '
                'earlier). Lift it with manage.py withdrawal_floors.'))
