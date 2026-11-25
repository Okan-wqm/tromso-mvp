// A list page (core.crud.ListView behind ?ui=next, core/listprops.py): the toolbar of a tab's list (its search and its
// filters, one GET form: the server reads the address and stays the only source of what is listed), the link tabs of its
// views, its notices, the table with each row's actions, the empty state and the pager. Built once for every list page;
// the server words every label, every cell and every address, and this component only draws them with the library.
// A row's title opens the record's own page (the new record form), never the classic dialog. A row action is a link or a
// small POST form with the page's CSRF token (cancelling a request): the server checks it like the classic page's.
// Rows may come in groups (`groups`, Live values' one plate per device): each group a plate with its own table of the
// shared columns; without groups the page is one table, as before.
import { useId, type FocusEvent, type FormEvent } from 'react';

import { tidy } from '../../date-input.js';

import { Button, LinkButton } from './Button.js';
import { CellLines, Table } from './Table.js';
import { Chip, type ChipKind } from './Chip.js';
import { Gauge, type GaugeProps } from './Gauge.js';
import { Icon, type IconName } from './Icon.js';
import { Plate, Plates } from './Plate.js';
import { Timeline, type TimelineProps } from './Timeline.js';
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
  /** a share drawn as a bar with the share in words beside it (a unit's capacity), under the text and its sub-lines */
  gauge?: GaugeProps | null;
  /** a closed disclosure in place of the text: its summary, and its lines shown when opened (a dead letter's payload) */
  details?: { summary: string; lines: string[] } | null;
}

export interface ListAction {
  kind: 'link' | 'post';
  href: string;
  label: string;
  icon: IconName;
  danger?: boolean;
  /** a post's own fields besides the CSRF token (`next`) */
  fields?: { name: string; value: string }[];
  /** the word beside the icon (an action that changes a safety state: Acknowledge, Resolve), not the icon alone */
  labelled?: boolean;
}

export interface ListRow {
  key: string;
  status?: 'critical' | 'warning' | null;
  voided?: boolean;
  cells: Record<string, ListCell>;
  actions: ListAction[];
}

export interface ListColumn { key: string; label: string; numeric?: boolean }

/** A group of the table's rows drawn as a plate of its own (Live values: one per device): its title, chips beside it
 *  (each a word), a meta line, and the keys of its rows in `table.rows` (every row in one group; the columns shared). */
export interface ListGroup {
  key: string;
  title: string;
  chips?: { kind: ChipKind; text: string }[];
  meta?: string | null;
  rows: string[];
}

export interface ListNotice {
  key: string;
  tone: NoticeTone;
  text: string;
  link?: ListLink | null;
  /** more links after the first, " · " between them */
  more?: ListLink[];
  title?: string;
  /** what the notice is about, a line each ("Atlantic salmon (Any water): Oxygen, pH") */
  items?: string[];
}

/** The rows drawn as cards: the column whose cell is the card's chip, and the columns drawn in its foot. */
export interface ListCards { chip: string | null; foot: string[] }

export interface ListFilterOption { value: string; label: string }
export interface ListFilter {
  /** a select (the default), a day typed the European way (frontend/date-input.ts tidies it), or a box that is ticked
   *  or not (`checked`; it sends `value` when ticked: Water chemistry's "Only warnings and criticals") */
  kind?: 'select' | 'day' | 'check';
  name: string;
  label: string;
  value: string;
  checked?: boolean;
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
  /** sentences above the table; one may end in links (Systems' "Show them"; Sampling points' "Show all · Add a point to
   *  it"), have a title and list what it is about (Water limits' fish with no limit) */
  notices: ListNotice[];
  /** lines above the table ("Showing 200 of 250 requests.") */
  lines: string[];
  table: { label: string; columns: ListColumn[]; rows: ListRow[]; actionsLabel: string };
  /** the rows in groups, one plate and table each (optional: without it, one table) */
  groups?: ListGroup[] | null;
  /** the rows as a grid of cards instead of a table (Sites; optional): a card's head the first column's cell with the
   *  chip column's beside it, its facts the other columns (a cell with nothing to say left out), its foot the foot
   *  columns' cells and the row's actions */
  cards?: ListCards | null;
  /** a timeline of the listed rows above the table, in a plate of its title (a channel's bindings over time; optional) */
  timeline?: (TimelineProps & { title: string }) | null;
  /** said when there is no row: "No … yet" with what to do, or "No … match" with the way back */
  empty: { title: string; text: string | null; link: ListLink | null; add: ListLink | null };
  pager: { label: string; range: string; page: string; previous: ListLink | null; next: ListLink | null } | null;
}

