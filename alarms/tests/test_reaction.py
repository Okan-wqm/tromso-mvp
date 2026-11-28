"""The owner's 10 s: from a value's commit to its alarm open, with the alarm worker running as it runs on a server (the
real command, in a process of its own, on the test database). The sweep is set to ten minutes here, so only the worker's
look at what changed (alarms/changes.py) can explain an alarm within the 10 s: a manual sample, a sensor value as the
ingest commits it, a burst of units in one commit, and a critical sample recorded while the worker was down. Each
measured latency is written to the test's output ("[alarm reaction] ...").

Below them, the look itself (`changes.token`) and the worker's use of it on a fake clock."""
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from farm.models import ProductionDepartment, Site, System, WaterLimit
from farm.tests.helpers import make_species, may_record, point_of, role, stock_fish
from farm.tests.test_stock import make_unit
from farm.water import services as water
from sensors import bindings
from sensors.tests import make_channel, make_connection, make_device, make_format

from .. import changes, engine, watch
from ..models import Alarm
from .test_worker import WorkerCase, make
from .test_worker_process import START, until

D = Decimal
TARGET = 10                                           # seconds: the owner's requirement, commit to open alarm
SLOW_SWEEP = {'ALARM_WORKER_SWEEP': '600', 'ALARM_WORKER_STALE_AFTER': '900'}


class Farm:
    """A site with a hall, a RAS, `count` stocked tanks of salmon with a pH limit (critical below 6), and a keeper."""

    def __init__(self, count=1):
        User = get_user_model()
        self.keeper = User.objects.create_user('keeper', 'keeper@example.com', 'x')
        self.keeper.groups.add(role('Water keeper', 'view_watermeasurement', 'add_watermeasurement',
                                    'view_stockoperation', 'add_stockoperation'))
        may_record(self.keeper, 'add_binding')          # binds the probe: the binding service asks (L-6)
        self.site = Site.objects.create(name='Bergen', code='BG', altitude=D(0))
        hall = ProductionDepartment.objects.create(site=self.site, name='Hall A', code='HA')
        ras = System.objects.create(name='RAS 1', code='R1', site=self.site, production_department=hall)
        self.salmon = make_species()
        WaterLimit.objects.create(species=self.salmon, parameter='ph', water_type='any', critical_low=D(6),
                                  warning_low=D('6.5'))
        self.units = [make_unit(f'T-{number:02d}', hall, system=ras) for number in range(1, count + 1)]
        for unit in self.units:
            stock_fish(self.keeper, unit, 1000, '50', 10, species=self.salmon)
        self.points = [point_of(unit) for unit in self.units]

    def sample(self, point, ph):
        return water.record(self.keeper, point=point, measured_at=timezone.now() - timedelta(minutes=1),
                            source='manual', values={'ph': D(str(ph))})


def critical_units():
    return set(Alarm.objects.filter(severity='critical', source='water_limit').values_list('point__unit', flat=True))


