// What the monitoring wall says aloud (Operations › Monitoring): when a card's state gets worse after the page was
// drawn, a sentence in a live region outside the polled grid (#monitor-announce holds the sentences and the state
// words, in the person's language; this code has none). A critical card goes to the assertive region, the others to the
// polite one; a first load, a better state, a card that comes into view and a card that goes say nothing, except that a
// card which loses sight of its water is always said: one whose values grow old (data-stale on the article: a critical
// value that is no longer fresh stays critical and is marked old) or that falls to "no recent data" from any state
// (F-244). At most one announcement per region in a window: what comes meanwhile is held, the latest goes out when the
// window has passed. The grid's merge (frontend/poll.ts) tells what it replaced with a `poll:merged` event; the state is
// the article's data-state. The grid's own notices (data-poll-state: not updated, gone, live again) are said too, in the
// assertive region (F-045).

/** The states in rising order (worst last) from the page's list (#monitor-announce data-states: monitoring/read.py
 *  STATES, worst first, the one list); empty is no state to rise from. */
export function order(spec: string): string[] {
  return spec.split(/\s+/).filter((key) => key && key !== 'empty').reverse();
}

const WINDOW = 5000;
// How a card's state is kept in the maps below: its data-state, and ':stale' when its data is old.
const STALE = ':stale';

export interface Rise {
  key: string;
  from: string;
  to: string;
  stale: boolean;   // the card's data is old now (a blind card always is)
}

function parse(value: string): { state: string; stale: boolean } {
  const state = value.endsWith(STALE) ? value.slice(0, -STALE.length) : value;
  return { state, stale: value.endsWith(STALE) || state === 'blind' };
}

/** The cards whose state is worse in `after` than in `before`, or whose data became old, in `after`'s order. */
export function rises(before: Map<string, string>, after: Map<string, string>, states: string[]): Rise[] {
  const found: Rise[] = [];
  for (const [key, value] of after) {
    const was = before.get(key);
    if (was === undefined) {
      continue;
    }
    const from = parse(was);
    const to = parse(value);
    if (!states.includes(from.state) || !states.includes(to.state)) {
      continue;
    }
    if (states.indexOf(to.state) > states.indexOf(from.state) || (to.stale && !from.stale)
        || (to.state === 'blind' && from.state !== 'blind')) {
      found.push({ key, from: from.state, to: to.state, stale: to.stale });
    }
  }
  return found;
}

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key]) : whole));
}

function word(rise: Rise, words: Record<string, string>, staleWord: string): string {
  const said = words[rise.to] ?? rise.to;
  return rise.stale && rise.to !== 'blind' && staleWord ? `${said}, ${staleWord}` : said;
}

function said(found: Rise[], unitOf: (key: string) => string, words: Record<string, string>, worse: string,
              more: string, staleWord: string): string {
  if (!found.length) {
    return '';
  }
  const first = fill(worse, { unit: unitOf(found[0].key), state: word(found[0], words, staleWord) });
  return found.length > 1 ? `${first} ${fill(more, { count: found.length - 1 })}` : first;
}

/** {assertive, polite}: the critical rises, and the others, each as its first in full and the rest as a count; a card
 *  whose data is old says so after its state word (`staleWord`). */
export function sentences(found: Rise[], unitOf: (key: string) => string, words: Record<string, string>, worse: string,
                          more: string, staleWord = ''): { assertive: string; polite: string } {
  return {
    assertive: said(found.filter((rise) => rise.to === 'critical'), unitOf, words, worse, more, staleWord),
    polite: said(found.filter((rise) => rise.to !== 'critical'), unitOf, words, worse, more, staleWord),
  };
}

/** What the grid says when its poll state changes: not updated (stale), gone, or live again after either; nothing on
 *  the first load or when nothing changed. */
export function pollNotice(previous: string | undefined, now: string,
                           texts: { stale: string; gone: string; live: string }): string {
  if (previous === undefined || previous === now) {
    return '';
  }
  if (now === 'stale') return texts.stale;
  if (now === 'gone') return texts.gone;
  return now === 'live' && (previous === 'stale' || previous === 'gone') ? texts.live : '';
}

/** One announcement per window; what comes meanwhile is held (the latest wins) and goes out with the next take after
 *  the window. */
export class Limiter {
  private last = Number.NEGATIVE_INFINITY;
  private held = '';

  constructor(private readonly window: number) {}

  take(text: string, now: number): string | null {
    if (text) {
      this.held = text;
    }
    if (!this.held || now - this.last < this.window) {
      return null;
    }
    const out = this.held;
    this.held = '';
    this.last = now;
    return out;
  }

  pending(): string {
    return this.held;
  }
}

// ---- the page ------------------------------------------------------------------------------------------------------
function states(nodes: Iterable<Element>): Map<string, string> {
  const found = new Map<string, string>();
  for (const node of nodes) {
    const key = node.getAttribute('data-key');
    const state = node.getAttribute('data-state');
    if (key !== null && state !== null) {
      found.set(key, node.hasAttribute('data-stale') ? `${state}${STALE}` : state);
    }
  }
  return found;
}

function start(): void {
  const holder = document.getElementById('monitor-announce');
  const grid = document.querySelector<HTMLElement>('.monitor-grid[data-poll]');
  if (holder === null || grid === null) {
    return;
  }
  const regions = {
    assertive: holder.querySelector<HTMLElement>('[data-announcer][aria-live="assertive"]'),
    polite: holder.querySelector<HTMLElement>('[data-announcer][aria-live="polite"]'),
  };
  const rising = order(holder.dataset.states ?? '');
  const words: Record<string, string> = {};
  for (const state of rising) {
    const word = holder.getAttribute(`data-state-${state}`);
    if (word) {
      words[state] = word;
    }
  }
  const limiters = { assertive: new Limiter(WINDOW), polite: new Limiter(WINDOW) };
  const speak = (region: 'assertive' | 'polite', text: string): void => {
    const out = limiters[region].take(text, Date.now());
    const node = regions[region];
    if (out !== null && node !== null) {
      node.textContent = out;
    }
    if (limiters[region].pending()) {
      window.setTimeout(() => speak(region, ''), WINDOW);
    }
  };
  grid.addEventListener('poll:merged', (event) => {
    const detail = (event as CustomEvent<{ replaced: { old: Element; node: Element }[] }>).detail;
    const before = states(detail.replaced.map((each) => each.old));
    const after = states(detail.replaced.map((each) => each.node));
    const unitOf = (key: string): string =>
      detail.replaced.find((each) => each.node.getAttribute('data-key') === key)?.node.querySelector('h3')?.textContent
        ?.trim() ?? key;
    const found = sentences(rises(before, after, rising), unitOf, words, holder.dataset.announceWorse ?? '',
                            holder.dataset.announceMore ?? '', holder.dataset.staleWord ?? '');
    if (found.assertive) {
      speak('assertive', found.assertive);
    }
    if (found.polite) {
      speak('polite', found.polite);
    }
  });
  // The grid's own notices (poll.ts sets data-poll-state): said in the assertive region, in the page's words.
  let pollState = grid.dataset.pollState;
  new MutationObserver(() => {
    const now = grid.dataset.pollState ?? '';
    const text = pollNotice(pollState, now, { stale: grid.dataset.staleText ?? '', gone: grid.dataset.goneText ?? '',
                                             live: grid.dataset.updatedText ?? '' });
    pollState = now;
    if (text) {
      speak('assertive', text);
    }
  }).observe(grid, { attributes: true, attributeFilter: ['data-poll-state'] });
}

if (typeof document !== 'undefined') {
  start();
}
