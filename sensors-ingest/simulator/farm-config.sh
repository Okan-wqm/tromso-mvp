#!/usr/bin/env bash
# Writes the farm flow's device list from the configuration view `sensors_ingest_config` (what the Sensors pages
# created for the live run: devices, topics, payload formats, water channels), never from hard-coded farm ids:
#   simulator/farm-config.sh DBNAME OUTFILE [NETWORK] [DBHOST]
# Devices of the A2 field simulator (topics sim/...) are left out: they have their own flow. A `+` level in a device
# topic is filled with the device code. The Node-RED container reads OUTFILE at start (FARM_DEVICES_FILE).
set -euo pipefail
DB=$1; OUT=$2; NET=${3:-balik-ciftligi_default}; HOST=${4:-db}
export MSYS_NO_PATHCONV=1
WATER="'temperature_c','oxygen_mg_l','oxygen_saturation_pct','ph','alkalinity_mg_l','co2_mg_l','tan_mg_l',\
'nitrite_n_mg_l','nitrate_n_mg_l','tgp_pct','salinity_ppt','turbidity_ntu'"
docker run --rm --network "$NET" -e PGPASSWORD="${PGPASSWORD:-balik}" timescale/timescaledb:2.32.1-pg17@sha256:2f5e6969faa5cd7f4b075d65f124e30dc50d456b7b807e5c1acd9d51ba7df51c \
  psql -h "$HOST" -U "${PGUSER:-balik}" -d "$DB" -Atq -c "
WITH v AS (SELECT DISTINCT ON (channel_no) * FROM sensors_ingest_config ORDER BY channel_no, valid_from NULLS FIRST)
SELECT coalesce(json_agg(d ORDER BY d.device_code), '[]') FROM (
  SELECT device_code, replace(topic, '+', lower(device_code)) AS topic, shape, time_path, time_unit, seq_path,
         items_path, name_key, value_key,
         json_agg(json_build_object('quantity', quantity, 'value_path', value_path, 'item_name', item_name,
                                    'range_min', range_min, 'range_max', range_max) ORDER BY channel_no) AS channels
  FROM v WHERE quantity IN ($WATER) AND topic NOT LIKE 'sim/%'
  GROUP BY device_code, topic, shape, time_path, time_unit, seq_path, items_path, name_key, value_key) d" > "$OUT"
echo "farm devices: $(grep -o '"device_code"' "$OUT" | wc -l) written to $OUT"