class ReactionTests(TransactionTestCase):
    serialized_rollback = True                         # the seeded rules and references, as a server has them

    def start(self, **env):
        log = tempfile.TemporaryFile()
        self.addCleanup(log.close)
        process = subprocess.Popen(
            [sys.executable, 'manage.py', 'run_alarm_worker'], cwd=settings.BASE_DIR, stdout=log,
            stderr=subprocess.STDOUT, env={**os.environ, 'DB_NAME': connection.settings_dict['NAME'], **SLOW_SWEEP,
                                           'PYTHONUNBUFFERED': '1', **env})
        process.log = log
        self.addCleanup(self.end, process)
        return process

    def end(self, process):
        if process.poll() is None:
            process.kill()
            process.wait(30)

    def said(self, process):
        process.log.seek(0)
        return process.log.read().decode('utf-8', 'replace')

    def started(self, process):
        until(lambda: watch.state().checked and watch.state().row.pid == process.pid, START,
              'the worker checking the alarms')
        time.sleep(2)                                  # its first passes over what setting up the farm wrote are done

    def report(self, what, seconds):
        seconds = sorted(seconds)
        sys.stderr.write(f'\n[alarm reaction] {what}: n={len(seconds)} p50={statistics.median(seconds):.2f} s '
                         f'max={seconds[-1]:.2f} s\n')

    def test_a_manual_critical_sample_opens_its_alarm_within_10_s(self):
        farm = Farm(3)
        process = self.start()
        self.started(process)
        took = []
        for unit, point in zip(farm.units, farm.points):
            farm.sample(point, 5.5)
            committed = time.monotonic()
            until(lambda: unit.pk in critical_units(), TARGET, f'the critical alarm of {unit.code}')
            took.append(time.monotonic() - committed)
        self.report('manual sample to open alarm', took)

    def test_a_sensor_value_as_the_ingest_commits_it_opens_its_alarm_within_10_s(self):
        farm = Farm(1)
        device = make_device(make_connection(), make_format(), farm.site, expected_interval_s=60)
        probe = make_channel(device, 'ph', code='PH-1')
        bindings.move(farm.keeper, probe, point=farm.points[0], at=timezone.now() - timedelta(hours=1))
        process = self.start()
        self.started(process)
        at = timezone.now()
        with transaction.atomic(), connection.cursor() as cursor:     # one commit, the ingest's: reading and state
            cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, %s)',
                           [probe.channel_no, at, 5.4])
            cursor.execute('INSERT INTO sensors_channel_state (channel_no, last_seen_at, last_good_at, last_value, '
                           'last_value_ts) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (channel_no) DO UPDATE SET '
                           'last_seen_at = EXCLUDED.last_seen_at, last_good_at = EXCLUDED.last_good_at, '
                           'last_value = EXCLUDED.last_value, last_value_ts = EXCLUDED.last_value_ts',
                           [probe.channel_no, at, at, 5.4, at])
        committed = time.monotonic()
        until(lambda: farm.units[0].pk in critical_units(), TARGET, 'the critical alarm of the sensor value')
        self.report('sensor value to open alarm', [time.monotonic() - committed])

    def test_a_burst_of_units_in_one_commit_all_open_within_10_s(self):
        farm = Farm(20)
        process = self.start()
        self.started(process)
        with transaction.atomic():
            for point in farm.points:
                farm.sample(point, 5.5)
        committed = time.monotonic()
        seen = {}

        def all_open():
            found = critical_units()
            for unit in found - set(seen):
                seen[unit] = time.monotonic() - committed
            return len(found) == len(farm.units)
        until(all_open, TARGET, f'{len(farm.units)} critical alarms')
        self.report(f'burst of {len(farm.units)} units in one commit', list(seen.values()))

    def test_a_critical_sample_recorded_while_the_worker_was_down_opens_on_its_first_pass(self):
        farm = Farm(1)
        first = self.start()
        self.started(first)
        first.kill()
        first.wait(30)
        farm.sample(farm.points[0], 5.5)
        time.sleep(3)
        self.assertEqual(critical_units(), set())                      # nobody checks while it is down
        second = self.start()
        until(lambda: farm.units[0].pk in critical_units(), START, 'the alarm once a worker runs again')
        self.assertIn('checks the alarms', self.said(second))


class TokenTests(TransactionTestCase):
    """Each statement its own transaction here, as the ingest's and the pages' are."""

    serialized_rollback = True

    def test_nothing_written_the_token_stays(self):
        self.assertEqual(changes.token(), changes.token())

    def test_a_value_the_ingest_commits_moves_the_token(self):
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO sensors_channel_state (channel_no, last_value) VALUES (7, 1.0)')
            before = changes.token()
            cursor.execute('UPDATE sensors_channel_state SET last_value = 1.0 WHERE channel_no = 7')   # same value
            self.assertNotEqual(changes.token(), before)

    def test_a_record_written_through_the_platform_moves_the_token(self):
        farm = Farm(1)
        before = changes.token()
        farm.sample(farm.points[0], 7.0)
        self.assertNotEqual(changes.token(), before)


class LookTests(WorkerCase):
    def test_a_change_is_passed_at_the_next_tick_not_at_the_sweep(self):
        tokens = iter(['a'] * 5 + ['b'] * 100)
        made = make(10, changes=lambda: next(tokens))
        made.run()
        self.assertEqual(made.run_pass.call_count, 2)                     # at once, and at the tick it changed

    def test_the_token_is_read_before_the_pass_so_a_change_during_it_gets_a_pass_more(self):
        state = {'token': 'a'}

        def a_pass_during_which_a_value_lands(**kwargs):
            state['token'] = 'b'
            return engine.Summary()
        made = make(5, run_pass=mock.Mock(side_effect=a_pass_during_which_a_value_lands),
                    changes=lambda: state['token'])
        made.run()
        self.assertEqual(made.run_pass.call_count, 2)


class NoStoreTests(SimpleTestCase):
    def test_the_alarm_path_never_reads_a_precomputed_water_store(self):
        """live-arch stage 3: the alarms judge the live tables; a store a page may read is never theirs."""
        root = settings.BASE_DIR / 'alarms'
        for path in sorted(root.glob('*.py')):
            with self.subTest(path=path.name):
                text = path.read_text(encoding='utf-8')
                self.assertNotIn('water_store', text.replace('precomputed water store', ''))
                self.assertNotIn('WATER_STORE', text)
