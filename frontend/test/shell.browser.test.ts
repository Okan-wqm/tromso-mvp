// The shell's first fill in a real browser (Playwright on the machine's own Chrome or Edge; skipped where there is none).
// The placeholder is the REAL templates/monitoring/_loading.html, rendered here for its few tags (trans, if grid, the
// full page's address); a tag this renderer does not know fails the test, so the test follows the template.
// A grid the server drew as a placeholder (data-poll-state="loading") is asked for at once, not after its interval; its
// first answer replaces the placeholder and says nothing, then the page goes to the card its address names (#card-…);
// a failed first answer (a 503, an empty or foreign 200, a 204) says "cannot be read" at once, politely, and "Updated
// again." politely when the cards come; a 401 is gone; the first request may take 35 s and the first retries come within
// 10 s whatever the interval; the pane's "cannot be read" is said politely too. Without poll.js the watchdog line (the
// full page's link) shows after half a minute by CSS alone; on a wall the loading line has the notices' size.
// static/css/monitor.css shows the placeholder's lines. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { join, resolve } from 'node:path';

import type { Page } from 'playwright-core';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';

const BUILD = resolve('.build/test');
const CSS = resolve('static/css/monitor.css');
const TEMPLATE = resolve('templates/monitoring/_loading.html');
const UNREAD = 'The cards cannot be read just now. The page tries again by itself.';
const FULL = '/?full=1';

