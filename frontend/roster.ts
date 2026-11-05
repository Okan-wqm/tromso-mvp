// The Shift schedule's keyboard and paint (templates/hr/roster.html; the server renders the table, every cell and every
// text, and decides every plan: this code only moves focus and collects the cells to send).
//   table[data-roster]            the week: arrow keys move focus from a cell's link to the neighbouring cell's
//   td[data-cell="<employee>:<day>"]  a cell that can be planned
//   form[data-roster-paint]       hidden without this script. A button [data-shift="<shift id | off | clear>"] chooses what
//                                 to paint; while one is chosen a click on a cell selects it (instead of opening its plan);
//                                 sending the form posts the chosen shift and the selected cells (`cells`, one input each)
//                                 to the server's batch route, which checks and writes all of them or none.
//   [data-roster-clear]           a button that empties the selection

const SELECTED = 'is-selected';

function cellsOf(table: HTMLTableElement): HTMLTableCellElement[][] {
  return [...table.tBodies].flatMap((body) => [...body.rows]).map((row) =>
    [...row.cells].filter((cell) => cell.classList.contains('roster-cell')));
}

function focusIn(cell: HTMLTableCellElement | undefined): boolean {
  const target = cell?.querySelector<HTMLElement>('a[href], button');
  if (!target) return false;
  target.focus();
  return true;
}

function initKeys(table: HTMLTableElement): void {
  table.addEventListener('keydown', (event) => {
    const step: Record<string, [number, number]> = {
      ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0],
    };
    const move = step[event.key];
    const here = (event.target as HTMLElement | null)?.closest<HTMLTableCellElement>('td.roster-cell');
    if (!move || !here) return;
    const grid = cellsOf(table);
    const row = grid.findIndex((cells) => cells.includes(here));
    if (row < 0) return;
    const column = grid[row].indexOf(here);
    // The next cell in that direction that has something to focus (an empty cell of a person who is not the viewer's
    // that day has none), else stay where we are.
    let r = row + move[0];
    let c = column + move[1];
    while (grid[r]?.[c] !== undefined) {
      if (focusIn(grid[r][c])) {
        event.preventDefault();
        return;
      }
      r += move[0];
      c += move[1];
    }
  });
}

function initPaint(table: HTMLTableElement, form: HTMLFormElement): void {
  form.hidden = false;
  const chosen = form.querySelector<HTMLInputElement>('input[name="shift"]');
  const buttons = [...form.querySelectorAll<HTMLButtonElement>('button[data-shift]')];
  const selected = new Set<HTMLTableCellElement>();
  if (!chosen) return;

  const mark = (cell: HTMLTableCellElement, on: boolean): void => {
    cell.classList.toggle(SELECTED, on);
    cell.setAttribute('aria-selected', String(on));
    if (on) selected.add(cell);
    else selected.delete(cell);
  };
  const clear = (): void => [...selected].forEach((cell) => mark(cell, false));

  for (const button of buttons) {
    button.addEventListener('click', () => {
      const same = chosen.value === button.dataset.shift;
      chosen.value = same ? '' : (button.dataset.shift ?? '');
      for (const other of buttons) other.setAttribute('aria-pressed', String(other === button && !same));
      if (same) clear();
    });
  }
  form.querySelector<HTMLElement>('[data-roster-clear]')?.addEventListener('click', clear);

  // While something is chosen, a click on a cell selects it; the cell's own link (its plan in a dialog) is not followed.
  table.addEventListener('click', (event) => {
    if (!chosen.value) return;
    const cell = (event.target as HTMLElement).closest<HTMLTableCellElement>('td[data-cell]');
    if (!cell) return;
    event.preventDefault();
    event.stopPropagation();
    mark(cell, !selected.has(cell));
  }, true);

  form.addEventListener('submit', (event) => {
    form.querySelectorAll('input[name="cells"]').forEach((input) => input.remove());
    if (!chosen.value || selected.size === 0) {
      event.preventDefault();
      return;
    }
    for (const cell of selected) {
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'cells';
      input.value = cell.dataset.cell ?? '';
      form.append(input);
    }
  });
}

const table = document.querySelector<HTMLTableElement>('table[data-roster]');
if (table) {
  initKeys(table);
  const form = document.querySelector<HTMLFormElement>('form[data-roster-paint]');
  if (form) initPaint(table, form);
}
