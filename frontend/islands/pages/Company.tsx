// Company › Overview in the new look (config.views.home behind ?ui=next, mounted by frontend/islands/company.tsx; the
// design's Company Panel v2, "overview"): what the company is doing now, a plate per area the person may read. The server
// reads and words every figure (config/company_props.py); this component only draws them with the design system.
import {
  AuditItem, CellLines, Chip, type ChipKind, EmptyState, List, ListItem, Notice, Plate, Plates, Table, Tile, Tiles,
} from '../ui/index.js';

interface Link { href: string; label: string }
interface TileData {
  key: string; label: string; figure: string; sub?: string | null; sub2?: string | null; source?: string | null;
  href?: string | null; status?: 'critical' | 'warning' | null; statusLabel?: string | null;
}
interface SiteRow {
  key: string; name: string; code: string; href: string | null; type: string; status: 'critical' | 'warning' | null;
  units: string | null; biomass: string | null; water: { kind: ChipKind; text: string } | null;
  /** the site's open alarms (a figure) and, under it, its units' water now (alarms.read.attention, counted in units) */
  alarms: { figure: string; sub: string | null } | null;
  onSite: string | null;
}
interface AlarmRow { key: string; severity: string; kind: 'critical' | 'warning'; what: string; href: string; where: string }
interface UpcomingItem { key: string; status: 'critical' | null; text: string; sub: string[]; link: Link | null }
interface FeedRow { key: string; item: string; site: string; onHand: string; cover: string | null; status: 'warning' | null; note: string | null }
interface MessageRow { key: string; title: string; href: string; text: string; when: string }
interface Entry {
  key: string; action: string; critical: boolean; record: string; by: { before: string; name: string; after: string };
  when: string;
}
interface KnowledgeRow { key: string; text: string; source: string; href: string; kind: ChipKind; chip: string }

export interface CompanyProps {
  today: { title: string; meta: string; tiles: TileData[] };
  sites: { title: string; link: Link; columns: Record<string, string>; rows: SiteRow[]; none: string; empty: string | null } | null;
  alarms: { title: string; link: Link; safety: string | null; columns: Record<string, string>; rows: AlarmRow[];
    more: string | null; empty: string | null;
    /** the stocked units' line (core.ui.attention_said) when one is flagged: said even when no alarm row is open */
    units: { tone: 'critical' | 'warning'; text: string } | null } | null;
  people: { title: string; link: Link; tiles: TileData[] } | null;
  upcoming: { title: string; items: UpcomingItem[]; empty: string | null; badge: string | null; link: Link;
    notSetUp: string | null } | null;
  feed: { title: string; link: Link; columns: Record<string, string>; rows: FeedRow[]; none: string; empty: string | null } | null;
  messages: { title: string; link: Link; rows: MessageRow[]; empty: string | null } | null;
  activity: { title: string; link: Link; critical: string; entries: Entry[]; empty: string | null } | null;
  knowledge: { title: string; link: Link; rows: KnowledgeRow[]; empty: string | null } | null;
}

function TileOf({ tile }: { tile: TileData }) {
  return (
    <Tile label={tile.label} figure={tile.figure} {...(tile.sub ? { sub: tile.sub } : {})} {...(tile.sub2 ? { sub2: tile.sub2 } : {})}
      {...(tile.source ? { source: tile.source } : {})} {...(tile.href ? { href: tile.href } : {})}
      {...(tile.status ? { status: tile.status } : {})} {...(tile.statusLabel ? { statusLabel: tile.statusLabel } : {})} />
  );
}

