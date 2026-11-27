// The Big card's Deffeyes chart on a phone (the new look: templates/monitoring/widgets/_chart.html, static/css/
// monitor-next.css): on a card narrower than its words need, the picture keeps the width at which the server's labels
// stand apart and scrolls sideways in its own frame (`.monitor-chart[tabindex]`). This puts the water's mark in sight
// when a frame is drawn: the frame is scrolled so the mark stands in its middle (review 2, N10: in the full-scale view
// the mark could lie in the hidden part), once per frame the server drew, on the page's first paint and after every
// poll that brings a new card (poll.ts `poll:merged`), never again on a frame the person has scrolled. A frame that
// does not scroll (the desk, the pane, a wall) is left alone. This code has no text of its own.

/** Where to scroll a frame `frame` px wide over a picture `content` px wide so the point `mark` px from the picture's
 *  left edge stands in the frame's middle: never before the picture's start nor past its end. */
export function centred(frame: number, content: number, mark: number): number {
  const most = Math.max(0, content - frame);
  return Math.round(Math.min(most, Math.max(0, mark - frame / 2)));
}

/** Scrolls each chart frame under `root` that scrolls, and has not been placed yet, to its water's mark. */
export function place(root: ParentNode): void {
  for (const frame of Array.from(root.querySelectorAll<HTMLElement>('.monitor-chart[tabindex]'))) {
    if (frame.dataset.placed === '1' || frame.scrollWidth <= frame.clientWidth + 1) continue;
    const mark = frame.querySelector('.chart-water');
    if (!mark) continue;
    const box = frame.getBoundingClientRect();
    const at = mark.getBoundingClientRect();
    frame.scrollLeft = centred(frame.clientWidth, frame.scrollWidth, at.left + at.width / 2 - box.left + frame.scrollLeft);
    frame.dataset.placed = '1';
  }
}

if (typeof document !== 'undefined') {
  place(document);
  document.addEventListener('poll:merged', (event) => { place(event.target instanceof Element ? event.target : document); });
}
