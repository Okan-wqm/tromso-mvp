"""A forgotten clock-out (owner decision F-095, 2026-11-10). A clock-in still open longer than the limit of Scheduling
settings (16 hours until HR sets another, never a constant in the code) counts as forgotten: nobody knows when the person
left, so the board says "Clock-out forgotten" instead of present, the person is told in words to ask their lead and
neither clocks in nor out (clocking out now would invent the hours since), and whoever may correct that person's
attendance closes the stretch on the Attendance page with the real time and a reason, logged. The emergency count still
counts it (an open clock-in may be a person on site) and says how many are that old."""
import re
from datetime import date, datetime, time, timedelta, timezone as utc
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase
from django.urls import reverse

from core.audit import message
from core.models import AuditLog
from farm.models import ProductionDepartment

from .. import read, rules, services
from ..models import AttendanceRecord, Employee, SchedulingSettings, Shift, ShiftAssignment
from .helpers import PRIVATE, user
from .helpers_people import PeopleTestCase, employee, place
from .test_scheduling_settings import SettingsTestCase, shift_data

UTC = utc.utc
DAY = date(2026, 3, 2)
PUNCH_PERMS = ('view_employee', 'view_attendancerecord')
ENTER_PERMS = (*PUNCH_PERMS, 'add_attendancerecord', 'change_attendancerecord', 'delete_attendancerecord')
LABEL = 'A clock-in counts as forgotten after (hours)'
TOLD = ('Your clock-in of 27.02.2026 07:00 was never closed: it has been open more than 16 hours and counts as a '
        'forgotten clock-out. Ask your lead to close it on the Attendance page with the time you really left; then you '
        'can clock in again.')
GOOD = {'standard_week_minutes': '2400', 'min_rest_minutes': '660', 'max_consecutive_days': '6', 'rest_rule': 'warn',
        'working_weekdays': ['0'], 'punch_window_minutes': '120', 'absent_after_minutes': '30', 'version': '1'}


def at(hour, minute=0, day=DAY):
    return datetime.combine(day, time(hour, minute), tzinfo=UTC)


def ago(days):
    return DAY - timedelta(days=days)


def punch(person, start, end=None, **fields):
    fields.setdefault('via', 'self')
    return AttendanceRecord.objects.create(employee=person, clock_in=start, clock_out=end, **fields)


def now(moment):
    return mock.patch('django.utils.timezone.now', return_value=moment)


class ForgottenRuleTests(SimpleTestCase):
    """rules.forgotten and rules.status, pure, at a fixed now."""

    SPAN = (at(6), at(14))

    def standing(self, punches, on_leave=False, span=SPAN, limit=16):
        return rules.status(span, punches, on_leave, at(10), 10, 30, 120, limit)

    def test_a_stretch_is_forgotten_only_while_open_and_longer_than_the_limit(self):
        self.assertFalse(rules.forgotten(at(0), None, at(16), 16))               # exactly the limit: not yet
        self.assertTrue(rules.forgotten(at(0), None, at(16, 1), 16))
        self.assertFalse(rules.forgotten(at(0), at(1), at(23), 16))              # closed: never
        self.assertTrue(rules.forgotten(at(0), None, at(12, 1), 12))             # the limit is the setting's
        self.assertFalse(rules.forgotten(at(0), None, at(12, 1), 13))

    def test_the_state_is_forgotten_whatever_the_plan_the_leave_or_the_stretches_before(self):
        old = at(7, day=ago(3))
        for on_leave, span in ((False, self.SPAN), (True, self.SPAN), (False, None), (True, None)):
            standing = self.standing([(old, None)], on_leave, span)
            self.assertEqual((standing.state, standing.first_in, standing.last_out, standing.late_minutes),
                             ('forgotten', old, None, 0), (on_leave, span))
        worked = [(at(6, day=ago(1)), at(14, day=ago(1))), (at(15, day=ago(1)), None)]      # came back, never left
        self.assertEqual((self.standing(worked).state, self.standing(worked).first_in), ('forgotten', at(15, day=ago(1))))

    def test_under_the_limit_an_open_clock_in_is_a_presence_as_before(self):
        self.assertEqual(self.standing([(at(1), None)]).state, 'present')                    # 9 hours
        self.assertEqual(self.standing([(at(19, day=ago(1)), None)]).state, 'present')       # 15 hours
        self.assertEqual(self.standing([(at(19, day=ago(1)), None)], limit=12).state, 'forgotten')
        self.assertIn('forgotten', rules.STATES)