export function Company({ today, sites, alarms, people, upcoming, feed, messages, activity, knowledge }: CompanyProps) {
  return (
    <Plates>
      <Plate title={today.title} meta={today.meta} span={12}>
        <Tiles label={today.title}>{today.tiles.map((tile) => <TileOf key={tile.key} tile={tile} />)}</Tiles>
      </Plate>

      {sites ? (
        <Plate title={sites.title} link={sites.link} span={8}>
          {sites.empty ? <EmptyState title={sites.empty} /> : (
            <Table<SiteRow>
              label={sites.title}
              rows={sites.rows}
              rowKey={(row) => row.key}
              rowStatus={(row) => row.status ?? undefined}
              columns={[
                { key: 'site', label: sites.columns.site, rowHeader: true, render: (row) => (
                  <CellLines strong sub={row.code} main={row.href ? <a href={row.href}>{row.name}</a> : row.name} />) },
                { key: 'type', label: sites.columns.type },
                { key: 'units', label: sites.columns.units, numeric: true, render: (row) => row.units ?? sites.none },
                { key: 'biomass', label: sites.columns.biomass, numeric: true, render: (row) => row.biomass ?? sites.none },
                { key: 'water', label: sites.columns.water, render: (row) => (row.water
                  ? <Chip kind={row.water.kind}>{row.water.text}</Chip> : sites.none) },
                { key: 'alarms', label: sites.columns.alarms, numeric: true, render: (row) => (row.alarms
                  ? <CellLines main={row.alarms.figure} sub={row.alarms.sub ?? undefined} /> : sites.none) },
                { key: 'onSite', label: sites.columns.onSite, numeric: true, render: (row) => row.onSite ?? sites.none },
              ]}
            />
          )}
        </Plate>
      ) : null}

      {alarms ? (
        <Plate title={alarms.title} link={alarms.link} safety={alarms.safety ?? undefined} span={4}
          foot={alarms.more ? <a href={alarms.link.href}>{alarms.more}</a> : undefined}>
          {alarms.units ? <Notice tone={alarms.units.tone}>{alarms.units.text}</Notice> : null}
          {alarms.empty ? <EmptyState title={alarms.empty} /> : !alarms.rows.length ? null : (
            <Table<AlarmRow>
              label={alarms.title}
              rows={alarms.rows}
              rowKey={(row) => row.key}
              rowStatus={(row) => row.kind}
              columns={[
                { key: 'severity', label: alarms.columns.severity, render: (row) => <Chip kind={row.kind}>{row.severity}</Chip> },
                { key: 'what', label: alarms.columns.what, render: (row) => (
                  <CellLines main={<a href={row.href}>{row.what}</a>} sub={row.where} />) },
              ]}
            />
          )}
        </Plate>
      ) : null}

      {people ? (
        <Plate title={people.title} link={people.link} span={4}>
          <Tiles size="small" label={people.title}>{people.tiles.map((tile) => <TileOf key={tile.key} tile={tile} />)}</Tiles>
        </Plate>
      ) : null}

      {upcoming ? (
        <Plate title={upcoming.title} link={upcoming.link} span={4}
          badge={upcoming.badge ? <Chip kind="critical">{upcoming.badge}</Chip> : undefined}>
          {upcoming.notSetUp ? <Notice tone="warning">{upcoming.notSetUp}</Notice> : null}
          {upcoming.empty ? <EmptyState title={upcoming.empty} /> : (
            <List label={upcoming.title}>
              {upcoming.items.map((item) => (
                <ListItem key={item.key} status={item.status ?? undefined} main={item.text} sub={<>
                  {item.sub.join(' · ')}
                  {item.link ? <> · <a href={item.link.href}>{item.link.label}</a></> : null}
                </>} />
              ))}
            </List>
          )}
        </Plate>
      ) : null}

      {feed ? (
        <Plate title={feed.title} link={feed.link} span={4}>
          {feed.empty ? <EmptyState title={feed.empty} /> : (
            <Table<FeedRow>
              label={feed.title}
              rows={feed.rows}
              rowKey={(row) => row.key}
              rowStatus={(row) => row.status ?? undefined}
              columns={[
                { key: 'item', label: feed.columns.item, rowHeader: true, render: (row) => (
                  <CellLines main={row.item} sub={row.note ? `${row.site} · ${row.note}` : row.site} />) },
                { key: 'onHand', label: feed.columns.onHand, numeric: true },
                { key: 'cover', label: feed.columns.cover, numeric: true, render: (row) => row.cover ?? feed.none },
              ]}
            />
          )}
        </Plate>
      ) : null}

      {messages ? (
        <Plate title={messages.title} link={messages.link} span={4}>
          {messages.empty ? <EmptyState title={messages.empty} /> : (
            <List label={messages.title}>
              {messages.rows.map((row) => (
                <ListItem key={row.key} main={<a href={row.href}>{row.title}</a>} sub={row.text} meta={row.when} />
              ))}
            </List>
          )}
        </Plate>
      ) : null}

      {activity ? (
        <Plate title={activity.title} link={activity.link} span={4}>
          {activity.empty ? <EmptyState title={activity.empty} /> : (
            <List ordered label={activity.title}>
              {activity.entries.map((entry) => (
                <AuditItem key={entry.key} action={entry.action} record={entry.record}
                  status={entry.critical ? 'critical' : undefined}
                  critical={entry.critical ? <Chip kind="critical">{activity.critical}</Chip> : undefined}
                  who={<>{entry.by.before} <strong>{entry.by.name}</strong> {entry.by.after} · {entry.when}</>} />
              ))}
            </List>
          )}
        </Plate>
      ) : null}

      {knowledge ? (
        <Plate title={knowledge.title} link={knowledge.link} span={4}>
          {knowledge.empty ? <EmptyState title={knowledge.empty} /> : (
            <List label={knowledge.title}>
              {knowledge.rows.map((row) => (
                <ListItem key={row.key} main={<a href={row.href}>{row.text}</a>} sub={row.source}
                  chip={<Chip kind={row.kind}>{row.chip}</Chip>} />
              ))}
            </List>
          )}
        </Plate>
      ) : null}
    </Plates>
  );
}

