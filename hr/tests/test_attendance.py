from datetime import date, datetime, time, timedelta, timezone as utc
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import AuditLog
from farm.models import ProductionDepartment, Site
from farm.stock.dates import site_today

from .. import read, rules, services
from ..models import AttendanceRecord, Employee, LeaveRequest, LeaveType, SchedulingSettings, Shift, ShiftAssignment
from .helpers import fields_of, user
from .helpers_people import PeopleTestCase, TOP, employee, place

UTC = utc.utc
DAY = date(2026, 3, 2)
PUNCH_PERMS = ('view_employee', 'view_attendancerecord')
ENTER_PERMS = (*PUNCH_PERMS, 'add_attendancerecord', 'change_attendancerecord', 'delete_attendancerecord')


def at(hour, minute=0, day=DAY):
    return datetime.combine(day, time(hour, minute), tzinfo=UTC)


def punch(person, start, end=None, **fields):
    fields.setdefault('via', 'self')
    return AttendanceRecord.objects.create(employee=person, clock_in=start, clock_out=end, **fields)


class StatusRuleTests(SimpleTestCase):
    """rules.status: pure, at a fixed now. Grace 10, absent after 30, punch window 120 (minutes)."""

    SPAN = (at(6), at(14))

    def standing(self, now, punches=(), on_leave=False, span=SPAN):
        return rules.status(span, punches, on_leave, now, 10, 30, 120)

    def test_upcoming_not_in_and_absent_follow_the_clock(self):
        self.assertEqual(self.standing(at(5)).state, 'upcoming')
        self.assertEqual(self.standing(at(6, 9)).state, 'upcoming')              # inside the grace
        self.assertEqual(self.standing(at(6, 10)).state, 'not_in')
        self.assertEqual(self.standing(at(6, 29)).state, 'not_in')
        self.assertEqual(self.standing(at(6, 30)).state, 'absent')
        self.assertEqual(self.standing(at(15)).state, 'absent')                 # the shift is over and nobody came

    def test_a_record_is_a_fact_present_late_or_done(self):
        on_time = self.standing(at(7), [(at(6, 5), None)])
        self.assertEqual((on_time.state, on_time.late_minutes, on_time.first_in), ('present', 0, at(6, 5)))
        late = self.standing(at(7), [(at(6, 25), None)])
        self.assertEqual((late.state, late.late_minutes), ('late', 15))        # 25 minutes after the start, grace 10
        done = self.standing(at(15), [(at(6, 2), at(14, 1))])
        self.assertEqual((done.state, done.last_out), ('done', at(14, 1)))
        self.assertEqual(self.standing(at(6, 45), [(at(6, 40), None)]).state, 'late')      # present beats absent

    def test_the_punch_window_decides_which_punches_belong_to_the_shift(self):
        early = self.standing(at(7), [(at(4, 30), None)])                      # 90 minutes before: inside the window
        self.assertEqual(early.state, 'present')
        earlier = self.standing(at(7), [(at(3, 0), at(5, 0))])                 # 3 hours before: not this shift's
        self.assertEqual(earlier.state, 'absent')

    def test_leave_beats_everything_and_an_unplanned_presence_is_still_a_presence(self):
        self.assertEqual(self.standing(at(7), [(at(6), None)], on_leave=True).state, 'on_leave')
        self.assertEqual(self.standing(at(8), [(at(7), None)], span=None).state, 'present')
        self.assertEqual(self.standing(at(8), [(at(7), at(8))], span=None).state, 'done')
        self.assertIsNone(self.standing(at(8), [], span=None))                  # nothing planned, nobody there: unlisted

    def test_a_night_shift_across_midnight_is_judged_at_its_own_instants(self):
        night = (at(22), at(6, day=DAY + timedelta(days=1)))
        self.assertEqual(self.standing(at(23), [(at(22, 4), None)], span=night).state, 'present')
        self.assertEqual(self.standing(at(2, day=DAY + timedelta(days=1)), [], span=night).state, 'absent')


