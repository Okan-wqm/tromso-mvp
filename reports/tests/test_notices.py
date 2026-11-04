"""The disease and welfare notices and the health events (D-4): a notice started from an event and what it begins with, the
events it can be about, the filing as the fact "Mattilsynet notified" the health records read, a notice given by
telephone recorded though its figures are not all ready, a notice recorded before notices existed, and the move of the
times the health events kept into filed notices (reports migration 0005) both ways."""
import hashlib
import json
from datetime import datetime, time, timezone as utc
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone as tz

from core.models import AuditLog
from farm.health import notices
from farm.models import HealthEvent, Site, StockOperation
from farm.stock import services
from farm.tests.helpers import role

from .. import compute
from ..models import Report, ReportSnapshot
from ..periods import OSLO
from .helpers import REPORTER, ReportTestCase, day
from .test_pages import FILED_AT, ReportPagesTestCase, report_data


class NoticeTestCase(ReportPagesTestCase):
    def setUp(self):
        super().setUp()
        self.event = HealthEvent.objects.create(site=self.sea, date=day(10, 20), kind='vet_visit', diagnosis='isa',
                                                confirmation='suspected', created_by=self.user)
        self.event.units.add(self.m1)
        self.stock(self.m1, 2000, '125', day(9, 20))

    def notice(self, **overrides):
        data = report_data(**{
            'kind': 'disease', 'site': str(self.sea.pk), 'period_start': '', 'occurred_on': '2026-10-20',
            'health_event': str(self.event.pk), 'what_happened': 'Suspected ISA in M-01', 'found_at': '2026-10-20T08:00',
            **overrides})
        response = self.client.post(reverse('reports:report_create'), data)
        return response, Report.objects.order_by('-created_at').first()


class StartingFromAnEventTests(NoticeTestCase):
    def test_a_notice_started_from_a_listed_disease_is_a_disease_notice_with_what_the_event_says(self):
        form =self.client.get(reverse('reports:report_create'), {'health_event': self.event.pk}).context['form']
        self.assertEqual((form.initial['kind'], form.initial['site'], form.initial['health_event'],
                          form.initial['occurred_on']), ('disease', self.sea.pk, self.event.pk, day(10, 20)))
        self.assertEqual(form.initial['what_happened'],
                         'Infectious salmon anaemia (ISA) · 2026-10-20 · Suspected · M-01')
        self.assertEqual(form.initial['cause'], 'Infectious salmon anaemia (ISA)')
        self.assertEqual((form.initial['contact_name'], form.initial['contact_email']), ('Kari Nord', 'kari@example.com'))

    def test_an_event_without_a_listed_disease_starts_a_welfare_notice(self):
        other = HealthEvent.objects.create(site=self.sea, date=day(10, 21), kind='mortality')
        form = self.client.get(reverse('reports:report_create'), {'health_event': other.pk}).context['form']
        self.assertEqual((form.initial['kind'], form.initial['what_happened']),
                         ('welfare', 'Increased mortality · 2026-10-21 · the whole site'))

    def test_the_dead_under_the_event_are_the_initial_figure(self):
        batch = self.stock(self.m1, 10, '125', day(9, 21))
        services.record_mortality(self.user, unit=self.m1, batch=batch, day=day(10, 21), count=4, cause='disease',
                                  health_event=self.event)
        form = self.client.get(reverse('reports:report_create'), {'health_event': self.event.pk}).context['form']
        self.assertEqual(form.initial['fish_dead'], 4)


