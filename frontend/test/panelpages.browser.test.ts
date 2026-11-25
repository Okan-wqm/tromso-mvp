// The production panel's pages the server draws in the new look (Tasks with its drawer, Regulatory reports, Storage,
// Messages), as the server answered them on the test world (frontend/test/pages/panel/<page>-<language>.html,
// scripts/record_test_world.py), in a real browser on the product's style sheets and scripts under the page's own
// Content-Security-Policy: in en, nb and tr, at 1440 and at 390 wide, no CSP violation, no serious axe finding, no
// page-wide scroll, the rail at its full width on a desktop, and a long conversation open at its newest message with
// its list scrolling inside its plate. Test code only.
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, join, resolve } from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

import type { Page } from 'playwright-core';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { policy } from './csp.js';
import { watchCsp } from './island-page.js';

const FOLDER = resolve('frontend/test/pages/panel');
const TYPES: Record<string, string> = { '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' };

/** /page/<page>-<language>: the recorded answer under its nonce's policy; /static/…: the product's files; /axe.js. */
function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    if (url.pathname.startsWith('/page/')) {
      const html = readFileSync(join(FOLDER, `${url.pathname.slice('/page/'.length)}.html`), 'utf8');
      const nonce = /nonce="([^"]+)"/.exec(html)?.[1] ?? '';
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Content-Security-Policy': policy(nonce) });
      response.end(html);
      return;
    }
    let file = '';
    if (url.pathname.startsWith('/static/')) file = resolve('static', `.${url.pathname.slice('/static'.length)}`);
    else if (url.pathname === '/axe.js') file = resolve('node_modules/axe-core/axe.min.js');
    if (file && existsSync(file)) {
      response.writeHead(200, { 'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream' });
      response.end(readFileSync(file));
    } else {
      response.writeHead(404);      // the strip's and the polls' answers: the pages say they cannot be read
      response.end();
    }
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

/** axe's serious and critical findings in the page's <main>, and two landmarks of one name (a plate and the region
 *  inside it): what these pages draw (the shell around it is the
 *  foundation's, held by its own tests, shell.browser.test.ts). */
async function axeOfMain(tab: Page, origin: string): Promise<string[]> {
  await tab.addScriptTag({ url: `${origin}/axe.js` });
  return tab.evaluate(async () => {
    const run = (window as unknown as { axe: { run: (context: unknown, options: unknown) => Promise<{ violations: { id: string; impact: string; nodes: unknown[] }[] }> } }).axe;
    const result = await run.run(document.querySelector('main') ?? document, { resultTypes: ['violations'] });
    return result.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious' || v.id === 'landmark-unique').map((v) => `${v.id} (${v.nodes.length})`);
  });
}

test('the production panel pages drawn by the server, in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  const pages = readdirSync(FOLDER).filter((file) => file.endsWith('.html')).map((file) => file.replace(/\.html$/, ''));
  assert.ok(pages.length >= 15, 'five pages in three languages');
  const server = await serve();
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    for (const page of pages) {
      for (const width of [1440, 390]) {
        await t.test(`${page} at ${width}`, async () => {
          const tab = await browser.newPage({ viewport: { width, height: 900 } });
          const violations = await watchCsp(tab);
          await tab.goto(`${origin}/page/${page}`);
          await tab.waitForLoadState('networkidle');
          assert.deepEqual(violations, [], 'CSP violations');
          assert.deepEqual(await axeOfMain(tab, origin), [], 'axe');
          assert.ok(await tab.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'no page-wide scroll');
          if (width === 1440) {
            const rail = await tab.evaluate(() => document.querySelector('aside.rail')?.getBoundingClientRect().width ?? 0);
            assert.ok(rail >= 240, `the rail keeps its width (${rail} px)`);
          }
          if (page.startsWith('messages-long')) {
            const list = await tab.evaluate(() => {
              const box = document.querySelector('.chat-messages');
              return box ? { top: box.scrollTop, height: box.clientHeight, full: box.scrollHeight } : null;
            });
            assert.ok(list, 'the conversation is on the page');
            assert.ok(list.full > list.height, 'the long conversation scrolls inside its plate');
            assert.ok(list.top + list.height >= list.full - 2, 'it opens at its newest message');
            if (width === 1440) {
              const tall = await tab.evaluate(() => document.documentElement.scrollHeight);
              assert.ok(tall < 1400, `the page stays its own height, not the conversation's (${tall} px)`);
            }
          }
          await tab.close();
        });
      }
    }
  } finally {
    await browser.close();
    server.close();
  }
});
