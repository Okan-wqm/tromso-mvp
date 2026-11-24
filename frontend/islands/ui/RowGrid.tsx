// A list of rows in a form (the design's drawer rows; static/css/ds.css, "A list of rows in a form"): a Django formset as
// one table, whatever the list (a site's contacts, a feeder's calibrations, a feeding table's bands, an experiment's
// groups). The management form is kept true (TOTAL_FORMS counts the rows drawn), each row carries its hidden fields and
// its errors, a row may have its own heading (a replicate's name), a row added from the formset's empty form takes the
// focus, and a row's Remove box (its DELETE field) is drawn as the design's x button, the row fading while it is ticked.
// The caller draws each cell's fields (frontend/islands/pages/RecordForm.tsx with the form layer's field components);
// every word comes from the server.
import { type ReactNode, useEffect, useRef, useState } from 'react';

import { Icon } from './Icon.js';
import { Notice } from './States.js';

export interface GridRowOf {
  /** the row's own heading (a replicate's name), drawn as its row header */
  head: string | null;
  hidden: { name: string; value: string }[];
  errors: string[];
  cells: ReactNode[];
}

export interface RowGridProps {
  /** the formset's prefix: its management fields are <prefix>-TOTAL_FORMS, -INITIAL_FORMS, ... */
  prefix: string;
  management: { name: string; value: string }[];
  /** the region's name for a screen reader (the list's legend) */
  legend: string;
  /** the heads of the cells' columns; a last cell without a head (the Remove box) gets `removeLabel`, read only */
  columns: string[];
  removeLabel?: string | undefined;
  rows: GridRowOf[];
  /** a row added at a position (the formset's empty form, its __prefix__ put to `index`); null: rows are not added here */
  newRow: ((index: number) => GridRowOf) | null;
  addLabel: string | null;
  addDisabled?: boolean | undefined;
  emptyText: string;
  errors: string[];
}

/** A row's Remove box as the design's remove button: the formset's DELETE box, its name for a screen reader. */
export function RemoveBox({ name, label, defaultChecked }: { name: string; label: string; defaultChecked?: boolean | undefined }) {
  return (
    <label className="icon-button icon-button-danger ui-row-remove" title={label}>
      <input type="checkbox" className="sr-only" name={name} defaultChecked={defaultChecked} />
      <Icon name="x" /><span className="sr-only">{label}</span>
    </label>
  );
}

export function RowGrid({ prefix, management, legend, columns, removeLabel, rows, newRow, addLabel, addDisabled, emptyText, errors }: RowGridProps) {
  const [added, setAdded] = useState(0);
  const body = useRef<HTMLTableSectionElement>(null);
  const grown = useRef(false);
  useEffect(() => {
    if (!grown.current) return;
    grown.current = false;
    body.current?.lastElementChild?.querySelector<HTMLElement>('input:not([type="hidden"]), select, textarea')?.focus();
  }, [added]);
  const all = [...rows, ...(newRow ? Array.from({ length: added }, (_each, index) => newRow(rows.length + index)) : [])];
  const total = `${prefix}-TOTAL_FORMS`;
  const first = all[0];
  const width = first ? first.cells.length + (first.head !== null ? 1 : 0) : columns.length;
  return (
    <div className="ui-form-grid-rows" data-wide="">
      {errors.length ? <Notice tone="critical"><ul className="errorlist">{errors.map((each) => <li key={each}>{each}</li>)}</ul></Notice> : null}
      {management.map((each) => <input key={each.name} type="hidden" name={each.name} value={each.name === total ? String(all.length) : each.value} />)}
      {all.length ? (
        <div className="ui-table-wrap" tabIndex={0} role="region" aria-label={legend}>
          <table className="ui-table grid-table">
            <thead><tr>{columns.map((column) => <th key={column} scope="col">{column}</th>)}
              {columns.length < width ? <th scope="col"><span className="sr-only">{removeLabel}</span></th> : null}</tr></thead>
            <tbody ref={body}>
              {all.map((row, index) => {
                const hidden = row.hidden.map((each) => <input key={each.name} type="hidden" name={each.name} value={each.value} />);
                return (
                  <tr key={`row-${index}`}>
                    {row.head !== null ? <th scope="row">{hidden}{row.head}</th> : null}
                    {row.cells.map((cell, at) => (
                      <td key={at}>
                        {at === 0 && row.head === null ? hidden : null}
                        {at === 0 && row.errors.length ? <ul className="errorlist row-error">{row.errors.map((each) => <li key={each}>{each}</li>)}</ul> : null}
                        {cell}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (emptyText ? <p className="contact-empty">{emptyText}</p> : null)}
      {addLabel !== null ? (
        <div className="ui-form-actions">
          <button type="button" className="ui-btn" disabled={Boolean(addDisabled) || !newRow}
            onClick={() => { grown.current = true; setAdded(added + 1); }}><Icon name="plus" />{addLabel}</button>
        </div>
      ) : null}
    </div>
  );
}
