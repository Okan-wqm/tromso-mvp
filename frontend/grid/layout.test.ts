// The grid library's layout functions (frontend/grid/layout.ts): examples first, then seeded properties over thousands
// of random layouts and gestures, then the geometry vectors shared with the server's validator.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  add, catalogueOf, cellFromPoint, changes, check, clamp, collides, compact, keyToDelta, move, nextId, parse,
  readingOrder, remove, resize, serialize,
} from './layout.js';
import type { Catalogue, Item, Layout } from './types.js';
import { deepFreeze, int, pick, property, type Random } from '../test/random.js';

const VECTORS = JSON.parse(readFileSync('monitoring/tests/layout_vectors.json', 'utf8')) as {
  columns: number;
  sizes: Record<string, [number, number, number, number]>;
  cases: { name: string; widgets: Item[]; problems: string[][] }[];
};

// The catalogue as the designer receives it (monitoring.cards.catalogue.as_data), built from the vectors' sizes.
const CAT = catalogueOf({
  columns: VECTORS.columns,
  widgets: Object.entries(VECTORS.sizes).map(([type, [minW, minH, maxW, maxH]]) => ({
    type, min_w: minW, min_h: minH, max_w: maxW, max_h: maxH, default_w: minW, default_h: minH, enabled: true,
  })),
}) as Catalogue;

function item(id: string, x: number, y: number, w = 3, h = 2, type = 'tasks'): Item {
  return { id, type, x, y, w, h };
}

function noOverlap(items: Layout): boolean {
  return items.every((a, index) => items.slice(index + 1).every((b) => !collides(a, b)));
}

function valid(items: Layout, cat: Catalogue = CAT): boolean {
  return check(items, cat).length === 0;
}

// ---- examples ------------------------------------------------------------------------------------------------------
test('the catalogue is read from the server data and refuses garbage', () => {
  assert.equal(CAT.columns, 12);
  assert.deepEqual(CAT.specs.value, { min_w: 2, min_h: 2, max_w: 6, max_h: 4, default_w: 2, default_h: 2,
                                       enabled: true });
  for (const garbage of [null, 7, 'x', {}, { columns: 12 }, { columns: '12', widgets: [] },
                         { columns: 12, widgets: [{ type: 'value' }] }]) {
    assert.equal(catalogueOf(garbage), null);
  }
});

test('collides: a shared cell, not a shared edge or corner', () => {
  assert.equal(collides(item('a', 0, 0), item('b', 2, 1)), true);
  assert.equal(collides(item('a', 0, 0), item('b', 3, 0)), false);
  assert.equal(collides(item('a', 0, 0), item('b', 0, 2)), false);
  assert.equal(collides(item('a', 0, 0), item('b', 3, 2)), false);
  assert.equal(collides(item('a', 0, 0, 6, 3), item('b', 1, 1)), true);
});

test('clamp keeps an item inside the grid and its sizes', () => {
  assert.deepEqual(clamp(item('a', 11, -2, 3, 2), CAT), item('a', 9, 0, 3, 2));
  assert.deepEqual(clamp(item('a', 0, 0, 1, 9), CAT), item('a', 0, 0, 3, 3));
  assert.deepEqual(clamp(item('a', 0, 0, 40, 2), CAT), item('a', 0, 0, 12, 2));
  assert.deepEqual(clamp(item('a', 2.6, 1.4, 3.2, 2), CAT), item('a', 3, 1, 3, 2));
  assert.deepEqual(clamp(item('a', Number.NaN, Number.POSITIVE_INFINITY, 3, 2), CAT), item('a', 0, 0, 3, 2));
});

test('compact floats each item up as far as it goes, in reading order, stable on ties', () => {
  const items = deepFreeze([item('b', 3, 5), item('a', 0, 4), item('c', 0, 9)]);
  assert.deepEqual(compact(items), [item('b', 3, 0), item('a', 0, 0), item('c', 0, 2)]);
  const tie = deepFreeze([item('x', 0, 3), item('y', 0, 3)]);                // the same cell: the first stays first
  assert.deepEqual(compact(tie), [item('x', 0, 0), item('y', 0, 2)]);
  assert.deepEqual(compact([]), []);
});

