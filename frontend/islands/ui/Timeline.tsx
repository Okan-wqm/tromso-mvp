// A timeline of lanes (static/css/ds.css, Timeline; Sensors › Bindings' history of one channel): one lane per place, its
// spans as bars on one time axis, the ticks above. Every position is the server's (x and width in % of the window), so
// the bars are SVG attributes in % of the track: no style attribute for the Content-Security-Policy to refuse, nothing
// worked out in the browser. Each bar says its words inside it (cut by its own box, the whole in its <title>), and each
// lane is a picture named by its place and every span in words, so neither colour nor the dashed edge of a backup is
// the only cue. An open span (still bound now) runs to the window's end.

export interface TimelineSpan {
  key: string;
  /** where it starts and how wide it is, in % of the window (0-100) */
  x: number;
  width: number;
  tone: 'primary' | 'backup';
  open: boolean;
  /** the span in words ("Primary · 06.11.2026 08:02 – now") */
  label: string;
}

export interface TimelineLane { key: string; label: string; spans: TimelineSpan[] }

export interface TimelineProps {
  label: string;
  ticks: { x: number; label: string }[];
  lanes: TimelineLane[];
}

const pct = (value: number) => `${Math.min(Math.max(value, 0), 100)}%`;

export function Timeline({ label, ticks, lanes }: TimelineProps) {
  return (
    <figure className="ui-timeline" aria-label={label}>
      <div className="ui-timeline-row" aria-hidden="true">
        <span />
        <svg className="ui-timeline-axis">
          {ticks.map((tick, index) => (
            <text key={tick.x} x={pct(tick.x)} y="12"
              textAnchor={index === 0 ? 'start' : index === ticks.length - 1 ? 'end' : 'middle'}>{tick.label}</text>
          ))}
        </svg>
      </div>
      {lanes.map((lane) => (
        <div key={lane.key} className="ui-timeline-row">
          <span className="ui-timeline-name">{lane.label}</span>
          <svg className="ui-timeline-track" role="img" aria-label={`${lane.label}: ${lane.spans.map((span) => span.label).join('; ')}`}>
            {ticks.map((tick) => <line key={tick.x} className="ui-timeline-tick" x1={pct(tick.x)} x2={pct(tick.x)} y1="0" y2="100%" />)}
            {lane.spans.map((span) => (
              <svg key={span.key} x={pct(span.x)} width={pct(Math.max(span.width, 0.5))} y="4" height="20"
                className="ui-timeline-span" data-tone={span.tone} data-open={span.open ? '' : undefined}>
                <title>{span.label}</title>
                <rect width="100%" height="100%" />
                <text x="6" y="14">{span.label}</text>
              </svg>
            ))}
          </svg>
        </div>
      ))}
    </figure>
  );
}
