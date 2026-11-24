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
//   - `markers`: moments (a sensor moved, calibrated; a feeding, a treatment, an alarm), a vertical line each, and over
//     it a mark of its own (an SVG drawn over the canvas, placed by uPlot's valToPos): a handle at the top of its line,
//     24 px across (the line under it takes no pointer, so the cursor and the drag-zoom reach the whole plot), its label
//     shown on hover and on focus; named for a screen reader, reached with Tab and a link where the marker has an
//     address, unless `marksListed`: the same moments are listed beside the chart (Tank › Water's events, every one a
//     link there), which is then the keyboard's and the screen reader's path, and the marks are for the pointer only (a
//     window of many events never fills the Tab order with a stop per event per chart);
//   - a series `dashed` (a line) or `hollow` (points): a value worked out, not measured (NH₃-N);
//   - `range`: the window's edges, so charts on one time axis line up whatever their values;
//   - `zone` and `decimals`: the site's clock on the time axis (dd.mm at midnight, HH:MM otherwise) and the quantity's
//     decimals on the values.
import { useEffect, useRef, useState } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';

import { clockText, extent, hasValues, Marks, type Envelope, type Limit, type Marker, type Overlay, type Series,
  type Zone } from './series-parts.js';

export { clockText, extent, hasValues, Marks };
export type { Envelope, Limit, Marker, Overlay, Series, SeriesColour, Severity, Zone } from './series-parts.js';

export interface SeriesChartProps {
  /** the moments, seconds since 1970, shared by every series */
  times: number[];
  series: Series[];
  /** the unit of the values, on the axis ("mg/L") */
  unit: string;
  emptyLabel: string;
  height?: number;
  envelope?: Envelope;
  zones?: Zone[];
  limits?: Limit[];
  gaps?: [number, number][];
  gapLabel?: string;
  markers?: Marker[];
  /** the markers are listed beside the chart, each a link there: the marks are for the pointer only (no Tab stop) */
  marksListed?: boolean;
  range?: [number, number];
  /** the IANA zone the times are read on (the site's clock) */
  zone?: string;
  decimals?: number;
}

function role(element: Element, name: string): string {
  return getComputedStyle(element).getPropertyValue(name).trim();
}


// The defaults: one identity each, so a chart without them is not built again on every render (they are in the effect's
// dependencies).
const NO_ZONES: Zone[] = [];
const NO_LIMITS: Limit[] = [];
const NO_GAPS: [number, number][] = [];
const NO_MARKERS: Marker[] = [];

export function SeriesChart({ times, series, unit, emptyLabel, height = 220, envelope, zones = NO_ZONES, limits = NO_LIMITS,
  gaps = NO_GAPS, gapLabel = '', markers = NO_MARKERS, marksListed = false, range, zone, decimals }: SeriesChartProps) {
  const box = useRef<HTMLDivElement>(null);
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const empty = !hasValues(series);
  useEffect(() => {
    const element = box.current;
    if (!element || empty) return undefined;
    const ink = role(element, '--chart-tick-ink');
    const grid = role(element, '--chart-grid');
    // the canvas's text in the product's face at the chart steps (--fs-chart-tick, --fs-chart-axis), not uPlot's system font
    const face = role(element, '--font-text');
    const tick = `${role(element, '--fs-chart-tick')} ${face}`;
    const axis = `600 ${role(element, '--fs-chart-axis')} ${face}`;
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
      placeMarks(u);
    };
    // The marks over the canvas: each marker inside the drawn time, at uPlot's own position of its moment (CSS pixels,
    // the plotting area's offset in the box added), redrawn with the chart (a zoom, a resize).
    const placeMarks = (u: uPlot) => {
      const host = element.getBoundingClientRect();
      const area = u.over.getBoundingClientRect();
      const left = area.left - host.left;
      const top = area.top - host.top;
      const [from, to] = [u.scales.x.min ?? -Infinity, u.scales.x.max ?? Infinity];
      const next: Overlay = {
        width: Math.round(host.width), height: Math.round(host.height), top: Math.round(top),
        bottom: Math.round(top + area.height),
        marks: markers.filter((marker) => marker.at >= from && marker.at <= to)
          .map((marker) => ({ marker, x: Math.round((left + u.valToPos(marker.at, 'x')) * 10) / 10 })),
      };
      setOverlay((was) => (was && JSON.stringify(was) === JSON.stringify(next) ? was : next));
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
        { stroke: ink, font: tick, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 }, space: 64,
          values: (_u: uPlot, splits: number[]) => splits.map((split) => clockText(split, zone)) },
        { stroke: ink, font: tick, labelFont: axis, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 }, label: unit,
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
  if (empty) return <p className="ui-empty-text ui-chart-empty">{emptyLabel}</p>;
  return (
    <div className="ui-series">
      <div ref={box} className="ui-series-plot" />
      {overlay && overlay.marks.length ? <Marks overlay={overlay} listed={marksListed} /> : null}
    </div>
  );
}
