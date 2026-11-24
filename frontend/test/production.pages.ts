// The Production and Sensors islands in a real browser (Playwright on the machine's own Chrome or Edge, as the gallery's
// test): each page mounted as Django mounts it (`{% island %}`: its root, its props as a JSON block, the built module of
// static/islands), with the props the real views gave in the test run's database on THE test world (core/test_world.py,
// through farm/tests/test_island_pages.py, kept in .build/island-props by core/island_props.py: never a recording of a
// real database, the repository is public), on the product's style sheets in the new look and under the product's
// Content-Security-Policy. Run by `npm run test:pages` after the Django tests (CI's Django job); a missing build or
// missing props fail it, never skip it. It holds, at 1440 and 390 px:
//   - every chart drawn (a canvas per chart with values, words for one without), the window's controls there;
//   - the window's from and to in the shared date box (a text box, dd.mm.yyyy HH:MM, tidied when left), never the
//     browser's own date box;
//   - Tank › Water: every event a mark on the charts for the pointer (its label shown on hover of its 24 px handle, no
//     Tab stop: the events list is the keyboard's path, each a link); the Deffeyes chart of the window drawn from the
//     server's figure (its pH labels, the water's path), its end without a diagram said as such in the warning's
//     colour (the test world's alkalinity is four days old), and under 480 px its labels left out for their words;
//   - each chart in words for a screen reader (its latest, lowest and highest; its gaps);
//   - no CSP violation, no critical or serious axe finding, every text at 4.5:1;
//   - nothing scrolls sideways.
// With SHOTS=<folder> it writes the screenshots.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, join, resolve } from 'node:path';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { axeFindings, CSP, lowContrast, watchCsp } from './checks.js';
import { linksOf } from './sheets.js';

const ISLANDS = resolve('static/islands');
const PROPS = resolve('.build/island-props');
const TYPES: Record<string, string> = { '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' };

const PAGES = [
  { key: 'water-en', island: 'water', props: 'water-en.json', lang: 'en', title: 'TT-01 · Water' },
  { key: 'water-nb', island: 'water', props: 'water-nb.json', lang: 'nb', title: 'TT-01 · Vann' },
  { key: 'sensor-charts-en', island: 'sensor-charts', props: 'sensor-charts-en.json', lang: 'en', title: 'Charts' },
];

interface Chunk { file: string; css?: string[]; imports?: string[]; name?: string; isEntry?: boolean }

function entry(name: string): { file: string; css: string[] } {
  const manifest = JSON.parse(readFileSync(join(ISLANDS, 'manifest.json'), 'utf8')) as Record<string, Chunk>;
  const found = Object.entries(manifest).find(([, chunk]) => chunk.isEntry && chunk.name === name);
  if (!found) throw new Error(`no island ${name} in static/islands: run npm run build`);
  const [key, chunk] = found;
  const css = [...(chunk.css ?? []), ...(manifest[key]?.imports ?? []).flatMap((child) => manifest[child]?.css ?? [])];
  return { file: chunk.file, css };
}

function html(spec: (typeof PAGES)[number]): string {
  const { file, css } = entry(spec.island);
  const props = readFileSync(join(PROPS, spec.props), 'utf8');
  return `<!doctype html><html lang="${spec.lang}" data-theme="industry" data-ui="next"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>${spec.title}</title>${linksOf('app_base.html')}${css.map((sheet) => `<link rel="stylesheet" href="/islands/${sheet}">`).join('')}</head>
<body><main class="content" id="content" data-measure="fluid"><div class="page-head ui-head"><div class="page-title"><h1>${spec.title}</h1></div></div>
<div class="ui-island" data-island="${spec.island}" data-props="island-${spec.island}-1"></div>
<script id="island-${spec.island}-1" type="application/json">${props.replaceAll('<', '\\u003C')}</script>
<script type="module" src="/islands/${file}"></script></main></body></html>`;
}

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    const headers = { 'Content-Security-Policy': CSP };
    const spec = PAGES.find((each) => url.pathname === `/page/${each.key}`);
    let file = '';
    if (url.pathname.startsWith('/css/') || url.pathname.startsWith('/fonts/') || url.pathname.startsWith('/img/')) file = resolve('static', `.${url.pathname}`);
    else if (url.pathname.startsWith('/islands/')) file = join(ISLANDS, url.pathname.slice('/islands/'.length));
    else if (url.pathname === '/axe.js') file = resolve('node_modules/axe-core/axe.min.js');
    if (spec) {
      response.writeHead(200, { ...headers, 'Content-Type': 'text/html; charset=utf-8' });
      response.end(html(spec));
    } else if (file && existsSync(file)) {
      response.writeHead(200, { ...headers, 'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream' });
      response.end(readFileSync(file));
    } else {
      response.writeHead(404, headers);
      response.end();
    }
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

