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
- Roles (`/roles/`) and users (`/users/`), managed by the platform admin only (see Roles and users).
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
- Deleting a site leaves its production departments without a site (see Production departments); the other dependants
  join the delete plan as their tabs arrive.

### Production departments (`/production-departments/`)

The farm's production departments: a hatchery hall, a nursery, a grow-out unit on a site. They are not the
company's organisational departments (management, HR and the like), which come with the HR module.
Table `production_departments` (renamed from `departments` by migration 0004, data kept): a table (production
department, type, site, capacity) with search by name or code, a
site filter that includes "without a site", a flat form in the dialog and delete. Differences from
the source:

- A production department belongs to a site chosen once, at creation. Deleting a site leaves its production departments
  without a site, as in the source; the confirmation lists them and each gets its own activity-log
  row (see the delete plan below).
- The source's `administration` type is not carried over: an administrative department is an organisational one.
- Code is unique among live production departments and a name is unique within a site, as database
  constraints; capacity cannot be negative.
- Not carried over: `settings` and `area` (accepted but never stored), the second status flag
  `isActive`, the load figure that was never filled in. Notes can be shown and cleared.
- The manager is a user of this system, and can be removed.

The bugs found in the source while porting are listed in
[docs/aquaculture-platform-bugs.md](docs/aquaculture-platform-bugs.md), with how each is avoided here.

### Facility › Systems (`/systems/`)

Table `systems`: a table (system, type, status, site, production department, volume, max biomass), nested
systems shown under their parent, search by name or code, filters by site and by production department
(including "without a production department"), a form in the dialog and delete. A system belongs to a site
(chosen once) and optionally to a production department of that site and to a parent system of that site.
Differences from the source:

