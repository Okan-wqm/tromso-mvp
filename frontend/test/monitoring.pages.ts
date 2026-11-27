// Operations › Monitoring in the new look in a real browser (Playwright on the machine's own Chrome or Edge, as the other
// page tests), on the pages the real views printed in the test run's database from THE test world (core/test_world.py
// `world` and `monitoring_world`: a unit in every state a card can be in), kept in .build/monitor-pages by
// monitoring/tests/test_next_pages.py (never a recording of a real database: the repository is public). Each page is the
// SHELL the server prints (no card, "Loading the cards…"), served under the product's Content-Security-Policy with the
// nonce it was printed with, with every sheet and script it names; its polls (frontend/poll.ts: the start-up gate, the
// merge by key) are answered with the fragments the same views printed, and the strip with its own. Run by
// `npm run test:pages` after the Django tests (CI's Django job); missing pages fail it, never skip it. It holds:
//   - every screen (Small, Simple, Detailed, Big, a board of Operator view cards) at 1440, 1920 and 390 px, the Small and
//     the Simple cards (every unit's default) in English, Norwegian and Turkish, the others in English: the cards come
//     with the first poll; every card has its link to Tank › Water; every state's glyph is drawn (a mask of the icon
//     set) and its word is there; no CSP violation, no critical or serious axe finding, every card text at 4.5:1 on
//     what it stands on, nothing scrolls sideways;
//   - the Big screen in English, Norwegian and Turkish: the design's Big card (its head over a hairline, its values and
//     its water's tiles, the chart's frame, the three boxes, an empty unit's cells), nothing of a tile cut or out of
//     its place, its text at 4.5:1 in the six themes;
//   - the pane: the Big card of the unit gone into, filled by its own poll, with its own link to the water, the design's
//     Big card, standing BESIDE the cards (never above them) at 1440 and 1920 px, its Close a 44 px target;
//   - the wall of Small cards at 1920x1080 and 3840x2160: one screen, nothing scrolls, no card text under 11 px, nothing
//     over the band, a card's state word or the wall's buttons (the toolbar is its two buttons);
//   - polling and the announcer in the new look: a card that gets worse is said ("TW-01 is now Critical."), a failed
//     poll marks the grid not updated, the next answer says "Updated again."; a first answer that fails says the
//     cards cannot be read, and the cards come when the server answers again.
// With SHOTS=<folder> it writes the screenshots.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { extname, join, resolve } from 'node:path';

import type { Page } from 'playwright-core';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { watchCsp } from './checks.js';
import { policy } from './csp.js';
import { legibleUnit } from '../wall/slots.js';

const PAGES = resolve('.build/monitor-pages');
const TYPES: Record<string, string> = { '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' };
const LANGUAGES = ['en', 'nb', 'tr'] as const;

interface Answer { status: number; next: string }
interface Screen { page: Answer; cards: Answer; worse?: Answer; pane?: Answer; nonce: string; lang: string }

// What the stub answers with now: the screen whose page was asked last, and how the grid's polls are answered.
let current = 'small-en';
let mode: 'cards' | 'worse' | 'fail' = 'cards';
// When set, the stub answers static/css/glyphs.css with a 404 (a sheet that did not load).
let noGlyphs = false;

/** A kept answer; '' when there is none (the stub then answers 404, as the server does for a pane that is gone). */
function read(name: string): string {
  const file = join(PAGES, `${name}.html`);
  return existsSync(file) ? readFileSync(file, 'utf8') : '';
}

/** The critical and serious axe findings, each with the elements it found (axe-core served from `origin`/axe.js). */
async function axeFindings(tab: Page, origin: string): Promise<string[]> {
  await tab.addScriptTag({ url: `${origin}/axe.js` });
  return tab.evaluate(async () => {
    const axe = (window as unknown as { axe: { run: (context: unknown, options: unknown) => Promise<{ violations: { id: string; impact: string; nodes: { target: string[] }[] }[] }> } }).axe;
    const result = await axe.run(document, { resultTypes: ['violations'] });
    return result.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious')
      .map((v) => `${v.id}: ${v.nodes.map((node) => node.target.join(' ')).slice(0, 4).join(' | ')}`);
  });
}

/** What reaches past the right edge of the window (the elements, outermost first): [] when nothing does. */
function sideways(tab: Page): Promise<string[]> {
  return tab.evaluate(() => {
    const past: string[] = [];
    for (const element of document.querySelectorAll<HTMLElement>('body *')) {
      const box = element.getBoundingClientRect();
      if (box.right <= document.documentElement.clientWidth + 1 || box.width === 0) continue;
      if (element.parentElement && element.parentElement.getBoundingClientRect().right > document.documentElement.clientWidth + 1
          && element.parentElement !== document.body) continue;
      past.push(`${element.tagName.toLowerCase()}.${String(element.className).split(' ').slice(0, 3).join('.')} to ${Math.round(box.right)}`);
    }
    return past.slice(0, 8);
  });
}

function serve(index: Record<string, Screen>): Promise<Server> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    const screen = index[current];
    const headers = { 'Content-Security-Policy': policy(screen?.nonce ?? '') };
    const page = /^\/page\/([\w-]+)$/.exec(url.pathname);
    const html = (body: string, extra: Record<string, string> = {}): void => {
      response.writeHead(200, { ...headers, 'Content-Type': 'text/html; charset=utf-8', ...extra }).end(body);
    };
    if (page) {
      current = page[1] ?? '';
      const found = index[current];
      if (!found) return void response.writeHead(404, headers).end();
      response.writeHead(200, { 'Content-Security-Policy': policy(found.nonce), 'Content-Type': 'text/html; charset=utf-8' })
        .end(read(`page-${current}`));
      return;
    }
    const next = { 'X-Poll-Next': `${url.pathname}${url.search}`, 'Cache-Control': 'no-store' };
    if (url.pathname === '/operations/monitoring/cards/') {
      if (mode === 'fail') return void response.writeHead(503, headers).end('The cards cannot be read just now.');
      const body = read(mode === 'worse' && screen?.worse ? `cards-${current}-worse` : `cards-${current}`);
      return body ? html(body, next) : void response.writeHead(404, headers).end();
    }
    if (url.pathname === '/operations/monitoring/pane/') {
      const body = read(`pane-${current}`);
      return body ? html(body, next) : void response.writeHead(404, headers).end();
    }
    if (url.pathname === '/ui/strip/') return html(read(`strip-${screen?.lang ?? 'en'}`));
    let file = '';
    if (noGlyphs && url.pathname.endsWith('/glyphs.css')) return void response.writeHead(404, headers).end();
    if (url.pathname.startsWith('/static/')) file = resolve(`.${url.pathname}`);
    else if (url.pathname === '/axe.js') file = resolve('node_modules/axe-core/axe.min.js');
    if (file && file.startsWith(resolve('.')) && existsSync(file)) {
      response.writeHead(200, { ...headers, 'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream' })
        .end(readFileSync(file));
      return;
    }
    response.writeHead(404, headers).end();
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

