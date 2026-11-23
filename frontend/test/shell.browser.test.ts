// The shell's first fill in a real browser (Playwright on the machine's own Chrome or Edge; skipped where there is none):
// a grid the server drew as a placeholder (data-poll-state="loading", templates/monitoring/_loading.html) is asked for
// at once, not after its interval; its first answer replaces the placeholder and says nothing; a failed first answer
// (a 503) says "cannot be read" at once and aloud, politely, and the cards come when the server answers; a 401 is gone; a 204 is
// no first answer, and its next address is not followed. static/css/monitor.css shows the placeholder's lines. Test
// code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { join, resolve } from 'node:path';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';

const BUILD = resolve('.build/test');
const CSS = resolve('static/css/monitor.css');
const UNREAD = 'The cards cannot be read just now. The page tries again by itself.';

/** One scenario: the answers the stub gives the grid's polls, in turn (the last one repeats), and what it was asked. */
interface Stub { answers: { status: number; body?: string; next?: string; delay?: number }[]; asked: string[]; }

function cards(states: string[]): string {
  return `<div data-key="band">${states.length} shown</div>` + states.map((state, index) =>
    `<article data-key="card:${index}" data-state="${state}" class="monitor-${state}"><h3>T-0${index + 1}</h3></article>`).join('');
}

