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
        for words in ('raw rows: 2880', 'hour rollup rows:', 'chart of one channel over the span:',
                      'channels over seven days:', 'replay of seven days hourly:', 'replay page of 2000 frames at one minute:',
                      'diagrams of 2000 frames at one minute:', 'latest of 2 channels:'):
            self.assertIn(words, report)

    def test_ten_thousand_ingest_writes_leave_the_activity_log_alone(self):
        revision, rows = audit.revision(), AuditLog.objects.count()
        call_command('bench_sensors', '--channels', '1', '--days', '7', '--interval', '60',
                     '--confirm-database', connection.settings_dict['NAME'], stdout=StringIO())
        self.assertEqual((audit.revision(), AuditLog.objects.count()), (revision, rows))

    def test_it_never_writes_over_rows_already_there(self):
        # A multi-row insert that meets a row in a compressed chunk would lose the rest silently (TimescaleDB 2.17.2):
        # the command refuses a range that holds rows, unless told to delete them first.
        name = connection.settings_dict['NAME']
        call_command('bench_sensors', '--channels', '1', '--days', '1', '--confirm-database', name, stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('bench_sensors', '--channels', '1', '--days', '1', '--confirm-database', name, stdout=StringIO())
        call_command('bench_sensors', '--channels', '1', '--days', '1', '--confirm-database', name, '--drop',
                     stdout=StringIO())

    def test_measure_only_times_what_is_there_and_writes_nothing(self):
        name = connection.settings_dict['NAME']
        call_command('bench_sensors', '--channels', '1', '--days', '1', '--confirm-database', name, stdout=StringIO())
        out = StringIO()
        call_command('bench_sensors', '--channels', '1', '--days', '1', '--confirm-database', name, '--measure-only',
                     stdout=out)
        self.assertIn('written: 0 rows', out.getvalue())
        self.assertIn('raw rows: 1440', out.getvalue())
