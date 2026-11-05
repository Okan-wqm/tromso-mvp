// The farm flow's check, MQTT side: listens on every device topic of the farm device list (as the ingest would), turns
// the flow off, opens a window, turns it on for SECONDS, turns it off again and drains; checks the rate (40 msg/s),
// that every packet carries all its device's values (7-8 in the farm), a consecutive sequence and a current device
// time, and counts the values sent per parameter code. Phase marks (MARK lines) let farm-check.sh read the database
// before and after the window. Env: BROKER, MQTT_USER, MQTT_PASSWORD, NODE_RED, FARM_FILE, SECONDS.
'use strict';
const mqtt = require('/usr/src/node-red/node_modules/mqtt');
const fs = require('fs');

const devices = JSON.parse(fs.readFileSync(process.env.FARM_FILE, 'utf8'));
const byTopic = new Map(devices.map((d) => [d.topic, d]));
const SECONDS = Number(process.env.SECONDS || 60);
let failures = 0;
const ok = (c, w) => { console.log((c ? 'PASS: ' : 'FAIL: ') + w); if (!c) failures += 1; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function press(id) {
  const r = await fetch(`${process.env.NODE_RED}/inject/${id}`, { method: 'POST' });
  if (r.status !== 200) throw new Error(`inject ${id}: HTTP ${r.status}`);
}
function pointer(obj, path) {
  if (!path) return undefined;
  return path.split('/').slice(1).map((s) => s.replace(/~1/g, '/').replace(/~0/g, '~'))
    .reduce((o, k) => (o === undefined || o === null ? undefined : o[k]), obj);
}
function valuesOf(d, p) {
  const out = [];
  if (d.shape === 'array') {
    const items = d.items_path ? pointer(p, d.items_path) : p;
    for (const ch of d.channels) {
      for (const it of items || []) if (String(it[d.name_key]) === ch.item_name) out.push([ch.quantity, it[d.value_key]]);
    }
  } else {
    for (const ch of d.channels) { const v = pointer(p, ch.value_path); if (v !== undefined) out.push([ch.quantity, v]); }
  }
  return out;
}

async function main() {
  ok(devices.length > 0, `farm device list has ${devices.length} devices`);
  const c = mqtt.connect(process.env.BROKER, { username: process.env.MQTT_USER, password: process.env.MQTT_PASSWORD,
    clientId: 'farm-check-' + require('crypto').randomUUID(), clean: true });
  let counting = false;
  const perQ = {}, perDev = new Map();
  let packets = 0, incomplete = 0, badTime = 0, notNumber = 0;
  c.on('message', (topic, payload) => {
    if (!counting) return;
    const d = byTopic.get(topic);
    if (!d) return;
    let p;
    try { p = JSON.parse(payload.toString('utf8')); } catch (e) { incomplete += 1; return; }
    packets += 1;
    const vals = valuesOf(d, p);
    if (vals.length !== d.channels.length) incomplete += 1;
    for (const [q, v] of vals) {
      if (typeof v !== 'number' || !isFinite(v)) notNumber += 1;
      perQ[q] = perQ[q] || { values: 0, min: Infinity, max: -Infinity };
      perQ[q].values += 1; perQ[q].min = Math.min(perQ[q].min, v); perQ[q].max = Math.max(perQ[q].max, v);
    }
    const t = pointer(p, d.time_path) ?? (d.shape === 'array' ? pointer((pointer(p, d.items_path) || [])[0] || {}, d.time_path) : undefined);
    const ms = d.time_unit === 'iso8601' ? Date.parse(t) : d.time_unit === 'epoch_ms' ? Number(t) : Number(t) * 1000;
    if (!(Math.abs(ms - Date.now()) < 5000)) badTime += 1;
    const seq = pointer(p, d.seq_path);
    const s = perDev.get(topic) || { last: undefined, gaps: 0, n: 0 };
    if (s.last !== undefined && seq !== s.last + 1) s.gaps += 1;
    s.last = seq; s.n += 1; perDev.set(topic, s);
  });
  await new Promise((res, rej) => { c.on('connect', res); c.on('error', rej); });
  await new Promise((res, rej) => c.subscribe(devices.map((d) => d.topic), { qos: 1 }, (e) => (e ? rej(e) : res())));
  await press('sw_farm_off');
  await sleep(4000);
  console.log('MARK before');
  await sleep(3000); // farm-check.sh reads the database now
  counting = true;
  const t0 = Date.now();
  await press('sw_farm_on');
  await sleep(SECONDS * 1000);
  await press('sw_farm_off');
  const window = (Date.now() - t0) / 1000;
  await sleep(4000);
  counting = false;
  console.log('MARK after');
  const rate = packets / window;
  ok(Math.abs(rate - 40) <= 4, `rate ${rate.toFixed(1)} msg/s (40 wanted) over ${window.toFixed(0)} s, ${packets} packets`);
  ok(incomplete === 0, `every packet carries all its device's values (${incomplete} incomplete)`);
  ok(notNumber === 0, `every value a finite number (${notNumber} not)`);
  ok(badTime === 0, `every packet has a current device time (${badTime} off)`);
  const gaps = [...perDev.values()].reduce((a, s) => a + s.gaps, 0);
  ok(gaps === 0, `sequence numbers consecutive on every device (${gaps} gaps)`);
  ok(perDev.size === devices.length, `every device published (${perDev.size} of ${devices.length})`);
  const want = ['temperature_c', 'oxygen_mg_l', 'oxygen_saturation_pct', 'ph', 'alkalinity_mg_l', 'co2_mg_l', 'tan_mg_l',
    'nitrite_n_mg_l', 'nitrate_n_mg_l', 'tgp_pct', 'salinity_ppt', 'turbidity_ntu'];
  const configured = new Set(devices.flatMap((d) => d.channels.map((ch) => ch.quantity)));
  for (const q of want.filter((x) => configured.has(x))) {
    const s = perQ[q];
    ok(s && s.values >= 10, `${q}: ${s ? s.values : 0} values sent, ${s ? s.min.toFixed(3) + '..' + s.max.toFixed(3) : ''}`);
  }
  ok(want.every((q) => configured.has(q)), `every measured parameter is configured on some device (missing: ${want.filter((q) => !configured.has(q)).join(',') || 'none'})`);
  console.log('COUNTS ' + JSON.stringify(Object.fromEntries(Object.entries(perQ).map(([q, s]) => [q, s.values]))));
  c.end();
  console.log(failures ? `${failures} FAILED` : 'ALL PASS');
  process.exit(failures ? 1 : 0);
}
main().catch((e) => { console.log('FAIL: ' + e.message); process.exit(1); });
