// The monitoring wall of FITTED cards (Operations › Monitoring with ?wall=1 and a template that has a measure): it cuts
// the screen under the band into columns and rows of equal cells by the one slot rule (frontend/wall/slots.ts), and
// turns the pages when there are more cards than cells. It sets custom properties and attributes on the grid through
// the CSSOM, never a style attribute in markup (the Content-Security-Policy), and never touches a card: the grid's
// children are the server's, replaced by the poll (frontend/poll.ts), and a card changed here would be replaced at
// every poll. static/css/monitor.css does the rest ("the wall of fitted cards", "the dock").
//   --cols, --rows   the grid, on .monitor-grid
//   --mh             the cards' height in card units (the template's measure), for the least height of a cell
//   --dock-space     on .monitor-grid: the room the pane takes beside the cards (0 when none is open)
//   --dock, --dock-top, data-dock="beside|full"   on #monitor-dock (the pane of the unit gone into, opened by
//                    frontend/windows.ts or drawn by the server for ?focus=): its width, one cell of a wall of
//                    full-height cards on this screen, and where it starts under the band; "full" when a card that
//                    wide could not be read beside the cards: the pane then lies over them
//   data-page, data-page-count, data-per   the page shown, the pages, the cards on one
//   [data-pages]     the band's page indicator (hidden by the server; shown here when there are two pages or more),
//                    [data-pages-text] its "2 / 3", [data-page-turn="-1|1"] its buttons, [data-page-worst] the way to
//                    the page of the worst card, shown while that card is on another page ([data-page-worst-text] its
//                    page, [data-page-worst-shape] the state's shape)
// THE KEYS of a wall: PageDown and PageUp turn the page; Home goes to the page of the worst card and puts the focus on
// that card's link (Enter then opens it); Escape closes the pane (windows.ts); Tab and Enter do what they do on links.
// A wall opens on the page of its worst card (the states' order is the page's own, #monitor-announce data-states:
// monitoring/read.py STATES); a card never moves, so a page is always the same cards. A poll keeps the page shown: a
// card that became the worst on another page is one key away (Home), and the band says on which page it is. A link
// of the band to a card (a chip's code, `#card-<unit>`) turns to that card's page. The band is replaced whole by a
// poll: the control that had the focus gets it back by its id (poll.ts restores it while the page indicator is still
// hidden, which a hidden element refuses: it is given again here once the indicator shows).
// A wall of cards that flow (Simple, Detailed) is left as it is: the page scrolls. Without this script the fitted
// cards stand four across and the grid scrolls.
import { dock, fillUnit, pageOf, slots, worst } from './wall/slots.js';

const number = (value: string | null | undefined): number => Number.parseFloat(value ?? '') || 0;
// The rungs a wall opens on and jumps to: critical, warning, no recent data (the first three of the states' order).
const WORST_RUNGS = 3;

function grid(): HTMLElement | null {
  return document.documentElement.hasAttribute('data-wall') ? document.querySelector<HTMLElement>('.monitor-grid') : null;
}

function cardsOf(wall: HTMLElement): HTMLElement[] {
  return Array.from(wall.querySelectorAll<HTMLElement>(':scope > .monitor-card'));
}

/** The measure of the wall's fitted cards, from their classes (mw-31 mh-12): the largest of each, null when none is
 *  fitted. */
function measure(cards: HTMLElement[]): { mw: number; mh: number; card: HTMLElement } | null {
  let mw = 0;
  let mh = 0;
  let first: HTMLElement | undefined;
  for (const card of cards) {
    if (!card.classList.contains('is-fit')) continue;
    const width = /(?:^|\s)mw-(\d+)(?:\s|$)/.exec(card.className);
    const height = /(?:^|\s)mh-(\d+)(?:\s|$)/.exec(card.className);
    if (!width || !height) continue;
    mw = Math.max(mw, Number(width[1]));
    mh = Math.max(mh, Number(height[1]));
    first ??= card;
  }
  return first ? { mw, mh, card: first } : null;
}

/** The states in the order a wall reads them, worst first (the page's list holds them worst first too). */
function order(): string[] {
  return (document.getElementById('monitor-announce')?.dataset.states ?? '').split(' ').filter(Boolean);
}

/** The worst card of the wall as it is now, with its page; null when no card is critical, a warning or blind. */
function worstOf(wall: HTMLElement): { index: number; page: number; state: string } | null {
  const states = cardsOf(wall).map((card) => card.dataset.state ?? '');
  return worst(states, Number(wall.dataset.per) || 1, order().slice(0, WORST_RUNGS));
}

