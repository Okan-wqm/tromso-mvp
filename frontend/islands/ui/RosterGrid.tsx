// A week roster (static/css/ds.css, Roster): a person per row, a day per column, each cell what is planned (a shift's code,
// planned off, on leave), a holiday's name and the rules' findings in words; the row's planned hours at the end. Every
// cell, word and address comes from the server (hr.read.week); the server decides every plan.
//
// Keyboard: the arrow keys move from a cell's control to the next cell in that direction that has one (Home and End to the
// row's first and last), as the classic schedule does. Paint (when the person may plan): choose a shift, Off or Clear in
// the paint bar (toggle buttons, aria-pressed); the plannable cells then become toggle buttons that Space or Enter (or a
// click) selects; "Apply to the selected days" posts the choice and the selected cells to the server's batch route
// (`paint.action`, with the page's CSRF token), which checks and writes all of them or none. Choosing the same paint
// again, or "Clear selection", empties the selection.
import { useRef, useState, type KeyboardEvent, type ReactNode } from 'react';

import { Button } from './Button.js';
import { Icon } from './Icon.js';

export interface RosterDay { key: string; head: string; sub: string }

export interface RosterCell {
  /** "<employee>:<yyyy-mm-dd>", what the batch route takes; null for a day the viewer does not reach the person on */
  key: string | null;
  /** what is planned: a shift (its code, in its tone 1 to 8), planned off, or on leave; its words and its title */
  chip?: { kind: 'shift' | 'off' | 'leave'; text: string; title?: string | null; tone?: number | null } | null;
  /** the plan's own page (editing it), or null */
  href?: string | null;
  /** an empty plannable day: its new plan's page and the link's words ("Plan this day") */
  add?: { href: string; label: string } | null;
  holiday?: string | null;
  /** the rules' findings for the day, in words; `blocks` when one refuses the plan */
  finding?: string | null;
  blocks?: boolean;
}

export interface RosterRow {
  key: string;
  name: string;
  sub: string;
  hours: string;
  /** the week's own finding (more than the standard week), in words */
  hoursFinding?: string | null;
  cells: RosterCell[];
}

export interface RosterPaint {
  action: string;
  csrfToken: string;
  /** where the server sends the person back (the page with its week and filters) */
  next: string;
  label: string;
  choices: { value: string; label: string; title?: string | null; kind?: 'shift' | 'off' | 'clear'; tone?: number | null }[];
  clearSelection: string;
  apply: string;
}

export interface RosterGridProps {
  label: string;
  employeeHead: string;
  hoursHead: string;
  days: RosterDay[];
  rows: RosterRow[];
  paint?: RosterPaint | null;
  /** what stands between the paint bar and the week (the page's search and filters, its count), as the design orders it */
  children?: ReactNode;
}

const MOVES: Record<string, [number, number]> = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] };

