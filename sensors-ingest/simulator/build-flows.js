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
];
fs.writeFileSync(__dirname + '/flows.json', JSON.stringify(nodes, null, 2) + '\n');
console.log('flows.json: ' + nodes.length + ' nodes');