/** The text of the cards, the band and the pane (or of `within`) under 4.5:1 on the ground it stands on: the nearest
 *  opaque background, and every hatch an ancestor draws behind it on the way there (a ::before with a gradient: the
 *  blind head's, review round 2, B4: the text lay on its stripe at 3.2 to 3.7:1), against the hatch's stripe. */
function lowContrast(tab: Page, within = '.monitor-grid *, .monitor-dock *'): Promise<string[]> {
  return tab.evaluate((selector) => {
    // (a colour as rgb() or, from color-mix, as color(srgb 0..1 ...))
    const parse = (value: string): number[] => {
      const found = (value.match(/[\d.]+/g) ?? []).map(Number);
      return value.trim().startsWith('color(') ? found.map((each, index) => (index < 3 ? each * 255 : each)) : found;
    };
    const lum = ([r = 0, g = 0, b = 0]: number[]): number => {
      const c = [r, g, b].map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
      return 0.2126 * (c[0] ?? 0) + 0.7152 * (c[1] ?? 0) + 0.0722 * (c[2] ?? 0);
    };
    const grounds = (element: Element): number[][] => {
      const stripes: number[][] = [];
      for (let at: Element | null = element; at; at = at.parentElement) {
        const value = parse(getComputedStyle(at).backgroundColor);
        if (value.length === 3 || (value[3] ?? 0) > 0.5) return [value.slice(0, 3), ...stripes];
        const before = getComputedStyle(at, '::before');
        const stripe = before.content !== 'none' && before.backgroundImage.includes('gradient')
          ? /(?:rgba?|color)\([^)]*\)/.exec(before.backgroundImage) : null;
        if (stripe) stripes.push(parse(stripe[0]).slice(0, 3));
      }
      return [parse(getComputedStyle(document.body).backgroundColor).slice(0, 3), ...stripes];
    };
    const low: string[] = [];
    for (const element of document.querySelectorAll(selector)) {
      const own = Array.from(element.childNodes).some((node) => node.nodeType === 3 && (node.textContent ?? '').trim());
      const box = element.getBoundingClientRect();
      if (!own || box.width < 2 || element.closest('svg, .sr-only, [aria-hidden="true"]')) continue;
      const fore = parse(getComputedStyle(element).color).slice(0, 3);
      for (const behind of grounds(element)) {
        const [high, lower] = [lum(fore), lum(behind)].sort((a, b) => b - a);
        const ratio = ((high ?? 0) + 0.05) / ((lower ?? 0) + 0.05);
        if (ratio < 4.5) low.push(`${element.className || element.tagName} "${(element.textContent ?? '').trim().slice(0, 30)}" ${ratio.toFixed(2)}`);
      }
    }
    return low;
  }, within);
}

/** On the desk page's cards: what is cut that must never be (a code, a state's word, a figure, "old", the saturation
 *  beside a label, a reason's figure and bound, the fish line, a figure running out of its cell), and cards of one kind
 *  that are not one size (Small cards; Big cards of a stocked unit, a row at a time; cards that flow). [] when none is. */
function uncut(tab: Page): Promise<string[]> {
  return tab.evaluate(() => {
    const wrong: string[] = [];
    const cards = Array.from(document.querySelectorAll<HTMLElement>('.monitor-grid > .monitor-card'));
    const sizes = new Map<string, Set<string>>();
    for (const card of cards) {
      const box = card.getBoundingClientRect();
      // (a Big card of a stocked unit is as tall as the tallest of its ROW, its rows each as high as their own cards;
      // an empty unit's Big card takes its own height: review H2, the coordinator's item 4)
      const fill = card.hasAttribute('data-fill');
      const kind = fill ? (card.dataset.state === 'empty' ? '' : `a row of Big cards at ${Math.round(box.top)}`)
        : card.className.includes('is-fit') ? 'fit' : 'flow';
      if (kind && !sizes.has(kind)) sizes.set(kind, new Set());
      sizes.get(kind)?.add(`${Math.round(box.width)}x${Math.round(box.height)}`);
      const code = card.querySelector('h3')?.textContent?.trim() ?? '?';
      // (review round 2, B2: the oxygen's saturation beside its label, the reason's figure and the bound it is past,
      // the fish line's figures; a label that says a second figure has it in a slot of its own)
      for (const label of Array.from(card.querySelectorAll<HTMLElement>('dt'))) {
        if ((label.textContent ?? '').includes(' · ') && !label.querySelector('.monitor-beside')) {
          wrong.push(`${code}: "${(label.textContent ?? '').trim()}" has no slot for its second figure`);
        }
      }
      for (const node of Array.from(card.querySelectorAll<HTMLElement>(
        'h3, .monitor-state-word, dd b, [data-old], dt .monitor-beside, .monitor-figure, .monitor-bound, .monitor-card-fish'))) {
        if (!node.offsetParent) continue;
        const own = node.getBoundingClientRect();
        const cut = (node.scrollWidth > node.clientWidth + 1 && getComputedStyle(node).overflowX !== 'visible')
          || (node.scrollHeight > node.clientHeight + 1 && getComputedStyle(node).overflowY !== 'visible');
        let clipped = false;
        for (let up = node.parentElement; up && up !== card.parentElement; up = up.parentElement) {
          const style = getComputedStyle(up);
          const frame = up.getBoundingClientRect();
          if (style.overflowX !== 'visible' && (own.right > frame.right + 1.5 || own.left < frame.left - 1.5)) clipped = true;
          if (style.overflowY !== 'visible' && (own.bottom > frame.bottom + 1.5 || own.top < frame.top - 1.5)) clipped = true;
        }
        const cell = node.closest('dl')?.getBoundingClientRect();
        if (cut || clipped || (cell && own.right > cell.right + 1.5)) wrong.push(`${code}: "${(node.textContent ?? '').trim()}"`);
      }
    }
    if (innerWidth >= 1100) for (const [kind, seen] of sizes) if (seen.size > 1) wrong.push(`${kind} cards of ${seen.size} sizes: ${[...seen].join(' ')}`);
    return wrong;
  });
}