function show(wall: HTMLElement, page: number): void {
  const pages = Number(wall.dataset.pageCount) || 1;
  const per = Number(wall.dataset.per) || 1;
  const chosen = Math.min(Math.max(page, 1), pages);
  wall.dataset.page = String(chosen);
  const cards = cardsOf(wall);
  const first = cards[(chosen - 1) * per];
  const top = cards[0];
  if (first && top) wall.scrollTop = first.offsetTop - top.offsetTop;
  const found = worstOf(wall);
  wall.querySelectorAll<HTMLElement>('[data-pages]').forEach((indicator) => {
    indicator.hidden = pages < 2;
    const text = indicator.querySelector('[data-pages-text]');
    if (text) text.textContent = `${chosen} / ${pages}`;
    const jump = indicator.querySelector<HTMLElement>('[data-page-worst]');
    if (!jump) return;
    jump.hidden = found === null || found.page === chosen;
    if (found === null) return;
    jump.dataset.state = found.state;
    const shape = jump.querySelector<HTMLElement>('[data-page-worst-shape]');
    if (shape) shape.className = `monitor-shape monitor-shape-${found.state}`;
    const where = jump.querySelector('[data-page-worst-text]');
    if (where) where.textContent = String(found.page);
  });
}

function clear(wall: HTMLElement): void {
  for (const name of ['--cols', '--rows', '--mh', '--band', '--dock-space']) wall.style.removeProperty(name);
  delete wall.dataset.page;
  delete wall.dataset.pageCount;
  delete wall.dataset.per;
  const pane = document.getElementById('monitor-dock');
  if (pane) delete pane.dataset.dock;
}

/** Lays the wall out for the window as it is now; `keep`: stay on the page shown (a poll changed the cards), else the
 *  page of the worst card. */
function lay(keep: boolean): void {
  const wall = grid();
  if (!wall) return;
  const cards = cardsOf(wall);
  const fitted = measure(cards);
  if (!fitted) {
    clear(wall);
    return;
  }
  wall.style.setProperty('--dock-space', '0px');          // (measured without the pane's room, which is set below)
  const style = getComputedStyle(wall);
  const gap = number(style.rowGap);
  const band = wall.querySelector<HTMLElement>(':scope > .monitor-band');
  const width = wall.clientWidth - number(style.paddingLeft) - number(style.paddingRight);
  // (the band wraps rather than cut a chip, review R4: the cards get the room it really leaves. Its row is as high as
  // --band says, so its own height is measured with the row left to its content: never less than the sheet's height
  // of a band, and as much more as a third line of chips needs. Measured in its row, it only ever read --band back,
  // and a third line was cut at the top of the screen.)
  if (band) {
    wall.style.removeProperty('--band');
    const least = band.offsetHeight;
    wall.style.setProperty('--band', 'max-content');
    wall.style.setProperty('--band', `${Math.max(least, band.offsetHeight)}px`);
  }
  const height = wall.clientHeight - (band ? band.offsetHeight + gap : 0);
  const own = getComputedStyle(fitted.card);
  const padX = number(own.paddingLeft) + number(own.paddingRight) + number(own.borderLeftWidth) + number(own.borderRightWidth);
  const padY = number(own.paddingTop) + number(own.paddingBottom) + number(own.borderTopWidth) + number(own.borderBottomWidth);
  // The pane of the unit gone into: one cell of a wall of full-height cards beside the overview, whose cards then
  // share the room that is left (they only get narrower: the order is the same and a card never moves).
  const pane = document.getElementById('monitor-dock');
  let space = 0;
  if (pane) {
    if (pane.querySelector('.monitor-window')) {
      const bar = pane.querySelector<HTMLElement>('.monitor-dock-bar');
      const room = height - (bar ? bar.offsetHeight : 0);
      const found = dock(width, room, gap, number(pane.dataset.mw), number(pane.dataset.mh), padX, padY);
      pane.dataset.dock = found.beside ? 'beside' : 'full';
      pane.style.setProperty('--dock', `${found.width}px`);
      pane.style.setProperty('--dock-top', `${wall.getBoundingClientRect().top + (band ? band.offsetHeight + gap : 0)}px`);
      space = found.beside ? found.width + gap : 0;
    } else {
      delete pane.dataset.dock;
    }
  }
  wall.style.setProperty('--dock-space', `${space}px`);
  // (a full-height card, data-fill, keeps a whole row of the screen: more of them than fit side by side turn pages)
  const least = fitted.card.hasAttribute('data-fill') ? fillUnit(width - space, height, fitted.mw, fitted.mh, padX, padY) : undefined;
  const chosen = slots(cards.length, width - space, height, gap, fitted.mw, fitted.mh, least, padX, padY);
  wall.style.setProperty('--cols', String(chosen.cols));
  wall.style.setProperty('--rows', String(chosen.rows));
  wall.style.setProperty('--mh', String(fitted.mh));
  const per = chosen.cols * chosen.rows;
  wall.dataset.per = String(per);
  wall.dataset.pageCount = String(chosen.pages);
  // (critical, warning, no recent data: the three rungs a wall opens on; a card never moves for the others either)
  show(wall, keep && wall.dataset.page ? Number(wall.dataset.page) : worstOf(wall)?.page ?? 1);
}

