// Tank › Water (farm/water/views.py `tank_water`), the one home of a tank's water history: every parameter on one time
// axis (small multiples), the sensors' lines with their lowest and highest, the meter and lab samples as points on the
// same chart, the fish's limits as tinted bands with their bound lines, the NH₃-N worked out per sample drawn hollow
// (worked out, not measured), the gaps shown and named, never bridged, and the window's events (feedings, treatments,
// harvests, alarms) as marks on every chart and as a list. The window is the address: the presets and the custom form
// are plain GET forms, so the page works as a link and with the back button. Every word and value comes from the server.
import { ChartFrame, EmptyState, Plate, Plates, Table } from './ui/index.js';
import { mount } from './ui/mount.js';
import { SeriesChart, type Marker } from './ui/SeriesChart.js';
import { keysOf, place, zonesOf, limitsOf, type Bands, type ChartData, type SeriesWords, type Worked } from './lib/series.js';

interface Event {
  at: number;
  until: number | null;
  kind: string;
  label: string;
  url: string;
  severity?: 'warning' | 'critical';
}

interface Place {
  point: string;
  kind: string;
  charts: ChartData[];
  worked: Record<string, { label: string; decimals: number; band: Bands; values: Worked[] }>;
}

interface Words extends SeriesWords {
  worked: string;
  noValue: string;
  time: string;
  custom: string;
  from: string;
  to: string;
  draw: string;
  empty: string;
  noChart: string;
  events: string;
  noEvents: string;
  notWorked: string;
  samples: string;
  calculated: string;
  zoneNote: string;
}

export interface WaterProps {
  range: string;
  start: number;
  end: number;
  zone: string;
  places: Place[];
  events: Event[];
  samples: string;
  ranges: { key: string; label: string; href: string; current: boolean }[];
  custom: { action: string; current: boolean; start: string; end: string };
  words: Words;
  locale: string;
  unit: { code: string; name: string; place: string };
}

function when(seconds: number, zone: string): string {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: zone, day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(seconds * 1000)).map((part) => [part.type, part.value]));
  return `${parts.day ?? ''}.${parts.month ?? ''}.${parts.year ?? ''} ${parts.hour ?? ''}:${parts.minute ?? ''}`;
}

function markersOf(events: Event[]): Marker[] {
  return events.map((event) => ({ at: event.at, label: event.label, ...(event.severity ? { status: event.severity } : {}) }));
}

function Window({ props }: { props: WaterProps }) {
  const { words } = props;
  return (
    <div className="ui-toolbar">
      <form method="get" action={props.custom.action}>
        <span className="ui-tile-label">{words.time}</span>
        <span className="ui-seg" role="group" aria-label={words.time}>
          {props.ranges.map((range) => (
            <button key={range.key} type="submit" name="range" value={range.key} className="ui-btn"
              aria-pressed={range.current}>{range.label}</button>
          ))}
        </span>
      </form>
      <form method="get" action={props.custom.action}>
        <label>{words.from}<input type="datetime-local" name="start" defaultValue={props.custom.start} required /></label>
        <label>{words.to}<input type="datetime-local" name="end" defaultValue={props.custom.end} required /></label>
        <button type="submit" className="ui-btn" aria-pressed={props.custom.current}>{words.draw}</button>
      </form>
    </div>
  );
}

function ParameterChart({ chart, props, markers }: { chart: ChartData; props: WaterProps; markers: Marker[] }) {
  const placed = place(chart, props.words, props.locale);
  const caption = [`${chart.tier_text}, ${chart.width_text}`, chart.simulated ? chart.simulated_text : '', ...chart.notes,
    props.words.zoneNote].filter(Boolean).join(' · ');
  return (
    <Plate span={6} label={chart.quantity.label}>
      <ChartFrame title={chart.quantity.label} keys={keysOf(placed)} caption={caption}
        label={`${chart.quantity.label}, ${props.unit.code}, ${when(props.start, props.zone)} – ${when(props.end, props.zone)}`}>
        <SeriesChart {...placed} markers={[...(placed.markers ?? []), ...markers]} gapLabel={props.words.noValue}
          emptyLabel={chart.empty_text} />
      </ChartFrame>
    </Plate>
  );
}

function WorkedChart({ code, item, props, markers }: { code: string; item: Place['worked'][string]; props: WaterProps; markers: Marker[] }) {
  const shown = item.values.filter((value) => value.value !== null);
  const refused = item.values.filter((value) => value.value === null);
  const times = shown.map((value) => value.at);
  const caption = [`${props.words.worked}: ${props.words.calculated}`,
    ...refused.map((value) => `${props.words.notWorked} ${when(value.at, props.zone)}: ${value.note}`), props.words.zoneNote].join(' · ');
  return (
    <Plate span={6} label={item.label}>
      <ChartFrame title={item.label} keys={[{ label: props.words.worked, series: 5 }]} caption={caption}
        label={`${item.label}, ${props.unit.code}, ${when(props.start, props.zone)} – ${when(props.end, props.zone)}`}>
        <SeriesChart key={code} times={times} unit="mg/L" decimals={item.decimals} zone={props.zone}
          range={[props.start, props.end]} emptyLabel={props.words.noChart} markers={markers}
          series={[{ label: props.words.worked, series: 5, points: true, hollow: true, values: shown.map((value) => value.value) }]}
          zones={zonesOf(item.band)} limits={limitsOf(item.band, props.words, item.decimals, props.locale)} />
      </ChartFrame>
    </Plate>
  );
}

function Water(props: WaterProps) {
  const markers = markersOf(props.events);
  const charts = props.places.flatMap((each) => each.charts);
  const worked = props.places.flatMap((each) => Object.entries(each.worked));
  return (
    <>
      <Window props={props} />
      {charts.length || worked.length ? (
        <Plates>
          {props.places.map((each) => [
            ...each.charts.map((chart) => <ParameterChart key={`${each.point}-${chart.quantity.code}`} chart={chart}
              props={props} markers={markers} />),
            ...Object.entries(each.worked).map(([code, item]) => <WorkedChart key={`${each.point}-${code}`} code={code}
              item={item} props={props} markers={markers} />),
          ])}
        </Plates>
      ) : <EmptyState title={props.words.empty} />}
      <Plates>
        <Plate title={props.words.events} span={12} link={{ href: props.samples, label: props.words.samples }}>
          {props.events.length ? (
            <Table label={props.words.events} rows={props.events} rowKey={(event) => `${event.kind}-${event.at}-${event.label}`}
              rowStatus={(event) => event.severity}
              columns={[
                { key: 'at', label: props.words.time, render: (event) => when(event.at, props.zone) },
                { key: 'label', label: props.words.events, rowHeader: true,
                  render: (event) => <a href={event.url}>{event.label}</a> },
              ]} />
          ) : <EmptyState title={props.words.noEvents} />}
        </Plate>
      </Plates>
    </>
  );
}

mount('water', Water);
