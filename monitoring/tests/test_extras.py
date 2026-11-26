"""The cleaner-fish line of a detailed card (read from `UnitStock.cleaner_stock`, never summed here) and the placement chips
(`farm.placements.of`, which fails open: absent, or raising, there is no chip and nothing else changes)."""
import sys
from types import SimpleNamespace
from unittest import mock

from django.urls import reverse

from farm.tests.test_cleaner_fish import CleanerFishTestCase

from .. import read
from . import ALL_RIGHTS, MonitoringCase, chosen
from farm.tests.helpers import may_record


class CleanerFishTests(CleanerFishTestCase):
    def setUp(self):
        super().setUp()
        self.reader = self.person('reader', *ALL_RIGHTS)
        self.client.force_login(self.reader)

    def person(self, username, *codenames):
        from django.contrib.auth import get_user_model
        from farm.tests.helpers import role
        user = get_user_model().objects.create_user(username, f'{username}@example.com', 'x')
        user.groups.add(role(f'{username} role', *codenames))
        return user

    def cards(self, mode):
        units = read.units_for(read.Params(units=(str(self.cage.pk),)))
        return read.cards(units, self.reader, chosen({unit.pk: mode for unit in units}))

    def test_the_unit_figures_are_the_production_fishs_and_the_detailed_card_says_the_cleaner_fish_beside_them(self):
        [card] = self.cards('detailed')
        self.assertEqual(card.stock.count, 2000)                      # the lumpfish are not in the unit's fish
        cleaner = card.stock.cleaner_stock
        self.assertEqual((cleaner.count, cleaner.biomass_kg), (10000, 500))
        html = self.client.get(reverse('monitoring:monitor'), {'full': '1', 'units': str(self.cage.pk), 'mode': 'detailed'}).content.decode()
        self.assertIn('Cleaner fish', html)
        self.assertIn('10,000', html)
        self.assertIn('500 kg', html)
        simple = self.client.get(reverse('monitoring:monitor'), {'full': '1', 'units': str(self.cage.pk)}).content.decode()
        self.assertNotIn('Cleaner fish', simple)                      # a simple card is the key figures

    def test_a_cage_with_salmon_and_lumpfish_is_not_ok_while_the_lumpfish_have_no_limit(self):
        """Cross review: the salmon's rows judge the water fine, the lumpfish beside them have none: never green."""
        from datetime import timedelta
        from decimal import Decimal
        from django.utils import timezone
        from farm.models import WaterLimit
        from farm.tests.helpers import point_of
        from farm.water import services as water_services
        for parameter, bounds in (('oxygen_mg_l', {'critical_low': Decimal(6)}),
                                  ('temperature_c', {'critical_high': Decimal(18)})):
            WaterLimit.objects.create(species=self.salmon, parameter=parameter, water_type='any', **bounds)
        may_record(self.user, 'add_watermeasurement')  # the water service asks (L-6)
        water_services.record(self.user, point=point_of(self.cage), measured_at=timezone.now() - timedelta(hours=1),
                              source='manual', values={'temperature_c': Decimal('9'), 'oxygen_mg_l': Decimal('9')})
        state = self.cards('simple')[0].state
        self.assertEqual(state.key, 'unjudged')
        self.assertIn('Temperature (°C): no limit for these fish', state.reasons)
        for parameter, bounds in (('oxygen_mg_l', {'critical_low': Decimal(5)}),
                                  ('temperature_c', {'critical_high': Decimal(17)})):
            WaterLimit.objects.create(species=self.lump, parameter=parameter, water_type='any', **bounds)
        self.assertNotEqual(self.cards('simple')[0].state.key, 'unjudged')

    def test_a_unit_without_cleaner_fish_has_no_such_line(self):
        html = self.client.get(reverse('monitoring:monitor'), {'full': '1', 'units': str(self.t1.pk), 'mode': 'detailed'}).content.decode()
        self.assertNotIn('Cleaner fish', html)


class ChipsTests(MonitoringCase):
    def cards(self):
        units = read.units_for(read.Params())
        return read.cards(units, self.reader, chosen({unit.pk: 'simple' for unit in units}))

    def test_with_no_provider_module_there_are_no_chips_and_nothing_breaks(self):
        with mock.patch.dict(sys.modules, {'farm.placements': None}):
            self.assertEqual([card.chips for card in self.cards()], [(), ()])

    def test_the_chips_of_the_registry_are_on_the_cards_it_names_and_one_call_serves_all_the_units(self):
        chip = SimpleNamespace(label='E-1 · Control', title='', url='')
        calls = []

        def of(units, user):
            calls.append(len(list(units)))
            return {self.t2.pk: [chip]}

        with mock.patch.dict(sys.modules, {'farm.placements': SimpleNamespace(of=of)}), \
                mock.patch('farm.placements', SimpleNamespace(of=of), create=True):
            found = {card.unit.code: card.chips for card in self.cards()}
        self.assertEqual(found, {'T-01': (), 'T-02': (chip,)})
        self.assertEqual(calls, [2])

    def test_a_registry_that_raises_leaves_the_card_as_it_was(self):
        def broken(units, user):
            raise RuntimeError('boom')

        with mock.patch.dict(sys.modules, {'farm.placements': SimpleNamespace(of=broken)}), \
                mock.patch('farm.placements', SimpleNamespace(of=broken), create=True):
            found = self.cards()
        self.assertEqual([card.chips for card in found], [(), ()])
        self.assertEqual({card.unit.code for card in found}, {'T-01', 'T-02'})
