"""A research or other production site (§ 3 l, § 4 nr. 20: only chapters 1, 2, 3 and 7 apply) owes none of the juvenile, biomass or
yearly stock reports; the lice and cleaner-fish reports follow the fish at sea, and what else follows is marked unverified (Q10)."""
from django.db import IntegrityError, transaction
from django.urls import reverse

from farm.models import Site
from farm.tests.helpers import role

from .. import due
from ..kinds import ReportKind
from .helpers import day
from .test_due import TODAY, DueTestCase


class ResearchSiteTests(DueTestCase):
    def setUp(self):
        super().setUp()
        self.sea.production_form = Site.ProductionForm.OTHER
        self.sea.save()
        self.hatchery.production_form = Site.ProductionForm.OTHER
        self.hatchery.save()

    def reason(self, kind, site):
        return next(line.reason for line in due.due(TODAY).lines_of(kind) if line.place == site)

    def test_it_owes_only_what_follows_the_fish_at_sea(self):
        self.assertEqual([kind for kind, _fish in due.owed(self.sea)], [ReportKind.SEA_LICE, ReportKind.CLEANER_FISH])
        self.assertEqual(due.owed(self.hatchery), [])

    def test_the_lines_say_why_nothing_else_is_owed_and_that_it_is_unverified(self):
        why = ('research or other production reports none of the juvenile, biomass or yearly stock reports (§ 3 l: only '
               'chapters 1, 2, 3 and 7 apply to it; unverified, Q10)')
        for kind in (ReportKind.SMOLT, ReportKind.BIOMASS, ReportKind.LAND_STOCK):
            for site in (self.sea, self.hatchery):
                self.assertEqual(self.reason(kind, site), why, (kind, site))
        self.assertEqual(self.reason(ReportKind.SEA_LICE, self.hatchery), 'Hatchery is not a sea site')

    def test_the_lice_report_still_follows_its_salmonids_at_sea(self):
        self.stock(self.m1, 1000, '100', day(10, 5))
        self.assertEqual(self.line_status(ReportKind.SEA_LICE), due.DUE)
        self.assertEqual([row.kind for row in due.due(TODAY).rows if row.kind in (
            ReportKind.BIOMASS, ReportKind.SMOLT, ReportKind.LAND_STOCK)], [])

    def line_status(self, kind):
        return next(line.status for line in due.due(TODAY).lines_of(kind) if line.place == self.sea)

    def test_a_research_site_has_no_driftsplan_and_the_database_knows_the_form(self):
        self.assertEqual([line for line in due.due(TODAY).duties if line.site == self.sea], [])
        self.assertIn('other', Site.ProductionForm.values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Site.objects.filter(pk=self.sea.pk).update(production_form='junk')

    def test_the_site_form_offers_it(self):
        self.user.groups.add(role('Site editor', 'view_site', 'change_site'))
        form = self.client.get(reverse('farm:site_edit', args=[self.sea.pk])).context['form']
        self.assertIn(('other', 'Research or other production'), list(form.fields['production_form'].choices))
