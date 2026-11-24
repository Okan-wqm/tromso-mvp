// Form fields (docs/design/system/README.md, Field; the frontend redesign's decision 4): the server is the only validator.
// A field shows the server's errors in words (with the octagon), is aria-invalid and describes itself by its help and its
// errors; ServerForm puts the focus on the first invalid field when the page comes back with errors. Nothing is checked
// again in the browser beyond what the server put on the control (required, min, max, step). The markup is the server's
// own field (templates/registration/_field.html): .field, the label, the control, .help, .errorlist.
import { type FormEvent, useEffect, useId, useRef, useState, type ReactNode } from 'react';

import { Icon } from './Icon.js';

interface FieldBase {
  name: string;
  label: ReactNode;
  help?: ReactNode | undefined;
  /** the server's messages for this field, in the page's language */
  errors?: string[] | undefined;
  required?: boolean | undefined;
  /** across the whole form grid (a text area, a long name) */
  wide?: boolean | undefined;
  disabled?: boolean | undefined;
  /** the required or optional mark after the label, in the page's words ("optional"): every field may carry one */
  mark?: ReactNode | undefined;
  /** the label for a screen reader only: a row of a list whose heading row names its fields */
  labelHidden?: boolean | undefined;
}

/** The label's mark (required or optional), in words from the server. */
export function FieldMark({ mark }: { mark?: ReactNode | undefined }) {
  return mark ? <span className="ui-field-mark">{mark}</span> : null;
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

function describedBy(id: string, help?: ReactNode, errors?: string[]): string | undefined {
  const ids = [help ? `${id}-help` : '', errors && errors.length ? `${id}-errors` : ''].filter(Boolean);
  return ids.length ? ids.join(' ') : undefined;
}

export interface TextFieldProps extends FieldBase {
  defaultValue?: string | undefined;
  type?: 'text' | 'email' | 'search' | 'password' | 'tel' | 'url' | undefined;
  /** a figure: the decimal keyboard on a phone; the server reads "7,4" as 7.4 */
  numeric?: boolean | undefined;
  unit?: ReactNode | undefined;
  placeholder?: string | undefined;
  multiline?: boolean | undefined;
  min?: string | undefined;
  max?: string | undefined;
  step?: string | undefined;
  autoComplete?: string | undefined;
  maxLength?: number | undefined;
  /** a date or a moment typed the European way (frontend/date-input.ts tidies it when the box is left) */
  dateInput?: 'day' | 'moment' | undefined;
  /** a code typed in capitals (the widget's data-uppercase): put in capitals while typing, as the classic page does */
  uppercase?: boolean | undefined;
}

export function TextField({ name, label, help, errors, required, wide, disabled, defaultValue, type = 'text', numeric,
  unit, placeholder, multiline, min, max, step, autoComplete, mark, maxLength, dateInput, uppercase, labelHidden }: TextFieldProps) {
  const id = useId();
  const invalid = Boolean(errors && errors.length);
  const control = multiline ? (
    <textarea id={id} name={name} defaultValue={defaultValue} required={required} disabled={disabled}
      placeholder={placeholder} maxLength={maxLength} aria-invalid={invalid || undefined} aria-describedby={describedBy(id, help, errors)} />
  ) : (
    <input id={id} name={name} type={type} defaultValue={defaultValue} required={required} disabled={disabled}
      placeholder={placeholder} inputMode={numeric ? 'decimal' : undefined} min={min} max={max} step={step}
      autoComplete={autoComplete} maxLength={maxLength} data-date-input={dateInput} data-uppercase={uppercase ? '' : undefined}
      onInput={uppercase ? (event: FormEvent<HTMLInputElement>) => {
        const box = event.currentTarget;
        const { selectionStart, selectionEnd } = box;
        box.value = box.value.toUpperCase();
        box.setSelectionRange(selectionStart, selectionEnd);
      } : undefined} aria-invalid={invalid || undefined} aria-describedby={describedBy(id, help, errors)} />
  );
  return (
    <div className={invalid ? 'field has-error' : 'field'} data-wide={wide ? '' : undefined}>
      <label htmlFor={id} className={labelHidden ? 'sr-only' : undefined}>{label}<FieldMark mark={mark} /></label>
      {unit ? <span className="ui-unit">{control}<span className="ui-unit-label">{unit}</span></span> : control}
      <Described id={id} help={help} errors={errors} />
    </div>
  );
}

export interface SelectOption { value: string; label: string; disabled?: boolean | undefined }

export interface SelectFieldProps extends FieldBase {
  options: SelectOption[];
  /** options under their group's heading (an <optgroup> each; a group without a label: its options as they are), after
   *  `options`: two options of the same name under two headings stay two different choices */
  groups?: { label: string | null; options: SelectOption[] }[] | undefined;
  defaultValue?: string | undefined;
}

/** A native select (the design's, with its chevron): the platform's own list on a phone, no popover to manage. */
const optionOf = (option: SelectOption) => <option key={option.value} value={option.value} disabled={option.disabled || undefined}>{option.label}</option>;

export function SelectField({ name, label, help, errors, required, wide, disabled, options, groups, defaultValue, mark, labelHidden }: SelectFieldProps) {
  const id = useId();
  const invalid = Boolean(errors && errors.length);
  return (
    <div className={invalid ? 'field has-error' : 'field'} data-wide={wide ? '' : undefined}>
      <label htmlFor={id} className={labelHidden ? 'sr-only' : undefined}>{label}<FieldMark mark={mark} /></label>
      <select id={id} name={name} defaultValue={defaultValue} required={required} disabled={disabled}
        aria-invalid={invalid || undefined} aria-describedby={describedBy(id, help, errors)}>
        {options.map(optionOf)}
        {groups?.map((group, index) => (group.label
          ? <optgroup key={`${group.label}-${index}`} label={group.label}>{group.options.map(optionOf)}</optgroup>
          : group.options.map(optionOf)))}
      </select>
      <Described id={id} help={help} errors={errors} />
    </div>
  );
}

export interface CheckboxGroupProps extends FieldBase {
  /** an option switched off by the server (a tank another experiment has booked) cannot be ticked */
  options: { value: string; label: string; disabled?: boolean | undefined }[];
  defaultValues?: string[] | undefined;
}

/** Boxes to tick, one or more (Supplies, Topics): a fieldset named by its legend. */
export function CheckboxGroup({ name, label, help, errors, wide, disabled, options, defaultValues = [], mark }: CheckboxGroupProps) {
  const id = useId();
  const invalid = Boolean(errors && errors.length);
  return (
    <fieldset className={invalid ? 'field field-set has-error' : 'field field-set'} data-wide={wide ? '' : undefined}
      aria-describedby={describedBy(id, help, errors)} aria-invalid={invalid || undefined} disabled={disabled}>
      <legend>{label}<FieldMark mark={mark} /></legend>
      <div className="ui-checks">
        {options.map((option) => (
          <label key={option.value} className="ui-check">
            <input type="checkbox" name={name} value={option.value} defaultChecked={defaultValues.includes(option.value)}
              disabled={option.disabled || undefined} />
            {option.label}
          </label>
        ))}
      </div>
      <Described id={id} help={help} errors={errors} />
    </fieldset>
  );
}

/** A value chosen once and shown where its field stood ("Chosen once, at creation"). */
export function FixedField({ label, value, help }: { label: ReactNode; value: ReactNode; help?: ReactNode }) {
  const id = useId();
  return (
    <div className="field">
      <span className="field-label" id={`${id}-label`}>{label}</span>
      <span className="ui-fixed" aria-labelledby={`${id}-label`}>{value}</span>
      {help ? <div className="help">{help}</div> : null}
    </div>
  );
}

export interface ServerFormProps {
  action: string;
  /** the form's CSRF token, as the server put it in the props */
  csrfToken: string;
  /** an error of the whole form (not of one field) */
  formErrors?: string[] | undefined;
  children: ReactNode;
  actions: ReactNode;
  method?: 'post' | 'get' | undefined;
  /** what the form is, for a screen reader */
  label?: string | undefined;
  /** it carries files (a library document's PDF) */
  multipart?: boolean | undefined;
  /** leave every check to the server, as the old page's novalidate (a form over several tabs: the browser cannot point at
   * a field on a hidden tab) */
  noValidate?: boolean | undefined;
}

/** A form Django receives and validates. Comes the page back with errors, the focus goes to the first invalid field. While
 * it is posting, it is busy: its submit buttons are switched off and say so (aria-busy), and a second press sends nothing;
 * coming back to the page from the browser's history (bfcache, pageshow) makes it ready again. */
export function ServerForm({ action, csrfToken, formErrors, children, actions, method = 'post', label, multipart, noValidate = false }: ServerFormProps) {
  const form = useRef<HTMLFormElement>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    // the first invalid field; a group of boxes (a fieldset: a box group, the matrix, a link list) is not focusable, so its
    // first control takes the focus and the group's legend and errors are read with it
    const first = form.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
    const target = first?.matches('fieldset') ? first.querySelector<HTMLElement>('input:not([type="hidden"]), select, textarea, button') : first;
    target?.focus();
  }, []);
  useEffect(() => {
    const ready = (event: PageTransitionEvent) => { if (event.persisted) setBusy(false); };
    window.addEventListener('pageshow', ready);
    return () => window.removeEventListener('pageshow', ready);
  }, []);
  // The submit buttons this form switched off while busy: only they are switched on again; a button that is off of its own
  // (a delete a plan blocks) stays off.
  const switched = useRef<HTMLButtonElement[]>([]);
  useEffect(() => {
    if (busy) {
      for (const button of form.current?.querySelectorAll<HTMLButtonElement>('button[type="submit"]') ?? []) {
        if (!button.disabled) {
          button.disabled = true;
          switched.current.push(button);
        }
        button.setAttribute('aria-busy', 'true');
      }
    } else {
      for (const button of switched.current) button.disabled = false;
      switched.current = [];
      for (const button of form.current?.querySelectorAll<HTMLButtonElement>('button[aria-busy]') ?? []) button.removeAttribute('aria-busy');
    }
  }, [busy]);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    if (busy) {
      event.preventDefault();
      return;
    }
    setBusy(true);
  };
  return (
    <form ref={form} action={action} method={method} aria-label={label} aria-busy={busy || undefined} noValidate={noValidate}
      encType={multipart ? 'multipart/form-data' : undefined} onSubmit={submit}>
      {method === 'post' ? <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken} /> : null}
      {formErrors && formErrors.length ? (
        <div className="ui-notice" data-tone="critical" role="alert">
          <Icon name="octagon" />
          <ul className="ui-notice-body errorlist">{formErrors.map((message) => <li key={message}>{message}</li>)}</ul>
        </div>
      ) : null}
      <div className="ui-form-grid">{children}</div>
      <div className="ui-form-actions">{actions}</div>
    </form>
  );
}
