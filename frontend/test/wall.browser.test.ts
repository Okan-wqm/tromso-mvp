// The monitoring wall of fitted cards in a real browser (Playwright on the machine's own Chrome or Edge; skipped where
// there is none, never under CI=1): what the real templates print for twenty Small cards with their band
// (frontend/test/pages/wall-small-en.html and -tr.html, rendered by Django from made-up units and the real chart of each:
// core/layout_pages.py), in the product's own sheets, laid out by the compiled frontend/wall.ts. On a 3440x1440 and a
// 1920x1080 screen the twenty cards are ONE page, every card is on the screen, nothing of a card lies outside it, no
// text is cut but the three that carry their whole text in a title (the unit's name, a long reason, why a picture
// cannot be drawn), a figure, a label, a code and a state word never, and the smallest text is at least 11 px; in
// Turkish too. On a 1280x720 window the wall turns pages rather than shrink: PageDown and PageUp turn them and the
// band says which. The same parts again in the NEW LOOK (?ui=next: data-ui="next", the theme Industry, and
// static/css/glyphs.css and monitor-next.css after the page's sheets, as monitor.html links them then): every test of
// the wall run again. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { join, resolve } from 'node:path';

import { chromium, type Page } from 'playwright-core';

import { BROWSERS, skipWithout } from './browsers.js';
import { linksOf } from './sheets.js';
import { legibleUnit } from '../wall/slots.js';

const SERVED: [string, string, string][] = [['/css/', resolve('static/css'), 'text/css'], ['/fonts/', resolve('static/fonts'), 'font/woff2'],
                                            ['/js/', resolve('.build/test'), 'text/javascript']];
const PAGES = resolve('frontend/test/pages');
// (the sheets in the order the monitoring page links them: app_base.html with the page's own two before tw.css)
const SHEETS = linksOf('app_base.html', ['monitor', 'card-grid']);
const SHEETS_NEXT = linksOf('app_base.html', ['monitor', 'card-grid', 'glyphs', 'monitor-next']);

/** The wall's page; `pane`: with the pane of a unit gone into in its dock (frontend/test/pages/dock-big-tr.html, the
 *  dock's own markup around the unit's Big card). */
function page(language: string, pane = false, next = false): string {
  const part = readFileSync(join(PAGES, `wall-small-${language}.html`), 'utf8');
  const docked = pane ? readFileSync(join(PAGES, 'dock-big-tr.html'), 'utf8') : '';
  const look = next ? 'data-theme="industry" data-ui="next"' : 'data-theme="fjord"';
  return `<!doctype html><html lang="${language}" ${look} data-wall><head><meta charset="utf-8"><title>wall</title>
${next ? SHEETS_NEXT : SHEETS}<script type="module" src="/js/wall.js"></script></head>
<body><div class="shell"><aside class="rail" id="rail"></aside><div class="console"><header class="topbar"></header><main class="content" data-measure="wall">
<aside class="monitor-dock" id="monitor-dock" data-mw="48" data-mh="61">${docked}</aside>
<div class="monitor-grid" data-card-width="2">${part}</div>
<div id="monitor-announce" data-states="critical warning blind unjudged note ok empty"></div></main></div></div></body></html>`;
}

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = (request.url ?? '').split('?')[0] ?? '';
    const language = /^\/(next-)?(en|tr)(-pane)?$/.exec(url);
    if (language) {
      return void response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
        .end(page(language[2] ?? 'en', language[3] !== undefined, language[1] !== undefined));
    }
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
      // (the head's right side, the withdrawal, the flip link and the state, never runs over the unit's code)
      const title = card.querySelector('h3')?.getBoundingClientRect();
      const side = card.querySelector('.monitor-card-state')?.getBoundingClientRect();
      if (title && side && side.left < title.right - 0.5) seen.never.push(`${code}: the head's right side runs over the code`);
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

/** The marks of the pH windows on the screen that touch one another: a border's word over the other's, a word over
 *  the water's mark (the 1C report's weak point). [] when none does. */
