// An interactive time series (frontend redesign, decision 3: uPlot, the one library for every interactive chart), drawn
// inside a ChartFrame. The values come from the server's series readers, finished: times in seconds, values or null.
// A null is a gap and is never bridged (spanGaps off). Colours are the chart roles read from the page (--chart-s1 …
// --chart-s5, --chart-grid, --chart-tick-ink), so the chart follows the person's theme; nothing is written as a style
// attribute (uPlot sizes its canvas through the CSSOM, which the Content-Security-Policy allows). No series with a value
// says `emptyLabel` in words instead of drawing an empty frame.
import { useEffect, useRef } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';

export interface Series {
  label: string;
  /** the categorical colour 1..5 */
  series: 1 | 2 | 3 | 4 | 5;
  /** points only (manual samples), or a line (a sensor) */
  points?: boolean;
  values: (number | null)[];
}

export interface SeriesChartProps {
  /** the moments, seconds since 1970, shared by every series */
  times: number[];
  series: Series[];
  /** the unit of the values, on the axis ("mg/L") */
  unit: string;
  emptyLabel: string;
  height?: number;
}

function role(element: Element, name: string): string {
  return getComputedStyle(element).getPropertyValue(name).trim();
}

export function hasValues(series: Series[]): boolean {
  return series.some((each) => each.values.some((value) => value !== null));
}

export function SeriesChart({ times, series, unit, emptyLabel, height = 220 }: SeriesChartProps) {
  const box = useRef<HTMLDivElement>(null);
  const empty = !hasValues(series);
  useEffect(() => {
    const element = box.current;
    if (!element || empty) return undefined;
    const ink = role(element, '--chart-tick-ink');
    const grid = role(element, '--chart-grid');
    const chart = new uPlot({
      width: Math.max(element.clientWidth, 200),
      height,
      legend: { show: false },
      cursor: { drag: { x: true, y: false } },
      axes: [
        { stroke: ink, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 } },
        { stroke: ink, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 }, label: unit },
      ],
      series: [
        {},
        ...series.map((each) => ({
          label: each.label,
          stroke: role(element, `--chart-s${each.series}`),
          width: 2,
          spanGaps: false,
          ...(each.points ? { paths: () => null, points: { show: true, size: 6 } } : { points: { show: false } }),
        })),
      ],
    }, [times, ...series.map((each) => each.values)], element);
    const resize = new ResizeObserver(() => chart.setSize({ width: Math.max(element.clientWidth, 200), height }));
    resize.observe(element);
    return () => { resize.disconnect(); chart.destroy(); };
  }, [times, series, unit, height, empty]);
  return empty ? <p className="ui-empty-text ui-chart-empty">{emptyLabel}</p> : <div ref={box} className="ui-series" />;
}
