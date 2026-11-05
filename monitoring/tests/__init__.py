"""Shared setup for the monitoring tests: the feeding tests' farm (T-01 with 10,000 salmon, T-02 with a protocol and a
ration, a site on each of two clocks) and helpers to make more stocked units and their water."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from farm.models import WaterLimit
from farm.tests.helpers import point_of, role, stock_fish
from farm.tests.test_protocols import WorkedExampleTestCase
from farm.tests.test_stock import make_unit
from farm.water import services as water_services

from ..cards import builtin
from ..cards.resolve import Choice

D = Decimal
# Everything a card can show: one right for each section.
ALL_RIGHTS = ('view_stockoperation', 'view_feedingrecord', 'view_watermeasurement', 'view_treatment',
              'view_healthevent', 'view_licecount', 'view_task')


# The built-in that draws a card as each mode drew it before templates.
TEMPLATE = {'simple': builtin.SIMPLE, 'detailed': builtin.DETAILED}


def chosen(modes):
    """The page's choice that draws each unit's card ({unit id: 'simple' | 'detailed'}) with the built-in of its mode,
    as a board's row for the unit would."""
    return Choice(rows={unit_id: TEMPLATE[mode] for unit_id, mode in modes.items()})


class MonitoringCase(WorkedExampleTestCase):
    """T-01 and T-02 of the worked example, and a person who may read every section of a card."""

    def setUp(self):
        super().setUp()
        self.reader = self.person('reader', *ALL_RIGHTS)
        self.client.force_login(self.reader)

    def person(self, username, *codenames):
        user = get_user_model().objects.create_user(username, f'{username}@example.com', 'x')
        if codenames:
            user.groups.add(role(f'{username} role', *codenames))
        return user

    def as_person(self, username, *codenames):
        """Signs in a person with only these rights; returns the user (a fresh object: permissions are cached)."""
        user = self.person(username, *codenames)
        self.client.force_login(user)
        return user

    def sample(self, unit, hours=1, **values):
        """A water sample at the unit's middle point, `hours` ago."""
        return water_services.record(self.user, point=point_of(unit), measured_at=timezone.now() - timedelta(hours=hours),
                                     source='manual', values={name: D(str(value)) for name, value in values.items()})

    def limit(self, parameter, **bounds):
        return WaterLimit.objects.create(species=self.salmon, parameter=parameter, water_type='any',
                                         **{name: D(str(value)) for name, value in bounds.items()})

    def farm_of(self, count, prefix='M', fresh=True):
        """`count` more units, each with fish of its own and fresh water at its middle point; returns them with the
        site's and department's names loaded (what the page's read gives)."""
        from farm.models import Tank
        units = []
        for number in range(count):
            unit = make_unit(f'{prefix}-{number:03d}', self.hall)
            stock_fish(self.user, unit, 500, '50', 10, species=self.salmon)
            if fresh:
                self.sample(unit, hours=1, temperature_c='9.5', oxygen_mg_l='9', ph='7.2')
            units.append(unit)
        return list(Tank.objects.select_related('production_department__site', 'system')
                    .filter(pk__in=[unit.pk for unit in units]).order_by('code'))
