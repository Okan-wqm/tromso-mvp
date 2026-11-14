// The slot rule of the monitoring wall (frontend/wall/slots.ts) against the vectors it shares with the Python rule
// (monitoring/cards/slots.py; monitoring/tests/test_slots.py runs the same file), the screens the design names, and the
// rule's own properties on random screens.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { FLOOR, pageOf, roomy, slots, worstPage } from './slots.js';
import { mulberry32 } from '../test/random.js';

interface Case {
  name: string; count: number; width: number; height: number; gap: number; mw: number; mh: number; min_u: number;
  pad_x: number; pad_y: number; cols: number; rows: number; pages: number; u: number; roomy: boolean;
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
    assert.equal(roomy(found, each.width, each.height, each.gap, each.mw, each.mh, each.pad_x, each.pad_y), each.roomy, each.name);
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
    const [mw, mh] = random() < 0.5 ? [31, 10] : [12 + Math.floor(random() * 52), 6 + Math.floor(random() * 58)];
    const padX = random() * 40;
    const padY = random() * 20;
    const found = slots(count, width, height, gap, mw, mh, FLOOR, padX, padY);
    const where = JSON.stringify({ count, width, height, gap, mw, mh, padX, padY, found });
    assert.ok(found.cols >= 1 && found.rows >= 1 && found.pages >= 1, where);
    assert.ok(found.cols * found.rows * found.pages >= count, where);                   // no card without a cell
    assert.ok((found.pages - 1) * found.cols * found.rows < count, where);              // no page without a card
    if (found.pages > 1) assert.ok(found.u >= FLOOR - 1e-6, where);                     // paged, never shrunk
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

test('a page holds the same cards whatever happens: the page of a card, and the page a wall opens on', () => {
  assert.deepEqual([0, 19, 20, 39, 40].map((index) => pageOf(index, 20)), [1, 1, 2, 2, 3]);
  const order = ['critical', 'warning', 'blind'];
  const states = ['ok', 'ok', 'warning', 'ok', 'ok', 'critical', 'ok'];
  assert.equal(worstPage(states, 2, order), 3);                // the critical card, not the warning before it
  assert.equal(worstPage(['ok', 'note', 'blind'], 2, order), 2);
  assert.equal(worstPage(['ok', 'note', 'empty'], 2, order), 1);
  assert.equal(worstPage([], 5, order), 1);
});
