"""How a recorded amount reads (farm/templatetags/feeding.py `amount`, behind the store's quantities and the feeding's
kilograms): one rule in every language. Three decimals after the separator read as a group of thousands in a column of
grouped figures ("251.804 kg" beside "1,420 kg" reads as 251 tonnes), so a kilogram or more shows at most two decimals;
under a kilogram the grams show (0.035 kg: a 40 g ration must not read 0.0, FDR-40)."""
from decimal import Decimal

from django.test import SimpleTestCase
from django.utils import translation

from farm.templatetags.feeding import feed_kg
from inventory.templatetags.inventory import quantity


class AmountTests(SimpleTestCase):
    CASES = {
        'en': {'251.804': '251.8 kg', '1420': '1,420 kg', '1250.5': '1,250.5 kg', '4.125': '4.13 kg', '0.035': '0.035 kg',
               '0.04': '0.04 kg', '12': '12 kg'},
        'nb': {'251.804': '251,8 kg', '1420': '1\xa0420 kg', '0.035': '0,035 kg'},
        'tr': {'251.804': '251,8 kg', '1420': '1.420 kg', '0.035': '0,035 kg'},
    }

    def test_a_kilogram_or_more_never_shows_three_decimals(self):
        for language, cases in self.CASES.items():
            with translation.override(language):
                for value, shown in cases.items():
                    with self.subTest(language=language, value=value):
                        self.assertEqual(quantity(Decimal(value), 'kg'), shown)
                        self.assertEqual(feed_kg(Decimal(value)), shown)

    def test_only_a_mass_is_rounded_things_counted_show_as_recorded(self):
        """The rule is for masses: a quantity of things counted (doses, bottles: units) is shown as it was recorded, to
        its three decimals, trailing zeros dropped, never rounded to two."""
        with translation.override('en'):
            self.assertEqual(quantity(Decimal('4.125'), 'units'), '4.125 units')
            self.assertEqual(quantity(Decimal('1250.500'), 'units'), '1,250.5 units')
            self.assertEqual(quantity(Decimal('12'), 'units'), '12 units')
            self.assertEqual(quantity(Decimal('4.125'), 'kg'), '4.13 kg')
