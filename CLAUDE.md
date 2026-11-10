# CLAUDE.md

Guidance for Claude Code (and its agents) working in this repository. The README (about 4,500 lines) is the
reference: read the section for the area you touch, not the whole file. This file holds what the README does not
say in one place: the owner's standing rules, how work lands, and this machine's traps.

## What this is

A fish-farm management MVP (land-based and sea sites) for a university pilot: server-rendered Django 6.1 on
PostgreSQL 17 + TimescaleDB 2.17, browser code in TypeScript, two Rust parts (`chemcore/`, the water-chemistry
core called through PyO3, and `sensors-ingest/`, the MQTT ingest). It started as a port of the farm module of
Suderra's aquaculture platform and has grown its own apps: `farm`, `inventory`, `tasks`, `reports`, `messaging`,
`knowledge`, `experiments`, `hr`, `monitoring`, `sensors`, `alarms`. The code map is README › Layout of the code.

It will be used on real farms with live fish. A wrong figure, a silent stale value or a lost record is a safety
problem, not a cosmetic one.

## Never

- Never touch production: `app.suderra.com`, `89.38.97.90`, the Cloudflare account. Never log in there.
- Never write to the source platform checkout (`F:\snowball-work\aquaculture_platform`): it is read-only reference.
- Never work in the stale copy under `J:\İCLOUD\...\Programlar\balik-ciftligi`. The repository is `F:\dev\balik-ciftligi`.
- Never put new work on drive C. Worktrees: `F:\dev\balik-wt\<name>`. Plans, reviews, tools, shots: `F:\dev\balik-notes\`.
- Never port anything satellite-related (satellite tables, Sentinel Hub settings, satellite UI).
- Never write JavaScript by hand: TypeScript only (`frontend/*.ts`, strict), no inline scripts, no chemistry in the browser.
- Never hard-code a limit, threshold, delay or rule a farm would want to change: it is user-editable reference data
  with seeded defaults.
- Never block a handling action on withdrawal or fasting: warn, store the acknowledgement, log it as critical.
- Never show a stale or assumed value silently: say "incomplete" or "no recent data" with the reason.
- Never add a dependency with a non-commercial, AGPL, SSPL or BUSL licence (MinIO and rodbus are banned by CI).
- Never add a `Co-Authored-By` trailer or a personal name to a commit, branch, PR or file. The only identity on
  GitHub is `Okan-wqm` with its noreply e-mail (already this repository's git config).
- Never delete someone's work in progress, an unmerged branch or a worktree with uncommitted changes.

## Commands

Everything runs in Docker; the Windows virtual environment cannot start the server (no `chemcore` module) and is
only good for small scripts. Use Git Bash for the scripts.

```
scripts/test.sh                              # whole Django suite, 6 workers, own throwaway TimescaleDB (13-20 min idle, far longer under load)
scripts/test.sh farm.tests.test_stock core   # only these labels (any `manage.py test` argument passes through)
CHECKS=1 SUITE=0 scripts/test.sh             # the project checks only, as CI runs them on a pull request (minutes)
npm run build                                # tsc -> static/js (not committed), Tailwind -> static/css/tw.css (committed)
npm run check && npm run check:css && npm test   # type check, tw.css up to date, TypeScript tests
chemcore/scripts/test.sh                     # chemistry core gates (run in the chemcore-tools image, see the script's header)
```

Run one full suite at a time: the machine is shared and loaded. Warnings are errors in every test run
(deprecations, naive datetimes).

After changing models or text, in the test runner's image (README › Tests, Data map, Languages):
`manage.py makemigrations --check`, `manage.py data_map` (commit `docs/data-map.md` and `.json`),
`manage.py update_catalogs` (commit `locale/*/django.po`, with the Norwegian and Turkish translations filled in).

### Development server (http://127.0.0.1:8047)

The database, broker and ingest are the compose project `balik-ciftligi` (`docker compose up -d`; DB on host port
5433, role and database `balik`). The app runs in a container from the test runner's image:

```
docker build -f docker/testrunner.Dockerfile -t balik-testrunner-chemcore .
MSYS_NO_PATHCONV=1 docker run --rm --name balik-dev-web --network balik-ciftligi_default -p 18047:8047 \
  -e DB_HOST=db -e DB_PORT=5432 -e COMPANY_NAME="Nordhav Akva" -v F:/dev/balik-ciftligi:/app -w /app \
  balik-testrunner-chemcore python manage.py runserver 0.0.0.0:8047 --noreload
