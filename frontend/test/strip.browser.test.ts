// The new look's status strip in a real browser (Playwright on the machine's own Chrome or Edge; skipped where there is none,
// never under CI=1), with the real frontend/poll.ts and frontend/strip.ts on the template's markup (checked against
// templates/app_base.html), the product's sheets and the server's policy. It holds:
//   - the strip is asked for once the page's scripts have run (poll.ts's start-up gate) and replaced by the answer;
//   - with no answer it says the alarms cannot be read, never "Reading…" for ever and never "no alarms";
//   - after one failed answer it is marked "not updated" (data-poll-stale-after="1"), never an old "No open alarms" unmarked;
//   - it is not asked for while it is not drawn (under 1100 px, data-poll-if-shown), and is once it is;
//   - a rise of its alarms is said in the live region (critical: the assertive one), a first answer and a fall are not.
// The interval is 1 s here instead of the template's 30, so the test does not wait. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, join, resolve } from 'node:path';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { policy } from './csp.js';
import { linksOf, mirrors } from './sheets.js';

const TEMPLATE = ['data-poll-every="30" data-poll-state="loading" data-poll-stale-after="1" data-poll-if-shown data-unread-text="',
  'data-strip-said="ui-strip-said" data-strip-alert="ui-strip-alert">{% include "core/_strip.html" with items=ui_strip %}</div>',
  '<p class="sr-only" id="ui-strip-said" role="status"></p><p class="sr-only" id="ui-strip-alert" role="alert"></p>'];

const item = (status: string, text: string): string => `<a class="ui-strip-item" href="/alarms/" data-strip="alarms"${status ? ` data-status="${status}"` : ''}>${text}</a><span class="ui-strip-item" data-strip="clock">06.11.2026, 10:19 · Europe/Oslo</span>`;

function page(script: string): string {
  return `<!doctype html><html lang="en" data-theme="industry" data-ui="next"><head><meta charset="utf-8"><title>strip</title>
${linksOf('app_base.html')}</head><body><header class="topbar ui-topbar">
<div class="ui-strip" id="strip" role="group" aria-label="Status" data-poll="/fragment/${script}" data-poll-every="1" data-poll-state="loading" data-poll-stale-after="1" data-poll-if-shown data-unread-text="Not updated: the alarms cannot be read" data-strip-said="ui-strip-said" data-strip-alert="ui-strip-alert">${item('', 'Reading the alarms…')}</div>
<p class="sr-only" id="ui-strip-said" role="status"></p><p class="sr-only" id="ui-strip-alert" role="alert"></p></header>
<script type="module" src="/static/js/poll.js"></script><script type="module" src="/static/js/strip.js"></script></body></html>`;
}

// The answers, by script: each request takes the next one (the last one repeats); a number is a failed answer.
const SCRIPTS: Record<string, (string | number)[]> = {
  ok: [item('critical', '1 unit critical')],
  down: [503],
  stale: [item('', 'No open alarms'), 503],
  rise: [item('', 'No open alarms'), item('warning', '1 unit with no recent data'), item('critical', '1 unit critical'), item('', 'No open alarms')],
};

function serve(): Promise<{ server: Server; asked: Record<string, number> }> {
  const asked: Record<string, number> = {};
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    const headers = { 'Content-Security-Policy': policy() };
    if (url.pathname.startsWith('/page/')) {
      response.writeHead(200, { ...headers, 'Content-Type': 'text/html; charset=utf-8' });
      response.end(page(url.pathname.slice('/page/'.length)));
      return;
    }
    if (url.pathname.startsWith('/fragment/')) {
      const name = url.pathname.slice('/fragment/'.length);
      const answers = SCRIPTS[name] ?? [503];
      const answer = answers[Math.min(asked[name] ?? 0, answers.length - 1)];
      asked[name] = (asked[name] ?? 0) + 1;
      if (typeof answer === 'number') {
        response.writeHead(answer, headers);
        response.end();
      } else {
        response.writeHead(200, { ...headers, 'Content-Type': 'text/html; charset=utf-8' });
        response.end(answer);
      }
      return;
    }
    const file = url.pathname.startsWith('/static/') ? resolve(`.${url.pathname}`)
      : url.pathname.startsWith('/css/') || url.pathname.startsWith('/fonts/') ? resolve('static', `.${url.pathname}`) : '';
    if (file && existsSync(file)) {
      response.writeHead(200, { ...headers, 'Content-Type': extname(file) === '.css' ? 'text/css' : extname(file) === '.js' ? 'text/javascript' : 'font/woff2' });
      response.end(readFileSync(file));
    } else {
      response.writeHead(404, headers);
      response.end();
    }
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done({ server, asked })));
}

