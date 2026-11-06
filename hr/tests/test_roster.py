from datetime import date, time

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import AuditLog
from farm.models import ProductionDepartment, Site

from .. import read, services
from ..models import Employee, Holiday, Posting, SchedulingSettings, Shift, ShiftAssignment
from ..units import token
from .helpers import PRIVATE, fields_of, user
from .helpers_people import PeopleTestCase, TOP, employee, place

MONDAY = date(2026, 3, 2)
PLANNER_PERMS = ('view_employee', 'view_shiftassignment', 'add_shiftassignment', 'change_shiftassignment',
                 'delete_shiftassignment')


def shift(code, start, end, **fields):
    return Shift.objects.create(name=code.title(), code=code, starts_at=start, ends_at=end, **fields)


class RosterTestCase(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.early = shift('EARLY', time(6), time(14), break_minutes=30, tone=2)
        self.late = shift('LATE', time(14), time(22), break_minutes=30, tone=3)
        self.night = shift('NIGHT', time(22), time(6), tone=4)
        self.planner = user('planner', *PLANNER_PERMS, group='Planner role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.planner)
        self.url = reverse('hr:production_shiftassignment_list')

    def cell(self, person, day, which=None, **fields):
        return ShiftAssignment.objects.create(employee=person, day=day, shift=which, **fields)

    def post_cell(self, person, day, which, actor=None, **extra):
        if actor is not None:
            self.client.force_login(actor)
        return self.client.post(reverse('hr:production_shiftassignment_create'), {
            'employee': str(person.pk), 'day': day.isoformat(), 'shift': str(which.pk) if which else '', 'note': '',
            **extra})


class ModelTests(RosterTestCase):
    def test_one_plan_per_person_and_day_among_live_rows_and_a_cleared_cell_frees_the_day(self):
        first = self.cell(self.in_a, MONDAY, self.early)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.cell(self.in_a, MONDAY, self.late)
        self.cell(self.in_b, MONDAY, self.early)                  # another person, the same day
        self.cell(self.in_a, MONDAY.replace(day=3), self.early)   # the same person, another day
        first.soft_delete(self.hr)
        self.assertEqual(self.cell(self.in_a, MONDAY, self.late).shift, self.late)

    def test_planned_off_is_a_row_without_a_shift(self):
        off = self.cell(self.in_a, MONDAY)
        self.assertIsNone(ShiftAssignment.objects.get(pk=off.pk).shift)

    def test_a_shift_or_a_person_with_plans_is_protected(self):
        self.cell(self.in_a, MONDAY, self.early)
        plan = __import__('core.softdelete', fromlist=['plan_delete']).plan_delete(self.early)
        self.assertFalse(plan.can_delete)
        with connection.cursor() as cursor, self.assertRaises(IntegrityError), transaction.atomic():
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute('DELETE FROM shifts WHERE id = %s', [self.early.pk])

    def test_every_column_is_covered(self):
        self.assertEqual(fields_of(ShiftAssignment), {'employee', 'day', 'shift', 'note'})


class CellFormTests(RosterTestCase):
    def test_create_read_edit_clear_a_cell_with_a_note(self):
        # Create
        self.client.force_login(self.planner)
        response = self.client.get(reverse('hr:production_shiftassignment_create'), {'employee': str(self.in_a.pk),
                                                                          'day': MONDAY.isoformat()})
        self.assertEqual(response.context['form']['day'].value(), MONDAY.isoformat())
        self.post_cell(self.in_a, MONDAY, self.early, note='Covers for Bo')
        row = ShiftAssignment.objects.get()
        self.assertEqual({name: getattr(row, name) for name in fields_of(ShiftAssignment)},
                         {'employee': self.in_a, 'day': MONDAY, 'shift': self.early, 'note': 'Covers for Bo'})
        self.assertEqual(row.created_by, self.planner)
        # Read: the week shows it, the edit form is filled from the row
        week = self.client.get(self.url, {'week': MONDAY.isoformat()}).context['week']
        cell = next(r for r in week.rows if r.employee == self.in_a).cells[0]
        self.assertEqual((cell.shift, cell.assignment.note), (self.early, 'Covers for Bo'))
        form = self.client.get(reverse('hr:production_shiftassignment_edit', args=[row.pk])).context['form']
        self.assertEqual((form['shift'].value(), form['note'].value()), (self.early.pk, 'Covers for Bo'))
        # Edit: another shift, then planned off; the person and the day cannot move
        self.client.post(reverse('hr:production_shiftassignment_edit', args=[row.pk]), {
            'employee': str(self.in_b.pk), 'day': '2026-03-05', 'shift': str(self.late.pk), 'note': '', 'version': '1'})
        row.refresh_from_db()
        self.assertEqual((row.employee, row.day, row.shift, row.note, row.version), (self.in_a, MONDAY, self.late, '', 2))
        self.client.post(reverse('hr:production_shiftassignment_edit', args=[row.pk]), {'shift': '', 'note': '', 'version': '2'})
        row.refresh_from_db()
        self.assertIsNone(row.shift)
        # Clear: a delete, logged
        self.client.post(reverse('hr:production_shiftassignment_delete', args=[row.pk]))
        self.assertTrue(ShiftAssignment.all_objects.get(pk=row.pk).is_deleted)
        self.assertEqual(list(AuditLog.objects.filter(entity_id=str(row.pk)).order_by('created_at')
                              .values_list('action', flat=True)), ['create', 'update', 'update', 'delete'])

    def test_the_note_is_never_written_to_the_log_and_a_stale_cell_is_refused(self):
        self.post_cell(self.in_a, MONDAY, self.early, actor=self.planner, note='Private words')
        row = ShiftAssignment.objects.get()
        entry = AuditLog.objects.get(entity_id=str(row.pk))
        self.assertEqual(entry.changes['Note'], [None, PRIVATE])
        self.assertNotIn('Private words', str(AuditLog.objects.values_list('changes', flat=True)))
        ShiftAssignment.objects.filter(pk=row.pk).update(version=3)
        self.client.post(reverse('hr:production_shiftassignment_edit', args=[row.pk]), {'shift': str(self.late.pk),
                                                                              'note': '', 'version': '1'})
        row.refresh_from_db()
        self.assertEqual(row.shift, self.early)

    def test_a_second_plan_for_the_same_cell_is_an_error_on_the_form(self):
        self.post_cell(self.in_a, MONDAY, self.early, actor=self.planner)
        response = self.post_cell(self.in_a, MONDAY, self.late)
        self.assertIn('day', response.context['form'].errors)
        self.assertEqual(ShiftAssignment.objects.count(), 1)

    def test_only_active_shifts_are_offered(self):
        Shift.objects.filter(pk=self.late.pk).update(status='inactive')
        self.client.force_login(self.planner)
        form = self.client.get(reverse('hr:production_shiftassignment_create')).context['form']
        self.assertEqual(set(form.fields['shift'].queryset), {self.early, self.night})


class RulesThroughTheFormTests(RosterTestCase):
    def test_a_short_rest_warns_saves_and_logs_the_warning(self):
        self.client.force_login(self.planner)
        self.post_cell(self.in_a, MONDAY, self.night)
        self.post_cell(self.in_a, date(2026, 3, 3), self.late)
        self.assertEqual(ShiftAssignment.objects.count(), 2)              # saved: the rule only warns by default
        entry = AuditLog.objects.filter(entity_id=str(ShiftAssignment.objects.get(day=date(2026, 3, 3)).pk)).get()
        self.assertEqual(entry.changes['Warnings'],
                         [None, [{'msgid': 'The rest since the last shift is shorter than the minimum.'}]])

    def test_the_rest_rule_set_to_block_refuses_the_same_plan(self):
        SchedulingSettings.get()
        SchedulingSettings.objects.update(rest_rule='block')
        self.post_cell(self.in_a, MONDAY, self.night, actor=self.planner)
        before = (ShiftAssignment.objects.count(), AuditLog.objects.count())
        response = self.post_cell(self.in_a, date(2026, 3, 3), self.late)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual((ShiftAssignment.objects.count(), AuditLog.objects.count()), before)

    def test_overlapping_shifts_are_always_refused_whatever_the_rest_rule(self):
        small_hours = shift('SMALL', time(2), time(10))
        self.post_cell(self.in_a, MONDAY, self.night, actor=self.planner)          # 22:00 Monday to 06:00 Tuesday
        before = (ShiftAssignment.objects.count(), AuditLog.objects.count())
        response = self.post_cell(self.in_a, date(2026, 3, 3), small_hours)        # 02:00 Tuesday: inside the night
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].non_field_errors(), ['This shift overlaps another shift of the person.'])
        self.assertEqual((ShiftAssignment.objects.count(), AuditLog.objects.count()), before)

    def test_a_shift_on_a_holiday_warns(self):
        Holiday.objects.create(day=MONDAY, name='Founders day')
        self.post_cell(self.in_a, MONDAY, self.early, actor=self.planner)
        entry = AuditLog.objects.get(entity_type='plan')
        self.assertEqual(entry.changes['Warnings'], [None, [{'msgid': 'The person works on a holiday.'}]])

    def test_a_site_in_another_zone_reads_the_rest_on_its_clock(self):
        Site.objects.filter(pk=self.site.pk).update(timezone='Europe/Oslo')
        # the night of the 28th ends at 06:00 on the 29th, after the clocks went forward (Oslo); 14:00 that day is 8 hours
        # of rest, short of the 11 hours
        self.post_cell(self.in_a, date(2026, 3, 28), self.night, actor=self.planner)
        self.post_cell(self.in_a, date(2026, 3, 29), self.late)
        entry = AuditLog.objects.filter(entity_id=str(ShiftAssignment.objects.get(day=date(2026, 3, 29)).pk)).get()
        self.assertEqual(entry.changes['Warnings'],
                         [None, [{'msgid': 'The rest since the last shift is shorter than the minimum.'}]])


