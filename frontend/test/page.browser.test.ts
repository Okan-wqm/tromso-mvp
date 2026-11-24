// A whole server-rendered page of the new look in a real browser (Playwright on the machine's own Chrome or Edge; skipped
// where there is none, never under CI=1): templates/app_base.html with the shell, the strip, every script the page names
// and an island ({% island %}), as Django prints them (frontend/test/pages/shell-next.html, written by manage.py
// layout_pages), served under the server's own Content-Security-Policy (config/settings.py, frontend/test/csp.ts) with
// the nonce the part was rendered with. The island is the component gallery (npm run build:gallery), served at the name
// the fixture manifest gives it. It holds: no CSP violation from the shell's scripts, the import map, the island and its
// stylesheet; the island mounted; the strip asked for and, with no server behind it, saying the alarms cannot be read;
// the way back to the classic look in the user menu. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, join, resolve } from 'node:path';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { policy } from './csp.js';

const GALLERY = resolve('.build/gallery');
const TYPES: Record<string, string> = { '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' };

function gallery(): { file: string; css: string[] } {
  const manifest = JSON.parse(readFileSync(join(GALLERY, 'manifest.json'), 'utf8')) as Record<string, { file: string; css?: string[]; name?: string }>;
  const entry = Object.values(manifest).find((chunk) => chunk.name === 'gallery');
  if (!entry) throw new Error('npm run build:gallery first');
  return { file: entry.file, css: entry.css ?? [] };
}

function serve(): Promise<{ server: Server; asked: string[] }> {
  const asked: string[] = [];
  const built = gallery();
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    asked.push(url.pathname);
    const headers = { 'Content-Security-Policy': policy('layout') };
    let file = '';
    if (url.pathname === '/') {
      response.writeHead(200, { ...headers, 'Content-Type': 'text/html; charset=utf-8' });
      response.end(readFileSync(resolve('frontend/test/pages/shell-next.html')));
      return;
    }
    if (url.pathname === '/ui/strip/') {            // the server cannot answer (a 503): the strip says so
      response.writeHead(503, headers);
      response.end();
      return;
    }
    if (url.pathname === '/static/islands/gallery.js') file = join(GALLERY, built.file);
    else if (url.pathname === '/static/islands/assets/gallery.css') file = join(GALLERY, built.css[0] ?? 'none');
    else if (url.pathname.startsWith('/static/')) file = resolve(`.${url.pathname}`);
    if (file && existsSync(file)) {
      response.writeHead(200, { ...headers, 'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream' });
      response.end(readFileSync(file));
      return;
    }
    response.writeHead(404, headers);
    response.end();
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done({ server, asked })));
}

test('a whole page of the new look, with an island, under the server\'s policy', { skip: skipWithout(BROWSERS) }, async () => {
  assert.ok(existsSync(join('static', 'js', 'shell.js')), 'npm run build first (static/js)');
  const { server, asked } = await serve();
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const violations: string[] = [];
    tab.on('console', (message) => { if (/Content.Security.Policy|Refused to/i.test(message.text())) violations.push(message.text()); });
    await tab.exposeFunction('__cspViolation', (text: string) => { violations.push(text); });
    await tab.addInitScript(() => {
      document.addEventListener('securitypolicyviolation', (event) => {
        (window as unknown as { __cspViolation: (text: string) => void }).__cspViolation(`${event.violatedDirective} ${event.blockedURI}`);
      });
    });
    await tab.goto(origin);
    await tab.waitForSelector('[data-island="gallery"][data-mounted] .ui-plate');
    await tab.waitForSelector('.ui-strip[data-poll-state="unread"]');            // asked for; no server behind it here
    assert.ok(asked.includes('/ui/strip/'), asked.join(' '));
    const said = await tab.evaluate(() => getComputedStyle(document.querySelector('.ui-strip') as Element, '::before').content);
    assert.equal(said, '"Not updated: the alarms cannot be read"');
    assert.equal(await tab.locator('[data-strip="alarms"]').isVisible(), false);  // never "Reading…" for ever
    await tab.click('.user-trigger');
    assert.equal(await tab.getAttribute('[data-look="classic"]', 'href'), '/farm/sites/?ui=classic');
    assert.deepEqual(violations, []);
    await tab.close();
  } finally {
    await browser.close();
    server.close();
  }
});
