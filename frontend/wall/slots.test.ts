// The slot rule of the monitoring wall (frontend/wall/slots.ts) against the vectors it shares with the Python rule
// (monitoring/cards/slots.py; monitoring/tests/test_slots.py runs the same file), the screens the design names, and the
// rule's own properties on random screens.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { FLOOR, dock, fillUnit, legibleUnit, pageOf, slots, worst, worstPage } from './slots.js';
import { mulberry32 } from '../test/random.js';

interface Case {
  name: string; count: number; width: number; height: number; gap: number; mw: number; mh: number; min_u: number;
  pad_x: number; pad_y: number; cols: number; rows: number; pages: number; u: number;
}
const VECTORS = JSON.parse(readFileSync('monitoring/tests/slot_vectors.json', 'utf8')) as { floor: number; cases: Case[] };
const named = (name: string): Case => {
  const found = VECTORS.cases.find((each) => each.name === name);
  assert.ok(found, name);
  return found;
};

test('the vectors shared with the Python rule', () => {
  assert.equal(VECTORS.floor, FLOOR);
  assert.ok(VECTORS.cases.length >= 50);
  for (const each of VECTORS.cases) {
    const found = slots(each.count, each.width, each.height, each.gap, each.mw, each.mh, each.min_u, each.pad_x, each.pad_y);
    assert.deepEqual([found.cols, found.rows, found.pages], [each.cols, each.rows, each.pages], each.name);
    assert.ok(Math.abs(found.u - each.u) < 1e-5, `${each.name}: unit ${found.u} against ${each.u}`);
  }
});

test('the screens the design names: three big cards on 3440x1440, four on 5120x1440, two on 16:9', () => {
  const big = (screen: string): number => named(`big x 20 on ${screen}`).cols * named(`big x 20 on ${screen}`).rows;
  assert.deepEqual(['3440x1440', '5120x1440', '2560x1440', '3840x2160', '1920x1080'].map(big), [3, 4, 2, 2, 2]);
  // twenty small cards are one page on every screen from 1920x1080 up, and never under the floor
  for (const screen of ['3440x1440', '5120x1440', '2560x1440', '3840x2160', '1920x1080']) {
    const small = named(`small x 20 on ${screen}`);
    assert.equal(small.pages, 1, screen);
    assert.ok(small.u >= FLOOR, screen);
  }
  // a low screen turns pages rather than shrink the type
  assert.ok(named('small x 20 on 1280x720').pages > 1);
  assert.ok(named('small x 20 on 1280x720').u >= FLOOR);
});

test('whatever the screen: every card has a cell, the unit is never under the floor when a page is turned', () => {
  const random = mulberry32(20261113);
  for (let round = 0; round < 400; round += 1) {
    const count = 1 + Math.floor(random() * 220);
    const width = 600 + random() * 5000;
    const height = 300 + random() * 2200;
    const gap = random() * 14;
    const [mw, mh] = random() < 0.5 ? [31, 12] : [12 + Math.floor(random() * 52), 6 + Math.floor(random() * 58)];
    const padX = random() * 40;
    const padY = random() * 20;
    const found = slots(count, width, height, gap, mw, mh, FLOOR, padX, padY);
    const where = JSON.stringify({ count, width, height, gap, mw, mh, padX, padY, found });
    assert.ok(found.cols >= 1 && found.rows >= 1 && found.pages >= 1, where);
    assert.ok(found.cols * found.rows * found.pages >= count, where);                   // no card without a cell
    assert.ok((found.pages - 1) * found.cols * found.rows < count, where);              // no page without a card
    // paged, never shrunk: under the floor only one card a page, at the largest unit a cell gives (a window too small)
    if (found.pages > 1 && found.u < FLOOR - 1e-6) assert.deepEqual([found.cols, found.rows, found.pages], [1, 1, count], where);
    // one page when one page can be read: no grid that holds every card gives a readable unit otherwise
    if (found.pages > 1) {
      for (let cols = 1; cols <= 16; cols += 1) {
        for (let rows = Math.ceil(count / cols); rows <= 12; rows += 1) {
          const room = (height - (rows - 1) * gap) / rows;
          const u = Math.min(((width - (cols - 1) * gap) / cols - padX) / mw, (room - padY) / mh);
          assert.ok(u < FLOOR, `${where}: ${cols}x${rows} would hold every card at ${u}`);
        }
      }
    }
  }
});

