# Third-party software

Nothing from a package registry is shipped to the browser: the browser runs only this project's own TypeScript, compiled
into `static/js/`. The Python packages the server runs are in `requirements.txt`.

## Development-only tools (`package.json` devDependencies)

Used to build and test the browser code on a developer's machine or in CI; never served, never bundled.

| Package | Licence | What it is used for |
|---|---|---|
| `typescript` | Apache-2.0 | Compiles and type-checks `frontend/` |
| `@types/node` | MIT | Types of Node's test runner and assertions, for the TypeScript unit tests only (`tsconfig.test.json`) |
| `playwright-core` | Apache-2.0 | Drives the machine's own Chrome or Edge for the designer's browser test (`frontend/test/designer.browser.test.ts`); no browser is downloaded |
| `axe-core` | MPL-2.0 | Accessibility rules run in that browser test on the designer (serious and critical violations fail it) |

## Server packages with a role beyond the web framework (`requirements.txt`)

| Package | Licence | What it is used for |
|---|---|---|
| `duckdb` 1.5.6 | MIT | The cold tier of the sensor readings (sensors/tiers.py): writes a chunk as a Parquet file and reads it back to verify, restore or chart it; its Parquet writer is built in, nothing else is installed |

The storage of the cold tier is a directory on the server (`COLD_ARCHIVE_DIR`); no object store is used. Any future
store must have a permissive licence (no AGPL: no MinIO). TimescaleDB's compression, continuous aggregates and chunk
functions (`drop_chunks`, `move_chunk`) are features of its community edition (Timescale License), as already used by the
sensors migrations.
