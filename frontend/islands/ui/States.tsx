// What a part shows when it has nothing, is still reading, or could not read (static/css/ds.css, Notice and "Empty,
// loading, error"); a sentence that must stay in sight (Notice). Every word comes from the server: no state is a bare
// spinner or a blank, and nothing absent is shown as a dash or a 0.
import type { ReactNode } from 'react';

import { Button } from './Button.js';
import { Icon } from './Icon.js';

// info: a page's help sentence (the classic panel-help), drawn as neutral with the info glyph
export type NoticeTone = 'warning' | 'ok' | 'critical' | 'neutral' | 'info';

export interface NoticeProps {
  tone?: NoticeTone;
  title?: ReactNode;
  children: ReactNode;
  /** a flash after a save closes; its close button is named by closeLabel */
  onClose?: () => void;
  closeLabel?: string;
}

const NOTICE_GLYPH = { warning: 'alert', ok: 'check-circle', critical: 'octagon', neutral: 'hourglass', info: 'info' } as const;

export function Notice({ tone = 'neutral', title, children, onClose, closeLabel }: NoticeProps) {
  return (
    <div className="ui-notice" data-tone={tone === 'neutral' || tone === 'info' ? undefined : tone} role={tone === 'critical' ? 'alert' : 'status'}>
      <Icon name={NOTICE_GLYPH[tone]} />
      <div className="ui-notice-body">
        {title ? <strong className="ui-notice-title">{title}</strong> : null}
        {children}
      </div>
      {onClose ? (
        <button type="button" className="icon-button" aria-label={closeLabel} onClick={onClose}><Icon name="x" /></button>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="ui-empty">
      <p className="ui-empty-title">{title}</p>
      {children ? <p className="ui-empty-text">{children}</p> : null}
      {action}
    </div>
  );
}

/** What is being read, in words, over skeleton lines that can never be taken for values. */
export function LoadingState({ label, lines = 3 }: { label: ReactNode; lines?: number }) {
  return (
    <div className="ui-loading" role="status" aria-live="polite">
      <span className="ui-loading-line"><span className="ui-spinner" aria-hidden="true" />{label}</span>
      {Array.from({ length: lines }, (_unused, index) => <span key={index} className="ui-skeleton" aria-hidden="true" />)}
    </div>
  );
}

export interface ErrorStateProps {
  title: ReactNode;
  children?: ReactNode;
  retryLabel?: string;
  onRetry?: () => void;
}

/** What could not be read and what to do; the retry is the one action. */
export function ErrorState({ title, children, retryLabel, onRetry }: ErrorStateProps) {
  return (
    <div className="ui-notice ui-error" data-tone="critical" role="alert">
      <Icon name="octagon" />
      <div className="ui-notice-body">
        <strong className="ui-notice-title">{title}</strong>
        {children}
      </div>
      {onRetry && retryLabel ? <Button onPress={onRetry} icon="repeat">{retryLabel}</Button> : null}
    </div>
  );
}
