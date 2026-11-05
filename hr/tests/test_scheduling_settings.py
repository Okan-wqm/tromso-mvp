from datetime import date, time

from django.db import IntegrityError, connection, transaction
from django.urls import reverse

from core.models import AuditLog
from farm.models import Site

from ..models import Holiday, SchedulingSettings, Shift
from .helpers import HrTestCase, fields_of, user


def shift_data(**overrides):
    values = {'name': 'Morning', 'code': 'morn', 'starts_at': '06:00', 'ends_at': '14:00', 'break_minutes': '30',
              'grace_minutes': '10', 'tone': '2', 'status': 'active'}
    values.update(overrides)
    return values


class SettingsTestCase(HrTestCase):
    def setUp(self):
        super().setUp()
        self.user = user('boss', 'view_shift', 'add_shift', 'change_shift', 'delete_shift', 'view_holiday',
                         'add_holiday', 'change_holiday', 'delete_holiday', 'view_schedulingsettings',
                         'change_schedulingsettings', 'view_auditlog')
        self.client.force_login(self.user)


class ShiftTests(SettingsTestCase):
    def test_create_read_edit_delete_every_column(self):
        self.client.post(reverse('hr:shift_create'), shift_data())
        shift = Shift.objects.get()
        self.assertEqual({name: getattr(shift, name) for name in fields_of(Shift)}, {
            'name': 'Morning', 'code': 'MORN', 'starts_at': time(6, 0), 'ends_at': time(14, 0), 'break_minutes': 30,
            'grace_minutes': 10, 'tone': 2, 'status': 'active'})
        self.assertEqual((shift.span_minutes, shift.paid_minutes), (480, 450))
        self.assertEqual(list(self.client.get(reverse('hr:shift_list')).context['objects']), [shift])
        form = self.client.get(reverse('hr:shift_edit', args=[shift.pk])).context['form']
        self.assertEqual(form['break_minutes'].value(), 30)
        self.client.post(reverse('hr:shift_edit', args=[shift.pk]), shift_data(
            name='Night', code='night', starts_at='22:00', ends_at='06:00', break_minutes='45', grace_minutes='0',
            tone='8', status='inactive', version='1'))
        shift.refresh_from_db()
        self.assertEqual((shift.name, shift.starts_at, shift.ends_at, shift.span_minutes, shift.tone, shift.status,
                          shift.version), ('Night', time(22, 0), time(6, 0), 480, 8, 'inactive', 2))
        self.client.post(reverse('hr:shift_delete', args=[shift.pk]))
        self.assertTrue(Shift.all_objects.get().is_deleted)
        self.assertEqual(list(AuditLog.objects.order_by('created_at').values_list('action', flat=True)),
                         ['create', 'update', 'delete'])

    def test_the_form_refuses_what_the_database_would(self):
        for overrides, field in (({'ends_at': '06:00'}, 'ends_at'), ({'break_minutes': '241'}, 'break_minutes'),
                                 ({'break_minutes': '480'}, 'break_minutes'), ({'grace_minutes': '121'}, 'grace_minutes'),
                                 ({'tone': '9'}, 'tone'), ({'tone': '0'}, 'tone')):
            errors = self.client.post(reverse('hr:shift_create'), shift_data(**overrides)).context['form'].errors
            self.assertIn(field if field in errors else '__all__', errors, overrides)
        self.assertFalse(Shift.objects.exists())

    def test_the_database_constraints_with_raw_rows(self):
        def make(**fields):
            values = {'name': 'S', 'code': 'S1', 'starts_at': time(6), 'ends_at': time(14), **fields}
            with transaction.atomic():
                return Shift.objects.create(**values)
        make()
        for fields in ({'code': 'S1'},                                  # unique among live shifts
                       {'code': 'S2', 'ends_at': time(6)},                # starts and ends together
                       {'code': 'S2', 'break_minutes': 241},
                       {'code': 'S2', 'starts_at': time(6), 'ends_at': time(10), 'break_minutes': 240},   # not shorter than 4 h
                       {'code': 'S2', 'grace_minutes': 121}, {'code': 'S2', 'tone': 0}, {'code': 'S2', 'tone': 9},
                       {'code': 's2'}, {'code': 'S2', 'status': 'gone'}):
            with self.assertRaises(IntegrityError, msg=fields), transaction.atomic():
                Shift.objects.bulk_create([Shift(**{'name': 'S', 'starts_at': time(6), 'ends_at': time(14), **fields})])
        # a night shift's span runs over midnight: 22:00-02:00 is 4 hours, so a 239 minute break is allowed, 240 not
        make(code='N1', starts_at=time(22), ends_at=time(2), break_minutes=239)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Shift.objects.bulk_create([Shift(name='N', code='N2', starts_at=time(22), ends_at=time(2),
                                             break_minutes=240)])

    def test_a_deleted_shifts_code_is_free_again(self):
        Shift.objects.create(name='S', code='S1', starts_at=time(6), ends_at=time(14)).soft_delete(self.user)
        Shift.objects.create(name='S', code='S1', starts_at=time(6), ends_at=time(14))


