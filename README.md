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
- A database viewer (`/database/`): every table as a spreadsheet-style grid, for the platform admin
  (see Database viewer).
- Two panels, switched from the top left: **Company** (overview, Facility › Sites, Administration)
  and **Production** (overview, production departments, systems, equipment). Each has its own overview. A
  panel is offered only to people who can use something in it (Company to everyone), and the panel
  a person works in is remembered for pages that belong to neither (change password).
- Three languages, English, Norwegian (bokmål) and Turkish, chosen with the EN / TR / NB switch in the
  user menu and on the sign-in pages (see Languages).
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

### Facility › Equipment (`/equipment/`)

Tables `equipment`, `equipment_systems`, `feeder_calibrations` and the catalogue `equipment_types`.
Pumps, filters, feeders, heaters, sensors, generators: a table (equipment, type, production department
and site, systems, parts, status, make and model) with parts listed under the equipment they belong to,
search by name, code or serial number, filters by site, production department, system (or "not linked
to any system", with a notice that counts them), category, type and status, a form in the dialog and
delete. The form has four inner tabs:

- **General**: name, code, category and type (the category narrows the types), status.
- **Location**: the production department, which decides the site ("Bergen · Hall A"); the systems
  it serves, a box per system of that site, one marked primary, each with a role and a criticality from
  1 to 5; the parent equipment (equipment can be a part of other equipment on its site).
- **Details**: manufacturer, model, serial number, purchase, warranty end and installation dates,
  description, notes.
- **Technical specifications**: the fields of the chosen type, built on the server from the type's
  schema (`core/schema.py`): numbers with their unit and bounds, choices, several choices, yes/no,
  dates, text. Changing the category or the type renders the form again with what was entered
  (`TabbedForm.refresh_on`); values typed for one type never fill the fields of another.

A feeder (a type of the Feeding category) has a fifth tab, **Feed calibration**, once it exists: per
feed size, the feed one shot dispenses and the silo capacity, at most 50 rows, saved as a whole list
like a site's contacts and logged on the equipment.

The type catalogue (29 types) is reference data: `farm/equipment_types.py` holds it and a migration
writes it; it has no screen (the source has none either), the admin and the database viewer show it,
and a test fails when the database and the file differ.

Differences from the source:

- Tanks, ponds and cages are not equipment: the source rerouted them from this form into the tanks
  table and lost data on the way (EQ-01). They get their own tab; their types are not in the catalogue.
- The links are checked on every save, not on create only: the systems and the parent on the site of
  the production department, no loops, the parts on the same site; the production department must be on
  a site.
- The specifications are checked against the type's schema on every save, by the same fields the form
  shows (types, bounds, choices, whole numbers), with the error on the field; blank values are not
  stored. Equipment keeps its type when the type is no longer offered.
- Each system link has a primary mark, a role and a criticality you can edit (the source had no input
  for role and criticality); one primary per piece of equipment and criticality 1 to 5 are database
  constraints. A deleted system keeps its link rows: the link stops counting and comes back when the
  system is restored. Saving the equipment drops its links to deleted systems, and the form says so.
- Only equipment statuses (the source also accepted tank statuses such as fallow).
- Code and serial number are unique among live equipment, as database constraints.
- Every optional field can be cleared, the parent too; description, installation date and notes have
  inputs (the source had none).
- Feed calibrations: a real foreign key; only a feeder has them, and a feeder that has them keeps a
  feeder type; new rows start empty instead of 0 / 0 / 0.
- Deleting a production department deletes its equipment, as in the source; deleting equipment deletes
  its parts. Deleting a site leaves its production departments without a site (as before), so their
  equipment stays with them, without systems: the source deleted that equipment with the site.
- The catalogue: English and metric throughout, bounds on every quantity, no fuel type on the heat
  exchanger (EQ-17 to EQ-19).
- Not ported: sub-equipment (a second way of nesting next to the parent, unusable in the source,
  EQ-20), the sensor links (`temperatureSensorId`, `isVisibleInSensor`), the supplier (added with the
  Suppliers tab), price, currency, location, maintenance schedule and operating hours (no screen set
  them), the second status flag `isActive`, the stored part count.

## Roles and users

There are no built-in roles. The platform admin (a Django superuser) can open everything and is the
only one who manages roles and users; everyone else gets exactly what their roles allow.

- **Access areas** (`config/access.py`, read by `core/access.py`): the parts of the console a role
  can be given, one line each, with the actions each offers: Sites, Production departments,
  Systems and Equipment (read, create, edit, delete) and Activity log (read). A new tab appears in the matrix by
  adding its line there. The matrix groups the areas where the menu puts their pages (e.g.
  `Production · Setup · Facility structure`); the grouping is not written a second time. Roles and
  users are not areas, so no role can grant them.
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

## Database viewer

Administration › Database (`/database/`) shows what the application really stores, table by table,
so the data can be checked against what the screens say. It is **read-only** (only GET is accepted;
there is no SQL console) and for the **platform admin only**: the permission `core.browse_database`
is not in the access matrix, so no role can be given it.

- **Tables** (`/database/`): every table by section with a line about it, its number of rows and, for
  tables that soft-delete, the number of deleted rows. Names are the real PostgreSQL names
  (`sites`, `audit_log`, `auth_user`).
- **Data** (`/database/<table>/`): a grid with the database's column names and SQL types in a frozen
  header, a filter row under it, a frozen row-number column and monospace values. NULL is a faint
  badge, booleans are check marks, timestamps and numbers are shown as stored (not localised), UUIDs
  are shortened (the full value on hover), long text and JSON open in place, and a foreign key shows the
  stored id and the record it points at, linked to that table filtered to that row. Deleted rows are
  shown and marked, and can be hidden or shown alone. A header sorts, a filter box matches text
  inside a value (equals, for numbers, ids and booleans), the search box looks in every column, 100
  rows a page. **Export CSV** gives the current filter, streamed and capped at 50,000 rows; text a
  spreadsheet would run as a formula (starting with `=`, `+`, `-`, `@`) gets a leading apostrophe.
- **Structure**: columns (SQL type, nullable, default, key, the model's field), constraints, indexes
  and the relationships in both directions, read from the database and matched with the Django
  model. A link the database does not check (`db_constraint=False`, like `audit_log.user_id`) says so.

Tables are not listed one by one: they come from the models of the apps in `config/database.py`
(`farm`, `core`, `auth`), so a tab that is ported later appears with no new code, in the section its
app belongs to. The tables of other apps (sessions, the Django admin's log) are not shown at all.
Everything the query string names is checked against the table's real columns and the rows come
through the ORM.

**Sensitive data.** `config/database.py` lists the masked columns (`auth_user.password`). A masked
column is never read from the database: its cells show a placeholder, it cannot be sorted, filtered or
searched (that would reveal it a character at a time) and the export leaves it out. A column that
holds a secret belongs in that list; a test fails when a column named like a password, secret, token
or session is not in it.

## Local setup

```
npm install && npm run build                 # compiles frontend/*.ts into static/js (use `npm run watch` while editing)
docker compose up -d                         # TimescaleDB on localhost:5433 (5432 is often a local PostgreSQL)
C:\Python312\python.exe -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python.exe manage.py migrate   # also enables the timescaledb extension (core/migrations)
.venv\Scripts\python.exe manage.py compile_catalogs   # builds the translations (.mo, not committed); redo after pulling .po changes
.venv\Scripts\python.exe manage.py createsuperuser
.venv\Scripts\python.exe manage.py runserver 8047
```

The database connection reads `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` and `DB_PORT`; the
defaults match the local container in `docker-compose.yml`.

## Languages

English is the source language of every text in the code and templates; Norwegian bokmål (`nb`) and
Turkish (`tr`) are translations kept in `locale/<language>/LC_MESSAGES/django.po`. A visitor gets the
language of the cookie set by the switch, otherwise of the browser, otherwise English; a signed-in
person's choice is also saved on their account (`Profile`) and the admin can set it on the user form,
so an invitation email arrives in the new person's language. Numbers and dates follow the language
(`60,3913`, `2. november 2026`). The activity log is stored in English and shown translated.

GNU gettext is not needed: `manage.py update_catalogs` and `manage.py compile_catalogs` (Babel) do
what `makemessages` and `compilemessages` do. How to add a string or a language, the glossary and the
translations that need a native speaker's review are in [`docs/i18n.md`](docs/i18n.md).

## Browser code

There is no hand-written JavaScript. The browser code is TypeScript in `frontend/` (strict mode),
compiled by `npm run build` into `static/js/`, which is not committed:

- `nav-boot.ts` sets the rail state before the first paint and owns the open/collapsed rule;
- `shell.ts` the rail toggle, the phone menu and the user menu;
- `components.ts` the shared parts every tab uses through data attributes: the dialog
  (`data-modal`), inner tabs, upper-case inputs, row lists and check boxes that need another one
  (`data-requires`, the role matrix), GET forms that leave empty fields out of the address
  (`data-omit-empty`, the database viewer's filters), choices and rows that belong to another field's
  value (`data-depends-on`), fields that render the form again with what was entered (`data-refresh`),
  link lists with one primary mark (`data-links`);
- `auth.ts` the show/hide password button.

Asset URLs carry the file's modification time (`{% asset %}`, core/templatetags/assets.py) and the
compiled modules are reached through an import map (`{% module_map %}`), so a browser never shows a
page with new markup and an old stylesheet or script from its cache. `manage.py check` warns when
the compiled code is missing.

The browser code has no text of its own: the templates render the texts it shows into data
attributes (`data-label-show`, `data-forbidden`, ...), already translated.

## One format for every tab

`core/crud.py` turns a `Resource` (model, form, labels, list template) into list, create, edit and
delete pages. Every tab gets the same behaviour from it: a role needs view/add/change/delete on the
model for each page (the platform admin has all of them), every change is written to the activity
log in the same transaction, an outdated `version` is refused, models with soft delete are hidden
rather than erased, and forms and confirmations open in a dialog (`templates/modal_base.html`) or,
opened directly, as a page. The menu is data (`config/navigation.py`: panels, main headings, groups,
entries) and shows each entry only to people allowed to read it. Production's menu has two main
headings, as in the platform: **Setup** (the farm's structure and reference lists) and **Operations**
(the daily production records; it appears with its first tab). The menu is the one place that says
where a page sits: the role matrix and the small heading above a tab's title follow it
(`core.navigation.place`). There are no built-in roles: the platform admin creates roles
and grants permissions.

### The delete plan

Records are soft-deleted, so the database's own `on_delete` never runs. `core/softdelete.py` reads
each link's `on_delete` instead and applies it to live records: `CASCADE` deletes the records that
point at it too, `SET_NULL` keeps them but clears the link, `PROTECT` blocks the delete. A model
adds conditions that are not links by overriding `delete_blockers()`. One plan serves the
confirmation, which lists what will be affected and disables the button when something blocks, and
the delete itself, which writes an activity-log row for every record it touches. A tab never writes
down what a delete does to its neighbours: it is whatever its links say. Records linked through a
many-to-many link (the equipment serving a system) keep their link rows; the confirmation lists them,
and the link counts again once the record is restored.

### Shared form parts

What one tab needed and the next ones will too lives in `core/`:

- `TabbedForm` (`core/crud.py`): inner tabs, fields grouped under a heading (`Fieldset`), a word per
  tab (`tab_help`), fields chosen once (`fixed_after_creation`) and fields that change the form itself
  (`refresh_on`: the form is rendered again from a `draft`, the values entered so far, nothing saved).
- `RowList` (`core/crud.py`): rows a record owns, edited as one list on a tab and saved together,
  replacing the stored rows, logged on the record (a site's contacts, a feeder's calibrations).
- `DependentSelect` (`core/widgets.py`) and `LinkList` (`core/links.py`): a choice, or a list of
  check boxes with the details of each link, that belongs to another field's value.
- `Schema` and `SchemaValuesField` (`core/schema.py`): fields described by data (a type's technical
  specifications), the form fields and the check of the stored values from one definition.
- `TreeMixin` (`core/models.py`): records nested under records of the same kind, without loops.

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
4. **The menu entry** in `config/navigation.py`, in the right panel, under the right main heading
   (Setup for structure and reference lists, Operations for daily records) and group, with the read
   permission. The role matrix and the page heading take their grouping from it.
5. Tests that create, read, edit and delete through the pages and check the stored rows, the
   validation and link rules, the delete plan, the activity-log rows and the permissions.
6. The bugs found in the source in `docs/aquaculture-platform-bugs.md`.
7. **Translatable text**: names, labels, help texts, choices and messages written with
   `gettext_lazy` / `{% trans %}`, `manage.py update_catalogs`, and the Turkish and Norwegian
   translations (`docs/i18n.md`); `TabTranslationTests` and the catalog tests in `core/test_catalogs.py`
   fail otherwise.

### Line endings

Every text file is LF (`.gitattributes`), so tools on any system produce the same file.

## Email

Email uses the console backend for now: the password reset email is printed in the `runserver`
terminal instead of being sent. It is written in the recipient's saved language, otherwise in the
language of the request. Put an SMTP backend into `MAILERS` in `config/settings.py` to send
real mail.

## Pages

| Path | Page |
|---|---|
| `/` | Company overview (sign-in required) |
| `/production/` | Production overview |
| `/sites/` | Facility › Sites |
| `/production-departments/` | Production departments |
| `/systems/` | Facility › Systems |
| `/equipment/` | Facility › Equipment; `<id>/calibrations/` saves a feeder's calibrations |
| `/activity/` | Activity log |
| `/roles/` | Administration › Roles (platform admin) |
| `/users/` | Administration › Users (platform admin) |
| `/database/` | Administration › Database: every table (platform admin) |
| `/database/<table>/` | One table: Data and Structure tabs; `export.csv` below it downloads the filtered rows |
| `/language/` | Language switch (POST; sets the cookie and the account's language) |
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
| `core/language.py`, `core/catalogs.py`, `locale/`, `config/formats/`, `docs/i18n.md` | Languages: which one a request gets, the catalogs without GNU gettext, the English date look, the guide and glossary |
| `core/access.py`, `config/access.py` | Access areas: what a role can be given (the permission matrix) |
| `farm/` | Farm module, one module per tab under `models/`, `forms/`, `resources/`; tests |
| `core/widgets.py`, `core/links.py` | `DependentSelect`: a choice that belongs to another field's value (a production department to its site); `LinkList`: check boxes for a record's links, with their details |
| `core/schema.py` | Fields described by a schema (a type's specifications): the form fields and the check of stored values |
| `farm/equipment_types.py` | The equipment type catalogue, written into the database by migrations |
| `core/database.py`, `config/database.py` | The database viewer's tables (from the models), their structure (from the database), sections, descriptions and masked columns |
| `core/dbgrid.py`, `core/dbview.py`, `templates/core/database/` | The viewer's grid (search, filters, sort, cells, export) and its three pages |
| `core/softdelete.py` | The delete plan: what deleting a record does to the records that point at it |
| `core/crud.py`, `templates/crud/`, `templates/modal_base.html`, `frontend/components.ts` | One format for every tab: list, form, delete, dialog, permissions, audit |
| `core/navigation.py`, `config/navigation.py`, `core/middleware.py` | The menu as data: panels (workspaces) with main headings, groups and entries, filtered by permission; the panel in use is remembered; where a page sits (`place`) for the role matrix and page headings |
| `farm/resources/`, `templates/farm/` | Farm tabs declared on top of `core.crud`; their URLs come from the registry |
| `core/admin.py` | The admin for farm records: shows deleted ones, restores them (checked like a new one), edits nothing; reference data (equipment types) is shown read-only |
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

Tests build the catalogs first and hash passwords quickly (`config/test_runner.py`); the TypeScript is
type-checked by a test when Node and `npm install` are there. The tests need the database container running (they check the timescaledb extension too). Set
`DB_TEST_NAME` to give a checkout its own test database when two test runs overlap.
