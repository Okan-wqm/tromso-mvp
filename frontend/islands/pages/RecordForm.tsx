// A tab's create or edit form in the new look (core.crud.FormView.page behind ?ui=next; the design's drawer form): the
// form as core/formpayload.py gives it, drawn field by field with the library's form components, its tabs, the History
// tab of an existing record and its delete link. It posts the same names to the same address; the server is the only
// validator and its errors come back in the next payload. Two behaviours of the old page are kept: a field whose value
// changes the form (`data-refresh`) posts the form again with the draft marker, and a select whose options belong to
// another field's value (`data-depends-on`) offers only those.
import { type FocusEvent, type FormEvent, Fragment, type ReactNode, useRef, useState } from 'react';

import { tidy } from '../../date-input.js';
import {
  Acknowledge, AuditItem, Button, Checkbox, CheckboxGroup, Chip, EmptyState, FileField, FixedField, LinkButton, LinkList,
  List, PermissionMatrix, RadioGroup, SelectField, ServerForm, Tabs, TextField,
} from '../ui/index.js';

type Value = string | number | boolean | null | string[];
interface Said { text?: string; html?: string }
interface Option { value: string; label: string; selected: boolean; attrs: Record<string, Value> }
interface Widget {
  kind: string; name: string; value: Value; attrs: Record<string, Value>;
  groups?: { label: string | null; options: Option[] }[];
  columns?: string[]; sections?: { label: string; areas: { label: string; notes: string[]; cells: { action: string; option: Option | null }[] }[] }[];
  rows?: { pk: string; label: string; group: string; id: string; checked: boolean; primary: boolean; details: Field[] }[];
  primary?: boolean; dependsOn?: string; emptyText?: string; areaLabel?: string;
  current?: { name: string; clearName: string | null; clearId: string | null; clearLabel: string } | null;
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
  delete: { href: string; label: string } | null;
  history: { label: string; intro: string; link: { href: string; label: string }; empty: string; critical: string;
    empty_value: string; entries: Entry[] } | null;
}

const text = (said: Said | null): string | undefined => (said ? said.text ?? said.html : undefined);
const str = (value: Value): string => (value === null || value === undefined || typeof value === 'boolean' ? '' : Array.isArray(value) ? value.join(',') : String(value));
const options = (widget: Widget) => (widget.groups ?? []).flatMap((group) => group.options);
const attr = (widget: Widget, name: string): string | undefined => {
  const value = widget.attrs[name];
  return value === undefined || value === null || value === false ? undefined : String(value);
};

/** One field of the payload, drawn by its kind. `source` is the value of the field a dependent select follows. */
export function FieldOf({ field, optional, source }: { field: Field; optional: string; source: (name: string) => string | undefined }) {
  const { widget } = field;
  const base = {
    name: widget.name, label: field.label, help: text(field.help), errors: field.errors,
    // the control is required as the server drew it (a formset's row is not); the mark says what the field is
    required: Boolean(widget.attrs.required), mark: field.required ? undefined : optional,
  };
  const initial = field.initial ? field.initial.values.map((value) => <input key={value} type="hidden" name={field.initial?.name} value={value} />) : null;
  const disabledText = (): string => {
    if (widget.kind === 'select' || widget.kind === 'multiselect' || widget.kind === 'radio' || widget.kind === 'checks') {
      return options(widget).filter((option) => option.selected).map((option) => option.label).join(', ');
    }
    return str(widget.value);
  };
  if (widget.kind === 'output' || (field.disabled && !['matrix', 'links', 'checkbox'].includes(widget.kind))) {
    return <>{<FixedField label={field.label} value={widget.kind === 'output' ? str(widget.value) || '—' : disabledText() || '—'} help={text(field.help)} />}{initial}</>;
  }
  let control: ReactNode;
  switch (widget.kind) {
    case 'select': {
      const follows = widget.attrs['data-depends-on'];
      const chosen = follows ? source(String(follows)) : undefined;
      const shown = options(widget).filter((option) => !follows || !option.attrs['data-group'] || chosen === undefined
        || String(option.attrs['data-group']).split(' ').includes(chosen));
      control = <SelectField {...base} key={follows ? `${widget.name}-${chosen ?? ''}` : widget.name}
        options={shown.map((option) => ({ value: option.value, label: option.label }))}
        defaultValue={shown.find((option) => option.selected)?.value ?? ''} />;
      break;
    }
    case 'multiselect':
    case 'checks':
      control = <CheckboxGroup {...base} wide options={options(widget).map((option) => ({ value: option.value, label: option.label }))}
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
        name: widget.current.name, intro: field.label, clearName: widget.current.clearName ?? undefined,
        clearLabel: widget.current.clearLabel } : null} />;
      break;
    case 'matrix':
      control = <PermissionMatrix {...base} areaLabel={widget.areaLabel ?? ''} columns={widget.columns ?? []}
        sections={(widget.sections ?? []).map((section) => ({ label: section.label, areas: section.areas.map((area) => ({
          label: area.label, notes: area.notes, cells: area.cells.map((cell) => (cell.option ? {
            action: cell.action, value: cell.option.value, checked: cell.option.selected, id: String(cell.option.attrs.id ?? ''),
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
        type={(['email', 'url', 'password'] as const).find((kind) => kind === widget.kind) ?? 'text'}
        numeric={widget.kind === 'number'} min={attr(widget, 'min')} max={attr(widget, 'max')} step={attr(widget, 'step')}
        maxLength={attr(widget, 'maxlength') ? Number(attr(widget, 'maxlength')) : undefined}
        autoComplete={attr(widget, 'autocomplete')}
        dateInput={widget.kind === 'day' ? 'day' : moment ? 'moment' : undefined} />;
    }
  }
  return <>{control}{initial}</>;
}

export function RecordForm({ form, csrfToken, submit, cancel, optional, tabsLabel, hasErrors, delete: remove, history }: RecordFormProps) {
  const holder = useRef<HTMLDivElement>(null);
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
  const left = (event: FocusEvent<HTMLDivElement>) => {
    const target = event.target as HTMLInputElement;
    const kind = target.dataset?.dateInput;
    if (kind) target.value = tidy(target.value.trim(), kind === 'moment');
  };
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
  const firstWithErrors = form.tabs.find((tab) => tab.hasErrors)?.key;
  return (
    <ServerForm action={form.action} csrfToken={csrfToken} formErrors={form.errors} label={submit} multipart={form.multipart} noValidate
      actions={<>
        {remove ? <LinkButton href={remove.href} variant="danger-text">{remove.label}</LinkButton> : null}
        <LinkButton href={cancel.href}>{cancel.label}</LinkButton>
        <Button variant="primary" type="submit">{submit}</Button>
      </>}>
      {form.hidden.map((hidden) => <input key={hidden.name} type="hidden" name={hidden.name} value={str(hidden.value)} />)}
      <div className="ui-form-body" data-wide="" ref={holder} onChange={changed} onBlur={left}>
        {items.length > 1 ? <Tabs label={tabsLabel} items={items} keepMounted {...(firstWithErrors ? { defaultSelected: firstWithErrors } : {})} />
          : items[0]?.content}
      </div>
    </ServerForm>
  );
}
