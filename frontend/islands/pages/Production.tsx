// Production › Overview in the new look (config.views.production_home behind ?ui=next, mounted by
// frontend/islands/production.tsx; the design's Production "overview"): today at every site as tiles, what needs
// attention (each row its status chip, what and where, its water values with their status and origin and age, and the
// way to the page that deals with it), the farm's structure, the reports due and the production team today. The server
// reads and words every figure from the classic page's own context (config/production_props.py); this component only
// draws them with the design system. The head (its status chips, Record water sample) is the server's.
import {
  Chip, type ChipKind, EmptyState, LinkButton, List, ListItem, Notice, Plate, Plates, StackedBar, type StackedBarProps,
  Tile, Tiles,
} from '../ui/index.js';

interface Link { href: string; label: string }
interface TileData {
  key: string; label: string; figure: string; href?: string | null; sub?: string | null; source?: string | null;
  status?: 'critical' | 'warning' | null; statusLabel?: string | null;
}
interface Value { label: string; figure: string; kind: ChipKind; sub: string[] }
interface Row {
  key: string; kind: string; chip: { kind: ChipKind; text: string }; title: string; sub: string | null; link: Link | null;
  status: 'critical' | 'warning' | null; values: Value[];
}

export interface ProductionProps {
  empty: { title: string; text: string } | null;
  today: { title: string; meta: string; tiles: TileData[] } | null;
  attention: { title: string; safety: string | null; failed: string | null; rows: Row[]; more: Link | null;
    nothing: { chip: string; text: string } | null } | null;
  farm: { title: string; source: string; tiles: TileData[]; groups: { title: string; tiles: TileData[] }[] } | null;
  reports: { title: string; badge: string | null; items: { key: string; text: string; sub: string; link: Link | null }[];
    empty: string | null; notSetUp: string | null; link: Link } | null;
  team: { title: string; stack: StackedBarProps; line: string; link: Link } | null;
}

function TileOf({ tile }: { tile: TileData }) {
  return (
    <Tile label={tile.label} figure={tile.figure} {...(tile.sub ? { sub: tile.sub } : {})}
      {...(tile.source ? { source: tile.source } : {})} {...(tile.href ? { href: tile.href } : {})}
      {...(tile.status ? { status: tile.status } : {})} {...(tile.statusLabel ? { statusLabel: tile.statusLabel } : {})} />
  );
}

function AttentionRow({ row }: { row: Row }) {
  return (
    <ListItem status={row.status ?? undefined} main={(
      <>
        <span><Chip kind={row.chip.kind}>{row.chip.text}</Chip> <strong>{row.title}</strong></span>
        {row.values.map((value) => (
          <span key={value.label} className="ui-cell-sub">
            {value.label} <Chip kind={value.kind}>{value.figure}</Chip>{value.sub.length ? ` ${value.sub.join(' · ')}` : ''}
          </span>
        ))}
      </>
    )} {...(row.sub ? { sub: row.sub } : {})}
      {...(row.link ? { meta: <LinkButton href={row.link.href} variant="ghost">{row.link.label}</LinkButton> } : {})} />
  );
}

export function Production({ empty, today, attention, farm, reports, team }: ProductionProps) {
  if (empty) return <EmptyState title={empty.title}>{empty.text}</EmptyState>;
  return (
    <Plates>
      {today ? (
        <Plate title={today.title} meta={today.meta} span={12}>
          <Tiles label={today.title}>{today.tiles.map((tile) => <TileOf key={tile.key} tile={tile} />)}</Tiles>
        </Plate>
      ) : null}

      {attention ? (
        <Plate title={attention.title} safety={attention.safety ?? undefined} span={farm ? 8 : 12}
          foot={attention.more ? <a href={attention.more.href}>{attention.more.label}</a> : undefined}>
          {attention.failed ? <Notice tone="warning">{attention.failed}</Notice> : null}
          {attention.nothing ? (
            <p className="ui-plate-body"><Chip kind="ok">{attention.nothing.chip}</Chip> {attention.nothing.text}</p>
          ) : (
            <List label={attention.title}>{attention.rows.map((row) => <AttentionRow key={row.key} row={row} />)}</List>
          )}
        </Plate>
      ) : null}

      {farm ? (
        <Plate title={farm.title} span={attention ? 4 : 12} foot={farm.source}>
          <Tiles size="small" label={farm.title}>{farm.tiles.map((tile) => <TileOf key={tile.key} tile={tile} />)}</Tiles>
          {farm.groups.map((group) => (
            <section key={group.title} aria-label={group.title}>
              <p className="ui-plate-body"><strong>{group.title}</strong></p>
              <Tiles size="small" label={group.title}>{group.tiles.map((tile) => <TileOf key={tile.key} tile={tile} />)}</Tiles>
            </section>
          ))}
        </Plate>
      ) : null}

      {reports ? (
        <Plate title={reports.title} link={reports.link} span={team ? 6 : 12}
          badge={reports.badge ? <Chip kind="critical">{reports.badge}</Chip> : undefined}>
          {reports.notSetUp ? <Notice tone="warning">{reports.notSetUp}</Notice> : null}
          {reports.empty ? <EmptyState title={reports.empty} /> : (
            <List label={reports.title}>
              {reports.items.map((item) => (
                <ListItem key={item.key} main={item.text} sub={item.link
                  ? <>{item.sub}, <a href={item.link.href}>{item.link.label}</a></> : item.sub} />
              ))}
            </List>
          )}
        </Plate>
      ) : null}

      {team ? (
        <Plate title={team.title} link={team.link} span={reports ? 6 : 12}>
          <div className="ui-plate-body">
            <StackedBar {...team.stack} />
            <p className="ui-cell-sub">{team.line}</p>
          </div>
        </Plate>
      ) : null}
    </Plates>
  );
}