class HolidayTests(SettingsTestCase):
    def test_create_read_edit_delete_every_column(self):
        site = Site.objects.create(name='Bergen', code='BG')
        self.client.post(reverse('hr:holiday_create'), {'day': '2026-12-25', 'name': ' Christmas Day ', 'site': ''})
        every = Holiday.objects.get()
        self.assertEqual({name: getattr(every, name) for name in fields_of(Holiday)},
                         {'day': date(2026, 12, 25), 'name': 'Christmas Day', 'site': None})
        self.client.post(reverse('hr:holiday_create'), {'day': '2026-12-25', 'name': 'Local day', 'site': str(site.pk)})
        self.assertEqual(Holiday.objects.count(), 2)
        self.assertEqual(len(self.client.get(reverse('hr:holiday_list')).context['objects']), 2)
        self.client.post(reverse('hr:holiday_edit', args=[every.pk]),
                         {'day': '2026-12-26', 'name': 'Boxing Day', 'site': '', 'version': '1'})
        every.refresh_from_db()
        self.assertEqual((every.day, every.name, every.version), (date(2026, 12, 26), 'Boxing Day', 2))
        self.client.post(reverse('hr:holiday_delete', args=[every.pk]))
        self.assertEqual(Holiday.objects.count(), 1)

    def test_one_holiday_a_day_for_every_site_and_one_per_site(self):
        site = Site.objects.create(name='Bergen', code='BG')
        Holiday.objects.create(day=date(2026, 5, 17), name='National day')
        Holiday.objects.create(day=date(2026, 5, 17), name='Local', site=site)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Holiday.objects.create(day=date(2026, 5, 17), name='Again')               # the missing site counts as one value
        with self.assertRaises(IntegrityError), transaction.atomic():
            Holiday.objects.create(day=date(2026, 5, 17), name='Again', site=site)
        errors = self.client.post(reverse('hr:holiday_create'), {'day': '2026-05-17', 'name': 'X1', 'site': ''}
                                  ).context['form'].errors
        self.assertIn('site', errors)
        Holiday.objects.get(site=site).soft_delete(self.user)
        Holiday.objects.create(day=date(2026, 5, 17), name='Local again', site=site)

    def test_a_site_with_holidays_is_not_deleted(self):
        site = Site.objects.create(name='Bergen', code='BG')
        Holiday.objects.create(day=date(2026, 5, 17), name='Local', site=site)
        from core.softdelete import plan_delete
        self.assertFalse(plan_delete(site).can_delete)


