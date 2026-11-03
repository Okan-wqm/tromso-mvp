"""Shared test helpers for the farm tabs."""
from django.contrib.auth.models import Group, Permission


def site_data(**overrides):
    data = {
        'name': 'Main Production Site', 'code': 'mps-001', 'type': 'land_based', 'status': 'active',
        'lokalitetsnummer': '', 'organisation_number': '', 'production_form': '', 'reports_from': '',
        'description': '', 'area_m2': '',
        'timezone': '', 'country': 'Norway', 'region': 'Vestland', 'street': '', 'city': '', 'state': '',
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