async function touching(tab: Page): Promise<string[]> {
  return tab.evaluate(() => {
    const wrong: string[] = [];
    for (const card of Array.from(document.querySelectorAll<HTMLElement>('.monitor-grid .monitor-card.is-fit'))) {
      const box = card.getBoundingClientRect();
      if (box.right <= 0 || box.left >= innerWidth || box.bottom <= 0 || box.top >= innerHeight) continue;   // another page
      const code = card.querySelector('h3')?.textContent?.trim() ?? '';
      for (const picture of Array.from(card.querySelectorAll<SVGSVGElement>('svg.monitor-ph-window'))) {
        const frame = picture.getBoundingClientRect();
        const marks = Array.from(picture.querySelectorAll<SVGGraphicsElement>('text, circle'))
          .map((mark) => ({ said: (mark.textContent ?? '').trim() || 'the mark', at: mark.getBoundingClientRect() }));
        for (const mark of marks) {
          if (mark.said !== 'the mark' && (mark.at.left < frame.left - 0.5 || mark.at.right > frame.right + 0.5)) {
            wrong.push(`${code}: "${mark.said}" leaves the picture`);
          }
        }
        for (let first = 0; first < marks.length; first += 1) {
          for (let second = first + 1; second < marks.length; second += 1) {
            const a = marks[first];
            const b = marks[second];
            if (a && b && a.at.left < b.at.right && b.at.left < a.at.right) wrong.push(`${code}: "${a.said}" touches "${b.said}"`);
          }
        }
      }
    }
    return wrong;
  });
}