class SettingsRowTests(SettingsTestCase):
    def test_the_row_exists_after_migrating_and_there_is_only_one(self):
        row = SchedulingSettings.objects.get()
        self.assertEqual((row.standard_week_minutes, row.min_rest_minutes, row.max_consecutive_days, row.rest_rule,
                          row.working_weekdays, row.punch_window_minutes, row.absent_after_minutes),
                         (2400, 660, 6, 'warn', [0, 1, 2, 3, 4], 120, 30))
        with self.assertRaises(IntegrityError), transaction.atomic():
            SchedulingSettings.objects.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SchedulingSettings.objects.bulk_create([SchedulingSettings(singleton=False)])
        self.assertEqual(SchedulingSettings.get().pk, row.pk)

    def test_the_page_shows_the_row_edits_it_and_has_no_add_or_delete(self):
        row = SchedulingSettings.objects.get()
        response = self.client.get(reverse('hr:schedulingsettings_list'))
        self.assertEqual(list(response.context['objects']), [row])
        self.assertContains(response, 'not the law')
        self.client.post(reverse('hr:schedulingsettings_edit', args=[row.pk]), {
            'standard_week_minutes': '2250', 'min_rest_minutes': '720', 'max_consecutive_days': '5',
            'rest_rule': 'block', 'working_weekdays': ['0', '1', '2', '3', '4', '5'], 'punch_window_minutes': '60',
            'absent_after_minutes': '15', 'version': '1'})
        row.refresh_from_db()
        self.assertEqual((row.standard_week_minutes, row.min_rest_minutes, row.max_consecutive_days, row.rest_rule,
                          row.working_weekdays, row.punch_window_minutes, row.absent_after_minutes, row.version),
                         (2250, 720, 5, 'block', [0, 1, 2, 3, 4, 5], 60, 15, 2))
        self.assertEqual(self.client.get('/hr/settings/scheduling/new/').status_code, 404)
        self.assertEqual(self.client.post(f'/hr/settings/scheduling/{row.pk}/delete/').status_code, 404)

    def test_the_form_and_the_database_hold_every_limit(self):
        row = SchedulingSettings.objects.get()
        good = {'standard_week_minutes': '2400', 'min_rest_minutes': '660', 'max_consecutive_days': '6',
                'rest_rule': 'warn', 'working_weekdays': ['0'], 'punch_window_minutes': '120',
                'absent_after_minutes': '30', 'version': '1'}
        for field, value in (('standard_week_minutes', '10081'), ('min_rest_minutes', '1441'),
                             ('max_consecutive_days', '0'), ('max_consecutive_days', '15'), ('rest_rule', 'ignore'),
                             ('working_weekdays', []), ('punch_window_minutes', '721'), ('absent_after_minutes', '241')):
            errors = self.client.post(reverse('hr:schedulingsettings_edit', args=[row.pk]), {**good, field: value}
                                      ).context['form'].errors
            self.assertIn(field, errors, (field, value))
        with connection.cursor() as cursor:
            for column, value in (('standard_week_minutes', 10081), ('min_rest_minutes', 1441),
                                  ('max_consecutive_days', 0), ('max_consecutive_days', 15),
                                  ('rest_rule', "'nope'"), ('punch_window_minutes', 721),
                                  ('absent_after_minutes', 241), ('working_weekdays', "'{}'"),
                                  ('working_weekdays', "'{7}'")):
                with self.assertRaises(IntegrityError, msg=(column, value)), transaction.atomic():
                    cursor.execute(f'UPDATE scheduling_settings SET {column} = {value}')

    def test_only_stricter_than_the_statute_is_a_matter_for_the_owner_not_a_constraint(self):
        # no statutory figure is a database constraint: a lower rest than the statute can be stored
        SchedulingSettings.objects.update(min_rest_minutes=60)
        self.assertEqual(SchedulingSettings.objects.get().min_rest_minutes, 60)


class SettingsAccessTests(SettingsTestCase):
    """Every settings route against the actors: the verb decides (the settings are not personal data), and the hidden
    entries have no line in the menu but are in the role matrix and reachable."""

    def test_the_verbs_decide_and_a_reader_reads_only(self):
        shift = Shift.objects.create(name='S', code='S1', starts_at=time(6), ends_at=time(14))
        holiday = Holiday.objects.create(day=date(2026, 5, 17), name='National day')
        row = SchedulingSettings.get()
        reader = user('reader', 'view_shift', 'view_holiday', 'view_schedulingsettings', group='Reader role')
        stranger = user('stranger')
        reads = [reverse('hr:shift_list'), reverse('hr:holiday_list'), reverse('hr:schedulingsettings_list')]
        writes = [reverse('hr:shift_create'), reverse('hr:shift_edit', args=[shift.pk]),
                  reverse('hr:shift_delete', args=[shift.pk]), reverse('hr:holiday_create'),
                  reverse('hr:holiday_edit', args=[holiday.pk]), reverse('hr:holiday_delete', args=[holiday.pk]),
                  reverse('hr:schedulingsettings_edit', args=[row.pk])]
        self.client.logout()
        for url in reads + writes:
            self.assertEqual(self.client.get(url).status_code, 302, url)               # anonymous: sign in
        for actor, read_status, write_status in ((stranger, 403, 403), (reader, 200, 403), (self.user, 200, 200)):
            self.client.force_login(actor)
            for url in reads:
                self.assertEqual(self.client.get(url).status_code, read_status, (actor.username, url))
            for url in writes:
                self.assertEqual(self.client.get(url).status_code, write_status, (actor.username, url))

    def test_the_hidden_entries_have_no_line_but_are_a_matrix_area_and_the_page_leads_to_them(self):
        response = self.client.get(reverse('home'))
        shown = [entry['label'] for section in response.context['rail_sections'] for group in section['groups']
                 for entry in group['entries']]
        self.assertIn('Scheduling settings', shown)
        self.assertNotIn('Shifts', shown)
        self.assertNotIn('Holidays', shown)
        page = self.client.get(reverse('hr:schedulingsettings_list'))
        self.assertContains(page, reverse('hr:shift_list'))
        self.assertContains(page, reverse('hr:holiday_list'))
        from core import access
        offered = {area.model for area in access.areas()}
        self.assertTrue({'hr.Shift', 'hr.Holiday', 'hr.SchedulingSettings'} <= offered)
        # the hidden page keeps its heading from the menu's data
        self.assertEqual(self.client.get(reverse('hr:shift_list')).context['group'], 'Time & shifts')
