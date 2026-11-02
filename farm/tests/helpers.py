"""Shared test helpers for the farm tabs."""
from django.contrib.auth.models import Group, Permission


def site_data(**overrides):
    data = {
        'name': 'Main Production Site', 'code': 'mps-001', 'type': 'land_based', 'status': 'active',
        'lokalitetsnummer': '', 'organisation_number_override': '', 'description': '', 'area_m2': '',
        'timezone': '', 'country': 'Norway', 'region': 'Vestland', 'street': '', 'city': '', 'state': '',
        'postal_code': '', 'latitude': '', 'longitude': '', 'altitude': '', 'site_manager': '',
        'contact_email': '', 'contact_phone': '',
    }
    data.update(overrides)
    return data


def contacts_data(rows, initial=0):
    data = {
        'contacts-TOTAL_FORMS': str(len(rows)), 'contacts-INITIAL_FORMS': str(initial),
        'contacts-MIN_NUM_FORMS': '0', 'contacts-MAX_NUM_FORMS': '1000',
    }
    for i, row in enumerate(rows):
        for key, value in row.items():
            if value is True:
                data[f'contacts-{i}-{key}'] = 'on'
            elif value is not False:
                data[f'contacts-{i}-{key}'] = value
    return data


def role(name, *codenames):
    group = Group.objects.create(name=name)
    group.permissions.set(Permission.objects.filter(codename__in=codenames))
    return group


SITE_MANAGER = ('view_site', 'add_site', 'change_site', 'delete_site', 'view_auditlog')


def make_species(code='SAL', common_name='Atlantic salmon', scientific_name='Salmo salar', **fields):
    from ..models import Species
    values = {'local_name': 'Laks', 'freshwater': True, 'saltwater': True, **fields}
    return Species.objects.create(code=code, common_name=common_name, scientific_name=scientific_name, **values)


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
