// The simulator's own test (owner amendment A2): listens on sim/# as the ingest would, presses each switch through the
// Node-RED admin API and checks what the "field" sends. Run by simulator/check.sh inside a node-red image container
// (it brings the mqtt library). Env: BROKER, MQTT_USER, MQTT_PASSWORD, NODE_RED (http://host:1880).
'use strict';
const mqtt = require('/usr/src/node-red/node_modules/mqtt');

const BROKER = process.env.BROKER || 'mqtt://mosquitto:1883';
const NODE_RED = process.env.NODE_RED || 'http://node-red:1880';
const seen = [];
let failures = 0;

function ok(cond, what) {
  console.log((cond ? 'PASS: ' : 'FAIL: ') + what);
  if (!cond) failures += 1;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function press(id) {
  const r = await fetch(`${NODE_RED}/inject/${id}`, { method: 'POST' });
  if (r.status !== 200) throw new Error(`inject ${id}: HTTP ${r.status}`);
}
function json(m) {
  try { return JSON.parse(m.payload.toString('utf8')); } catch (e) { return undefined; }
}
function window(fromMs, topic) {
  return seen.filter((m) => m.at >= fromMs && (!topic || m.topic === topic));
}
const PLC = 'sim/plc-1/tags', PROBE = 'sim/o2-probe-1/data', FLOW = 'sim/flow-meter-1/state';

async function main() {
  const c = mqtt.connect(BROKER, {
    username: process.env.MQTT_USER, password: process.env.MQTT_PASSWORD,
    clientId: 'sim-check-' + process.pid, clean: true,
  });
  c.on('message', (topic, payload, packet) => seen.push({ topic, payload, qos: packet.qos, at: Date.now() }));
  await new Promise((res, rej) => { c.on('connect', res); c.on('error', rej); });
  await new Promise((res, rej) => c.subscribe('sim/#', { qos: 1 }, (e) => (e ? rej(e) : res())));

  // 1. the three device shapes, 1 s period, sequence and device time in every message, QoS 1
  let t = Date.now();
  await sleep(6000);
  for (const topic of [PLC, PROBE, FLOW]) {
    const w = window(t, topic);
    ok(w.length >= 4 && w.length <= 8, `${topic}: one message per second (${w.length} in 6 s)`);
    ok(w.every((m) => m.qos === 1), `${topic}: QoS 1`);
  }
  const plc = window(t, PLC).map(json);
  ok(plc.every((p) => p && typeof p.ts === 'string' && /[+-]\d\d:\d\d$|Z$/.test(p.ts) && !isNaN(Date.parse(p.ts))),
    'PLC: ISO time with an offset');
  ok(plc.every((p, i) => i === 0 || p.seq === plc[i - 1].seq + 1), 'PLC: sequence numbers consecutive');
  const tags = plc[0] && plc[0].tags;
  ok(tags && Object.keys(tags).length >= 6 && typeof tags.pump1_run.value === 'boolean' &&
    ['temp_inlet', 'temp_outlet', 'o2_sump', 'ph_sump', 'flow_main'].every((k) => typeof tags[k].value === 'number'),
  'PLC: an object of tags, numbers and a boolean');
  const probe = window(t, PROBE).map(json);
  ok(probe.every((p) => p && Array.isArray(p.items) && p.items.length === 3 &&
    p.items.every((i) => typeof i.n === 'string' && typeof i.v === 'number' && Math.abs(i.t - Date.now()) < 15000)),
  'probe: an array of items with epoch-ms times');
  const flow = window(t, FLOW).map(json);
  ok(flow.every((p) => p && /Z$/.test(p.time) && Number.isInteger(p.sequence) && typeof p.flow_m3h === 'number' &&
    typeof p.total_m3 === 'number'), 'flow meter: ISO UTC time, sequence, flow and a running total');
  ok(flow.every((p, i) => i === 0 || p.total_m3 >= flow[i - 1].total_m3), 'flow meter: total never decreases');
  const minute = new Date().getUTCMinutes() % 10;
  const varies = new Set(plc.map((p) => p.tags.temp_inlet.value)).size > 1;
  ok(minute < 2 ? !varies : varies, `PLC temperature ${minute < 2 ? 'flat (plateau minutes)' : 'noisy'} at minute ${minute} of 10`);

  // 2. duplicates
  await press('sw_dup_on');
  t = Date.now();
  await sleep(4000);
  await press('sw_dup_off');
  const seqs = window(t, PLC).map((m) => json(m).seq);
  ok(seqs.length >= 6 && new Set(seqs).size * 2 <= seqs.length + 1, `duplicates: every PLC message twice (${seqs.length} for ${new Set(seqs).size})`);

  // 3. outage then replay of the backlog
  await sleep(1500);
  const before = window(0, PLC).map(json).pop().seq;
  await press('sw_outage_start');
  t = Date.now();
  await sleep(5000);
  ok(window(t + 500, PLC).length === 0 && window(t + 500, PROBE).length === 0, 'outage: the devices are silent');
  const replayAt = Date.now();
  await press('sw_outage_replay');
  await sleep(4000);
  const back = window(replayAt, PLC).map(json);
  const firstBack = back[0];
  ok(back.length >= 5 && firstBack && firstBack.seq === before + 1, `replay: the backlog comes back from seq ${before + 1} (got ${firstBack && firstBack.seq})`);
  ok(back.every((p, i) => i === 0 || p.seq === back[i - 1].seq + 1), 'replay: no sequence number missing');
  ok(firstBack && replayAt - Date.parse(firstBack.ts) >= 3000, 'replay: backlog messages carry their original (older) device time');

  // 4. out of order
  await press('sw_ooo');
  t = Date.now();
  await sleep(9000);
  const o = window(t, PLC).map((m) => json(m).seq);
  ok(o.some((s, i) => i > 0 && s < o[i - 1]), `out of order: a sequence number goes back (${o.join(',')})`);

  // 5. late, garbage, clock skew
  t = Date.now();
  await press('sw_late');
  await press('sw_garbage');
  await press('sw_skew_ahead');
  await sleep(3000);
  await press('sw_skew_off');
  const late = window(t, PLC).map(json).filter((p) => p && p.ts && Date.now() - Date.parse(p.ts) > 2 * 86400e3);
  ok(late.length >= 2, `late: messages days old (${late.length})`);
  const garbage = window(t).filter((m) => json(m) === undefined);
  ok(garbage.some((m) => m.topic === PLC && m.payload.length < 100), 'garbage: a broken JSON message');
  ok(garbage.concat(window(t)).some((m) => m.payload.length > 64 * 1024), 'garbage: an oversize message (> 64 KiB)');
  ok(window(t).some((m) => m.topic.startsWith('sim/unknown/')), 'garbage: a message on a topic no device has');
  ok(window(t, PLC).map(json).some((p) => p && p.tags && p.tags.o2_sump && p.tags.o2_sump.value === 'abc'), 'garbage: a value that is not a number');
  ok(window(t, PLC).map(json).some((p) => p && p.tags && p.ts === undefined), 'garbage: a message without its time');
  const ahead = window(t, FLOW).map(json).filter((p) => Date.parse(p.time) - Date.now() > 300e3);
  ok(ahead.length >= 1, 'clock skew: the flow meter runs minutes ahead');
  await sleep(2000);
  const after = window(Date.now() - 1500, FLOW).map(json);
  ok(after.length >= 1 && after.every((p) => Math.abs(Date.parse(p.time) - Date.now()) < 5000), 'clock skew off: back to true time');

  c.end();
  console.log(failures ? `${failures} FAILED` : 'ALL PASS');
  process.exit(failures ? 1 : 0);
}
main().catch((e) => { console.log('FAIL: ' + e.message); process.exit(1); });
