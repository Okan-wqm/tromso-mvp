// The server's chart data placed on one time axis (frontend/islands/lib/series.ts): the means at their buckets' middles,
// a break in every gap (never bridged), meter and lab samples apart at their own moments, the limits as zones and lines,
// the values worked out drawn hollow. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { flaggedText, formatNumber, keysOf, limitsOf, place, zonesOf, type ChartData } from './series.js';

const WORDS = { sensor: 'Sensor', manual: 'Meter or test kit', lab: 'Laboratory', worked: 'Worked out', warning: 'Warning', critical: 'Critical' };

function chart(extra: Partial<ChartData> = {}): ChartData {
  return {
    head: 'T-01 · Oxygen', title: 'T-01', quantity: { code: 'oxygen_mg_l', label: 'Oxygen (mg/L)', unit: 'mg/L', decimals: 2, water: true },
    tier: 'raw', tier_text: 'stored values', width_s: 60, width_text: '1 min', start: 0, end: 600, zone: 'UTC',
    empty: false, empty_text: 'No sensor values in this time.', simulated: false, simulated_text: '',
    other_text: 'From the backup or the system’s channel', said: [], gap_text: '',
    buckets: { start: [0, 60, 300], end: [60, 120, 360], avg: [9, 9.2, 8.8], min: [8.9, 9.1, 8.7], max: [9.1, 9.3, 8.9],
      n: [1, 1, 1], channel: [1, 1, 1], role: ['primary', 'primary', 'primary'], origin: ['sensor', 'sensor', 'sensor'],
      other: [false, false, false], simulated: [false, false, false] },
    gaps: [[120, 300]], samples: [{ at: 90, value: 9.5, source: 'manual' }, { at: 400, value: 8.1, source: 'lab' }],
    markers: [{ at: 200, kind: 'calibration', channel: 1, label: 'Calibrated' }], notes: [], bands: { critical_low: 6, warning_low: 7 },
    ...extra,
  };
}

test('the means sit at their buckets\' middles and a gap breaks the line, never bridged', () => {
  const placed = place(chart(), WORDS, 'en');
  assert.deepEqual(placed.times, [30, 90, 210, 330, 400]);
  const line = placed.series.find((each) => each.label === 'Sensor');
  assert.deepEqual(line?.values, [9, 9.2, null, 8.8, undefined]);          // 400 s: the lab sample's moment, not a break
  assert.deepEqual(placed.envelope?.low, [8.9, 9.1, null, 8.7, undefined]);
  assert.deepEqual(placed.range, [0, 600]);
  assert.deepEqual(placed.gaps, [[120, 300]]);
});

test('meter and lab samples are drawn apart at their own moments; the keys name only what is drawn', () => {
  const placed = place(chart(), WORDS, 'en');
  assert.deepEqual(placed.series.find((each) => each.label === 'Meter or test kit')?.values, [undefined, 9.5, undefined, undefined, undefined]);
  assert.deepEqual(placed.series.find((each) => each.label === 'Laboratory')?.values, [undefined, undefined, undefined, undefined, 8.1]);
  assert.deepEqual(keysOf(placed).map((key) => key.label), ['Sensor', 'Meter or test kit', 'Laboratory']);
  const bare = place(chart({ samples: [], buckets: { ...chart().buckets, start: [], end: [], avg: [], min: [], max: [] } }), WORDS, 'en');
  assert.deepEqual(bare.series, []);
  assert.equal(bare.envelope, undefined);
});

test('the limits are zones beyond each bound and a line on it, in the page\'s language', () => {
  const bands = { critical_low: 6, warning_low: 7, warning_high: 14 };
  assert.deepEqual(zonesOf(bands), [{ from: null, to: 6, status: 'critical' }, { from: 6, to: 7, status: 'warning' },
    { from: 14, to: null, status: 'warning' }]);
  assert.deepEqual(limitsOf(bands, WORDS, 2, 'nb').map((limit) => limit.label), ['Critical 6,00', 'Warning 7,00', 'Warning 14,00']);
  assert.deepEqual(zonesOf({}), []);
  assert.equal(formatNumber(1520, 0, 'en'), '1,520');
});

test('a value worked out per sample is drawn hollow, and one that could not be is left out', () => {
  const placed = place(chart(), WORDS, 'en', [{ at: 90, value: 0.0012, status: 'ok', note: '' }, { at: 400, value: null, status: 'unevaluated', note: 'no pH' }]);
  const worked = placed.series.find((each) => each.label === 'Worked out');
  assert.equal(worked?.hollow, true);
  assert.deepEqual(worked?.values, [undefined, 0.0012, undefined, undefined, undefined]);
});

test('a bucket from a backup or the system\'s channel is drawn as such, never as the place\'s own probe (review F1)', () => {
  const buckets = { ...chart().buckets, other: [false, true, false], channel: [1, 7, 1], role: ['primary', 'primary', 'primary'],
    origin: ['sensor', 'system_sensor', 'sensor'] };
  const placed = place(chart({ buckets }), WORDS, 'en');
  const other = placed.series.find((each) => each.label === 'From the backup or the system’s channel');
  assert.equal(other?.points, true);
  assert.deepEqual(other?.values, [undefined, 9.2, undefined, undefined, undefined]);
  assert.deepEqual(keysOf(placed).map((key) => key.label), ['Sensor', 'From the backup or the system’s channel',
    'Meter or test kit', 'Laboratory']);
  assert.equal(place(chart(), WORDS, 'en').series.some((each) => each.label.startsWith('From the backup')), false);
});

test('a value past a limit is said in words with its status, its time and its value; an OK one is not', () => {
  const when = (seconds: number): string => `t${seconds}`;
  assert.deepEqual(flaggedText([{ at: 90, value: 5.8, status: 'critical', status_text: 'Critical' },
    { at: 120, value: 6.6, status: 'warning', status_text: 'Warning' }, { at: 150, value: 9, status: 'ok', status_text: 'OK' },
    { at: 180, value: null, status: 'critical', status_text: 'Critical' }], 2, 'mg/L', 'nb', when),
  ['Critical: t90, 5,80 mg/L', 'Warning: t120, 6,60 mg/L']);
});