test('move places the item, pushes what it lands on down, and compacts', () => {
  const items = deepFreeze([item('a', 0, 0), item('b', 0, 2), item('c', 3, 0)]);
  assert.deepEqual(move(items, 'c', 0, 0, CAT), [item('a', 0, 2), item('b', 0, 4), item('c', 0, 0)]);
  assert.deepEqual(move(items, 'a', 20, 0, CAT), [item('a', 9, 0), item('b', 0, 0), item('c', 3, 0)]);
  assert.equal(move(items, 'nobody', 0, 0, CAT), items);
});

test('resize keeps the sizes of the catalogue and pushes neighbours down', () => {
  const items = deepFreeze([item('a', 0, 0), item('b', 0, 2)]);
  assert.deepEqual(resize(items, 'a', 3, 3, CAT), [item('a', 0, 0, 3, 3), item('b', 0, 3)]);
  assert.deepEqual(resize(items, 'a', 1, 1, CAT), [item('a', 0, 0, 3, 2), item('b', 0, 2)]);
  assert.equal(resize(items, 'nobody', 3, 3, CAT), items);
});

test('add puts a new widget of its default size at the bottom, or where it was dropped; remove closes the gap', () => {
  const items = deepFreeze([item('w1', 0, 0), item('w2', 3, 0, 3, 3)]);
  const added = add(items, 'value', CAT);
  assert.deepEqual(added, { items: [...items, { id: 'w3', type: 'value', x: 0, y: 3, w: 2, h: 2 }], id: 'w3' });
  const dropped = add(items, 'value', CAT, { x: 0, y: 0 });
  assert.deepEqual(dropped.items[2], { id: 'w3', type: 'value', x: 0, y: 0, w: 2, h: 2 });
  assert.ok(noOverlap(dropped.items));
  assert.equal(add(items, 'gauge', CAT).items, items);                          // an unknown type adds nothing
  assert.deepEqual(remove(deepFreeze([item('a', 0, 0), item('b', 0, 2)]), 'a'), [item('b', 0, 0)]);
});

test('nextId continues the highest wN', () => {
  assert.equal(nextId([]), 'w1');
  assert.equal(nextId([item('w2', 0, 0), item('w10', 3, 0), item('other', 6, 0)]), 'w11');
});

test('reading order is (y, x), the order the server writes the widgets in', () => {
  const items = [item('c', 0, 4), item('b', 6, 0), item('a', 0, 0)];
  assert.deepEqual(readingOrder(items).map((each) => each.id), ['a', 'b', 'c']);
});

test('changes say what moved, grew, came and went, by keys the page translates', () => {
  const before = [item('a', 0, 0), item('b', 3, 0), item('c', 6, 0)];
  const after = [item('a', 0, 2), item('b', 3, 0, 4, 2), item('d', 9, 0)];
  assert.deepEqual(changes(before, after), [
    { kind: 'moved', id: 'a', x: 0, y: 2, w: 3, h: 2 },
    { kind: 'resized', id: 'b', x: 3, y: 0, w: 4, h: 2 },
    { kind: 'removed', id: 'c', x: 6, y: 0, w: 3, h: 2 },
    { kind: 'added', id: 'd', x: 9, y: 0, w: 3, h: 2 },
  ]);
  assert.deepEqual(changes(before, before), []);
});

