// Company › Overview's island in a real browser (Playwright on the machine's own Chrome or Edge; skipped where there is
// none, never under CI=1), mounted with props recorded from the demonstration company (frontend/test/pages/
// company-props-<language>.json, config/company_props.py's answer), on the product's style sheets and under the product's
// Content-Security-Policy, in the new look, in every theme and every language. It holds: no CSP violation, no critical or
// serious axe finding, every text at 4.5:1, every block the props carry drawn, and no sideways scroll at 390 px. With
// SHOTS=<folder> it writes screenshots at 1440 and 390 px. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, join, resolve } from 'node:path';

import type { Page } from 'playwright-core';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { CSP } from './csp.js';
import { linksOf } from './sheets.js';

const THEMES = ['industry', 'fjord', 'polarnatt', 'nordlys', 'tang', 'laks'];
const LANGUAGES = ['en', 'nb', 'tr'];
const GALLERY = resolve('.build/gallery');
const TYPES: Record<string, string> = { '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' };

function entry(name: string): { file: string; css: string[] } {
  const manifest = join(GALLERY, '.vite', 'manifest.json');
  if (!existsSync(manifest)) throw new Error('.build/gallery has no build: run `npm run build:gallery` (npm test does)');
  const found = Object.values(JSON.parse(readFileSync(manifest, 'utf8')) as Record<string, { file: string; css?: string[]; name?: string; isEntry?: boolean }>)
    .find((chunk) => chunk.name === name && chunk.isEntry);
  if (!found) throw new Error(`${name} is not in .build/gallery/.vite/manifest.json`);
  return { file: found.file, css: found.css ?? [] };
}

function props(language: string): unknown {
  return JSON.parse(readFileSync(resolve(`frontend/test/pages/company-props-${language}.json`), 'utf8'));
}

function page(theme: string, language: string): string {
  const island = entry('company');
  return `<!doctype html><html lang="${language}" data-theme="${theme}" data-ui="next"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Overview</title>${linksOf('app_base.html')}${island.css.map((css) => `<link rel="stylesheet" href="/gallery/${css}">`).join('')}</head>
<body><main class="content" id="content" data-measure="fluid"><div class="page-head ui-head"><div class="page-title"><h1>Overview</h1></div></div>
<div class="ui-island" data-island="company" data-props="island-company-1"></div>
<script id="island-company-1" type="application/json">${JSON.stringify(props(language)).replaceAll('<', '\\u003C')}</script>
<script type="module" src="/gallery/${island.file}"></script></main></body></html>`;
}

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    let file = '';
    if (url.pathname.startsWith('/css/') || url.pathname.startsWith('/fonts/') || url.pathname.startsWith('/img/')) file = resolve('static', `.${url.pathname}`);
    else if (url.pathname.startsWith('/gallery/')) file = join(GALLERY, url.pathname.slice('/gallery/'.length));
    else if (url.pathname === '/axe.js') file = resolve('node_modules/axe-core/axe.min.js');
    const headers = { 'Content-Security-Policy': CSP };
    const asked = /^\/page\/([a-z]+)\/([a-z]+)$/.exec(url.pathname);
    if (asked) {
      response.writeHead(200, { ...headers, 'Content-Type': 'text/html; charset=utf-8' });
      response.end(page(asked[1] ?? 'industry', asked[2] ?? 'en'));
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
      (window as unknown as { __cspViolation: (text: string) => void }).__cspViolation(`${event.violatedDirective} ${event.blockedURI}`);
    });
  });
  return violations;
}

async function axe(tab: Page, origin: string): Promise<string[]> {
  await tab.addScriptTag({ url: `${origin}/axe.js` });
  return tab.evaluate(async () => {
    const run = (window as unknown as { axe: { run: (context: unknown, options: unknown) => Promise<{ violations: { id: string; impact: string; nodes: unknown[] }[] }> } }).axe;
    const result = await run.run(document, { resultTypes: ['violations'] });
    return result.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious').map((v) => `${v.id} (${v.nodes.length})`);
  });
}

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
    const selector = '.ui-chip > span, .ui-tile-label, .ui-tile-figure, .ui-tile-sub, .ui-tile-source, .ui-notice-body, .ui-plate-head h2, .ui-plate-meta, .ui-plate-link, .ui-table th, .ui-table td, .ui-list-main, .ui-list-meta, .ui-cell-sub, .ui-audit-record, .ui-audit-who, .ui-empty-title';
    for (const element of document.querySelectorAll(selector)) {
      if (!element.textContent?.trim()) continue;
      const fore = parse(getComputedStyle(element).color).slice(0, 3);
      const [high, lower] = [lum(fore), lum(ground(element))].sort((a, b) => b - a);
      const ratio = ((high ?? 0) + 0.05) / ((lower ?? 0) + 0.05);
      if (ratio < 4.5) low.push(`${element.className || element.tagName} "${element.textContent.trim().slice(0, 30)}" ${ratio.toFixed(2)}`);
    }
    return low;
  });
}

test('Company › Overview\'s island in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  const server = await serve();
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    for (const theme of THEMES) {
      for (const language of LANGUAGES) {
        await t.test(`${theme}, ${language}: every block drawn, no CSP violation, no serious axe finding, text at 4.5:1`, async () => {
          const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
          const violations = await watchCsp(tab);
          await tab.goto(`${origin}/page/${theme}/${language}`);
          await tab.waitForSelector('[data-island="company"][data-mounted] .ui-plate');
          const given = props(language) as Record<string, { title?: string } | null>;
          const titles = await tab.locator('.ui-plate-head h2').allTextContents();
          for (const [key, block] of Object.entries(given)) {
            if (block && block.title) assert.ok(titles.includes(block.title), `${key}: "${block.title}" drawn`);
          }
          assert.deepEqual(violations, [], 'CSP violations');
          assert.deepEqual(await lowContrast(tab), [], 'text under 4.5:1');
          assert.deepEqual(await axe(tab, origin), [], 'axe');
          assert.deepEqual(violations, [], 'CSP violations after axe');
          await tab.close();
        });
      }
    }
    for (const width of [1440, 390]) {
      await t.test(`${width} px: nothing scrolls sideways${process.env.SHOTS ? ', screenshot written' : ''}`, async () => {
        const tab = await browser.newPage({ viewport: { width, height: 900 } });
        await tab.goto(`${origin}/page/industry/en`);
        await tab.waitForSelector('[data-mounted] .ui-plate');
        assert.equal(await tab.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), 0);
        if (process.env.SHOTS) {
          mkdirSync(process.env.SHOTS, { recursive: true });
          await tab.screenshot({ path: join(process.env.SHOTS, `company-island-${width}.png`), fullPage: true });
        }
        await tab.close();
      });
    }
  } finally {
    await browser.close();
    server.close();
  }
});
