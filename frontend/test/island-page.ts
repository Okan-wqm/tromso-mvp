// An island page in a real browser for the page islands' tests (frontend/test/company.browser.test.ts,
// recordform.browser.test.ts): the island built into the gallery (.build/gallery, `npm run build:gallery`) mounted with
// given props in a page on the product's style sheets, in the new look, served under the product's Content-Security-
// Policy; a watch on CSP violations, axe, and the contrast of the texts. Test code only.
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, join, resolve } from 'node:path';

import type { Page } from 'playwright-core';

import { CSP } from './csp.js';
import { linksOf } from './sheets.js';

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

/** The page of island `name` with `props`, in `theme` and `language`. */
export function islandPage(name: string, props: unknown, theme: string, language: string, heading: string): string {
  const island = entry(name);
  return `<!doctype html><html lang="${language}" data-theme="${theme}" data-ui="next"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>${heading}</title>${linksOf('app_base.html')}${island.css.map((css) => `<link rel="stylesheet" href="/gallery/${css}">`).join('')}</head>
<body><main class="content" id="content" data-measure="fluid"><div class="page-head ui-head"><div class="page-title"><h1>${heading}</h1></div></div>
<div class="ui-island" data-island="${name}" data-props="island-${name}-1"></div>
<script id="island-${name}-1" type="application/json">${JSON.stringify(props).replaceAll('<', '\\u003C')}</script>
<script type="module" src="/gallery/${island.file}"></script></main></body></html>`;
}

/** A server of /page/<theme>/<language> (the page `page` gives) and the style sheets, fonts, gallery build and axe. */
export function serve(page: (theme: string, language: string) => string): Promise<Server> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    const headers = { 'Content-Security-Policy': CSP };
    const asked = /^\/page\/([a-z]+)\/([a-z]+)$/.exec(url.pathname);
    let file = '';
    if (url.pathname.startsWith('/css/') || url.pathname.startsWith('/fonts/') || url.pathname.startsWith('/img/')) file = resolve('static', `.${url.pathname}`);
    else if (url.pathname.startsWith('/gallery/')) file = join(GALLERY, url.pathname.slice('/gallery/'.length));
    else if (url.pathname === '/axe.js') file = resolve('node_modules/axe-core/axe.min.js');
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

export async function watchCsp(tab: Page): Promise<string[]> {
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

export async function axe(tab: Page, origin: string): Promise<string[]> {
  await tab.addScriptTag({ url: `${origin}/axe.js` });
  return tab.evaluate(async () => {
    const run = (window as unknown as { axe: { run: (context: unknown, options: unknown) => Promise<{ violations: { id: string; impact: string; nodes: unknown[] }[] }> } }).axe;
    const result = await run.run(document, { resultTypes: ['violations'] });
    return result.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious').map((v) => `${v.id} (${v.nodes.length})`);
  });
}

/** [element "text" ratio] of every text under 4.5:1 on what it stands on, among `selector`'s elements. */
export async function lowContrast(tab: Page, selector: string): Promise<string[]> {
  return tab.evaluate((wanted) => {
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
    for (const element of document.querySelectorAll(wanted)) {
      if (!element.textContent?.trim() || !(element as HTMLElement).offsetParent) continue;
      const fore = parse(getComputedStyle(element).color).slice(0, 3);
      const [high, lower] = [lum(fore), lum(ground(element))].sort((a, b) => b - a);
      const ratio = ((high ?? 0) + 0.05) / ((lower ?? 0) + 0.05);
      if (ratio < 4.5) low.push(`${element.className || element.tagName} "${element.textContent.trim().slice(0, 30)}" ${ratio.toFixed(2)}`);
    }
    return low;
  }, selector);
}
