// The page layout rules of static/css in a real browser (Playwright on the machine's own Chrome or Edge; skipped where there
// is none), on what the real templates print: frontend/test/pages/*.html, rendered by Django from made-up records
// (core/layout_pages.py) and kept current by `manage.py layout_pages --check` (core/tests_layout_pages.py). Only the page's
// frame (the shell's rail and content area) is written here. A page never scrolls sideways at a phone's, a tablet's or a
// desktop's width; a wide table scrolls in its own frame and shows that more of it lies to a side; row actions stand apart;
// a water value's origin and age stand on their own line under the value and break only between the two; nothing of a
// monitoring card spills out of it, in Norwegian too; a form's one primary button comes last, on the row of the others.
// Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { join, resolve } from 'node:path';

import { chromium, type Page } from 'playwright-core';

const BROWSERS = [
  process.env.CHROME_PATH ?? '',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
].filter((path) => path && existsSync(path));
const CSS = resolve('static/css');
const PAGES = resolve('frontend/test/pages');
const WIDTHS = [390, 1024, 1440];
const PARTS = ['meal', 'tabs', 'stock', 'water', 'matrix', 'card-en', 'card-nb', 'approve'];

const part = (name: string): string => `<section id="part-${name}">${readFileSync(join(PAGES, `${name}.html`), 'utf8')}</section>`;

