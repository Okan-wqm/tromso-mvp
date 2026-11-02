# Fish farm prototype

A small Django prototype of the farm module of Suderra's aquaculture platform: Django 6.1 on
PostgreSQL 17 with TimescaleDB 2.17 (Docker). The farm module's tabs are ported one at a time.

What works today:

- Sign in, sign out, forgot password (reset link by email), change password. All of it is Django's
  built-in auth: PBKDF2 password hashing, signed one-time reset tokens, the standard password
  validators, CSRF protection and sign-out by POST only.
- An activity log (`/activity/`): who created, changed or deleted which record, when, with the old
  and new value of every changed field. Rows are written in the same transaction as the change and a
  database trigger refuses to update or delete them. Each record's form has a History tab.
- Every page needs a signed-in user (`LoginRequiredMiddleware`) unless its view opts out.
- The console shell: a left menu that collapses (296 px to 110 px, icon over label), remembers the
  choice, collapses by itself below 1100 px when no choice is saved and slides in from the left on
  phones; a sticky top bar with the page title and the user menu.

## Ported farm tabs

Each tab is ported from `aquaculture_platform` (farm-service entities and migrations, farm-module
React forms) and reviewed before the next one starts. Every form has tests that create, read, edit
and delete through the pages and check what is stored in the database.

### Facility › Sites (`/sites/`)

Tables `sites` and `site_contacts`. Cards with search by name, code or region; a form with three
inner tabs (Basic info, Location, Contact); contacts saved as a whole list on the Contact tab;
delete is a soft delete. Differences from the source:

- Single company: no `tenantId`, no row-level security.
- Satellite monitoring is not ported (monitoring radius, monitoring area, its revision trigger).
- The jsonb `location` and `address` are flat columns (latitude, longitude, altitude, street, city,
  state, postal code); the source kept city and country twice.
- Code, name and lokalitetsnummer are unique among live sites and at most one contact is primary,
  as database constraints; the source enforced most of this only in service code.
- Column lengths win where the source's form allowed longer values (name 150, code 20, email 150).
- Editing is guarded by the `version` column: a save based on an old version is refused.
- Delete blockers (tanks holding biomass) and the cascade to departments, systems and equipment
  come with those tabs.

## Local setup

```
npm install && npm run build                 # compiles frontend/*.ts into static/js (use `npm run watch` while editing)
docker compose up -d                         # TimescaleDB on localhost:5433 (5432 is often a local PostgreSQL)
C:\Python312\python.exe -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python.exe manage.py migrate   # also enables the timescaledb extension (core/migrations)
.venv\Scripts\python.exe manage.py createsuperuser
.venv\Scripts\python.exe manage.py runserver 8047
```

The database connection reads `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` and `DB_PORT`; the
defaults match the local container in `docker-compose.yml`.

## Browser code

There is no hand-written JavaScript. The browser code is TypeScript in `frontend/` (strict mode),
compiled by `npm run build` into `static/js/`, which is not committed:

- `nav-boot.ts` sets the rail state before the first paint and owns the open/collapsed rule;
- `shell.ts` the rail toggle, the phone menu and the user menu;
- `components.ts` the shared parts every tab uses through data attributes: the dialog
  (`data-modal`), inner tabs, upper-case inputs and row lists;
- `auth.ts` the show/hide password button.

## One format for every tab

`core/crud.py` turns a `Resource` (model, form, labels, list template) into list, create, edit and
delete pages. Every tab gets the same behaviour from it: a role needs view/add/change/delete on the
model for each page (the platform admin has all of them), every change is written to the activity
log in the same transaction, an outdated `version` is refused, models with soft delete are hidden
rather than erased, and forms and confirmations open in a dialog (`templates/modal_base.html`) or,
opened directly, as a page. The rail menu is data (`config/navigation.py`) and shows each entry
only to people allowed to read it. There are no built-in roles: the platform admin creates roles
and grants permissions.

## Email

Email uses the console backend for now: the password reset email is printed in the `runserver`
terminal instead of being sent. Put an SMTP backend into `MAILERS` in `config/settings.py` to send
real mail.

## Pages

| Path | Page |
|---|---|
| `/` | Overview (sign-in required) |
| `/sites/` | Facility › Sites |
| `/activity/` | Activity log |
| `/accounts/login/` | Sign in |
| `/accounts/logout/` | Sign out (POST) |
| `/accounts/password_reset/` | Forgot password |
| `/accounts/password_change/` | Change password |
| `/admin/` | Django admin |

## Layout of the code

| Path | Contents |
|---|---|
| `config/` | Settings, URLs, the overview view |
| `core/` | TimescaleDB extension, audit log (model, append-only trigger, `audit.py` helpers, activity page), tests |
| `farm/` | Farm module: models, forms, views, tests |
| `core/crud.py`, `templates/crud/`, `templates/modal_base.html`, `static/js/components.js` | One format for every tab: list, form, delete, dialog, permissions, audit |
| `core/navigation.py`, `config/navigation.py` | The rail menu as data, filtered by permission |
| `farm/resources.py`, `templates/farm/` | Farm tabs declared on top of `core.crud` |
| `static/css/components.css` | Shared page components (buttons, cards, tabs, form grids, audit trail) |
| `templates/auth_base.html`, `templates/registration/` | Sign-in and password pages |
| `templates/app_base.html`, `templates/icons/` | Console shell (rail, top bar, user menu), Lucide icons |
| `static/css/base.css` | Colour tokens, reset, form controls shared by every page |
| `static/css/auth.css` | Sign-in layout |
| `static/css/app.css` | Console shell layout |
| `frontend/`, `tsconfig.json`, `package.json` | Browser code in TypeScript |

## Tests

```
.venv\Scripts\python.exe manage.py test
```

The tests need the database container running (they check the timescaledb extension too).
