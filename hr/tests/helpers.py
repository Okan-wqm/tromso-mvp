from django.contrib.auth import get_user_model
from django.test import TestCase

from farm.tests.helpers import role

AUDIT_COLUMNS = {'id', 'created_at', 'updated_at', 'created_by', 'updated_by', 'version', 'is_deleted',
                 'deleted_at', 'deleted_by'}

HR_ADMIN = (
    'view_officedepartment', 'add_officedepartment', 'change_officedepartment', 'delete_officedepartment',
    'view_auditlog',
)


def user(name='ali', *codenames, group=None):
    """A person who can sign in, with a role of these permissions (by codename)."""
    person = get_user_model().objects.create_user(name, f'{name}@example.com', 'x')
    if codenames:
        person.groups.add(role(group or f'{name} role', *codenames))
    return person


def fields_of(model):
    """The columns a model's own tests must cover: every field but the audit columns every record has."""
    return {field.name for field in model._meta.fields} - AUDIT_COLUMNS


class HrTestCase(TestCase):
    """A signed-in person with the office-department verbs."""

    def setUp(self):
        self.user = user('ali', *HR_ADMIN)
        self.client.force_login(self.user)


class _Private:
    """Equal to the log's value for a private text: the enumerated "Private text" with its digest, whatever the digest is."""

    def __eq__(self, other):
        return isinstance(other, dict) and other.get('msgid') == 'Private text' and bool(other.get('rev'))

    def __repr__(self):
        return 'PRIVATE'


PRIVATE = _Private()
