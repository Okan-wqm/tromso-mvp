"""Production › Reports › Regulatory reports through its pages, against the stored rows: starting, editing and
discarding a draft and its answers, recording the filing and what it freezes, the refusals (by the forms and by the
database), corrections, the exports, the permissions, the activity log, the database viewer and the admin."""
import csv
import io
import json
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core import database
from core.audit import message
from core.models import AuditLog
from core.softdelete import plan_delete
from farm.models import Supplier
from farm.models.site import zone_of
from farm.stock import services as stock_services
from farm.tests.helpers import role, rows_data

from .. import compute, services
from ..models import Report, ReportSnapshot, ResistanceSuspicion, UnitAnswer
from ..periods import OSLO
from .helpers import OCTOBER, ReportTestCase, day, previewed
from .schema import errors

FILED_AT = '2026-11-03T09:30'


def _raw(sql, *params):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


def report_data(**overrides):
    data = {'kind': 'smolt', 'site': '', 'period_start': '2026-10-17', 'contact_name': 'Kari Nord',
            'contact_email': 'kari@example.com', 'contact_phone': '+47 98989898', 'notes': ''}
    data.update(overrides)
    return data


@override_settings(STOCK_BACKDATE_DAYS=3650)
class ReportPagesTestCase(ReportTestCase):
    def start(self, **overrides):
        response = self.client.post(reverse('reports:report_create'),
                                    report_data(**{'site': str(self.hatchery.pk), **overrides}))
        return response, Report.objects.order_by('-created_at').first()

    def file(self, report, **overrides):
        data = {'submitted_at': FILED_AT, 'channel': 'altinn', 'reference': 'AR123456',
                'version': str(Report.objects.get(pk=report.pk).version),
                'content_sha256': previewed(Report.objects.get(pk=report.pk)), **overrides}
        return self.client.post(reverse('reports:report_submit', args=[report.pk]), data, follow=True)


