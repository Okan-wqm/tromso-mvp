// A tab's create or edit form in the new look (core.crud.FormView.page behind ?ui=next; the design's drawer form): the
// form as core/formpayload.py gives it, drawn field by field with the library's form components, its tabs, the History
// tab of an existing record and its delete link. It posts the same names to the same address; the server is the only
// validator and its errors come back in the next payload. Two behaviours of the old page are kept: a field whose value
// changes the form (`data-refresh`) posts the form again with the draft marker, and a select whose options belong to
// another field's value (`data-depends-on`) offers only those. A tab with a form template of its own adds its panels
// (core/formpanels.py): tabs of their own before History, or more on one of the record's tabs after the record's form,
// each a list saved apart (its own form), a table, help, a one-button form or a link; and a refused save may ask the
// withdrawal guard's question above the form (QuestionBox).
import { type FocusEvent, type FormEvent, Fragment, type ReactNode, useEffect, useRef, useState } from 'react';

import { tidy } from '../../date-input.js';
import {
  Acknowledge, AuditItem, Button, Checkbox, CheckboxGroup, Chip, type ChipKind, EmptyState, FileField, FixedField, type IconName,
  LinkButton, LinkList, List, ListCellView, type ListColumn, ListItem, type ListRow, Notice, PermissionMatrix, RadioGroup,
  RowList, SelectField, ServerForm, Table, Tabs, TextField, Icon,
} from '../ui/index.js';

type Value = string | number | boolean | null | string[];
interface Said { text?: string; segments?: ({ text: string } | { href: string; label: string })[] }
interface Option { value: string; label: string; selected: boolean; attrs: Record<string, Value> }
interface Widget {
  kind: string; name: string; value: Value; attrs: Record<string, Value>;
  groups?: { label: string | null; options: Option[] }[];
  columns?: string[]; sections?: { label: string; areas: { label: string; notes: string[]; cells: { action: string; said: string; option: Option | null }[] }[] }[];
  rows?: { pk: string; label: string; group: string; id: string; checked: boolean; primary: boolean; details: Field[] }[];
  primary?: boolean; dependsOn?: string; emptyText?: string; areaLabel?: string; shown?: string;
  current?: { name: string; href: string | null; clearName: string | null; clearId: string | null; clearLabel: string;
    intro?: string; changeLabel?: string } | null;
}
export interface Field {
  name: string; label: string; help: Said | null; required: boolean; disabled: boolean; fieldset: boolean; errors: string[];
  widget: Widget; initial: { name: string; values: string[] } | null;
}
interface Tab { key: string; label: string; help: Said | null; hasErrors: boolean; fieldsets: { label: string; help: Said | null; fields: Field[] }[] }
interface Entry { key: string; action: string; critical: boolean; by: { before: string; name: string; after: string }; when: string;
  changes: { label: string; old: string | null; new: string | null }[] }

export interface RecordFormProps {
  form: { action: string; multipart: boolean; hidden: { name: string; value: Value; kind: string }[]; errors: string[]; tabs: Tab[] };
  csrfToken: string;
  submit: string;
  cancel: { href: string; label: string };
  optional: string;
  tabsLabel: string;
  hasErrors: string;
  /** the tab to open: the tab of the field whose change asked for a draft refresh (a tab with an error comes first) */
  openTab?: string | null;
  delete: { href: string; label: string } | null;
  history: { label: string; intro: string; link: { href: string; label: string }; empty: string; critical: string;
    empty_value: string; entries: Entry[] } | null;
  /** what a refused save asks first (the withdrawal guard's question), above the form's tabs */
  question?: Question | null;
  /** what the tab's own form page adds (core/formpanels.py): tabs of their own, or more on one of the record's tabs */
  panels?: Panel[];
}

/** The withdrawal guard's question (core.formpanels.question): the warnings, and the box to go on or why a second person
 * must approve. */
