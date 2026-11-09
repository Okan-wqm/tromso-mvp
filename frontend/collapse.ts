// A folded part of the rail (<details class="rail-collapse" data-collapse="<key>">, Setup; core.navigation.Section
// collapsed): folded the first time, then as the person left it, on every page; the page it holds always opens it
// (the server writes `open data-current` there). The choice is kept in the browser, per part.
const PREFIX = 'suderra.collapse.';

/** Whether the part is open: always on a page it holds, else as saved ('open' or 'closed'), else folded. */
export function opened(saved: string | null, holdsCurrent: boolean): boolean {
  return holdsCurrent || saved === 'open';
}

function read(key: string): string | null {
  try { return localStorage.getItem(PREFIX + key); } catch { return null; }
}

function write(key: string, value: string): void {
  try { localStorage.setItem(PREFIX + key, value); } catch { /* storage blocked: it folds again next time */ }
}

/** Applies the saved choice to every folded part of `root` and keeps the person's next one. */
export function bindCollapses(root: ParentNode): void {
  for (const part of root.querySelectorAll<HTMLDetailsElement>('details.rail-collapse[data-collapse]')) {
    const key = part.dataset.collapse ?? '';
    const holds = part.hasAttribute('data-current');
    part.open = opened(read(key), holds);
    // On a page it holds it is open by the page, not by the person: nothing is kept from there (a parsed `open` fires a
    // toggle too).
    if (!holds) part.addEventListener('toggle', () => write(key, part.open ? 'open' : 'closed'));
  }
}
