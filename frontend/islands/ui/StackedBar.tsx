// A stacked bar (static/css/ds.css, Stacked bar; templates/ui/_stack.html draws the same bar on the server): one whole
// (the people planned today) cut into its parts (here, not in yet, absent, on leave), each part a segment as long as its
// share, in its tone. The bar is an SVG whose viewBox is the whole, so a segment's length is a plain attribute: no style
// attribute, nothing for the Content-Security-Policy to refuse. The bar is a picture (role="img") named by `label` and
// every part in words; the legend under it says each part, its figure and its tone's mark, so nothing is told by colour
// alone. Every word and figure comes from the server; a part of 0 is in the legend and draws no segment.

export type StackTone = 'ok' | 'warning' | 'critical' | 'hold' | 'neutral' | 'note';

export interface StackPart {
  key: string;
  label: string;
  /** the part's count, the segment's length */
  value: number;
  /** the figure as the server words it ("3") */
  figure: string;
  tone: StackTone;
}

export interface StackedBarProps {
  /** what the whole is ("Planned today: 12") */
  label: string;
  parts: StackPart[];
  /** said when the whole is 0 ("Nobody is planned today"): no bar is drawn */
  empty?: string | null;
}

export function StackedBar({ label, parts, empty }: StackedBarProps) {
  const total = parts.reduce((sum, part) => sum + Math.max(part.value, 0), 0);
  let x = 0;
  const said = `${label}. ${parts.map((part) => `${part.label} ${part.figure}`).join(', ')}`;
  return (
    <figure className="ui-stack">
      {total > 0 ? (
        <svg className="ui-stack-bar" viewBox={`0 0 ${total} 1`} preserveAspectRatio="none" role="img" aria-label={said}>
          {parts.filter((part) => part.value > 0).map((part) => {
            const segment = <rect key={part.key} className="ui-stack-seg" data-tone={part.tone} x={x} y={0} width={part.value} height={1} />;
            x += part.value;
            return segment;
          })}
        </svg>
      ) : <p className="ui-stack-empty">{empty ?? label}</p>}
      <figcaption>
        <span className="ui-stack-title">{label}</span>
        <ul className="ui-stack-legend" role="list">
          {parts.map((part) => (
            <li key={part.key} data-tone={part.tone}>
              <span className="ui-stack-swatch" aria-hidden="true" />
              <span>{part.label}</span>
              <strong>{part.figure}</strong>
            </li>
          ))}
        </ul>
      </figcaption>
    </figure>
  );
}
