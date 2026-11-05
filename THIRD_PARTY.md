# Third-party software

Nothing from a package registry is shipped to the browser: the browser runs only this project's own TypeScript, compiled
into `static/js/`. The Python packages the server runs are in `requirements.txt` (pinned with hashes in `docker/requirements.lock`). The
water-chemistry core's Rust crates (the server only) are listed with their licences in `chemcore/THIRD_PARTY`.

## Development-only tools (`package.json` devDependencies)

Used to build and test the browser code on a developer's machine or in CI; never served, never bundled.

| Package | Licence | What it is used for |
|---|---|---|
| `typescript` | Apache-2.0 | Compiles and type-checks `frontend/` |
| `@types/node` | MIT | Types of Node's test runner and assertions, for the TypeScript unit tests only (`tsconfig.test.json`) |
| `playwright-core` | Apache-2.0 | Drives the machine's own Chrome or Edge for the designer's browser test (`frontend/test/designer.browser.test.ts`); no browser is downloaded |
| `axe-core` | MPL-2.0 | Accessibility rules run in that browser test on the designer (serious and critical violations fail it) |