test('the Production and Sensors islands in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  assert.ok(existsSync(join(ISLANDS, 'manifest.json')), 'static/islands has no build: run npm run build');
  for (const spec of PAGES) {
    assert.ok(existsSync(join(PROPS, spec.props)), `${spec.props} is missing: the Django tests write it (farm.tests.test_island_pages)`);
  }
  const server = await serve();
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    for (const spec of PAGES) {
      const props = JSON.parse(readFileSync(join(PROPS, spec.props), 'utf8')) as Record<string, unknown>;
      for (const width of [1440, 390]) {
        await t.test(`${spec.key} at ${width} px: drawn, no CSP violation, no serious axe finding, 4.5:1, no sideways scroll`, async () => {
          const tab = await browser.newPage({ viewport: { width, height: 900 } });
          const violations = await watchCsp(tab);
          await tab.goto(`${origin}/page/${spec.key}`);
          await tab.waitForSelector(`[data-island="${spec.island}"][data-mounted] .ui-toolbar`);
          if (spec.island === 'water') {
            const places = props.places as { charts: { empty: boolean }[] }[];
            const drawn = places.flatMap((each) => each.charts).filter((chart) => !chart.empty).length;
            if (drawn) await tab.waitForSelector('.ui-series canvas');
            assert.equal(await tab.locator('.ui-series canvas').count() >= drawn, true, 'a canvas per chart with values');
            assert.equal(await tab.locator('.ui-segmented button[aria-pressed="true"]').count(), 1, 'the window in force is pressed');
            const events = props.events as { label: string; when: string; url: string }[];
            if (drawn && events.length) {
              await tab.waitForSelector('.ui-chart-mark');
              const marks = tab.locator('.ui-chart-mark');
              assert.equal(await tab.locator('.ui-chart-mark[tabindex], a.ui-chart-mark').count(), 0, 'no Tab stop per event per chart');
              assert.equal(await marks.first().getAttribute('aria-hidden'), 'true', 'the marks are for the pointer');
              await marks.first().locator('.ui-chart-mark-handle').hover();
              assert.equal(await marks.first().locator('.ui-chart-mark-label').evaluate((label) => getComputedStyle(label).visibility),
                'visible', 'a hovered mark shows its label');
              assert.equal(await tab.locator('.ui-table tbody a').count(), events.length, 'the events list: a link each');
              await tab.mouse.move(0, 0);
            }
            assert.ok(await tab.locator('.ui-chart dl.sr-only dt').count(), 'the charts in words');
            const ranged = props.range_chart as { chart: unknown; path?: string[]; stale?: string } | null;
            if (ranged?.chart) {
              assert.equal(await tab.locator('svg.deffeyes-chart .deffeyes-track').count(), ranged.path?.length ?? 0, 'the path, one line a run');
              if (ranged.stale) {
                assert.equal(await tab.locator('.ui-chart-now[data-status="warning"]', { hasText: ranged.stale }).count(), 1,
                  'the window end without a diagram, said in the warning colour');
              }
              const label = tab.locator('svg.deffeyes-chart .deffeyes-ph').first();
              assert.ok(await tab.locator('svg.deffeyes-chart .deffeyes-ph').count(), 'the pH labels the server placed');
              assert.equal(await label.isVisible(), width >= 1440, 'the pH labels only where they can be read');
              assert.equal(await tab.locator('.deffeyes-scale').isVisible(), width < 1440, 'their words where they are not drawn');
            }
          } else {
            assert.ok(await tab.locator('select[name="target"]').count());
            if (props.chart) await tab.waitForSelector('.ui-chart');
          }
          // the window's from and to: the shared date box, never the browser's own (dd.mm.yyyy HH:MM in every language)
          assert.equal(await tab.locator('input[type="datetime-local"], input[type="date"]').count(), 0, 'no native date box');
          const start = tab.locator('input[name="start"][data-date-input="moment"][type="text"]');
          assert.equal(await start.count(), 1, 'from is the shared date box');
          const typed = await start.inputValue();
          await start.fill('1.2.2026 6:05');
          await start.press('Tab');
          assert.equal(await start.inputValue(), '01.02.2026 06:05', 'the date box tidies what was typed');
          await start.fill(typed);
          assert.deepEqual(violations, [], 'CSP violations');
          assert.deepEqual(await lowContrast(tab), [], 'text under 4.5:1');
          assert.deepEqual(await axeFindings(tab, origin), [], 'axe');
          assert.deepEqual(violations, [], 'CSP violations after axe');
          assert.equal(await tab.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), 0);
          if (process.env.SHOTS) {
            mkdirSync(process.env.SHOTS, { recursive: true });
            await tab.screenshot({ path: join(process.env.SHOTS, `${spec.key}-${width}.png`), fullPage: true });
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
