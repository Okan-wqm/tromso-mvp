"""Cross review F10 (alarm plan §7c): the staleness and offline thresholds an alarm depends on are the user's rule data,
never the code's: how long a water value says something about the water now (per parameter, farm.WaterFreshness), how
far ahead of the server's clock a value may be stamped and still count as fresh (the platform settings' clock
tolerance), and how many heartbeats a sensor channel's value stays fresh for (per channel). Their defaults are today's
values. The ingest contract's hour (evaluate.MAX_AHEAD) is the ingest's, not a rule: it stays, said why."""
import ast
import pathlib
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction

from core.models import PlatformSettings
from farm.water import evaluate, parameters
from sensors.tests import make_channel, make_connection, make_device, make_format

from . import AlarmsCase

TODAY = {'temperature_c': 24, 'oxygen_mg_l': 24, 'oxygen_saturation_pct': 24, 'ph': 72, 'alkalinity_mg_l': 336,
         'co2_mg_l': 72, 'tan_mg_l': 168, 'nitrite_n_mg_l': 168, 'nitrate_n_mg_l': 336, 'tgp_pct': 168,
         'salinity_ppt': 168, 'turbidity_ntu': 168, 'nh3_n_mg_l': 168, 'nh4_n_mg_l': 168,
         # formula 3's ionic-strength inputs, water parameters since farm 0040, their rows seeded by farm 0042: the
         # conductivity at 25 °C 7 days, the hardness 14, as formula 3 had read them (farm/water/freshness.py SEEDS)
         'conductivity_25_us_cm': 168, 'hardness_mg_l': 336,
         # the optional phosphate, a water parameter with its row since the phosphate migration of farm
         'phosphate_p_mg_l': 168}


def rows():
    from farm import models
    return models.WaterFreshness


def forget():
    from farm.water import freshness
    freshness.forget()


