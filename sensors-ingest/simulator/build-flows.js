// Writes flows.json (the Node-RED field simulator, owner amendment A2) from the function bodies below, so the code is
// reviewed as JavaScript and the flows file stays generated. No credential is in the flows: the broker login comes
// from start.sh (flows_cred.json written from SIM_MQTT_USER and the secret file at container start).
//   docker run --rm -v "$PWD:/sim" -w /sim node:22-bookworm-slim node build-flows.js
'use strict';
const fs = require('fs');

// Shared by the three devices: a 1 s signal with slow sine, linear drift, gaussian noise, and plateaus (the first 2
// of every 10 minutes hold the last value exactly, so the ingest's deadband suppresses them).
const SIGNAL = `
const now = Date.now();
const st = context.get('st') || { seq: 0, t0: now, last: {}, total: 0 };
st.seq += 1;
const flat = new Date(now).getUTCMinutes() % 10 < 2;
function gauss() {
  let u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}
function sig(key, base, amp, periodMin, sd, driftPerHour) {
  if (flat && st.last[key] !== undefined) return st.last[key];
  const hours = (now - st.t0) / 3600e3;
  const x = base + amp * Math.sin((2 * Math.PI * now) / (periodMin * 60e3)) + driftPerHour * hours + sd * gauss();
  const r = Math.round(x * 1000) / 1000;
  st.last[key] = r;
  return r;
}
`;

const PLC = SIGNAL + `
// A PLC: one object payload with several tags, ISO time with a +01:00 offset, its own sequence number.
const local = new Date(now + 3600e3).toISOString().replace('Z', '+01:00');
const tag = (v) => ({ value: v, quality: 'good' });
msg.topic = 'sim/plc-1/tags';
msg.payload = {
  ts: local,
  seq: st.seq,
  tags: {
    temp_inlet: tag(sig('temp_inlet', 9.5, 0.4, 30, 0.02, 0.05)),
    temp_outlet: tag(sig('temp_outlet', 10.1, 0.4, 30, 0.02, 0.05)),
    o2_sump: tag(sig('o2_sump', 10.2, 0.8, 20, 0.05, -0.1)),
    ph_sump: tag(sig('ph_sump', 7.35, 0.05, 45, 0.005, 0)),
    flow_main: tag(sig('flow_main', 120, 5, 15, 0.8, 0)),
    pump1_run: { value: true, quality: 'good' },
  },
};
context.set('st', st);
return msg;
`;

const PROBE = SIGNAL + `
// An oxygen probe: an array of items, each with its name, value and epoch-millisecond time.
msg.topic = 'sim/o2-probe-1/data';
const items = [
  { n: 'do', v: sig('do', 9.8, 0.9, 25, 0.04, -0.05), t: now },
  { n: 'temp', v: sig('temp', 9.6, 0.3, 30, 0.02, 0.03), t: now },
  { n: 'sat', v: sig('sat', 96, 6, 25, 0.4, 0), t: now },
];
msg.payload = { seq: st.seq, items };
context.set('st', st);
return msg;
`;

const FLOW = SIGNAL + `
// A flow meter: ISO UTC time (shifted by the clock-skew switch), a sequence, the flow and its running total.
const flowNow = sig('flow', 42, 3, 12, 0.3, 0);
st.total = Math.round((st.total + flowNow / 3600) * 1000) / 1000;
const skew = flow.get('skew_s') || 0;
msg.topic = 'sim/flow-meter-1/state';
msg.payload = { time: new Date(now + skew * 1000).toISOString(), sequence: st.seq, flow_m3h: flowNow, total_m3: st.total };
context.set('st', st);
return msg;
`;

