// The card designer in a real browser (Playwright on the machine's own Chrome or Edge; skipped where there is none):
// the keyboard moves and the history, a drag as one entry, the palette, the inspector, the preview refreshing without
// moving the focus, the announcements, and no serious accessibility violation (axe-core). The page is the designer's
// markup with a stub preview server; the scripts are the compiled TypeScript of this build (.build/test). Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, join, resolve } from 'node:path';

import { chromium, type Browser, type Page } from 'playwright-core';

const BROWSERS = [
  process.env.CHROME_PATH ?? '',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
].filter((path) => path && existsSync(path));
const BUILD = resolve('.build/test');
const SIZES = JSON.parse(readFileSync('monitoring/tests/layout_vectors.json', 'utf8')).sizes as
  Record<string, [number, number, number, number]>;

const CATALOGUE = {
  columns: 12, schema: 1, max_widgets: 40,
  widgets: Object.entries(SIZES).map(([type, [minW, minH, maxW, maxH]]) => ({
    type, label: `w-${type}`, min_w: minW, min_h: minH, max_w: maxW, max_h: maxH, default_w: Math.max(minW, 3),
    default_h: minH, bind: type === 'value' || type === 'bar' ? 'parameter' : 'none', enabled: type !== 'spark',
    options: type === 'feeding' ? [{ name: 'week', label: 'opt-week', type: 'boolean' }] : [],
  })),
  parameters: [{ value: 'oxygen_mg_l', label: 'p-oxygen', short: 'o2' }, { value: 'ph', label: 'p-ph', short: 'ph' }],
  points: [{ value: 'middle', label: 'pt-middle' }, { value: 'inlet', label: 'pt-inlet' }],
};
const LAYOUT = { schema: 1, widgets: [
  { id: 'w1', type: 'tasks', x: 0, y: 0, w: 3, h: 2 },
  { id: 'w2', type: 'value', x: 3, y: 0, w: 3, h: 2, bind: { parameter: 'oxygen_mg_l' } },
] };
const LABELS = ['undo', 'redo', 'revert', 'remove', 'x', 'y', 'w', 'h', 'binding', 'point', 'middle', 'palette', 'canvas',
                'order', 'none', 'errors', 'warnings', 'frame'];

