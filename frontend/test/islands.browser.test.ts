// The islands' component library in a real browser (Playwright on the machine's own Chrome or Edge; skipped where there is
// none, never under CI=1): the component gallery (frontend/test/gallery, built by `npm run build:gallery`) mounted as a
// page mounts an island, on the product's style sheets in the order app_base.html links them, under the product's
// Content-Security-Policy (config/settings.py, SECURE_CSP), in the new look and in every theme. It holds:
//   - no CSP violation, at load and after pressing, typing and switching tabs (React Aria's press rule ships in ds.css);
//   - no critical or serious axe finding;
//   - the text of every button, chip, tile and notice at 4.5:1 on what it stands on, in every theme;
//   - a visible focus on every button and field; a busy button refuses the press; the first invalid field gets the focus;
//   - no horizontal scroll at 390 px.
// With SHOTS=<folder> it also writes screenshots of the gallery at 1440 and 390 px. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, join, resolve } from 'node:path';

import type { Page } from 'playwright-core';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { linksOf } from './sheets.js';

const THEMES = ['industry', 'fjord', 'polarnatt', 'nordlys', 'tang', 'laks'];
const GALLERY = resolve('.build/gallery');
// The product's policy (config/settings.py, SECURE_CSP), without the nonce: a page of islands needs none.
export const CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
  + "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'";
const TYPES: Record<string, string> = { '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' };

// The gallery's entry in the build's manifest, as {% island %} reads it: its module and its stylesheets (uPlot's).
function galleryEntry(): { file: string; css: string[] } {
  const manifest = join(GALLERY, '.vite', 'manifest.json');
  if (!existsSync(manifest)) throw new Error('.build/gallery has no gallery: run `npm run build:gallery` (npm test does)');
  const entry = Object.values(JSON.parse(readFileSync(manifest, 'utf8')) as Record<string, { file: string; css?: string[]; name?: string }>)
    .find((chunk) => chunk.name === 'gallery');
  if (!entry) throw new Error('the gallery is not in .build/gallery/.vite/manifest.json');
  return { file: entry.file, css: entry.css ?? [] };
}

export function page(theme: string, props: unknown): string {
  const entry = galleryEntry();
  return `<!doctype html><html lang="en" data-theme="${theme}" data-ui="next"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Gallery</title>${linksOf('app_base.html')}${entry.css.map((css) => `<link rel="stylesheet" href="/gallery/${css}">`).join('')}</head>
<body><main class="content" id="content" data-measure="fluid"><div class="page-head ui-head"><div class="page-title"><h1>Gallery</h1></div></div>
<div class="ui-island" data-island="gallery" data-props="island-gallery-1"></div>
<script id="island-gallery-1" type="application/json">${JSON.stringify(props).replaceAll('<', '\\u003C')}</script>
<script type="module" src="/gallery/${entry.file}"></script></main></body></html>`;
}

const PROPS = {
  rows: [
    { code: 'FS-01', name: 'Feed store 1', site: 'Test Site South', capacity: '120,000 kg', status: 'ok', word: 'Active' },
    { code: 'SI-02', name: 'Silo 2', site: 'Test Site North', capacity: '5,000 kg', status: 'warning', word: 'Below the reorder level' },
    { code: 'CR-01', name: 'Cold room', site: 'Test Site South', capacity: '8 m³', status: 'neutral', word: 'Inactive' },
  ],
  errors: { organisation_number: ['Enter nine digits, with or without spaces.'] },
};

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    let file = '';
    if (url.pathname.startsWith('/css/') || url.pathname.startsWith('/fonts/') || url.pathname.startsWith('/img/')) file = resolve('static', `.${url.pathname}`);
    else if (url.pathname.startsWith('/gallery/')) file = join(GALLERY, url.pathname.slice('/gallery/'.length));
    else if (url.pathname === '/axe.js') file = resolve('node_modules/axe-core/axe.min.js');     // from its own address, as the policy allows
    const headers = { 'Content-Security-Policy': CSP };
    if (url.pathname.startsWith('/page/')) {
      response.writeHead(200, { ...headers, 'Content-Type': 'text/html; charset=utf-8' });
      response.end(page(url.pathname.slice('/page/'.length), PROPS));
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

async function watchCsp(tab: Page): Promise<string[]> {
  const violations: string[] = [];
  tab.on('console', (message) => { if (/Content.Security.Policy|Refused to/i.test(message.text())) violations.push(message.text()); });
  await tab.exposeFunction('__cspViolation', (text: string) => { violations.push(text); });
  await tab.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (event) => {
      (window as unknown as { __cspViolation: (text: string) => void }).__cspViolation(`${event.violatedDirective} ${event.blockedURI} ${event.sample}`);
    });
  });
  return violations;
}

