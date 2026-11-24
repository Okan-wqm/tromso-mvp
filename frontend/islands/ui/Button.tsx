// Buttons (docs/design/system/README.md, Components: Button; the new look's rules in static/css/ds.css):
//   secondary (the default, outlined), primary (one per view, with the registration marks in the new look), ghost (the
//   action colour, no border: "All reports"), danger (the only red fill: a destructive confirm, never beside Edit),
//   danger-text (the red word: Delete in a drawer's foot), link.
// States: hover and pressed from the tokens, the focus ring, disabled (isDisabled), busy (busy: the label stays, a ring
// turns in place of its icon, the press is refused, aria-disabled, and React Aria marks it data-pending). React Aria's Button gives the
// press, keyboard and focus-visible handling; the look is the design system's .ui-btn.
import type { ReactNode } from 'react';
import { Button as AriaButton, type ButtonProps as AriaButtonProps } from 'react-aria-components';

import { Icon, type IconName } from './Icon.js';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-text' | 'link';

export interface ButtonProps extends Omit<AriaButtonProps, 'className' | 'style' | 'children' | 'isPending'> {
  variant?: ButtonVariant;
  /** coarse: 48 px and more for a finger at the tank side */
  size?: 'coarse';
  icon?: IconName;
  busy?: boolean;
  children: ReactNode;
}

export function Button({ variant = 'secondary', size, icon, busy = false, children, ...rest }: ButtonProps) {
  return (
    <AriaButton
      {...rest}
      className="ui-btn"
      data-variant={variant === 'secondary' ? undefined : variant}
      data-size={size}
      isPending={busy}
    >
      {busy ? <span className="ui-spinner" aria-hidden="true" /> : icon ? <Icon name={icon} /> : null}
      {children}
    </AriaButton>
  );
}

export interface LinkButtonProps {
  href: string;
  variant?: ButtonVariant;
  icon?: IconName;
  children: ReactNode;
}

/** A link that looks like a button (a page's "Add site" that opens the form page). */
export function LinkButton({ href, variant = 'secondary', icon, children }: LinkButtonProps) {
  return (
    <a className="ui-btn" data-variant={variant === 'secondary' ? undefined : variant} href={href}>
      {icon ? <Icon name={icon} /> : null}
      {children}
    </a>
  );
}

export interface IconButtonProps extends Omit<AriaButtonProps, 'className' | 'style' | 'children'> {
  icon: IconName;
  /** what it does, for a screen reader and the tooltip: "Edit Bergen Hatchery" */
  label: string;
  tone?: 'danger';
}

/** The square icon button (a row's pencil, a dialog's close): its name is its label. */
export function IconButton({ icon, label, tone, ...rest }: IconButtonProps) {
  return (
    <AriaButton {...rest} className={tone === 'danger' ? 'icon-button icon-button-danger' : 'icon-button'} aria-label={label}>
      <Icon name={icon} />
    </AriaButton>
  );
}
