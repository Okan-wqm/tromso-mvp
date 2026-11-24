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
//   - the wall of Small cards at 1920x1080 and 3840x2160: one screen, nothing scrolls, no card text under 11 px;
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

/** The text of the cards, the band and the pane under 4.5:1 on the ground it stands on (the nearest opaque background). */
function lowContrast(tab: Page): Promise<string[]> {
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
    for (const element of document.querySelectorAll('.monitor-grid *, .monitor-dock *')) {
      const own = Array.from(element.childNodes).some((node) => node.nodeType === 3 && (node.textContent ?? '').trim());
      const box = element.getBoundingClientRect();
      if (!own || box.width < 2 || element.closest('svg, .sr-only, [aria-hidden="true"]')) continue;
      const fore = parse(getComputedStyle(element).color).slice(0, 3);
      const [high, lower] = [lum(fore), lum(ground(element))].sort((a, b) => b - a);
      const ratio = ((high ?? 0) + 0.05) / ((lower ?? 0) + 0.05);
      if (ratio < 4.5) low.push(`${element.className || element.tagName} "${(element.textContent ?? '').trim().slice(0, 30)}" ${ratio.toFixed(2)}`);
    }
    return low;
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
    const tab = await browser.newPage({ viewport: { width, height } });
    const violations = await watchCsp(tab);
    await tab.goto(`${origin}/page/${key}`);
    return { tab, violations };
  };
  try {
    for (const language of LANGUAGES) {
      for (const screen of ['small', 'simple', 'detailed', 'big']) {
        if (language !== 'en' && screen !== 'small') continue;            // every language on the Small cards
        for (const width of [1440, 390]) {
          await t.test(`${screen} ${language} at ${width} px: the cards, their links and glyphs, CSP, axe, 4.5:1`, async () => {
            mode = 'cards';
            const key = `${screen}-${language}`;
            const { tab, violations } = await open(key, width, 900);
            await tab.waitForSelector('.monitor-grid[data-poll-state="live"] > .monitor-card');
            const seen = await drawn(tab);
            assert.ok(seen.cards >= 7, `${seen.cards} cards`);
            assert.equal(seen.links, seen.cards, 'every card links its tank\'s water');
            assert.ok(seen.states.every(Boolean), 'every card says its state');
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