const FAULTS = `
// Field faults on the way to the broker: an outage buffers everything (replayed by the switch board), out-of-order
// holds five PLC messages and sends them reversed, duplicates send every message twice.
if (flow.get('outage')) {
  const b = flow.get('backlog') || [];
  if (b.length < 20000) b.push(msg); else flow.set('backlog_lost', (flow.get('backlog_lost') || 0) + 1);
  flow.set('backlog', b);
  node.status({ fill: 'red', shape: 'ring', text: 'outage: ' + b.length + ' buffered' });
  return null;
}
let out = [msg];
if ((flow.get('ooo_left') || 0) > 0 && msg.topic === 'sim/plc-1/tags') {
  const buf = flow.get('ooo_buf') || [];
  buf.push(msg);
  if (buf.length < 5) { flow.set('ooo_buf', buf); return null; }
  flow.set('ooo_left', 0);
  flow.set('ooo_buf', []);
  out = buf.reverse();
}
if (flow.get('dup')) out = out.flatMap((m) => [m, RED.util.cloneMessage(m)]);
const skew = flow.get('skew_s') || 0;
node.status({ fill: 'green', shape: 'dot', text: (flow.get('dup') ? 'duplicates, ' : '') + (skew ? 'skew ' + skew + ' s' : 'normal') });
return [out];
`;

const SWITCHES = `
// The switch board: each inject node sends its name. Replay and the one-shot faults go straight to the broker.
const now = Date.now();
const iso = (t) => new Date(t).toISOString();
const plc = (ts, seq, o2) => ({ topic: 'sim/plc-1/tags', payload: { ts, seq, tags: { temp_inlet: { value: 9.5 }, o2_sump: { value: o2 } } } });
switch (msg.payload) {
  case 'outage_start':
    flow.set('outage', true);
    return null;
  case 'outage_replay': {
    flow.set('outage', false);
    const b = flow.get('backlog') || [];
    flow.set('backlog', []);
    let i = 0;
    const step = () => {
      const chunk = b.slice(i, i + 100);
      i += 100;
      if (chunk.length) { node.send([chunk]); setTimeout(step, 100); }
    };
    step();
    node.status({ fill: 'blue', shape: 'dot', text: 'replayed ' + b.length });
    return null;
  }
  case 'dup_on': flow.set('dup', true); return null;
  case 'dup_off': flow.set('dup', false); return null;
  case 'ooo': flow.set('ooo_left', 5); flow.set('ooo_buf', []); return null;
  case 'skew_ahead': flow.set('skew_s', 600); return null;
  case 'skew_behind': flow.set('skew_s', -3600); return null;
  case 'skew_off': flow.set('skew_s', 0); return null;
  case 'late':
    // stored by a device during a long outage and sent days later (3 days, and 20 days: a compressed chunk)
    return [[plc(iso(now - 3 * 86400e3), 1, 10.1), plc(iso(now - 20 * 86400e3), 2, 10.3)]];
  case 'garbage': {
    const pad = 'x'.repeat(70 * 1024);
    return [[
      { topic: 'sim/plc-1/tags', payload: '{"ts": 12' },
      { topic: 'sim/plc-1/tags', payload: JSON.stringify({ ts: iso(now), seq: 0, tags: { o2_sump: { value: 'abc' } } }) },
      { topic: 'sim/plc-1/tags', payload: JSON.stringify({ seq: 0, tags: { o2_sump: { value: 10 } } }) },
      { topic: 'sim/plc-1/tags', payload: JSON.stringify({ ts: iso(now), seq: 0, tags: { o2_sump: { value: 'NaN' } } }) },
      { topic: 'sim/plc-1/tags', payload: JSON.stringify({ ts: iso(now), pad }) },
      { topic: 'sim/unknown/device-9', payload: JSON.stringify({ ts: iso(now), v: 1 }) },
    ]];
  }
  default:
    node.warn('unknown switch ' + msg.payload);
    return null;
}
`;


