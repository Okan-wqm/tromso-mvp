"""The owner's university scenario (2026-11-24), the acceptance test of experiment confidentiality.

Twelve tanks, each its own recirculating system; four sealed experiments run side by side on three tanks each (blood
sampling, a feed trial, filter performance, a disease challenge); two technicians hold Oversee and do the daily work. The
technicians read every tank's farm facts (the tank, its water, feeding, stock, tasks) and none of the science of any
experiment; each team reads its own science and none of the others'; a lead of one experiment reads nothing of another's;
every tank's alarm reaches the technicians."""
from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core import sealing
from core.codes import next_code
from farm.models import FeedingRecord, StockMovement, System, Tank, WaterMeasurement
from farm.tests.helpers import point_of, stock_fish
from farm.tests.test_stock import make_unit
from tasks.models import Task

from .. import sealing as experiments_sealing
from ..models import Experiment, Factor, Member, ReplicateSystem, ReplicateUnit
from . import world

TRIALS = ('blood sampling', 'feed trial', 'filter performance', 'disease challenge')
# What no technician may meet: every experiment's name, design and notes carry it.
SCIENCE = 'SCQ'


class UniversityScenarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        world.build_open(cls)
        began = cls.today - timedelta(days=world.BEGAN)
        last = began + timedelta(days=world.DURATION)
        cls.tanks, cls.experiments, cls.leads, cls.factors = [], [], [], []
        for number in range(12):
            system = System.objects.create(site=cls.site, production_department=cls.hall, name=f'RAS {number + 1}',
                                           code=f'RAS-{number + 1}')
            tank = make_unit(f'U-{number + 1:02}', cls.hall, system=system)
            stock_fish(cls.boss, tank, 100, '40', days_ago=world.BEGAN - 1, species=cls.salmon)
            FeedingRecord.objects.create(unit=tank, date=cls.today - timedelta(days=1), feed=cls.feed,
                                         amount_kg=Decimal('0.8'))
            WaterMeasurement.objects.create(point=point_of(tank), measured_at=timezone.now() - timedelta(hours=1),
                                            source='manual', oxygen_mg_l=Decimal('9.1'))
            task = Task(title=f'Daily check of U-{number + 1:02}', due_date=cls.today)
            task.set_place(tank)
            task.save()
            cls.tanks.append(tank)
        for index, trial in enumerate(TRIALS):
            experiment = Experiment.objects.create(
                code=next_code(Experiment, f'E-{cls.today.year}-'), name=f'{trial} {SCIENCE}', site=cls.site,
                species=cls.salmon, duration_days=world.DURATION, starts_on=began,
                hypothesis=f'{trial} hypothesis {SCIENCE}', primary_endpoint='bfcr', notes=f'{SCIENCE} notes')
            factor = Factor.objects.create(experiment=experiment, name=f'{trial} factor {SCIENCE}', kind='other',
                                           unit='x')
            group = experiment.groups.create(name=f'{trial} group {SCIENCE}')
            replicate = group.replicates.create(number=1)
            for tank in cls.tanks[index * 3:index * 3 + 3]:
                booking = ReplicateSystem.objects.create(replicate=replicate, system=tank.system, from_on=began,
                                                         until_on=last)
                ReplicateUnit.objects.create(replicate=replicate, unit=tank, from_on=began, until_on=last,
                                             booking=booking)
            Experiment.objects.filter(pk=experiment.pk).update(status='running', allocation_method='manual',
                                                               allocation_note='by hand')
            lead = world.person(f'lead{index}', *world.EXPERIMENT_RIGHTS, 'farm.view_tank', 'farm.view_feedingrecord')
            Member.objects.create(experiment=experiment, user=lead, role='lead')
            cls.experiments.append(experiment)
            cls.leads.append(lead)
            cls.factors.append(factor)
        everyday = world.area_perms(exclude_apps=('reports', 'experiments'))
        cls.technicians = [world.person(f'tech{number}', *everyday, 'experiments.oversee_experiment')
                           for number in (1, 2)]

    def read(self, user, queryset):
        with sealing.as_viewer(user):
            return set(queryset.values_list('pk', flat=True))

    def test_the_technicians_read_every_tanks_farm_facts(self):
        tanks = {tank.pk for tank in self.tanks}
        for technician in self.technicians:
            with self.subTest(technician=technician.username):
                self.assertTrue(tanks <= self.read(technician, Tank.objects.all()))
                self.assertTrue(tanks <= self.read(technician, Tank.objects.filter(feedings__isnull=False)))
                self.assertEqual(len(self.read(technician, FeedingRecord.objects.filter(unit__in=tanks))), 12)
                self.assertEqual(len(self.read(technician, WaterMeasurement.objects.filter(point__unit__in=tanks))), 12)
                self.assertEqual(len(self.read(technician, StockMovement.objects.filter(unit__in=tanks))), 12)
                self.assertEqual(len(self.read(technician, Task.objects.filter(title__startswith='Daily check'))), 12)
                self.assertEqual(len(self.read(technician, System.objects.filter(code__startswith='RAS-'))), 12)

    def test_the_technicians_meet_none_of_the_science(self):
        for technician in self.technicians:
            with self.subTest(technician=technician.username):
                self.assertFalse(self.read(technician, Experiment.objects.filter(name__contains=SCIENCE)))
                self.assertFalse(self.read(technician, Factor.objects.all()))
                page = Client()
                page.force_login(technician)
                units = page.get(reverse('farm:production_units'))
                self.assertEqual(units.status_code, 200)
                for tank in self.tanks:
                    self.assertContains(units, tank.code)
                self.assertNotContains(units, SCIENCE)

    def test_each_team_reads_its_own_science_and_none_of_the_others(self):
        for index, lead in enumerate(self.leads):
            with self.subTest(lead=lead.username):
                mine = self.experiments[index]
                others = [each for each in self.experiments if each != mine]
                self.assertEqual(self.read(lead, Experiment.objects.filter(name__contains=SCIENCE)), {mine.pk})
                self.assertEqual(self.read(lead, Factor.objects.all()), {self.factors[index].pk})
                # No Oversee: the other experiments' tanks are not theirs to read either.
                theirs = {tank.pk for tank in self.tanks[index * 3:index * 3 + 3]}
                self.assertEqual(self.read(lead, Tank.objects.filter(code__startswith='U-')), theirs)
                self.assertFalse(self.read(lead, Experiment.objects.filter(pk__in=[each.pk for each in others])))

    def test_every_tanks_alarm_reaches_the_technicians(self):
        technicians = {technician.pk for technician in self.technicians}
        for index, tank in enumerate(self.tanks):
            with self.subTest(tank=tank.code):
                keepers = {user.pk for user in experiments_sealing.keepers(tank.pk, tank.system_id)}
                self.assertTrue(technicians <= keepers)
                self.assertIn(self.leads[index // 3].pk, keepers)
                self.assertFalse({lead.pk for lead in self.leads} - {self.leads[index // 3].pk} & keepers)
