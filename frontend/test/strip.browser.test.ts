// The new look's status strip in a real browser (Playwright on the machine's own Chrome or Edge; skipped where there is none,
// never under CI=1): the alarms item the server draws as a placeholder ("Reading the alarms…") is asked for by the real
// frontend/poll.ts once the page's scripts have run (its start-up gate), and replaced by the server's answer; an answer
// that never comes says the alarms cannot be read, never "Reading…" for ever and never "no alarms". The markup is the
// template's (checked against templates/app_base.html), on the product's style sheets, under the product's policy. Test
// code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, join, resolve } from 'node:path';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { policy } from './csp.js';
import { linksOf, mirrors } from './sheets.js';

const CSP = policy();                    // config/settings.py's, read by frontend/test/csp.ts
const OPEN = '<span class="ui-strip-poll" data-poll="{{ item.poll }}" data-poll-every="30" data-poll-state="loading" data-unread-text="';
const FRAGMENT = '<a class="ui-strip-item" href="/alarms/" data-strip="alarms" data-status="critical">1 unit critical</a>';

function page(answer: string): string {
  return `<!doctype html><html lang="en" data-theme="industry" data-ui="next"><head><meta charset="utf-8"><title>strip</title>
${linksOf('app_base.html')}</head><body><header class="topbar ui-topbar"><div class="ui-strip" role="group" aria-label="Status">
<span class="ui-strip-poll" id="alarms" data-poll="/fragment/${answer}" data-poll-every="30" data-poll-state="loading" data-unread-text="The alarms cannot be read"><a class="ui-strip-item" href="/alarms/" data-strip="alarms">Reading the alarms…</a></span>
<span class="ui-strip-item" data-strip="clock">24.11.2026, 04:05 · Europe/Oslo</span></div></header>
<script type="module" src="/static/js/poll.js"></script></body></html>`;
}

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    const headers = { 'Content-Security-Policy': CSP };
    if (url.pathname.startsWith('/page/')) {
      response.writeHead(200, { ...headers, 'Content-Type': 'text/html; charset=utf-8' });
      response.end(page(url.pathname.slice('/page/'.length)));
    } else if (url.pathname === '/fragment/ok') {
      response.writeHead(200, { ...headers, 'Content-Type': 'text/html; charset=utf-8' });
      response.end(FRAGMENT);
    } else if (url.pathname === '/fragment/down') {
      response.writeHead(503, headers);
      response.end();
    } else {
      const file = url.pathname.startsWith('/static/') ? resolve(`.${url.pathname}`) : url.pathname.startsWith('/css/') || url.pathname.startsWith('/fonts/') ? resolve('static', `.${url.pathname}`) : '';
      if (file && existsSync(file)) {
        response.writeHead(200, { ...headers, 'Content-Type': extname(file) === '.css' ? 'text/css' : extname(file) === '.js' ? 'text/javascript' : 'application/octet-stream' });
        response.end(readFileSync(file));
      } else {
        response.writeHead(404, headers);
        response.end();
      }
    }
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

test('the strip\'s alarms in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  assert.deepEqual(mirrors('app_base.html', OPEN), [], 'the placeholder is the template\'s');
  assert.ok(existsSync(join('static', 'js', 'poll.js')), 'npm run build first (static/js/poll.js)');
  const server = await serve();
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    await t.test('the placeholder is asked for after the gate and replaced by the answer', async () => {
      const tab = await browser.newPage();
      await tab.goto(`${origin}/page/ok`);
      await tab.waitForSelector('#alarms[data-poll-state="live"]');
      assert.equal((await tab.textContent('#alarms'))?.trim(), '1 unit critical');
      assert.equal(await tab.getAttribute('#alarms a', 'data-status'), 'critical');
      await tab.close();
    });
    await t.test('no answer: it says the alarms cannot be read, in words, and never stays "Reading…"', async () => {
      const tab = await browser.newPage();
      await tab.goto(`${origin}/page/down`);
      await tab.waitForSelector('#alarms[data-poll-state="unread"]');
      const said = await tab.evaluate(() => {
        const element = document.querySelector('#alarms') as Element;
        return { after: getComputedStyle(element, '::after').content, link: getComputedStyle(element.querySelector('a') as Element).display };
      });
      assert.equal(said.after, '"The alarms cannot be read"');
      assert.equal(said.link, 'none');
      await tab.close();
    });
  } finally {
    await browser.close();
    server.close();
  }
});