class ForgottenSettingTests(SettingsTestCase):
    def post(self, **values):
        row = SchedulingSettings.objects.get()
        return self.client.post(reverse('hr:schedulingsettings_edit', args=[row.pk]),
                                {**GOOD, 'version': str(row.version), **values})

    def test_the_limit_is_16_hours_until_hr_sets_another_shown_edited_and_logged(self):
        row = SchedulingSettings.objects.get()
        self.assertEqual(row.forgotten_after_hours, 16)                         # the migration's row
        page = self.client.get(reverse('hr:schedulingsettings_list'))
        self.assertContains(page, f'<dt>{LABEL}</dt><dd>16</dd>')
        form = self.client.get(reverse('hr:schedulingsettings_edit', args=[row.pk]), headers={'X-Modal': '1'})
        self.assertContains(form, 'name="forgotten_after_hours"')
        self.assertContains(form, 'Default 16 hours')
        self.assertEqual(self.post(forgotten_after_hours='12').status_code, 302)
        row.refresh_from_db()
        self.assertEqual((row.forgotten_after_hours, row.version), (12, 2))
        entry = AuditLog.objects.get(entity_id=str(row.pk), action='update')
        self.assertEqual(entry.changes[LABEL], ['16', '12'])
        self.assertEqual(entry.user, self.user)

    def test_a_blank_or_absurd_value_is_refused_with_its_reason_and_nothing_changes(self):
        said = {'': 'Say after how many hours an open clock-in counts as a forgotten clock-out.',
                '0': 'Give a whole number of hours from 1 to 168 (a week).',
                '169': 'Give a whole number of hours from 1 to 168 (a week).',
                '-3': 'Give a whole number of hours from 1 to 168 (a week).',
                'x': 'Enter a whole number.', '7.5': 'Enter a whole number.'}
        before = AuditLog.objects.count()
        for value, reason in said.items():
            with self.subTest(value=value):
                errors = self.post(forgotten_after_hours=value).context['form'].errors
                self.assertEqual(errors, {'forgotten_after_hours': [reason]})
        self.assertEqual(SchedulingSettings.objects.get().forgotten_after_hours, 16)
        self.assertEqual(AuditLog.objects.count(), before)
        with connection.cursor() as cursor:
            for value in (0, 169):
                with self.assertRaisesMessage(IntegrityError, 'chk_scheduling_forgotten_after'), transaction.atomic():
                    cursor.execute('UPDATE scheduling_settings SET forgotten_after_hours = %s', [value])

    def test_a_limit_shorter_than_an_active_shift_and_its_punch_window_is_refused_naming_the_shift(self):
        """A person on a 14-hour shift who clocked in when the punch window opened (120 minutes before it) must not
        count as forgotten before the shift ends: they could not clock out (review R8)."""
        Shift.objects.create(name='Long day', code='LONG', starts_at=time(6), ends_at=time(20))
        Shift.objects.create(name='Old watch', code='WATCH', starts_at=time(0), ends_at=time(23), status='inactive')
        said = ('The shift Long day (LONG) and the 120 minutes a person may clock in before it are longer than %s '
                'hours: a person on it would count as forgotten before it ends.')
        for hours in ('13', '14', '15'):
            errors = self.post(forgotten_after_hours=hours).context['form'].errors
            self.assertEqual(errors, {'forgotten_after_hours': [said % hours]}, hours)
        self.assertEqual(self.post(forgotten_after_hours='16').status_code, 302)      # the shift and its window: allowed
        row = SchedulingSettings.objects.get()
        self.assertEqual(row.forgotten_after_hours, 16)
        # the window counts too: widening it alone is refused the same way
        errors = self.post(forgotten_after_hours='16', punch_window_minutes='180', version=str(row.version)
                           ).context['form'].errors
        self.assertEqual(errors, {'forgotten_after_hours': [
            'The shift Long day (LONG) and the 180 minutes a person may clock in before it are longer than 16 hours: a '
            'person on it would count as forgotten before it ends.']})

    def test_a_shift_too_long_for_the_limit_is_refused_until_the_limit_is_raised(self):
        said = ('This shift and the 120 minutes a person may clock in before it are longer than the 16 hours after '
                'which a clock-in counts as forgotten (Scheduling settings): raise that limit first.')
        for ends_at in ('23:00', '20:01'):                                   # 17 hours; 14 hours 1 minute and the window
            response = self.client.post(reverse('hr:shift_create'), shift_data(starts_at='06:00', ends_at=ends_at))
            self.assertEqual(response.context['form'].errors, {'ends_at': [said]}, ends_at)
        self.assertFalse(Shift.objects.exists())
        self.assertEqual(self.client.post(reverse('hr:shift_create'), shift_data(
            starts_at='06:00', ends_at='23:00', status='inactive')).status_code, 302)   # not planned: nobody is on it
        SchedulingSettings.objects.update(forgotten_after_hours=19)
        self.assertEqual(self.client.post(reverse('hr:shift_create'), shift_data(
            code='long', starts_at='06:00', ends_at='23:00')).status_code, 302)

    def test_with_settings_the_forms_accept_an_early_clock_in_is_never_forgotten_before_the_shift_ends(self):
        """The reviewer's case: a 06:00-20:00 shift, the limit the least the forms allow for it (16), a clock-in when
        the punch window opens (04:00). At 20:00 the person is still present, not forgotten: they can clock out."""
        long_day = Shift.objects.create(name='Long day', code='LONG', starts_at=time(6), ends_at=time(20))
        self.assertEqual(self.post(forgotten_after_hours='16').status_code, 302)
        row = SchedulingSettings.objects.get()
        standing = rules.status((at(6), at(20)), [(at(4), None)], False, at(20), long_day.grace_minutes,
                                row.absent_after_minutes, row.punch_window_minutes, row.forgotten_after_hours)
        self.assertEqual(standing.state, 'present')

    def test_the_setting_speaks_each_language(self):
        from core.models import Profile
        for language, words in {'nb': 'En innstempling regnes som glemt etter (timer)',
                                'tr': 'Girişin unutulmuş sayılacağı süre (saat)'}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            self.assertContains(self.client.get(reverse('hr:schedulingsettings_list')), words)


