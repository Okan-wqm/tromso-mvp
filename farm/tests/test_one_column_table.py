"""A feeding table of one temperature column gave an SFR only at exactly that temperature (no extrapolation, owner
decision Q1), so a farm that typed one column got no ration on almost every day and the page said "outside this table
(12.0–12.0 °C)" (audit F-080). A table now has at least two columns: between them the SFR is interpolated, outside them
there is none; the lookup has no branch for one column left."""
from decimal import Decimal as D

from django.urls import reverse

from ..feeding.ration import Cell, sfr_at
from ..models import FeedingProtocol
from .test_protocols import ProtocolTestCase, table_data


class OneColumnTableTests(ProtocolTestCase):
    def test_a_table_needs_two_temperature_columns(self):
        protocol = FeedingProtocol.objects.create(name='Smolt', species=self.salmon, expected_fcr=D('1.0'))
        url = reverse('farm:feedingprotocol_table', args=[protocol.pk])
        whole = {'min_weight_g': '0', 'max_weight_g': '', 'feed': str(self.feed.pk), 'meals_per_day': '4',
                 'expected_fcr': '', 'sfr_120': '1.1'}
        response = self.client.post(url, table_data(protocol.version, '12', [whole]))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.context['table_form'].errors['temperatures'], [
            'Give at least two temperature columns: the SFR is read between them, never outside them.'])
        self.assertFalse(protocol.bands.exists())
        saved = self.client.post(url, table_data(protocol.version, '12 14', [{**whole, 'sfr_140': '1.3'}]))
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(protocol.bands.get().rates.count(), 2)

    def test_a_stored_table_of_one_column_still_reads_only_its_own_temperature(self):
        one = (Cell(D('12'), D('1.1')),)
        self.assertEqual(sfr_at(one, D('12')).value, D('1.1'))
        self.assertIsNone(sfr_at(one, D('12.1')))