// ---- the farm flow (owner scenario): 40 messages per second over the water devices of the configuration view ----
// Runs in the function node's start-up code: every device publishes on its own timer, like a field transmitter, at
// (devices / 40) seconds plus or minus 15 % jitter, so the farm as a whole sends 40 messages per second. Each message
// carries all the device's water values (7-8 for the demo sensors). The device list (topic, payload format, channels)
// comes from FARM_DEVICES_FILE, written from the configuration view by farm-config.sh: nothing is hard-coded.
const FARM_INIT = `
const devices = global.get('farm');
if (!Array.isArray(devices) || devices.length === 0) {
  node.status({ fill: 'grey', shape: 'ring', text: 'no farm device list (FARM_DEVICES_FILE)' });
  return;
}
const period = (devices.length / 40) * 1000;
const seq = {}, timers = [];
let sent = 0;
function gauss() { let u = 0, v = 0; while (u === 0) u = Math.random(); while (v === 0) v = Math.random(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }
function hash(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h; }
// The water of one tank at time t, from a model, never from a table:
// - temperature follows the day (warmest mid-afternoon);
// - feeding at 08, 12 and 16 local time: oxygen falls and recovers (about 45 min), CO2 and turbidity rise with it, pH
//   follows CO2 (carbonate equilibrium: about -0.25 per tenfold CO2), TAN peaks later and slower, nitrite later still;
// - nitrate rises slowly through the week and drops at the Monday water exchange; alkalinity is used up by
//   nitrification over the same week;
// - saturation is worked out from the oxygen and the temperature.
function water(code, t) {
  const h = hash(code), u = (h % 1000) / 1000;
  const local = new Date(t + 3600e3);
  const hour = local.getUTCHours() + local.getUTCMinutes() / 60 + local.getUTCSeconds() / 3600;
  const dayStart = t - hour * 3600e3;
  const feed = (tau) => [8, 12, 16].reduce((a, fh) => {
    const dt = (t - (dayStart + fh * 3600e3)) / 60e3;
    return dt >= 0 ? a + Math.exp(-dt / tau) : a;
  }, 0);
  const f45 = feed(45), f120 = feed(120), f360 = feed(360);
  const days = ((local.getUTCDay() + 6) % 7) + hour / 24; // since Monday 00:00
  const T = 8 + 6 * u + 0.6 * Math.sin((2 * Math.PI * (hour - 9)) / 24) + 0.03 * gauss();
  const O2 = 9.2 + 1.5 * u - 1.6 * f45 + 0.2 * Math.sin((2 * Math.PI * (hour - 14)) / 24) + 0.04 * gauss();
  const co2base = 7 + 5 * u;
  const CO2 = co2base + 3.5 * f45 + 0.15 * gauss();
  const solubility = 14.62 - 0.3898 * T + 0.006969 * T * T - 0.00005897 * T * T * T;
  return {
    temperature_c: [T, 1],
    oxygen_mg_l: [O2, 2],
    oxygen_saturation_pct: [(100 * O2) / solubility, 1],
    ph: [7.05 + 0.4 * u - 0.25 * Math.log10(CO2 / co2base) + 0.008 * gauss(), 2],
    co2_mg_l: [CO2, 1],
    alkalinity_mg_l: [140 - 40 * u - 4 * days + 0.8 * gauss(), 0],
    tan_mg_l: [0.15 + 0.4 * u + 0.5 * f120 + 0.01 * gauss(), 3],
    nitrite_n_mg_l: [0.02 + 0.08 * u + 0.06 * f360 + 0.002 * gauss(), 3],
    nitrate_n_mg_l: [12 + 20 * u + 4 * days + 0.3 * gauss(), 1],
    tgp_pct: [100 + 2 * u + 0.6 * Math.sin((2 * Math.PI * hour) / 6) + 0.08 * gauss(), 1],
    salinity_ppt: [(h % 5 === 0 ? 31 + 3 * u : 0.3 + u) + 0.02 * gauss(), 1],
    turbidity_ntu: [0.6 + 1.5 * u + 1.4 * f45 + 0.06 * gauss(), 1],
  };
}
function setp(obj, path, val) {
  const parts = path.split('/').slice(1).map((s) => s.replace(/~1/g, '/').replace(/~0/g, '~'));
  let o = obj;
  for (let k = 0; k < parts.length - 1; k++) { o[parts[k]] = o[parts[k]] || {}; o = o[parts[k]]; }
  o[parts[parts.length - 1]] = val;
}
function packet(d) {
  const now = Date.now();
  seq[d.device_code] = (seq[d.device_code] || 0) + 1;
  const w = water(d.device_code, now);
  const values = {};
  for (const ch of d.channels) {
    const m = w[ch.quantity];
    if (!m) continue;
    let x = Math.round(m[0] * Math.pow(10, m[1])) / Math.pow(10, m[1]);
    if (ch.range_min !== null && ch.range_min !== undefined) x = Math.min(Math.max(x, ch.range_min), ch.range_max);
    values[ch.quantity] = x;
  }
  const time = d.time_unit === 'iso8601' ? new Date(now).toISOString() : d.time_unit === 'epoch_s' ? now / 1000 : now;
  let payload;
  if (d.shape === 'array') {
    const items = d.channels.filter((ch) => values[ch.quantity] !== undefined)
      .map((ch) => ({ [d.name_key]: ch.item_name, [d.value_key]: values[ch.quantity] }));
    if (d.items_path) {
      payload = {};
      setp(payload, d.items_path, items);
      if (d.time_path) setp(payload, d.time_path, time);
      if (d.seq_path) setp(payload, d.seq_path, seq[d.device_code]);
    } else {
      payload = items;
      if (d.time_path) for (const it of items) setp(it, d.time_path, time);
    }
  } else {
    payload = {};
    if (d.time_path) setp(payload, d.time_path, time);
    if (d.seq_path) setp(payload, d.seq_path, seq[d.device_code]);
    for (const ch of d.channels) if (values[ch.quantity] !== undefined) setp(payload, ch.value_path, values[ch.quantity]);
  }
  return { topic: d.topic, payload: JSON.stringify(payload) };
}
devices.forEach((d) => {
  const tick = () => {
    if (flow.get('farm_on') !== false) {
      node.send(packet(d));
      sent += 1;
      if (sent % 200 === 0) node.status({ fill: 'green', shape: 'dot', text: devices.length + ' devices, ' + sent + ' sent' });
    }
    timers[devices.indexOf(d)] = setTimeout(tick, period * (0.85 + 0.3 * Math.random()));
  };
  timers.push(setTimeout(tick, Math.random() * period));
});
context.set('timers', timers);
node.status({ fill: 'green', shape: 'dot', text: devices.length + ' devices, every ' + (period / 1000).toFixed(2) + ' s each' });
`;

