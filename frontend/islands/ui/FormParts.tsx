// The form layer's other controls (README, Shared form parts: core/formpayload.py): every widget kind a form of the
// project has beside the text, select and box-group fields of Field.tsx. Each draws the markup the server's own widget
// template draws (templates/registration/_field.html and the widget templates: .check, .matrix, .links, .contact-row,
// .file-current), so the same style sheets dress it in both looks, and each posts the same names and values as the old
// page (core/tests_formpayload.py is the oracle: the payload's controls equal the old markup's). Every word comes from
// the server; nothing is validated here.
import { type ReactNode, useEffect, useId, useRef, useState } from 'react';

import { FieldMark } from './Field.js';
import { Icon } from './Icon.js';

interface Said {
  help?: ReactNode | undefined;
  errors?: string[] | undefined;
  mark?: ReactNode | undefined;
}

function Described({ id, help, errors }: { id: string; help?: ReactNode | undefined; errors?: string[] | undefined }) {
  return (
    <>
      {help ? <div className="help" id={`${id}-help`}>{help}</div> : null}
      {errors && errors.length ? (
        <ul className="errorlist" id={`${id}-errors`}>
          {errors.map((message) => <li key={message} className="ui-field-error"><Icon name="octagon" />{message}</li>)}
        </ul>
      ) : null}
    </>
  );
}

function described(id: string, help?: ReactNode, errors?: string[]): string | undefined {
  const ids = [help ? `${id}-help` : '', errors && errors.length ? `${id}-errors` : ''].filter(Boolean);
  return ids.length ? ids.join(' ') : undefined;
}

export interface CheckboxProps extends Said {
  name: string;
  label: ReactNode;
  /** the value it posts when ticked ('on' when the server gives none) */
  value?: string | undefined;
  defaultChecked?: boolean | undefined;
  disabled?: boolean | undefined;
  required?: boolean | undefined;
}

/** One box (Active, Only while on shift): the label beside it, as the old field's `label.check`. */
export function Checkbox({ name, label, value, defaultChecked, disabled, required, help, errors, mark }: CheckboxProps) {
  const id = useId();
  const invalid = Boolean(errors && errors.length);
  return (
    <div className={invalid ? 'field has-error' : 'field'}>
      <label className="check">
        <input type="checkbox" id={id} name={name} value={value ?? 'on'} defaultChecked={defaultChecked} disabled={disabled}
          required={required} aria-invalid={invalid || undefined} aria-describedby={described(id, help, errors)} />
        {' '}{label}<FieldMark mark={mark} />
      </label>
      <Described id={id} help={help} errors={errors} />
    </div>
  );
}

export interface ChoiceOption { value: string; label: string; disabled?: boolean | undefined }

export interface RadioGroupProps extends Said {
  name: string;
  label: ReactNode;
  options: ChoiceOption[];
  defaultValue?: string | undefined;
  required?: boolean | undefined;
  disabled?: boolean | undefined;
  wide?: boolean | undefined;
}

/** One of several, each a radio button: a fieldset named by its legend. */
export function RadioGroup({ name, label, options, defaultValue, required, disabled, wide, help, errors, mark }: RadioGroupProps) {
  const id = useId();
  const invalid = Boolean(errors && errors.length);
  return (
    <fieldset className={invalid ? 'field field-set has-error' : 'field field-set'} data-wide={wide ? '' : undefined}
      disabled={disabled} aria-invalid={invalid || undefined} aria-describedby={described(id, help, errors)}>
      <legend>{label}<FieldMark mark={mark} /></legend>
      <div className="ui-checks">
        {options.map((option) => (
          <label key={option.value} className="ui-check">
            <input type="radio" name={name} value={option.value} defaultChecked={option.value === defaultValue}
              required={required} disabled={option.disabled} />
            {option.label}
          </label>
        ))}
      </div>
      <Described id={id} help={help} errors={errors} />
    </fieldset>
  );
}

export interface FileFieldProps extends Said {
  name: string;
  label: ReactNode;
  accept?: string | undefined;
  required?: boolean | undefined;
  disabled?: boolean | undefined;
  wide?: boolean | undefined;
  /** the file the record has: its name and address, the words before it, and the box that removes it */
  current?: {
    name: string;
    href?: string | undefined;
    intro: ReactNode;
    clearName?: string | undefined;
    clearLabel?: ReactNode;
    changeLabel?: ReactNode;
  } | null | undefined;
}

