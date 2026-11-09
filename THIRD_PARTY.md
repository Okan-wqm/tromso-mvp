# Third-party software

Nothing from a package registry is shipped to the browser: the browser runs only this project's own TypeScript, compiled
into `static/js/`. The Python packages the server runs are in `requirements.txt` (pinned with hashes in `docker/requirements.lock`). The
water-chemistry core's Rust crates (the server only) are listed with their licences in `chemcore/THIRD_PARTY`.

## Fonts served to the browser (`static/fonts/`)

The two typefaces of the design system (`docs/design/system/README.md`, Type), self-hosted as WOFF2 so that no page asks
another server for anything and the console works offline on site (`static/css/fonts.css`). Both are under the SIL Open
Font License 1.1, which allows commercial use, embedding and redistribution with the licence kept beside the files (it
is, in `static/fonts/OFL-*.txt`); only the fonts on their own may not be sold. Taken from Google Fonts (the Latin and
Latin Extended subsets) on 08.11.2026.

| Font | Licence | Copyright | Used for |
|---|---|---|---|
| Atkinson Hyperlegible Next (variable, 400–700) | OFL-1.1 (`static/fonts/OFL-atkinson-hyperlegible-next.txt`) | 2020-2024 The Atkinson Hyperlegible Next Project Authors | Every text read or entered (`--font-text`) |
| Bricolage Grotesque (600, optical size axis) | OFL-1.1 (`static/fonts/OFL-bricolage-grotesque.txt`) | 2022 The Bricolage Grotesque Project Authors | h1, h2 and the wordmark (`--font-display`) |


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