class TheNoticeTests(NoticeTestCase):
    def test_a_disease_notice_is_stored_with_its_event_and_computed_from_it(self):
        batch = self.stock(self.m1, 10, '125', day(9, 21))
        services.record_mortality(self.user, unit=self.m1, batch=batch, day=day(10, 21), count=4, cause='disease',
                                  health_event=self.event)
        response, report = self.notice()
        self.assertEqual(response.status_code, 302)
        self.assertEqual((report.kind, report.site, report.health_event, report.occurred_on),
                         ('disease', self.sea, self.event, day(10, 20)))
        result = compute.compute(report)
        self.assertEqual(result.problems, [])
        self.assertEqual(result.content['health_event'], {
            'id': str(self.event.pk), 'date': '2026-10-20', 'diagnosis': 'isa', 'confirmation': 'suspected',
            'deaths': 4, 'units': ['1']})
        # What it read is in its sources: a void of the deaths changes the fingerprint.
        before = compute.fingerprint(result.scope)
        services.void(self.user, StockOperation.objects.get(health_event=self.event), 'Entered twice')
        self.assertNotEqual(compute.fingerprint(compute.compute(report).scope), before)

    def test_what_the_form_refuses(self):
        response, _report = self.notice(health_event='')
        self.assertIn('health_event', response.context['form'].errors)               # a disease notice needs its event
        elsewhere = HealthEvent.objects.create(site=self.hatchery, date=day(10, 20), kind='observation')
        response, _report = self.notice(health_event=str(elsewhere.pk))
        self.assertEqual(response.context['form'].errors['health_event'], ['Choose a health event of the site.'])
        self.assertFalse(Report.objects.exists())

    def test_one_notice_per_event_and_the_database_holds_it(self):
        self.notice()
        response, _report = self.notice()
        self.assertEqual(response.context['form'].errors['health_event'],
                         ['This health event has a notice already: open it from the list.'])
        for fields in ({'kind': 'disease', 'health_event': None},                       # a disease notice has its event
                       {'kind': 'smolt', 'health_event': self.event, 'period_start': day(10, 1),
                        'occurred_on': None}):                                          # no other report has one
            with self.subTest(fields), self.assertRaises(IntegrityError), transaction.atomic():
                Report.objects.create(site=self.sea, **{'occurred_on': day(10, 20), **fields})
        # A welfare notice may name its event or none.
        self.client.post(reverse('reports:report_create'), report_data(
            kind='welfare', site=str(self.sea.pk), period_start='', occurred_on='2026-10-21', what_happened='x',
            found_at='2026-10-21T06:00'))
        self.assertEqual(Report.objects.filter(kind='welfare', health_event__isnull=True).count(), 1)

    def test_the_event_is_fixed_once_the_notice_is_started(self):
        _response, report = self.notice()
        other = HealthEvent.objects.create(site=self.sea, date=day(10, 22), kind='observation')
        response = self.client.post(reverse('reports:report_edit', args=[report.pk]), report_data(
            kind='disease', site=str(self.sea.pk), period_start='', occurred_on='2026-10-20',
            health_event=str(other.pk), what_happened='Changed', found_at='2026-10-20T08:00',
            version=str(report.version)))
        self.assertEqual(response.status_code, 302)
        report.refresh_from_db()
        self.assertEqual((report.health_event, report.what_happened), (self.event, 'Changed'))

    def test_an_event_with_a_notice_cannot_be_deleted_from_under_it(self):
        self.notice()
        with self.assertRaises(Exception), transaction.atomic():
            HealthEvent.all_objects.filter(pk=self.event.pk).delete()


