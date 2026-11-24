// Form fields (docs/design/system/README.md, Field; the frontend redesign's decision 4): the server is the only validator.
// A field shows the server's errors in words (with the octagon), is aria-invalid and describes itself by its help and its
// errors; ServerForm puts the focus on the first invalid field when the page comes back with errors. Nothing is checked
// again in the browser beyond what the server put on the control (required, min, max, step). The markup is the server's
// own field (templates/registration/_field.html): .field, the label, the control, .help, .errorlist.
import { useEffect, useId, useRef, type ReactNode } from 'react';

import { Icon } from './Icon.js';

interface FieldBase {
  name: string;
  label: ReactNode;
  help?: ReactNode;
  /** the server's messages for this field, in the page's language */
  errors?: string[];
  required?: boolean;
  /** across the whole form grid (a text area, a long name) */
  wide?: boolean;
  disabled?: boolean;
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
  defaultValue?: string;
  type?: 'text' | 'email' | 'search' | 'password' | 'tel' | 'url';
  /** a figure: the decimal keyboard on a phone; the server reads "7,4" as 7.4 */
  numeric?: boolean;
  unit?: ReactNode;
  placeholder?: string;
  multiline?: boolean;
  min?: string;
  max?: string;
  step?: string;
  autoComplete?: string;
}

export function TextField({ name, label, help, errors, required, wide, disabled, defaultValue, type = 'text', numeric,
  unit, placeholder, multiline, min, max, step, autoComplete }: TextFieldProps) {
  const id = useId();
  const invalid = Boolean(errors && errors.length);
  const control = multiline ? (
    <textarea id={id} name={name} defaultValue={defaultValue} required={required} disabled={disabled}
      placeholder={placeholder} aria-invalid={invalid || undefined} aria-describedby={describedBy(id, help, errors)} />
  ) : (
    <input id={id} name={name} type={type} defaultValue={defaultValue} required={required} disabled={disabled}
      placeholder={placeholder} inputMode={numeric ? 'decimal' : undefined} min={min} max={max} step={step}
      autoComplete={autoComplete} aria-invalid={invalid || undefined} aria-describedby={describedBy(id, help, errors)} />
  );
  return (
    <div className={invalid ? 'field has-error' : 'field'} data-wide={wide ? '' : undefined}>
      <label htmlFor={id}>{label}</label>
      {unit ? <span className="ui-unit">{control}<span className="ui-unit-label">{unit}</span></span> : control}
      <Described id={id} help={help} errors={errors} />
    </div>
  );
}

export interface SelectFieldProps extends FieldBase {
  options: { value: string; label: string }[];
  defaultValue?: string;
}

/** A native select (the design's, with its chevron): the platform's own list on a phone, no popover to manage. */
export function SelectField({ name, label, help, errors, required, wide, disabled, options, defaultValue }: SelectFieldProps) {
  const id = useId();
  const invalid = Boolean(errors && errors.length);
  return (
    <div className={invalid ? 'field has-error' : 'field'} data-wide={wide ? '' : undefined}>
      <label htmlFor={id}>{label}</label>
      <select id={id} name={name} defaultValue={defaultValue} required={required} disabled={disabled}
        aria-invalid={invalid || undefined} aria-describedby={describedBy(id, help, errors)}>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
      <Described id={id} help={help} errors={errors} />
    </div>
  );
}

export interface CheckboxGroupProps extends FieldBase {
  options: { value: string; label: string }[];
  defaultValues?: string[];
}

/** Boxes to tick, one or more (Supplies, Topics): a fieldset named by its legend. */
export function CheckboxGroup({ name, label, help, errors, wide, disabled, options, defaultValues = [] }: CheckboxGroupProps) {
  const id = useId();
  const invalid = Boolean(errors && errors.length);
  return (
    <fieldset className={invalid ? 'field field-set has-error' : 'field field-set'} data-wide={wide ? '' : undefined}
      aria-describedby={describedBy(id, help, errors)} aria-invalid={invalid || undefined} disabled={disabled}>
      <legend>{label}</legend>
      <div className="ui-checks">
        {options.map((option) => (
          <label key={option.value} className="ui-check">
            <input type="checkbox" name={name} value={option.value} defaultChecked={defaultValues.includes(option.value)} />
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
  formErrors?: string[];
  children: ReactNode;
  actions: ReactNode;
  method?: 'post' | 'get';
  /** what the form is, for a screen reader */
  label?: string;
}

/** A form Django receives and validates. Comes the page back with errors, the focus goes to the first invalid field. */
export function ServerForm({ action, csrfToken, formErrors, children, actions, method = 'post', label }: ServerFormProps) {
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    const first = form.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
    if (first) first.focus();
  }, []);
  return (
    <form ref={form} action={action} method={method} aria-label={label} noValidate={false}>
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
