// SeriesChart's own rules (frontend/islands/ui/SeriesChart.tsx), without a browser: the time axis on the site's clock, the
// value axis that always holds the limits, and the marks over the canvas (a link and a named mark reached with Tab; the
// marks of moments listed beside the chart for the pointer only, with no Tab stop; a 24 px handle the only part that
// takes the pointer). The browser test (islands.browser.test.ts, the gallery's series) holds the drawing. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { renderToStaticMarkup } from 'react-dom/server';

import { clockText, extent, hasValues, Marks, type Overlay } from './series-parts.js';

test('the time axis says a day at the site\'s midnight and a time otherwise, never a day twice', () => {
  const midnight = Date.UTC(2026, 10, 20, 23, 0) / 1000;          // 00:00 on 21.11 in Oslo (UTC+1)
  assert.equal(clockText(midnight, 'Europe/Oslo'), '21.11');
  assert.equal(clockText(midnight + 5400, 'Europe/Oslo'), '01:30');
  assert.equal(clockText(midnight, 'UTC'), '23:00');
});

test('the value axis holds every value, the envelope and every limit, with a margin; nothing to draw is 0 to 1', () => {
  const [low, high] = extent([{ label: 'Sensor', series: 1, values: [7, null, 8, undefined] }],
    { low: [6.8, null, 7.9, undefined], high: [7.2, null, 8.1, undefined], series: 1 },
    [{ value: 6, status: 'critical', label: 'Critical 6' }]);
  assert.ok(low < 6 && high > 8.1, `${low} ${high}`);
  assert.deepEqual(extent([], undefined, []), [0, 1]);
  assert.equal(hasValues([{ label: 'Sensor', series: 1, values: [null, undefined] }]), false);
});

const OVERLAY: Overlay = {
  width: 400, height: 220, top: 10, bottom: 190,
  marks: [{ marker: { at: 60, label: '01:00 · Calibrated', href: '/calibrations/' }, x: 100 },
    { marker: { at: 120, label: '02:00 · O₂ 5.8 mg/L', status: 'critical' }, x: 300 }],
};

test('a mark is a link or a named mark reached with Tab, a handle 24 px across its only target, its label beside it', () => {
  const html = renderToStaticMarkup(<Marks overlay={OVERLAY} />);
  assert.match(html, /<a class="ui-chart-mark" href="\/calibrations\/" aria-label="01:00 · Calibrated">/);
  assert.match(html, /<g class="ui-chart-mark" tabindex="0" role="img" aria-label="02:00 · O₂ 5.8 mg\/L" data-status="critical">/);
  assert.equal(html.match(/<circle class="ui-chart-mark-handle"[^>]* r="12"/g)?.length, 2);
  assert.match(html, /text-anchor="end"[^>]*>02:00 · O₂ 5.8 mg\/L<\/text>/);   // the right half reads to the left
  assert.doesNotMatch(html, /style=/);
});

test('marks whose moments are listed beside the chart are for the pointer only: no link, no Tab stop, hidden from a reader', () => {
  const html = renderToStaticMarkup(<Marks overlay={OVERLAY} listed />);
  assert.doesNotMatch(html, /<a /);
  assert.doesNotMatch(html, /tabindex/);
  assert.equal(html.match(/<g class="ui-chart-mark" aria-hidden="true"/g)?.length, 2);
  assert.match(html, /<title>01:00 · Calibrated<\/title>/);                     // its label on hover
});
