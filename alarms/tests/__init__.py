"""Shared setup for the alarms tests: a site with a hall, a RAS and two tanks with salmon, a pH limit, the people who are
notified (an operator on the hall's rule, a manager one level up) and helpers for samples and the loop."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from farm.models import ProductionDepartment, Site, System, WaterLimit
from farm.tests.helpers import make_species, may_record, point_of, role, stock_fish
from farm.tests.test_stock import make_unit
from farm.water import services as water

from .. import engine, outbox
from ..models import Alarm, RecipientRule
from ..routing import NO_RULES, TO_OVERSEERS, UNREACHED
from .doubles import RecordingTransport

D = Decimal
OXYGEN = D('9.00')


# The alarm tests run the pass as a farm does (landing review 4, R5): the alarm system's watch on who it reached on, and a
# connected transport (a double that records what it would send).
RECORDING = {'push': 'alarms.tests.doubles.RecordingTransport'}

# A test of what waits, and of what the pages say, while no transport is connected (the pilot's state): a world, never a
# switch of what the alarm system does (landing review 5, N2: its watch on who it reached runs in every test, as on a
# farm).
NOTHING_CONNECTED = override_settings(ALARM_TRANSPORTS={})


def ran_clean(case, summary):
    """Review 8 of derived-fresh, N3: a pass whose step crashed leaves every level as it was, so "it stays open" and
    "nothing was raised" hold on a crash too. THE check of a test pass that expects no failure: no step failed, and no
    unit's water was left unevaluated by an exception (sources.UNIT_UNEVALUATED). Returns the summary."""
    from ..sources import UNIT_UNEVALUATED
    case.assertEqual(summary.failed_steps, [], f'a step of the pass failed: {summary}')
    case.assertFalse(Alarm.objects.filter(source='system', parameter=UNIT_UNEVALUATED).exists(),
                     'a unit could not be evaluated: its water read raised')
    return summary


def farm_alarms(alarms=None):
    """The alarms (all of them, or of `alarms`) without the alarm system's own about who it reached (no recipient rule,
    no connected channel, a critical told to nobody: routing.TO_OVERSEERS). THE helper of a test that counts what its
    world raises and makes no rule or connects nothing on purpose: the watch runs there as everywhere, and its alarms
    are beside the point of such a test, not absent."""
    return (Alarm.objects.all() if alarms is None else alarms).exclude(source='system', parameter__in=TO_OVERSEERS)


@override_settings(ALARM_TRANSPORTS=RECORDING)
class AlarmsCase(TestCase):
    # A test whose world tells nobody of a critical alarm on purpose (a rule of another site, a level nobody is on, the
    # sender failing) says so here, with its reason; every other test that has made a rule asserts the watch is quiet.
    reaches_nobody = ''

    def setUp(self):
        # What the recording transport took is this test's alone (review 5, N9).
        for kept in (RecordingTransport.sent, RecordingTransport.floods):
            kept.clear()
            self.addCleanup(kept.clear)
        User = get_user_model()
        self.keeper = User.objects.create_user('keeper', 'keeper@example.com', 'x')
        self.keeper.groups.add(role('Water keeper', 'view_watermeasurement', 'add_watermeasurement',
                                    'delete_watermeasurement', 'view_stockoperation', 'add_stockoperation'))
        may_record(self.keeper, 'add_binding')          # binds the fixtures' sensors: the binding service asks (L-6)
        self.bergen = Site.objects.create(name='Bergen', code='BG', altitude=D(0))
        self.oslo = Site.objects.create(name='Oslo', code='OS', altitude=D(0))
        self.hall = ProductionDepartment.objects.create(site=self.bergen, name='Hall A', code='HA')
        self.ras = System.objects.create(name='RAS 1', code='R1', site=self.bergen, production_department=self.hall)
        self.t1 = make_unit('T-01', self.hall, system=self.ras)
        self.mid1 = point_of(self.t1)
        self.salmon = make_species()
        stock_fish(self.keeper, self.t1, 1000, '50', 10, species=self.salmon)
        WaterLimit.objects.create(species=self.salmon, parameter='ph', water_type='any', critical_low=D(6),
                                  warning_low=D('6.5'))
        self.operators = role('Operators')
        self.operator = User.objects.create_user('operator', 'operator@example.com', 'x', first_name='Ola')
        self.operator.groups.add(self.operators)
        self.manager = User.objects.create_user('manager', 'manager@example.com', 'x', first_name='Mona')
        self.now = timezone.now().replace(microsecond=0)

    def sample(self, ph, hours=1, point=None):
        """A pH sample, the oxygen measured with it: a unit with fish and no fresh oxygen is critical (owner decision of
        2026-11-23, monitoring/tests/test_silent_oxygen.py), which these tests are not about."""
        return water.record(self.keeper, point=point or self.mid1, measured_at=self.now - timedelta(hours=hours),
                            source='manual', values={'ph': D(str(ph)), 'oxygen_mg_l': OXYGEN})

    def rule(self, level=0, **fields):
        values = {'site': self.bergen, 'min_severity': 'warning', 'level': level, 'channel': 'push', **fields}
        if 'user' not in values and 'role' not in values:
            values['role'] = self.operators
        return RecipientRule.objects.create(**values)

    def loop(self, minutes=0, seconds=0, failing=False):
        """The worker at a moment: its pass, then a round through the outbox (alarms/worker.py); the pass's Summary. A
        pass ran clean (`ran_clean`) unless the test makes it fail on purpose (`failing`)."""
        at = self.now + timedelta(minutes=minutes, seconds=seconds)
        # A farm set up with its rules and a connected channel: the watch on who it reached opens nothing in this pass (one
        # opened before the rules were made clears after its off-delay, as any alarm does).
        watched = RecipientRule.objects.filter(is_active=True).exists() and not self.reaches_nobody
        before = set(self.watch_alarms()) if watched else set()
        summary = engine.run_once(at)
        if not failing:
            ran_clean(self, summary)
        outbox.send_due(at)
        if watched:
            self.assertFalse(set(self.watch_alarms()) - before,
                             'the alarm system said an alarm reached nobody on a farm with its rules')
        return summary

    def watch_alarms(self):
        return Alarm.objects.filter(source='system', parameter__in=(UNREACHED, NO_RULES)).values_list('pk', flat=True)

    def critical(self):
        """The one critical water alarm (a critical value holds the warning level too: its alarm opens beside it)."""
        return Alarm.objects.get(severity='critical', source='water_limit')
