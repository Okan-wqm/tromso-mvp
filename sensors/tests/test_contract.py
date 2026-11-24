"""The contract with the ingest service (sensors/CONTRACT.md): the configuration view and its columns, the contract row,
the quality flags, the epoch a configuration change moves (and the notification it sends), the dead-letter and runtime
tables and the role the service signs in with. Any change here is a change of the contract and fails these tests."""
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone as tz
from pathlib import Path

import psycopg
from django.conf import settings
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from sensors import quality
from sensors.models import (Calibration, Channel, ChannelState, Contract, DeadLetter, Device, DeviceState,
                            IngestStatus, QualityFlag)

from . import SensorsCase, make_channel, make_connection, make_device, make_format, one, rows

VIEW_COLUMNS = [
    'connection_id', 'host', 'port', 'use_tls', 'username', 'secret_file', 'client_id', 'keepalive_s',
    'device_id', 'device_code', 'topic', 'expected_interval_s',
    'encoding', 'shape', 'time_path', 'time_unit', 'seq_path', 'items_path', 'name_key', 'value_key',
    'channel_no', 'channel_code', 'quantity', 'value_path', 'item_name', 'reduction', 'deadband', 'heartbeat_s',
    'range_min', 'range_max', 'channel_state', 'valid_from', 'valid_to', 'a', 'b', 'is_simulated',
]
RUNTIME_TABLES = ('sensors_channel_state', 'sensors_device_state', 'sensors_ingest_status', 'sensors_dead_letter')
CONFIG_TABLES = ('sensors_connection', 'sensors_payload_format', 'sensors_device', 'sensors_channel',
                 'sensors_calibration')
ROLE = 'sensors_ingest'
INGEST = Path(settings.BASE_DIR) / 'sensors-ingest'
# The files of sensors-ingest/ that make a channel in SQL of their own (the fixture of its tests, the seeds of its
# bench, multi-source and end-to-end runs): the scan below must have read them, or it has gone blind.
CHANNEL_FIXTURES = {'tests/common/mod.rs', 'bench/seed.sql', 'bench/multisource_setup.py', 'e2e/seed.sql'}
INSERT = re.compile(r'INSERT\s+INTO\s+(\w+)\s*\(([^()]*)\)', re.IGNORECASE)
# A statement written over several lines of a Rust string (a backslash ends the line) or as Python strings side by
# side is one statement.
CONTINUED = re.compile(r'''\\\r?\n\s*|["']\s*\r?\n\s*["']''')


def ingest_inserts():
    """[(file, table, columns)] of every `INSERT INTO table (columns)` in the ingest's sources, tests, seeds, scripts
    and notes (not its build output)."""
    found = []
    for folder, folders, names in os.walk(INGEST):
        folders[:] = sorted(name for name in folders if name != 'target' and not name.startswith('.'))
        for name in sorted(names):
            path = Path(folder) / name
            if path.suffix not in ('.rs', '.sql', '.py', '.sh', '.md'):
                continue
            text = path.read_text(encoding='utf-8')
            if path.suffix in ('.rs', '.py'):
                text = CONTINUED.sub('', text)
            for table, columns in INSERT.findall(text):
                found.append((path.relative_to(INGEST).as_posix(), table.lower(),
                              [column.strip().strip('\\"') for column in columns.split(',')]))
    return found