export interface Question {
  title: string; messages: string[]; secondPerson: string | null;
  box: { name: string; value: string; label: string; help: string } | null;
}
interface RowOf { fields: Field[]; hidden: { name: string; value: Value }[]; errors?: string[] }
/** A list of rows saved as a whole (core.crud.RowList), its own form posted to its own address. */
export interface RowsBlock {
  kind: 'rows'; action: string; version: Value; rowKind: string; columns: string[]; legend: string; empty: string;
  add: string; save: string; remove: string; question: Question | null;
  formset: { prefix: string; management: { name: string; value: Value }[]; errors: string[]; rows: RowOf[]; empty: RowOf };
}
export type Block =
  | { kind: 'help'; text: string }
  | { kind: 'notice'; tone: 'info' | 'warning'; text: string }
  | { kind: 'status'; chip: { kind: ChipKind; text: string }; text: string }
  | { kind: 'table'; label: string; columns: ListColumn[]; rows: ListRow[] }
  | { kind: 'checks'; label: string; lines: { text: string; done: boolean; sub: string }[] }
  | { kind: 'post'; action: string; label: string; primary: boolean; fields: { name: string; value: string }[] }
  | { kind: 'link'; href: string; label: string; icon: IconName | null }
  | { kind: 'notices'; title: string; tone: 'warning' | 'critical'; texts: string[] }
  | FormBlock
  | RowsBlock;
/** A row of a formset drawn as a table: its own heading (a replicate's name) where it has one, a cell a column. */
export interface GridRow { head: string | null; hidden: { name: string; value: Value }[]; errors: string[]; cells: Field[][] }
/** A formset as a table (a feeding table's bands, an experiment's groups): core.formpanels.grid. */
export interface GridPart {
  kind: 'grid'; prefix: string; legend: string; columns: string[]; management: { name: string; value: Value }[];
  errors: string[]; rows: GridRow[]; empty: GridRow | null; add: string | null; addDisabled: boolean; emptyText: string;
}
export interface ButtonPart { kind: 'button'; label: string; name: string; value: string; primary: boolean; disabled: boolean }
export type FormPart = { kind: 'fields'; fields: Field[] } | { kind: 'heading'; text: string } | { kind: 'help'; text: string }
  | ButtonPart | GridPart;
/** A form of its own, saved as a whole to its own address (core.formpanels.form). */
export interface FormBlock {
  kind: 'form'; action: string; label: string; hidden: { name: string; value: Value }[]; errors: string[];
  parts: FormPart[]; actions: ButtonPart[];
}
/** A tab of its own (`tab` null), or more on the record's tab `tab`. */
export interface Panel { key: string; label: string | null; tab: string | null; hasErrors: boolean; blocks: Block[] }

/** A help: its words, or its words and its links to the application's own pages (core.formpayload._Segments). */
const text = (said: Said | null): ReactNode => {
  if (!said) return undefined;
  if (said.segments) {
    return said.segments.map((segment, index) => ('href' in segment
      ? <a key={index} href={segment.href}>{segment.label}</a> : <Fragment key={index}>{segment.text}</Fragment>));
  }
  return said.text;
};
const str = (value: Value): string => (value === null || value === undefined || typeof value === 'boolean' ? '' : Array.isArray(value) ? value.join(',') : String(value));
const options = (widget: Widget) => (widget.groups ?? []).flatMap((group) => group.options);
const attr = (widget: Widget, name: string): string | undefined => {
  const value = widget.attrs[name];
  return value === undefined || value === null || value === false ? undefined : String(value);
};

/** One field of the payload, drawn by its kind. `source` is the value of the field a dependent select follows. In a row of
 * a list (`inRow`) a field is named by the list's heading row: its label is for a screen reader, without help or mark, as
 * the old row (crud/_row.html) draws it; a box keeps its words beside it (Remove, Primary). */