/** On a wall: what another element lies over (review round 2, B1: the new look's toolbar was drawn over the band, and
 *  the wall's buttons over a card's state word): the band's time and every tally, the state word of every card on the
 *  screen and the wall's buttons must each be what the screen shows at their middle; and the toolbar is no wider than
 *  its buttons. [] when nothing is covered. */
function covered(tab: Page): Promise<string[]> {
  return tab.evaluate(() => {
    const wrong: string[] = [];
    const seen = (node: HTMLElement): boolean => {
      const at = node.getBoundingClientRect();
      const top = document.elementFromPoint(at.left + at.width / 2, at.top + at.height / 2);
      return top !== null && (node === top || node.contains(top));
    };
    const words = Array.from(document.querySelectorAll<HTMLElement>('.monitor-grid > .monitor-card .monitor-state-word'))
      .filter((word) => { const at = word.getBoundingClientRect(); return at.top >= 0 && at.bottom <= innerHeight; });
    const buttons = Array.from(document.querySelectorAll<HTMLElement>('.monitor-actions .button'));
    for (const node of [...document.querySelectorAll<HTMLElement>('.monitor-band .monitor-head, .monitor-tally li'), ...words, ...buttons]) {
      if (!seen(node)) wrong.push(`covered: "${(node.textContent ?? '').trim().slice(0, 40)}"`);
    }
    const toolbar = document.querySelector<HTMLElement>('.monitor-toolbar')?.getBoundingClientRect();
    const actions = document.querySelector<HTMLElement>('.monitor-actions')?.getBoundingClientRect();
    if (toolbar && actions && toolbar.width > actions.width + 2) wrong.push(`the toolbar is ${toolbar.width} px wide, its buttons ${actions.width}`);
    if (!words.length || !buttons.length) wrong.push(`${words.length} state words, ${buttons.length} buttons on the screen`);
    return wrong;
  });
}

/** The Big card (a full-height fitted card: the Big screen's, a board's, the pane's, a wall's) as the design draws it in
 *  the new look ("Suderra Console", Monitoring, the Big card and "Focus · the big card beside the overview"): the head
 *  over a hairline, nothing of it lying over the unit's code; its four first values hairline tiles; the Deffeyes chart
 *  in a hairline frame, the region the water is in hatched, an old mark hollow (the sheet's colour) even in a region;
 *  the water of its middle point as the design's tiles, four to a line or two on a phone, exactly where the server says
 *  they fit (`data-tiles`), a row a value elsewhere; what to dose, the other points (each value with its age) and the
 *  stock hairline boxes; a unit with no fish says the unit, the chart's place and the three boxes, and is no taller
 *  than what it says. Never cut: every cell of a tile whole inside its tile, every row of the water inside its place,
 *  the card's foot ("State from") inside the card. [] when the cards are so. */
