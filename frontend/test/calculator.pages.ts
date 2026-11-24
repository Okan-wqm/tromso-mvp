// The water calculator and its printed report in the new look, in a real browser (Playwright on the machine's own Chrome
// or Edge): the pages as Django printed them in the test run's database on THE test world (core/test_world.py, through
// farm/tests/test_island_pages.py, kept whole in .build/island-props by core/island_props.py `keep_page`: never a
// recording of a real database, the repository is public), served with the product's static files under the product's
// Content-Security-Policy and the nonce each page was printed with. The calculator is a server-rendered GET form whose
// results are the server's live parts (frontend/poll.ts swaps them in): there is no island and no JSON, so the test
// serves the parts the same run printed for the results address. Run by `npm run test:pages` after the Django tests
// (CI's Django job); a missing build or a missing page fails it, never skips it. It holds, at 1440 and 390 px, in
// English and Norwegian:
//   - the values plate (where the values come from: TT-01's latest values; the tabs), the four small charts, the Water
//     Quality Management Chart with the pH labels the server placed and its layers as boxes, the results and the
//     simulator's steps;
//   - a value typed: the results address asked with the form's values, and the live parts swapped in;
//   - the printed report in the new look (its own page, data-ui on it), and on A4 across (SHOTS: a PDF of it);
//   - the printed report in BOTH looks keeps every row inside its table, on the screen and on paper: a value with its
//     judgement in words (the best estimate's note) wraps in its column, never pushes the values past the page's edge;
//   - no CSP violation, no critical or serious axe finding, every text at 4.5:1, nothing scrolls sideways.
// With SHOTS=<folder> it writes the screenshots.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, join, resolve } from 'node:path';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { axeFindings, lowContrast, watchCsp } from './checks.js';
import { policy } from './csp.js';

const PAGES = resolve('.build/island-props');
const STATIC = resolve('static');
const TYPES: Record<string, string> = { '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' };
const LANGUAGES = ['en', 'nb'];
// The calculator's three addresses (farm/urls.py) and the page each serves, as the Django test kept them.
const ROUTES: Record<string, string> = {
  '/operations/water/calculator/': 'page',
  '/operations/water/calculator/results/': 'parts',
  '/operations/water/calculator/report/': 'report',
};

function kept(view: string, language: string): string {
  return join(PAGES, `calculator-${view}-${language}.html`);
}

/** The nonce Django printed the page with (the import map carries it): the policy the server sent with it allows it. */
function nonceOf(html: string): string {
  return /nonce="([^"]+)"/.exec(html)?.[1] ?? '';
}

