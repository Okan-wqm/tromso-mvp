// An interactive time series (frontend redesign, decision 3: uPlot, the one library for every interactive chart), drawn
// inside a ChartFrame. The values come from the server's series readers, finished: times in seconds, values or null.
// A null is a gap and is never bridged (spanGaps off). Colours are the chart roles read from the page (--chart-s1 …
// --chart-s5, --chart-grid, --chart-tick-ink, --chart-warn, --chart-crit, --chart-stale), so the chart follows the
// person's theme; nothing is written as a style attribute (uPlot sizes its canvas through the CSSOM, which the
// Content-Security-Policy allows). No series with a value says `emptyLabel` in words instead of drawing an empty frame.
//
// What a water or sensor chart needs beyond the lines, all optional and all finished by the server:
//   - `envelope`: each bucket's lowest and highest, a light band behind its mean;
//   - `zones` and `limits`: the fish's limits, the band beyond each bound tinted (warning, critical) and each bound a
//     line with its label (warning dashed, critical solid);
//   - `gaps`: the stretches without a value, tinted and named, so a missing stretch is seen, never read as a flat line;
//   - `markers`: moments (a sensor moved, calibrated; a feeding, a treatment, an alarm), a vertical line each;
//   - a series `dashed` (a line) or `hollow` (points): a value worked out, not measured (NH₃-N);
//   - `range`: the window's edges, so charts on one time axis line up whatever their values;
//   - `zone` and `decimals`: the site's clock on the time axis (dd.mm at midnight, HH:MM otherwise) and the quantity's
//     decimals on the values.
import { useEffect, useRef } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';

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
  label: string;
  status?: Severity;
}

export type SeriesColour = 1 | 2 | 3 | 4 | 5;

export interface SeriesChartProps {
  /** the moments, seconds since 1970, shared by every series */
  times: number[];
  series: Series[];
  /** the unit of the values, on the axis ("mg/L") */
  unit: string;
  emptyLabel: string;
  height?: number;
  envelope?: { low: (number | null | undefined)[]; high: (number | null | undefined)[]; series: SeriesColour };
  zones?: Zone[];
  limits?: Limit[];
  gaps?: [number, number][];
  gapLabel?: string;
  markers?: Marker[];
  range?: [number, number];
  /** the IANA zone the times are read on (the site's clock) */
  zone?: string;
  decimals?: number;
}

function role(element: Element, name: string): string {
  return getComputedStyle(element).getPropertyValue(name).trim();
}

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
export function extent(series: Series[], envelope: SeriesChartProps['envelope'], limits: Limit[]): [number, number] {
  const values = [...series.flatMap((each) => each.values), ...(envelope ? [...envelope.low, ...envelope.high] : []),
    ...limits.map((limit) => limit.value)].filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  if (!values.length) return [0, 1];
  const low = Math.min(...values);
  const high = Math.max(...values);
  const margin = (high - low) * 0.08 || Math.max(Math.abs(high) * 0.05, 0.5);
  return [low - margin, high + margin];
}

