// The Shift schedule in the new look (hr.resources.ShiftAssignmentResource behind ?ui=next, mounted by
// frontend/islands/roster.tsx): the week's links, the list's toolbar (search and department as one GET form that keeps the
// week), the people shown and the pages, the roster grid with its paint (ui/RosterGrid.tsx), or the empty state; and the
// Crew block for a worker. The server words and decides everything (hr.resources.roster.next_props).
import {
  CellLines, Chip, type ChipKind, EmptyState, ListToolbar, type ListPageProps, Plate, RosterGrid,
  type RosterGridProps, Table,
} from '../ui/index.js';

interface Link { href: string; label: string }
interface CrewRow { key: string; name: string; sub: string; cells: ({ kind: ChipKind; text: string; sub: string } | null)[] }

export interface RosterPageProps {
  week: { label: string; previous: Link; title: string; next: Link; print: string };
  toolbar: ListPageProps['toolbar'];
  line: { text: string; links: Link[] };
  grid: RosterGridProps;
  empty: { title: string; text: string } | null;
  crew: { title: string; head: string; days: { key: string; head: string; sub: string }[]; rows: CrewRow[]; text: string | null } | null;
}

/** `week` (its links and title) is drawn by the page head (templates/hr/roster_next.html), as the design puts it. */
export function Roster({ toolbar, line, grid, empty, crew }: RosterPageProps) {
  return (
    <>
      <ListToolbar toolbar={toolbar} />
      {empty ? <EmptyState title={empty.title}>{empty.text}</EmptyState> : (
        <>
          <p className="ui-cell-sub">{line.text}{line.links.map((link) => <span key={link.href}> <a href={link.href}>{link.label}</a></span>)}</p>
          <RosterGrid {...grid} />
        </>
      )}
      {crew ? (
        <Plate title={crew.title} span={12}>
          {crew.rows.length ? (
            <Table<CrewRow>
              label={crew.title}
              rows={crew.rows}
              rowKey={(row) => row.key}
              columns={[
                { key: 'name', label: crew.head, rowHeader: true, render: (row) => <CellLines strong main={row.name} sub={row.sub} /> },
                ...crew.days.map((day, index) => ({
                  key: day.key, label: <>{day.head}<span className="ui-cell-sub">{day.sub}</span></>,
                  render: (row: CrewRow) => {
                    const cell = row.cells[index];
                    return cell ? <CellLines main={<Chip kind={cell.kind}>{cell.text}</Chip>} sub={cell.sub} /> : null;
                  },
                })),
              ]}
            />
          ) : <div className="ui-plate-body"><p className="ui-empty-text">{crew.text}</p></div>}
        </Plate>
      ) : null}
    </>
  );
}