/** A file to send (a library document's PDF): the record's file by its own name, a box to remove it, the input. */
export function FileField({ name, label, accept, required, disabled, wide, current, help, errors, mark }: FileFieldProps) {
  const id = useId();
  const invalid = Boolean(errors && errors.length);
  return (
    <div className={invalid ? 'field has-error' : 'field'} data-wide={wide ? '' : undefined}>
      <label htmlFor={id}>{label}<FieldMark mark={mark} /></label>
      {current ? (
        <>
          <p className="file-current">{current.intro} {current.href ? <a href={current.href} target="_blank" rel="noopener">{current.name}</a> : current.name}</p>
          {current.clearName && !required ? (
            <label className="check"><input type="checkbox" name={current.clearName} disabled={disabled} /> {current.clearLabel}</label>
          ) : null}
          {current.changeLabel ? <p className="file-change">{current.changeLabel}</p> : null}
        </>
      ) : null}
      <input type="file" id={id} name={name} accept={accept} required={required} disabled={disabled}
        aria-invalid={invalid || undefined} aria-describedby={described(id, help, errors)} />
      <Described id={id} help={help} errors={errors} />
    </div>
  );
}

export interface AcknowledgeProps extends Said {
  name: string;
  /** what the warnings are: the block's title ("Before handling") */
  title: ReactNode;
  /** the warnings, in words */
  children: ReactNode;
  /** the box's words ("I have read this and go on") */
  label: ReactNode;
  /** the warnings' fingerprint: what is acknowledged, so a change meanwhile is not taken as read */
  value: string;
  defaultChecked?: boolean | undefined;
}

/** The design's critical acknowledgement: going on past handling warnings is stored and logged as critical. */
export function Acknowledge({ name, title, children, label, value, defaultChecked, help, errors }: AcknowledgeProps) {
  const id = useId();
  const invalid = Boolean(errors && errors.length);
  return (
    <div className="ui-notice ui-ack" data-tone="critical" role="group" aria-labelledby={`${id}-title`}>
      <Icon name="octagon" />
      <div className="ui-notice-body">
        <strong className="ui-notice-title" id={`${id}-title`}>{title}</strong>
        {children}
        <label className="check ui-ack-box">
          <input type="checkbox" id={id} name={name} value={value} defaultChecked={defaultChecked}
            aria-invalid={invalid || undefined} aria-describedby={described(id, help, errors)} />
          {' '}{label}
        </label>
        <Described id={id} help={help} errors={errors} />
      </div>
    </div>
  );
}

/** `said`: the box's name for a screen reader, as the server words it ("Sites: Read") */
export interface MatrixCell { action: string; said: string; value: string; checked: boolean; requires?: string | undefined; id: string }
export interface MatrixArea { label: string; notes: string[]; cells: (MatrixCell | null)[] }

export interface PermissionMatrixProps extends Said {
  name: string;
  label: ReactNode;
  /** the head of the areas' column ("Area") and of each action's */
  areaLabel: string;
  columns: string[];
  sections: { label: string; areas: MatrixArea[] }[];
}

/** A role's rights, an area per row and an action per column, as the server's PermissionMatrix draws them. A Create,
 * Edit or Delete box needs its row's Read, as on the old page (frontend/components.ts, data-requires): ticking one ticks
 * Read, unticking Read unticks them (core.access.implied adds Read on save all the same). Posts one value per ticked box. */
