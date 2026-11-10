-- The bench configuration (database sensors_bench): 100 devices bench/dev-<i> with five deadband channels each
-- (500 channel states touched per batch), and one device bench/kill-0 with one `all` channel for the broker crash
-- accounting (every acknowledged message must have its row).
\set ON_ERROR_STOP on
BEGIN;
INSERT INTO sites (id, created_at, updated_at, version, is_deleted, name, code, organisation_number, type, status,
  is_active, description, street, city, state, postal_code, country, region, timezone, site_manager, contact_email,
  contact_phone, notes, lice_area, production_form)
VALUES ('00000000-0000-0000-0000-00000000b0b1', now(), now(), 1, false, 'Bench site', 'BENCH', '', 'land_based',
  'active', true, '', '', '', '', '', 'NO', '', 'Europe/Oslo', '', '', '', '', '', '');
INSERT INTO sensors_connection (id, created_at, updated_at, version, is_deleted, name, host, port, use_tls, username,
  secret_file, client_id, keepalive_s, is_active)
VALUES ('00000000-0000-0000-0000-0000000c0b0b', now(), now(), 1, false, 'Bench broker', 'bench-broker', 1883, false,
  'ingest', 'mqtt_ingest', 'sensors-ingest-bench', 30, true);
INSERT INTO sensors_payload_format (id, created_at, updated_at, version, is_deleted, name, encoding, shape, time_path,
  time_unit, seq_path, items_path, name_key, value_key)
VALUES ('00000000-0000-0000-0000-0000000f0b0b', now(), now(), 1, false, 'Bench', 'json', 'object', '/t', 'epoch_ms',
  '/seq', '', '', '');
INSERT INTO sensors_device (id, created_at, updated_at, version, is_deleted, code, name, topic, expected_interval_s,
  manufacturer, model, note, is_active, connection_id, site_id, payload_format_id, is_simulated)
SELECT ('00000000-0000-0000-0001-' || lpad(to_hex(d), 12, '0'))::uuid, now(), now(), 1, false, 'BENCH-' || d, 'bench ' || d,
  'bench/dev-' || d, 1, '', '', '', true, '00000000-0000-0000-0000-0000000c0b0b', '00000000-0000-0000-0000-00000000b0b1',
  '00000000-0000-0000-0000-0000000f0b0b', false
FROM generate_series(0, 99) d;
INSERT INTO sensors_device (id, created_at, updated_at, version, is_deleted, code, name, topic, expected_interval_s,
  manufacturer, model, note, is_active, connection_id, site_id, payload_format_id, is_simulated)
VALUES ('00000000-0000-0000-0002-000000000000', now(), now(), 1, false, 'KILL-0', 'crash accounting', 'bench/kill-0', 1,
  '', '', '', true, '00000000-0000-0000-0000-0000000c0b0b', '00000000-0000-0000-0000-00000000b0b1',
  '00000000-0000-0000-0000-0000000f0b0b', false);
INSERT INTO sensors_channel (id, created_at, updated_at, version, is_deleted, code, name, quantity, unit, unit_factor,
  unit_offset, value_path, item_name, address_protocol, address, reduction, deadband, heartbeat_s, fresh_heartbeats,
  range_min, range_max, state, note, device_id)
SELECT gen_random_uuid(), now(), now(), 1, false, 'C' || k, 'c' || k, 'temperature_c', 'C', 1, 0, '/v/c' || k, '',
  'mqtt', '{}', 'deadband', 0.05, 60, 3, -50, 100, 'active', '', ('00000000-0000-0000-0001-' || lpad(to_hex(d), 12, '0'))::uuid
FROM generate_series(0, 99) d, generate_series(0, 4) k;
INSERT INTO sensors_channel (id, created_at, updated_at, version, is_deleted, code, name, quantity, unit, unit_factor,
  unit_offset, value_path, item_name, address_protocol, address, reduction, deadband, heartbeat_s, fresh_heartbeats,
  range_min, range_max, state, note, device_id)
VALUES (gen_random_uuid(), now(), now(), 1, false, 'K0', 'k0', 'oxygen_mg_l', 'mg/L', 1, 0, '/v/c0', '', 'mqtt', '{}',
  'all', 0, 60, 3, NULL, NULL, 'active', '', '00000000-0000-0000-0002-000000000000');
COMMIT;