class DraftTests(ReportPagesTestCase):
    def test_a_draft_is_started_read_edited_and_discarded_through_the_pages(self):
        self.october()
        form = self.client.get(reverse('reports:report_create'), {'kind': 'smolt', 'site': self.hatchery.pk,
                                                                   'period': '2026-10'})
        self.assertEqual((form.context['form']['kind'].value(), str(form.context['form']['site'].value()),
                          form.context['form']['period_start'].value(), form.context['form']['contact_name'].value()),
                         ('smolt', str(self.hatchery.pk), OCTOBER.start, 'Kari Nord'))
        response, report = self.start()
        self.assertEqual(response.status_code, 302)
        # A day of the month is enough: the report is for its month.
        self.assertEqual((report.kind, report.site, report.period_start, report.contact_email, report.created_by,
                          report.submitted_at), ('smolt', self.hatchery, OCTOBER.start, 'kari@example.com', self.user,
                                                 None))
        page = self.client.get(reverse('reports:report_detail', args=[report.pk]))
        self.assertContains(page, 'As the records give it now')
        self.assertContains(page, '3850')
        self.assertEqual(page.context['deadline'], day(11, 7))
        self.client.post(reverse('reports:report_edit', args=[report.pk]), report_data(
            contact_phone='+47 12345678', notes='Checked', version='1'))
        report.refresh_from_db()
        self.assertEqual((report.contact_phone, report.notes, report.kind, report.site, report.version),
                         ('+47 12345678', 'Checked', 'smolt', self.hatchery, 2))
        self.client.post(reverse('reports:report_delete', args=[report.pk]))
        self.assertTrue(Report.all_objects.get(pk=report.pk).is_deleted)
        self.assertFalse(Report.objects.exists())
        actions = list(AuditLog.objects.filter(entity_type='regulatory report').order_by('created_at')
                       .values_list('action', flat=True))
        self.assertEqual(actions, ['create', 'update', 'delete'])

    def test_the_key_is_fixed_once_started_and_one_live_report_per_period(self):
        _response, report = self.start()
        self.client.post(reverse('reports:report_edit', args=[report.pk]), report_data(
            kind='biomass', site=str(self.sea.pk), period_start='2026-09-03', version='1'))
        report.refresh_from_db()
        self.assertEqual((report.kind, report.site, report.period_start), ('smolt', self.hatchery, OCTOBER.start))
        response, _same = self.start(period_start='2026-10-30')
        self.assertEqual(response.context['form'].errors['period_start'],
                         ['This report has already been started for this period: open it from the list.'])
        self.assertEqual(Report.objects.count(), 1)

    def test_what_the_form_refuses(self):
        response, _report = self.start(period_start='2099-01-05')
        self.assertEqual(response.context['form'].errors['period_start'], ['The period has not begun yet.'])
        response, _report = self.start(kind='slaughter_planned', facility='')
        self.assertIn('facility', response.context['form'].errors)
        response, _report = self.start(kind='nonsense')         # a report that does not exist
        self.assertIn('kind', response.context['form'].errors)
        self.assertFalse(Report.objects.exists())

    def test_a_planned_slaughter_is_started_for_a_coming_week(self):
        response, report = self.start(kind='slaughter_planned', site='', facility=str(self.facility.pk),
                                      period_start='2099-01-07')
        self.assertEqual((report.kind, report.facility, report.site, report.period_start.isoweekday()),
                         ('slaughter_planned', self.facility, None, 1))

    def test_a_welfare_notice_with_its_narrative(self):
        response, report = self.start(kind='welfare', site=str(self.sea.pk), period_start='', occurred_on='2026-10-30',
                                      what_happened='Oxygen fell in M-01', found_at='2026-10-30T06:15',
                                      cause='A blower stopped', fish_dead='120', fish_injured='', fish_involved='5000',
                                      situation='Oxygen restored', measures='Spare blower started')
        self.assertEqual((report.kind, report.occurred_on, report.what_happened, report.fish_dead,
                          report.fish_involved), ('welfare', day(10, 30), 'Oxygen fell in M-01', 120, 5000))
        result = compute.compute(report)
        self.assertEqual((result.problems, result.content['cause']), ([], 'A blower stopped'))

    def test_the_time_found_is_typed_on_the_sites_clock_and_shown_back_on_it(self):
        self.sea.timezone = 'Asia/Tokyo'                                      # nine hours ahead of UTC
        self.sea.save()
        values = dict(kind='welfare', site=str(self.sea.pk), period_start='', occurred_on='2026-10-30',
                      what_happened='Oxygen fell')
        _response, report = self.start(found_at='2026-10-30T06:15', **values)
        self.assertEqual(report.found_at, datetime(2026, 10, 30, 6, 15, tzinfo=zone_of(self.sea)))
        self.assertEqual(report.found_at.astimezone(dt_tz.utc), datetime(2026, 10, 29, 21, 15, tzinfo=dt_tz.utc))
        edit = self.client.get(reverse('reports:report_edit', args=[report.pk]))
        self.assertEqual(edit.context['form'].initial['found_at'], datetime(2026, 10, 30, 6, 15))
        self.assertContains(edit, 'value="30.10.2026 06:15"')                       # dd.mm.yyyy HH:MM in every language
        self.assertEqual(compute.compute(report).content['found_at'], '2026-10-29T21:15:00+00:00')
        # The future is the site's future: a time that is past in UTC may still be to come in Tokyo.
        soon = timezone.localtime(timezone.now(), zone_of(self.sea)) + timedelta(hours=2)
        response, _again = self.start(found_at=soon.strftime('%Y-%m-%dT%H:%M'), **{
            **values, 'occurred_on': soon.date().isoformat()})
        self.assertEqual(response.context['form'].errors['found_at'], ['The time cannot be in the future.'])

    def test_the_answers_of_a_biomass_report_are_a_list_of_their_own(self):
        _response, report = self.start(kind='biomass', site=str(self.sea.pk))
        url = reverse('reports:report_units', args=[report.pk])
        self.client.post(url, {**rows_data('units', [{'unit': str(self.m1.pk), 'reduced_capacity': True}]),
                               'version': str(report.version)})
        self.assertEqual(list(UnitAnswer.objects.values_list('unit__code', 'reduced_capacity', 'created_by')),
                         [('M-01', True, self.user.pk)])
        # A unit of another site is not offered.
        response = self.client.post(url, {**rows_data('units', [{'unit': str(self.k1.pk)}]),
                                          'version': str(Report.objects.get(pk=report.pk).version)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(UnitAnswer.objects.count(), 1)
        # A smolt report has no such list.
        _response, smolt = self.start()
        self.assertEqual(self.client.post(reverse('reports:report_units', args=[smolt.pk]),
                                          rows_data('units', [])).status_code, 404)

    def test_a_unit_answer_is_read_edited_and_removed_through_its_page(self):
        _response, report = self.start(kind='biomass', site=str(self.sea.pk))
        url = reverse('reports:report_units', args=[report.pk])

        def version():
            return str(Report.objects.get(pk=report.pk).version)
        self.client.post(url, {**rows_data('units', [{'unit': str(self.m1.pk), 'reduced_capacity': True}]),
                               'version': version()})
        answer = UnitAnswer.objects.get()
        self.assertContains(self.client.get(reverse('reports:report_edit', args=[report.pk])), 'data-panel="units"')
        self.client.post(url, {**rows_data('units', [{'id': str(answer.pk), 'unit': str(self.m1.pk),
                                                      'reduced_capacity': False}], initial=1), 'version': version()})
        self.assertEqual(list(UnitAnswer.objects.values_list('unit__code', 'reduced_capacity')), [('M-01', False)])
        # The unit is listed once.
        response = self.client.post(url, {**rows_data('units', [
            {'id': str(answer.pk), 'unit': str(self.m1.pk)}, {'unit': str(self.m1.pk)}], initial=1),
                                          'version': version()})
        self.assertEqual((response.status_code, UnitAnswer.objects.count()), (200, 1))
        self.client.post(url, {**rows_data('units', [{'id': str(answer.pk), 'DELETE': True}], initial=1),
                               'version': version()})
        self.assertFalse(UnitAnswer.objects.exists())


class FilingTests(ReportPagesTestCase):
    def test_recording_the_filing_freezes_the_content_and_logs_its_hash(self):
        self.october()
        _response, report = self.start()
        response = self.file(report)
        self.assertContains(response, 'Recorded as filed.')
        report.refresh_from_db()
        self.assertEqual((report.submitted_at, report.submitted_by, report.channel, report.reference, report.status),
                         (datetime.fromisoformat(FILED_AT).replace(tzinfo=OSLO), self.user,
                          'altinn', 'AR123456', 'submitted'))
        snapshot = ReportSnapshot.objects.get(report=report)
        self.assertEqual(snapshot.content, compute.compute(report).content)
        self.assertEqual(snapshot.content_sha256, compute.content_hash(snapshot.content))
        logged = AuditLog.objects.filter(entity_type='regulatory report', action='update').latest('created_at')
        self.assertEqual(logged.changes['Content hash'], [None, snapshot.content_sha256])
        self.assertEqual(logged.changes['Status'], [message('Draft'), message('Filed')])
        page = self.client.get(reverse('reports:report_detail', args=[report.pk]))
        self.assertContains(page, 'As filed')
        self.assertContains(page, 'The records still give what was filed.')
        self.assertReportsAddUp()

    def test_the_filing_time_is_oslos_whatever_zone_the_browser_is_in(self):
        self.october()
        _response, report = self.start()
        with timezone.override('Pacific/Auckland'):
            self.file(report)
        report.refresh_from_db()
        self.assertEqual(report.submitted_at, datetime(2026, 11, 3, 9, 30, tzinfo=OSLO))
        self.assertEqual(report.submitted_at.astimezone(dt_tz.utc), datetime(2026, 11, 3, 8, 30, tzinfo=dt_tz.utc))
        _response, draft = self.start(period_start='2026-09-15')
        with timezone.override('Pacific/Auckland'):
            form = self.client.get(reverse('reports:report_detail', args=[draft.pk])).context['submit_form']
        now = timezone.localtime(timezone.now(), OSLO).replace(tzinfo=None)
        self.assertLess(abs(form.initial['submitted_at'] - now), timedelta(minutes=2))      # Oslo's wall clock

    def test_what_the_filing_refuses(self):
        _response, report = self.start()                       # no fish in October: not ready
        response = self.file(report)
        self.assertContains(response, 'It is not ready:')
        self.october()
        self.assertContains(self.file(report, reference=''), 'Give the receipt or reference the authority gave.')
        self.assertContains(self.file(report, submitted_at='2099-01-01T10:00'), 'The time cannot be in the future.')
        self.assertContains(self.file(report, version='99'), 'Someone else changed this report')
        self.assertIsNone(Report.objects.get(pk=report.pk).submitted_at)
        # A notice phoned in has no receipt.
        _response, notice = self.start(kind='welfare', site=str(self.sea.pk), period_start='', occurred_on='2026-10-30',
                                       what_happened='Oxygen fell', found_at='2026-10-30T06:15')
        self.file(notice, channel='telephone', reference='')
        self.assertEqual(Report.objects.get(pk=notice.pk).channel, 'telephone')

    def test_a_filed_report_never_changes(self):
        self.october()
        _response, report = self.start()
        self.file(report)
        report.refresh_from_db()
        response = self.client.post(reverse('reports:report_edit', args=[report.pk]), report_data(
            contact_phone='+47 1', version=str(report.version)))
        self.assertIn('It was filed and cannot change: start a correction instead.',
                      response.context['form'].non_field_errors())
        self.assertEqual(plan_delete(report).blockers, ['It was filed: start a correction instead.'])
        self.client.post(reverse('reports:report_delete', args=[report.pk]))
        self.assertFalse(Report.all_objects.get(pk=report.pk).is_deleted)
        # The database refuses it whatever writes: the report, what was filed, the answers.
        for change in (lambda: Report.objects.filter(pk=report.pk).update(contact_phone='+47 1'),
                       lambda: _raw('DELETE FROM regulatory_reports WHERE id = %s', report.pk),
                       lambda: ReportSnapshot.objects.filter(report=report).update(content={}),
                       lambda: ReportSnapshot.objects.filter(report=report).delete(),
                       lambda: ResistanceSuspicion.objects.create(report=report, substance='AZAMETHIPHOS',
                                                                  cause='BIOESSAY')):
            with self.assertRaises(DatabaseError), transaction.atomic():
                change()
        # The user columns stay writable (Django may clear them when a person is removed).
        Report.objects.filter(pk=report.pk).update(updated_by=None)

    def test_a_correction_after_the_records_changed(self):
        self.october()
        _response, report = self.start()
        self.file(report)
        stock_services.void(self.user, self.out, 'Went to the wrong site')       # K-02 keeps its 500 fish
        page = self.client.get(reverse('reports:report_detail', args=[report.pk]))
        self.assertContains(page, 'The records no longer give what was filed: a correction is needed.')
        paths = [path for path, _before, _after in page.context['differences']['figures']]
        self.assertIn(f'/units/{self.k2.pk}/fish_at_end', paths)
        self.assertIn(f'/units/{self.k2.pk}/moved_out_of_site', paths)
        # Said as the figures are named on the page, the unit by its number, never as a key of the content.
        self.assertContains(page, '<li>Unit K-02 · Fish at the month’s end: 500 → 1000</li>', html=True)
        self.assertContains(page, '<li>Unit K-02 · Moved out of the site: 500 → 0</li>', html=True)
        self.assertNotContains(page, f'/units/{self.k2.pk}/')
        response = self.client.post(reverse('reports:report_correct', args=[report.pk]))
        correction = Report.objects.get(corrects=report)
        self.assertRedirects(response, reverse('reports:report_edit', args=[correction.pk]))
        self.assertEqual((correction.kind, correction.site, correction.period_start, correction.contact_phone,
                          correction.submitted_at), (report.kind, report.site, report.period_start,
                                                     report.contact_phone, None))
        # One correction at a time; a draft is changed, not corrected.
        self.client.post(reverse('reports:report_correct', args=[report.pk]))
        self.client.post(reverse('reports:report_correct', args=[correction.pk]))
        self.assertEqual(Report.objects.count(), 2)
        self.assertEqual(Report.objects.get(pk=report.pk).status, 'submitted')
        self.file(correction, reference='AR999')
        self.assertEqual(Report.objects.get(pk=report.pk).status, 'superseded')
        self.assertEqual(compute.compute(correction).content['units'][str(self.k2.pk)]['fish_at_end'], 1000)
        self.assertEqual(plan_delete(Report.objects.get(pk=correction.pk)).blockers,
                         ['It was filed: start a correction instead.'])

    def test_differences_tell_identity_apart_from_figures(self):
        self.october()
        _response, report = self.start()
        self.file(report)
        self.k1.regulatory_unit_id = 'Kar 1'
        self.k1.save()
        differences = services.differences(Report.objects.get(pk=report.pk))
        self.assertEqual((differences['figures'], [item[0] for item in differences['identity']]),
                         ([], [f'/units/{self.k1.pk}/number']))


class ExportTests(ReportPagesTestCase):
    def test_the_smolt_report_as_mattilsynets_api_takes_it(self):
        self.october()
        _response, report = self.start()
        response = self.client.get(reverse('reports:report_export', args=[report.pk, 'json']))
        self.assertIn('not-filed', response['Content-Disposition'])
        body = json.loads(response.content)
        self.assertEqual(errors(body, 'SettefiskrapportDto'), [])
        self.assertEqual((body['klientReferanse'], body['organisasjonsnummer'], body['lokalitetsnummer'],
                          body['rapporteringsmåned'], body['rapporteringsår']),
                         (str(report.pk), '987654321', 12345, 10, 2026))
        self.assertEqual(body['produksjonsenheter'][0], {
            'karId': 'K-01', 'artskode': 'SAL', 'snittvektGram': 5, 'beholdningVedMånedsslutt': 3850,
            'antallAvlivet': 50, 'antallSelvdød': 100, 'antallFlyttetEksternt': 0})
        self.file(report)
        filed = self.client.get(reverse('reports:report_export', args=[report.pk, 'json']))
        self.assertNotIn('not-filed', filed['Content-Disposition'])

    def test_the_planned_slaughter_as_mattilsynets_api_takes_it(self):
        operator = Supplier.objects.create(name='Fjord Slakteri AS', code='FSL', supplies=['slaughter'],
                                           organisation_number='NO912345678MVA')
        self.facility.operator = operator
        self.facility.save()
        batch = self.stock(self.m1, 1000, '4000', day(10, 1))
        from farm.models import HandlingPlanItem
        HandlingPlanItem.objects.create(kind='harvest', date=day(11, 18), unit=self.m1, batch=batch,
                                        planned_kg=Decimal('2500.6'), facility=self.facility, created_by=self.user)
        _response, report = self.start(kind='slaughter_planned', site='', facility=str(self.facility.pk),
                                       period_start='2026-11-16')
        body = json.loads(self.client.get(reverse('reports:report_export', args=[report.pk, 'json'])).content)
        self.assertEqual(errors(body, 'PlanlagtSlaktRapportDto'), [])
        self.assertEqual((body['uke'], body['år'], body['godkjenningsnummer'],
                          body['planlagteLokaliteter'][0]['ukeplanPerArt'][0]['onsdagKg']), (47, 2026, 'M123', 2501))
        # The company that files is the slaughterhouse's operator, never a farm whose fish it slaughters.
        self.assertEqual(body['organisasjonsnummer'], '912345678')
        self.assertEqual(body['planlagteLokaliteter'][0]['organisasjonsnummer'], '987654321')

    def test_a_planned_slaughter_of_a_facility_without_an_operator_is_not_ready(self):
        batch = self.stock(self.m1, 1000, '4000', day(10, 1))
        from farm.models import HandlingPlanItem
        HandlingPlanItem.objects.create(kind='harvest', date=day(11, 18), unit=self.m1, batch=batch,
                                        planned_kg=Decimal('2500.6'), facility=self.facility, created_by=self.user)
        _response, report = self.start(kind='slaughter_planned', site='', facility=str(self.facility.pk),
                                       period_start='2026-11-16')
        problem = (f'{self.facility} has no company that files for it with a 9-digit organisation number (Purchasing '
                   '› Suppliers, the operator of Slaughter facilities).')
        self.assertIn(problem, compute.compute(report).problems)
        self.assertContains(self.file(report), 'It is not ready:')
        self.facility.operator = Supplier.objects.create(name='Fjord Slakteri AS', code='FSL', supplies=['slaughter'],
                                                         organisation_number='ABC-1')
        self.facility.save()
        self.assertIn(problem, compute.compute(report).problems)            # not nine digits

    def test_the_csv_guards_free_text_and_keeps_numbers(self):
        self.october()
        _response, report = self.start(contact_name='=HYPERLINK("x")')
        response = self.client.get(reverse('reports:report_export', args=[report.pk, 'csv']))
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(rows[0], ['section', 'field', 'value'])
        self.assertIn(['kontaktperson', 'navn', "'=HYPERLINK(\"x\")"], rows)
        self.assertIn(['lokalitetsnummer', '', '12345'], rows)
        # A kind the API has no endpoint for has no JSON.
        _response, biomass = self.start(kind='biomass', site=str(self.sea.pk))
        self.assertEqual(self.client.get(reverse('reports:report_export', args=[biomass.pk, 'json'])).status_code, 404)
        self.assertEqual(self.client.get(reverse('reports:report_print', args=[biomass.pk])).status_code, 200)


class PermissionTests(ReportPagesTestCase):
    def test_each_action_needs_its_permission(self):
        self.october()
        _response, report = self.start()
        reader = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        reader.groups.add(role('Report reader', 'view_report'))
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse('reports:report_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('reports:report_detail', args=[report.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('reports:report_export', args=[report.pk, 'csv'])).status_code, 200)
        for url in (reverse('reports:report_create'), reverse('reports:report_edit', args=[report.pk]),
                    reverse('reports:report_delete', args=[report.pk]),
                    reverse('reports:report_submit', args=[report.pk]),
                    reverse('reports:report_correct', args=[report.pk])):
            self.assertEqual(self.client.post(url, {}).status_code, 403, url)
        nobody = get_user_model().objects.create_user('per', 'per@example.com', 'x')
        self.client.force_login(nobody)
        self.assertEqual(self.client.get(reverse('reports:report_list')).status_code, 403)


class IntegrationTests(ReportPagesTestCase):
    def test_the_list_filters_and_shows_the_deadline(self):
        self.october()
        _response, report = self.start(period_start='2026-09-15')
        page = self.client.get(reverse('reports:report_list'), {'status': 'draft', 'kind': 'smolt'})
        self.assertEqual(list(page.context['objects']), [report])
        self.assertContains(page, 'Overdue')                        # 7 October 2026 has passed
        self.assertEqual(list(self.client.get(reverse('reports:report_list'), {'status': 'filed'}).context['objects']),
                         [])
        self.assertContains(page, '<p class="eyebrow">Reports</p>', html=True)     # an unlabelled group (OUR-20)

    def test_the_database_viewer_shows_the_tables(self):
        tables = {table.name for _section, found in database.sections() for table in found}
        self.assertTrue({'regulatory_reports', 'regulatory_report_snapshots', 'regulatory_report_unit_answers',
                         'regulatory_report_resistance_suspicions', 'regulatory_report_sensitivity_tests',
                         'regulatory_report_treatment_answers'} <= tables)

    def test_a_discarded_draft_comes_back_from_the_admin_unless_another_was_started(self):
        _response, report = self.start()
        self.client.post(reverse('reports:report_delete', args=[report.pk]))
        admin_user = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin_user)
        changelist = reverse('admin:reports_report_changelist')
        self.client.post(changelist, {'action': 'restore', '_selected_action': [str(report.pk)]})
        self.assertFalse(Report.all_objects.get(pk=report.pk).is_deleted)
        self.client.force_login(self.user)
        self.client.post(reverse('reports:report_delete', args=[report.pk]))
        _response, again = self.start()
        self.client.force_login(admin_user)
        self.client.post(changelist, {'action': 'restore', '_selected_action': [str(report.pk)]})
        self.assertTrue(Report.all_objects.get(pk=report.pk).is_deleted)
        self.assertIn(Report, admin.site._registry)
        self.assertIn(ReportSnapshot, admin.site._registry)
