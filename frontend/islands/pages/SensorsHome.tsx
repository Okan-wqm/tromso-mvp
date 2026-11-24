// Sensors › Overview in the new look (sensors.views.home behind ?ui=next; the design's Sensors "overview"): the ingest's
// state (alive or down, devices online, channels without a fresh value, open alarm events, dead letters, what the ingest
// could not keep) and the configuration counted, each tile a link to its page. The server reads and words every figure
// (sensors/pages.py `home_props`, from the classic page's own reads); this component only draws them.
import { EmptyState, Plate, Plates, Tile, Tiles } from '../ui/index.js';

interface TileData { key: string; label: string; figure: string; href: string }
interface Block { title: string; meta?: string; tiles: TileData[] }

export interface SensorsHomeProps { state: Block | null; setup: Block | null; empty: string | null }

export function SensorsHome({ state, setup, empty }: SensorsHomeProps) {
  if (empty) return <EmptyState title={empty} />;
  return (
    <Plates>
      {state ? (
        <Plate title={state.title} meta={state.meta} span={12}>
          <Tiles label={state.title}>{state.tiles.map((tile) => <Tile key={tile.key} label={tile.label} figure={tile.figure} href={tile.href} />)}</Tiles>
        </Plate>
      ) : null}
      {setup ? (
        <Plate title={setup.title} span={12}>
          <Tiles size="small" label={setup.title}>{setup.tiles.map((tile) => <Tile key={tile.key} label={tile.label} figure={tile.figure} href={tile.href} />)}</Tiles>
        </Plate>
      ) : null}
    </Plates>
  );
}