/** What the pane in the dock looks like beside the wall. */
interface Docked {
  mode: string; left: number; right: number; top: number; bottom: number; cardsRight: number; bandBottom: number;
  unit: number; smallest: number; spills: string[]; cut: string[]; chart: [number, number]; card: [number, number];
}
async function docked(tab: Page): Promise<Docked> {
  return tab.evaluate(() => {
    const pane = document.getElementById('monitor-dock') as HTMLElement;
    const at = pane.getBoundingClientRect();
    const card = pane.querySelector<HTMLElement>('.monitor-card') as HTMLElement;
    const box = card.getBoundingClientRect();
    const found = { mode: pane.dataset.dock ?? '', left: at.left, right: at.right, top: at.top, bottom: at.bottom,
                    cardsRight: 0, bandBottom: (document.querySelector('.monitor-band') as HTMLElement).getBoundingClientRect().bottom,
                    unit: Number.parseFloat(getComputedStyle(card.firstElementChild as Element).fontSize), smallest: 1000,
                    spills: [] as string[], cut: [] as string[], chart: [0, 0] as [number, number],
                    card: [box.width, box.height] as [number, number] };
    for (const small of Array.from(document.querySelectorAll<HTMLElement>('.monitor-grid > .monitor-card'))) {
      const rect = small.getBoundingClientRect();
      if (rect.bottom <= 1 || rect.top >= innerHeight - 1) continue;
      found.cardsRight = Math.max(found.cardsRight, rect.right);
    }
    const chart = card.querySelector('svg.monitor-chart-svg')?.getBoundingClientRect();
    if (chart) found.chart = [chart.width, chart.height];
    for (const node of Array.from(pane.querySelectorAll<HTMLElement>('*'))) {
      if (node.closest('svg') || node.closest('.sr-only')) continue;
      const own = getComputedStyle(node);
      if (own.display === 'none' || own.display === 'contents') continue;
      const rect = node.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) continue;
      const inside = node.matches('h3 a') ? node.parentElement?.getBoundingClientRect() ?? rect : rect;
      const out = Math.max(inside.right - at.right, inside.bottom - at.bottom, at.left - inside.left, at.top - inside.top);
      if (out > 1.5) found.spills.push(`${node.tagName.toLowerCase()}.${node.className} by ${Math.round(out)} px`);
      const text = Array.from(node.childNodes).some((child) => child.nodeType === 3 && (child.textContent ?? '').trim() !== '');
      if (!text) continue;
      found.smallest = Math.min(found.smallest, Number.parseFloat(own.fontSize));
      if (own.overflowX !== 'visible' && node.scrollWidth > node.clientWidth + 1 && !node.title) {
        found.cut.push((node.textContent ?? '').trim().slice(0, 40));
      }
    }
    return found;
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

for (const [name, prefix] of [['', ''], [' in the new look', 'next-']] as const) test(`the monitoring wall of small cards${name}`, { skip: skipWithout(BROWSERS) }, async (t) => {
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
        await open(tab, origin, prefix + language, width, height);
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
        assert.deepEqual(await touching(tab), [], 'the words of a pH window never touch one another or the mark');
      });
    }

    for (const [width, height] of [[3440, 1440], [5120, 1440], [1920, 1080]] as const) {
      await t.test(`going into a tank at ${width}x${height}: the Big card beside the overview, both whole`, async () => {
        await open(tab, origin, prefix + 'tr-pane', width, height);
        const pane = await docked(tab);
        assert.equal(pane.mode, 'beside');
        // beside the cards and under the band: nothing of the overview lies under the pane
        assert.ok(pane.left >= pane.cardsRight - 0.5, `the pane starts at ${pane.left}, the cards end at ${pane.cardsRight}`);
        assert.ok(pane.top >= pane.bandBottom - 0.5 && pane.bottom <= height + 0.5 && pane.right <= width + 0.5);
        // the Big card at a unit that can be read, its chart the dominant picture, nothing cut or outside
        assert.ok(pane.unit >= 14 && pane.smallest >= 11, `unit ${pane.unit}, smallest text ${pane.smallest}`);
        assert.ok(pane.chart[0] > 0.8 * pane.card[0] && pane.chart[1] > 0.35 * pane.card[1], `chart ${pane.chart} in card ${pane.card}`);
        assert.deepEqual([pane.spills, pane.cut], [[], []]);
        // the overview is alive beside it: the same cards in the same order, only narrower, each still whole
        const seen = await look(tab);
        assert.equal(seen.cards, 20);
        assert.deepEqual([seen.spills, seen.cut, seen.never], [[], [], []]);
        assert.ok(seen.smallest >= 11, `the smallest text is ${seen.smallest} px`);
        assert.equal(seen.pageScrolls, false);
        assert.deepEqual(await ages(tab), []);
        assert.deepEqual(await touching(tab), []);
        // the open card is marked among the others
        assert.equal(await tab.locator('.monitor-grid > .monitor-card.is-open').count(), 1);
        // closing (the pane leaves the dock) gives the cards the whole width back
        const before = await tab.evaluate(() => (document.querySelector('.monitor-grid > .monitor-card') as HTMLElement).getBoundingClientRect().width);
        await tab.evaluate(() => {
          document.querySelector('#monitor-dock .monitor-window')?.remove();
          document.dispatchEvent(new CustomEvent('dock:changed'));
        });
        await tab.waitForTimeout(100);
        const after = await look(tab);
        const width2 = await tab.evaluate(() => {
          const cards = Array.from(document.querySelectorAll<HTMLElement>('.monitor-grid > .monitor-card'));
          return Math.max(...cards.map((card) => card.getBoundingClientRect().right));
        });
        assert.ok(width2 > width - 40, `the cards reach ${width2} of ${width}`);
        assert.deepEqual([after.cards, after.onScreen, after.pages], [20, 20, '1']);
        assert.ok(before > 0);
      });
    }

    await t.test('a band of three lines keeps its first line on the screen and the cards whole under it', async () => {
      await open(tab, origin, prefix + 'tr', 1920, 1080);
      const lines = async (): Promise<{ cut: string[]; height: number; rows: number }> => tab.evaluate(() => {
        const band = document.querySelector('.monitor-band') as HTMLElement;
        const box = band.getBoundingClientRect();
        const cut: string[] = [];
        const tops = new Set<number>();
        for (const node of Array.from(band.querySelectorAll<HTMLElement>('.monitor-head, .monitor-tally li, .monitor-strip li'))) {
          const rect = node.getBoundingClientRect();
          tops.add(Math.round(rect.top));
          if (rect.top < Math.max(box.top, 0) - 0.5 || rect.bottom > box.bottom + 0.5) cut.push((node.textContent ?? '').trim().slice(0, 30));
        }
        return { cut, height: box.height, rows: tops.size };
      });
      const before = await lines();
      assert.deepEqual(before.cut, []);
      // more chips than two lines hold (a hall-wide alarm in a long language)
      await tab.evaluate(() => {
        const strip = document.querySelector('.monitor-strip') as HTMLElement;
        const chip = strip.querySelector('li') as HTMLElement;
        for (let more = 0; more < 6; more += 1) strip.append(chip.cloneNode(true));
        window.dispatchEvent(new Event('resize'));
      });
      await tab.waitForTimeout(150);
      const after = await lines();
      assert.ok(after.rows > before.rows && after.height > before.height + 10, `${after.rows} lines, ${after.height} px`);
      assert.deepEqual(after.cut, [], 'no line of the band lies outside it');
      const seen = await look(tab);
      assert.deepEqual([seen.spills, seen.cut, seen.never], [[], [], []]);
      assert.equal(seen.pageScrolls, false);
    });

    await t.test('a window too low for a readable card beside the cards: the pane lies over them, never hidden', async () => {
      await open(tab, origin, prefix + 'tr-pane', 1280, 720);
      const pane = await docked(tab);
      assert.equal(pane.mode, 'full');
      assert.ok(pane.right - pane.left > 0.9 * 1280, `the pane is ${pane.right - pane.left} px wide`);
      assert.ok(pane.card[0] > 0 && pane.card[1] > 0);
    });

    for (const [width, height] of [[3440, 1440], [5120, 1440], [2560, 1440], [3840, 2160]] as const) {
      await t.test(`twenty-four cards are one screen at ${width}x${height}, the age under every figure`, async () => {
        await open(tab, origin, prefix + 'tr', width, height);
        await twentyFour(tab);
        const seen = await look(tab);
        assert.deepEqual([seen.cards, seen.onScreen, seen.pages], [24, 24, '1']);
        assert.deepEqual([seen.spills, seen.cut, seen.never], [[], [], []]);
        assert.ok(seen.smallest >= 11, `the smallest text is ${seen.smallest} px`);
        assert.deepEqual(await ages(tab), []);
      });
    }

    await t.test('twenty-four cards on 1920x1080 turn pages rather than lose the age or shrink the type', async () => {
      await open(tab, origin, prefix + 'tr', 1920, 1080);
      await twentyFour(tab);
      const seen = await look(tab);
      assert.ok(seen.smallest >= 11, `the smallest text is ${seen.smallest} px`);
      assert.deepEqual([seen.spills, seen.cut, seen.never], [[], [], []]);
      assert.deepEqual(await ages(tab), []);
    });

    await t.test('a board read from across the room: its type at the legible unit, the wall turning pages', async () => {
      await open(tab, origin, prefix + 'en', 1920, 1080);
      const before = await look(tab);
      // a 55" Full HD TV read from 3 m (the board's Wall screen tab: data-screen-inches, data-distance-m on the grid)
      await tab.evaluate(() => {
        const grid = document.querySelector('.monitor-grid') as HTMLElement;
        grid.dataset.screenInches = '55.0';
        grid.dataset.distanceM = '3.0';
        window.dispatchEvent(new Event('resize'));
      });
      await tab.waitForTimeout(150);
      const far = await look(tab);
      const units = await tab.evaluate(() => {
        const cards = Array.from(document.querySelectorAll<HTMLElement>('.monitor-grid > .monitor-card'))
          .filter((card) => { const box = card.getBoundingClientRect(); return box.bottom > 1 && box.top < innerHeight - 1; });
        const band = document.querySelector('.monitor-band') as HTMLElement;
        return { cards: cards.map((card) => Number.parseFloat(getComputedStyle(card.firstElementChild as Element).fontSize)),
                 band: Number.parseFloat(getComputedStyle(band).fontSize) };
      });
      const legible = legibleUnit(55, 3, 1920, 1080);
      assert.ok(Number(far.pages) > Number(before.pages), `${far.pages} pages from 3 m, ${before.pages} at the desk`);
      assert.ok(units.cards.length > 0 && units.cards.every((unit) => unit >= legible - 0.5), `units ${units.cards} under ${legible}`);
      assert.ok(units.band >= legibleUnit(55, 3, 1920, 1080, 1) - 0.5, `band ${units.band}`);
      assert.deepEqual([far.spills, far.cut, far.never], [[], [], []]);
      assert.equal(far.pageScrolls, false, 'the screen itself never scrolls');
      assert.deepEqual(await ages(tab), []);
      // the board says no distance any more: the wall is as it was
      await tab.evaluate(() => {
        const grid = document.querySelector('.monitor-grid') as HTMLElement;
        delete grid.dataset.distanceM;
        window.dispatchEvent(new Event('resize'));
      });
      await tab.waitForTimeout(150);
      assert.equal((await look(tab)).pages, before.pages);
    });

    await t.test('a low window turns pages rather than shrink the type, and the keys turn them', async () => {
      await open(tab, origin, prefix + 'en', 1280, 720);
      const first = await look(tab);
      assert.ok(Number(first.pages) > 1, `${first.pages} pages`);
      assert.ok(first.smallest >= 11, `the smallest text is ${first.smallest} px`);
      assert.deepEqual([first.cut, first.never, first.spills], [[], [], []]);
      assert.equal(first.pageScrolls, false, 'the cards of the other pages never make the screen itself scroll');
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

    await t.test('on a paged wall: Home goes to the worst card, a chip turns to its card, a poll keeps the focus', async () => {
      await open(tab, origin, prefix + 'en', 1280, 720);
      const first = await look(tab);
      const worstPage = Number(first.page);                       // the wall opened on the page of HA-R02 (critical)
      const jump = tab.locator('#pages-worst');
      assert.equal(await jump.isHidden(), true, 'on the worst card\'s page there is nowhere to jump');
      // another page: the band says where the worst card is, and Home is the one key to it
      const other = worstPage === 1 ? 'PageDown' : 'PageUp';
      await tab.keyboard.press(other);
      await tab.waitForTimeout(50);
      assert.notEqual(Number((await look(tab)).page), worstPage);
      assert.equal(await jump.isVisible(), true);
      assert.equal((await jump.locator('[data-page-worst-text]').textContent())?.trim(), String(worstPage));
      assert.equal(await jump.getAttribute('data-state'), 'critical');
      await tab.keyboard.press('Home');
      await tab.waitForTimeout(50);
      assert.equal(Number((await look(tab)).page), worstPage);
      assert.equal(await tab.evaluate(() => document.activeElement?.closest('.monitor-card')?.querySelector('h3')?.textContent?.trim()), 'HA-R02');
      assert.equal(await jump.isHidden(), true);
      // the button does the same as the key
      await tab.keyboard.press(other);
      await tab.waitForTimeout(50);
      await jump.click();
      await tab.waitForTimeout(50);
      assert.equal(Number((await look(tab)).page), worstPage);
      // a chip's code turns to the page of its card (review R8): from the last page to the warning card's
      const pages = Number(first.pages);
      for (let turn = 0; turn < pages; turn += 1) await tab.keyboard.press('PageDown');
      await tab.waitForTimeout(50);
      assert.equal(Number((await look(tab)).page), pages);
      const chip = tab.locator('.monitor-strip a', { hasText: 'HA-K02' }).first();
      const target = await chip.evaluate((link: HTMLAnchorElement) => {
        const card = document.getElementById(new URL(link.href).hash.slice(1)) as HTMLElement;
        const grid = card.parentElement as HTMLElement;
        const index = Array.from(grid.querySelectorAll(':scope > .monitor-card')).indexOf(card);
        return Math.floor(index / Number(grid.dataset.per)) + 1;
      });
      await chip.click();
      await tab.waitForTimeout(50);
      assert.equal(Number((await look(tab)).page), target);
      // a poll replaces the whole band (its page indicator comes hidden from the server): the button that had the
      // focus has it again, and the page shown is the same
      for (let turn = 0; turn < pages; turn += 1) await tab.keyboard.press('PageDown');
      await tab.locator('#pages-prev').focus();
      await tab.evaluate(() => {
        const grid = document.querySelector('.monitor-grid') as HTMLElement;
        const band = grid.querySelector('.monitor-band') as HTMLElement;
        const fresh = band.cloneNode(true) as HTMLElement;
        (fresh.querySelector('[data-pages]') as HTMLElement).hidden = true;         // as the server prints it
        (fresh.querySelector('[data-pages-text]') as HTMLElement).textContent = '';
        band.replaceWith(fresh);
        grid.dispatchEvent(new CustomEvent('poll:merged', { bubbles: true, detail: { replaced: [{ old: band, node: fresh }], inserted: [], removed: [] } }));
      });
      await tab.waitForTimeout(50);
      assert.equal(await tab.evaluate(() => document.activeElement?.id), 'pages-prev');
      const kept = await look(tab);
      assert.deepEqual([Number(kept.page), kept.indicator], [pages, `${pages} / ${pages}`]);
    });
  } finally {
    await browser.close();
    server.close();
  }
});
