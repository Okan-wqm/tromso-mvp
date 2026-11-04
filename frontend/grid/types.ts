// The types of the card designer's grid library (frontend/grid/). A layout is an immutable list of items; every
// function of the library returns a new list and never changes the one it is given.

// One widget on the grid: its id, its type (a key of the catalogue), its place (x, y) and size (w, h) in cells. The
// binding and options are carried through untouched: the server's validator owns them (monitoring/cards/validate.py).
export interface Item {
  readonly id: string;
  readonly type: string;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
  readonly bind?: unknown;
  readonly opts?: unknown;
}

export type Layout = readonly Item[];

// A widget type's sizes in cells, from monitoring.cards.catalogue (as_data).
export interface Spec {
  readonly min_w: number;
  readonly min_h: number;
  readonly max_w: number;
  readonly max_h: number;
  readonly default_w: number;
  readonly default_h: number;
  readonly enabled: boolean;
}

export interface Catalogue {
  readonly columns: number;
  readonly schema: number;
  readonly specs: Readonly<Record<string, Spec>>;
}

// The geometry the library mirrors from the server's validator (monitoring/tests/layout_vectors.json).
export type GeometryCode = 'bounds' | 'size' | 'overlap';

export interface Problem {
  readonly code: GeometryCode;
  readonly widget: string;
  readonly other?: string;
}

// Why a stored layout could not be read, in the server validator's codes.
export type ParseError = 'shape' | 'schema' | 'keys' | 'id' | 'duplicate' | 'type' | 'number';

export type Parsed =
  | { readonly ok: true; readonly items: Layout }
  | { readonly ok: false; readonly error: ParseError; readonly widget: string };

// What a gesture did to one widget; the kind is the key of the sentence the page announces (data-announce-<kind>).
export type ChangeKind = 'moved' | 'resized' | 'removed' | 'added';

export interface Change {
  readonly kind: ChangeKind;
  readonly id: string;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

export type Delta =
  | { readonly kind: 'move'; readonly dx: number; readonly dy: number }
  | { readonly kind: 'resize'; readonly dw: number; readonly dh: number };

export interface Cell {
  readonly x: number;
  readonly y: number;
}
