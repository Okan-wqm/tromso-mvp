// Operations › Monitoring in the new look in a real browser (Playwright on the machine's own Chrome or Edge, as the other
// page tests), on the pages the real views printed in the test run's database from THE test world (core/test_world.py
// `world` and `monitoring_world`: a unit in every state a card can be in), kept in .build/monitor-pages by
// monitoring/tests/test_next_pages.py (never a recording of a real database: the repository is public). Each page is the
// SHELL the server prints (no card, "Loading the cards…"), served under the product's Content-Security-Policy with the
// nonce it was printed with, with every sheet and script it names; its polls (frontend/poll.ts: the start-up gate, the
// merge by key) are answered with the fragments the same views printed, and the strip with its own. Run by
// `npm run test:pages` after the Django tests (CI's Django job); missing pages fail it, never skip it. It holds:
//   - every screen (Small, Simple, Detailed, Big) at 1440 and 390 px, in English, Norwegian and Turkish: the cards come
//     with the first poll; every card has its link to Tank › Water; every state's glyph is drawn (a mask of the icon
//     set) and its word is there; no CSP violation, no critical or serious axe finding, every card text at 4.5:1 on
//     what it stands on, nothing scrolls sideways;
//   - the pane: the Big card of the unit gone into, filled by its own poll, with its own link to the water;
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
 *  that are not one size. [] when none is. */
function uncut(tab: Page): Promise<string[]> {
  return tab.evaluate(() => {
    const wrong: string[] = [];
    const cards = Array.from(document.querySelectorAll<HTMLElement>('.monitor-grid > .monitor-card'));
    const sizes = new Map<string, Set<string>>();
    for (const card of cards) {
      const kind = card.className.includes('is-fit') ? 'fit' : 'flow';
      const box = card.getBoundingClientRect();
      if (!sizes.has(kind)) sizes.set(kind, new Set());
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
      for (const screen of ['small', 'simple', 'detailed', 'big']) {
        if (language !== 'en' && screen !== 'small') continue;            // every language on the Small cards
        for (const width of [1440, 1920, 390]) {
          await t.test(`${screen} ${language} at ${width} px: the cards, their links and glyphs, CSP, axe, 4.5:1`, async () => {
            mode = 'cards';
            const key = `${screen}-${language}`;
            const { tab, violations } = await open(key, width, 900);
            await tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card');
            const seen = await drawn(tab);
            assert.ok(seen.cards >= 7, `${seen.cards} cards`);
            assert.equal(seen.links, seen.cards, 'every card links its tank\'s water');
            assert.ok(seen.states.every(Boolean), 'every card says its state');
            if (width >= 1100) {
              // the rail keeps its width beside the top bar, whatever the strip says (its alarms sentence is long here)
              const rail = await tab.evaluate(() => [document.querySelector('.rail')?.getBoundingClientRect().width ?? 0,
                Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--rail-w'))]);
              assert.ok(Math.abs((rail[0] ?? 0) - (rail[1] ?? 0)) < 0.5, `the rail is ${rail[0]} px, not ${rail[1]}`);
            }
            assert.deepEqual(await uncut(tab), [], 'a code, a state word, a figure, the saturation, "old", the figure and bound of a reason are never cut; the cards are one size');
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

    await t.test('the pane: the Big card of the unit gone into, beside the Small cards', async () => {
      mode = 'cards';
      for (const [width, height] of [[1440, 900], [1920, 1080]] as const) {
        const { tab, violations } = await open('pane-en', width, height);
        await tab.waitForSelector('.monitor-dock [data-poll-state="live"] .monitor-card.is-fit');
        await tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card');
        const pane = await drawn(tab, '.monitor-dock');
        assert.equal(pane.cards, 1);
        assert.equal(pane.links, 1, 'the pane\'s card links its tank\'s water');
        assert.equal(await tab.locator('.monitor-dock a.monitor-water-link[id^="pane-water-"]').count(), 1, 'its own id');
        assert.deepEqual(await lowContrast(tab), [], 'card text under 4.5:1');
        assert.deepEqual(await axeFindings(tab, origin), [], 'axe');
        assert.deepEqual(violations, [], 'CSP violations');
        await shot(tab, `pane-en-${width}`);
        await tab.close();
      }
    });

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