class PunchModelTests(PeopleTestCase):
    def refused(self, **fields):
        values = {'employee': self.in_a, 'clock_in': at(6), 'via': 'self', **fields}
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceRecord.objects.bulk_create([AttendanceRecord(**values)])

    def test_the_out_is_after_the_in_and_an_entered_stretch_has_its_reason(self):
        self.refused(clock_out=at(6))
        self.refused(clock_out=at(5))
        self.refused(via='entered')
        self.refused(via='gone')
        punch(self.in_a, at(6), at(7), via='entered', note='Forgot to clock in')

    def test_stretches_never_overlap_and_at_most_one_is_open(self):
        punch(self.in_a, at(6), at(10))
        self.refused(clock_in=at(9), clock_out=at(11))
        self.refused(clock_in=at(5), clock_out=at(7))
        punch(self.in_a, at(10), at(12))                                  # adjacent: the first ends where this begins
        open_one = punch(self.in_a, at(13))
        self.refused(clock_in=at(15))                                      # a second open one, later
        self.refused(clock_in=at(12, 30), clock_out=at(13, 30))            # inside the open one's reach
        punch(self.in_b, at(6))                                            # another person: no clash
        open_one.soft_delete(self.hr)
        punch(self.in_a, at(13, 30))                                       # a voided stretch holds nothing

    def test_two_stretches_on_one_day_are_allowed_split_work(self):
        punch(self.in_a, at(6), at(9))
        punch(self.in_a, at(10), at(14))
        self.assertEqual(AttendanceRecord.objects.filter(employee=self.in_a).count(), 2)

    def test_every_column_is_covered(self):
        self.assertEqual(fields_of(AttendanceRecord), {'employee', 'clock_in', 'clock_out', 'via', 'note', 'entry_key'})


class SelfPunchTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.ann = user('ann', *PUNCH_PERMS, group='Punch role')
        Employee.objects.filter(pk=self.in_a.pk).update(user=self.ann, first_name='', last_name='')
        self.in_a.refresh_from_db()

    def test_clock_in_and_out_at_the_servers_time_logged_each(self):
        with mock.patch('django.utils.timezone.now', return_value=at(6, 2)):
            record = services.clock_in(self.ann)
        self.assertEqual((record.employee, record.clock_in, record.clock_out, record.via, record.note),
                         (self.in_a, at(6, 2), None, 'self', ''))
        with mock.patch('django.utils.timezone.now', return_value=at(14, 1)):
            services.clock_out(self.ann)
        record.refresh_from_db()
        self.assertEqual((record.clock_out, record.version), (at(14, 1), 2))
        self.assertEqual(list(AuditLog.objects.filter(entity_id=str(record.pk)).order_by('created_at')
                              .values_list('action', flat=True)), ['create', 'update'])

    def test_a_second_clock_in_while_open_and_a_clock_out_when_not_in_are_refused_and_change_nothing(self):
        with mock.patch('django.utils.timezone.now', return_value=at(6)):
            services.clock_in(self.ann)
        before = (AttendanceRecord.objects.count(), AuditLog.objects.count())
        with self.assertRaises(ValidationError):
            services.clock_in(self.ann)
        self.assertEqual((AttendanceRecord.objects.count(), AuditLog.objects.count()), before)
        services.clock_out(self.ann)
        before = (AttendanceRecord.objects.count(), AuditLog.objects.count())
        with self.assertRaises(ValidationError):
            services.clock_out(self.ann)
        self.assertEqual((AttendanceRecord.objects.count(), AuditLog.objects.count()), before)

    def test_only_a_person_with_read_and_an_employee_row_clocks(self):
        stranger = user('nobody')
        with self.assertRaises(PermissionDenied):
            services.clock_in(stranger)
        admin = user('plain', 'view_attendancerecord', group='Plain role')          # a login with no employee row
        with self.assertRaises(PermissionDenied):
            services.clock_in(admin)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_the_clock_in_button_on_the_page_posts_and_redirects(self):
        self.client.force_login(self.ann)
        response = self.client.post(reverse('hr:production_punch', args=['in']))
        self.assertRedirects(response, reverse('hr:production_today'), fetch_redirect_response=False)
        self.assertEqual(AttendanceRecord.objects.get().employee, self.in_a)
        self.client.post(reverse('hr:production_punch', args=['in']))                              # again: a message, no second row
        self.assertEqual(AttendanceRecord.objects.count(), 1)
        self.assertEqual(self.client.get(reverse('hr:production_punch', args=['in'])).status_code, 405)
        self.client.post(reverse('hr:production_punch', args=['out']))
        self.assertIsNotNone(AttendanceRecord.objects.get().clock_out)


class EnteredPresenceTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.lead = user('boss', *ENTER_PERMS, group='Enter role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.lead)

    def post(self, person, start, end, note='Phone was dead', actor=None):
        self.client.force_login(actor or self.lead)
        return self.client.post(reverse('hr:production_attendancerecord_create'), {
            'employee': str(person.pk), 'clock_in': start, 'clock_out': end, 'note': note})

    def test_create_read_edit_void_a_stretch_typed_on_the_sites_clock(self):
        Site.objects.filter(pk=self.site.pk).update(timezone='Europe/Oslo')
        self.post(self.in_a, '2026-03-02T07:00', '2026-03-02T15:30')
        record = AttendanceRecord.objects.get()
        self.assertEqual({name: getattr(record, name) for name in fields_of(AttendanceRecord) if name != 'entry_key'},
                         {'employee': self.in_a, 'clock_in': at(6), 'clock_out': at(14, 30), 'via': 'entered',
                          'note': 'Phone was dead'})                       # 07:00 in Oslo (winter) is 06:00 UTC
        self.assertEqual(record.created_by, self.lead)
        listed = self.client.get(reverse('hr:production_attendancerecord_list'), {'from': '2026-03-01', 'to': '2026-03-03'})
        self.assertContains(listed, '07:00')                                # shown on the site's clock, not UTC
        form = self.client.get(reverse('hr:production_attendancerecord_edit', args=[record.pk])).context['form']
        self.assertEqual(form['clock_in'].value().isoformat(), '2026-03-02T07:00:00')
        # Edit: correct the out; logged with before and after, the note never
        self.client.post(reverse('hr:production_attendancerecord_edit', args=[record.pk]), {
            'clock_in': '2026-03-02T07:00', 'clock_out': '2026-03-02T16:00', 'note': 'Corrected', 'version': '1'})
        record.refresh_from_db()
        self.assertEqual((record.clock_out, record.version), (at(15), 2))
        entry = AuditLog.objects.filter(entity_id=str(record.pk), action='update').get()
        self.assertEqual(set(entry.changes), {'Clock out', 'Note'})      # a new note is a change; its words are never logged
        self.assertNotIn('Corrected', str(list(AuditLog.objects.values_list('changes', flat=True))))
        self.assertNotIn('Phone was dead', str(list(AuditLog.objects.values_list('changes', flat=True))))
        # Void = delete
        self.client.post(reverse('hr:production_attendancerecord_delete', args=[record.pk]))
        self.assertTrue(AttendanceRecord.all_objects.get().is_deleted)

    def test_a_reason_is_required_and_the_out_must_follow_the_in(self):
        errors = self.post(self.in_a, '2026-03-02T07:00', '', note='').context['form'].errors
        self.assertIn('note', errors)
        errors = self.post(self.in_a, '2026-03-02T07:00', '2026-03-02T06:00').context['form'].errors
        self.assertIn('clock_out', errors)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_an_overlapping_stretch_is_an_error_on_the_form_through_the_exclusion_constraint(self):
        self.post(self.in_a, '2026-03-02T06:00', '2026-03-02T10:00')
        errors = self.post(self.in_a, '2026-03-02T09:00', '2026-03-02T11:00').context['form'].errors
        self.assertTrue(errors, 'the overlap is refused with a message, not a server error')
        self.assertEqual(AttendanceRecord.objects.count(), 1)
        self.post(self.in_a, '2026-03-02T10:00', '')                       # an open stretch from the 10th hour on: allowed
        errors = self.post(self.in_a, '2026-03-02T12:00', '2026-03-02T13:00').context['form'].errors
        self.assertTrue(errors)

    def test_the_overlap_is_checked_on_the_sites_clock_never_read_as_utc(self):
        # The form's overlap check (the exclusion constraint) must see the instants the typed times stand for, as the
        # database does: a time typed on the Oslo clock read as UTC is an hour off in winter.
        Site.objects.filter(pk=self.site.pk).update(timezone='Europe/Oslo')
        punch(self.in_a, at(6), at(7))                                     # 07:00 to 08:00 on the Oslo clock
        response = self.post(self.in_a, '2026-03-02T06:00', '2026-03-02T07:00')     # just before it: 05:00 to 06:00 UTC
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        self.assertEqual(sorted(AttendanceRecord.objects.values_list('clock_in', flat=True)), [at(5), at(6)])
        errors = self.post(self.in_a, '2026-03-02T07:30', '2026-03-02T08:30').context['form'].errors  # inside it
        self.assertIn('clock_out', errors)
        self.assertEqual(AttendanceRecord.objects.count(), 2)

    def test_a_person_outside_the_team_is_not_a_choice_and_other_teams_stretches_are_404(self):
        before = (AttendanceRecord.objects.count(), AuditLog.objects.count())
        response = self.post(self.in_b, '2026-03-02T06:00', '2026-03-02T10:00')
        self.assertIn('employee', response.context['form'].errors)
        other = punch(self.in_b, at(6), at(10))
        for method, name in (('get', 'hr:production_attendancerecord_edit'), ('post', 'hr:production_attendancerecord_edit'),
                             ('get', 'hr:production_attendancerecord_delete'), ('post', 'hr:production_attendancerecord_delete')):
            self.assertEqual(getattr(self.client, method)(reverse(name, args=[other.pk]), {'version': '1'}).status_code, 404)
        rows = self.client.get(reverse('hr:production_attendancerecord_list'), {'from': '2026-03-01', 'to': '2026-03-03'}
                               ).context['objects']
        self.assertEqual(list(rows), [])
        self.assertEqual((AttendanceRecord.objects.count(), AuditLog.objects.count()), (before[0] + 1, before[1]))

    def test_the_service_checks_the_verb_the_team_and_the_reason(self):
        for actor, person, note, error in ((self.lead, self.in_b, 'x', PermissionDenied),
                                           (user('reader', *PUNCH_PERMS, group='Reader role'), self.in_a, 'x', PermissionDenied),
                                           (self.lead, self.in_a, '  ', ValidationError)):
            with self.assertRaises(error):
                services.enter_presence(actor, person, at(6), at(7), note)
        self.assertEqual(AttendanceRecord.objects.count(), 0)
        record = services.enter_presence(self.lead, self.in_a, at(6), None, ' Late phone ')
        self.assertEqual((record.note, record.via, record.clock_out), ('Late phone', 'entered', None))

    def test_the_page_heading_is_attendance_not_today_though_the_permission_is_shared(self):
        self.client.force_login(self.lead)
        response = self.client.get(reverse('hr:production_attendancerecord_list'))
        self.assertEqual((response.context['title'], response.context['group']), ('Attendance', 'Time & attendance'))


class BoardTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14), grace_minutes=10)
        self.night = Shift.objects.create(name='Night', code='NIGHT', starts_at=time(22), ends_at=time(6))
        self.lead = user('boss', *PUNCH_PERMS, group='Board role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.lead)
        self.ben = employee('E-80', 'Bergh')
        place(self.ben, self.dept_a)
        self.cy = employee('E-81', 'Cyr')
        place(self.cy, self.dept_a)
        SchedulingSettings.get()

    def plan(self, person, shift, day=DAY):
        return ShiftAssignment.objects.create(employee=person, day=day, shift=shift)

    def states(self, moment, actor=None):
        board = read.board(actor or self.lead, moment)
        return {row.employee.last_name: row.state for row in board.rows}, board

    def test_the_states_come_from_the_plan_the_punches_and_the_leave_at_a_fixed_now(self):
        for person in (self.in_a, self.ben, self.cy):
            self.plan(person, self.early)
        punch(self.in_a, at(6, 3))                                   # in on time, still in
        punch(self.ben, at(6, 40), at(9))                             # late, and gone again
        states, board = self.states(at(10))
        self.assertEqual(states, {'Alfa': 'present', 'Bergh': 'done', 'Cyr': 'absent'})
        self.assertEqual(board.counts, {'present': 1, 'done': 1, 'absent': 1})
        self.assertEqual((board.planned, board.here), (3, 1))
        row = next(r for r in board.rows if r.employee == self.ben)
        self.assertEqual((row.standing.late_minutes, row.standing.first_in, row.standing.last_out), (30, at(6, 40), at(9)))
        states, _ = self.states(at(6, 5))
        self.assertEqual(states, {'Alfa': 'present', 'Bergh': 'upcoming', 'Cyr': 'upcoming'})
        states, _ = self.states(at(6, 20))
        self.assertEqual(states['Cyr'], 'not_in')

    def test_people_planned_off_or_with_no_plan_are_not_listed_unless_they_are_there(self):
        self.plan(self.in_a, None)                                     # planned off
        states, _ = self.states(at(8))
        self.assertEqual(states, {})
        punch(self.ben, at(7))                                          # not planned, but here
        states, board = self.states(at(8))
        self.assertEqual(states, {'Bergh': 'present'})
        self.assertTrue(board.rows[0].unscheduled)

    def test_approved_leave_is_listed_on_leave_and_pending_leave_is_not_leave(self):
        kind = LeaveType.objects.create(name='Annual', code='AN')
        for person, status in ((self.in_a, 'approved'), (self.ben, 'pending')):
            LeaveRequest.objects.create(employee=person, leave_type=kind, first_day=DAY, last_day=DAY, status=status,
                                        decided_at=at(1) if status == 'approved' else None)
            self.plan(person, self.early)
        states, _ = self.states(at(10))
        self.assertEqual(states['Alfa'], 'on_leave')
        self.assertEqual(states['Bergh'], 'absent')

    def test_a_night_shift_that_began_yesterday_is_judged_until_it_ends(self):
        self.plan(self.in_a, self.night, DAY - timedelta(days=1))                # 22:00 on the 1st to 06:00 on the 2nd
        punch(self.in_a, at(22, 5, DAY - timedelta(days=1)))
        states, _ = self.states(at(3))
        self.assertEqual(states, {'Alfa': 'late'})                               # five minutes in, and this shift has no grace
        states, _ = self.states(at(7))                                           # the night is over, nothing planned today
        self.assertEqual(states, {'Alfa': 'present'})                            # still clocked in: still a presence

    def test_each_person_is_read_on_their_sites_clock(self):
        auckland = Site.objects.create(name='Auckland', code='AK', timezone='Pacific/Auckland')
        far = ProductionDepartment.objects.create(site=auckland, name='Far hall', code='FAR', manager=self.lead)
        kiwi = employee('E-90', 'Kiwi')
        place(kiwi, far)
        # 2026-03-02 22:00 UTC is 11:00 on the 3rd in Auckland (UTC+13): a shift planned on the 3rd, 06:00 local, is under way
        self.plan(kiwi, self.early, DAY + timedelta(days=1))
        self.plan(self.in_a, self.early, DAY)
        moment = at(22)
        states, board = self.states(moment)
        self.assertEqual(states, {'Alfa': 'absent', 'Kiwi': 'absent'})            # in Auckland it is the 3rd and 11:00
        self.assertEqual(next(r for r in board.rows if r.employee == kiwi).day, DAY + timedelta(days=1))
        states, _ = self.states(at(8))                                            # 21:00 on the 2nd in Auckland: the 3rd's shift is ahead
        self.assertEqual(states, {'Alfa': 'absent'})

    def test_the_board_shows_only_the_viewers_team_and_everyone_shows_all(self):
        for person in (self.in_a, self.in_b):
            self.plan(person, self.early)
        self.assertEqual(set(self.states(at(10))[0]), {'Alfa'})
        self.assertEqual(set(self.states(at(10), self.hr)[0]), {'Alfa', 'Bravo'})

    def test_the_queries_do_not_grow_with_the_people(self):
        read.board(self.lead, at(10))
        def count(people):
            for n in range(people):
                person = employee(f'E-{5000 + n + people}', f'Many{n}')
                place(person, self.dept_a)
                self.plan(person, self.early)
                punch(person, at(6, 2))
            with CaptureQueriesContext(connection) as queries:
                read.board(self.lead, at(10))
            return len(queries)
        self.assertEqual(count(4), count(40))


class TodayPageTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(0), ends_at=time(23, 59))
        self.lead = user('boss', *ENTER_PERMS, group='Today role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.lead)

    def test_the_page_the_fragment_and_the_numbers_for_the_viewers_team_only(self):
        today = site_today(None)
        for person in (self.in_a, self.in_b):
            ShiftAssignment.objects.create(employee=person, day=today, shift=self.early)
        self.client.force_login(self.lead)
        page = self.client.get(reverse('hr:production_today'))
        self.assertEqual(page.status_code, 200)
        self.assertEqual([r.employee.last_name for r in page.context['board'].rows], ['Alfa'])
        self.assertContains(page, reverse('hr:production_today_board'))                       # the page polls its own fragment
        fragment = self.client.get(reverse('hr:production_today_board'))
        self.assertEqual(fragment.status_code, 200)
        self.assertContains(fragment, 'Alfa')
        self.assertNotContains(fragment, 'Bravo')
        self.assertContains(page, reverse('hr:production_attendancerecord_create'))           # Mark present

    def test_the_verb_decides_and_no_hr_page_is_open_without_it(self):
        stranger = user('stranger')
        for name in ('hr:production_today', 'hr:production_today_board'):
            self.client.force_login(stranger)
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
            self.client.logout()
            self.assertEqual(self.client.get(reverse(name)).status_code, 302, name)

    def test_a_person_who_never_clocks_has_no_buttons(self):
        self.client.force_login(self.lead)
        self.assertNotContains(self.client.get(reverse('hr:production_today')), reverse('hr:production_punch', args=['in']))
