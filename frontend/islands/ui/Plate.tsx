// A plate (static/css/ds.css, Plate): the design's top-level panel, framed by a hairline (and, in the new look, the
// registration marks), with a head: its title, a badge, the meta ("Worked out 23.11.2026, 13:42 · Europe/Oslo") and a
// link to the page the figures come from. A safety sentence may stand under the head; the body is the plate's own
// (tiles, a table, a list). Plates stand in Plates, a 12-column grid: span 4, 6, 8 or 12.
import type { ReactNode } from 'react';

import { Icon } from './Icon.js';

export type Span = 4 | 6 | 8 | 12;

export function Plates({ children }: { children: ReactNode }) {
  return <div className="ui-plates">{children}</div>;
}

export interface PlateProps {
  title?: ReactNode;
  meta?: ReactNode;
  badge?: ReactNode;
  link?: { href: string; label: string };
  /** a sentence that must stay in sight ("Nothing is sent yet: …"), drawn as a warning notice */
  safety?: ReactNode;
  span?: Span;
  /** what the plate is, for a screen reader, when it has no title */
  label?: string;
  foot?: ReactNode;
  children?: ReactNode;
}

export function Plate({ title, meta, badge, link, safety, span = 12, label, foot, children }: PlateProps) {
  return (
    <section className="ui-plate" data-span={String(span)} aria-label={title ? undefined : label}>
      {title || link ? (
        <div className="ui-plate-head">
          {title ? <h2>{title}</h2> : null}
          {badge}
          {meta ? <span className="ui-plate-meta">{meta}</span> : null}
          {link ? <a className="ui-plate-link" href={link.href}>{link.label} <span aria-hidden="true">→</span></a> : null}
        </div>
      ) : null}
      {safety ? (
        <p className="ui-notice" data-tone="warning">
          <Icon name="alert" />
          <span className="ui-notice-body">{safety}</span>
        </p>
      ) : null}
      {children}
      {foot ? <div className="ui-table-foot">{foot}</div> : null}
    </section>
  );
}