function bigCards(tab: Page, root = '.monitor-grid'): Promise<string[]> {
  return tab.evaluate((selector) => {
    const wrong: string[] = [];
    const line = (element: Element | null, side: 'Top' | 'Right' | 'Bottom' | 'Left'): number =>
      (element ? Number.parseFloat(getComputedStyle(element)[`border${side}Width`]) : 0);
    const inside = (node: Element, frame: DOMRect): boolean => {
      const box = node.getBoundingClientRect();
      return box.left >= frame.left - 1 && box.right <= frame.right + 1 && box.top >= frame.top - 1 && box.bottom <= frame.bottom + 1;
    };
    const meets = (a: DOMRect, b: DOMRect): boolean =>
      a.width > 0 && b.width > 0 && a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1;
    const colour = (value: string): string => { const probe = document.createElement('i'); probe.style.color = value; document.body.append(probe); const found = getComputedStyle(probe).color; probe.remove(); return found; };
    const sheet = colour('var(--surface-sheet)');
    const cards = Array.from(document.querySelectorAll<HTMLElement>(`${selector} .monitor-card.is-fit[data-fill]`));
    if (!cards.length) wrong.push('no Big card');
    for (const card of cards) {
      const code = card.querySelector('h3')?.textContent?.trim() ?? '?';
      const frame = card.getBoundingClientRect();
      if (!frame.height) continue;           // (a card on another page of a wall)
      const head = card.querySelector(':scope > .monitor-card-head');
      if (line(head, 'Bottom') < 1) wrong.push(`${code}: no hairline under the head`);
      const title = card.querySelector('h3 a')?.getBoundingClientRect();
      for (const other of Array.from(head?.querySelectorAll<HTMLElement>('.monitor-card-state > *, .monitor-card-name > p') ?? [])) {
        if (title && other.offsetParent && meets(title, other.getBoundingClientRect())) wrong.push(`${code}: "${(other.textContent ?? '').trim().slice(0, 20)}" lies over the code`);
      }
      for (const tile of Array.from(card.querySelectorAll<HTMLElement>('.w-value > dl'))) {
        if (line(tile, 'Top') < 1 || line(tile, 'Right') < 1 || line(tile, 'Bottom') < 1) wrong.push(`${code}: a value that is not a tile`);
      }
      const chart = card.querySelector<SVGElement>('svg.monitor-chart-svg');
      if (chart) {
        if (Number.parseFloat(getComputedStyle(chart).outlineWidth) < 1) wrong.push(`${code}: the chart has no frame`);
        for (const zone of ['co2', 'nh3']) {
          const region = chart.querySelector(`.chart-region-${zone}`);
          if (!region) continue;
          const hatched = getComputedStyle(region).fill.startsWith('url(');
          const inZone = chart.classList.contains(`in-${zone}`) && chart.classList.contains('is-critical');
          if (hatched !== inZone) wrong.push(`${code}: the ${zone} region ${hatched ? 'hatched' : 'not hatched'} with the water ${inZone ? 'in' : 'out of'} it`);
        }
        // (its words stand apart: on a phone the picture keeps the width at which they do and scrolls: review L4)
        const words = Array.from(chart.querySelectorAll('text, .chart-locator')).map((node) => [node.textContent?.trim().slice(0, 16) ?? '', node.getBoundingClientRect()] as const)
          .filter(([, box]) => box.width > 0);
        words.forEach(([one, a], index) => words.slice(index + 1).forEach(([two, b]) => {
          if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1) wrong.push(`${code}: "${one}" lies over "${two}" in the chart`);
        }));
        const mark = chart.querySelector('.chart-water');
        if (mark && chart.classList.contains('is-old') && getComputedStyle(mark).fill !== sheet) wrong.push(`${code}: an old mark is not hollow (${getComputedStyle(mark).fill})`);
      }
      for (const box of Array.from(card.querySelectorAll<HTMLElement>(':is(.w-dosing, .w-points, .w-stock) > section'))) {
        if (line(box, 'Top') < 1 || line(box, 'Left') < 1) wrong.push(`${code}: a box without its hairline`);
      }
      for (const value of Array.from(card.querySelectorAll<HTMLElement>('.w-points section > span[title]'))) {
        // (a figure, in any language: a value said in words, "no data", has no age)
        if (/\d/.test(value.textContent ?? '') && !value.querySelector('.monitor-point-age')?.textContent?.trim()) wrong.push(`${code}: an other point's value without its age`);
      }
      if (card.dataset.state === 'empty') {
        for (const part of ['.monitor-cells', '.w-chart', '.w-dosing', '.w-points', '.w-stock']) {
          if (!card.querySelector<HTMLElement>(part)?.offsetParent) wrong.push(`${code}: an empty unit's card without ${part}`);
        }
      }
      const basis = card.querySelector('[data-basis]');
      if (basis && !inside(basis, frame)) wrong.push(`${code}: its foot ("State from") is not inside the card`);
      // (on the desk an empty unit's card is as tall as what it says, never a screen of blank: its foot at its bottom)
      if (basis && card.dataset.state === 'empty' && !card.closest('.monitor-dock') && !document.documentElement.hasAttribute('data-wall')
          && frame.bottom - basis.getBoundingClientRect().bottom > 40) wrong.push(`${code}: an empty unit's card ${Math.round(frame.bottom - basis.getBoundingClientRect().bottom)} px taller than what it says`);
      const place = card.querySelector<HTMLElement>('.w-water_table');
      for (const rows of Array.from(card.querySelectorAll<HTMLElement>('.w-water_table .monitor-rows'))) {
        const tiles = rows.hasAttribute('data-tiles');
        for (const table of Array.from(rows.querySelectorAll<HTMLElement>(':scope > [role="table"]'))) {
          const values = Array.from(table.querySelectorAll<HTMLElement>(':scope > [role="row"]')).filter((row) => row.querySelector('[role="rowheader"]'));
          const drawnAsTiles = values.length > 0 && getComputedStyle(values[0] as Element).display !== 'contents';
          if (drawnAsTiles !== tiles) wrong.push(`${code}: ${values.length} values drawn as ${drawnAsTiles ? 'tiles' : 'rows'}, the server says ${tiles ? 'tiles' : 'rows'}`);
          if (!tiles) continue;
          const head = table.querySelector<HTMLElement>(':scope > [role="row"]:has(> [role="columnheader"])');
          if (head && head.getBoundingClientRect().width > 2) wrong.push(`${code}: the water's head is shown over tiles`);
          const lines = new Map<number, number>();
          for (const row of values) {
            const box = row.getBoundingClientRect();
            lines.set(Math.round(box.top), (lines.get(Math.round(box.top)) ?? 0) + 1);
            if (line(row, 'Bottom') < 1 || line(row, 'Right') < 1) wrong.push(`${code}: a water tile without its hairline`);
            for (const cell of Array.from(row.children)) {
              const shown = getComputedStyle(cell);
              if (shown.display === 'none' || !cell.textContent?.trim()) continue;
              const cut = (cell as HTMLElement).scrollWidth > (cell as HTMLElement).clientWidth + 1 && shown.overflowX !== 'visible';
              if (cut || !inside(cell, box)) wrong.push(`${code}: "${(cell.textContent ?? '').trim()}" is cut or out of its tile`);
            }
          }
          const most = Math.max(...lines.values());
          if (most > (frame.width < 480 ? 2 : 4)) wrong.push(`${code}: ${most} water tiles to a line`);
          if (values.length > 1 && most < 2) wrong.push(`${code}: the water tiles stand one to a line`);
        }
      }
      if (place) {
        const room = place.getBoundingClientRect();
        for (const row of Array.from(place.querySelectorAll<HTMLElement>('[role="row"]'))) {
          const box = row.getBoundingClientRect();
          if (box.height > 2 && box.bottom > room.bottom + 1.5) wrong.push(`${code}: "${(row.textContent ?? '').trim().slice(0, 30)}" below the water's place`);
        }
      }
    }
    return wrong;
  }, root);
}

/** The cards of the grid that lie over one another (a Big card drawn over the Small cards under it: review H2). */
function overlapping(tab: Page): Promise<string[]> {
  return tab.evaluate(() => {
    const cards = Array.from(document.querySelectorAll<HTMLElement>('.monitor-grid > .monitor-card'));
    const boxes = cards.map((card) => [card.querySelector('h3')?.textContent?.trim() ?? '?', card.getBoundingClientRect()] as const);
    const wrong: string[] = [];
    boxes.forEach(([a, one], index) => boxes.slice(index + 1).forEach(([b, two]) => {
      if (one.left < two.right - 1 && two.left < one.right - 1 && one.top < two.bottom - 1 && two.top < one.bottom - 1) wrong.push(`${a} over ${b}`);
    }));
    return wrong;
  });
}

/** Every control of the Big cards, the pane, the band and the overview's code links whose hit box is under 44 by 44 px
 *  (the brief's target): the box is found as the browser finds a tap, by what lies at each point around the control's
 *  middle (the control or something in it), across and down. [] when every one is a target. */
function smallTargets(tab: Page): Promise<string[]> {
  return tab.evaluate(() => {
    const selector = ['.monitor-card.is-fit h3 a', '.monitor-card.is-fit .monitor-flip', '.monitor-card.is-fit .monitor-view a',
                      '.monitor-card.is-fit[data-fill] .monitor-water-link', '.monitor-dock-close', '.monitor-band .monitor-modes a',
                      '.monitor-band .monitor-view a'].join(', ');
    const wrong: string[] = [];
    for (const control of Array.from(document.querySelectorAll<HTMLElement>(selector))) {
      if (!control.offsetParent) continue;
      control.scrollIntoView({ block: 'center', inline: 'center' });
      const box = control.getBoundingClientRect();
      if (box.width === 0) continue;
      const mine = (x: number, y: number): boolean => { const found = document.elementFromPoint(x, y); return found !== null && (found === control || control.contains(found)); };
      const x = box.left + box.width / 2;
      const y = box.top + Math.min(box.height / 2, 10);
      if (!mine(x, y)) { wrong.push(`${control.textContent?.trim() || control.id}: not reached at its middle`); continue; }
      const run = (dx: number, dy: number): number => { let n = 0; while (n < 80 && mine(x + dx * (n + 1), y + dy * (n + 1))) n += 1; return n; };
      const across = run(-1, 0) + run(1, 0) + 1;
      const down = run(0, -1) + run(0, 1) + 1;
      if (across < 44 || down < 44) wrong.push(`${(control.textContent ?? '').trim().slice(0, 20) || control.id}: ${across} x ${down} px`);
    }
    return wrong;
  });
}