- The links are checked on every save, not on create only: the production department must be on the system's
  site, a parent on the same site, and a system cannot be nested under itself or anything below it.
  The parent list offers only valid choices (the source excluded the system itself but not its
  descendants and was narrowed by the list's own filters).
- A link or the description can be cleared when editing (the source sent `undefined`, which the API
  reads as "no change").
- Volume and biomass cannot be negative (database check and form).
- The hand-typed tank count is not carried over: it would drift from the real tanks and is derived
  once tanks exist. The second status flag `isActive` is not carried over either.
- Code is unique within a site among live systems.
- Deleting a site deletes its systems, a system the systems nested under it, and a production department
  leaves its systems without one, all through the delete plan.

## Roles and users

There are no built-in roles. The platform admin (a Django superuser) can open everything and is the
only one who manages roles and users; everyone else gets exactly what their roles allow.

- **Access areas** (`config/access.py`, read by `core/access.py`): the parts of the console a role
  can be given, one line each, with the actions each offers. Today: Facility › Sites (read, create,
  edit, delete) and Administration › Activity log (read). A new tab appears in the matrix by adding
  its line there. Roles and users are not areas, so no role can grant them.
- **Roles** (`/roles/`, Django `Group`): a table with each role's users and what it allows; the
  dialog has the name and a permission matrix (areas by group, columns Read / Create / Edit /
  Delete). Create, Edit and Delete include Read: the form adds it and the browser ticks it. Saving
  sets exactly the ticked boxes (the model's standard view/add/change/delete permissions). The
  activity log shows permission changes as "Sites: read, create; Activity log: read". Deleting a
  role removes it from its people.
- **Users** (`/users/`): username, name, email, roles, active, last sign-in, and a Platform admin
  badge. Email is required and unique. A new user has no password: they are sent the password reset
  email, whose link sets their first password (and "Forgot password" sends a new link if it
  expired). People are deactivated, not deleted, and nobody can deactivate their own account.
  Platform admin status is not edited here (only with `createsuperuser`).

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
  (`data-modal`), inner tabs, upper-case inputs, row lists and check boxes that need another one
  (`data-requires`, the role matrix);
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

### The delete plan

Records are soft-deleted, so the database's own `on_delete` never runs. `core/softdelete.py` reads
each link's `on_delete` instead and applies it to live records: `CASCADE` deletes the records that
point at it too, `SET_NULL` keeps them but clears the link, `PROTECT` blocks the delete. A model
adds conditions that are not links by overriding `delete_blockers()`. One plan serves the
confirmation, which lists what will be affected and disables the button when something blocks, and
the delete itself, which writes an activity-log row for every record it touches. A tab never writes
down what a delete does to its neighbours: it is whatever its links say.

### Restoring

A deleted record stays in the database. In `/admin/` (platform admin) every farm record type lists its
records including deleted ones, and the "Restore" action brings them back: refused when a record it
points at is deleted too (bring that back first) or its code was taken meanwhile, and logged. Only
the record itself returns, not what was deleted with it. The admin edits nothing, and users and roles
are not in it: they are changed on their own screens, where every change is logged.

### Adding a tab

A tab is done only when all of this exists; the first three are enforced by `TabRulesTests` in
`core/tests.py`, which checks every declared `Resource`:

1. The model on `AuditedModel` (author, version, soft delete) with its constraints and links; each
   link's `on_delete` says what deleting the other record does to it.
2. The form on `TabbedForm` and the `Resource`, each in its own module (`farm/forms/<tab>.py`,
   `farm/resources/<tab>.py`, the model in `farm/models/<tab>.py`); the URLs and the admin follow from
   the registered resource and the model, nothing to add by hand.
3. **The permission matrix**: the area in `config/access.py`, so a role can be given it.
4. **The menu entry** in `config/navigation.py` with the read permission.
5. Tests that create, read, edit and delete through the pages and check the stored rows, the
   validation and link rules, the delete plan, the activity-log rows and the permissions.
6. The bugs found in the source in `docs/aquaculture-platform-bugs.md`.

### Line endings

Every text file is LF (`.gitattributes`), so tools on any system produce the same file.

## Email

Email uses the console backend for now: the password reset email is printed in the `runserver`
terminal instead of being sent. Put an SMTP backend into `MAILERS` in `config/settings.py` to send
real mail.

## Pages

| Path | Page |
|---|---|
| `/` | Overview (sign-in required) |
| `/sites/` | Facility › Sites |
| `/production-departments/` | Production departments |
| `/systems/` | Facility › Systems |
| `/activity/` | Activity log |
| `/roles/` | Administration › Roles (platform admin) |
| `/users/` | Administration › Users (platform admin) |
| `/accounts/login/` | Sign in |
| `/accounts/logout/` | Sign out (POST) |
| `/accounts/password_reset/` | Forgot password |
| `/accounts/password_change/` | Change password |
| `/admin/` | Django admin: deleted farm records, and restoring them (platform admin) |

## Layout of the code

| Path | Contents |
|---|---|
| `config/` | Settings, URLs, the overview view |
| `core/` | TimescaleDB extension, audit log (model, append-only trigger, `audit.py` helpers, activity page), roles and users (`resources.py`, `forms.py`), tests |
| `core/access.py`, `config/access.py` | Access areas: what a role can be given (the permission matrix) |
| `farm/` | Farm module, one module per tab under `models/`, `forms/`, `resources/`; tests |
| `core/widgets.py` | `DependentSelect`: a choice that belongs to another field's value (a production department to its site) |
| `core/softdelete.py` | The delete plan: what deleting a record does to the records that point at it |
| `core/crud.py`, `templates/crud/`, `templates/modal_base.html`, `frontend/components.ts` | One format for every tab: list, form, delete, dialog, permissions, audit |
| `core/navigation.py`, `config/navigation.py` | The rail menu as data, filtered by permission |
| `farm/resources/`, `templates/farm/` | Farm tabs declared on top of `core.crud`; their URLs come from the registry |
| `core/admin.py` | The admin for farm records: shows deleted ones, restores them (checked like a new one), edits nothing |
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

Tests hash passwords quickly (`config/test_runner.py`). The tests need the database container running (they check the timescaledb extension too). Set
`DB_TEST_NAME` to give a checkout its own test database when two test runs overlap.