const FARM_FINAL = `
for (const t of context.get('timers') || []) clearTimeout(t);
`;

const FARM_SWITCH = `
flow.set('farm_on', msg.payload === 'farm_on');
node.status({ fill: msg.payload === 'farm_on' ? 'green' : 'grey', shape: 'dot', text: msg.payload });
return null;
`;
let y = 60;
const at = () => (y += 60);
const fn = (id, name, func, x, wires) => ({
  id, type: 'function', z: 'tab_sim', name, func: func.trim(), outputs: 1, timeout: 0, noerr: 0,
  initialize: '', finalize: '', libs: [], x, y: at(), wires: [wires],
});
const inject = (id, name, payload, wires) => ({
  id, type: 'inject', z: 'tab_sim', name, props: [{ p: 'payload' }], repeat: '', crontab: '', once: false,
  onceDelay: 0.1, topic: '', payload, payloadType: 'str', x: 160, y: at(), wires: [wires],
});

const nodes = [
  { id: 'tab_sim', type: 'tab', label: 'Field simulator', disabled: false,
    info: 'Field devices for the Sensors ingest (sensors-ingest/simulator). Built by build-flows.js; do not edit here.' },
  { id: 'sim_broker', type: 'mqtt-broker', name: 'Sensors broker', broker: '${SIM_MQTT_HOST}', port: '1883',
    clientid: 'sensors-simulator', autoConnect: true, usetls: false, protocolVersion: '4', keepalive: '30',
    cleansession: true, autoUnsubscribe: true, birthTopic: '', birthQos: '0', birthRetain: 'false', birthPayload: '',
    birthMsg: {}, closeTopic: '', closeQos: '0', closeRetain: 'false', closePayload: '', closeMsg: {}, willTopic: '',
    willQos: '0', willRetain: 'false', willPayload: '', willMsg: {}, userProps: '', sessionExpiry: '' },
  { id: 'tick', type: 'inject', z: 'tab_sim', name: 'every second', props: [], repeat: '1', crontab: '', once: true,
    onceDelay: 1, topic: '', x: 140, y: at(), wires: [['dev_plc', 'dev_probe', 'dev_flow']] },
  fn('dev_plc', 'PLC (object of tags)', PLC, 380, ['faults']),
  fn('dev_probe', 'O2 probe (array, epoch ms)', PROBE, 380, ['faults']),
  fn('dev_flow', 'Flow meter (ISO time)', FLOW, 380, ['faults']),
  fn('faults', 'field faults', FAULTS, 620, ['mqtt_out']),
  { id: 'mqtt_out', type: 'mqtt out', z: 'tab_sim', name: 'to broker (QoS 1)', topic: '', qos: '1', retain: 'false',
    respTopic: '', contentType: '', userProps: '', correl: '', expiry: '', broker: 'sim_broker', x: 860, y: at(), wires: [] },
  inject('sw_outage_start', 'outage: start', 'outage_start', ['switches']),
  inject('sw_outage_replay', 'outage: end and replay backlog', 'outage_replay', ['switches']),
  inject('sw_dup_on', 'duplicates on', 'dup_on', ['switches']),
  inject('sw_dup_off', 'duplicates off', 'dup_off', ['switches']),
  inject('sw_ooo', 'out of order (next 5 PLC)', 'ooo', ['switches']),
  inject('sw_late', 'late messages (3 and 20 days)', 'late', ['switches']),
  inject('sw_garbage', 'garbage payloads', 'garbage', ['switches']),
  inject('sw_skew_ahead', 'clock skew: flow meter +10 min', 'skew_ahead', ['switches']),
  inject('sw_skew_behind', 'clock skew: flow meter -1 h', 'skew_behind', ['switches']),
  inject('sw_skew_off', 'clock skew: off', 'skew_off', ['switches']),
  fn('switches', 'switch board', SWITCHES, 620, ['mqtt_out']),
  // the farm tab: its own broker connection and credential (a real field publisher: QoS 1, persistent session)
  { id: 'farm_broker', type: 'mqtt-broker', name: 'Farm broker (own credential)', broker: '${SIM_MQTT_HOST}', port: '1883',
    clientid: 'demo-simulator-farm', autoConnect: true, usetls: false, protocolVersion: '4', keepalive: '30',
    cleansession: false, autoUnsubscribe: true, birthTopic: '', birthQos: '0', birthRetain: 'false', birthPayload: '',
    birthMsg: {}, closeTopic: '', closeQos: '0', closeRetain: 'false', closePayload: '', closeMsg: {}, willTopic: '',
    willQos: '0', willRetain: 'false', willPayload: '', willMsg: {}, userProps: '', sessionExpiry: '' },
  { id: 'tab_farm', type: 'tab', label: 'Farm', disabled: false,
    info: 'Water devices of the configuration view (FARM_DEVICES_FILE from farm-config.sh), each on its own jittered timer, 40 messages per second in total.' },
  { id: 'farm_devices', type: 'function', z: 'tab_farm', name: 'farm devices (own timers)', func: 'return null;',
    outputs: 1, timeout: 0, noerr: 0, initialize: FARM_INIT.trim(), finalize: FARM_FINAL.trim(), libs: [], x: 400,
    y: 60, wires: [['farm_out']] },
  { id: 'farm_out', type: 'mqtt out', z: 'tab_farm', name: 'to broker (QoS 1)', topic: '', qos: '1', retain: 'false',
    respTopic: '', contentType: '', userProps: '', correl: '', expiry: '', broker: 'farm_broker', x: 680, y: 60, wires: [] },
  { ...inject('sw_farm_on', 'farm on', 'farm_on', ['farm_switch']), z: 'tab_farm', y: 140 },
  { ...inject('sw_farm_off', 'farm off', 'farm_off', ['farm_switch']), z: 'tab_farm', y: 200 },
  { ...fn('farm_switch', 'farm switch', FARM_SWITCH, 400, []), z: 'tab_farm', y: 170, wires: [[]] },
];
fs.writeFileSync(__dirname + '/flows.json', JSON.stringify(nodes, null, 2) + '\n');
console.log('flows.json: ' + nodes.length + ' nodes');
