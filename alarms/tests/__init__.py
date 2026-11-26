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
from ..models import Alarm, AlarmClearance, RecipientRule
from ..routing import NO_RULES, UNREACHED

D = Decimal
OXYGEN = D('9.00')


# The alarm tests run the pass as a farm does (landing review 4, R5): the alarm system's watch on who it reached on, and a
# connected transport (a double that records what it would send).
RECORDING = {'push': 'alarms.tests.doubles.RecordingTransport'}


@override_settings(ALARM_SUPERVISE_REACH=True, ALARM_TRANSPORTS=RECORDING)
class AlarmsCase(TestCase):
    # A test whose world tells nobody of a critical alarm on purpose (a rule of another site, a level nobody is on, the
    # sender failing) says so here, with its reason; every other test that has made a rule asserts the watch is quiet.
    reaches_nobody = ''

    def setUp(self):
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

    def loop(self, minutes=0, seconds=0):
        """The worker at a moment: its pass, then a round through the outbox (alarms/worker.py); the pass's Summary."""
        at = self.now + timedelta(minutes=minutes, seconds=seconds)
        summary = engine.run_once(at)
        outbox.send_due(at)
        if RecipientRule.objects.filter(is_active=True).exists() and not self.reaches_nobody:
            # A farm set up with its rules and a connected channel: the watch on who it reached stays quiet.
            self.assertFalse(Alarm.objects.filter(source='system', parameter__in=(UNREACHED, NO_RULES))
                             .exclude(pk__in=AlarmClearance.objects.values('alarm')).exists(),
                             'the alarm system said an alarm reached nobody on a farm with its rules')
        return summary

    def critical(self):
        """The one critical water alarm (a critical value holds the warning level too: its alarm opens beside it)."""
        return Alarm.objects.get(severity='critical', source='water_limit')
