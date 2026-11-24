"""The production team today on the redesigned Production overview (config.views.team_today): the HR board of the
production people (hr.read.board, realm production), tile for tile as Today & attendance says it, so the overview and
the HR page cannot disagree; only for a person who may read attendance."""
from datetime import time
from unittest import mock

from django.urls import reverse

from config.views import team_today
from farm.models import ProductionDepartment

from .. import read, scope
from ..models import SchedulingSettings, Shift, ShiftAssignment
from .helpers import user
from .helpers_people import PeopleTestCase, employee, place
from .test_attendance import DAY, PUNCH_PERMS, at, punch


class TeamTodayTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14), grace_minutes=10)
        self.lead = user('boss', *PUNCH_PERMS, group='Board role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.lead)
        ben, cy = employee('E-80', 'Bergh'), employee('E-81', 'Cyr')
        for person in (ben, cy):
            place(person, self.dept_a)
        for person in (self.in_a, ben, cy):
            ShiftAssignment.objects.create(employee=person, day=DAY, shift=early)
        punch(self.in_a, at(6, 3))                                   # here
        punch(ben, at(6, 40), at(9))                                  # done
        SchedulingSettings.get()                                      # Cyr: absent at 10:00
        clock = mock.patch('django.utils.timezone.now', return_value=at(10))
        clock.start()
        self.addCleanup(clock.stop)

    def test_the_tiles_are_the_boards_of_the_production_people(self):
        found = team_today(self.lead)
        board = read.board(self.lead, at(10), realm=scope.PRODUCTION)
        self.assertEqual([(tile['key'], tile['count']) for tile in found['tiles']],
                         [(tile.key, tile.count) for tile in board.tiles if tile.key != 'forgotten'])
        counts = {tile['key']: tile['count'] for tile in found['tiles']}
        self.assertEqual((counts['here'], counts['done'], counts['absent']), (1, 1, 1))
        self.assertEqual(found['planned'], sum(counts.values()))
        self.assertEqual(found['url'], reverse('hr:production_today'))
        self.assertEqual([str(tile['label']) for tile in found['tiles']],
                         ['Upcoming', 'Here now', 'Not in yet', 'Absent', 'On leave', 'Done'])

    def test_nobody_without_the_right_to_read_attendance(self):
        self.assertIsNone(team_today(user('nobody')))