export function FieldOf({ field, optional, source, inRow = false }: { field: Field; optional: string;
  source: (name: string) => string | undefined; inRow?: boolean }) {
  const { widget } = field;
  const base = {
    name: widget.name, label: field.label, help: inRow ? undefined : text(field.help), errors: field.errors,
    // the control is required as the server drew it (a formset's row is not); the mark says what the field is
    required: Boolean(widget.attrs.required), mark: field.required || inRow ? undefined : optional, labelHidden: inRow,
  };
  const initial = field.initial ? field.initial.values.map((value) => <input key={value} type="hidden" name={field.initial?.name} value={value} />) : null;
  const disabledText = (): string => {
    if (widget.kind === 'select' || widget.kind === 'multiselect' || widget.kind === 'radio' || widget.kind === 'checks') {
      return options(widget).filter((option) => option.selected).map((option) => option.label).join(', ');
    }
    return str(widget.value);
  };
  if (widget.kind === 'output' || (field.disabled && !['matrix', 'links', 'checkbox'].includes(widget.kind))) {
    return <>{<FixedField label={field.label} value={widget.kind === 'output' ? widget.shown ?? str(widget.value) : disabledText() || '—'} help={text(field.help)} />}{initial}</>;
  }
  let control: ReactNode;
  switch (widget.kind) {
    case 'select': {
      const follows = widget.attrs['data-depends-on'];
      const chosen = follows ? source(String(follows)) : undefined;
      const offered = (option: Option) => !follows || !option.attrs['data-group'] || chosen === undefined
        || String(option.attrs['data-group']).split(' ').includes(chosen);
      // each group under its heading, as the old page draws it; an option the server switched off stays off
      const groups = (widget.groups ?? []).map((group) => ({ label: group.label, options: group.options.filter(offered)
        .map((option) => ({ value: option.value, label: option.label, disabled: Boolean(option.attrs.disabled) })) }))
        .filter((group) => group.options.length);
      control = <SelectField {...base} key={follows ? `${widget.name}-${chosen ?? ''}` : widget.name} options={[]} groups={groups}
        defaultValue={options(widget).filter(offered).find((option) => option.selected)?.value} />;
      break;
    }
    case 'multiselect':
    case 'checks':
      control = <CheckboxGroup {...base} wide options={options(widget).map((option) => ({ value: option.value, label: option.label,
        disabled: Boolean(option.attrs.disabled) }))}
        defaultValues={options(widget).filter((option) => option.selected).map((option) => option.value)} />;
      break;
    case 'radio':
      control = <RadioGroup {...base} options={options(widget).map((option) => ({ value: option.value, label: option.label,
        disabled: Boolean(option.attrs.disabled) }))} defaultValue={options(widget).find((option) => option.selected)?.value} />;
      break;
    case 'checkbox':
      control = <Checkbox {...base} value={widget.value === null ? undefined : str(widget.value)}
        defaultChecked={Boolean(widget.attrs.checked)} disabled={field.disabled} />;
      break;
    case 'acknowledge':
      control = <Acknowledge name={widget.name} title={field.label} label={field.label} value={str(widget.value)}
        defaultChecked={Boolean(widget.attrs.checked)} errors={field.errors}>{text(field.help)}</Acknowledge>;
      break;
    case 'file':
      control = <FileField {...base} wide accept={attr(widget, 'accept')} current={widget.current ? {
        name: widget.current.name, href: widget.current.href ?? undefined, intro: widget.current.intro ?? field.label,
        changeLabel: widget.current.changeLabel, clearName: widget.current.clearName ?? undefined,
        clearLabel: widget.current.clearLabel } : null} />;
      break;
    case 'matrix':
      control = <PermissionMatrix {...base} areaLabel={widget.areaLabel ?? ''} columns={widget.columns ?? []}
        sections={(widget.sections ?? []).map((section) => ({ label: section.label, areas: section.areas.map((area) => ({
          label: area.label, notes: area.notes, cells: area.cells.map((cell) => (cell.option ? {
            action: cell.action, said: cell.said, value: cell.option.value, checked: cell.option.selected, id: String(cell.option.attrs.id ?? ''),
            requires: cell.option.attrs['data-requires'] ? String(cell.option.attrs['data-requires']) : undefined } : null)) })) }))} />;
      break;
    case 'links':
      control = <LinkList {...base} columns={widget.columns ?? []} primary={widget.primary} emptyText={widget.emptyText}
        group={widget.dependsOn ? source(widget.dependsOn) : undefined}
        rows={(widget.rows ?? []).map((row) => ({ pk: row.pk, label: row.label, group: row.group, checked: row.checked,
          primary: row.primary, details: row.details.map((detail) => <FieldOf key={detail.name} field={detail} optional={optional} source={source} />) }))} />;
      break;
    case 'hidden':
    case 'unshown':
      control = <input type="hidden" name={widget.name} value={str(widget.value)} />;
      break;
    default: {
      const moment = widget.kind === 'moment';
      control = <TextField {...base} defaultValue={str(widget.value)} multiline={widget.kind === 'textarea'}
        wide={widget.kind === 'textarea'} placeholder={attr(widget, 'placeholder')}
        type={(['email', 'url', 'password'] as const).find((kind) => kind === widget.kind) ?? (widget.attrs.type === 'tel' ? 'tel' : 'text')}
        numeric={widget.kind === 'number'} min={attr(widget, 'min')} max={attr(widget, 'max')} step={attr(widget, 'step')}
        maxLength={attr(widget, 'maxlength') ? Number(attr(widget, 'maxlength')) : undefined}
        autoComplete={attr(widget, 'autocomplete')} uppercase={widget.attrs['data-uppercase'] !== undefined}
        dateInput={widget.kind === 'day' ? 'day' : moment ? 'moment' : undefined} />;
    }
  }
  return <>{control}{initial}</>;
}

