"""manage.py bench_sensors: synthetic readings for the storage and read-time figures of the plan (raw rows, minute rollup
rows against raw, the time of a chart and of the latest values). It writes into the database it is pointed at, so it
refuses to run unless that database's name is confirmed; and the ingest's own writes never touch the activity log."""
from io import StringIO

from django.core.management import CommandError, call_command
from django.db import connection

from core import audit
from core.models import AuditLog

from . import SensorsCase


class BenchTests(SensorsCase):
    def test_it_refuses_an_unconfirmed_database(self):
        with self.assertRaises(CommandError):
            call_command('bench_sensors', '--channels', '1', '--days', '1', stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('bench_sensors', '--channels', '1', '--days', '1', '--confirm-database', 'balik',
                         stdout=StringIO())

    def test_a_small_run_writes_readings_and_reports_the_figures(self):
        out = StringIO()
        call_command('bench_sensors', '--channels', '2', '--days', '1', '--interval', '60',
                     '--confirm-database', connection.settings_dict['NAME'], stdout=out)
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM sensors_reading WHERE channel_no >= 1000000')
            self.assertEqual(cursor.fetchone()[0], 2 * 1440)
        report = out.getvalue()
        for words in ('raw rows: 2880', 'minute rollup rows:', 'rollup / raw:', 'chart of one channel:',
                      'latest of 2 channels:'):
            self.assertIn(words, report)

    def test_ten_thousand_ingest_writes_leave_the_activity_log_alone(self):
        revision, rows = audit.revision(), AuditLog.objects.count()
        call_command('bench_sensors', '--channels', '1', '--days', '7', '--interval', '60',
                     '--confirm-database', connection.settings_dict['NAME'], stdout=StringIO())
        self.assertEqual((audit.revision(), AuditLog.objects.count()), (revision, rows))
