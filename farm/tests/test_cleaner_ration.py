"""Cleaner fish and the ration (D-1): lumpfish and wrasses eat what the salmon leave, their own feed block and the lice,
and have no feeding table of their own. The meal board and every page that reads the ration mark them as cleaner fish
instead of warning that no protocol is assigned (the production fish's warning); they stay listed with their fish and
weight, and are never in the salmon's ration figures, a protocol of their own giving them a ration on their own line."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse

from core.models import Profile

from ..feeding import ration
from ..feeding.views import next_meal
from ..models import ProtocolAssignment, Tank
from ..models.feeding import FeedTarget
from .helpers import role
from .test_cleaner_fish import CleanerFishTestCase
from .test_protocols import PROTOCOL_KEEPER, ProtocolTestCase, Row, band, protocol, temperature

D = Decimal


class CleanerFishWithoutAFeedingTableTests(CleanerFishTestCase):
    """The cleaner-fish cage (2,000 salmon of 125 g, 10,000 lumpfish of 50 g) with a salmon protocol assigned to the
    cage (a unit's row, which the lumpfish read past as another species') and the cage at 13 °C."""

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Protocol keeper', *PROTOCOL_KEEPER))
        self.protocol = ProtocolTestCase.make_protocol(self)
        ProtocolTestCase.assign(self, self.protocol, unit=self.cage)
        ProtocolTestCase.water(self, '13', unit=self.cage, hours=0)

    def board(self):
        response = self.client.get(reverse('farm:meal_board'), {'site': self.fjord.pk})     # the cage's site only
        row = next(row for row in response.context['rows'] if row['unit'] == self.cage)
        return response, row, {line['batch']: line for line in row['lines']}

    def feed_cage(self, kilos, target=FeedTarget.PRODUCTION, feed=None, days_ago=1):
        return self.record(kilos=kilos, days_ago=days_ago, unit=self.cage, feed=feed or self.feed, target=target)

    def test_the_board_marks_them_as_cleaner_fish_keeps_them_listed_and_leaves_them_out_of_the_salmons_ration(self):
        response, row, lines = self.board()
        salmon, lump = lines[self.salmon_batch], lines[self.lump_batch]
        self.assertEqual((salmon['why'], salmon['cleaner'], salmon['share'].end.missing), ('', False, ''))
        self.assertIsNotNone(salmon['share'].ration_kg)
        self.assertEqual((lump['why'], lump['cleaner'], lump['share'].end.missing), ('', True, ration.CLEANER_FISH))
        self.assertIsNone(lump['share'].ration_kg)
        self.assertNotContains(response, 'No protocol is assigned')
        self.assertNotContains(response, 'these fish are Lumpfish')
        self.assertContains(response, '<span>Cleaner fish</span>', count=1)
        self.assertContains(response, f'<span class="ui-code">{self.lump_batch.code}</span>')
        self.assertContains(response, '10,000 fish')
        self.assertContains(response, '50.0 g as stocked')
        day = row['day']
        self.assertEqual((day.ration_kg, day.calculated_kg, day.next_meal_kg),
                         (salmon['share'].ration_kg, salmon['share'].calculated_kg, salmon['share'].next_meal_kg))

    def test_without_any_protocol_the_salmon_are_warned_and_the_cleaner_fish_are_not(self):
        ProtocolAssignment.objects.all().delete()
        response, row, lines = self.board()
        self.assertEqual(lines[self.salmon_batch]['why'], 'No protocol is assigned to these fish.')
        self.assertEqual((lines[self.lump_batch]['why'], lines[self.lump_batch]['cleaner']), ('', True))
        self.assertContains(response, 'No protocol is assigned to these fish.', count=1)
        self.assertContains(response, '<span>Cleaner fish</span>', count=1)
        self.assertIsNone(row['day'].calculated_kg)

    def test_cleaner_fish_with_a_protocol_of_their_own_get_their_ration_on_their_own_line_only(self):
        own = ProtocolTestCase.make_protocol(self, name='Lumpfish', species=self.lump, bands=((0, None, None),),
                                             sfr=(('2.00', '2.00'),))
        ProtocolTestCase.assign(self, own, batch=self.lump_batch)
        response, row, lines = self.board()
        salmon, lump = lines[self.salmon_batch], lines[self.lump_batch]
        self.assertEqual((lump['why'], lump['cleaner'], lump['share'].end.protocol), ('', True, own))
        self.assertEqual(lump['share'].ration_kg, D(500) * D('2.00') / 100)            # 500 kg at 2 %
        self.assertContains(response, '<span>Cleaner fish</span>', count=1)
        self.assertEqual((row['day'].ration_kg, row['day'].calculated_kg),
                         (salmon['share'].ration_kg, salmon['share'].calculated_kg))  # the salmon's alone (D-1)
        self.assertEqual(next_meal(self.cage)['amount_kg'],
                         salmon['share'].next_meal_kg.quantize(D('0.001'), ROUND_HALF_UP))

    def test_their_feeding_does_not_make_their_estimate_incomplete(self):
        self.feed_cage('4', FeedTarget.CLEANER_FISH, self.block)
        self.feed_cage('3')
        response, _row, lines = self.board()
        self.assertEqual(lines[self.lump_batch]['share'].blind_days, 0)
        self.assertEqual(lines[self.lump_batch]['share'].end_g, D(50))     # no table, no growth credited
        self.assertNotContains(response, 'Estimate incomplete')
        ProtocolAssignment.objects.all().delete()                          # the salmon's own gap is still told
        board = self.client.get(reverse('farm:meal_board'), {'site': self.fjord.pk})
        self.assertContains(board, 'Estimate incomplete: 1 feeding day', count=1)

    def test_the_drawer_the_days_view_and_the_monitoring_card_do_not_warn_either(self):
        drawer = self.client.get(reverse('farm:production_units'), {'unit': self.cage.pk})
        rows = {batch: why for batch, _share, why in drawer.context['ration_rows']}
        self.assertEqual(rows[self.lump_batch], '')
        self.assertNotContains(drawer, 'these fish are Lumpfish')
        self.assertContains(drawer, 'Cleaner fish: no feeding table of their own.', count=1)
        days = self.client.get(reverse('farm:feeding_records'), {'view': 'days', 'unit': self.cage.pk})
        self.assertNotContains(days, 'these fish are Lumpfish')
        self.assertNotContains(days, 'No protocol is assigned')
        self.assertContains(days, 'Cleaner fish: no feeding table of their own.')
        from monitoring import read as monitoring_read
        from monitoring.tests import ALL_RIGHTS, chosen
        self.user.groups.add(role('Monitor', *ALL_RIGHTS))
        user = get_user_model().objects.get(pk=self.user.pk)               # permissions are cached on the object
        unit = Tank.objects.select_related('production_department__site', 'system').get(pk=self.cage.pk)
        card, = monitoring_read.cards([unit], user, chosen({unit.pk: 'simple'}))
        self.assertEqual([line['why'] for line in card.lines], ['', ''])
        self.assertFalse([reason for reason in card.state.reasons if 'Lumpfish' in reason or 'protocol' in reason])

    def test_the_mark_speaks_each_language(self):
        for language, word in {'nb': 'Rensefisk', 'tr': 'Temizleyici balık'}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            with self.subTest(language=language):
                board = self.client.get(reverse('farm:meal_board'), {'site': self.fjord.pk})
                self.assertContains(board, f'<span>{word}</span>', count=1)


class CleanerFishPolicyTests(SimpleTestCase):
    """The ration's policy knows which batches are cleaner fish (farm/feeding/ration.py): without a row of their own they
    have no ration and no warning; a unit's row of the production species is not theirs; a row of their own is read as
    any batch's is."""

    def policy(self, rows):
        tables = {'P': ration.Table(protocol(species='S'), (band(0, None),)),
                  'L': ration.Table(protocol(name='Lumpfish', species='LUM'), (band(0, None),))}
        return ration.Policy(rows, tables, {'B1': 'S', 'L1': 'LUM'}, lambda unit_id, day: temperature(),
                             cleaner=frozenset({'L1'}))

    def test_cleaner_fish_have_no_ration_and_no_warning_without_a_row_of_their_own(self):
        for rows in ([], [Row('P', unit_id='T1')]):
            with self.subTest(rows=rows):
                basis = self.policy(rows).basis('T1', 'L1', date(2026, 11, 5), D(50), beside=True)
                self.assertEqual((basis.missing, basis.why(), basis.has_ration, basis.fcr, basis.skipped),
                                 (ration.CLEANER_FISH, '', False, None, None))
        alone = self.policy([]).basis('T1', 'L1', date(2026, 11, 5), D(50))     # no production fish beside them
        self.assertEqual((alone.missing, alone.why()), (ration.NO_PROTOCOL, 'No protocol is assigned to these fish.'))
        salmon = self.policy([]).basis('T1', 'B1', date(2026, 11, 5), D(50))
        self.assertEqual((salmon.missing, salmon.why()), (ration.NO_PROTOCOL, 'No protocol is assigned to these fish.'))

    def test_a_row_of_their_own_gives_them_a_ration(self):
        basis = self.policy([Row('L', batch_id='L1')]).basis('T1', 'L1', date(2026, 11, 5), D(50))
        self.assertEqual((basis.missing, basis.protocol.name, basis.has_ration), ('', 'Lumpfish', True))

    def test_a_units_row_of_their_species_feeds_them_and_the_salmon_read_it_past(self):
        policy = self.policy([Row('L', unit_id='T1')])
        lump, salmon = (policy.basis('T1', batch, date(2026, 11, 5), D(50)) for batch in ('L1', 'B1'))
        self.assertEqual((lump.missing, lump.protocol.name), ('', 'Lumpfish'))
        self.assertEqual((salmon.missing, salmon.skipped.protocol_id), (ration.NO_PROTOCOL, 'L'))
