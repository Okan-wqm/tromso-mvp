"""The chip beside a tank booked to an experiment (farm/placements.py, filled by `experiments.ready()`): registered, read from the
experiment's own placements on each unit's day, shown on Production units, its drawer and the meal board for those who may
read experiments, never a reason a farm page fails, and queries that do not grow with the units."""
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation

from core import softdelete
from core.models import Profile
from farm import placements
from farm.tests.helpers import role
from farm.tests.test_stock import make_unit

from .. import read
from ..models import ReplicateUnit
from .test_overview import RanTrialCase
from .test_pages import person


class ChipTests(RanTrialCase):
    def chips(self, units=None, user=None):
        return read.chips(units or self.tanks, user or self.user)

    def test_the_experiments_provider_is_registered_with_the_farm(self):
        self.assertIn(read.chips, placements._providers)

    def test_a_booked_tank_has_its_experiment_group_and_replicate_and_an_unbooked_one_none(self):
        found = self.chips()
        label = f'{self.trial.code} · Control · R1'
        self.assertEqual([chip.label for chip in found[self.tanks[0].pk]], [label])
        self.assertEqual(found[self.tanks[0].pk][0].title, 'Diet trial (Running)')
        self.assertEqual(found[self.tanks[0].pk][0].url, reverse('experiments:experiment_detail', args=[self.trial.pk]))
        self.assertEqual([chip.label for chip in found[self.tanks[3].pk]], [f'{self.trial.code} · High feed · R2'])
        self.assertNotIn(self.tanks[4].pk, found)
        self.assertEqual(sorted(found), sorted(tank.pk for tank in self.tanks[:4]))

    def test_a_draft_reserves_its_tank_and_shows_it_as_a_draft(self):
        draft = self.experiment('Next', starts_on=self.today)
        self.placement(self.replicate(self.group(draft, 'A'), 1), self.tanks[5])
        chip = self.chips()[self.tanks[5].pk][0]
        self.assertEqual((chip.label, chip.title), (f'{draft.code} · A · R1', 'Next (Draft)'))

    def test_a_placement_that_has_ended_or_not_begun_shows_nothing(self):
        ReplicateUnit.objects.filter(unit=self.tanks[0]).update(until_on=self.day(1))
        later = self.experiment('Later', starts_on=self.today + timedelta(days=5))
        self.placement(self.replicate(self.group(later, 'A'), 1), self.tanks[6], first=5, last=60)
        found = self.chips()
        self.assertNotIn(self.tanks[0].pk, found)
        self.assertNotIn(self.tanks[6].pk, found)
        self.assertIn(self.tanks[1].pk, found)

    def test_only_those_who_may_read_experiments_see_a_chip(self):
        self.assertEqual(self.chips(user=person('plain', 'view_tank')), {})

    def test_a_deleted_experiments_tank_has_no_chip(self):
        other = self.experiment('Gone')
        self.placement(self.replicate(self.group(other, 'A'), 1), self.tanks[7])
        self.assertIn(self.tanks[7].pk, self.chips())
        softdelete.execute(softdelete.plan_delete(other), self.user)
        self.assertNotIn(self.tanks[7].pk, self.chips())

    def test_the_queries_do_not_grow_with_the_units(self):
        small, large = self.tanks[:2], self.tanks + [make_unit(f'Z-{n:02d}', self.hall) for n in range(30)]
        counts = []
        for units in (small, large):
            self.chips(units)                                   # the first call fills the permission cache
            with CaptureQueriesContext(connection) as queries:
                self.chips(units)
            counts.append(len(queries))
        self.assertEqual(counts[0], counts[1])

    def test_each_unit_is_read_on_its_own_day(self):
        ReplicateUnit.objects.filter(unit=self.tanks[0]).update(until_on=self.today)
        ahead = self.today + timedelta(days=1)                   # a site that is already tomorrow
        with mock.patch('experiments.read.local_today',
                        side_effect=lambda unit: ahead if unit.pk == self.tanks[0].pk else self.today):
            found = self.chips()
        self.assertNotIn(self.tanks[0].pk, found)
        self.assertIn(self.tanks[1].pk, found)


class PageTests(RanTrialCase):
    """The chip on Production units, in its drawer and on the meal board: shown, and a farm page that never depends on it."""

    def label(self, group='Control', number=1):
        return f'{self.trial.code} · {group} · R{number}'

    def test_production_units_shows_the_chip_in_the_row_and_the_drawer(self):
        page = self.client.get(reverse('farm:production_units'))
        self.assertContains(page, self.label(), count=1)
        self.assertContains(page, f'href="{reverse("experiments:experiment_detail", args=[self.trial.pk])}"')
        rows = {row['unit'].code: row['placements'] for row in page.context['rows']}
        self.assertEqual(len(rows['T-01']), 1)
        self.assertEqual(len(rows['T-05']), 0)
        drawer = self.client.get(reverse('farm:production_units'), {'unit': self.tanks[0].pk})
        self.assertEqual(len(drawer.context['drawer_placements']), 1)
        self.assertContains(drawer, self.label(), count=2)          # the row and the drawer's title
        other = self.client.get(reverse('farm:production_units'), {'unit': self.tanks[4].pk})
        self.assertEqual(other.context['drawer_placements'], ())

    def test_the_meal_board_shows_the_chip_of_each_booked_unit(self):
        page = self.client.get(reverse('farm:meal_board'))
        self.assertContains(page, self.label())
        self.assertContains(page, self.label('High feed', 2))

    def test_a_person_who_may_not_read_experiments_sees_no_chip(self):
        self.user.groups.clear()
        self.user.groups.add(role('Farm only', 'view_tank', 'view_feedingrecord', 'view_stockoperation'))
        for url in (reverse('farm:production_units'), reverse('farm:meal_board')):
            self.assertNotContains(self.client.get(url), self.trial.code)

    def test_a_failing_provider_never_breaks_a_farm_page(self):
        with mock.patch('experiments.read.placements', side_effect=RuntimeError('down')):
            with self.assertLogs(placements.logger, 'ERROR'):
                units = self.client.get(reverse('farm:production_units'), {'unit': self.tanks[0].pk})
            with self.assertLogs(placements.logger, 'ERROR'):
                board = self.client.get(reverse('farm:meal_board'))
        for page in (units, board):
            self.assertEqual(page.status_code, 200)
            self.assertNotContains(page, self.trial.code)
        self.assertContains(units, 'T-01')

    def test_the_pages_speak_each_language_with_the_chip_on(self):
        self.addCleanup(translation.deactivate)
        for language in ('tr', 'nb'):
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            for url in (reverse('farm:production_units'), reverse('farm:meal_board')):
                page = self.client.get(url)
                self.assertContains(page, self.label(), msg_prefix=language)
                self.assertNotIn('%(', page.content.decode())


class MonitoringTests(RanTrialCase):
    """The monitoring card asks the same registry: a booked tank's card carries its experiment's chip."""

    def test_the_card_of_a_booked_tank_shows_its_experiment(self):
        from monitoring.tests import ALL_RIGHTS
        self.user.groups.add(role('Monitor', *ALL_RIGHTS))
        page = self.client.get(reverse('monitoring:monitor'), {'units': f'{self.tanks[0].pk},{self.tanks[4].pk}'})
        self.assertContains(page, f'{self.trial.code} · Control · R1', count=1)
