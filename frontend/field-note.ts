// A field's long reference note as a tooltip (registration/_field.html with `notes`: the calculator in the new look). The
// note is the server's help text, in the page and the input's description (aria-describedby) whether it is open or not;
// this script only shows and places it:
//   - the mouse resting on the field for a second, or the keyboard's focus on its control, shows it; leaving hides it;
//   - Esc closes it;
//   - the ⓘ button beside the label (a finger has no hover) opens and closes it, and keeps it open until pressed again;
//   - it stands under the control, or above it where there is no room below, and never past the window's edges.
// Without the script the note stays text under the field. No text of its own; position through the CSSOM (the
// Content-Security-Policy allows it, as uPlot's), never a style attribute.

export const NOTE_DELAY_MS = 1000;
const GAP = 6;
const EDGE = 8;

export interface Box { left: number; top: number; right: number; bottom: number }

/** Where a note of `width` × `height` stands for a control at `anchor`, in a window of `viewWidth` × `viewHeight`: under
 *  the control, else above it when it would leave the window below and fits above; never past the side edges. */
export function placeNote(anchor: Box, width: number, height: number, viewWidth: number, viewHeight: number): { left: number; top: number; above: boolean } {
  const below = anchor.bottom + GAP;
  const above = below + height > viewHeight - EDGE && anchor.top - GAP - height >= EDGE;
  const top = above ? anchor.top - GAP - height : below;
  const left = Math.max(EDGE, Math.min(anchor.left, viewWidth - EDGE - width));
  return { left, top, above };
}

function setUp(field: HTMLElement): void {
  if (field.dataset.noteReady) return;
  const note = field.querySelector<HTMLElement>('[data-note]');
  const control = field.querySelector<HTMLElement>('input, select, textarea');
  const toggle = field.querySelector<HTMLButtonElement>('[data-note-toggle]');
  if (!note || !control) return;
  field.dataset.noteReady = 'true';
  field.classList.add('is-noted');
  let timer: number | undefined;
  let pinned = false;
  let open = false;

  const place = (): void => {
    const at = control.getBoundingClientRect();
    const spot = placeNote(at, note.offsetWidth, note.offsetHeight, document.documentElement.clientWidth, window.innerHeight);
    note.style.setProperty('left', `${Math.round(spot.left)}px`);
    note.style.setProperty('top', `${Math.round(spot.top)}px`);
    note.dataset.side = spot.above ? 'above' : 'below';
  };
  const follow = (): void => { if (open) place(); };
  const show = (): void => {
    window.clearTimeout(timer);
    if (open) return;
    open = true;
    note.classList.add('is-open');
    toggle?.setAttribute('aria-expanded', 'true');
    place();
    window.addEventListener('scroll', follow, true);
    window.addEventListener('resize', follow);
  };
  const hide = (): void => {
    window.clearTimeout(timer);
    if (!open) return;
    open = false;
    pinned = false;
    note.classList.remove('is-open');
    toggle?.setAttribute('aria-expanded', 'false');
    window.removeEventListener('scroll', follow, true);
    window.removeEventListener('resize', follow);
  };

  field.addEventListener('pointerenter', (event) => {
    if (event.pointerType !== 'mouse' || open) return;
    timer = window.setTimeout(show, NOTE_DELAY_MS);
  });
  field.addEventListener('pointerleave', (event) => {
    if (event.pointerType !== 'mouse') return;
    window.clearTimeout(timer);
    if (!pinned && document.activeElement !== control) hide();
  });
  control.addEventListener('focus', show);
  control.addEventListener('blur', () => { if (!pinned) hide(); });
  field.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && open) {
      event.preventDefault();
      hide();
    }
  });
  toggle?.addEventListener('click', () => {
    if (open && pinned) {
      hide();
      return;
    }
    show();
    pinned = true;
  });
}

/** Every field with a note under `root` (the page, or what the dialog loads). */
export function initFieldNotes(root: ParentNode): void {
  root.querySelectorAll<HTMLElement>('[data-field-note]').forEach(setUp);
}
