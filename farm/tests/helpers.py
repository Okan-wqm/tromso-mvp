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
