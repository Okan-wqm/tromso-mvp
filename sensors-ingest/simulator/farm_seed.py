"""A stand-in for the devices the Django side creates for the live run, for the farm check only: 40 devices
(farm/<code>), each with 7 or 8 water channels so that every measured parameter of farm/water/parameters.py MEASURED
appears on many devices; half the devices publish an object payload, half an array. Writes SQL to stdout.
The farm flow itself never reads this: it reads whatever devices the configuration view holds.
Run: python -I farm_seed.py > seed.sql"""
CODES = ['temperature_c', 'oxygen_mg_l', 'oxygen_saturation_pct', 'ph', 'alkalinity_mg_l', 'co2_mg_l', 'tan_mg_l',
         'nitrite_n_mg_l', 'nitrate_n_mg_l', 'tgp_pct', 'salinity_ppt', 'turbidity_ntu']
# deadband, heartbeat, reduction: sensors/quantities.py WATER_DEFAULTS
DEFAULTS = {'temperature_c': (0.1, 60, 'all'), 'oxygen_mg_l': (0.1, 300, 'all'),
            'oxygen_saturation_pct': (1, 300, 'all'), 'ph': (0.02, 300, 'deadband'),
            'alkalinity_mg_l': (1, 3600, 'deadband'), 'co2_mg_l': (0.5, 300, 'deadband'),
            'tan_mg_l': (0.01, 900, 'deadband'), 'nitrite_n_mg_l': (0.01, 900, 'deadband'),
            'nitrate_n_mg_l': (0.5, 900, 'deadband'), 'tgp_pct': (0.5, 300, 'deadband'),
            'salinity_ppt': (0.2, 600, 'deadband'), 'turbidity_ntu': (1, 600, 'deadband')}
UNITS = {'temperature_c': 'C', 'oxygen_mg_l': 'mg/L', 'oxygen_saturation_pct': '%', 'ph': 'pH',
         'alkalinity_mg_l': 'mg/L', 'co2_mg_l': 'mg/L', 'tan_mg_l': 'mg/L', 'nitrite_n_mg_l': 'mg/L',
         'nitrate_n_mg_l': 'mg/L', 'tgp_pct': '%', 'salinity_ppt': 'ppt', 'turbidity_ntu': 'NTU'}
A = "now(), now(), 1, false"
out = [r'\set ON_ERROR_STOP on', 'BEGIN;',
       "INSERT INTO sites (id, created_at, updated_at, version, is_deleted, name, code, organisation_number, type, "
       "status, is_active, description, street, city, state, postal_code, country, region, timezone, site_manager, "
       "contact_email, contact_phone, notes, lice_area, production_form) VALUES ('00000000-0000-0000-0000-00000000fa01',"
       " %s, 'Farm check site', 'FARMCHECK', '', 'land_based', 'active', true, '', '', '', '', '', 'NO', '',"
       " 'Europe/Oslo', '', '', '', '', '', '');" % A,
       "INSERT INTO sensors_connection (id, created_at, updated_at, version, is_deleted, name, host, port, use_tls, "
       "username, secret_file, client_id, keepalive_s, is_active) VALUES ('00000000-0000-0000-0000-00000000fac0', %s, "
       "'Farm broker', 'mosquitto', 1883, false, 'ingest', 'mqtt_ingest', 'sensors-ingest-farm', 30, true);" % A,
       "INSERT INTO sensors_payload_format (id, created_at, updated_at, version, is_deleted, name, encoding, shape, "
       "time_path, time_unit, seq_path, items_path, name_key, value_key) VALUES "
       "('00000000-0000-0000-0000-00000000faf0', %s, 'Farm object', 'json', 'object', '/time', 'iso8601', '/seq', "
       "'', '', ''), ('00000000-0000-0000-0000-00000000faf1', %s, 'Farm array', 'json', 'array', '/t', 'epoch_ms', "
       "'/seq', '/values', 'p', 'v');" % (A, A)]
for k in range(40):
    dev = '00000000-0000-0000-00fa-%012x' % k
    code = 'TANK-%02d' % k if k < 32 else 'SYSTEM-%02d' % (k - 32)
    array = k % 2
    out.append("INSERT INTO sensors_device (id, created_at, updated_at, version, is_deleted, code, name, topic, "
               "expected_interval_s, manufacturer, model, note, is_active, connection_id, site_id, payload_format_id) "
               "VALUES ('%s', %s, '%s', '%s', 'farm/%s', 1, '', '', '', true, '00000000-0000-0000-0000-00000000fac0', "
               "'00000000-0000-0000-0000-00000000fa01', '00000000-0000-0000-0000-00000000faf%d');"
               % (dev, A, code, code, code.lower(), array))
    for j in range(7 + k % 2):
        q = CODES[(k * 5 + j) % len(CODES)]
        db, hb, red = DEFAULTS[q]
        vp, item = ('', q) if array else ('/w/' + q, '')
        out.append("INSERT INTO sensors_channel (id, created_at, updated_at, version, is_deleted, code, name, quantity, "
                   "unit, unit_factor, unit_offset, value_path, item_name, address_protocol, address, reduction, "
                   "deadband, heartbeat_s, range_min, range_max, state, note, device_id) VALUES (gen_random_uuid(), %s, "
                   "'%s', '%s', '%s', '%s', 1, 0, '%s', '%s', 'mqtt', '{}', '%s', %s, %d, NULL, NULL, 'active', '', "
                   "'%s');" % (A, q.upper().replace('_', '-'), q, q, UNITS[q], vp, item, red,
                               0 if red == 'all' else db, hb, dev))
out.append('COMMIT;')
print('\n'.join(out))
