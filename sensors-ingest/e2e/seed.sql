-- The configuration of the end-to-end run (database sensors_e2e, migrated by Django): one broker connection, the
-- three simulator devices with their payload formats and channels, one calibration. What the Sensors pages would
-- create; written as SQL here because the end-to-end run tests the ingest, not the pages.
\set ON_ERROR_STOP on
BEGIN;
INSERT INTO sites (id, created_at, updated_at, version, is_deleted, name, code, organisation_number, type, status,
  is_active, description, street, city, state, postal_code, country, region, timezone, site_manager, contact_email,
  contact_phone, notes, lice_area, production_form)
VALUES ('00000000-0000-0000-0000-00000000e2e1', now(), now(), 1, false, 'E2E hatchery', 'E2E', '', 'land_based',
  'active', true, '', '', '', '', '', 'NO', '', 'Europe/Oslo', '', '', '', '', '', '');

INSERT INTO sensors_connection (id, created_at, updated_at, version, is_deleted, name, host, port, use_tls, username,
  secret_file, client_id, keepalive_s, is_active)
VALUES ('00000000-0000-0000-0000-0000000c0e2e', now(), now(), 1, false, 'Hall broker', 'mosquitto', 1883, false,
  'ingest', 'mqtt_ingest', 'sensors-ingest-e2e', 30, true);

INSERT INTO sensors_payload_format (id, created_at, updated_at, version, is_deleted, name, encoding, shape, time_path,
  time_unit, seq_path, items_path, name_key, value_key) VALUES
('00000000-0000-0000-0000-0000000f0001', now(), now(), 1, false, 'PLC tags', 'json', 'object', '/ts', 'iso8601', '/seq', '', '', ''),
('00000000-0000-0000-0000-0000000f0002', now(), now(), 1, false, 'Probe items', 'json', 'array', '/t', 'epoch_ms', '/seq', '/items', 'n', 'v'),
('00000000-0000-0000-0000-0000000f0003', now(), now(), 1, false, 'Flow meter', 'json', 'object', '/time', 'iso8601', '/sequence', '', '', '');

INSERT INTO sensors_device (id, created_at, updated_at, version, is_deleted, code, name, topic, expected_interval_s,
  manufacturer, model, note, is_active, connection_id, site_id, payload_format_id, is_simulated) VALUES
('00000000-0000-0000-0000-0000000d0001', now(), now(), 1, false, 'PLC-1', 'Hall PLC', 'sim/plc-1/tags', 1, 'Sim', 'PLC', '', true,
  '00000000-0000-0000-0000-0000000c0e2e', '00000000-0000-0000-0000-00000000e2e1', '00000000-0000-0000-0000-0000000f0001', false),
('00000000-0000-0000-0000-0000000d0002', now(), now(), 1, false, 'O2-PROBE-1', 'Sump oxygen probe', 'sim/o2-probe-1/data', 1, 'Sim', 'Probe', '', true,
  '00000000-0000-0000-0000-0000000c0e2e', '00000000-0000-0000-0000-00000000e2e1', '00000000-0000-0000-0000-0000000f0002', false),
('00000000-0000-0000-0000-0000000d0003', now(), now(), 1, false, 'FLOW-1', 'Main flow meter', 'sim/flow-meter-1/state', 1, 'Sim', 'Meter', '', true,
  '00000000-0000-0000-0000-0000000c0e2e', '00000000-0000-0000-0000-00000000e2e1', '00000000-0000-0000-0000-0000000f0003', false);

-- code, device, quantity, unit, value_path, item_name, reduction, deadband, heartbeat, range
INSERT INTO sensors_channel (id, created_at, updated_at, version, is_deleted, code, name, quantity, unit, unit_factor,
  unit_offset, value_path, item_name, address_protocol, address, reduction, deadband, heartbeat_s, fresh_heartbeats,
  range_min, range_max, state, note, device_id)
SELECT gen_random_uuid(), now(), now(), 1, false, c.code, c.code, c.quantity, c.unit, 1, 0, c.value_path, c.item_name,
  'mqtt', '{}', c.reduction, c.deadband, c.heartbeat_s, 3, c.range_min, c.range_max, 'active', '', c.device_id::uuid
FROM (VALUES
  ('TEMP-IN', '00000000-0000-0000-0000-0000000d0001', 'temperature_c', 'C', '/tags/temp_inlet/value', '', 'deadband', 0.1, 60, -2.0, 40.0),
  ('TEMP-OUT', '00000000-0000-0000-0000-0000000d0001', 'temperature_c', 'C', '/tags/temp_outlet/value', '', 'deadband', 0.1, 60, -2.0, 40.0),
  ('O2-SUMP', '00000000-0000-0000-0000-0000000d0001', 'oxygen_mg_l', 'mg/L', '/tags/o2_sump/value', '', 'all', 0.0, 60, 0.0, 30.0),
  ('PH-SUMP', '00000000-0000-0000-0000-0000000d0001', 'ph', 'pH', '/tags/ph_sump/value', '', 'deadband', 0.02, 300, 4.0, 10.0),
  ('FLOW-MAIN', '00000000-0000-0000-0000-0000000d0001', 'flow_m3_h', 'm3/h', '/tags/flow_main/value', '', 'deadband', 2.0, 60, 0.0, 500.0),
  ('DO', '00000000-0000-0000-0000-0000000d0002', 'oxygen_mg_l', 'mg/L', '', 'do', 'all', 0.0, 60, 0.0, 30.0),
  ('TEMP', '00000000-0000-0000-0000-0000000d0002', 'temperature_c', 'C', '', 'temp', 'deadband', 0.1, 60, -2.0, 40.0),
  ('SAT', '00000000-0000-0000-0000-0000000d0002', 'oxygen_saturation_pct', '%', '', 'sat', 'deadband', 1.0, 60, 0.0, 300.0),
  ('FLOW', '00000000-0000-0000-0000-0000000d0003', 'flow_m3_h', 'm3/h', '/flow_m3h', '', 'deadband', 0.5, 60, 0.0, 500.0)
) AS c(code, device_id, quantity, unit, value_path, item_name, reduction, deadband, heartbeat_s, range_min, range_max);

-- the inlet probe was calibrated a day ago: +0.1 C from then on
INSERT INTO sensors_calibration (valid_from, gain, "offset", performed_by, note, created_at, channel_id)
SELECT now() - interval '1 day', 1.0, 0.1, 'e2e', '', now(), id FROM sensors_channel WHERE code = 'TEMP-IN';
COMMIT;