/** templates/monitoring/_loading.html as Django draws it in English: `grid` the grid's (else the pane's). */
function loading(grid: boolean): string {
  let html = readFileSync(TEMPLATE, 'utf-8')
    .replace(/^\{% load i18n %\}/, '')
    .replace(/\{% comment %\}[\s\S]*?\{% endcomment %\}/g, '')
    .replace(/\{% trans "([^"]*)" %\}/g, '$1')
    .replace(/\{\{ full_url \}\}/g, FULL)
    .replace(/\{% if grid %\}([\s\S]*?)(?:\{% else %\}([\s\S]*?))?\{% endif %\}/g,
             (_whole, yes: string, no: string | undefined) => (grid ? yes : no ?? ''));
  assert.doesNotMatch(html, /\{[%{]/, 'templates/monitoring/_loading.html has a tag this test does not draw');
  html = html.trim();
  return `${html}\n`;
}

interface Answer { status: number; body?: string; next?: string; delay?: number; }
/** What the stub answers the grid's polls (and the pane's), in turn (the last one repeats), and what it was asked. */
interface Stub { answers: Answer[]; asked: string[]; pane?: Answer[]; paneAsked?: string[]; }
/** How the page is drawn: the grid's interval, a wall, the scripts, the pane, a sheet of the test's own. */
interface Look { every?: number; wall?: boolean; scripts?: boolean; dock?: boolean; style?: string; }

function cards(states: string[]): string {
  return `<div data-key="band">${states.length} shown</div>` + states.map((state, index) =>
    `<article id="card-${index}" data-key="card:${index}" data-state="${state}" class="monitor-${state}">` +
    `<h3>T-0${index + 1}</h3></article>`).join('');
}

function page(look: Look): string {
  const dock = look.dock ? `<aside id="monitor-dock"><section class="monitor-window monitor-pane" data-dock-unit="1">
<div class="monitor-window-body" data-window-body data-poll="/pane" data-poll-every="60" data-poll-merge="data-key"
 data-poll-state="loading" data-stale-text="Not updated." data-gone-text="Gone.">${loading(false)}</div></section></aside>` : '';
  const scripts = look.scripts === false ? ''
    : '<script type="module" src="/js/poll.js"></script><script type="module" src="/js/announce.js"></script>';
  return `<!doctype html><html lang="en"${look.wall ? ' data-wall' : ''}><head><meta charset="utf-8"><title>shell</title>
<link rel="stylesheet" href="/css/monitor.css">${look.style ? `<style>${look.style}</style>` : ''}</head><body>${dock}
<div class="monitor-grid" data-poll="/cards" data-poll-every="${look.every ?? 60}" data-poll-merge="data-key" data-poll-state="loading"
 data-stale-text="Not updated." data-gone-text="Gone." data-updated-text="Updated again.">${loading(true)}</div>
<div id="monitor-announce" data-announce-worse="{unit} is now {state}." data-announce-more="{count} more."
 data-states="critical warning blind unjudged note ok empty" data-stale-word="no recent data"
 data-state-critical="Critical" data-state-warning="Warning" data-state-blind="Blind" data-state-unjudged="No limit"
 data-state-note="Note">
 <p data-announcer aria-live="assertive"></p><p data-announcer aria-live="polite"></p></div>
${scripts}</body></html>`;
}

function answer(response: import('node:http').ServerResponse, list: Answer[], asked: string[], url: string): void {
  asked.push(url);
  const given = list[Math.min(asked.length - 1, list.length - 1)];
  setTimeout(() => {
    if (response.destroyed) return;
    response.writeHead(given.status, { 'Content-Type': 'text/html; charset=utf-8',
                                       ...(given.next ? { 'X-Poll-Next': given.next } : {}) }).end(given.body ?? '');
  }, given.delay ?? 0);
}

function serve(stub: Stub, look: Look): Promise<Server> {
  const server = createServer((request, response) => {
    const url = request.url ?? '';
    if (url === '/') {
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(page(look));
    } else if (url.startsWith('/cards')) {
      answer(response, stub.answers, stub.asked, url);
    } else if (url.startsWith('/pane')) {
      answer(response, stub.pane ?? [{ status: 404 }], stub.paneAsked ??= [], url);
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

async function run(stub: Stub, look: Look, check: (tab: Page) => Promise<void>, hash = ''): Promise<void> {
  const server = await serve(stub, look);
  const address = server.address();
  const browser = await launch();
  try {
    const tab = await browser.newPage();
    const errors: string[] = [];
    tab.on('pageerror', (error) => errors.push(error.message));
    await tab.goto(`http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}/${hash}`);
    await check(tab);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    server.closeAllConnections();
    server.close();
  }
}

const state = (tab: Page): Promise<string | null> => tab.locator('.monitor-grid').getAttribute('data-poll-state');
const said = async (tab: Page): Promise<string[]> => tab.locator('#monitor-announce [data-announcer]').allTextContents();
const shown = (tab: Page, selector: string): Promise<boolean> => tab.locator(selector).first().isVisible();
// The waits are generous on purpose: a notice can sit up to 5 s behind the announcer's limiter, and a loaded CI runner
// adds to it (a 503-then-ok run once took 30 s and missed a 5 s wait). A wait only bounds how long a failing test hangs;
// what each test proves is asserted after it.
const until = (tab: Page, wanted: string, timeout = 12000): Promise<unknown> =>
  tab.waitForFunction((value) => document.querySelector('.monitor-grid')?.getAttribute('data-poll-state') === value,
                      wanted, { timeout });
const politely = (tab: Page, text: string, timeout = 12000): Promise<unknown> =>
  tab.waitForFunction((value) => document.querySelector('[aria-live="polite"]')?.textContent === value, text, { timeout });

test('the placeholder is the template\'s, with its watchdog line and no state', () => {
  const grid = loading(true);
  assert.match(grid, /^<div class="monitor-loading" data-key="loading">/);
  assert.match(grid, /<p data-stuck><a href="\/\?full=1">Still loading\? Open the full page<\/a><\/p>/);
  assert.match(grid, /<noscript>/);
  assert.doesNotMatch(loading(false), /data-stuck|noscript/);               // the pane's: the grid's says it once
  assert.doesNotMatch(grid, /data-state|monitor-(critical|warning|ok)/);
});

test('the first fill comes at once, replaces the placeholder and says nothing', { skip: skipWithout(BROWSERS) }, async () => {
  const stub: Stub = { answers: [{ status: 200, body: cards(['critical', 'ok']), next: '/cards?after=1', delay: 1500 },
                                 { status: 204, next: '/cards?after=1' }], asked: [] };
  await run(stub, {}, async (tab) => {
    await until(tab, 'loading');
    assert.equal(await shown(tab, '[data-loading]'), true);                   // while the answer is on its way
    assert.equal(await shown(tab, '[data-unread]'), false);
    assert.equal(await shown(tab, '[data-stuck]'), false);
    await until(tab, 'live');                                                  // long before its 60 s interval
    assert.deepEqual(stub.asked, ['/cards']);
    assert.deepEqual(await tab.locator('.monitor-grid > *').evaluateAll(
      (nodes) => nodes.map((node) => node.getAttribute('data-key'))), ['band', 'card:0', 'card:1']);
    assert.equal(await tab.locator('[data-stuck]').count(), 0);               // the watchdog went with the placeholder
    await tab.waitForTimeout(1500);
    assert.deepEqual(await said(tab), ['', '']);                              // a first load: no "is now Critical"
  });
});

test('a 503 first says the cards cannot be read at once, then "Updated again." when they come',
     { skip: skipWithout(BROWSERS) }, async () => {
  const stub: Stub = { answers: [{ status: 503, body: 'The cards cannot be read just now.' },
                                 // the good answer is held back 8 s, longer than the announcer's 5 s limiter: with
                                 // a quick one the limiter could go straight to "Updated again." and never say the
                                 // failure, which made this test fail now and then on a loaded runner
                                 { status: 200, body: cards(['warning']), next: '/cards?after=2', delay: 8000 },
                                 { status: 204, next: '/cards?after=2' }], asked: [] };
  await run(stub, { every: 1 }, async (tab) => {
    await until(tab, 'unread');                                                // the first failure, not the second
    assert.equal(stub.asked.length, 1);
    assert.equal(await shown(tab, '[data-unread]'), true);
    assert.equal(await shown(tab, '[data-loading]'), false);
    await politely(tab, UNREAD);                                               // politely: the screen says it too
    assert.deepEqual(await said(tab), ['', UNREAD]);
    await until(tab, 'live', 25000);                                           // asked again after the longer wait
    assert.equal(await tab.locator('[data-key="loading"]').count(), 0);
    assert.equal(await tab.locator('[data-key="card:0"]').count(), 1);
    assert.equal(stub.asked[1], '/cards');                                     // the same address: no token yet
    await politely(tab, 'Updated again.', 12000);                              // review F3: the way back is said
    assert.deepEqual(await said(tab), ['', 'Updated again.']);
  });
});

test('an empty or foreign 200 first is no fill: unread, its next address not followed', { skip: skipWithout(BROWSERS) },
     async () => {
  const stub: Stub = { answers: [{ status: 200, body: '', next: '/cards?after=empty' },
                                 { status: 200, body: '<html><body><h1>Bad gateway</h1></body></html>', next: '/cards?after=x' },
                                 { status: 200, body: cards(['ok']), next: '/cards?after=4' },
                                 { status: 204, next: '/cards?after=4' }], asked: [] };
  await run(stub, { every: 1 }, async (tab) => {
    await until(tab, 'unread');
    assert.equal(await tab.locator('[data-key="loading"]').count(), 1);       // the placeholder stays, saying so
    assert.equal(await shown(tab, '[data-unread]'), true);
    await tab.waitForFunction(() => document.querySelector('.monitor-grid')?.getAttribute('data-poll-state') === 'live',
                              undefined, { timeout: 15000 });
    assert.deepEqual(stub.asked.slice(0, 3), ['/cards', '/cards', '/cards']);  // neither "next" was followed
    assert.equal(await tab.locator('[data-key="card:0"]').count(), 1);
    assert.equal(await tab.locator('h1').count(), 0);                          // the foreign page was never put in
  });
});

test('a 401 first is gone: no card, no loading line, the notice, no more asking', { skip: skipWithout(BROWSERS) }, async () => {
  const stub: Stub = { answers: [{ status: 401 }], asked: [] };
  await run(stub, { every: 1 }, async (tab) => {
    await until(tab, 'gone');
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
  await run(stub, { every: 1 }, async (tab) => {
    await until(tab, 'unread');
    assert.equal(await tab.locator('[data-key="loading"]').count(), 1);
    await until(tab, 'live', 10000);
    assert.equal(stub.asked[1], '/cards');
    assert.equal(await state(tab), 'live');
    assert.equal(await tab.locator('[data-key="card:0"]').count(), 1);
  });
});

test('after the first fill the page goes to the card its address names', { skip: skipWithout(BROWSERS) }, async () => {
  const stub: Stub = { answers: [{ status: 200, body: cards(['ok', 'ok', 'warning']), next: '/cards?after=5' },
                                 { status: 204, next: '/cards?after=5' }], asked: [] };
  const style = '.monitor-grid > article { display: block; min-height: 1500px; }';
  await run(stub, { style }, async (tab) => {
    await until(tab, 'live');
    const where = await tab.evaluate(() => ({
      y: window.scrollY, top: document.getElementById('card-2')?.getBoundingClientRect().top ?? -1,
      height: window.innerHeight }));
    assert.ok(where.y > 1000, `scrolled to ${where.y}`);                       // (the grid puts cards side by side)
    assert.ok(where.top >= -1 && where.top < where.height, `card-2 at ${where.top}`);
  }, '#card-2');
});

test('a slow first answer is waited for (35 s), and the first retries come within 10 s', { skip: skipWithout(BROWSERS) },
     async () => {
  const slow: Stub = { answers: [{ status: 200, body: cards(['ok']), next: '/cards?after=6', delay: 22000 },
                                 { status: 204, next: '/cards?after=6' }], asked: [] };
  await run(slow, {}, async (tab) => {
    await until(tab, 'live', 30000);                                           // a 20 s timeout had aborted it
    assert.equal(slow.asked.length, 1);
  });
  const retried: Stub = { answers: [{ status: 503 }, { status: 200, body: cards(['ok']), next: '/cards?after=7' },
                                    { status: 204, next: '/cards?after=7' }], asked: [] };
  await run(retried, { every: 60 }, async (tab) => {
    await until(tab, 'unread');
    await until(tab, 'live', 13000);                                           // not 60 s later: nothing is on the screen
    assert.equal(retried.asked.length, 2);
  });
});

test('the pane\'s "cannot be read" is said politely', { skip: skipWithout(BROWSERS) }, async () => {
  const stub: Stub = { answers: [{ status: 200, body: cards(['ok']), next: '/cards?after=8' }, { status: 204, next: '/cards?after=8' }],
                       asked: [], pane: [{ status: 503 }] };
  await run(stub, { dock: true }, async (tab) => {
    await tab.waitForFunction(() => document.querySelector('.monitor-window-body')?.getAttribute('data-poll-state') === 'unread',
                              undefined, { timeout: 5000 });
    assert.equal(await shown(tab, '.monitor-window-body [data-unread]'), true);
    await politely(tab, UNREAD);
    assert.deepEqual(await said(tab), ['', UNREAD]);
  });
});

test('without poll.js the watchdog shows the full page\'s link after half a minute; a wall\'s line is large',
     { skip: skipWithout(BROWSERS) }, async () => {
  await run({ answers: [{ status: 503 }], asked: [] }, { scripts: false }, async (tab) => {
    const stuck = tab.locator('[data-stuck]');
    assert.equal(await stuck.isVisible(), false);
    assert.deepEqual(await stuck.evaluate((node) => {
      const style = getComputedStyle(node);
      return [style.animationName, style.animationDelay, style.animationFillMode];
    }), ['monitor-stuck', '30s', 'forwards']);
    await tab.evaluate(() => document.getAnimations().forEach((each) => each.finish()));   // half a minute later
    assert.equal(await stuck.isVisible(), true);
    assert.equal(await stuck.locator('a').getAttribute('href'), FULL);
    assert.equal(await stuck.locator('a').textContent(), 'Still loading? Open the full page');
    assert.equal(await shown(tab, '[data-loading]'), true);                   // it is still loading, and says so
  });
  await run({ answers: [{ status: 200, body: cards(['ok']), delay: 3000 }], asked: [] }, { wall: true }, async (tab) => {
    const size = await tab.locator('[data-loading]').evaluate((node) => Number.parseFloat(getComputedStyle(node).fontSize));
    assert.ok(size >= 20, `the wall's loading line is ${size}px`);            // the notices' size, not 16 px grey
  });
});