class PlanShiftsTests(RosterTestCase):
    def state(self):
        return (list(ShiftAssignment.all_objects.order_by('day', 'employee').values_list(
            'employee', 'day', 'shift', 'is_deleted', 'version')), AuditLog.objects.count())

    def test_a_batch_sets_every_cell_and_logs_each(self):
        days = [date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)]
        warnings = services.plan_shifts(self.planner, [(self.in_a, day) for day in days], self.early)
        self.assertEqual(warnings, [])
        self.assertEqual(sorted(ShiftAssignment.objects.values_list('day', flat=True)), days)
        self.assertEqual(AuditLog.objects.filter(entity_type='plan', action='create').count(), 3)
        # again with another shift: updates; with CLEAR: deletes
        services.plan_shifts(self.planner, [(self.in_a, days[0])], self.late)
        self.assertEqual(ShiftAssignment.objects.get(day=days[0]).shift, self.late)
        services.plan_shifts(self.planner, [(self.in_a, day) for day in days], services.CLEAR)
        self.assertEqual(ShiftAssignment.objects.count(), 0)
        services.plan_shifts(self.planner, [(self.in_a, days[0])], None)               # planned off
        self.assertIsNone(ShiftAssignment.objects.get().shift)

    def test_one_person_outside_the_team_stops_the_whole_batch(self):
        before = self.state()
        with self.assertRaises(PermissionDenied):
            services.plan_shifts(self.planner, [(self.in_a, MONDAY), (self.in_b, MONDAY)], self.early)
        self.assertEqual(self.state(), before)

    def test_a_blocking_finding_stops_the_batch_and_names_the_cells(self):
        SchedulingSettings.get()
        SchedulingSettings.objects.update(rest_rule='block')
        self.cell(self.in_a, MONDAY, self.night)
        before = self.state()
        with self.assertRaises(ValidationError) as caught:
            services.plan_shifts(self.planner, [(self.in_a, date(2026, 3, 3)), (self.in_a, date(2026, 3, 10))], self.late)
        self.assertIn('2026-03-03', caught.exception.messages[0])
        self.assertEqual(self.state(), before)                     # the second, clean cell was not written either

    def test_the_verb_each_cell_needs(self):
        reader = user('readonly', 'view_employee', 'view_shiftassignment', group='Read role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=reader)
        before = self.state()
        with self.assertRaises(PermissionDenied):
            services.plan_shifts(reader, [(self.in_a, MONDAY)], self.early)
        self.assertEqual(self.state(), before)
        creator = user('creator', 'view_employee', 'view_shiftassignment', 'add_shiftassignment', group='Create role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=creator)
        services.plan_shifts(creator, [(self.in_a, MONDAY)], self.early)               # a new cell needs Create
        with self.assertRaises(PermissionDenied):
            services.plan_shifts(creator, [(self.in_a, MONDAY)], self.late)            # changing it needs Edit
        with self.assertRaises(PermissionDenied):
            services.plan_shifts(creator, [(self.in_a, MONDAY)], services.CLEAR)       # clearing it needs Delete

    def test_the_day_decides_whose_team_a_person_is_in(self):
        mover = employee('E-8', 'Hotel')
        place(mover, self.dept_a, TOP, date(2026, 3, 31))
        place(mover, self.dept_b, date(2026, 4, 1))
        services.plan_shifts(self.planner, [(mover, date(2026, 3, 31))], self.early)
        with self.assertRaises(PermissionDenied):
            services.plan_shifts(self.planner, [(mover, date(2026, 4, 1))], self.early)
        self.assertEqual(ShiftAssignment.objects.count(), 1)


class WeekReadTests(RosterTestCase):
    def week(self, actor, **kwargs):
        return read.week(actor, MONDAY, **kwargs)

    def test_a_lead_reads_their_team_only_and_everyone_reads_all(self):
        self.assertEqual([r.employee.last_name for r in self.week(self.planner).rows], ['Alfa'])
        self.assertEqual([r.employee.last_name for r in self.week(self.hr).rows], ['Alfa', 'Bravo', 'Charlie'])

    def test_the_cells_show_shifts_off_days_holidays_and_the_hours(self):
        self.cell(self.in_a, MONDAY, self.early)
        self.cell(self.in_a, date(2026, 3, 3))                                        # planned off
        Holiday.objects.create(day=date(2026, 3, 4), name='Day off')
        Holiday.objects.create(day=date(2026, 3, 5), name='Other site only', site=Site.objects.create(name='X', code='XX'))
        row = self.week(self.planner).rows[0]
        self.assertEqual([c.shift for c in row.cells[:2]], [self.early, None])
        self.assertTrue(row.cells[1].is_off)
        self.assertEqual((row.cells[2].holiday.name, row.cells[3].holiday), ('Day off', None))
        self.assertIsNone(row.cells[4].assignment)
        self.assertEqual((row.planned_minutes, str(row.planned_hours)), (450, '7.5'))

    def test_the_week_starts_on_monday_whatever_day_is_asked(self):
        self.assertEqual(read.week(self.hr, date(2026, 3, 5)).start, MONDAY)
        self.assertEqual(read.week(self.hr, date(2026, 3, 8)).days[-1], date(2026, 3, 8))

    def test_findings_sit_on_their_day_and_a_long_week_on_the_row(self):
        for n in range(6):
            self.cell(self.in_a, date(2026, 3, 2 + n), self.early)
        row = self.week(self.planner).rows[0]
        self.assertEqual([item.code for item in row.week_findings], ['week_hours'])
        self.cell(self.in_b, MONDAY, self.night)
        self.cell(self.in_b, date(2026, 3, 3), self.late)
        row = next(r for r in self.week(self.hr).rows if r.employee == self.in_b)
        self.assertEqual([i.code for i in row.cells[1].findings], ['rest_short'])
        self.assertIn('shorter than the minimum', row.cells[1].finding_text)

    def test_a_person_who_moved_is_visible_to_each_manager_on_their_days_only(self):
        mover = employee('E-8', 'Hotel')
        place(mover, self.dept_a, TOP, date(2026, 3, 4))
        place(mover, self.dept_b, date(2026, 3, 5))
        for n in range(7):
            self.cell(mover, date(2026, 3, 2 + n), self.early)
        old = next(r for r in self.week(self.planner).rows if r.employee == mover)
        self.assertEqual([c.visible for c in old.cells], [True, True, True, False, False, False, False])
        self.assertEqual([c.assignment is not None for c in old.cells], [True, True, True, False, False, False, False])
        self.assertEqual(old.planned_minutes, 3 * 450)
        newer = user('newer', *PLANNER_PERMS, group='Newer role')
        ProductionDepartment.objects.filter(pk=self.dept_b.pk).update(manager=newer)
        fresh = next(r for r in self.week(newer).rows if r.employee == mover)
        self.assertEqual([c.visible for c in fresh.cells], [False, False, False, True, True, True, True])

    def test_people_who_left_or_have_not_joined_are_not_in_the_week(self):
        gone = employee('E-9', 'India')
        Employee.objects.filter(pk=gone.pk).update(left_on=date(2026, 2, 1))
        late = employee('E-10', 'Juliet', on=date(2026, 3, 9))
        place(gone, self.dept_a, TOP, date(2026, 2, 1))
        place(late, self.dept_a, date(2026, 3, 9))
        self.assertEqual([r.employee.last_name for r in self.week(self.planner).rows], ['Alfa'])

    def test_paging_search_and_department_filter_narrow_the_people_and_say_n_of_m(self):
        for n in range(5):
            place(employee(f'E-2{n}', f'Zulu{n}'), self.dept_a)
        week = self.week(self.planner, per_page=4)
        self.assertEqual((week.shown, week.total, week.pages, week.page), (4, 6, 2, 1))
        self.assertEqual(self.week(self.planner, per_page=4, page=2).shown, 2)
        self.assertEqual(self.week(self.planner, query='zulu3').shown, 1)
        self.assertEqual([r.employee.last_name for r in self.week(self.hr, department=self.finance).rows], ['Charlie'])

    def test_the_queries_do_not_grow_with_the_people(self):
        read.week(self.planner, MONDAY)                              # warm the permission cache
        def count(people):
            for n in range(people):
                person = employee(f'E-{3000 + n + people}', f'Many{n}')
                place(person, self.dept_a)
                self.cell(person, MONDAY, self.early)
            with CaptureQueriesContext(connection) as queries:
                read.week(self.planner, MONDAY)
            return len(queries)
        small = count(5)
        large = count(40)
        self.assertEqual(small, large)


class RosterUrlTests(RosterTestCase):
    def test_the_schedule_lists_the_team_and_never_widens_by_query(self):
        self.client.force_login(self.planner)
        for query in ({}, {'department': token(self.dept_b)}, {'q': 'Bravo'}, {'department': token(self.finance)}):
            week = self.client.get(self.url, {'week': MONDAY.isoformat(), **query}).context['week']
            self.assertEqual({r.employee.last_name for r in week.rows} - {'Alfa'}, set(), query)
        self.assertEqual(self.client.get(self.url, {'week': 'nonsense', 'page': 'x'}).status_code, 200)

    def test_a_cell_of_someone_in_another_team_is_a_404_on_every_verb(self):
        row = self.cell(self.in_b, MONDAY, self.early)
        self.client.force_login(self.planner)
        before = (ShiftAssignment.objects.count(), AuditLog.objects.count(), row.version)
        self.assertEqual(self.client.get(reverse('hr:production_shiftassignment_edit', args=[row.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('hr:production_shiftassignment_edit', args=[row.pk]),
                                          {'shift': str(self.late.pk), 'version': '1'}).status_code, 404)
        self.assertEqual(self.client.post(reverse('hr:production_shiftassignment_delete', args=[row.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('hr:production_shiftassignment_delete', args=[row.pk])).status_code, 404)
        row.refresh_from_db()
        self.assertEqual((ShiftAssignment.objects.count(), AuditLog.objects.count(), row.version), before)

    def test_a_forged_person_in_a_new_cell_fails_the_choice_and_writes_nothing(self):
        self.client.force_login(self.planner)
        before = (ShiftAssignment.objects.count(), AuditLog.objects.count())
        response = self.post_cell(self.in_b, MONDAY, self.early)
        self.assertEqual(response.status_code, 200)
        self.assertIn('employee', response.context['form'].errors)
        self.assertEqual((ShiftAssignment.objects.count(), AuditLog.objects.count()), before)

    def test_a_person_the_lead_does_not_plan_on_that_day_is_refused_on_the_form(self):
        mover = employee('E-8', 'Hotel')
        place(mover, self.dept_b, TOP, date(2026, 3, 31))
        place(mover, self.dept_a, date(2026, 4, 1))                 # the planner's person from the first of April
        self.client.force_login(self.planner)
        refused = self.post_cell(mover, date(2026, 3, 31), self.early)
        self.assertEqual((refused.status_code, ShiftAssignment.objects.count()), (200, 0))
        self.assertEqual(refused.context['form'].non_field_errors(), ['You do not plan this person on this day.'])
        self.post_cell(mover, date(2026, 4, 1), self.early)
        self.assertEqual(ShiftAssignment.objects.count(), 1)

    def test_the_verbs_decide_who_reads_plans_and_changes(self):
        for actor, listed in ((user('stranger'), 403), (self.planner, 200), (self.hr, 403)):
            self.client.force_login(actor)
            self.assertEqual(self.client.get(self.url).status_code, listed, actor.username)
        reader = user('reader', 'view_employee', 'view_shiftassignment', group='Reader role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=reader)
        self.client.force_login(reader)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertNotContains(self.client.get(self.url), 'roster-add')           # no plus without Create
        self.assertEqual(self.client.get(reverse('hr:production_shiftassignment_create')).status_code, 403)

    def test_the_batch_plan_view(self):
        self.client.force_login(self.planner)
        post = {'cells': [f'{self.in_a.pk}:2026-03-02', f'{self.in_a.pk}:2026-03-03'], 'shift': str(self.early.pk),
                'next': '/hr/schedule/?week=2026-03-02'}
        response = self.client.post(reverse('hr:production_roster_plan'), post)
        self.assertRedirects(response, '/hr/schedule/?week=2026-03-02', fetch_redirect_response=False)
        self.assertEqual(ShiftAssignment.objects.count(), 2)
        # a forged person: 404 and nothing written, not even the cells of the person that is allowed
        before = (ShiftAssignment.objects.count(), AuditLog.objects.count())
        self.assertEqual(self.client.post(reverse('hr:production_roster_plan'), {
            'cells': [f'{self.in_a.pk}:2026-03-09', f'{self.in_b.pk}:2026-03-09'], 'shift': 'clear'}).status_code, 404)
        self.assertEqual((ShiftAssignment.objects.count(), AuditLog.objects.count()), before)
        for bad in ({'shift': 'off'}, {'cells': ['nope'], 'shift': 'off'}, {'cells': [f'{self.in_a.pk}:2026-03-02'],
                                                                           'shift': 'not-a-shift'}):
            self.assertEqual(self.client.post(reverse('hr:production_roster_plan'), bad).status_code, 400, bad)
        self.assertEqual(self.client.get(reverse('hr:production_roster_plan')).status_code, 405)
        # an address of another site is not followed
        response = self.client.post(reverse('hr:production_roster_plan'), {**post, 'next': 'https://evil.example/'})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        # planned off and clear
        self.client.post(reverse('hr:production_roster_plan'), {**post, 'shift': 'off'})
        self.assertEqual(set(ShiftAssignment.objects.values_list('shift', flat=True)), {None})
        self.client.post(reverse('hr:production_roster_plan'), {**post, 'shift': 'clear'})
        self.assertEqual(ShiftAssignment.objects.count(), 0)
        # no verb: refused
        self.client.force_login(user('reader2', 'view_shiftassignment', group='Reader2'))
        self.assertEqual(self.client.post(reverse('hr:production_roster_plan'), post).status_code, 403)    # no right to plan: refused before the request is read
