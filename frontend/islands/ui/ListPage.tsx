// A list page (core.crud.ListView behind ?ui=next, core/listprops.py): the toolbar of a tab's list (its search and its
// filters, one GET form: the server reads the address and stays the only source of what is listed), the link tabs of its
// views, its notices, the table with each row's actions, the empty state and the pager. Built once for every list page;
// the server words every label, every cell and every address, and this component only draws them with the library.
// A row's title opens the record's own page (the new record form), never the classic dialog. A row action is a link or a
// small POST form with the page's CSRF token (cancelling a request): the server checks it like the classic page's.
import { Button, LinkButton } from './Button.js';
import { CellLines, Table } from './Table.js';
import { Chip, type ChipKind } from './Chip.js';
import { Icon, type IconName } from './Icon.js';
import { EmptyState, Notice, type NoticeTone } from './States.js';
import { LinkTabs, type LinkTab } from './Tabs.js';

export interface ListLink { href: string; label: string }

/** One cell: its main text (a link when it opens the record), a sub-line or two, or a status chip. */
export interface ListCell {
  text?: string | null;
  href?: string | null;
  strong?: boolean;
  chip?: { kind: ChipKind; text: string } | null;
  /** chips after the text (a "Platform admin" mark), each a word of its own */
  chips?: { kind: ChipKind; text: string }[];
  sub?: string[];
}

export interface ListAction {
  kind: 'link' | 'post';
  href: string;
  label: string;
  icon: IconName;
  danger?: boolean;
  /** a post's own fields besides the CSRF token (`next`) */
  fields?: { name: string; value: string }[];
}

export interface ListRow {
  key: string;
  status?: 'critical' | 'warning' | null;
  voided?: boolean;
  cells: Record<string, ListCell>;
  actions: ListAction[];
}

export interface ListColumn { key: string; label: string; numeric?: boolean }

export interface ListFilterOption { value: string; label: string }
export interface ListFilter {
  /** a select (the default), or a day typed the European way (frontend/date-input.ts tidies it) */
  kind?: 'select' | 'day';
  name: string;
  label: string;
  value: string;
  placeholder?: string;
  options: ListFilterOption[];
  /** options under group labels (an optgroup each), after `options` */
  groups?: { label: string; options: ListFilterOption[] }[];
}

export interface ListPageProps {
  csrfToken: string;
  tabs: { label: string; tabs: LinkTab[] } | null;
  toolbar: {
    label: string;
    search: { name: string; value: string; label: string; placeholder: string } | null;
    /** what the address holds that the form has no control for (a view, a tab): sent again, so a search keeps it */
    keep: { name: string; value: string }[];
    filters: ListFilter[];
    submit: string;
    add: ListLink | null;
  };
  notices: { key: string; tone: NoticeTone; text: string }[];
  /** lines above the table ("Showing 200 of 250 requests.") */
  lines: string[];
  table: { label: string; columns: ListColumn[]; rows: ListRow[]; actionsLabel: string };
  /** said when there is no row: "No … yet" with what to do, or "No … match" with the way back */
  empty: { title: string; text: string | null; link: ListLink | null; add: ListLink | null };
  pager: { label: string; range: string; page: string; previous: ListLink | null; next: ListLink | null } | null;
}

function Cell({ cell }: { cell: ListCell }) {
  const main = cell.chip ? <Chip kind={cell.chip.kind}>{cell.chip.text}</Chip>
    : cell.href ? <a href={cell.href}>{cell.text}</a> : cell.text;
  const chips = cell.chips?.map((each) => <Chip key={each.text} kind={each.kind}>{each.text}</Chip>);
  const sub = cell.sub && cell.sub.length ? cell.sub.join(' · ') : undefined;
  return <CellLines strong={Boolean(cell.strong)} main={chips && chips.length ? <>{main} {chips}</> : main} sub={sub} />;
}

function Action({ action, csrfToken }: { action: ListAction; csrfToken: string }) {
  const className = action.danger ? 'icon-button icon-button-danger' : 'icon-button';
  if (action.kind === 'post') {
    return (
      <form method="post" action={action.href}>
        <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken} />
        {action.fields?.map((field) => <input key={field.name} type="hidden" name={field.name} value={field.value} />)}
        <button type="submit" className={className} aria-label={action.label} title={action.label}><Icon name={action.icon} /></button>
      </form>
    );
  }
  return <a className={className} href={action.href} aria-label={action.label} title={action.label}><Icon name={action.icon} /></a>;
}

