// The designer's keyboard (frontend/grid/keyboard.ts): what a key does to the selected widget, as a pure function, so
// every key a person can press on the canvas is checked without a browser.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { applyKey } from './keyboard.js';
import { catalogueOf } from './layout.js';
import type { Catalogue, Layout } from './types.js';
import { deepFreeze } from '../test/random.js';

const CAT = catalogueOf({ columns: 12, widgets: [{ type: 'tasks', min_w: 3, min_h: 2, max_w: 12, max_h: 3,
                                                   default_w: 3, default_h: 2, enabled: true }] }) as Catalogue;
const ITEMS: Layout = deepFreeze([
  { id: 'a', type: 'tasks', x: 0, y: 0, w: 3, h: 2 },
  { id: 'b', type: 'tasks', x: 3, y: 0, w: 3, h: 2 },
  { id: 'c', type: 'tasks', x: 0, y: 2, w: 3, h: 2 },
]);

test('an arrow moves the selected widget one cell, pushing what it lands on', () => {
  const done = applyKey(ITEMS, 'a', 'ArrowRight', false, CAT);
  assert.ok(done);
  assert.deepEqual(done.items.find((item) => item.id === 'a'), { id: 'a', type: 'tasks', x: 1, y: 0, w: 3, h: 2 });
  assert.equal(done.selected, 'a');
});

test('shift and an arrow grow or shrink it within its sizes', () => {
  const grown = applyKey(ITEMS, 'a', 'ArrowDown', true, CAT);
  assert.equal(grown?.items.find((item) => item.id === 'a')?.h, 3);
  const shrunk = applyKey(ITEMS, 'a', 'ArrowLeft', true, CAT);
  assert.equal(shrunk?.items.find((item) => item.id === 'a')?.w, 3);        // already its narrowest
});

test('Delete removes it and selects the next in reading order, or the one before at the end', () => {
  assert.deepEqual(applyKey(ITEMS, 'a', 'Delete', false, CAT)?.selected, 'b');
  const last = applyKey(ITEMS, 'c', 'Delete', false, CAT);
  assert.deepEqual([last?.items.map((item) => item.id), last?.selected], [['a', 'b'], 'b']);
  assert.equal(applyKey([ITEMS[0]], 'a', 'Delete', false, CAT)?.selected, '');
});

test('no selection or another key does nothing', () => {
  assert.equal(applyKey(ITEMS, '', 'ArrowRight', false, CAT), null);
  assert.equal(applyKey(ITEMS, 'a', 'x', false, CAT), null);
  assert.equal(applyKey(ITEMS, 'nobody', 'ArrowRight', false, CAT), null);
});