test('a pointer is a cell; the arrow keys are a move, with Shift a resize', () => {
  const box = { left: 100, top: 50, width: 600 };                              // 12 columns of 50 px, rows of 28 px
  assert.deepEqual(cellFromPoint(100, 50, box, 12, 28), { x: 0, y: 0 });
  assert.deepEqual(cellFromPoint(649, 50 + 28 * 3 + 5, box, 12, 28), { x: 10, y: 3 });
  assert.deepEqual(cellFromPoint(5000, -40, box, 12, 28), { x: 11, y: 0 });
  assert.deepEqual(keyToDelta('ArrowLeft', false), { kind: 'move', dx: -1, dy: 0 });
  assert.deepEqual(keyToDelta('ArrowDown', false), { kind: 'move', dx: 0, dy: 1 });
  assert.deepEqual(keyToDelta('ArrowRight', true), { kind: 'resize', dw: 1, dh: 0 });
  assert.deepEqual(keyToDelta('ArrowUp', true), { kind: 'resize', dw: 0, dh: -1 });
  assert.equal(keyToDelta('a', false), null);
});

test('parse reads a stored layout and serialize writes it back the same', () => {
  const stored = { schema: 1, widgets: [
    { id: 'w1', type: 'value', x: 0, y: 0, w: 3, h: 2, bind: { parameter: 'oxygen_mg_l' }, opts: { size: 'large' } },
    { id: 'w2', type: 'fish', x: 0, y: 2, w: 12, h: 5 },
  ] };
  const parsed = parse(deepFreeze(stored), CAT);
  assert.equal(parsed.ok, true);
  if (parsed.ok) {
    assert.deepEqual(serialize(parsed.items), stored);
  }
});

test('garbage is a typed error, never a throw', () => {
  const cases: [unknown, string][] = [
    [null, 'shape'], [[], 'shape'], ['x', 'shape'], [{ schema: 1 }, 'shape'], [{ schema: 1, widgets: {} }, 'shape'],
    [{ schema: 2, widgets: [] }, 'schema'], [{ schema: '1', widgets: [] }, 'schema'],
    [{ schema: 1, widgets: [7] }, 'shape'],
    [{ schema: 1, widgets: [{ id: 'w1', type: 'tasks', x: 0, y: 0, w: 3 }] }, 'keys'],
    [{ schema: 1, widgets: [{ id: 'W 1', type: 'tasks', x: 0, y: 0, w: 3, h: 2 }] }, 'id'],
    [{ schema: 1, widgets: [item('w1', 0, 0), item('w1', 3, 0)] }, 'duplicate'],
    [{ schema: 1, widgets: [{ ...item('w1', 0, 0), type: 'gauge' }] }, 'type'],
    [{ schema: 1, widgets: [{ ...item('w1', 0, 0), x: '0' }] }, 'number'],
    [{ schema: 1, widgets: [{ ...item('w1', 0, 0), y: 0.5 }] }, 'number'],
  ];
  for (const [input, error] of cases) {
    const parsed = parse(input, CAT);
    assert.equal(parsed.ok, false, JSON.stringify(input));
    if (!parsed.ok) {
      assert.equal(parsed.error, error, JSON.stringify(input));
    }
  }
});

// ---- the shared vectors ----------------------------------------------------------------------------------------------
test('the geometry vectors say what the server validator says', () => {
  assert.ok(VECTORS.cases.length >= 12);
  for (const vector of VECTORS.cases) {
    const found = check(vector.widgets, CAT).map((problem) =>
      problem.code === 'overlap' ? [problem.code, problem.widget, problem.other] : [problem.code, problem.widget]);
    assert.deepEqual(found, vector.problems, vector.name);
  }
});

// ---- properties --------------------------------------------------------------------------------------------------
const TYPES = Object.keys(VECTORS.sizes).filter((type) => type !== 'spark');

function randomLayout(random: Random): Layout {
  let items: Layout = [];
  const count = int(random, 0, 14);
  for (let index = 0; index < count; index += 1) {
    const at = random() < 0.5 ? { x: int(random, -3, 14), y: int(random, -2, 30) } : undefined;
    items = add(items, pick(random, TYPES), CAT, at).items;
  }
  return items;
}

type Gesture = (items: Layout) => Layout;

