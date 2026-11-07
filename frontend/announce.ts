// What the monitoring wall says aloud (Operations › Monitoring): when a card's state gets worse after the page was
// drawn, a sentence in a live region outside the polled grid (#monitor-announce holds the sentences and the state
// words, in the person's language; this code has none). A critical card goes to the assertive region, the others to the
// polite one; a first load, a better state, a card that comes into view and a card that goes say nothing. At most one
// announcement per region in a window: what comes meanwhile is held, the latest goes out when the window has passed.
// The grid's merge (frontend/poll.ts) tells what it replaced with a `poll:merged` event; the state is the article's
// data-state. The wall's connection going stale or gone is said too, assertively, in the banner's words.

// Worst last; empty is no state to rise from.
const ORDER = ['ok', 'note', 'blind', 'warning', 'critical'];
const WINDOW = 5000;

export interface Rise {
  key: string;
  from: string;
  to: string;
}

/** The cards whose state is worse in `after` than in `before`, in `after`'s order. */
export function rises(before: Map<string, string>, after: Map<string, string>): Rise[] {
  const found: Rise[] = [];
  for (const [key, to] of after) {
    const from = before.get(key);
    if (from === undefined || !ORDER.includes(from) || !ORDER.includes(to)) {
      continue;
    }
    if (ORDER.indexOf(to) > ORDER.indexOf(from)) {
      found.push({ key, from, to });
    }
  }
  return found;
}

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key]) : whole));
}

function said(found: Rise[], unitOf: (key: string) => string, words: Record<string, string>, worse: string,
              more: string): string {
  if (!found.length) {
    return '';
  }
  const first = fill(worse, { unit: unitOf(found[0].key), state: words[found[0].to] ?? found[0].to });
  return found.length > 1 ? `${first} ${fill(more, { count: found.length - 1 })}` : first;
}

/** {assertive, polite}: the critical rises, and the others, each as its first in full and the rest as a count. */
export function sentences(found: Rise[], unitOf: (key: string) => string, words: Record<string, string>, worse: string,
                          more: string): { assertive: string; polite: string } {
  return {
    assertive: said(found.filter((rise) => rise.to === 'critical'), unitOf, words, worse, more),
    polite: said(found.filter((rise) => rise.to !== 'critical'), unitOf, words, worse, more),
  };
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

/** What is said when the wall's connection state (the grid's data-poll-state, set by frontend/poll.ts) changes: the
 *  banner's own text when it becomes stale or gone, nothing when it stays or comes back (the cards say the rest). */
export function connectionSentence(from: string | null, to: string | null,
                                   texts: { stale: string; gone: string }): string | null {
  if (from === to || (to !== 'stale' && to !== 'gone')) {
    return null;
  }
  return texts[to] || null;
}

// ---- the page ------------------------------------------------------------------------------------------------------
function states(nodes: Iterable<Element>): Map<string, string> {
  const found = new Map<string, string>();
  for (const node of nodes) {
    const key = node.getAttribute('data-key');
    const state = node.getAttribute('data-state');
    if (key !== null && state !== null) {
      found.set(key, state);
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
  const words: Record<string, string> = {};
  for (const state of ORDER) {
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
  // The stale and gone banner is CSS content (monitor.css ::before), which a screen reader does not hear: say it too.
  new MutationObserver((changes) => {
    for (const change of changes) {
      const text = connectionSentence(change.oldValue, grid.dataset.pollState ?? null,
                                      { stale: grid.dataset.staleText ?? '', gone: grid.dataset.goneText ?? '' });
      if (text !== null) {
        speak('assertive', text);
      }
    }
  }).observe(grid, { attributes: true, attributeFilter: ['data-poll-state'], attributeOldValue: true });
  grid.addEventListener('poll:merged', (event) => {
    const detail = (event as CustomEvent<{ replaced: { old: Element; node: Element }[] }>).detail;
    const before = states(detail.replaced.map((each) => each.old));
    const after = states(detail.replaced.map((each) => each.node));
    const unitOf = (key: string): string =>
      detail.replaced.find((each) => each.node.getAttribute('data-key') === key)?.node.querySelector('h3')?.textContent
        ?.trim() ?? key;
    const found = sentences(rises(before, after), unitOf, words, holder.dataset.announceWorse ?? '',
                            holder.dataset.announceMore ?? '');
    if (found.assertive) {
      speak('assertive', found.assertive);
    }
    if (found.polite) {
      speak('polite', found.polite);
    }
  });
}

if (typeof document !== 'undefined') {
  start();
}
