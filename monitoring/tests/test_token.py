"""The change token: what a screen asks "has anything changed?" with. Every writer of a figure on a card moves it (a
writer that does not audit fails here), a read does not, the next minute does, and so do the language, the person's
rights and the address; a card read writes nothing."""
from datetime import datetime, timedelta, timezone as utc
from decimal import Decimal

from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation

from core import softdelete
from core.models import AuditLog
from farm.feeding import services as feeding_services
from farm.health import services as health_services
from farm.models import Medicine, Tank
from farm.stock import services as stock_services
from farm.tests.helpers import role
from farm.tests.test_health import event_data
from farm.water import services as water_services
from tasks import services as task_services
from tasks.models import Task

from .. import read
from . import ALL_RIGHTS, MonitoringCase, chosen

MOMENT = datetime(2026, 11, 4, 12, 0, 30, tzinfo=utc.utc)


class TokenTests(MonitoringCase):
    query = 'kind=tank'

    def token(self, user=None, query=None, now=MOMENT):
        return read.change_token(user or self.reader, self.query if query is None else query, now=now)

    def test_a_read_does_not_move_it_and_the_next_minute_does(self):
        first = self.token()
        read.cards(read.units_for(read.Params()), self.reader, chosen({}))
        self.assertEqual(self.token(), first)
        self.assertEqual(self.token(now=MOMENT + timedelta(seconds=20)), first)           # the same minute
        self.assertNotEqual(self.token(now=MOMENT + timedelta(seconds=40)), first)        # the next one

    def test_the_language_the_rights_the_address_and_the_board_change_it(self):
        first = self.token()
        with translation.override('tr'):
            self.assertNotEqual(self.token(), first)
        with translation.override('nb'):
            self.assertNotEqual(self.token(), first)
        fewer = self.as_person('fewer', 'view_stockoperation')
        self.assertNotEqual(self.token(user=fewer), first)
        self.assertNotEqual(self.token(query='kind=pond'), first)
        self.assertNotEqual(read.change_token(self.reader, self.query, board='b', now=MOMENT), first)
        # two people with the same rights share one token: no user id is in it
        twin = self.as_person('twin', *ALL_RIGHTS)
        self.assertEqual(self.token(user=twin), first)

    def test_a_permission_change_moves_it_without_any_data_changing(self):
        person = self.as_person('grows', 'view_stockoperation')
        before = self.token(user=person)
        from django.contrib.auth.models import Permission
        person.groups.first().permissions.add(Permission.objects.get(codename='view_watermeasurement'))
        person = type(person).objects.get(pk=person.pk)                                   # a request's fresh user
        self.assertNotEqual(self.token(user=person), before)

    def test_the_revision_is_read_before_anything_else(self):
        """A change that lands between the revision and the rest makes the NEXT token differ, so the revision is
        asked for first."""
        order = []
        with mock.patch.object(read.audit, 'revision', side_effect=lambda: order.append('revision') or 'r'),                 mock.patch.object(read, 'sections_for', side_effect=lambda user: order.append('rights') or frozenset()):
            read.change_token(self.reader, self.query, now=MOMENT)
        self.assertEqual(order, ['revision', 'rights'])
        before = self.token()
        self.mortality(self.batch, 1, days_ago=0)
        self.assertNotEqual(self.token(), before)

    def writers(self):
        """Each writer of something a card shows, as one call. A writer that does not write its audit entry would not
        move the token: this table is what finds it."""
        operation = self.mortality(self.batch, 2, days_ago=1)
        record = self.record(kilos='3', days_ago=2)
        sample = self.sample(self.t2, hours=3, temperature_c='11')
        count = None
        medicine = Medicine.objects.create(name='Bath', kind='lice', administration='bath', active_substance='x',
                                           lice_report_code='AZAMETHIPHOS')
        task = Task(title='Wash', due_date=self.today)
        task.set_place(self.t2)
        task.save()
        task.assignees.set([self.user])
        spare = Tank.objects.get(pk=self.p1.pk)
        edited = {}

        def lice():
            nonlocal count
            count = health_services.record_lice_count(self.user, unit=self.t1, day=self.day(1), fish_counted=10,
                                                      adult_females=1, mobile=0, attached=0)

        def edit_unit():
            form = self.client.get(reverse('farm:tank_edit', args=[spare.pk])).context['form']
            data = {name: ('' if form[name].value() is None else form[name].value()) for name in form.fields}
            data['description'] = 'Edited for the wall'
            edited['response'] = self.client.post(reverse('farm:tank_edit', args=[spare.pk]), data)

        return [
            ('a stock operation', lambda: self.mortality(self.batch, 1, days_ago=0)),
            ('a weighing', lambda: stock_services.record_weighing(self.user, unit=self.t1, batch=self.batch,
                                                                  day=self.day(0), avg_weight_g=Decimal(60))),
            ('a stock void', lambda: stock_services.void(self.user, operation, 'Typed twice')),
            ('a feeding', lambda: self.record(kilos='4', days_ago=0)),
            ('a feeding void', lambda: feeding_services.void_feeding(self.user, record, 'Typed twice')),
            ('a water sample', lambda: self.sample(self.t1, hours=1, temperature_c='9')),
            ('a water void', lambda: water_services.void(self.user, sample, 'Wrong point')),
            ('a treatment', lambda: health_services.record_treatment(
                self.user, units=[self.t1], method='bath', reason='sea_lice', start_date=self.day(1),
                end_date=self.day(1), medicine=medicine)),
            ('a sea-lice count', lice),
            ('a health event', lambda: self.client.post(reverse('farm:healthevent_create'), event_data(
                self.bergen, date=self.day(1).isoformat(), units=[str(self.t1.pk)]))),
            ('a task', lambda: task_services.complete(self.user, task)),
            ('a unit edited', edit_unit),
            ('a unit deleted', lambda: self.client.post(reverse('farm:tank_delete', args=[spare.pk]))),
            ('a unit restored', lambda: softdelete.restore(Tank.all_objects.get(pk=spare.pk), self.user)),
        ]

    def test_every_writer_moves_the_token(self):
        self.user.groups.add(role(
            'Health writer', 'add_healthevent', 'view_healthevent', 'view_site', 'delete_tank', 'change_tank',
            'view_tank'))
        self.client.force_login(self.user)
        for name, write in self.writers():
            with self.subTest(writer=name):
                before_token, before_rows = self.token(), AuditLog.objects.count()
                write()
                self.assertGreater(AuditLog.objects.count(), before_rows, f'{name} wrote no activity-log entry')
                self.assertNotEqual(self.token(), before_token, f'{name} did not move the token')

    def test_a_card_read_writes_nothing(self):
        units = read.units_for(read.Params())
        rows = AuditLog.objects.count()
        with CaptureQueriesContext(connection) as log:
            read.cards(units, self.reader, chosen({unit.pk: 'detailed' for unit in units}), occupancy='all')
            self.token()
        verbs = {query['sql'].lstrip().split(None, 1)[0].upper() for query in log}
        self.assertLessEqual(verbs, {'SELECT', 'WITH', 'SAVEPOINT', 'RELEASE'})      # savepoints: the chips' fail-open, no write
        self.assertEqual(AuditLog.objects.count(), rows)