function serve(asked: string[]): Promise<Server> {
  let language = 'en';
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    asked.push(url.pathname + url.search);
    if (url.searchParams.get('lang')) language = url.searchParams.get('lang') ?? 'en';
    const view = ROUTES[url.pathname];
    if (view) {
      const html = readFileSync(kept(view === 'report' && url.searchParams.get('look') === 'classic' ? 'report-classic' : view, language), 'utf8');
      response.writeHead(200, { 'Content-Security-Policy': policy(nonceOf(html)), 'Content-Type': 'text/html; charset=utf-8' });
      response.end(html);
      return;
    }
    const headers = { 'Content-Security-Policy': policy() };
    if (url.pathname === '/ui/strip/') {            // the strip's own address: no server behind it here, it says so
      response.writeHead(503, headers);
      response.end();
      return;
    }
    let file = '';
    if (url.pathname.startsWith('/static/')) file = join(STATIC, url.pathname.slice('/static/'.length));
    else if (url.pathname === '/axe.js') file = resolve('node_modules/axe-core/axe.min.js');
    if (file.startsWith(STATIC) || file.endsWith('axe.min.js')) {
      if (existsSync(file)) {
        response.writeHead(200, { ...headers, 'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream' });
        response.end(readFileSync(file));
        return;
      }
    }
    response.writeHead(404, headers);
    response.end();
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

test('the water calculator and its report in the new look, in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  assert.ok(existsSync(join(STATIC, 'js', 'poll.js')), 'static/js has no build: run npm run build');
  for (const language of LANGUAGES) {
    for (const view of [...Object.values(ROUTES), 'report-classic']) {
      assert.ok(existsSync(kept(view, language)), `${kept(view, language)} is missing: the Django tests write it (farm.tests.test_island_pages)`);
    }
  }
  const asked: string[] = [];
  const server = await serve(asked);
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    for (const language of LANGUAGES) {
      for (const width of [1440, 390]) {
        await t.test(`calculator-${language} at ${width} px: drawn, live, no CSP violation, no serious axe finding, 4.5:1, no sideways scroll`, async () => {
          const tab = await browser.newPage({ viewport: { width, height: 900 } });
          const violations = await watchCsp(tab);
          await tab.goto(`${origin}/operations/water/calculator/?lang=${language}`);
          await tab.waitForSelector('html[data-ui="next"] form.calc[data-live] .calc-values-plate');
          assert.ok(await tab.locator('[data-tabs]:not([hidden]) [role="tab"]').count() >= 6, 'the values in tabs');
          assert.ok((await tab.locator('[data-live-part="source"] .calc-offer').count()) > 0, 'TT-01\'s values, each with its age');
          assert.equal(await tab.locator('.calc-plot').count(), 4, 'the four small charts');
          assert.ok(await tab.locator('svg.deffeyes-chart .deffeyes-ph').count(), 'the pH labels the server placed');
          assert.ok(await tab.locator('.calc-layers input[type="checkbox"]').count(), 'the layers, each a box');
          assert.ok(await tab.locator('.calc-simulator:not([hidden]) table.calc-steps tbody tr').count() >= 2, 'the simulator\'s steps');
          assert.equal(await tab.locator('.calc-results .calc-status').count(), 3, 'ammonia, hydrogen sulfide and the CO₂ judged');
          assert.ok(await tab.locator('.calc-results .calc-tiles dd').count() >= 6, 'the values worked out as tiles');
          assert.equal(await tab.locator('.calc-results tr[data-tile]').first().isVisible(), false, 'said once: as a tile, not again in the card');
          assert.ok((await tab.locator('.calc-chart-words').textContent())?.startsWith('pH '), 'the water of the chart in one line');
          // a value typed: the server is asked with the form's values and its parts replace the page's
          await tab.evaluate(() => { (document.querySelector('[data-live-part="results"]') as HTMLElement).dataset.drawn = 'before'; });
          const before = asked.length;
          const field = tab.locator('input[name="temperature_c"]');
          await field.fill('13.5');
          await tab.waitForSelector('[data-live-part="results"]:not([data-drawn])');
          const results = asked.slice(before).find((each) => each.startsWith('/operations/water/calculator/results/'));
          assert.ok(results?.includes('temperature_c=13.5'), `the results asked with the value typed: ${asked.slice(before).join(' ')}`);
          assert.equal(await field.inputValue(), '13.5', 'the field is never in a part: what was typed stays');
          assert.deepEqual(violations, [], 'CSP violations');
          assert.deepEqual(await lowContrast(tab), [], 'text under 4.5:1');
          // the page's own content; the shell around it (the language buttons, the user menu) is the foundation's
          assert.deepEqual(await axeFindings(tab, origin, '#content'), [], 'axe');
          assert.deepEqual(violations, [], 'CSP violations after axe');
          assert.equal(await tab.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), 0);
          if (process.env.SHOTS) {
            mkdirSync(process.env.SHOTS, { recursive: true });
            await tab.screenshot({ path: join(process.env.SHOTS, `calculator-${language}-${width}.png`), fullPage: true });
          }
          await tab.close();
        });
      }
      await t.test(`calculator-report-${language}: the new look, no CSP violation, no serious axe finding, 4.5:1, A4 across`, async () => {
        const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
        const violations = await watchCsp(tab);
        await tab.goto(`${origin}/operations/water/calculator/report/?lang=${language}`);
        await tab.waitForSelector('html[data-ui="next"] body.report .calc-results .calc-status');
        assert.ok(await tab.locator('svg.deffeyes-chart .deffeyes-ph').count(), 'the chart with every layer');
        assert.ok(await tab.locator('.calc-simulator table.calc-steps tbody tr').count() >= 2, 'the simulator\'s steps');
        assert.equal(await tab.locator('[data-print]:not([hidden])').count(), 1, 'its Print button, shown by the script');
        assert.deepEqual(violations, [], 'CSP violations');
        assert.deepEqual(await lowContrast(tab), [], 'text under 4.5:1');
        assert.deepEqual(await axeFindings(tab, origin), [], 'axe');
        assert.equal(await tab.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), 0);
        if (process.env.SHOTS) {
          mkdirSync(process.env.SHOTS, { recursive: true });
          await tab.screenshot({ path: join(process.env.SHOTS, `calculator-report-${language}-1440.png`), fullPage: true });
          await tab.pdf({ path: join(process.env.SHOTS, `calculator-report-${language}-a4.pdf`), format: 'A4', landscape: true, printBackground: true });
        }
        await tab.close();
      });
      await t.test(`calculator-report-${language}, both looks: every row inside its table, on the screen and on A4 across`, async () => {
        const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
        // the tables' cells that reach past their table's frame (a value pushed out of the page), in CSS pixels
        const overflowing = () => tab.evaluate(() => [...document.querySelectorAll('.report-table')].flatMap((table) => {
          const frame = (table.closest('.table-wrap') ?? table).getBoundingClientRect();
          return [...table.querySelectorAll('td, th')].filter((cell) => cell.getBoundingClientRect().right > frame.right + 1)
            .map((cell) => (cell.textContent ?? '').trim().slice(0, 40));
        }));
        for (const look of ['classic', 'next']) {
          await tab.emulateMedia({ media: 'screen' });
          await tab.setViewportSize({ width: 1440, height: 900 });
          await tab.goto(`${origin}/operations/water/calculator/report/?lang=${language}${look === 'classic' ? '&look=classic' : ''}`);
          await tab.waitForSelector('.report-table td.num');
          assert.equal(await tab.locator('html[data-ui="next"]').count(), look === 'next' ? 1 : 0);
          assert.deepEqual(await overflowing(), [], `${look}: cells past their table on the screen`);
          await tab.emulateMedia({ media: 'print' });
          await tab.setViewportSize({ width: 1047, height: 734 });        // A4 across, less the 8 mm margins, in CSS pixels
          assert.deepEqual(await overflowing(), [], `${look}: cells past their table on paper`);
          assert.equal(await tab.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), 0,
            `${look}: the page wider than the paper`);
          if (process.env.SHOTS && look === 'classic') {
            await tab.pdf({ path: join(process.env.SHOTS, `calculator-report-classic-${language}-a4.pdf`), format: 'A4', landscape: true, printBackground: true });
          }
        }
        await tab.close();
      });
    }
  } finally {
    await browser.close();
    server.close();
  }
});
