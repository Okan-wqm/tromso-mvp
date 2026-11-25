// The parts of a series chart that need no browser and no style sheet (frontend/islands/ui/SeriesChart.tsx draws
// with them): its types, the value and time axes' rules and the marks over the canvas. Apart from SeriesChart, which
// loads uPlot's style sheet, so that the tests can render them without a bundler (series-chart.test.tsx).
import uPlot from 'uplot';

export interface Series {
  label: string;
  /** the categorical colour 1..5 */
  series: 1 | 2 | 3 | 4 | 5;
  /** points only (manual samples), or a line (a sensor) */
  points?: boolean;
  /** a value worked out, not measured: a line drawn dashed */
  dashed?: boolean;
  /** points drawn hollow (a value worked out per sample, not measured) */
  hollow?: boolean;
  /** null: a gap, the line breaks there; undefined: no value of this series at that moment (another series has one) */
  values: (number | null | undefined)[];
}

export type Severity = 'warning' | 'critical';

export interface Zone {
  /** the lower edge (null: the bottom of the chart) */
  from: number | null;
  /** the upper edge (null: the top of the chart) */
  to: number | null;
  status: Severity;
}

export interface Limit {
  value: number;
  status: Severity;
  label: string;
}

export interface Marker {
  at: number;
  /** what happened, in words: the mark's accessible name and its hover and focus label */
  label: string;
  status?: Severity;
  /** where the record is read (a feeding's list, an alarm's detail): the mark is then a link */
  href?: string;
  /** the moment is listed beside the chart, a link there (Tank › Water's events): its mark is for the pointer only, no
   *  Tab stop; a marker of the chart's own (a sensor moved, calibrated) keeps its Tab stop */
  listed?: boolean;
}

/** A marker placed on the drawing, in CSS pixels of the chart's box. */
interface PlacedMark {
  marker: Marker;
  x: number;
}

export interface Overlay {
  width: number;
  height: number;
  top: number;
  bottom: number;
  marks: PlacedMark[];
}

export type SeriesColour = 1 | 2 | 3 | 4 | 5;

/** A chart's envelope: each bucket's lowest and highest, a light band behind its mean. */
export interface Envelope { low: (number | null | undefined)[]; high: (number | null | undefined)[]; series: SeriesColour }

export function hasValues(series: Series[]): boolean {
  return series.some((each) => each.values.some((value) => value !== null && value !== undefined));
}

const two = (value: number): string => String(value).padStart(2, '0');

/** A tick of the time axis on the site's clock: dd.mm at a midnight, HH:MM at any other time (never one day twice). */
export function clockText(seconds: number, zone: string | undefined): string {
  const date = zone ? uPlot.tzDate(new Date(seconds * 1000), zone) : new Date(seconds * 1000);
  const day = `${two(date.getDate())}.${two(date.getMonth() + 1)}`;
  const time = `${two(date.getHours())}:${two(date.getMinutes())}`;
  return time === '00:00' ? day : time;
}

/** The value axis's extent: the values, and every limit the person must see the values against. */
export function extent(series: Series[], envelope: Envelope | undefined, limits: Limit[]): [number, number] {
  const values = [...series.flatMap((each) => each.values), ...(envelope ? [...envelope.low, ...envelope.high] : []),
    ...limits.map((limit) => limit.value)].filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  if (!values.length) return [0, 1];
  const low = Math.min(...values);
  const high = Math.max(...values);
  const margin = (high - low) * 0.08 || Math.max(Math.abs(high) * 0.05, 0.5);
  return [low - margin, high + margin];
}

/** The markers' marks over the canvas: a handle at the top of the line to hover or focus (24 px across), the line lit and
 *  the label beside it while it is. `listed` (every mark) or a marker's own `listed`: the moment is listed beside the
 *  chart, its mark is for the pointer only.
 *  Exported for its tests. */
export function Marks({ overlay, listed = false }: { overlay: Overlay; listed?: boolean }) {
  return (
    <svg className="ui-chart-marks" width={overlay.width} height={overlay.height}
      viewBox={`0 0 ${overlay.width} ${overlay.height}`}>
      {overlay.marks.map(({ marker, x }, index) => {
        const end = x > overlay.width / 2;            // a label in the right half reads to the left of its line
        const body = (
          <>
            <title>{marker.label}</title>
            <line className="ui-chart-mark-hit" x1={x} y1={overlay.top} x2={x} y2={overlay.bottom} />
            <circle className="ui-chart-mark-handle" cx={x} cy={overlay.top + 4} r="12" />
            <text className="ui-chart-mark-label" x={end ? x - 14 : x + 14} y={overlay.top + 8}
              textAnchor={end ? 'end' : 'start'} aria-hidden="true">{marker.label}</text>
          </>
        );
        const key = `${marker.at}-${index}`;
        if (listed || marker.listed) {
          return <g key={key} className="ui-chart-mark" aria-hidden="true" data-status={marker.status}>{body}</g>;
        }
        return marker.href ? (
          <a key={key} className="ui-chart-mark" href={marker.href} aria-label={marker.label} data-status={marker.status}>
            {body}
          </a>
        ) : (
          <g key={key} className="ui-chart-mark" tabIndex={0} role="img" aria-label={marker.label} data-status={marker.status}>
            {body}
          </g>
        );
      })}
    </svg>
  );
}
