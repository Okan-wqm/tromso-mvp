// The monitoring wall of fitted cards in a real browser (Playwright on the machine's own Chrome or Edge; skipped where
// there is none, never under CI=1): what the real templates print for twenty Small cards with their band
// (frontend/test/pages/wall-small-en.html and -tr.html, rendered by Django from made-up units and the real chart of each:
// core/layout_pages.py), in the product's own sheets, laid out by the compiled frontend/wall.ts. On a 3440x1440 and a
// 1920x1080 screen the twenty cards are ONE page, every card is on the screen, nothing of a card lies outside it, no
// text is cut but the three that carry their whole text in a title (the unit's name, a long reason, why a picture
// cannot be drawn), a figure, a label, a code and a state word never, and the smallest text is at least 11 px; in
// Turkish too. On a 1280x720 window the wall turns pages rather than shrink: PageDown and PageUp turn them and the
// band says which. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { join, resolve } from 'node:path';

import { chromium, type Page } from 'playwright-core';

import { BROWSERS, skipWithout } from './browsers.js';

const SERVED: [string, string, string][] = [['/css/', resolve('static/css'), 'text/css'], ['/fonts/', resolve('static/fonts'), 'font/woff2'],
                                            ['/js/', resolve('.build/test'), 'text/javascript']];
const PAGES = resolve('frontend/test/pages');
const SHEETS = ['fonts', 'tokens', 'base', 'ui', 'app', 'components', 'monitor', 'card-grid', 'tw'];

function page(language: string): string {
  const part = readFileSync(join(PAGES, `wall-small-${language}.html`), 'utf8');
  return `<!doctype html><html lang="${language}" data-theme="fjord" data-wall><head><meta charset="utf-8"><title>wall</title>
${SHEETS.map((name) => `<link rel="stylesheet" href="/css/${name}.css">`).join('')}<script type="module" src="/js/wall.js"></script></head>
<body><div class="shell"><aside class="rail" id="rail"></aside><div class="console"><header class="topbar"></header><main class="content">
<div class="monitor-grid" data-card-width="2">${part}</div>
<div id="monitor-announce" data-states="critical warning blind unjudged note ok empty"></div></main></div></div></body></html>`;
}

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = (request.url ?? '').split('?')[0] ?? '';
    const language = /^\/(en|tr)$/.exec(url);
    if (language) return void response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(page(language[1] ?? 'en'));
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

interface Seen {
  cols: string; rows: string; page: string; pages: string; cards: number; onScreen: number; pageScrolls: boolean;
  spills: string[]; cut: string[]; never: string[]; smallest: number; indicator: string; indicatorHidden: boolean;
  tallyCut: string[];
}

/** What the wall looks like now, measured in the page. */
function look(tab: Page): Promise<Seen> {
  return tab.evaluate(() => {
    const grid = document.querySelector<HTMLElement>('.monitor-grid');
    if (!grid) throw new Error('no grid');
    const style = getComputedStyle(grid);
    const cards = Array.from(grid.querySelectorAll<HTMLElement>(':scope > .monitor-card'));
    const seen = { cols: style.getPropertyValue('--cols').trim(), rows: style.getPropertyValue('--rows').trim(),
                   page: grid.dataset.page ?? '', pages: grid.dataset.pageCount ?? '', cards: cards.length, onScreen: 0,
                   pageScrolls: document.documentElement.scrollHeight > window.innerHeight + 1
                     || document.documentElement.scrollWidth > window.innerWidth + 1,
                   spills: [] as string[], cut: [] as string[], never: [] as string[], smallest: 1000, indicator: '',
                   indicatorHidden: true, tallyCut: [] as string[] };
    const ownText = (node: Element): boolean => Array.from(node.childNodes).some((child) => child.nodeType === 3 && (child.textContent ?? '').trim() !== '');
    // cut by itself: an element that clips its own text (the one-line ellipsis)
    const cutOff = (node: Element): boolean => getComputedStyle(node).overflowX !== 'visible' && node.scrollWidth > node.clientWidth + 1;
    // cut by another: the element's box reaches past an ancestor that clips, up to and with its card
    const clipped = (node: Element, card: Element): boolean => {
      const rect = node.getBoundingClientRect();
      for (let up = node.parentElement; up; up = up.parentElement) {
        const style = getComputedStyle(up);
        const frame = up.getBoundingClientRect();
        if (style.overflowX !== 'visible' && (rect.right > frame.right + 1.5 || rect.left < frame.left - 1.5)) return true;
        if (style.overflowY !== 'visible' && (rect.bottom > frame.bottom + 1.5 || rect.top < frame.top - 1.5)) return true;
        if (up === card) break;
      }
      return false;
    };
    for (const card of cards) {
      const box = card.getBoundingClientRect();
      if (box.bottom <= 1 || box.top >= window.innerHeight - 1) continue;          // a card of another page
      if (box.top >= -1 && box.bottom <= window.innerHeight + 1) seen.onScreen += 1;
      const code = card.querySelector('h3')?.textContent?.trim() ?? '?';
      for (const node of Array.from(card.querySelectorAll<HTMLElement>('*'))) {
        if (node.closest('svg') || node.closest('.sr-only')) continue;
        const own = getComputedStyle(node);
        if (own.display === 'none' || own.display === 'contents') continue;
        const rect = node.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) continue;
        // (the code's link is an inline box as high as its face, a little higher than the line it stands on: its
        // heading's own box is what must be inside the card)
        const inside = node.matches('h3 a') ? node.parentElement?.getBoundingClientRect() ?? rect : rect;
        const out = Math.max(inside.right - box.right, inside.bottom - box.bottom, box.left - inside.left, box.top - inside.top);
        if (out > 1.5) seen.spills.push(`${code}: ${node.tagName.toLowerCase()}.${node.className} by ${Math.round(out)} px`);
        if (!ownText(node)) continue;
        seen.smallest = Math.min(seen.smallest, Number.parseFloat(own.fontSize));
        const said = `${code}: "${(node.textContent ?? '').trim().slice(0, 40)}"`;
        if (cutOff(node) && !node.title) seen.cut.push(said);
      }
      // (the code is measured by its heading: its link is an inline box a little higher than the line it stands on)
      for (const node of Array.from(card.querySelectorAll<HTMLElement>('h3, dt, dd b, .monitor-state'))) {
        // (a figure stays inside its own tile: it never runs under its neighbour either)
        const tile = node.closest('dl')?.getBoundingClientRect();
        const wide = tile !== undefined && node.getBoundingClientRect().right > tile.right + 1.5;
        if (cutOff(node) || clipped(node, card) || wide) seen.never.push(`${code}: "${(node.textContent ?? '').trim().slice(0, 40)}"`);
      }
    }
    const indicator = grid.querySelector<HTMLElement>('[data-pages]');
    seen.indicatorHidden = !indicator || getComputedStyle(indicator).display === 'none';
    seen.indicator = indicator?.querySelector('[data-pages-text]')?.textContent ?? '';
    for (const node of Array.from(grid.querySelectorAll<HTMLElement>('.monitor-tally li, .monitor-head'))) {
      if (node.scrollWidth > node.clientWidth + 1) seen.tallyCut.push((node.textContent ?? '').trim());
    }
    return seen;
  });
}