let seen = '';
function relay(): void {
  const size = `${window.innerWidth}x${window.innerHeight}`;
  const keep = size === seen;
  seen = size;
  lay(keep);
}

function turn(by: number): void {
  const wall = grid();
  if (wall && wall.dataset.pageCount) show(wall, (Number(wall.dataset.page) || 1) + by);
}

/** The first thing of a card a key can stand on (its code's link). */
function handle(card: HTMLElement | undefined): HTMLElement | null {
  return card?.querySelector<HTMLElement>('h3 a, a, button') ?? null;
}

/** Turns to the page of `card` and puts the focus on it; false when the wall is not laid out or the card is not its. */
function reach(card: HTMLElement | null): boolean {
  const wall = grid();
  if (!wall || !card || !wall.dataset.pageCount) return false;
  const index = cardsOf(wall).indexOf(card);
  if (index < 0) return false;
  show(wall, pageOf(index, Number(wall.dataset.per) || 1));
  handle(card)?.focus({ preventScroll: true });
  return true;
}

/** To the page of the worst card, the focus on that card. */
function toWorst(): boolean {
  const wall = grid();
  const found = wall && wall.dataset.pageCount ? worstOf(wall) : null;
  return found !== null && wall !== null && reach(cardsOf(wall)[found.index] ?? null);
}

document.addEventListener('keydown', (event) => {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  if (event.key !== 'PageDown' && event.key !== 'PageUp' && event.key !== 'Home') return;
  if (event.target instanceof Element && event.target.closest('input, select, textarea, [contenteditable]')) return;
  const wall = grid();
  if (!wall || !wall.dataset.pageCount) return;
  if (event.key === 'Home') {
    if (toWorst()) event.preventDefault();
    return;
  }
  event.preventDefault();
  turn(event.key === 'PageDown' ? 1 : -1);
});
document.addEventListener('click', (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const button = target?.closest<HTMLElement>('[data-page-turn]');
  if (button) turn(Number(button.dataset.pageTurn) || 0);
  if (target?.closest('[data-page-worst]')) toWorst();
  // a link of the band to a card: its page, and the focus on the card (a chip that also opens the pane, data-dock, is
  // windows.ts's to follow: here only the page turns)
  const link = target?.closest<HTMLAnchorElement>('.monitor-band a[href*="#card-"]');
  if (!link) return;
  const card = document.getElementById(new URL(link.href, window.location.href).hash.slice(1));
  const wall = grid();
  if (!wall || !card || !wall.dataset.pageCount) return;
  if (link.hasAttribute('data-dock')) {
    const index = cardsOf(wall).indexOf(card);
    if (index >= 0) show(wall, pageOf(index, Number(wall.dataset.per) || 1));
  } else if (reach(card)) {
    event.preventDefault();
  }
});

// What had the focus inside the grid, by its id: a poll that replaces the band (or a card) gives it back.
let held = '';
document.addEventListener('focusin', (event) => {
  const target = event.target;
  held = target instanceof HTMLElement && target.id && grid()?.contains(target) ? target.id : '';
});

// A poll replaced, added or removed cards (and the band with its page indicator): the same page, laid out again, and
// the focus back where it was.
document.addEventListener('poll:merged', (event) => {
  if (!(event.target instanceof HTMLElement) || !event.target.classList.contains('monitor-grid')) return;
  lay(true);
  // (only a focus that was LOST: the element was replaced and nothing else took the focus since)
  if (!held || (document.activeElement !== null && document.activeElement !== document.body)) return;
  const again = document.getElementById(held);
  if (again && grid()?.contains(again)) again.focus({ preventScroll: true });
});
// The pane was opened, replaced or closed (frontend/windows.ts), or its card came: the cards share the room anew.
// (fewer columns beside a pane are other pages: the page shown is then the one of the card that is open)
document.addEventListener('dock:changed', () => {
  lay(true);
  const wall = grid();
  const unit = document.querySelector<HTMLElement>('#monitor-dock .monitor-window')?.dataset.dockUnit;
  const card = unit ? document.getElementById(`card-${unit}`) : null;
  if (!wall || !card || !wall.dataset.pageCount) return;
  const index = cardsOf(wall).indexOf(card);
  if (index >= 0) show(wall, pageOf(index, Number(wall.dataset.per) || 1));
});

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', relay);
else relay();
window.addEventListener('load', relay);
window.addEventListener('resize', relay);
document.addEventListener('fullscreenchange', relay);
