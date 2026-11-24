// The new look's status strip (templates/app_base.html, core/ui.py strip): frontend/poll.ts asks for it again every 30 s;
// this says a RISE of its alarms item aloud (WCAG 4.1.3), never the item itself on every answer: from nothing to a
// warning, or to critical, in the live regions the server put beside the strip (a critical in the assertive one). The
// first answer after the page was drawn is the first load and says nothing; a fall says nothing (the screen shows it).
// The words are the server's, already translated: the item's own text.

const RANK: Record<string, number> = { '': 0, warning: 1, critical: 2 };

/** The status of a strip's alarms item ('' when it says nothing is wrong), or null when there is no item yet. */
export function statusOf(strip: ParentNode): string | null {
  const item = strip.querySelector<HTMLElement>('[data-strip="alarms"]');
  if (!item) return null;
  return item.dataset.status ?? '';
}

/** Whether going from `before` to `after` is a rise to say: both known, and `after` worse. */
export function rose(before: string | null, after: string | null): boolean {
  if (before === null || after === null) return false;
  return (RANK[after] ?? 0) > (RANK[before] ?? 0);
}

export function watchStrip(strip: HTMLElement, doc: Document = document): MutationObserver {
  let before: string | null = strip.dataset.pollState === 'loading' ? null : statusOf(strip);
  const observer = new MutationObserver(() => {
    if (strip.dataset.pollState === 'loading') return;
    const after = statusOf(strip);
    if (rose(before, after)) {
      const region = doc.getElementById((after === 'critical' ? strip.dataset.stripAlert : strip.dataset.stripSaid) ?? '');
      const text = strip.querySelector('[data-strip="alarms"]')?.textContent?.trim() ?? '';
      if (region) region.textContent = text;
    }
    before = after ?? before;
  });
  observer.observe(strip, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-poll-state'] });
  return observer;
}

if (typeof document !== 'undefined') {
  document.querySelectorAll<HTMLElement>('.ui-strip[data-strip-said]').forEach((strip) => { watchStrip(strip); });
}
