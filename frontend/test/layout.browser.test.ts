// The page layout rules of static/css in a real browser (Playwright on the machine's own Chrome or Edge; skipped where there
// is none), on what the real templates print: frontend/test/pages/*.html, rendered by Django from made-up records
// (core/layout_pages.py) and kept current by `manage.py layout_pages --check` (core/tests_layout_pages.py). Only the page's
// frame (the shell's rail and content area) is written here. A page never scrolls sideways at a phone's, a tablet's or a
// desktop's width; a wide table scrolls in its own frame and shows that more of it lies to a side; row actions stand apart;
// a water value's origin and age stand on their own line under the value and break only between the two; nothing of a
// monitoring card spills out of it, in Norwegian too; a form's one primary button comes last, on the row of the others.
// The page loads the product's own typefaces (static/css/fonts.css, static/fonts), as app_base.html does: without them the
// browser falls back to the machine's system-ui font (Segoe UI on Windows, DejaVu Sans on Linux, a much wider face), and
// a width measured on one machine says nothing about another. Test code only.
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
const FONTS = resolve('static/fonts');
const PAGES = resolve('frontend/test/pages');
const WIDTHS = [390, 1024, 1440];
const PARTS = ['meal', 'tabs', 'stock', 'water', 'matrix', 'card-en', 'card-nb', 'approve', 'overview'];

const part = (name: string): string => `<section id="part-${name}">${readFileSync(join(PAGES, `${name}.html`), 'utf8')}</section>`;