function page(): string {
  const labels = LABELS.map((name) => `data-label-${name}="l-${name}"`).join(' ');
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>designer</title>
<style>.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.designer-canvas{--row-px:28;position:relative;display:grid;grid-template-columns:repeat(12,minmax(0,1fr));grid-auto-rows:28px;
min-height:224px;padding-top:36px;width:600px}.designer-frame{position:absolute;inset:0 0 auto 0;height:32px}
.designer-item{grid-column:calc(var(--x) + 1)/span var(--w);grid-row:calc(var(--y) + 1)/span var(--h);margin:2px;position:relative}
.designer-handle{position:absolute;right:0;bottom:0;width:14px;height:14px}</style></head><body><main>
<form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="t"><input name="name" value="Mine" aria-label="name">
<div class="designer" data-designer data-preview-url="/preview" data-announce-moved="{label} moved to {x},{y}"
 data-announce-resized="{label} sized {w}x{h}" data-announce-added="{label} added" data-announce-removed="{label} removed"
 data-announce-preview="updated" ${labels}>
 <div data-designer-palette></div>
 <button type="button" data-designer-undo>l-undo</button><button type="button" data-designer-redo>l-redo</button>
 <button type="button" data-designer-revert>l-revert</button><label><input type="checkbox" data-designer-lines checked> lines</label>
 <div data-designer-canvas class="designer-canvas"></div><aside data-designer-inspector></aside>
 <nav data-designer-order></nav><div data-designer-problems role="status"></div>
 <label>unit <select data-designer-unit><option value="u1">T-01</option></select></label>
 <label>state <select data-designer-state><option value="">own</option></select></label>
 <label>width <select data-designer-width><option value="26rem">card</option></select></label>
 <div data-designer-preview></div><p class="sr-only" data-designer-status aria-live="polite"></p>
 <textarea name="layout" aria-label="layout" data-designer-layout>${JSON.stringify(LAYOUT)}</textarea>
</div></form></main>
<script id="card-catalogue" type="application/json">${JSON.stringify(CATALOGUE)}</script>
<script type="module" src="/js/designer.js"></script></body></html>`;
}

let previews = 0;

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    if (request.url === '/') {
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(page());
      return;
    }
    if (request.url === '/preview') {
      previews += 1;
      const answer = { html: `<article data-key="card:u1"><h3>T-01</h3><button type="button" id="pv-${previews}">x</button></article>`,
                       problems: [{ severity: 'warning', widget: '', code: 'no_oxygen', message: 'msg-warning' }] };
      setTimeout(() => response.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(answer)), 50);
      return;
    }
    const file = join(BUILD, (request.url ?? '').replace(/^\/js\//, ''));
    if (request.url?.startsWith('/js/') && file.startsWith(BUILD) && existsSync(file)) {
      response.writeHead(200, { 'Content-Type': extname(file) === '.js' ? 'text/javascript' : 'text/plain' })
        .end(readFileSync(file));
      return;
    }
    response.writeHead(404).end();
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

async function layoutOf(tab: Page): Promise<{ widgets: { id: string; x: number; y: number; w: number; h: number }[] }> {
  return JSON.parse(await tab.inputValue('[data-designer-layout]'));
}

async function settled(tab: Page): Promise<void> {
  const before = previews;
  await tab.waitForTimeout(700);                          // the preview waits 400 ms after a change, the stub 50 ms
  if (previews === before) {
    await tab.waitForTimeout(300);
  }
}

test('the designer in a browser', { skip: BROWSERS.length ? false : 'no Chrome or Edge on this machine' }, async (t) => {
  const server = await serve();
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser: Browser = await chromium.launch({ executablePath: BROWSERS[0], headless: true });
  try {
    const tab = await browser.newPage();
    const errors: string[] = [];
    tab.on('pageerror', (error) => errors.push(error.message));
    await tab.goto(`${origin}/`);
    await tab.waitForSelector('#designer-w1');

    await t.test('an arrow moves the selected widget, announced, and undo takes it back', async () => {
      await tab.click('#designer-w1');
      await tab.keyboard.press('ArrowDown');                // nothing above to fall into: the layout stays compact
      assert.equal((await layoutOf(tab)).widgets[0].y, 0);
      await tab.keyboard.press('ArrowRight');               // w2 is pushed down out of its way
      assert.deepEqual((await layoutOf(tab)).widgets[0], { id: 'w1', type: 'tasks', x: 1, y: 0, w: 3, h: 2 });
      assert.match(await tab.textContent('[data-designer-status]') ?? '', /w-tasks moved to 2,1/);
      assert.equal(await tab.evaluate(() => document.activeElement?.id), 'designer-w1');
      await tab.click('[data-designer-undo]');
      assert.equal((await layoutOf(tab)).widgets[0].x, 0);
      await tab.keyboard.down('Shift');
      await tab.focus('#designer-w1');
      await tab.keyboard.press('ArrowDown');
      await tab.keyboard.up('Shift');
      assert.equal((await layoutOf(tab)).widgets[0].h, 3);
    });

    await t.test('a drag is one entry in the history', async () => {
      const box = await tab.locator('#designer-w2').boundingBox();
      assert.ok(box);
      await tab.mouse.move(box.x + 10, box.y + 10);
      await tab.mouse.down();
      for (const step of [1, 2, 3]) {
        await tab.mouse.move(box.x + 10 + step * 50, box.y + 10);
      }
      await tab.mouse.up();
      const moved = (await layoutOf(tab)).widgets.find((each) => each.id === 'w2');
      assert.equal(moved?.x, 6);
      await tab.click('[data-designer-undo]');
      assert.equal((await layoutOf(tab)).widgets.find((each) => each.id === 'w2')?.x, 3);
    });

    await t.test('the palette adds, the inspector places and binds', async () => {
      await tab.click('[data-designer-palette] [data-type="feeding"]');
      const added = (await layoutOf(tab)).widgets.find((each) => each.id === 'w3');
      assert.ok(added);
      await tab.fill('[data-designer-inspector] input[data-field="x"]', '5');
      await tab.dispatchEvent('[data-designer-inspector] input[data-field="x"]', 'change');
      assert.equal((await layoutOf(tab)).widgets.find((each) => each.id === 'w3')?.x, 4);
      await tab.click('#designer-w2');
      await tab.selectOption('[data-designer-inspector] select >> nth=0', 'ph');
      const bound = (await layoutOf(tab)).widgets.find((each) => each.id === 'w2') as unknown as { bind: object };
      assert.deepEqual(bound.bind, { parameter: 'ph' });
    });

    await t.test('the preview refreshes without taking the focus and shows the problems', async () => {
      await tab.focus('#designer-w1');
      await tab.keyboard.press('ArrowRight');
      const before = previews;
      await settled(tab);
      assert.ok(previews > before);
      assert.equal(await tab.evaluate(() => document.activeElement?.id), 'designer-w1');
      assert.ok(await tab.locator('[data-designer-preview] article').count());
      assert.match(await tab.textContent('[data-designer-problems]') ?? '', /msg-warning/);
    });

    await t.test('no serious accessibility violation', async () => {
      await tab.addScriptTag({ path: resolve('node_modules/axe-core/axe.min.js') });
      const found = await tab.evaluate(async () => {
        const axe = (window as unknown as { axe: { run: (context: unknown, options: unknown) => Promise<{ violations:
          { id: string; impact: string }[] }> } }).axe;
        const result = await axe.run(document.querySelector('[data-designer]'), { resultTypes: ['violations'] });
        return result.violations.filter((each) => each.impact === 'serious' || each.impact === 'critical')
          .map((each) => each.id);
      });
      assert.deepEqual(found, []);
    });

    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    server.close();
  }
});
