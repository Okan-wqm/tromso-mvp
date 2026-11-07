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

## Test-only Python packages (`scripts/testrunner/requirements.txt`)

Installed only in the image the tests run in (`scripts/test.sh`); never on a server.

| Package | Licence | What it is used for |
|---|---|---|
| `tblib` | BSD-2-Clause | Lets the parallel test runner send a failing test's traceback from its worker to the main process |