function page(every: number): string {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>shell</title>
<link rel="stylesheet" href="/css/monitor.css"></head><body>
<div class="monitor-grid" data-poll="/cards" data-poll-every="${every}" data-poll-merge="data-key" data-poll-state="loading"
 data-stale-text="Not updated." data-gone-text="Gone." data-updated-text="Updated again."><div class="monitor-loading" data-key="loading"><p data-loading>Loading the cards…</p><p data-unread>${UNREAD}</p><noscript><p><a href="/?full=1">full</a></p></noscript></div>
</div>
<div id="monitor-announce" data-announce-worse="{unit} is now {state}." data-announce-more="{count} more."
 data-states="critical warning blind unjudged note ok empty" data-stale-word="no recent data"
 data-state-critical="Critical" data-state-warning="Warning" data-state-blind="Blind" data-state-unjudged="No limit"
 data-state-note="Note">
 <p data-announcer aria-live="assertive"></p><p data-announcer aria-live="polite"></p></div>
<script type="module" src="/js/poll.js"></script><script type="module" src="/js/announce.js"></script></body></html>`;
}

function serve(stub: Stub, every: number): Promise<Server> {
  const server = createServer((request, response) => {
    const url = request.url ?? '';
    if (url === '/') {
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(page(every));
    } else if (url.startsWith('/cards')) {
      stub.asked.push(url);
      const answer = stub.answers[Math.min(stub.asked.length - 1, stub.answers.length - 1)];
      setTimeout(() => {
        response.writeHead(answer.status, { 'Content-Type': 'text/html; charset=utf-8',
                                            ...(answer.next ? { 'X-Poll-Next': answer.next } : {}) }).end(answer.body ?? '');
      }, answer.delay ?? 0);
    } else if (url === '/css/monitor.css') {
      response.writeHead(200, { 'Content-Type': 'text/css' }).end(readFileSync(CSS));
    } else {
      const file = join(BUILD, url.replace(/^\/js\//, ''));
      if (url.startsWith('/js/') && file.startsWith(BUILD) && existsSync(file)) {
        response.writeHead(200, { 'Content-Type': 'text/javascript' }).end(readFileSync(file));
      } else {
        response.writeHead(404).end();
      }
    }
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

async function run(stub: Stub, every: number, check: (tab: import('playwright-core').Page) => Promise<void>): Promise<void> {
  const server = await serve(stub, every);
  const address = server.address();
  const browser = await launch();
  try {
    const tab = await browser.newPage();
    const errors: string[] = [];
    tab.on('pageerror', (error) => errors.push(error.message));
    await tab.goto(`http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}/`);
    await check(tab);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    server.close();
  }
}

const state = (tab: import('playwright-core').Page): Promise<string | null> =>
  tab.locator('.monitor-grid').getAttribute('data-poll-state');
const said = async (tab: import('playwright-core').Page): Promise<string[]> =>
  tab.locator('[data-announcer]').allTextContents();
const shown = (tab: import('playwright-core').Page, selector: string): Promise<boolean> =>
  tab.locator(selector).isVisible();

test('the first fill comes at once, replaces the placeholder and says nothing', { skip: skipWithout(BROWSERS) }, async () => {
  const stub: Stub = { answers: [{ status: 200, body: cards(['critical', 'ok']), next: '/cards?after=1', delay: 1500 },
                                 { status: 204, next: '/cards?after=1' }], asked: [] };
  await run(stub, 60, async (tab) => {
    await tab.waitForFunction(() => document.querySelector('.monitor-grid')?.getAttribute('data-poll-state') === 'loading');
    assert.equal(await shown(tab, '[data-loading]'), true);                   // while the answer is on its way
    assert.equal(await shown(tab, '[data-unread]'), false);
    await tab.waitForFunction(() => document.querySelector('.monitor-grid')?.getAttribute('data-poll-state') === 'live',
                              undefined, { timeout: 5000 });                     // long before its 60 s interval
    assert.deepEqual(stub.asked, ['/cards']);
    assert.deepEqual(await tab.locator('.monitor-grid > *').evaluateAll(
      (nodes) => nodes.map((node) => node.getAttribute('data-key'))), ['band', 'card:0', 'card:1']);
    await tab.waitForTimeout(1500);
    assert.deepEqual(await said(tab), ['', '']);                              // a first load: no "is now Critical"
  });
});

test('a 503 first says the cards cannot be read at once, then the cards come', { skip: skipWithout(BROWSERS) }, async () => {
  const stub: Stub = { answers: [{ status: 503, body: 'The cards cannot be read just now.' },
                                 { status: 200, body: cards(['warning']), next: '/cards?after=2' },
                                 { status: 204, next: '/cards?after=2' }], asked: [] };
  await run(stub, 1, async (tab) => {
    await tab.waitForFunction(() => document.querySelector('.monitor-grid')?.getAttribute('data-poll-state') === 'unread',
                              undefined, { timeout: 5000 });                     // the first failure, not the second
    assert.equal(stub.asked.length, 1);
    assert.equal(await shown(tab, '[data-unread]'), true);
    assert.equal(await shown(tab, '[data-loading]'), false);
    await tab.waitForFunction(() => document.querySelector('[aria-live="polite"]')?.textContent !== '',
                              undefined, { timeout: 5000 });
    assert.deepEqual(await said(tab), ['', UNREAD]);                          // politely: the screen says it too
    await tab.waitForFunction(() => document.querySelector('.monitor-grid')?.getAttribute('data-poll-state') === 'live',
                              undefined, { timeout: 10000 });                    // asked again after the longer wait
    assert.equal(await tab.locator('[data-key="loading"]').count(), 0);
    assert.equal(await tab.locator('[data-key="card:0"]').count(), 1);
    await tab.waitForTimeout(1500);
    assert.deepEqual(await said(tab), ['', UNREAD]);                          // the first fill: no "Updated again."
    assert.equal(stub.asked[1], '/cards');                                     // the same address: no token yet
  });
});

test('a 401 first is gone: no card, no loading line, the notice, no more asking', { skip: skipWithout(BROWSERS) }, async () => {
  const stub: Stub = { answers: [{ status: 401 }], asked: [] };
  await run(stub, 1, async (tab) => {
    await tab.waitForFunction(() => document.querySelector('.monitor-grid')?.getAttribute('data-poll-state') === 'gone',
                              undefined, { timeout: 5000 });
    assert.equal(await shown(tab, '.monitor-loading'), false);
    assert.equal(await tab.locator('.monitor-grid').evaluate((grid) => getComputedStyle(grid, '::before').content),
                 '"Gone."');
    await tab.waitForTimeout(2500);
    assert.equal(stub.asked.length, 1);
    assert.deepEqual(await said(tab), ['Gone.', '']);
  });
});

test('a 204 first is no fill: unread, and its next address is not followed', { skip: skipWithout(BROWSERS) }, async () => {
  const stub: Stub = { answers: [{ status: 204, next: '/cards?after=stale' }, { status: 200, body: cards(['ok']), next: '/cards?after=3' },
                                 { status: 204, next: '/cards?after=3' }], asked: [] };
  await run(stub, 1, async (tab) => {
    await tab.waitForFunction(() => document.querySelector('.monitor-grid')?.getAttribute('data-poll-state') === 'unread',
                              undefined, { timeout: 5000 });
    assert.equal(await tab.locator('[data-key="loading"]').count(), 1);
    await tab.waitForFunction(() => document.querySelector('.monitor-grid')?.getAttribute('data-poll-state') === 'live',
                              undefined, { timeout: 10000 });
    assert.equal(stub.asked[1], '/cards');
    assert.equal(await state(tab), 'live');
    assert.equal(await tab.locator('[data-key="card:0"]').count(), 1);
  });
});