test('a legible unit no grid reaches: one card a page at the largest unit a cell gives, never the densest grid', () => {
  // the review's pairs on a Full HD screen (B3): 24" from 3 m and 5 m, 55" from 5 m ask for more than any cell gives
  const room = named('small x 20 on 1920x1080');
  const largest = Math.min((room.width - room.pad_x) / room.mw, (room.height - room.pad_y) / room.mh);
  for (const [inches, distance] of [[24, 3], [24, 5], [55, 5]] as const) {
    const least = legibleUnit(inches, distance, 1920, 1080);
    assert.ok(least > largest, `${inches}" at ${distance} m asks ${least}, a cell gives ${largest} at most`);
    const found = slots(20, room.width, room.height, room.gap, room.mw, room.mh, least, room.pad_x, room.pad_y);
    assert.deepEqual([found.cols, found.rows, found.pages], [1, 1, 20], `${inches}" at ${distance} m`);
    assert.ok(Math.abs(found.u - largest) < 1e-9, `${inches}" at ${distance} m: ${found.u}`);
  }
  // whatever the screen and the unit asked: a page that cannot be read is never more than one card at the largest unit
  const random = mulberry32(20261124);
  for (let round = 0; round < 300; round += 1) {
    const count = 1 + Math.floor(random() * 60);
    const [width, height, gap] = [600 + random() * 4000, 300 + random() * 2000, random() * 14];
    const [mw, mh, padX, padY] = [12 + Math.floor(random() * 52), 6 + Math.floor(random() * 58), random() * 40, random() * 20];
    const least = FLOOR + random() * 200;
    const found = slots(count, width, height, gap, mw, mh, least, padX, padY);
    const where = JSON.stringify({ count, width, height, gap, mw, mh, padX, padY, least, found });
    if (found.u < least - 1e-6) {
      const cell = Math.max(height, mh * FLOOR + padY);
      assert.deepEqual([found.cols, found.rows, found.pages], [1, 1, count], where);
      assert.ok(Math.abs(found.u - Math.min((width - padX) / mw, (cell - padY) / mh)) < 1e-9, where);
    }
  }
});

test('a page holds the same cards whatever happens: the page of a card, and the page a wall opens on', () => {
  assert.deepEqual([0, 19, 20, 39, 40].map((index) => pageOf(index, 20)), [1, 1, 2, 2, 3]);
  const order = ['critical', 'warning', 'blind'];
  const states = ['ok', 'ok', 'warning', 'ok', 'ok', 'critical', 'ok'];
  assert.equal(worstPage(states, 2, order), 3);                // the critical card, not the warning before it
  assert.equal(worstPage(['ok', 'note', 'blind'], 2, order), 2);
  assert.equal(worstPage(['ok', 'note', 'empty'], 2, order), 1);
  assert.equal(worstPage([], 5, order), 1);
});

test('the pane beside the cards is one cell of the wall of full-height cards, or lies over them', () => {
  for (const screen of ['3440x1440', '5120x1440', '2560x1440', '3840x2160', '1920x1080']) {
    const big = named(`big x 20 on ${screen}`);
    const found = dock(big.width, big.height, big.gap, big.mw, big.mh, big.pad_x, big.pad_y);
    // as wide as a card of the all-big wall of this screen (never more than half of it), at that card's unit
    const cell = (big.width - (big.cols - 1) * big.gap) / big.cols;
    assert.ok(Math.abs(found.width - Math.min(cell, big.width / 2)) < 1e-6, screen);
    assert.equal(found.beside, true, screen);
    // and the small cards still have a readable unit in the room that is left
    const small = named(`small x 20 on ${screen}`);
    const left = slots(20, small.width - found.width - small.gap, small.height, small.gap, small.mw, small.mh, FLOOR,
                       small.pad_x, small.pad_y);
    assert.ok(left.u >= FLOOR - 1e-6, `${screen}: ${left.u}`);
  }
  // a window too low for a readable full-height card: the pane lies over the cards, it is never dropped
  const low = named('small x 20 on 1280x720');
  assert.equal(dock(low.width, low.height, low.gap, 48, 61, low.pad_x, low.pad_y).beside, false);
  assert.ok(fillUnit(low.width, low.height, 48, 61) < FLOOR);
});

test('the worst card, its page and its state', () => {
  const order = ['critical', 'warning', 'blind'];
  assert.deepEqual(worst(['ok', 'ok', 'warning', 'ok', 'ok', 'critical', 'ok'], 2, order), { index: 5, page: 3, state: 'critical' });
  assert.deepEqual(worst(['ok', 'blind', 'warning'], 2, order), { index: 2, page: 2, state: 'warning' });
  assert.equal(worst(['ok', 'note'], 2, order), null);
});

test('the legible unit: the vectors shared with the Python rule', () => {
  const cases = (JSON.parse(readFileSync('monitoring/tests/slot_vectors.json', 'utf8')) as {
    legible: { inches: number; distance_m: number; screen_w: number; screen_h: number; u: number }[] }).legible;
  assert.ok(cases.length >= 10);
  for (const each of cases) {
    const found = legibleUnit(each.inches, each.distance_m, each.screen_w, each.screen_h);
    assert.ok(Math.abs(found - each.u) < 1e-5, `${JSON.stringify(each)}: ${found}`);
  }
  // the same TV at a pixel ratio of 2 gets half the CSS px: the same millimetres
  assert.ok(Math.abs(legibleUnit(55, 3, 3840, 2160) - 2 * legibleUnit(55, 3, 1920, 1080)) < 1e-9);
  assert.equal(legibleUnit(0, 3, 1920, 1080), FLOOR);
});

test('the pane stands beside the cards only where its card can be read at the wall\'s distance', () => {
  // 55" Full HD TV at 3 m: a Big card's unit there is far over 14 px but under the legible one: over the cards
  const floor = legibleUnit(55, 3, 1920, 1080);
  assert.equal(dock(1920, 1000, 8, 48, 61, 0, 0).beside, true);
  assert.equal(dock(1920, 1000, 8, 48, 61, 0, 0, floor).beside, false);
});