/** The pane beside the overview, as the design's "Focus · the big card beside the overview": on a desk wide enough for a
 *  readable Big card and a column of Small cards, the pane stands at the right of the cards, beside them (never above
 *  them); its Close a target of at least 44 px (the brief's). [] when it does. */
function besideTheCards(tab: Page): Promise<string[]> {
  return tab.evaluate(() => {
    const wrong: string[] = [];
    const pane = document.querySelector('#monitor-dock .monitor-window')?.getBoundingClientRect();
    const cards = Array.from(document.querySelectorAll('.monitor-grid > .monitor-card')).map((card) => card.getBoundingClientRect());
    if (!pane || !cards.length) return ['no pane or no cards'];
    const right = Math.max(...cards.map((box) => box.right));
    const top = Math.min(...cards.map((box) => box.top));
    if (pane.left < right - 0.5) wrong.push(`the pane starts at ${pane.left}, the cards end at ${right}`);
    if (top > pane.bottom) wrong.push(`the cards start (${top}) under the pane (${pane.bottom})`);
    const close = document.querySelector('#monitor-dock .monitor-dock-close')?.getBoundingClientRect();
    if (!close || close.height < 44 || close.width < 44) wrong.push(`the pane's Close is ${close?.width} x ${close?.height}`);
    return wrong;
  });
}

// The six themes of the console: four days, two nights (core/theme.py).
const THEMES = ['industry', 'fjord', 'tang', 'laks', 'polarnatt', 'nordlys'] as const;

/** Card text under 4.5:1 in each of the six themes (`within`, as lowContrast), theme by theme; [] when none. */
async function lowInThemes(tab: Page, within?: string): Promise<string[]> {
  const low: string[] = [];
  for (const theme of THEMES) {
    await tab.evaluate((name) => { document.documentElement.dataset.theme = name; }, theme);
    low.push(...(await lowContrast(tab, within)).map((each) => `${theme}: ${each}`));
  }
  await tab.evaluate(() => { document.documentElement.dataset.theme = 'industry'; });
  return low;
}

interface Drawn { cards: number; links: number; states: string[]; glyphs: number; bare: number; sideways: number }

