// The Water Quality Management Chart (a Deffeyes diagram) as a typed SVG of the server's geometry: farm/water/deffeyes.py
// `render` places every part in pixels (the isolines and their pH labels, the regions and their borders, the Ω lines, the
// water's star, the ticks) and `as_props` hands them over; the island only draws them, with the classes the server's own
// SVG uses (templates/farm/_deffeyes_chart.html, static/css/components.css), so both look alike. No chemistry, no
// placing, no markup string: what is not in the props is not drawn. `children` draws over the plot in the same pixels (a
// path through a time, on Tank › Water).
import type { ReactNode } from 'react';

interface Tick { at: string; label: string }
interface Named { key: string; name: string; points: string }

export interface DeffeyesDrawing {
  width: number;
  height: number;
  plot: { left: number; top: number; right: number; bottom: number; size: number; centre_x: number; centre_y: number;
    x_tick_y: number; y_tick_x: number; x_title_y: number; y_title_x: number };
  x_ticks: Tick[];
  y_ticks: Tick[];
  isolines: { ph: string; labelled: boolean; colour: string; points: string;
    label: { x: string; y: string; angle: string; text: string } | null }[];
  regions: Named[];
  boundaries: Named[];
  omega: Named[];
  legend: { key: string; name: string }[];
  point: { x: string; y: string; star: string };
  notes: string[];
}

export interface DeffeyesWords {
  water: string;
  dic: string;
  alkalinity: string;
  isolines: string;
}

/** `label`: the drawing's name when it stands alone; without it the drawing is inside a ChartFrame, which names it. */
export function DeffeyesChart({ chart, words, label, children }: {
  chart: DeffeyesDrawing; words: DeffeyesWords; label?: string; children?: ReactNode;
}) {
  const { plot } = chart;
  return (
    <svg className="deffeyes-chart" viewBox={`0 0 ${chart.width} ${chart.height}`} {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}>
      <g className="deffeyes-grid">
        {chart.x_ticks.map((tick) => <line key={`x${tick.at}`} x1={tick.at} y1={plot.top} x2={tick.at} y2={plot.bottom} />)}
        {chart.y_ticks.map((tick) => <line key={`y${tick.at}`} x1={plot.left} y1={tick.at} x2={plot.right} y2={tick.at} />)}
      </g>
      {chart.regions.map((region) => (
        <polygon key={region.key} className={`deffeyes-zone deffeyes-zone-${region.key}`} points={region.points}>
          <title>{region.name}</title>
        </polygon>
      ))}
      {chart.boundaries.map((line, index) => (
        <polyline key={`${line.key}-${index}`} className={`deffeyes-border deffeyes-border-${line.key}`} points={line.points} />
      ))}
      <g className="deffeyes-isolines">
        {chart.isolines.map((isoline) => (
          <polyline key={isoline.ph} className={isoline.labelled ? 'deffeyes-isoline is-labelled' : 'deffeyes-isoline'}
            stroke={isoline.colour} points={isoline.points} />
        ))}
        {chart.isolines.map((isoline) => (isoline.label ? (
          <text key={`label-${isoline.ph}`} className="deffeyes-ph" fill={isoline.colour}
            transform={`translate(${isoline.label.x} ${isoline.label.y}) rotate(${isoline.label.angle})`}>{isoline.label.text}</text>
        ) : null))}
      </g>
      {chart.omega.map((line, index) => (
        <polyline key={`${line.key}-${index}`} className={`deffeyes-omega deffeyes-omega-${line.key}`} points={line.points}>
          <title>{line.name}</title>
        </polyline>
      ))}
      {children}
      <polygon className="deffeyes-point" points={chart.point.star}><title>{words.water}</title></polygon>
      <rect className="deffeyes-frame" x={plot.left} y={plot.top} width={plot.size} height={plot.size} />
      <g className="deffeyes-ticks">
        {chart.x_ticks.map((tick) => <text key={`x${tick.at}`} x={tick.at} y={plot.x_tick_y} textAnchor="middle">{tick.label}</text>)}
        {chart.y_ticks.map((tick) => (
          <text key={`y${tick.at}`} x={plot.y_tick_x} y={tick.at} textAnchor="end" dominantBaseline="middle">{tick.label}</text>
        ))}
      </g>
      <text className="deffeyes-axis" x={plot.centre_x} y={plot.x_title_y} textAnchor="middle">{words.dic}</text>
      <text className="deffeyes-axis" transform={`translate(${plot.y_title_x} ${plot.centre_y}) rotate(-90)`}
        textAnchor="middle">{words.alkalinity}</text>
    </svg>
  );
}

/** The chart's legend, as the server's: the water's star, the isolines, each region and Ω line by its name. */
export function DeffeyesLegend({ chart, words, extra }: { chart: DeffeyesDrawing; words: DeffeyesWords; extra?: ReactNode }) {
  return (
    <ul className="deffeyes-legend">
      <li>
        <svg className="deffeyes-key" viewBox="0 0 16 16" aria-hidden="true">
          <polygon className="deffeyes-point" points="8,0.5 9.8,5.6 15.1,5.7 10.9,9 12.4,14.1 8,11.1 3.6,14.1 5.1,9 0.9,5.7 6.2,5.6" />
        </svg>
        {words.water}
      </li>
      {extra}
      {chart.isolines.length ? <li><span className="deffeyes-swatch deffeyes-swatch-isolines" aria-hidden="true" />{words.isolines}</li> : null}
      {chart.legend.map((item) => (
        <li key={item.key}><span className={`deffeyes-swatch deffeyes-swatch-${item.key}`} aria-hidden="true" />{item.name}</li>
      ))}
    </ul>
  );
}
