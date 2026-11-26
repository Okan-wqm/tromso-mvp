"""A farm with a hatchery and a sea site, their units, and the stock of October 2026, recorded through the stock
service (farm/stock/services.py) as people record it: the reports read it back."""
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.testing import StartedClock
from farm.models import ProductionDepartment, Site
from farm.stock import services
from farm.tests.helpers import RECORDER, correction_window, make_facility, make_species, may_record, role
from farm.tests.test_stock import make_unit

from .. import compute, integrity
from ..models import Report
from ..periods import MONTH, WEEK, Period

REPORTER = ('view_report', 'add_report', 'change_report', 'delete_report', 'view_auditlog')
OCTOBER = Period(MONTH, date(2026, 10, 1))
WEEK_47 = Period(WEEK, date(2026, 11, 16))


def day(month, number):
    return date(2026, month, number)


def previewed(report):
    """The hash of the content the report's page shows now: what a person sends back when recording the filing."""
    return compute.content_hash(compute.compute(report).content)


# The records are dated in October 2026: far enough back for the platform owner's correction window to need widening.
# And the clock is held (README, Tests: a test dated on fixed days does not read the day it runs on): the pages and the
# deadlines read today, and a plan's "day it was agreed" is the day its row was made. On the real clock
# PlannedSlaughterTests' deadline of week 47 (Thursday 12.11.2026, a fast from Wednesday 11) failed from 12.11.2026 on,
# and the overdue driftsplan of 2026 from the day 2027's is owed (found with TEST_CLOCK=2027-12-31T23:30:00+00:00).
# The moment is the day these tests last ran on the real clock; from there the clock runs on, as the reports and their
# log rows are told apart by when they were made.
class ReportTestCase(StartedClock, TestCase):
    NOW = datetime(2026, 11, 11, 12, 0, tzinfo=dt_timezone.utc)

    def setUp(self):
        correction_window(3650).__enter__()             # the test's transaction puts the row back
        self.user = get_user_model().objects.create_user('kari', 'kari@example.com', 'x', first_name='Kari',
                                                         last_name='Nord')
        self.user.groups.add(role('Reporter', *REPORTER))
        # the records the fixtures write through the farm's services, which ask who may (the data-layering audit, L-6)
        may_record(self.user, *RECORDER, 'add_licecount', 'delete_licecount', 'add_treatment', 'delete_treatment')
        self.client.force_login(self.user)
        self.hatchery = Site.objects.create(name='Hatchery', code='HA', type='hatchery', lokalitetsnummer=12345,
                                            organisation_number='987654321')
        self.sea = Site.objects.create(name='Fjord', code='FJ', type='sea_cage', latitude=60, longitude=5,
                                       lokalitetsnummer=23456, organisation_number='987654321')
        self.hall = ProductionDepartment.objects.create(site=self.hatchery, name='Hall', code='HL')
        self.bay = ProductionDepartment.objects.create(site=self.sea, name='Bay', code='BY')
        self.k1, self.k2, self.k3 = (make_unit(code, self.hall) for code in ('K-01', 'K-02', 'K-03'))
        self.m1 = make_unit('M-01', self.bay, regulatory_unit_id='1')
        self.salmon = make_species(official_code='SAL')
        self.facility = make_facility()

    # ---- October 2026, as the stock service records it -------------------------------------------------------
    def october(self):
        """5,000 fish of 2 g into K-01 in September; in October 100 die, 50 are culled, 1,000 go to K-02 (the same
        site), K-01 is weighed at 5 g, 500 go from K-02 to the sea site, and K-03 is stocked with 800 of 3 g and
        emptied into the sea site."""
        self.first = self.stock(self.k1, 5000, '2', day(9, 20))
        services.record_mortality(self.user, unit=self.k1, batch=self.first, day=day(10, 5), count=100, cause='disease')
        services.record_cull(self.user, unit=self.k1, batch=self.first, day=day(10, 6), count=50, reason='small_size')
        services.record_transfer(self.user, source=self.k1, batch=self.first, day=day(10, 10),
                                 legs=[(self.k2, 1000)], reason='density')
        services.record_weighing(self.user, unit=self.k1, batch=self.first, day=day(10, 12), avg_weight_g=Decimal(5))
        self.out = services.record_transfer(self.user, source=self.k2, batch=self.first, day=day(10, 15),
                                            legs=[(self.m1, 500)], reason='growth_stage')
        self.second = self.stock(self.k3, 800, '3', day(10, 20))
        services.record_transfer(self.user, source=self.k3, batch=self.second, day=day(10, 25),
                                 legs=[(self.m1, 800)], reason='growth_stage')

    def assertReportsAddUp(self):
        """`manage.py check_reports` finds nothing (reports/integrity.py)."""
        self.assertEqual(integrity.problems(), [])

    def stock(self, unit, count, weight, on):
        operation = services.record_input(self.user, species=self.salmon, input_stage='smolt', origin='own_hatchery',
                                          day=on, lines=[(unit, count, Decimal(weight))])
        return operation.movements.get().batch

    def report(self, kind, period=None, site=None, **fields):
        """A draft started as the page starts one, with its contact person."""
        values = {'contact_name': 'Kari Nord', 'contact_email': 'kari@example.com', 'contact_phone': '+47 98989898',
                  'created_by': self.user, 'updated_by': self.user, **fields}
        if kind == Report.Kind.SLAUGHTER_PLANNED:
            values.setdefault('facility', self.facility)
        else:
            values.setdefault('site', site or self.hatchery)
        return Report.objects.create(kind=kind, period_start=period.start if period else None, **values)