export function SeriesChart({ times, series, unit, emptyLabel, height = 220, envelope, zones = [], limits = [], gaps = [],
  gapLabel = '', markers = [], range, zone, decimals }: SeriesChartProps) {
  const box = useRef<HTMLDivElement>(null);
  const empty = !hasValues(series);
  useEffect(() => {
    const element = box.current;
    if (!element || empty) return undefined;
    const ink = role(element, '--chart-tick-ink');
    const grid = role(element, '--chart-grid');
    const status = { warning: role(element, '--chart-warn'), critical: role(element, '--chart-crit') };
    const stale = role(element, '--chart-stale');
    const [low, high] = extent(series, envelope, limits);
    const shade = (u: uPlot, colour: string, alpha: number, x0: number, x1: number, y0: number, y1: number) => {
      const ctx = u.ctx;
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.fillStyle = colour;
      ctx.fillRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
      ctx.restore();
    };
    const fillEnvelope = (u: uPlot) => {
      if (!envelope) return;
      const ctx = u.ctx;
      ctx.save();
      ctx.globalAlpha = 0.18;
      ctx.fillStyle = role(element, `--chart-s${envelope.series}`);
      let first = -1;
      const close = (last: number) => {
        for (let back = last; back >= first; back -= 1) {
          const value = envelope.low[back];
          const time = times[back];
          if (value !== null && value !== undefined && time !== undefined) {
            ctx.lineTo(u.valToPos(time, 'x', true), u.valToPos(value, 'y', true));
          }
        }
        ctx.closePath();
        ctx.fill();
        first = -1;
      };
      times.forEach((time, index) => {
        const upper = envelope.high[index];
        if (upper === undefined) return;                       // another series' moment: skipped, not a break
        if (upper === null) {                                  // a gap: the band ends here, never bridged
          if (first >= 0) close(index - 1);
          return;
        }
        const x = u.valToPos(time, 'x', true);
        const y = u.valToPos(upper, 'y', true);
        if (first < 0) { ctx.beginPath(); ctx.moveTo(x, y); first = index; } else ctx.lineTo(x, y);
      });
      if (first >= 0) close(times.length - 1);
      ctx.restore();
    };
    const behind = (u: uPlot) => {
      const { left, top, width, height: tall } = u.bbox;
      for (const each of zones) {
        const y0 = each.to === null ? top : u.valToPos(each.to, 'y', true);
        const y1 = each.from === null ? top + tall : u.valToPos(each.from, 'y', true);
        shade(u, status[each.status], each.status === 'critical' ? 0.14 : 0.12, left, left + width, y0, y1);
      }
      for (const [from, to] of gaps) shade(u, stale, 0.16, u.valToPos(from, 'x', true), u.valToPos(to, 'x', true), top, top + tall);
      fillEnvelope(u);
    };
    const over = (u: uPlot) => {
      const { left, top, width, height: tall } = u.bbox;
      const ctx = u.ctx;
      const scale = devicePixelRatio || 1;
      ctx.save();
      ctx.font = `${12 * scale}px ${getComputedStyle(element).fontFamily}`;
      for (const limit of limits) {
        const y = u.valToPos(limit.value, 'y', true);
        ctx.strokeStyle = status[limit.status];
        ctx.fillStyle = status[limit.status];
        ctx.lineWidth = scale;
        ctx.setLineDash(limit.status === 'warning' ? [6 * scale, 4 * scale] : []);
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(left + width, y);
        ctx.stroke();
        ctx.textAlign = 'right';                            // at the right end: the values' ticks stand at the left
        ctx.fillText(limit.label, left + width - 6 * scale, y - 4 * scale);
        ctx.textAlign = 'left';
      }
      ctx.setLineDash([2 * scale, 3 * scale]);
      for (const marker of markers) {
        const x = u.valToPos(marker.at, 'x', true);
        ctx.strokeStyle = marker.status ? status[marker.status] : ink;
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, top + tall);
        ctx.stroke();
      }
      if (gapLabel) {
        ctx.fillStyle = ink;
        ctx.setLineDash([]);
        for (const [from, to] of gaps) {
          const x0 = u.valToPos(from, 'x', true);
          const x1 = u.valToPos(to, 'x', true);
          if (x1 - x0 > ctx.measureText(gapLabel).width + 8 * scale) {
            ctx.textAlign = 'center';
            ctx.fillText(gapLabel, (x0 + x1) / 2, top + tall / 2);
            ctx.textAlign = 'left';
          }
        }
      }
      ctx.restore();
    };
    const chart = new uPlot({
      width: Math.max(element.clientWidth, 200),
      height,
      legend: { show: false },
      cursor: { drag: { x: true, y: false } },
      ...(zone ? { tzDate: (seconds: number) => uPlot.tzDate(new Date(seconds * 1000), zone) } : {}),
      scales: {
        x: { time: true, ...(range ? { range: (): uPlot.Range.MinMax => [range[0], range[1]] } : {}) },
        y: { range: (): uPlot.Range.MinMax => [low, high] },
      },
      axes: [
        { stroke: ink, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 }, space: 64,
          values: (_u: uPlot, splits: number[]) => splits.map((split) => clockText(split, zone)) },
        { stroke: ink, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 }, label: unit,
          ...(decimals !== undefined ? { values: (_u: uPlot, splits: number[]) => splits.map((split) => split.toFixed(decimals)) } : {}) },
      ],
      hooks: { drawClear: [behind], draw: [over] },
      series: [
        {},
        ...series.map((each) => ({
          label: each.label,
          stroke: role(element, `--chart-s${each.series}`),
          width: 2,
          spanGaps: false,
          ...(each.dashed ? { dash: [6, 4] } : {}),
          ...(each.points
            ? { paths: () => null, points: { show: true, size: 7, ...(each.hollow ? { fill: role(element, '--surface-sheet'), width: 2 } : {}) } }
            : { points: { show: false } }),
        })),
      ],
    }, [times, ...series.map((each) => each.values)], element);
    const resize = new ResizeObserver(() => chart.setSize({ width: Math.max(element.clientWidth, 200), height }));
    resize.observe(element);
    return () => { resize.disconnect(); chart.destroy(); };
  }, [times, series, unit, height, empty, envelope, zones, limits, gaps, gapLabel, markers, range, zone, decimals]);
  return empty ? <p className="ui-empty-text ui-chart-empty">{emptyLabel}</p> : <div ref={box} className="ui-series" />;
}
