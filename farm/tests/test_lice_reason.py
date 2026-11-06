"""A sea-lice medicine given for another reason (hydrogen peroxide is also an AGD treatment) is right sometimes, so it is
never refused; but such a treatment is not in the weekly sea-lice report to Mattilsynet, which lists the treatments for
sea lice, so the treatment's dialog says so and goes on only past the box (audit F-083, F-239). The rule is one function,
farm.health.lice.left_out_of_lice_report, which the report reads too (reports/tests/test_lice.py)."""
from core.models import AuditLog

from ..health import lice, services
from ..models import HandlingAcknowledgement
from .test_health import HealthTestCase

WARNING = ('Salmosan vet. is a sea-lice medicine, given here for “Other parasites (e.g. AGD)”: the weekly sea-lice '
           'report to Mattilsynet lists only the treatments for sea lice, so this one will not be in it.')


class LiceMedicineReasonTests(HealthTestCase):
    def test_a_lice_medicine_given_for_another_reason_warns_and_goes_on_past_the_box(self):
        bath = self.medicine(days=7)
        refused = self.refused(self.treat, bath, 1, 1, reason='parasites')
        self.assertEqual(refused, {'handling_ack': ['Tick the box to go on despite these warnings.']})
        checked = services.handling([self.t1], self.day(1), 'bath', bath, self.day(1), reason='parasites')
        self.assertEqual(checked.messages(), [WARNING])
        self.treat(bath, 1, 1, reason='parasites', handling_ack=checked.fingerprint)
        log = AuditLog.objects.get(entity_type='treatment', action='create')
        self.assertEqual(log.severity, AuditLog.Severity.NORMAL)          # a report's warning, not the fish's
        self.assertEqual(log.changes['Warnings acknowledged'][1], WARNING)
        self.assertFalse(HandlingAcknowledgement.objects.exists())

    def test_for_sea_lice_or_another_kind_of_medicine_it_asks_nothing(self):
        self.treat(self.medicine(days=7), 1, 1)
        antibiotic = self.medicine(name='Aquaflor', kind='antibacterial', administration='in_feed', days=0,
                                   active_substance='florfenicol')
        self.treat(antibiotic, 0, 0, reason='bacterial')
        self.assertFalse(AuditLog.objects.filter(entity_type='treatment', changes__has_key='Warnings acknowledged')
                         .exists())

    def test_the_rule_is_one_function(self):
        bath = self.medicine(days=7)
        self.assertTrue(lice.left_out_of_lice_report(bath, 'parasites'))
        self.assertFalse(lice.left_out_of_lice_report(bath, 'sea_lice'))
        self.assertFalse(lice.left_out_of_lice_report(None, 'parasites'))
