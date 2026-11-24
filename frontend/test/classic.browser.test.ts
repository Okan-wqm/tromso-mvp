// The CLASSIC look (no data-ui: the default until the switch, S8) is not changed by the new look's rules, measured in a real
// browser (Playwright on the machine's own Chrome or Edge; skipped where there is none, never under CI=1), on the product's
// sheets in app_base.html's order and the real templates' markup (frontend/test/pages/overview.html, written by
// manage.py layout_pages; the Production units filter copied from its template and checked against it). It holds what the
// review of ui-foundation (H2) found changed:
//   - a metric card's figure is the readout step in the text face at every width, never cut;
//   - a pressed segment of the classic .ui-seg keeps its look (no border, no outside margin, no new stacking);
//   - the classic look's theme is Fjord when no theme is chosen.
// Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, resolve } from 'node:path';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { policy } from './csp.js';
import { linksOf, mirrors } from './sheets.js';

const SEG = '<div class="ui-seg filter-group" role="group" aria-label="Fish"><a href="#a" aria-pressed="true">With fish</a>'
  + '<a href="#b" aria-pressed="false">Empty</a><a href="#c" aria-pressed="false">All</a></div>';
const TEMPLATE_SEG = ['<div class="ui-seg filter-group" role="group" aria-label="{% trans "Fish" %}">',
  '<a href="{{ button.href }}" aria-pressed="{{ button.pressed|yesno:"true,false" }}">'];

function page(): string {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>classic</title>${linksOf('app_base.html')}</head><body><main class="content" id="content" data-measure="fluid">
<div class="ui-toolbar filter-bar" id="filters">${SEG}</div>
<section id="part-overview">${readFileSync(resolve('frontend/test/pages/overview.html'), 'utf8')}</section></main></body></html>`;
}

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    const headers = { 'Content-Security-Policy': policy() };
    if (url.pathname === '/') {
      response.writeHead(200, { ...headers, 'Content-Type': 'text/html; charset=utf-8' });
      response.end(page());
      return;
    }
    const file = resolve('static', `.${url.pathname}`);
    if ((url.pathname.startsWith('/css/') || url.pathname.startsWith('/fonts/')) && existsSync(file)) {
      response.writeHead(200, { ...headers, 'Content-Type': extname(file) === '.css' ? 'text/css' : 'font/woff2' });
      response.end(readFileSync(file));
      return;
    }
    response.writeHead(404, headers);
    response.end();
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

test('the classic look stays as it was', { skip: skipWithout(BROWSERS) }, async (t) => {
  assert.deepEqual(mirrors('farm/production_units.html', ...TEMPLATE_SEG), [], 'the filter is the template\'s');
  const server = await serve();
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    const tab = await browser.newPage();
    await tab.goto(origin);
    await t.test('a metric card\'s figure is the readout step, 28 px in the text face, never cut, at every width', async () => {
      for (const width of [390, 768, 1024, 1440]) {
        await tab.setViewportSize({ width, height: 900 });
        const figures = await tab.$$eval('[data-metric] .ui-tile-figure', (all) => all.map((figure) => {
          const style = getComputedStyle(figure);
          return { size: style.fontSize, face: style.fontFamily, overflow: style.overflow, cut: style.textOverflow };
        }));
        assert.ok(figures.length >= 8, `${figures.length} figures`);
        for (const figure of figures) {
          assert.equal(figure.size, '28px', `at ${width} px`);
          assert.match(figure.face, /^"?Atkinson Hyperlegible Next/, `at ${width} px`);
          assert.equal(figure.overflow, 'visible');
          assert.equal(figure.cut, 'clip');
        }
      }
    });
    await t.test('a pressed classic .ui-seg segment has no border, no outside margin and no new stacking', async () => {
      const pressed = await tab.$eval('#filters [aria-pressed="true"]', (segment) => {
        const style = getComputedStyle(segment);
        return { border: style.borderTopWidth, left: style.borderLeftWidth, margin: style.marginRight, z: style.zIndex };
      });
      assert.deepEqual(pressed, { border: '0px', left: '0px', margin: '0px', z: 'auto' });
    });
    await t.test('with no theme chosen the classic look is on Fjord (:root: the sign-in page, 500.html, the report)', async () => {
      const canvas = await tab.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--surface-canvas').trim());
      assert.equal(canvas, '#f4f6f8');
    });
    await tab.close();
  } finally {
    await browser.close();
    server.close();
  }
});