/** What is wrong with the line under a figure (review R1: where a value came from and how old it is stand under
 *  EVERY figure of a card on the screen, in visible text, whole): [] when nothing is. */
async function ages(tab: Page): Promise<string[]> {
  return tab.evaluate(() => {
    const wrong: string[] = [];
    const cards = Array.from(document.querySelectorAll<HTMLElement>('.monitor-grid .monitor-card.is-fit'));
    for (const card of cards) {
      const box = card.getBoundingClientRect();
      if (box.right <= 0 || box.left >= innerWidth || box.bottom <= 0 || box.top >= innerHeight) continue;   // another page
      const code = card.querySelector('h3')?.textContent?.trim() ?? '';
      for (const figure of Array.from(card.querySelectorAll<HTMLElement>('dl b'))) {
        const tile = figure.closest('dl') as HTMLElement;
        const line = tile.querySelector<HTMLElement>('.monitor-under');
        if (!line) { wrong.push(`${code}: a figure with no line under it`); continue; }
        const at = line.getBoundingClientRect();
        const text = (line.textContent ?? '').replace(/\s+/g, ' ').trim();
        const inside = tile.getBoundingClientRect();
        if (getComputedStyle(line).display === 'none' || at.height < 8) wrong.push(`${code}: "${text}" is not shown`);
        else if (!text.includes(' · ')) wrong.push(`${code}: "${text}" lacks the origin or the age`);
        else if (line.scrollWidth > line.clientWidth + 1 || at.right > inside.right + 1 || at.bottom > box.bottom + 1) wrong.push(`${code}: "${text}" is cut`);
        else if (Number.parseFloat(getComputedStyle(line).fontSize) < 11) wrong.push(`${code}: "${text}" is under 11 px`);
      }
    }
    return wrong;
  });
}

/** Four more cards on the wall (copies of its first four under their own keys): a farm of twenty-four tanks. */
async function twentyFour(tab: Page): Promise<void> {
  await tab.evaluate(() => {
    const wall = document.querySelector('.monitor-grid') as HTMLElement;
    Array.from(wall.querySelectorAll<HTMLElement>('.monitor-card')).slice(0, 4).forEach((card, index) => {
      const copy = card.cloneNode(true) as HTMLElement;
      copy.dataset.key = `card:copy-${index}`;
      copy.id = `card-copy-${index}`;
      copy.querySelectorAll('[id]').forEach((node) => node.removeAttribute('id'));
      wall.append(copy);
    });
    window.dispatchEvent(new Event('resize'));
  });
  await tab.waitForTimeout(150);
}

