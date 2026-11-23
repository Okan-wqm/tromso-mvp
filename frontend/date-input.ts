// The shared date box (core.widgets.DayInput, MomentInput: input[data-date-input="day|moment"]): a text box, never the
// browser's own date box, which says a date in the browser's language (11/06/2026 09:19 AM). A date is typed and shown the
// European way in every language (owner rule): dd.mm.yyyy, and HH:MM on the 24-hour clock for a moment; when the box is
// left, a date in that shape (or ISO) is put with its leading zeros (6.11.2026 9:19 -> 06.11.2026 09:19). Any other shape
// (a slash, a dash, a two-digit year) is never reinterpreted: it stays as typed and the server refuses it with the shape it
// wants (core/dates.py). A moment without its time stays as typed too. No library, no picker.

const pad = (value: number): string => String(value).padStart(2, '0');

function day(text: string): { d: number; m: number; y: number } | null {
  let found = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(text);
  let d: number, m: number, y: number;
  if (found) {
    [d, m, y] = [Number(found[1]), Number(found[2]), Number(found[3])];
  } else if ((found = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text))) {             // ISO, as an address carries it
    [y, m, d] = [Number(found[1]), Number(found[2]), Number(found[3])];
  } else {
    return null;
  }
  const probe = new Date(Date.UTC(y, m - 1, d));
  if (probe.getUTCFullYear() !== y || probe.getUTCMonth() !== m - 1 || probe.getUTCDate() !== d) return null;
  return { d, m, y };
}

function clock(text: string): string | null {
  const found = /^(\d{1,2}):(\d{2})$/.exec(text);
  if (!found) return null;
  const [hours, minutes] = [Number(found[1]), Number(found[2])];
  return hours < 24 && minutes < 60 ? `${pad(hours)}:${pad(minutes)}` : null;
}

/** What `typed` is put as: dd.mm.yyyy, with ` HH:MM` when `moment` and a time was typed; else as typed (trimmed). */
export function tidy(typed: string, moment: boolean): string {
  const text = typed.trim();
  const [datePart, ...rest] = text.split(/[ T]+/);
  const timePart = rest.join(' ');
  if (rest.length > 1 || (timePart && !moment) || (moment && !timePart)) return text;
  const date = day(datePart);
  if (!date) return text;
  const shown = `${pad(date.d)}.${pad(date.m)}.${date.y}`;
  if (!timePart) return shown;
  const time = clock(timePart);
  return time ? `${shown} ${time}` : text;
}

export function initDateInputs(root: ParentNode): void {
  for (const input of root.querySelectorAll<HTMLInputElement>('input[data-date-input]')) {
    if (input.dataset.dateReady) continue;
    input.dataset.dateReady = '1';
    input.addEventListener('change', () => {          // capture: before a filter's autosubmit reads the value
      input.value = tidy(input.value, input.dataset.dateInput === 'moment');
    }, true);
  }
}
