// A status chip (docs/design/system/README.md, Badge): glyph and word, a ladder of fill weight, so a status survives
// greyscale, colour blindness and glare. The word comes from the server, in the page's language.
//   ok        check, the word in ok-text, no fill            warning   triangle on the warning tint
//   critical  octagon on the critical fill                   hold      hourglass, outlined (pending, not in yet)
//   stale     clock on sunken (no recent data, with its age) nodata    dashed outline (not measured)
//   neutral   sunken (inactive, draft)   note   the note tint   accent   outlined in the action colour (Open, Platform admin)
import type { ReactNode } from 'react';

import { Icon, type IconName } from './Icon.js';

export type ChipStatus = 'ok' | 'warning' | 'critical' | 'hold' | 'neutral' | 'note' | 'accent';
export type ChipState = 'stale' | 'nodata';
export type ChipKind = ChipStatus | ChipState;

const GLYPHS: Partial<Record<ChipKind, IconName>> = {
  ok: 'check-circle', warning: 'alert', critical: 'octagon', hold: 'hourglass', stale: 'clock',
};
const STATES = new Set<ChipKind>(['stale', 'nodata']);

export function Chip({ kind, children }: { kind: ChipKind; children: ReactNode }) {
  const glyph = GLYPHS[kind];
  return (
    <span className="ui-chip" data-status={STATES.has(kind) ? undefined : kind} data-state={STATES.has(kind) ? kind : undefined}>
      {glyph ? <Icon name={glyph} /> : null}
      <span>{children}</span>
    </span>
  );
}

/** A row of chips (a page head's summary: "12 sites", "1 inactive"). */
export function Chips({ children, label }: { children: ReactNode; label?: string }) {
  return <div className="ui-chips" role={label ? 'group' : undefined} aria-label={label}>{children}</div>;
}
