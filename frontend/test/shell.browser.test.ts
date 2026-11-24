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
interface Stub { answers: Answer[]; asked: string[]; pane?: Answer[]; paneAsked?: string[]; served?: string[]; }
/** How the page is drawn: the grid's interval, a wall, the scripts, the pane, a sheet of the test's own, announce.js
 *  served that many ms late, the monitoring page's own scripts in its own order (windows.js, which imports poll.js,
 *  before announce.js: templates/monitoring/monitor.html and app_base.html). */
interface Look { every?: number; wall?: boolean; scripts?: boolean; dock?: boolean; style?: string; lateAnnouncer?: number;
                 windows?: boolean; inline?: string; link?: boolean; flip?: boolean; }

function cards(states: string[]): string {
  return `<div data-key="band">${states.length} shown</div>` + states.map((state, index) =>
    `<article id="card-${index}" data-key="card:${index}" data-state="${state}" class="monitor-${state}">` +
    `<h3>T-0${index + 1}</h3></article>`).join('');
}

function page(look: Look): string {
  const dock = look.dock ? `<aside id="monitor-dock"${look.windows ? ' data-pane-url="/pane" data-grid-url="/cards" data-every="60"' : ''}><section class="monitor-window monitor-pane" data-dock-unit="1">
<div class="monitor-window-body" data-window-body data-poll="/pane" data-poll-every="60" data-poll-merge="data-key"
 data-poll-state="loading" data-stale-text="Not updated." data-gone-text="Gone.">${loading(false)}</div></section></aside>` : '';
  const template = look.windows ? `<template id="monitor-dock-template"><section class="monitor-window monitor-pane" tabindex="-1">
<h2 data-dock-title></h2><a data-dock-close href="/">Close</a><div class="monitor-window-body" data-window-body></div></section></template>` : '';
  const scripts = look.scripts === false ? ''
    : look.windows ? `${template}<script type="module" src="/js/windows.js"></script>` +
                     '<script type="module" src="/js/announce.js"></script><script type="module" src="/js/poll.js"></script>'
    : '<script type="module" src="/js/poll.js"></script><script type="module" src="/js/announce.js"></script>';
  return `<!doctype html><html lang="en"${look.wall ? ' data-wall' : ''}><head><meta charset="utf-8"><title>shell</title>
<link rel="stylesheet" href="/css/monitor.css">${look.style ? `<style>${look.style}</style>` : ''}</head><body>${dock}${look.link ? '<a data-dock="2" data-dock-code="T-02" id="open-2" href="/?focus=2">open</a>' : ''}
<div class="monitor-grid" data-poll="/cards" data-poll-every="${look.every ?? 60}" data-poll-merge="data-key" data-poll-state="loading"
 data-stale-text="Not updated." data-gone-text="Gone." data-updated-text="Updated again.">${loading(true)}${look.flip ? '<a data-poll-url="/cards?flip=1" id="flip" href="/?flip=1">flip</a>' : ''}</div>
<div id="monitor-announce" data-announce-worse="{unit} is now {state}." data-announce-more="{count} more."
 data-states="critical warning blind unjudged note ok empty" data-stale-word="no recent data"
 data-state-critical="Critical" data-state-warning="Warning" data-state-blind="Blind" data-state-unjudged="No limit"
 data-state-note="Note">
 <p data-announcer aria-live="assertive"></p><p data-announcer aria-live="polite"></p></div>
${scripts}${look.inline ? `<script type="module">${look.inline}</script>` : ''}</body></html>`;
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
      (stub.served ??= []).push('cards');
      answer(response, stub.answers, stub.asked, url);
    } else if (url.startsWith('/pane')) {
      (stub.served ??= []).push('pane');
      answer(response, stub.pane ?? [{ status: 404 }], stub.paneAsked ??= [], url);
    } else if (url === '/js/announce.js' && look.lateAnnouncer) {
      // announce.js arrives after the grid's first answer: poll.js must not have asked before it ran
      setTimeout(() => {
        if (!response.destroyed) {
          (stub.served ??= []).push('announce.js');
          response.writeHead(200, { 'Content-Type': 'text/javascript' }).end(readFileSync(join(BUILD, 'announce.js')));
        }
      }, look.lateAnnouncer);
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
                                 { status: 200, body: cards(['warning']), next: '/cards?after=2' },
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

test('a 503 first is said even when announce.js comes after the answer: the grid asks once every script has run',
     { skip: skipWithout(BROWSERS) }, async () => {
  // The flake behind main's red browser job (2026-11-24): poll.js asked at once, the 503 came back before announce.js
  // had run, so announce.js started from "unread", saw no change and never said it.
  const stub: Stub = { answers: [{ status: 503, body: 'The cards cannot be read just now.' },
                                 { status: 200, body: cards(['ok']), next: '/cards?after=5' },
                                 { status: 204, next: '/cards?after=5' }], asked: [] };
  await run(stub, { every: 1, lateAnnouncer: 1500 }, async (tab) => {
    await until(tab, 'unread');
    assert.deepEqual(stub.served?.slice(0, 2), ['announce.js', 'cards']);    // the grid waited for announce.js
    await politely(tab, UNREAD);
    await until(tab, 'live');
    await politely(tab, 'Updated again.');
  });
});

test('the pane the server drew, adopted by windows.js, waits for announce.js too: its 503 is said',
     { skip: skipWithout(BROWSERS) }, async () => {
  // review F1: windows.js (which imports poll.js) watches the pane as it runs, before announce.js has; the pane waits at
  // poll.ts's gate, so its first failure is still said. The monitoring page's own script order.
  const stub: Stub = { answers: [{ status: 200, body: cards(['ok']), next: '/cards?after=9' }, { status: 204, next: '/cards?after=9' }],
                       asked: [], pane: [{ status: 503 }] };
  await run(stub, { dock: true, windows: true, lateAnnouncer: 1500, every: 1 }, async (tab) => {
    await tab.waitForFunction(() => document.querySelector('.monitor-window-body')?.getAttribute('data-poll-state') === 'unread',
                              undefined, { timeout: 12000 });
    assert.equal(stub.served?.[0], 'announce.js');                             // nothing was asked before it ran
    await politely(tab, UNREAD);
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

// ---- the start-up gate (frontend/poll.ts `watch` and `begin`): what happens before every script of the page has run ----
async function early(stub: Stub, look: Look, check: (tab: Page) => Promise<void>): Promise<void> {
  const server = await serve(stub, look);
  const address = server.address();
  const browser = await launch();
  try {
    const tab = await browser.newPage();
    const errors: string[] = [];
    tab.on('pageerror', (error) => errors.push(error.message));
    await tab.goto(`http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}/`, { waitUntil: 'commit' });
    await check(tab);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    server.closeAllConnections();
    server.close();
  }
}
const okCards = (): Stub => ({ answers: [{ status: 200, body: cards(['ok']), next: '/cards?after=9' }, { status: 204, next: '/cards?after=9' }],
                               asked: [] });

test('a dock link clicked before the page is ready reaches the grid', { skip: skipWithout(BROWSERS) }, async () => {
  const stub = okCards();
  stub.pane = [{ status: 200, body: cards(['ok']), next: '/pane?after=1' }, { status: 204, next: '/pane?after=1' }];
  await early(stub, { dock: true, windows: true, link: true, lateAnnouncer: 3000, every: 60 }, async (tab) => {
    await tab.waitForFunction(() => document.readyState !== 'loading');
    await tab.waitForTimeout(700);
    assert.equal(stub.served?.includes('announce.js') ?? false, false, 'the page must still be loading');
    await tab.evaluate(() => (document.getElementById('open-2') as HTMLElement).click());
    await tab.waitForLoadState('load');
    await tab.waitForTimeout(2500);
    assert.ok(stub.asked.some((url) => url.includes('focus=2')), `the grid never asked with the focus: ${JSON.stringify(stub.asked)}`);
  });
});

test('a data-poll-url link clicked before the page is ready reaches the grid', { skip: skipWithout(BROWSERS) }, async () => {
  const stub = okCards();
  await early(stub, { flip: true, lateAnnouncer: 3000, every: 60 }, async (tab) => {
    await tab.waitForFunction(() => document.readyState !== 'loading');
    await tab.waitForTimeout(700);
    assert.equal(stub.served?.includes('announce.js') ?? false, false, 'the page must still be loading');
    await tab.click('#flip');
    await tab.waitForLoadState('load');
    await tab.waitForTimeout(2500);
    assert.ok(stub.asked.some((url) => url.includes('flip=1')), `the grid never asked for the flip: ${JSON.stringify(stub.asked)}`);
  });
});

const GRID = "const g = document.querySelector('.monitor-grid');";
const IMPORT = "import { watch } from '/js/poll.js';";
const gateTest = (name: string, inline: string, check: (stub: Stub, tab: Page) => Promise<void>): void => {
  test(name, { skip: skipWithout(BROWSERS) }, async () => {
    const stub = okCards();
    await run(stub, { inline: IMPORT + GRID + inline, lateAnnouncer: 1500, every: 60 }, async (tab) => {
      await tab.waitForTimeout(2500);
      await check(stub, tab);
    });
  });
};
gateTest('the gate: an element removed before the start is never asked', "watch(g); g.remove();",
         async (stub) => { assert.deepEqual(stub.asked, []); });
gateTest('the gate: an element stopped before the start (still in the page) is never asked', 'watch(g)();',
         async (stub) => { assert.deepEqual(stub.asked, [], 'the scan of [data-poll] started it again'); });
gateTest('the gate: a placeholder asked before the start is asked once, at the address it was given',
         "watch(g); g.dispatchEvent(new CustomEvent('poll:now', { detail: { url: '/cards?x=1' } }));",
         async (stub) => { assert.deepEqual(stub.asked, ['/cards?x=1']); });
gateTest('the gate: a filled element asked before the start is asked once, at the address it was given',
         "g.dataset.pollState = 'live'; watch(g); g.dispatchEvent(new CustomEvent('poll:now', { detail: { url: '/cards?y=1' } }));",
         async (stub) => { assert.deepEqual(stub.asked, ['/cards?y=1']); });
test('the gate: the stop got before the start still stops the poll after it', { skip: skipWithout(BROWSERS) }, async () => {
  const stub = okCards();
  stub.pane = [{ status: 200, body: cards(['ok']), next: '/pane?after=1' }, { status: 204, next: '/pane?after=1' }];
  const inline = IMPORT + "const p = document.querySelector('.monitor-window-body'); p.dataset.pollEvery = '1'; window.__stop = watch(p);";
  await run(stub, { dock: true, inline, lateAnnouncer: 1200, every: 60 }, async (tab) => {
    await tab.waitForTimeout(3500);
    const before = stub.paneAsked?.length ?? 0;
    assert.ok(before >= 2, `the pane was asked ${before} times`);
    await tab.evaluate(() => (window as unknown as { __stop: () => void }).__stop());
    await tab.waitForTimeout(400);
    const settled = stub.paneAsked?.length ?? 0;
    await tab.waitForTimeout(3500);
    assert.equal(stub.paneAsked?.length ?? 0, settled);
  });
});