async function open(tab: Page, origin: string, language: string, width: number, height: number): Promise<void> {
  await tab.setViewportSize({ width, height });
  await tab.goto(`${origin}/${language}`);
  await tab.evaluate(async () => {
    await Promise.all(['400 15px "Atkinson Hyperlegible Next"', '600 15px "Atkinson Hyperlegible Next"'].map((face) => document.fonts.load(face)));
    await document.fonts.ready;
  });
  // the wall script has laid the grid out (it sets --cols), and again after the faces came
  await tab.waitForFunction(() => getComputedStyle(document.querySelector('.monitor-grid') as Element).getPropertyValue('--cols').trim() !== '');
  await tab.evaluate(() => window.dispatchEvent(new Event('resize')));
  await tab.waitForTimeout(100);
}

test('the monitoring wall of small cards', { skip: skipWithout(BROWSERS) }, async (t) => {
  const server = await serve();
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await chromium.launch({ executablePath: BROWSERS[0] ?? '', headless: true });
  try {
    const tab = await browser.newPage({ reducedMotion: 'reduce' });
    for (const [language, width, height, grid] of [['en', 3440, 1440, '5x4'], ['en', 1920, 1080, '4x5'], ['tr', 3440, 1440, '5x4'],
                                                   ['tr', 1920, 1080, '4x5'], ['en', 5120, 1440, '5x4'], ['en', 2560, 1440, '4x5'],
                                                   ['en', 3840, 2160, '4x5']] as const) {
      await t.test(`twenty cards are one screen at ${width}x${height} (${language}): nothing cut, nothing outside its card`, async () => {
        await open(tab, origin, language, width, height);
        const seen = await look(tab);
        assert.equal(`${seen.cols}x${seen.rows}`, grid);
        assert.deepEqual([seen.cards, seen.onScreen, seen.pages], [20, 20, '1']);
        assert.equal(seen.pageScrolls, false, 'the page itself never scrolls');
        assert.deepEqual(seen.spills, [], 'nothing of a card lies outside it');
        assert.deepEqual(seen.cut, [], 'no text is cut but what carries its whole text in a title');
        assert.deepEqual(seen.never, [], 'a code, a label, a figure and a state word are never cut');
        assert.ok(seen.smallest >= 11, `the smallest text is ${seen.smallest} px`);
        assert.equal(seen.indicatorHidden, true, 'one page: no page indicator');
        assert.deepEqual(seen.tallyCut, [], 'the band\'s clock and tally are whole');
        assert.deepEqual(await ages(tab), [], 'where it came from and how old it is stand under every figure');
      });
    }

    for (const [width, height] of [[3440, 1440], [5120, 1440], [2560, 1440], [3840, 2160]] as const) {
      await t.test(`twenty-four cards are one screen at ${width}x${height}, the age under every figure`, async () => {
        await open(tab, origin, 'tr', width, height);
        await twentyFour(tab);
        const seen = await look(tab);
        assert.deepEqual([seen.cards, seen.onScreen, seen.pages], [24, 24, '1']);
        assert.deepEqual([seen.spills, seen.cut, seen.never], [[], [], []]);
        assert.ok(seen.smallest >= 11, `the smallest text is ${seen.smallest} px`);
        assert.deepEqual(await ages(tab), []);
      });
    }

    await t.test('twenty-four cards on 1920x1080 turn pages rather than lose the age or shrink the type', async () => {
      await open(tab, origin, 'tr', 1920, 1080);
      await twentyFour(tab);
      const seen = await look(tab);
      assert.ok(seen.smallest >= 11, `the smallest text is ${seen.smallest} px`);
      assert.deepEqual([seen.spills, seen.cut, seen.never], [[], [], []]);
      assert.deepEqual(await ages(tab), []);
    });

    await t.test('a low window turns pages rather than shrink the type, and the keys turn them', async () => {
      await open(tab, origin, 'en', 1280, 720);
      const first = await look(tab);
      assert.ok(Number(first.pages) > 1, `${first.pages} pages`);
      assert.ok(first.smallest >= 11, `the smallest text is ${first.smallest} px`);
      assert.deepEqual([first.cut, first.never, first.spills], [[], [], []]);
      assert.deepEqual(await ages(tab), []);
      assert.equal(first.indicatorHidden, false);
      assert.equal(first.indicator, `${first.page} / ${first.pages}`);
      // it opened on the page of its worst card (HA-R02, critical, is the fifth card)
      const per = Number(first.cols) * Number(first.rows);
      assert.equal(Number(first.page), Math.floor(4 / per) + 1);
      await tab.keyboard.press('PageDown');
      await tab.waitForTimeout(50);
      const next = await look(tab);
      assert.equal(Number(next.page), Math.min(Number(first.page) + 1, Number(first.pages)));
      assert.equal(next.indicator, `${next.page} / ${next.pages}`);
      assert.deepEqual([next.cut, next.never, next.spills], [[], [], []]);
      await tab.keyboard.press('PageUp');
      await tab.keyboard.press('PageUp');
      await tab.keyboard.press('PageUp');
      await tab.waitForTimeout(50);
      assert.equal((await look(tab)).page, '1');                                  // never before the first page
      await tab.locator('[data-page-turn="1"]').click();
      await tab.waitForTimeout(50);
      assert.equal((await look(tab)).page, '2');
    });
  } finally {
    await browser.close();
    server.close();
  }
});
