// Undo and redo of the card designer, as immutable values: a history is the layouts before (past), the one shown
// (present) and the ones undone (future). A gesture (a drag, a resize, a key press, an added or removed widget) is
// committed once at its end, so it is one entry; the canvas draws its previews without committing them. At most CAP
// entries are kept back; a new entry clears what could be redone; a layout equal to the present is not an entry.
import type { Layout } from './types.js';

export const CAP = 100;

export interface History {
  readonly past: readonly Layout[];
  readonly present: Layout;
  readonly future: readonly Layout[];
}

export function start(present: Layout): History {
  return { past: [], present, future: [] };
}

function same(a: Layout, b: Layout): boolean {
  return a === b || JSON.stringify(a) === JSON.stringify(b);
}

export function commit(history: History, next: Layout): History {
  if (same(history.present, next)) {
    return history;
  }
  return { past: [...history.past, history.present].slice(-CAP), present: next, future: [] };
}

export function canUndo(history: History): boolean {
  return history.past.length > 0;
}

export function canRedo(history: History): boolean {
  return history.future.length > 0;
}

export function undo(history: History): History {
  if (!canUndo(history)) {
    return history;
  }
  return { past: history.past.slice(0, -1), present: history.past[history.past.length - 1],
           future: [history.present, ...history.future] };
}

export function redo(history: History): History {
  if (!canRedo(history)) {
    return history;
  }
  return { past: [...history.past, history.present], present: history.future[0], future: history.future.slice(1) };
}
