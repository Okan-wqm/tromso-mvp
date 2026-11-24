// An icon of the one icon set (templates/icons/*.svg, built into icon-shapes.ts by scripts/icons.mjs): the same outline
// the server-rendered pages include, drawn as React elements (no markup string). Always decorative (aria-hidden): the
// words beside it carry the meaning. Its size and stroke come from where it stands (static/css: .icon in a button, a
// chip, the rail).
import { createElement } from 'react';

import { ICONS, type IconName } from './icon-shapes.js';

export type { IconName };

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg className={className ? `icon ${className}` : 'icon'} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {ICONS[name].map(([tag, attributes], index) => createElement(tag, { key: index, ...attributes }))}
    </svg>
  );
}
