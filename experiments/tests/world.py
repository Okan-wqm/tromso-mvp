"""World A and world B for the confidentiality tests (experiments/tests/test_confidential.py).

World B is an ordinary farm: a site, a hall, an open tank with fish, its feeding, water, health, lice and a task, an open
system, a sensor channel. World A is world B plus a sealed experiment X: a running trial whose replicates hold a whole
system (two tanks) and one more tank, with everything on them. Every text of X and of what lies on its cells carries the
canary `XQZ`: its name, hypothesis and notes, its factor, level and group, the tanks' and the system's names and codes,
the batch stocked into them, the notes of their mortality, feeding, water sample, health event, treatment and lice count,
a task's title, a channel's name. Whoever may not see X must never meet the canary anywhere: in a page, a header, a
redirect, an export, a chart's data, a choice of a form or the activity log.

`build_open(cls)` makes world B and `build_sealed(cls)` adds X; a test that compares the two worlds renders between the
two calls. The rows are made straight in the database (the pages and services have their own tests), except the stock,
which the stock service books."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.utils import timezone

from core.access import areas
from core.codes import next_code
from farm import withdrawal_gate
from farm.models import (
    Feed, FeedingRecord, HealthEvent, LiceCount, Medicine, ProductionDepartment, Site, Species, System, Tank,
    Treatment, WaterMeasurement,
)
from farm.stock.dates import site_today
from farm.tests.helpers import make_species, point_of, stock_fish
from farm.tests.test_stock import make_unit
from sensors.tests import make_channel, make_connection, make_device, make_format
from tasks.models import Task

from ..models import Experiment, ExperimentGroup, Factor, GroupLevel, Level, Member, Replicate, ReplicateUnit

CANARY = 'XQZ'
# The trial began this many days ago and runs this many days.
BEGAN, DURATION = 5, 56


def _role(name, codenames):
    group, _ = Group.objects.get_or_create(name=name)
    group.permissions.set(Permission.objects.filter(
        content_type__app_label__in={app for app, _code in codenames},
        codename__in={code for _app, code in codenames}))
    return group


def _perms(*names):
    return [tuple(name.split('.')) for name in names]


def area_perms(actions=('view',), exclude_apps=()):
    """Every right of the role matrix for these actions, but those of the apps left out."""
    found = []
    for area in areas():
        for action in actions:
            if action in area.actions:
                perm = area.perm(action)
                if perm.split('.')[0] not in exclude_apps:
                    found.append(perm)
    return found


def person(username, *perms, **fields):
    user = get_user_model().objects.create_user(username, f'{username}@example.com', 'x', **fields)
    if perms:
        user.groups.add(_role(f'{username} role', _perms(*perms)))
    return user


EXPERIMENT_RIGHTS = ('experiments.view_experiment', 'experiments.add_experiment', 'experiments.change_experiment',
                     'experiments.delete_experiment')


@withdrawal_gate.opened('test fixture: the worlds’ feedings and treatments written straight in the database')
def build_open(cls):
    """World B: the farm without X, and the people who look at it."""
    cls.site = Site.objects.create(name='Bergen', code='BG')
    cls.hall = ProductionDepartment.objects.create(site=cls.site, name='Hall A', code='HA')
    cls.salmon = Species.objects.filter(code='SAL').first() or make_species()
    cls.open_system = System.objects.create(site=cls.site, production_department=cls.hall, name='Open loop', code='OL')
    cls.open_tank = make_unit('T-01', cls.hall, system=cls.open_system)
    cls.today = site_today(cls.site)
    cls.boss = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
    cls.feed = Feed.objects.create(name='Grower 4', code='GR-4', feed_type='grower', pellet_size_mm=Decimal(4))
    cls.medicine = Medicine.objects.create(name='Salmosan vet.', kind='lice', administration='bath',
                                           active_substance='azamethiphos', lice_report_code='AZAMETHIPHOS')
    cls.open_batch = stock_fish(cls.boss, cls.open_tank, 1000, '50', days_ago=20, species=cls.salmon)
    FeedingRecord.objects.create(unit=cls.open_tank, date=cls.today - timedelta(days=1), feed=cls.feed,
                                 amount_kg=Decimal('2.5'), notes='open feeding')
    WaterMeasurement.objects.create(point=point_of(cls.open_tank), measured_at=timezone.now() - timedelta(hours=2),
                                    source='manual', ph=Decimal('7.1'), notes='open water')
    LiceCount.objects.create(unit=cls.open_tank, date=cls.today - timedelta(days=1), fish_counted=20, adult_females=1,
                             mobile=1, attached=0, notes='open lice')
    task = Task(title='Clean the open drum filter', due_date=cls.today)
    task.set_place(cls.open_tank)
    task.save()
    cls.connection = make_connection()
    cls.format = make_format()
    cls.device = make_device(cls.connection, cls.format, cls.site)
    cls.open_channel = make_channel(cls.device, name='Open temperature')

    # The people. None of them is in X's team or holds a share of it.
    cls.hr = person('hr', 'hr.view_employee', 'hr.add_employee', 'hr.change_employee', 'hr.view_officedepartment',
                    'hr.view_attendancerecord', 'hr.view_leaverequest', 'hr.view_shiftassignment')
    everything = area_perms(exclude_apps=('reports',))
    cls.staff = person('staff', *everything)
    cls.researcher = person('researcher', *everything, *EXPERIMENT_RIGHTS, 'core.view_auditlog')
    cls.student = person('student', 'experiments.view_experiment', 'experiments.add_experiment',
                         'farm.view_tank', 'farm.view_system', 'farm.view_stockoperation', 'farm.view_feedingrecord',
                         'farm.view_watermeasurement', 'tasks.view_task')
    cls.lead = person('lead', *everything, *EXPERIMENT_RIGHTS)


@withdrawal_gate.opened('test fixture: the worlds’ feedings and treatments written straight in the database')
def build_sealed(cls):
    """Adds X to world B: a running trial with a whole system (two tanks) and a tank, and everything on them."""
    began = cls.today - timedelta(days=BEGAN)
    cls.sealed_system = System.objects.create(site=cls.site, production_department=cls.hall, name='XQZ loop',
                                              code='XQZ-S')
    cls.sealed_tanks = [make_unit(f'XQZ-{number}', cls.hall, system=cls.sealed_system if number < 3 else None)
                        for number in (1, 2, 3)]
    for tank in cls.sealed_tanks:
        Tank.objects.filter(pk=tank.pk).update(name=f'XQZ tank {tank.code}')
    cls.experiment = Experiment.objects.create(
        code=next_code(Experiment, f'E-{cls.today.year}-'), name='XQZ diet trial', site=cls.site, species=cls.salmon,
        duration_days=DURATION, starts_on=began, hypothesis='XQZ more protein', primary_endpoint='bfcr',
        notes='XQZ notes')
    factor = Factor.objects.create(experiment=cls.experiment, name='XQZ temperature', kind='other', unit='C')
    level = Level.objects.create(factor=factor, label='XQZ warm')
    group = ExperimentGroup.objects.create(experiment=cls.experiment, name='XQZ group')
    GroupLevel.objects.create(experiment=cls.experiment, group=group, factor=factor, level=level)
    cls.replicates = [Replicate.objects.create(group=group, number=number) for number in (1, 2)]
    last = began + timedelta(days=DURATION)
    cls.placements = [
        ReplicateUnit.objects.create(replicate=cls.replicates[0], unit=cls.sealed_tanks[0], from_on=began, until_on=last),
        ReplicateUnit.objects.create(replicate=cls.replicates[0], unit=cls.sealed_tanks[1], from_on=began, until_on=last),
        ReplicateUnit.objects.create(replicate=cls.replicates[1], unit=cls.sealed_tanks[2], from_on=began, until_on=last),
    ]
    # Started past the service, as the experiments' own tests do (a draft is built, then it runs).
    Experiment.objects.filter(pk=cls.experiment.pk).update(status='running', allocation_method='manual',
                                                           allocation_note='XQZ by hand')
    cls.experiment.refresh_from_db()
    Member.objects.create(experiment=cls.experiment, user=cls.lead, role='lead')
    cls.factor, cls.level, cls.group = factor, level, group

    tank = cls.sealed_tanks[0]
    cls.sealed_batch = stock_fish(cls.boss, tank, 500, '40', days_ago=BEGAN - 1, species=cls.salmon,
                                  name='XQZ batch', notes='XQZ stocked')
    cls.feeding = FeedingRecord.objects.create(unit=tank, date=cls.today - timedelta(days=1), feed=cls.feed,
                                               amount_kg=Decimal('1.5'), notes='XQZ feeding')
    cls.sealed_point = point_of(tank)
    cls.sample = WaterMeasurement.objects.create(point=cls.sealed_point, measured_at=timezone.now() - timedelta(hours=3),
                                                 source='manual', ph=Decimal('7.3'), notes='XQZ water')
    cls.lice = LiceCount.objects.create(unit=tank, date=cls.today - timedelta(days=1), fish_counted=20, adult_females=2,
                                        mobile=0, attached=0, notes='XQZ lice')
    cls.event = HealthEvent.objects.create(site=cls.site, date=cls.today - timedelta(days=1), kind='observation',
                                           findings='XQZ findings')
    cls.event.units.set([tank])
    cls.treatment = Treatment.objects.create(method='bath', medicine=cls.medicine, reason='sea_lice',
                                             start_date=cls.today - timedelta(days=2),
                                             end_date=cls.today - timedelta(days=1), notes='XQZ treatment')
    cls.treatment.units.set([tank])
    cls.task = Task(title='XQZ weigh the trial tank', due_date=cls.today)
    cls.task.set_place(tank)
    cls.task.save()
    cls.system_task = Task(title='XQZ backwash the trial loop', due_date=cls.today)
    cls.system_task.set_place(cls.sealed_system)
    cls.system_task.save()
    cls.sealed_channel = make_channel(cls.device, 'oxygen_mg_l', name='XQZ oxygen')
    from sensors.models import Binding
    cls.binding = Binding.objects.create(channel=cls.sealed_channel, point=cls.sealed_point,
                                         valid_from=timezone.now() - timedelta(days=BEGAN - 1))


def sealed_ids(cls):
    """{model label: [pk]} of every record of X and on its cells: what a route is tried with in place of its argument."""
    rows = [cls.experiment, cls.factor, cls.level, cls.group, *cls.replicates, *cls.placements, *cls.sealed_tanks,
            cls.sealed_system, cls.sealed_batch, cls.feeding, cls.sealed_point, cls.sample, cls.lice, cls.event,
            cls.treatment, cls.task, cls.system_task, cls.sealed_channel, cls.binding,
            *cls.sealed_batch.movements.values_list('operation', flat=True).distinct()]
    found = {}
    from farm.models import StockOperation
    for row in rows:
        if not hasattr(row, '_meta'):
            row = StockOperation.all_objects.get(pk=row)
        found.setdefault(row._meta.label, []).append(row.pk)
    return found