class ForgottenTestCase(PeopleTestCase):
    """Ann (E-1, department A) clocked in on 27 February at 07:00 and never clocked out; it is 2 March, 10:00. Her lead
    may enter and correct attendance."""

    def setUp(self):
        super().setUp()
        self.ann = user('ann', *PUNCH_PERMS, group='Punch role')
        Employee.objects.filter(pk=self.in_a.pk).update(user=self.ann, first_name='', last_name='')
        self.in_a.refresh_from_db()
        self.lead = user('boss', *ENTER_PERMS, group='Enter role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.lead)
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        self.open = punch(self.in_a, at(7, day=ago(3)))
        SchedulingSettings.get()

    def messages(self, response):
        return [str(found) for found in response.context['messages']]


class BoardTests(ForgottenTestCase):
    def setUp(self):
        super().setUp()
        self.ben = employee('E-80', 'Bergh')
        self.cy = employee('E-81', 'Cyr')
        for person in (self.ben, self.cy):
            place(person, self.dept_a)
        for person in (self.in_a, self.ben):
            ShiftAssignment.objects.create(employee=person, day=DAY, shift=self.early)
        punch(self.ben, at(21, day=ago(1)))                                # 13 hours ago: long, not forgotten
        punch(self.cy, at(8, day=ago(2)))                                  # two days ago, and nothing planned today

    def page(self, actor=None):
        self.client.force_login(actor or self.lead)
        with now(at(10)):
            return self.client.get(reverse('hr:production_today_board')).content.decode()

    def test_a_forgotten_clock_out_is_its_own_state_never_a_presence_and_the_tiles_still_add_up(self):
        board = read.board(self.lead, at(10))
        self.assertEqual({row.employee.employee_number: row.state for row in board.rows},
                         {'E-1': 'forgotten', 'E-80': 'present', 'E-81': 'forgotten'})
        self.assertEqual(board.counts, {'forgotten': 1, 'present': 1})
        tiles = dict((tile.key, tile.count) for tile in board.tiles)
        self.assertEqual((board.planned, sum(tiles.values()), tiles['forgotten'], tiles['here']), (2, 2, 1, 1))
        # Cyr, not planned, is listed but is neither "here, not planned" nor done: nobody knows
        self.assertEqual((board.unplanned, board.unplanned_done, board.unplanned_forgotten), (0, 0, 1))
        row = next(row for row in board.rows if row.employee == self.in_a)
        self.assertEqual((row.standing.first_in, row.standing.last_out), (at(7, day=ago(3)), None))

    def test_the_emergency_count_keeps_every_open_clock_in_and_says_how_many_are_forgotten(self):
        """An open clock-in may be a person on site (someone back at work who could not clock in): the muster count never
        drops it; it says how many are older than the limit, with the limit's own number."""
        board = read.board(self.lead, at(10))
        self.assertEqual((board.on_site, board.forgotten_open, board.forgotten_after_hours), (3, 2, 16))
        page = self.page()
        shown = dict((label, count) for count, label in re.findall(
            r'<span class="tile-count">(\d+)</span><span class="tile-label">([^<]+)</span>', page))
        self.assertEqual((shown['On site now'], shown['Here now'], shown['Clock-out forgotten']), ('3', '1', '1'))
        self.assertNotIn('Here, not planned', shown)
        self.assertIn('2 of them open more than 16 hours: clock-out forgotten', page)
        self.assertIn('1 more not planned today', page)
        self.assertIn('Open since 27.02.2026 07:00: to be closed on the Attendance page', page)   # the site's clock
        self.assertIn('badge-state-forgotten', page)
        self.assertNotIn('12 hours', page)

    def test_the_limit_is_read_from_the_setting(self):
        SchedulingSettings.objects.update(forgotten_after_hours=12)
        board = read.board(self.lead, at(10))
        self.assertEqual({row.state for row in board.rows}, {'forgotten'})          # Bergh's 13 hours too
        self.assertEqual((board.on_site, board.forgotten_open), (3, 3))
        self.assertIn('3 of them open more than 12 hours: clock-out forgotten', self.page())
        SchedulingSettings.objects.update(forgotten_after_hours=96)
        self.assertEqual({row.state for row in read.board(self.lead, at(10)).rows}, {'present'})

    def test_the_row_leads_who_may_correct_it_to_the_stretch_and_nobody_else(self):
        close = reverse('hr:production_attendancerecord_edit', args=[self.open.pk])
        self.assertIn(f'href="{close}"', self.page())
        reader = user('reader', *PUNCH_PERMS, 'all_production_employee', group='Reader role')
        self.assertNotIn(close, self.page(reader))
        self.assertIn('Clock-out forgotten', self.page(reader))

    def test_the_queries_do_not_grow_with_the_people(self):
        from django.test.utils import CaptureQueriesContext
        read.board(self.lead, at(10))                                       # the lead's rights are read once

        def count(people):
            for n in range(people):
                person = employee(f'E-{7000 + n + people}', f'Many{n}')
                place(person, self.dept_a)
                punch(person, at(7, day=ago(2)))
            with CaptureQueriesContext(connection) as queries:
                read.board(self.lead, at(10))
            return len(queries)
        self.assertEqual(count(4), count(40))


class PersonTests(ForgottenTestCase):
    def test_the_person_is_told_in_words_and_offered_neither_button(self):
        self.client.force_login(self.ann)
        with now(at(10)):
            page = self.client.get(reverse('hr:production_today'))
        self.assertContains(page, TOLD)
        self.assertNotContains(page, reverse('hr:production_punch', args=['in']))
        self.assertNotContains(page, reverse('hr:production_punch', args=['out']))
        self.assertNotContains(page, 'Clocked in since')

    def test_neither_a_clock_in_nor_a_clock_out_is_taken_and_nothing_is_written(self):
        """A clock-out now would store three days of work nobody did; a second clock-in cannot stand beside an open one."""
        before = (AttendanceRecord.objects.count(), AuditLog.objects.count())
        self.client.force_login(self.ann)
        for direction in ('in', 'out'):
            with self.subTest(direction=direction), now(at(10)):
                response = self.client.post(reverse('hr:production_punch', args=[direction]), follow=True)
                self.assertEqual(self.messages(response), [TOLD])
                with self.assertRaisesMessage(ValidationError, TOLD):
                    (services.clock_in if direction == 'in' else services.clock_out)(self.ann)
        self.open.refresh_from_db()
        self.assertEqual((self.open.clock_out, self.open.version), (None, 1))
        self.assertEqual((AttendanceRecord.objects.count(), AuditLog.objects.count()), before)

    def test_under_the_limit_the_person_clocks_out_as_before(self):
        with now(at(22, day=ago(3))):                                       # 15 hours after 07:00
            self.client.force_login(self.ann)
            page = self.client.get(reverse('hr:production_today'))
            self.assertContains(page, reverse('hr:production_punch', args=['out']))
            self.assertNotContains(page, 'forgotten')
            services.clock_out(self.ann)
        self.open.refresh_from_db()
        self.assertEqual(self.open.clock_out, at(22, day=ago(3)))

    def test_the_sentence_names_the_limit_as_set_and_the_time_on_the_sites_clock(self):
        from farm.models import Site
        Site.objects.filter(pk=self.site.pk).update(timezone='Europe/Oslo')
        SchedulingSettings.objects.update(forgotten_after_hours=24)
        with now(at(10)), self.assertRaises(ValidationError) as refused:
            services.clock_in(self.ann)
        self.assertIn('Your clock-in of 27.02.2026 08:00 was never closed: it has been open more than 24 hours',
                      refused.exception.messages[0])


class ClosingTests(ForgottenTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('hr:production_attendancerecord_edit', args=[self.open.pk])

    def close(self, actor=None, **values):
        self.client.force_login(actor or self.lead)
        with now(at(10)):
            return self.client.post(self.url, {'clock_in': '2026-02-27T07:00', 'clock_out': '2026-02-27T15:30',
                                               'note': 'Went home at half past three, phone was flat',
                                               'version': '1', **values})

    def test_the_attendance_page_lists_it_whatever_its_age_and_says_it_is_forgotten(self):
        AttendanceRecord.objects.filter(pk=self.open.pk).update(clock_in=at(7, day=ago(20)))    # older than the fortnight
        punch(self.in_a, at(6, day=ago(30)), at(14, day=ago(30)))                               # closed and old: not listed
        self.client.force_login(self.lead)
        with now(at(10)):
            page = self.client.get(reverse('hr:production_attendancerecord_list'))
        self.assertEqual([record.pk for record in page.context['objects']], [self.open.pk])
        self.assertContains(page, 'Clock-out forgotten')
        self.assertContains(page, self.url)

    def test_the_lead_closes_it_with_the_real_time_and_a_reason_and_it_is_logged(self):
        errors = self.close(note='').context['form'].errors
        self.assertEqual(errors, {'note': ['Say why the time was entered by hand.']})
        self.open.refresh_from_db()
        self.assertEqual((self.open.clock_out, self.open.via, self.open.version), (None, 'self', 1))
        self.assertEqual(self.close().status_code, 302)
        self.open.refresh_from_db()
        self.assertEqual((self.open.clock_in, self.open.clock_out, self.open.via, self.open.note, self.open.updated_by,
                          self.open.version),
                         (at(7, day=ago(3)), at(15, 30, day=ago(3)), 'entered',
                          'Went home at half past three, phone was flat', self.lead, 2))
        entry = AuditLog.objects.get(entity_id=str(self.open.pk), action='update')
        self.assertEqual((entry.user, entry.changes), (self.lead, {
            'Clock out': [None, '2026-02-27 15:30:00+00:00'],
            'How': [message('Clocked in by the person'), message('Entered by hand')],
            'Note': [None, PRIVATE]}))
        self.assertNotIn('phone was flat', str(entry.changes))

    def test_once_closed_the_person_is_off_the_board_and_clocks_in_again(self):
        self.close()
        board = read.board(self.lead, at(10))
        self.assertEqual(([row.state for row in board.rows], board.on_site, board.forgotten_open), ([], 0, 0))
        with now(at(10)):
            record = services.clock_in(self.ann)
        self.assertEqual((record.clock_in, record.via), (at(10), 'self'))
        self.assertEqual(read.board(self.lead, at(10, 5)).rows[0].state, 'present')

    def test_only_who_may_correct_that_persons_attendance_closes_it(self):
        """The existing scope: Edit on Attendance and the person in one's team on the stretch's day; never one's own."""
        before = AuditLog.objects.count()
        reader = user('reader', *PUNCH_PERMS, 'all_production_employee', group='Reader role')
        other = user('otherlead', *ENTER_PERMS, group='Other lead role')
        ProductionDepartment.objects.filter(pk=self.dept_b.pk).update(manager=other)
        self.ann.groups.add(self.lead.groups.get())                          # Edit on Attendance, on her own stretch
        for actor, status in ((reader, 403), (other, 404), (self.ann, 403)):
            self.assertEqual(self.close(actor).status_code, status, actor.username)
        self.open.refresh_from_db()
        self.assertEqual((self.open.clock_out, AuditLog.objects.count()), (None, before))

    def test_a_correction_that_changes_a_time_the_person_clocked_needs_its_reason_too(self):
        """Not only a forgotten one: a time typed by hand is an entered time (the table's own rule), whoever clocked in."""
        done = punch(self.in_b, at(6), at(14))
        boss_b = user('bossb', *ENTER_PERMS, group='Enter B role')
        ProductionDepartment.objects.filter(pk=self.dept_b.pk).update(manager=boss_b)
        self.client.force_login(boss_b)
        url = reverse('hr:production_attendancerecord_edit', args=[done.pk])
        same = {'clock_in': '2026-03-02T06:00', 'clock_out': '2026-03-02T14:00', 'note': '', 'version': '1'}
        self.assertEqual(self.client.post(url, same).status_code, 302)       # nothing typed anew: still the person's own
        done.refresh_from_db()
        self.assertEqual((done.via, done.version), ('self', 2))
        errors = self.client.post(url, {**same, 'clock_out': '2026-03-02T15:00', 'version': '2'}).context['form'].errors
        self.assertEqual(errors, {'note': ['Say why the time was entered by hand.']})
        self.assertEqual(self.client.post(url, {**same, 'clock_out': '2026-03-02T15:00', 'note': 'Stayed an hour',
                                                'version': '2'}).status_code, 302)
        done.refresh_from_db()
        self.assertEqual((done.clock_out, done.via), (at(15), 'entered'))


class NoTimeAheadTests(ForgottenTestCase):
    """Review R6: a time typed by hand is a time that has been. A clock-out ahead of now would close a forgotten stretch
    days ahead (invented hours), keep the person from clocking in with the wrong sentence and take them out of every
    count; so neither a clock-in nor a clock-out later than the server's now is taken, on the form or by the service."""

    AHEAD_OUT = 'The clock-out cannot be later than now: give the time the person really left.'
    AHEAD_IN = 'The clock-in cannot be later than now.'

    def post(self, url, **values):
        self.client.force_login(self.lead)
        with now(at(10)):
            return self.client.post(url, {'clock_in': '2026-02-27T07:00', 'clock_out': '', 'note': 'Phone was flat',
                                          **values})

    def test_a_forgotten_stretch_is_not_closed_with_a_time_ahead(self):
        url = reverse('hr:production_attendancerecord_edit', args=[self.open.pk])
        before = AuditLog.objects.count()
        errors = self.post(url, clock_out='2026-03-05T15:30', version='1').context['form'].errors
        self.assertEqual(errors, {'clock_out': [self.AHEAD_OUT]})
        errors = self.post(url, clock_out='2026-03-02T10:01', version='1').context['form'].errors     # a minute ahead
        self.assertEqual(errors, {'clock_out': [self.AHEAD_OUT]})
        self.open.refresh_from_db()
        self.assertEqual((self.open.clock_out, self.open.via, AuditLog.objects.count()), (None, 'self', before))
        board = read.board(self.lead, at(10))
        self.assertEqual((board.on_site, board.forgotten_open), (1, 1))             # still counted, still to be closed
        self.assertEqual(self.post(url, clock_out='2026-03-02T10:00', version='1').status_code, 302)   # now itself
        self.open.refresh_from_db()
        self.assertEqual(self.open.clock_out, at(10))

    def test_presence_is_not_entered_ahead_on_the_form_or_by_the_service(self):
        self.open.soft_delete(self.lead)
        url = reverse('hr:production_attendancerecord_create')
        errors = self.post(url, employee=str(self.in_a.pk), clock_in='2026-03-09T07:00').context['form'].errors
        self.assertEqual(errors, {'clock_in': [self.AHEAD_IN]})
        errors = self.post(url, employee=str(self.in_a.pk), clock_in='2026-03-02T07:00',
                           clock_out='2026-03-02T15:00').context['form'].errors
        self.assertEqual(errors, {'clock_out': [self.AHEAD_OUT]})
        with now(at(10)):
            for start, end, sentence in ((at(11), None, self.AHEAD_IN), (at(7), at(15), self.AHEAD_OUT)):
                with self.assertRaisesMessage(ValidationError, sentence):
                    services.enter_presence(self.lead, self.in_a, start, end, 'Phone was flat')
            self.assertFalse(AttendanceRecord.objects.exists())
            record = services.enter_presence(self.lead, self.in_a, at(7), at(10), 'Phone was flat')
        self.assertEqual(record.clock_out, at(10))


class MovedPersonTests(ForgottenTestCase):
    """Review R9: Ann moved from department A to B on 1 March; her stretch has been open since 27 February. She is told
    to ask her lead, so her lead of today closes it: an open stretch is reached by whoever reaches the person today,
    as well as by whoever reached them on its first day. A closed stretch stays with the manager of its day."""

    def setUp(self):
        super().setUp()
        from ..models import Posting
        Posting.objects.filter(employee=self.in_a).update(valid_until=date(2026, 2, 28))
        place(self.in_a, self.dept_b, start=date(2026, 3, 1))
        self.new_lead = user('newlead', *ENTER_PERMS, group='New lead role')
        ProductionDepartment.objects.filter(pk=self.dept_b.pk).update(manager=self.new_lead)
        self.closed = punch(self.in_a, at(6, day=ago(4)), at(14, day=ago(4)))       # 26 February, closed: history
        self.edit = reverse('hr:production_attendancerecord_edit', args=[self.open.pk])

    def sees(self, actor):
        self.client.force_login(actor)
        with now(at(10)):
            board = self.client.get(reverse('hr:production_today_board')).content.decode()
            listed = [record.pk for record in self.client.get(
                reverse('hr:production_attendancerecord_list')).context['objects']]
            return ('Clock-out forgotten' in board, self.edit in board, self.client.get(self.edit).status_code,
                    self.open.pk in listed, self.closed.pk in listed)

    def test_the_lead_of_today_and_the_lead_of_its_first_day_both_reach_the_open_stretch(self):
        #                                   row    link   opens  listed  the closed one listed
        self.assertEqual(self.sees(self.new_lead), (True, True, 200, True, False))
        self.assertEqual(self.sees(self.lead), (False, False, 200, True, True))     # not on their board: not their person today

    def test_the_lead_of_today_closes_it_and_it_is_logged_as_theirs(self):
        self.client.force_login(self.new_lead)
        with now(at(10)):
            response = self.client.post(self.edit, {'clock_in': '2026-02-27T07:00', 'clock_out': '2026-02-27T15:30',
                                                    'note': 'Left at half past three', 'version': '1'})
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        self.open.refresh_from_db()
        self.assertEqual((self.open.clock_out, self.open.via, self.open.updated_by),
                         (at(15, 30, day=ago(3)), 'entered', self.new_lead))
        self.assertEqual(AuditLog.objects.get(entity_id=str(self.open.pk), action='update').user, self.new_lead)
        # closed, it is history of its day: the old lead's, no longer the new one's
        self.assertEqual(self.client.get(self.edit).status_code, 404)

    def test_a_closed_stretch_of_before_the_move_is_not_the_new_leads(self):
        self.client.force_login(self.new_lead)
        url = reverse('hr:production_attendancerecord_edit', args=[self.closed.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'clock_in': '2026-02-26T06:00', 'clock_out': '2026-02-26T15:00',
                                                'note': 'x', 'version': '1'}).status_code, 404)