function page(): string {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>layout</title>
<link rel="stylesheet" href="/css/tokens.css"><link rel="stylesheet" href="/css/base.css"><link rel="stylesheet" href="/css/ui.css"><link rel="stylesheet" href="/css/app.css"><link rel="stylesheet" href="/css/components.css">
<link rel="stylesheet" href="/css/monitor.css"></head><body><div class="shell"><aside class="rail"></aside><div class="console">
<header class="topbar"><div class="title-block"><h1>Layout</h1></div></header><main class="content">${PARTS.map(part).join('\n')}</main></div></div></body></html>`;
}

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    const file = join(CSS, (request.url ?? '').replace(/^\/css\//, ''));
    if (request.url === '/') response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(page());
    else if (request.url?.startsWith('/css/') && file.startsWith(CSS) && existsSync(file)) {
      response.writeHead(200, { 'Content-Type': 'text/css' }).end(readFileSync(file));
    } else response.writeHead(404).end();
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

type Box = { left: number; right: number; top: number; bottom: number; width: number };
const box = (tab: Page, selector: string): Promise<Box> => tab.locator(selector).first().evaluate((element) => {
  const r = element.getBoundingClientRect();
  return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width };
});

// The cue: the frame's computed shade layers, and whether the frame is scrolled to a side (the shades are painted by the
// browser from them: the scroll-attached one shows exactly while the content-attached cover has moved off its edge).
async function frame(tab: Page, selector: string): Promise<{ wide: boolean; atStart: boolean; atEnd: boolean; shaded: boolean }> {
  return tab.locator(selector).first().evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      wide: element.scrollWidth > element.clientWidth + 1,
      atStart: element.scrollLeft <= 0,
      atEnd: element.scrollLeft + element.clientWidth >= element.scrollWidth - 1,
      shaded: /radial-gradient/.test(style.backgroundImage) && /local/.test(style.backgroundAttachment)
        && /scroll/.test(style.backgroundAttachment),
    };
  });
}

test('the page layout of the real templates', { skip: BROWSERS.length ? false : 'no Chrome or Edge on this machine' }, async (t) => {
  const server = await serve();
  const address = server.address();
  const browser = await chromium.launch({ executablePath: BROWSERS[0], headless: true });
  try {
    const tab = await browser.newPage();
    await tab.goto(`http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}/`);

    for (const width of WIDTHS) {
      await tab.setViewportSize({ width, height: 900 });
      await tab.waitForTimeout(50);

      await t.test(`no page scrolls sideways at ${width} px`, async () => {
        const [scroll, client, wide] = await tab.evaluate(() => {
          const limit = document.documentElement.clientWidth;
          const past = [...document.querySelectorAll('main *')].filter((element) => !element.parentElement?.closest('.table-wrap')
            && element.getBoundingClientRect().right > limit + 1);
          const outermost = past.filter((element) => !past.includes(element.parentElement as Element));
          return [document.documentElement.scrollWidth, limit, outermost.map((element) => `${element.tagName}.${element.className}`).join(', ')];
        });
        assert.ok(scroll <= client, `the page is ${scroll} px wide in a ${client} px window: ${wide}`);
      });

      await t.test(`a wide table scrolls in its frame and shows it at ${width} px`, async () => {
        const stock = await frame(tab, '#part-stock .table-wrap');
        assert.ok(stock.shaded, 'the frame paints the shade that shows more lies to a side');
        if (width === 390) assert.ok(stock.wide && stock.atStart && !stock.atEnd, 'the stock table goes on to the right');
        const matrix = await frame(tab, '#part-matrix .table-wrap');
        assert.ok(matrix.shaded, 'the role matrix is in the same frame');
      });
    }

    await t.test('nothing of a monitoring card spills out of it, in English and Norwegian at 390 and 1440 px', async () => {
      for (const width of [390, 1440]) {
        await tab.setViewportSize({ width, height: 900 });
        await tab.waitForTimeout(50);
        for (const card of ['#part-card-en .monitor-card', '#part-card-nb .monitor-card']) {
          const spill = await tab.locator(card).evaluate((element) => {
            const edge = element.getBoundingClientRect().right;
            return [...element.querySelectorAll('*')].filter((inner) => inner.getBoundingClientRect().right > edge + 1)
              .map((inner) => `${inner.tagName}.${inner.className} "${(inner.textContent ?? '').trim().slice(0, 30)}"`);
          });
          assert.deepEqual(spill, [], `${card} at ${width} px`);
        }
      }
    });

    await tab.setViewportSize({ width: 1440, height: 900 });
    await tab.waitForTimeout(50);

    await t.test('row actions stand apart', async () => {
      const links = await tab.locator('#part-stock td.row-actions a').evaluateAll((elements) => elements.map((element) => {
        const r = element.getBoundingClientRect();
        return [r.left, r.right];
      }));
      assert.ok(links.length >= 2);
      for (let i = 1; i < links.length; i++) {
        assert.ok(links[i][0] - links[i - 1][1] >= 8, `actions ${i - 1} and ${i} are ${links[i][0] - links[i - 1][1]} px apart`);
      }
    });

    await t.test('a water value\'s origin and age stand on a line under the value', async () => {
      const cell = '#part-water td.wq';
      const value = await tab.locator(cell).first().evaluate((element) => {
        const range = document.createRange();
        range.setStart(element.firstChild as Node, 0);
        range.setEnd(element.firstChild as Node, (element.firstChild as Text).length);
        return range.getBoundingClientRect().bottom;
      });
      const source = await box(tab, `${cell} .wq-source`);
      assert.ok(source.top >= value - 1, `the origin starts at ${source.top}, the value ends at ${value}`);
    });

    await t.test('a monitoring card breaks a value’s origin line only between the origin and the age', async () => {
      for (const selector of ['.wq-origin', '.wq-age']) {
        const lines = await tab.locator(`#part-card-en ${selector}, #part-card-nb ${selector}`).evaluateAll(
          (elements) => elements.map((element) => element.getClientRects().length));
        assert.ok(lines.length > 0 && lines.every((count) => count === 1), `${selector} runs over ${lines} lines`);
      }
    });

    await t.test('a dialog\'s primary button is last, on the row of the others', async () => {
      const cancel = await box(tab, '#part-approve .form-actions .button-ghost');
      const approve = await box(tab, '#part-approve .form-actions button[type=submit]');
      assert.ok(Math.abs(cancel.top - approve.top) < 2, 'Cancel and Approve are on one row');
      assert.ok(approve.left > cancel.right, 'Approve comes after Cancel');
      assert.ok(approve.width < 400, `Approve is ${approve.width} px wide`);
    });
  } finally {
    await browser.close();
    server.close();
  }
});
