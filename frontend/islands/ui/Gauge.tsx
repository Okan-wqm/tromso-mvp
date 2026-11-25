// A gauge (static/css/ui.css, .ui-gauge; templates/farm/production_units.html draws the same gauge on the server): a share
// of a whole, such as a unit's density against its capacity, as a short bar and the share in words beside it, so the bar
// is never the only cue (it is aria-hidden; the text says the figure). The bar is an SVG whose viewBox is 0-100, so the
// filled part is a plain width attribute: no style attribute for the Content-Security-Policy to refuse. A share above
// 100 fills the bar and is said whole in the text; a status (critical, warning) colours the fill and the text, and the
// server says it in words too (an "Over" chip). Every figure and word comes from the server.

export interface GaugeProps {
  /** the share in % (0-100 fills the bar; more is drawn full) */
  value: number;
  /** the share in words ("12 % of capacity") */
  text: string;
  status?: 'critical' | 'warning' | null;
}

export function Gauge({ value, text, status }: GaugeProps) {
  const width = Math.min(Math.max(Number.isFinite(value) ? value : 0, 0), 100);
  return (
    <span className="ui-gauge" data-status={status ?? undefined}>
      <svg className="ui-gauge-track" viewBox="0 0 100 1" preserveAspectRatio="none" aria-hidden="true" focusable="false">
        <rect className="ui-gauge-fill" width={width} height={1} />
      </svg>
      <span className="ui-gauge-text">{text}</span>
    </span>
  );
}