export function RosterGrid({ label, employeeHead, hoursHead, days, rows, paint, children }: RosterGridProps) {
  const [chosen, setChosen] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const table = useRef<HTMLTableElement>(null);
  const painting = Boolean(paint && chosen);

  const choose = (value: string) => {
    if (value === chosen) {
      setChosen('');
      setSelected([]);
    } else {
      setChosen(value);
    }
  };
  const toggle = (key: string) => setSelected((now) => (now.includes(key) ? now.filter((each) => each !== key) : [...now, key]));

  // Arrow keys: the next cell in that direction that has a control (a cell of a day the viewer does not reach has none).
  const move = (event: KeyboardEvent<HTMLTableElement>) => {
    const here = (event.target as HTMLElement).closest('td[data-roster-cell]');
    if (!here || !table.current) return;
    const grid = [...table.current.tBodies[0]?.rows ?? []].map((row) => [...row.querySelectorAll('td[data-roster-cell]')]);
    const r0 = grid.findIndex((cells) => cells.includes(here));
    const c0 = grid[r0]?.indexOf(here) ?? -1;
    const focus = (cell: Element | undefined) => {
      const target = cell?.querySelector<HTMLElement>('a[href], button');
      if (!target) return false;
      target.focus();
      event.preventDefault();
      return true;
    };
    if (event.key === 'Home' || event.key === 'End') {
      const cells = event.key === 'Home' ? grid[r0] ?? [] : [...grid[r0] ?? []].reverse();
      cells.some((cell) => focus(cell));
      return;
    }
    const step = MOVES[event.key];
    if (!step) return;
    for (let r = r0 + step[0], c = c0 + step[1]; grid[r]?.[c] !== undefined; r += step[0], c += step[1]) {
      if (focus(grid[r]?.[c])) return;
    }
  };

  const content = (row: RosterRow, cell: RosterCell, day: RosterDay) => {
    const chip = cell.chip ? <span className="ui-roster-plan" data-kind={cell.chip.kind} data-tone={cell.chip.tone ?? undefined}>{cell.chip.text}</span> : null;
    if (painting && cell.key) {
      const on = selected.includes(cell.key);
      return (
        <button type="button" className="ui-roster-pick" aria-pressed={on}
          aria-label={`${row.name}, ${[day.head, day.sub].filter(Boolean).join(' ')}${cell.chip ? `: ${cell.chip.text}` : ''}`}
          onClick={() => toggle(cell.key as string)}>
          {chip ?? <span aria-hidden="true">·</span>}
        </button>
      );
    }
    if (cell.href) return <a className="ui-roster-link" href={cell.href} title={cell.chip?.title ?? undefined}>{chip}</a>;
    if (chip) return <span title={cell.chip?.title ?? undefined}>{chip}</span>;
    if (cell.add) return <a className="ui-roster-add" href={cell.add.href} aria-label={cell.add.label} title={cell.add.label}><Icon name="plus" /></a>;
    return null;
  };

  return (
    <div className="ui-roster">
      {paint ? (
        <form method="post" action={paint.action} className="ui-roster-paint">
          <input type="hidden" name="csrfmiddlewaretoken" value={paint.csrfToken} />
          <input type="hidden" name="next" value={paint.next} />
          <input type="hidden" name="shift" value={chosen} />
          {selected.map((key) => <input key={key} type="hidden" name="cells" value={key} />)}
          <div role="group" aria-label={paint.label} className="ui-roster-choices">
            <span className="ui-cell-sub" aria-hidden="true">{paint.label}</span>
            {paint.choices.map((choice) => (
              <button key={choice.value} type="button" className="ui-roster-choice" aria-pressed={chosen === choice.value}
                data-kind={choice.kind ?? 'shift'} data-tone={choice.tone ?? undefined}
                title={choice.title ?? undefined} onClick={() => choose(choice.value)}>{choice.label}</button>
            ))}
          </div>
          <Button variant="link" isDisabled={!selected.length} onPress={() => setSelected([])}>{paint.clearSelection}</Button>
          <Button type="submit" variant="primary" isDisabled={!chosen || !selected.length}>{paint.apply}</Button>
        </form>
      ) : null}
      {children}
      <div className="ui-table-wrap" tabIndex={0} role="region" aria-label={label}>
        <table className="ui-table ui-roster-table" ref={table} onKeyDown={move}>
          <thead>
            <tr>
              <th scope="col">{employeeHead}</th>
              {days.map((day) => <th key={day.key} scope="col">{day.head}{day.sub ? <span className="ui-cell-sub">{day.sub}</span> : null}</th>)}
              <th scope="col" className="num">{hoursHead}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <th scope="row"><span className="ui-cell-strong">{row.name}</span><span className="ui-cell-sub">{row.sub}</span></th>
                {row.cells.map((cell, index) => {
                  const day = days[index] as RosterDay;
                  return (
                    <td key={day.key} data-roster-cell="" data-finding={cell.blocks ? 'block' : cell.finding ? 'warning' : undefined}
                      data-selected={cell.key && selected.includes(cell.key) ? '' : undefined}>
                      {cell.key ? content(row, cell, day) : null}
                      {cell.key && cell.holiday ? <span className="ui-cell-sub">{cell.holiday}</span> : null}
                      {cell.key && cell.finding ? (
                        <span className="ui-roster-finding" title={cell.finding}><Icon name={cell.blocks ? 'octagon' : 'alert'} /><span className="ui-cell-sub">{cell.finding}</span></span>
                      ) : null}
                    </td>
                  );
                })}
                <td className="num">{row.hours}{row.hoursFinding ? <span className="ui-roster-finding"><Icon name="alert" /><span className="ui-cell-sub">{row.hoursFinding}</span></span> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
