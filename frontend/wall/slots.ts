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

/** A FULL-HEIGHT card (its measure is higher than wide) keeps at least this share of the unit one card alone on the
 *  screen would have: the wall turns pages rather than set more of them side by side (monitoring/cards/slots.py). */
export const FILL = 0.97;

/** The smallest unit (`minU`) of a wall of full-height cards. */
export function fillUnit(width: number, height: number, mw: number, mh: number, padX = 0, padY = 0): number {
  return FILL * Math.max(Math.min((width - padX) / mw, (height - padY) / mh), 0);
}

/** The pane beside an overview (the Big card of the unit gone into): as wide as ONE cell of a wall of full-height
 *  cards of `mw` by `mh` units on this screen (so the pane is the card the all-big wall would show), at most half the
 *  screen. `beside` is false when a card that wide could not be read (its unit under `floor`: FLOOR, or the wall's
 *  legible unit at its distance): the pane then lies over
 *  the cards instead of standing beside them, never hidden. `width`, `height`: the room under the band. */
export function dock(width: number, height: number, gap: number, mw: number, mh: number, padX = 0, padY = 0,
                     floor = FLOOR): { width: number; beside: boolean } {
  const big = slots(MAX_COLS, width, height, gap, mw, mh, fillUnit(width, height, mw, mh, padX, padY), padX, padY);
  const wide = Math.min((width - (big.cols - 1) * gap) / big.cols, width * 0.5);
  const unit = Math.min((wide - padX) / mw, (height - padY) / mh);
  return { width: wide, beside: unit >= Math.max(floor, FLOOR) - 0.5 };
}

/** The page (from 1) that holds the card at `index` (from 0) when a page holds `per` cards. */
export function pageOf(index: number, per: number): number {
  return Math.floor(Math.max(index, 0) / Math.max(per, 1)) + 1;
}

/** The page of the worst card: the first card in the first of `order` (the states, worst first) that any card is in;
 *  the first page when none is. `states`: each card's state, in the page's order. */
export function worstPage(states: readonly string[], per: number, order: readonly string[]): number {
  return worst(states, per, order)?.page ?? 1;
}

/** The worst card: the first card in the first of `order` that any card is in, with its place, its page and its
 *  state; null when no card is in any of them. */
export function worst(states: readonly string[], per: number, order: readonly string[]):
    { index: number; page: number; state: string } | null {
  for (const state of order) {
    const index = states.indexOf(state);
    if (index >= 0) {
      return { index, page: pageOf(index, per), state };
    }
  }
  return null;
}

// ---- how large a wall's type must be to be read from where it is watched (monitoring/cards/slots.py, the authority;
// frontend-redesign CONSENSUS §9): state words at 20 arcmin (FHWA-RD-98-057 ch. 3), every other text at 15 arcmin
// (MIL-STD-1472H §5.17.18.2), a character's height the cap height of the text face. The standards' figures, not a
// farm's preference: a board chooses its screen and its distance.
export const ARCMIN_CRITICAL = 20;
export const ARCMIN_SECONDARY = 15;
export const CAP = 0.67;
const STEP_STATE = 1.25;
const STEP_SMALLEST = 0.8;
const MM_PER_INCH = 25.4;

/** The font size (CSS px) whose characters subtend `arcmin` at `distanceM` on a screen of `inches` diagonal that is
 *  `screenW` by `screenH` CSS px. */
export function textPx(arcmin: number, inches: number, distanceM: number, screenW: number, screenH: number): number {
  const pxMm = (inches * MM_PER_INCH) / Math.hypot(screenW, screenH);
  const heightMm = 2 * distanceM * 1000 * Math.tan(((arcmin / 60) * Math.PI) / 180 / 2);
  return heightMm / CAP / pxMm;
}

/** The smallest unit (`minU`) of a wall read from `distanceM` on that screen; FLOOR when the board says no screen or no
 *  distance (0). `critical`: the step of the unit its critical words are set in (a card's state word, 1.25; the band's
 *  tally and chips, 1). */
export function legibleUnit(inches: number, distanceM: number, screenW: number, screenH: number,
                            critical = STEP_STATE): number {
  if (!(inches > 0 && distanceM > 0 && screenW > 0 && screenH > 0)) return FLOOR;
  return Math.max(FLOOR, textPx(ARCMIN_CRITICAL, inches, distanceM, screenW, screenH) / critical,
                  textPx(ARCMIN_SECONDARY, inches, distanceM, screenW, screenH) / STEP_SMALLEST);
}