class TheFilingTellsTheHealthRecordsTests(NoticeTestCase):
    def test_pending_until_the_notice_is_filed_then_told_with_its_receipt(self):
        self.assertEqual(notices.pending([self.event]), [self.event])
        self.user.groups.add(role('Health reader', 'view_healthevent'))
        _response, report = self.notice()
        self.assertEqual(notices.pending([self.event]), [self.event])         # a draft tells no one
        page = self.client.get(reverse('farm:healthevent_list'))
        self.assertContains(page, f'{reverse("reports:report_create")}?health_event={self.event.pk}')
        self.file(report, channel='altinn', reference='AR-7')
        told = notices.told([self.event])[self.event.pk]
        self.assertEqual((told.reference, told.at), ('AR-7', datetime.fromisoformat(FILED_AT).replace(tzinfo=OSLO)))
        self.assertEqual(notices.pending([self.event]), [])
        page = self.client.get(reverse('farm:healthevent_list'))
        self.assertContains(page, 'Notified')
        self.assertNotContains(page, 'Notify at once')

    def test_a_person_who_may_not_start_reports_gets_no_link(self):
        reader = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        reader.groups.add(role('Reader', 'view_report'))
        self.assertEqual(notices.start_url(self.event, reader), '')
        self.assertIn('health_event=', notices.start_url(self.event, self.user))

    def test_a_notice_given_by_telephone_is_recorded_though_the_site_has_no_organisation_number(self):
        Site.objects.filter(pk=self.sea.pk).update(organisation_number='')
        _response, report = self.notice()
        problems = compute.compute(report).problems
        self.assertEqual(problems, ['Fjord (FJ) has no organisation number (Facility › Sites, its Reports tab).'])
        self.assertContains(self.file(report, channel='altinn', reference='AR-1'), 'It is not ready:')
        self.assertContains(self.file(report, channel='telephone', reference=''), 'Recorded as filed.')
        report.refresh_from_db()
        self.assertEqual((report.status, report.channel), ('submitted', 'telephone'))
        self.assertReportsAddUp()
        logged = AuditLog.objects.filter(entity_type='regulatory report', action='update').latest('created_at')
        self.assertEqual(logged.changes['Not ready when filed'], [None, ' '.join(problems)])
        self.assertEqual(notices.pending([self.event]), [])

    def test_the_log_of_a_filing_is_english_at_rest_whoever_records_it(self):
        Site.objects.filter(pk=self.sea.pk).update(organisation_number='')
        _response, report = self.notice()
        english = compute.compute(report).problems
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = 'nb'
        response = self.file(report, channel='telephone', reference='')
        self.assertContains(response, 'Registrert som innsendt')        # the page is in Norwegian
        logged = AuditLog.objects.filter(entity_type='regulatory report', action='update').latest('created_at')
        self.assertEqual(logged.changes['Not ready when filed'], [None, ' '.join(english)])

    def test_a_correction_of_a_notice_keeps_the_event_it_is_about(self):
        _response, report = self.notice()
        self.file(report, channel='altinn', reference='AR-1')
        self.client.post(reverse('reports:report_correct', args=[report.pk]))
        correction = Report.objects.get(corrects=report)
        self.assertEqual((correction.health_event, correction.escape, correction.kind, correction.site),
                         (self.event, None, 'disease', self.sea))
        self.assertEqual(compute.compute(correction).content['health_event']['id'], str(self.event.pk))

    def test_the_telephone_exception_is_for_notices_not_for_the_monthly_reports(self):
        Site.objects.filter(pk=self.hatchery.pk).update(organisation_number='')
        self.october()
        _response, report = self.start()
        self.assertContains(self.file(report, channel='telephone', reference=''), 'It is not ready:')

    def test_a_welfare_notice_that_came_of_the_event_tells_too(self):
        other = HealthEvent.objects.create(site=self.sea, date=day(10, 22), kind='mortality')
        self.client.post(reverse('reports:report_create'), report_data(
            kind='welfare', site=str(self.sea.pk), period_start='', occurred_on='2026-10-22', health_event=str(other.pk),
            what_happened='Mortality rose', found_at='2026-10-22T06:00'))
        report = Report.objects.get(health_event=other)
        self.file(report, channel='email', reference='mail-1')
        self.assertIn(other.pk, notices.told([other]))


class RecordedBeforeNoticesExistedTests(NoticeTestCase):
    def test_a_notice_of_format_0_is_shown_as_what_it_is_and_never_compared(self):
        report = Report.objects.create(
            kind='disease', site=self.sea, health_event=self.event, occurred_on=day(10, 20), submitted_at=tz.now(),
            submitted_by=self.user, channel='other', reference='', created_by=self.user, updated_by=self.user)
        content = {'kind': 'disease', 'health_event': str(self.event.pk), 'diagnosis': 'isa',
                   'confirmation': 'suspected', 'notified_at': '2026-10-21T09:00:00+00:00'}
        ReportSnapshot.objects.create(
            report=report, format_version=0, content=content,
            content_sha256=hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest(),
            sources_fingerprint=hashlib.sha256(b'x').hexdigest())
        page = self.client.get(reverse('reports:report_detail', args=[report.pk]))
        self.assertContains(page, 'Recorded on the health event before notices existed')
        self.assertNotContains(page, 'a correction is needed')
        self.assertEqual(page.context['differences']['legacy'], True)
        self.assertIn(self.event.pk, notices.told([self.event]))