/** A date box left: its day or moment put dd.mm.yyyy (frontend/date-input.ts), as the old page's date box does. */
function tidied(event: FocusEvent<HTMLDivElement>) {
  const target = event.target as HTMLInputElement;
  const kind = target.dataset?.dateInput;
  if (kind) target.value = tidy(target.value.trim(), kind === 'moment');
}

/** The withdrawal guard's question (farm/_withdrawal_change.html): the warnings, and the box whose value is their
 * fingerprint, so changed warnings are asked again; or, when a second person must approve, why a tick cannot go past. */
export function QuestionBox({ question }: { question: Question }) {
  const warnings = <ul role="list">{question.messages.map((message) => <li key={message}>{message}</li>)}</ul>;
  if (!question.box) {
    return (
      <Notice tone="critical" title={question.title}>
        {warnings}
        {question.secondPerson ? <p className="form-error">{question.secondPerson}</p> : null}
      </Notice>
    );
  }
  return (
    <Acknowledge name={question.box.name} title={question.title} label={question.box.label} value={question.box.value}
      help={question.box.help}>{warnings}</Acknowledge>
  );
}

/** A row of a list as the server drew it: its hidden fields, what is wrong with the row, its fields named by the heading
 * row. An empty row (`index` given) is the formset's empty form at that position (`__prefix__` put to it). */
function RowFields({ row, optional, index }: { row: RowOf; optional: string; index?: number }) {
  const at = index === undefined ? row : JSON.parse(JSON.stringify(row).replace(/__prefix__/g, String(index))) as RowOf;
  // a row added here is taken away by its own button before it is saved: its Remove box would stand in that column
  const fields = index === undefined ? at.fields : at.fields.filter((field) => !field.widget.name.endsWith('-DELETE'));
  return (
    <>
      {at.hidden.map((hidden) => <input key={hidden.name} type="hidden" name={hidden.name} value={str(hidden.value)} />)}
      {at.errors && at.errors.length ? <ul className="errorlist row-error">{at.errors.map((error) => <li key={error}>{error}</li>)}</ul> : null}
      {fields.map((field) => <FieldOf key={field.name} field={field} optional={optional} source={() => undefined} inRow />)}
    </>
  );
}

/** A list of rows saved as a whole, its own form (crud/_row_list.html): the record's version travels with it, so a save
 * based on an outdated record is refused; one row of a list may be its primary one (a contact), ticking it unticks the
 * others, as on the old page. */
