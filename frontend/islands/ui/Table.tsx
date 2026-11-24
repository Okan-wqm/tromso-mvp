// A table (docs/design/system/README.md, Tables; static/css/ds.css, Table): a real <table class="ui-table"> in a frame
// that scrolls inside itself, keyboard-reachable (tabindex 0) and named (`label`). Heads on sunken, figures right-aligned
// on one line (numeric columns), a row's status as its 4 px edge (critical, warning), a voided row faded, and the row's
// actions in a column that stays at the right edge while the table scrolls. Every word (the heads, `actionsLabel`, the
// foot) comes from the server.
import type { ReactNode } from 'react';

import { Icon } from './Icon.js';

export interface Column<Row> {
  key: string;
  label: ReactNode;
  numeric?: boolean;
  /** the cell; without it, row[key] as text */
  render?: (row: Row) => ReactNode;
  /** the first column may head its row (<th scope="row">) */
  rowHeader?: boolean;
}

export interface TableProps<Row> {
  label: string;
  columns: Column<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  rowStatus?: (row: Row) => 'critical' | 'warning' | undefined;
  /** the words of a row's status, read before its first cell (with rowStatus: its glyph is drawn there too) */
  statusLabels?: { critical: string; warning: string };
  rowVoided?: (row: Row) => boolean;
  actions?: (row: Row) => ReactNode;
  /** the head of the actions column, for a screen reader ("Actions") */
  actionsLabel?: string;
  foot?: ReactNode;
}

function cellText<Row>(column: Column<Row>, row: Row): ReactNode {
  if (column.render) return column.render(row);
  const value = (row as Record<string, unknown>)[column.key];
  return value === null || value === undefined ? '' : String(value);
}

export function Table<Row>({ label, columns, rows, rowKey, rowStatus, statusLabels, rowVoided, actions, actionsLabel, foot }: TableProps<Row>) {
  return (
    <>
      <div className="ui-table-wrap" tabIndex={0} role="region" aria-label={label}>
        <table className="ui-table">
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column.key} scope="col" className={column.numeric ? 'num' : undefined}>{column.label}</th>
              ))}
              {actions ? <th scope="col" className="ui-actions"><span className="sr-only">{actionsLabel}</span></th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const status = rowStatus?.(row);
              return (
              <tr key={rowKey(row)} data-status={status} data-voided={rowVoided?.(row) ? '' : undefined}>
                {columns.map((column, index) => {
                  const marked = index === 0 && status ? (
                    <span className="ui-row-status"><Icon name={status === 'critical' ? 'octagon' : 'alert'} />
                      {statusLabels ? <span className="sr-only">{statusLabels[status]}: </span> : null}</span>
                  ) : null;
                  const content = <>{marked}{cellText(column, row)}</>;
                  const className = column.numeric ? 'num' : undefined;
                  return column.rowHeader
                    ? <th key={column.key} scope="row" className={className}>{content}</th>
                    : <td key={column.key} className={className}>{content}</td>;
                })}
                {actions ? <td className="ui-actions"><div className="ui-row-actions">{actions(row)}</div></td> : null}
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {foot ? <div className="ui-table-foot">{foot}</div> : null}
    </>
  );
}

/** A cell's main text with a sub-line under it (a code, a place, a time). */
export function CellLines({ main, sub, strong }: { main: ReactNode; sub?: ReactNode; strong?: boolean }) {
  return (
    <>
      <span className={strong ? 'ui-cell-strong' : undefined}>{main}</span>
      {sub ? <span className="ui-cell-sub">{sub}</span> : null}
    </>
  );
}
