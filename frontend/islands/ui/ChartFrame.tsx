// The frame of a chart (static/css/ds.css, Chart frame): its title, the latest value at the right (in its status's text
// colour when it is abnormal), the drawing, its keys and a caption that says where the values come from and how old they
// are. The frame never draws data: the drawing is a child (a typed SVG of the server's geometry, or an interactive series
// with uPlot), reading its colours from the chart roles (--chart-*). An empty series says so in words, never a flat line.
import { useId, type ReactNode } from 'react';

export interface ChartKey {
  label: ReactNode;
  /** the categorical series colour 1..5 (--chart-s1 … --chart-s5) */
  series: 1 | 2 | 3 | 4 | 5;
}

export interface ChartFrameProps {
  title: ReactNode;
  now?: ReactNode;
  nowStatus?: 'critical' | 'warning';
  keys?: ChartKey[];
  caption?: ReactNode;
  /** the drawing's name for a screen reader ("Dissolved oxygen, TK-02, last 24 hours") */
  label: string;
  /** the drawing in words, for a screen reader and for whoever cannot see it (WCAG 1.1.1): the figures it shows, as the
   *  server words them ([["Latest", "6.50 mg/L at 13:42"], ["Lowest", "5.92 mg/L at 04:12"], ["Gaps", "03:00 to 05:00"]]) */
  values?: [string, string][];
  children: ReactNode;
}

export function ChartFrame({ title, now, nowStatus, keys, caption, label, values, children }: ChartFrameProps) {
  const id = useId();
  return (
    <figure className="ui-chart">
      <div className="ui-chart-head">
        <h3>{title}</h3>
        {now ? <span className="ui-chart-now" data-status={nowStatus}>{now}</span> : null}
      </div>
      <div className="ui-chart-draw" role="img" aria-label={label} aria-describedby={values && values.length ? id : undefined}>{children}</div>
      {values && values.length ? (
        <dl className="sr-only" id={id}>{values.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}</dl>
      ) : null}
      {keys && keys.length ? (
        <ul className="ui-chart-keys">
          {keys.map((key) => <li key={key.series} className="ui-chart-key" data-series={String(key.series)}><span>{key.label}</span></li>)}
        </ul>
      ) : null}
      {caption ? <figcaption className="ui-chart-caption">{caption}</figcaption> : null}
    </figure>
  );
}