function RowsForm({ block, label, csrfToken, optional }: { block: RowsBlock; label: string; csrfToken: string; optional: string }) {
  const { formset } = block;
  const primary = formset.empty.fields.filter((field) => field.widget.attrs['data-primary'] !== undefined)
    .map((field) => field.widget.name.slice(field.widget.name.lastIndexOf('-')));
  const ticked = (event: FormEvent<HTMLDivElement>) => {
    const box = event.target as HTMLInputElement;
    const suffix = primary.find((each) => box.name?.endsWith(each));
    if (!suffix || !box.checked) return;
    box.form?.querySelectorAll<HTMLInputElement>('input[type="checkbox"]').forEach((other) => {
      if (other !== box && other.name.endsWith(suffix)) other.checked = false;
    });
  };
  return (
    <ServerForm action={block.action} csrfToken={csrfToken} label={label} noValidate
      actions={<Button variant="primary" type="submit">{block.save}</Button>}>
      <div className="ui-form-rows" data-wide="" onChange={ticked} onBlur={tidied}>
        {block.version !== null ? <input type="hidden" name="version" value={str(block.version)} /> : null}
        {block.question ? <QuestionBox question={block.question} /> : null}
        <RowList prefix={formset.prefix} management={formset.management.map((each) => ({ name: each.name, value: str(each.value) }))}
          rows={formset.rows.map((row, index) => ({ key: `row-${index}`, content: <RowFields row={row} optional={optional} /> }))}
          newRow={(index) => <RowFields row={formset.empty} optional={optional} index={index} />}
          columns={block.columns} legend={block.legend} addLabel={block.add} removeLabel={block.remove} emptyText={block.empty}
          errors={formset.errors} kind={block.rowKind || undefined} />
      </div>
    </ServerForm>
  );
}

const buttonOf = (part: ButtonPart) => (
  <Button key={`${part.name}-${part.value}-${part.label}`} variant={part.primary ? 'primary' : 'secondary'} type="submit"
    {...(part.name ? { name: part.name, value: part.value } : {})} isDisabled={part.disabled}>{part.label}</Button>
);

/** A formset as a table (farm/_band_row.html, experiments/_group_row.html): its management form kept true (the rows
 * drawn are counted), each row's hidden fields and errors, a cell a column, a row's own heading where it has one, and a
 * row added from the empty form (its __prefix__ put to its position), which takes the focus. */