export function PermissionMatrix({ name, label, areaLabel, columns, sections, help, errors, mark }: PermissionMatrixProps) {
  const id = useId();
  const initial: Record<string, boolean> = {};
  for (const section of sections) for (const area of section.areas) for (const cell of area.cells) if (cell) initial[cell.id] = cell.checked;
  const [ticked, setTicked] = useState(initial);
  const needing: Record<string, string[]> = {};
  for (const section of sections) {
    for (const area of section.areas) {
      for (const cell of area.cells) if (cell?.requires) (needing[cell.requires] ??= []).push(cell.id);
    }
  }
  const toggle = (cell: MatrixCell, on: boolean) => {
    setTicked((was) => {
      const next = { ...was, [cell.id]: on };
      if (on && cell.requires) next[cell.requires] = true;
      if (!on) for (const other of needing[cell.id] ?? []) next[other] = false;
      return next;
    });
  };
  const invalid = Boolean(errors && errors.length);
  return (
    <fieldset className={invalid ? 'field field-set has-error' : 'field field-set'} data-wide=""
      aria-describedby={described(id, help, errors)} aria-invalid={invalid || undefined}>
      <legend>{label}<FieldMark mark={mark} /></legend>
      <div className="ui-table-wrap">
        <table className="matrix">
          <thead>
            <tr><th scope="col">{areaLabel}</th>{columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr>
          </thead>
          {sections.map((section) => (
            <tbody key={section.label}>
              <tr className="matrix-group"><th scope="colgroup" colSpan={columns.length + 1}>{section.label}</th></tr>
              {section.areas.map((area) => [
                <tr key={area.label}>
                  <th scope="row">{area.label}</th>
                  {area.cells.map((cell, index) => (
                    <td key={columns[index] ?? index}>
                      {cell ? (
                        <label className="matrix-check">
                          <input type="checkbox" name={name} value={cell.value} id={cell.id} checked={Boolean(ticked[cell.id])}
                            onChange={(event) => toggle(cell, event.currentTarget.checked)} />
                          <span className="sr-only">{cell.said}</span>
                        </label>
                      ) : null}
                    </td>
                  ))}
                </tr>,
                area.notes.length ? (
                  <tr key={`${area.label}-notes`} className="matrix-note">
                    <td colSpan={columns.length + 1}>{area.notes.map((note) => <span key={note} className="row-sub">{note}</span>)}</td>
                  </tr>
                ) : null,
              ])}
            </tbody>
          ))}
        </table>
      </div>
      <Described id={id} help={help} errors={errors} />
    </fieldset>
  );
}

export interface LinkRow {
  pk: string;
  label: string;
  group?: string | undefined;
  checked: boolean;
  primary: boolean;
  /** the primary mark's words for a screen reader, as the server said them for this row (else `primaryWords`) */
  said?: string | undefined;
  /** the inputs of the link's details, drawn by the caller with the field components */
  details?: ReactNode;
}

export interface LinkListProps extends Said {
  name: string;
  label: ReactNode;
  rows: LinkRow[];
  /** the heads of the details' columns */
  columns: string[];
  /** a primary radio per row, named "<name>-primary", headed by `primaryLabel` */
  primary?: boolean | undefined;
  primaryLabel?: string | undefined;
  /** "<record> is the primary one", for a screen reader: the record's place is %(record)s */
  primaryWords?: string | undefined;
  /** the value of the field the rows belong to (a production department): only the rows of it are offered */
  group?: string | undefined;
  emptyText?: ReactNode;
}

/** A record's links to records of another table (core.links: the systems a piece of equipment serves): a box per record,
 * the primary one marked, the link's details beside it. Only the rows of the chosen `group` are shown, as the browser
 * guides; the server decides. */
export function LinkList({ name, label, rows, columns, primary, primaryLabel, primaryWords, group, emptyText, help, errors, mark }: LinkListProps) {
  const id = useId();
  const invalid = Boolean(errors && errors.length);
  const shown = rows.filter((row) => group === undefined || !row.group || row.group.split(' ').includes(group));
  return (
    <fieldset className={invalid ? 'field field-set has-error' : 'field field-set'} data-wide=""
      aria-describedby={described(id, help, errors)} aria-invalid={invalid || undefined}>
      <legend>{label}<FieldMark mark={mark} /></legend>
      <div className="links">
        {shown.length ? (
          <div className="link-head" aria-hidden="true">
            <span className="link-name" />
            {primary ? <span className="link-primary">{primaryLabel}</span> : null}
            {columns.map((column) => <span key={column} className="link-detail">{column}</span>)}
          </div>
        ) : null}
        {shown.map((row) => (
          <div key={row.pk} className="link-row">
            <label className="check link-name"><input type="checkbox" name={name} value={row.pk} defaultChecked={row.checked} /> {row.label}</label>
            {primary ? (
              <label className="check link-primary">
                <input type="radio" name={`${name}-primary`} value={row.pk} defaultChecked={row.primary} />
                <span className="sr-only">{row.said ?? (primaryWords ?? '%(record)s').replace('%(record)s', row.label)}</span>
              </label>
            ) : null}
            {row.details}
          </div>
        ))}
        {shown.length ? null : <p className="link-none">{emptyText}</p>}
      </div>
      <Described id={id} help={help} errors={errors} />
    </fieldset>
  );
}

export interface RowListProps {
  /** the formset's prefix: its management fields are <prefix>-TOTAL_FORMS, -INITIAL_FORMS, -MIN_NUM_FORMS, -MAX_NUM_FORMS */
  prefix: string;
  /** the management fields as the server gave them */
  management: { name: string; value: string }[];
  /** the rows the record has: drawn by the caller (their fields, their DELETE box) */
  rows: { key: string; content: ReactNode }[];
  /** a new row at a position: the caller draws the formset's empty form with __prefix__ put to `index` */
  newRow: (index: number) => ReactNode;
  /** the columns' heads */
  columns: string[];
  legend: string;
  addLabel: ReactNode;
  removeLabel: string;
  emptyText: ReactNode;
  errors?: string[] | undefined;
  /** the class giving the heading row and the rows their columns (components.css: calibration-row, team-row) */
  kind?: string | undefined;
}

/** A list of rows saved as a whole (core.crud.RowList: a site's contacts, a task's checklist): the formset's table, a
 * row added from its empty form, a new row taken away again before it is saved, and the management form kept true (the
 * count of rows is what is drawn). A saved row is removed by its own DELETE box, as the server's formset asks. */
export function RowList({ prefix, management, rows, newRow, columns, legend, addLabel, removeLabel, emptyText, errors, kind }: RowListProps) {
  const row = (base: string) => (kind ? `${base} ${kind}` : base);
  const [added, setAdded] = useState<number[]>([]);
  const [next, setNext] = useState(0);
  const total = rows.length + added.length;
  // A row just added takes the focus on its first box, as on the old page.
  const list = useRef<HTMLDivElement>(null);
  const grown = useRef(false);
  useEffect(() => {
    if (!grown.current) return;
    grown.current = false;
    list.current?.lastElementChild?.querySelector<HTMLElement>('input:not([type="hidden"]), select, textarea')?.focus();
  }, [added]);
  const field = (suffix: string) => management.find((each) => each.name === `${prefix}-${suffix}`);
  return (
    <div className="row-list">
      {errors && errors.length ? (
        <div className="ui-notice" data-tone="critical" role="alert">
          <Icon name="octagon" />
          <ul className="ui-notice-body errorlist">{errors.map((message) => <li key={message}>{message}</li>)}</ul>
        </div>
      ) : null}
      {management.map((each) => (
        <input key={each.name} type="hidden" name={each.name}
          value={each.name === `${prefix}-TOTAL_FORMS` ? String(total) : each.value} />
      ))}
      {field('TOTAL_FORMS') ? null : <input type="hidden" name={`${prefix}-TOTAL_FORMS`} value={String(total)} />}
      {columns.length ? <div className={row("row-list-head")} aria-hidden="true">{columns.map((column) => <span key={column}>{column}</span>)}</div> : null}
      <div className="contact-rows" ref={list}>
        {rows.map((each) => <fieldset key={each.key} className={row("contact-row")}><legend className="sr-only">{legend}</legend>{each.content}</fieldset>)}
        {added.map((key, position) => (
          <fieldset key={`new-${key}`} className={row("contact-row")}>
            <legend className="sr-only">{legend}</legend>
            {newRow(rows.length + position)}
            <button type="button" className="icon-button icon-button-danger" aria-label={removeLabel}
              onClick={() => setAdded((was) => was.filter((each) => each !== key))}><Icon name="x" /></button>
          </fieldset>
        ))}
      </div>
      {total ? null : <p className="contact-empty">{emptyText}</p>}
      <div className="ui-form-actions">
        <button type="button" className="ui-btn" onClick={() => { grown.current = true; setAdded((was) => [...was, next]); setNext(next + 1); }}>
          <Icon name="plus" />{addLabel}
        </button>
      </div>
    </div>
  );
}
