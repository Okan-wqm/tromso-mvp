"""A medicine's withdrawal is worked out live from its rows (HLT-02), so changing a row changes the withdrawal of every
course already given with it, including those whose fish are held now or were harvested: that change protects or
endangers food and is logged as critical, as going on past a withdrawal is; a medicine nobody was treated with is logged
as before (audit F-196). check_withdrawal lists any harvest it brings inside a withdrawal
(test_harvest_inside_withdrawal)."""
from django.urls import reverse

from core.models import AuditLog

from .helpers import rows_data
from .test_health import HealthTestCase


class WithdrawalRuleChangeTests(HealthTestCase):
    def post(self, medicine, days):
        return self.client.post(reverse('farm:medicine_withdrawals', args=[medicine.pk]), rows_data(
            'withdrawals', [{'species': '', 'degree_days': '', 'days': days, 'safety_margin_pct': '', 'note': ''}],
            0, record=medicine))

    def logged(self, medicine):
        return AuditLog.objects.filter(entity_type='medicine', entity_id=str(medicine.pk), action='update').get()

    def test_a_change_of_a_medicine_already_given_is_critical(self):
        bath = self.medicine(days=7)
        self.treat(bath, 9, 9)                               # ended: the change frees no fish held today
        self.assertEqual(self.post(bath, '1').status_code, 302)
        self.assertEqual(self.logged(bath).severity, AuditLog.Severity.CRITICAL)

    def test_a_change_of_a_medicine_never_given_is_not(self):
        bath = self.medicine(days=7)
        self.assertEqual(self.post(bath, '1').status_code, 302)
        self.assertEqual(self.logged(bath).severity, AuditLog.Severity.NORMAL)
