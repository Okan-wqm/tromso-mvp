// The wall's announcements in a real browser (Playwright on the machine's own Chrome or Edge; skipped where there is
// none): poll.ts merges a changed card and sends poll:merged, announce.ts says a worse state aloud in the right region,
// and says nothing on the first load or for a better state. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { join, resolve } from 'node:path';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';

const BUILD = resolve('.build/test');

// The states the stub answers with, one per poll: T-01 gets critical, then T-02 a warning, then T-01 better.
const ROUNDS = [['ok', 'ok'], ['critical', 'ok'], ['critical', 'warning'], ['ok', 'warning']];
let round = 0;
// When set, the stub answers the grid's polls with a server error (the cards cannot be read).
let broken = false;

function cards(states: string[]): string {
  return states.map((state, index) => `<article data-key="card:${index}" data-state="${state}" class="monitor-${state}">` +
    `<h3>T-0${index + 1}</h3><p>${state}</p></article>`).join('');
}

function page(): string {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>wall</title></head><body>
<div class="monitor-grid" data-poll="/cards" data-poll-every="1" data-poll-merge="data-key" data-poll-state="live"
 data-stale-text="Not updated." data-gone-text="Gone." data-updated-text="Updated again.">${cards(ROUNDS[0])}</div>
<div id="monitor-announce" data-announce-worse="{unit} is now {state}." data-announce-more="{count} more."
 data-state-critical="Critical" data-state-warning="Warning" data-state-blind="Blind" data-state-note="Note">
 <p data-announcer aria-live="assertive"></p><p data-announcer aria-live="polite"></p></div>
<script type="module" src="/js/poll.js"></script><script type="module" src="/js/announce.js"></script></body></html>`;
}

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    if (request.url === '/') {
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(page());
    } else if (request.url?.startsWith('/cards') && broken) {
      response.writeHead(503).end('The cards cannot be read just now.');
    } else if (request.url?.startsWith('/cards')) {
      round = Math.min(round + 1, ROUNDS.length - 1);
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'X-Poll-Next': '/cards' })
        .end(cards(ROUNDS[round]));
    } else {
      const file = join(BUILD, (request.url ?? '').replace(/^\/js\//, ''));
      if (request.url?.startsWith('/js/') && file.startsWith(BUILD) && existsSync(file)) {
        response.writeHead(200, { 'Content-Type': 'text/javascript' }).end(readFileSync(file));
      } else {
        response.writeHead(404).end();
      }
    }
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

test('the wall says a worse card aloud', { skip: skipWithout(BROWSERS) }, async () => {
  const server = await serve();
  const address = server.address();
  const browser = await launch();
  try {
    const tab = await browser.newPage();
    const errors: string[] = [];
    tab.on('pageerror', (error) => errors.push(error.message));
    await tab.goto(`http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}/`);
    const assertive = tab.locator('[data-announcer][aria-live="assertive"]');
    const polite = tab.locator('[data-announcer][aria-live="polite"]');
    assert.equal(await assertive.textContent(), '');                               // the first load says nothing
    await tab.waitForFunction(() => document.querySelector('[aria-live="assertive"]')?.textContent !== '',
                              undefined, { timeout: 15000 });
    assert.equal(await assertive.textContent(), 'T-01 is now Critical.');
    await tab.waitForFunction(() => document.querySelector('[aria-live="polite"]')?.textContent !== '',
                              undefined, { timeout: 15000 });
    assert.equal(await polite.textContent(), 'T-02 is now Warning.');
    await tab.waitForTimeout(2500);                                               // T-01 better: nothing new is said
    assert.equal(await assertive.textContent(), 'T-01 is now Critical.');
    // The server cannot read the cards: after two failures the grid says it is not updated, aloud too (F-045), and
    // says so again when it is updated again.
    broken = true;
    await tab.waitForFunction(() => document.querySelector('[aria-live="assertive"]')?.textContent === 'Not updated.',
                              undefined, { timeout: 20000 });
    broken = false;
    await tab.waitForFunction(() => document.querySelector('[aria-live="assertive"]')?.textContent === 'Updated again.',
                              undefined, { timeout: 30000 });
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    server.close();
  }
});