/** One cell of a list's table, as the server worded it: also a read-only table of a record's page (core/formpanels.py). */
export function Cell({ cell }: { cell: ListCell }) {
  if (cell.details) {
    return (
      <details className="ui-cell-details">
        <summary>{cell.details.summary}</summary>
        {cell.details.lines.map((line, index) => <span key={index} className="ui-cell-sub">{line}</span>)}
      </details>
    );
  }
  const main = cell.chip ? <Chip kind={cell.chip.kind}>{cell.chip.text}</Chip>
    : cell.href ? <a href={cell.href}>{cell.text}</a> : cell.text;
  const chips = cell.chips?.map((each) => <Chip key={each.text} kind={each.kind}>{each.text}</Chip>);
  const sub = cell.sub && cell.sub.length ? cell.sub.join(' · ') : undefined;
  const lines = <CellLines strong={Boolean(cell.strong)} main={chips && chips.length ? <>{main} {chips}</> : main} sub={sub} />;
  if (!cell.gauge) return lines;
  return <>{lines}<span className="ui-cell-sub"><Gauge {...cell.gauge} /></span></>;
}

function Action({ action, csrfToken }: { action: ListAction; csrfToken: string }) {
  const className = action.danger ? 'icon-button icon-button-danger' : 'icon-button';
  if (action.kind === 'post') {
    return (
      <form method="post" action={action.href}>
        <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken} />
        {action.fields?.map((field) => <input key={field.name} type="hidden" name={field.name} value={field.value} />)}
        {action.labelled
          ? <button type="submit" className="ui-btn" data-variant={action.danger ? 'danger-text' : undefined}><Icon name={action.icon} />{action.label}</button>
          : <button type="submit" className={className} aria-label={action.label} title={action.label}><Icon name={action.icon} /></button>}
      </form>
    );
  }
  if (action.labelled) {
    return <a className="ui-btn" data-variant={action.danger ? 'danger-text' : undefined} href={action.href}><Icon name={action.icon} />{action.label}</a>;
  }
  return <a className={className} href={action.href} aria-label={action.label} title={action.label}><Icon name={action.icon} /></a>;
}

/** The shared date box's rule (frontend/date-input.ts): a day typed the European way is put dd.mm.yyyy. */
function tidied(input: EventTarget | null) {
  if (input instanceof HTMLInputElement && input.dataset.dateInput) input.value = tidy(input.value, input.dataset.dateInput === 'moment');
}