class FreshnessRuleTests(AlarmsCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(lambda: forget() if hasattr(evaluate, 'freshness') else None)

    def test_todays_values_are_the_seeded_rows(self):
        self.assertEqual(dict(rows().objects.values_list('parameter', 'fresh_hours')), TODAY)
        self.assertEqual(PlatformSettings.get().clock_tolerance_seconds, 300)
        self.assertFalse(hasattr(parameters.Parameter, 'fresh_hours'))

    def test_a_changed_freshness_is_read_at_once(self):
        ph = parameters.get('ph')
        self.assertTrue(evaluate.is_fresh(ph, self.now - timedelta(hours=48), self.now))
        row = rows().objects.get(parameter='ph')
        row.fresh_hours = 24
        row.save()
        self.assertFalse(evaluate.is_fresh(ph, self.now - timedelta(hours=48), self.now))

    def test_the_clock_tolerance_is_the_platform_owners(self):
        ph = parameters.get('ph')
        self.assertTrue(evaluate.is_fresh(ph, self.now + timedelta(minutes=4), self.now))
        settings_row = PlatformSettings.get()
        settings_row.clock_tolerance_seconds = 60
        settings_row.save()
        self.assertFalse(evaluate.is_fresh(ph, self.now + timedelta(minutes=4), self.now))

    def test_a_missing_row_is_made_again_from_the_seed(self):
        rows().all_objects.filter(parameter='ph').delete()
        forget()
        from farm.water import freshness
        self.assertEqual(freshness.hours('ph'), 72)
        self.assertTrue(rows().objects.filter(parameter='ph').exists())

    def test_the_database_refuses_nonsense(self):
        for values in ({'fresh_hours': 0}, {'fresh_hours': 8761}):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                rows().objects.filter(parameter='ph').update(**values)
        for seconds in (-1, 3601):
            with self.subTest(seconds=seconds), self.assertRaises(IntegrityError), transaction.atomic():
                PlatformSettings.objects.update(clock_tolerance_seconds=seconds)


class HeartbeatRuleTests(AlarmsCase):
    def test_a_channels_value_stays_fresh_for_its_own_number_of_heartbeats(self):
        channel = make_channel(make_device(make_connection(), make_format(), self.bergen), 'ph', heartbeat_s=60)
        channel.refresh_from_db()
        self.assertEqual((channel.fresh_heartbeats, channel.fresh_s), (3, 180))
        channel.fresh_heartbeats = 5
        channel.save()
        channel.refresh_from_db()
        self.assertEqual(channel.fresh_s, 300)
        with self.assertRaises(IntegrityError), transaction.atomic():
            type(channel).objects.filter(pk=channel.pk).update(fresh_heartbeats=0)


# The modules an alarm's decision reads, scanned for numbers: every one is a finding but an index (0, 1, 2), a column's
# size, or a name below, each with why it is not a rule the user sets.
SCANNED = ['alarms/*.py', 'farm/water/evaluate.py', 'farm/water/freshness.py', 'sensors/clock.py']
NAMED = {
    ('alarms/engine.py', 'LOCK'): "the advisory lock's key: an identity, not a threshold",
    ('alarms/worker.py', 'LOCK'): "the worker's session lock's key: an identity, not a threshold",
    ('alarms/worker.py', 'MS'): 'milliseconds in a second: a unit, not a threshold',
    ('alarms/worker.py', 'KEEPALIVE'): "shares of the worker's own stale_after (settings.ALARM_WORKER, the "
                                       "deployment's): how fast a dead worker's lock is let go, not a farm rule",
    ('alarms/models.py', 'LEVEL_BOUNDS'): 'the escalation levels a rule may name (0 to 9): a schema limit of the rule '
                                          'rows, checked by the database, not a value in force',
    ('alarms/models.py', 'DELAY_BOUNDS'): "the refusal of nonsense of a clear delay (§7c), never the delay in force",
    ('alarms/models.py', 'ON_DELAY_BOUNDS'): 'the refusal of unsafe raise delays per severity (cross review F9: the '
                                             "owner's 10 s target), never the delay in force",
    ('alarms/models.py', 'ESCALATION_BOUNDS'): 'the refusal of unsafe escalation times per severity (cross review F9), '
                                               'never the time in force',
    ('alarms/models.py', 'ATTEMPTS_BOUNDS'): 'the refusal of nonsense of delivery attempts (§7c)',
    ('alarms/models.py', 'RETRY_BOUNDS'): 'the refusal of nonsense of a retry time (a second to an hour), never the '
                                          'time in force',
    ('alarms/outbox.py', 'CLAIM'): "the advisory lock class of a notification being sent: an identity, not a threshold",
    ('alarms/models.py', 'CLOCK_SKEW_BOUNDS'): "the refusal of nonsense of a device clock limit: at most the ingest "
                                               "contract's hour",
    ('alarms/models.py', 'CLOCK_WINDOW_BOUNDS'): 'the refusal of nonsense of a device clock window (none to an hour), '
                                                 'never the window in force',
    ('alarms/models.py', 'USUAL_BOUNDS'): 'where the rules page warns (never refuses): advice, not a rule in force',
    ('farm/water/evaluate.py', 'MAX_AHEAD'): "the ingest contract's hour (sensors_contract.future_skew_s is at most "
                                             '3600 s): a protocol limit both sides of the contract hold, not a policy',
    ('farm/water/freshness.py', 'FRESH_HOURS_BOUNDS'): 'the refusal of nonsense of a freshness (1 h to a year)',
    ('farm/water/freshness.py', 'SEEDS'): "the defaults a missing row is made again with (as the platform settings' "
                                          'row is): the values in force are the rows',
}


class NoThresholdInTheCodeTests(AlarmsCase):
    """§7c, honestly: every number in the modules an alarm's decision reads is a finding, but an index, a column's size,
    or a name of NAMED, each with its reason; a name ending in _BOUNDS is no pass by itself."""

    def test_no_number_in_the_alarm_decision_is_a_threshold(self):
        root = pathlib.Path(settings.BASE_DIR)
        found, named = [], set()
        for pattern in SCANNED:
            for path in sorted(root.glob(pattern)):
                relative = path.relative_to(root).as_posix()
                tree = ast.parse(path.read_text(encoding='utf-8'))
                for node in ast.walk(tree):
                    if isinstance(node, ast.keyword) and node.arg in ('max_length', 'max_digits', 'decimal_places'):
                        node.value._exempt = True
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        for target in targets:
                            if (relative, getattr(target, 'id', '')) in NAMED:
                                named.add((relative, target.id))
                                for inner in ast.walk(node.value):
                                    inner._exempt = True
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
                            and not isinstance(node.value, bool) and node.value not in (0, 1, 2)
                            and not getattr(node, '_exempt', False)):
                        found.append(f'{relative}:{node.lineno}: {node.value}')
        self.assertEqual(found, [])
        self.assertEqual(set(NAMED) - named, set())          # no reason kept for a name that is gone
