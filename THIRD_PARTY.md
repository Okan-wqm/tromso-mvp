# Third-party software

Nothing from a package registry is shipped to the browser: the browser runs only this project's own TypeScript, compiled
into `static/js/`. The Python packages the server runs are in `requirements.txt`.

## Shipped to the browser

Served from the project's own static files; no page loads anything from another site (the Content-Security-Policy allows
only the project's address, `config/settings.py` SECURE_CSP).

| Asset | Licence | Where | What it is |
|---|---|---|---|
| Bricolage Grotesque (variable, weight 400 to 700, optical size 12 to 96; Latin and Latin Extended subsets as Google Fonts serves them, v9) | OFL-1.1 (SIL Open Font License 1.1), the licence text in `static/fonts/OFL.txt`; Copyright 2022 The Bricolage Grotesque Project Authors (https://github.com/ateliertriay/bricolage) | `static/fonts/bricolage-grotesque-latin.woff2`, `static/fonts/bricolage-grotesque-latin-ext.woff2`, declared in `static/css/base.css` | The console's typeface |

## Development-only tools (`package.json` devDependencies)

Used to build and test the browser code on a developer's machine or in CI; never served, never bundled.

| Package | Licence | What it is used for |
|---|---|---|
| `typescript` | Apache-2.0 | Compiles and type-checks `frontend/` |
| `@types/node` | MIT | Types of Node's test runner and assertions, for the TypeScript unit tests only (`tsconfig.test.json`) |
| `playwright-core` | Apache-2.0 | Drives the machine's own Chrome or Edge for the designer's browser test (`frontend/test/designer.browser.test.ts`); no browser is downloaded |
| `axe-core` | MPL-2.0 | Accessibility rules run in that browser test on the designer (serious and critical violations fail it) |
