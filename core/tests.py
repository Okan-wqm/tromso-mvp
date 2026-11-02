from django.db import connection
from django.test import TestCase


class DatabaseTests(TestCase):
    def test_timescaledb_extension_is_installed(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
            self.assertIsNotNone(cursor.fetchone())
