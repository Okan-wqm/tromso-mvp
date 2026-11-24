from contextlib import ContextDecorator
"""Shared test helpers for the farm tabs."""
from django.contrib.auth.models import Group, Permission


def site_data(**overrides):
    data = {
        'name': 'Main Production Site', 'code': 'mps-001', 'type': 'land_based', 'status': 'active',
        'lokalitetsnummer': '', 'organisation_number': '', 'production_form': '', 'reports_from': '',
        'description': '', 'area_m2': '',
        'timezone': 'Europe/Oslo', 'country': 'Norway', 'region': 'Vestland', 'street': '', 'city': '', 'state': '',
        'postal_code': '', 'latitude': '', 'longitude': '', 'altitude': '', 'site_manager': '',
        'contact_email': '', 'contact_phone': '',
    }
    data.update(overrides)
    return data


def rows_data(prefix, rows, initial=0, record=None):
    """What a row list (core.crud.RowList) posts: its management form, each row's fields under the list's
    prefix (a check box given as True/False), and the version of its `record` as stored now, which the page
    sends with the list (a save based on an outdated record is refused)."""
    data = {
        f'{prefix}-TOTAL_FORMS': str(len(rows)), f'{prefix}-INITIAL_FORMS': str(initial),
        f'{prefix}-MIN_NUM_FORMS': '0', f'{prefix}-MAX_NUM_FORMS': '1000',
    }
    if record is not None:
        data['version'] = str(type(record).all_objects.values_list('version', flat=True).get(pk=record.pk))
    for i, row in enumerate(rows):
        for key, value in row.items():
            if value is True:
                data[f'{prefix}-{i}-{key}'] = 'on'
            elif value is not False:
                data[f'{prefix}-{i}-{key}'] = value
    return data


def contacts_data(rows, initial=0, record=None):
    return rows_data('contacts', rows, initial, record)


def role(name, *codenames):
    group = Group.objects.create(name=name)
    group.permissions.set(Permission.objects.filter(codename__in=codenames))
    return group


class correction_window(ContextDecorator):
    """The platform owner's correction window (core.platform) set to `days` for a block or a test method, and put
    back after it."""

    def __init__(self, days):
        self.days = days

    def __enter__(self):
        from core.models import PlatformSettings
        self.before = PlatformSettings.get().correction_window_days
        PlatformSettings.objects.update(correction_window_days=self.days)
        return self

    def __exit__(self, *exc):
        from core.models import PlatformSettings
        PlatformSettings.objects.update(correction_window_days=self.before)
        return False


# What every refusal by the correction window ends with (core.platform.window_way_out), and what a refused stocking
# says before it (farm.stock.dates.opening_way_out): flow fault B-07.
WINDOW_WAY_OUT = ('The correction window is the platform owner’s setting: it is changed in Company › Administration › '
                  'Platform settings.')
OPENING_WAY_OUT = ('Fish the farm already had before then are registered as an opening balance (Company › '
                   'Administration › Opening balances), by the platform owner.')


SITE_MANAGER = ('view_site', 'add_site', 'change_site', 'delete_site', 'view_auditlog')


def make_species(code='SAL', common_name='Atlantic salmon', scientific_name='Salmo salar', **fields):
    from ..models import Species
    values = {'local_name': 'Laks', 'freshwater': True, 'saltwater': True, **fields}
    return Species.objects.create(code=code, common_name=common_name, scientific_name=scientific_name, **values)


def make_facility(name='Fjord Slakteri', approval_number='M123', **fields):
    """An active slaughter facility that takes every species (Harvest and logistics › Slaughter facilities)."""
    from ..models import SlaughterFacility
    return SlaughterFacility.objects.create(name=name, approval_number=approval_number, **fields)


def stock_fish(user, unit, count=1000, weight='50', days_ago=10, species=None, **fields):
    """Stocks a new batch of `count` fish of `weight` g into `unit`, `days_ago` days back; returns the batch."""
    from datetime import timedelta
    from decimal import Decimal

    from ..models import Species
    from ..stock import services
    species = species or Species.objects.first() or make_species()
    values = {'input_stage': 'fry', 'origin': 'own_hatchery', **fields}
    operation = services.record_input(user, species=species, day=services.local_today(unit) - timedelta(days=days_ago),
                                      lines=[(unit, count, Decimal(weight))], **values)
    return operation.movements.get().batch


def point_of(owner, kind='middle'):
    """The owner's sampling point of that kind (its middle one by default), made with the points a new owner starts
    with when it has none yet: a test's units and systems are made straight in the database, not through the tabs that
    make their points (farm/water/points.py), and without a log row. A piece of equipment has none by default, so
    the point asked for is made."""
    from ..models import SamplingPoint
    from ..models.water_point import owner_type_of
    from ..water.points import template_for
    owner_type = owner_type_of(owner)
    wanted = template_for(owner_type, getattr(owner, 'kind', '')) or [(kind, kind.replace('_', ' ').capitalize())]
    for point_kind, name in wanted:
        SamplingPoint.all_objects.get_or_create(**{owner_type: owner}, kind=point_kind, name=name)
    return SamplingPoint.objects.get(**{owner_type: owner}, kind=kind)


LIVE_ON_A_SITE = 'chk_production_departments_live_on_a_site'


def leave_without_site(department):
    """Makes `department` one of the rows a deleted site left without a site before the database held that a live
    production department is on a site: the check is put back NOT VALID, as on a database that had such rows (farm
    migration 0029), so the row stays as it is until it is changed."""
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1 FROM pg_constraint WHERE conname = %s', [LIVE_ON_A_SITE])
        held = cursor.fetchone() is not None
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')    # a table with pending deferred checks cannot be altered
        cursor.execute(f'ALTER TABLE production_departments DROP CONSTRAINT IF EXISTS {LIVE_ON_A_SITE}')
        cursor.execute('UPDATE production_departments SET site_id = NULL WHERE id = %s', [department.pk])
        if held:
            cursor.execute(f'ALTER TABLE production_departments ADD CONSTRAINT {LIVE_ON_A_SITE} '
                           'CHECK (site_id IS NOT NULL OR is_deleted) NOT VALID')
    department.refresh_from_db()
    return department


def going_on(call, *args, **kwargs):
    """A write the withdrawal guard asks about (a harvest brought inside a withdrawal, fish released earlier), gone on
    with as the person does: the box's value, the change's fingerprint, sent with the same write
    (farm/tests/test_withdrawal_guard.py tests the question itself)."""
    from ..health.withdrawal import WithdrawalChanged
    try:
        return call(*args, **kwargs)
    except WithdrawalChanged as asked:
        return call(*args, withdrawal_ack=asked.change.fingerprint, **kwargs)


# The rights a fixture needs to write the farm's records through their services, which ask who may themselves (the
# data-layering audit, L-6): stocking, a sample, a feeding, and voiding each.
RECORDER = ('add_stockoperation', 'delete_stockoperation', 'add_watermeasurement', 'delete_watermeasurement',
            'add_feedingrecord', 'delete_feedingrecord')


def may_record(user, *codenames):
    """`user` given the rights a fixture records with (RECORDER, or `codenames`), as rights of the person (no role, so
    no role name to clash); returns the user read again, since Django keeps a person's rights once it has read them."""
    from django.contrib.auth.models import Permission
    user.user_permissions.add(*Permission.objects.filter(codename__in=codenames or RECORDER))
    return type(user).objects.get(pk=user.pk)
