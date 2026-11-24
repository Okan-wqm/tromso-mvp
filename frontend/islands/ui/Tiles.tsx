// Stat tiles (static/css/ds.css, Tile; templates/_metric_card.html draws the same tile on the server): one figure people
// read at a glance, its label, a sub-line and its source and time; the whole tile is the link to where the figure comes
// from. Grey by default; only an abnormal figure (status critical or warning) gets its 4 px edge, its glyph before the
// label and the status's text colour, and `statusLabel` says it in words for a screen reader.
import type { ReactNode } from 'react';

import { Icon } from './Icon.js';

export function Tiles({ children, size, label }: { children: ReactNode; size?: 'small'; label?: string }) {
  return <div className="ui-tiles" data-size={size} role={label ? 'group' : undefined} aria-label={label}>{children}</div>;
}

export interface TileProps {
  label: ReactNode;
  figure: ReactNode;
  sub?: ReactNode;
  sub2?: ReactNode;
  source?: ReactNode;
  status?: 'critical' | 'warning';
  /** the status in words ("Critical"), read before the label by a screen reader */
  statusLabel?: string;
  href?: string;
}

export function Tile({ label, figure, sub, sub2, source, status, statusLabel, href }: TileProps) {
  const body = (
    <>
      <span className="ui-tile-label">
        {status ? <Icon name={status === 'critical' ? 'octagon' : 'alert'} /> : null}
        {status && statusLabel ? <span className="sr-only">{statusLabel}: </span> : null}
        {label}
      </span>
      <span className="ui-tile-figure" data-figure="">{figure}</span>
      {sub ? <span className="ui-tile-sub">{sub}</span> : null}
      {sub2 ? <span className="ui-tile-sub2">{sub2}</span> : null}
      {source ? <span className="ui-tile-source">{source}</span> : null}
    </>
  );
  return href
    ? <a className="ui-tile" href={href} data-status={status}>{body}</a>
    : <div className="ui-tile" data-status={status}>{body}</div>;
}