test('the strip in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  assert.deepEqual(mirrors('app_base.html', ...TEMPLATE), [], 'the markup is the template\'s');
  assert.ok(existsSync(join('static', 'js', 'strip.js')), 'npm run build first (static/js)');
  const { server, asked } = await serve();
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  const open = async (name: string, width = 1440) => {
    const tab = await browser.newPage({ viewport: { width, height: 900 } });
    await tab.goto(`${origin}/page/${name}`);
    return tab;
  };
  try {
    await t.test('asked for after the gate and replaced by the answer', async () => {
      const tab = await open('ok');
      await tab.waitForSelector('#strip[data-poll-state="live"]');
      assert.equal((await tab.textContent('[data-strip="alarms"]'))?.trim(), '1 unit critical');
      assert.equal(await tab.getAttribute('[data-strip="alarms"]', 'data-status'), 'critical');
      assert.equal((await tab.textContent('#ui-strip-alert'))?.trim(), '');         // a first answer is not said
      await tab.close();
    });
    await t.test('no answer: "not updated" in words, the alarms item never left saying "Reading…"', async () => {
      const tab = await open('down');
      await tab.waitForSelector('#strip[data-poll-state="unread"]');
      assert.equal(await tab.evaluate(() => getComputedStyle(document.querySelector('#strip') as Element, '::before').content),
        '"Not updated: the alarms cannot be read"');
      assert.equal(await tab.locator('[data-strip="alarms"]').isVisible(), false);
      await tab.close();
    });
    await t.test('one failed answer after "No open alarms": marked not updated at once', async () => {
      const tab = await open('stale');
      await tab.waitForSelector('#strip[data-poll-state="live"]');
      await tab.waitForSelector('#strip[data-poll-state="stale"]', { timeout: 5000 });
      assert.equal(await tab.evaluate(() => getComputedStyle(document.querySelector('#strip') as Element, '::before').content),
        '"Not updated: the alarms cannot be read"');
      await tab.close();
    });
    await t.test('not asked for while it is not drawn (under 1100 px), asked for once it is', async () => {
      const before = asked.ok ?? 0;
      const tab = await open('ok', 1024);
      await tab.waitForTimeout(2500);
      assert.equal(asked.ok ?? 0, before, 'not asked while hidden');
      await tab.setViewportSize({ width: 1440, height: 900 });
      await tab.waitForSelector('#strip[data-poll-state="live"]', { timeout: 15000 });
      assert.ok((asked.ok ?? 0) > before);
      await tab.close();
    });
    await t.test('a rise is said, a critical one assertively; a fall is not', async () => {
      const tab = await open('rise');
      await tab.waitForFunction(() => document.querySelector('#ui-strip-said')?.textContent === '1 unit with no recent data', null, { timeout: 8000 });
      await tab.waitForFunction(() => document.querySelector('#ui-strip-alert')?.textContent === '1 unit critical', null, { timeout: 8000 });
      await tab.waitForFunction(() => document.querySelector('[data-strip="alarms"]')?.textContent === 'No open alarms', null, { timeout: 8000 });
      assert.equal(await tab.textContent('#ui-strip-said'), '1 unit with no recent data');   // the fall said nothing
      await tab.close();
    });
  } finally {
    await browser.close();
    server.close();
  }
});
