// Tank › Water (farm/water/views.py `tank_water`), the one home of a tank's water history: every parameter on one time
// axis (small multiples), the sensors' lines with their lowest and highest, the meter and lab samples as points on the
// same chart, the fish's limits as tinted bands with their bound lines, the NH₃-N worked out per sample drawn hollow
// (worked out, not measured), the buckets from a backup or the system's channel drawn as such, every sample past a limit
// said with its status, the gaps shown and named, never bridged, each chart in words (its latest, lowest and highest, its
// gaps), and the window's events (feedings, treatments, harvests, alarms) as marks on every chart for the pointer and as
// a list, the keyboard's and the screen reader's path, each a link to its records (a day-dated record said as its day
// or days, never "00:00"), and the Deffeyes chart of the window (the server's diagram of the newest water drawn, its star
// named with its time, "No diagram after …" when the window's end has none, and the water's path through the time). The
// window is the address: the presets and the custom form (the shared date box, dd.mm.yyyy HH:MM) are plain GET forms, so
// the page works as a link and with the back button. Every word and value comes from the server. A page of several
// points (System › Water: the loop and its tanks' points) heads each point's charts with the point's name, and each
// chart's accessible name says its point.
import { ChartFrame, Chip, EmptyState, Plate, Plates, Table } from './ui/index.js';
import { useDateInputs } from './lib/dates.js';
import { DeffeyesChart, DeffeyesLegend, type DeffeyesDrawing, type DeffeyesWords } from './lib/deffeyes.js';
import { mount } from './ui/mount.js';
import { SeriesChart, type Marker } from './ui/SeriesChart.js';
import { flaggedText, formatNumber, keysOf, place, zonesOf, limitsOf, type Bands, type ChartData, type SeriesWords, type Worked } from './lib/series.js';

