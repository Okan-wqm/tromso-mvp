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


def rows_data(prefix, rows, initial=0):
    """What a row list (core.crud.RowList) posts: its management form and each row's fields under the
    list's prefix. A check box is given as True/False."""
    data = {
        f'{prefix}-TOTAL_FORMS': str(len(rows)), f'{prefix}-INITIAL_FORMS': str(initial),
        f'{prefix}-MIN_NUM_FORMS': '0', f'{prefix}-MAX_NUM_FORMS': '1000',
    }
    for i, row in enumerate(rows):
        for key, value in row.items():
            if value is True:
                data[f'{prefix}-{i}-{key}'] = 'on'
            elif value is not False:
                data[f'{prefix}-{i}-{key}'] = value
    return data


def contacts_data(rows, initial=0):
    return rows_data('contacts', rows, initial)


def role(name, *codenames):
    group = Group.objects.create(name=name)
    group.permissions.set(Permission.objects.filter(codename__in=codenames))
    return group


SITE_MANAGER = ('view_site', 'add_site', 'change_site', 'delete_site', 'view_auditlog')