class EscapeNoticeTests(NoticeTestCase):
    def setUp(self):
        super().setUp()
        self.batch = self.stock(self.m1, 3000, '200', day(9, 25))
        self.operation = services.record_escape(
            self.user, unit=self.m1, batch=self.batch, day=day(10, 25), count=300, cause='A net tore in the storm',
            found_time=time(6, 15), health_status='Healthy', recaptured=12)
        self.record = self.operation.escape_record

    def escape_notice(self, **overrides):
        data = report_data(**{'kind': 'escape', 'site': str(self.sea.pk), 'period_start': '', 'occurred_on': '2026-10-25',
                              'escape': str(self.record.pk), 'what_happened': '300 fish escaped from M-01',
                              **overrides})
        return self.client.post(reverse('reports:report_create'), data), Report.objects.order_by('-created_at').first()

    def test_a_notice_started_from_an_escape_begins_with_what_it_says(self):
        form = self.client.get(reverse('reports:report_create'), {'escape': self.record.pk}).context['form']
        self.assertEqual((form.initial['kind'], form.initial['site'], form.initial['escape'],
                          form.initial['occurred_on'], form.initial['cause'], form.initial['fish_involved'],
                          form.initial['situation']),
                         ('escape', self.sea.pk, self.record.pk, day(10, 25), 'A net tore in the storm', 300, 'Healthy'))
        self.assertEqual(form.initial['what_happened'], '300 fish of Atlantic salmon (SAL) escaped from M-01.')

    def test_the_notice_reads_the_escape_record_and_the_fold(self):
        response, report = self.escape_notice()
        self.assertEqual(response.status_code, 302)
        result = compute.compute(report)
        self.assertEqual(result.problems, [])                  # no time-found of its own: the record has it
        self.assertEqual(result.content['escape'], {
            'id': str(self.operation.pk), 'date': '2026-10-25', 'found_time': '06:15', 'suspected': False,
            'unit': '1', 'species': 'SAL', 'fish': 300, 'avg_weight_g': '200.0',
            'cause': 'A net tore in the storm', 'health_status': 'Healthy', 'recaptured': 12})

    def test_what_the_form_refuses_and_the_database_holds(self):
        response, _report = self.escape_notice(escape='')
        self.assertIn('escape', response.context['form'].errors)
        other = self.stock(self.k1, 500, '5', day(10, 1))
        elsewhere = services.record_escape(self.user, unit=self.k1, batch=other, day=day(10, 20), count=10,
                                           cause='Left open').escape_record
        response, _report = self.escape_notice(escape=str(elsewhere.pk))
        self.assertEqual(response.context['form'].errors['escape'], ['Choose an escape from a unit of the site.'])
        self.escape_notice()
        response, _report = self.escape_notice()
        self.assertEqual(response.context['form'].errors['escape'],
                         ['This escape has a notice already: open it from the list.'])
        for fields in ({'kind': 'escape', 'escape': None}, {'kind': 'welfare', 'escape': self.record}):
            with self.subTest(fields), self.assertRaises(IntegrityError), transaction.atomic():
                Report.objects.create(site=self.sea, occurred_on=day(10, 26), **fields)

    def test_a_correction_of_an_escape_notice_keeps_the_escape(self):
        _response, report = self.escape_notice()
        self.file(report, channel='altinn', reference='AR-9')
        self.client.post(reverse('reports:report_correct', args=[report.pk]))
        correction = Report.objects.get(corrects=report)
        self.assertEqual((correction.escape, correction.health_event, correction.kind), (self.record, None, 'escape'))
        self.assertEqual(compute.compute(correction).content['escape']['fish'], 300)

    def test_the_time_found_of_an_escape_is_the_records_not_a_second_one(self):
        _response, report = self.escape_notice()
        self.assertEqual(compute.compute(report).content['escape']['found_time'], '06:15')
        self.assertIsNone(report.found_at)

    def test_a_void_of_the_escape_after_the_filing_is_told(self):
        _response, report = self.escape_notice()
        self.file(report, channel='altinn', reference='AR-9')
        services.void(self.user, self.operation, 'Counted in the wrong cage')
        page = self.client.get(reverse('reports:report_detail', args=[report.pk]))
        self.assertTrue(page.context['differences']['figures'])


