// The ONE slot rule of a monitoring wall of fitted cards: how many columns and rows of equal cells a screen is cut
// into, as a pure function. monitoring/cards/slots.py is the same rule in Python (the authority, as the validator is
// for a layout's geometry); both run monitoring/tests/slot_vectors.json.
//
// A fitted card is `mw` units wide and `mh` high (its template's measure) and every length inside it is a multiple of
// its unit, so the unit a cell gives is  min((cell width - the card's own padding) / mw, (cell height - padding) / mh).
// Of every grid whose cells hold all the cards, the rule takes the one that gives the largest unit (with equal units,
// the fewer cells). When that unit is under the smallest that can be read (`minU`; never under FLOOR), the wall turns
// pages instead of shrinking the type: the grid with the MOST cells whose unit can still be read (with equal cells,
// the larger unit). A cell is never lower than `mh` units of FLOOR: a window too low for one row scrolls.

/** Under this unit (px) a card's smallest text, 0.8 of it, is under 11 px. */
export const FLOOR = 14;
const MAX_COLS = 16;
const MAX_ROWS = 12;
const EPSILON = 1e-6;

export interface Slots {
  readonly cols: number;
  readonly rows: number;
  readonly u: number;        // the unit a card gets, px
  readonly pages: number;
}

/** The grid for `count` cards on a screen `width` by `height` px (the room under the band) with `gap` px between
 *  cells, for cards of `mw` by `mh` units whose own padding and borders take `padX` and `padY` px. */
export function slots(count: number, width: number, height: number, gap: number, mw: number, mh: number,
                      minU: number = FLOOR, padX = 0, padY = 0): Slots {
  const least = Math.max(minU, FLOOR);
  let all: Slots | null = null;
  let paged: Slots | null = null;
  for (let cols = 1; cols <= MAX_COLS; cols += 1) {
    for (let rows = 1; rows <= MAX_ROWS; rows += 1) {
      const room = (height - (rows - 1) * gap) / rows;
      const cell = Math.max(room, mh * FLOOR + padY);
      const u = Math.min(((width - (cols - 1) * gap) / cols - padX) / mw, (cell - padY) / mh);
      const fits = cell <= room + 0.5;
      const cells = cols * rows;
      const found: Slots = { cols, rows, u, pages: Math.max(1, Math.ceil(count / cells)) };
      if (fits && cells >= count && (all === null || u > all.u + EPSILON
          || (Math.abs(u - all.u) <= EPSILON && cells < all.cols * all.rows))) {
        all = found;
      }
      if (u >= least - EPSILON && (fits || rows === 1) && (paged === null || cells > paged.cols * paged.rows
          || (cells === paged.cols * paged.rows && u > paged.u))) {
        paged = found;
      }
    }
  }
  if (all !== null && all.u >= least - EPSILON) {
    return all;
  }
  return paged ?? all ?? { cols: 1, rows: 1, u: FLOOR, pages: Math.max(1, count) };
}

/** The page (from 1) that holds the card at `index` (from 0) when a page holds `per` cards. */
export function pageOf(index: number, per: number): number {
  return Math.floor(Math.max(index, 0) / Math.max(per, 1)) + 1;
}

/** The page of the worst card: the first card in the first of `order` (the states, worst first) that any card is in;
 *  the first page when none is. `states`: each card's state, in the page's order. */
export function worstPage(states: readonly string[], per: number, order: readonly string[]): number {
  for (const state of order) {
    const index = states.indexOf(state);
    if (index >= 0) {
      return pageOf(index, per);
    }
  }
  return 1;
}
