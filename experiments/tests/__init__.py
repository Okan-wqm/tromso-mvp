"""Shared setup for the Experiments tests: the stock test case's farm (a hall with tanks on one site, a sea site with a
pond, a salmon and a trout) with six more tanks, a protocol to feed by, and helpers that write rows by the ORM, which
checks nothing (the constraints are what is tested), and through the services."""
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction

from core.codes import next_code
from farm.models import Feed, FeedingProtocol, ProtocolBand, ProtocolRate
from farm.tests.helpers import may_record
from farm.tests.test_stock import StockTestCase, make_unit

from ..models import (
    Experiment, ExperimentGroup, Factor, GroupLevel, Level, Member, Replicate, ReplicateUnit,
)

D = Decimal


class ExperimentTestCase(StockTestCase):
    # Who may read the experiments the helper makes: open, so the experiments' own tests (design, places, start, the
    # pages) read and change them as everyone who reads experiments did before confidentiality. Who reads a sealed or
    # private one has its own tests (test_access, test_confidential, test_oversee); None leaves the database's default
    # (sealed).
    audience = 'open'
    def setUp(self):
        super().setUp()
        # the fixtures' experiments are written through the services, which ask who may (the data-layering audit, L-6)
        may_record(self.user, 'add_experiment', 'change_experiment')
        self.tanks = [self.t1, self.t2] + [make_unit(f'T-{number:02d}', self.hall) for number in range(3, 9)]
        self.feed = Feed.objects.create(name='Grower 4', code='GR-4', feed_type='grower', pellet_size_mm=D(4))

    def protocol(self, name='Salmon grow-out', species=None, status='active'):
        """A feeding protocol with a one-band table (the farm's own tests build richer ones)."""
        protocol = FeedingProtocol.objects.create(name=name, species=species or self.salmon, expected_fcr=D('1.00'),
                                                  status=status)
        band = ProtocolBand.objects.create(protocol=protocol, min_weight_g=0, max_weight_g=None, feed=self.feed,
                                           meals_per_day=4)
        ProtocolRate.objects.create(band=band, temperature_c=D(12), sfr_pct=D('1.10'))
        return protocol

    def experiment(self, name='Diet trial', **fields):
        """A draft experiment of salmon at Bergen, numbered as the form numbers it, by the ORM."""
        values = {'site': self.bergen, 'species': self.salmon, 'duration_days': 56, **fields}
        if self.audience is not None:
            values.setdefault('audience', self.audience)
        values.setdefault('code', next_code(Experiment, f'E-{self.today.year}-'))
        return Experiment.objects.create(name=name, **values)

    def factor(self, experiment, name='Diet', kind='diet', **fields):
        return Factor.objects.create(experiment=experiment, name=name, kind=kind, **fields)

    def level(self, factor, protocol=None, label='', **fields):
        if factor.kind == 'diet' and protocol is None:
            protocol = self.protocol(f'Protocol {Level.objects.count() + 1}')
        return Level.objects.create(factor=factor, protocol=protocol, label=label, **fields)

    def group(self, experiment, name='A', role='test', **fields):
        return ExperimentGroup.objects.create(experiment=experiment, name=name, role=role, **fields)

    def group_level(self, group, level):
        return GroupLevel.objects.create(experiment=group.experiment, group=group, factor=level.factor, level=level)

    def replicate(self, group, number=1):
        return Replicate.objects.create(group=group, number=number)

    def placement(self, replicate, unit, first=0, last=56, **fields):
        return ReplicateUnit.objects.create(replicate=replicate, unit=unit, from_on=self.today + timedelta(days=first),
                                            until_on=self.today + timedelta(days=last), **fields)

    def member(self, experiment, user, role='researcher'):
        return Member.objects.create(experiment=experiment, user=user, role=role)

    def refuses(self, call, *args, **kwargs):
        """The database refuses what `call` writes (its own savepoint: the test goes on)."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            call(*args, **kwargs)
