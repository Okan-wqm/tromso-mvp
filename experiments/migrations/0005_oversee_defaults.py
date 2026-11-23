"""Oversee by default for the roles that care for the fish (plan 4, owner amendment C1 and decision C2.3): every role that
may already record stock operations, feedings, health events, treatments or lice counts gets Experiments: oversee, so a
sealed experiment never hides from them the fish they keep alive. Each right given is one row of the activity log (by
'system'), and the names of the roles given it are printed; the platform admin takes it away from a role in the role
matrix. A role that holds it already is neither given it nor said. The names are written here, as they are when this
migration is made (a migration never reads live code).

Going back takes away exactly what this gave and is still held, read from its own log rows, each logged."""
from django.db import migrations

from core.migrations._log import SYSTEM, entries, system_entry

OVERSEE = ('experiments', 'oversee_experiment')
# The rights that mark a role caring for the fish.
CARE = (('farm', 'add_stockoperation'), ('farm', 'add_feedingrecord'), ('farm', 'add_healthevent'),
        ('farm', 'add_treatment'), ('farm', 'add_licecount'))
SAID = 'Experiments: oversee'
GIVEN = 'experiments 0005: a role that cares for the fish oversees the tanks of confidential experiments (plan 4, C2.3).'
TAKEN = 'experiments 0005 reversed: the right this migration gave is taken away again.'


def _oversee(apps):
    """The Oversee permission, made here when the permissions are not made yet (a new database)."""
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    kind, _made = ContentType.objects.get_or_create(app_label=OVERSEE[0], model='experiment')
    permission, _made = Permission.objects.get_or_create(
        content_type=kind, codename=OVERSEE[1], defaults={'name': 'Can oversee the tanks of experiments'})
    return permission


def grant(apps, schema_editor=None):
    """Gives Oversee to every role holding one of the care rights; returns the names of the roles given it."""
    Group = apps.get_model('auth', 'Group')
    permission = _oversee(apps)
    care = None
    for app, codename in CARE:
        condition = {'permissions__content_type__app_label': app, 'permissions__codename': codename}
        found = Group.objects.filter(**condition).values_list('pk', flat=True)
        care = set(found) if care is None else care | set(found)
    given = []
    for group in Group.objects.filter(pk__in=care or ()).order_by('name'):
        if group.permissions.filter(pk=permission.pk).exists():
            continue
        group.permissions.add(permission)
        given.append(group.name)
        if schema_editor is not None:
            system_entry(schema_editor, 'role', group.pk, group.name, {'Permissions': [None, SAID], 'Note': [None, GIVEN]})
    if given and schema_editor is not None:
        print(f'\n  experiments 0005: Oversee given to {", ".join(given)}')
    return given


def withdraw(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    permission = Permission.objects.filter(content_type__app_label=OVERSEE[0], codename=OVERSEE[1]).first()
    if permission is None:
        return
    owed = {}
    for role_id, who, _action, changes in entries(schema_editor, 'role'):
        note = (changes.get('Note') or [None, None])[1] if who == SYSTEM else None
        if note == GIVEN:
            owed[role_id] = owed.get(role_id, 0) + 1
        elif note == TAKEN:
            owed[role_id] = owed.get(role_id, 0) - 1
    for role_id, count in owed.items():
        group = Group.objects.filter(pk=role_id).first() if count > 0 else None
        if group is None or not group.permissions.filter(pk=permission.pk).exists():
            continue
        group.permissions.remove(permission)
        system_entry(schema_editor, 'role', group.pk, group.name, {'Permissions': [SAID, None], 'Note': [None, TAKEN]})


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('core', '0015_access_event'),
        ('experiments', '0004_confidential'),
    ]

    operations = [migrations.RunPython(grant, withdraw)]
