"""Shared setup for the Messages tests: people with and without the area Messages."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase

from farm.tests.helpers import role

USE = ('view_conversation',)
CHANNELS = ('view_conversation', 'add_conversation')


def person(username, *codenames, **fields):
    user = get_user_model().objects.create_user(username, f'{username}@example.com', 'x', **fields)
    if codenames:
        user.groups.add(role(f'{username} role', *codenames))
    return user


def check_deferred():
    """Runs the deferred foreign keys now (Django's own and the two-column ones of migration 0001); a test
    never commits, so they would otherwise never be checked."""
    with connection.cursor() as cursor:
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')


class MessagingTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ali = person('ali', *CHANNELS, first_name='Ali', last_name='Kaya')
        cls.egon = person('egon', *USE, first_name='Egon', last_name='Berg')
        cls.kari = person('kari', *USE, first_name='Kari', last_name='Nord')
        cls.outsider = person('olav', 'view_site')       # signs in, may not use Messages