/** The list's toolbar: the search and the filters as one GET form, and the Add link (also the Shift schedule's). */
export function ListToolbar({ toolbar }: { toolbar: ListPageProps['toolbar'] }) {
  const { search, filters, keep } = toolbar;
  const searchId = useId();
  if (!search && !filters.length) return toolbar.add ? <div className="ui-toolbar"><LinkButton href={toolbar.add.href} variant="primary" icon="plus">{toolbar.add.label}</LinkButton></div> : null;
  return (
    <div className="ui-toolbar">
      {/* a day box is tidied when it is left, and before the form goes (Enter sends it without leaving the box) */}
      <form method="get" role="search" aria-label={toolbar.label} className="ui-list-filters"
        onBlur={(event: FocusEvent<HTMLFormElement>) => tidied(event.target)}
        onSubmit={(event: FormEvent<HTMLFormElement>) => { for (const box of event.currentTarget.querySelectorAll('input[data-date-input]')) tidied(box); }}>
        {keep.map((each) => <input key={each.name} type="hidden" name={each.name} value={each.value} />)}
        {search ? (
          // the frame is a div (ds.css draws a label holding its control as a labelled filter, label above it)
          <div className="ui-search">
            <Icon name="search" />
            <label className="sr-only" htmlFor={searchId}>{search.label}</label>
            <input id={searchId} type="search" name={search.name} defaultValue={search.value} placeholder={search.placeholder} />
          </div>
        ) : null}
        {filters.map((filter) => filter.kind === 'check' ? (
          // a box is named by its words beside it, in sight (a ticked filter must say what it hides)
          <label key={filter.name} className="ui-check">
            <input type="checkbox" name={filter.name} value={filter.value} defaultChecked={Boolean(filter.checked)} />
            <span>{filter.label}</span>
          </label>
        ) : (
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

function RowsTable({ label, columns, rows, actionsLabel, csrfToken }: {
  label: string; columns: ListColumn[]; rows: ListRow[]; actionsLabel: string; csrfToken: string;
}) {
  return (
    <Table<ListRow>
      label={label}
      rows={rows}
      rowKey={(row) => row.key}
      rowStatus={(row) => row.status ?? undefined}
      rowVoided={(row) => Boolean(row.voided)}
      columns={columns.map((column, index) => ({
        key: column.key, label: column.label, numeric: Boolean(column.numeric), rowHeader: index === 0,
        render: (row: ListRow) => { const cell = row.cells[column.key]; return cell ? <Cell cell={cell} /> : null; },
      }))}
      {...(rows.some((row) => row.actions.length) ? {
        actions: (row: ListRow) => row.actions.map((action) => <Action key={action.href + action.label} action={action} csrfToken={csrfToken} />),
        actionsLabel,
      } : {})}
    />
  );
}

/** The rows in their groups: a plate each, its title, chips and meta in the head, its own table of the shared columns. */
function Groups({ groups, table, csrfToken }: { groups: ListGroup[]; table: ListPageProps['table']; csrfToken: string }) {
  const byKey = new Map(table.rows.map((row) => [row.key, row]));
  return (
    <Plates>
      {groups.map((group) => (
        <Plate key={group.key} title={group.title} {...(group.meta ? { meta: group.meta } : {})}
          {...(group.chips?.length ? { badge: <>{group.chips.map((each) => <Chip key={each.text} kind={each.kind}>{each.text}</Chip>)}</> } : {})}>
          <RowsTable label={group.title} columns={table.columns} actionsLabel={table.actionsLabel} csrfToken={csrfToken}
            rows={group.rows.flatMap((key) => { const row = byKey.get(key); return row ? [row] : []; })} />
        </Plate>
      ))}
    </Plates>
  );
}

/** A notice of the list: its title, its sentence, its links (" · " between them) and the items it is about. */
function ListNoticeView({ notice }: { notice: ListNotice }) {
  return (
    <Notice tone={notice.tone} {...(notice.title ? { title: notice.title } : {})}>
      {notice.text}
      {notice.link ? <> <a href={notice.link.href}>{notice.link.label}</a></> : null}
      {notice.more?.map((link) => <span key={link.href + link.label}> · <a href={link.href}>{link.label}</a></span>)}
      {notice.items?.length ? (
        <ul className="ui-notice-items">
          {notice.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
    </Notice>
  );
}

/** Whether a cell says anything (a card leaves out a fact with nothing to say, as the classic card does). */
function says(cell: ListCell | undefined): cell is ListCell {
  return Boolean(cell && (cell.text || cell.chip || cell.chips?.length || cell.sub?.length || cell.details));
}

/** The rows as cards of one size in a regular grid: a card's head the first column's cell (its title and code) with the
 *  chip column's cell beside it, its facts the other columns' labels and cells, its foot the foot columns' cells and the
 *  row's actions, kept at the card's bottom. */
function RowCards({ label, columns, rows, cards, csrfToken }: {
  label: string; columns: ListColumn[]; rows: ListRow[]; cards: ListCards; csrfToken: string;
}) {
  const [head, ...rest] = columns;
  const facts = rest.filter((column) => column.key !== cards.chip && !cards.foot.includes(column.key));
  return (
    <ul className="ui-list-cards" aria-label={label}>
      {rows.map((row) => {
        const title = head ? row.cells[head.key] : undefined;
        const chip = cards.chip ? row.cells[cards.chip] : undefined;
        return (
          <li key={row.key} className="ui-list-card" data-status={row.status ?? undefined}>
            <div className="ui-list-card-head">
              <h2 className="ui-list-card-title">
                {title?.href ? <a href={title.href}>{title.text}</a> : title?.text}
                {title?.sub?.length ? <span className="ui-cell-sub">{title.sub.join(' · ')}</span> : null}
              </h2>
              {says(chip) ? <Cell cell={chip} /> : null}
            </div>
            <dl className="ui-list-card-facts">
              {facts.map((column) => {
                const cell = row.cells[column.key];
                return says(cell) ? <div key={column.key}><dt>{column.label}</dt><dd><Cell cell={cell} /></dd></div> : null;
              })}
            </dl>
            <div className="ui-list-card-foot">
              {cards.foot.map((key) => { const cell = row.cells[key]; return says(cell) ? <span key={key}><Cell cell={cell} /></span> : null; })}
              {row.actions.length ? (
                <span className="ui-list-card-actions">
                  {row.actions.map((action) => <Action key={action.href + action.label} action={action} csrfToken={csrfToken} />)}
                </span>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function ListPage({ csrfToken, tabs, toolbar, notices, lines, table, groups, cards, timeline, empty, pager }: ListPageProps) {
  return (
    <>
      {tabs ? <LinkTabs label={tabs.label} tabs={tabs.tabs} /> : null}
      <ListToolbar toolbar={toolbar} />
      {notices.map((notice) => <ListNoticeView key={notice.key} notice={notice} />)}
      {table.rows.length ? (
        <>
          {timeline ? (
            <Plates>
              <Plate title={timeline.title}><Timeline label={timeline.label} ticks={timeline.ticks} lanes={timeline.lanes} /></Plate>
            </Plates>
          ) : null}
          {lines.map((line) => <p key={line} className="ui-cell-sub">{line}</p>)}
          {cards ? <RowCards label={table.label} columns={table.columns} rows={table.rows} cards={cards} csrfToken={csrfToken} />
            : groups && groups.length ? <Groups groups={groups} table={table} csrfToken={csrfToken} />
            : <RowsTable label={table.label} columns={table.columns} rows={table.rows} actionsLabel={table.actionsLabel}
              csrfToken={csrfToken} />}
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