interface Event {
  at: number;
  until: number | null;
  /** a day-dated record (a treatment, a harvest): `when` is its day or days, never a time of day */
  all_day: boolean;
  /** the record's own moment or days, as the server words them on the site's clock */
  when: string;
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

interface RangeChart {
  chart: DeffeyesDrawing | null;
  /** the water's point through the window, a polyline's points per run of frames with a diagram (never bridged) */
  path?: string[];
  first?: { x: string; y: string; at: number };
  /** the runs of one frame, each a dot (a polyline of one point draws nothing) */
  dots?: { x: string; y: string; at: number }[];
  /** the newest frame with a diagram */
  at?: number;
  /** the head's words: the star's water with its time, or "No diagram after …" (then `now_status` warning) */
  now?: string;
  now_status?: '' | 'warning';
  /** the window's end has no diagram: why, in words ('' when it has one) */
  stale?: string;
  /** what the hidden labels say, where the chart is too narrow for them */
  scale?: string;
  /** the chart in words */
  said?: [string, string][];
  caption?: string;
  /** why there is no diagram in the window */
  reason: string;
  words: DeffeyesWords & { title: string; path: string; first: string };
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
  /** the limit bands are the fish's limits of today, drawn over the whole window */
  bandsToday: string;
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
  custom: { action: string; current: boolean; start: string; end: string; example: string };
  range_chart: RangeChart | null;
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
  // listed: each event is a link in the events list, the keyboard's path; the chart's own markers keep their Tab stop
  return events.map((event) => ({ at: event.at, label: `${event.when} · ${event.label}`, href: event.url, listed: true,
    ...(event.severity ? { status: event.severity } : {}) }));
}

function Window({ props }: { props: WaterProps }) {
  const { words } = props;
  const custom = useDateInputs<HTMLFormElement>();
  return (
    <div className="ui-toolbar">
      <form method="get" action={props.custom.action}>
        <span className="ui-tile-label">{words.time}</span>
        <span className="ui-segmented" role="group" aria-label={words.time}>
          {props.ranges.map((range) => (
            <button key={range.key} type="submit" name="range" value={range.key} className="ui-btn"
              aria-pressed={range.current}>{range.label}</button>
          ))}
        </span>
      </form>
      <form ref={custom} method="get" action={props.custom.action}>
        <label>{words.from}<input type="text" name="start" defaultValue={props.custom.start} required autoComplete="off"
          data-date-input="moment" placeholder={props.custom.example} /></label>
        <label>{words.to}<input type="text" name="end" defaultValue={props.custom.end} required autoComplete="off"
          data-date-input="moment" placeholder={props.custom.example} /></label>
        <button type="submit" className="ui-btn" aria-pressed={props.custom.current}>{words.draw}</button>
      </form>
    </div>
  );
}

/** A chart's accessible name: what it shows, its point when the page has several, the unit or system, the window. */
function named(what: string, point: string | null, props: WaterProps): string {
  return [what, point, props.unit.code, `${when(props.start, props.zone)} – ${when(props.end, props.zone)}`].filter(Boolean).join(', ');
}

function ParameterChart({ chart, point, props, markers }: { chart: ChartData; point: string | null; props: WaterProps; markers: Marker[] }) {
  const placed = place(chart, props.words, props.locale);
  const flagged = flaggedText(chart.samples, chart.quantity.decimals, chart.quantity.unit, props.locale,
    (seconds) => when(seconds, props.zone));
  const banded = Object.keys(chart.bands).length > 0;
  const caption = [`${chart.tier_text}, ${chart.width_text}`, ...flagged, banded ? props.words.bandsToday : '',
    chart.gap_text ? `${props.words.noValue}: ${chart.gap_text}` : '', ...chart.notes, props.words.zoneNote].filter(Boolean).join(' · ');
  return (
    <Plate span={6} label={chart.quantity.label}>
      <ChartFrame title={chart.quantity.label} keys={keysOf(placed)} caption={caption}
        {...(chart.simulated ? { now: <Chip kind="neutral">{chart.simulated_text}</Chip> } : {})}
        values={[...chart.said, ...flagged.map((text): [string, string] => [props.words.samples, text])]}
        label={named(chart.quantity.label, point, props)}>
        <SeriesChart {...placed} markers={[...(placed.markers ?? []), ...markers]} gapLabel={props.words.noValue}
          emptyLabel={chart.empty_text} />
      </ChartFrame>
    </Plate>
  );
}

function WorkedChart({ code, item, point, props, markers }: { code: string; item: Place['worked'][string]; point: string | null; props: WaterProps; markers: Marker[] }) {
  const shown = item.values.filter((value) => value.value !== null);
  const refused = item.values.filter((value) => value.value === null);
  const times = shown.map((value) => value.at);
  const flagged = flaggedText(item.values, item.decimals, 'mg/L', props.locale, (seconds) => when(seconds, props.zone));
  const refusals = refused.map((value) => `${props.words.notWorked} ${when(value.at, props.zone)}: ${value.note}`);
  const caption = [`${props.words.worked}: ${props.words.calculated}`, ...flagged,
    Object.keys(item.band).length ? props.words.bandsToday : '', ...refusals, props.words.zoneNote].filter(Boolean).join(' · ');
  return (
    <Plate span={6} label={item.label}>
      <ChartFrame title={item.label} keys={[{ label: props.words.worked, series: 5 }]} caption={caption}
        values={[...shown.map((value): [string, string] => [when(value.at, props.zone),
          `${formatNumber(value.value ?? 0, item.decimals, props.locale)} mg/L${value.status_text ? ` (${value.status_text})` : ''}`]),
        ...refusals.map((text): [string, string] => [props.words.notWorked, text])]}
        label={named(item.label, point, props)}>
        <SeriesChart key={code} times={times} unit="mg/L" decimals={item.decimals} zone={props.zone}
          range={[props.start, props.end]} emptyLabel={props.words.noChart} markers={markers}
          series={[{ label: props.words.worked, series: 5, points: true, hollow: true, values: shown.map((value) => value.value) }]}
          zones={zonesOf(item.band)} limits={limitsOf(item.band, props.words, item.decimals, props.locale)} />
      </ChartFrame>
    </Plate>
  );
}

function RangeDeffeyes({ range, props }: { range: RangeChart; props: WaterProps }) {
  const { words } = range;
  const label = `${words.title}, ${props.unit.code}, ${when(props.start, props.zone)} – ${when(props.end, props.zone)}`;
  return (
    <Plate span={6} label={words.title}>
      {range.chart ? (
        <ChartFrame title={words.title} label={label} {...(range.now ? { now: range.now } : {})}
          {...(range.now_status ? { nowStatus: range.now_status } : {})}
          values={[...(range.said ?? []), ...(range.scale ? [[words.isolines, range.scale] as [string, string]] : [])]}
          caption={[range.stale, range.caption, ...range.chart.notes, props.words.zoneNote].filter(Boolean).join(' · ')}>
          <DeffeyesChart chart={range.chart} words={words}>
            {(range.path ?? []).map((points, index) => <polyline key={index} className="deffeyes-track" points={points} />)}
            {(range.dots ?? []).map((dot) => (
              <circle key={dot.at} className="deffeyes-track-dot" cx={dot.x} cy={dot.y} r="3">
                <title>{when(dot.at, props.zone)}</title>
              </circle>
            ))}
            {range.first ? (
              <circle className="deffeyes-track-start" cx={range.first.x} cy={range.first.y} r="5">
                <title>{`${words.first}: ${when(range.first.at, props.zone)}`}</title>
              </circle>
            ) : null}
          </DeffeyesChart>
          {range.scale ? <p className="deffeyes-scale">{range.scale}</p> : null}
          <DeffeyesLegend chart={range.chart} words={words} extra={(
            <>
              <li><span className="deffeyes-swatch deffeyes-swatch-track" aria-hidden="true" />{words.path}</li>
              <li><span className="deffeyes-swatch deffeyes-swatch-track-start" aria-hidden="true" />{words.first}</li>
            </>
          )} />
        </ChartFrame>
      ) : <EmptyState title={words.title}>{range.reason}</EmptyState>}
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
          {props.places.map((each) => {
            const point = props.places.length > 1 ? each.point : null;
            return [
              ...(point ? [<h2 key={`${each.point}-head`} className="ui-plates-head">{point}</h2>] : []),
              ...each.charts.map((chart) => <ParameterChart key={`${each.point}-${chart.quantity.code}`} chart={chart}
                point={point} props={props} markers={markers} />),
              ...Object.entries(each.worked).map(([code, item]) => <WorkedChart key={`${each.point}-${code}`} code={code}
                item={item} point={point} props={props} markers={markers} />),
            ];
          })}
          {props.range_chart ? <RangeDeffeyes range={props.range_chart} props={props} /> : null}
        </Plates>
      ) : <EmptyState title={props.words.empty} />}
      <Plates>
        <Plate title={props.words.events} span={12} link={{ href: props.samples, label: props.words.samples }}>
          {props.events.length ? (
            <Table label={props.words.events} rows={props.events} rowKey={(event) => `${event.kind}-${event.at}-${event.label}`}
              rowStatus={(event) => event.severity}
              columns={[
                { key: 'at', label: props.words.time, render: (event) => event.when },
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