function Toolbar({ toolbar }: { toolbar: ListPageProps['toolbar'] }) {
  const { search, filters, keep } = toolbar;
  if (!search && !filters.length) return toolbar.add ? <div className="ui-toolbar"><LinkButton href={toolbar.add.href} variant="primary" icon="plus">{toolbar.add.label}</LinkButton></div> : null;
  return (
    <div className="ui-toolbar">
      <form method="get" role="search" aria-label={toolbar.label} className="ui-list-filters">
        {keep.map((each) => <input key={each.name} type="hidden" name={each.name} value={each.value} />)}
        {search ? (
          <label className="ui-search">
            <Icon name="search" />
            <span className="sr-only">{search.label}</span>
            <input type="search" name={search.name} defaultValue={search.value} placeholder={search.placeholder} />
          </label>
        ) : null}
        {filters.map((filter) => (
          <label key={filter.name}>
            <span className="sr-only">{filter.label}</span>
            {filter.kind === 'day' ? (
              <input type="text" name={filter.name} defaultValue={filter.value} placeholder={filter.placeholder}
                autoComplete="off" data-date-input="day" />
            ) : <select name={filter.name} defaultValue={filter.value}>
              {filter.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              {filter.groups?.map((group) => (
                <optgroup key={group.label} label={group.label}>
                  {group.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </optgroup>
              ))}
            </select>}
          </label>
        ))}
        <Button type="submit" variant="ghost" icon="search">{toolbar.submit}</Button>
      </form>
      {toolbar.add ? <LinkButton href={toolbar.add.href} variant="primary" icon="plus">{toolbar.add.label}</LinkButton> : null}
    </div>
  );
}

export function ListPage({ csrfToken, tabs, toolbar, notices, lines, table, empty, pager }: ListPageProps) {
  return (
    <>
      {tabs ? <LinkTabs label={tabs.label} tabs={tabs.tabs} /> : null}
      <Toolbar toolbar={toolbar} />
      {notices.map((notice) => <Notice key={notice.key} tone={notice.tone}>{notice.text}</Notice>)}
      {table.rows.length ? (
        <>
          {lines.map((line) => <p key={line} className="ui-cell-sub">{line}</p>)}
          <Table<ListRow>
            label={table.label}
            rows={table.rows}
            rowKey={(row) => row.key}
            rowStatus={(row) => row.status ?? undefined}
            rowVoided={(row) => Boolean(row.voided)}
            columns={table.columns.map((column, index) => ({
              key: column.key, label: column.label, numeric: Boolean(column.numeric), rowHeader: index === 0,
              render: (row: ListRow) => { const cell = row.cells[column.key]; return cell ? <Cell cell={cell} /> : null; },
            }))}
            {...(table.rows.some((row) => row.actions.length) ? {
              actions: (row: ListRow) => row.actions.map((action) => <Action key={action.href + action.label} action={action} csrfToken={csrfToken} />),
              actionsLabel: table.actionsLabel,
            } : {})}
          />
          {pager ? (
            <nav className="pager list-pager" aria-label={pager.label}>
              <span>{pager.range}</span>
              <span className="pager-links">
                {pager.previous ? <LinkButton href={pager.previous.href} variant="ghost">{pager.previous.label}</LinkButton> : null}
                <span>{pager.page}</span>
                {pager.next ? <LinkButton href={pager.next.href} variant="ghost">{pager.next.label}</LinkButton> : null}
              </span>
            </nav>
          ) : null}
        </>
      ) : (
        <EmptyState title={empty.title} action={empty.add
          ? <LinkButton href={empty.add.href} variant="primary" icon="plus">{empty.add.label}</LinkButton> : undefined}>
          {empty.text || empty.link ? <>{empty.text}{empty.link ? <> <a href={empty.link.href}>{empty.link.label}</a></> : null}</> : null}
        </EmptyState>
      )}
    </>
  );
}
