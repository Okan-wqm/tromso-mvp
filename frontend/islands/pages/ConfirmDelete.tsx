// A tab's delete confirmation in the new look (core.crud.DeleteView behind ?ui=next): the old page's question, what is in
// the way, what goes with the record, what loses its link, what is kept and what stays linked, and what deleting does,
// all in the server's words (core.formpayload.delete_payload); the danger button posts to the same address. A plan with
// blockers switches the button off, as the old page does.
import { Button, Chip, LinkButton, List, ListItem, Notice, ServerForm } from '../ui/index.js';

interface Group { kind: string; count: number; records: string[]; title: string; note: string | null }
export interface ConfirmDeleteProps {
  action: string; cancel: string; cancelLabel: string; csrfToken: string; question: string; heading: string; submit: string;
  blocked: { title: string; reasons: string[] } | null; groups: Group[]; canDelete: boolean; outcome: string;
}

export function ConfirmDelete({ action, cancel, cancelLabel, csrfToken, question, submit, blocked, groups, canDelete, outcome }: ConfirmDeleteProps) {
  return (
    <ServerForm action={action} csrfToken={csrfToken} label={submit} noValidate actions={<>
      <LinkButton href={cancel}>{cancelLabel}</LinkButton>
      <Button variant="danger" type="submit" isDisabled={!canDelete}>{submit}</Button>
    </>}>
      <p className="ui-confirm-question">{question}</p>
      {blocked ? (
        <Notice tone="critical" title={blocked.title}>
          <List label={blocked.title}>{blocked.reasons.map((reason) => <ListItem key={reason} main={reason} />)}</List>
        </Notice>
      ) : null}
      {groups.map((group) => (
        <section key={`${group.kind}-${group.title}`} className="ui-confirm-group" aria-label={group.title}>
          <h3>{group.title} <Chip kind="neutral">{String(group.count)}</Chip></h3>
          {group.note ? <p className="help">{group.note}</p> : null}
          {group.records.length ? <List label={group.title}>{group.records.map((record, index) => <ListItem key={`${record}-${index}`} main={record} />)}</List> : null}
        </section>
      ))}
      <p className="help">{outcome}</p>
    </ServerForm>
  );
}
