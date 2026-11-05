"""Running the sensors: the broker's passwd and acl files written from the rows (manage.py sensor_broker_sync), the ingest
role made able to sign in from a secret file (manage.py sensors_ingest_role), the dead letters page (the payload shown
escaped, as text and hex; a person resolves one, logged), the old dead letters pruned (manage.py sensors_housekeeping), and
the overview's tiles from the runtime tables (the ingest alive or not, devices online, channels stale, dead letters of the
last day), each for the right that may read it."""
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

import psycopg
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from farm.tests.helpers import role

from sensors import credentials
from sensors.models import ChannelState, Credential, DeadLetter, Device, DeviceState, IngestStatus

from . import SensorsCase, make_device


class BrokerSyncTests(SensorsCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.gateway = Credential.objects.create(username='gateway-1', password_hash=credentials.hash_secret('s1'))
        Device.objects.filter(pk=self.device.pk).update(credential=self.gateway)
        Credential.objects.create(username='disabled', password_hash=credentials.hash_secret('s2'), is_enabled=False)
        Credential.objects.create(username='never-had-a-secret')

    def run_sync(self, *extra):
        out = StringIO()
        call_command('sensor_broker_sync', '--passwd', str(self.folder / 'passwd'), '--acl', str(self.folder / 'acl'),
                     *extra, stdout=out)
        return out.getvalue()

    def test_the_files_hold_the_enabled_credentials_and_each_devices_topic(self):
        self.run_sync()
        passwd = (self.folder / 'passwd').read_text()
        self.assertEqual(passwd.splitlines(), [f'gateway-1:{self.gateway.password_hash}'])
        acl = (self.folder / 'acl').read_text()
        self.assertIn('user ingest\ntopic read farm/hall/probe-1\n', acl)
        self.assertIn('user gateway-1\ntopic write farm/hall/probe-1\n', acl)
        self.assertNotIn('disabled', acl + passwd)

    def test_an_inactive_or_deleted_device_loses_its_topic(self):
        self.device.soft_delete(self.user)
        self.run_sync()
        self.assertNotIn('farm/hall/probe-1', (self.folder / 'acl').read_text())

    def test_the_ops_lines_are_kept_first_and_checked(self):
        extra = self.folder / 'ops'
        extra.write_text(f'ingest:{credentials.hash_secret("ingest-secret")}\n')
        self.run_sync('--extra', str(extra))
        self.assertTrue((self.folder / 'passwd').read_text().startswith('ingest:$7$'))
        extra.write_text('not a passwd line\n')
        with self.assertRaises(CommandError):
            self.run_sync('--extra', str(extra))

    def test_check_says_whether_the_files_are_current(self):
        self.run_sync()
        self.run_sync('--check')
        Credential.objects.create(username='gateway-2', password_hash=credentials.hash_secret('s3'))
        with self.assertRaises(CommandError):
            self.run_sync('--check')


class IngestRoleTests(TransactionTestCase):
    """On a role of its own, so the shared `sensors_ingest` of the cluster is never touched by a test."""
    serialized_rollback = True
    ROLE = 'test_sensors_role_probe'

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute(f'DROP ROLE IF EXISTS {self.ROLE}')
            cursor.execute(f'CREATE ROLE {self.ROLE} NOLOGIN')
        self.addCleanup(self.drop)

    def drop(self):
        with connection.cursor() as cursor:
            cursor.execute(f'DROP ROLE IF EXISTS {self.ROLE}')

    def can_login(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolcanlogin FROM pg_roles WHERE rolname = %s', [self.ROLE])
            return cursor.fetchone()[0]

    def test_the_role_signs_in_with_the_files_password_and_is_closed_again(self):
        secret = Path(tempfile.mkdtemp()) / 'pw'
        secret.write_text("it's a s3cret; DROP TABLE x\n")
        call_command('sensors_ingest_role', '--role', self.ROLE, '--password-file', str(secret), stdout=StringIO())
        self.assertTrue(self.can_login())
        params = connection.get_connection_params()
        with psycopg.connect(dbname=params['dbname'], host=params['host'], port=params['port'], user=self.ROLE,
                             password="it's a s3cret; DROP TABLE x") as signed_in:
            self.assertEqual(signed_in.execute('SELECT current_user').fetchone()[0], self.ROLE)
        call_command('sensors_ingest_role', '--role', self.ROLE, '--disable', stdout=StringIO())
        self.assertFalse(self.can_login())

    def test_an_empty_password_file_is_refused(self):
        secret = Path(tempfile.mkdtemp()) / 'pw'
        secret.write_text('\n')
        with self.assertRaises(CommandError):
            call_command('sensors_ingest_role', '--role', self.ROLE, '--password-file', str(secret), stdout=StringIO())
        self.assertFalse(self.can_login())


class DeadLetterTests(SensorsCase):
    def setUp(self):
        self.keeper = get_user_model().objects.create_user('keeper', 'keeper@example.com', 'x')
        self.keeper.groups.add(role('Dead letters', 'view_deadletter', 'change_deadletter'))
        self.client.force_login(self.keeper)
        now = timezone.now()
        self.letter = DeadLetter.objects.create(
            connection_id=self.connection.pk, topic='farm/x', reason='not_json', payload_sha256='a' * 64,
            payload=b'<script>alert(1)</script>\xff', payload_len=27, first_at=now, last_at=now, count=3)

    def test_the_page_shows_the_payload_escaped_as_text_and_hex(self):
        page = self.client.get(reverse('sensors:dead_letters'))
        self.assertNotContains(page, '<script>alert(1)</script>')
        self.assertContains(page, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertContains(page, '3c736372697074')
        self.assertContains(page, 'Not JSON')

    def test_the_reason_filter(self):
        self.assertNotContains(self.client.get(reverse('sensors:dead_letters'), {'reason': 'bad_time'}), 'farm/x')

    def test_a_person_resolves_one_and_it_is_logged(self):
        response = self.client.post(reverse('sensors:dead_letter_resolve', args=[self.letter.pk]))
        self.assertEqual(response.status_code, 302)
        self.letter.refresh_from_db()
        self.assertEqual(self.letter.resolved_by, self.keeper)
        self.assertIsNotNone(self.letter.resolved_at)
        self.assertTrue(AuditLog.objects.filter(entity_id=str(self.letter.pk), action='update').exists())

    def test_reading_without_the_right_to_resolve(self):
        reader = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        reader.groups.add(role('Reader', 'view_deadletter'))
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse('sensors:dead_letters')).status_code, 200)
        self.assertEqual(self.client.post(reverse('sensors:dead_letter_resolve', args=[self.letter.pk])).status_code, 403)

    def test_housekeeping_prunes_the_old_ones_only(self):
        old = timezone.now() - timedelta(days=91)
        DeadLetter.objects.create(connection_id=self.connection.pk, topic='farm/y', reason='bad_time',
                                  payload_sha256='b' * 64, payload=b'x', payload_len=1, first_at=old, last_at=old)
        call_command('sensors_housekeeping', stdout=StringIO())
        self.assertEqual(list(DeadLetter.objects.values_list('topic', flat=True)), ['farm/x'])


class OverviewTests(SensorsCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(self.admin)

    def tiles(self):
        page = self.client.get(reverse('sensors:home'))
        return {str(tile['label']): tile for tile in page.context['state_tiles']}

    def test_an_ingest_without_a_heartbeat_is_said_to_be_down(self):
        self.assertEqual(self.tiles()['Ingest']['text'], 'No heartbeat yet')
        IngestStatus.objects.create(connection_id=self.connection.pk, heartbeat_at=timezone.now(), connected=True)
        self.assertEqual(self.tiles()['Ingest']['text'], 'Alive')
        IngestStatus.objects.filter(pk=self.connection.pk).update(heartbeat_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(self.tiles()['Ingest']['text'], 'Down')

    def test_devices_online_channels_stale_and_dead_letters(self):
        now = timezone.now()
        make_device(self.connection, self.format, self.site, code='PROBE-2')
        DeviceState.objects.create(device_id=self.device.pk, last_message_at=now)
        ChannelState.objects.create(channel_no=self.channel.channel_no, last_value=1, last_value_ts=now - timedelta(hours=1),
                                    last_good_at=now - timedelta(hours=1))
        DeadLetter.objects.create(connection_id=self.connection.pk, topic='farm/x', reason='not_json',
                                  payload_sha256='c' * 64, payload=b'x', payload_len=1, first_at=now, last_at=now)
        tiles = self.tiles()
        self.assertEqual(tiles['Devices online']['count'], '1 / 2')
        self.assertEqual(tiles['Channels without a fresh value']['count'], 1)
        self.assertEqual(tiles['Dead letters, last 24 hours']['count'], 1)

    def test_a_person_without_rights_sees_no_state(self):
        self.client.force_login(get_user_model().objects.create_user('nobody', 'n@example.com', 'x'))
        self.assertEqual(self.client.get(reverse('sensors:home')).context['state_tiles'], [])


class BrokerAuthDirTests(BrokerSyncTests):
    def test_without_paths_the_files_go_to_the_configured_folder(self):
        with self.settings(SENSORS_BROKER_AUTH_DIR=str(self.folder / 'auth')):
            call_command('sensor_broker_sync', stdout=StringIO())
        self.assertTrue((self.folder / 'auth' / 'passwd').read_text().startswith('gateway-1:$7$'))
        self.assertIn('topic write farm/hall/probe-1', (self.folder / 'auth' / 'acl').read_text())


class IngestCounterTests(SensorsCase):
    def test_the_overview_shows_what_the_ingest_dropped_and_what_the_database_refused(self):
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        IngestStatus.objects.create(connection_id=self.connection.pk, heartbeat_at=timezone.now(), connected=True,
                                    qos0_dropped=3, poison_total=2)
        tiles = {str(tile['label']): tile for tile in self.client.get(reverse('sensors:home')).context['state_tiles']}
        self.assertEqual(tiles['QoS 0 messages dropped on a full queue']['count'], 3)
        self.assertEqual(tiles['Messages the database refused']['count'], 2)

    def test_the_writer_gets_zero_counters_by_default(self):
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO sensors_ingest_status (connection_id, heartbeat_at) VALUES (%s, now())',
                           [self.connection.pk])
        status = IngestStatus.objects.get()
        self.assertEqual((status.qos0_dropped, status.poison_total), (0, 0))