```

Docker Desktop's 127.0.0.1 port relay hangs on this machine, so `F:\dev\balik-notes\tools\forward.py` forwards
127.0.0.1:8047 to the docker-desktop VM address on 18047 (`wsl -d docker-desktop ip -4 addr show eth0`; it changes
when WSL restarts). The server runs with `--noreload`: restart the container after landing code. Rebuild the image
when `chemcore/` or `requirements.txt` changed.

## How the code is built

- **One format for every tab.** A tab is a `Resource` on `core/crud.py` (permissions, audit, version, soft delete,
  dialog and page); it adds only its own model, form and template bits. Follow README › Adding a tab: model on
  `AuditedModel`, form on `TabbedForm`, the area in `config/access.py`, the menu entry in `config/navigation.py`,
  create/read/edit/delete tests through the pages checked against the stored rows, the data map, the translations.
  `TabRulesTests`, `core.test_datamap` and the catalog tests enforce it.
- **One write path, one read API per area** (`services.py`, `read.py`, a `fold.py` for ledgers). Rules live there,
  never in views. Corrections are void + new record with who, when and why; the activity log is append-only.
- **Fix the class, not the case.** Close a problem at the layer it belongs to (a constraint, the delete plan in
  `core/softdelete.py`, a shared resolver), with a test that fails without the fix. No patches, no duplicates, no
  second implementation of something that exists: search first.
- **Do not port the source's bugs.** The source platform is faulty end to end; trace every field from the UI to
  the column, fix on our side at the model or constraint, and record each source bug in
  `docs/aquaculture-platform-bugs.md`.
- **Everything is linked and integrated when it lands**: audit log, role matrix, menu, delete plan, admin restore,
  database viewer, data map, three languages, README. Nothing is deferred to "later".
- **Chemistry is cited.** Every constant and test value in `chemcore/` names a primary source; nothing changes a
  result silently (golden files, the `chemcore/EXPECTED` handshake). A change to chemistry numbers needs the
  owner's approval and an independent check.
- **Text.** UI source text is English, with Norwegian bokmål and Turkish translations in the same change; the
  activity log is stored in English and translated at display. Dates are shown dd.mm.yyyy. Every text file is LF.
- **Design.** Tailwind v4 compiled to `static/css/tw.css` over the role tokens (all five themes must work; no CDN,
  CSP-safe). Overview and dashboard pages are dense metric-card grids; a redesign never drops information the old
  page showed. Page-design work uses the frontend-design skill. Pages are redesigned one at a time, and only the
  page the owner has named (`F:\dev\balik-notes\plan\pages\PAGES.md`).

## How work lands

`main` is the only long-lived branch; there are no pull requests in daily work (CI runs the whole suite on every
push to `main`). Work happens on a `wip/<name>` branch in a worktree under `F:\dev\balik-wt\`, in small logical
commits with the test commit beside the code commit. Commit subjects start with the date and time:
`[YYYY-MM-DD HH:MM +zzzz] Subject` (from `date '+%Y-%m-%d %H:%M %z'`).

Landing a branch, one at a time, in the agreed order:

1. Independent review of the branch (a reviewer that did not write it), findings fixed on the branch.
2. Merge `main` into the branch; renumber migrations after main's; regenerate the data map and the catalogs.
3. Full `scripts/test.sh` on the branch, plus `makemigrations --check`, `npm run check`, `npm test`.
   A branch with a migration or a change under `sensors-ingest/` also runs `sensors-ingest/tests/run.sh` (CI's `rust` job: the ingest's tests on the schema Django migrates).
4. Back up the dev database (`pg_dump -U balik`, about 7 minutes, into `Programlar\db-backups\`).
5. Fast-forward `main`, then `migrate` + `compile_catalogs` + `npm run build` in one go, restart the dev server.
6. Live check through the real pages (create, edit and delete one record of every new kind; crawl the pages in
   EN, NB and TR), then push, then remove the worktree and delete the merged branch.
7. Update the README section and the relevant notes in the same batch, and tell the owner what to click to check.

Before `git worktree remove`: a worktree's `node_modules` may be a junction to the main checkout's. Remove the
junction first (PowerShell: `(Get-Item <wt>\node_modules -Force).Delete()`), or main's `node_modules` is emptied.

Features the owner postponed (ask before building): overfeed/underfeed alarms, multi-tenant, payroll, the DRF API,
the mobile app. New features wait while in-flight branches are being landed.

## Working with agents

- Stay within the agent count agreed with the owner; ask before scaling up.
- Analysis agents read the code, not the Markdown notes; implementation agents get their own worktree; the
  coordinator reviews. Expert panels are evidence-only and re-check each other's claims.
- Notes, registers and memory rows are hints: verify against the code, the tests and the latest run before acting.
- Report to the owner in Turkish, plainly, with a "weak points" part (what was not verified, what repeated, what
  was lost). The owner checks the UI, not the code: show visible progress and say what to click.

## Where things are

| What | Where |
|---|---|
| Plans (alarms, experiments access, perf, pages, backlog, ...) | `F:\dev\balik-notes\plan\<area>\` (`PLAN.md`, `BACKLOG.md`, `PAGES.md`) |
| Reviews, audits, science verification | `F:\dev\balik-notes\` (`audit\`, `audit-verify\`, `verify-science\VERIFY.md`) |
| Tools (port forwarder, page crawler) | `F:\dev\balik-notes\tools\` |
| Database backups | `J:\İCLOUD\iCloudDrive\suderra\Programlar\db-backups\` |
| Design brief and screenshots | `docs/design/`, `J:\İCLOUD\iCloudDrive\suderra\Programlar\claude-design\` |
| Source platform (read-only) | `F:\snowball-work\aquaculture_platform` |
| A paused branch's state | `PAUSED.md` at the top of its worktree |