// [selector of a text element, its text colour, the colour of the ground it stands on, contrast] for every low pair
async function lowContrast(tab: Page): Promise<string[]> {
  return tab.evaluate(() => {
    const parse = (value: string): number[] => (value.match(/[\d.]+/g) ?? []).map(Number);
    const lum = ([r = 0, g = 0, b = 0]: number[]): number => {
      const c = [r, g, b].map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
      return 0.2126 * (c[0] ?? 0) + 0.7152 * (c[1] ?? 0) + 0.0722 * (c[2] ?? 0);
    };
    const ground = (element: Element): number[] => {
      for (let at: Element | null = element; at; at = at.parentElement) {
        const value = parse(getComputedStyle(at).backgroundColor);
        if (value.length === 3 || (value[3] ?? 0) > 0.5) return value.slice(0, 3);
      }
      return parse(getComputedStyle(document.body).backgroundColor).slice(0, 3);
    };
    const low: string[] = [];
    const selector = '.ui-btn:not(:disabled):not([aria-disabled="true"]), .ui-chip > span, .ui-tile-label, .ui-tile-figure, .ui-tile-sub, .ui-tile-source, .ui-notice-body, .ui-plate-head h2, .ui-plate-meta, .ui-plate-link, .help, .errorlist li, .ui-table th, .ui-table td, .ui-tab, .ui-empty-text, .ui-chart-caption, .field label';
    for (const element of document.querySelectorAll(selector)) {
      if (!element.textContent?.trim()) continue;
      const fore = parse(getComputedStyle(element).color).slice(0, 3);
      const back = ground(element);
      const [high, lower] = [lum(fore), lum(back)].sort((a, b) => b - a);
      const ratio = ((high ?? 0) + 0.05) / ((lower ?? 0) + 0.05);
      if (ratio < 4.5) low.push(`${element.className || element.tagName} "${element.textContent.trim().slice(0, 30)}" ${ratio.toFixed(2)}`);
    }
    return low;
  });
}

