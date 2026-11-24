// The rest of Production and Sensors in a real browser (Playwright on the machine's own Chrome or Edge): the Sensors lists
// (the shared list page), Sensors › Overview, Production › Overview and Production units, each mounted as Django mounts it
// (`{% island %}`: its root, its props as a JSON block, the built module of static/islands) with the props the real views
// gave in the test run's database on THE test world (sensors/tests/test_pages_next.py and the Production tests keep them
// in .build/island-props as {island, props}, core/island_props.py: never a recording of a real database), on the
// product's style sheets in the new look and under the product's Content-Security-Policy. Run by `npm run test:pages`
// after the Django tests (CI's Django job); missing props or build fail it, never skip it. It holds, at 1440 and 390 px:
//   - the page drawn (a table, tiles or the empty state);
//   - nothing opens the classic dialog;
//   - no CSP violation, no critical or serious axe finding, every text at 4.5:1;
//   - nothing scrolls sideways.
// With SHOTS=<folder> it writes the screenshots.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readdirSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, join, resolve } from 'node:path';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { axeFindings, CSP, lowContrast, watchCsp } from './checks.js';
import { linksOf } from './sheets.js';

const ISLANDS = resolve('static/islands');
const PROPS = resolve('.build/island-props');
const TYPES: Record<string, string> = { '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' };
// the pages of this test: the props files their Django tests keep, by name
const PREFIXES = ['sensors-', 'production-'];

interface Kept { island: string; props: unknown }
interface Chunk { file: string; css?: string[]; imports?: string[]; name?: string; isEntry?: boolean }

function pages(): string[] {
  return existsSync(PROPS) ? readdirSync(PROPS).filter((name) => PREFIXES.some((prefix) => name.startsWith(prefix)) && name.endsWith('.json'))
    .map((name) => name.slice(0, -'.json'.length)).sort() : [];
}

function kept(key: string): Kept {
  return JSON.parse(readFileSync(join(PROPS, `${key}.json`), 'utf8')) as Kept;
}

function entry(name: string): { file: string; css: string[] } {
  const manifest = JSON.parse(readFileSync(join(ISLANDS, 'manifest.json'), 'utf8')) as Record<string, Chunk>;
  const found = Object.entries(manifest).find(([, chunk]) => chunk.isEntry && chunk.name === name);
  if (!found) throw new Error(`no island ${name} in static/islands: run npm run build`);
  const [key, chunk] = found;
  return { file: chunk.file, css: [...(chunk.css ?? []), ...(manifest[key]?.imports ?? []).flatMap((child) => manifest[child]?.css ?? [])] };
}

function html(key: string): string {
  const { island, props } = kept(key);
  const { file, css } = entry(island);
  const lang = key.split('-').at(-1) ?? 'en';
  return `<!doctype html><html lang="${lang}" data-theme="industry" data-ui="next"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>${key}</title>${linksOf('app_base.html')}${css.map((sheet) => `<link rel="stylesheet" href="/islands/${sheet}">`).join('')}</head>
<body><main class="content" id="content" data-measure="fluid"><div class="page-head ui-head"><div class="page-title"><h1>${key}</h1></div></div>
<div class="ui-island" data-island="${island}" data-props="island-${island}-1"></div>
<script id="island-${island}-1" type="application/json">${JSON.stringify(props).replaceAll('<', '\\u003C')}</script>
<script type="module" src="/islands/${file}"></script></main></body></html>`;
}

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    const headers = { 'Content-Security-Policy': CSP };
    const asked = /^\/page\/([\w-]+)$/.exec(url.pathname)?.[1];
    let file = '';
    if (url.pathname.startsWith('/css/') || url.pathname.startsWith('/fonts/') || url.pathname.startsWith('/img/')) file = resolve('static', `.${url.pathname}`);
    else if (url.pathname.startsWith('/islands/')) file = join(ISLANDS, url.pathname.slice('/islands/'.length));
    else if (url.pathname === '/axe.js') file = resolve('node_modules/axe-core/axe.min.js');
    if (asked && pages().includes(asked)) {
      response.writeHead(200, { ...headers, 'Content-Type': 'text/html; charset=utf-8' });
      response.end(html(asked));
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

test('the rest of Production and Sensors in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  assert.ok(existsSync(join(ISLANDS, 'manifest.json')), 'static/islands has no build: run npm run build');
  const keys = pages();
  assert.ok(keys.some((key) => key.startsWith('sensors-')), 'no Sensors props: sensors.tests.test_pages_next writes them');
  const server = await serve();
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    for (const key of keys) {
      const { island } = kept(key);
      for (const width of [1440, 390]) {
        await t.test(`${key} at ${width} px: drawn, no dialog link, no CSP violation, no serious axe finding, 4.5:1, no sideways scroll`, async () => {
          const tab = await browser.newPage({ viewport: { width, height: 900 } });
          const violations = await watchCsp(tab);
          await tab.goto(`${origin}/page/${key}`);
          await tab.waitForSelector(`[data-island="${island}"][data-mounted] :is(table, .ui-tiles, .ui-empty, .ui-plate)`);
          assert.equal(await tab.locator('[data-modal]').count(), 0, 'nothing opens the classic dialog');
          assert.deepEqual(violations, [], 'CSP violations');
          assert.deepEqual(await lowContrast(tab), [], 'text under 4.5:1');
          assert.deepEqual(await axeFindings(tab, origin), [], 'axe');
          assert.deepEqual(violations, [], 'CSP violations after axe');
          assert.ok(await tab.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'no sideways scroll');
          if (process.env.SHOTS) {
            mkdirSync(process.env.SHOTS, { recursive: true });
            await tab.screenshot({ path: join(process.env.SHOTS, `${key}-${width}.png`), fullPage: true });
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