/** What the screen shows: its cards, their links to the water, their state words, the glyphs drawn and those not. */
function drawn(tab: Page, root = '.monitor-grid'): Promise<Drawn> {
  return tab.evaluate((selector) => {
    const cards = Array.from(document.querySelectorAll(`${selector} .monitor-card`));
    const shapes = Array.from(document.querySelectorAll(`${selector} .monitor-shape`)).filter((shape) => (shape as HTMLElement).offsetParent);
    return {
      cards: cards.length,
      links: cards.filter((card) => card.querySelector('a.monitor-water-link[href$="/water/"]')).length,
      states: cards.map((card) => card.querySelector('.monitor-state-word')?.textContent ?? ''),
      glyphs: shapes.filter((shape) => getComputedStyle(shape).maskImage.startsWith('url(')).length,
      bare: shapes.filter((shape) => { const box = shape.getBoundingClientRect(); return box.width < 6 || box.height < 6; }).length,
      sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  }, root);
}

async function shot(tab: Page, name: string, full = true): Promise<void> {
  if (!process.env.SHOTS) return;
  mkdirSync(process.env.SHOTS, { recursive: true });
  await tab.screenshot({ path: join(process.env.SHOTS, `monitoring-${name}.png`), fullPage: full });
}

test('Operations › Monitoring in the new look, in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  assert.ok(existsSync(join(PAGES, 'index.json')), '.build/monitor-pages is missing: the Django tests write it (monitoring.tests.test_next_pages)');
  assert.ok(existsSync(join('static', 'js', 'poll.js')), 'npm run build first (static/js)');
  const index = JSON.parse(readFileSync(join(PAGES, 'index.json'), 'utf8')) as Record<string, Screen>;
  const server = await serve(index);
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  // (one page at a time: a page a failed check left open would go on polling the stub for another screen)
  const open = async (key: string, width: number, height: number): Promise<{ tab: Page; violations: string[] }> => {
    await Promise.all(browser.contexts().flatMap((context) => context.pages()).map((page) => page.close()));
    // (reduced motion: the rail is never caught half way through its width's transition, which once looked like a
    // squeezed rail in a screenshot)
    const tab = await browser.newPage({ viewport: { width, height }, reducedMotion: 'reduce' });
    const violations = await watchCsp(tab);
    await tab.goto(`${origin}/page/${key}`);
    return { tab, violations };
  };
  try {
    for (const language of LANGUAGES) {
      for (const screen of ['small', 'simple', 'detailed', 'big', 'operator', 'mixed']) {
        // every language: Small, Simple and Big (the Big card's tiles hold the longest words: Norwegian, Turkish)
        if (language !== 'en' && !['small', 'simple', 'big'].includes(screen)) continue;
        // (the board that mixes Small and Big cards at a tablet's width too: review H2)
        for (const width of screen === 'mixed' ? [1440, 1920, 1024, 390] : [1440, 1920, 390]) {
          await t.test(`${screen} ${language} at ${width} px: the cards, their links and glyphs, CSP, axe, 4.5:1`, async () => {
            mode = 'cards';
            const key = `${screen}-${language}`;
            const { tab, violations } = await open(key, width, 900);
            await tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card');
            const seen = await drawn(tab);
            assert.ok(seen.cards >= 7, `${seen.cards} cards`);
            assert.equal(seen.links, seen.cards, 'every card links its tank\'s water');
            assert.ok(seen.states.every(Boolean), 'every card says its state');
            if (!['small', 'big', 'mixed'].includes(screen)) {
              // the design's card (monitoring/_card_next.html): every card, its Deffeyes chart's button among the actions
              // at its foot (it opens the unit's chart in the movable window), shown
              const flowing = await tab.evaluate(() => Array.from(document.querySelectorAll<HTMLElement>('.monitor-grid > .monitor-card'))
                .map((card) => [card.classList.contains('is-next'),
                  Boolean(card.querySelector<HTMLElement>('.monitor-card-actions > button[data-window]')?.offsetParent)]));
              assert.ok(flowing.every(([next, chart]) => next && chart), JSON.stringify(flowing));
            }
            if (width >= 1100) {
              // the rail keeps its width beside the top bar, whatever the strip says (its alarms sentence is long here)
              const rail = await tab.evaluate(() => [document.querySelector('.rail')?.getBoundingClientRect().width ?? 0,
                Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--rail-w'))]);
              assert.ok(Math.abs((rail[0] ?? 0) - (rail[1] ?? 0)) < 0.5, `the rail is ${rail[0]} px, not ${rail[1]}`);
            }
            assert.deepEqual(await uncut(tab), [], 'a code, a state word, a figure, the saturation, "old", the figure and bound of a reason are never cut; the cards are one size');
            if (screen === 'big' || screen === 'mixed') {
              assert.deepEqual(await bigCards(tab), [], 'the Big card of the design, nothing of it cut');
              assert.deepEqual(await overlapping(tab), [], 'no card lies over another');
              if (width === 1440) assert.deepEqual(await lowInThemes(tab), [], 'Big card text under 4.5:1 in a theme');
            }
            if (screen === 'mixed') {
              // a Small card keeps its one size beside a Big one, whatever row it stands in
              const small = await tab.evaluate(() => Array.from(document.querySelectorAll<HTMLElement>('.monitor-grid > .is-fit:not([data-fill])'))
                .map((card) => Math.round(card.getBoundingClientRect().height)));
              assert.ok(small.length >= 5 && new Set(small).size === 1, `Small card heights ${small}`);
            }
            if (['small', 'big', 'mixed'].includes(screen)) assert.deepEqual(await smallTargets(tab), [], 'every control a 44 px target');
            assert.ok(seen.glyphs > 0, 'the state glyphs are drawn');
            assert.equal(seen.bare, 0, 'no glyph is a speck');
            assert.deepEqual(seen.sideways ? await sideways(tab) : [], [], `nothing scrolls sideways (${seen.sideways} px)`);
            assert.deepEqual(await lowContrast(tab), [], 'card text under 4.5:1');
            assert.deepEqual(await axeFindings(tab, origin), [], 'axe');
            assert.deepEqual(violations, [], 'CSP violations');
            await shot(tab, `${key}-${width}`);
            await tab.close();
          });
        }
      }
    }

    await t.test('the safety cues of the new look: the edge of each state, the hatch of an old value, the glyphs, the hatch in six themes', async () => {
      mode = 'cards';
      const { tab } = await open('small-en', 1440, 900);
      await tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card');
      const cues = await tab.evaluate(() => {
        const cards = Array.from(document.querySelectorAll<HTMLElement>('.monitor-grid > .monitor-card'));
        const edge: Record<string, string> = {};
        for (const card of cards) edge[card.dataset.state ?? ''] = getComputedStyle(card).borderLeftStyle;
        const stale = cards.filter((card) => card.hasAttribute('data-stale')).map((card) => getComputedStyle(card).backgroundImage);
        const masks = new Map<string, string>();
        for (const card of cards) {
          const shape = card.querySelector('.monitor-state .monitor-shape');
          if (shape) masks.set(card.dataset.state ?? '', getComputedStyle(shape).maskImage);
        }
        return { edge, stale, masks: Array.from(masks.entries()) };
      });
      // the classic look's edge style of each state: dashed for no recent data and no limit, dotted for empty
      assert.deepEqual([cues.edge.blind, cues.edge.unjudged, cues.edge.empty, cues.edge.critical, cues.edge.ok],
                       ['dashed', 'dashed', 'dotted', 'solid', 'solid']);
      // a card whose value is old keeps its hatch strip (an old critical, TW-08, and the blind ones)
      assert.ok(cues.stale.length >= 2 && cues.stale.every((image) => image.includes('gradient')), cues.stale.join(' | '));
      // one glyph of its own for each of the seven states
      assert.equal(cues.masks.length, 7);
      assert.equal(new Set(cues.masks.map(([, mask]) => mask)).size, 7);
      // the blind head's hatch reads in the six themes (its stripe against the plate)
      for (const theme of ['fjord', 'industry', 'polarnatt', 'nordlys', 'tang', 'laks']) {
        const ratio = await tab.evaluate((name) => {
          document.documentElement.dataset.theme = name;
          const card = document.querySelector('.monitor-grid > article.monitor-blind') as HTMLElement;
          const probe = document.createElement('i');
          card.append(probe);
          const colour = (value: string): number[] => {
            probe.style.setProperty('color', value);
            const text = getComputedStyle(probe).color;
            const found = (text.match(/[0-9.]+/g) ?? []).slice(0, 3).map(Number);
            return text.startsWith('color(') ? found.map((each) => each * 255) : found;
          };
          const lum = ([r = 0, g = 0, b = 0]: number[]): number => {
            const c = [r, g, b].map((v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
            return 0.2126 * (c[0] ?? 0) + 0.7152 * (c[1] ?? 0) + 0.0722 * (c[2] ?? 0);
          };
          const [high, low] = [lum(colour('var(--hatch)')), lum(colour('var(--plate)'))].sort((a, b) => b - a);
          probe.remove();
          return ((high ?? 0) + 0.05) / ((low ?? 0) + 0.05);
        }, theme);
        assert.ok(ratio >= 1.5, `the hatch in ${theme}: ${ratio.toFixed(2)}:1`);
        // ... and the text on it still at 4.5:1 (review round 2, B4)
        assert.deepEqual(await lowContrast(tab, '.monitor-grid > .monitor-blind > .monitor-card-head *'), [], `text on the hatch in ${theme}`);
      }
      await tab.close();
      // without glyphs.css (a sheet that did not load): the classic shapes, never seven identical squares
      noGlyphs = true;
      try {
        const bare = await open('small-en', 1440, 900);
        await bare.tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card');
        const shapes = await bare.tab.evaluate(() => Array.from(new Set(Array.from(document.querySelectorAll<HTMLElement>(
          '.monitor-grid > .monitor-card .monitor-state .monitor-shape')).map((shape) => {
          const style = getComputedStyle(shape);
          return [style.clipPath, style.borderStyle, style.borderRadius, style.backgroundColor === 'rgba(0, 0, 0, 0)'].join(' ');
        }))));
        assert.ok(shapes.length >= 5, shapes.join(' | '));
        await bare.tab.close();
      } finally {
        noGlyphs = false;
      }
    });

    await t.test('the Big card: its water as tiles where the server says, wherever the table\'s head stands; the hatch reads in six themes', async () => {
      mode = 'cards';
      const { tab } = await open('big-en', 1440, 900);
      await tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card');
      // a table whose head stands last, and one with no head: the tiles are what the server said, nothing else
      const moved = await tab.evaluate(() => {
        const tables = Array.from(document.querySelectorAll<HTMLElement>('.monitor-rows[data-tiles] > [role="table"]'));
        const [first, second] = tables;
        const head = (table: HTMLElement | undefined): HTMLElement | null => table?.querySelector(':scope > [role="row"]:has(> [role="columnheader"])') ?? null;
        const one = head(first);
        if (one && first) first.append(one);
        head(second)?.remove();
        return tables.length;
      });
      assert.ok(moved >= 2, `${moved} tables of tiles`);
      assert.deepEqual(await bigCards(tab), [], 'tiles with the head last or missing');
      for (const theme of THEMES) {
        const ratio = await tab.evaluate((name) => {
          document.documentElement.dataset.theme = name;
          const parse = (value: string): number[] => (value.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
          const lum = ([r = 0, g = 0, b = 0]: number[]): number => {
            const c = [r, g, b].map((v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
            return 0.2126 * (c[0] ?? 0) + 0.7152 * (c[1] ?? 0) + 0.0722 * (c[2] ?? 0);
          };
          const line = document.querySelector('.monitor-hatch-line');
          const ground = document.querySelector('.monitor-hatch-ground');
          if (!line || !ground) return 0;
          const [high, low] = [lum(parse(getComputedStyle(line).stroke)), lum(parse(getComputedStyle(ground).fill))].sort((a, b) => b - a);
          return ((high ?? 0) + 0.05) / ((low ?? 0) + 0.05);
        }, theme);
        assert.ok(ratio >= 3, `the hatch in ${theme}: ${ratio.toFixed(2)}:1`);
      }
      await tab.close();
    });

    await t.test('the pane: the Big card of the unit gone into, beside the Small cards', async () => {
      mode = 'cards';
      for (const [width, height] of [[1440, 900], [1920, 1080]] as const) {
        const { tab, violations } = await open('pane-en', width, height);
        await tab.waitForSelector('.monitor-dock [data-poll-state="live"] .monitor-card.is-fit');
        await tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card');
        const pane = await drawn(tab, '.monitor-dock');
        assert.equal(pane.cards, 1);
        assert.deepEqual(await smallTargets(tab), [], 'every control a 44 px target');
        assert.deepEqual(await besideTheCards(tab), [], 'the pane beside the overview, as the design’s');
        assert.deepEqual(await bigCards(tab, '.monitor-dock'), [], 'the pane’s Big card is the design’s, nothing of it cut');
        assert.deepEqual(await lowInThemes(tab), [], 'card text under 4.5:1 in a theme, the pane’s too');
        assert.equal(pane.links, 1, 'the pane\'s card links its tank\'s water');
        assert.equal(await tab.locator('.monitor-dock a.monitor-water-link[id^="pane-water-"]').count(), 1, 'its own id');
        assert.deepEqual(await lowContrast(tab), [], 'card text under 4.5:1');
        assert.deepEqual(await axeFindings(tab, origin), [], 'axe');
        assert.deepEqual(violations, [], 'CSP violations');
        await shot(tab, `pane-en-${width}`);
        await tab.close();
      }
    });

    for (const language of LANGUAGES) {
      for (const name of ['pane-tw08', 'pane-tw09', 'pane-tw12']) {
        await t.test(`${name} ${language}: the pane's Big card of an old, a many-valued and an old acid water`, async () => {
          mode = 'cards';
          const { tab, violations } = await open(`${name}-${language}`, 1440, 900);
          await tab.waitForSelector('.monitor-dock [data-poll-state="live"] .monitor-card.is-fit');
          await tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card');
          assert.deepEqual(await bigCards(tab, '.monitor-dock'), [], 'the pane\u2019s Big card, nothing of it cut');
          assert.deepEqual(await besideTheCards(tab), [], 'beside the cards');
          assert.deepEqual(await smallTargets(tab), [], 'every control a 44 px target');
          assert.deepEqual(await lowContrast(tab), [], 'card text under 4.5:1');
          assert.deepEqual(violations, [], 'CSP violations');
          if (language === 'en') await shot(tab, `${name}-en-1440`);
          await tab.close();
        });
      }
      for (const [width, height] of language === 'en' ? [[1920, 1080], [3840, 2160]] as const : [[1920, 1080]] as const) {
        await t.test(`the wall of Big cards ${language} at ${width}x${height}: its notices a row of their own, every card whole`, async () => {
          mode = 'cards';
          const { tab, violations } = await open(`wall-big-${language}`, width, height);
          await tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card');
          await tab.waitForFunction(() => document.querySelector('.monitor-grid')?.hasAttribute('data-page'));
          const seen = await tab.evaluate(() => {
            const grid = document.querySelector('.monitor-grid') as HTMLElement;
            const notices = Array.from(document.querySelectorAll<HTMLElement>('.content > .alarm-watch > p'));
            // (the wall turns its pages inside the grid: what must hold is that every card on the screen lies whole in the
            // grid's room, under the band, and that the page itself does not scroll)
            const room = grid.getBoundingClientRect();
            const band = (grid.querySelector('.monitor-band') as HTMLElement).getBoundingClientRect();
            const cut = Array.from(grid.querySelectorAll<HTMLElement>(':scope > .monitor-card')).filter((card) => {
              const box = card.getBoundingClientRect();
              return box.height > 0 && box.bottom > band.bottom + 1 && box.top < room.bottom - 1 && (box.top < band.bottom - 1 || box.bottom > room.bottom + 1);
            }).map((card) => card.querySelector('h3')?.textContent?.trim());
            return { scrolls: document.documentElement.scrollHeight > innerHeight + 1, cut,
                     notices: notices.length, above: notices.every((notice) => notice.getBoundingClientRect().bottom <= grid.getBoundingClientRect().top + 0.5),
                     shown: Array.from(grid.querySelectorAll<HTMLElement>(':scope > .monitor-card'))
                       .filter((card) => { const box = card.getBoundingClientRect(); return box.height > 0 && box.bottom > 0 && box.top < innerHeight; }).length };
          });
          assert.ok(seen.notices >= 1, 'the alarms\u2019 notices are on the wall');
          assert.ok(seen.above, 'the notices stand above the grid');
          assert.equal(seen.scrolls, false, 'the wall is one screen');
          assert.deepEqual(seen.cut, [], 'the cards of the page shown are whole in the grid’s room');
          assert.ok(seen.shown >= 1, `${seen.shown} cards on the screen`);
          assert.deepEqual(await bigCards(tab), [], 'every Big card on the screen whole, its foot in sight');
          assert.deepEqual(await covered(tab), [], 'nothing lies over the band, a state word or the buttons of the wall');
          assert.deepEqual(violations, [], 'CSP violations');
          if (language === 'en') await shot(tab, `wall-big-en-${width}`, false);
          await tab.close();
        });
      }
    }

    for (const [width, height] of [[1920, 1080], [3840, 2160]] as const) {
      await t.test(`the wall of Small cards at ${width}x${height}: one screen, nothing scrolls, no text under 11 px`, async () => {
        mode = 'cards';
        const { tab, violations } = await open('wall-en', width, height);
        await tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card');
        await tab.waitForFunction(() => document.querySelector('.monitor-grid')?.hasAttribute('data-page'));
        const seen = await tab.evaluate(() => {
          const cards = Array.from(document.querySelectorAll<HTMLElement>('.monitor-grid > .monitor-card'));
          let smallest = 1000;
          for (const card of cards) {
            for (const element of card.querySelectorAll('*')) {
              const own = Array.from(element.childNodes).some((node) => node.nodeType === 3 && (node.textContent ?? '').trim());
              if (!own || element.closest('svg, .sr-only') || !(element as HTMLElement).offsetParent) continue;
              smallest = Math.min(smallest, parseFloat(getComputedStyle(element).fontSize));
            }
          }
          return { scrolls: document.documentElement.scrollHeight > window.innerHeight + 1
                     || document.documentElement.scrollWidth > window.innerWidth + 1,
                   smallest, links: cards.filter((card) => card.querySelector('a.monitor-water-link')).length, cards: cards.length };
        });
        assert.equal(seen.scrolls, false, 'the wall is one screen');
        assert.ok(seen.smallest >= 11, `the smallest text is ${seen.smallest} px`);
        assert.equal(seen.links, seen.cards);
        assert.deepEqual(await covered(tab), [], 'nothing lies over the band, a state word or the buttons of the wall');
        assert.deepEqual(violations, [], 'CSP violations');
        await shot(tab, `wall-en-${width}`, false);
        await tab.close();
      });
    }

    await t.test('a board read from 2 m on a 55" TV: its cards at the legible unit, the wall turning pages', async () => {
      mode = 'cards';
      const { tab, violations } = await open('wall-board-en', 1920, 1080);
      await tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card');
      await tab.waitForFunction(() => document.querySelector('.monitor-grid')?.hasAttribute('data-page'));
      const seen = await tab.evaluate(() => {
        const grid = document.querySelector('.monitor-grid') as HTMLElement;
        const shown = Array.from(grid.querySelectorAll<HTMLElement>(':scope > .monitor-card'))
          .filter((card) => { const box = card.getBoundingClientRect(); return box.bottom > 1 && box.top < innerHeight - 1; });
        return { pages: Number(grid.dataset.pageCount), screen: [screen.width, screen.height],
                 units: shown.map((card) => Number.parseFloat(getComputedStyle(card.firstElementChild as Element).fontSize)),
                 scrolls: document.documentElement.scrollHeight > innerHeight + 1 };
      });
      const least = legibleUnit(55, 2, seen.screen[0] ?? 0, seen.screen[1] ?? 0);
      assert.ok(seen.pages > 1, `${seen.pages} pages`);
      assert.ok(seen.units.length > 0 && seen.units.every((unit) => unit >= least - 0.5), `units ${seen.units} under ${least}`);
      assert.equal(seen.scrolls, false);
      assert.deepEqual(await covered(tab), [], 'nothing lies over the band, a state word or the buttons of the wall');
      assert.deepEqual(violations, [], 'CSP violations');
      await shot(tab, 'wall-board-en-1920', false);
      await tab.close();
    });

    await t.test('polling in the new look: a worse card is said, a failed poll marks the grid, the next answer says so', async () => {
      mode = 'cards';
      const { tab } = await open('small-en', 1440, 900);
      const grid = tab.locator('.monitor-grid');
      await tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card');
      const assertive = tab.locator('#monitor-announce [aria-live="assertive"]');
      assert.equal(await assertive.textContent(), '', 'the first load says nothing');
      const now = (): Promise<void> => grid.evaluate((element) => { element.dispatchEvent(new CustomEvent('poll:now')); });
      mode = 'worse';
      await now();
      await tab.waitForFunction(() => document.querySelector('#monitor-announce [aria-live="assertive"]')?.textContent !== '');
      assert.equal(await assertive.textContent(), 'TW-01 is now Critical.');
      assert.equal(await tab.locator('.monitor-grid > .monitor-card.monitor-critical a.monitor-water-link').count() >= 2, true,
        'the worse card is merged in, with its link');
      mode = 'fail';
      await now();
      await tab.waitForTimeout(300);
      await now();
      await tab.waitForSelector('.monitor-grid[data-poll-state="stale"]');
      const notice = await grid.evaluate((element) => getComputedStyle(element, '::before').content);
      assert.match(notice, /Not updated/);
      assert.equal(await tab.locator('.monitor-grid > .monitor-card').count() >= 7, true, 'the last picture stays');
      mode = 'cards';
      await now();
      await tab.waitForSelector('.monitor-grid[data-poll-state="live"]');
      await tab.waitForFunction(() => /Updated again/.test(document.querySelector('#monitor-announce')?.textContent ?? ''));
      await tab.close();
    });

    await t.test('a first answer that fails says the cards cannot be read, and they come when the server answers', async () => {
      mode = 'fail';
      const { tab } = await open('small-en', 1440, 900);
      await tab.waitForSelector('.monitor-grid[data-poll-state="unread"]');
      assert.equal(await tab.locator('.monitor-grid .monitor-card').count(), 0, 'no card, no state: never "all is well"');
      assert.equal(await tab.locator('.monitor-grid [data-unread]').isVisible(), true);
      await tab.waitForFunction(() => /cannot be read/.test(document.querySelector('#monitor-announce [aria-live="polite"]')?.textContent ?? ''));
      await shot(tab, 'unread-en-1440', false);
      mode = 'cards';
      await tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card', { timeout: 20000 });
      await tab.close();
    });
  } finally {
    await browser.close();
    server.close();
  }
});