def view(channel_no=None):
    sql = 'SELECT * FROM sensors_ingest_config'
    with connection.cursor() as cursor:
        if channel_no is None:
            cursor.execute(sql + ' ORDER BY channel_no, valid_from NULLS FIRST')
        else:
            cursor.execute(sql + ' WHERE channel_no = %s ORDER BY valid_from NULLS FIRST', [channel_no])
        names = [column.name for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


class ViewTests(SensorsCase):
    def test_the_columns_are_the_contract(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT * FROM sensors_ingest_config LIMIT 0')
            self.assertEqual([column.name for column in cursor.description], VIEW_COLUMNS)

    def test_an_uncalibrated_channel_has_one_epoch_from_the_beginning_with_its_unit_conversion(self):
        Channel.objects.filter(pk=self.channel.pk).update(unit_factor=0.1, unit_offset=-2)
        [row] = view(self.channel.channel_no)
        self.assertIsNone(row['valid_from'])                  # from the beginning
        self.assertIsNone(row['valid_to'])
        self.assertAlmostEqual(row['a'], 0.1)
        self.assertAlmostEqual(row['b'], -2)
        self.assertEqual((row['device_id'], row['connection_id'], row['topic'], row['time_unit']),
                         (self.device.pk, self.connection.pk, 'farm/hall/probe-1', 'epoch_ms'))

    def test_calibration_epochs_compose_with_the_unit_conversion_the_first_covering_the_time_before_it(self):
        Channel.objects.filter(pk=self.channel.pk).update(unit_factor=2, unit_offset=1)
        first, second = datetime(2026, 10, 1, tzinfo=tz.utc), datetime(2026, 11, 1, tzinfo=tz.utc)
        Calibration.objects.create(channel=self.channel, valid_from=second, gain=0.5, offset=3)
        Calibration.objects.create(channel=self.channel, valid_from=first, gain=1.1, offset=-0.2)
        rows_ = view(self.channel.channel_no)
        self.assertEqual(len(rows_), 2)
        early, late = rows_
        self.assertEqual((early['valid_from'], early['valid_to']), (None, second))
        self.assertEqual((late['valid_from'], late['valid_to']), (second, None))
        # value = unit_factor * (gain * raw + offset) + unit_offset
        self.assertAlmostEqual(early['a'], 2 * 1.1)
        self.assertAlmostEqual(early['b'], 2 * -0.2 + 1)
        self.assertAlmostEqual(late['a'], 2 * 0.5)
        self.assertAlmostEqual(late['b'], 2 * 3 + 1)

    def test_only_live_active_configuration_reaches_the_service(self):
        maintenance = make_channel(self.device, 'ph', state='maintenance')
        retired = make_channel(self.device, 'salinity_ppt', state='retired')
        deleted = make_channel(self.device, 'tgp_pct')
        deleted.soft_delete(self.user)
        self.assertEqual({row['channel_no'] for row in view()}, {self.channel.channel_no, maintenance.channel_no})
        self.assertEqual(view(maintenance.channel_no)[0]['channel_state'], 'maintenance')
        self.assertFalse(view(retired.channel_no))
        Device.objects.filter(pk=self.device.pk).update(is_active=False)
        self.assertEqual(view(), [])
        Device.objects.filter(pk=self.device.pk).update(is_active=True)
        self.connection.is_active = False
        self.connection.save()
        self.assertEqual(view(), [])
        self.connection.is_active = True
        self.connection.save()
        self.device.soft_delete(self.user)
        self.assertEqual(view(), [])

    def test_a_simulated_device_is_said_so_to_the_ingest(self):
        self.assertEqual({row['is_simulated'] for row in view()}, {False})
        Device.objects.filter(pk=self.device.pk).update(is_simulated=True)
        self.assertEqual({row['is_simulated'] for row in view()}, {True})

    def test_no_credential_reaches_the_view(self):
        self.assertFalse({'password_hash', 'credential_id', 'credential'} & set(VIEW_COLUMNS))


class ContractRowTests(TestCase):
    def test_one_row_with_the_version_and_the_defaults(self):
        contract = Contract.objects.get()
        self.assertEqual((contract.pk, contract.schema_version, contract.future_skew_s, contract.retention_days,
                          contract.late_limit_days), (1, 1, 60, 730, 728))

    def test_a_message_is_refused_as_too_old_two_days_before_the_raw_data_is_dropped(self):
        # The rollups take in late readings up to a day past the limit and never reach the dropped region (sensors
        # migration 0003): the limit stays at least two days inside the retention.
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            Contract.objects.update(late_limit_days=729)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Contract.objects.update(late_limit_days=0)

    def test_a_second_row_is_refused(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            Contract.objects.create(id=2, schema_version=1)


class QualityFlagTests(TestCase):
    def test_the_table_equals_the_python_constants(self):
        stored = [(flag.bit, flag.name, flag.is_bad) for flag in QualityFlag.objects.order_by('bit')]
        self.assertEqual(stored, [(bit, name, bad) for bit, name, bad, _text in quality.FLAGS])

    def test_the_bad_mask_is_240_and_the_bits_are_powers_of_two(self):
        self.assertEqual(quality.BAD_MASK, 240)
        self.assertEqual(quality.ALL_BITS, 255)
        self.assertEqual([bit for bit, *_rest in quality.FLAGS], [1 << number for number in range(8)])
        self.assertTrue(quality.is_bad(quality.OUT_OF_RANGE | quality.HEARTBEAT))
        self.assertFalse(quality.is_bad(quality.LATE | quality.HEARTBEAT | quality.RECEIVE_TIME | quality.CLOCK_SUSPECT))
        self.assertEqual(quality.names(9), ['heartbeat', 'late'])


class EpochTests(SensorsCase):
    def epoch(self):
        return Contract.objects.get().config_epoch

    def test_every_change_of_a_table_the_view_reads_moves_the_epoch(self):
        steps = [
            lambda: make_connection('Sea broker'),
            lambda: make_format('Array format', shape='array', name_key='n', value_key='v'),
            lambda: make_device(self.connection, self.format, self.site, code='PROBE-2'),
            lambda: make_channel(self.device, 'ph'),
            lambda: Calibration.objects.create(channel=self.channel, valid_from=timezone.now()),
            lambda: Channel.objects.filter(pk=self.channel.pk).update(deadband=0.2),
            lambda: Calibration.objects.filter(channel=self.channel).delete(),
        ]
        for step in steps:
            before = self.epoch()
            step()
            self.assertGreater(self.epoch(), before)

    def test_a_statement_moves_it_once_whatever_the_rows(self):
        make_channel(self.device, 'ph')
        before = self.epoch()
        Channel.objects.filter(device=self.device).update(note='x')
        self.assertEqual(self.epoch(), before + 1)

    def test_runtime_writes_do_not_move_it(self):
        before = self.epoch()
        ChannelState.objects.create(channel_no=self.channel.channel_no)
        self.assertEqual(self.epoch(), before)

    def test_triggers_are_on_every_configuration_table(self):
        found = {name for name, in rows("SELECT event_object_table FROM information_schema.triggers "
                                       "WHERE trigger_name = 'trg_sensors_config_changed'")}
        self.assertEqual(found, set(CONFIG_TABLES))


class NotificationTests(TransactionTestCase):
    """A committed configuration change notifies channel `sensors_config` with the new epoch: what the service LISTENs
    on (it also polls every 30 s, so a lost notification only delays it)."""
    serialized_rollback = True

    def test_a_committed_change_notifies_the_new_epoch(self):
        params = connection.get_connection_params()
        params.pop('cursor_factory', None)
        params.pop('context', None)
        listener = psycopg.connect(**{key: value for key, value in params.items()
                                      if key in ('dbname', 'user', 'password', 'host', 'port')}, autocommit=True)
        self.addCleanup(listener.close)
        listener.execute('LISTEN sensors_config')
        make_connection('Notified broker')
        epoch = Contract.objects.get().config_epoch
        received = [notify.payload for notify in listener.notifies(timeout=5, stop_after=1)]
        self.assertEqual(received, [str(epoch)])


class RuntimeTableTests(SensorsCase):
    def test_dead_letters_are_one_row_per_message_counted_and_bounded(self):
        now = timezone.now()
        payload = b'{"t": 1'
        digest = hashlib.sha256(payload).hexdigest()
        fields = dict(connection_id=self.connection.pk, topic='farm/x', reason='not_json', payload_sha256=digest,
                      payload=payload, payload_len=len(payload), first_at=now, last_at=now)
        letter = DeadLetter.objects.create(**fields)
        letter.refresh_from_db()
        self.assertEqual(letter.count, 1)
        self.refused('uq_sensors_dead_letter_message', lambda: DeadLetter.objects.create(**fields))
        self.refused('chk_sensors_dead_letter_reason', lambda: DeadLetter.objects.create(**{**fields, 'reason': 'odd'}))
        self.refused('chk_sensors_dead_letter_hash', lambda: DeadLetter.objects.create(**{**fields, 'payload_sha256': 'x'}))
        self.refused('chk_sensors_dead_letter_payload', lambda: DeadLetter.objects.create(
            **{**fields, 'payload_sha256': 'f' * 64, 'payload': b'x' * 4097, 'payload_len': 4097}))
        self.refused('chk_sensors_dead_letter_times', lambda: DeadLetter.objects.create(
            **{**fields, 'payload_sha256': 'e' * 64, 'last_at': now - timedelta(seconds=1)}))
        DeadLetter.objects.create(**{**fields, 'payload_sha256': 'overflow', 'payload': b''})

    def test_the_writer_gets_its_defaults_from_the_database(self):
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO sensors_channel_state (channel_no) VALUES (%s)', [self.channel.channel_no])
            cursor.execute('INSERT INTO sensors_device_state (device_id) VALUES (%s)', [self.device.pk])
            cursor.execute('INSERT INTO sensors_ingest_status (connection_id, heartbeat_at) VALUES (%s, now())',
                           [self.connection.pk])
        self.assertEqual(ChannelState.objects.get().run_n, 0)
        state = DeviceState.objects.get()
        self.assertEqual((state.accepted_total, state.late_total, state.dead_total, state.ignored_total), (0, 0, 0, 0))
        status = IngestStatus.objects.get()
        self.assertEqual((status.connected, status.queue_depth, status.version), (False, 0, ''))

    def test_the_state_table_is_tuned_for_updates_in_place(self):
        options = one("SELECT reloptions FROM pg_class WHERE relname = 'sensors_channel_state'")
        self.assertIn('fillfactor=70', options)
        self.assertIn('autovacuum_vacuum_scale_factor=0.01', options)
        indexes = {name for name, in rows("SELECT indexname FROM pg_indexes WHERE tablename = 'sensors_channel_state'")}
        self.assertEqual(indexes, {'sensors_channel_state_pkey'})


class RoleTests(TestCase):
    def privilege(self, table, kind):
        return one('SELECT has_table_privilege(%s, %s, %s)', [ROLE, table, kind])

    def test_the_migration_makes_the_role_unable_to_sign_in(self):
        # A role belongs to the whole PostgreSQL cluster, not to one database: where an ingest already runs
        # (`manage.py sensors_ingest_role` gave it a password), the live role can sign in, and that is right. So the
        # migration's own statement is tried on a fresh role name inside this test's transaction.
        from importlib import import_module
        statement = import_module('sensors.migrations.0001_config').GRANTS[0].replace(ROLE, 'sensors_ingest_probe')
        with connection.cursor() as cursor:
            cursor.execute(statement)
        self.assertEqual(one('SELECT rolcanlogin FROM pg_roles WHERE rolname = %s', ['sensors_ingest_probe']), False)

    def test_it_reads_the_contract_and_writes_only_the_runtime_tables(self):
        for table in ('sensors_ingest_config', 'sensors_contract', 'sensors_quality_flag'):
            self.assertTrue(self.privilege(table, 'SELECT'), table)
            self.assertFalse(self.privilege(table, 'INSERT'), table)
            self.assertFalse(self.privilege(table, 'UPDATE'), table)
        for table in RUNTIME_TABLES:
            for kind in ('SELECT', 'INSERT', 'UPDATE'):
                self.assertTrue(self.privilege(table, kind), f'{table} {kind}')
            self.assertFalse(self.privilege(table, 'DELETE'), table)
        for table in (*CONFIG_TABLES, 'sensors_credential', 'auth_user', 'audit_log'):
            self.assertFalse(self.privilege(table, 'SELECT'), table)

    def test_it_holds_no_right_on_any_other_relation(self):
        """Every table and view of the schema, not a list (the data-layering audit, L-14): the role holds exactly the
        rights its migrations grant (sensors 0001, 0002, 0006) and nothing on anything else, so a new table is never
        readable or writable by the ingest unless a migration says so."""
        granted = {'sensors_ingest_config': {'SELECT'}, 'sensors_contract': {'SELECT'},
                   'sensors_quality_flag': {'SELECT'}, 'sensors_reading': {'INSERT'},
                   **{table: {'SELECT', 'INSERT', 'UPDATE'} for table in RUNTIME_TABLES}}
        kinds = ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER')
        relations = [name for name, in rows("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = "
                                            "c.relnamespace WHERE n.nspname = 'public' AND c.relkind IN "
                                            "('r', 'v', 'm', 'p')")]
        held = {name: {kind for kind in kinds if self.privilege(name, kind)} for name in relations}
        self.assertEqual({name: rights for name, rights in held.items() if rights}, granted)


class IngestSqlTests(TestCase):
    """The ingest's tests, bench and end-to-end runs make their configuration in SQL of their own, on the schema these
    migrations make. A column added here that the database does not fill (NOT NULL without a database default: a
    model's `default` is Python's) breaks every such INSERT, and only the ingest's own run would say so (as
    `fresh_heartbeats` of sensors 0010 did). So this suite reads those statements against the schema."""

    def test_every_insert_of_the_ingest_names_the_columns_the_database_does_not_fill(self):
        inserts = ingest_inserts()
        self.assertLessEqual(CHANNEL_FIXTURES, {file for file, table, _columns in inserts if table == 'sensors_channel'})
        tables = {}
        for table in sorted({table for _file, table, _columns in inserts}):
            tables[table] = dict(rows(
                "SELECT column_name, is_nullable = 'NO' AND column_default IS NULL AND is_generated = 'NEVER' "
                "AND is_identity = 'NO' FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s", [table]))
        self.assertLessEqual({'sites', *CONFIG_TABLES, *RUNTIME_TABLES, 'sensors_reading'},
                             {table for table, columns in tables.items() if columns})
        wrong = []
        for file, table, given in inserts:
            columns = tables[table]
            if not columns:                                   # a table of the run's own (a temporary one), not ours
                continue
            left_out = sorted(name for name, needed in columns.items() if needed and name not in given)
            unknown = sorted(name for name in given if name not in columns)
            if left_out:
                wrong.append(f'{file}: INSERT INTO {table} leaves out {", ".join(left_out)} '
                             f'(NOT NULL, no database default)')
            if unknown:
                wrong.append(f'{file}: INSERT INTO {table} names {", ".join(unknown)}, not a column of it')
        self.assertEqual(wrong, [], 'sensors-ingest/ writes these in SQL of its own: change them with the migration, '
                                    'and run sensors-ingest/tests/run.sh')
