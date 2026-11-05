// The card designer's grid: pure functions over an immutable layout (no DOM, no state, no library). Each returns a new
// list and never changes the one it is given; garbage in is a typed answer, never a throw or an endless loop.
//
// The server is the authority (monitoring/cards/validate.py): this file mirrors its geometry (bounds, sizes, overlaps)
// for the designer, and both run monitoring/tests/layout_vectors.json. Compaction (floating widgets up) exists only
// here: the server never moves a widget.
//
// The rules of a gesture: the item that moves (or grows, or is dropped) is placed first, where it was put, clamped
// into the grid and its sizes; every item it lands on is pushed straight down below it, in reading order, and so on
// down; then the layout is compacted. A widget added without a place goes below everything.
import type { Catalogue, Cell, Change, Delta, Item, Layout, ParseError, Parsed, Problem, Spec } from './types.js';

const ID = /^[a-z][a-z0-9_-]{0,15}$/;
const REQUIRED = ['id', 'type', 'x', 'y', 'w', 'h'];
const OPTIONAL = ['bind', 'opts'];

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isWhole(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

function isItem(value: unknown): value is Item {
  return isObject(value) && typeof value.id === 'string' && typeof value.type === 'string'
    && ['x', 'y', 'w', 'h'].every((key) => Number.isFinite(value[key]));
}

// ---- the catalogue -------------------------------------------------------------------------------------------------
// The catalogue as monitoring.cards.catalogue.as_data gives it, or null when it is not one.
export function catalogueOf(data: unknown): Catalogue | null {
  if (!isObject(data) || !isWhole(data.columns) || data.columns < 1 || !Array.isArray(data.widgets)) {
    return null;
  }
  const specs: Record<string, Spec> = {};
  for (const entry of data.widgets) {
    const sizes = ['min_w', 'min_h', 'max_w', 'max_h', 'default_w', 'default_h'];
    if (!isObject(entry) || typeof entry.type !== 'string' || !sizes.every((key) => isWhole(entry[key]))) {
      return null;
    }
    specs[entry.type] = {
      min_w: entry.min_w as number, min_h: entry.min_h as number, max_w: entry.max_w as number,
      max_h: entry.max_h as number, default_w: entry.default_w as number, default_h: entry.default_h as number,
      enabled: entry.enabled !== false,
    };
  }
  return { columns: data.columns, schema: isWhole(data.schema) ? data.schema : 1, specs };
}

// ---- reading and writing a stored layout ----------------------------------------------------------------------------
function refused(error: ParseError, widget = ''): Parsed {
  return { ok: false, error, widget };
}

// A stored layout read into items, or the first reason it cannot be, in the server validator's order and codes.
export function parse(input: unknown, cat: Catalogue): Parsed {
  if (!isObject(input) || Object.keys(input).length !== 2 || !('schema' in input) || !Array.isArray(input.widgets)
      || !input.widgets.every(isObject)) {
    return refused('shape');
  }
  if (input.schema !== cat.schema) {
    return refused('schema');
  }
  const items: Item[] = [];
  const seen = new Set<string>();
  for (const widget of input.widgets as Record<string, unknown>[]) {
    const id = widget.id;
    if (typeof id !== 'string' || !ID.test(id)) {
      return refused('id', typeof id === 'string' ? id : '');
    }
    if (seen.has(id)) {
      return refused('duplicate', id);
    }
    seen.add(id);
    const keys = Object.keys(widget);
    if (!REQUIRED.every((key) => key in widget) || keys.some((key) => !REQUIRED.includes(key) && !OPTIONAL.includes(key))) {
      return refused('keys', id);
    }
    if (typeof widget.type !== 'string' || !(widget.type in cat.specs)) {
      return refused('type', id);
    }
    if (!['x', 'y', 'w', 'h'].every((key) => isWhole(widget[key]))) {
      return refused('number', id);
    }
    items.push(Object.freeze({ ...(widget as unknown as Item) }));
  }
  return { ok: true, items };
}

// The layout as the server stores it: the keys in one order, the binding and options as they came.
export function serialize(items: Layout, schema = 1): { schema: number; widgets: Record<string, unknown>[] } {
  return {
    schema,
    widgets: items.map((item) => {
      const stored: Record<string, unknown> = { id: item.id, type: item.type, x: item.x, y: item.y, w: item.w,
                                                h: item.h };
      if (item.bind !== undefined) {
        stored.bind = item.bind;
      }
      if (item.opts !== undefined) {
        stored.opts = item.opts;
      }
      return stored;
    }),
  };
}

// ---- geometry ------------------------------------------------------------------------------------------------------
export function collides(a: Item, b: Item): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

// The geometry problems of a layout, in the server's order: each widget's bounds then size, then each overlapping pair.
export function check(items: Layout, cat: Catalogue): Problem[] {
  const placed = Array.isArray(items) ? items.filter(isItem) : [];
  const problems: Problem[] = [];
  for (const item of placed) {
    if (item.x < 0 || item.y < 0 || item.x + item.w > cat.columns) {
      problems.push({ code: 'bounds', widget: item.id });
    }
    const spec = cat.specs[item.type];
    if (spec !== undefined && !(spec.min_w <= item.w && item.w <= spec.max_w && spec.min_h <= item.h
                                && item.h <= spec.max_h)) {
      problems.push({ code: 'size', widget: item.id });
    }
  }
  placed.forEach((item, index) => {
    for (const other of placed.slice(index + 1)) {
      if (collides(item, other)) {
        problems.push({ code: 'overlap', widget: item.id, other: other.id });
      }
    }
  });
  return problems;
}

function whole(value: number): number {
  return Number.isFinite(value) ? Math.round(value) : 0;
}

function within(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high);
}