function GridOf({ part, optional }: { part: GridPart; optional: string }) {
  const [added, setAdded] = useState(0);
  const body = useRef<HTMLTableSectionElement>(null);
  const grown = useRef(false);
  useEffect(() => {
    if (!grown.current) return;
    grown.current = false;
    body.current?.lastElementChild?.querySelector<HTMLElement>('input:not([type="hidden"]), select, textarea')?.focus();
  }, [added]);
  const rows = [...part.rows, ...(part.empty ? Array.from({ length: added }, (_each, index) => JSON.parse(JSON.stringify(part.empty)
    .replace(/__prefix__/g, String(part.rows.length + index))) as GridRow) : [])];
  const total = `${part.prefix}-TOTAL_FORMS`;
  const remove = rows[0]?.cells.at(-1)?.[0]?.label ?? '';
  return (
    <div className="ui-form-grid-rows" data-wide="">
      {part.errors.length ? <Notice tone="critical"><ul className="errorlist">{part.errors.map((each) => <li key={each}>{each}</li>)}</ul></Notice> : null}
      {part.management.map((each) => <input key={each.name} type="hidden" name={each.name} value={each.name === total ? String(rows.length) : str(each.value)} />)}
      {rows.length ? (
        <div className="ui-table-wrap" tabIndex={0} role="region" aria-label={part.legend}>
          <table className="ui-table grid-table">
            <thead><tr>{part.columns.map((column) => <th key={column} scope="col">{column}</th>)}
              {part.columns.length < (rows[0]?.cells.length ?? 0) + (rows[0]?.head !== null ? 1 : 0)
                ? <th scope="col"><span className="sr-only">{remove}</span></th> : null}</tr></thead>
            <tbody ref={body}>
              {rows.map((row, index) => (
                <tr key={`row-${index}`}>
                  {row.head !== null ? <th scope="row">{row.hidden.map((hidden) => <input key={hidden.name} type="hidden" name={hidden.name} value={str(hidden.value)} />)}{row.head}</th> : null}
                  {row.cells.map((cell, at) => (
                    <td key={cell.map((field) => field.name).join(' ') || at}>
                      {at === 0 && row.head === null ? row.hidden.map((hidden) => <input key={hidden.name} type="hidden" name={hidden.name} value={str(hidden.value)} />) : null}
                      {at === 0 && row.errors.length ? <ul className="errorlist row-error">{row.errors.map((each) => <li key={each}>{each}</li>)}</ul> : null}
                      {cell.map((field) => <FieldOf key={field.name} field={field} optional={optional} source={() => undefined} inRow />)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (part.emptyText ? <p className="contact-empty">{part.emptyText}</p> : null)}
      {part.add !== null ? (
        <div className="ui-form-actions">
          <button type="button" className="ui-btn" disabled={part.addDisabled || !part.empty}
            onClick={() => { grown.current = true; setAdded(added + 1); }}><Icon name="plus" />{part.add}</button>
        </div>
      ) : null}
    </div>
  );
}

/** A form of its own on the record's page (a feeding table, an experiment's design or places), saved as a whole. A field
 * that changes the form itself (data-refresh: the temperature columns, a factor's name) posts it again with the draft
 * marker, nothing saved, as the old page does. */
function OwnForm({ block, csrfToken, optional }: { block: FormBlock; csrfToken: string; optional: string }) {
  const changed = (event: FormEvent<HTMLDivElement>) => {
    const target = event.target as HTMLInputElement | HTMLSelectElement;
    const marker = target.dataset?.refresh;
    if (!marker || !target.form) return;
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = marker;
    input.value = target.name;
    target.form.append(input);
    target.form.requestSubmit();
  };
  return (
    <ServerForm action={block.action} csrfToken={csrfToken} label={block.label} formErrors={block.errors} noValidate
      actions={<>{block.actions.map(buttonOf)}</>}>
      {block.hidden.map((hidden) => <input key={hidden.name} type="hidden" name={hidden.name} value={str(hidden.value)} />)}
      <div className="ui-form-own" data-wide="" onChange={changed} onBlur={tidied}>
        {block.parts.map((part, index) => {
          switch (part.kind) {
            case 'fields':
              return <div key={index} className="ui-form-grid">{part.fields.map((field) => <FieldOf key={field.name} field={field} optional={optional} source={() => undefined} />)}</div>;
            case 'heading':
              return <h3 key={index} className="ui-form-group">{part.text}</h3>;
            case 'help':
              return <p key={index} className="help">{part.text}</p>;
            case 'button':
              return <p key={index}>{buttonOf(part)}</p>;
            case 'grid':
              return <GridOf key={index} part={part} optional={optional} />;
            default:
              return null;
          }
        })}
      </div>
    </ServerForm>
  );
}

/** One block of a panel, drawn with the library. */
function BlockOf({ block, label, csrfToken, optional }: { block: Block; label: string; csrfToken: string; optional: string }) {
  switch (block.kind) {
    case 'help':
      return <p className="help">{block.text}</p>;
    case 'notice':
      return <Notice tone={block.tone === 'warning' ? 'warning' : 'neutral'}>{block.text}</Notice>;
    case 'status':
      return <p><Chip kind={block.chip.kind}>{block.chip.text}</Chip> {block.text}</p>;
    case 'table':
      return (
        <Table<ListRow> label={block.label} rows={block.rows} rowKey={(row) => row.key}
          columns={block.columns.map((column, index) => ({ key: column.key, label: column.label, numeric: Boolean(column.numeric),
            rowHeader: index === 0, render: (row: ListRow) => { const cell = row.cells[column.key]; return cell ? <ListCellView cell={cell} /> : null; } }))} />
      );
    case 'checks':
      return (
        <List label={block.label}>
          {block.lines.map((line, index) => (
            <ListItem key={`${index}-${line.text}`} main={<><span aria-hidden="true">{line.done ? '☑' : '☐'}</span> {line.text}</>}
              sub={line.sub || undefined} />
          ))}
        </List>
      );
    case 'post':
      return (
        <ServerForm action={block.action} csrfToken={csrfToken} label={block.label}
          actions={<Button variant={block.primary ? 'primary' : 'secondary'} type="submit">{block.label}</Button>}>
          {block.fields.map((field) => <input key={field.name} type="hidden" name={field.name} value={field.value} />)}
        </ServerForm>
      );
    case 'link':
      return <p><LinkButton href={block.href} {...(block.icon ? { icon: block.icon } : {})}>{block.label}</LinkButton></p>;
    case 'rows':
      return <RowsForm block={block} label={label} csrfToken={csrfToken} optional={optional} />;
    case 'notices':
      return (
        <Notice tone={block.tone} title={block.title}>
          <ul role="list">{block.texts.map((each) => <li key={each}>{each}</li>)}</ul>
        </Notice>
      );
    case 'form':
      return <OwnForm block={block} csrfToken={csrfToken} optional={optional} />;
    default:
      return null;
  }
}

function PanelBlocks({ panel, label, csrfToken, optional }: { panel: Panel; label: string; csrfToken: string; optional: string }) {
  return <div className="ui-form-panel">{panel.blocks.map((block, index) => <BlockOf key={`${block.kind}-${index}`} block={block} label={label} csrfToken={csrfToken} optional={optional} />)}</div>;
}

export function RecordForm({ form, csrfToken, submit, cancel, optional, tabsLabel, hasErrors, openTab, delete: remove, history,
  question, panels = [] }: RecordFormProps) {
  const holder = useRef<HTMLDivElement>(null);
  // Back from the browser's history (bfcache) after a draft refresh, the draft marker must not go with the next Save.
  useEffect(() => {
    const back = (event: PageTransitionEvent) => {
      if (event.persisted) holder.current?.closest('form')?.querySelectorAll('input[name="_draft"]').forEach((marker) => marker.remove());
    };
    window.addEventListener('pageshow', back);
    return () => window.removeEventListener('pageshow', back);
  }, []);
  const fields = form.tabs.flatMap((tab) => tab.fieldsets.flatMap((fieldset) => fieldset.fields));
  const initialValues: Record<string, string> = {};
  for (const field of fields) {
    if (field.widget.kind === 'select') initialValues[field.widget.name] = options(field.widget).find((option) => option.selected)?.value ?? '';
  }
  const [values, setValues] = useState(initialValues);
  const refresh = new Set(fields.filter((field) => field.widget.attrs['data-refresh']).map((field) => field.widget.name));
  const changed = (event: FormEvent<HTMLDivElement>) => {
    const target = event.target as HTMLInputElement | HTMLSelectElement;
    if (!target.name) return;
    if (target instanceof HTMLSelectElement) setValues((was) => ({ ...was, [target.name]: target.value }));
    if (refresh.has(target.name) && target.form) {
      // The old page's draft refresh (TabbedForm.refresh_on): the form again with what was entered, nothing saved.
      const marker = document.createElement('input');
      marker.type = 'hidden';
      marker.name = '_draft';
      marker.value = target.name;
      target.form.append(marker);
      target.form.requestSubmit();
    }
  };
  const left = tidied;
  const fieldOf = (field: Field) => <FieldOf key={field.name} field={field} optional={optional} source={(name) => values[name]} />;
  // A tab is the design's two-column field grid; a group of fields (Fieldset) heads its fields across the grid.
  const panel = (tab: Tab) => (
    <div className="ui-form-grid">
      {tab.help ? <p className="help" data-wide="">{text(tab.help)}</p> : null}
      {tab.fieldsets.map((fieldset, index) => (
        <Fragment key={fieldset.label || `plain-${index}`}>
          {fieldset.label ? <h3 className="ui-form-group">{fieldset.label}</h3> : null}
          {fieldset.help ? <p className="help" data-wide="">{text(fieldset.help)}</p> : null}
          {fieldset.fields.map(fieldOf)}
        </Fragment>
      ))}
    </div>
  );
  const items = form.tabs.map((tab) => ({ id: tab.key, label: tab.hasErrors ? <>{tab.label}<span className="sr-only"> {hasErrors}</span></> : tab.label,
    content: panel(tab), ...(tab.hasErrors ? { count: <Chip kind="critical">!</Chip> } : {}) }));
  if (history) {
    items.push({ id: 'history', label: history.label, content: (
      <>
        <p className="help">{history.intro} <a href={history.link.href}>{history.link.label}</a></p>
        {history.entries.length ? (
          <List ordered label={history.label}>
            {history.entries.map((entry) => (
              <AuditItem key={entry.key} action={entry.action} record="" status={entry.critical ? 'critical' : undefined}
                critical={entry.critical ? <Chip kind="critical">{history.critical}</Chip> : undefined}
                who={<>{entry.by.before} <strong>{entry.by.name}</strong> {entry.by.after} · {entry.when}</>}>
                {entry.changes.length ? (
                  <dl className="ui-changes">
                    {entry.changes.map((change) => (
                      <div key={change.label}>
                        <dt>{change.label}</dt>
                        <dd>{change.old !== null ? <><del>{change.old ?? history.empty_value}</del> → </> : null}
                          <ins>{change.new ?? history.empty_value}</ins></dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
              </AuditItem>
            ))}
          </List>
        ) : <EmptyState title={history.empty} />}
      </>
    ) });
  }
  // The tab's own panels: a tab of its own after the record's tabs and before History (crud/form.html's extra_tabs), or
  // more on one of the record's tabs, after the record's form (extra_panels: a list is a form of its own, never inside
  // the record's).
  const own = panels.filter((each) => !each.tab || !form.tabs.some((tab) => tab.key === each.tab));
  const onTab = panels.filter((each) => !own.includes(each));
  const at = history ? items.length - 1 : items.length;
  items.splice(at, 0, ...own.map((each) => ({
    id: each.key, label: each.hasErrors ? <>{each.label}<span className="sr-only"> {hasErrors}</span></> : each.label ?? each.key,
    content: <PanelBlocks panel={each} label={each.label ?? submit} csrfToken={csrfToken} optional={optional} />,
    ...(each.hasErrors ? { count: <Chip kind="critical">!</Chip> } : {}) })));
  const recordTabs = new Set(form.tabs.map((tab) => tab.key));
  const opened = (key: string | null | undefined) => (key && items.some((item) => item.id === key) ? key : undefined);
  const [selected, select] = useState(form.tabs.find((tab) => tab.hasErrors)?.key ?? own.find((each) => each.hasErrors)?.key
    ?? opened(openTab) ?? items[0]?.id ?? '');
  const tabbed = items.length > 1;
  const recordForm = (body: ReactNode) => (
    <ServerForm action={form.action} csrfToken={csrfToken} formErrors={form.errors} label={submit} multipart={form.multipart} noValidate
      actions={<>
        {remove ? <LinkButton href={remove.href} variant="danger-text">{remove.label}</LinkButton> : null}
        <LinkButton href={cancel.href}>{cancel.label}</LinkButton>
        <Button variant="primary" type="submit">{submit}</Button>
      </>}>
      {form.hidden.map((hidden) => <input key={hidden.name} type="hidden" name={hidden.name} value={str(hidden.value)} />)}
      {question ? <div data-wide=""><QuestionBox question={question} /></div> : null}
      <div className="ui-form-body" data-wide="" ref={holder} onChange={changed} onBlur={left}>{body}</div>
    </ServerForm>
  );
  // more on a record's tab: in sight while that tab is (every tab's while there are no tabs)
  const extras = onTab.map((each) => (
    <div key={`on-${each.key}`} hidden={tabbed && selected !== each.tab ? true : undefined}>
      <PanelBlocks panel={each} label={each.label ?? submit} csrfToken={csrfToken} optional={optional} />
    </div>
  ));
  if (!tabbed) return <>{recordForm(items[0]?.content)}{extras}</>;
  return (
    <Tabs label={tabsLabel} items={items} keepMounted selected={selected} onChange={select}
      layout={(panel) => (
        <>
          {/* the record's form and its actions stand with the record's own tabs; a list's tab has its own Save */}
          <div hidden={recordTabs.has(selected) ? undefined : true}>
            {recordForm(items.filter((item) => recordTabs.has(item.id)).map((item) => panel(item.id)))}
          </div>
          {extras}
          {items.filter((item) => !recordTabs.has(item.id)).map((item) => panel(item.id))}
        </>
      )} />
  );
}