function randomGesture(random: Random, items: Layout): Gesture {
  const target = items.length ? pick(random, items).id : 'nobody';
  const kind = int(random, 0, 4);
  if (kind === 0) {
    const [x, y] = [int(random, -5, 16), int(random, -5, 40)];
    return (given) => move(given, target, x, y, CAT);
  }
  if (kind === 1) {
    const [w, h] = [int(random, -2, 15), int(random, -2, 14)];
    return (given) => resize(given, target, w, h, CAT);
  }
  if (kind === 2) {
    const type = pick(random, TYPES);
    const at = random() < 0.5 ? { x: int(random, -3, 14), y: int(random, -2, 30) } : undefined;
    return (given) => add(given, type, CAT, at).items;
  }
  if (kind === 3) {
    return (given) => remove(given, target);
  }
  return (given) => compact(given);
}

const RUNS = 2000;

test('property: every gesture leaves a valid layout (no overlap, in bounds, in sizes)', () => {
  property('valid', RUNS, (random) => {
    let items = randomLayout(random);
    assert.ok(valid(items), JSON.stringify(items));
    for (let step = 0; step < 6; step += 1) {
      items = randomGesture(random, items)(deepFreeze(items));
      assert.ok(valid(items), JSON.stringify(check(items, CAT)));
    }
  });
});

test('property: ids are kept by a move, a resize and a compaction; add adds one, remove removes one', () => {
  property('ids', RUNS, (random) => {
    const items = deepFreeze(randomLayout(random));
    const ids = items.map((each) => each.id).sort();
    const target = items.length ? pick(random, items).id : 'nobody';
    for (const after of [move(items, target, int(random, 0, 11), int(random, 0, 20), CAT),
                         resize(items, target, int(random, 1, 12), int(random, 1, 12), CAT), compact(items)]) {
      assert.deepEqual(after.map((each) => each.id).sort(), ids);
    }
    const added = add(items, pick(random, TYPES), CAT);
    assert.deepEqual(added.items.map((each) => each.id).sort(), [...ids, added.id].sort());
    if (items.length) {
      assert.deepEqual(remove(items, target).map((each) => each.id).sort(), ids.filter((id) => id !== target));
    }
  });
});

test('property: compact is idempotent and never moves an item down', () => {
  property('compact', RUNS, (random) => {
    const items = deepFreeze(randomLayout(random));
    const once = compact(items);
    assert.deepEqual(compact(deepFreeze(once)), once);
    for (const after of once) {
      const before = items.find((each) => each.id === after.id) as Item;
      assert.ok(after.y <= before.y && after.x === before.x && after.w === before.w && after.h === before.h);
    }
  });
});

test('property: serialize and parse round-trip any valid layout', () => {
  property('round trip', RUNS, (random) => {
    const items = randomLayout(random);
    const parsed = parse(deepFreeze(serialize(items)), CAT);
    assert.equal(parsed.ok, true);
    if (parsed.ok) {
      assert.deepEqual(parsed.items, items);
    }
  });
});

test('property: garbage never throws and never loops', () => {
  const atoms: unknown[] = [null, undefined, 0, -1, 1.5, Number.NaN, '', 'w1', true, [], {}, 1e9, -1e9];
  property('garbage', RUNS, (random) => {
    const junk = (depth: number): unknown => {
      const roll = int(random, 0, 3);
      if (depth > 3 || roll === 0) {
        return pick(random, atoms);
      }
      if (roll === 1) {
        return Array.from({ length: int(random, 0, 4) }, () => junk(depth + 1));
      }
      const keys = ['schema', 'widgets', 'id', 'type', 'x', 'y', 'w', 'h', 'bind', 'opts', ...TYPES];
      return Object.fromEntries(Array.from({ length: int(random, 0, 6) }, () => [pick(random, keys), junk(depth + 1)]));
    };
    const input = random() < 0.3 ? { schema: 1, widgets: junk(1) } : junk(0);
    const parsed = parse(input, CAT);
    assert.equal(typeof parsed.ok, 'boolean');
    for (const garbage of [junk(0), junk(0)]) {
      assert.doesNotThrow(() => check(Array.isArray(garbage) ? (garbage as Layout) : [], CAT));
    }
  });
});
