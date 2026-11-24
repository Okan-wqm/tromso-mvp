// The server's chart data (sensors/chart.py `data`, the one serialiser of the series reader) put on one time axis for
// SeriesChart: no value is worked out here, only placed. Every bucket's mean at the middle of its bucket, its lowest and
// highest as the envelope, a break (null) in the middle of every gap so a line never bridges it, the meter and lab samples
// and the values worked out per sample as points at their own moments, the fish's limits as tinted zones and bound
// lines, the moves and calibrations as markers. Shared by Tank › Water and Sensors › Charts.
import type { Limit, Marker, Series, SeriesChartProps, Zone } from '../ui/SeriesChart.js';

export interface Bands {
  critical_low?: number;
  warning_low?: number;
  warning_high?: number;
  critical_high?: number;
}

export interface ChartData {
  head: string;
  title: string;
  quantity: { code: string; label: string; unit: string; decimals: number; water: boolean };
  tier: string;
  tier_text: string;
  width_s: number;
  width_text: string;
  start: number;
  end: number;
  zone: string;
  empty: boolean;
  empty_text: string;
  simulated: boolean;
  simulated_text: string;
  buckets: {
    start: number[]; end: number[]; avg: number[]; min: number[]; max: number[]; n: number[]; channel: number[];
    role: string[]; origin: string[]; other: boolean[]; simulated: boolean[];
  };
  gaps: [number, number][];
  samples: { at: number; value: number; source: string }[];
  markers: { at: number; kind: string; channel: number; label: string }[];
  notes: string[];
  bands: Bands;
}

/** A value worked out per sample (farm/water/views.py `_history_of`: the NH₃-N). */
export interface Worked {
  at: number;
  value: number | null;
  status: string;
  note: string;
}

export interface SeriesWords {
  sensor: string;
  manual: string;
  lab: string;
  worked?: string;
  warning: string;
  critical: string;
}

/** A number as the page's language writes it, with the quantity's decimals. */
export function formatNumber(value: number, decimals: number, locale: string): string {
  return new Intl.NumberFormat(locale, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(value);
}

export function zonesOf(bands: Bands): Zone[] {
  const zones: Zone[] = [];
  const { critical_low: cl, warning_low: wl, warning_high: wh, critical_high: ch } = bands;
  if (cl !== undefined) zones.push({ from: null, to: cl, status: 'critical' });
  if (wl !== undefined) zones.push({ from: cl ?? null, to: wl, status: 'warning' });
  if (wh !== undefined) zones.push({ from: wh, to: ch ?? null, status: 'warning' });
  if (ch !== undefined) zones.push({ from: ch, to: null, status: 'critical' });
  return zones;
}

export function limitsOf(bands: Bands, words: SeriesWords, decimals: number, locale: string): Limit[] {
  const line = (value: number | undefined, status: 'warning' | 'critical'): Limit[] => (value === undefined ? []
    : [{ value, status, label: `${status === 'warning' ? words.warning : words.critical} ${formatNumber(value, decimals, locale)}` }]);
  return [...line(bands.critical_low, 'critical'), ...line(bands.warning_low, 'warning'),
    ...line(bands.warning_high, 'warning'), ...line(bands.critical_high, 'critical')];
}

export type Placed = Pick<SeriesChartProps, 'times' | 'series' | 'envelope' | 'zones' | 'limits' | 'gaps' | 'markers' | 'range'
  | 'zone' | 'decimals' | 'unit'>;

/** The chart on its own time axis; `worked` adds the values worked out per sample, hollow. */
export function place(chart: ChartData, words: SeriesWords, locale: string, worked: Worked[] = []): Placed {
  const { buckets } = chart;
  const mids = buckets.start.map((start, index) => (start + (buckets.end[index] ?? start)) / 2);
  const breaks = chart.gaps.map(([from, to]) => (from + to) / 2);
  const manual = chart.samples.filter((sample) => sample.source !== 'lab');
  const lab = chart.samples.filter((sample) => sample.source === 'lab');
  const times = [...new Set([...mids, ...breaks, ...chart.samples.map((sample) => sample.at), ...worked.map((item) => item.at)])]
    .sort((a, b) => a - b);
  const at = (moments: number[], values: (number | null)[]) => {
    const found = new Map(moments.map((moment, index) => [moment, values[index] ?? null]));
    return times.map((time) => (found.has(time) ? found.get(time) : undefined));
  };
  const withBreaks = (values: (number | null | undefined)[]) => values.map((value, index) => {
    const time = times[index];
    return time !== undefined && breaks.includes(time) && !mids.includes(time) ? null : value;
  });
  const series: Series[] = [];
  if (mids.length) series.push({ label: words.sensor, series: 1, values: withBreaks(at(mids, buckets.avg)) });
  if (manual.length) series.push({ label: words.manual, series: 3, points: true, values: at(manual.map((s) => s.at), manual.map((s) => s.value)) });
  if (lab.length) series.push({ label: words.lab, series: 4, points: true, values: at(lab.map((s) => s.at), lab.map((s) => s.value)) });
  const shown = worked.filter((item) => item.value !== null);
  if (shown.length && words.worked) {
    series.push({ label: words.worked, series: 5, points: true, hollow: true,
      values: at(shown.map((item) => item.at), shown.map((item) => item.value)) });
  }
  const markers: Marker[] = chart.markers.map((marker) => ({ at: marker.at, label: marker.label }));
  return {
    times, series, unit: chart.quantity.unit, decimals: chart.quantity.decimals, zone: chart.zone,
    range: [chart.start, chart.end], gaps: chart.gaps, markers,
    ...(mids.length ? { envelope: { low: withBreaks(at(mids, buckets.min)), high: withBreaks(at(mids, buckets.max)), series: 1 as const } } : {}),
    zones: zonesOf(chart.bands), limits: limitsOf(chart.bands, words, chart.quantity.decimals, locale),
  };
}

/** The keys under a chart: only the series it draws. */
export function keysOf(placed: Placed): { label: string; series: 1 | 2 | 3 | 4 | 5 }[] {
  return placed.series.map((each) => ({ label: each.label, series: each.series }));
}
