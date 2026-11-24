// Lists (static/css/ds.css, Lists; the design's "list" and "audit" blocks): the rows of a plate on hairlines. A list item
// has its main line, a sub-line, a meta at the right (a time) and a chip, and a status edge; an activity entry heads with
// its action, a critical chip, the record and who and when. Every word comes from the server.
import type { ReactNode } from 'react';

export function List({ children, ordered, label }: { children: ReactNode; ordered?: boolean; label?: string | undefined }) {
  return ordered
    ? <ol className="ui-list" role="list" aria-label={label}>{children}</ol>
    : <ul className="ui-list" role="list" aria-label={label}>{children}</ul>;
}

export interface ListItemProps {
  main: ReactNode;
  sub?: ReactNode;
  meta?: ReactNode;
  chip?: ReactNode;
  status?: 'critical' | 'warning' | undefined;
}

export function ListItem({ main, sub, meta, chip, status }: ListItemProps) {
  return (
    <li className="ui-list-item" data-status={status}>
      <span className="ui-list-main">
        <span>{main}</span>
        {sub ? <span className="ui-cell-sub">{sub}</span> : null}
      </span>
      {meta ? <span className="ui-list-meta">{meta}</span> : null}
      {chip}
    </li>
  );
}

export interface AuditItemProps {
  action: ReactNode;
  /** the critical chip, when the entry is critical */
  critical?: ReactNode;
  record: ReactNode;
  /** "by <strong>name</strong> · when", as the server's sentence puts it */
  who: ReactNode;
  status?: 'critical' | undefined;
  children?: ReactNode;
}

export function AuditItem({ action, critical, record, who, status, children }: AuditItemProps) {
  return (
    <li className="ui-list-item ui-audit-item" data-status={status}>
      <span className="ui-audit-head">
        <strong className="ui-audit-action">{action}</strong>
        {critical}
        <span className="ui-audit-record">{record}</span>
        <span className="ui-audit-who">{who}</span>
      </span>
      {children}
    </li>
  );
}
