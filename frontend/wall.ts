// The monitoring wall of FITTED cards (Operations › Monitoring with ?wall=1 and a template that has a measure): it cuts
// the screen under the band into columns and rows of equal cells by the one slot rule (frontend/wall/slots.ts), and
// turns the pages when there are more cards than cells. It sets custom properties and attributes on the grid through
// the CSSOM, never a style attribute in markup (the Content-Security-Policy), and never touches a card: the grid's
// children are the server's, replaced by the poll (frontend/poll.ts), and a card changed here would be replaced at
// every poll. static/css/monitor.css does the rest ("the wall of fitted cards").
//   --cols, --rows   the grid, on .monitor-grid
//   --mh             the cards' height in card units (the template's measure), for the least height of a cell
//   data-page, data-page-count, data-per   the page shown, the pages, the cards on one
//   [data-pages]     the band's page indicator (hidden by the server; shown here when there are two pages or more),
//                    [data-pages-text] its "2 / 3", [data-page-turn="-1|1"] its buttons
// PageDown and PageUp turn the page. A wall opens on the page of its worst card (the states' order is the page's own,
// #monitor-announce data-states: monitoring/read.py STATES); a card never moves, so a page is always the same cards.
// A wall of cards that flow (Simple, Detailed) is left as it is: the page scrolls. Without this script the fitted
// cards stand four across and the grid scrolls.
import { slots, worstPage } from './wall/slots.js';

const number = (value: string | null | undefined): number => Number.parseFloat(value ?? '') || 0;

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

function show(wall: HTMLElement, page: number): void {
  const pages = Number(wall.dataset.pageCount) || 1;
  const per = Number(wall.dataset.per) || 1;
  const chosen = Math.min(Math.max(page, 1), pages);
  wall.dataset.page = String(chosen);
  const cards = cardsOf(wall);
  const first = cards[(chosen - 1) * per];
  const top = cards[0];
  if (first && top) wall.scrollTop = first.offsetTop - top.offsetTop;
  wall.querySelectorAll<HTMLElement>('[data-pages]').forEach((indicator) => {
    indicator.hidden = pages < 2;
    const text = indicator.querySelector('[data-pages-text]');
    if (text) text.textContent = `${chosen} / ${pages}`;
  });
}

function clear(wall: HTMLElement): void {
  for (const name of ['--cols', '--rows', '--mh', '--band']) wall.style.removeProperty(name);
  delete wall.dataset.page;
  delete wall.dataset.pageCount;
  delete wall.dataset.per;
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
  const style = getComputedStyle(wall);
  const gap = number(style.rowGap);
  const band = wall.querySelector<HTMLElement>(':scope > .monitor-band');
  const width = wall.clientWidth - number(style.paddingLeft) - number(style.paddingRight);
  // (the band wraps rather than cut a chip, review R4: the cards get the room it really leaves)
  if (band) wall.style.setProperty('--band', `${band.offsetHeight}px`);
  const height = wall.clientHeight - (band ? band.offsetHeight + gap : 0);
  const own = getComputedStyle(fitted.card);
  const padX = number(own.paddingLeft) + number(own.paddingRight) + number(own.borderLeftWidth) + number(own.borderRightWidth);
  const padY = number(own.paddingTop) + number(own.paddingBottom) + number(own.borderTopWidth) + number(own.borderBottomWidth);
  const chosen = slots(cards.length, width, height, gap, fitted.mw, fitted.mh, undefined, padX, padY);
  wall.style.setProperty('--cols', String(chosen.cols));
  wall.style.setProperty('--rows', String(chosen.rows));
  wall.style.setProperty('--mh', String(fitted.mh));
  const per = chosen.cols * chosen.rows;
  wall.dataset.per = String(per);
  wall.dataset.pageCount = String(chosen.pages);
  const states = cards.map((card) => card.dataset.state ?? '');
  // (critical, warning, no recent data: the three rungs a wall opens on; a card never moves for the others either)
  show(wall, keep && wall.dataset.page ? Number(wall.dataset.page) : worstPage(states, per, order().slice(0, 3)));
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

document.addEventListener('keydown', (event) => {
  if (event.altKey || event.ctrlKey || event.metaKey || (event.key !== 'PageDown' && event.key !== 'PageUp')) return;
  const wall = grid();
  if (!wall || !wall.dataset.pageCount) return;
  event.preventDefault();
  turn(event.key === 'PageDown' ? 1 : -1);
});
document.addEventListener('click', (event) => {
  const button = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-page-turn]') : null;
  if (button) turn(Number(button.dataset.pageTurn) || 0);
});
// A poll replaced, added or removed cards (and the band with its page indicator): the same page, laid out again.
document.addEventListener('poll:merged', () => lay(true));

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', relay);
else relay();
window.addEventListener('load', relay);
window.addEventListener('resize', relay);
document.addEventListener('fullscreenchange', relay);
