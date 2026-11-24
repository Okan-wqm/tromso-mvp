// The Production and Sensors islands in a real browser (Playwright on the machine's own Chrome or Edge, as the gallery's
// test): each page mounted as Django mounts it (`{% island %}`: its root, its props as a JSON block, the built module of
// static/islands), with props the pages gave on the dev database (frontend/test/pages/props, captured by
// F:\dev\balik-notes\ui-production\capture_props.py: real readings, never made up), on the product's style sheets in the
// new look and under the product's Content-Security-Policy. It holds, at 1440 and 390 px:
//   - every chart drawn (a canvas per chart with values, words for one without), the window's controls there;
//   - no CSP violation, no critical or serious axe finding, every text at 4.5:1;
//   - nothing scrolls sideways.
// With SHOTS=<folder> it writes the screenshots. It needs `npm run build` (static/islands); without it, it is skipped.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, join, resolve } from 'node:path';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { axeFindings, CSP, lowContrast, watchCsp } from './checks.js';
import { linksOf } from './sheets.js';

const ISLANDS = resolve('static/islands');
const PROPS = resolve('frontend/test/pages/props');
const TYPES: Record<string, string> = { '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' };

const PAGES = [
  { key: 'water-en', island: 'water', props: 'water-props-en.json', lang: 'en', title: 'HA-K01 · Water' },
  { key: 'water-nb', island: 'water', props: 'water-props-nb.json', lang: 'nb', title: 'HA-K01 · Vann' },
  { key: 'sensor-charts-en', island: 'sensor-charts', props: 'sensor-charts-props-en.json', lang: 'en', title: 'Charts' },
];

interface Chunk { file: string; css?: string[]; imports?: string[]; name?: string; isEntry?: boolean }

function entry(name: string): { file: string; css: string[] } {
  const manifest = JSON.parse(readFileSync(join(ISLANDS, '.vite', 'manifest.json'), 'utf8')) as Record<string, Chunk>;
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

const built = existsSync(join(ISLANDS, '.vite', 'manifest.json'));

test('the Production and Sensors islands in a browser', { skip: skipWithout(BROWSERS) || (!built && 'no static/islands build') }, async (t) => {
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
            assert.equal(await tab.locator('.ui-seg button[aria-pressed="true"]').count(), 1, 'the window in force is pressed');
          } else {
            assert.ok(await tab.locator('select[name="target"]').count());
            if (props.chart) await tab.waitForSelector('.ui-chart');
          }
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
