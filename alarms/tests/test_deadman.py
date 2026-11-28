"""The dead man: the farm is told when the alarm worker itself stops (owner decision of 2026-11-15, item H: a page that
promises an alarm says whether the alarms are being checked and since when they are not). The pages that show or
promise alarms (the Alarms pages, the water page, the monitoring wall, the Sensors overview) say it from the worker's
row on the database's clock; the worker that takes over after a stretch with no pass raises a critical alarm naming
it, notified as any alarm of the alarm system; and the off-server dead man is asked after each good pass, never more
often than its period, on a thread of its own, never after a pass with a failed step."""
import threading
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from farm.tests.helpers import role

from .. import engine, worker
from ..models import Alarm, AlarmWorkerStatus, Notification
from . import AlarmsCase
from .test_worker import TIMING, make, unlock_all

PAGES = ('alarms:alarm_list', 'alarms:alarm_snoozes', 'farm:water', 'monitoring:monitor', 'sensors:home')


class DeadManCase(AlarmsCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(unlock_all)

    def row(self, seconds_ago, state='running', ok_seconds_ago='same', steps=''):
        now = timezone.now()
        at = now - timedelta(seconds=seconds_ago)
        ok = at if ok_seconds_ago == 'same' else (now - timedelta(seconds=ok_seconds_ago) if ok_seconds_ago else None)
        AlarmWorkerStatus.objects.update_or_create(name='alarms', defaults=dict(
            state=state, started_at=now - timedelta(hours=2), heartbeat_at=at, last_pass_at=at, last_ok_pass_at=ok,
            failed_steps=steps, stale_after_seconds=45, last_send_at=now))


class PageTests(DeadManCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser('admin', 'admin@example.com', 'x'))

    def said(self, name):
        return self.client.get(reverse(name)).content.decode()

    def test_every_page_that_promises_an_alarm_says_when_none_is_checked(self):
        cases = [(lambda: None, 'no alarm worker has run here'),
                 (lambda: self.row(120), 'the alarm worker does not answer'),
                 (lambda: self.row(10, state='stopped'), 'the alarm worker stopped'),
                 (lambda: self.row(10, ok_seconds_ago=300, steps='water'), 'these steps of the alarm worker fail: water')]
        for prepare, words in cases:
            AlarmWorkerStatus.objects.all().delete()
            prepare()
            for name in PAGES:
                with self.subTest(words=words, page=name):
                    page = self.said(name)
                    self.assertIn('NOT being checked', page)
                    self.assertIn(words, page)

    def test_nothing_is_said_while_they_are_checked_and_the_water_page_says_when(self):
        self.row(5)
        for name in PAGES:
            with self.subTest(page=name):
                self.assertNotIn('NOT being checked', self.said(name))
        water = self.said('farm:water')
        self.assertIn('raises an alarm', water)
        self.assertIn('The alarms were last checked', water)

    def test_since_when_is_the_last_good_pass_on_the_companys_clock(self):
        self.row(600, ok_seconds_ago=900)
        page = self.said('alarms:alarm_list')
        from core.templatetags.dates import site_clock
        from django.utils.formats import date_format
        since = AlarmWorkerStatus.objects.get().last_ok_pass_at
        self.assertIn(date_format(site_clock(since), 'DATETIME_FORMAT'), page)


class GapTests(DeadManCase):
    def test_a_worker_taking_over_after_a_stretch_with_no_pass_raises_it_and_it_clears(self):
        self.rule()
        self.row(600)                                              # the last pass ten minutes ago
        before = AlarmWorkerStatus.objects.get().last_pass_at
        made = make(1, run_pass=engine.run_once)
        made.run()
        alarm = Alarm.objects.get(source='system', parameter='alarms_unchecked')
        self.assertEqual(alarm.severity, 'critical')
        from core.templatetags.dates import on, zone_for
        self.assertIn(on(before, zone_for(None)).strftime('%d.%m.%Y %H:%M'), alarm.summary)
        self.assertIn('nobody was told', alarm.summary)
        engine.run_once(timezone.now() + timedelta(seconds=1))      # the next pass: notified while it is open
        self.assertTrue(Notification.objects.filter(alarm=alarm).exists())
        engine.run_once(timezone.now() + timedelta(minutes=2))      # after its off-delay it clears
        self.assertTrue(hasattr(Alarm.objects.get(pk=alarm.pk), 'clearance'))

    def test_no_gap_on_a_first_start_or_a_short_restart(self):
        for prepare in (lambda: None, lambda: self.row(20, state='stopped')):
            AlarmWorkerStatus.objects.all().delete()
            prepare()
            made = make(1, run_pass=mock.Mock(return_value=engine.Summary()))
            made.run()
            made.run_pass.assert_called_once_with(check_queues=True)    # a first pass checks the queues
            unlock_all()
        self.assertFalse(Alarm.objects.filter(parameter='alarms_unchecked').exists())


class PingTests(DeadManCase):
    URL = 'https://dead-man.invalid/ping/abc'

    def worker(self, count, summaries, **timing):
        asked = []
        made = make(count, run_pass=mock.Mock(side_effect=summaries), deadman_url=self.URL, deadman_every=30.0,
                    deadman_timeout=5.0, **timing)
        made.ping = lambda url, timeout: asked.append((url, timeout, made.clock()))
        made.spawn = lambda target, args: target(*args)                # at once, on the clock of the pass
        return made, asked

    def test_asked_after_good_passes_at_most_every_period_never_after_a_failed_step(self):
        good, bad = engine.Summary(), engine.Summary(failed_steps=['water'])
        made, asked = self.worker(65, [good, bad, good, good, good, good, good], sweep=10.0)
        made.run()
        self.assertEqual(made.run_pass.call_count, 7)                 # at 0, 10, ..., 60 of the fake clock
        self.assertEqual([at - 1000 for _url, _timeout, at in asked], [0, 30, 60])
        self.assertEqual({(url, timeout) for url, timeout, _at in asked}, {(self.URL, 5.0)})

    def test_a_ping_that_hangs_never_holds_a_pass(self):
        release = threading.Event()
        self.addCleanup(release.set)
        made = make(3, run_pass=mock.Mock(return_value=engine.Summary()), deadman_url=self.URL, deadman_every=1.0,
                    deadman_timeout=5.0, sweep=1.0)
        made.ping = lambda url, timeout: release.wait(30)
        made.run()
        self.assertEqual(made.run_pass.call_count, 3)

    def test_off_without_an_address_and_only_https(self):
        made, asked = self.worker(20, [engine.Summary()] * 25, sweep=1.0)
        made.timing = worker.Timing(**TIMING)
        made.run()
        self.assertEqual(asked, [])
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            worker.Timing(**{**TIMING, 'deadman_url': 'http://dead-man.invalid/', 'deadman_every': 30,
                             'deadman_timeout': 5})


class ReaderTests(DeadManCase):
    def test_a_person_without_the_alarms_right_reads_the_notice_on_the_water_page(self):
        keeper = get_user_model().objects.get(username='keeper')
        keeper.groups.add(role('Water reader', 'view_watermeasurement'))
        self.client.force_login(keeper)
        page = self.client.get(reverse('farm:water'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'NOT being checked')
