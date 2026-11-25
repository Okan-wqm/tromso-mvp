// Where the new look's red strip leads, in a real browser (Playwright on the machine's own Chrome or Edge; skipped where
// there is none, never in CI). The owner's report of 2026-11-24: the strip was red from the units' water, no alarm was
// open (the alarm engine was not running) and the strip led to the Alarms page, which was empty. The strip is what the
// server prints beside the wall of twenty cards (frontend/test/pages/strip-units.html and strip-split.html, rendered by
// Django through core.ui.alarms_item from the rungs of the cards of wall-small-en.html: core/layout_pages.py); its links
// are followed to what the server serves there: the wall for Monitoring. It holds:
//   - a red strip with no open alarm leads to Monitoring, where every unit it counts is listed on its rung;
//   - with an open alarm too, the item has one link per page, each with its own name: the alarms to the Alarms page,
//     the units to Monitoring.
// Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { join, resolve } from 'node:path';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { linksOf } from './sheets.js';

const PAGES = resolve('frontend/test/pages');
const CSS = resolve('static/css');
const part = (name: string): string => readFileSync(join(PAGES, name), 'utf8');
const hrefOf = (html: string, marker: string): string => {
  const found = new RegExp(`href="([^"]+)"[^>]*${marker}`).exec(html);
  assert.ok(found?.[1], `no link with ${marker}`);
  return found[1];
};

/** A page of the new look with the strip in its top bar (the sheets app_base.html links). */
function stripPage(name: string): string {
  return `<!doctype html><html lang="en" data-theme="industry" data-ui="next"><head><meta charset="utf-8"><title>strip</title>
${linksOf('app_base.html')}</head><body><header class="topbar ui-topbar"><div class="ui-strip" role="group" aria-label="Status">${part(`${name}.html`)}</div></header></body></html>`;
}

/** What the server serves at Monitoring's address: the wall of cards, and at the Alarms page's: its heading. */
function serve(monitor: string, alarms: string): Promise<Server> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    const html = (body: string) => void response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(body);
    if (url.pathname === '/strip-units' || url.pathname === '/strip-split') return html(stripPage(url.pathname.slice(1)));
    if (url.pathname === monitor) {
      return html(`<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Monitoring</title></head><body><main>
<h1>Monitoring</h1><div class="monitor-grid">${part('wall-small-en.html')}</div></main></body></html>`);
    }
    if (url.pathname === alarms) return html('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Alarms</title></head><body><h1>Alarms</h1></body></html>');
    const file = join(CSS, url.pathname.slice('/css/'.length));
    if (url.pathname.startsWith('/css/') && file.startsWith(CSS) && existsSync(file)) {
      return void response.writeHead(200, { 'Content-Type': 'text/css' }).end(readFileSync(file));
    }
    response.writeHead(404).end();
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

/** {rung: count} the strip's words say ("2 units critical · 1 unit with a warning"). */
function counted(text: string): Record<string, number> {
  const words: [string, RegExp][] = [['critical', /(\d+) units? critical/], ['warning', /(\d+) units? with a warning/],
    ['blind', /(\d+) units? with no recent data/], ['unjudged', /(\d+) units? with no limit/]];
  return Object.fromEntries(words.map(([rung, pattern]) => [rung, Number(pattern.exec(text)?.[1] ?? 0)]));
}

test('the red strip leads to the page that lists what it counts', { skip: skipWithout(BROWSERS) }, async (t) => {
  const units = part('strip-units.html');
  const monitor = hrefOf(units, 'data-strip="alarms"');
  const alarms = hrefOf(part('strip-split.html'), 'data-strip-part="alarms"');
  assert.notEqual(monitor, alarms);
  const server = await serve(monitor, alarms);
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  const open = async (name: string) => {
    const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await tab.goto(`${origin}/${name}`);
    return tab;
  };
  try {
    await t.test('no open alarm: the red strip leads to Monitoring, which lists every unit it counts on its rung', async () => {
      const tab = await open('strip-units');
      const item = tab.locator('a[data-strip="alarms"][data-status="critical"]');
      assert.ok(await item.isVisible(), 'the red strip is drawn');
      const said = counted((await item.textContent()) ?? '');
      assert.ok((said.critical ?? 0) >= 1, 'the strip counts a critical unit');
      await Promise.all([tab.waitForURL(`${origin}${monitor}`), item.click()]);
      for (const [rung, count] of Object.entries(said)) {
        assert.equal(await tab.locator(`article.monitor-card[data-state="${rung}"]`).count(), count, `${rung} units listed`);
      }
      await tab.close();
    });
    await t.test('an open alarm too: one link each, the alarms to the Alarms page, the units to Monitoring', async () => {
      const tab = await open('strip-split');
      const item = tab.locator('[data-strip="alarms"][data-status="critical"]');
      assert.equal(await item.locator('a').count(), 2);
      const alarm = tab.getByRole('link', { name: '1 open alarm', exact: true });
      const unit = tab.getByRole('link', { name: /units? critical/ });
      assert.equal(await alarm.getAttribute('href'), alarms);
      assert.equal(await unit.getAttribute('href'), monitor);
      await Promise.all([tab.waitForURL(`${origin}${monitor}`), unit.click()]);
      assert.ok((await tab.locator('article.monitor-card[data-state="critical"]').count()) >= 1);
      await tab.goBack();
      await Promise.all([tab.waitForURL(`${origin}${alarms}`), alarm.click()]);
      assert.equal(await tab.textContent('h1'), 'Alarms');
      await tab.close();
    });
  } finally {
    await browser.close();
    server.close();
  }
});
