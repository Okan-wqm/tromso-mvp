// What a key does to the designer's selected widget, as a pure function (the canvas calls it; frontend/designer.ts):
// an arrow moves it one cell, Shift and an arrow grow or shrink it one cell, Delete or Backspace removes it and selects
// the next widget in reading order (the one before when it was the last). Every other key, or no selection: null, and
// the browser keeps the key (Tab still leaves the canvas: no key is trapped).
import { keyToDelta, move, readingOrder, remove, resize } from './layout.js';
import type { Catalogue, Layout } from './types.js';

export interface KeyResult {
  readonly items: Layout;
  readonly selected: string;
}

const REMOVE_KEYS = new Set(['Delete', 'Backspace']);

export function applyKey(items: Layout, selected: string, key: string, shift: boolean, cat: Catalogue): KeyResult | null {
  const item = items.find((each) => each.id === selected);
  if (item === undefined) {
    return null;
  }
  if (REMOVE_KEYS.has(key)) {
    const order = readingOrder(items).map((each) => each.id);
    const index = order.indexOf(selected);
    const next = order[index + 1] ?? order[index - 1] ?? '';
    return { items: remove(items, selected), selected: next };
  }
  const delta = keyToDelta(key, shift);
  if (delta === null) {
    return null;
  }
  if (delta.kind === 'move') {
    return { items: move(items, selected, item.x + delta.dx, item.y + delta.dy, cat), selected };
  }
  return { items: resize(items, selected, item.w + delta.dw, item.h + delta.dh, cat), selected };
}