test('the islands\' component library in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  const server = await serve();
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    for (const theme of THEMES) {
      await t.test(`${theme}: mounted, no CSP violation, no serious axe finding, every text at 4.5:1`, async () => {
        const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
        const violations = await watchCsp(tab);
        await tab.goto(`${origin}/page/${theme}`);
        await tab.waitForSelector('[data-island="gallery"][data-mounted] .ui-plate');
        await tab.click('#b-busy');
        await tab.keyboard.press('Tab');
        await tab.click('.ui-tabs [role="tab"]:nth-child(2)');
        await tab.fill('input[name="name"]', 'Test Site East');
        assert.deepEqual(violations, [], 'CSP violations');
        assert.deepEqual(await lowContrast(tab), [], 'text under 4.5:1');
        await tab.addScriptTag({ url: `${origin}/axe.js` });
        const found = await tab.evaluate(async () => {
          const axe = (window as unknown as { axe: { run: (context: unknown, options: unknown) => Promise<{ violations: { id: string; impact: string; nodes: unknown[] }[] }> } }).axe;
          const result = await axe.run(document, { resultTypes: ['violations'] });
          return result.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious').map((v) => `${v.id} (${v.nodes.length})`);
        });
        assert.deepEqual(found, [], 'axe');
        assert.deepEqual(violations, [], 'CSP violations after axe');
        await tab.close();
      });
    }

    await t.test('states: busy refuses a second press, the first invalid field has the focus, focus is visible', async () => {
      const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      await tab.goto(`${origin}/page/industry`);
      await tab.waitForSelector('[data-mounted] .ui-plate');
      assert.equal(await tab.evaluate(() => document.activeElement?.getAttribute('name')), 'organisation_number');
      assert.equal(await tab.getAttribute('input[name="organisation_number"]', 'aria-invalid'), 'true');
      await tab.click('#b-busy');
      assert.equal(await tab.getAttribute('#b-busy', 'data-pending'), 'true');
      assert.equal(await tab.getAttribute('#b-busy', 'aria-disabled'), 'true');
      assert.equal(await tab.locator('#b-busy .ui-spinner').count(), 1);
      // the series is drawn by uPlot on a canvas; a frame without values says so in words
      await tab.waitForSelector('.ui-series canvas');
      assert.equal(await tab.locator('.ui-chart-empty').first().textContent(), 'No values in this range.');
      for (const selector of ['#b-primary', '#b-secondary', '#b-ghost', '#b-danger', 'input[name="name"]', 'select[name="site"]']) {
        await tab.focus(selector);
        await tab.keyboard.press('Shift+Tab');
        await tab.keyboard.press('Tab');
        const ring = await tab.evaluate((s) => {
          const style = getComputedStyle(document.querySelector(s) as Element);
          return style.outlineStyle !== 'none' && style.outlineWidth !== '0px' || style.boxShadow !== 'none';
        }, selector);
        assert.ok(ring, `${selector} shows its focus`);
      }
      // the registration marks of the new look: a plate and the primary button draw them, a secondary does not
      const marks = await tab.evaluate(() => ['.ui-plate', '#b-primary', '#b-secondary'].map((s) => getComputedStyle(document.querySelector(s) as Element, '::before').backgroundImage.includes('linear-gradient')));
      assert.deepEqual(marks, [true, true, false]);
      await tab.close();
    });

    await t.test('the watch sees a violation: an inline style, as React Aria would add without its marker, is refused and reported', async () => {
      const tab = await browser.newPage();
      const violations = await watchCsp(tab);
      await tab.goto(`${origin}/page/industry`);
      await tab.waitForSelector('[data-mounted] .ui-plate');
      await tab.evaluate(() => { const style = document.createElement('style'); style.textContent = '[data-x] { color: red; }'; document.head.append(style); });
      await tab.waitForTimeout(200);
      assert.ok(violations.some((line) => line.includes('style-src')), violations.join('\n'));
      await tab.close();
    });

    for (const width of [1440, 390]) {
      await t.test(`${width} px: nothing scrolls sideways${process.env.SHOTS ? ', screenshot written' : ''}`, async () => {
        const tab = await browser.newPage({ viewport: { width, height: 900 } });
        await tab.goto(`${origin}/page/industry`);
        await tab.waitForSelector('[data-mounted] .ui-plate');
        const overflow = await tab.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        assert.equal(overflow, 0);
        // six tiles of a whole-width plate: one row at 1440 px (as the design), two to a row on a phone
        const rows = await tab.evaluate(() => new Set([...document.querySelectorAll('[aria-label="Company today"] .ui-tile')]
          .map((tile) => Math.round(tile.getBoundingClientRect().top))).size);
        assert.equal(rows, width === 1440 ? 1 : 3);
        if (process.env.SHOTS) {
          mkdirSync(process.env.SHOTS, { recursive: true });
          await tab.screenshot({ path: join(process.env.SHOTS, `gallery-${width}.png`), fullPage: true });
          for (const theme of ['polarnatt', 'laks']) {
            await tab.evaluate((name) => { document.documentElement.dataset.theme = name; }, theme);
            await tab.screenshot({ path: join(process.env.SHOTS, `gallery-${width}-${theme}.png`), fullPage: true });
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
