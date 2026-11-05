"""The duties outside this system (coverage review R16, R17 and the others): the driftsplan and the lice coordination plan as due
lines for the sea sites they bind, the person's record that they were done, the reminders on the overview, and the one page that
lists every duty with what is known and what is not."""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse

from core.models import AuditLog
from farm.models import Site
from farm.tests.helpers import role

from .. import duties, due, services
from ..models import OutsideDutyDone
from .helpers import day
from .test_due import TODAY, DueTestCase


class LinesTests(DueTestCase):
    def lines(self, site=None, today=TODAY):
        return [line for line in due.due(today).duties if site is None or line.site == site]

    def test_a_sea_site_of_food_fish_owes_the_driftsplan_even_when_idle_and_the_lice_plan_only_with_salmonids(self):
        found = {(line.duty.code, line.year): line for line in self.lines(self.sea)}
        self.assertEqual(set(found), {('driftsplan', 2026)})                  # idle: no salmonids ever held
        line = found[('driftsplan', 2026)]
        self.assertEqual((line.deadline, line.status), (date(2026, 10, 1), duties.OVERDUE))
        self.stock(self.m1, 1000, '100', day(10, 5))
        self.assertEqual({(line.duty.code, line.year) for line in self.lines(self.sea)},
                         {('driftsplan', 2026), ('lice_plan', 2026)})

    def test_what_is_not_a_sea_site_of_food_fish_or_broodstock_owes_no_driftsplan(self):
        self.assertEqual(self.lines(self.hatchery), [])                       # land
        self.sea.production_form = Site.ProductionForm.SETTEFISK
        self.sea.save()
        self.assertEqual(self.lines(self.sea), [])
        self.sea.production_form = ''
        self.sea.save()
        self.assertEqual(self.lines(self.sea), [])
        self.sea.production_form = Site.ProductionForm.STAMFISK
        self.sea.save()
        self.assertEqual([line.duty.code for line in self.lines(self.sea)], ['driftsplan'])

    def test_the_status_follows_the_day(self):
        self.assertEqual(self.lines(self.sea, date(2026, 8, 15))[0].status, duties.DUE_SOON)    # 47 days before
        self.assertEqual(self.lines(self.sea, date(2026, 5, 1))[0].status, duties.UPCOMING)
        self.assertEqual(self.lines(self.sea, date(2026, 10, 1))[0].status, duties.DUE_SOON)    # on the day itself
        self.assertEqual([line.year for line in self.lines(self.sea, date(2027, 2, 1))], [2026, 2027])


class RecordTests(DueTestCase):
    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Duty keeper', 'view_report', 'change_report'))
        self.url = reverse('reports:duty_done') + f'?duty=driftsplan&site={self.sea.pk}&year=2026'

    def test_a_record_that_it_was_done_ends_the_reminder_is_logged_and_can_be_undone(self):
        self.assertContains(self.client.get(self.url), 'Operating plan (driftsplan)')
        response = self.client.post(self.url, {'done_on': '2026-09-28', 'reference': 'ALT-77'})
        self.assertEqual(response.status_code, 302)
        record = OutsideDutyDone.objects.get()
        self.assertEqual((record.duty, record.site, record.year, record.done_on, record.reference, record.recorded_by),
                         ('driftsplan', self.sea, 2026, date(2026, 9, 28), 'ALT-77', self.user))
        line, = [line for line in due.due(TODAY).duties if line.site == self.sea]
        self.assertEqual((line.status, line.done), (duties.DONE, record))
        entry = AuditLog.objects.get(entity_type='duty done', action='create')
        self.assertEqual(entry.changes['Receipt or reference'], [None, 'ALT-77'])
        page = self.client.get(reverse('reports:outside_duties'))
        self.assertContains(page, 'ALT-77')
        self.client.post(reverse('reports:duty_undo', args=[record.pk]))
        self.assertFalse(OutsideDutyDone.objects.exists())
        self.assertEqual(AuditLog.objects.filter(entity_type='duty done', action='delete').count(), 1)

    def test_what_is_refused(self):
        future = self.client.post(self.url, {'done_on': '2099-01-01', 'reference': ''})
        self.assertEqual(future.status_code, 422)
        elsewhere = reverse('reports:duty_done') + f'?duty=driftsplan&site={self.hatchery.pk}&year=2026'
        self.assertEqual(self.client.post(elsewhere, {'done_on': '2026-09-28'}).status_code, 422)   # a land site
        self.assertFalse(OutsideDutyDone.objects.exists())
        self.assertEqual(self.client.get(reverse('reports:duty_done') + f'?duty=recapture&site={self.sea.pk}&year=2026'
                                         ).status_code, 404)                 # not an annual duty recorded here
        self.assertEqual(self.client.get(reverse('reports:duty_done') + f'?duty=driftsplan&site={self.sea.pk}&year=x'
                                         ).status_code, 404)

    def test_the_database_holds_one_record_a_year_in_range(self):
        base = {'duty': 'driftsplan', 'site': self.sea, 'year': 2026, 'done_on': date(2026, 9, 1)}
        OutsideDutyDone.objects.create(**base)
        for fields in ({}, {'duty': 'other'}, {'year': 2025}, {'year': 2101}):
            with self.subTest(fields), self.assertRaises(IntegrityError), transaction.atomic():
                OutsideDutyDone.objects.create(**{**base, **fields})

    def test_each_action_needs_its_permission(self):
        reader = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        reader.groups.add(role('Reader', 'view_report'))
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse('reports:outside_duties')).status_code, 200)
        self.assertNotContains(self.client.get(reverse('reports:outside_duties')), 'Record as done')
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {'done_on': '2026-09-28'}).status_code, 403)
        nobody = get_user_model().objects.create_user('per', 'per@example.com', 'x')
        self.client.force_login(nobody)
        self.assertEqual(self.client.get(reverse('reports:outside_duties')).status_code, 403)

    def test_the_service_refuses_a_duty_that_does_not_bind_the_site(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            services.record_duty_done(self.user, duty='lice_plan', site=self.sea, year=2026, done_on=date(2026, 9, 1))


class PageTests(DueTestCase):
    def test_the_page_lists_every_duty_with_its_deadline_channel_form_and_what_is_not_verified(self):
        self.user.groups.add(role('Duty reader', 'view_report'))
        page = self.client.get(reverse('reports:outside_duties'))
        for duty in duties.DUTIES:
            self.assertContains(page, str(duty.title))
        self.assertContains(page, '15 July each year')
        self.assertContains(page, 'Altinn 3')
        self.assertContains(page, 'https://lovdata.no/forskrift/2008-06-17-822/§45')
        self.assertContains(page, 'unverified')
        self.assertEqual({duty.code for duty in duties.DUTIES if duty.recordable}, {'driftsplan', 'lice_plan'})

    def test_the_reports_page_and_the_overview_remind_of_an_overdue_one(self):
        reports = self.client.get(reverse('reports:report_list'))
        self.assertContains(reports, 'Outside this system')
        self.assertContains(reports, 'Operating plan (driftsplan)')
        home = self.client.get(reverse('home'))
        self.assertContains(home, 'Operating plan (driftsplan)')
        self.assertTrue(home.context['upcoming']['overdue'] >= 1)
        OutsideDutyDone.objects.create(duty='driftsplan', site=self.sea, year=2026, done_on=date(2026, 9, 1))
        self.assertNotContains(self.client.get(reverse('home')), 'Operating plan (driftsplan)')