class TimesMovedIntoNoticesTests(TransactionTestCase):
    """Reports migration 0005 and its reverse (farm migration 0024 drops the column after it)."""

    before = [('farm', '0023_reports_fields'), ('reports', '0003_sea_lice_answers')]

    def setUp(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.before)
        self.old = self.executor.loader.project_state(self.before + [('core', '0007_audit_severity')]).apps
        User = self.old.get_model(*settings.AUTH_USER_MODEL.split('.'))
        self.kari, self.ola = User.objects.create(username='kari'), User.objects.create(username='ola')
        site = self.old.get_model('farm', 'Site').objects.create(name='Fjord', code='FJ')
        self.site = site
        self.Event = self.old.get_model('farm', 'HealthEvent')
        self.told = datetime(2026, 11, 1, 9, 30, tzinfo=utc.utc)

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def event(self, **fields):
        return self.Event._base_manager.create(site_id=self.site.pk, date=datetime(2026, 10, 30).date(),
                                               kind='vet_visit', **fields)

    def migrate(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_each_time_becomes_a_filed_notice_by_the_person_who_recorded_it_and_the_reverse_brings_it_back(self):
        OldLog = self.old.get_model('core', 'AuditLog')
        logged = self.event(diagnosis='pd', confirmation='suspected', authority_notified_at=self.told)
        OldLog.objects.create(user_id=self.ola.pk, user_name='ola', action='update', entity_type='health event',
                                entity_id=str(logged.pk), entity_label='x',
                                changes={'Mattilsynet notified at': [None, self.told.isoformat()]})
        edited = self.event(diagnosis='isa', confirmation='confirmed', authority_notified_at=self.told,
                            updated_by_id=self.kari.pk)
        created = self.event(authority_notified_at=self.told, created_by_id=self.kari.pk)
        voided = self.event(diagnosis='vhs', confirmation='suspected', authority_notified_at=self.told,
                            created_by_id=self.kari.pk, is_deleted=True, void_reason='Wrong')
        self.event(diagnosis='pd', confirmation='suspected')                          # never told: no notice
        self.migrate()
        reports = {report.health_event_id: report for report in Report.objects.all()}
        self.assertEqual(len(reports), 4)
        self.assertEqual({event: (report.kind, report.submitted_by.username) for event, report in reports.items()}, {
            logged.pk: ('disease', 'ola'), edited.pk: ('disease', 'kari'), created.pk: ('welfare', 'kari'),
            voided.pk: ('disease', 'kari')})
        report = reports[logged.pk]
        self.assertEqual((report.submitted_at, report.channel, report.reference, report.site.name, report.status,
                          report.notes, report.occurred_on.isoformat()),
                         (self.told, 'other', '', 'Fjord', 'submitted',
                          'Recorded on the health event before notices existed.', '2026-10-30'))
        snapshot = report.snapshot
        self.assertEqual((snapshot.format_version, snapshot.content['notified_at'], snapshot.content['diagnosis']),
                         (0, self.told.isoformat(), 'pd'))
        self.assertEqual(snapshot.content_sha256, compute.content_hash(snapshot.content))
        entry = AuditLog.objects.get(entity_type='regulatory report', entity_id=str(report.pk))
        self.assertEqual((entry.user_name, entry.changes['Content hash'][1]), ('ola', snapshot.content_sha256))
        self.assertIn(logged.pk, notices.told(HealthEvent.all_objects.filter(pk=logged.pk)))
        # The reverse brings the times back into the column and undoes the move.
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        back = executor.loader.project_state(self.before).apps.get_model('farm', 'HealthEvent')
        self.assertEqual(sorted(back._base_manager.exclude(authority_notified_at=None).values_list('pk', flat=True)),
                         sorted([logged.pk, edited.pk, created.pk, voided.pk]))
        self.assertEqual({event.authority_notified_at for event in back._base_manager.exclude(
            authority_notified_at=None)}, {self.told})
        notices_left = executor.loader.project_state(self.before).apps.get_model('reports', 'Report')
        self.assertEqual(notices_left._base_manager.count(), 0)          # the move is undone: the times are back

    def test_a_time_no_known_person_recorded_stops_the_move_and_names_the_event(self):
        orphan = self.event(diagnosis='pd', confirmation='suspected', authority_notified_at=self.told)
        with self.assertRaisesMessage(RuntimeError, str(orphan.pk)):
            self.migrate()
        self.Event._base_manager.filter(pk=orphan.pk).update(created_by_id=self.kari.pk)
        self.migrate()
        self.assertEqual(Report.objects.get().submitted_by.username, 'kari')
