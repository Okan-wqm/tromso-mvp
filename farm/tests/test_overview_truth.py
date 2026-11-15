"""The overviews say what is true (flow faults M-06, M-20). The production overview said "Nothing needs attention", its
Reports card "None overdue" and its panel "No report is due." while a stocked unit had no water sample in 30 days, a site
with fish was not set up for reports (so nothing could be known to be due for it) and a notice read "Due at once"; the
company's home page said "No report is due." too. Each is now said from the read of the page that owns it: the Water
page's rows (farm.water.views.overview: `unmeasured`), the Reports page's due list (reports.views.overview_upcoming:
`not_set_up`, `at_once`)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from ..models import HealthEvent, StockOperation
from ..stock import services
from .helpers import role
from .test_production_overview import OverviewTestCase, card_of, section

READER = ('view_stockoperation', 'view_watermeasurement', 'view_report')


class UnmeasuredUnitTests(OverviewTestCase):
    def test_a_stocked_unit_without_a_water_sample_needs_attention_and_an_empty_one_does_not(self):
        self.stock()
        self.sample(self.t1, co2_mg_l='8')
        self.assertIn('Nothing needs attention', section(self.page(), 'Needs attention'))   # T-02 is empty: not asked
        self.stock(self.t2)
        html = self.page()
        attention = section(html, 'Needs attention')
        self.assertNotIn('Nothing needs attention', html)
        self.assertIn('1 stocked unit without a water sample', html)                 # the head's chip
        self.assertIn('data-attention="unmeasured"', attention)
        self.assertIn('T-02', attention)
        self.assertNotIn('T-01', attention)
        self.assertIn('Fish, and no water sample in the last 30 days.', attention)
        self.assertIn(reverse('farm:water'), attention)
        self.sample(self.t2, co2_mg_l='8')
        self.assertIn('Nothing needs attention', section(self.page(), 'Needs attention'))

    def test_a_person_who_may_not_read_the_water_is_told_nothing_of_it(self):
        self.stock()
        self.as_role('view_stockoperation')
        self.assertNotIn('without a water sample', self.page())


class ReportsTruthTests(OverviewTestCase):
    def setUp(self):
        super().setUp()
        self.stock()                                                     # Bergen holds fish and is not set up for reports
        self.sample(self.t1, co2_mg_l='8')
        self.reader = get_user_model().objects.create_user('reader', 'reader@example.com')
        self.reader.groups.add(role('Reader', *READER))
        self.client.force_login(self.reader)

    def test_a_site_with_fish_that_is_not_set_up_for_reports_is_not_nothing_due(self):
        html = self.page()
        self.assertNotIn('Nothing needs attention', html)
        self.assertIn('1 site not set up for reports', html)
        attention = section(html, 'Needs attention')
        self.assertIn('data-attention="not-set-up"', attention)
        self.assertIn('Bergen', attention)
        self.assertIn('It holds fish, and what it owes cannot be worked out: no report is listed as due for it.', attention)
        card = card_of(html, 'reports-due')
        self.assertIn('1 site not set up for reports', card)
        self.assertNotIn('None overdue', card)
        panel = section(html, 'Reports due')
        self.assertIn('1 site with fish is not set up for reports: what it owes is not known, so nothing is listed as '
                      'due for it.', panel)
        self.assertNotIn('No report is due.', panel)                      # that would be a guess

    def test_the_companys_home_page_says_it_too(self):
        home = self.client.get(reverse('home')).content.decode()
        self.assertIn('1 site with fish is not set up for reports: what it owes is not known, so nothing is listed as '
                      'due for it.', home)
        self.assertNotIn('No report is due.', home)

    def test_a_site_that_is_set_up_and_owes_nothing_says_no_report_is_due(self):
        services.void(self.user, StockOperation.objects.get(), 'Not stocked after all')    # no fish: nothing to set up
        self.client.force_login(self.reader)
        html = self.page()
        self.assertIn('No report is due.', section(html, 'Reports due'))
        self.assertIn('None overdue', card_of(html, 'reports-due'))
        self.assertIn('Nothing needs attention', section(html, 'Needs attention'))

    def test_a_notice_due_at_once_needs_attention(self):
        HealthEvent.objects.create(site=self.bergen, date=timezone.localdate() - timedelta(days=1), kind='vet_visit',
                                   diagnosis='isa', confirmation='suspected')
        html = self.page()
        self.assertNotIn('Nothing needs attention', html)
        self.assertIn('1 notice due at once', html)                                  # the head's chip
        attention = section(html, 'Needs attention')
        self.assertIn('data-attention="notice"', attention)
        self.assertIn('A notice is filed at once: it has no later deadline.', attention)
        card = card_of(html, 'reports-due')
        self.assertIn('1 due at once', card)
        self.assertNotIn('None overdue', card)
