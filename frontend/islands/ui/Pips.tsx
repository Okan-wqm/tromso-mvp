// A day's meals as pips (static/css/ui.css, .ui-pips; templates/farm/_meal_board_table.html draws the same pips on the
// server): one pip per planned meal, filled for a meal given, ringed for the next one, dashed for the later ones. The pips
// are drawn for the eye only (aria-hidden spans inside an element named by `label`, "2 of 4 meals done"): the words say
// the count, so the pips are never the only cue. The states and the words come from the server.

export type PipState = 'done' | 'next' | '';

export interface PipsProps {
  /** one state per planned meal, in order */
  states: PipState[];
  /** the meals in words ("2 of 4 meals done") */
  label: string;
}

export function Pips({ states, label }: PipsProps) {
  return (
    <span className="ui-pips" role="img" aria-label={label}>
      {states.map((state, index) => <span key={index} className="ui-pip" data-state={state || undefined} />)}
    </span>
  );
}
