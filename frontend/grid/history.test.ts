// Undo and redo (frontend/grid/history.ts): a gesture is one entry, at most CAP entries back, a new entry clears redo.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CAP, canRedo, canUndo, commit, redo, start, undo } from './history.js';
import { move } from './layout.js';
import { catalogueOf } from './layout.js';
import type { Catalogue, Layout } from './types.js';
import { deepFreeze, int, property } from '../test/random.js';

const CAT = catalogueOf({ columns: 12, widgets: [{ type: 'tasks', min_w: 3, min_h: 2, max_w: 12, max_h: 3,
                                                   default_w: 3, default_h: 2, enabled: true }] }) as Catalogue;
const ONE: Layout = deepFreeze([{ id: 'w1', type: 'tasks', x: 0, y: 0, w: 3, h: 2 }]);
const TWO: Layout = deepFreeze([{ id: 'w1', type: 'tasks', x: 3, y: 0, w: 3, h: 2 }]);

test('a new history has nothing to undo or redo', () => {
  const history = start(ONE);
  assert.equal(history.present, ONE);
  assert.equal(canUndo(history), false);
  assert.equal(canRedo(history), false);
  assert.equal(undo(history), history);
  assert.equal(redo(history), history);
});

test('commit, undo, redo', () => {
  const history = commit(start(ONE), TWO);
  assert.equal(history.present, TWO);
  const back = undo(history);
  assert.equal(back.present, ONE);
  assert.equal(canRedo(back), true);
  assert.equal(redo(back).present, TWO);
});

test('a layout equal to the present is not an entry', () => {
  const history = start(ONE);
  assert.equal(commit(history, deepFreeze([{ ...ONE[0] }])), history);
});

test('a gesture is one entry: the drag previews are not committed, its end is', () => {
  let shown: Layout = ONE;
  for (let x = 1; x <= 6; x += 1) {
    shown = move(shown, 'w1', x, 0, CAT);                                     // what the canvas draws while dragging
  }
  const history = commit(start(ONE), shown);
  assert.equal(history.past.length, 1);
  assert.equal(undo(history).present, ONE);
});

test('a new entry clears what could be redone', () => {
  const history = commit(undo(commit(start(ONE), TWO)), deepFreeze([{ ...ONE[0], x: 6 }]));
  assert.equal(canRedo(history), false);
});

test('at most CAP entries are kept, the oldest go first', () => {
  let history = start(ONE);
  for (let step = 1; step <= CAP + 20; step += 1) {
    history = commit(history, deepFreeze([{ ...ONE[0], y: step }]));
  }
  assert.equal(CAP, 100);
  assert.equal(history.past.length, CAP);
  assert.equal(history.past[0][0].y, 20);
});

test('property: undo after any run of commits gives back each layout exactly, and the inputs are never changed', () => {
  property('undo exact', 2000, (random) => {
    const layouts: Layout[] = [ONE];
    let history = start(ONE);
    for (let step = 0; step < int(random, 1, 12); step += 1) {
      const next = deepFreeze([{ ...ONE[0], x: int(random, 0, 9), y: int(random, 0, 50) }]);
      const before = history;
      history = commit(deepFreeze(history), next);
      if (history !== before) {
        layouts.push(next);
      }
    }
    for (let index = layouts.length - 1; index > 0; index -= 1) {
      assert.equal(history.present, layouts[index]);
      history = undo(history);
    }
    assert.equal(history.present, ONE);
  });
});
