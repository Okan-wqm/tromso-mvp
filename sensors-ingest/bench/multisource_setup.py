"""Writes the many-sources bench setup into a directory (argument 1) for N devices (argument 2):
devices.txt (index password broker format skew outage), passwd/acl for each broker (as sensor_broker_sync would:
one credential per device, its own topic), and seed.sql (two Connection rows, three payload formats, the devices and
their channels). Devices 0..99 publish to broker 2, the rest to broker 1; format = index % 3; every 50th device
(index % 50 == 7) runs its clock 10 minutes ahead; devices 75..99 and N-25..N-1 drop out together and come back with
a backlog. Run: python -I multisource_setup.py OUT N"""
import os
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'spikes'))
from s0f_mosquitto_hash import mosquitto_hash  # noqa: E402

out, n = sys.argv[1], int(sys.argv[2])
os.makedirs(out, exist_ok=True)
ingest_pw = open(os.path.join(out, 'mqtt_ingest')).read().split('\n')[0]
monitor_pw = open(os.path.join(out, 'monitor_pw')).read().split('\n')[0]


def broker(i):
    return 'ms-broker2' if i < 100 else 'ms-broker1'


def outage(i):
    return 75 <= i < 100 or i >= n - 25


devices, passwd, acl = [], {'ms-broker1': [], 'ms-broker2': []}, {'ms-broker1': [], 'ms-broker2': []}
for b in passwd:
    passwd[b] += ['ingest:' + mosquitto_hash(ingest_pw), 'monitor:' + mosquitto_hash(monitor_pw)]
    acl[b] += ['user ingest', 'topic read ms/#', 'user monitor', 'topic read $SYS/#']
for i in range(n):
    pw = secrets.token_urlsafe(24)
    skew = int(i % 50 == 7)
    devices.append('%d %s %s %d %d %d' % (i, pw, broker(i), i % 3, skew, int(outage(i))))
    passwd[broker(i)].append('dev-%d:%s' % (i, mosquitto_hash(pw)))
    acl[broker(i)] += ['user dev-%d' % i, 'topic write ms/dev-%d' % i]
open(os.path.join(out, 'devices.txt'), 'w').write('\n'.join(devices) + '\n')
for b in passwd:
    os.makedirs(os.path.join(out, b), exist_ok=True)
    open(os.path.join(out, b, 'passwd'), 'w').write('\n'.join(passwd[b]) + '\n')
    open(os.path.join(out, b, 'acl'), 'w').write('\n'.join(acl[b]) + '\n')

AUDIT = "now(), now(), 1, false"
sql = [r'\set ON_ERROR_STOP on', 'BEGIN;',
       "INSERT INTO sites (id, created_at, updated_at, version, is_deleted, name, code, organisation_number, type, "
       "status, is_active, description, street, city, state, postal_code, country, region, timezone, site_manager, "
       "contact_email, contact_phone, notes, lice_area, production_form) VALUES "
       "('00000000-0000-0000-0000-0000000005e1', %s, 'Multi-source site', 'MS', '', 'land_based', 'active', true, "
       "'', '', '', '', '', 'NO', '', 'Europe/Oslo', '', '', '', '', '', '');" % AUDIT]
for k in (1, 2):
    sql.append("INSERT INTO sensors_connection (id, created_at, updated_at, version, is_deleted, name, host, port, "
               "use_tls, username, secret_file, client_id, keepalive_s, is_active) VALUES "
               "('00000000-0000-0000-0000-00000000c0%02d', %s, 'Broker %d', 'ms-broker%d', 1883, false, 'ingest', "
               "'mqtt_ingest', 'sensors-ingest-ms-%d', 30, true);" % (k, AUDIT, k, k, k))
formats = [("'/ts'", "'iso8601'", "'/seq'", "'object'", "''", "''", "''"),
           ("'/t'", "'epoch_ms'", "'/seq'", "'array'", "'/items'", "'n'", "'v'"),
           ("'/time'", "'iso8601'", "'/sequence'", "'object'", "''", "''", "''")]
for f, (tp, tu, sp, shape, ip, nk, vk) in enumerate(formats):
    sql.append("INSERT INTO sensors_payload_format (id, created_at, updated_at, version, is_deleted, name, encoding, "
               "shape, time_path, time_unit, seq_path, items_path, name_key, value_key) VALUES "
               "('00000000-0000-0000-0000-0000000f00%02d', %s, 'MS format %d', 'json', %s, %s, %s, %s, %s, %s, %s);"
               % (f, AUDIT, f, shape, tp, tu, sp, ip, nk, vk))
CHANNELS = [  # code, quantity, value_path, item_name, reduction, deadband, heartbeat
    [('TEMP', 'temperature_c', '/tags/temp_inlet/value', '', 'deadband', 0.1, 60),
     ('O2', 'oxygen_mg_l', '/tags/o2_sump/value', '', 'all', 0, 60),
     ('PH', 'ph', '/tags/ph_sump/value', '', 'deadband', 0.02, 300)],
    [('DO', 'oxygen_mg_l', '', 'do', 'all', 0, 60),
     ('TEMP', 'temperature_c', '', 'temp', 'deadband', 0.1, 60),
     ('SAT', 'oxygen_saturation_pct', '', 'sat', 'deadband', 1, 60)],
    [('FLOW', 'flow_m3_h', '/flow_m3h', '', 'deadband', 0.5, 60)],
]
for i in range(n):
    dev = '00000000-0000-0000-0005-%012x' % i
    conn = 2 if i < 100 else 1
    note = ('skew ' if i % 50 == 7 else '') + ('outage' if outage(i) else '')
    sql.append("INSERT INTO sensors_device (id, created_at, updated_at, version, is_deleted, code, name, topic, "
               "expected_interval_s, manufacturer, model, note, is_active, connection_id, site_id, payload_format_id, is_simulated) "
               "VALUES ('%s', %s, 'MS-%d', 'ms %d', 'ms/dev-%d', 1, '', '', '%s', true, "
               "'00000000-0000-0000-0000-00000000c0%02d', '00000000-0000-0000-0000-0000000005e1', "
               "'00000000-0000-0000-0000-0000000f00%02d', false);" % (dev, AUDIT, i, i, i, note, conn, i % 3))
    for code, q, vp, item, red, db, hb in CHANNELS[i % 3]:
        sql.append("INSERT INTO sensors_channel (id, created_at, updated_at, version, is_deleted, code, name, quantity, "
                   "unit, unit_factor, unit_offset, value_path, item_name, address_protocol, address, reduction, "
                   "deadband, heartbeat_s, fresh_heartbeats, range_min, range_max, state, note, device_id) VALUES "
                   "(gen_random_uuid(), %s, '%s', '%s', '%s', '', 1, 0, '%s', '%s', 'mqtt', '{}', '%s', %s, %d, 3, NULL, "
                   "NULL, 'active', '', '%s');" % (AUDIT, code, code, q, vp, item, red, db, hb, dev))
sql.append('COMMIT;')
open(os.path.join(out, 'seed.sql'), 'w').write('\n'.join(sql) + '\n')
print('devices %d' % n)