function page(): string {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>layout</title>
<link rel="stylesheet" href="/css/fonts.css"><link rel="stylesheet" href="/css/tokens.css"><link rel="stylesheet" href="/css/base.css"><link rel="stylesheet" href="/css/ui.css"><link rel="stylesheet" href="/css/app.css"><link rel="stylesheet" href="/css/components.css">
<link rel="stylesheet" href="/css/monitor.css"><link rel="stylesheet" href="/css/tw.css"></head><body><div class="shell"><aside class="rail" id="rail"><nav class="rail-nav"><a class="rail-link" id="rail-units" href="#"><svg class="icon"></svg><span class="rail-label">Production units</span></a></nav></aside><div class="console">
<header class="topbar"><div class="title-block"><h1>Layout</h1></div></header><main class="content">${PARTS.map(part).join('\n')}</main></div></div></body></html>`;
}

// The page, static/css and static/fonts (fonts.css asks for ../fonts/*.woff2).
const SERVED: [string, string, string][] = [['/css/', CSS, 'text/css'], ['/fonts/', FONTS, 'font/woff2']];

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = request.url ?? '';
    if (url === '/') return void response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(page());
    for (const [prefix, root, type] of SERVED) {
      const file = join(root, url.slice(prefix.length));
      if (url.startsWith(prefix) && file.startsWith(root) && existsSync(file)) {
        return void response.writeHead(200, { 'Content-Type': type }).end(readFileSync(file));
      }
    }
    response.writeHead(404).end();
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
    // The layout is measured settled: with motion the rail's width moves for 0.2 s (app.css) after a collapse or a new
    // window size, longer than the 50 ms the steps wait, and a measure taken mid-move failed one run in three.
    const tab = await browser.newPage({ reducedMotion: 'reduce' });
    await tab.goto(`http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}/`);
    // The typefaces are loaded before anything is measured (font-display: swap paints the fallback first).
    const loaded = await tab.evaluate(async () => {
      await Promise.all(['400 15px "Atkinson Hyperlegible Next"', '600 24px "Bricolage Grotesque"'].map((face) => document.fonts.load(face)));
      await document.fonts.ready;
      const families = [...document.fonts].filter((font) => font.status === 'loaded').map((font) => font.family.replace(/"/g, ''));
      return [...new Set(families)].sort();
    });
    assert.deepEqual(loaded, ['Atkinson Hyperlegible Next', 'Bricolage Grotesque'], 'the product\'s typefaces are loaded (static/css/fonts.css)');

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

    await t.test('the meal board shows every column without scrolling at 1440 px, and scrolled to its end at 1024 and 390 px nothing lies under its sticky columns', async () => {
      for (const width of [1440, 1024, 390]) {
        await tab.setViewportSize({ width, height: 900 });
        await tab.waitForTimeout(50);
        const meal = await frame(tab, '#part-meal .table-wrap');
        if (width === 1440) {
          assert.ok(!meal.wide, 'the meal board fits its frame at 1440 px (README: five numbers never clip)');
          // With room to spare: the least width the table takes (every column at its longest unbreakable line, measured
          // with the table squeezed to nothing) stays 24 px inside the frame, headroom for another operating system's
          // glyph rasterising (Windows and Linux Chrome differ by a few px) and for a record a little longer than these.
          const fit = await tab.locator('#part-meal .table-wrap').evaluate((wrap) => {
            const table = wrap.querySelector('table')!;
            table.style.width = '0px';
            const least = table.getBoundingClientRect().width;
            table.style.width = '';
            return { frame: wrap.clientWidth, least };
          });
          assert.ok(fit.frame - fit.least >= 24,
            `the meal board needs ${fit.least} px of its ${fit.frame} px frame at 1440 px: ${fit.frame - fit.least} px to spare, 24 at least`);
        }
        const hidden = await tab.locator('#part-meal .table-wrap').evaluate((wrap) => {
          wrap.scrollLeft = wrap.scrollWidth;
          const first = wrap.querySelector('thead .sticky-first')!.getBoundingClientRect();
          const end = wrap.querySelector('thead .sticky-end')!.getBoundingClientRect();
          const heads = [...wrap.querySelectorAll('thead th:not(.sticky-first):not(.sticky-end)')];
          const last = heads[heads.length - 1].getBoundingClientRect();
          const cut = [...wrap.querySelectorAll('td, th')].filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
            .map((cell) => (cell.textContent ?? '').trim().slice(0, 30));
          wrap.scrollLeft = 0;
          return { under: last.right > end.left + 1 ? 'the last column ends under the actions' : '',
            overlap: first.right > end.left + 1 ? 'the sticky columns overlap' : '', cut };
        });
        assert.deepEqual(hidden, { under: '', overlap: '', cut: [] }, `at ${width} px`);
      }
    });

    await t.test('the collapsed rail says a link\'s name beside it on focus, not only on hover', async () => {
      await tab.setViewportSize({ width: 1280, height: 900 });
      await tab.evaluate(() => { document.documentElement.dataset.nav = 'collapsed'; });
      await tab.waitForTimeout(50);
      const hidden = await box(tab, '#rail-units .rail-label');
      assert.ok(hidden.width <= 1, 'the name is read aloud only while the link is not in focus');
      await tab.focus('#rail-units');
      const shown = await box(tab, '#rail-units .rail-label');
      const rail = await box(tab, '#rail');
      assert.ok(shown.width > 40 && shown.left >= rail.right, `the name stands beside the rail (${JSON.stringify(shown)})`);
      await tab.evaluate(() => { delete document.documentElement.dataset.nav; (document.activeElement as HTMLElement).blur(); });
    });

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
    await t.test('below 1024 px the page ends above the bottom bar: its last line is never under the bar', async () => {
      for (const width of [390, 1023]) {
        await tab.setViewportSize({ width, height: 900 });
        await tab.waitForTimeout(50);
        const room = await tab.evaluate(() => {
          const bar = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--bottombar-h'));
          const end = document.querySelector('main')!.getBoundingClientRect().bottom + window.scrollY;
          return { bar, below: document.documentElement.scrollHeight - end };
        });
        assert.ok(room.below >= room.bar - 1, `at ${width} px the page goes on ${room.below} px below its content, the bar is ${room.bar} px`);
      }
    });

    await t.test('the production overview: two columns at 1440 px, one at 390 px, nothing spills, in Norwegian', async () => {
      for (const width of [1440, 390]) {
        await tab.setViewportSize({ width, height: 900 });
        await tab.waitForTimeout(50);
        const layout = await tab.locator('#part-overview').evaluate((part) => {
          const sections = [...part.querySelectorAll('section')].map((section) => section.getBoundingClientRect());
          const edge = part.getBoundingClientRect().right;
          const spill = [...part.querySelectorAll('*')].filter((inner) => inner.getBoundingClientRect().right > edge + 1)
            .map((inner) => `${inner.tagName}.${inner.className} "${(inner.textContent ?? '').trim().slice(0, 30)}"`);
          return { lefts: [...new Set(sections.map((box) => Math.round(box.left)))].length, spill };
        });
        assert.deepEqual(layout.spill, [], `at ${width} px`);
        assert.equal(layout.lefts, width === 1440 ? 2 : 1, `the sections stand in ${layout.lefts} columns at ${width} px`);
      }
    });

    await t.test('the production overview is a dashboard: metric cards several to a row, compact attention rows', async () => {
      for (const [width, least, most] of [[1440, 5, 6], [1024, 4, 6], [390, 2, 2]] as const) {
        await tab.setViewportSize({ width, height: 900 });
        await tab.waitForTimeout(50);
        const board = await tab.locator('#part-overview').evaluate((part) => {
          const cards = [...part.querySelectorAll('#today-title ~ * [data-metric]')].map((card) => card.getBoundingClientRect());
          const top = Math.min(...cards.map((box) => box.top));
          const rows = part.querySelectorAll('[data-attention="water"]');
          return {
            cards: cards.length,
            first: cards.filter((box) => Math.abs(box.top - top) < 2).length,
            widest: Math.max(...cards.map((box) => box.width)),
            tallest: Math.max(...cards.map((box) => box.height)),
            row: Math.max(...[...rows].map((row) => row.getBoundingClientRect().height)),
            rows: rows.length,
          };
        });
        assert.ok(board.cards >= 10, `${board.cards} cards`);
        assert.ok(board.first >= least && board.first <= most, `${board.first} cards in the first row at ${width} px`);
        assert.ok(board.widest <= 320, `a card is ${board.widest} px wide at ${width} px: a bar across the page, not a card`);
        assert.ok(board.tallest <= 150, `a card is ${board.tallest} px tall at ${width} px`);
        assert.ok(board.rows >= 3);
        if (width === 1440) assert.ok(board.row <= 84, `a water row needing attention is ${board.row} px tall at 1440 px`);
      }
    });

    await t.test('the production overview\'s links and buttons are 48 px targets on a coarse pointer', async () => {
      const touch = await browser.newContext({ hasTouch: true, isMobile: true, viewport: { width: 390, height: 900 }, reducedMotion: 'reduce' });
      try {
        const phone = await touch.newPage();
        await phone.goto(tab.url());
        const coarse = await phone.evaluate(() => matchMedia('(pointer: coarse)').matches);
        assert.ok(coarse, 'the touch context has a coarse pointer');
        const small = await phone.locator('#part-overview a').evaluateAll((links) => links
          .map((link) => [(link.textContent ?? '').trim().slice(0, 30), link.getBoundingClientRect().height] as const)
          .filter(([, height]) => height < 48));
        assert.deepEqual(small, []);
      } finally {
        await touch.close();
      }
    });
  } finally {
    await browser.close();
    server.close();
  }
});