// The item made whole, inside its sizes, inside the columns and below the top. An unknown type keeps its size.
export function clamp(item: Item, cat: Catalogue): Item {
  const spec = cat.specs[item.type];
  let w = whole(item.w);
  let h = whole(item.h);
  if (spec !== undefined) {
    w = within(w, spec.min_w, Math.min(spec.max_w, cat.columns));
    h = within(h, spec.min_h, spec.max_h);
  }
  w = within(w, 1, cat.columns);
  h = Math.max(h, 1);
  return { ...item, x: within(whole(item.x), 0, cat.columns - w), y: Math.max(whole(item.y), 0), w, h };
}

// The items in reading order, (y, x), ties in the list's order (a stable sort).
export function readingOrder(items: Layout): Layout {
  return items.map((item, index) => ({ item, index }))
    .sort((a, b) => a.item.y - b.item.y || a.item.x - b.item.x || a.index - b.index)
    .map((entry) => entry.item);
}

function bottom(items: Iterable<Item>): number {
  let lowest = 0;
  for (const item of items) {
    lowest = Math.max(lowest, item.y + item.h);
  }
  return lowest;
}

// Each item in reading order goes down below anything placed before it that it lands on (an overlap in the input is
// resolved), then up as far as nothing placed blocks it. The list keeps its order; only y changes.
export function compact(items: Layout): Layout {
  const placed: Item[] = [];
  const moved = new Map<Item, Item>();
  for (const item of readingOrder(items)) {
    let current = item;
    for (let hit = placed.find((other) => collides(current, other)); hit !== undefined;
         hit = placed.find((other) => collides(current, other))) {
      current = { ...current, y: hit.y + hit.h };
    }
    while (current.y > 0) {
      const higher = { ...current, y: current.y - 1 };
      if (placed.some((other) => collides(higher, other))) {
        break;
      }
      current = higher;
    }
    placed.push(current);
    moved.set(item, current.y === item.y ? item : current);
  }
  return items.map((item) => moved.get(item) as Item);
}

