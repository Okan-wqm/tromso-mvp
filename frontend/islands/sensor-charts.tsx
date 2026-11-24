// Sensors › Charts in the new look (sensors/views.py `charts`, `_charts_props`): the technician's raw-channel view. The
// query is a plain GET form (a place, a quantity, a preset time or from and to in the shared date box, dd.mm.yyyy HH:MM,
// and a place to compare with), so the chart is an address; the server reads the series (sensors/read.py `series`, sensors/chart.py `data`) and the island
// only places it: the mean with its lowest and highest, the meter and lab samples, the fish's limits as bands and lines
// for a person who may read the water, the gaps shaded and named, never bridged, the moves and calibrations, the
// channel's newest value (said stale when it is), the CSV of what is drawn. The compared place is read on exactly the
// same window and drawn under it on the same time axis. A pressed preset is the last `range` of the query (the
// browser sends the pressed button after the hidden one), so it wins over the one in force.
import { useState } from 'react';

import { ChartFrame, Chip, EmptyState, LinkButton, Notice, Plate, Plates } from './ui/index.js';
import { mount } from './ui/mount.js';
import { useDateInputs } from './lib/dates.js';
import { SeriesChart } from './ui/SeriesChart.js';
import { formatNumber, keysOf, place, type ChartData, type SeriesWords } from './lib/series.js';

interface Group { label: string; options: { value: string; label: string }[] }
interface Now { value: number | null; at: number | null; fresh: boolean; channel: number }

interface Words extends SeriesWords {
  place: string; quantity: string; time: string; from: string; to: string; draw: string; choose: string;
  compare: string; compareQuantity: string; noCompare: string; sameQuantity: string; csv: string; now: string;
  stale: string; noValue: string; start: string; gaps: string; noBinding: string; example: string;
}

export interface SensorChartsProps {
  action: string;
  locale: string;
  places: Group[];
  quantities: Group[];
  ranges: string[];
  values: Record<'target' | 'quantity' | 'range' | 'start' | 'end' | 'compare' | 'compare_quantity', string>;
  errors: Record<string, string[]>;
  chart: ChartData | null;
  now: Now | null;
  compare: { chart: ChartData; now: Now | null } | null;
  csv: string;
  words: Words;
}

function Options({ groups, empty }: { groups: Group[]; empty?: string }) {
  return (
    <>
      {empty !== undefined ? <option value="">{empty}</option> : null}
      {groups.map((group) => (group.label
        ? <optgroup key={group.label} label={group.label}>{group.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</optgroup>
        : group.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)))}
    </>
  );
}

function nowText(now: Now | null, chart: ChartData, words: Words, locale: string): string {
  if (!now) return words.noBinding;
  if (now.value === null || !now.fresh) return words.stale;
  return `${formatNumber(now.value, chart.quantity.decimals, locale)} ${chart.quantity.unit} ${words.now}`;
}

function Drawn({ chart, now, props }: { chart: ChartData; now: Now | null; props: SensorChartsProps }) {
  const placed = place(chart, props.words, props.locale);
  const caption = [`${chart.tier_text}, ${chart.width_text}`, ...chart.notes, chart.gaps.length ? props.words.gaps : '']
    .filter(Boolean).join(' · ');
  return (
    <Plate title={chart.head} span={12} badge={chart.simulated ? <Chip kind="neutral">{chart.simulated_text}</Chip> : undefined}>
      <ChartFrame title={`${chart.title} · ${chart.quantity.label}`} now={nowText(now, chart, props.words, props.locale)}
        keys={keysOf(placed)} caption={caption} label={chart.head} interactive={Boolean(placed.markers?.length)}>
        <SeriesChart {...placed} gapLabel={props.words.noValue} emptyLabel={chart.empty_text} height={300} />
      </ChartFrame>
    </Plate>
  );
}

function SensorCharts(props: SensorChartsProps) {
  const { words, values } = props;
  const errors = Object.values(props.errors).flat();
  // The preset in force goes with Draw (a place or a quantity changed); typing a time leaves it for from and to.
  const [range, setRange] = useState(values.range);
  const form = useDateInputs<HTMLFormElement>();
  return (
    <>
      <form ref={form} method="get" action={props.action} className="ui-toolbar">
        <label>{words.place}<select name="target" defaultValue={values.target} required><Options groups={props.places} empty={words.choose} /></select></label>
        <label>{words.quantity}<select name="quantity" defaultValue={values.quantity} required><Options groups={props.quantities} /></select></label>
        <input type="hidden" name="range" value={range} />
        <span className="ui-segmented" role="group" aria-label={words.time}>
          {props.ranges.map((range) => (
            <button key={range} type="submit" name="range" value={range} className="ui-btn" aria-pressed={values.range === range}>{range}</button>
          ))}
        </span>
        <label>{words.from}<input type="text" name="start" defaultValue={values.start} onChange={() => setRange('')}
          autoComplete="off" data-date-input="moment" placeholder={words.example} /></label>
        <label>{words.to}<input type="text" name="end" defaultValue={values.end} onChange={() => setRange('')}
          autoComplete="off" data-date-input="moment" placeholder={words.example} /></label>
        <label>{words.compare}<select name="compare" defaultValue={values.compare}><Options groups={props.places} empty={words.noCompare} /></select></label>
        <label>{words.compareQuantity}<select name="compare_quantity" defaultValue={values.compare_quantity}><Options groups={props.quantities} empty={words.sameQuantity} /></select></label>
        <button type="submit" className="ui-btn" data-variant="primary">{words.draw}</button>
        {props.csv ? <LinkButton href={props.csv} icon="download">{words.csv}</LinkButton> : null}
      </form>
      {errors.length ? <Notice tone="critical">{errors.join(' ')}</Notice> : null}
      {props.chart ? (
        <Plates>
          <Drawn chart={props.chart} now={props.now} props={props} />
          {props.compare ? <Drawn chart={props.compare.chart} now={props.compare.now} props={props} /> : null}
        </Plates>
      ) : (errors.length ? null : <EmptyState title={words.start} />)}
    </>
  );
}

mount('sensor-charts', SensorCharts);