// `first` placed where it is; every other item, in reading order, pushed straight down below whatever it lands on.
function settle(items: Layout, first: Item): Layout {
  const placed: Item[] = [first];
  const moved = new Map<string, Item>([[first.id, first]]);
  for (const item of readingOrder(items.filter((each) => each.id !== first.id))) {
    let current = item;
    for (let hit = placed.find((other) => collides(current, other)); hit !== undefined;
         hit = placed.find((other) => collides(current, other))) {
      current = { ...current, y: hit.y + hit.h };
    }
    placed.push(current);
    moved.set(item.id, current);
  }
  const all = items.some((each) => each.id === first.id) ? items : [...items, first];
  return compact(all.map((item) => moved.get(item.id) as Item));
}

function changed(items: Layout, id: string, change: (item: Item) => Item, cat: Catalogue): Layout {
  const item = items.find((each) => each.id === id);
  if (item === undefined) {
    return items;
  }
  return settle(items, clamp(change(item), cat));
}

export function move(items: Layout, id: string, x: number, y: number, cat: Catalogue): Layout {
  return changed(items, id, (item) => ({ ...item, x, y }), cat);
}

export function resize(items: Layout, id: string, w: number, h: number, cat: Catalogue): Layout {
  return changed(items, id, (item) => ({ ...item, w, h }), cat);
}

// The next free id: w followed by one more than the highest number of a wN id.
export function nextId(items: Layout): string {
  let highest = 0;
  for (const item of items) {
    const found = /^w(\d+)$/.exec(item.id);
    if (found !== null) {
      highest = Math.max(highest, Number(found[1]));
    }
  }
  return `w${highest + 1}`;
}

// A new widget of `type` at its default size: dropped at `at` (and settled there), or below everything. An unknown
// or disabled type adds nothing.
export function add(items: Layout, type: string, cat: Catalogue, at?: Cell): { items: Layout; id: string } {
  const spec = cat.specs[type];
  if (spec === undefined || !spec.enabled) {
    return { items, id: '' };
  }
  const id = nextId(items);
  const fresh = clamp({ id, type, x: at ? at.x : 0, y: at ? at.y : bottom(items), w: spec.default_w,
                        h: spec.default_h }, cat);
  return { items: at ? settle(items, fresh) : [...items, fresh], id };
}

export function remove(items: Layout, id: string): Layout {
  return compact(items.filter((item) => item.id !== id));
}

// What happened to each widget between two layouts: the gone and the changed in the first's order, then the new.
export function changes(before: Layout, after: Layout): Change[] {
  const found: Change[] = [];
  const next = new Map(after.map((item) => [item.id, item]));
  const previous = new Set(before.map((item) => item.id));
  const of = (kind: Change['kind'], item: Item): Change =>
    ({ kind, id: item.id, x: item.x, y: item.y, w: item.w, h: item.h });
  for (const item of before) {
    const now = next.get(item.id);
    if (now === undefined) {
      found.push(of('removed', item));
    } else if (now.w !== item.w || now.h !== item.h) {
      found.push(of('resized', now));
    } else if (now.x !== item.x || now.y !== item.y) {
      found.push(of('moved', now));
    }
  }
  for (const item of after) {
    if (!previous.has(item.id)) {
      found.push(of('added', item));
    }
  }
  return found;
}

// ---- input -----------------------------------------------------------------------------------------------------------
// The cell under a point of the page, given the grid's box, its columns and its row height in pixels; clamped to the
// grid's columns and to the first row.
export function cellFromPoint(x: number, y: number, box: { left: number; top: number; width: number },
                              columns: number, rowPx: number): Cell {
  const column = Math.floor((x - box.left) / (box.width / columns));
  const row = Math.floor((y - box.top) / rowPx);
  return { x: within(Number.isFinite(column) ? column : 0, 0, columns - 1), y: Math.max(Number.isFinite(row) ? row : 0, 0) };
}

const STEPS: Readonly<Record<string, readonly [number, number]>> = {
  ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
};

// An arrow key moves the selected widget one cell; with Shift it grows or shrinks it one cell. Any other key: null.
export function keyToDelta(key: string, shift: boolean): Delta | null {
  const step = STEPS[key];
  if (step === undefined) {
    return null;
  }
  return shift ? { kind: 'resize', dw: step[0], dh: step[1] } : { kind: 'move', dx: step[0], dy: step[1] };
}
