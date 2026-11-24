# Fish farm prototype

A small Django prototype of the farm module of Suderra's aquaculture platform: Django 6.1 on
PostgreSQL 17 with TimescaleDB 2.17 (Docker). The farm module's tabs are ported one at a time.

What works today:

- Sign in, sign out, forgot password (reset link by email), change password. All of it is Django's
  built-in auth: PBKDF2 password hashing, signed one-time reset tokens, the standard password
  validators, CSRF protection and sign-out by POST only. A new person is invited by email with a one-time
  link that sets their password (see Email).
- An activity log (`/activity/`): who created, changed or deleted which record, when, with the old
  and new value of every changed field. Rows are written in the same transaction as the change and a
  database trigger refuses to update or delete them. Each record's form has a History tab. An entry where
  someone went on past a handling warning is marked critical.
- Every page needs a signed-in user (`LoginRequiredMiddleware`) unless its view opts out.
- Roles (`/roles/`) and users (`/users/`), managed by the platform admin only (see Roles and users).
- A database viewer (`/database/`): every table as a spreadsheet-style grid, for the platform admin
  (see Database viewer).
- Three panels, switched from the top left: **Company** (overview, Facility › Sites and Storage locations,
  Knowledge, Alarms, Administration, and HR) and **Production** (overview, production departments, systems, equipment, tanks,
  ponds & cages, species, feeds, water limits, medicines, slaughter facilities, handling rules, suppliers, and
  under Operations the production units with their fish, the water chemistry, the store (Storage), the tasks and
  the recurring tasks, Feeding: the meal board, the records, the feeding protocols and their assignments,
  Harvest: harvested, harvest plan, production plans, and Health: treatments, health events and sea-lice
  counts; and under Communication the messages). The third, **Sensors**, holds the MQTT connections, devices, channels and their bindings, the charts and live values, dead letters and alarms (see Sensors). Each has its own overview. A
  panel is offered only to people who can use something in it (Company to everyone), and the panel
  a person works in is remembered for pages that belong to neither (change password).
- Messages (`/messages/`): direct conversations and channels between people, with the unread count in the
  menu, in the Production panel; built so that AI assistants join the same conversations later (see
  Messages).
- Knowledge (`/knowledge/`), in the Company panel: a **Library** of articles and reports with their reference,
  their PDF (sent only to people who may read it) and its text read page by page and searched, and **Knowledge
  entries**, each a statement with exactly one source and a review, which AI agents will later watch the farm
  with and cite (see Knowledge).
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

Tables `sites` and `site_contacts`. Cards with search by name, code or region; a form with four
inner tabs (Basic info, Location, Contact, Reports); contacts saved as a whole list on the Contact tab;
delete is a soft delete. Differences from the source:

- Single company: no `tenantId`, no row-level security.
- Satellite monitoring is not ported (monitoring radius, monitoring area, its revision trigger).
- The jsonb `location` and `address` are flat columns (latitude, longitude, altitude, street, city,
  state, postal code); the source kept city and country twice.
- Code, name and lokalitetsnummer are unique among live sites and at most one contact is primary,
  as database constraints; the source enforced most of this only in service code.
- Column lengths win where the source's form allowed longer values (name 150, code 20, email 150).
- Editing is guarded by the `version` column: a save based on an old version is refused.
- A site with live units is not deleted (the confirmation says how many hold it): their fish and feed are counted
  for a site only through it (F-212). Without units, its production departments, systems and equipment are deleted
  with it and come back with it when it is restored (see the delete plan); the other dependants join the delete plan
  as their tabs arrive. Its health events stay with it, out of sight, and come back with it.
- **Every site has its time zone** (Basic info), the clock its feeding days, shifts, punches and plans are read on
  (`farm.models.site.zone_of`). An empty zone once ran a Norwegian site's day on the server's UTC, an hour or two off,
  unseen. Now the form asks for one, offering the company's first; a site made without one (a seed, a test) is given the
  company's, stored; the database refuses an empty one (`chk_sites_timezone_given`). **The company's zone is a setting of
  its own**, `COMPANY_TIME_ZONE` (environment, `Europe/Oslo` by default; later the platform owner's settings), never the
  server's `TIME_ZONE` (UTC): a place without a site (a person not posted, a record or a form over sites of several
  zones, the activity log, a record's history, the messages) reads it (`zone_of(None)`, `core.dates.company_zone`), and a
  test reads the code so nothing falls back to the server's clock or day (`core/tests_company_clock.py`: also `date.today()`,
  `now().date()`, `Trunc*` without `tzinfo`, a `__date` lookup on a moment; the attendance list's day of a stretch is the
  company's, `hr.read.local_day` the site's for a person's placement). The server refuses to
  start on a zone that is not one a site may have (system check `farm.E001`). Migration `farm/0028_site_timezone_required`
  gives every site without a zone the company's, and refuses such a zone rather than write it.
- The Location tab has the sea-lice limit area (Nord-Trøndelag and southwards, or Nordland, Troms and Finnmark),
  which decides the weeks of the lower spring limit (see Operations › Health).
- The Reports tab has what the regulatory reports need of the site (see Production › Reports): its **organisation
  number** (the permit holder's, which owns the fish: nine digits, typed with or without spaces and stored as
  digits, a database check; it replaces the source's free-text override), its **production form** (juveniles,
  food fish or broodstock, which decides the reports it owes) and **reports from**, the day its reports are listed
  as due from (the periods before were filed elsewhere).

### Production departments (`/production-departments/`)

The farm's production departments: a hatchery hall, a nursery, a grow-out unit on a site. They are not the
company's organisational departments (management, HR and the like), which come with the HR module.
Table `production_departments` (renamed from `departments` by migration 0004, data kept): a table (production
department, type, site, capacity) with search by name or code, a
site filter that includes "without a site" (rows from before F-212), a flat form in the dialog and delete. Differences from
the source:

- A production department belongs to a site chosen once, at creation, and a live one always has a site: a database
  check (`chk_production_departments_live_on_a_site`) refuses one without. The source left a deleted site's
  departments without a site, where their units' fish were in no site's reports and their feed drew on no store
  (F-212); now a site is deleted only once its units are gone, and its departments go with it. A department left
  without a site before is kept as it was (the check was added `NOT VALID`, migration 0029): its form asks for a site
  the next time it is saved (whatever its units' records: on no site they are in no report), its units take no fish
  until then, and `manage.py check_stock` names it; once it names none, the check can be validated. "On a site" means a
  live department on a live site (`farm.models.tank.ON_A_SITE` / `on_a_site`, one predicate for the stocking list, a
  unit's checks and the stock's write path): three constraint triggers (farm 0030) refuse a live unit in a deleted
  department or on a deleted site, a department deleted with live units and a site deleted with live departments, a
  unit's save locks its site and department (the order a site's delete takes them), and `check_stock` names live units
  in deleted departments and live departments on deleted sites (cross review F1).
- The source's `administration` type is not carried over: an administrative department is an organisational one.
- Code is unique among live production departments and a name is unique within a site, as database
  constraints; capacity cannot be negative.
- Not carried over: `settings` and `area` (accepted but never stored), the second status flag
  `isActive`, the load figure that was never filled in. Notes can be shown and cleared.
- The manager is a user of this system, and can be removed. It is chosen on the form among the people who can sign in
  (a person already chosen stays offered after their account is deactivated) and is what makes a team in HR: a manager
  with a role that gives the HR pages sees and plans the department's people there (see Human resources).

The bugs found in the source while porting are listed in
[docs/aquaculture-platform-bugs.md](docs/aquaculture-platform-bugs.md), with how each is avoided here.

### Facility › Systems (`/systems/`)

Table `systems`: a table (system, type, status, site, production department, volume, max biomass), nested
systems shown under their parent, search by name or code, filters by site and by production department
(including "without a production department"), a form in the dialog and delete. A system belongs to a site
(chosen once) and optionally to a production department of that site and to a parent system of that site. A new
system starts with its loop point (a sampling point of the kind middle, named "Loop"); each row links to its points.
Differences from the source:

- The links are checked on every save, not on create only: the production department must be on the system's
  site, a parent on the same site, and a system cannot be nested under itself or anything below it.
  The parent list offers only valid choices (the source excluded the system itself but not its
  descendants and was narrowed by the list's own filters).
- A link or the description can be cleared when editing (the source sent `undefined`, which the API
  reads as "no change").
- Volume and biomass cannot be negative (database check and form).
- The hand-typed tank count is not carried over: it would drift from the real tanks. The list counts
  the units in each system instead (linked to the units list). The second status flag `isActive` is not
  carried over either.
- A system cannot be moved to another production department while units of another are in it.
- Code is unique within a site among live systems.
- Deleting a site deletes its systems, a system the systems nested under it, and a production department
  leaves its systems without one, all through the delete plan.

### Facility › Equipment (`/equipment/`)

Tables `equipment`, `equipment_systems`, `feeder_calibrations` and the catalogue `equipment_types`.
Pumps, filters, feeders, heaters, sensors, generators (equipment has no sampling points until its inlet and
outlets are added under Setup › Facility structure › Sampling points; each row links there): a table (equipment, type, production department
and site, systems, parts, status, make and model) with parts listed under the equipment they belong to,
search by name, code or serial number, filters by site, production department, system (or "not linked
to any system", with a notice that counts them), category, type and status, a form in the dialog and
delete. The form has four inner tabs:

- **General**: name, code, category and type (the category narrows the types), status.
- **Location**: the production department, which decides the site ("Bergen · Hall A"); the systems
  it serves, a box per system of that site, one marked primary, each with a role and a criticality from
  1 to 5; the parent equipment (equipment can be a part of other equipment on its site).
- **Details**: manufacturer, model, serial number, the supplier it was bought from (a supplier of
  equipment and spare parts, see Purchasing › Suppliers), purchase, warranty end and installation
  dates, description, notes.
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
- Every optional field can be cleared, the parent and the supplier too; description, installation date
  and notes have inputs (the source had none).
- The supplier is a link to a live supplier of equipment and spare parts, checked by the model; the
  source kept a loose id with no foreign key and offered every supplier (SUP-06). Deleting the supplier
  leaves the equipment without one.
- Feed calibrations: a real foreign key; only a feeder has them, and a feeder that has them keeps a
  feeder type; new rows start empty instead of 0 / 0 / 0.
- Deleting a production department deletes its equipment, as in the source; deleting equipment deletes
  its parts. Deleting a site deletes its production departments, so their equipment goes with them, as the source
  deleted it with the site.
- The catalogue: English and metric throughout, bounds on every quantity, no fuel type on the heat
  exchanger (EQ-17 to EQ-19).
- Not ported: sub-equipment (a second way of nesting next to the parent, unusable in the source,
  EQ-20), the sensor links (`temperatureSensorId`, `isVisibleInSensor`), price, currency, location,
  maintenance schedule and operating hours (no screen set them), the second status flag `isActive`, the
  stored part count.

### Facility › Tanks, ponds & cages (`/tanks/`)

Table `tanks`: the units fish are held in, a tank, a pond or a cage, each in a production department and
optionally in one system. The model keeps the source's name (`Tank`, table `tanks`) because its later
tables point at `tankId`; a person reads "unit". Master data only: the fish in a unit (count, biomass,
batches) are on Operations › Production units. A new unit starts with its **sampling points** (where its water
is sampled, Setup › Facility structure › Sampling points: a tank an inlet, a middle, a side outlet and a bottom
drain, a pond an inlet, a middle and an outlet, a cage its middle), made in the same transaction and logged; each
row links to its points. A table (unit, kind with its shape or type, production department
and site, system, volume, water volume, max density, max biomass, water type, status), search by name,
code or regulatory unit ID, filters by site, production department, system (or "not in a system"), kind,
status and water type, a form in the dialog and delete. The form has five inner tabs:

- **General**: name, code, kind (tank, pond or cage, chosen once), status with the time it was set and
  its reason, water type, regulatory unit ID (the kar or merd number in reports to the authorities).
- **Location**: the production department ("Bergen · Hall A"), and a system of its site; a system that
  belongs to a production department takes only that department's units.
- **Dimensions**: the fields of the chosen kind, built per form (changing the kind, the shape, the pond
  type or the cage type renders the form again with what was entered, `TabbedForm.refresh_on`). A tank:
  shape and material, the shape's measures (a circle's diameter; a rectangle's or raceway's length and
  width; a square's side; an oval's long and short axis; a D-ended tank's overall length and width), its
  depth and water depth, or, for a shape of its own, its volume. A pond: earthen or lined, water source,
  surface area, average and deepest depth, water depth, liner and, when lined, its thickness. A cage:
  floating or submersible, circular or square, diameter or side, net depth, submersion depth (submersible
  only), net material, mesh size (half mesh) and frame. Each field has the bounds of its kind in its help.
- **Capacity**: the max density; the volume, water volume, freeboard and max biomass are shown, never
  typed.
- **Details**: installation date, description, notes.

The volume, the water volume and the max biomass are **generated columns**: the database works them out
from the measures on every write (`Tank.water_surface()`: π·d²/4, L·W, an ellipse π·L·W/4, a D-ended
tank (L − W)·W + π·W²/4, a pond's area), so a stored volume always matches its unit, whatever wrote the
row. The max biomass is the water volume (else the volume) times the max density. The status follows the
source's status machine, in one place (`TRANSITIONS`), with one move added: maintenance → active, the way back for
a unit serviced with its fish in it (F-166); a new unit holds no fish, so it starts as
preparing, fallow, maintenance or inactive; the form offers the current status and where it can go.
Every rule that needs the fish in a unit asks `Tank.has_stock()`, which reads the stock ledger: active
and harvesting need fish, preparing, fallow, cleaning and inactive need none (maintenance and
quarantine can be either), and a unit with fish cannot be deleted or resized. Stocking and emptying a
unit move its status by themselves (see Production units).

Differences from the source:

- Its own tab: the source created units only through the equipment form, which lost the typed code and
  every pond and cage field on the way (TNK-01 to TNK-03).
- Every kind has typed columns, and the columns of another kind stay empty: kind, shape, measures and
  bounds are database checks, one per rule.
- Derived values are derived: the source let a typed volume and max biomass contradict the dimensions
  and the density; the D-ended and oval formulas are corrected (TNK-05 to TNK-10).
- Bounds per kind (a net is 15–50 m deep, a tank's depth stops at 20 m), and max densities up to the
  intensive species (TNK-09, TNK-11); see the bounds table in the bug document.
- The system is checked on every save, against the department's site and, when the system has one, its
  production department; a system cannot move to another production department while units of another
  are in it; deleting a system takes its units out of it, logged.
- Water type is required and has no default (the source defaulted to saltwater in one place and
  freshwater in another).
- The water origin is optional (cross review F3, farm 0041, `chk_tanks_water_origin`): sea water or diluted sea water,
  or fresh water with salt added (NaCl, for smolt or against disease). Fresh water with sea water or a sea-salt mix
  added is diluted sea water, and the help texts of the unit and the calculator say so (its magnesium, calcium and
  sulfate are sea water's; the salt-added water audit of 2026-11-20, `F:\dev\balik-notes\chem-audit-fable\SALT-ADDED.md`,
  question 1; farm 0049). The water chemistry reads it (Water-chemistry core): salt-added water is worked out without
  sea water's ions; not said, a salinity of 1 to 5 ‰ is taken as diluted
  sea water and the value says so. A loop or a sampling point takes its units' origin when they all say the same.
- The code is unique among live units. The regulatory unit ID is the locality's own number (merd 1 on two sites
  is two units): unique among the live units of a site, held by the database per production department and by the
  form across the site. A unit with stock records stays on its site, and so does a production department whose
  units have some, since moved, their past figures would be reported for another locality. A deleted unit can
  be restored from the admin.
- A site with live units is not deleted (F-212); the source deactivated their tanks. A unit is in a production
  department on a site: one left without a site before (see Production departments) is not offered for a new unit,
  and the unit is moved to a department on a site the next time it is saved.
- Water sources "spring" and "sea or estuary" and the net material "polyester (PET)" are added; an
  earthen pond is bare soil or compacted clay, a membrane or concrete makes it a lined pond.
- Not ported: the sensor link (`temperatureSensorId`), the equipment type (kind and shape replace the
  13 tank, pond and cage types), `isActive` (status and soft delete), the stock mirrors
  (`currentBiomass`, `currentCount`), the maintenance dates (nothing wrote them; the Maintenance tab),
  the `location`, `waterFlow` and `aeration` JSON (no screen wrote them), the legacy `ponds` and `farms`
  tables, the code generator, quotas and events.
- A cage's volume is a cylinder or box down to the net depth, as in the source; a cone-bottomed net
  holds less (a question for the owner, in the bug document).
### Reference data › Species (`/species/`)

Table `species`: the species the farm grows or stocks, Atlantic salmon, rainbow trout, lumpfish,
picked later by batches, feeds and the water limits. A table (species with its local name,
scientific name with family and genus, code, official code with a "Missing" mark when there is none,
category, water, cleaner fish, status), search by common, local or scientific name, code or official
code, filters by category, water environment, cleaner fish (any, lumpfish, wrasse, none) and status,
50 species a page, a form in the dialog and delete. The form has four inner tabs:

- **Basic info**: common name (English), local name (the farm's own language, e.g. Laks),
  scientific name, code, description.
- **Classification**: category, family and the water environment: fresh, brackish and sea water,
  at least one. The genus is shown on an existing species; it is the first word of the scientific name.
- **Regulatory**: the official code (artskode), the cleaner-fish type (lumpfish or wrasse) and, under
  **Medicine withdrawal**, the **assumed water temperature for withdrawal** (°C, 0 to 40, a database check, empty
  allowed): the degree-days one day counts for when no water temperature was measured, so a past day without a
  measurement and a withdrawal projected when none was measured at all do not silently count as nothing (see
  Operations › Health). It is the farm's own assumption, never filled in from the catalogue; a low value is the
  conservative choice, and empty keeps such a day at 0 °C.
- **Stocking**: under **Batches of different sizes**, the **max weight ratio of batches in one unit** (1 to 1000, a
  database check, empty allowed): how many times heavier, on average, one batch of the species may be than another
  sharing a unit with it (the owner: fish of very different weights of the same species must not be in the same tank;
  the bigger ones outcompete the smaller at feeding). A stocking, transfer or grading beyond it asks for an
  acknowledgement first, and a unit holding such a mix says so (see Production units). Empty means no check, and the
  list says "No check"; the list's **Size limit** column shows it (2×). Migration 0034 gave every species there the
  owner's default 2. It is not a withdrawal input: it is edited freely.
  **A new species' box is empty, and empty takes the default of the species' kind** (`farm.forms.species.
  offered_weight_ratio`): 2 for a production species, **no check for a cleaner fish** (the owner, 2026-11-10: lumpfish
  and wrasses are topped up with fish of other sizes), also when the catalogue fills the cleaner-fish type in. The
  person is told after saving which was applied. Whatever is typed is kept, a 2 for a cleaner fish too: the box is
  never filled in beforehand, because a value standing in it could not be told from a typed one. On an edit, empty
  means no check, as before. A top-up of a cleaner species without a limit asks nothing and its cage shows no
  "Mixed sizes" chip; salmon is unchanged. Migration `farm/0038_cleaner_fish_no_size_check` emptied the limit of the
  cleaner species that still held 0034's untouched default (2, and no person's word about the limit in the activity
  log), deleted ones too, one activity-log row each (by `system`). A limit a person changed stays; a cleaner species
  whose 2 came with its own creation through the form is left as it is and named in the migration's output (the 2 may
  have been typed); going back gives 2 back only where it took it and nobody chose since.
- **Status and notes**: active, experimental, inactive or discontinued; notes. Active and
  experimental species are the ones a new batch can take (Production units).

The species catalogue (`farm/species_catalog.py`) knows the 13 species Norwegian farms grow or stock
(salmon, rainbow and brown trout, Arctic char, cod, halibut, turbot, seabass, seabream, lumpfish and
three wrasses). When a species is created under one of these scientific names, or renamed to one,
the fields left blank are filled in from it (local name in Norwegian, family, water environments
when none is ticked, cleaner-fish type, official code) and the message after saving lists them;
a typed value is never replaced, and an edit that keeps the name fills nothing, so every field can
be cleared. Official codes are the FAO ASFIS 3-alpha codes Mattilsynet's reports ask for, for the nine
grow-out species (e.g. SAL) and the five cleaner fish (LUM lumpfish, USB ballan wrasse, YFM corkwing, TBR
goldsinny, ENX rock cook; the source's map had them wrong, SPC-32, REP-51). A catalogue species cannot be
given an official code other than its own. No species rows are seeded
and there is no "add from catalogue" action.

Deleting a species: a batch links to it with `on_delete=PROTECT`, so a species with batches is set
to discontinued instead of deleted. The feeds that suit it keep their suitability rows for it (a
many-to-many link of the feed, `CASCADE`): the confirmation lists those feeds, the rows stop showing and
come back with the species when it is restored (see Reference data › Feeds). Later report code must
send the official code and never fall back to the internal code.

Differences from the source:

- The scientific name is normalised (`salmo  SALAR` is stored as `Salmo salar`), checked as a
  binomial (a subspecies may follow; `sp.` is not accepted) and unique among live species whatever
  its case; the code is capital letters, digits, `-` and `_`, unique among live species; the official
  code is three capital letters or empty. All of it is checked by the database too.
- The official code can be changed and cleared on an existing species (the source dropped it on
  update, SPC-01), and is filled in from the catalogue (SPC-03).
- The water environment is three flags instead of one water type: salmon and trout live in fresh
  and in sea water (SPC-22).
- The cleaner-fish type is on the form; "is a cleaner fish" is derived from it (SPC-04). The
  source's `cleaner-fish` tag is not carried over.
- One status; the second flag `isActive` is not carried over (SPC-15). The genus is not stored.
- Every field can be cleared; the list is paged on the server instead of 100 cards filtered in the
  browser.
- Not ported: tags, the species-level supplier (it belongs to the batch), market and breeding
  information, documents, the image, the light regime (a production protocol, not a species
  constant), the "compatible feeds" section (never stored by the source; it belongs to the Feeds
  tab) and the JSON blobs. Two parts come back with later tabs as typed tables, never as JSON, and
  with no silent defaults: the water limits per species and parameter, each in its parameter's unit
  (Reference data › Water limits, see Operations › Water chemistry; SPC-05, SPC-19, SPC-23), and growth
  bands, target FCR, survival and harvest weight per stage (the growth model, with the batches tab;
  SPC-20, SPC-21). Deleting a species deletes its water limits with it (listed in the confirmation).

### Reference data › Feeds (`/feeds/`)

Tables `feeds` and `feed_suitability`: the feeds the farm uses, who makes them, their pellet and
analysis, and the species, life stages and fish weights each one suits. A table (feed with its code,
manufacturer, feed type, pellet size with its buoyancy, protein / fat, gross energy with the digestible
energy, what it suits, price per kg, status), search by name, code or manufacturer, filters by feed
type, manufacturer, species it suits and status, 50 feeds a page, a form in the dialog and delete. The
form has four inner tabs:

- **Basic info**: name (as on the bag), code, manufacturer (a supplier of feed), feed type (larval,
  starter, fry, grower, finisher, broodstock, medicated, other), dry or wet (the cleaner-fish report gives the
  month's kilos of each), pellet size in mm, buoyancy (floating, slow sinking, sinking, or not stated),
  status (active, inactive, discontinued).
- **Analysis**: the composition as fed, in % of the feed as delivered (crude protein, crude fat,
  carbohydrate as NFE, crude fibre, ash, moisture, phosphorus), and the gross and digestible energy in
  MJ/kg.
- **Price and notes**: the price per kg with its currency (three letters, e.g. NOK), notes.
- **Suitable for**, once the feed exists: a row per species and life stage (every stage, larvae,
  post-larvae, fry, fingerlings, juveniles, smolt, adults, broodstock) with the fish weights in grams
  and a note; at most 50, saved as a whole list like a feeder's calibrations and logged on the feed.

The rules, each a database check as well, with the error on the field to change:

- Protein, fat, carbohydrate, fibre, ash and moisture are the parts of the feed as fed and add up to at
  most 100; phosphorus is part of the ash and at most the ash; each percentage is 0–100. NFE is what is
  left when the others are taken away, so a declaration's figures plus NFE make 100.
- The digestible energy is at most the gross energy, both at most 40 MJ/kg (pure fat holds about 39.5).
- The pellet size is 0.01–100 mm with two decimals: the column and bounds of a feeder's calibrations
  (`FeederCalibration.feed_size_mm`), so a feed's size finds a feeder's calibration by equality.
- A price (0.01 or more) needs its currency, and a currency a price; the currency is stored in capitals.
- A weight band runs from the lower weight up to, not including, the upper one
  (`FeedSuitability.suits(weight)`), so the bands of a feed range (0–5, 5–20 g) meet without
  overlapping; either end can be left open; the lower is below the upper. One row per species and stage.
- Code (2 to 50 capital letters, digits, `-` and `_`) and name (whatever its case) are unique among
  live feeds; a deleted feed frees them and a restore from the admin re-checks them.

The manufacturer is a live supplier of feed (a `SupplierLink`, see Purchasing › Suppliers); the list
shows its status when it is not active. A supplier keeps the feed category while live feeds name it, and
**a supplier that makes live feeds cannot be deleted** (`PROTECT`): the maker is part of what a feed is,
for its declaration and its traceability (a medicated feed above all), so a supplier the farm stops
buying from is set inactive or blocked, or its feeds get another manufacturer first. Restoring a feed
needs its manufacturer live and still a supplier of feed.

Deleting a feed keeps its suitability rows with it. Deleting a species keeps its rows in the table but
out of sight (`FeedSuitability.objects` holds the rows of live species; `Feed.species` is the
many-to-many link through them): the species' confirmation lists the feeds linked to it, saving a
feed's list leaves those rows alone, and restoring the species brings them back.

Not on this tab, each with a tab of its own later: the feed stock (lots, quantities, expiry, storage
conditions, where it is kept), purchase orders and the feeding records; the feeding tables (feeding rate per fish
weight and temperature, FCR) are Operations › Feeding › Protocols, built from these feeds.

What the feeding tabs can rely on: a feed is `farm.Feed` (UUID, live ones through `Feed.objects`), with
`status` active, inactive or discontinued (offer active ones for new feeding plans; a record keeps its
feed whatever the status becomes); `pellet_size_mm` matches `FeederCalibration.feed_size_mm` by
equality; the analysis and energy are typed decimals or `NULL` (not stated, never 0 by default);
`price_per_kg` and `currency` come together or not at all; the suitability is
`feed.suitability.all()` (live species only) with `growth_stage`, whose values are a batch's
`input_stage` values (`FeedSuitability.GrowthStage` is built from `InputStage`, without eggs, plus
"every stage"), and `suits(weight_g)` for the band. A feed record of a later tab should link to the feed
with `PROTECT`, as batches link to a species.

Differences from the source:

- Which species, life stages and weights a feed suits is written and read on this tab; the source
  accepted it on create through the API only and never returned it (FEED-01). The weight band is per
  species and stage; the feed-level minimum and maximum (whose maximum the source lost on create) are
  not carried over (FEED-02, FEED-14).
- The analysis is typed columns with the rules above, instead of a JSON object rebuilt on every edit,
  with the energy under two names and units (FEED-04 to FEED-06).
- The manufacturer is a link to a supplier of feed; the source had free texts for the manufacturer and
  the brand next to a link to any supplier (FEED-08).
- The status is the product's; the source's low stock, out of stock and expired are stock states, set
  again by every stock movement (FEED-07). One status, no `isActive` (FEED-19).
- One list of feed types, the source's eight, in the model; its `feed_types` table is not ported
  (FEED-09). Buoyancy has no default (FEED-16); a price has its own currency (FEED-17).
- Code and name are unique among live feeds and every optional field can be cleared (FEED-03, FEED-10).
- Not ported: brand, description, the pellet size label, the product stage text, the ingredients text,
  unit size and unit price, the storage temperatures, humidity and requirements, shelf life and expiry
  date, stock quantity, minimum stock and unit, the procurement lead time, documents, the environmental
  impact, the feeding curve, the 2D feeding matrix and the feeding table, the sites a feed is approved
  for (FEED-13), and on the suitability rows the recommendation level, priority, feeding rate and
  frequency and the JSON of rates per temperature and expected performance.
- The life stages are the ones a batch is stocked at (`InputStage`, one list for the farm, without
  eggs), smolt among them; the source's grower and pre-adult stages are not: the weight band says it
  more precisely.

### Purchasing › Suppliers (`/suppliers/`)

Tables `suppliers`, `supplier_contacts` and `supplier_sites`: the companies the farm buys from, goods,
live fish and services. A table (supplier with its code and organisation number, what it supplies,
primary contact with the supplier's email and phone, city and country, sites served, rating, status),
search by name, code, organisation number, email, city or country, filters by what it supplies, site
and status, 50 suppliers a page, a form in the dialog and delete. The form has five inner tabs:

- **Basic info**: name, code, organisation number, what it supplies (a box per category, at least
  one), status (active, inactive, suspended, blocked) and the farm's own rating from 1 to 5.
- **Contact**: the supplier's email, phone and website, and its contact persons (name, role, email,
  phone, at most one primary), saved as a whole list like a site's contacts.
- **Address**: street, postal code, city, country.
- **Sites**: the sites it delivers to or works at.
- **Terms and notes**: payment terms, notes.

What a supplier supplies is a list of categories, several at once (`Supplier.supplies`, a PostgreSQL
array of choices, `core.fields.ChoiceArrayField`): live fish and eggs, feed, equipment and spare parts,
consumables, chemicals, medicines and vaccines, veterinary and fish health, laboratory analyses, diving
and ROV, wellboat and transport, maintenance and repair, consultancy, other. The database checks that
there is at least one and that each is a category; they are stored once each, in that order. The
activity log stores each as its msgid and shows them in the reader's language.

Equipment links to its supplier (`Equipment.supplier`, on the equipment's Details tab and in its list).
Only a live supplier of equipment and spare parts can be chosen: the category is what says a supplier
sells equipment, so a feed mill or a vet is not offered, and the rule is part of the model's
validation (`limit_choices_to`), not only of the form. The status is not a filter: the link says
where the equipment was bought, which stays true when a supplier is later suspended or blocked, and
old equipment is often registered after the fact; the list shows the status of a supplier that is not
active. A supplier keeps the equipment category while equipment is bought from it. Deleting a supplier
leaves its equipment without a supplier, each change logged on the equipment; deleting a site keeps
the suppliers' links to it, which count again when the site is restored. Bought fish link to their
supplier too (`Batch.supplier`, a live supplier of live fish and eggs): that link is `PROTECT`, since
where fish came from must stay traceable, so a supplier fish were bought from keeps that category and
is set inactive rather than deleted.

A feed links to its manufacturer the same way (`Feed.manufacturer`, a live supplier of feed, see
Reference data › Feeds), and like bought fish, a supplier that makes live feeds cannot be deleted. Every
link to a supplier is a `SupplierLink` (`farm/models/supplier.py`): equipment, a feed's manufacturer, bought
fish, a slaughter facility's operator, a harvest's transport, a delivery or return of the store. One
declaration per link holds the category it takes (`limit_choices_to`, the model's validation and the form's
list; or, for the store, `category_field`: the category of each item it brought), the words the supplier's
form says when the category must stay ticked (`needed`, checked by `Supplier.clean`), and, for a `PROTECT`
link from a plain row the delete plan does not follow, why the supplier cannot be deleted (`blocker`, read by
`Supplier.delete_blockers`). The supplier reads its links (`Supplier.links`), so a new link adds no code to the
supplier.

Differences from the source:

- What it supplies is one list of categories, checked by the database, instead of a main type next to
  a second list nobody could read or edit (SUP-08, SUP-09). The categories cover what a fish farm buys:
  eggs and smolt, medicines apart from chemicals, and each kind of service.
- Every field of the form is stored on create (the source dropped notes, products and the city,
  SUP-01) and can be cleared on edit (SUP-07); the status chosen on create is kept (SUP-04).
- Contact persons are rows; the source accepted a list and stored one name (SUP-02).
- One status; the second flag `isActive` is not carried over (SUP-05).
- Code (required, 2 to 20 capital letters, digits, `-` and `_`), name (whatever its case) and
  organisation number are unique among live suppliers, as database constraints; a deleted supplier
  frees them and a restore from the admin re-checks them (SUP-03, SUP-13).
- The organisation number is on the form, without spaces, in capital letters (SUP-10); the website is a
  URL, `https://` added when left out (SUP-21); the rating is 1 to 5 or none (SUP-17).
- The address is flat columns, each once (SUP-12); payment terms are text (SUP-11).
- Not ported: the free list of product names (the products are records of their own tabs, the feeds,
  chemicals and consumables, linked to the supplier), the preferred site (a preferred supplier is a
  choice per site and category, for the purchasing tab, SUP-16), the type table `supplier_types`,
  description, fax and certifications (accepted and never stored, SUP-23).

### Operations › Production units (`/operations/units/`)

Every tank, pond and cage of Setup with the fish in it now, and the operations on them: the platform's
`/sites/tanks`. Tables `batches`, `stock_operations` and `stock_movements`.

**The page.** A Production tab with the number of stocked units (the cleaner-fish tab comes later), a
search (unit, batch, species), **New batch**, one row of filters (site, kind, stocked or empty, status),
the count line ("14 units · 3.2 t") and a table with the source's nine default columns: unit (code,
production department · site), batch ("B-2026-001 + B-2026-004" and the species, or "Empty — ready to
stock"), fish, average weight, biomass, density · capacity with its bar, biological FCR (bFCR), survival and last
fed, both from the feeding records (see Feeding records; the source showed 0 and nothing). A row
picked (accent tint and bar) and a row over its max biomass (amber, an "Over" mark, a rust bar) look
different. A unit holding lots of one species further apart in weight than the species' size limit (stocked with the
acknowledgement, or weighed apart since) has a warning chip by its code, on this page and on the Meal board, at the
weights each page shows: here the measured ones with their day ("Mixed sizes: 4,217 g as stocked 10 Oct 2026 and 78.0 g
weighed 3 Nov 2026 (limit 2×)", `UnitStock.size_mixes`), on the board its estimates ("4,602 g est."), so the chip and
the line beside it never disagree; cleaner fish against their own species only. The filters and the open unit are in the address, so a view can be linked and the back
button works; a row is one link. Two empty states: no units at all (with a link to Setup) and no match
(with "Clear filters"). The column chooser and sorting come next.
For people who may read the water (see Water chemistry), the table also has **Temp. (°C)** and **O₂ (mg/L)**
after survival, each the latest value of the unit's middle sampling point coloured by its status, stale ones grey
(time and age on hover), a status dot by the unit's code (its worst fresh status), and the count line says how many units
shown are critical ("14 units · 3.2 t · 2 critical"); the production overview has a tile "Sampling points with a
critical water value", the Water chemistry page's own count (every point it lists, an outlet too), so the two never disagree.

**The drawer** (`?unit=`), beside the table: the unit's code, name, place, status and since when; for a
stocked unit its batches, "Stocked · N days", fish, average, biomass, bFCR and eFCR, survival, the density
bar against its max with the volume, a line per batch (fish, average and when it was weighed, biomass,
survival, deaths and culls, the feed of its stay and its bFCR, its share of the unit), its feeding (see
Feeding records) and the operations, **Record feeding** first; for an empty unit its volume, max density
and max biomass and "Stock this unit" with the unit chosen, or why it cannot be stocked; for every unit,
with the water read, its **Water**: the latest value of every parameter with its age, status and limits,
the worked-out NH₃-N and O₂ saturation, **Record water sample** (the unit fixed, back to the drawer) and
its water history; for every unit its last 20 operations and 10 feedings, voided ones struck through with
their reason, each with **Void** while it may be voided.

**Operations**, each a dialog (in the shared dialog, or as a page) whose form is one call of the stock
service, with the server's reason on the field it concerns: a new batch (species, stage at input,
stocking date, fish arriving and their average weight, origin, farmed or wild-caught (the origin says it
for the own hatchery's fish and the farm's catch; bought fish say it, which a cleaner fish requires), supplier
and its batch number, strain, year class, name, expected harvest, notes, and the units the fish go into, whose
fish must add up to the fish arriving); mortality (fish, cause, the weighed kilos if known); cull (fish,
reason: a cleaner fish's are the six causes of Mattilsynet's cleaner-fish report, a production fish's the
others, each batch offered its own); a sampling
weigh-in (fish weighed and their weight together, or a measured average); transfer / split (to one or
several units, a reason); grading (per size class a unit, fish and measured average, and the average of
the fish that stay); harvest (fish and their round kilos as weighed, the slaughter facility, the transport and
vessel; "this empties the unit of this batch" records the fish the book still holds as an unaccounted loss; see
Operations › Harvest); **delivery** (live fish out of the company: fish, their weighed kilos if known, who received them and
the receiving site's lokalitetsnummer if it has one; it is a transport, so the fast is checked; it is the smolt report's fish
moved out of the site); **escape** (fish escaped or only suspected, the cause, when found, the health status of the fish and the
fish recaptured: a count adjustment of the reason escape with its record, from which Fiskeridirektoratet's notice is started; an
escape from several units is recorded for each). A harvest shows the handling check (the medicine withdrawal and the fast) and a transfer, a grading and a
delivery the fast alone (a medicine withdrawal is a meat withdrawal: it means nothing for live fish), and each asks for an
acknowledgement when it warns. A unit holding two batches asks which one.
Dates default to the farm's today (the site's time zone), never in the future, at most the platform owner's correction window (31 days until they set another; Platform settings) back
(`core.platform.correction_window_days`). A refusal by the window says what to do: every such message is worded in one
place (`farm.stock.dates.too_old`) and ends with whose setting the window is and where it is changed ("The correction
window is the platform owner’s setting: it is changed in Company › Administration › Platform settings.",
`core.platform.window_way_out`, the path read from the menu), and a refused stocking first names the opening balance
("Fish the farm already had before then are registered as an opening balance (Company › Administration › Opening
balances), by the platform owner."): a stock operation and its void, a feeding, a water sample and its void, a
treatment, a lice count, a health event, a movement of the store, a harvest plan, a protocol assignment and an
experiment's day 0 (`farm/tests/test_window_refusals.py`). A form sent twice records once (the form's key, stored with it in `entry_keys`).

**The opening balance** (F-197; Company › Administration › Opening balances, `/administration/opening-balances/`): the fish
a farm already has on the day it starts using the platform. The platform owner (Platform settings: Edit; nobody else, checked
in the view and in the service) registers each batch with the stocking dialog's form and unit rows plus the takeover day,
the real stocking date, the year class (required) and the source document the counts come from (the old system's export,
a count sheet). It is a stocking (`OperationKind.INPUT`) with an `OpeningBalance` record, as an escape is a count adjustment
with its record, and is named "Opening balance" wherever it is listed: the operation is dated the takeover day, inside the
correction window, with the count and average weight of that day; the batch's stocking date is the real one, any day up to
the takeover day, beyond the window by design. Every read of the ledger takes the fish as stock already there: their stay
starts on the real stocking date (days stocked, the drawer's "since"), their average counts as measured on the takeover day
(the biomass report's basis, the feeding projection's start), nothing exists before the takeover day, and the reports never
count them as fish stocked (the monthly biomass report leaves them out of "stocked", the cleaner-fish report adds them to the
month's opening figure, a site-in-use notice does not count them as fish arriving), each saying in a warning that the stock
was taken over that day. Its log entry is critical, with the document and the real stocking date. It is voided like any
stocking (inside the window), which voids its batch. `check_stock` accepts an opening balance dated after its batch's
stocking date and still finds any other stocking off its batch's date.

**The ledger.** A batch holds its identity and origin, no count. An operation (`StockOperation`) is what
a person did, with its date; its lines (`StockMovement`) say how many fish of which batch came into (+)
or left (−) which unit, or were weighed there (0). Every figure on the page is computed from the live
lines: a unit's fish is their sum, its biomass a date-ordered fold (`farm/stock/fold.py`): fish leave at
their batch's average in that unit on that day, a weighing sets the biomass from that day, the last fish
out take whatever the book holds, moved fish arrive with exactly the grams that left, a grading weighs
the whole lot. Only measured weights enter the book. Nothing is stored that can drift.

**A record of a day the unit held fish can be entered once the unit is empty** (flow fault S-04): the dialogs gate on
the record's own day inside the correction window, never on the fish in the unit today. A dialog of a unit offers the
batches in it now and those that left it on a day that may still be dated (`farm.stock.read.left_within`, `PastShare`:
"B-2026-001 — in the unit until 10.11.2026"); the Treatments and Sea-lice count dialogs and the feeding chooser offer
such units, and the drawer of an emptied unit has "Records of the fish that left" with the same dialogs. A unit that is
empty now gets no default date (today would be wrong): the person gives the day, in the stock dialogs and in the
feeding, treatment and sea-lice dialogs alike (`farm.stock.read.offered_day`); the batch choice counts the batches the
unit holds now and says that those that left can still be chosen (`farm.forms.stock.batches_help`,
`farm/tests/test_review_texts.py`). The service decides on that day as it
does for every record, so every later figure follows (a weighing dated before the harvest changes the harvest's book
kilos; a treatment dated before it is asked about the harvest inside its withdrawal), and a record that would leave a
later operation without its fish is refused, naming it ("The harvest of 10.11.2026 in T-01 would be left without its
fish … Void that operation first, or correct this one."). No fish now and none inside the window is said: "No fish are
in T-02, and none were in it in the last 31 days: there is nothing to record here." (`farm/tests/test_emptied_unit.py`).

**One write path** (`farm/stock/services.py`, `_commit`): it locks the batches and the units, checks the
date, the units' status (a unit takes fish while active, preparing or fallow, and only on a site: F-212), the species (one per unit,
several batches of it; on a sea site cleaner fish may join the production species, see Cleaner fish below), then
writes and folds every batch involved from its first line, so a backdated
operation is accepted only if every later day stays right (no share ever below 0 fish, and every feeding
recorded in the unit still finds fish there on its day: "The feeding of 2 Nov in T-01 would have no fish:
void it first."); above a unit's max biomass it asks for an acknowledgement, stored on the operation. The same way, a
stocking, a transfer or split and a grading that would leave a unit holding lots of one species further apart in
weight than the species' size limit (Setup › Species; none set: no check) ask for an acknowledgement of their own ("T-01
would hold Atlantic salmon (SAL) of very different sizes on 4 Nov 2026: B-2026-004 at 4,217 g as stocked 10 Oct 2026
and B-2026-007 at 78.0 g as stocked 20 Oct 2026, 54.07 times as heavy, above the limit of 2×"), stored on the
operation (`size_mix_ack`, a database check keeps it to operations that bring fish in) and in its log entry; both
questions are asked together and each box answers its own. **Lots** (`farm/stock/sizes.py`): a unit's fish by size,
kept along the fold, so the size classes of one batch put back together after a grading are compared like two batches
(the cross review's F1); a weighing keeps the lots' spread, a grading's weighing of the fish that stay makes them one.
The weights compared are the feeding walk's estimates where feed was credited since the measured point, else the
measured weights, said with their day; the ratio is rounded up to 0.01 so it never reads as the limit; cleaner fish are
weighed against their own species only, never the salmon they clean. **Every later day too** (F2): the timeline with
the operation is folded against the one without it, and a unit over its capacity, or a mix, that appears on any day
from the operation's date on because of it is asked about (a backdated stocking before a later one), at that day. **A
void** (F3) asks the same of the fish it brings back, with the same boxes on its dialog, the answer kept in its log
entry. A weighing, a mortality or any operation that brings no fish in is never asked (a weighing that shows a mix is
warned about on the pages instead). The unit's status follows its fish:
the first fish make a preparing or fallow unit active, the last fish out make an active one fallow and
a harvesting or quarantined one due for cleaning; a void that brings fish back makes the unit active.
Every operation, every void and every status change is in the activity log ("Voided", with the reason).

**Cleaner fish** (lumpfish, wrasse: a species with a cleaner-fish type) are batches like any other, in the same
ledger, with the same operations, and on a sea site they share the production fish's cage: a unit holds one
species of production fish, beside any cleaner fish; elsewhere one species (a hatchery's tank has one `artskode`
in the smolt report). They are not part of the unit's fish: its count, biomass, average, density, capacity,
survival, bFCR and feed rate are the production fish's (cleaner fish are outside the biomass and capacity rules,
docs/regulatory-reports.md, D-2; the capacity check of an arrival asks about the production fish's biomass only), and
the cleaner fish get a line of their own in the row and the drawer ("Cleaner fish: B-2026-004 · 10,000 fish"),
marked in the drawer's batch table. A cleaner fish is not harvested (it is culled at the end of its use, for
the cause "healthy, no longer to be used"), so the harvest dialog, the harvest plan and the harvest targets
leave it out; a sea-lice count needs production fish in the unit (the lice are counted on the salmon); the
medicine withdrawal and the water judging still see every fish. Which of the two a feeding is for is on the
record (see Feeding records). `check_stock` holds the species rule with the same function as the service. Whether a
species is a cleaner fish is fixed once fish of it have been stocked (every read takes the flag live; lumpfish to
wrasse may change).

**The development seed's mixed cages.** `manage.py fix_seed_size_mix --user <name> [--dry-run]
[--accept-handling-warnings]` separates what the seed history (seed-history-2026-11) stocked together in Tromsø's TG-M01
and TG-M02: the post-smolt B-2026-005 and the smolt B-2026-007 go by the app's own transfers (reason "growth stage",
dated the farm's today) into cages of their own, TG-M03 and TG-M04, made like TG-M02 through the units form; the
grow-out salmon B-2026-004 and its lumpfish stay in TG-M01, and TG-M02's lumpfish follow the post-smolt into TG-M03
after them (reason "other", the notes say why: a cage of cleaner fish alone is not realistic), leaving TG-M02 empty. Not dated back to the stocking: every later record of those fish
(mortalities, weighings, the escape, the cages' feedings) was booked in the old cages, and the stock refuses a transfer
that would leave them without their fish. One transaction, locks in the lock order, checked before it commits (the
cages, `check_stock` finding nothing new); run again it does nothing; `--dry-run` only reads, in a read-only
transaction. The run needs the database migrated. The dry run also reads a database not migrated yet: the units and
batches of the plan are read with the columns the database holds (`stored`: a column a pending migration adds to their
tables, the unit's water origin of farm 0041 for one, is left out, whichever it is), and the stock without the opening
balances.

**Batch details.** A batch's year class (årsklasse) and whether its fish are farmed or wild-caught are what the reports
ask of a batch and what fish stocked before they were asked for do not have; stock is never edited, so the drawer's batch
table has a **Batch details** dialog (who may record stock) that sets the two, logged as an update of the batch whose version
moves on, so a report filed from the batch is told to need a correction. The own hatchery's fish are farmed and the farm's
catch wild-caught whatever is typed; a bought cleaner fish must say which.

**Void** is the undo: the operation stops counting, the stock is folded again without it, and it is
refused when later operations need its fish (the message names them). A correction is a void and a new
entry. Voiding a stocking voids its batch; a batch number is never given twice. The admin shows voided
operations and batches but does not restore them (a restore would skip the checks).

**Who may do what:** the area Production units in the role matrix (Production · Operations): Read the
page, Create records an operation, Delete voids one. The feeding figures (bFCR, last fed, the batches' fed and
bFCR, the drawer's eFCR and Feeding part) are shown only to people who may read the feeding records, as the
Temp. and O₂ columns are to those who may read the water (`feeding.views.unit_figures`); a role with the stock
right alone sees the stock. A unit with fish cannot be deleted, nor resized,
nor set to a status that needs it empty; a species with batches and a supplier fish were bought from
cannot be deleted (`PROTECT`). `manage.py check_stock` checks the whole ledger from scratch (counts,
operations made of their lines, stocking dates, unit statuses, species, feedings without fish, fish in a unit or
a production department without a site) and the tests run it.

Differences from the source (details in the bug document, STK-01 to STK-73):

- One ledger instead of the count in six places and the biomass in seven; no mirrors, no reconcile
  job, no read-model tables. A batch's status is derived (in stock, ended), not set by hand.
- The split of a new batch must add up; fish never come from nowhere (no "allocate").
- Removals at the unit's own average, weighings applied in date order, a harvest's weighed kilos kept
  beside the book (the last harvest is never refused); grading in one transaction, as a weighing.
- One date rule and one void for every operation; the server's reasons reach the person; dialogs in
  the person's language; the drawer's "Stock this unit" knows its unit.
- Days stocked, survival and losses per unit over its current stay; survival counts deaths only, losses
  deaths and culls (owner decision Q2). Capacity and density computed on every read.
- The medicine withdrawal of a unit's fish is on its row and in its drawer (see Operations › Health); the
  harvest dialog's warning and acknowledgement are the handling check's (farm/handling). A transfer or a grading
  moves live fish: it is not warned of a medicine withdrawal.
- Not ported: a cleaner-fish tab of its own (the announced one; their figures are on the unit's line and drawer
  for now), sensors (the water comes from the samples, see Water chemistry), lot numbers, buyers and prices, batch
  documents and costs, a dialog for a count correction (an escape is the one count adjustment with a dialog). Harvest
  plans and the handling check are on
  Operations › Harvest; the medicine withdrawal they check is the health records' (Operations › Health),
  through the registry of farm/handling/withdrawal.py. The registry answers for many units at once (a provider
  takes `(units, day)` and gives `{unit id: blocks}`; `blocks_of`, `check.in_force_of`), so a page of fifty units
  costs what a page of one does.

### Operations › Monitoring (`/operations/monitoring/`)

A live card per tank, pond or cage, small, simple or detailed, in one grid that doubles as a wall screen for a control room
(the Small card is made for a wide monitor: every tank of a hall on one screen), with a unit's Deffeyes chart in a movable
window. The app `monitoring` is composition only: it stores nothing but shared wall boards and card templates, derives no
figure and writes nothing, a poll included. Every number on a card comes from the module that owns it, through a read that
answers for many units at once (the table is `monitoring/read.py`'s docstring):

| Card figure | Owner |
|---|---|
| fish, average g, biomass, volume, density, capacity, over capacity, since, deaths, culls, survival, last weighed, batches | `UnitStock` (farm/stock/read.py), `stock_of` |
| ration, fed today, remaining, next meal, why there is no ration (a fast too), weigh soon or now | `feeding.read.figures(details, ration=True)`: one walk of the projected weight for all the cards, then `meal_lines` and `drift`, which the meal board prints too |
| bFCR, eFCR, last fed, feed rate, feed in use | `UnitFeeding`, `Week` |
| water per parameter with age and status | `water.read.points_water`: one `latest()`, the middle point of a simple card, every active point of a detailed one |
| medicine withdrawal | the registry's one bulk answer (`harvest.views.withdrawals`), with the stock right, as Production units |
| open health events (every card), treatments and the latest sea-lice count (detailed) | `health.read.open_events`, `recent_treatments`, `latest_counts` |
| open, overdue and due-today tasks (detailed) | `tasks.read.per_unit` |
| the Deffeyes chart in its window | `water.calculation.chart_of` through `farm:water_unit_chart` (see Water chemistry) |
| a unit's or a system's water history (Tank › Water, System › Water, behind `?ui=next`) | `farm:water_unit_chart` / `farm:water_system_chart` with `?view=history`: `sensors.read.water_history` (every parameter's `series` on one window, the NH₃-N worked out per sample, the limit bands `bands_of`), the events each for the person who may read them, the Deffeyes replay's address and the Deffeyes for the range (`range_deffeyes`: about 120 replay frames of the window, the newest frame's diagram from `deffeyes.render` with the pH labels the server placed, the water's path through the time broken where a frame has no diagram, else the reason); a system's points side by side. The page's from and to are the shared date box (dd.mm.yyyy HH:MM), its events marks on every chart (named, reached by Tab, a link to the record) |
| the calculated CO₂ and the pH window of a card that shows them (the Small card) | `water.calculation.charts_of`: every such unit's chart at once, from the water the card read already holds and one read of the fish's limits |

**The page** has a toolbar (a GET form that works without script: site, department, system, kind, fish (stocked by default,
empty, all), the cards (Simple, Small, Detailed), a text search, a unit picker, Wall and Full screen) and the grid: the
**band** (below) and one article per unit in the farm's one order (site, department, code), so a card never moves when its
state does.
Each card has its Simple or Detailed link (the page with that card flipped; with script the grid refetches), its state word
and shape, the withdrawal with its date, and a Deffeyes chart button that opens the window. A **section the person may not read
is not read at all** (no query) and the card says so ("Water: not shown to you" and "State from: Fish"); one right for each
section (`monitoring.read.sections_for`, the one place that spells a permission). Detailed never widens access.

**Shell first** (live-arch stage 1, 2026-11-23). The page itself is drawn WITHOUT its cards: the toolbar, the grid's place
holding "Loading the cards…" (`templates/monitoring/_loading.html`), the pane's frame when the address has a focus, the
windows' place. It has no band, no tally, no card, no state word and no state colour, so a page whose cards have not come
never reads as all is well, and it reads no card source (no stock, feeding or water read, no change token): it costs the same
few queries whatever the farm. The grid is drawn with `data-poll-state="loading"` and its address carries no token, so
`frontend/poll.ts` asks for the fragment at once (as soon as every script of the page has run, so `announce.ts` is in
place to hear a first failure) and its first answer is always the cards (200), with the next address
(`X-Poll-Next`), from which the polls go on as below; the fragment replaces the placeholder by key, and that first fill says
nothing aloud (it is the first load); then the page goes to the card a `#card-<unit>` address names, as a page drawn
whole does. A first answer that fails (the 503 of a source the cards need, a server error, no answer within 35 s, a 204,
or a 200 with nothing keyed in it: an empty body, a proxy's page) shows "The cards cannot be read just now. The page tries
again by itself." at once, in the look of the stale notice, and says it aloud once, in the POLITE live region
(`frontend/announce.ts`; the stale and gone notices stay assertive); the page asks again, never more than 10 s apart while
nothing is on the screen, and when the cards come it says "Updated again." politely. A first fill that succeeds says
nothing. A 401, 403 or a redirect to sign-in is gone, as for any poll (the red notice, the placeholder hidden). The pane's
body (`?focus=`) is filled the same way from its own fragment, and its "cannot be read" is said politely too. A
WATCHDOG line in the grid's placeholder, "Still loading? Open the full page" (a link to `?full=1`), is hidden and shown
by the sheet after 30 s (an animation's delay, CSS only): it is the way out when poll.js never loads or never runs, and
it goes with the placeholder at the first fill. On a wall the placeholder's lines have the notices' size. `?full=1` is the page as it was before, the cards drawn by the server: the way in
without script (the placeholder's `<noscript>` link) and what the old pages' tests read. The shell with its first answers put
in place is byte for byte the full page (`monitoring/tests/test_shell.py` ParityTests; on the dev data, the parity of the
branch against main). The fragment and the pane are unchanged.

**The band** (`monitoring.read.band`, `templates/monitoring/_grid.html`; it replaced the head and the strip of one-line
reasons, 2026-11-13) stands above the cards on the page and in every answer of the fragment, as ONE keyed child: when the
cards were computed ("computed at 09:17", so a frozen screen is visibly old) and how many units are shown ("2 of 3 units
shown"); the **tally**, how many units are on each rung (shape, count, word: "1 Critical", "2 Warning", "14 OK"), which
counts every card whatever follows; the page of cards and its turn buttons (shown by `frontend/wall.ts` when a wall has
more cards than fit); the switch of the screen's cards (Small, Simple, Detailed; on a board: Small, As the board), plain
links that keep the filters and the wall; then a **chip** per thing that needs a look, worst first: the state's shape
(its word for a screen reader), the units' codes, each a link to its card, and what is wrong in short, the value against
the bound it is past ("T-02 O₂ (mg/L) 5.00 < critical limit 6.00"; a warning against the number alone, "6.50 < 7.00";
an old value says "no recent data"). Units whose chip would say the same words share one chip; the units with no recent
data share one, and those with a value no limit judges another. The server caps it: at most `MONITOR_BAND_CHIPS` chips
(6), each naming at most `MONITOR_BAND_CODES` units (4), the rest counted ("+3", "+5 more units"), never dropped
silently. The short form of a reason is its `Brief` (`read.brief_of`): the water's own answer to "which value is past
which bound" (`farm.water.read.crossed`, `evaluate.crossed`: the bound `judge` judged it by, the worse fresh value when
that decided the status, the oxygen's other unit when a row on that unit judged it), never a second judgement; a reason
that is not a value against a bound is said whole. A value worked out (the oxygen in its other unit, the NH₃-N) is judged
unrounded (`Reading.exact`) and shown at its parameter's decimals, so a true 59.988 % of saturation, critical against 60.0,
is shown 60.0; a sentence that sets such a value beside its bound never reads as on it or inside it: where the shown value
would, it says the exact value with the fewest extra decimals that read past ("O₂ (%) 59.99 < critical limit 60.0"; at
most three more decimals, then cut toward the side it is on; `farm.templatetags.water.value_past`, the one rule). The
judgement is never changed, only the words: the same rule says the value in the bar's name ("O₂ (%) 59.99, critical;
limits: critical below 60.0, …"), in the note an oxygen judged through its other unit keeps ("Judged as 59.99 %.") and in
the two notes the drawer prints right after a row's limits ("… reads 59.99 (…): the worst fresh value decides the
status", "last own value 59.99 critical on …", which the alarm's summary carries too: `read.said_value`), and a chip of
units past the same bound says the lowest (or highest) of their unrounded values. The figure on its own says it too
(owner decision, 2026-11-22: "show as many decimals as it takes to show it is past"): a value judged past a bound that its
shown value rounds onto is shown with the decimals that prove it everywhere it is shown, 59.99 and not 60.0: the cell of
the water tables, the drawer and the overview (`farm/_water_value.html`, filter `reading_figure`), the cards' figure and
the saturation beside a tile's label (`render.face`, `render.tile`) and the alarm's summary. One rule for all of them:
`read.past_bound` (the nearest bound its own value was judged past, on the unrounded value) and
`farm.templatetags.water.proof_of` (the fewest decimals that read past it). A value clearly past its bound, a value inside
its bounds and a measured value (judged as entered) keep the parameter's decimals ("55.0", "60.0"). Known limits, left as
they are: the calculator (judged in the Rust core on floats, printed without a bound), the position of the bar's marker
(drawn at the rounded value) and `signed_amount` (a calculator margin of -0.003 reads 0.00). On a wall each row of the
band is one line; on the desk page they wrap.

**The Small card and the screen's view** (owner decisions 5 and 7, 2026-11-12: wide monitors; a small card for the
overview). `mode=small` is a VIEW of the screen: EVERY card of it is drawn with the built-in Small template, on a board or
not, whatever the rules say (it ranks first in the ladder below; "Template: Small · the view chosen on this screen" is in
the unit name's title). The Small card says the unit's code and name, its state's shape and word, the FIRST reason of the
state in short with how many more there are ("O₂ (mg/L) 5.00 · critical limit 6.00  +1"; every reason is there in full
in the titles and for a screen reader, and on the card its flip link shows), or, with no reason, its fish ("Atlantic
salmon · 12,000 fish · 1,045 kg · 7.4 kg/m³"); then four values, each a short label, the figure and, where the card is
tall enough, how old it is and where it came from: the oxygen in mg/L with its saturation beside the label
("O₂ · 98.0 %"), the temperature, the pH and the **calculated CO₂**; and the **pH window**. A figure past its limit takes
the state's shape and colour and its word under it; an old value says "old" in its label whatever the card's height and
is set in italics; a missing one is said in words ("no data"), never as a dash. The unit's status when it is not in use,
the withdrawal (the word; its batches and dates in its title, and "until 25.11.2026" in the reason line of a Note card),
a source that could not be read and the flip link (to Detailed, until the Big card exists) are on the frame.
The **calculated CO₂** is the figure the chemistry core's analysis gives for the unit's chart (from the pH, the
alkalinity, the temperature and the salinity; owner decision 2: a probe's value never enters the chart), tagged
"calculated" with the age of the oldest of those four values. In this first phase it is SHOWN, NOT JUDGED: the card's
state is what the readings say, as before, so a card can say OK while its pH window shows the water in the CO₂ region;
that changes when the calculated CO₂ becomes a judged value (after the chemistry branch has landed).
The **pH window** (`monitoring.cards.render.ph_window`, drawn by the server as an SVG in percentages, with no script and
no style attribute) is the Deffeyes chart's one-line slice at the unit's own alkalinity, on the scale the farm has set for the unit's
WATER TYPE (owner decision 15, 2026-11-16: `monitoring.PhWindowScale`, one row for each of the product's water types,
freshwater, saltwater and brackish, the class a unit's water already has (`Tank.water_type`); seeded by migration 0007
with the 6.4 to 8.6 the code held; changed on **Setup › Reference data › pH window scales** (`/ph-window-scales/`, its
own right to read and to change, never added or deleted: a CHECK keeps one row per water type, the ends between 0 and
14 and at least half a pH unit apart); the card read fetches the rows ONCE for a wall whose cards draw the window
(`read.ph_scales`, no query per card, none for a wall without the window); a water whose row is gone says "The pH
window cannot be drawn: no scale is set for freshwater." and no number of the code stands in). A pH beyond the scale
is an arrow and the number at that end ("◀ 6.10"), never a mark drawn on the end, and the picture's name says the
scale. Left of one border the CO₂ is past its limit, right of the other the
NH₃ is, each border with its pH; the mark is the unit's pH. A region is grey and takes the critical tint only while the
water is in it (the core says so: past that border); the stretch between the borders is green only when the core has a
safe zone at all (every limit it needs is set) and the limits judge the unit's alkalinity inside its band; a missing
limit is never drawn as a safe side ("no NH₃ limit", "no TAN"); the mark is hollow and dashed when a value it is drawn
from is old; its name says every number in words. When the chart cannot be worked out it says why in one line ("The pH
window cannot be drawn: no value of Salinity (‰, g/kg).").

**The state** is one ladder (`state_of`, the thresholds are the owners', none invented here): critical (a water reading judged
critical, an old one too: "CO₂: Critical, no recent data", the water page's rule through
`PointWater.alerts`); warning (a warning reading, an old one too, over capacity, an estimate that says weigh now); **no recent data** (a stocked unit whose
temperature or oxygen is missing or older than its 24 hours, or with no middle point, or whose live sensors could not be read:
the water's own status ranks OK above stale, so a fresh pH would hide a three-day-old oxygen; never OK, never red, the age is
printed; not worked out when the water is hidden); **no limit** (a value of the stocked unit that no water limit row judges for
every species of its fish, "pH (NBS scale): no limit for these fish": a row for the salmon does not judge it for the lumpfish
beside them (`Limits.uncovered`); what it means for the fish is not known, so it is never OK. The dissolved oxygen is one
quantity (owner, 2026-11-07): a % with no row of its own is worked out to mg/L with the solubility (its own observation's
temperature, else the point's fresh one, the salinity and the site's pressure) and judged by the mg/L row, and the reverse;
one that cannot be worked out is "no limit". Both values are shown with their origin and age); note (a withdrawal in force,
weigh soon, a ration that cannot be
worked out with its reason, an open health event); ok; empty. Word, shape and reasons, never colour alone; the words are
`read.STATES`, the one list the card, the strip, the announcer and the designer read.

**Danger is never shown as OK** (audit F-090, F-244, F-088, F-025, F-134). A value keeps what its limit said when it grows old
(`Reading.judged` beside `status`, farm/water/read.py): an old critical nitrite keeps the card critical ("Nitrite: Critical, no
recent data, 8 days old") and marks the article `data-stale`, so the announcer says it ("T-01 is now Critical, no recent data"; it takes the order of the states from the page, `data-states`,
never from a list of its own);
a card that falls to no recent data from any state is said too, and the grid's own notices (not updated, signed out, updated
again) are said in the assertive region. Reference data › Water limits lists **Fish with no limit**: per species and water type
kept today, the parameters no row judges (`water.read.missing_limits`). The value-against-limits bar draws each stretch as
`evaluate.judge` says of it, so limits with upper bounds only are ok below them. A source that fails is logged with its name and
trace (at most once a minute per source): a required one gives the 503 (the screen keeps its last picture and says it is not
updated), an optional one says "Could not be read: Tasks" on the frame, where no template can hide it.

**Polling.** The grid is `data-poll` with `data-poll-merge="data-key"` (every 15 s, `settings.MONITOR_POLL_SECONDS`). The
fragment `cards/?...&after=<token>` computes the **change token** first (`core.audit.revision()`: the newest audit entry and
how many lie in the five minutes up to it, two indexed queries, read before any data; the minute, the language, what the person
may read, the board and the canonical address), answers **204** with the same `X-Poll-Next` while it is equal, else 200 with the
cards and the next address; the minute re-draws the figures that run on the clock at most once a minute. A writer that does not
write its audit entry would leave a card up to a minute old: the token test enumerates the writers. The fragment is rendered
without a request, so the shell's context (the menu, the unread count) is never worked out for a poll.

**The wall.** `?wall=1` puts `data-wall` on `<html>` (no rail, no top bar, no width limit, larger figures), and the page and its
polls keep the session alive once a day (the default session is two weeks and a wall must not sign itself out); the grid prints a
large notice from `data-poll-state` when the server cannot be reached or cannot read the cards, or the person is signed out,
and the announcer says it aloud (and says when the grid is updated again). A wall of cards that flow (Simple, Detailed, a
template without a measure) is as it was: larger figures, and the page scrolls.

**The wall of fitted cards** (`?wall=1&mode=small`; `static/css/monitor.css`, `frontend/wall.ts`). A template with a
**measure** (its card's width and height in the card's own unit: Small is 31 by 10) is FITTED: the card is drawn at the
size of its cell, and every length inside it is a multiple of ONE unit taken from the card's own size (`--u`, container
units), in four type sizes (0.8, 1, 1.25 and 2.4 of the unit: `tw:text-u-s`, `-m`, `-l`, `-xl`) and two weights, so the
same card reads on a 1080-high desk screen and a 2160-high wall. The wall is exactly one screen: the band and columns by
rows of equal cells, chosen by the one **slot rule** (`monitoring/cards/slots.py`, the authority, and
`frontend/wall/slots.ts`, where the screen's size is known; both run `monitoring/tests/slot_vectors.json`): of every grid
whose cells hold all the cards, the one that gives a card its largest unit; when that unit is under 14 px (the smallest
text would be under 11 px) the wall turns PAGES rather than shrink the type: the grid with the most cells that can still
be read, PageDown and PageUp (and the band's buttons) turn the page, the band says "2 / 3", and the wall opens on the page
of its worst card. A card never moves, so a page is always the same cards. Twenty small cards are one page on 3440×1440,
5120×1440, 2560×1440, 3840×2160 and 1920×1080 (5 by 4 on the two wide screens, 4 by 5 on 16:9); twenty-four are one
page on the first four and two pages on 1920×1080 (`monitoring/tests/slot_vectors.json`). The line under each figure
says where it came from in one word and how old it is ("sensor · 12 s", "sample · 3 h", "calc. · 7 d") at EVERY size
(review R1: a value 23 hours old must not look like one of ten minutes ago, and a wall has no pointer for a title):
the Small measure (31 × 12) holds it, nothing hides it, and a cell too low for the card turns pages.
The script sets only custom properties and attributes on the grid (never on a card: the poll would replace it), lays the
wall out again after every poll and resize, and without it the cards stand four across and the grid scrolls. The
toolbar's two buttons (leave the wall, full screen) stand at the band's right end as icons. On the desk page a fitted
card is at least 34 rem wide and as high as it needs.

The window's WORDS (a border's pH, "no NH₃ limit", "no TAN") are placed by one rule, `render.place_names`, and never
stand over one another, over the water's mark or outside the picture: a border's word stands in its own region
against its border; else between the borders against it, when the stretch holds it; else in its own region moved past
what stands in the way; the CO₂ word is always left of the NH₃ word; when no pair of places fits, the word of the
border nearer the water stands alone and the other's number is in the picture's name. The server does not know a
word's width, so it reckons it from its letters and the card's measure (`letter_pc`); the browser layout test holds
that to the real boxes (no two marks of a window touch, on every screen it lays out). When the farm has set no
alkalinity limit row the stretch between the borders is not drawn safe and the window says why in words ("no
alkalinity band", its short form where only that fits, and always in the picture's name: review R6).

**Going into a tank: the pane** (Phase 1D; owner decision 7: "in the small one, when an alarm comes they go INTO it
and look"). On a card of the overview (a fitted card that is not a full-height one: the Small card) the unit's CODE is
a link, `?focus=<unit>`: the page then draws that unit's Big card in a pane (`#monitor-dock`,
`templates/monitoring/_dock.html`) and marks the card that is open with an outline; the link of the open card, the
pane's "Close" link and Escape close it. It is a link, so it works without script (the pane stands before the cards in
the page); with script `frontend/windows.ts` DOCKS the existing window: it opens, replaces (one tank at a time) and
closes the pane without a page load, the address follows (`history.replaceState`, the page's own query with `focus`
set or taken out), the pane's body is polled at its own fragment (`monitoring:pane`,
`/operations/monitoring/pane/?focus=…`: the Big card keyed as a card of the grid, 204 while nothing changed, 404 when
the unit is gone, which closes the pane) and the grid is asked again at once with the same query, so `focus` is part of
the canonical address (`Params.focus`) and every later poll of the grid carries it. The overview stays alive beside the
pane: `frontend/wall.ts` gives the pane the width of ONE cell of a wall of full-height cards on this screen
(`frontend/wall/slots.ts dock`, at most half the screen) and the cards the room that is left, by the same slot rule
(they only get narrower or turn pages: the order is the same and a card never moves); a window too low for a readable
Big card beside the cards gets the pane OVER the cards (`data-dock="full"`), never a hidden one. The band's chips open
the unit they name where the cards are small ones (and turn the wall to that card's page); on a wall of full-height
cards a chip turns to its card's page. The switch to Big drops the focus (the pane is the way into one tank from an
overview). The card in the pane is a second card of its unit on the page, so its ids carry a `pane-` prefix; its code
links to the unit's page, and it says IN SIGHT what the Small card only has room to say in a title (review R11: a wall
has no pointer): the department beside the name, and at its foot what the state is from and which template draws it.
The Small card keeps the oxygen's saturation beside its label when the mg/L is old (R11). Cost: the pane is one unit's
card read (the same `read.cards`, 43 reads), on the page with a focus and at each of its own polls that finds
a change.

**The keys of a wall** (`frontend/wall.ts`, `frontend/windows.ts`): PageDown and PageUp turn the page; **Home** goes
to the page of the worst card (critical, then warning, then no recent data) and puts the focus on that card's link, so
Enter opens it; Escape closes the pane and gives the focus back to the open card's link; Tab and Enter do what they do
on links (every switch is a link). A poll keeps the page shown; while the worst card is on another page the band's page
indicator shows a third button (its state's shape and "→ 3": the page), so a card that became critical elsewhere is
one key or one click away. Every link and button of the band has an id (`pages-prev`, `pages-next`, `pages-worst`,
`mode-…`, `charts-…`, `chip-<unit>`, `band-more`): a poll replaces the whole band, and the control that had the focus
gets it back (poll.ts by id; wall.ts once more after it has shown the page indicator, which the server prints hidden:
review R8).

**Boards** (Setup › Facility structure › Monitoring boards, `/monitoring-boards/`). A board is a
named, shared wall screen: a name (unique among the live boards in any case), a description, the template its cards are drawn
with by default (empty: the rules decide; it ranks below the rules, as its default mode did), its card width (compact,
automatic, comfortable), how often its screens ask (10 to 600 seconds, empty: the system's 15), and its **Units** tab, one
card per unit with its own template (empty: the board's or the rules'; above every rule), saved as a whole list with the board's version (a list based on an outdated
board is refused) and one activity-log entry. Tables `monitor_boards` and `monitor_board_units`; every rule the database can
hold is a constraint (the name, the modes, the refresh range, one card per unit and board). A board holds only live units: the
form offers live units, and a unit that is deleted keeps its row (a configuration, not history), its card hidden by the live join
and back when the unit is restored; saving the list drops the row. There is no position: cards go in the farm's one order. A
board is deleted and restored like any record (nothing depends on it). Anyone who may read Monitoring may choose a board in the
picker (a board is configuration, not a record); the area Monitoring boards in the role matrix, after Tanks, ponds & cages, is for
making and changing them. A window's place is remembered per board on each device.

**Cleaner fish and placements.** A detailed card says the cleaner fish beside the production fish (`UnitStock.cleaner_stock`:
the unit's own figures never count them). When the placement registry (`farm.placements`, a trial's replicate) is present, its
chips are on the cards, from one call for all the units; it fails open (no registry, or one that raises: no chip, nothing else
changes).

**Who may do what.** Reading the page needs the right to read stock operations (Production units' area; the menu entry follows
Production units, which keeps the page title and eyebrow); the fragment has the same gate; the chart needs the water right.

Decisions of the owner (2026-11-04): a wall page extends its session once a day; Production units stops printing bFCR and last fed
to roles without feeding rights; the chart's temperature is the unit's own point's (superseded by A9 on 2026-11-07: the loop's fresh value stands in
when the unit has none of its own); the chart refused and
says so; "No recent data" when the temperature or the oxygen is older than 24 hours or missing, whatever the unit's kind.

Not built, on purpose: any figure recomputed in `monitoring`, a feed-due alarm (the protocols have meals per day, no clock), trend
sparklines, a stored calculation, a server cache or a push channel (a measured miss first), a stored status, an "open in the
calculator" link.

**Measured at 100 units** (a throwaway test database, the test client, 100 stocked units with water and 19 days of feeding each; the
real figures need the live farm): a simple card page costs 48 queries (264 ms of them), the fragment 43, a detailed page 55 and its
fragment 50, the 204 path 7 queries and 20 ms; the render takes 1.7 to 2.8 s and the body 395 to 548 KB (about 4 to 5 KB a card), so
the time is Python and template work, not the database: the change token is what spares an unchanged poll, and a measured slow
screen would first bound the feeding walk (`project` reads every feeding of the lineage) or cache the rendered card, never the other
way round. The queries stay equal from 6 to 100 units (pinned at 6 and 24 in `monitoring/tests/test_budget.py`). `CONN_MAX_AGE` is
left alone: the queries are a tenth of the time, so there is no evidence for it.

**Made faster without a cache** (2026-11-22, on the dev data: 25 units, 20 stocked, 899 feedings, 232 sensor bindings).
The waste found by profiling was removed, every result is still worked out on each request, and **nothing is stored or
cached between requests, so there is nothing to invalidate**: (1) the ration walk read the sensors once per day it asked
a temperature for and once per channel inside that (179 reads of the bindings and the hypertable for one wall); it now
reads the moments the walk can ask (the days a protocol is in force for, not every feeding day) in one ask
(`Series.prefetch`, `sources.values_at`, two queries; on the dev wall the walk asks for 18 moments, 155 were read before
the days were restricted and 18 are now); one failing ask fails every moment of it together, so those moments are then asked one by one as before and
a failure costs only the moments it hits; (2) the last feeding (`last_fed_of`) built every feeding of the lineage as a
record with its unit, department and site; it now reads them once, every column, weighs each as a plain row by the same
`fed_moment` and builds only the winners from those very rows (one snapshot: a feeding voided or changed meanwhile can
neither break the answer nor split a moment from its record); (3) the feeding walk scanned every share of the fold for
each unit of each day; it groups them by unit once per step (`fold._by_unit`); (4) a wall read its units' own-water
points twice (`points_of` and `latest`); it reads them once (`read.own_water`, handed on); (5) the page read the
activity log's revision twice (the grid's token and the pane's); once now. Measured in-process on this machine (5 warm
runs each, median, `main` and the branch back to back while another suite ran): the page 5.0 s and 330 queries before,
2.2 s and 118 after; the cards fragment 4.6 s and 319 queries, 2.7 s and 109; the pane 2.2 s and 136 queries, 1.5 s and
85. Every answer is byte for byte the same on the dev data with the clock pinned. Why no cache: the ration of today runs
on the temperature at the moment of the request and its age, the freshness states must stay live, and a late sensor
reading (the ingest's late path) moves a past day's temperature without any write Django sees, so no key could prove a
stored walk still valid. What is left is Python: the template render of the cards (Django's engine, about 0.5 to 0.7 s
for 20 cards), the water read (about 0.5 s) and the feeding walk (about 0.4 s); the queries stay equal with the units
(`test_budget.EndpointBudgetTests`: the page, the fragment and the pane at 8 and 26 stocked units).

**A clock before the ledger.** The stock reads every ledger line there is, the ration's day stops at the unit's today, and
they agree because no line is dated after the unit's today (a date in the future is refused on the clock of every site
it touches). With the clock set back before the newest lines (the farm replayed as it was on a day) or a site's time
zone moved behind, they differ: a batch that left after the day is in the day's lines and not in the stock, and a unit
stocked after the day holds fish and has no day. The wall answered a 500 for it (a `KeyError` in `meal_lines`, then the
feeding widget's `count meals=` of no day). `feeding.read.meal_lines` now reads a batch its caller does not have (one
query for all, none when the stock has them all) and the feeding widget leaves out the meals line of no day (its other
fields show the dash they show for any missing value); `ClockBeforeTheLedgerTests` pins the clock before such lines. The
card still mixes the two reads while the clock is behind (the stock is the ledger's, the lines are the day's): making
the stock itself clock-aware is a larger change to a reader every page uses, and nothing but a replayed clock needs it.

**A fitted template in the designer** (Phase 1D, review R7). Each widget has its LOOKS (`catalogue.WidgetSpec.looks`):
value, water table, pH window, chart, dosing, points and stock have a fitted look; fish, feeding, health, tasks,
experiments, the bar and the chart button have none. The validator takes the template's measure
(`validate.validate(layout, measure)`): on a fitted card a widget with no fitted look is an ERROR that names it (it
would be cut on a wall without a word), as is a layout of more than 24 rows; a place too low or too narrow for what
the widget prints there (`fit_units`, reckoned from the measure: advice, the preview is the proof) and, on a card that
flows, a widget made for a fitted one, are warnings. The form refuses the measure with the sentence ("This layout
cannot be a fitted card: there is no fitted look for Fish, Feeding …"); the designer's preview sends the form's
measure, shows the same problems and draws the card FITTED at the measure's own proportion (`.designer-preview.is-fitted`).

**Card templates: the widget catalogue and the validator** (`monitoring/cards/`). A card will be a fixed **frame** (the unit,
its state word, shape and reasons, the withdrawal, what the state is from, the flip link: never data, so no template can
remove it) and a **template**, a JSON layout of widgets on a 12-column grid. `catalogue.py` is the one truth of what a card
can hold: each widget type's label, minimum, maximum and default size in cells, the card read's sources it shows, whether it
is bound to a water parameter (and point), and its options as `core.schema.Schema` descriptors (only how it is drawn: no
colour, font, threshold, unit or free text); `as_data()` hands it to the designer in the person's language. The v1 widgets:
value and value-against-limits (one parameter), water (the middle point's key values or every point's every value), fish
(the key figures or every figure), feeding (the week too or not), health, tasks, experiments, the Deffeyes chart button,
the pH window (it reads the unit's chart: source `chart`), and a trend that is catalogued but refused until a bulk series
read exists. A value widget may also be bound to a value the unit's chart works out (`catalogue.CALCULATED`: the
calculated CO₂, `co2_calc_mg_l`, shown at the CO₂ parameter's precision; the designer is offered it among the
parameters). `validate.py` is the one validator (pure, no
query; the model, the form, the preview and the tests call it): errors block (the shape, an unknown version, more than 40
widgets or 32 KB, keys, ids, kinds, whole numbers, a widget outside the 12 columns or below the grid's last row (`catalogue.ROWS`, the
tallest widgets stacked 40 high: a designer's layout, compacted upwards, always fits) or outside its sizes, each overlapping
pair named once, a binding the widget cannot have, an option its schema refuses), warnings never do (no oxygen anywhere,
more than two large widgets, more than 16 widgets). An older layout version is upgraded one pure step at a time and checked
as upgraded, never changed in place; a fixture per version passes. The geometry is shared with the designer's TypeScript
through `monitoring/tests/layout_vectors.json`, which both suites run.

**Card templates in the database** (`monitoring/models.py`, migrations 0002 to 0005). `monitor_card_templates`: a name (unique
among the live templates in any case, not blank), a description, whether it is built in, the layout's version (stamped in
the layout too) and the layout (JSONB), the template its flip link shows (`expanded`, never itself) and the **measure** of
a fitted card (`measure_w`, `measure_h`: its width and height in the card's own unit, 12 to 64 by 6 to 64, both or
neither: a CHECK, said with IS NOT NULL since a range test of a NULL lets a CHECK pass; the form's General tab has the two
fields, and a fitted layout takes at most 24 rows). The database holds
the layout's shape (an object whose widgets are a list), at most 40 widgets, at most 32 KB and the version stamp, so a hand
edit cannot store what no card can read; everything that needs the catalogue is the validator's. Four templates are built in
(`monitoring/cards/builtin.py`, frozen the same in migrations 0002 and 0005, a test keeps them equal): **Simple** and
**Detailed**, the cards as they were (each flips to the other), **Operator view** (the oxygen and the temperature large and
first, then O₂ %, pH and TAN; offered, not a default) and **Small** (fitted, 31 by 10 units: the oxygen, the temperature,
the pH, the calculated CO₂ and the pH window; it flips to Detailed until the Big card exists). A trigger refuses any change
and any delete of a built-in,
whoever writes; a CHECK allows only those four ids to be built in and never deleted (so a database emptied and loaded
again, a test run's rollback or a restored dump, gets them back). Copy a built-in to change it (the copy keeps its measure).
`monitor_card_assignments`: which template a unit's card gets, a rule for one unit, system, system type (hatchery and nursery
reachable here), species or unit kind, or with none the global rule (migration 0002 makes it: every unit gets Simple). One
scope per rule and one live rule per scope (NULLs equal, so one global) are a CHECK and a partial unique index. A rule of a
deleted unit, system or species stays and counts again on restore; deleting a template deletes its rules, detaches the
boards' defaults and the templates that flip to it (each logged); a built-in and the template of the global rule cannot be
deleted, nor the global rule. A board gets its default template and a card width (compact, automatic, comfortable); a
board's card row its own template. Migration 0004 copies each board's default mode and each row's mode into the built-in
templates; back, a built-in maps to its mode again. The mode columns stay for one release, so a rollback loses nothing.

**Which template a card gets** (`monitoring/cards/resolve.py`), first hit wins: the screen's view (`mode=small`: every card
of the screen as Small, on a board or not; the address's, never stored), the board's row for the unit, a rule for the
unit, for its system, for its system's type, for the species of its fish (an empty unit has none and falls through), for
its kind, the board's default (no board: the page's `mode=simple|detailed`, the built-ins), the global rule, and with no rule
at all Simple from the code. `?flip=` shows a card's flip target and its link goes back. Only live templates and live rules
of live units, systems and species count; a rule of something deleted counts again when it is restored. A stored layout the
validator refuses (a hand edit) never blanks a card: it is drawn with the built-in Detailed layout from the code and the error
is logged once per template per process. The live templates and rules are two queries, whatever the number of units.

**What the read reads** (`monitoring/read.py`): `SOURCES` is the one table of the card's sources, each with the right that reads
it and whether the card can be drawn without it (it replaced `PERMISSIONS`). `needs` is the union of the sources of every
widget of the shown cards' templates, plus the roll-up's set (fish, feeding, the middle point's water, open events) for every
card, so the state never depends on the template: a card with no water widget is still critical. A source no shown widget
needs runs no query (every active point's water and the feeding week only for the cards that show them). An optional source
(treatments, lice counts, tasks, placement chips) that fails is read in its own savepoint, its widgets say so, and it is logged
at most once a minute; a required one that fails answers **503** (the page and the fragment), so a polling screen backs off
and keeps its last picture with its stale notice. The two template queries are the only reads card templates add: 33
reads simple, 40 detailed and mixed at 6, 24 and 200 units (the recording's 31 and 38 reads, plus the two; the recording
also counted 4 savepoint statements, the chips' and the placement registry's own), and each optional source now has a
savepoint of its own: 4 savepoint statements simple, 10 detailed (`RecordedCountsTests`).
The unit's **chart** is one more source (`chart`, optional, worked out from the water's answer and read only for a person
who may read the water): `water.calculation.charts_of` for the cards whose template shows it (the pH window, a value bound
to the calculated CO₂) and for no other card, from the water the card read already holds (no sample and no sampling point
is read again) and ONE read of the fish and their limits for all those cards (`water.read.limits_of`). A wall of Small
cards costs 43 reads at 6, 24 and 200 units (42 measured 2026-11-13, three more than Simple's 39; one more since
2026-11-17, the pH window's scales, read once for the wall), a wall of Big cards 43 too (measured 2026-11-17: Small's
42 without the scales, and every active point's water for the card's other points), and the pane of a unit gone into
is one Big card's read; all pinned in `RecordedCountsTests`. A Big card weighs up to 30,500 bytes in the page (real
Turkish cards on a copy of the development data, 2026-11-17: 19,272 to 29,120 bytes; a wall of 20 is about 0.6 MB
before compression), a Small one up to 6,800. A chart that cannot be read leaves the cards: "Could not be read: Deffeyes chart" on the frame and "no data"
in its widgets.

**How a card is drawn** (`monitoring/cards/render.py`, `templates/monitoring/_card.html`, `templates/monitoring/widgets/`). The
frame (the unit and its link, the state word, shape and reasons, the withdrawal, the flip link named after the template it
shows, "Empty", what the state is from) is not data and no template can remove it. Below it `div.card-grid`: one
`div.w.w-<type>` per widget with the classes of its cell (`gx-<x> gy-<y> gw-<w> gh-<h>`, never a style attribute, which the
Content-Security-Policy blocks; `static/css/card-grid.css`, made from the catalogue by `manage.py card_grid_css`, whose `--check`
and a test fail when it is stale, turns them into `--x --y --w --h`), placed by plain CSS grid on 12 columns (`static/css/monitor.css`; a row at
least `--row` 1.75 rem high, growing with its content) and, below 30 rem of card, one column in the same order; the wall runs no
layout script. `build(card)` (no query) gives the widgets in reading order (y, then x), so what is read, what Tab visits and
what is seen agree; a unit with no fish shows only the experiments and the Deffeyes button; a widget whose sources the person
may not read says "Feeding: not shown to you" (the Deffeyes button is left out); a widget whose optional source failed says
"no data". A focusable element of a widget is `w-<unit>-<widget id>` (poll.ts restores the focus by id). `face(reading, now)`
is the one way a single value is said: the figure at the parameter's precision, its status in words, where it came from
(the sample's source) and its age in bands ("just now", "40 s ago", "12 min ago", "3 h ago", "2 d ago", so a card changes
once per band, not per poll), "old" past the parameter's freshness, and "no data" rather than a dash; a value the fish have a
limit for that the chemistry core refused to work out says "Cannot be evaluated" (with no figure) or keeps its safe-side
basis figure, drawn in the warning's shape and tone (`alert_of`, as the water page's chip), its reason in the note and in the
card's state; what was measured where a value is stored converted (a pH on another scale than NBS, a phosphate as PO₄, a
basis-only NH₃: `Reading.measured`) stands visibly beside the source; a worked-out value's note says the formula and ionic
strength it was worked out by (`Reading.provenance`, `Analysis.provenance`); the calculated CO₂'s figure is the core's
judged one (formula 4's safe side), its best estimate is on the unit's chart page and the calculator, not on the card
(its weight is bounded). The water table keeps the
water page's own value markup and adds the origin and age under each value. A bar is the value against the four bounds of
the limit that judged it, an SVG with `role="img"` named by the same sentence, its bands told apart by dash pattern as well as
tone (no `<meter>`: browser colours, three cut points); without a limit it says so. A board's card width sets `--card-min`
(17, 21 or 28 rem, 15 % more on a wall). The old per-section partials are gone: the built-ins Simple and Detailed draw what
they drew, value for value (`test_golden`).
A FITTED card (a template with a measure, `Resolved.measure`) has the same frame on two lines
(`templates/monitoring/_card_fit.html`) and its widgets in equal rows that share the card's height; it is drawn with
`tw:` utilities (as `/production/` is), the page's own sheets loading before `tw.css` (`app_base.html` block
`page_styles`), and `static/css/monitor.css` holds only what a utility cannot say: the card's unit, the wall's cells and
the pH window's marks. Of the widgets, the value (`widgets/_value_fit.html`, `render.tile`) and the pH window have a
fitted look; the others keep their flowing markup, so a fitted template of one's own should hold those two until the Big
card brings the rest.

**Setup › Reference data › Card templates** (`/card-templates/`) and **Card template rules** (`/card-template-rules/`), tabs on
`core.crud` (`monitoring/resources.py`). A template's form has a General tab (name, description, the template its flip link
shows) and a Design tab (the layout, checked by the validator; each refusal names its widget, nothing is stored); the
version guards two designers (the second is told). The list shows the built-ins first with a mark, and how many rules,
boards and board cards use each; a built-in opens read-only (saving it is refused, as by the database) and **Copy** makes an
editable one ("Simple (copy)", "(copy 2)" …), with the add right. The activity log says the layout as one English line per
widget ("w1 value 3x2 at 0,0 binds oxygen_mg_l"). Deleting one lists the rules that go with it and the boards and templates
that lose their pointer; restoring brings back the template only. A rule's form is a template and at most one of unit,
system, system type, species, kind (none: every unit); the list is in the ladder's order, the global rule last, which
cannot be deleted or narrowed. Role matrix areas **Card templates** and **Card template rules** (after Handling rules);
reading Monitoring needs neither, and a reader of cards without them cannot open the designer. A template saved writes an
activity-log entry, so every wall's change token moves. The designer's **preview** (`POST /card-templates/preview/`, JSON `{layout,
unit, name, state}`, the change right, at most 64 KB) checks the layout first (an error draws nothing and is listed), then
draws the same card the wall would for that one unit with the previewer's own rights, marked `data-preview`; it writes and
logs nothing, and `state` (a forced state for a look at it) is accepted there only.

**The frame says more** (owner decision 4: a unit in maintenance, cleaning or quarantine rolls up as before): the unit's status
when it is not active ("Maintenance"), the withdrawal as a note chip (it lasts weeks; not an alarm), a dashed line when the
stored template cannot be drawn ("Template error: … this card is shown as Detailed"), and under the basis which template
draws the card and why ("Template: Simple · the rule for every unit"). **Colours** are checked against the token table by
`monitoring/tests/test_frame.py`: text that says something at least 4.5:1 on white (the warning amber is #7A5410), a border or a
dot that carries meaning at least 3:1 (the water page's warning dot moved from #C58A16, 2.99:1, to the text's amber), the pale
sage never carries meaning (a note card's border is the muted green, an empty one's dotted); `@media (forced-colors: active)`
keeps the shapes, the bands of a bar and the state borders in high-contrast mode (and the pH window's regions and mark).
The fitted card, the band and the pH window use three inks on three grounds and a colour only for a state; every pair of
text and ground they use is at least 4.5:1 in all six themes (`test_frame.py`: the inks on the sheet and the canvas, the
state's text on the sheet and on its tint, a border's number on the grey region, the safe stretch and the critical tint).

**Measured with templates** (2026-11-05, `monitoring/tests/test_load.py`, run with `MONITOR_LOAD=1`; the test database on this
development machine, the test client): a wall of 200 cards drawn with a 12-widget template (four values, a bar, every
figure of the fish, the feeding week, every point's water, health, tasks, the Deffeyes button) costs 67 queries, 3.4 s and
1,512 KB for the page, 62 queries, 3.1 s and 1,477 KB for the fragment (about 7.5 KB a card: each value now says its
origin and age), and the unchanged poll 7 queries in 0.03 s. Decision: no card cache, no widget hash or patch protocol and
no gzip in Django now. The queries stay flat with the units and the 204 path answers every unchanged poll, so a wall pays
the 3 s at most once a minute (the token's bucket) or after a change; gzip belongs to the web server in front (compressing
pages with a CSRF token in Django invites BREACH), and a cache or a patch protocol waits for a measured miss on the wall's
own hardware (the live check of the plan: 20 polls, 30 % of the cards changing, long tasks, a 24 h memory soak).

**Measured with the Small card** (2026-11-15, the same check, `test_a_wall_of_200_small_cards`; the machine was running
two other suites, so the seconds are an upper figure and not a comparison with the 3.4 s above): a wall of 200 Small
cards, each with its four values, the calculated CO₂ and the pH window from the unit's chart, costs 69 queries, 11.7 s
and 1,222 KB for the page, 62 queries, 11.3 s and 1,184 KB for the fragment (about 6 KB a card). The reads stay flat with
the units (42 at 6, 24 and 200 units, `test_budget.py`): the chart adds one read of the fish's limits for the whole wall
and the chemistry core once for each unit. The same day the 12-widget wall costs 81 queries for the page and 74 for the
fragment, on this work and on the commit it started from alike (the same statements, compared one by one): one above
that check's bound of 80. The growth since 2026-11-05 came with what landed in between, not with the Small card; the
bound is not raised here.

**The Big card** (`mode=big`, the built-in Big template, migration 0006; owner decisions 4, 10, 11, 12): the card of
one tank read from across the room, fitted (48 × 61 units, 21 rows) and FULL-HEIGHT: a card higher than it is wide
keeps a whole row of the wall (`monitoring/cards/slots.py` `FILL`: at least 0.97 of the unit one card alone would
have), so 3440×1440 shows three, 5120×1440 four, and more turn pages. Its four first values are large, each with its
strip against the limit row and under it where it came from and how old it is; the unit's Deffeyes chart takes eleven
of the 21 rows, drawn by the server as a picture of the card's own size (`farm/water/deffeyes.py` `card_figure`,
`picture`: no viewBox outside, a stretched plot inside, labels by percentage, no style attribute) in one of two views:
CLOSE, the window `close_window(figure, band, target_active)` works out (the water, the active target and where each
limit's border crosses the water's alkalinity are the middle half of it; never narrower than 0.5 mmol/L; a window of
four fifths of the core's box IS the box; held to the mock-up's own rule on 26 waters in
`farm/tests/close_vectors.json` and to its promises on 2,000 made-up ones), and FULL, the core's box, ONE box for the
charts of one water type on the screen (the core's `extent`, `monitoring/read.py` `chart_extents`). `?chart=full` sets
the screen, `?zoom=<unit>,…` the cards that differ; both are in `Params.canonical()`, so the poll answers the same
view. The picture says its view and its magnification, what the farm has not set (no NH₃ limit, no CO₂ limit, no
alkalinity band: a side that is not drawn never reads as safe), "last known position" when an input is old, and under
it where the water is, said from the picture itself (the safe zone only when the water lies in the region the core
drew). Then every value of the middle point, a row each (figure, strip, source in words, arrival as clock time or day
and month, with its age: never cut), every reason in full under the head, the other sampling points, the stock, and the
dosing box, which in this phase says "No dosing advice" and why. The dev copy's real waters come out at ×5 to ×12 in
the close view; ×12 is the smallest window, where a water lies within 0.06 mmol/L of its only border.

**Characterised before card templates** (2026-11-04): `monitoring/tests/test_golden.py` renders a fixed farm of twenty units in
every state (critical, warning, no recent data, note, OK, empty; over capacity, a withdrawal, tasks, a lice count, a treatment,
an event, the saturation instead of mg/L) on eight screens (simple, detailed, all units, flipped, a board's mixed modes, the
fragment, and two people who may not read every section) and compares what each card says with `golden_cards.json`
(`monitoring/tests/golden.py`: the state word, the reasons, every labelled figure, the links, and every text and title, which a
card may add to but never lose; ids, dates and ages normalised). The card read's queries were recorded at 6, 24 and 200 units:
35 simple, 42 detailed, 42 mixed, equal at every size (`RecordedCountsTests`).

### Operations › Feeding: Meal board, Records, Protocols and Assignments

The Feeding group of Operations has four pages: the **Meal board** (`/operations/feeding/board/`), **Records**
(`/operations/feeding/`, the feeding records below and, by unit and day, the calculated ration against the feed
given), **Protocols** (`/operations/feeding/protocols/`, the feeding tables) and **Assignments**
(`/operations/feeding/assignments/`, which protocol feeds which fish from which day). Only protocols and
assignments are stored; every ration, estimate and deviation is computed on read, so none can drift
(`farm/feeding/ration.py`, `projection.py`, `temperature.py`). Owner decisions Q1–Q9 are in the bug document
(Feeding protocols and meal board).

**A protocol** (table `feeding_protocols`) is a feeding table for one species: weight bands
(`feeding_protocol_bands`), each from its lower weight up to, not including, its upper one (only the last may be
open), with its feed (the pellet is the feed's), its meals a day (1–48) and optionally its expected FCR, and per band
the SFR, % of the body weight a day (0–15; 0 is "do not feed at this temperature"), at each temperature column
(`feeding_protocol_rates`, −3 to 40 °C). The protocol's own expected FCR (0.50–3.00) is the fallback of a band without
one, always shown with its source. The bands meet without gaps (checked when the table is saved) and never overlap
(an exclusion constraint, `btree_gist`, created by migration 0015); every cell is filled (the grid is saved whole).
The dialog has a General tab (name, unique among live protocols in any case; species; status; expected FCR;
notes), the **Feeding table** tab, a grid of the bands by the temperature columns: the columns are typed as
"4 8 12 16", **at least two** (one column gave an SFR at exactly its own temperature and none on every other day, audit
F-080; a table stored with one keeps that), and changing them renders the grid again with what was entered (`data-refresh`, nothing saved); the
whole table is saved at once, replacing the stored bands and cells, guarded by the protocol's version and logged on
the protocol as one change ("Feeding table", before and after). A band whose feed is not listed as suitable for the
species at its weights is noticed, not refused. Status: a new protocol is a draft; it is set active once it has a
table; a retired one keeps the days it fed and takes no new assignment, and it cannot be retired while an
assignment covers today or later. **Once a protocol is assigned its table, species and expected FCR are fixed**
(owner decision Q3): the rations of past days are read from it; **Duplicate** makes a draft copy ("… (copy)") with
its table, to change and assign from a date.

**An assignment** (table `protocol_assignments`) is one row per target: a unit (the protocol feeds whatever is in
it), a whole batch (it follows the batch into every unit it is moved to, through transfers and splits) or a batch in
one unit, from a day and optionally until a day (both included). The dialog offers the three as units and a batch to
choose: units alone, a batch alone, or a batch and units; it writes a row per unit with one `group_id`, each logged
(`farm/feeding/assignments.py`: the rows and their write path, which an experiment's start uses too, so its rows are the
ones the dialog writes), and says when a batch has not been in a chosen unit yet (a planned move is allowed). The database keeps one row in
force per unit, per batch and per batch in a unit on any day (three exclusion constraints among live rows; the form
checks them by the constraint itself and says which unit clashes). For a batch in a unit on a day the most specific
row wins: batch in unit, then unit, then whole batch (owner decision Q8); a unit's row for another species is read
past with its reason. Only active protocols are assigned, a batch only with its species; a first day may be at most
the correction window back (Platform settings). Before its first day a row may change or be deleted; from then on only its last day
(yesterday at the earliest) and notes change, and it is ended, not deleted: the days it fed keep their protocol.
The list groups the rows of one dialog, filters by site, unit, batch, protocol and in force / starting later /
ended, and counts the fish each row feeds today after the more specific rows.

**The ration** of a batch in a unit on a day (`farm/feeding/ration.py`): the protocol by the rule above; the band
by the fish's **estimated** average (owner decision Q7); the **temperature** of the unit, else of its system's loop,
then of the systems that system is nested in (`farm/feeding/temperature.py`, the water samples' series of
`farm/water/read.py`, picked by A9's `read.choose`): the unit's own fresh value wins (its own-water points), else
the nearest system's fresh value (its loop, or its own sensors when it has no loop point), else the newest stale one;
fresh is the temperature parameter's 24 h. **However old, the newest temperature gives the ration** (owner amendment
A11, 2026-11-08, the one explicit exception to A9.3; it replaced decision Q5's 7-day cut-off; with nothing fresh, the
MOST RECENTLY entered temperature across every tier, so a 2-day-old loop value beats an 8-day-old own one): a stale one
says so on
the meal board, "Based on the temperature from 03.11.2026 07:40 (5 days old)"; only a unit where no temperature was ever
recorded has no ration ("No temperature recorded here yet: record one."); the moment is now for today and the end of the day for a past day.
The sensors are read at every moment a walk may ask (each feeding day and each day asked, on its unit's clock, that a
protocol assignment covers: a day no row covers asks no temperature) in ONE ask before the walk (`Series.prefetch`,
`sources.values_at`: the bindings, then one statement with a LATERAL lookup per binding and moment on the hypertable's
key), never once per day and once per channel (2026-11-22: a wall's walk had made 179 reads of the bindings and the
hypertable; `farm.tests.test_protocols.SensorRationTemperatureTests` holds one ask and the same bases, day by day, as
main's way of asking each day on its own). One failing ask fails every moment of it together (the answer is the same
fail-open one, samples only, and the log says so); those moments are then asked one by one, as before, so a failure
costs only the moments it hits. Nothing of it is kept after the request. The SFR is
the band's cell at that temperature, **interpolated linearly between two columns and never extrapolated** (owner
decision Q1): outside the first and last column, or a fish outside the bands, there is no ration and the page says
why; never a default temperature or rate. The day's ration R = estimated biomass × SFR / 100, a meal R ÷ the band's
meals a day, at full precision (rounded only for display).

**The estimated weight** (`farm/feeding/projection.py`, kept by the feeding walk itself, `farm/feeding/fold.py`, never
written back: bFCR, eFCR, density, capacity and the 10 % acknowledgement read the measured book only). It restarts at
the measured value at every stocking, weighing (a grading's remainder too) and fish graded in. Fish that leave take
the estimate's own average; fish moved by a plain transfer carry their estimated grams and the day of their last
measured point; graded fish carry their measured weight. **After each feeding** (in the day's order: its time, then
the order of entry) the batch gains its part of the feed (the record's split by book biomass) × 1000 ÷ the expected
FCR at its estimated weight then, and the next meal is worked out again from the new estimate (owner decision Q9),
but growth is credited only up to the day's calculated ration (Q4): feed above it is shown as "over the ration" and
not counted. Feed of fish without an expected FCR (no protocol, outside the bands) adds nothing and the estimate says
"incomplete: N feeding days without an expected FCR". A day without a temperature has no ration to cap with, so its
feed is credited as given. The estimate is marked "weigh soon" after `WEIGH_SOON_DAYS` (14) since its measured point
and "weigh now: the estimate is unreliable" after `WEIGH_NOW_DAYS` (28) (owner decision Q6).

**The day's calculated ration** (Records) follows the same rule: each recorded meal counts R ÷ M at the estimate just
before it (a record's meals, or one when it does not say, counted up to the band's M meals a day), and the meals
still to come count R ÷ M at the current estimate; **the next meal** is R ÷ M at the current estimate, **remaining**
the meals still to come at it. It is computed on read (owner decision Q2): a change of the stock, a record or a
water sample computes it again; the table itself does not change once assigned.

**A weighing is a correction point**: just before it restarts the estimate, the walk keeps the estimated and the
measured average, the difference (g, %, and kg over the fish), the days since the previous measured point, the
realised bFCR between that point and this one (the FCR window rule) and the expected FCR of the feed given meanwhile
(Σ feed ÷ Σ feed ÷ FCR). The weighing dialog shows it before saving ("Estimated 97.5 g on 2 Nov (15 days since the
last measured weight); you entered 94.0 g: −3.5 g, −3.6 %"), rendered again when the batch, the date or the weight
changes; the drawer shows it next to the weighing in its operations, and Records next to the day.

**The Meal board** lists today, on each site's clock, the units with fish (filters site, production department,
system), a line per batch: fish and estimated biomass, the estimated and the measured average (weighed when, drift
mark), the temperature with its age and whether it is the unit's or a loop's (Record water sample), the protocol and
which row applied ("via unit T-01", "via batch B-2026-001", "via B-2026-001 in T-01"), the band, feed and pellet,
the expected FCR, the SFR (the two cells read, in its title), the ration and meals × kg, fed today, remaining and the
next meal; a unit without a ration says why in the row. Cleaner fish beside production fish without a feeding table
of their own (no protocol row applies to them: they eat what the salmon leave, their own feed block and the lice) are
no fault (cleaner fish alone in a unit, a hatchery's tank of lumpfish, are its production fish: no table is a gap, said
as for any fish): their
line is marked **Cleaner fish**, with their fish and weight, and has no ration, no "No protocol is assigned" and no
"Estimate incomplete" for their feedings (their estimate stays the measured weight); the drawer, Records' days view and
the monitoring card say the same. A protocol of their own (their batch's row, or a unit's row of their species) gives
them a ration on their own line, never in the production fish's figures or the next meal (D-1). **Record meal** opens the existing feeding dialog with today,
now on the site's clock, the band's feed, the next meal's kilos and one meal, posts the existing feeding record path
unchanged (`farm.feeding.services.record_feeding`) and comes back to the board. No new column on `feeding_records`.
The unit's drawer on Production units has the same per batch under Feeding (Today's ration).

**Records** has two views: the feeding records (the list below) and **By unit and day** (`?view=days`; site, unit,
batch, from and to, the last 7 days by default, at most 31 a page): per unit and day the batches with their estimated
weight and the basis of the ration (protocol, SFR at the temperature, meals) or why there is none, the calculated
ration, the feed given to the production fish, the deviation (given − calculated, kg and %), and the weighings' correction
lines; the feed given to the cleaner fish is not in that sum or the deviation, it has a line of its own under it.

**Who may do what:** Feeding records (Read = Meal board and Records, Create = record a feeding or a meal, Delete =
void one), Feeding protocols and Protocol assignments (read, create, edit, delete) in the role matrix (Production ·
Operations · Feeding). A feed in a live protocol's table is not deleted (its `PROTECT`, said by `Feed.delete_blockers`
since a band is a plain row of its protocol); a species with a protocol is not deleted (`PROTECT`); a protocol with
assignments is not deleted (`PROTECT`: end and keep them, or delete those not started); an empty unit can be deleted
and a voided batch stays voided, and both keep their assignment rows (`DO_NOTHING`, as their feeding records): they
come back with a restored unit, and the list marks them.

Not in the MVP (feeding-protocols §6.12): **over- and underfeeding alarms**, postponed by the owner; the proposal is
ready: per day a deviation within ±10 % is noise (hand weighing and feeder calibration ±5–10 %, appetite ±10–15 % in
salmonids), ±10–20 % a warning, beyond ±20 % critical, and underfeeding below −20 % on two days running critical
(appetite loss is an early sign of disease, low oxygen or a temperature drop); per meal ±20 % a warning, ±35 %
critical; judged only after the day's last meal or once a meal's time has passed; shown on the board, Records and
Production units, nobody notified. Also later: sensors as temperature sources, an oxygen gate before a meal, meal
times and feeding windows, fasting and medication calendars, catch-up of missed meals, stored day plans and pours,
hysteresis and manual band pins, rate adjustments and FCR overrides per assignment, a learned FCR from the realised
intervals, forecasts and the production plan.

**Read for many units.** `feeding.read.figures(stock, details=(), ration=False)` answers for any number of units in one walk of
the projected weight: for each unit of `details` its last 7 days (`weeks`: two queries for all of them, the records of the days
and the feed in use), today's ration and the corrections of its weighings; with `ration`, today's ration of every unit with fish.
The drawer, the meal board and the monitoring cards all read it. The meal board's per-batch lines and the weigh soon or now
drift live in `feeding.read` (`meal_lines`, `drift`), and the board and the cards print the same lines. A person who may not read
the feeding records is not given the figures (`feeding.views.unit_figures`).

### Operations › Feeding › Records: the feeding records (`/operations/feeding/`)

Table `feeding_records`: feed given to one unit on one day, the farm's daily feeding record. A record is
the unit, the day, the feed (an active feed of Reference data › Feeds) and the kilos given, to the gram,
and optionally the time, the number of meals, the feeder and notes; several a day are fine (meals, a feed
change mid-day). **No batch is stored**: the batches a record fed are the batches the stock ledger has in
the unit that day, the feed split between them by their book biomass at the start of the day (at its
end when the unit was empty that morning, the day it was stocked). A record is for the unit's production
fish or for the cleaner fish beside them (its **target**, stored): the feed is split among the batches of
its target only, so salmon feed is never booked to lumpfish. A backdated stock operation therefore
never leaves a stored batch wrong, and nothing is written back into the stock: feed never changes a count
or a gram of the book (only measured weights enter it).

**Recording.** "Record feeding", the first and primary button of a stocked unit's drawer on Production
units, or **Record feeding** on the list (it lists the units with fish). The dialog has the date (the
farm's today), the feed (the active feeds; those whose suitability rows suit the fish's species and
average weight first, the others under "Other active feeds": choosing one of those is allowed and
noticed), the kilos (`0.035` for 35 g), meals, time, feeder (a feeder of the unit's site) and notes; in a unit
that holds cleaner fish also **Fed to** (production fish, cleaner fish, or "as the feed suits": the cleaner
fish's when the feed suits only them or the unit has no production fish). A unit with two batches of the
target says how the feed is split ("Split by the book biomass at the start of 2 Nov:
B-2026-001 71 %, B-2026-004 29 %"). The rules, in one write path (`farm/feeding/services.py`), each with
the server's reason on its field:

- the date as for the stock: the farm's today at the latest, at most the correction window (Platform settings) back;
- the unit must hold fish of the target at the start or the end of that day (from the stock ledger; the
  reason is on the target when the unit holds the other kind); and the other way round, a stock operation (a backdated harvest or transfer, the void of the stocking that brought the
  fish) is refused while a recorded feeding would be left without fish, naming it;
- a new record takes an active feed; a record keeps its feed whatever the feed's status becomes;
- above `FEEDING_ACK_PERCENT` (10 %) of the book biomass of the target's fish in a day (the day's feedings of the target in
  the unit, this one included: two feedings of 6 % are 12 %, audit F-081), the person is asked to confirm,
  and the confirmation is stored on the record (a kilo typed for a gram is caught; fry may be fed more);
- a form sent twice records once; the unit is locked as a stock operation locks it, so a feeding and a
  harvest of one unit take turns.

**Void** is the undo, the stock's own (one rule for both, `farm.stock.services.voided`): a reason, within
the backdating window, the record stays struck through with its reason, "Voided" in the activity log. A
correction is a void and a new record; nothing is edited.

**The list**: filters in the address, site, unit, batch (the records whose split fed it), feed, from and
to dates, and "Show voided"; 50 a page, newest first (a record without a time after those of its day with
one, then the order of entry, so pages never repeat or skip a row); the count line ("128 records · 3.4
t", voided ones not in the total); per record the date and time, the unit with its department and site,
the batches it fed, the feed with its pellet size, the kilos, meals, feeder, who recorded it and when,
notes, and **Void** while allowed.

**The figures**, computed on read from the stock ledger and the live records, nothing stored
(`farm/feeding/read.py`; the walk is `farm/feeding/fold.py`, one pass over the stock fold):

- **Last fed**: the latest day of a record in the current stay of the unit's fish (Today, Yesterday or
  the date).
- **bFCR** (biological) = feed / biological gain, **eFCR** (economic) = feed / economic gain, over a
  window from the first measured point of the fish's stay in the unit (their stocking, or fish graded in)
  to its last weighing; the feed of the days from its start up to the weighing's day (the fish are weighed
  before the day's feeding); biological gain = biomass at the weighing − biomass at the start + biomass
  removed meanwhile (dead fish at their weighed kilos when weighed, a harvest at its weighed kilos, the
  rest at the book's average) − biomass added; economic gain leaves out the fish lost (dead, culled,
  escaped, unaccounted). eFCR ≥ bFCR. Per unit: Σ feed / Σ gain over its batches that have a window. A
  dash when the fish were not weighed since they came in, no feed was recorded or there was no growth
  (the dash's title says which). Fish moved in by a plain transfer arrive at book weight, so they start a
  window only at their first weighing. Known bias, said in the drawer: dead fish leave at the last
  weighed average, so their growth since is not credited (bFCR a little high when many die).
- **A bounded window** (`read.window(stay, first, last)`, `read.windows_in(unit_ids, first, last)`): the same window
  with its ends put on the measured points of two given days (the last point of each day: the state at its end),
  for a period that is not the whole stay (an experiment's days). A day without a measured point gives no window,
  never an interpolated one, and a window must start before it ends; a bound left out is the stay's own end.
  `measured_on(unit_ids, day)` says which batches have a measured point on a day (where a window can start or end).
  `windows_in` walks the units' feeding once from the first day on and gives `{(unit, batch): window}` for the
  units asked (a batch that came into a unit more than once has the window of its latest stay that has one); an
  FCR over several windows is `Conversion` of them, ratio of sums, the formula of this page.
- In the drawer: fed today (kilos, meals), the last 7 days' kilos and the **feed rate** (SFR, % of the
  biomass a day = 100 × feed / the sum of the book biomass of the days with fish; the book does not grow
  between weighings, so it reads high as the last weighing ages, and the drawer says how old it is), the
  feed in use, each batch's window ("1 Oct – 15 Oct, 168 kg fed, 196 kg grown") and its last 10 records.
- The production overview: feed today and over the last 7 days on the whole farm, **each site on its own day** (the
  owner's decision of 12.11.2026: everything is shown on the site's own day, by the site's own clock). Feed recorded
  on a site's today is in "Feed today" at once, whatever the company's clock says; the 7 days are each site's own last
  7; a figure over sites on different clocks is the sum of each site's own day, and on a farm of more than one clock
  both cards say "Each site on its own day". The filter is `farm.clocks.own_days`, beside the clocks the tasks read.
  Each card opens the feeding records from the earliest to the latest of those days among the sites, so in the hours
  when two sites are on different days that list holds one day more of one site than the figure
  (`farm.tests.test_feeding.OverviewFeedOnSeveralClocksTests`). A unit whose department has no site (a row a deleted
  site left) counts on the company's day, as everywhere. The query reads only the records of the days some clock
  counts, never the whole table (`FourClocks*Tests`: four clocks, a site ahead, a site behind, the two nights the
  clocks change).
- **What still reads the company's day over sites of several clocks** (found while the two figures above were
  changed; none changed here). The owner decided on 12.11.2026 that the first three go to the site's own day on a
  branch of their own: Feeding › Records › By unit and day (its last day and its default seven days,
  `farm/feeding/views.py` `_by_day`); the water history's date filter; the default date of a form opened without a
  unit (a harvest, a feeding protocol's first day). Not decided: the feeding protocols' "in force today" count and
  filter and the check that refuses to retire a protocol assigned "for today or later"
  (`farm/resources/feeding_protocol.py`, `farm/models/feeding_protocol.py`); HR's head counts, organisation chart,
  the attendance list's default days, the roster's default week and who is in a person's scope today (`hr/read.py`,
  `hr/resources/attendance.py`, `hr/resources/roster.py`, `hr/scope.py`). The reports' deadlines read Oslo's day on
  purpose: they are the authority's.

**Who may do what:** the area Feeding records in the role matrix (Production · Operations · Feeding): Read
the Meal board, Records and the feeding part of a unit's drawer, Create records a feeding or a meal, Delete voids
one. A feed or a feeder
with live records cannot be deleted (`PROTECT`: set the feed to discontinued, the feeder to
decommissioned); an empty unit with feeding records can be, as with its stock history (owner decision
Q-F3), and its records stay with it (`DO_NOTHING`, see the delete plan). `manage.py check_stock` reports a
feeding without fish. The admin shows voided records and does not restore them.

Differences from the source (details in the bug document, FDR-01 to FDR-41):

- The unit is the record's anchor and is required; the source's web dialog had no unit input, so its
  manual records had none (FDR-07, FDR-34). No batch column: the source booked feed on whatever batch it
  was told, or on a unit's "primary" batch, while it spread the growth over all of them (FDR-05, FDR-06).
- Feed is never written into the stock; the source added feed / expected FCR to the biomass, so its unit
  FCR met the target by construction and its rations fed the projection (FDR-19, FDR-21).
- One FCR definition, on measured weights only, biological and economic; the source had three formulas
  that disagreed, none economic (FDR-22, FDR-23, FDR-32). Last fed and the feed rate are computed from the
  records (FDR-24, FDR-31).
- Recording never depends on the feed store (FDR-08); records are kept, no 800-day retention (FDR-18);
  one date rule, farm-local (FDR-20, FDR-36); void with reason instead of a partial edit (FDR-13, FDR-30,
  FDR-37); who recorded is the person signed in (FDR-11); amounts recorded to the gram and shown to the gram
  under a kilogram, with at most two decimals from a kilogram (FDR-35, FDR-40; Shared page parts).
- Not ported: planned amounts and variance stored on a record (the ration is computed on read, see the Meal
  board and Records above), waste, cost and currency, method, environment, behaviour, duration, verified-by,
  stored day plans and meal rows, feed stock (lots, deductions), the feeder's shots and calibrations (the feeder
  is recorded, the kilos are typed), the batch page's FCR, SGR and alerts.

### Operations › Water chemistry (`/operations/water/`) and Reference data › Water limits (`/water-limits/`)

The water samples people take, each at a **sampling point** (a place on a unit, on a system's loop or on a piece
of equipment, next section), and the limits the owner sets per species. Tables `water_measurements` (a
TimescaleDB hypertable) and `water_limits`; the points are `water_sampling_points`.

**The parameters** are a fixed list in code (`farm/water/parameters.py`), each with one unit and one
basis in its label and its column's name, so a value can never be relabelled into another unit and
nitrogen is always recorded as N (owner decision 3; the help of each field gives the kit conversions,
NO₂⁻ ÷ 3.28, NO₃⁻ ÷ 4.43, NH₄⁺ ÷ 1.29, NH₃ ÷ 1.22: each the ion's molar mass over nitrogen's; 46.0055 / 14.0067 =
3.2845 for nitrite, which said 3.29 until the water-chemistry audit of 2026-11-19, F7). Each has a plausible range, which catches a typing slip and is a
database check (the ranges are argued in the bug document), its precision and how long a value is fresh. The
hardness and the conductivity compensated to 25 °C are the fresh water's ionic-strength inputs of the chemistry (formula 3,
Water-chemistry core); a conductivity at the water's own temperature is the sensors' process quantity `conductivity_us_cm`
and the chemistry never reads it (cross review F8: a meter's temperature compensation on, referred to 25 °C). A limit's
bounds hold 10 digits, 4 of them decimals, so a conductivity's limit fits:

| Column | Label | Decimals | Plausible | Fresh |
|---|---|---|---|---|
| `temperature_c` | Temperature (°C) | 1 | −3 … 40 | 24 h |
| `oxygen_mg_l` | Dissolved oxygen (mg/L O₂) | 2 | 0 … 50 | 24 h |
| `oxygen_saturation_pct` | Oxygen saturation (% of air saturation) | 1 | 0 … 400 | 24 h |
| `ph` | pH (NBS scale) | 2 | 2 … 12 | 72 h |
| `alkalinity_mg_l` | Alkalinity (mg/L as CaCO₃) | 0 | 0 … 1000 | 14 days |
| `hardness_mg_l` | Total hardness (mg/L as CaCO₃) | 0 | 0 … 10000 | 14 days |
| `co2_mg_l` | Carbon dioxide (mg/L free CO₂) | 1 | 0 … 200 | 72 h |
| `tan_mg_l` | Total ammonia nitrogen (mg/L TAN as N) | 3 | 0 … 100 | 7 days |
| `nitrite_n_mg_l` | Nitrite (mg/L NO₂ as N) | 3 | 0 … 100 | 7 days |
| `nitrate_n_mg_l` | Nitrate (mg/L NO₃ as N) | 1 | 0 … 1000 | 14 days |
| `tgp_pct` | Total gas pressure (% of barometric pressure) | 1 | 50 … 200 | 7 days |
| `salinity_ppt` | Salinity (‰, g/kg) | 1 | 0 … 50 | 7 days |
| `conductivity_25_us_cm` | Conductivity at 25 °C (µS/cm, temperature-compensated) | 0 | 0 … 100000 | 7 days |
| `turbidity_ntu` | Turbidity (NTU) | 1 | 0 … 4000 | 7 days |

**A sample** is one row: what a person measured at one point at one moment, a typed column per
parameter, empty when not measured, at least one value (a database check). The point is one sampling point
(`point`, a required foreign key; the table has no unit or system column: the unit, loop or equipment is the
point's owner, so the two cannot disagree). The time is on the clock of the point's site, never in the
future and at most the correction window back (Platform settings, `farm/stock/dates.py`), the rule of every daily
record; the source is a meter or kit, or a laboratory; the person is the one signed in. A form sent twice
records once (its key, stored with the time). Samples are never edited: **Void** (with a reason, logged as
"Voided" like a stock operation) and a new entry correct one; a voided sample stays in the history, struck
through. The only writer is `farm/water/services.py`, which also refuses a point that is inactive, deleted or on a
deleted owner.

**The hypertable.** `water_measurements` is a TimescaleDB hypertable on `measured_at` (90-day chunks),
made by one `RunSQL` in migration `farm/0014_water`, which depends on `core/0001_timescaledb` (the
migration that runs `CREATE EXTENSION IF NOT EXISTS timescaledb`). Its primary key in the database is
`(id, measured_at)`, as a hypertable's must be, while Django's model keeps `id`, so `makemigrations
--check` stays clean (a test runs it). The rules that follow are in the model's docstring: every unique
constraint includes `measured_at`, no foreign key points at the table (the table's own key to its point is
fine: it points the other way), compression is left for later.

**Limits** (Setup › Reference data › Water limits) are rows per species, parameter (every measured one,
and the un-ionised ammonia NH₃-N) and water type, or any water: critical below, warning below, warning
above, critical above, any of them open, and where the values come from. The bounds go up, each is in
its parameter's range and precision, and there is one live row per species, parameter and water type;
the database checks all of it, and the form says it on the field. The unit is the parameter's. **Nothing
is seeded**: the owner enters the values a vet or a guideline gives (starting points for Atlantic salmon
are in the bug document, not in the database).

**Judged on read** (`farm/water/evaluate.py`, `farm/water/read.py`); nothing about a status is stored:
- Inside the warning bounds a value is ok, outside them a warning, outside the critical bounds critical;
  a value on a bound is in the inner band.
- A value is judged for the species in its unit on the day it was measured (any time of that day, from
  the stock ledger), against the row for the unit's water type, else the row for any water; with
  several species the worst wins. A loop's sample is judged for every unit of the loop. **A unit without
  fish shows its values with "no limit"** (owner decision 1). A value without a limit says why, under a point's status on
  the water page: "No fish in the unit", or "No water limit is set for the fish in the unit" (`Reading.why_no_limit`; the
  species is not named, the water's readers need not read the stock).
- **A point's status is the worst of its values**, and an old critical or warning value still counts: the point reads
  "Critical, no recent data" (`Reading.judged` keeps what the limits said when the value grew old, `PointWater.old_alert`),
  never hidden by a fresh OK of another parameter and never "No limit" (HA-K02's side outlet: a CO₂ of 15.6 three days old
  read "No limit" once it aged, because the sample's other values have no limit row). A point whose judged values all grew
  old and were not alarming is **Stale**. The overview's critical count counts such a point too (it holds a critical
  value, old or not), the monitoring card says it critical the same way, and the Production units dot reads "Critical, no
  recent data" in its title and for a screen reader (`farm/_water_dot.html`), never red alone.
- **A past sample is judged against the limits as they are now** (owner decision 2): a changed limit
  re-judges the history at once; the limits of the time are not kept. The page says so.
- The latest value of each parameter is per parameter, not per sample: a later sample without DO never
  hides a critical DO. A value older than its freshness is "stale" with its age, never ok. A unit's
  status is the worst of its fresh values; stale when nothing is fresh.

**Worked out from a sample**, never stored (`farm/water/chemistry.py`, each pinned by a test against
published values):
- **NH₃-N** = TAN × K / (K + [H⁺]), with K the ammonium constant of Clegg & Whitfield (1995, eq. 18; their pure-water
  pK in fresh water) converted to the free scale, and the pH (NBS) converted too, by the core's formula 4 (Water-chemistry
  core): in fresh water with its own ionic strength, [H⁺] = 10^−pH / γH; in salt water by Millero's (1986) measured step
  between the NBS and the seawater scales. It needs the pH and the temperature of the same
  sample; the salinity is the sample's, else its point's latest fresh at the sample's time (measured at or before it, within the salinity's 7 days: a stale salinity never enters a calculation), else its owner's middle
  point's, else 0 where every unit it concerns is in fresh water; otherwise the page says what is missing. The
  alkalinity, the conductivity at 25 °C and the hardness that give its ionic strength are found the same way (none
  found: an ionic strength of 0, the safe side). NH₄-N = TAN − NH₃-N is shown. Each worked-out value says the formula
  it was worked out by in its title ("Formula 4: ionic strength 0.0072, from the conductivity at 25 °C."): nothing worked
  out is stored, so a past sample is shown by today's formula, and says so.
  **The NH₃-N shown, judged and alarmed is on the safe side of the best estimate** (formula 4's Rule S, the
  water-chemistry audit of 2026-11-19 and the owner's decision; before it, cross review F1 and the owner's decision of
  2026-11-09): up to 1 ‰ the ideal water, every activity 1, Emerson et al. (1975) as Piper et al. 1982 and US EPA 1985
  used it, exactly as formula 3 had it; from 5 ‰ the best estimate at the pH + 0.03, the uncertainty of a pH reading
  (US EPA 1989, p. 3), which puts the best estimate's [NH₃]/[NH₄⁺] 7.2 % higher at every temperature and the NH₃-N up
  to 7.15 % higher, less the higher the pH (formula 4 below); blended between; salt-added water:
  the ideal throughout. The larger of it and the best estimate is judged (in fresh water the ideal is the larger as soon
  as an ion is measured: at 12 °C, pH 7.5 the best estimate is 8.7 % lower at 500 µS/cm, 11.6 % at 1000 and 17.2 % at
  3000; with nothing measured the two are within 0.5 %). The best estimate's NH₃-N is said in the title beside it ("NH₃
  judged on the safe side ..., the larger of it and the best estimate; best estimate 0.0121 mg/L."); it is never judged.
  Against formula 3 the judged NH₃ of brackish and sea water fell (S 5: 11 to 14 %, S 10: 8 to 12 %, S 20: 4 to 9 %,
  S 34: 0 to 5 %, 0 to 30 °C): formula 3 judged it on Khoo et al.'s (1977) constant applied to the unconverted NBS pH,
  whose margin over the best estimate was the size of pH NBS − pH free, never designed. Fresh water did not move, except where no ion is measured: there the judged NH₃ is
  up to 0.5 % stricter than formula 3's (the best estimate is the larger), never looser; the CO₂ is unchanged.
  **Above 30 °C or a salinity of 35 ‰ the NH₃ and the CO₂ say a warning** in the same title ("NH₃ and CO₂: above 30 °C or
  a salinity of 35 ‰ the water is outside the range the formula was checked over ..."): the judged values keep their
  margin over the best estimate there (`chemcore/core/tests/formula4.rs`), but nothing of formula 4 was computed or
  checked above 30 °C (the step's temperature share is fitted from 0 to 30 °C, Millero's line held at S 35 above it).
  The value is still worked out and judged, with the warning; never refused. The two bounds are validity bounds of the
  cited constants (`fresh::NH3_GUARD_MAX_TEMP_C`, `NH3_GUARD_MAX_SALINITY`), not farm limits, so they are not reference
  data.
- **Oxygen saturation**: Benson & Krause (1984) as in Standard Methods 4500-O, corrected for the
  barometric pressure of the site's altitude (sea-level pressure, said so, when the site has none; the altitude is
  0 .. 5000 m (owner: no site lies below sea level, a minus sign is a slip), held by the form, the model and the
  database `chk_sites_altitude_range`, F-089, and the calculator's field takes the same range). From
  mg/L the % is worked out, from % the mg/L, the value saying what it was worked out from ("Worked out from 9.5 °C,
  0.0 ‰ and 1.000 atm", on the water page and the card). **What an oxygen entry is worked out with is its provenance,
  never a measurement** (second cross review, finding 1): the record form and the round leave the temperature and the
  salinity EMPTY and only say in the help (and a round's cell) what an oxygen would be worked out with now ("now 9.5,
  system sensor #1 · 30 s ago", or fresh water's 0). A value typed there is a measurement of the sample and stored as one
  (alone too). Left empty beside an oxygen, the server finds, when it writes the sample, the point's temperature and
  salinity fresh AT the sample's own point and time by the one resolver (`read.oxygen_basis`: nothing measured more than
  the clock's skew after it, so a backdated entry never takes a later value and another point's value never lands on the
  point chosen), else fresh water's 0 for the salinity, and stores them as `oxygen_basis_*` (value, source, sensor
  channel, when measured; held by `chk_water_measurements_oxygen_basis_*`: only beside an oxygen, never beside the
  sample's own value) and in the activity log; the worked-out value then says it ("The temperature is system sensor #1,
  08.11.2026 10:00."). The basis is read only by the oxygen's conversion: it never becomes the point's latest temperature
  or salinity. With nothing fresh to work it out with, the forms ask for the value ("Needed with the oxygen: no fresh
  temperature here at that time ..."); a sample written otherwise (an import, a test) is kept without a basis and its
  other unit says what it needs. When both units are entered and differ by more than 10 %, both are
  kept and flagged.

**The page** has three tabs: **Latest** (one row per point: the middle point of every unit (a unit without one
has a row that says so) and every other point, of a loop, a unit or a piece of equipment, that has a sample in the
last 30 days; its status and the latest value of each parameter, coloured by status, its time and age on hover;
a filter by site), **History** (the samples, newest first, 50 a page, filtered by site, by unit, loop or
equipment and then by one of its points, dates, and "only warnings and criticals"; each value says which point
it was taken at, coloured as judged now, worked-out values in italics; Void while the sample is in the window)
and **Calculator** (below). **Record sample** opens the dialog (a sampling point chosen from the points grouped
by what owns them, "T-01 › Middle"; date and time on the site's clock, source, the fourteen values in four
groups, notes). Opened from a unit, a loop or a piece of equipment (`?unit=`, `?system=`, `?equipment=`) it
offers that owner's active points with its middle point chosen, so a routine sample takes no more fields than
before, and when the owner has only one point it is fixed; each field's help shows the limits of the fish
there. `?point=<id>` names one point. **Round** is the morning round: a site and optionally a production
department or a system, the columns to fill (temperature and oxygen by default), one row per unit's middle
point (a unit that is not inactive) and per loop, and, when asked ("Also list": inlets, outlets, side outlets,
bottom drains, depth points, the points of equipment), the other points of them, one time and one source; empty
rows are skipped, a value out of range is shown in its cell and nothing is recorded until every cell is right
(at most 200 rows).

**A unit's water** is read for its middle point (`read.middle_points`, the one definition; `read.unit_water`): what
Production units, its drawer, the overview tile, the status dot and the calculator show of it. By owner rule A9 (below,
"The water's latest value"), every active point measuring the unit's own water is the unit's own (A9.1, owner
2026-11-08: the middle, a depth point, an outlet, a drain; `read.OWN_WATER_KINDS`). An inlet's sample is the supply
stream's, not the fish's: it is judged for the same fish and shown at its own point, but it never stands for the unit
and never moves the unit's status. The unit's system's loop stands in only for a parameter the unit has nothing fresh
of. Its **temperature** for the ration
(`farm/feeding/temperature.py`) is picked by the same rule (`read.choose`), with the loops of the systems its system is
nested in as further tiers; the withdrawal's daily mean (`farm/health/withdrawal.py`) takes the lowest daily mean of the unit's own-water points (never the inlet; owner 2026-11-08: the conservative side), else
its own system's loop (a day without one counts at the species' assumed temperature, else as 0 °C, and says so: the safe
side). Both ask `read.water_sources`, the one place that says where a unit's temperature is read from,
and a test fails when another module reads the samples.

**The calculator** (the third tab, `/operations/water/calculator/`) is laid out as the source's: where the
values come from, the input bar, the dosing simulator, the row of charts [NH₃ and H₂S against pH | the **Water
Quality Management Chart**, larger | the carbonate species and the calcite saturation against pH] and the
results row [ammonia | hydrogen sulfide | worked out | dosing recipes]; on a phone one column, the big chart
first. Every chart is SVG drawn on the server without a chart library (`farm/water/deffeyes.py`,
`farm/water/charts.py`); one `Calculation` (`farm/water/calculation.py`) feeds the page, its live parts and
its report, so they never disagree. It is a GET form: the values live in the address, nothing is stored, and
without values it shows its defaults.
- **Interactive**: the results follow the form. Ticking or unticking a layer redraws the chart at once;
  typing redraws the charts and the results after a 0.3 s pause; no button. The browser asks the server for
  the calculator's live parts (`/operations/water/calculator/results/`, each part a `data-live-part`) and
  swaps them in; a request still on its way is dropped, the fields are never replaced (focus and caret
  stay), the wrong values come back under their fields and in a list that links to them, and the address
  follows the form, so a link opens the same view. The server is the one source of every number and of the
  SVG: the browser code (`frontend/poll.ts`, the live form, usable by any GET form) has no chemistry. Without
  the script the form has a Calculate button and the page is drawn again.
- **Where the values come from**: entered here, or a unit or a loop. Choosing one puts in the latest value
  of each measured field of its water, its middle point's (temperature, pH, salinity, alkalinity, TAN,
  dissolved oxygen: `read.owner_water`, each
  with its age, stale ones marked), its site's altitude, and the limits of the fish in it today
  (`read.limits_now`: the critical high of NH₃-N and of CO₂, the warning bounds of alkalinity as the safe
  zone's band, the four pH bounds; with several species the strictest), and sends the address with them. They
  can be changed for this calculation (marked "changed here"); nothing is written back. A field the point has no
  value for keeps what was entered, and the bar says which; the pH bounds are the fish's all four, one they
  have none of is emptied. The calculator has one limit per ammonia, CO₂ or sulfide (the critical one) and
  its own 0.2 pH alert band: a species' warning bound for NH₃-N is not used, so a value between the warning and
  the critical bound is ok here and a warning in the water module.
- **In** (tabs Water, System, Target, Limits, Reagents, Simulator): temperature, pH (NBS, 4 to 12),
  salinity, alkalinity (mg/L as CaCO₃), each with its parameter's label, range and precision; optionally
  TAN, total sulfide (µg/L as S, as laboratories and methylene-blue kits report it), dissolved oxygen; the
  volume (m³), the calcium and the altitude; a target pH and alkalinity and the alkalinity band of the safe
  zone; the limits NH₃-N (mg/L as N), CO₂ (mg/L) and H₂S (µg/L as H₂S) and the pH a step of the simulator may
  have (critical and warning, each side); the reagents to dose with (the
  source's nine; NaHCO₃, NaOH, CO₂ added and CO₂ stripped to start with); the simulator's grams of each; and
  the chart's layers.
- **The chart**: DIC (mmol/L) across, alkalinity (meq/L) up, 0 to 6 each and wider when the point, the
  target, the band, the dosing waypoint or a simulator step needs it; pH isolines every 0.25 from 4.25 to
  12.5 (every 0.5 labelled); the regions where NH₃ (above its border's isoline), H₂S (below its border's
  isoline) and CO₂ (below the curve where CO₂ = the limit) pass their limits; the safe zone (the band, between
  the NH₃ border and the higher of the CO₂ and H₂S borders); Ω = 1 for calcite and aragonite with the calcium
  given, from 5 to 44 ‰ (Mucci's range; the calcium and the carbonate per litre against the Ksp per litre, Mucci's
  times the square of the sea water's density, Water-chemistry core); the water (a star) and the target (a cross); the dosing layer (one
  reagent chosen: its direction from the water; two: both, the wedge between them and their path to the
  target through the waypoint; more: a note) and the simulator's path, an arrow at each step. A note says
  why a layer asked for is not drawn; a region's name with its border (NH₃ toxic (pH > 8.04)) is in its
  tooltip and the legend.
- **The small charts**: NH₃-N (TAN × the NH₃ share) from pH 6 to 9.5 with the limit, the H₂S and HS⁻ shares
  of the total sulfide from 4 to 12.5, the CO₂, HCO₃⁻ and CO₃²⁻ shares of the DIC from 4 to 12, and the
  calcite and aragonite saturation index at the water's DIC from 6 to 9.5 (5 to 44 ‰ with the calcium only);
  the NH₃ and H₂S charts carry the safe, alert (0.2 pH) and danger bands of their borders, none when the value
  or its limit is missing; an axis widens to hold the water.
- **Out**: ammonia (NH₃-N and its status, the most TAN this pH allows, the border and the margin, NH₃'s share
  at the border), hydrogen sulfide (H₂S as H₂S and its status, the most total sulfide, the border and the
  margin), worked out (CO₂ and its status, border and margin; the CO₂ the air leaves in the water; alkalinity
  in meq/L, DIC, target DIC and CO₂; oxygen solubility and saturation). A status follows the source: past the
  border critical, within 0.2 pH a warning.
- **Dosing** (`farm/water/dosing.py`): each reagent moves the water along its own direction on the chart,
  per mmol: NaHCO₃ +1 DIC +1 alkalinity, Na₂CO₃ and CaCO₃ +1 +2, NaOH 0 +1, Ca(OH)₂ and CaO 0 +2, CO₂ +1 0,
  stripping −1 0, HCl 0 −1 (Deffeyes 1965; Stumm & Morgan 1996). A **recipe** reaches the target with two
  reagents: the move is split on their directions with both amounts ≥ 0; every pair of the chosen reagents,
  ranked as the source ranks them (sodium bicarbonate first), an overshoot-and-correct pair only when nothing
  else reaches, at most six; grams for the volume and g/m³; a recipe is flagged when its stripping would end
  below the CO₂ of water in equilibrium with the air whichever of its two doses goes first. The **simulator**
  adds the grams in turn and shows each step's pH (against the pH bounds, as the water limits judge it: inside
  the warning bounds ok, outside a warning, outside the critical bounds critical), alkalinity (a warning
  outside the band), DIC, CO₂, NH₃-N and H₂S, each judged as the water is, the change from the water to the
  last step, and its path on the chart. Amounts are of the pure substance (a product of 31 % HCl
  weighs about three times as much). Stripping below the CO₂ of water in equilibrium with the air (Weiss
  1974, 420 µmol/mol, the site's pressure) is flagged; acid past the alkalinity is shown as acid, and more
  CO₂ stripped than there is carbon stops the simulation (the source clamped both, WQ-41). The dosing is
  checked against an independent carbonate model (Plummer & Busenberg's constants in fresh water, Lueker's with
  Dickson's boron in sea water): the pH agrees within 0.005 in fresh water and 0.012 in sea water. In fresh
  water salted to a few ‰ with NaCl alone, Millero's constants (which include the ion pairs of sea water's
  magnesium and calcium) may put the pH after a strong base up to about 0.15 lower near pH 9, the side that
  under-warns on NH₃: this is the inherited convention of the chemistry above, not a new one.
- **Print report** opens `/operations/water/calculator/report/` with the same address: the values, the
  values worked out, every chart with every layer drawn (as the source's report forces its safety layers
  on), the simulator and the recipes, on a page of its own for A4 across.
- **The chemistry** (`farm/water/chemistry.py`, one module with the ammonia and oxygen above): K1 and K2
  of carbonic acid of Millero, Graham, Huang, Bustos-Serrano & Pierrot (2006), fresh to sea water (the
  source calls them Millero 2010, WQ-39); Kw of Millero (1995) on his seawater scale (pure water's at a salinity of 0;
  formula 1 took the 2007 Guide's approximate total-scale value); KB of Dickson (1990)
  with Uppström's (1974) boron; the ammonium constant of Clegg & Whitfield (1995, eq. 18; formula 3 took Millero's
  1995) for the best estimate, while fresh and salt-added water are judged on the larger of it and the ideal water,
  which keeps Yao & Millero's (1995) pure-water value, and brackish water of 1 to 5 ‰ on the larger of the best
  estimate and a blend of the two (`formula4.rs limits_basis`; formula 4 below; the calculator's list of sources, on
  the page and in the report, says all of it); KH₂S of Millero,
  Plese & Fernandez (1988), whose measurements are in sea water of 5 to 40 ‰ at 5 to 25 °C (the paper's abstract): in
  fresh water, below 5 °C and above 25 °C the H₂S rests on the equation alone, checked against no second source (the
  tests hold its 25 °C values, 6.98 fresh and 6.51 at S 35; the H₂S audit of 2026-11-20 recalled two other fresh-water
  fits, Millero 1986 and Broderius & Smith 1977, that put pK₁ 0.03 to 0.13 lower at 5 to 12 °C, i.e. less H₂S, but
  did not open them), and the calculator says so, once on the page, in its live part and in the report, beside every
  number that rests on it: the H₂S of a total sulfide, and the most total sulfide an H₂S limit gives at the pH (the
  calculator always has a limit, its default 2 µg/L; `farm/calculator/_h2s_basis.html`); the
  Ksp of Mucci (1983); the CO₂ solubility of Weiss (1974); each converted to the free
  scale, the pH (NBS) too, as the source does. DIC = (alkalinity − [OH⁻] + [H⁺] − [B(OH)₄⁻]) / (α1 + 2 α2),
  CO₂ = DIC α0; NH₃-N = TAN K / (K + [H⁺]); H₂S = total sulfide × 34.08 / 32.07 × [H⁺] / (K + [H⁺]). A pH
  and an alkalinity that cannot go together (the hydroxide and the borate alone at or above the alkalinity) are refused:
  by the form and a unit's chart with the reason, and by the core itself (`ImpossibleWaterError`), by one rule.
- **The NBS pH in salt water** (formula 4 since 2026-11-19, `chemcore/core/src/formula4.rs`): pH free − pH NBS is
  Millero's (1986, table 7) measured pH NBS − pH total at 25 °C, the line 0.1306 + 0.00073 S through his S 5 to 35
  points (held above 35), on the free scale by Dickson's bisulfate, moved in temperature by 0.75 of the bisulfate and
  fluoride term (fitted to Takahashi et al.'s 1982 fH, 0 to 30 °C, S 30 to 36): within 0.004 pH of Millero's points and
  0.0062 of Takahashi's fit (S 30 to 35, 0 to 30 °C). It replaced the in-house Davies-type conversion of formula 3,
  described next, which was 0.024 pH off at 12 °C and 0.04 to 0.05 at 0 to 4 °C in salt water (the water-chemistry
  audit's consensus, point 3). Below 5 ‰ the band blends the fresh path's Davies offset with this step (Millero's S 0
  and 2.5 points). Nothing was measured below 25 °C under S 20.
- **The ionic strength and the NBS pH** (formula 3 from 2026-11-09 to 2026-11-19, its fresh path still formula 4's; the
  source's convention, formula 1, took the
  ionic strength from the salinity alone, so a fresh water was ideal): up to 1 ‰ the water's own ionic strength (the
  conductivity at 25 °C, else the salinity, never below the measured hardness and alkalinity's ions; none measured, 0)
  with Davies activity coefficients; from 5 ‰ the seawater constants; between, a blend (Water-chemistry core). A pH (NBS)
  is put on the seawater scale with a Davies-type activity coefficient whose Debye-Hückel A is the temperature's (an
  in-house variant of Zeebe & Wolf-Gladrow's, not a published method; cross review F2), not CO2SYS's apparent coefficient of Takahashi et al. (1982): at 35 ‰ the two differ by −0.048 pH at 0 °C, −0.038 at
  5 °C, +0.001 at 25 °C and +0.034 at 40 °C (formula 1, with a fixed ε of 79: −0.073, −0.058, +0.004, +0.051). Closer
  to it at 20 to 35 ‰ for t ≤ 15 °C and at 35 ‰ at every temperature; not at 10 ‰ from 10 to 20 °C (B1.md; formula 4,
  Takahashi's fH for 20 to 40 ‰, is the planned follow-up).
- **The pH's scale** (the K_NH4 panel's proposal, built by the owner's decision of 2026-11-11;
  `chemcore/core/src/scale.rs`, `chemcore/findings/pH-scale.md`): every pH stored, shown, judged and worked out from is
  on the NBS scale, what a meter calibrated with NBS/NIST buffers reads, and its field says so with the size of the
  hazard (a total-scale pH reads 0.09 to 0.15 lower from 5 to 35 ‰ and 0 to 30 °C by formula 4's step; typed as NBS
  the NH₃ comes out 19 to 28 % too low).
  Where a pH is typed (Record water sample, a water round, the calculator) its **scale can be chosen**: NBS (the
  default: nothing changes, the golden files keep their bytes), total (a seawater sensor calibrated with TRIS),
  seawater (SWS) or free. A pH on another scale is put on the NBS scale by the core at that door: pH free = pH total +
  log₁₀(1 + ST/KS) (Dickson, Sabine & Christian 2007, ch. 2, eq. 15; the seawater scale with FT/KF too), less the
  water's own offset free − NBS. Only for sea water (5 ‰ or more, the sea path's constants alone; not fresh water with
  salt added) and only with the temperature and the salinity of the same sample; otherwise refused with the reason,
  by the form, the write path (`farm/water/services.on_nbs`) and the core (`SeawaterScaleError`). A sample keeps what
  was measured (`ph_scale`, `ph_as_measured`, `ph_converted_formula`; `chk_water_measurements_ph_scale` holds them
  together) and its reading says it wherever a value's title is shown (the latest values, the history, a monitoring
  card): "Measured 7.95 on the total scale; put on the NBS scale by formula 4 with the sample's 12.0 °C and 34.0 ‰."
  The stored pH has the column's two decimals; the calculator converts without rounding and says "pH 7.95 on the
  total scale is 8.06 on the NBS scale" (formula 4; 8.08 by formula 3), its target pH and pH limits are NBS, and values taken from a unit are NBS. **No
  page holds a pH on another scale, so none can mix them.** A sensor's pH is put on the NBS scale by the same
  conversion, by its channel's pH scale (Sensors › Channels, *pH scale*; after the water-chemistry audit of 2026-11-19,
  below). Checked against PyCO2SYS 1.8.3.4 and seacarb 3.4.2 over 0 to 40 °C by 5 to 40 ‰ (72 cells): the free and the
  seawater-scale pH of a total-scale pH within 8.9e-15 and 2.4e-7 pH; the NBS leg is the core's own conversion (−0.069
  to +0.055 pH against CO2SYS's, as every NBS pH), which cancels in what the water's own constants work out.
- **After the independent review of 2026-11-16** (`F:\dev\balik-notes\chem-v3\REVIEW.md`; R5, R7, R8 and R10 are the
  owner's to decide):
  - *A water the core refuses is said in words at every door* (R1). A stored value inside its parameter's range can
    still give a water the core refuses (a conductivity past the Davies range on a water below 5 ‰: 40 000 µS/cm at
    S 0). One gate, `deffeyes.why_impossible`, which the calculator's form, a unit's chart, a replay frame and the
    trail ask before they work a water out, says the core's own refusal first (`deffeyes.unworkable`), in the one
    wording a sample's NH₃ has (`messages.refused`: "Cannot be worked out: …"). The pages answer 200 and say why there
    is no chart or no result; the trail lists the hour with its reason (`unworkable`).
  - *A loaded pH is never converted twice* (R2). The calculator loads a unit's pH as NBS, carries the loaded value
    beside the field (`ph_loaded`, `CalculatorForm.LOADED`) and says "measured 7.95 on the total scale, stored as 8.08
    NBS"; another scale on the unchanged loaded value is refused with the reason. A pH typed over it is converted.
  - *Salt-added water never takes a seawater scale* (R4): refused by its origin at every salinity, also past the Davies
    limit (about 28.4 ‰ as NaCl) where the core works its constants out by the sea path (`scale::converts`).
  - *A converted value says what was measured in visible text* (R6): `Reading.measured`, printed beside the stored
    number by `farm/_water_value.html` ("measured 7.95 on the total scale"; "entered as 15.35 mg/L PO₄").
  - *The phosphate says its unit, and every dose says its phosphate* (R3). Where a phosphate is typed (the sample
    form, the round, the calculator) its unit is chosen: "as P (PO₄-P)", the default, or "as PO₄", which is put on P
    at that door by the molar masses (`parameters.PO4_PER_P`, 94.9714 / 30.973762 = 3.066; the one place). A sample
    keeps what was entered (`phosphate_unit`, `phosphate_as_measured`; `chk_water_measurements_phosphate_unit`); the
    range is the phosphorus's whatever the unit; a phosphate loaded into the calculator is as P and is not converted
    again. Beside every recipe and beside the simulator's steps: "Worked out with phosphate 5.01 mg/L as P (15.35 as
    PO₄): a wrong phosphate changes this dose." The help names the 3.07-fold slip. (True P 5 typed as 15.35 with the
    unit left at P gave NaHCO₃ 2.14 + NaOH 14.96 g/m³ where 8.59 + 11.89 is right.) A sensor's phosphate channel is as
    P, as before.
  - *A CO₂ curve that bends back says so* (R9): with a phosphate the judged CO₂ curve bends back near an alkalinity of
    0; the chart's note `co2.bends_back` says it exactly when the drawn curve does (`geometry::bends_back`).
- **After the verification of those fixes** (2026-11-18, the last part of the same REVIEW.md):
  - *A water the core refuses is never silent* (V-A). A judged value the core refuses to work out (a TAN sample's NH₃
    where the water's conductivity, its own or the point's latest fresh one, is past the Davies range) is "Cannot be
    evaluated" (`Status.UNEVALUATED`, between warning and OK) where the fish have a limit for it: the unit is never OK
    behind it; the water page, the monitoring card and the overview's "Needs attention" say "… cannot be evaluated:
    <reason>" (`messages.unevaluated`), and the alarms raise a warning for the unit (below, Alarms).
    **Judged on the limits' basis** (decision of 2026-11-18 on the re-check's RC-3; `read.Context._ammonia_on_basis`):
    the judged NH₃ is the larger of the basis the limits were set on and the activity-corrected value, and the basis
    needs no conductivity (`fresh::limits_basis`: the temperature, the salinity and the origin only;
    `farm/tests/test_core_refusal.py` holds the basis without the ions equal to the basis with them). So a refused
    water's NH₃ is the basis's NH₃-N, at least the judged value, shown with "at least: the limits' basis": past a limit it
    is that limit's status and alarm (critical past the critical limit; the verifier's water, pH 9.00 and TAN 5 at
    12 °C, is critical, where it was a warning), inside the limits "Cannot be evaluated". The "cannot be evaluated"
    sentence and the unit's system warning stay beside it either way. Only where the core gives no basis either is
    there no value. A refused value never ends a limit alarm.
    **The page and the alarm agree** (RC-2): a unit whose own NH₃ the core refused and whose loop's fresh sample is
    critical is critical on its page (`read.worst_fresh`), on its card and in its alarms (`alarms.sources.decided`).
  - *A value is typed only when the form says so* (V-B; `CalculatorForm._loaded`). A value equal to the one carried
    beside the field (`ph_loaded`, `phosphate_loaded`) is loaded, and stays loaded on its stored scale when "Values
    from" is changed to a unit that has none; a different one is typed. An address that carries none is refused a scale
    or unit where the unit now offers another value: a loaded pH or phosphate is never converted twice.
  - *A salt-added unit makes its loop salt-added for the pH-scale rule* (V-C; `read.scale_origin` over `read.one_water`:
    the units given and every live unit of their systems). One water, one answer at every point of it: the loop point,
    each unit's middle point and its other own points (the re-check's RC-1: B-02, which says nothing, in a loop with the
    salt-added B-01, took a total-scale 7.95 as 8.09 at its own point). The sample, its row of a round and the
    calculator loaded from the loop or from any of its units refuse a seawater scale. `common_origin`, which gives the
    constants, is unchanged, so no worked-out number moves.
  - *One upper bound as PO₄* (V-F): 306.61 (`parameters.PO4_HIGH`, the last two-decimal PO₄ at most 100 as P) at the
    sample, the round and the calculator, in one sentence; the check now holds the entry and the stored P together
    within the rounding (farm 0046).
  - *A sample's NH₃ catches what the gate catches* (V-G): an arithmetic error of the core is said, never a failed page;
    so do the pH-scale rule of the sample door (`services.on_nbs`) and of the calculator (`CalculatorForm._ph_scale`).
  - *The history's "Only warnings and criticals" keeps a sample that cannot be evaluated* (the re-check's RC-5).
  - Left as the verification says: V-D (farm 0045 and 0046 add their check validated, an exclusive lock on
    `water_measurements` while each chunk is scanned: land with the server stopped; going back past 0045 keeps the P
    and loses the PO₄ entry), V-E (the phosphate sentence is one per list, above it), V-H (the chrono advisory of
    `sensors-ingest`: a dated ignore on main, not on this branch; since solved without an ignore, the ingest moved from
    chrono to `time`).
- **After the water-chemistry audit of 2026-11-19** (`F:\dev\balik-notes\chem-audit-fable\AUDIT.md`; no constant and no
  formula moved, the golden files keep their bytes; F2, a published NBS conversion in salt water, waits for the owner):
  - *A sensor's pH has a scale* (F1, owner decision 1 of 2026-11-17). A pH channel says the scale its probe reports on
    (`sensors.Channel.ph_scale`: NBS, the default for every channel there is; total, as a TRIS-calibrated ISFET or
    optical sea-water probe reports; seawater; free). The ingest stores what the device sends. Where the water is read
    (`farm/water/read.py`: the latest values, the water at a past moment; the replay; the trail) a value on another scale
    is put on the NBS scale by the one conversion a typed sample takes (`read.ph_on_nbs`, which `services.on_nbs` calls
    too), with the place's fresh temperature from the sensors (as a sensor's TAN takes its pH and temperature), else the
    place's temperature (a sample's) where it is fresh at the pH's own time, as the oxygen's other unit, the replay and
    the trail take it (the review's C2; the provenance then says "The temperature is manual, 19.11.2026 10:00."), and the
    salinity of the same moment (a fresh sensor's, else the point's fresh sample's, else 0 in fresh water), for sea water
    of 5 ‰ or more and never for fresh water with salt added, while the pH is fresh. It is then shown as the typed
    sample's is ("measured 7.95 on the total scale" beside 8.06; "Measured 7.95 on the total scale by the sensor; put on
    the NBS scale by formula 4 with 12.0 °C and 34.0 ‰ of the same moment."), and its NH₃ is the typed sample's: a TRIS
    probe at 12 °C and S 34 gives the judged NH₃-N the same water typed as a total-scale sample gives. Otherwise (no
    temperature fresh at its time, no salinity, fresh or salt-added water, a water the core cannot work out at all,
    a pH no longer fresh) **the pH has no value and cannot be evaluated**, said with the reason (the core's own where it
    refused the water, never "not sea water": C5), and so is an NH₃ worked out from it; the unconverted number is shown
    and used nowhere (a worse fresh sample still decides the status). **It is never silent for the alarms** (the
    review's M1): the unit gets the alarm system's warning "<unit>: pH (NBS scale) cannot be evaluated: <why>" (Alarms,
    below), as a refused NH₃ does. The replay's frame has no pH and no diagram then, with the reason; the trail's hour
    is unworkable with it. The sensor's own chart draws its values as measured and says their scale beside the NBS
    samples. The alarm rules on a channel (Sensors › Alarm rules) take no above or below on a pH (a water value: the
    water limits judge its level, on the converted value); a rate is about the same on every scale and never compares a
    value with one from before a change of scale (C1).
    *A change of a channel's scale* (whatever door saves it, `Channel.save`) records the moment (`ph_scale_from`). What
    the probe measured before is on a scale not known any more (a probe recalibrated, or a setting put right: the
    application cannot tell which), so **those values are used nowhere, neither on the old scale nor on the new**: the
    latest pH says "cannot be evaluated: measured before the channel's pH scale was changed" until the probe's next
    value, the past moments, the replay, the trail and the chart leave them out (the chart marks the change, and a
    window with values left out says "Channel #n's values before <the change> are not drawn: its pH scale was changed
    then", even a window wholly before it, which draws nothing: C4). The alarm system's warning for such a value waits
    while it would still be fresh (the probe's next value is due by then and is read on the new scale), so a change of
    scale does not raise and end a warning; a probe that sends nothing after the change is warned of once its value
    would be stale (`alarms/sources.py _unevaluated_since`). This is the safe side both ways: a total-scale reading taken as NBS reads NH₃ low,
    an NBS reading taken as total reads a low pH too high. The channel's form asks the scale (pH channels only; empty:
    as it is), its list and the live values say it, its edit page says when it was changed; the column, a database
    default for the ingest's inserts and the check `chk_sensors_channel_ph_scale` are sensors 0013.
  - *The NH₃-N is judged unrounded* (F3): the limits, the worst fresh value and the alarm's deadband test read the value
    as worked out (`Reading.exact`, `judged_value`), the page shows it at four decimals. A true 0.01034 mg/L read 0.0103
    and was OK against a limit of 0.0103; it is now a warning that reads 0.0103. The oxygen worked out in its other
    unit is judged the same way. Where the number shown would read as on the limit it is past, a sentence that sets
    the value beside its bound says the exact one instead ("0.01034 > 0.0103", never "0.0103 > 0.0103"; `value_past`,
    Monitoring, the band above).
  - *Words* (F5 to F11): the sea-water basis says what it is (above); the activity-corrected NH₃ of a water with seawater
    constants says it rests on the application's own NBS conversion and reads up to about 16 % below the published
    references in cold sea water, information and not the better value (F6); a kit's nitrite is divided by 3.28 (F7);
    the calculator gives the ionic strength in mol/kg H₂O where it is the salinity's (DOE 1994: 0.7014 at S 34 is
    0.695 mol/L) and in mol/L where it is the fresh path's estimate (F8); the core's notes say that concentrations per
    litre are taken as per kg in sea water too, which moves the CO₂ by at most +0.143 % and the NH₃ not at all (F9); a
    water below 0 °C says that the constants are fitted from 0 °C and extrapolated there, the judged NH₃ and CO₂ on the
    safe side (`fresh::BELOW_FITTED_TEMP`, code `below_fitted_temp`; F10); an NH₃ worked out from a pH measured on the
    total, seawater or free scale, typed or from a sensor, and the calculator with such a pH, say that it is judged on
    the NBS scale on the limits' basis (a free-scale constant on that NBS pH, unconverted), the safe side, about 13 to
    25 % above what that pH gives exactly
    (F11). Since formula 4 these words say what formula 4 does: the best estimate rests on Millero's step and Clegg &
    Whitfield's constant, and the NH₃ is judged at the NBS pH + 0.03, up to about 7 % above it, less the higher the pH
    (the margin is the same as for a pH typed as NBS: only the pH it starts from moves; formula 4 below).
- **The optional phosphate** (PO₄-P, mg/L as P; the independent check's hypothesis 12a, owner 2026-11-10;
  `chemcore/findings/phosphate.md`): phosphate is part of the alkalinity a titration measures, [HPO₄²⁻] + 2 [PO₄³⁻] −
  [H₃PO₄] (Dickson 1981's definition as Dickson, Sabine & Christian 2007 give it, ch. 2), with Millero's (1995)
  constants (the Guide's ch. 5, eq. 49, 52, 55, its 0.015 put back; on the fresh path with Davies coefficients).
  **Without the input nothing moves** (no constant is computed; the golden files keep their bytes). With it, a water
  parameter like the others (record form, round, limits and freshness as reference data, a sensor quantity; the
  calculator's field; a unit's chart, the replay and the trail take the unit's fresh value): the DIC and the water's own
  CO₂ of a pH and an alkalinity are lower by it, and **every dose, recipe and simulator step meets its buffer** (before,
  at 10 mg/L in fresh water the CO₂ after a base dose or a degassing came out 57 to 71 % too low and the pH 0.4 to 0.55
  too high: the unsafe side). **A judged CO₂ never falls because a phosphate was given**: every CO₂ judgement, border
  and the chart's CO₂ curve take the largest of the limits' basis, the water's own value without the phosphate and its
  own with it, so a mistyped phosphate (PO₄ typed as P is 3.07 times too much) cannot hide CO₂; the own value with the
  phosphate is said beside it ("CO₂ judged without the phosphate: …"). A pH and an alkalinity whose phosphate alone
  is that much alkalinity are refused with the phosphate in the reason. The NH₃ does not read it. Checked against
  PyCO2SYS 1.8.3.4 over 763 waters (S 0 to 35, 5 to 25 °C, 1 to 4 meq/L, pH 6.5 to 8, 1 to 30 mg/L): the constants and
  the phosphate's alkalinity within 3.1e-14; in sea water the CO₂ a median of 7.0e-6 and at most 1.4e-3 apart (the
  per-litre bookkeeping, next to the floor), the pH after a dose within 1.0e-4; in ideal fresh water everything within
  1e-10. The fresh path with real ions (Davies) has no independent reference.
- **Formula 4: the judged NH₃ and CO₂ on the safe side of one best estimate** (Rule S; the water-chemistry audit of
  2026-11-19, its paper debate's consensus `F:\dev\balik-notes\chem-audit-fable\CONSENSUS.md` and the owner's decision
  of the same day; `chemcore/core/src/formula4.rs`, `FORMULA_VERSION` 4; formula 3 and 1 still worked out by name). The
  best estimate: Clegg & Whitfield's (1995) K_NH4 fresh to sea, the carbonate constants as before, the NBS step above.
  The judged value, the same structure as below (the larger of a basis and the best estimate, so every border, status,
  safe TAN and chart takes it unchanged), with another basis: up to 1 ‰ formula 3's ideal water unchanged (fresh water
  is judged exactly as before: `chemcore/core/tests/formula4.rs`; only where nothing is measured, ionic strength 0, the
  best estimate's pure-water K_NH4 may be up to 0.5 % above the ideal's at 0 °C and judges); from 5 ‰ the best estimate
  at the pH + 0.03 for NH₃ and at the pH − 0.03 for CO₂ (the uncertainty of a pH reading: US EPA 1989, p. 3), so the
  judged NH₃ has the best estimate's ratio r = [NH₃]/[NH₄⁺] × 10^0.03 (+7.15 %), which puts the NH₃-N, r / (1 + r) of the
  TAN, (10^0.03 − 1) / (1 + 10^0.03 r) above its best estimate: up to +7.15 % (where r is nothing) and less the higher the
  pH. Over everything the program accepts (T −3 to 40 °C, S 5 to 50 ‰, pH 2 to 12; 241 595 waters) it is +7.1519 % at pH
  2 and +0.013 % at pH 12 (S 5, 27 °C), never rising with the pH, and the program is within 3e-15 of that closed form.
  The page's words therefore say "up to about 7 % above it, less the higher the pH" (they said "about 7 % above it",
  false at a high pH, until the follow-up of the verification of 2026-11-22; the same for the note beside a pH put on
  the NBS scale), and `farm/tests/test_formula_v4.py` sweeps a coarser grid (3 790 waters) and holds them to it (the
  sweep: `F:\dev\balik-notes\small-fixes\nh3_sweep_full.py`). The judged CO₂ is at least +7.15 % above its best
  estimate, more
  where the lower pH takes borate and hydroxide out of the alkalinity (the carbonate's share grows). Over everything the
  program accepts (T −3 to 40 °C, S 5 to 50 ‰, pH 2 to 12, alkalinity 0 to 1000 mg/L as CaCO₃; 1.32 million waters, none
  judged on the best estimate) the judged CO₂ is never below +7.15 % (the least of the sweep, +7.1535 %, at S 5, −3 °C,
  pH 5.8, 1000 mg/L), is lower the higher the alkalinity at every temperature, salinity and pH swept, and has no
  maximum worth naming: +11.3 % at pH 8.2
  and +19.1 % at pH 9 with 50 mg/L (S 50, 40 °C at most), +171 000 % beside the alkalinity floor. The page's words
  therefore give the floor and the direction, "at least 7 % above it and more the lower the alkalinity", and no
  maximum (they said "up to about 10 % at pH 8.2 and 14 % at pH 9 with 50 mg/L", false over that range, until the
  verification of 2026-11-22, F2, and "about 7 to 9 %" before that). `farm/tests/test_formula_v4.py` runs the sweep
  coarser (17 116 waters, its bounds read from `farm/water/parameters.py`) and holds the words to it; between, blended
  with the band's weight (no step at 1 or 5 ‰: S 0 to 40 by 0.05 ‰, at most 0.5 % a
  step); salt-added water the ideal throughout. Held over the owner's MUST ranges, sea water S 5 to 40 at 0 to 30 °C and
  land water at 8 to 30 °C (`formula4.rs`: 57 660 sea cells, the NH₃/NH₄⁺ ratio +7.15 % exactly, CO₂ at least +7.15 %; every land
  cell at or above the best estimate); outside them the margin is the rule's and holds (tested −2 to 40 °C), the best
  estimate itself is not checked above 30 °C (the warning `nh3_past_guard` says it). Against formula 3: the judged NH₃
  of brackish and sea water falls 11 to 14 % at S 5, 8 to 12 % at S 10, 4 to 9 % at S 20, 0 to 5 % at S 34 (formula 3's
  margin there was the size of pH NBS − pH free, never designed), and the judged CO₂, which formula 3 put up to 7.5 %
  below the best estimate in 11 of 48 cells from 12 °C and S 5, is never below it. The owner's example, 12 °C, S 34,
  pH 7.60, TAN 1 mg/L: best estimate 0.00608, judged 0.00651 (formula 3 judged 0.00672). The core was checked against
  the debate's Python prototype (`F:\dev\balik-notes\chem-audit-fable\f4\compare.txt`): from 5 ‰ identical with the
  decided line; below 5 ‰ the judged NH₃ up to 0.46 % apart (the prototype's ideal water took Clegg & Whitfield's
  pure-water constant, the core keeps formula 3's), the CO₂ 0.002 %. Golden v4 (`chemcore/golden/v4`,
  `record_golden_v4.py`, golden v3's corpus by formula 4) holds it bit for bit (`farm/tests/test_golden_v4.py`).
  **Stored samples converted by an older formula**: a pH typed on the total, seawater or free scale was stored on the
  NBS scale by the formula of its day (`ph_converted_formula`); formula 4's step moves such an NBS pH by up to 0.044
  (−2 to 30 °C, S 5 to 40), so `manage.py rederive_ph` (`farm/water/rederive.py`; `--dry-run` reads only) converts them
  again from what was measured, by the sample door's own conversion, each rewrite logged in the activity log with the
  old and new NBS pH and the formula (samples are otherwise never edited); a sample the conversion now refuses is left
  as it was and named. Running it again changes nothing. The check `farm.W001` (`manage.py check --database default`)
  counts samples left on an older formula: run the command at landing, after the backup. A sample the command refuses
  stays counted, voided or not (voided samples are converted too); the hint says so and the way out: if the unit's
  water origin is wrong, correct it and run the command again. There is no way to acknowledge such a sample yet.
- **NH₃ and CO₂ are judged on the larger of the limits' basis and the activity-corrected value** (formula 3; formula 4
  keeps the rule and replaced the sea-water basis described here, above; cross review F1,
  owner 2026-11-09; `chemistry::Basis`, `fresh::limits_basis`): the NH₃-N, the CO₂, their statuses, borders and margins,
  the safe TAN, the NH₃ share, the target CO₂, the small NH₃ chart, the simulator's steps and the safe zone all take the
  larger; the activity-corrected NH₃-N and CO₂ are shown beside them as information ("not judged"), with a line saying
  which judged. The limits' basis is the ideal water up to 1 ‰ (every activity 1: Emerson et al. 1975's fraction, on
  which Piper et al. 1982 and US EPA 1985 set the NH₃ limits; Standard Methods 4500-CO₂ D's free CO₂), formula 1's
  seawater constants from 5 ‰ for CO₂ and, for NH₃ from 5 ‰ (cross review round 2, S1), Khoo, Culberson & Bates
  (1977)'s eq. 11 (p. 285), pKaˢ = pK° + (0.1552 − 0.0003142 t) I with Emerson's pure-water pK° = 0.09018 + 2729.92/T
  (`fresh::pk_nh4_seawater`), applied to the NBS pH as measured, blended between as formula 3 blends; a salt-added water
  keeps the ideal throughout, past the Davies limit too.
  **What that sea-water constant is** (the water-chemistry audit of 2026-11-19, F5, checked against the paper,
  `F:\dev\balik-notes\chem-audit-fable\PAPERS-CHECK-A.md`): a constant on the free hydrogen ion scale (Khoo's eq. 7,
  p. 283) and molal (Table III, p. 288), measured from 5 to 40 °C at S 20.31 to 44.55 (this form within −0.009 to
  +0.011 of the 24 values). The application applies it to the meter's NBS pH without converting that pH to the free
  scale; in sea water the NBS pH reads above the free pH, so the NH₃ reads higher than with a converted pH (6 to 20 % at
  S 20 to 35): the safe side, on purpose, not "the true value". No paper says a sea-water table takes an NBS pH; that
  toxicity tests calibrate with NBS buffers is US EPA 1989's statement (p. 2). At 12 °C and S 34 the judged NH₃ is
  about 3 to 15 % above the best published estimates (depending on how the free scale is reached), and formula 3's
  judged NH₃ is above formula 1's by about 25 % at 12 °C, 35 % at 4 °C and 41 % at 0 °C (S 34; about 4 % only near 30
  to 35 °C), as `F:\dev\balik-notes\chem-v3\OWNER-DECISIONS.md` now says. It was described here before as "Khoo's pKa
  on the NBS pH, as Bower & Bidwell 1978 apply it": Bower & Bidwell never cite Khoo; their tables take Whitfield's
  (1974) 25 °C values per salinity band with a linear temperature term (Table 1, p. 1012; p. 1015). Against their
  Table 5 this basis gives the same NH₃ at 12 °C and S 34 and less below it (−4.0 % at 4 °C, −7.5 % at 0 °C), their
  linear term being the one that departs from the measurements (the audit's F12, for the owner).
  **What that sea-water basis is not** (the K_NH4 panel, 2026-11-10; it was earlier called "the saltwater criteria's
  convention" here): the US EPA 1989 saltwater ammonia criteria (EPA 440/5-88-004, pp. 1–2 and 27–28, eq. 4, read by
  the panel) did not use Khoo's pK. They used Hampson's (1977) program for Whitfield's (1974) seawater model with a
  linear temperature term, 0.0324 (298 − T); what is shared is a stoichiometric pK applied to the NBS meter pH. Against our basis EPA's printed table gives 6.7 to 14.3 % more NH₃ at 0 to 5 °C (that linear term, which is
  8.1 % wrong in pure water at 0 °C) and agrees within 2 to 6 % at 10 to 25 °C; the EIFAC (1986) sea-water tables imply a
  pK inside our basis's span over each of their salinity bands at 10 to 30 °C, or up to 0.011 below it (NH₃ −2.6 to
  +6.7 % against the band edges). A limit taken from EPA 1989's own table for water of 0 to 5 °C was therefore set
  with up to 14 % more NH₃ than this basis shows: documented, not copied (the panel's decision; no limit is seeded,
  each is entered per species). Which convention a farm's own sea-water NH₃ limits follow is not known.
  **The basis keeps formula 1's ion product of water** (the 2007 Guide's total-scale value, `chemistry::kw_total`),
  while the water's own constants take Millero's (`fresh::ideal_water`): so the judged CO₂ never falls below formula
  1's. Its size in fresh water (measured 2026-11-12 over 0 to 30 °C, 10 to 400 mg/L, pH 6 to 10, 1 953 possible
  waters at a salinity of 0): the basis's CO₂ is the higher of the two, by at most 0.035 % up to pH 8.5 (30 °C, 10 mg/L;
  0.009 % from 40 mg/L), 0.12 % up to pH 9, 0.45 % up to pH 9.5, and 4.1 % at pH 10 within 0.06 meq/L of the
  alkalinity floor; the median is below 0.001 %. It is Kw's 1.51 % times the hydroxide's share of the alkalinity above
  the floor. The independent check's "at most 0.13 % away from the floor" for the Kw correction itself did not hold
  on its own grid: 22 of its 2 160 waters move more (18 at pH 9, 4 at pH 8.5), up to 0.40 % at least 0.2 meq/L above
  the floor (40 °C, 40 ‰, 1 meq/L, pH 9) and 3.8 % within 0.04 meq/L of it; up to pH 8.5 in golden v3's waters the
  move is below 0.09 %.
  CO₂ needs the same rule: the salmonid CO₂ guidelines
  rest partly on free CO₂ worked out from pH and alkalinity the ideal way (Standard Methods 4500-CO₂ D, which the
  calculator is checked against), partly on probes; which basis each was set on was not verified study by study, so for
  live fish the larger is taken. At 12 °C, 80 mg/L, pH 7.5 the corrected CO₂ is 8.8 % below the judged at 500 µS/cm,
  11.7 % at 1000 and 17.5 % at 3000. At the calculator's example (12 °C, 1 ‰) the NH₃ border is 7.986 (formula 3's
  corrected share alone 8.045) and the CO₂ 19.62 mg/L (corrected 17.12). The chart's CO₂ curve is drawn in the water's own
  constants at the limit over the bicarbonate-range ratio of the basis's CO₂ to its own (K1 10^offset over the basis's, a
  ratio of the equilibria alone, so a replay page still shares one diagram among frames equal but for pH and alkalinity):
  the judged CO₂ along it within −0.74 to +0.38 % of the limit (the round-2 review's 165 888 boundary points, S 0 to
  35 ‰, 2 to 25 °C, unsaid and salt-added); the statuses and borders are exact. The stripping
  floor (the air's CO₂, a true concentration, Weiss 1974) is held against the water's own CO₂.
- **The safe zone needs every limit it is bounded by**: without the TAN, the NH₃ limit, the CO₂ limit or
  the alkalinity band, or with a total sulfide but no H₂S limit, it is not drawn and a note says what is
  missing (a missing value is never taken for a safe one). Without a total sulfide it is drawn and named
  "Safe zone (H₂S not assessed)". A border outside the chart's pH range (4 to 12.5) is said in words in
  the table, and its region is still shaded wherever it meets the plotted box (a large box reaches past
  pH 12.5 or below 4).
- **The limits are defaults, not the fish's**, unless the values come from a unit: NH₃-N 0.0103 mg/L
  (0.0125 mg/L NH₃, Piper et al. 1982, as N), CO₂ 15 mg/L (a salmonid guideline), H₂S 2 µg/L (US EPA
  1986); the example water is the source's (12 °C, pH 7.0, 1 ‰, 80 mg/L, TAN 0.5 mg/L, band 50 to 100 mg/L,
  target pH 7.5 at 100 mg/L, 1 m³) with 2 µg/L sulfide as S.
- **Checked** (`farm/tests/test_deffeyes.py`, `farm/tests/test_calculator.py`): the constants against their
  papers' published values; CO₂ against Standard Methods 4500-CO₂ D; the source's own TypeScript, copied
  unchanged from its engine, run over 689 waters and 24 charts, 798 dosing cases, 36 simulator runs and
  the small charts' data (`farm/tests/deffeyes_reference/driver.ts` makes `reference.json`, how is in its
  header): every value agrees within the table's rounding (DIC, NH₃ and H₂S within 1e−8 relative, the
  constants within 5e−8 pK, CO₂ within 3e−6 for the molar mass, the borders within 1e−6 pH, the boundaries
  within the source's 4-decimal points, the doses within 2e−5 for the molar masses); every recipe, added
  by the simulator, ends at its target; the simulator's pH after NaHCO₃ and NaOH against Plummer &
  Busenberg's constants solved on their own; the alkalinity a gram of each base gives against the
  stoichiometry (1.68 kg NaHCO₃ per kg as CaCO₃ ...); Weiss's K0 against Dickson et al.'s check value and
  Plummer & Busenberg; the chart's lines and regions against the formulas, the point at its coordinates;
  the page, its live parts, the report and the values of a unit in each language. What the source did
  wrong is in the bug document (WQ-30 to WQ-46).
- **Not ported**: the fish type and size (they changed nothing, WQ-37: here the fish come with a unit),
  the measurement points' reading sources and sensor sets of the values bar (no sensors here yet).

**A unit's own chart** (`/operations/water/units/<id>/chart/`, for the monitoring cards' window): the same chart
and calculation, from the latest readings of one of the unit's sampling points (its middle point by default,
`?point=` another of its own active points, 404 for any other) and the limits of its fish
(`calculation.chart_of`). It never makes a value up: a unit chart refuses and lists the readings the point lacks
(temperature, pH, alkalinity, salinity), or says that the unit has no middle point and lists its points, or that
the pH and the alkalinity cannot go together (`deffeyes.why_impossible`, the calculator's own check). The one
assumption is a fresh-water unit's salinity of 0 (`read.assumed_salinity`, also the ammonia's rule), shown as
"assumed". The temperature is the point's own, else (A9) its loop's fresh one when it has none. TAN, oxygen and the site's altitude are drawn
when there; no total sulfide or calcium is measured, so there is no H₂S or Ω layer, and a limit the fish do not
have is said, not drawn. Each reading shows its age, status and point; the chart's SVG ids carry the point
(`uid`), so several windows on one page never clash. The endpoint needs only the right to read water samples.
The chart is drawn from the LATEST values received (owner decision 1, 2026-11-12: "it should be drawn according to the
latest data that came in"): an input that is no longer fresh does not refuse it. It is never silent about it:
`ChartInput.old` and `UnitChart.old` name the inputs that are old at the chart's moment, and the window says
"Last known position." above the chart with each old input and when it was measured, and "old" on its row.
`calculation.charts_of(units, water)` is the same chart for many units at once (a wall of monitoring cards): from the
water the caller already holds, with one read of the fish's limits for all the units (`read.limits_of`), each answer
`chart_of(unit)`'s figure for figure (`farm/tests/test_charts_of.py`).
`calculation.inputs_from` is the one mapping from field values to the analysis, used by the calculator's form
and by this chart. Still to come: total sulfide, calcium and H₂S become parameters (a column each, a migration,
a limit parameter for H₂S); the pH and the alkalinity are taken from the same sample, or their age difference
is shown, since the latest value of each may come from different samples (the calculator shows each value's
age); and a point's history can draw its samples as a track.

**Who may do what**: the area Water chemistry (Production · Operations): Read the page (the calculator
too), Create records a sample or a round, Delete voids one; the area Water limits (Production · Setup ·
Reference data) with read, create, edit and delete; the area Sampling points (Production · Setup · Facility
structure) with read, create, edit and delete.

**Deleting**: a unit, a system or a piece of equipment keeps its sampling points, and they their samples, out of
sight while it is deleted (the links are `DO_NOTHING`; the confirmation counts both) and back when it is restored,
as its stock lines are: points are history of their owner, not a part deleted with it. A species takes its water
limits with it, each listed and logged. The admin shows voided samples but does not restore them.

**Alarms.** A warning or a critical value is shown on the page, on the unit in Production units (its columns, dot, count
line and drawer) and as a tile of the production overview, and it raises an alarm (Company › Alarms, see Alarms): its
recipients are notified by push, it escalates when nobody acknowledges it, and everything is kept. Nothing is sent yet:
the push transport comes with the mobile app, and the pages say so.

Differences from the source (details in the bug document, WQ-01 to WQ-49):

- One store of limits, per species and water type, read by the one evaluator; the source had seven that
  disagreed and never applied its species limits (WQ-01, WQ-02, WQ-24).
- Typed columns with one unit and basis each and plausible ranges in the database, instead of a JSONB
  bag, free-text units and ammonia and nitrite of no basis (WQ-03, WQ-07, WQ-23).
- Status on read, per parameter, from the latest value of that parameter (WQ-04, WQ-05, WQ-06, WQ-21);
  two bands (WQ-09); nothing is required but one value (WQ-08).
- The time and the person are the server's rules (WQ-10, WQ-11); samples are voided, never edited or
  erased, and every change is logged (WQ-12); loop samples can be recorded (WQ-13); real foreign keys
  (WQ-14, WQ-15); a round skips empty rows (WQ-16) and is translated (WQ-17).
- The oxygen saturation is worked out from mg/L (or the reverse) at the site's altitude (WQ-27); TGP is
  a parameter (WQ-25).
- A sample is at a sampling point of a fixed kind, with the flow and the share of the outflow of the points on a
  stream, never at "nowhere" and never with an owner spread over loose columns (WQ-47, WQ-48, WQ-49).
- The calculator's chart keeps the H₂S limit in its safe zone, draws one when ammonia cannot reach its
  limit and none when a limit it needs is missing (WQ-30); sulfide goes in as S and H₂S comes out as H₂S
  (WQ-31); Ω only where its constants hold (WQ-32); the axes hold the point (WQ-33); a border off the chart
  is said in words (WQ-34); CO₂ is judged against its limit (WQ-36); every input is checked (WQ-37,
  WQ-38); K1 and K2 are cited to their paper (WQ-39). Its dosing finds the base-and-stripping recipes
  (WQ-40), shows an acid overdose as acid (WQ-41), judges each step as the water is (WQ-43), says the
  amounts are of the pure substance (WQ-44) and flags stripping below the air's CO₂ (WQ-45); its small
  charts keep the water on them (WQ-42).
- Not ported: sensors and their reading sources (their channels, the priority of a primary and a backup source,
  the inheritance of a site's values), charts and daily means,
  notifications, H₂S as a sample parameter, the other lab
  parameters, detection limits ("< 0.02"), attachments, limits per life stage or site, a sampling plan
  per unit, and a site's intake water. The rations read the latest water temperature from here and keep
  no copy of their own (WQ-02; `farm/feeding/temperature.py`).

### Setup › Facility structure › Sampling points (`/sampling-points/`)

Table `water_sampling_points`: **where in the water a sample is taken**, so that every sample says exactly where and
a mass balance can later be run on it (concentration × flow at every inlet and outlet of a unit, a loop or a piece
of equipment). A point is owned by **exactly one** of a unit (a tank, pond or cage), a system (its loop) or a piece
of equipment (a biofilter, a degasser, a drum filter, a pump): three nullable keys and a database check that one of
them is set. It has a name, unique among its owner's live points whatever the case (a deleted point frees its name),
and a **kind** from a fixed list in code (`farm/models/water_point.py`; not reference data, because the balance must
know what each kind means). Each kind has one **flow role**, the one place that says it (`FLOW_ROLE`, `flow_role`):

| Kind | Role | Meaning |
|---|---|---|
| Inlet | stream in | the water entering the owner |
| Middle | within | the owner's own water: a unit's bulk, a loop's sump, the inside of a piece of equipment |
| Depth point | within | water taken at a depth (`depth_m`: a cage or a pond) |
| Outlet | stream out | the water leaving the owner |
| Side outlet | stream out | a tank's sidewall outflow |
| Bottom drain | stream out | a tank's bottom-drain outflow |

What each owner can have (`kinds_for`; checked on the form): a tank all six, a pond an inlet, a middle, depth points
and an outlet, a cage a middle and depth points, a loop an inlet (make-up water), a middle (the sump) and an outlet
(discharge), a piece of equipment an inlet, a middle and outlets (a drum filter two: the clean water and the backwash).
An owner has **one active middle point**, the one that stands for its water (a partial unique index per owner).

The optional figures, each a column and a database check: `flow_m3_h`, the design or last-known flow of the stream
(0 to 100,000 m³/h), on the points on a stream only (inlets and outlets); `flow_share_pct`, 0 to 100, the share of the
owner's outflow that leaves at this outlet (a side outlet 90, a bottom drain 10), on outlets only; `depth_m`, 0 to
200 m, on a depth point only, which must have one (and the form refuses one deeper than its unit). A kind's form
hides what it does not use, and what it did use before is emptied when the kind changes (as a unit's kind-dependent
fields are). Nothing here is measured.

**The rule no check can hold.** An owner's active outlet shares add up to **at most 100 %**, which spans rows: the
form refuses a share that would take them past 100 (`SamplingPoint.clean`, run by the form and by a restore) and
the list says so when the shares an owner states do not add up to 100 % (less is allowed: a stream not yet described).
Two people saving two outlets in the same second can pass 100 together, since nothing locks the owner there; the
list then reports it ("more than 100 %") until someone corrects it. An owner whose outlets state no share is not
reported: nothing is claimed about it.

**Status.** A point is active or inactive. A point that has samples (voided ones too) cannot be deleted, with a
message that says so: they stay in the history, so it is made inactive instead, which keeps them and takes no new
sample (the sample dialog does not offer it, the service refuses it). A point without samples is deleted like any
record (soft, logged, its name freed). Inactive points are left out of the water rounds, the dialog and the sources
of a unit's water; the history shows them.

**The default points** (`farm/water/points.py`: the one template and the one service, `create_defaults`): a tank an
inlet, a middle, a side outlet and a bottom drain; a pond an inlet, a middle and an outlet; a cage its middle; a
system "Loop" (kind middle); a piece of equipment none. The Tanks and Systems tabs call it when a record is created,
in the same transaction, so each point has its row in the activity log. The names are stored as written (English, like
any name a person types; the kinds are translated). A unit or system made by another route (a script, a test) has no
points until the function is called: Production units says so on its drawer and Latest has a row for it. Migration
`farm/0019_water_points` made them for the units and systems that existed, and put every existing sample on the
middle point of its unit or loop ("Middle" or "Loop").

**The tab**: a table (owner, point, kind with its flow role, flow, share of the outflow, depth, status), search by
point or owner, filters by site, owner type and kind, and `?unit=`, `?system=` or `?equipment=` to show one
owner's points (the units, systems and equipment lists link to them); the form asks for the owner first (chosen once,
the form is drawn again with that kind of owner's choice and kinds), then the name, kind, status, description and, for
the kinds that have them, the depth, the flow and the share. A point's History link opens its samples on Water
chemistry. The activity log names it "sampling point" and records every field. The admin lists every point, deleted
ones too, and restores one (the restore checks it like a new one: its name and its single active middle point).

**Deleting an owner** keeps its points out of sight with it (see Water chemistry, Deleting); the delete
confirmation of a point is the one of any record and says why a point with samples cannot go.

**Preparing for a mass balance.** What is stored: for every owner, its points with their kind and so their flow
role, a design or last-known flow on each inlet and outlet, and the share of the outflow of each outlet, all of them
tied to the samples taken there (concentration at the point). What a future balance still needs, none of it built here:
- **Stream links**: which outlet feeds which inlet (a tank's side outlet to the drum filter's inlet, the filter's
  clean outlet to the biofilter's inlet, a loop's make-up inlet to the supply), a table of point to point rows, so
  that the streams between pieces of equipment form a graph the balance walks. A point on a unit and a point on
  equipment need no change; the link is a new table pointing at two points.
- **Measured flows**: a flow over time at a point (from a flow meter or a pump's curve), read where the design flow
  is now; `flow_m3_h` stays the figure to use when none was measured.
- **Sensor channels assigned to points**: a sensor's channel belongs to a point (the source binds a channel to a
  point, a position and a depth: WQ-47), so that a continuous series stands beside the manual samples at the
  same place and the balance can use either.
- **What a point's water is at a moment**: the latest sample at or before it (`read.Series`, `read.samples_of`), the
  mass flow being concentration × flow; the loss of a piece of equipment its inlet less its outlets, per parameter.

**Who may do what**: the area Sampling points (Production · Setup · Facility structure): read, create, edit and delete,
each for the tab; recording a sample at a point is the Water chemistry area's.

### Operations › Storage (`/operations/storage/`) and Facility › Storage locations (`/storage-locations/`)

The store: where the farm keeps feed (medicines once the health module's `Medicine` is in; chemicals and
consumables when their records are ported), the lots it holds, and what came in and went out. Its own app,
`inventory`, with its own tables and migrations: `storage_locations`, `inventory_items`, `inventory_lots`,
`inventory_operations`, `inventory_lines` and `inventory_reorder_levels`.

**Storage locations** (Company › Facility, a `core.crud` tab): a place on a site where stock is kept, a
warehouse, a silo, a cold room, a chemical store, a medicine cabinet or an outdoor store. A table (location
with its code, site, kind, feeder, capacity, **on hand now** worked out from the book with its number of
lots, status), search by name or code, filters by site, kind and status, a form in the dialog with two inner
tabs (General: site, name, code, kind, status, feeder; Capacity and notes) and a third, **Reorder levels**,
saved as a list (one row per feed: the quantity below which the overview says the stock is low). The site is
chosen once, at creation. A silo is a location, not equipment, and may name the feeder it fills (a feeder of
its site; only a silo has one). The capacity is optional, in kg or in units counted (owner decision Q-S2):
above it the overview warns and nothing is refused. An inactive location takes no new stock; what it holds
still shows and can leave. Code unique among live locations, name unique within its site, capacity and its
unit together, the feeder only on a silo: database checks, with the message on the field. Every optional
field can be cleared.

**The ledger.** An item (`InventoryItem`) has exactly one link, to a feed now (a database check); the person
never picks an item, they pick a feed and the write path finds or makes its item. A lot (`InventoryLot`) is
its number and expiry as printed on the bag, optional for feed and required for medicines (owner decision
Q-S5): a delivery that names a known lot reuses it (any case), a different expiry for it is refused, feed
without a printed number is one lot per expiry. An operation (`InventoryOperation`) is what a person did,
with its date on the clock of the sites of its locations: a **delivery** from a supplier (lines of lots into
locations, a cost per kg with its currency, the supplier's own document number, the one free text: a number,
not a link), an **issue** (taken out for something other than feeding: a treatment, samples, maintenance), a
**write-off** (expired, damaged, contaminated, spilled), a **return to the supplier** (it leaves the store), a
**transfer** (one lot from one location to another, on the same site or another, owner decision Q-S6) or a
**count** (one location at the end of a day). Its lines (`InventoryLine`) say how much of which lot came into
(+) or left (−) which location, or was counted there. Nothing about the quantity is stored anywhere else.

**Feeding never waits for the store.** The feed given is read from the feeding records of the units of a
site (the unit's production department's site), per feed and day, and drawn on read from the site's lots,
first expired first out (lots not expired that day by expiry, a lot without one last, then the day it first
arrived, its number, the location's code; then expired lots, which the overview reports). What the book
cannot cover is **feeding beyond the book**, per site and day: shown on the overview and the item's page,
never refused, and never filled by a later delivery (owner decision Q-S1): it is fixed by recording the
missing delivery, dated on or before the day (within the backdating window). Every unit that takes fish is on a
site (F-212), so every feeding draws on a store; a unit left without a site before takes no fish and
`check_stock` names it.

**The fold** (`inventory/fold.py`, pure; `inventory/read.py` loads it), per item over every location of every
site, day by day: arrivals, departures, the feeding's draw, counts. The lines are facts and the feeding is an
estimate of which lots were fed (a record names no lot), so a departure is checked against the book of the
lines alone (it may never take a lot in a location below 0, on its day or later), and the feeding draws only
what no later departure of the same lot needs. A count sets every lot of its location to the quantity
counted (0 for one it does not list) at the end of its day; its variance is the counted quantity less the
book just before it, feeding of that day included, **worked out on read, never stored** (owner decision
Q-S7). One person records a count; there is no approval step.

**One write path** (`inventory/services.py`, `_commit`): it locks the items, then the locations, each in
primary-key order (a feeding takes no lock), refuses a form sent twice (its token), checks the date on the
clock of every site it touches (`farm.stock.dates.check_site_date`: the farm's today at the latest, at most
the correction window back), live locations, arrivals into active locations only, a live supplier that
supplies the item's category (feed), lot number and expiry where the category needs them, then writes the
operation and its lines and folds every item it touches from its first line: a backdated operation is placed
where it belongs and accepted only if every later day stays right ("The write-off of 3 Nov from WH-1 would be
left without its stock: … Void that operation first, or correct this one."). A supplier keeps the categories
its live deliveries and returns need (`SupplierLink.category_field`). Every operation, void and new lot is in
the activity log.

**Void** is the farm's one void (`farm.stock.services.voided`, on the clock of the operation's sites): a
reason, within the backdating window, struck through in the history, "Voided" in the log; refused when a
later departure needs its stock (the message names it), or when a deleted location would hold stock again. A
lot left without live lines is voided with it, so its number can be delivered again with another expiry. A
correction is a void and a new entry; nothing is edited.

**The page** has four tabs in the address (`?tab=`) and the actions Receive delivery, Transfer, Issue, Write
off, Return to supplier and Count a location, each a dialog (the shared dialog or a page, the server's
reasons on their fields, back to the page it came from):

- **Overview**: feeding beyond the book (per site and feed, since when, a link to the day-by-day book) and
  expired lots fed; **a feed that was fed and never delivered** (it has no item yet: an item is made at the first
  delivery or reorder level) is named too, with all its feeding inside the correction window as the shortfall ("32 kg
  of Grower 4 fed at Bergen since 12.11.2026, and none of it was ever delivered to the store …": `read.undelivered`
  folds it as an item without a line, by the same fold; `inventory/tests/test_undelivered_feed.py`); per site and item the stock on hand, the feed of the last 7 days and the **days of
  cover** (on hand ÷ the kilos fed a day there over the last 7 days); low stock (on hand of an item in a
  location below its reorder level, owner decision Q-S4: what a purchasing agent will read to propose
  orders); over capacity; lots expiring within 30 days and expired lots with stock; the value on hand per
  site and currency (on hand × what the lot cost when delivered), never added across currencies.
- **Stock**: a row per lot in a location (location, item, lot, expiry with an Expired badge, on hand, last
  movement, value) with Transfer, Issue, Write off and Return, each with the lot and its location already
  chosen; filters site, location, item and Show empty; totals per site and item. The item's day-by-day book
  (`items/<id>/?site=`: in, out, fed from the book, fed beyond it, the count difference, the stock at the end
  of each day) and the lot's trace (`lots/<id>/`: its deliveries and supplier, moves, departures and counts,
  voided ones struck through, and the feeding estimated to have drawn it) are pages of their own.
- **Movements**: the operations, newest first, 50 a page, each with its lines, supplier and document number,
  who recorded it and when, notes, and Void while allowed; filters site, location, operation, item, supplier,
  from and to (whole farm days), Show voided. The operation "Feeding (from the records)" lists the feed given
  per site, feed and day, each linked to its feeding records.
- **Counts**: each count with its variance per lot (book, counted, difference), who counted, Void while
  allowed, and Count a location. The count dialog lists the lots the book has in the location at the end of
  the chosen day (changing the location or the day renders it again, nothing saved); each must be filled in,
  0 when none is left; lots found that the book did not have there are added as rows (a feed, a lot number
  and expiry: a known lot is reused, an unknown one is made, its supplier unknown).

**Who may do what:** the area Storage (Production · Operations): Read the page, Create records a delivery,
an issue, a write-off, a return, a transfer or a count, Delete voids one; the area Storage locations (Company
· Facility) with read, create, edit and delete (editing includes the reorder levels). **Deleting**: a location
that holds stock cannot be deleted, so neither can its site; an empty one goes with its site. Deleting the
feeder leaves the silo without one (logged). A feed with an item of the store, and a supplier named by a live
delivery or return, cannot be deleted (`PROTECT`: traceability one step back). A deleted location keeps its
lines and counts. `manage.py check_inventory` checks the whole store from scratch (operations made of their
lines, transfer pairs, the suppliers' categories, lots that need a number and expiry, no departure below 0 in
the book of the lines, no deleted location with stock) and the tests run it. The admin shows voided operations
and lots and does not restore them.

**For the health module (Medicine):** the second link of `InventoryItem` (`medicine`, `PROTECT`, null), the
exactly-one check (`feed` xor `medicine`) and the `category` expression (a medicine → `medicines`) change in
one migration of `inventory`; `LOT_REQUIRED` already requires a medicine lot's number and expiry; the
delivery line and the count's found rows offer the medicine beside the feed, and `STOCKED` in
`inventory/forms.py` gains `medicines` so the suppliers of medicines are offered; a medicine's unit is then
chosen from `Unit`. Consumption from a treatment is read like the feeding (storage §3.8).

Differences from the source (details in the bug document, STR-01 to STR-28):

- One ledger and quantities on read, instead of a projection, a log and a total on each product that the
  master forms could overwrite (STR-08, STR-15); feeding is read from the records and never refused (STR-01,
  STR-10), per site, never from another site's store (STR-11).
- Every reference is a foreign key: item, lot, location, site, supplier (STR-12, STR-13); a return takes stock
  out (STR-03); a count corrects the book, there is no "adjustment" (STR-02); a count's variance is read
  against the book of its day (STR-05); a departure names its lot in its location from a list (STR-06,
  STR-07, STR-18); a transfer is one operation through the one write path, with the form's token (STR-07).
- Every movement is dated on its day on the site's clock (STR-17, STR-26), the overview never adds kilos to
  units or one currency to another and has no fake fill rate (STR-20), a location keeps its site (STR-21).
- Not ported: purchase orders (phase 2, owner decision Q-S3: the delivery keeps its supplier and the
  supplier's document number, and an order line link can be added to the delivered line later), chemicals,
  consumables and healthcare without a master (STR-04), lot-mix relabelling (STR-19), temperature and humidity
  ranges, the `hazmat` kind, count approval, a feeding record's lot, silo-first draw through the feeder, spare
  parts (STR-28), barcode scanning.

### Operations › Harvest (`/operations/harvests/`, `/operations/harvest-plan/`, `/operations/production-plans/`), Setup › Harvest and logistics › Slaughter facilities (`/slaughter-facilities/`) and Setup › Reference data › Handling rules (`/handling-rules/`)

What was harvested, where it went, what is planned, and what must be known before fish are handled. Tables
`slaughter_facilities` (with `slaughter_facility_species`), `harvest_records`, `production_plans`,
`handling_plan_items`, `handling_rules` and `handling_acknowledgements`.

**One ledger, no second stock.** A harvest is still the stock operation of Production units (`record_harvest`
through `_commit`): its fish, its round kilos and its date stay on its line and the operation. What a harvest
adds is its `HarvestRecord`, 1:1 with the operation (its primary key): the **slaughter facility**, required,
the **transport** supplier (a supplier of wellboat and transport) and the **wellboat or vehicle**. It is written
in the same transaction and never edited: voiding the harvest voids it with it (every read goes through the
live operation). `check_stock` reports a live harvest without its record and a record on another kind of
operation. Harvests recorded before the record existed have none: check_stock lists them as data from
before the rule (their facility is unknown).

**The harvest dialog** (a unit's drawer, or "Record harvest" on a plan) asks the fish, the **round weight
(kg)**, the live weight as weighed before bleeding and gutting (the old label "Weighed (kg)" did not say which
weight it was), "this empties the unit", the facility (active ones that take the batch's species, or that
list no species), the transport and the vessel, and shows the handling check (below). After saving, the drawer
shows the harvest as "520 kg weighed · book 500 kg · +20 kg (+4.0 %)" and "To Fjord Slakteri (M123) ·
Brønnbåt AS · MS Ronja".

**Harvested** (`/operations/harvests/`): one row per harvest, newest first: date, unit with its production
department and site, batch and species, fish, round weight, average weight (round kilos × 1000 ÷ fish), the
**book** kilos (what the fold took out for the harvest line: the batch's average in the unit, the last fish the
rest of the book), the **difference** in kg and % of the book, the unaccounted loss of a harvest that emptied
the unit (its fish and book kilos), facility and approval number, transport and vessel, who recorded it, the
plan it fulfilled and a badge when a handling warning was acknowledged. Filters in the address: site,
production department, unit, batch, species, facility, from and to, and "Show voided" (struck through with
the reason, counted nowhere); 50 a page; the count line ("2 harvests · 510 kg round weight, 490 kg in the
book") and **totals per batch and per site** of the filtered rows (harvests, fish, round weight, average, book,
difference). Everything is computed on read (`farm/harvest/read.py`).

**Harvest plan** (`/operations/harvest-plan/`): planned harvests (to a slaughter facility) and planned
transports (to another unit) of one batch's fish in one unit on a day, with the fish and round kilos meant, the
transport and vessel and notes. The kind is chosen once; the batches follow the unit and the facilities the
batch's species. The **status is derived**, never set: cancelled when it has a reason ("Cancelled because";
clearing it plans it again), done when the operation that fulfils it counts, overdue when its day has passed,
planned otherwise. **Record harvest / Record transfer** on an open item opens the stock's dialog started from
it (unit, batch, date, fish, facility, transport, vessel, the destination unit) and the service links the
operation to the item in the same transaction; it is refused for a deleted or cancelled item, one recorded
already, another kind of operation or other fish. Voiding that operation plans the item again with nothing to
change. Planned against actual: the fish and kilos of the linked operation (a harvest's round kilos, a
transfer's book kilos). Each open item shows the fast it asks of its unit ("Fasting before the harvest of 15 Nov
2026: from 12 Nov 2026, 00:00 (72 h)") and a medicine withdrawal on its day. A plan names fish that are in the
unit, a day inside the backdating window at the earliest, and, for a harvest, an active facility that takes the
species; a done item cannot be cancelled (void its operation first). Nothing requires a plan: a harvest is
never refused for lacking one (the source's HRV-05).

**Production plans** (`/operations/production-plans/`): every batch in stock in each unit it is in, with its
fish, book average and when it was weighed, its **target weight** (one live plan per batch; "Set target" or the
weight, to edit), the batch's expected harvest (entered at stocking: one fact, one place), when the fish were
last fed and a medicine withdrawal; **Plan harvest** starts a planned harvest of the share at the target weight
(fish = the share's count, round kilos = fish × target, on the day the target is reached). Plans of batches no
longer in stock follow. **The estimated weight now** is the feeding protocols' estimate (Operations › Feeding);
**the day the target is reached** walks it forward a day at a time (`farm/harvest/forecast.py`): each day the fish
eat that day's ration (the protocol in force, the band at the weight reached, its SFR at the unit's latest
temperature, held constant and shown) and grow by it ÷ the band's expected FCR; a fasting day before a planned
harvest or transport gives no growth; no protocol, a weight outside the bands or no temperature stops it with the
reason, never a default, and so does two years without reaching it. Nothing is stored.

The page reads its rows together, not one by one: the withdrawals in force of every unit shown in one ask of the
registry (`check.holding_of`), every row's earliest suitable harvest date in one pass (`check.earliest_of`), the last
feedings of the stock in one read (`feeding.read.last_fed_in`, what the units list says, without walking the
feedings), and the forecast: one projection walk plus a per-batch walk of up to 730 days for a batch with a target.
Nothing is kept between requests, so nothing can be stale. Measured on the development data (20 rows, warm median of
5, on a loaded machine, 22.11.2026): 825 queries and about 10 s before, 131 queries and about 1.8 s after; the page
is the same byte for byte with the clock pinned, and its query count does not grow with its rows. The tests
(`farm/tests/test_production_plans_reads.py`) hold the set reads to main's one-at-a-time reads as they were before
them (copied into the test as the oracle) and to fixed dates, at five frozen moments on three site clocks, and the
page to at most 60 queries at 3 and at 9 units. What is left is mostly the forecast's walk of the feedings and the
last feeding's read of every feeding since the fish came in.

**Slaughter facilities** (Setup › Harvest and logistics): name, Mattilsynet's approval number (godkjenningsnummer, 1
to 6 letters or digits, stored in capitals, unique among live facilities; the format is the source's and is not
verified with Mattilsynet), the operator (a supplier of the new category **Slaughter and processing**, which
keeps that category while it operates a facility), address, municipality, coordinates (both or neither), the
species it takes (none: every species), capacity in tonnes a day, active or inactive, notes. There is no
"default" facility (HRV-09): every harvest names its own (HRV-08). A facility harvests went to is not deleted
("1 harvest record still belongs to it. Set it inactive instead."), and a supplier named as a harvest's transport
keeps its category and is not deleted either (`Supplier.delete_blockers` asks every SupplierLink, and a link from
a record the delete plan does not follow says it blocks, `SupplierLink.blocker`).

**Handling rules** (Setup › Reference data): per kind of handling (harvest, transport, grading, treatment) and
species, or for every species (no species), how long the fish must have been without feed and where the value comes
from. **The fast is typed as a number with a unit, hours or days** (the same form for every kind) and stored in the one
hours column (5 days is 120 hours; 0 to 720 hours, 30 days); a rule of whole days is shown back as days, in the form and
in the list ("5 days (120 h)", "36 h"). A **harvest** can also ask for **purging in degree-days**: the fish are held
without feed, in clean water, so that any off-flavour clears; only for fish that are harvested and sent to the factory
(a database check: degree-days belong to the harvest rule alone). A rule has hours or days, degree-days, or both (a
database check); with both, each must be reached and the later decides. One live rule per kind and species, and one for
every species (the database's `NULLS NOT DISTINCT`, checked on the form too). **These are the farm's own rules; the starting values are to be
checked with your veterinarian.** Migration `0017` writes four general rules, each with its source:

| Handling | Hours | Why |
|---|---|---|
| harvest | 72 | Mattilsynet asks for no feed left in stomach and gut at slaughter (an outcome, no hours). Gut-clearing feed withdrawal is typically 48–72 h ([Hvas et al. 2024, *Reviews in Aquaculture*](https://munin.uit.no/handle/10037/33239)), slower in cold water; [BIM 2024](https://bim.ie/wp-content/uploads/2024/05/BIM-Fish-Welfare-During-Handling.pdf) and RSPCA (2015) advise no more than 72 h before harvest. |
| transport | 24 | BIM 2024: feed withdrawal at least 24 to 48 h before crowding, by water temperature and fish size. RSPCA (2015, T 2.9) caps pre-transport fasting at 48 h unless a vet specifies it: a maximum, not a minimum. |
| grading | 24 | BIM 2024: at least 24 to 48 h before grading; RSPCA (2015, FW 6.2): not above 48 h. A grading is also checked against the transport rule; the longer applies (owner). |
| treatment | 24 | BIM 2024: commonly 24 to 48 h before handling; RSPCA (2024): at most 48 h before physical delousing, 72 h before a freshwater bath. The medicine's product information wins. |

**The handling check** (`farm/handling/`, one for every dialog): before fish are harvested, is a medicine
withdrawal in force, and before they are harvested, transported (a transfer), graded or treated (the health tab's
dialog), have they fasted long enough? Nothing is blocked (owner decision): both are warnings.

- *Fasting*: the hours from the fish's **last feeding** to the **start of the handling's day** on the site's
  clock (an operation has a date and no time), and, **for a harvest whose rule asks for purging, the degree-days**: the
  sum of the batch's daily mean water temperatures of the **full days after the day of the last feeding up to the day
  before the harvest** (the day of the feeding and the harvest's own day are not counted). A day's temperature is the
  one the medicine withdrawal adds up (`farm/water/degree_days.py`, one definition for both: the unit's middle point,
  else its system's loop; a past day without a measured temperature counts at the species' assumed temperature, else as
  0 °C, and the warning says so). Each thing the rule asks for must be reached, so the warning shows each: "Last fed
  3 Nov 2026, 02:52, 48.0 h and 36 degree-days before 6 Nov 2026: the harvest rule asks for 72 h and 60 degree-days." **The fast is of the fish in the unit
  handled** (the owner, 14.11.2026: fish of two batches in one unit are one group; flow fault S-01): one fast for the
  unit, whichever batch a dialog names, counted from the latest feeding of production fish along the fish's own path
  (`farm.feeding.read.last_fed_of`, `Paths`): this unit's feedings since each of its batches came into it, the
  feedings of the unit they came from up to and including the day of the move (a move has no time), and so on back;
  **a path is cut at a place in the ledger's own order** (the day, then the order the operations were entered: the
  order the transfers happened in), never at a day, so a unit emptied and refilled on one day, a move there and back
  and a grading day (the fish moved out before others came in) keep the true last feeding of the fish now in the
  unit; where a day leaves a doubt the day counts in both units (over-warned, never under-warned). The ledger is
  indexed once for every unit asked (`Paths`; a test counts the reads of ledger lines, not seconds), and the pages'
  `figures()` hands the reader the lines its own walk folded, so the units list, the drawer, the plans and a wall of
  cards cost no query more than before (`monitoring.tests.test_budget`);
  never a unit the fish were not in, nor their old unit after they left it, so a sibling tank fed after a split does
  not break the fast of the fish that were moved, and the least-fasted fish of a mixed unit decide. The sentence, the
  acknowledgement row (`handling_acknowledgements.feeding`, farm 0039, which goes back only while no row names a
  feeding: `farm/tests/test_migration_feeding_acknowledgement.py`) and the critical log line name the feeding's
  unit ("Last fed 09.11.2026 09:00 in T-01, 87.0 h before …"), and when that unit is on another clock than the unit
  handled, the moment on both. The one reader also gives "Last fed" on the units list, the drawer ("in T-01, before
  the fish were moved here"), the production plans and the cards (`farm/tests/test_fast_of_the_unit.py`, the cases of
  the panel's rules). A record without a time counts from the end
  of its day and a feeding on the day gives 0 h, so **the fast is never overstated**; the sentence names the feeding
  once, as it is true: its day and time, or its day and "(no time recorded: counted from the end of the day)", never
  the counted moment as a feeding time, and a feeding on the handling's own day reads "Fed on the day of the handling
  itself (09:00): no fast before …", with the unit when the fish were fed in the unit they came out of that day
  ("09:00 in T-01") (with a warning the notes do not repeat the feeding;
  `farm/tests/test_fasting_sentence.py`) (and the degree-days of several
  batches in a unit are the fewest). The rule is the species'
  own, else the one for every species; a grading takes the longer of the grading and the transport rule. No
  rule, or no feeding in the 31 days before (longer than any rule), is said, not warned.
- *Medicine withdrawal* (**a harvest and a live delivery**: the fish leave the farm and may be eaten, slaughtered
  at the facility the harvest names or sold alive; the owner's decision 12 of 19.11.2026: a live delivery of held
  fish is warned through the same check, "Not suitable for a live delivery — medicine withdrawal of B-2026-001: the
  fish may leave the farm from 21.11.2026. Fish sold alive may be eaten.", ticked, stored as a handling
  acknowledgement and logged as critical, as a harvest is, and never blocked; `check.WITHDRAWAL_OPERATIONS`. A
  delivery's warning is in its own words, never "harvest from …" (`withdrawal.leave_from`, "from about …" when
  projected, "end unknown"), its shared-unit sentence says the fish "cannot be told apart when they are caught", and
  its dialog shows the earliest suitable date as a harvest's does (below; review of S-03 at 6776780, F-1). **A
  live delivery is a harvest also after the fact** (the owner's decision 13 of 19.11.2026): a later write that puts a
  recorded delivery inside a withdrawal asks as for a harvest (the withdrawal guard, below). A medicine withdrawal is a meat withdrawal, so it means
  nothing when live fish are moved or graded on the farm, where the fast and the live-transfer facts are what
  matter, and a treatment during a withdrawal harms nobody): every block
  a registered provider gives for the **unit** whose end is after the day, or unknown (unknown is a warning, never
  clear). The withdrawal is the unit's, never the chosen batch's: a net cannot separate the batches of one unit, so
  the withdrawal of any fish in it holds a harvest of it, whichever batch the dialog names (`check.in_force(unit, day)`
  takes no batch). The warning names the batch that is held and, when the unit holds other fish beside it, says "It
  holds every fish in T-02: the fish of different batches in one unit cannot be told apart at a harvest."; the
  acknowledgement row keeps that batch, the earliest suitable harvest date and the plan rows read the same blocks, and a
  harvest locks every batch in its unit (`farm.stock.services._locked_for`), so it and a write that changes one of
  their withdrawals take turns (`farm/tests/test_withdrawal_shared_unit.py`). **A batch holds a unit on a day when it
  had fish there at any moment of that day** (`farm.stock.read.Presence.during`: at the end of the day before, or fish
  of it came in that day), so held fish that come into a unit and leave it again the same day still hold it that day:
  the other batch's harvest out of it warns and takes its tick, and `check_withdrawal` lists it, and the fish that were
  beside them stay held to the same end after that day, wherever they go (the lots, flow fault S-03: Operations ›
  Health, the medicine withdrawal); the same question says
  which fish a course reached (`farm/tests/test_withdrawal_same_day.py`; the stock books' `Presence.present`, the ends
  of the days, is unchanged). **Cleaner fish beside the production fish are kept apart** (`check.held_apart`; the
  owner's decision of 16.11.2026): their withdrawal is no warning on the production fish's harvest, no acknowledgement of
  theirs and not their earliest date; the dialog says it as a note ("Cleaner fish in C-01 are in a medicine
  withdrawal (B-2026-004, harvest from 19.11.2026): keep them out of the harvest."; a live delivery's dialog in a
  delivery's words, "… (B-2026-004, the fish may leave the farm from 19.11.2026): keep them out of the live
  delivery."), and the unit's own line still shows it (`farm/tests/test_withdrawal_cleaner_fish.py`). The health records register their provider in `farm/apps.py` (`farm/handling/withdrawal.py`:
  `register(provider)`, `blocks(unit, day)`, `WithdrawalBlock(batch, until, approximate, reason, source)`; see
  Operations › Health). With no provider registered the harvest dialog would say "Medicine withdrawal not
  checked" and warn nothing.
  It reads "Not suitable for harvest — medicine withdrawal of B-2026-001: harvest from 14.12.2026". **A withdrawal's
  end is said in one wording everywhere** (`farm.handling.withdrawal.harvest_from`, the template filter
  `harvest_from`): "harvest from <the first day the fish may be harvested>", "harvest from about …" when projected,
  "end unknown" when it cannot be worked out, never "until <date>" (which read as the last held day on the Treatments
  list and as the first free day on five other pages, a day apart for one withdrawal): the harvest dialog, the drawer,
  the units row, the harvest plan and production plan rows, the Treatments list (which says both days, the last held
  day only with the first free day beside it: "until 13.12.2026 (harvest from 14.12.2026)", `held_until`), the
  earliest suitable date, the
  withdrawal guard's question, the stored critical log line and `check_withdrawal`
  (`farm/tests/test_withdrawal_wording.py`). Not yet in that wording: the monitoring card's badge ("Withdrawal ·
  <date>", `templates/monitoring/_card.html`) and the column label "Withdrawal until" of the two acknowledgement
  tables (a label change is a migration). The informational
  badges (Production units rows, the drawer's Harvest and handling section, the plans) say the same and stay.
- *The dialogs* (harvest, transfer, grading) show the check for the form's date and batch under "Before
  handling": the last feeding and its hours, the rule, for a harvest the withdrawal, and with warnings the box "Go
  on despite these warnings" (the harvest's: "Fish under a medicine withdrawal must not go to food. Going on is
  stored with what is shown here and logged as critical."; the others': "Going on is stored with what is shown
  here and logged as critical."). The box carries the warnings' fingerprint.
- *The save* runs the check again after the locks (a feeding of the unit takes turns with it). With warnings it
  needs the box ticked on exactly these warnings: a feeding recorded meanwhile, a treatment entered or another
  date asks again ("The warnings changed since the form was shown"). Going on stores one
  `HandlingAcknowledgement` per warning with what the person was shown (the withdrawal's end, estimated or not,
  and reason; or the last feeding, the hours fasted and asked, a harvest's degree-days fasted and asked, and the rule;
  a database check says a fasting row has at least one of the two not reached), and the operation's
  activity-log entry is **critical**, with the warnings. Who and when are the operation's.
- *The meal board* gives **no ration on a fasting day**: the ration's policy (`farm/feeding/read.policy`) loads
  the fasts planned harvests and transports ask for (`farm.handling.fasting.fasts`, every day from the one the
  fast starts on to the planned day, in full, for the whole unit; where two overlap the one that starts first
  wins) and `ration.Policy.basis` answers `FASTING` with the reason, e.g. "Fasting before the harvest of 15 Nov
  2026: from 12 Nov 2026, 00:00 (72 h)". **When feeding must stop** for a handling on day D is one function
  (`fasting.start_of_fast`, which the board, the plan rows and the earliest harvest date ask): by hours, the start of D
  less the hours; by degree-days, found **backwards from D**: the day s such that the full days s to D − 1 add up to the
  rule's degree-days, a past day at its measured temperature (or the assumed one, else 0 °C), a day not over or still to
  come at the mean of the unit's last 7 measured days within 30, else the species' assumed temperature; the later of
  the two starts wins. With no temperature to project at, the degree-days are unknown: the hours alone apply and the
  board says "Degree-days unknown: no temperature."; a fast the water never reaches in 60 days starts at 60 and says so.
  It says what it projected, "(72 h and 60 degree-days)", and how many days were counted without a measurement. The band stays, so a feeding recorded anyway is still credited at its
  expected FCR; the production plan's forecast skips the same days. Cancelling the plan gives the ration back.
  The feeding dialog says so on such a day ("A feeding can still be recorded").
- *The earliest suitable harvest date* (`check.earliest`, on a harvest's dialog and the drawer's Harvest and handling
  section, and on each harvest plan item and production plan row): the **later of the end of the batch's medicine
  withdrawal and the first day its purge can be complete from the last feeding** (if it is not fed again), and **which
  decides**: "Earliest suitable harvest date: 17 Nov 2026. Medicine withdrawal decides: harvest from 17.11.2026." or "Earliest
  suitable harvest date: 15 Nov 2026. Purging decides: feeding must stop by 11 Nov 2026." (a tie goes to the
  withdrawal; an unknown withdrawal end is "not known"). It is worked out from the parts above on read, nothing is
  stored; a plan dated before it is marked, and a harvest before it is a warning on the parts' terms, acknowledged and
  logged as critical as before, never a block. A live delivery's dialog says it too, in its own words and with the
  fast of a transport (the rule a delivery's fast is checked by) where a harvest has its purge: "Earliest suitable live
  delivery date: 17.11.2026. Medicine withdrawal decides: the fish may leave the farm from 17.11.2026." or "… The fast
  decides: feeding must stop by …" (`check.earliest(unit, batch, kind=transport)`). A transfer and a grading do not
  say it. A page of many rows asks `check.earliest_of(pairs)`, which reads each input once for all the rows (the
  withdrawals in force, `check.holding_of(units)`, or the caller's, which must name every unit asked; the rule of
  each species; the units' last feedings; the water, `BatchWater.of_each`, read together only for batches whose
  samples are read over the same moments, so each batch's water is the one it has alone, also when a system's loop
  point is on a site of another clock) and gives each row exactly what `earliest` gives it alone (`earliest` is its
  case of one pair; `farm/tests/test_production_plans_reads.py` holds both to main's reads before them).
- *Production units*: a "Withdrawal" badge on a unit with a withdrawal in force today, and the drawer's
  **Harvest and handling** part: the check of a harvest today and the unit's open plans with their fasts.

**The activity log** has a severity: normal, or critical for an operation someone went on with past a handling
warning (`AuditLog.severity`, a database check, a partial index); critical entries have a red edge and a
Critical badge, and the log filters by severity. (An opening balance, the one record dated beyond the correction window,
is critical too.)

**Who may do what** (Production · Operations · Harvest, and Setup · Reference data): Harvested (read; a harvest
is recorded and voided as a stock operation, Production units' Create and Delete), Harvest plan and Production
plans (read, create, edit, delete; recording from a plan also needs Production units' Create), Slaughter
facilities and Handling rules (read, create, edit, delete).

**Deleting:** a unit keeps its plans out of sight while it is deleted (`DO_NOTHING`, counted in the
confirmation, back with it); a deleted destination unit is cleared from its planned transports; a species takes
its handling rules with it and keeps its facilities' link rows; a facility or a supplier a harvest names stays.

Differences from the source (details in the bug document, HRV-01 to HRV-23):

- A harvest is the stock operation, so a harvest empties its unit on every path (the web's "Complete Harvest"
  never moved a fish, HRV-06), and a void is the only undo (edit could cancel without moving stock, HRV-07).
- Every harvest names its slaughter facility; there is no default facility to lose (HRV-08, HRV-09). Round weight
  is labelled as round; gutted kilos and the quality-class split come with the slaughter result, never as a
  default class (HRV-03, HRV-04).
- The withdrawal is a provider's computed end, never an episode's status (HRV-01), read inside the save's
  transaction (HRV-10); the plan shows the check, not "harvest allowed" (HRV-11).
- Fasting is tied to every handling and to the plans (HRV-22); a plan names its unit (HRV-13), its kilos are
  prefilled from the book or the target (HRV-14), and nothing needs a plan (HRV-05); a production plan has a
  target weight (HRV-23).
- Not ported: the slaughter result (gutted kilos per quality class, yield) and Mattilsynet's weekly slaughter
  reports, lot numbers, buyers and prices, customer deliveries, size-grade distribution, an approval workflow for
  plans, temperature scenarios, a "fasted too long" warning (6 days in a slaughter pen, akvakulturdriftsforskriften §
  54), and alarms.

### Operations › Health and Reference data › Medicines

The fish's health: the medicines the farm uses with their withdrawal (Setup › Reference data › **Medicines**,
`/medicines/`), what was given the fish (Operations › Health › **Treatments**, `/operations/health/treatments/`),
what was seen, found or advised (**Health events**, `/operations/health/events/`) and the sea lice counted
(**Sea-lice counts**, `/operations/health/lice/`). Tables `medicines`, `treatments` with `treatment_units`,
`health_events` with `health_event_units`, and `lice_counts`. Typed columns and database checks, no JSON
(the source kept a treatment, its withdrawal and a lab result in five JSON blobs of one row, HLT-07, HLT-15).

**Medicines** (a tab: table, search, filters by kind, administration and status, the dialog, delete): name
(unique among live medicines whatever its case), MT number, kind (sea-lice medicine, antibacterial, other
antiparasitic, antifungal, vaccine, anaesthetic, other), how it is given (bath, in feed, injection, dip), the
active substance, for a sea-lice medicine its substance as Mattilsynet's weekly lice report names it (the
official value is stored, e.g. `EMAMECTIN_BENZOAT`; other medicines have none), the strength with its unit
(both or neither), the manufacturer (a supplier of medicines and vaccines, a `SupplierLink`), prescription only,
status, notes. **Its withdrawal is a list of rows per species** (the **Withdrawal** tab, saved apart from the
medicine details once it exists, like a feed's suitability; table `medicine_withdrawals`): a row is for a species or,
with no species, for every species that has no row of its own (the SPC states it per species), with **degree-days,
days or both, at least one** (a database check; 0 means none; both given, the later end wins), the farm's own
**safety margin** in percent (0 to 200, 0 when empty) on top of the label value, and a note. One row per species and
one for every species (a database check, checked on the form too), at most 50. The label value stays stored as the SPC
states it; the value used is `value × (1 + margin ÷ 100)` rounded up (150 degree-days and 20 % is 180, 7 days and 20 %
is 9; with no margin the label value is used as it is), and the pages say both: "150 degree-days + 20 % safety margin
= 180 degree-days". **Fish of a species that has no row and no row for every species are held with an unknown end**:
"No withdrawal is recorded for Atlantic salmon of Salmosan vet.: add it in Reference data › Medicines." Never
silently no withdrawal. The list shows each medicine's rows per species, "Not recorded" with none. The rows are owned by
their medicine as a site's contacts are: they stay with it when it is deleted and come back when it is restored; a
species keeps its rows out of sight while it is deleted, and cannot be erased from the database while a row names it.
`farm/health/withdrawal.py`'s `row_for` is the one place that says which row applies to a species; the withdrawal, the
Medicines pages and the treatment dialog's choice all ask it. Nothing is seeded: the values are the product's SPC,
entered by the farm and checked by its vet. A change of the rows of a medicine already given (a live treatment) is logged as
**critical**, and goes through the withdrawal guard (below): the withdrawal is worked out live, so a change that brings a
recorded harvest inside a withdrawal, or frees fish held today, is asked about first (audit F-196). A medicine a treatment used cannot be deleted, nor its manufacturer
(`PROTECT`): set it inactive. Migration `0021` copies each medicine's old two columns into a row for every species, and
goes back when every medicine has one (it says why when it cannot).

**Treatments** (a read page with dialogs, like Feeding records): one course given to the fish of one or more
units of a site: the method (bath, in feed, injection, dip with a medicine; thermal, mechanical, freshwater or
other without one, a database check), the medicine (an active one; a treatment is given the way its medicine is,
so the lice report's method follows), the reason (sea lice, other parasites, bacterial, fungal, vaccination,
sedation, other; a vaccination uses a vaccine and a vaccine is a vaccination), the first and **last day** (the
first day follows the date rule of every daily record, the last may be planned up to 28 days ahead), the dose
and the amount used with their units (the report's units), the bath time, who prescribed it and the
prescription number, the vet (a supplier of veterinary and fish health services) and the health event it
answers. **The fast before it** is the shared handling check's (kind treatment; Setup › Reference data ›
Handling rules, 24 h to start with): the dialog shows when the fish of each unit were last fed against the rule, and too short a
fast is a warning; going on stores a handling acknowledgement on the treatment (`HandlingAcknowledgement`, which
belongs to a stock operation or a treatment, exactly one, a database check) and makes its log entry critical. A
medicated feed is not checked: it is the feeding itself. **A sea-lice medicine given for another reason** (hydrogen
peroxide is also an AGD treatment) is never refused, but the weekly sea-lice report lists only the treatments for sea
lice: the dialog says it will not be in it and goes on past the box, and the log entry keeps the warning ("Warnings
acknowledged"; not critical, it is a report's warning). The rule is one function, `farm.health.lice.left_out_of_lice_report`
(audit F-083, F-239). Every unit must hold fish on the first day; the other
way round, a stock operation that would leave a treatment (or a lice count) without fish on its day is refused,
naming it, and `check_stock` reports one. **No
batch is stored**: the batches treated are the ones the stock ledger has in its units from its first to its last
day. The list filters by site, unit, batch, method, medicine, dates, "under withdrawal today" and
"vaccinations", shows every batch a treatment reached with the withdrawal it puts on it, and offers **Last day**
(the course ended earlier or goes on: Edit, logged with the old and new day) and **Void** (with a reason, the
farm's window; it lifts the withdrawal). Nothing else is edited: a correction is a void and a new record.
**The list reads the fish on the day of the site they are on now** (the owner's decision of 12.11.2026: everything
is read on the site's own day, by the site's own clock; the company's day plays no part in whether fish are held).
`farm.health.withdrawal.of_treatments` reads each batch a treatment reached or holds on today of the site its held fish are on now,
with the reader the unit's own withdrawal line and the harvest check use (`of_units`), asked that same day; which
units share a day is said in one place (`site_days`). So the list's row, "Under withdrawal today", the day counts and
the unit's own line are one answer:

- a site ahead of the company: a course given today there has begun and holds the fish, and fish free on the site's
  day are free on the list, though the company's day has not come;
- a site behind the company: its running day is not counted as a past day without a temperature, and its fish are
  not freed a day early;
- a batch moved between clocks is read on the day of where it is now, with every course it carries;
- a batch that arrived today in a unit under a running course is in the course;
- every batch is shown with the units its fish held by the course are in now (`B-001 (T-01, T-03) · …`), and one whose
  held fish are on sites of different days once for each day, each part with its units and its own answer
  (`B-001 (K-01) · … `, `B-001 (T-02) · …`);
- fish that are nowhere any more (harvested out) are shown without a unit, not held, read on the day of the units the
  course was given in.

`farm/tests/test_withdrawal_clocks.py` asserts for each of these that the list says what the unit's own line says.
**Known and accepted:** on the day fish move between clocks, the unit they left still names them on its own day (a
batch counts in a unit on the day it leaves), so that day the list shows them as two parts, as the two units' lines
do. And fish of a course given today on the later clock that are moved the same day to the earlier clock are held
by their own site's calendar: that part shows the withdrawal at once and is marked held when its own day reaches the
course's first day, hours later (a part of the batch that was never in the course's units is not held at all: S-03). **The hard edge of the same rule** (the third review's case K; as on
main, and the owner's rule applied as decided): the course is given today on a site whose clock is ahead (its first
day is that site's today, say the 11th), and some of those very fish are moved the same day to a site whose clock is
behind, where it is still the 10th. Exactly then, for the hours until the second site's own day reaches the course's
first day, that site's unit line and harvest check say nothing of the withdrawal for fish that were in the bath: on
their site's calendar the course begins tomorrow. The Treatments list shows that part with the withdrawal's end and
not as held; a write guard sees the course at once. Closing it would mean reading those fish on another day than
their site's own, which is the owner's to decide.

**The write guards keep their day**, the earliest today among every unit the fish were in (`withdrawal.reach`,
`earliest_today` in `farm/stock/dates.py`): a guard asks before a write stands, of fish that can be on several sites.
One thing changed for them: a course that has begun where it was given has begun (`Reader.there`, `Reader.holds`).
Before, a course given today on the later clock began "tomorrow" on the guard's day and was not seen: a unit of such
fish could be deleted and a medicine's withdrawal made shorter without the question (`GuardsOnTwoClocksTests`).

**The medicine withdrawal** is worked out on read, never stored (`farm/health/withdrawal.py`), so a void, a
corrected temperature or a backdated transfer changes it at once:

- it **holds the fish that were exposed, not their batch** (flow fault S-03; the owner, 14.11.2026). The reader works
  out **lots** on read, nothing stored (`Reader.lots`; a lot is the fish of one batch in one unit over one stay):
  - **A.** the fish of a batch that were in a treated unit at any moment of a day from the course's first day to its
    last are exposed (also fish that passed through it that day);
  - **B.** the hold follows them: a move out of a held lot holds the lot the fish go into, to the same end;
  - **C.** a unit is held as a whole: every batch in a unit at any moment of a day a held lot is in it is held there
    from that day, to the same end, and stays held after either moves on (the owner's example: tank A treated and held
    to 23.11, 500 untreated fish of tank B moved into A and on to tank C before the end: tank C is held to 23.11);
  - **D.** fish of the same batch that left the treated unit before the course's first day, or were never in it, are
    not held: a tank split off before the course is free, on every page, and its harvest asks nothing;
  - **E.** an unknown end (no withdrawal row; medicated feed without a treatment) holds the same fish.
  A lot ends the day its last fish leave the unit and still holds that day (a harvest of that day lies inside); fish
  that come into the unit later are another lot. The order of the operations within a day is not read (a move has no
  time): fish that leave a unit on the day held fish come into it are held too (over-warned, never under-warned).
  When fish are held only because they shared a unit, every place says so by name: "These fish shared T-03 with
  B-2026-001 (treated in T-01)."; when the batch they shared it with was itself only held by sharing, the sentence
  names it and the ORIGINAL treated batch and tank as the source, and never says a batch was treated, or in a tank,
  that was not: "These fish shared T-03 with B-2026-002, which waits with B-2026-001 (treated in T-01)." (the
  guard's harvest question the same way: "… the fish harvested shared T-03 with B-2026-002, which waits with
  B-2026-001 …"); fish held in a unit they were not treated in: "These fish were treated in T-01."
  (the unit's line, the harvest warning, its stored acknowledgement, the critical log line, `check_withdrawal`).
  A unit's line says each cause once per batch with its latest end; while the exposed fish of a cause are in the
  unit their line stands for every fish in it. **Cleaner fish** (the owner, 16.11.2026; `check.held_apart`): a held
  lot of production fish holds the unit as a whole, its cleaner fish too, and their hold follows them where they are
  moved; a held lot of cleaner fish never makes another lot held (sharing a unit with held cleaner fish carries no
  hold onward), and the harvest dialog of the production fish beside them says it as one note per cleaner batch with
  its latest end: no warning, no acknowledgement, no change of the earliest date.
  **What a reader loads is bounded by the holds in force, not by the farm's history** (`Reader`): the courses that
  are not provably over (a medicine whose rows are all in days, one of them for every species, is over by the
  calendar; a degree-day row or a species that may have no row needs the fish read), the batches they can have
  exposed, and, of the withdrawals still in force in the window asked, the batches they can have reached
  (`farm.stock.read.reach` over `spans()`: one grouped query of the live ledger says who was where). A batch that
  only shared a unit long before, or with fish that were never held, is not read. A course of UNKNOWN end is in
  force for the days the platform owner set (below), and its fish are read for as long. The queries do not grow with the units or the
  batches (the units list, a drawer, the plans, the cards, the Treatments list and a guard cost the same for 6
  units as for 24: `farm/tests/test_withdrawal_lots.py`, the ten cases of the rule and the recorded counts), and
  the batches read and locked do not grow with the generations of fish long gone
  (`farm/tests/test_withdrawal_combined.py`, `HistoryTests`);
- **per species**: the medicine's row for the batch's species, else its row for every species, else the end is
  unknown (see Medicines); the margin is applied to both values;
- **days**: day 1 is the day after the last treatment day, the first day the fish may be harvested is the last
  day + the days + 1;
- **degree-days**: the EXPOSED batch's daily mean water temperature is added up from the day after the last day
  until it reaches the row's degree-days, the next day is the first harvest day. **Open question for the farm's vet**
  (decided for now, the safe side): the degrees are still those of the exposed batch in EVERY unit it is in (the
  lowest counts), also a unit that was never treated, not those of the held fish alone; so an untreated sibling
  tank's cold water still moves the end of the held fish, and for a degree-day medicine deleting that sibling tank
  or its loop stays blocked (below). A unit's daily mean is the mean
  of that farm-local day's temperatures in the unit, else in its system's loop (the water samples, never a
  copy); with the batch in several units that day, the lowest counts. **A past day without a measured
  temperature counts at the batch species' assumed water temperature** (Reference data › Species; one query reads
  the species of all the batches), **and as 0 °C when the species has none**, and the warning says how many days
  and at what ("3 days without a measured water temperature are counted at the assumed 8.0 °C (the species'
  setting in Reference data)", or "... are counted as 0 °C: set the species' assumed temperature in Reference data
  › Species."); not reached by today, the rest is projected at the mean of the last 7 measured days within 30
  ("about"); with none measured, at the species' assumed temperature when it has one ("Projected at the assumed
  8.0 °C ... no water temperature was measured in the last 30 days"), else the end is unknown ("record the water
  temperature");
- both given, the later end wins; a running course counts from its planned last day;
- **medicated feed** (a feed of the type Medicated) fed to a batch on a day no live in-feed treatment of the unit
  covers holds it with an unknown end until the treatment is recorded or the feeding voided; the feeding dialog
  says so when such a feeding is recorded.
- **an end unknown for want of a rule holds for a number of days only** (the owner's decision of 17.11.2026). Two
  records leave a withdrawal with nothing to end by: a medicine with no withdrawal row for the species (give it one
  in Reference data › Medicines) and a medicated feeding no in-feed treatment covers (record the treatment under
  Health › Treatments, or void the feeding). Such a withdrawal
  holds, and spreads as any other, to the day set in **Platform settings › An unknown withdrawal end holds for
  (days)** after the course's last day (180 until the platform owner sets another; 1 to 3650). After it the fish are
  not held: no warning, no delete block. The course is then listed under **Unresolved old courses** at the top of
  the Treatments page and by `check_withdrawal` ("Unresolved old course · B-2024-003: …"), each with what gives it
  an end (`withdrawal.unresolved`). **The ceiling never applies to a degree-day withdrawal** (decision of
  18.11.2026, following "degree-days stay as they are"): degree-days that are short, or can be neither counted nor
  projected (no temperature lately and no assumed temperature, or a mean of 0 °C or below), hold the fish however
  old the course is, exactly as before the ceiling existed, until the farm records the water temperature or sets
  the species' assumed temperature in Reference data › Species (the only way once the fish are gone); the unit's
  line, the harvest dialog, the Treatments page and `check_withdrawal` say both. A change of the setting is a rule
  change: it goes through the withdrawal guard (`guarded_ceiling`), which asks before a shorter one frees fish held
  today, and before a longer one holds fish again that had been let go or brings a harvest recorded meanwhile
  inside a withdrawal (each answer stored and logged as critical; asked of every course without a rule, of any
  age), the data layer refuses it anywhere else (`farm/withdrawal_gate.py`), and it is logged with its old and new
  value (`farm/tests/test_withdrawal_ceiling.py`). It also bounds what a reader loads for old courses without a
  rule (a course with a degree-day row is read for as long as it holds);

A withdrawal holds the fish from the treatment's first day (or the medicated feeding's day) to the day before
the first harvest day; a day before the treatment is not held.

**Every reader asks the lots.** The unit's own line and the handling check (`of_units`, through the registry), the
harvests inside a withdrawal (`_inside`: the lot of the harvested fish is held that day; `check_withdrawal` says "…
inside a withdrawal of B-2026-001, through T-01 shared with B-2026-001" when the fish met it in another unit), the
Treatments list (`of_treatments`: each batch with the units its held fish are in now, and ", shared a unit" for a
batch that was not treated itself), and the write guard (`snapshot`, `change`): fish are **released lot by lot**, the
question names the batch and the unit ("B-2026-002 in T-03 is held today (…) and would no longer be held …"), and a
move the write itself records or voids is followed, so a move dated before the course that takes fish out of its
reach, and the void of the move that had brought fish beside held fish, are asked about where the fish are after it;
a move of fish that were never held asks nothing.
**The spread is said at the move** (the owner's decisions 7 and 8 of 16.11.2026: fish moved into a tank that holds
fish are one group with them, whoever is combined waits for the others' withdrawal, wherever those fish go; it is
said when it is made, and the move is allowed). A transfer, a split, a grading or a stocking that combines held fish
with fish that are not held, in either direction, is asked about by the same box: "B-2026-002 in T-02 will wait for
the harvest with B-2026-001, the held fish it is combined with in T-02: harvest from 18.11.2026. …" ("… and the end
of that withdrawal is not known." for an unknown end), once for every lot the move newly holds, also the lots fish
went on to when the move is dated in the past. **Fish that were held already, to an earlier end, are told too** when
the move combines them with a longer or an unknown hold, in either direction (they now wait longer: a batch held
until tomorrow moved in beside fish held for two months); fish combined with a hold that ends no later than their
own are not asked about. Fish moved or stocked INTO the treated tank dated on a course day are exposed themselves,
and the sentence names no other batch: "B-2026-002 in T-01 will wait for the harvest with the fish treated in T-01:
…". **A void asks the same way** when it combines held fish with fish that are not (the void of the move that had
emptied a tank held fish then came into, of the cull that had emptied the held tank). **Whatever the batch**: fish
of the SAME batch are asked about exactly as another batch's (a split before the course merged back into the held
tank, held fish moved into the tank split off before it, a sibling tank of decision 7 moved into its held part):
the fish already in the tank and the fish each move brings in are asked about each on their own
(`farm/tests/test_withdrawal_spread_matrix.py`: same or other batch, held side or not-held side moving in, by a
transfer, split, grading, stocking and void). Going on stores a handling
acknowledgement on the operation (the batch
that now waits, the end, the withdrawal's source, the sentence) and a critical log line; `check_stock` knows such a
row on a transfer, a grading or a stocking (a stocking is not a handling; a withdrawal row on any other operation
is still reported). It is asked when the
dialog is sent, not when it opens: the tanks are chosen in it (`farm/tests/test_withdrawal_combined.py`).
**Locks.** A write locks every batch whose withdrawal it can change (`farm.stock.services.lock_fish`, which every
stock operation, void, treatment, feeding, sample and medicine row goes through): its own fish, the batches its
fish can have reached since its day (a move joins fish), and the batches the withdrawals of its fish hold; the
batches in one statement in primary-key order, then the units. So a move of held fish into T-02 and a harvest, at the
same moment, of fish that went on from T-02 to T-03 take turns and the later sees the earlier
(`farm/tests/test_withdrawal_locks.py`: two real transactions, both orders; also where the harvested batch was
never in a unit of the move and the lock in common comes from the reach alone, with the two mutants that show the
unseen harvest when the reach is cut out; a sample in the treated tank today locks fish held by sharing elsewhere
through the holds alone, and a grading takes these locks first, as every write does). It is bounded by the day of
the write and the holds in force, not by the
history. A write of reference data (a feed's type, a species' assumed temperature, a sampling point, the ceiling) is
not a dated record: its guard reads from the day it reaches the fish, however long ago, so every recorded harvest it
puts inside a withdrawal is asked about; a dated record's guard reads from the first day of the correction window.
**What blocks a delete** (`held_reached`): a unit, a loop or a species waits while a lot held today would be moved
by it: the unit holds such a lot; the withdrawal's batch was exposed in it (without the unit the course reached
nobody); or, for a degree-day withdrawal, its batch was in the unit since the course's last day (its water counts for
the end: the open question above). An empty unit that was never treated is no longer blocked by a hold elsewhere on
a batch that was once in it; for a day-based medicine neither is the untreated sibling tank.
**Landing this changes what stored courses hold, with no record changed** (worked out on read): a tank split off
before a course loses its withdrawal; a unit whose fish shared a unit with held fish and moved on, or that held fish
passed through, gains one until the same end. **The landing carries a before and an after listing**: `manage.py check_withdrawal --listing` writes the fish
held now (unit, batch, end, about, the course or feeding, why) and every harvest and live delivery inside a
withdrawal (its line's kind, `harvest` or `delivery`, beside its unit and batch) as sorted,
tab-separated lines with no ids, made for a diff. It reads only what the rule before and the rule after both have,
so the same command file runs on a checkout of the old rule: the listing of the data before the landing and the
listing after it are kept with the landing notes, and their diff is what the landing changed.

Where it shows: the health records give it to the shared handling check through the registry of
`farm/handling/withdrawal.py` (`blocks(unit, day)`: a block per batch held in the unit and cause, `until` the first day the fish
may be harvested; the provider is registered in `farm/apps.py`). From there Production units marks the unit's
row **Withdrawal** and the drawer's Harvest and handling section says **"Not suitable for harvest — medicine
withdrawal of B-2026-001: harvest from 14.12.2026."** ("harvest from about …" when projected, "end unknown") with why, to everyone
who sees the page; the harvest dialog warns, never blocks (owner decision), and keeps the acknowledgement (the
transfer and grading dialogs are not asked for a withdrawal: live fish are not eaten). The Treatments list shows each batch's end with both days, the second in the same words: "until 13.12.2026 (harvest from 14.12.2026)".

**Health events** (a tab: created and edited on their form, every change logged, voided with a reason instead of
deleted): the site (chosen once) and some of its units or the whole site, the date, the kind (observation, vet or
fish-health visit, lab result, increased mortality), the signs (several of a fixed list), a diagnosis from a
reviewed catalogue (`farm/health/diseases.py`: the EU-listed and the Norwegian category F and G diseases of
dyrehelseforskriften §§ 5–6, each with whether it must be notified, and common unlisted ones), suspected or
confirmed (with a diagnosis, a database check), who examined,
the vet and the laboratory (suppliers) with its reference, findings, recommendations, closed on and the outcome.
That Mattilsynet was told is not a field of the event: it is the filing of a disease notice (Production › Reports), which the
health records read through a registry (`farm/health/notices.py`). A notifiable diagnosis, suspected or confirmed, that no
filed notice tells Mattilsynet of raises the red **Notify Mattilsynet** banner on the list and in the unit's drawer, with a link
to start the notice filled in from the event for people who may (§ 7: at once, already on suspicion; sea lice are reported
weekly with the counts instead); the list's Mattilsynet column shows when it was told. With no notices registered it says
nothing about it, never "not notified". A mortality or a cull may be recorded under an event (the dialogs offer
the events of the unit's site that concern it, open or closed within the backdating window, to people who may
read them; `StockOperation.health_event`, a database check
keeps it to those two kinds) and the event counts its **deaths** from those lines; mortality has the cause
**Treatment** for deaths a treatment or its handling caused. Closing an event never lifts a withdrawal: that is
the treatment's (HLT-01). An event that a live treatment or operation names is not voided.

**Sea-lice counts** (a read page with dialogs): per unit and day, the fish examined and the lice of each stage
found on them in total (adult females, mobile, attached); the averages per fish are worked out, never stored
rounded. One live count per unit and day; a correction is a void and a new count (HLT-19). The page shows each
site's **weekly averages** for the latest 12 weeks, as lakselusforskriften (FOR-2012-12-05-1140, read on Lovdata
on 2026-11-03) has them:

- Vedlegg 1 point 6: a unit's average is its lice / its fish examined, the site's average **the mean of the
  units' averages**, every unit weighing the same (the source weighted them by their fish, HLT-22); the latest
  count of each unit in the ISO week counts;
- § 8: the site's average of adult female lice must stay **below 0.5**, and below **0.2 from Monday of week 16
  to Sunday of week 21** from Nord-Trøndelag southwards, **weeks 21 to 26** in Nordland, Troms and Finnmark; at
  the limit is over it ("færre enn"). The area is the site's (Facility › Sites, Location: Sea-lice limit area);
  a site without one is judged by the stricter of the two, and the page says so;
- Vedlegg 1 points 2 and 3: at least 20 fish a cage in weeks 14–21 (south) or 19–26 (north), 10 otherwise; a
  smaller sample is pointed out; how many of the units with fish were counted is shown. The weekly table is always the
  site's whole weeks: the filters of the list below choose which sites and weeks it shows (a unit: its site; a date
  range: the weeks it touches), never which counts make an average (audit F-082).

Over the limit is a warning on the page; nobody is alerted yet, and the weekly report to Mattilsynet is not
built (§ 10).

**The unit's drawer** on Production units has a **Health** section: the withdrawal of each batch with why, the
open health events that concern the unit, its treatments of the last 90 days, its latest lice count, and Record
treatment, Record sea-lice count and Record health event with the unit chosen.

**Who may do what**: the areas Medicines (Production · Setup · Reference data: read, create, edit, delete),
Treatments (read, create, edit = change the last day, delete = void), Health events (read, create, edit, delete =
void) and Sea-lice counts (read, create, delete = void), the last three under Production · Operations · Health.
The admin shows voided treatments, events and counts and does not restore them. `manage.py check_withdrawal`
works out every unit's withdrawal from scratch and lists the fish held, with the end and why, and then **every harvest
and every live delivery already recorded inside a withdrawal** of its own batch or of a production batch that had fish in its unit at any moment of that day ("… lies inside a
withdrawal of B-2026-001, in the same unit (harvest from …)"; "Live delivery of … (300 fish to Nordic Smolt AS) lies
inside a withdrawal (the fish may leave the farm from …)"; medicated fish that may have gone to food), however it came to (a treatment entered
after the harvest, a longer course, a corrected temperature, a medicine's withdrawal changed), each with whether someone
acknowledged it or not: an acknowledgement counts only for the harvest, the batch and the withdrawal it names (when the
harvest was recorded, or when the write that brought it inside was), never for another withdrawal of the same harvest.
It ends with one count line of each, also when it is none ("No harvest lies inside a medicine withdrawal.", "1 live
delivery lies inside a medicine withdrawal.").

**The withdrawal guard** (audit F-195, F-188, F-196 and the three cross-reviews): every write that can create, grow, shorten
or end a medicine withdrawal goes through one function, `farm.health.withdrawal.guarded`: a treatment, its last day and its
void, a medicated feeding and its void, a medicine's withdrawal rows, a water sample (a round too) and its void, every stock
operation and its void, and on their Setup pages a feed's type, a species' assumed water temperature, a unit's loop (its
system, whose samples count for a unit without its own) and a sampling point's active flag, kind and owner. Those pages
(`farm/resources/withdrawal_input.py`) lock the fish the record reaches before the record itself, the order a stock
operation and a water sample lock them in; a record changed between the edit's first read and its lock is refused as a
crossed edit. A system, a unit, a species or a sampling point is **not deleted or restored** while a withdrawal holds fish
it reaches (weighed as it stands live: the readers read live records, so a deleted unit's fish would show no withdrawal at
all), or while water samples are on the point: its delete page says why (`withdrawal_blockers()`), and the gate refuses
any other way of flipping the flag, the admin's restore included (shown as a message). A unit's loop changed outside the
guard is refused when it moves a withdrawal (worked out as the guard works it, rolled back), free when it moves none.
**The data layer holds it** (`farm/withdrawal_gate.py`): those rows and fields refuse a change made anywhere but inside the guard, whatever writes it
(a model's save or delete, `loaddata`, a treatment's units from either side or through their link table, a queryset's
update, delete, bulk create or bulk update, a field named by its column alike), so a new path that skips the guard fails
at once with a ValidationError; a test fixture, a command or a correction meant to write behind it says so with
`withdrawal_gate.opened(reason)`. Migrations work on historical models and raw SQL is not seen. A test derives the columns
the withdrawal readers read from the queries they run and fails on one that is neither registered nor said not to be an
input (`farm/tests/test_withdrawal_gate_coverage.py`).

Inside the write's transaction the guard locks the fish first (`farm.stock.services.lock_fish`: the batches, then the
units, then the batches read again under the unit locks, so a batch that arrived in between is locked too; a harvest locks
them in the same order, so the two take turns), works out their withdrawals, makes the write **once**, in a savepoint, and
works them out again from what it left. It asks when the write

- brings a harvest already recorded inside a withdrawal, or makes the withdrawal it lies inside end later than before
  (medicated fish may have gone to food: a treatment entered up to 31 days back, a longer course, a backdated medicated
  feeding, a corrected temperature, a longer medicine withdrawal, a backdated move of held fish, a void, a longer
  ceiling), or does any of that to a **live delivery** already recorded (the owner's decision 13 of 19.11.2026: its
  fish left alive and may be eaten). Both are read by one rule (`_harvest_lines` reads every line of
  `check.WITHDRAWAL_LINES`, `_inside` compares them) and asked in the same box: a delivery as "Live delivery of
  16.11.2026 from T-01 (B-2026-001, 300 fish to Nordic Smolt AS) lies inside this withdrawal (the fish may leave the
  farm from 22.11.2026): medicated fish sold alive may have been eaten.", stored as a `delivered` acknowledgement that
  names the delivery (a `harvested` one names the harvest) and counted by the second-person setting as a harvest is
  (every kind of write that can do it, a water sample and the reference data among them:
  `farm/tests/test_withdrawal_delivery_after.py`, `farm/tests/test_withdrawal_delivery_paths.py`), or
- makes the withdrawal of fish held today end earlier, or ends it (a course voided or shortened, a medicine's withdrawal
  shortened, a medicated feeding voided, a temperature corrected): the message gives the old and the new end.

Unless the person went on past exactly this impact, the savepoint is rolled back and the write refused: the dialog shows
what was found with its box, `withdrawal_ack`, whose value (the impact's fingerprint) the form hands to its own service, so
a tick acknowledges that write only; an impact that changed since it was shown is asked again. Going on keeps the write as
it was made, stores a `WithdrawalAcknowledgement` per warning (the write, the batch, the withdrawal, the harvest, the end
and what was shown; the database refuses an edit or a delete) and logs a critical entry on the record with the warnings.
The database's CHECK holds that a `harvested` or `delivered` row names an operation; that it names one of its kind (a
harvest, a live delivery: `models.handling.OPERATION_NAMED`) is a cross-table rule, which `check_stock` holds
(`farm/stock/integrity.py`). An acknowledgement covers the end it was given for: `check_withdrawal` says "Not acknowledged (acknowledged until …; now
…)" once a withdrawal ends later than that. A harvest the write records itself is asked about by its own handling check,
not twice. Whether a second person must approve going on past a withdrawal is a setting of the platform owner's (owner
answer, 2026-11-06); it is asked in one place, `farm.handling.check.second_person_must_approve(user, kinds, record)`, which
answers no until that setting exists.


Differences from the source (details in the bug document, HLT-01 to HLT-23):

- One treatment record, read by the withdrawal and (later) the lice report; the source had two that never met
  (HLT-03). The withdrawal is the medicine's, in degree-days or days, from the last treatment day, worked out on
  read; the source's date started at the click, was days only, was lifted by resolving the disease and could be
  edited away (HLT-01, HLT-02, HLT-04, HLT-08).
- Real foreign keys and checks everywhere (HLT-16); voids instead of deletes and edits that are logged (HLT-04);
  the server's reasons on the field (HLT-17); a reviewed disease catalogue with ILA as the listed, endemic disease
  it is (HLT-11); the statutory lice limits and the cage-mean average (HLT-10, HLT-22).
- Not ported: the `health_events` JSON, quarantine as a flag (a unit status), the stats tiles, the chemical
  master as a medicine catalogue, welfare scores, escape incidents, vaccination details, medicine stock, lab
  result values, the reports to Mattilsynet, treatment effect and resistance tests, cleaner-fish health
  (health-maturity §4d). The water temperature at a treatment is not typed on it: it is the water samples'.
**Read for many units.** `health.read.recent_treatments(units)`, `open_events(units)` and `latest_counts(unit_ids)` (one
`DISTINCT ON` row a unit) answer for many units in a constant number of queries; the drawer calls them with its one unit and the
monitoring cards with all of theirs.

### Operations › Tasks (`/operations/tasks/`) and Recurring tasks (`/operations/tasks/recurring/`)

The farm's jobs: "clean the drum filter of T-01", "report the lice count to Mattilsynet", each at one place,
for the people who do it, due on a day. Tables `tasks`, `task_assignees`, `task_checklist_items`,
`task_notes`, and for the recurring tasks `task_series`, `task_series_assignees`,
`task_series_checklist_items`; the app is `tasks/`.

**A task** is a title, a description, a category (feeding, cleaning, maintenance, fish health, water quality,
harvest, transport, administration, other), a priority (urgent, high, medium, low), a due date and
optionally a due time, and:

- **one place, chosen from a list**: a whole site, a production department, a system, a unit or a piece of
  equipment, exactly one (a database check over five real links). The dialog's **Site** select narrows the
  **Location** select, which lists every live place grouped by kind ("T-01 · Tank 1 — Hall A · Bergen");
  **Without a site** offers the production departments without a site and what is in them. Nothing is typed;
  the server checks the place against the site and refuses anything not offered.
- optionally **the batch** it is about: a batch with fish at the chosen place now (from the stock ledger),
  narrowed by the Location select (a chain: site → location → batch). A task keeps its batch after the fish
  leave; a new choice, or a new place, is checked again.
- **its people**: one or more user accounts, offered as the active users who can read Tasks (the platform
  admin among them). Each of them sees it under My tasks and any of them can start and complete it. Someone
  who can no longer be chosen (deactivated, or the role taken away) stays on the tasks they had, marked so.
- a **checklist**, once the task exists: its lines, at most 30, edited as a list on the dialog's Checklist
  tab until the first line is ticked; then each tick is the only change, with who and when.
- **notes**: anyone who can read Tasks adds one in the drawer; a note is never edited or removed there (task
  notes are part of the work record; Messages are not, see below). The activity log says that a note was added,
  by whom and when, never its words; a description (a task's and a recurring task's), a completion note and a
  reason for cancelling are logged the same way (a person's free text is private in the log, which nobody can
  erase from: Security in the pages, Personal data). The words live on the task. **Reopening loses none of them:**
  it clears the completion note and the reason on the task (it is open again) and keeps each as a note by the
  person who wrote it, marked as what it was (`TaskNote.kind`, `tasks.services.reopen`); the drawer says
  "Completion note, kept when the task was reopened". Only the erasure procedure removes a person's words.

**Statuses**: open, **in progress** (who started it and when), **done** (who completed it, when, and a
note), **cancelled** (who, when and why). Start, Complete and a tick: a person the task is for, or whoever
may edit tasks; Cancel and Reopen: whoever may edit tasks (reopening clears the completion or the
cancellation and the start). The person who created a task has no rights of their own (owner decision 8).
Each change is one call of `tasks/services.py`, in one transaction with the task locked, logged, and
the database holds the rule (done exactly with who and when, cancelled exactly with a reason, in progress
exactly with who started it).

**Overdue is worked out on read**, never stored: a task that is open or in progress is overdue once its due
date has passed, or on its due date once its due time has passed, each on the clock of its place's site
(`farm.models.site.zone_of`; the company's for a production department without a site). A task due 3 Nov at
23:00 on an Oslo site is due today at 23:30 UTC on 2 Nov and overdue at 22:30 UTC on 3 Nov.

**The page** has three views, each a query of its own, filtered and paged on the server (50 a page):
**Today** (the overdue first, then the ones due today by time and priority, then the ones done today),
**Open** (every open one and in progress, by due date) and **Completed** (done and cancelled, latest first),
with the number of each, a search, filters (site or "without a site", place, assignee or **My tasks**,
priority, category, due from and to) and the overdue count. A row is one link: it opens **the drawer**
(`?task=`) with the place (shown "Place deleted" once its place is deleted), batch, due date, people,
recurring task, who started, completed or cancelled it, the checklist with a tick per line, the notes, and
what the person may do: Start, Complete, Reopen, Edit, Cancel task, Delete. **New task** opens the dialog;
`?place=unit:<id>` starts it at a place (for a "New task" button on a unit's drawer later). A form sent twice
creates one task (its key, `core.crud.ENTRY_KEY`). The production overview has two tiles, the tasks due
today and the overdue ones.

**Recurring tasks** plan a task at a place for its people: **daily** every N days, **weekly** every N weeks
on chosen weekdays, or **monthly** every N months on a day of the month (the 29th to 31st fall on a shorter
month's last day), from a first day (and up to a last day, if it has one), with an optional due time and its
own checklist, copied to each task. The dates are worked out from the first day on the site's calendar, so
nothing drifts and a daylight-saving weekend moves nothing (`TaskSeries.dates`). Its tasks are **real tasks**,
made up to `TASK_HORIZON_DAYS` (14) ahead; the first time, or after a gap, the missed days are made back to
at most `TASK_BACKFILL_DAYS` (7), and they are overdue (owner decision 3). They are made when a recurring
task is saved, before the Tasks pages and the overview read, and by `manage.py generate_tasks` for a cron;
one recurring task per transaction, locked, and a unique key per recurring task and day, so each day is made
once however often and however concurrently. A planned task that nobody touched (open, never edited, no tick,
no note) is only the rule's projection: **changing, pausing or deleting** the recurring task replaces or
removes those from today on and keeps every other one; a task a person deleted is not made again; resuming
does not make the paused days. The list shows each rule in words ("Every 2 weeks on Monday, Thursday at
08:00"), the place, the people, the next day and whether it is active.

**Deleting**: a task is soft-deleted (the delete plan, restorable from the admin). Deleting a place does not
wait for its tasks (owner decision 7): they keep the link (`DO_NOTHING`), stay in the lists showing "Place
deleted", and show the place again when it is restored; the confirmation counts them. A recurring task goes
with its place (`CASCADE`), taking its planned tasks nobody touched (`Task.deleted_with`); the others stay.

**Who may do what**: the areas Tasks and Recurring tasks (Production · Operations), each read, create, edit
and delete; see Statuses for start, complete, tick and notes.

**Not in the MVP, and how it plugs in**: notifications (signals from `tasks/services.py`; the system
assistant's direct message in Messages, a menu badge, an e-mail digest), auto rules (from the prototype's
own write paths with a dedupe key, e.g. a critical water value opens a task at that unit, not the source's
free-text conditions), maintenance (preventive maintenance as a recurring task at an equipment place, a
repair as a task), a calendar, people without a login (with HR), and the AI assistants (reading
`tasks/read.py`, writing through `tasks/services.py` with the person's confirmation). Task notes are not a
Messages conversation: a conversation is for its members only and not in the activity log, while a task's
notes are part of the farm's record that a supervisor, the next shift or an auditor reads on the task (the
activity log records that a note was added, not what it says).

Differences from the source (details in the bug document, TSK-01 to TSK-23):

- The place is one of five real links chosen from a list (the source's was free text, its `siteId` never
  written); the people are user accounts (the source mixed accounts with workers who cannot sign in and
  copied their names); every link is a foreign key (TSK-01, TSK-02, TSK-12).
- Overdue is worked out on read on the site's clock (the source stored it on the server's clock and lost
  "in progress"); each view is its own server query (the source showed the first 50 tasks, and its Today never
  matched a date) (TSK-03, TSK-04, TSK-09).
- A rule anchored to its first day with weekdays and a day of the month, made once per day in its own
  transaction (the source's drifted, ran on UTC and shared one transaction) (TSK-06, TSK-14).
- Every action has its page and test; the status changes only through its own actions with who and when;
  the checklist keeps who ticked what; a form sent twice creates once (TSK-05, TSK-07, TSK-10, TSK-11, TSK-16).
- Not ported: tags, the time estimate, auto rules, the calendar, notifications, the AI tools.

`tasks.read.per_unit(unit_ids)` counts each unit's open, overdue and due-today tasks in one grouped query, with the same filters
as the views above on each site's own clock (the monitoring cards).

### Research › Experiments (`/research/experiments/`)

Trials of one species on one site, for a research facility: the design (factors and their levels, groups and
controls), the replicates, the tanks and the days each is booked to a replicate, how the tanks were allocated, and the
team. The app `experiments` reads `farm` and nothing reads it: it stores only what no other record holds, and every
figure (fish, feed, FCR, water, deaths) is read through the farm's own reads over the days a tank is booked; a diet is
applied through the farm's own feeding-protocol assignments. No farm table has an experiment column.
The reference (what a day means, the allocation method id, every constraint and trigger, what the code holds and what must be
checked live) is [`docs/experiments.md`](docs/experiments.md).

**What is stored** (tables `experiments`, `experiment_factors`, `experiment_levels`, `experiment_groups`,
`experiment_group_levels`, `experiment_replicates`, `experiment_replicate_units`, `experiment_members`; migration
`experiments/0001_initial`, which depends on the farm's migration 0018 only, so the order in which other branches add
farm migrations does not matter):

- An **experiment**: a generated number (`E-2026-001`, never reused, `core.codes.next_code`), a name, a template flag, its
  status (draft, running, closed), its site and species (one of each: a unit holds one species, and one clock gives the
  day key), the hypothesis, the primary endpoint (`experiments/variables.py`: biological FCR, economic FCR, survival,
  biomass gain: what the farm's reads give today), the start day (day 0, the baseline weighing) and the duration in days
  (the last day is the final weighing), how the tanks were allocated (not yet, randomised with a seed, or placed by hand
  with the reason), the experiment it was copied from and notes (the key of the form that made it is in the one key
  table, `core.models.EntryKey`).
- A **factor** (a thing the groups differ in: the diet, whose levels name feeding protocols, which is how the farm
  applies it, or another factor with a unit) has **levels**: a diet level names its protocol and has no label; another
  level has a label and optionally a number (a dose, a setting). A **group** has a role (test, control, negative or
  positive control: both kinds of control may exist) and a level of every factor (**group levels**); it has
  **replicates**, numbered within it (the number is stored: a replaced tank must not renumber R2). A **placement** books
  one tank to one replicate for a range of days, both included (the tank, not a system: `Tank.system` changes and has no
  history, so a system is only a shortcut on the page that books its tanks).
- The **team**: a person and a role (lead, researcher, student, technician, advisor), one lead.

**What the database holds** (constraints, tested one by one by writes that check nothing; the rest is said below):

| Rule | Held by |
|---|---|
| a tank is in one experiment at a time, drafts included (a draft reserves its tanks), the days inclusive | exclusion constraint `excl_replicate_units_unit` on (tank, daterange), the twin of the feeding assignments'; a placement has both days, so it never books a tank for ever |
| a window ends on or after the day it starts | check |
| one level per factor per group; a level belongs to its factor; the group and the factor belong to the row's experiment; a level has its factor's kind | unique pair and four composite foreign keys (`fk_experiment_group_levels_*`, `fk_experiment_levels_factor_kind`; a wrong row would put another trial's level in a group and corrupt every factor column of the dataset) |
| a diet level has a protocol and no label or number; another level has a label and no protocol | check (else a start would silently skip a diet) |
| one diet factor; one lead; names unique among live rows, whatever the case; replicate numbers unique in a group; a number is never reused | unique constraints (partial among live rows where a row can be deleted) |
| a template is a draft without a start day or an allocation; a started experiment has its day 0, hypothesis, primary endpoint and allocation; the allocation method, its seed and its reason belong together | checks |
| a started design cannot change; a placement only gets shorter | triggers (below) |
| a protocol or tank in a trial cannot be deleted | `PROTECT` and the delete plan (a deleted draft frees its tanks) |

**A started design cannot change**, for any writer (pre-registration: what was planned is what is judged): triggers of
migration `experiments/0002_design_frozen`, tried by raw SQL and the ORM with no form or service in between. Once an
experiment is not a draft, every column of it but the status, name, notes and bookkeeping is fixed, the status goes
forward only (draft, running, closed: the model's `TRANSITIONS`, which a test compares with the trigger on every pair)
and the row is never deleted or soft-deleted; its factors, levels, groups, group levels and replicates take no insert,
update or delete; its placements are free while it is a draft, a running one may get a new placement (a replacement)
and shorten one with a reason (`until_on` never longer), a closed one allows nothing, a started experiment's placement
is never deleted, and a template has none. A change of `created_by`, `updated_by` or `deleted_by` alone is always let
through, so removing a person from the system never fails on what they once created. The refusals are
`check_violation`, so the ORM raises them as an `IntegrityError` like a constraint. The team is not the design and is
not guarded.

What PostgreSQL cannot say without copying columns (a tank on the experiment's site, a window inside the experiment's
span, a level for every factor, a diet applied at the start) is checked by the services and says so where it is.
The owner decided five things: a draft reserves its tanks; no trial is registered beyond the farm's 31-day
window; a tank that was ever in a trial is never deleted (set it inactive); a hypothesis and a primary endpoint are
needed to start; one species and one site per experiment.

**The pages** (Production panel, under a main heading of its own, **Research**, between Operations and Communication;
the tab is a `core.crud` Resource, `experiments/resources.py`):

- **The list** has three views, Experiments, Mine (the ones the person is in the team of) and Templates, filtered by
  status, site and species and searched by number, name or hypothesis; each row opens the read page, with Edit and
  Delete beside it for those who may (a started experiment has no Delete). The counts are of the live groups and
  replicates.
- **The form** has the tabs **Details** (name, species and site, chosen once; hypothesis; primary endpoint; day 0;
  duration; notes), **Design**, **Places**, **Team** and History. Creating opens the details only, then opens the new experiment: its number is
  given on saving, inside the creating transaction (`core.codes.next_code`, `E-<year of the site's clock>-<n>`), its
  creator is its lead (logged as a change of its team), and a form sent twice creates one. Once the experiment has
  started its hypothesis, endpoint, day 0 and duration are fixed beside their fields ("Copy it to change the design"),
  and the name and notes stay editable.
- **The Design tab** is two grids saved as a whole (`ExperimentDesignView`, `<id>/design/`; `experiments/services.save_design`):
  the factors (name, kind, the unit of a quantity's levels; a new experiment starts with one diet factor) and the groups
  (name, role, one cell for each factor, replicates). A diet cell chooses among the active feeding protocols of the
  experiment's species (one retired since stays in its cell, and the design says so); another factor's cell is a label and
  an optional number (a dose, a setting). Levels are made from the cells and never listed alone: two groups that give the same
  protocol or label share one level, and a level no cell asks for goes. 3 diets by 2 replicates is three rows and no factor
  language. Changing a factor's name or kind, or "Add factor", renders the grid again with the columns (the form's
  `data-refresh`, nothing saved); a started experiment shows its design as it is. Rows are matched to the stored ones by their
  id, so renaming a group keeps its replicates and the tanks placed in them (a factor whose kind changed is a new factor); the
  replicates of a group are made equal to its count, the highest removed first and never one that holds a tank, and a group
  with tanks is not removed. The save is one transaction that locks the experiment, refuses a stale version or a started
  experiment, and writes one activity-log row on the experiment ("Design", before and after as text in English); the parts
  it removes are deleted through the delete plan, one row each.
- **What is wrong with a design** is one list, `design.problems(experiment)`, which the Design tab shows and the Start dialog and
  `manage.py check_experiments` will: errors block Start (no hypothesis, primary endpoint, day 0 or lead; a day 0 older than
  the farm's 31 days; no group; a group without a replicate or without a level of some factor; two groups with the same
  levels; a diet protocol that is not active or is of another species), warnings are acknowledged at Start (one group;
  fewer than two replicates in a group; no control; unequal replicates; a protocol not yet assigned, so its table can change
  until Start; feeding tables that differ in more than the feed). It is derived on read: nothing about it is stored. `CHECKS`
  is a list other areas append to, so a permit can block Start without this module knowing it. The warnings carry a
  fingerprint, as the handling check's, so a start whose warnings changed meanwhile is asked again.
- **The Places tab** (`ExperimentPlacesView`, `<id>/places/`; `services.save_places` and `randomise`) gives the replicates their
  tanks, for the days of the experiment (day 0 to day 0 plus the duration, both included, on the site's clock) unless a row gives
  days of its own. Either **Randomise**: a pool of tanks and systems of the site (as many as replicates, a system giving all its
  tanks to one replicate) and a seed, dealt by the fixed method `sha256_v1` (`experiments/allocation.py`: the items sorted by the
  SHA-256 of "seed:code", the i-th taking the i-th replicate in the order of the groups and the replicate numbers; fixed test
  vectors guard it, and it is not `random.shuffle(seed)`, which only `random()` of Python's generators keeps stable across
  versions); the method and the seed are stored with the placements, so the deal can be repeated and checked. Or **by hand**: a row
  a replicate with its tanks (a multiple choice), "add the tanks of a system" (the tanks of the system and of the systems nested in
  it are added; a system is never stored, only a shortcut, because `Tank.system` changes and keeps no history) and a reason, which is
  needed (a placement that is not randomised is registered as "placed by hand: why"). A banner says which. A tank another
  experiment holds on those days (drafts included: a draft reserves its tanks) is shown with that experiment's number and cannot
  be chosen. Both are one transaction that locks the tanks (primary-key order) and then the experiment, refuses a stale version, a
  started experiment, a template, a tank off the site, days outside the experiment, a tank in two places on one day and a booking by
  another experiment (named by its number; the exclusion constraint holds it for any writer, and a booking that comes in between
  is told the same way), and writes one row on the experiment ("Places", and "Allocation" when it changed). A draft's placements
  are not evidence: the ones replaced are removed for good and the change is that one row. Changing a draft's day 0 or duration
  moves the placements that equalled the old span (a placement with days of its own stays; the design says when it is outside the
  span), and the form refuses a move onto days another experiment holds the tank, on the field that moved it. A template has no
  tanks; a started experiment shows where its tanks stand.
- **The design's warnings and errors about the tanks** (`design.problems`): errors, the tanks not allocated, a replicate without a
  tank, a tank off the site, a placement outside the experiment's days; warnings, the tanks of one replicate in different systems,
  and one system holding tanks of different groups (water-borne confounding, from the current `Tank.system`). The reads
  (`experiments/read.py`): `cells` is the one definition of what belongs to the trial (each placement with its replicate, group,
  tank and days), `booked` says which experiment holds which tanks on some days, and `error_df` is the replicates less the groups.
- **Start** (the dialog `<id>/start/`, from the Design tab and the read page; `services.start`) fixes the design and applies the
  diet. The dialog shows what is wrong with the design (`design.problems`): the errors block (the button is off), the
  warnings are read and acknowledged with one box whose value is their fingerprint, so a start whose warnings changed
  meanwhile is asked again (`check.require_acknowledged(…, field='start_ack')`, the handling check's rule and widget).
  Besides the findings above, a draft asks that nothing stands in the diet's way: **a unit's own assignment on a tank in the
  days it is booked is an error, listed, and never ended by the start** (the person ends it on Assignments); so is a protocol
  assigned to a batch in the tank, which would beat the unit's (`farm/feeding/ration.py`); and, once day 0 has come, warnings
  for a tank with no fish of the species that day, two batches of it, or fish not weighed that day (a measured point of the
  stay on day 0, `feeding/read.measured_on`, is what the bounded FCR window starts from). Starting is one transaction that
  locks the batches the tanks held, the tanks (primary-key order) and then the experiment, refuses a stale version, a second
  start, a template and an error, and, for every group with a diet level, writes the farm's own assignment rows (unit scope, from
  the first to the last day of each placement) through `farm/feeding/assignments.py`, the rows and log entries the assignment
  dialog would write, so the meal board and the rations follow the diet; they are found later by (unit, protocol, first day),
  with no link column on a farm table. The status goes draft to running through `TRANSITIONS`, and one row on the experiment
  says "Status: Draft → Running" with the warnings acknowledged, in English. A feeding recorded while it starts waits for the tank
  (a test races the two), and two starts at once give one winner and one assignment row each.
- **Copy and templates** (the dialog `<id>/copy/`, **Copy as a new experiment** and **Save as a template** on the read page and the
  Design tab; the add permission: Create creates and copies; `services.copy`). A copy is a new draft with the design of an
  experiment of any status, or of a template: the factors, their levels (the same feeding-protocol rows, so a repeat of a started
  experiment feeds identically, an assigned protocol being frozen), the groups with their levels and the replicates as empty
  places, the hypothesis, endpoint, duration and notes; never the placements, the allocation or its seed, or the team, but the
  copier, who leads it. `copied_from` says where it came from (and outlives a deleted source). A template is a design without a
  day 0 (the list's Templates view); a copy of a template is an experiment. The number is the next one (never reused), a form
  sent twice makes one copy, and the new experiment is logged as created with its design and its source.
- **The team** is a list saved as a whole (`RowList`, logged on the experiment as "Team"): a person and their part,
  exactly one lead; only people who can read Experiments are offered, and one kept from before stays in the list.
- **The read page** (`<id>/view/`, for everyone who may read the tab) shows the details and, in the address's `?tab=`, **Overview**,
  **Data** or **Team**. The **Overview** says where the experiment is ("Day 23 of 56", "Day 0 is in 5 days", "The final weighing was
  4 days ago"), lists what is wrong with a draft (the errors and warnings of `design.problems`), and gives a row a replicate, by
  group with a control badge: its tanks and their days, the batches of the species that were in them on those days (cleaner fish
  never count), the fish and biomass now while it runs, the survival, and bFCR and eFCR. **Every figure is the farm's own number for the
  same stay and the same days** (`experiments/read.overview`): the conversion is `Conversion` of `feeding.read.windows_in`
  bounded by the placement's days (from the baseline weighing on day 0 to the latest weighing, or to the weighing of the
  placement's last day once it has come), summed over the replicate's tanks as a ratio of sums, the fish and biomass come from
  `stock_of`, the survival from the fish there on the first day (in the tanks the replicate began with: a replacement's are the same fish) less the fish lost since (mortality, culls, an adjustment down),
  all bounded by the days: **no "since stocking" figure ever sits beside a trial figure**, no figure is stored or copied, and a draft
  has none. A dash says why (hover it: not weighed, no feed, no growth); a replacement tank without a measured point at the
  move leaves a gap in the replicate's conversion window, and the page says which tank it leaves out. No figure of a group is
  made: a mean over replicates is a statistic, which the statistics come with. The queries do not grow with the tanks (a test counts
  them for 6 and for 60). The **Data** tab lists each tank with its days, the feeding records of them and the feed given (one read of the feeding),
  and links, for those who may read them, to the farm's own lists with the tank and the days chosen: Feeding records, Treatments,
  Sea-lice counts, Water chemistry (its history) and the unit's drawer. `read.placements(unit_ids, day)` says which placement each
  tank has on a day (at most one: the exclusion constraint), for whoever asks which experiment a tank is in (the record lock to
  come).
- **Running amendments** (the **Release** and **Replace** buttons on the Data tab of a running experiment, for those who may
  edit; `services.release_unit`, `replace_unit`). A tank that leaves is released: its placement ends on the last day it was in
  the experiment (yesterday at the earliest, the farm's rule for ending a row that has started; never later than it was booked,
  never before it began), with its **reason**, which is asked. A tank that is replaced ends the day before the new tank's first day
  (today at the earliest) and the new tank takes its replicate's place to the day the old one was booked to, so **the replicate keeps
  its number**; the new tank must be on the site and free of every booking for those days (another experiment's, or this one's, named
  by its number) and no assignment of its own may stand in the way of the diet. The diet follows through the farm's own
  assignments (`farm/feeding/assignments.py`, as at the start): the old tank's row ends the same day (`assignments.end`, logged as an
  edit of the assignment), the new tank gets its row for the group's protocol. The days the old tank was in stay as they are and what it
  gave up to its last day stays in the figures (the figures are bounded by the placement's days, so a replacement without a
  weighing at the move leaves a gap that the Overview names). One row "Places" and one "Reason it left" go on the experiment's log; the
  tanks and batches are locked before the experiment, and a form older than the stored version is refused.
- **The chip beside a tank** (`farm/placements.py`, filled by `experiments.read.chips`, registered in `experiments.ready()`). Production
  units (the row and the drawer) and the meal board show "E-2026-001 · Control · R2" beside a tank that is booked to an experiment today
  (the unit's site's today; a draft reserves its tank, so it shows too, as a draft), linking to the experiment, for those who may read
  experiments. The registry is a list of providers, as the medicine withdrawal's is, and it **fails open**: with none registered, or
  one that raises or breaks its transaction (it runs in its own savepoint), the page shows no chip and nothing else changes. One read of
  the placements for each distinct day, so the farm's pages do not grow with their units.
- **Deviations and `check_experiments`.** The Overview of a started experiment ends with **Deviations from the design**: what the farm's
  own records show on the days of the placements that the design did not say, derived from them (`read.deviations`, never stored, and
  nothing is ever refused for a design): **a batch** of the species that was in a tank on some day and not on its first day (cleaner
  fish never count), **fish moved** between two replicates or between a tank of the experiment and one that is not in it (a move inside
  one replicate, as a replacement makes, is not one), **a feed on no band** of the group's protocol, and **a ration that does not follow the
  diet** (the farm's own `Policy.resolve` gives the batch in a tank another protocol than the group's, or none, on some day: a
  protocol assigned to the batch in the unit beats the unit's, or the diet's row was ended). Each reads the days up to today or the last
  day of the placement, and the queries do not grow with the tanks. `manage.py check_experiments` (`experiments/integrity.py`, as
  `check_stock`) checks every started experiment from scratch for what the database cannot hold: a design that lost a part (a group
  without replicates or without a level, the rules of `design.HOLDS_AFTER_START`), a tank off the site or booked outside the days of the experiment, a
  tank deleted while it is in one, a team without a lead, and, while it runs, a placement of a diet group without its live feeding assignment
  from its first day to its last. The test suite runs it after its scenarios.
- **Delete** goes through the delete plan: a draft is deleted with its factors, levels, groups, replicates and placements
  (one activity-log row each, its tanks free again), a started experiment is refused with the reason. A restored draft
  comes back with its design (what its delete took along, core.softdelete.restore). A copy of a deleted experiment
  keeps pointing at it.
  A protocol a level names, a tank or a department a placement names, and a site or species an experiment names cannot
  be deleted while it does.

**Who may do what**: the area Experiments (Production · Research): Read the list and the read pages, Create makes and copies an
experiment, Edit changes it, saves its design, its places and its team, and starts it, Delete removes a draft. The recommended roles are data in Roles (no built-in roles): a researcher all four, a
student Read, Create and Edit, a technician and an advisor Read. Rights per experiment (a student edits only the
experiments they are in the team of) come with the permissions plan, which reads the team. The admin lists experiments,
deleted ones too, and restores an experiment with the parts its delete took along.

## Regulatory reports (Production › Reports, `/reports/`)

The reports the farm owes Mattilsynet and Fiskeridirektoratet, made from the records and filed by people. Its own app
(`reports/`, tables `regulatory_reports`, `regulatory_report_snapshots` and the rows of a report's answers); it reads the
farm's records through the farm's own reads (the stock fold, the feeding walk, the health records, the water read) and the farm
never reads it, except through the one registry of `farm/health/notices.py`. `docs/regulatory-reports.md` has every field of
every report, where it comes from, the design and the owner's decisions D-1 to D-15; the source's bugs are in the bug document.

**What it does not do.** It sends nothing: no Altinn, Maskinporten or Mattilsynet API call, no scheduler, no e-mail. A person
files the report where the authority takes it, then records here **when, how and with which receipt**. What was filed is
frozen: its content, with a hash that is also in the activity log, and the hash of the records it was made from. If the
records change afterwards (a void, a backdated record, a unit moved to another site) its page says "the records no longer give
what was filed: a correction is needed", figure by figure, each named as the page names it, the unit by its number ("Unit K-02 ·
Fish at the month’s end: 500 → 1000", `reports/labels.py`), never a key of the content; a correction is a new report of the same key that replaces it.

A report's page shows its figures in the kind's own table (smolt, biomass, the slaughter plan, land stock, a site taken
into use or emptied), an event notice's narrative for a notice (`reports.kinds.EVENTS`), and any other kind (sea lice,
cleaner fish) as the print page does: every figure named by **one label registry** (`reports/labels.py`, the words the pages
use, translated, numbers as the language writes them, and what names rather than counts, an organisation number, a
lokalitetsnummer, an approval number, a unit number, a code, a year class, a week, printed as written, never
"987,654,321": `labels.names`, `reports/tests/test_identifiers.py`; a test computes a report of every kind with every optional part filled
(the contact person, a health event and its units, an escape, a planned slaughter by weekday), renders its print page and
describes every path of its content, and fails on any row or difference that is a raw key or "(unnamed figure)"; a second
test reads the computation's code (dict keys and assigned keys) so every key it writes has its
label), never a content or API key and never another kind's fields. The values are said the same way (`labels.shown`): a
date dd.mm.yyyy, a notice's **Found at** on the site's clock as dd.mm.yyyy HH:MM (it is typed there), a coded value (a
batch's biomass basis, a loss's cause) in words. The content keeps the machine form, and so does the **CSV export**: the
authority's field names, dates in ISO and an instant as ISO with its UTC offset (`2026-10-25T06:15:00+00:00`), so the file
says its zone.

**The reports** (`reports/kinds.py`: authority, basis, period, deadline, where it is filed):

| Report | For | Deadline |
|---|---|---|
| Sea lice (lakselusforskriften § 10) | a sea site, an ISO week | Tuesday of the next week |
| Smolt (akvakulturdriftsforskriften § 58) | a juvenile site, a month | the 7th of the next month |
| Cleaner fish (§ 44, § 3 h) | every sea site, whatever its permit, a month in which it held cleaner fish | the 7th of the next month |
| Monthly biomass (§ 44; Fiskeridirektoratet's form is to be confirmed) | a sea site of food fish or broodstock, a month | the 7th of the next month |
| Planned slaughter (restkontrollforskriften § 9a) | a slaughter facility, a week | Thursday 24:00 before, or when the fish start fasting if earlier |
| A land site's yearly stock, a site taken into use, a site emptied (§ 44a) | a food-fish or broodstock site on land, and a hatchery of cleaner-fish juveniles (§ 3 i) | 7 January, when it happens |
| Escape (§ 38), disease (dyrehelseforskriften § 7), welfare (§ 14) | a notice, started by a person from the escape or the health event | at once |

**Due** (`reports/due.py`, read from the records, never stored). Which reports a site owes follows its **production form**
(Facility › Sites, Reports tab), its type and the fish it held in the period (a week or month without fish of the kind owes
nothing); it is listed from its **reports-from** date to the last closed period, minus the filed ones, a draft staying listed
with its deadline and an **Overdue** mark. A site that holds fish and has no reports-from date, no production form or a species with no official code (not known to be
a salmonid) is listed as "Not set up for reports" with what is missing and a link to its form, never hidden. Planned slaughters
are owed per facility and week from the first week the site reports, and the duty arises from the harvest, planned or done
(restkontrollforskriften § 9a): a plan item that is not cancelled (still open or already recorded as a harvest) and a harvest
recorded with no plan at all each owe their week, and a week that has passed stays owed, with its deadline and an Overdue
mark, until its notice is filed or a person closes it with a reason (*Close without filing*, in the activity log, shown under
the kind's tab and reopened from there). Escapes and listed diseases, and an increased-mortality event still unexplained 14 days on (no diagnosis, not closed:
dyrehelseforskriften § 7 second paragraph; a welfare notice), from their records since the site's reports-from date until a notice of each is filed (a
notice told by telephone counts). The days are Oslo's calendar, whatever
clock the site keeps, and the ISO week of 28 December to 3 January is 2026-W53. The page also lists the **filed reports whose
records changed**: only the rows a report read are compared with the ones it was filed from (never a ledger folded again), and a
report of a period older than the last 31 days, the backdating window, is not read again.

**Tabs and where each kind stands.** The Reports page has a tab for every kind of report, always there: *All reports* first,
then the urgent notices (welfare, disease, escape, a land site taken into use or emptied) and the scheduled reports (sea
lice, monthly biomass, smolt, cleaner fish, planned slaughter, a land site's yearly stock), each with the number of its reports
due. A tab lists that kind's reports (drafts and filed) and the filed ones whose records changed, has its own **Start one**
link for people who may create, and above them **Where it stands**: a line for every site (for the planned slaughter, every
slaughter facility) saying *N due*, *up to date* or *not due* and, when nothing is due, why in plain words ("no salmonids in
the sea at Fjord since 2026-10-01", "site not set up: no production form", "Hatchery is not a sea site", "no cleaner fish held
at ...", "no harvest is planned to ... from this week on"). The lines come from the due list itself (`reports/due.py`: the
rule that decides what is owed also gives the reason when nothing is), not from a second copy of it, so a site set up as
food fish that holds no fish says so instead of showing nothing. The site and status filters stay when a tab is chosen. The
**company overview** has an *Upcoming reports* block (the next deadlines of the due list, the overdue first and in red, a notice
at once) for people who may read the reports.

**A report** has a kind, a site (a slaughter facility for the planned slaughter), a period or the day of the event, its health
event or escape for a notice, the contact person (the person who starts it, as the authority asks for one on every report), and for
a notice the person's account of what happened (what, when found, cause, fish dead, injured and involved, the situation, the
measures; filled in from the event when it is started from one). The key (kind, site, period, event) is fixed once it exists and
one live original is allowed for each; a draft can be edited and discarded (the delete plan, restorable in the admin), a filed
report never. A report page shows the figures as the records give them now, what keeps it from being **ready** (a species without
its official code, a site without its organisation number, a cage that was due a count and has none, a treatment without an
amount: each with where to put it right) and what is worth a look.

**The answers no record holds** are rows on the report's form while it is a draft: for the sea-lice week, whether each treatment was
given before the count and which were given together (the records carry dates, no times), the suspicions of resistance and the
sensitivity tests; for the biomass report, the units used for production of reduced capacity. They are frozen with the filing.

**Clocks.** The time of a filing is Oslo's, as the authority keeps it; the time something was found is typed on the site's own
clock (Facility › Sites) and stored as the moment it was; the browser's zone is never used.

**A value the authority has not confirmed** (the amount of a lice treatment, the type of a medicated feed or an injection: questions
Q1 and Q2 of the register Production › Reports › Questions for the authority) is shown with its question on the report's
page, and the filing is refused until the person confirms it was checked by hand; the confirmation is logged. Answering the
question in the register lifts it.

**Filed late.** Recording a filing stores the deadline and whether it came after it (the day in Oslo); the report and the list say
"Filed 2 days after its deadline" and a notice, filed at once, is never late. **Said, not assumed:** the biomass report's harvest weights are the round kilos weighed at
harvest, the only kilos the farm holds, and say so (`slaktetilstand` round): it never asks, so round kilos cannot be filed as gutted
(audit F-086; gutted kilos come with the slaughter result, OUR-18); a cleaner-fish
month with no feed recorded is a problem unless the person says none was given. The cleaner-fish file for the API has one row per
species, with the mixed origin when both farmed and wild-caught fish are in it.

**Through the reporting API.** The system sends nothing, but a person who files through the API can record the id it returned (the filing
form); the JSON export of a correction then says how the API takes it, `PUT` to that id, with the client reference of the filing it
replaces (`X-Api-Method`, `X-Api-Path`, `X-Corrects-Client-Reference`; the print page says the same), and the sea-lice endpoint, which
has POST only, is said to. The facts of the contract (scopes, headers, methods, errors) are in docs/regulatory-reports.md, 7.2.

**A research site.** A site's production form can be *Research or other production*: it owes no juvenile, biomass or yearly stock report
(only chapters 1, 2, 3 and 7 of the regulation apply, § 3 l) and has no operating plan; the sea-lice and cleaner-fish reports and the
notices still follow the fish, and the lines of the Reports page say it is unverified with the authority (question Q10).

**Duties outside this system.** The operating plan (driftsplan, due 1 October each year for every sea site of food fish or broodstock, idle
ones too) and the lice coordination plan (§ 4, before 1 October each year, sea sites with salmonids) are listed as due lines with a
reminder on the Reports page and the company overview; you file them in Altinn and record here when and with what reference. The page
*Duties outside this system* lists them and the others (the land broodstock report of 15 July, recapture, executed slaughter, the county
governor's report, the cleaner-fish broodstock report) with their deadline, channel, whom they bind by production form, a link to the text
and what is not verified. Nothing is sent and no form is built for them.

**What you are about to record.** Before a filing is recorded, the report's page says "What you are about to record as filed", with
the content hash and a link to the print page (the exact values to type, each figure named); every export
carries the same hash. The recording posts that hash, and if the records changed meanwhile (a backdated record) it is refused
with "review it again": what is frozen is exactly what was previewed.

**Recording the filing** (Edit): when, through what (Altinn, the reporting API from another system, e-mail, telephone, other)
and the receipt or reference (none for a call). In one transaction the report is locked, its version checked, its content computed
and stored with its hashes, and the filing logged with the hash. A report that is not ready is refused, except a **notice given
by telephone**, which is recorded as it was told, what was missing kept in the log entry. A database trigger keeps a filed report,
its content and its answers unchanged whatever writes them.

**Exports** (Read): a printable page, CSV (section, the authority's field name, value; text guarded against spreadsheet formulas,
numbers left numbers) and, for sea lice, smolt, cleaner fish and planned slaughter, **JSON in the shape of Mattilsynet's reporting
API**, validated in the tests against its OpenAPI. They are built from the frozen content once the report is filed, else from
the records now, and say which.

**What each computes** (nothing is typed but the contact person and the answers above):
- *Sea lice*: the week's counts per cage and the site's average per stage (the mean of the cages' averages, as the regulation
  says), the cages that held salmonids and were due a count (7 days, 14 below 4 °C; none for broodstock below 4 °C, nor when every
  fish is planned for slaughter within 14 days of the day the count fell due, whether the harvest is still planned or already
  recorded (a plan whose harvest was voided is open again); a cage with no production fish left on that day needs none), the sea temperature (the mean of the week's samples at the site's depth points of
  3 m, from Water chemistry), the week's lice treatments with substance, strength and amount from their records (the amount is
  the product's: Mattilsynet's § 10 c asks for the active substance's, so the report says to confirm which it wants). A
  treatment of the week with a sea-lice medicine recorded for another reason is not in it, and the report warns of each one
  (void it and record it again if it was given against sea lice) and reads it for its fingerprint. The fingerprint also
  reads what decides whether a cage was due a count: its earlier counts and the harvest plans (audit F-206).
- *Smolt*: per tank and species that held fish, its number, species, the fish and average weight at the month's end (a tank
  emptied in the month reports the fish just before, less those moved to another tank of the site, which are in that tank's
  count), and the fish dead, culled and moved out of the site, deliveries included. A tank that held two species one after the
  other is listed once for each, with a warning.
- *Cleaner fish*: per unit, species and origin the fish at the end of the month before, those stocked and moved in, those taken out
  by the six causes, dead and moved out, the month's count adjustments netted (an escape and a recount up in one month are
  warned about, so the netting does not hide the escape), and the dry and wet feed of the cleaner fish.
- *Monthly biomass*: per production unit the fish stocked, the stock and its biomass at the month's end with how it was worked out
  (the last weighing, the feeding projection where feed was credited since it, or the last weighing marked stale), the harvest, the live fish moved to another
  site, the losses by cause and the feed; the day the site was left fallow. Broodstock at sea is warned that the season it was put
  out in and the permit it is reported for (§ 44 second paragraph) have no field yet.
- *Planned slaughter*: per locality, species and weekday the whole kilos of the week's planned harvests to the facility (a
  cancelled one is left out), filed by the company that operates the slaughterhouse (its nine-digit organisation number from
  Purchasing › Suppliers), never by a farm whose fish it slaughters.

**`manage.py check_reports`** checks every report from scratch (a filed one has its content and the content its hash, a draft has
none, a correction corrects a filed report of the same key, a notice is of its event's site); the tests run it after their writes.

**Roles.** The area **Regulatory reports** (Production · Reports): Read the page, a report and its exports; Create starts a report, a
notice or a correction; Edit fills in a draft and records the filing; Delete discards a draft.

**Differences from the source.** Nothing is filed by the system and no draft is made behind anyone's back; the figures are never
stored beside the records; the source's wrong cleaner-fish codes (USB for lumpfish, BER, GRO, BNB), unknown origin, unit counts by
weight and missing dry and wet feed are not ported; the source's per-tab wizards, thresholds tables and scheduler are not ported.
The bugs found in it (REP-01 to REP-62) are in the bug document.

## Messages (Production › Communication, `/messages/`)

People write to each other in **direct conversations** (two people) and **channels** (a name and its
members). It sits in the Production panel under a main heading of its own, **Communication**: it is neither
the farm's structure (Setup) nor a production record (Operations), and it is where the AI assistants will
join the people running production (below). The menu entry shows the person's unread messages, and the
panel switcher a panel's total. App `messaging`, tables `conversations`, `conversation_participants`,
`messages` and `assistants`.

**The page** has the person's conversations on the left, the latest activity first, each with its last
message ("You: …" for one's own) and its unread count, and the open conversation on the right: its latest 50
messages (earlier ones a link away), a "New" line above the first one not read before, the compose box
(Enter sends, Shift+Enter starts a new line) and, for a channel, its member count and **Members**. **New
message** asks for a person and opens your direct conversation with them, the one you already have if there
is one; **New channel** asks for a name and the first members. On a phone one of the two columns shows.
Times are on the company's clock (`COMPANY_TIME_ZONE`, the `company_clock` filter), as in the activity log.

**The rules**, each where it can be held:

- A direct conversation is one per pair, whoever starts it: the conversation's `direct_key` (`user:3
  user:7`, sorted) is unique in the database, and when both people start it at the same moment the second
  insert fails on that key and is answered with the first one. A direct conversation is never left and has
  no members to manage.
- A participant is a person **or** an assistant, exactly one (a database check), once per conversation,
  left or not: leaving or being removed is a soft delete (who and when kept), the name stays on one's
  messages, and adding the person again brings the same row back.
- A message's author is a participant of the message's own conversation, and a participant's read pointer
  is a message of their own conversation: two foreign keys on two columns each, added by migration
  `messaging/0001` (Django cannot declare them). A message has text (not only spaces) and at most 4000
  characters (a check and the column's length); a deleted one says when.
- Only the members of a conversation read and write it: to anyone else it does not exist (404 on every
  page and fragment, also for the platform admin, who is not a member of other people's conversations).
- A channel's owners add people, remove members and make members owners or owners members; anyone leaves.
  A channel with members keeps an owner: the last one cannot leave, be removed or step down while others
  remain. A channel its last member leaves is deleted with that membership at one moment (logged; its messages stay with
  it, and the admin's restore brings it back with that member), so its name is free again (F-110, cross review F5).
  Channel names are unique among live channels, whatever their case.
- Messages are never edited: a correction is a new message, as a void and a new entry is for the records.
  The author deletes a message: the row stays with who deleted it and when, and everyone sees "Message
  deleted", never the text again (in the conversation, the list, the polls).
- Only people who may use Messages (an active account with the area's Read) are offered or accepted as the
  other party or as members; they could never read what is written to them otherwise.

**Unread** for a participant: the messages of the conversation after their read pointer, written by someone
else, not deleted. Opening a conversation (and each poll of it) moves the pointer to the last message it
shows; the pointer only moves forward (one `UPDATE … WHERE last_read < n`). A new member starts with the
conversation's latest message as read, so joining a channel brings no history in as unread. The pointer is a
message number, not a time: posting locks the conversation, so its messages are numbered in the order they
are committed and a reader's pointer never passes a message that was still being written (the source's
time-based pointer could, MSG-21).

**Live updates** are polled for the MVP, by `frontend/poll.ts` and only while the page is in view: the open
conversation asks every 5 s for the messages after the last one it shows (`/messages/<id>/new/?after=`,
rows to add, 204 when there are none, the next address in `X-Poll-Next`), the list of conversations renders
itself again every 15 s and the menu's badge every 30 s. The server renders every fragment; the browser only
puts it in place. **What replaces it:** a push channel (server-sent events under ASGI, or a WebSocket with
Django Channels and Redis for several processes) that listens to `messaging.events.message_posted`, sent once
a message is committed, and tells the members' open pages and the mobile app which conversation changed;
they fetch the same fragments (or the API's rows) they poll today, so the server side stays as it is. A
message deleted after it was shown stays on an open page until it is reloaded (the push will carry deletions).

**The activity log** records the channels: created (name, members, owners), members added and removed,
owners changed, each with the lists before and after, under the record type "channel". It records no message
and no direct conversation: the log is read by roles that are not members (Activity log: Read), would show
them what was written or who writes to whom, and a message already keeps its author, time and who deleted it
on its own row. **The database viewer** masks `messages.body` (`config/database.py`): the platform admin sees
who wrote in which conversation when, the read pointers and the deletions, enough to check the unread counts
against the rows, but not what people wrote to each other, which is for the members (they read it on the
page). Whoever runs the database itself can still read the column: that is an operations matter (access to
the server and its backups), not the application's. The Django admin does not list the messaging tables.

**Who may do what:** the area Messages in the role matrix (Production · Communication): Read is the Messages
page, writing in one's own conversations and starting a direct conversation; Create also creates channels.
Owning a channel is the channel's own role, not the matrix's. The platform admin has both but, like everyone,
reads only the conversations they are a member of.

**The code**: the one write path `messaging/services.py` (start or get a direct conversation, create a channel,
add and remove members, change a role, leave, post, delete a message, mark read), the reads
`messaging/read.py` (the list with unread counts and last messages, the unread total, a conversation's
messages), the pages `messaging/views.py` (they only call those two), the event `messaging/events.py`.
Services raise ValidationError for what was entered, PermissionDenied for what the person may not do and
Http404 for a conversation they are not in, so a REST API for the mobile app (Django REST framework) calls
the same functions and maps the same three answers; none of the rules is in the views.

### AI assistants (designed for, not built)

Every person will get one or more AI assistants, and assistants will watch the farm's systems; they take part
in the same conversations as the people. What exists now is the shape: `Assistant` (a name and an owner,
none for an assistant that watches systems; no rows, no screen) and a participant that is a person or an
assistant. How the AI work plugs in:

- **Who writes an assistant's message:** a worker, never the browser. It calls `services.post(participant,
  body)` with the assistant's participant row: the same write path, numbering, unread counts and polls as a
  person's message. A person can never post as an assistant: the pages only post as the person signed in
  (`post_as`).
- **How a message reaches an assistant:** a listener on `events.message_posted` (sent after the commit)
  finds the assistants taking part in the conversation, decides whether the message is for one (a direct
  conversation with it, its name mentioned in a channel) and queues the work; the listener only queues. The
  worker builds the context from the conversation's messages (the assistant's own as the model's turns, the
  others' with their authors' names) and replies. A watching assistant posts on its own schedule, the same
  way, in a channel set up for it.
- **Its rights:** an assistant reads only the conversations it is a participant of, like a person; a person's
  assistant acts with no more rights than its owner (the worker checks the owner's permissions).
- **Tool calls and proposed actions, later:** a message can carry a proposed action (record a feeding, a water
  sample) in a table of its own linked to the message, with a status (proposed, accepted, refused, done) and
  who decided. A person with the right permission accepts it, and it runs through the tab's own write path
  (`farm/feeding/services.py`, `farm/water/services.py`) as that person, so every check and activity-log row
  stays as it is. Nothing an assistant proposes is written without a person.
- To come with it: the assistant's settings (model, instructions, which systems it watches) on `assistants`,
  and the direct key of a person–assistant pair (`assistant:<id> user:<id>`, `services.direct_key`).

Differences from the source (`apps/messaging-service`, `web/modules/messaging-module`; details in the bug
document, MSG-01 to MSG-21):

- One model. The web's messaging uses the messaging service's channels; the auth service's `message_threads`
  are SuperAdmin ↔ tenant-admin support tickets, a separate model with its own unread counters, not ported.
- Unread is one rule everywhere, without one's own and deleted messages and only in live conversations
  (MSG-05, MSG-06); the pointer is a commit-ordered message number, not a time (MSG-21), and is only ever a
  message of its conversation (MSG-10).
- A direct conversation started twice at once returns the one conversation (MSG-07); a deleted message's text
  is never served again (MSG-02); only a member deletes, and only their own message (MSG-03); a channel keeps
  an owner, and owners can hand over (MSG-15); names fit their column (MSG-14).
- Screens to start a direct conversation, create a channel and manage its members (the source's web had none).
- Not ported: attachments (MSG-01), reactions, pins, threads (MSG-16), forwarding, editing, typing indicators
  and presence, search, notification preferences, archiving, legal hold, receipts per message, sockets and
  NATS (polling for now, above), AI personas (the assistants above replace them), tenants.

## Knowledge (Company › Knowledge: Library `/knowledge/library/`, Knowledge entries `/knowledge/entries/`)

The place where people record what the company knows, so that AI agents can later watch the farm with it and
cite it: "in salmon under 50 g, CO₂ above 15 mg/L causes disease" (from an article) is to warn the person
when a unit's live values match and name the article and its page; "a feed order is at least 20 t and arrives
in 3 days" (from a supplier's terms) is to let an agent propose a purchase order. Knowledge is not only about
fish, and it belongs to the organisation, so it sits in the **Company** panel, in the group **Knowledge**. App
`knowledge`, tables `documents`, `document_pages`, `document_species`, `knowledge_entries` and
`knowledge_entry_species`. What is built now is the recording; the agents are designed for (below), not built.

**The Library** holds documents: articles, reports, books, guidelines, regulations. A document has its
reference (title; authors, one per line, family name first, in their order; year; where it was published;
volume, issue and pages; DOI and web address), its abstract, language, topics, species and optionally its
PDF. The list (50 a page) shows each document with how a text cites it ("Olsen & Hansen (2019)"), its year,
topics, species, the PDF with its page count and whether its text was found, and how many knowledge entries
cite it; filters by topic, species and year; a search over everything, PDFs included. The read page
(`/knowledge/library/<id>/view/`, for everyone who may read the library) shows the full reference in APA 7 form
(`knowledge/citation.py`: "Olsen, B. E., & Hansen, K. (2019). Title. *Aquaculture*, *512*(3), 45–67.
https://doi.org/…"; a document without authors is cited by its title, one without a year with "n.d."), the
abstract and details, **Open the PDF** and **Download**, what reading its text gave, after a search the pages
where the words are with their passages, and the knowledge entries taken from it with **Add knowledge from this
document**. **Read the text, page by page** shows what was read from the PDF, 20 pages a screen.

The rules, each a database check as well: a title; authors without empty lines (spaces trimmed on save); a
year from 1500 to 2100 (and the form refuses one later than next year); a DOI that starts with `10.` and has no
spaces, stored without its link (`https://doi.org/` or `doi:` typed before it are removed) and unique among
live documents whatever its case, so the same article is not added twice; a web address with http or https
only; topics from the list; the file and what is known about it come together (below).

**The file.** A PDF of at most `KNOWLEDGE_MAX_FILE_BYTES` (20 MB, `config/settings.py`), its name ending in
`.pdf` and its first bytes `%PDF-` (the browser's word for its type is not trusted). It is stored by Django's
storage under `MEDIA_ROOT` (`DJANGO_MEDIA_ROOT`, by default `media/` in the checkout, not committed) under a
name of our own (`knowledge/documents/<random>.pdf`); the uploaded file's name is kept on the document for the
person and the download. **There is no public address**: no `MEDIA_URL` route exists, and the file is sent only
by `knowledge.views.document_file` (`/knowledge/library/<id>/file/`, `?download` for an attachment) to a
signed-in person with the Library's read permission, for a live document, `private` for caches. Replacing or
removing the file (the File tab's **Remove the file**) deletes the old one from the storage once the change is
committed (a rolled-back save keeps it); a deleted document keeps its file and text, for a restore. Django
streams a large upload to a temporary file before the form can refuse it, so the web server in front must cap
a request's body too (e.g. nginx `client_max_body_size 25m`).

**Its text** is read when a new file is saved (`Document.save`, `knowledge/extraction.py`, pypdf): page by page
into `document_pages` (the page's number and, when the PDF labels its pages as the journal does, its printed
number, so a citation can say "p. 237"), normalised to NFKC (the ligatures of PDFs, "ﬁ", read as "fi"; "CO₂" as
"CO2") and without control characters. The outcome is on the document: **Text found** (with the page count),
**No text found** (a scan: pages that are images; not an error, its text needs OCR, which is not done yet), or
**Could not be read** with the reason (a damaged PDF; one protected by a password; one with only an owner
password is read, with `cryptography`). The PDF is kept whatever the outcome. The reading runs in the request
(fine for the MVP's articles; a worker with a time limit is the place for it when books and scans come).

**Searching** (`knowledge/search.py`). Every searchable text is a `tsvector` in a **generated column**, so the
database keeps it in step with the text whatever writes the row, each with a GIN index: a document's own
(title weighted A, authors B, abstract C, venue D), one per page of its PDF (so no vector meets PostgreSQL's 1 MB
limit and a hit names its page), and an entry's (statement A, quote B, section and citation C, person D). The
stored texts are analysed with the **`simple`** configuration: lower case, every word as written, whatever the
language. The library holds English, Norwegian and Turkish texts, often mixed in one document (a Norwegian
report with an English abstract, a Turkish thesis with an English one), so no single language's stemmer suits
the stored side, and a per-document language would stem half of such a document wrongly. The stemming is
done on the **query** side instead: each word typed is analysed with the `english`, `norwegian` and `turkish`
stemmers and with `simple`, and each stem is a prefix, so "diseases" finds "disease", "fisken" finds
"fiskehelse", "balıklar" finds "balıklarda"; stems shorter than three letters and numbers match whole ("pH" is
not "phosphorus", "15" is not "150"). Every word must be in the document, in its own vector or on any of its
pages ("Olsen nephrocalcinosis" finds Olsen's article that speaks of it on page 4); an entry matches by its own
words or those of the document it cites. Results are ranked by `ts_rank` (a title hit above an abstract hit
above a hit in the text), the best page's passage shown with the words marked. What is typed is turned into
quoted lexemes, never read as query syntax.

**Knowledge entries.** An entry is a statement in the person's own words (at most 2000 characters), its topics
(at least one: water quality, feeding, health, growth, welfare, harvest, procurement and logistics, equipment,
regulation, other), the species it holds for (none: any), and **its source, exactly one kind**:

- **A document in the library**, with the page(s), the section and the quote (the document's own words);
- **Another published source**: its citation as a reference list gives it, its web address, or both, and
  optionally a quote;
- **An expert or our own observation**: the person ("Kari Nordmann, fish health vet") and optionally when.

The form shows the fields of the kind chosen (choosing another renders the form again, `refresh_on`), and saving
empties the fields of the other kinds (`KnowledgeEntry.clean`). The database holds it whatever writes the row:
one check per kind says that kind has what it needs and that the other kinds' fields are empty, a check keeps
the kind in its list and the quote away from an observation. The list (50 a page) shows each statement with its
source in a line ("Olsen & Hansen (2019), p. 4, 3.2 Results") and its status; filters by topic, species, kind of
source and status; the read page shows the statement, the source (the document's full reference, linked to it
for people who may read the library) and the quote.

**The review.** An entry is a **draft** until someone with the Edit permission marks it **reviewed**
(**Mark as reviewed** on its read page or on the Review tab of its dialog, `knowledge.views.review_entry`): the
reviewer is the person signed in and the time is now, never typed, and a database check keeps the status, the
reviewer and the time together. The review is refused when the entry changed since the reviewer opened it (its
version), and **Back to draft** undoes it. Editing the statement, topics, species or source of a reviewed entry
takes it back to draft and says so, so a review always covers the words as they are. AI agents will act on
reviewed entries only.

**Who may do what:** the areas Library and Knowledge entries (Company · Knowledge) with read, create, edit and
delete; for entries, Edit also reviews. Reading the PDF and its text needs the Library's read.

**Deleting.** A document cited by a live entry **cannot be deleted** (`PROTECT`): the entry *is* its source, an
entry pointing at nothing would say nothing anyone could check, and the "exactly one source" check would refuse
the detached row anyway. The confirmation says how many entries cite it; re-point or delete them first. A
deleted entry's document can then go; restoring the entry waits for its document (core.softdelete.restore).
Deleting a species keeps the documents' and entries' links to it, out of sight, as for feeds. Both are soft
deletes, restored from the admin.

**The activity log** records a document's metadata as for every tab, its file by its own name (never the
storage's), and what reading the text gave (Text, Number of pages): **never the text itself**. An entry's log
has its fields and its review (Status, Reviewed by, Reviewed at). **The database viewer** (section Knowledge)
shows the extracted text and the search vectors as it shows any long text: cut to 80 characters in the grid, at
most 5,000 on click, whole only in the CSV export.

### AI agents: how they plug in (designed for, not built)

Nothing below exists yet; the tables above are shaped so it can be added without rewriting them.

**The Rule** (a table of its own, `knowledge_rules`, one entry to many rules): the structured form of an entry
that a program can apply. It **cites its entry** (`entry`, `PROTECT`), so every warning or proposal it makes
names the entry, and through it the document, page and quote.

| Field | What it holds |
|---|---|
| `entry` | The knowledge entry it applies (its source, its review). |
| `subject` | What it is about: a production unit's water, a batch, a species, a supplier's orders. |
| `species`, `stage`, `weight_min_g`, `weight_max_g` | Scope: the species (none: any), the life stage (`InputStage`), the band of average weight (`FeedSuitability.suits` semantics, lower included, upper excluded). |
| conditions (rows of `knowledge_rule_conditions`) | Each a metric, an operator and a value in the metric's unit, all to hold: a water parameter of `farm/water/parameters.py` by its key (`co2_mg_l`, `oxygen_mg_l`, `tan_mg_l`, …, and the worked-out NH₃-N and O₂ saturation), the average weight, the density, the days since stocking, a supplier's or feed's terms (minimum order in kg, lead time in days). The metric list is code, like the water parameters, so a value is never compared in another unit. |
| `consequence` | What follows, in words, and its kind: a warning, a proposed action (a purchase order, a water exchange). |
| `severity` | Information, warning or critical, as the water limits' bands. |
| `status` | Proposed (by an agent), accepted, retired; who accepted it and when. |

Example: entry "In Atlantic salmon under 50 g, free CO₂ above 15 mg/L leads to nephrocalcinosis" (Olsen et al.
2019, p. 4) → rule: subject unit water, species Atlantic salmon, weight below 50 g, condition `co2_mg_l > 15`,
consequence "risk of nephrocalcinosis", severity warning.

**Extraction proposes, a person decides.** An agent reads a document's pages (`document_pages`, page by page;
for long ones, chunks of pages with an embedding each in a table of their own written by the same save that
writes the page, pgvector, so they can never disagree with the text) and **proposes** entries, as drafts
whose source is the document with the page and the exact quote, and rules for them, as proposed. Nothing
proposed is used until a person reviews the entry and accepts the rule. The quote is checked against the
page's text before it is shown, so an agent cannot cite words the document does not have.

**Warnings cite their source.** An evaluator, next to the water's (`farm/water/evaluate.py`), applies the
accepted rules of reviewed entries to the values read now (a unit's latest water, its batches' average weight
from the stock ledger): a match is a warning on the unit and in the drawer, "CO₂ 17 mg/L: risk of
nephrocalcinosis in salmon under 50 g. Olsen et al. (2019), p. 4", linked to the entry. As for the water,
nothing is sent yet; the MVP alerts nobody. A proposed action (the purchase order) is a proposal a person
accepts, written through the tab's own write path as that person, as the Messages' assistants will do.

**Owner decision open:** whether a person may review their own entry (four eyes). Today anyone with Edit may;
a check `reviewed_by <> created_by` and a Review column of its own in the role matrix are the two changes it
would take.

Not built now: OCR of scanned PDFs, other file types (Word, images), reading the text in a background worker,
embeddings, the rules and their evaluator, exporting references (BibTeX, RIS), fetching a reference from its
DOI (Crossref), versions of a document's file, phrase search ("…" in the query).

## Sensors (the Sensors panel, `/sensors/`)

Live values from field devices over MQTT, stored in TimescaleDB, drawn as charts, and joined to the water of the tanks,
ponds, cages and systems. A panel of its own, chosen from the panel switcher like Production, offered to people who can
use something in it. Django owns every table, view, trigger and page; a Rust service (`sensors-ingest/`, its own branch
and README) subscribes to the brokers, decodes, validates, reduces and writes. The contract between the two is
`sensors/CONTRACT.md`, held by the database itself and checked by `sensors/tests/test_contract.py`.

What works:

- **Setup**: Connections (the MQTT brokers; the ingest's own sign-in is a secret *file* name, never a secret), Payload
  formats (how a kind of device writes its messages: one object with a value per channel, or a list of named items;
  where the device time and the sequence number are, as JSON pointers; no time: the receive time, flagged), Devices (one
  topic each, at a site (the site of where it is placed), optionally the instrument of a piece of equipment; offline after three intervals without a
  message), Channels (what a value measures, from the quantity catalogue `sensors/quantities.py`; a pH channel's pH
  scale, NBS unless set, its values put on the NBS scale where the water is read and the ones from before a change of
  scale used nowhere (Water chemistry, after the water-chemistry audit of 2026-11-19); where it is in the
  message; the unit conversion; how it is stored: every value, or a value that moves past the deadband and at least once
  per heartbeat; fresh for its own number of heartbeats (`fresh_heartbeats`, 3 by default, 1 to 20); a range outside which a value is stored but flagged and used nowhere;
  maintenance and retired states; calibrations as a list on the site's clock, applied by the ingest at the device time,
  never rewriting stored values), Bindings (where a channel's values belong over time: a sampling point or a system for a
  water value, a piece of equipment or a system for a process value; one primary and one backup per place and quantity;
  a move ends one binding and starts the next, so a sensor's earlier values stay with the tank they were taken in; a
  whole device moves at once, between sites too, or is taken out of the water: see Portable sensors).
- **Operations**: Charts (a place and a quantity over a preset or chosen time, drawn by the server; the CSV is exactly
  the drawn buckets; `sensors:chart_data` gives the same chart as data for the redesigned page behind `?ui=next`:
  `sensors/chart.py` `data`, exactly what the SVG draws, each manual sample with its source, meter or lab, the fish's
  limit bands for a person who may read the water, the channel's newest value with its freshness, whether the drawn
  values come from the live demo's channels ("Simulated values", `sensors/demo.py` `demo_channels`), and with
  `compare=<place>` and `compare_quantity` a second chart read on exactly the same window; each bucket's sum adds its
  rows in time order, so the same chart and CSV are the same on every read), Live values (every channel listened to, its last value at its quantity's decimals, the water parameter's
  own, as the water pages say it: `sensors/templatetags/sensors.py` `measured`, also the alarm thresholds and peaks; its
  age, fresh or stale, where it is bound),
  Dead letters (what the ingest could not store, counted, the payload shown escaped as text and hex; resolved by a
  person, logged), Alarm rules and Alarm events (each event is an alarm of Company › Alarms, which notifies its recipients and keeps
  who acknowledged it; the Acknowledge button here writes that record).
- **Administration**: Credentials (a publisher's sign-in at the broker; the secret is made on the server, shown once
  when made or replaced, stored only as Mosquitto's `$7$` PBKDF2-SHA512 hash, masked in the database viewer and never in
  the activity log).
- **Overview**: the ingest alive or down (a heartbeat within 90 s), devices online, channels without a fresh value, dead
  letters of the last day, open alarms, devices not placed; each tile for the right that may read it.

### The water's latest value (owner rule A9, 2026-11-07; it replaced A1)

Per unit and parameter, each on its own, in one place (`farm/water/read.py` `latest`, the sensors reach it through the
registry `farm/water/sources.py`, registered by `SensorsConfig.ready()`; the farm never imports the sensors): among the
unit's OWN fresh values (the sensors on its points and its own manual or lab samples, at every active point measuring
the unit's own water, A9.1 "its own sampling points": the middle, a depth point, an outlet, a drain, never an inlet,
which measures the supply stream (owner, 2026-11-08); between two channels measured at the same time the
primary before the backup, a point's before a later-named point's) the
newest by measurement time wins, whatever its origin; only when it has no fresh value of its own does the system stand in,
for the middle point: the newest fresh value of a sensor on the unit's system, of a sensor bound to the system's loop
point, or of a sample of the system's loop; else the newest of its own values, shown stale, else the system's. A value
standing in from the system is judged for the unit's fish, as the unit's own would be. The rule is ONE function,
`read.choose(tiers, now, fresh)`: the latest values (`read.latest`), a value at a moment (`Series.latest`) and the
ration's temperature (`feeding.temperature.TemperatureBook.at`, which adds the loops of parent systems as further tiers)
all pick through it, from the same places, with one tie-breaker at one measurement time: a sensor before a sample, the
primary channel before the backup.

**The worst fresh value decides the status** (owner decision 2026-11-08, on the second cross review's P2, where a
20-hour-old manual 9.0 mg/L hid a system probe reading 3.0 mg/L now): the value SHOWN stays A9's choice, but the status,
and so the card's state and alarm, is the worst judgement among every fresh value of the place (its own points' and its
system's, each judged for the unit's fish; never an inlet's, never a stale one) (`read.worst_fresh`). When another value
decides it, the reading says so beside the value on the water page and the card: "system sensor #1 reads 3.00
(08.11.2026 12:40): the worst fresh value decides the status" (a sample is named with its point). Each place's
readings are judged on their own copy, so a loop value standing in for two units carries each unit's own judgement. **Computed for the unit,
measured at the point** (owner, 2026-11-08): a unit's middle point shows the unit's status (`PointWater.status`), and
the card names the point that drove it ("Carbon dioxide (mg/L free CO₂) (T-01 › East side outlet): Critical"); a count
of critical sampling points (the water page, the overview tile) counts what was measured at each point
(`PointWater.point_status`, which keeps the point's own old critical too), so one physical problem is counted once.
**Every limited quantity** goes through the worst fresh value (`read.WORST_FRESH_CODES`), the derived NH₃-N and NH₄-N
too: every sample's own NH₃ (its TAN with its own pH and temperature) and the sensors' worked-out one are its candidates,
so a newer OK TAN elsewhere never hides a fresh critical NH₃ (third cross review). **A unit without an active middle
point** is read through its first active own-water point (`read.anchors`: depth, outlets, drain; never an inlet), which
then stands for the unit (`PointWater.for_unit`) with its other points and its system: never "Not measured" while an
outlet or the system has a fresh value. A derived oxygen is no second card reason beside the measurement it comes
from.

A stale value never enters a calculation whose result is JUDGED (PLAN A9.3; the one thing drawn from old values is the
unit's Deffeyes chart, by the owner's decision of 2026-11-12: the chart, and the calculated CO₂ and pH window a
monitoring card takes from it, are drawn from the latest values received and say which of them are old, "Last known
position"; nothing is judged from them): a value is worked out (the other oxygen unit, NH₃, the oxygen
judged through the mg/L row) only from values fresh AT its own time (`read.fresh_at`: measured at or before it, or within
the clock's skew after it, and still fresh then), so a 3-day-old saturation is never judged with today's temperature and
a salinity older than its 7 days is not used (the value is then not worked out and says why: "Needs the salinity: none
was measured here in the 7 days before.", "Not worked out: the TAN is no longer fresh."). A % judged against an mg/L
limit (or the reverse) says so beside it: "Judged as 3.98 mg/L. Worked out from 9.0 °C, 0.0 ‰ and 1.000 atm. Limit:
Atlantic salmon: critical below 6.00." (`Reading.through` keeps the converted reading and its limit rows). A channel in maintenance
or retired is skipped. A value stamped further ahead of the server's clock than the platform owner's clock tolerance
(Platform settings, 300 s by default: a device whose clock runs fast) is never fresh and never shown as the newest, but up to the ingest contract's hour
(`evaluate.MAX_AHEAD`) it takes part in the worst fresh value and says so ("The device clock is ahead by 10 min.");
beyond the hour it is a data error the card says ("Dissolved oxygen (mg/L O₂): timestamp in the future"), never
silently OK. A probe bound to the loop point is a system sensor in a unit's system tier. Sensor values enter as the parameter's Decimal at its decimals and are judged by the same water
limits. Derived values follow their base value's source (a sensor TAN gives NH₃ only with fresh sensor pH and
temperature, at the oldest input's time; a manual TAN only with its own sample's). Every latest value on the water page,
the monitoring cards and the Deffeyes window says where it comes from and how old it is ("unit sensor #12 · 12 s ago",
"system sensor #3 · 40 s ago", "manual · 2 days"), on a line of its own under the value, printed by one part
(`templates/farm/_water_source.html`) that keeps the origin and the age apart, so the line breaks between the two and
never runs into the figure; a card's water cells are wide enough for either on one line; when the sensors cannot be read, the pages say the values come from
the samples only. The ration's temperature takes a fresh sensor value at its moment too.

A unit's or a system's Deffeyes can be drawn as it was at a past moment (`?at=` on the window's address, read by
`core.dates.read_moment`, 1900-2100, else 400; the site's
clock): the samples taken up to then and each channel's value then, from the bindings that held then. The hourly trail of
a unit's point on the diagram is `sensors:trail` (JSON, from the hour rollup: `points`, the hours `missing` an input and
the hours `impossible`, whose pH and alkalinity cannot go together, never drawn). The monitoring card's own buttons for
these, for a place's charts (`sensors:target_charts`) and for binding a channel from a card (`sensors:binding_create`
with `?channel=&target=`) are left to the card-template designer.

### The Deffeyes replay (owner amendments A6, A7, A8)

`sensors.read.deffeyes_frames(target, start, end, step, cursor)` and its JSON endpoint `sensors:deffeyes_frames`
(`?target=unit:<id>|system:<id>&start=&end=` on the site's clock, or `range=`; `step` in seconds; `cursor`) give a unit's
or a system's water at every step of a range, for a player that moves it over the diagram (the player, its speed and its
controls are the UI's, not built here):

- The user's step is kept, snapped up to the chart ladder (1 min, 5 min, 15 min, 1 h, 1 day ...), never widened: five
  days at one minute are 7 200 frames, served in pages of at most 2 000 (`cursor` the page's first frame, `next` the
  following page's, None after the last).
- Each frame reads what a unit's chart reads (temperature, pH, alkalinity, salinity required; TAN and oxygen when
  there), each by owner rule A9 at that moment through the live view's one function (`farm.water.read.choose`, over
  `sensors.read.tiers`: the unit's own-water points, never the inlet, then its system's sensors, those on its loop
  point and the loop's samples): the newest of the fresh values (a sensor value at or before it, no older than its
  channel's freshness (its fresh heartbeats), at the parameter's decimals as the chart takes it; a fresh manual or lab
  sample), a sensor's before a sample's at one time; else for the salinity of fresh water the assumption; else missing.
  Nothing is interpolated or carried past its freshness. A moved sensor counts for the place it was in. The hourly
  trail (`sensors/trail.py`) picks each hour's inputs the same way at the hour's end.
- One query of the readings per tier and page. Below an hour each channel's value at a frame is what the live view's
  rule (`value_at`) gives at its moment: the newest clean reading at or before it, taken while the channel was bound
  there, when it is no older than the channel's freshness; `read.choose` then takes the newest of a tier's fresh
  values, so a probe moved away and back gives its newest reading (`sensors/tests/test_replay.py` ValueAtTests holds
  every frame equal to value_at on irregular readings at every raw step). At a step of 5 s or less the page's span is
  read, the last reading of each step kept; at a longer step one indexed look-up per frame and channel (the primary
  key read backwards), so a page reads about one reading per frame however dense the readings are (a test holds it to
  two). From an hour the page's hours of the hour rollup are read once, each frame given the last value of the newest
  hour ended by it.
- Every frame with its required inputs carries the whole diagram of its water (A8): isolines, regions, borders, Ω
  lines, names and notes, with the fish's limits, computed only by `farm/water/deffeyes.py` as `deffeyes.figure`, a
  JSON shape of flat number arrays. The server's SVG is drawn from the same shape (`deffeyes.draw` is
  `deffeyes.render(deffeyes.figure(...))`, tested equal through JSON). Frames whose diagram reads exactly the same values
  share one figure (an exact key; only the oxygen, which the diagram never reads, is left out of it); a page's figures
  share one box, holding every point of the page. A water whose pH and alkalinity cannot go together has no diagram and
  says why.
- The endpoint sends the page's figures once each and the frames as columns (figure index, point, missing, reason, and
  per input its values, origins, ages and channels); it needs the rights to read readings and water samples.

### Portable sensors (a probe moved between tanks, systems and sites)

A device (a probe with several channels: temperature, O₂, pH ...) is often carried: used in one tank today, in another
tank, pond, cage or system tomorrow, maybe at another site, or taken out of the water for storage or calibration. Its
readings always belong to where it was at the moment they were taken (owner rule A1): history follows the place, never
the device.

- **Move device** (Sensors › Setup › Devices, a device's row or its Placement tab; a monitoring card can link to it with
  `sensors:device_move?device=<id>&target=unit:<id>`, or `point:`, `system:`, `equipment:`, `out`): every live channel
  of the device that is not retired moves from one moment, in one transaction (`sensors/bindings.py` `move_device`,
  through the same steps as a single channel's move: its open binding closed at the moment, the next opened). Each
  channel goes where its kind goes at the place chosen (`landing`): a water value to a unit's middle point, to the
  sampling point chosen or to the system (its water as a whole); a process value to the system or the piece of
  equipment (or the system or piece of equipment a chosen point is on). The dialog shows each channel's place now and
  from then before anything moves; one that cannot go there (a process value to a unit, a water value to a piece of
  equipment, a place that already has a primary of that quantity, two channels of one quantity, a moment before a
  channel's binding started or in the future) is shown with its reason and nothing moves. A retired or deleted channel's
  open binding just ends. One entry on the device's log lists every channel's old and new place (and the site when it
  changes); each channel's own log says its move too. The role (primary or backup) is chosen once for the device.
- **Out of the water**: the same dialog with "Out of the water" ends every open binding (`unbind_device`). The device
  keeps sending: its readings are stored as they come and belong to no place, so no chart, latest value, value at a
  moment or replay frame of any place has them. The device list and the device's Placement tab say "Not placed", the
  list filters `?placed=no`, and the overview counts the devices not placed.
- **The site is where the device is.** A device is at one site at a time: while placed, the site of the places its
  channels are bound to; out of the water, the site it was taken out at. A move to another site moves the device's site
  in the same transaction (logged); a channel moved alone to a place of another site is refused ("move the whole
  device"); the device form shows a placed device's site as following it, not editable (`bindings.holds_site`: placed
  at a place of a site; a department without a site holds none). The database holds it from both sides (migration
  0007, `sensors_place_site` and constraint triggers): an open binding to a place of another site than its device's,
  and a placed device's site changed, are refused; a unit or a piece of equipment moved to a production department of
  another site, a system or a production department given another site, are refused while a device is placed there
  ("move the device or take it out of the water first", said on the unit's or equipment's form), so a placed device's
  site never lags its place. Closed bindings are history and never checked; an edit of an open binding that leaves its
  place as it was (its note) is never refused.
  Every moment of a binding is typed and shown on the clock of the place's site (`bindings.clock`: the Move and Move
  device dialogs, their links, a binding's end); a chart's clock was already the place's.
- **Only the readings taken there.** A place's chart, its latest value and its replay have exactly the readings taken
  while a channel was bound there: a value measured before the probe came (its last value from the previous place) is
  never the new place's latest; on the hour tiers the whole hours of a binding come from the hour rollup and the parts
  of an hour it only partly holds (a move at 01:30, a device taken out, a window's edge) from the raw readings
  (`read.hours_of`, each part inside one hour: a stay from 01:30 to 02:20 is two parts), so the hour that holds a move
  is shared by the two places and no replay frame ever reads a value measured after it.
- **Alarms belong to the place.** An alarm event is tied to the binding it opened under (`AlarmEvent.binding`). The
  check (`manage.py check_sensors`) looks only at channels bound now, with what they measured while bound there
  (`Binding.took`, the same rule as the latest values): a device out of the water raises nothing, the no-data clock
  starts when it was placed, a time above or a rate reads only the readings taken there. Moving the device or taking it
  out closes its open events at that moment; an event whose binding no longer holds is closed by the next check. A
  site's open events (`alarms.open_events(site)`) are those of its places; the Alarm events page names the place.
- **Locks**: every move locks the device first and then its channels, each row alone, so a channel's move and a
  device's move at once wait for each other and never deadlock, and the site row is never locked.
- **Where it is and was**: the device's Placement tab lists where it was from and until (`placement_history`); the
  bindings list with `?place=unit:<id>` (or `system:`, `point:`, `equipment:`) lists the sensors at a place, those there
  now first, then those there before.
- Readings taken while the probe is carried count for the place it left until the moment typed for the move: take it
  out of the water when it is lifted (Out of the water) and move it when it goes in.

### Storage

- `sensors_reading`: a hypertable in 7-day chunks, compressed after 14 days (per channel, newest first), dropped after
  730 days; primary key (channel, time) so a redelivered message is stored once; a row carries how many messages it stands
  for and, for more than one, their sum, lowest and highest, so every mean is exact (a sum of sums over a sum of counts,
  never a mean of means). Quality is one bitset (`sensors/quality.py`): bad rows (out of range, device bad, maintenance,
  simulated) are stored as evidence and left out of everything drawn or judged.
- One continuous aggregate, per hour, built from the clean raw readings (no minute rollup: at the common one row a
  minute it held as many rows as the raw table, failing the plan's 40 % gate, so the owner removed it). Charts take the
  raw readings bucketed below an hour, the hour rollup up to a day, and the site's local days from the hours (a day the
  clocks go back has 25 hours). The rollup refreshes every hour over the last 75 days and is compressed after 90; a daily
  job takes in later readings back to the contract's late limit (728 days). The refresh never reaches back into dropped
  raw data: TimescaleDB 2.17 invalidates a dropped region and a refresh there would empty the rollup.
- Late or old readings are written one row per statement: TimescaleDB 2.17.2 silently drops the remaining rows of a
  multi-row `INSERT ... ON CONFLICT` that meets a compressed chunk (`sensors/tests/test_timescale.py` holds the case).
  A `DELETE` of rows in a compressed chunk fails in 2.17.2 ("btree index keys must be ordered by attribute"); nothing in
  the application deletes readings (retention drops whole chunks).
- A value is fresh while both its device time and its receipt are within the channel's freshness (its fresh heartbeats): a
  gateway replaying an old backlog delivers values received now but measured long ago, which are not fresh.
- The database viewer counts a hypertable by the database's estimate and leaves the readings out (billions of rows).
- Licences: compression, continuous aggregates and their policies are TimescaleDB's TSL features of the community build
  (free for an application that owns its schema, as this one; a test asserts `timescaledb.license = 'timescale'`). No new
  Python package; the credential hash is the standard library's `hashlib`.

### Running it

- `manage.py sensors_ingest_role --password-file FILE` lets the ingest's database role (NOLOGIN after the migration) sign
  in; `--disable` closes it.
- `manage.py sensor_broker_sync [--passwd PATH] [--acl PATH] [--extra OPS_LINES] [--check]` writes Mosquitto's files from
  the credentials and devices (atomic replace; by default into `SENSORS_BROKER_AUTH_DIR`, `.sensors/broker-auth`), then
  `docker compose kill -s HUP mosquitto` makes the broker read them. Replacing a credential's secret (Credentials, Replace the secret)
  shows the new secret once; the broker takes it at the next sync.
- `manage.py sensors_demo_setup --confirm [--secret-file FILE]` makes the live demo's sensors for the existing tanks and
  systems (one connection, one JSON payload format, a device per tank with a middle point and per system on topic
  `demo/<code>`, eight water channels each covering every measured parameter together, bound to the tank's middle point
  or the system, a simulator credential with its secret shown once); it is idempotent, touches only what it made (found
  again by its connection's client id, its format's name and its credential's user name), and `--remove` deletes exactly that.
- `manage.py check_sensors [--loop 60]` checks the alarm rules; `manage.py sensors_housekeeping` (daily) deletes dead
  letters older than 90 days.
- `manage.py bench_sensors --confirm-database NAME` writes synthetic readings into a database named on the command line
  (never a farm's) and prints the storage and read figures, the replay's page and its diagrams included (`--frames`,
  `--measure-only` to time rows already there, refreshed and compressed).
- The overview shows the ingest's counters: messages dropped at QoS 0 and refused (poison) since it started.

### Measured figures (bench_sensors on the local container, a shared developer machine)

- 10 channels × 2 years at one row a minute, refreshed and compressed as in use: a chart of one channel over the whole
  span 71-131 ms; ten channels over seven days in 15-minute buckets from the raw readings 196-379 ms (the plan's 300 ms
  is met only on a quiet machine); the replay of seven days hourly 15-37 ms; the latest values of ten channels 29-50 ms.
- 4 channels × 30 days at one row a minute: one replay page of 2 000 frames at one minute, the readings in one query,
  69-218 ms. At one stored row a second (4 channels × 3 days) the same page takes 1.2-2.1 s (its 33 hours hold 480 000
  rows); a lookup per frame and channel is 0.6-0.9 s. Neither meets 300 ms at that rate.
- **The page's diagrams (A8) do not meet 300 ms**: the whole diagram of a frame takes 18-26 ms to compute in Python, so
  2 000 frames at the readings' resolution (every frame a different water) take 38-53 s and 28 MB as JSON; at the
  parameters' decimals, as the replay reads the values, 903 different waters of 2 000 in 15-17 s and 12.6 MB. This is the
  measured trigger the owner named for moving the water chemistry core to Rust; nothing is approximated to go faster.

## Human resources (Company › HR: `/hr/`)

The company's people, where they work and, as the pages arrive, their time. It is one piece of the Company
panel, not a module of its own: the same roles, delete plans, activity log, database viewer and languages. It is
built by reading the source platform's HR service and listing what was wrong with it
([docs/aquaculture-platform-bugs.md](docs/aquaculture-platform-bugs.md), "Human resources"). The rules it holds:

- **One source for departments.** The production departments are the farm's own rows (Production › Setup), never copied
  into HR: Company › HR › Departments lists only the white-collar departments (Finance, administration, management), HR's
  own rows (`hr.OfficeDepartment`, table `office_departments`), which nest under one another for the organisation chart;
  the production departments and their people are under Production › Team (below).
- **A team lead sees and plans their own team only, and never pay.** The role matrix gives the verbs; the rows come from
  the relationship, in one place (`hr.scope.team`, see Row scope under One format for every tab). There is no pay, bank
  or identity-number column anywhere in `hr` (a test fails on one); pay will be an app of its own that points at the
  person and is never offered to a team role.
- **State is read, not stored:** who is present, late, absent or on leave, worked minutes, leave days, balances, head
  counts and the department of a past day are worked out on the site's clock when a page is read.
- **The law is owner data.** Limits (rest, weekly hours, days in a row) are settings that warn by default and may only be
  stricter than the statute; none is a database constraint.

The team lead is the **Manager** of a production department (chosen on the production department's form, shown in its
list and logged) or of an office department, plus a role with the HR areas. The Manager field has no other effect.

### Departments (`/hr/departments/`)

The office departments (created, edited and deleted here; the production departments are the farm's, under Production).
A table with status, site, manager and head count, in tree order, search by name or code and a status filter. An office
department has a name, a code (unique among live ones, capital letters, digits, hyphens and underscores), a parent (the chart), a site (the clock of its
people: set the site's time zone on the site), a manager, a status and a description. Database rules, tested with raw
SQL: code unique among live rows (free again after a delete), name unique under one parent and among the top-level
ones (`nulls_distinct=False`), not its own parent, a trigger that refuses a cycle however it is written (it walks up
through deleted rows too, so a restore cannot close a loop), code and status checks. A department with departments
below it is not deleted (the delete plan names them); a deleted one is restored from the admin, checked like a new one.

### Team list (`/hr/team/`) and the team scope

One row per person (`hr.Employee`, table `employees`): number, name, employment type (staff, student, researcher,
technician, advisor, contractor, volunteer), first and last day. A person with an account is named by it (first and last
name stay empty here, a database check); one who never signs in carries their own name, a last name at least. The account
is optional, so a student or a visiting researcher needs no login (and gets no invitation mail). A person is never deleted:
a last day closes the record and the history stays readable. There is no pay, bank, identity-number, address or contact
column (`hr/tests/test_boundary.py` fails on one).

**Where a person works is a dated placement** (`hr.Posting`, table `postings`): exactly one department, a production
department or an office department (a database check, as a task's place is), a title, from a day and until a day (empty
while open). One placement covers any day (an exclusion constraint), so the department of a past day is read, not
overwritten. The form's Placement tab shows the current one; changing the department or the title needs the day the
change counts from, and `hr.services.move` closes the open placement the day before and opens the next (one transaction,
both logged; a change dated the first day of the current placement corrects it in place). A department with people placed
in it is made inactive, not deleted (both links are PROTECT; the delete plan says so).

**The team** (`hr.scope.team(user, day)`) is the one place that says who may reach whom: the person themselves, the people
placed on that day in a production department the user manages (its Manager) or in an office department they manage or
any below it, and, for a holder of Everyone (`hr.all_employee`, a column on the Employees row of the role matrix), every
employee. `EmployeeResource.scoped` is that function, so the list, a person's read page, the edit and the placement given
are all of the team, whatever the address or the query. A lead with a role that gives Read on Employees reads their
team's read pages; the form needs Edit, and only a holder of Everyone can create someone (a new person has no team yet).
A move is a placement in a department, so the department moved to must be one the lead manages too
(`hr.scope.can_manage`, from the same `managed_departments` as the team): a lead does not hand a person to another
manager or into the office, and a holder of All production moves people between production departments only. A lead does
not write their own record either (placement, title, last day: `hr.services.own_record`, the rule of one's own attendance
and plan); the list offers them their own read page, not the form. A holder of Everyone does both.
A person who moved belongs to the old manager up to the move and to the new one from it (`scope.visible_days`, for the
reads that run over several days). A manager without a role, or a role without a department, reaches nothing beyond
themselves. The Departments page counts, per department, the people placed there today that the viewer may reach.

The activity log shows the employees and their placements only to holders of Everyone (`core.audit.restrict`); a lead
who reads the log sees everything else but not the people.

### Time & shifts › Scheduling settings (`/hr/settings/scheduling/`), Shifts and Holidays

**Scheduling settings** is the one row of limits and defaults (table `scheduling_settings`; a unique `singleton` column
with a check keeps it one; the migration makes it, the only seed: no shift, holiday or leave type is seeded). It is
changed, never added or deleted. Every setting has exactly one reader: the standard week (the Team overview), the
minimum rest, the most days in a row and the rest rule, warn or block (the rules of the roster), the working weekdays
(the days a leave request is charged for), the punch window and the absent-after minutes (Today) and the hours after
which an open clock-in counts as a forgotten clock-out (`forgotten_after_hours`, 16 until HR sets another; its one rule
is `hr.rules.forgotten`, see Today & attendance). The figures are
labelled defaults on the page, **not the law**: none of the statutory figures is verified, so none is a database
constraint (a rest of 60 minutes can be stored); the settings may only be set stricter than the statute, and the owner
confirms them. Sanity checks only: ranges and the enumerations. The forgotten clock-out limit is 1 to 168 hours (a
database check); a blank or an out-of-range value is refused with its reason, and so is one shorter than the longest
active shift with the punch window before it (a stretch begins at the clock-in, which may come the whole window before
the shift: a person on that shift would count as forgotten before it ends and could not clock out; a wider window alone
is held to it too), as the shift form refuses an active shift that, with the window, is longer than the limit.

**Shifts** (`/hr/settings/shifts/`, no menu line, reached from the settings page; Shifts is its own matrix area): a name,
a code (capital letters, digits, hyphens, underscores; unique among live shifts, free again after a delete), the start
and end on the wall clock of the site (an end at or before the start is the next day), a break (0-240, shorter than the
shift: a database check on the two time columns), a grace (0-120), a tone 1-8 (a CSS class: no colour value is stored,
HR-27) and a status. **Holidays** (`/hr/settings/holidays/`): a day, a name and a site or every site, one per day for
every site and one per site (`nulls_distinct=False`); typed in by HR, never seeded, because the country's days are the
owner's data. A site with holidays is not deleted.

### Time & shifts › Shift schedule (`/hr/schedule/`)

A week of the viewer's people as a table: a row per person (their department under the name), a cell per day, the planned
hours at the end. A cell shows the day's one state (`hr.read.Cell.state`, which the Team overview counts by too): "On leave"
on a day of approved leave (over a planned shift or a planned day off, which someone else is to cover), else the shift (its
code in its tone), "Off" for planned off; then the holiday of the person's site, and
a "!" with the finding when a rule is broken; it opens the plan of that person and day in a dialog (a plus on an empty cell
when the viewer may create). The week is the ISO week (Monday first, no setting); `?week=` takes any date of it, `?department=`
and the search narrow the people and never widen them, and the list says "n of m" with its own paging. Everything on the page is
worked out on the server (`hr.read.week`: one query each for the page's people, their plan a fortnight either side, their
placements and the holidays, whatever the number of people), and a person who moved is shown to each manager on their days
only (`hr.scope.visible_days`).

**One roster table** (`hr.ShiftAssignment`, `shift_assignments`, shown as "plan" in the log): a person and the day a shift
starts (a night shift ends on the next day), the shift or none (planned off, which is not the same as no plan), a note (private:
masked in the log and the viewer). One row per person and day among live rows; a cleared cell is a soft delete, and clearing a selection clears its
filled cells (an empty one has nothing to clear, F-024). Leave and
holidays are joined when the week is read, there is no publish step, and every change is logged with its before and after.

**Real instants, not wall-clock sums** (`hr/clock.py`): a shift on a day becomes two UTC instants through the site's time zone, so
22:00-06:00 is 7 hours on the night the clocks go forward and 9 on the night they go back, and the rest between shifts is the
real gap, across a week's border and for a night shift (the source computed 1920 minutes where 480 is right: HR-08).

**The rules** (`hr/rules.py`, pure functions, one place each): two shifts that overlap and a shift on a day of approved leave
always block; a rest shorter than the minimum warns or blocks by the setting; more hours than the standard week, more days in a
row than the maximum and work on a holiday warn. They run on every save: a blocking finding is an error on the form and a
warning is told after the save and written into the audit row. `hr.services.plan_shifts` sets a shift, planned off or nothing on
a batch of cells, all or none (the verb each cell needs, the person in the user's team on that day, the rules for each person;
a person outside the team is a 404 and writes nothing); the page's batch route is `/hr/schedule/plan/` (POST).

### Time & shifts › Leave requests (`/hr/leave/`) and Leave types

**Leave types** (`/hr/settings/leave-types/`, no menu line, reached from Scheduling settings, which lists them and
links "Manage leave types" beside Shifts and Holidays; a test holds that every hidden menu entry is linked from a
visible page of its group, `hr/tests/test_leave_types_linked.py`): a name, a code, the days a
year (empty: no limit) and whether a request needs approval; owner data, none seeded. While no active type exists the
leave request form says so under the empty list and where types are added (the place by the menu's own names,
`core.navigation.trail`). **A request** (`hr.LeaveRequest`,
`leave_requests`) is a person, a type, a first and a last day, a status (pending, approved, rejected, cancelled), the person's
reason, the decider, the time and a note. Database rules: the last day is not before the first; an approved or rejected request
has the time it was decided; **no overlap** for one person while a request is pending or approved (an exclusion constraint on
the days, so two people filing at once cannot both win; adjacent days, rejected, cancelled and deleted requests do not block);
and **nobody decides their own leave**, by the service and by a trigger whatever writes.

What a request costs is read, never stored (`hr.leave`): the days whose weekday is a working weekday (a setting, Monday to Friday
by default) minus the holidays of every site and of the person's site, split by year for a request that crosses New Year (the
source charged calendar days, HR-07); the balance of a type with a yearly allowance is the allowance less the days of the year
that pending and approved requests are charged for, and a request over it is refused on the form. `away_on(day, user_ids)` is the
interface for the places that may only learn that someone is away, never why.

**One approval step.** Staff hold Read and Create (they file for themselves and cancel their own); a lead holds Edit as well,
and **Edit also approves, rejects and cancels** (the matrix has no extra column, as for a knowledge entry's review). The decider
is someone with Edit whose team holds the person and who is not the person; a lead's own request therefore reaches whoever has
them in their team, or a holder of Everyone. A type that needs no approval is granted the moment it is filed, with no decider. A
pending request is cancelled by the person or a decider at any time, an approved one by the person only while its first day
has not started on the site's clock. Once it has begun, a decider (never the person, never on their own leave:
`hr.services.can_correct`) still puts it right: **ends it earlier** (`shorten_leave`, a new last day from its first day to the
day before its last: the person came back early; the request's page has the field) or cancels it (it was never taken). Only
within the correction window after the leave's last day (`hr.services.correction_window_days`, the platform owner's
correction-window setting, 31 days by default): an older leave is history and is refused with the reason. The
decisions are `hr.services.decide_leave`, `cancel_leave` and `shorten_leave` (POST routes, a dialog for the rejection
note), each in one transaction with its audit row, and every refusal leaves rows and log unchanged.

**Within the employment.** No shift is planned, no presence entered or punched and no leave asked for a day before the person
joined or after their last day (`hr.services.check_employed`, the one rule for the plan, the punch, the entered presence, the
attendance form and the leave form; clearing a planned day is always allowed). A lead was already held to it by the
placements, which end on the last day; a holder of Everyone and the person themselves are held by this rule. Every path
reads it with the person's row locked (`lock_employed`: the forms check it first for the sentence, the save checks it
again under the lock in the tab's `after_save`, which rolls the save back onto the form; `enter_presence`, the punch and
approving a pending leave lock first), so a last day committed meanwhile is never passed. HR's lock order: the person
first (`hr.services.lock_person`, FOR NO KEY UPDATE, so a record being added for them does not wait on it), then their
records; an edit of a plan, a punch or a leave request locks the person before the record (`PersonFirst`, through
`Resource.edited`), as the batch plan, the punch and `leave_company` do. It holds the other way too: a
first or last day that would leave plans, held leave or punches outside is refused on the person form and by
`leave_company`, naming what to correct first (`employment_conflicts`; later plans and later pending leave go with the
last day as before). The database backs it (`hr/0011_employment_bounds`: constraint triggers deferred to the commit on
plans, leave, punches and the person's dates; a punch is checked on the UTC day with a day of slack, its exact day is
the site's).

**Privacy.** A lead sees the person and the days; the **type** (sick, annual) only the person, who may decide the request (Edit) and the
holders of Everyone see: in the list, on the read page and in the search (the scope marks each request `type_shown` and a search for a
type reads the mark, so a search for "sick" tells nothing). The reason is the person's own words, shown to them and to the holders
of Everyone only (the list, the read page and the edit form leave it out for anyone else, and a lead cannot overwrite it). The reason
and the decision note are masked in the activity log ("Private text") and in the database viewer, and leave requests appear in the log
only for holders of Everyone. Approved leave is read over the roster: planning a shift on a day of approved leave is refused, and
the week shows the cell as on leave. When a person leaves, their later pending requests are cancelled and later plans removed.

### HR dashboard › Today & attendance (`/hr/`) and Time & shifts › Attendance (`/hr/time/attendance/`)

**A punch is a stretch, not a day** (`hr.AttendanceRecord`, `attendance_records`): a clock-in and a clock-out (none while the person
is in), who made it (`self`: the person clocked in at the server's time, never the browser's; `entered`: a lead typed the time, on
the site's clock, and must say why) and a note (private: masked in the log and the viewer). A person can work in two stretches and a
night shift crosses midnight, so there is **no one-row-a-day rule** (the source's was a racy application check, HR-10, HR-14). The
database holds the rest: the out is after the in, an entered stretch has its reason, no two stretches of a person overlap and at
most one is open (an exclusion constraint on `tstzrange(clock_in, clock_out)`: an open stretch runs on to infinity, so it also
forbids a second open one). A stretch has no stored day, site or state.

**Who is where is read** (`hr.read.board`, `hr.rules.status`, pure): for each person of the viewer's team the planned shift today on the
person's own site clock (or the night that began yesterday and is still running), their stretches from the punch window before the start
(a setting) and their approved leave give one state: *upcoming* (before the start plus the grace), *not in yet* (until the later of the
grace and the absent-after minutes), *absent*, *present* or *late* (clocked in, past the grace) while in, *done* once out, *on leave*. A
record is a fact and the plan an intent: a person who is there but not planned is listed as present, "not planned", and **a clock-in
beats leave**: whoever clocked in is on the board whatever their plan or leave (the headcount on site, in an emergency), and an open
clock-in counts whatever the punch window (someone called in hours before their shift is present, not upcoming or absent; only
the clock-ins inside the window say whether they were late). People planned off,
with nothing planned or on a day off are not listed (the source counted every unrecorded person absent, HR-12); pending leave is not
leave; nothing planned and on leave is not listed either. Today shows the figures (`hr.read.Board`): **On site now** first (every open
clock-in on the farm, whoever looks: the emergency muster, a number only, never names past the viewer's team, by site when
there are several, `hr.read.muster`; the tile says "Everyone clocked in, all teams" and how many of them are forgotten
clock-outs, with the limit's own number),
Planned today, then one
tile per state the planned people are in, each person in exactly one, so they add up to it (upcoming, here now with the late among
them said in it, not in yet, absent, on leave, done, and clock-out forgotten, a tile shown when someone is in it), and "Here, not planned" apart (only those still in; someone unplanned who clocked
out is listed as done, not counted here); closed stretches are read from two days back and an open clock-in whatever its age;
then the people; the board is a fragment the page
polls (`data-poll`, 30 seconds) and the server draws every number and every time, on the clock of each person's site. The person's own
**Clock in** and **Clock out** buttons need Read on Attendance and an employee row of their own, and are refused while a stretch is open
or none is.

**A forgotten clock-out** (owner decision F-095, 2026-11-10; `hr.rules.forgotten`, the one rule): a clock-in still open longer
than the limit of Scheduling settings (16 hours until HR sets another, never a figure in the code). Nobody knows when the person
left, so nothing is assumed in either direction and no hours are invented:

- **The board** gives the person a state of their own, *clock-out forgotten*, whatever their plan or leave, with "Open since …: to
  be closed on the Attendance page" and, for who may correct that person's attendance, a link to the stretch. Never present or
  here now (that would be an assumed value), never done (there is no time to say) and never absent (the person may be back at
  work, unable to clock in beside the open stretch). A planned person in it is counted in its own tile, so the tiles still add
  up to Planned today; one not planned is listed and said under that tile, in no other figure.
- **The emergency count** (On site now) keeps every open clock-in, the forgotten ones too, and says how many of them are that old:
  an overcount is checked, a person missed is not, and a forgotten stretch may be the only trace of someone who came back to work.
- **The person** is told in words on Today instead of the two buttons ("Your clock-in of … was never closed: … Ask your lead,
  or whoever keeps attendance for you, to close it on the Attendance page with the time you really left; then you can clock in
  again.": a lead and a person without one are told something they can do), and a clock-in or clock-out sent
  all the same is refused with the same sentence and writes nothing (`hr.services.forgotten_refusal`). A clock-out now would store
  the days since as worked; a second clock-in cannot stand beside an open stretch (the table's exclusion constraint), and closing
  the old one for them would invent the time they left.
- **The lead closes it** on the Attendance page: whoever may correct that person's attendance (Edit on Attendance, never
  one's own stretch without Everyone) types the real clock-out and the reason. **An open stretch is reached by whoever
  reaches the person today as well as on its first day** (`hr.scope.stretches`, the one rule of who reaches a stretch): a
  person who moved department since they clocked in is closed by their lead of today, not sent to a lead they no longer
  have; once closed, the stretch is history of its day and its day's manager's. The stretch becomes an entered one (`via`),
  and the log row says who closed it, the clock-out, that it was entered by hand and that a reason was given (never its
  words). Then the person clocks in again.
- **Never ahead of now** (`hr.services.check_times`, the one rule of a stretch's two typed times, on the form and in
  `enter_presence`): the clock-out after the clock-in, and neither later than the server's now, each refused with its
  sentence on the field. A clock-out typed days ahead would close the stretch with hours nobody has worked, keep the person
  from clocking in and take them out of the emergency count while the record says they are in.
- **The limit counts elapsed hours** (`hr.rules.forgotten_before` works in UTC), also on the night the clocks change.
- **Totals.** Nothing in the code sums worked time yet (state is read, not stored); the rule for whatever does is the same: a
  forgotten stretch has no end and counts for nothing until it is closed.

**The Attendance page** lists the stretches of the viewer's team over the last fortnight or the days asked for, times on the site's clock,
with **Mark present** (Create: a person of the team, the times, the reason), a correction (Edit, logged with what it was before) and a
void (Delete). A stretch still open is listed whenever it began (it runs on through the days asked for), so a forgotten
clock-out is always there to close, marked "Clock-out forgotten". **A time typed by hand needs its reason, whoever clocked
in:** a correction that changes the clock-in or clock-out of a stretch the person clocked themselves makes it an entered
stretch (the table's own check then holds the reason); an edit that leaves both times alone leaves it the person's own. The
log keeps what the person's own clock-in keeps, so also who made the stretch (`AttendanceRecordResource.snapshot`,
`hr.services.PUNCH_FIELDS`). The page's heading is Attendance though it shares its permission with Today (the role matrix places the area under
HR dashboard, where its Read page first sits).

### HR dashboard › Organization chart (`/hr/organization/`) and Time & shifts › Team overview (`/hr/overview/`)

**Team overview** is the Shift schedule's week as numbers (`hr.read.overview`, built from the same cells and the same scope, so the two pages
cannot disagree): per person the days working, planned off and on leave, the planned hours and how many minutes they stand above or below the
standard week (a setting; a week over it is marked), and per day how many work, are off or are away. It has the week, department and search
filters and the "n of m" paging of the schedule, needs Read on the Shift schedule, and runs in a fixed number of queries.

**Organization chart** is the company as a family tree, one per panel: each box (a site, a department, the Production box) shows its
name, kind, manager with their title and head count, and its children hang below it joined by connector lines (down from the parent, a bar
over the siblings, down into each child), each level on one line. It is nested lists (a box's children are the list inside its item) and
the stylesheet draws it (`static/css/hr.css`: pseudo-element connectors in the token colours; no chart library and no script), so it reads,
prints and is announced as a list of lists. A department's people open under its box as small cards with a native disclosure
(`<details>`). A wide tree scrolls sideways inside its own labelled frame (keyboard-focusable; a line of text and edge shadows say there is
more), never the page; below 768px it is an indented vertical tree; printed, it goes on a landscape A4 (a named page) without the menu, the
frame or the closed people lists. The data is one read per panel (`hr.read.org_tree(user, realm)`): Company's office departments under their parents and one
**Production** box with the production people the viewer may count (computed, never a row, so nothing to delete; there with no production
department; a link to Production's chart for who may open it). **Where the Production box hangs:** when the company has exactly one top
office department (one without a parent, e.g. Management), the Production box is its last child and its people count in that department's
"in all"; with several top departments, or none, it stands beside them as a top box of its own. And Production's sites with their production departments; each box with its manager
and the people in it, direct and in all below, counted among the people the viewer may reach (a lead's chart counts their own team). For a
viewer who may read people (`hr.view_employee`) a department's box also carries its people (`hr.read.chart_people`: placed in it today,
among those the viewer may reach, so the cards are the count, sorted by last name, each with their placement title) and the manager's
title (their placement title today, in that department first); a reader of departments only sees the counts and the manager's name, no
person and no title. A
production department created, renamed or deleted under Production is in the chart at once, from the same rows.

**Rules the review of the branch added.** A record of a person belongs to the manager of the department the person was placed in
on the record's own day (`hr.scope.by_day`: a plan, a punch, a leave request), so a person who moved leaves their old records with
the old manager on every verb; the week names the department and the clock of the first day the viewer reaches, and its findings
are worked out from the days the viewer reaches only. A lead does not plan or write their own attendance (Everyone may). The
Manager of a production department and the account of an employee are chosen by those who administer HR (`hr.change_officedepartment`
or Everyone), because they decide whose rows and whose private words a person reaches. A pending request carries no decider and a
hand-entered note has words, as database checks; a decision note over 500 characters is an error on the page.

### Production › Team (`/production/team/`): the production people, and Company › HR left with the office's

The HR pages are served twice over **one set of records**: Company › HR for the office people and Production › Team for the people
placed in a production department. Nothing is copied and nothing is stored to split them: the **realm** (`hr.scope`) is read from
the placements on the day asked (production: a live placement in a live production department; office: everyone else, so an unplaced
person is never lost), and it only narrows the reach the role and the team already give. A person who moves changes sides by a dated
placement and appears in each panel on its own days. The HR administrator (Everyone) reaches the office people in Company and the
production people in Production, with the same permission.

- **Pages.** Team › Time & attendance: Today & attendance (`/production/team/`, own clock in and out), Shift schedule
  (`/production/team/schedule/`), Leave requests (`/production/team/leave/`, the number beside it is the pending requests the person
  may decide), Attendance (`/production/team/attendance/`: the same right as Today, so a Today reader has it) and Team overview (shown
  in the menu, and opened, for the people who lead production); Team › People: Team list (`/production/team/people/`) and Organization chart
  (`/production/team/organization/`), both with Read on Employees. Company › HR keeps its pages for the office; its lines that
  Production repeats are not shown to a person whose HR is all in Production (`Entry.show_when`). **The menu and the address bar
  agree**: a line the menu leaves out for a person is refused at its address too, with the 403 page
  (`core.middleware.MenuAccessMiddleware`, `core.navigation.refused`), so nobody opens by its address a page their menu hides
  (`hr/tests/test_menu_access.py` walks every line for every starting role, a lead, an office person and the admin, and
  every address of HR's tabs on both mounts). **A hidden menu line means no access.** The role matrix says it under the
  area: a role gives the right, and the line (and its pages) still depend on the person ("Company · HR · Shift schedule:
  not for a person whose HR is all in Production", "Production · Team · Team overview: only for a person who leads
  production people"; `Entry.show_note`, `core.navigation.notes`). Roles & permissions stay in Company › Administration: roles are company-wide.
- **How.** `core.crud.Mount` serves a tab a second time under another address and panel: one Resource, one registry entry, the same
  views; the request carries the mount, the tab's `scoped` narrows to it, and every link (`{% url ...|mounted:request %}`), redirect and
  heading stays in it. A record of the other realm is a 404 on every address. A decision, a cancel, a plan or a punch returns to the
  page it came from (a checked local `next`). New people and new plans are chosen in the panel's realm; a move offers every department.
- **All production** (`hr.all_production_employee`, a matrix column on Employees): every person in a live production department, a
  department without a manager (a new one, or one whose manager's account is gone) too; never an office person and, being no Everyone,
  never a leave reason. The head of production's reach.
- **Crew** (`hr.crew_shiftassignment`, a matrix column on the Shift schedule): under their own week a production worker sees the name
  and the shift code and times of the people in their own production department on each day (`hr.read.crew_week`), built from plain
  values: no note, finding, leave or its type, punch, employee number, hours or link. A day off, a day on leave and a day with nothing
  planned are the same empty cell. A crew is a worker's: someone with no employee record (the platform admin) gets no block, and a
  worker with no production placement that week is told so (`CrewWeek.placed`, from `hr.scope.production_days`), never that
  nobody else is placed in their department.
- **Approving leave** opens a dialog with the person's planned shifts inside the request (`hr.read.leave_impact`) to cover; it never
  blocks the approval. Nobody decides their own leave (service and trigger), so a sole production manager's own request goes to a head
  of production or HR.
- **Roles.** `manage.py hr_roles` creates **Production manager** (Today, Attendance with entering presence and correcting a
  stretch, Shift schedule with planning and clearing a day, Leave requests with deciding, All production; no voiding of a
  stretch, no Team list, chart, settings or office people) and **Production worker** (own Today, own week with Crew,
  own leave) when they do not exist, and keeps a role an administrator changed as it is (`hr/roles.py`, never run on migrate).
  Clearing a day and entering and correcting attendance are the owner's addition of 2026-11-10 (F-203: the manager closes
  a forgotten clock-out). A Production manager role made before it gets the three rights from migration
  `hr/0012_production_manager_rights`, one activity-log row per right given (by `system`); a right the role held already
  is not said, what an administrator changed otherwise stays, and going back takes away exactly what it gave.
- **Not built here** (decided with the owner): a minimum crew per shift and an on-site count. The legal items (information and
  discussion on attendance recording, impact assessment, working-time figures, retention, the undeletable log) are on
  [docs/hr-launch-checklist.md](docs/hr-launch-checklist.md) for HR and the data-protection officer: nothing there is encoded as law.

### HR: checks, the demonstration company, the browser code and the tests

- **`manage.py check_hr`** reads what no database constraint can hold because it looks at several rows and changes with time, and
  fails with the list: a last day with a placement after it, leave after it, a placement before the person joined, a person placed in
  no department today, an office department with people but no site (they would be read on the company clock) and an inactive
  department with people. It changes nothing; a person decides.
- **`manage.py seed_hr_demo`** (only with `DEBUG` on, idempotent) makes a small company for a walk-through in a browser: a site on
  Oslo time, two production departments with managers, an office department, nine people placed in them, three shifts, a week of
  plans, a holiday, leave types, a pending leave request, a punch, and four roles made like any role (Demo lead, Demo staff, Demo
  HR admin, Demo auditor) with a sign-in each (`demo_lead_hatchery`, `demo_lead_nursery`, `demo_staff`, `demo_hr`, `demo_auditor`).
- **Browser code** (`frontend/roster.ts`, TypeScript only): on the Shift schedule the arrow keys move between cells, and the paint
  form (hidden without the script) picks a shift, selects cells and posts them to the batch route, which plans all or none; the page's
  Print button is the shared `data-print`. The script has no text of its own.
- **Tests** (`hr/tests/`): the realm, the mounted pages and the role presets walked for every role (`test_realm`,
  `test_production_team`, `test_crew`, `test_roles`, `test_leave_impact`, `test_leave_type_privacy`); per model the create, read, edit,
  delete and restore round trips against stored rows with a test that
  names every column; the constraints through `IntegrityError` on raw rows, including both triggers, the open punch and the
  exclusions; the team scope by function and by URL for every actor (404 on every verb outside it, nothing written or logged, every
  route needs a row in the matrix or the suite fails); the boundary (no pay, bank, tax or identity column, form field, template word
  or import, and every free-text column named and masked); derived state at a fixed `now` for sites ahead of and behind UTC and the
  7 and 9 hour nights; the rules as pure functions; the services' refusals leaving rows and log unchanged; query budgets (the same
  number of queries for few and many people) on the Team list, Departments, the week, the overview, the chart, the board and the leave
  list; and the migrations back to nothing and forward again.

## Alarms (Company › Alarms: Alarms `/alarms/`, Alarm recipients `/alarms/recipients/`, Alarm severity rules `/alarms/severity-rules/`, Alarm deadbands `/alarms/deadbands/`)

The owner's answer (2026-11-06, F-091): alarms reach everyone's phone as push notifications through the coming mobile app
(not e-mail: it gets too little attention), and every alarm, every notification and every acknowledgement (who, when,
from which device, how late) is logged. The server side is built; the push transport plugs in with the app.

- **What raises an alarm** is judged where it is judged today (`alarms/sources.py`): the sensor alarm rules (each event of
  `sensors/alarms.py` is mirrored as an alarm and cleared when it closes) and the water limits: one read of every live
  unit's water (`farm/water/read.py` `unit_water`: its middle point, its other own points and its system standing in, the
  worst fresh value deciding), so an inlet raises nothing and a depth point or the loop raises its unit's alarm (alarm plan,
  defect 1). A water alarm's subject is the unit's quantity at a level (`water:unit:<unit>:<slot>:<severity>`), never the
  point that stood for it, so a replaced middle point keeps one alarm per level and its successor's values clear it; a
  removed unit ends its alarms ("the unit was removed"); `alarms` 0007 re-keyed the subjects and cleared any duplicate
  with the cause "merged" (cross review F7).
- **Levels (ISA-18.2 L and LL)**: a unit's parameter (the dissolved oxygen in mg/L and in % is one) has a warning and a
  critical subject, each its own alarm: warning holds while the value is judged warning or critical, critical while it is
  judged critical, so a severity change never clears and reopens (defect 2). A level is raised once it has held for its
  severity's on-delay, counted from the first offending value's time, or from the pass for a value stamped ahead of the
  clock (`sources.seen_at`: a device whose clock is fast never delays or suppresses an alarm, cross review F1); it clears
  once a fresh value, taken after the last bad one (defect 4), is clear of it and EVERY fresh value that takes part in
  the unit's status (`Reading.deciding`) is clear of it even moved by the parameter's deadband (the same judgement on the
  moved values, cross review F2), for the off-delay; at once when the unit has no fish ("no fish in the unit any more") or
  its fish no limit row ("the water limit was removed", the log entry naming the row, who removed it and when, F12). A value that only goes
  stale never clears it. While the live sources cannot be read nothing clears, and that is a critical system alarm of its
  own, restored when they answer (defect 3). A clearance says why. The timers are each subject's row
  (`alarm_subject_state`), so a restart loses none; its open alarm is a unique column set by one compare-and-set
  statement, so a subject never has two open alarms (defect 6). A warning is not notified while its critical is open.
- **The rules are the user's reference data** (owner, alarm plan §7c): per severity the on-delay, the off-delay, the
  escalation time and the delivery attempts (Alarm severity rules, one row each: critical 0 s, 30 s, 5 min, 5; warning 30 s,
  30 s, 30 min, 5), per parameter the deadband (Alarm deadbands: dissolved oxygen 0.2 mg/L and 2 %, temperature 0.3 °C, pH
  0.05, CO₂ 1 mg/L, TAN 0.05, NH₃-N 0.002, NO₂-N 0.05 mg/L, salinity 0.5 ‰). These are the owner's defaults (§7a),
  seeded once by `alarms` 0002; from then on they are rows edited on their tabs by the alarm admin's rights, bounded by
  database checks, logged, read once per pass (`alarms/rules.py`): a change takes effect on the next pass. The bounds are
  per severity and the model's and the database's, not only the form's (cross review F9): a critical alarm is raised
  within the owner's 10 s target (on-delay at most 10 s) and escalated within 30 min, a warning raised within 15 min, a
  deadband at most its parameter's range; an unusual value inside them (any critical on-delay, a long escalation, a
  deadband over half the narrowest band of the live limits) is shown with a warning on the rules' page, never refused. A
  severity's rule is never deleted (model, check, trigger: `alarms` 0006); a row lost all the same (a restore) never stops
  the evaluation: the safest value of each field stands in (no on-delay, the longest off-delay, the shortest escalation,
  the most attempts) and a critical configuration alarm says so until the row is back (F6). The staleness thresholds the
  alarms depend on are rule data too (F10): how long a water value counts as fresh per parameter (Setup › Reference data ›
  Water freshness, seeded with the hours the code held; the conductivity at 25 °C and the hardness by farm 0042, 7 and 14
  days), the clock tolerance (Platform settings) and a sensor channel's
  fresh heartbeats; the ingest contract's hour (`evaluate.MAX_AHEAD`) is the contract's and stays. No number in the modules
  an alarm's decision reads is a threshold: a test reads them, each named exception with its reason.
- **A device clock** that differs from the platform's is an alarm of its own (owner, 2026-11-09): the skew is measured per
  device from what the ingest stores (`sensors/clock.py`: the device's time of its newest good value against when it was
  received, ahead or behind; a time the ingest replaced is ahead by more than the contract's future skew; a value received
  longer ago than the channel's freshness measures nothing), judged by each severity's device clock limit and deadband
  (Alarm severity rules: warning 60 s / 10 s, the ingest contract's default future skew; critical 300 s / 30 s, the clock
  tolerance), raised and cleared per device on its site by the same lifecycle (`alarms/clock.py`). The device list and the
  unit's card (for the devices whose values it shows) say it as a data-quality note ("Device clock is 4 min ahead").
  "Behind" is late delivery as much as a slow clock (an ingest restart, a gateway draining what it stored during a
  link drop), so it holds only when the device is behind on every pass of its severity's window (Alarm severity rules,
  "Device clock behind for", 600 s: the minimum over the window), and not at all while the ingest reports messages
  waiting for the device's connection; "ahead" is judged at once. Under the ingest contract's future skew (60 s by
  default) the ingest replaces a device time further ahead by the receive time, so the values stay right and "ahead"
  tops out at the warning "more than 60 s ahead"; the rules page says so with the contract's own number, and the critical
  limit is reached behind. The device's values still decide its unit's status; their alarms are never delayed.
- **The alarm system supervises itself** (EEMUA 191, cross review F3): a step of the pass that fails is a critical system
  alarm from the pass it fails in until it passes again; the water step reads all units at once and, when that fails, each
  on its own, and evaluates each on its own, so a unit that cannot be read or evaluated raises its own critical alarm on
  its site ("could not be evaluated") and every other unit goes on; a unit with fish and no point to read its own water at
  is a configuration warning on its site (F16); a judged value that comes without a number for a stated reason (the NH₃
  of a water whose conductivity is past the Davies range, which the chemistry core refuses; a sensor pH on the total,
  seawater or free scale that cannot be put on the NBS scale: the review of the water-chemistry audit, M1) is a warning
  on its site, "<unit>: <value> cannot be evaluated: <the reason>" (subject
  `system:unit:<id>:value_unevaluated:<parameter>`, one per value the limits judge, `REFUSABLE`; its on-delay counted
  from the value's time, for a sensor pH from before its channel's scale changed from when that value would be stale),
  ended on evidence only: "restored" once the value is worked out again, "the water limit was removed" or "no fish in
  the unit any more" once nothing judges it; a later TAN without its pH, or the refused sample leaving the 30-day
  window, ends nothing (RC-4). Beside it the value's own limit levels judge its limits' basis, which needs no
  conductivity and which the judged value is never below (critical past the critical limit, RC-3), or another fresh
  value of the unit's water that judged it on the page (RC-2), and they stay judged by those values: a level
  another value raised ends "back inside the limit" when that water recovers, though the unit's own newest value is
  value-less (F3-1); its own "not measured" is never a "no fish" cause. The summary says "at least" before a basis
  (F3-5). A refused value never clears a limit level, and a pass that could not read the unit ends nothing.
- **Which value can end a water limit level** (the verification of FIX3, F3-1 and F3-7; `alarms/sources.py`, the rule at
  the top; `AlarmSubjectState.own_held`, alarms 0014). The unit's own value is one measured at its own points; another
  value is one of the rest of its water (its loop standing in for it, or another fresh value that judged it worse). A level raised by the unit's own value ends only on the
  unit's own evidence: an own full sample clear of it ends it "back inside the limit" (with every other fresh value clear
  too); an own TAN without its pH, another point's OK value, nothing new, or the bad sample voided end nothing. A level
  raised by another value (the unit's own value clear or value-less) ends when the values that judge it are clear:
  another point's newer OK value ends it; an own full OK sample ends it only when the other values are clear too; an
  own TAN without its pH changes nothing; the bad sample voided ends it only where a value taken after it is clear.
  Either way another bad value holds it, a refused value is never evidence, a
  value that only goes stale ends nothing, and the limit removed or no fish end it with that cause. Every combination is
  a test: `alarms/tests/test_who_ends_a_level.py`. 0014 decides nothing for the levels open when it lands: the first
  pass works out who holds each (F3-8).
  **Decision (2026-11-19, F3-9, under the owner's standing rule):** a critical or warning measured on the unit is
  confirmed over only by measuring the unit again. When the unit's own bad value goes stale and its loop's OK value
  stands in, the level stays open and keeps escalating, and the page, the card and the alarm agree: the unit is
  critical (or warning), its last own value is shown marked stale beside the loop's value with "last own value 0.8924
  critical on dd.mm.yyyy hh:mm, no recent data: measure this unit" (`read.last_own`, `messages.last_own`; nb, tr),
  and a level raised in that state says the same in its summary.
- A system alarm reaches its site's recipient rules; a farm-wide one the
  company-wide rules, and where no rule reaches it by site, every rule its severity reaches: it never reaches nobody (F8).
- **Who is notified**: the alarm recipient rules (a tab: a site or every site, a production department or every one, the
  least severity, a level 0 to 9, a role or one person, only while on shift by the HR roster (`hr.read.on_shift`, the
  board's own rule), the channel). Level 0 is notified when the alarm opens; a rule added later still reaches an alarm that
  is open.
- **Escalation**: an open alarm nobody has acknowledged goes on to the next level with a rule that reaches it once its
  level was first notified its severity's escalation time ago (Alarm severity rules), or at once when
  nobody could be notified at its level. An alarm nobody can be notified of says so. A cleared or acknowledged alarm is
  never escalated.
- **The outbox**: one notification per alarm, person, channel and level (push only; channels are pluggable). A transport
  per channel is named in `settings.ALARM_TRANSPORTS` (`alarms/transports.py`, an interface with a test double); none is
  connected, so nothing is sent anywhere, every notification waits, and the pages say so. A failing transport is tried
  again up to its severity's delivery attempts.
- **Acknowledgement**: who, when, from which device and app ('console' from these pages, the app's name later), the
  notification answered; once per person; the delay is computed from the alarm's opening. Who holds Alarms: Edit may
  acknowledge, and so may anyone the alarm was sent to. The sensors' Alarm events page acknowledges through the same
  service: the event's own acknowledgement columns were carried over by a migration and removed.
- **Append-only**: alarms, clearances, notifications, delivery attempts, escalations and acknowledgements are never changed
  or deleted (a database trigger, as for the activity log), and each is written with its activity-log entry (critical for
  a critical alarm). The Alarms page lists them, open first; an alarm's page shows its whole history in time order.
- **The loop**: `manage.py run_alarms [--loop SECONDS]` (`alarms/engine.py`) checks the sensor rules and the water limits,
  queues, escalates and hands what is queued to the connected transports. Each step (sensor rules, sensor events, water,
  device clocks, notify, send, and the supervision last) runs in its own transaction under one advisory lock, so two loops never queue or send twice and a failing
  step rolls back alone, logged and said in the pass's summary; a failed pass is logged and the loop goes on (defect 5).
  The writes are set-based and the routing is read once per pass (`alarms/routing.py` `Router`): a burst of alarms costs
  the queries one costs (defect 7). Deployment runs it instead of `check_sensors` (the sensors' check alone).

## Platform settings (Company › Administration, `/administration/platform-settings/`)

The rules the platform owner (the customer the platform is given to) sets for the whole company, one row
(`core.models.PlatformSettings`, database checks keep it one row and bound each value), read by the rest of the code through
`core/platform.py` only (once per request: `PlatformSettingsMiddleware`). Read and Edit are an access area of their own;
"platform owner" is the role that holds Edit. Every change is in the activity log with its old and new value.

- **Correction window (days)**, 1 to 3650, 31 until the owner sets another (owner decisions Q3 and Q-F4, F-243): how far
  back a daily record (a stock operation, a feeding, a water sample, a movement of the store, a plan, a treatment, a protocol
  assignment, an experiment's day 0) may be dated, and how old a record may be voided. Older records stay as they are;
  inside the window every record is logged as before. `core.platform.correction_window_days()` is its one reader; the
  messages name the days it says. The regulatory reports re-read a filed report for changes only inside it.
  (Not this window: the fast's 31-day look-back for the last feeding, longer than the longest handling rule, and the
  31 days one page of feeding records covers.)
- **A second person approves a withdrawal warning acknowledgement** (F-164): `core.platform.second_approval_required(
  'withdrawal')` is asked by the one hook (`farm/handling/check.py` `second_person_must_approve`); an unknown kind is an
  error, never a quiet no. The second person's approval flow is not built yet, so the setting FAILS CLOSED (cross review
  F4): ticked, going on past a medicine withdrawal is refused with the reason (a second person must approve, and that
  approval cannot be given here yet); nobody goes on alone. The setting is consulted before anything is asked: the
  harvest dialog and the withdrawal guard's question show that sentence in the place of their box, and a save is
  answered with it whatever is ticked, never first with "Tick the box" (`check.needs_second_person`,
  `farm/tests/test_second_approval_said_first.py`). Unticked (the default), one person's acknowledgement goes on,
  logged as critical.
- **Clock tolerance (seconds)**, 0 to 3600, 300 until the owner sets another (cross review F10): how far ahead of the
  server's clock a water value may be stamped and still count as fresh. A value further ahead, up to the ingest
  contract's hour, still decides its unit's status and its alarm, but is not shown as the newest.

## Roles and users

There are no built-in roles. The platform admin (a Django superuser) can open everything and is the
only one who manages roles and users; everyone else gets exactly what their roles allow.

- **Access areas** (`config/access.py`, read by `core/access.py`): the parts of the console a role
  can be given, one line each, with the actions each offers: Sites, Production departments,
  Systems, Equipment, Tanks, ponds & cages, Sampling points, Species, Feeds, Water limits and Suppliers (read,
  create, edit, delete), Production units (read the page, create = record an operation, delete = void one),
  Feeding records (read the Meal board and Records, create = record a feeding or a meal, delete = void one),
  Feeding protocols and Protocol assignments (read, create, edit, delete), Water chemistry (read the page
  and a unit's water, create = record a sample or a round, delete = void one), Storage (read the page,
  create = record a delivery, issue, write-off, return, transfer or count, delete = void one), Storage
  locations (read, create, edit, delete), Tasks and Recurring tasks (read, create, edit, delete; a person a task
  is for also starts, ticks and completes it), Slaughter facilities and Handling rules (read, create, edit,
  delete), Harvested (read), Harvest plan and Production plans (read, create, edit, delete), Medicines (read,
  create, edit, delete), Treatments (read, create, edit = change the last day, delete = void one), Health events
  (read, create, edit, delete = void one), Sea-lice counts (read, create, delete = void one), Regulatory reports
  (read the page, a report and its exports; create = start a report, a notice or a correction; edit = fill in a draft and
  record it as filed; delete = discard a draft), Messages (read =
  use Messages, create = also create channels), Library and Knowledge entries (read, create, edit, delete; Edit
  also reviews an entry), Employees (read, create, edit, All production and Everyone), Departments (the office departments: read, create, edit, delete), Shift schedule (and Crew), Attendance (read = Today & attendance and the Attendance page, create = enter presence by hand, edit = correct, delete = void), Leave requests (read, create, edit = also approves, rejects and cancels), Leave types, Shifts and Holidays (read, create, edit, delete; on the schedule Edit changes a plan and Delete clears a cell) and Scheduling settings (read, edit), Alarms (read, edit = acknowledge), Alarm recipients (read, create, edit, delete), Alarm severity rules (read, edit), Alarm deadbands (read, create, edit, delete),
  Platform settings (read, edit: the platform owner's right), Opening balances (read; registering one is the platform owner's
  right) and Activity log (read).
  A new tab appears in the matrix by
  adding its line there. The matrix groups the areas where the menu puts their pages (e.g.
  `Production · Setup · Facility structure`); the grouping is not written a second time. Roles and
  users are not areas, so no role can grant them.
  **What an area's Read also reaches is said under it** (`Area.note`, printed below the area's row in the matrix, in
  every language): Experiments and Regulatory reports show farm figures to a person without Read on the farm areas they
  come from (an experiment's read page the batches, fish, biomass, survival and feed conversion of its own tanks; a
  report, on its page and in its exports, everything it is computed from: stock and biomass, the feed given, slaughter
  and harvest plans, smolt, cleaner fish, sea-lice counts and treatments with their medicines, health events with
  diagnosis and deaths, escapes and the sea temperature; the note names them all, the most sensitive among them). That is kept on purpose (a trial needs its own tanks' figures and a regulatory filing its numbers; owner
  decision F-168 / F-173, 2026-11-10), so whoever grants either area is told what comes with it
  (`core/tests_matrix_notes.py`).
- **Roles** (`/roles/`, Django `Group`): a table with each role's users and what it allows; the
  dialog has the name and a permission matrix (areas by group, columns Read / Create / Edit /
  Delete, and Crew, All production and Everyone where an area offers them: see Row scope). Create, Edit and Delete include Read: the form adds it and the browser ticks it. Crew, All production and Everyone include nothing: they widen whose rows the role's other rights reach, so a role saved in the matrix keeps exactly what it had (the Production manager preset has All production without the Team list, `hr/roles.py`). **Deploying this rule:** a role saved before it kept the Read the old rule added; migration `hr/0010_restore_preset_rights` puts the two presets back to exactly their rights, and `manage.py check --database default` lists any other role whose Read on an area may come only from it (core.W003: Read and All production or Everyone, no Create, Edit or Delete there) for the administrator to review in Roles. Crew is not such a column: it is drawn only on the Shift schedule's own page, which needs Read on that area, so Read beside Crew is how it works at all (the Production worker preset) and the check leaves it alone (`core.access.OWN_PAGE`). Saving
  sets exactly the ticked boxes (the model's standard view/add/change/delete permissions). The
  activity log shows permission changes as "Sites: read, create; Activity log: read". Deleting a
  role removes it from its people.
- **Users** (`/users/`): username, name, email, roles, active, invitation, last sign-in, and a Platform admin
  badge. A new user has no password and cannot sign in until they set one: creating them queues the
  **invitation**, a mail with a one-time link that sets their first password, which is sent right after the save
  (see Email: a mail leaves after the request). The Invitation column says where each person stands: "The
  invitation to kari@example.com is being sent", "Invitation sent 10.11.2026 14:05 to kari@example.com. Password
  not set yet.", its link has expired, the address has changed since (so that link no longer works), "Invitation
  not sent" with the reason (the mail server's own words, or that the sending was interrupted), "Not invited yet",
  or "Password set", with when and through which link when it was set through one ("through the link sent to
  wrong@…, which is not this account's address now" tells a link used before a mistyped address was put right).
  While the password is not set, the row has **Send invitation (again)** (POST `/users/<id>/invite/`, the platform
  admin only, never to someone who has set a password, is inactive, has no address or has an invitation under way).
  The activity log and the person's History tab have a row for every invitation (Invited: by whom, when, to which
  address), the platform's own row when one did not go out (Not sent, the kind of failure) and a row when a password
  is set through a link (Password set: by the person, the address the link went to); never a link. An edit sends
  nothing. Deactivating a person ends every link sent to them.
  Email is unique and may be left out: the person is created, the admin is told that no invitation was sent,
  the row says "Not invited: no email address", and the person cannot sign in until an address is added and
  the invitation sent from the row (nobody hands out a password here). An inactive person is not invited.
  Guests and students are users like everyone else. People are deactivated, not deleted, and nobody can
  deactivate their own account. Platform admin status is not edited here (only with `createsuperuser`).

## Security in the pages

- **Text is escaped everywhere.** No template prints a value with `|safe` or `autoescape off` (the one exception is
  the two account e-mails' bodies, `templates/mail/`, which are plain text; `core/tests_escaping.py` names them). A form's help text is text too: several forms write a name into it
  (a task whose place was deleted, equipment whose systems were deleted), so `templates/registration/_field.html`
  escapes it, and Django's own layouts (`{{ form }}`, `as_p`, `as_table`, `as_ul`, `as_field_group`) draw their fields
  with the same template (`templates/django/forms/`). Markup reaches a page only from the few places that build it with
  every piece of text escaped (a reference, a found passage, a sensor chart, the import map);
  `core/tests_escaping.py` names them and fails when a new one appears.
- **Every page asks for a right.** `core/tests_routes.py` walks every route of the project: someone not signed in is
  sent to sign in everywhere but the sign-in and password-reset pages and the language switch, and a signed-in person
  with no role is refused (403, a record page too: it asks for the right before it looks the record up) everywhere but a
  short named list (the overviews, which show only
  the tiles a person's roles allow, and the person's own password; the clock-in/out route, whose argument is a word, not a record). A new page without a check fails it. A page that
  writes asks for its right before it reads the request (the shift plan answered such a person 400 for a malformed
  request before; now 403).
- **A Content-Security-Policy on every response** (`config/settings.py` SECURE_CSP, Django's own middleware): a page loads
  only from its own address; scripts are the project's files plus what carries the response's nonce (the import map,
  `core/templatetags/assets.py`); no inline script, no inline style (a monitoring widget's cell is a class,
  `static/css/card-grid.css`; a capacity bar's or gauge's fill an SVG rectangle's width, `templates/farm/_capacity_bar.html`
  and the units table's `ui-gauge-track`), no
  event-handler attribute, no plug-in, no frame around a page, no form sent elsewhere. So even text that slipped past the
  escaping could not run. `core/tests_csp.py` opens every page that takes no record as the platform admin, as a page and
  as a dialog, and fails on anything the policy would block; it also reads every template for the parts that appear only
  with data. A script that changes a style through the DOM (`element.style`) is allowed by the policy.
- **The fonts are the project's own** (`static/fonts`, declared in `static/css/fonts.css`: Atkinson Hyperlegible Next and
  Bricolage Grotesque under the SIL Open Font License 1.1, one entry each in `THIRD_PARTY.md`): no page asks Google or any
  other site for anything, so no reader's address leaves the farm with a page, and the farm's own network shows them.
- **Personal data is private in the activity log** (owner decision F-059 / F-061 / F-179 / F-050, 2026-11-10; review
  R1 to R7). The log is append-only (a trigger): no page and no ordinary statement changes or removes a row, so what
  is written into it stays. Two pieces of code set the trigger aside, each inside its own transaction and for its own
  updates only: the conversion below (`core/0011`), and the erasure of a stranger's address on request
  (`manage.py erase_stranger_address`, at the end of this list).
  - **What is private**, in the code (the tabs' `private_fields`, `ContactList.PRIVATE`, `tasks.services.PRIVATE`,
    `SERIES_PRIVATE`, `add_note`) and in the conversion's list, which a test holds together: a contact person's e-mail
    and phone (a site's and a supplier's contact list); a site's, a supplier's and a report's own contact e-mail and
    phone; a task's and a recurring task's description, a task's notes, completion note and reason for cancelling; HR's
    leave reasons and notes (as before). **Plain, by decision**, with the reason in
    [docs/erasure.md](docs/erasure.md): a contact's name, role and primary flag, a site manager, a report's contact
    person, a supplier's name, number and address, a user account's address, name and roles, a task's title and checklist.
  - **How.** One mechanism, `core.audit.private` / `core.audit.digest`: the enumerated "Private text" with eight hex
    digits of an HMAC-SHA256 under the digests' own key (`settings.AUDIT_DIGEST_KEY`, `DJANGO_AUDIT_DIGEST_KEY`; the
    secret key when it is not set, so the two are rotated apart). A contact list is logged as parts: who the contact
    is in plain text, then the e-mail and the phone as private values that say which they are; the page shows
    `Kari (Vet, primary), Email: Private text, Phone: Private text`. This is **pseudonymisation**: the log still shows
    that a value changed, and two equal digests mean "probably the same value"; whoever holds the key and the log can
    recover a short value (a phone number) by trying them all.
  - **The digest is stored, never shown.** `AuditLog.shown_changes` is the one place a stored value becomes text (the
    activity log, and a record's History tab, which whoever may edit the record reads without the Activity log right),
    and it never prints a digest: nobody types a guess, saves and compares it with a removed contact's. The database
    viewer masks `audit_log.changes` (`config/database.py`: cells, search, sort, filter and the CSV export), so the
    platform admin cannot either; a digest is read only with direct access to the database.
  - **The rows written before** were converted by migration `core/0011_private_log_values`
    (`core/migrations/_private.py`, one place the migration, the command and the check call). An old contact-list
    sentence is taken apart and becomes exactly what the code writes now, so the name, the role, the primary flag and
    who was added or taken off stay. It is read with matched brackets (contacts split on "; " and details on ", " only
    where no bracket is open, so "Service manager (24 h line)" is a role) and from the right-hand end: the e-mail is
    what the contact form's own field accepts (`validate_email`, one definition), the phone is digits in a phone's
    form, "primary" is last. No address and no number of five digits or more stays plain unless it is the role left of
    the e-mail: a role and a phone that cannot be told apart become one private part beside the name; a sentence whose
    brackets do not balance, or with a name that holds an address or a number, becomes one private value, counted, its
    entries named by id in the log's own row. Words without a number typed into the phone box stay plain as a role. The table is locked against writers before it is read; the append-only trigger is set aside for the
    updates only, inside the transaction, and set back; only `changes` is written. **One-way:** going back is refused
    once a row was converted. It refuses to convert real data under a key printed in the repository (DEBUG off and a
    `django-insecure-` key).
  - **Before and after it runs.** `manage.py private_log_values --dry-run` writes nothing and says how many values
    would be converted and which entries' contact lists cannot be taken apart: run it on a copy of the database first.
    Stop every server running the old code before `migrate` (it would write plain values behind the conversion);
    afterwards `manage.py check --database default` (core.W004) counts plain values under private labels, and
    `manage.py private_log_values` converts what an old server left.
  - **A stranger's address is erased from the log on request** (the owner's decision of 2026-11-11). An invitation
    sent to a mistyped address leaves that address in `account_mails` and in the account's log rows (`Email`,
    `Sent to`, `Link sent to`). `manage.py erase_stranger_address ADDRESS` lists what would change and, for each
    account, what the log says of the address; with `--apply --instruction ... --carried-out-by ...` it replaces the
    address, in one transaction, by `erased@invalid` in `account_mails` (also inside a mail server's reply) and by the
    value "Erased on request" in the log, and adds one "Erased on request" row on each account touched
    (`core/erasure.py`). **Who:** the platform's database administrator, on the data-protection officer's written
    instruction for that address. **What it checks:** only that no account has the address now. It cannot tell a
    stranger's address from a person's own former one, so the dry run shows when the address was the account's own,
    whether it replaced an earlier address, whether a password was set through a link sent to it and what the
    account wrote meanwhile (by the account's key, whatever its name), and warns when it does not look like a
    stranger's: always when it replaced an earlier address and a password was set through a link sent to it, the way
    an account is taken over. The DPO judges, the command obeys. **What it will not do:** an address that is an
    account's own now, a mail to it still being sent (refused, not waited for), an address that only contains it, any
    other label, shape or record (it names where else the text stands; nothing covers an account's username or the
    name on the log's old rows), an instruction or a name that holds the address anywhere in it (nothing it writes
    may hold it; this refusal refuses rather once too often). **The Turkish capital İ and the dotless ı** are other
    letters than i to the comparison that decides what is replaced, so `İNFO@EXAMPLE.COM` is not erased for
    `info@example.com`; the dry run names the rows that hold the address only when they are read as i, and the
    refusals read them as i. **The log's writers, the alarms among them, wait while it holds the lock**: it reads
    everything first, then tries for at most `--lock-wait` seconds (5; a positive number, 600 at most) to have the
    log and `account_mails` locked. It waits for the log with nothing in its hand and takes the mails at once or
    lets the log go and starts again: it never waits for a lock while it holds another one, so no other session (the
    mail worker, which writes a mail's row and then the log) is stopped by a deadlock with it, and a table held for
    a while (a writer, a vacuum or an analyze) is waited out. When the seconds are over it gives up, has changed
    nothing and names the table it could not lock. It reads every mail again under the locks. **What remains:** the rows themselves (who invited whom, that a link was used, that the address
    changed), the placeholder, and the address in every backup taken before. A placeholder, not a digest: this is
    erasure, not the pseudonymisation above. The users tab, the History tab and the log read an erased row in every
    language (`core/tests_erasure.py`).
  What is erased where on a person's request, what remains and who may do it: [docs/erasure.md](docs/erasure.md).

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
  badge, booleans are check marks, timestamps, numbers and arrays are shown as stored (not localised), UUIDs
  are shortened (the full value on hover), long text and JSON open in place, and a foreign key shows the
  stored id and the record it points at, linked to that table filtered to that row. Deleted rows are
  shown and marked, and can be hidden or shown alone. A header sorts, a filter box matches text
  inside a value (equals, for numbers, ids and booleans), the search box looks in every column, 100
  rows a page. **Export CSV** gives the current filter, streamed and capped at 50,000 rows; text a
  spreadsheet would run as a formula (starting with `=`, `+`, `-`, `@`) gets a leading apostrophe.
- **Structure**: columns (SQL type, nullable, default, key, the model's field), constraints, indexes
  and the relationships in both directions, read from the database and matched with the Django
  model. A generated column (a unit's volume) shows its expression where a default would be, and is
  sorted and filtered as the number it holds. A link the database does not check (`db_constraint=False`, like `audit_log.user_id`) says so.

Tables are not listed one by one: they come from the models of the apps in `config/database.py`
(`farm`, `knowledge`, `inventory`, `messaging`, `reports`, `tasks`, `hr`, `experiments`, `monitoring`, `sensors`, `core`, `auth`; the
sensor readings, billions of rows, stay out), so a tab that is ported later appears with no new code, in the section its
app belongs to. The tables of other apps (sessions, the Django admin's log) are not shown at all.
Everything the query string names is checked against the table's real columns and the rows come
through the ORM.

**Sensitive data.** `config/database.py` lists the masked columns (`auth_user.password`,
`messages.body`: what people write to each other, see Messages, and `audit_log.changes`: it holds the digests of
private values, and what changed is read on the activity log page). A masked
column is never read from the database: its cells show a placeholder, it cannot be sorted, filtered or
searched (that would reveal it a character at a time) and the export leaves it out. A column that
holds a secret belongs in that list; a test fails when a column named like a password, secret, token
or session is not in it.

## Data map

Every table can be filled, read, changed and deleted on some screen, and a table that cannot says so. The map of which
screen does what is **generated from the code**, never kept by hand: `manage.py data_map` writes
[docs/data-map.md](docs/data-map.md) (for people and for the visual design: per table its description, columns, links
and their `on_delete`, constraints, the create, edit, delete and read screens with their routes, the forms and inner
tabs each column is on, soft delete and restore, its database viewer entry, the tests that mention it, and a last
section, **Gaps**, ranked) and [docs/data-map.json](docs/data-map.json) (the same, for tools). `manage.py data_map
--check` fails when the committed files are stale; run `manage.py data_map` and commit the result after any change to
a model, a form, a tab or a `screens.py`. It reads the code only, so it needs no database. A merge that conflicts in
the two files is settled by running it again.

What the code already says is read from it: the models (tables, columns, `on_delete`, constraints), a tab
(`core.crud.Resource`: its create, edit and delete pages, its list and read pages, its form's fields and inner
tabs, the delete plan), its row lists (a site's contacts), the field of a many-to-many link or a `LinkList` on a
form, the routes, the admin's Restore, the database viewer and the model docstrings. A **tab needs no declaration**.

What it cannot say is declared once, next to the app that owns the table, in `<app>/screens.py`: a `SCREENS` dict
from a model's name to a `Screen` (`core/datamap.py`). It is needed for a table that is not a tab (a record a dialog
writes through a service, a row the code fills) and for what a tab's form leaves out:

```python
SCREENS = {
    'FeedingRecord': Screen(
        create=(feeding.record_feeding,),             # the dialog's view (a function, a tab, or a URL name)
        edit=no('a ledger is never edited: a mistake is voided and recorded again'),
        delete=(feeding.void_feeding,),
        read=(feeding.feeding_records, feeding.meal_board),
        extra_fields={'token': 'the form's one-time token'},      # a form field that is no column
        columns={'void_reason': system('typed in the void dialog')},  # a column no form has, and why
    ),
}
```

- `create`, `edit`, `delete`, `read`: the views that do it, or `no(why)` (missing on purpose) or `gap(why)` (missing and
  should not be: it is listed under Gaps). A view is named by its function, so a renamed or unrouted view fails. A
  tab, a row list and a many-to-many link have their paths from the code; a declaration is added to them (a health
  event is voided as well as edited).
- `part_of='farm.StockOperation'`: written with that record, so its create, edit and delete are that record's.
- `forms`: form classes that are not model forms of the table but fill its columns by the same name (a dialog's plain
  form). `fills={'count': 'count_delta'}`: a form field that fills a column of another name (`'VoidForm.reason'`
  names the form).
- `columns`: a column no form covers: `computed` (the code fills it), `system` (set as part of the work),
  `dynamic` (a form makes its fields per record) or `gap` (a person should fill it and no form has it); `'*'` for all
  the rest. The audit columns, a primary key, an uneditable column and the parent of a row list need nothing.
- `extra_fields`: a form field that is not a column and fills none. `restore=no(why)`: a soft-deleted record the admin
  does not restore. `note`: a line the paths do not say.

`core.test_datamap.DataMapTests` enforces it: a model with no create, edit, delete or read path, a column on no form
with no reason, a form field that is no column, a declaration for what is not there or already covered, a declared
view that no route answers to, a table the database viewer does not show (its app is missing from
`config/database.py`), and committed files out of date all fail, the message naming the model and the `screens.py` to
declare it in. A new app is picked up from `INSTALLED_APPS` (the apps whose code is under the project directory), so
its tables fail the test until its `screens.py` declares them. **Adding a feature** therefore ends with its tables
on the map: a tab declares nothing but its fields on its form; a dialog that writes through a service names its
views in `screens.py`.

## Revisions (`core_rev`, `core/rev.py`)

The rule (performance plan; live-data architecture, stage 3): a derived figure is worked out on read by the function
that owns it. It may be stored only when the database itself proves the stored copy still valid: no figure is cached
for a time (no TTL), no counter sits on a business table, and no write path has to remember to clear anything. The
proof is a **revision per (scope, key)** in the table `core_rev`. Nothing reads it yet: the stored water (the plan's
B3) will stamp the revisions of its inputs and use a stored row only while every one of them is unchanged; until then
the revisions move and no page changes.

**How a revision moves.** The database moves it, never Python: each tracked table has three triggers, made by the
migration operation `core.operations.TrackRev`. One notes the keys a changed row touches (the old and the new row's) and
the earliest day it touches while the transaction runs, writing nothing; the second, deferred, applies them at COMMIT,
each key once and in sorted order, so a 5,000-line stock operation writes one row per key and two writers in opposite
order never deadlock (a deterministic test holds that a commit blocked on one key already holds every key sorted before
it and none after it, whichever order it wrote them in); the third moves every key of its scope on a TRUNCATE, which
fires no row trigger. A key's row stays locked from its apply to the end of that COMMIT: on a big operation that is the
rest of its commit, about a tenth of a second, and a second writer of the same key waits that long at its own
commit. The services, `bulk_create`, the admin, raw SQL, a soft
delete, a restore of a record and a TRUNCATE are all covered; a transaction or savepoint rolled back moves nothing.
Keys are text (a batch's id is a UUID; a table-level scope's key is `0`). A change without a day counts for the whole
history (`dirty_from` 0001-01-01).

**What is tracked:** every input of the water's judgement (`farm/water/read.py` `latest`, the sensors' provider):

| Scope | Key | Tables | Why |
|---|---|---|---|
| `water_point` | sampling point | `water_measurements` | the samples: a value written, changed, moved to another point, voided or restored |
| `unit_stock` | unit | `stock_movements`, `stock_operations` (date, void), `batches` (species) | the fish in a unit on a day decide which species, so which limits, a value is judged for (`SpeciesBook`) |
| `batch` | batch | the same three | the stock fold's own key (ported from the performance work; no reader yet) |
| the table's name | `0` | `water_sampling_points`, `water_limits`, `species`, `water_freshness`, `tanks`, `systems`, `sites`, `production_departments`, `equipment`, `equipment_systems`, `platform_settings`, `sensors_binding`, `sensors_channel` | the points and their owners, the limits and the live species they belong to, the freshness rules and the clock tolerance, the places (a unit's water type, its system, its site's clock and altitude), the equipment and the systems it serves (whose units an equipment point is judged for), which channel counts where with its state, pH scale and freshness |

A ledger line moves its batch and its unit with its operation's day; an operation re-dated or voided or restored moves
every batch and unit it has lines of, with the earlier of its two days; a batch given another species moves itself and
every unit it was ever in, with the whole history. A table-level key moves on any change of its table: reference data
changes rarely, and a stored row then is simply built again. **Never tracked:** the tables the ingest writes
(`sensors_reading`, `sensors_channel_state`, `sensors_device_state`, `sensors_ingest_status`, `sensors_dead_letter`:
`core.rev.NEVER_TRACKED`). A test holds it against the ingest's database role itself: the tables `sensors_ingest` may
write are exactly these, none has a revision trigger and none is tracked. A trigger there would slow every reading and
could stall the ingest's commits. A live value is proved by its channel's
state, which the stored row snapshots, never by a revision.

**The proof a stored figure uses.** It keeps the revisions it was built from, read BEFORE the data (`rev.stamp`, one
query). It is valid while every revision is still the same. A day-ranged figure (a fold checkpoint) may also use
`dirty_from`, the earliest day changed since its last build (`rev.mark_built`, a compare-and-set refused when a write
landed while it read). A key without a row is unknown, never valid: `rev.ensure(pairs)` gives keys a row (above the
floor, the whole history dirty), and the migrations that add the triggers gave one to every point, unit, batch and table
there was then (`core_rev_ensure`). A reader ensures its keys, then stamps them, then reads the data.

**Operating it.**
- `manage.py check --database default` warns (core.W005) when a declared trigger is missing, disabled, or enabled for
  replica sessions only, on a table or on a chunk of the `water_measurements` hypertable: a change to its table would
  pass unseen. Quiet until core/0014 has run. It checks that each trigger is there and fires, not its definition.
  TimescaleDB refuses to disable a trigger on a hypertable or a chunk; a chunk's trigger can still be dropped.
- `manage.py core_rev_repair` (the warning's hint) makes the missing triggers again exactly as their migrations made
  them (`core.rev.operations()`), then rebuilds every revision, since changes may have passed unseen meanwhile. It does
  nothing when none is missing.
- `manage.py core_rev_rebuild` after a restore of the database, a load run with the triggers off, or a session run with
  `session_replication_role = replica` (which skips ordinary triggers): every revision moves past every stored figure's
  stamp and a floor is set for keys seen later, so every stored figure is built again. It locks `core_rev` first (SHARE
  ROW EXCLUSIVE: readers go on, the commits of writes to tracked tables wait until it ends, a second or less) and reads
  the largest revision only then, so a committing writer neither deadlocks with it nor has its revision set back (a
  deterministic test holds both).
- A migration that writes a tracked table and then alters it in the same transaction must run `SET CONSTRAINTS ALL
  IMMEDIATE` first (a table with pending deferred trigger events cannot be altered), as farm 0019 and 0021 already do.

**What the stored water (B3) must hold to.** The revisions prove only what their triggers see; the reader is bound by:
- **Every input is a key.** The `batch` scope covers the lines, the operations' dates and voids and the batches'
  species, which is what the water reads (`SpeciesBook`). It does not cover all the stock fold reads (the opening
  balances, a batch's input date, an operation's kind, which are edited only by their own operations today): a stored
  fold checkpoint must add them before it relies on `batch`.
- **Ensure, stamp, then read**, in that order, in one REPEATABLE READ snapshot; `rev.mark_built` runs last, in its own
  short transaction, so the rows it locks are held for no longer than that.
- **No write on read.** `farm.water.freshness._load()` makes a missing freshness row again and `PlatformSettings.get()`
  makes the settings row when a restore lost it: both write tracked tables while reading, so they fail in a READ ONLY
  evaluator and move a key when they do write. The evaluator must read those rows without them (or have them made by a
  migration or a command first).
- **What bypasses the triggers**, after which `manage.py core_rev_rebuild` must run: TimescaleDB's `drop_chunks` (it
  drops chunks, no row trigger fires), `session_replication_role = replica`, `ALTER TABLE ... DISABLE TRIGGER ALL` on a
  plain table, a rewrite of a table outside the ORM and SQL (`pg_restore`, a load with `--disable-triggers`, a copy
  of the files). The reader must also call `core.rev.missing()` and compute live while it names anything, so a dropped
  trigger never lets a stale row through. `core.rev.STAMPED` gets the stored table's largest stamp, so a rebuild moves
  every revision past it.

**What it costs a write** (measured 23.11.2026 on a GitHub runner, ubuntu-24.04, the test runner's throwaway server
with fsync off, one worker: each case committed with every revision trigger made and again with them all dropped,
alternating, the median; TimescaleDB refuses to disable a hypertable's triggers, so they are dropped and made again):

| Write | Triggers on | Off | Added |
|---|---|---|---|
| a water sample through `farm.water.services.record` | 117.60 ms | 117.56 ms | +0.03 ms (lost in the service's own time) |
| a water sample, one bare INSERT | 2.31 ms | 1.95 ms | +0.36 ms |
| a limit edit (`save`) | 2.53 ms | 1.91 ms | +0.63 ms |
| a 5,000-line operation (2,500 transfer pairs), 1 batch, 2 units | 436 ms | 294 ms | +142 ms |
| the same over 50 batches and 50 units | 443 ms | 294 ms | +149 ms |
| the void of a 5,000-line operation (one UPDATE, keys from its lines) | 19.1 ms | 1.3 ms | +17.8 ms |

A ledger line costs about 30 µs: two note triggers (scopes `batch` and `unit_stock`) and two deferred apply events per
row, whatever the number of keys; the apply itself writes one row per key. A sample or a reference row costs a fraction
of a millisecond. The measurement is the temporary test `tests_rev_overhead.py` (kept in the notes, not in the
repository).

## Local setup

```
npm install && npm run build                 # compiles frontend/*.ts into static/js (use `npm run watch` while editing),
                                             # then builds static/css/tw.css (Tailwind; commit it when it changed)
docker compose up -d                         # TimescaleDB on localhost:5433 (5432 is often a local PostgreSQL)
C:\Python312\python.exe -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python.exe manage.py migrate   # also enables the timescaledb extension (core/migrations)
.venv\Scripts\python.exe manage.py compile_catalogs   # builds the translations (.mo, not committed); redo after pulling .po changes
.venv\Scripts\python.exe manage.py createsuperuser
.venv\Scripts\python.exe manage.py runserver 8047
```

The water chemistry needs the `chemcore` module, which is built only in the container image (see
[Water-chemistry core](#water-chemistry-core-chemcore)); a plain virtual environment does not start without it.

The database connection reads `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` and `DB_PORT`; the
defaults match the local container in `docker-compose.yml`. The mail settings (`EMAIL_HOST`, `DEFAULT_FROM_EMAIL`, `PUBLIC_BASE_URL` and the rest) are listed under Email: a development server needs none and prints its mail in the `runserver` terminal. `COMPANY_TIME_ZONE` is the company's time zone, a new site's and the one migration farm/0028 gives a site without one
(default `Europe/Oslo`; the server's own clock stays UTC; one of the zones a site may have, or the server refuses to start: `farm.E001`). `DB_CONN_MAX_AGE` keeps a connection open between requests for that many seconds (default 0, one per request) and is meant for a server with long-lived worker threads or processes (gunicorn); a kept connection is health-checked before reuse. Never set it for `manage.py runserver`: the development server starts a new thread for every request, so each request leaves its own connection open until the database refuses new clients ("too many clients"). Uploaded files (the library's PDFs) go to
`MEDIA_ROOT`: `DJANGO_MEDIA_ROOT`, by default `media/` in the checkout (ignored by git); keep it outside the
checkout anywhere but a developer's machine, and back it up with the database.

## Water-chemistry core (`chemcore/`)

The chemistry of the Water Quality Management Chart, the calculator and the replay has moved, function by function,
from `farm/water/*.py` into a Rust core, `chemcore/`, that runs **only on the server**, called from Django through
PyO3. Nothing of it is ever shipped to the browser (owner amendment B2: no calculation, formula or constant is
reachable there, no WebAssembly); the browser receives finished results. The plan, the owner's amendments and the
steps are in the scratchpad plan `chemcore/PLAN.md`; the state of each step is below.

- `chemcore/core`: the chemistry, `#![no_std]`, `unsafe` forbidden, its only dependency `libm` (every exp, log,
  pow comes from it, never from the platform, so a result never moves with the server's C library).
- `chemcore/py`: the Python module `chemcore` (PyO3, abi3 for CPython 3.12 and later), built into a wheel by
  maturin. Only `farm/water/native.py` imports it (a test checks the whole checkout). There is no Python
  fallback: without the module the server does not start, and the checkout's own `chemcore/` directory is refused
  as a module.
- The handshake: `chemcore/EXPECTED` names the build the server accepts (version, formula version, a digest of the
  core's source). The system check `core.E001` (an Error) stops the server when the installed module differs.
  `chemcore/scripts/gen_expected.sh` writes the file from the built module; it is never edited by hand.
- Errors are explicit: never a silent fallback, never a NaN shown as a number, never a concentration below 0 (a water
  that cannot be is refused: `ImpossibleWaterError`, below). Every formula carries its literature source and validity
  range in the code.

**Building from a clean machine** (Docker is the only requirement; native Windows builds are not supported: the
development machine has no MSVC linker, and the owner chose container-only development):

```
docker build -f docker/testrunner.Dockerfile -t balik-testrunner-chemcore .          # tools, wheel, runner
docker build -f docker/testrunner.Dockerfile --target chemcore-tools -t chemcore-tools .
docker run --rm -v "$PWD:/repo" -w /repo chemcore-tools sh chemcore/scripts/test.sh     # every gate
docker run --rm -v "$PWD:/app" -w /app balik-testrunner-chemcore sh chemcore/scripts/gen_expected.sh   # after a core change
docker run --rm --network balik-ciftligi_default -e DB_HOST=db -e DB_PORT=5432 -v "$PWD:/app" balik-testrunner-chemcore python manage.py test
```

The image's stages: `chemcore-tools` (`rust:1.88.0-slim-bookworm` by digest, rustfmt and clippy, maturin 1.16.0 by
hash from `docker/chemcore-build.lock`, cargo-deny 0.20.2 by sha256), `chemcore-wheel` (`maturin build --release
--locked`), `runner` (`python:3.12-slim` by digest, every package by hash from `docker/requirements.lock`, then
the wheel; the build fails when `import chemcore` does). `chemcore/scripts/test.sh` is the gate list: rustfmt,
clippy with `unwrap`, `expect`, `panic`, indexing and `todo` denied, `cargo test`, the core depends on `libm` only,
no wasm crate or target, `cargo deny` (licences MIT, Apache-2.0, Apache-2.0 WITH LLVM-exception, Unicode-3.0; no
copyleft reference code such as PyCO2SYS copied; rodbus and wasm crates banned; advisories), `chemcore/THIRD_PARTY`
regenerated and compared, and the runner's lock agreeing with `requirements.txt`.

**Pinned, and how to upgrade.** Rust 1.88.0 (`chemcore/rust-toolchain.toml` and the image digest), `libm` 0.2.16
and `pyo3` 0.30.1 exactly (`chemcore/Cargo.toml`, `Cargo.lock` committed, `--locked` everywhere), maturin 1.16.0,
cargo-deny 0.20.2, the two base images by digest. To upgrade one: change the pin (and the digest or hash) in one
commit, rebuild, run `test.sh` and the Django suite, regenerate `EXPECTED`. A `libm` or toolchain change can move a
last bit, so it also bumps `FORMULA_VERSION` and re-records the golden reference (never silently). The Python
locks are regenerated with `pip-compile --generate-hashes` (pip-tools) in the runner's base image from
`requirements.txt` (and `maturin==<version>` for the build lock).

**Measured before the first line of product code (S0 spike, 2026-11-05).** `libm` and glibc (2.36 and 2.41) differ
in the last bit in 1 to 11 % of exp/log/pow calls (at most 2 ulp), so the Rust core can never be bit-identical to
today's Python: every comparison with the Python reference is by a tolerance class, and only native against PyO3
is bit-for-bit. `libm::pow(x, 2.0)` equals `x * x` on 7 x 10^7 draws. Rust `{:.2}` formats exactly as Python
`%.2f` (10^6 values, ties included), while the `shown` rule (half-even on the shortest digits) differs from
`%.2f` on 9.6 % of a tie-heavy sample: one display rule for the card and the player is still to be chosen. The
wheel is 225 KB, imports in 10 ms, a call costs 0.2 to 0.3 µs. One whole chart takes about 1 ms (Python 18 to
25 ms); 2000 all-different waters take 2 to 3 s, so the replay shares the heavy layers between frames of the same
temperature (a synthetic page: 54 different temperatures, 99 to 164 ms, 128 KB compressed).

**Nothing changes a result silently.** These references hold the chemistry (golden v3 beside them, for the owner):

- *Golden v1* (`chemcore/golden/v1`, 2.8 MB): what today's Python returns for a fixed corpus (every constant of
  1 245 waters, 1 920 carbonate waters with each solve's path, 1 500 analyses, 600 charts, the dosing and simulator,
  the small charts, and the edges: which inputs Python refuses, the alkalinity floor ±1e-9, the box's ties).
  `chemcore/scripts/record_golden.py` records it, only in the runner image (the last bits are glibc's); its manifest
  names the formula modules' git blobs. `farm/tests/test_golden.py`: the recorder reproduces itself byte for byte and
  today's Python reproduces v1 bit for bit. v1 is never re-recorded silently; a version that changes results is v2,
  after the owner decides. `chemcore/tolerances.toml` holds the parity classes the Rust core will be held to.
- *Formula 3 and golden v3* (`chemcore/golden/v3`, 480 KB; I1 and I2, owner amendment B5; **the application's since
  2026-11-09**, `FORMULA_VERSION` 3). Every chemistry of a water starts from `chemistry.water_equilibria` (in Rust
  `fresh::water_equilibria`; the analysis, the chart, the dosing, the simulator, the small charts, the replay, the trail
  and a sample's NH₃ all take it), and every `Equilibria` says what it was worked out by: its `formula`, its
  `ionic_strength`, the `strength_source` (conductivity, hardness, salinity, alkalinity, seawater, none) and the
  `sea_weight`; the pages say it beside every worked-out value. Up to 1 ‰ (`FRESH_UP_TO`) the ionic strength is the
  water's own: an estimate, the conductivity compensated to 25 °C (I = 1.6e-5 κ, Russell 1976) else the salinity's (DOE
  1994), never below the lower bound of the ions measured (the hardness with the alkalinity, else the alkalinity alone),
  0 with nothing measured (formula 1's ideal water); the constants are the thermodynamic ones made concentration
  constants with Davies activity coefficients whose A is the temperature's (I1: ε of Malmberg & Maryott 1956, ρ of
  Kell 1975; Hamer's 1968 table within 0.03 %). From 5 ‰ (`SEA_FROM`) they are formula 1's seawater constants, the NBS
  conversion with the same A and Kw Millero's on his seawater scale (the corrections of 2026-11-10, below). Between, each constant is the geometric blend, the sea's weight linear in the salinity
  (Millero et al. 2006 measured K1, K2 from S 1; Dickson's 1990 KSO₄ and KB hold from S 5): the old 5 ‰ boundary jumped
  up to 25 % in CO₂, the band not at all. The band assumes sea water's ions (sulfate, fluoride, the Mg and Ca ion pairs in Millero's K1
  and K2, borate): a unit may say its **water origin** (cross review F3, F4). Salt-added fresh water takes the fresh path up
  to the Davies limit (S 28.39 ‰ as NaCl, or a conductivity of about 59 500 µS/cm; then the sea path, its constants and
  corrected values jumping there, its judged NH₃ and CO₂ never dropping, the ideal basis kept on both sides), its ionic strength NaCl's (the salinity as NaCl's molality,
  58.443 g/mol; the conductivity by NaCl's 8.4e-6 per µS/cm, from its molar conductivity of about 118.5 S cm²/mol at
  0.01 mol/L, 25 °C, instead of Russell's 1.6e-5, which fits bicarbonate waters and overstates a NaCl water's ionic
  strength about 1.9 times, its corrected NH₃ and CO₂ about 4 % low at 3000 µS/cm), no seawater boron: at 3 ‰ its CO₂ is 4.6 to
  9.2 % above what the band gives. Not said, the band is kept and the provenance says "assumes sea water's ion
  composition; salt-added fresh water may read low CO₂". **Plausibility warnings** (cross review F5; `fresh::plausibility`, on every
  `Equilibria` as `warnings`), said after the provenance with the value, never a refusal: the conductivity against the
  salinity (the salinity's ionic strength outside 5.9e-6 to 2.1e-5 per µS/cm, NaCl's 8.4e-6 to Russell's 1.6e-5 each
  widened by Russell's ±30 % scatter); a conductivity with no salinity and the hardness measured giving over 30 times the
  ionic strength of the hardness and alkalinity (in-house, round 2: world-average river water, Livingstone 1963, has
  about 1.3, an intensive RAS 10 to 20), or giving less
  than their bound by over 1.5 times (Russell's scatter; the bound is used); a sea water's conductivity on a fresh water
  (a salinity under 1 ‰ with a conductivity PSS-78, UNESCO 1983 with Hill et al. 1986, reads as 5 ‰ or more, about
  8 950 µS/cm: a hard fresh RAS at 2000 to 3000 µS/cm stays quiet). Each says what to check. The thresholds are documented constants: no reference table holds per-water constants. The fresh path refuses an ionic strength above 0.5, the Davies limit
  (`DAVIES_MAX`; a sample's NH₃ then says why and shows nothing). The conductivity and the hardness are water parameters
  (cross review F8: only the compensated conductivity is read; the sensors' `conductivity_us_cm`, at the water's own
  temperature, never). Formula 1 is still worked out exactly, by name only (`formula=1`: golden v1, `FORMULAS` = 1, 3),
  so a value shown before the switch can be reproduced; a test fails when an application module calls formula 1's
  `equilibria`. `chemcore/scripts/record_golden_v3.py` records golden v3 from the core (1 980 waters, each with formula
  1's and formula 3's constants and provenance, the CO₂, the NH₃ share and, from 5 ‰, log Ω at five pH, and the whole
  analysis of each by both; each recording again is by the script, its reason in the script's docstring); `farm/tests/test_golden_v3.py`
  holds the core to it bit for bit; `farm/tests/test_cold_water.py` holds formula 3 at 0 to 12 °C to Emerson et al.'s
  table, the Plummer & Busenberg and Harned & Hamer constants and an independent implementation of the free CO₂. Every NH₃ and CO₂ judgement takes the larger of the basis the limits were set on and the activity-corrected
  value (cross review F1: `Equilibria::nh3_share`, `ph_where_nh3`, `co2_judged`, `ph_where_co2`, `fresh::limits_basis`;
  the corrected values beside them as information; `farm/tests/test_limits_basis.py`, `chemcore/core/tests/basis.rs`). The
  comparison for the owner, in Turkish, with the jump table, the choice of the band and the before and after numbers
  at 2, 5, 8 and 12 °C, is `chemcore/findings/I2-comparison.md`; I1 is in `chemcore/findings/B1.md`.
- *Three corrections to formula 3* (2026-11-10, owner-approved after an independent check of the core against PyCO2SYS
  1.8.3.4 and seacarb 3.4.2, numbers only; formula 3 had not left its branch, so they are in formula 3 itself and golden
  v3 was recorded again by its script; formula 1 and golden v1 are untouched, each keeping its old behaviour by name).
  **Kw**: formula 3's ion product of water is Millero's (1995) on his seawater scale (`kw_sws`, ln constant 148.9802)
  over [H⁺]SWS / [H⁺]free (`kw_free`), as K1, K2 and KNH4 are converted, on the sea path (`fresh::sea_equilibria`), in
  the band and on the fresh path, where at S 0 it is pure water's (pKw 13.995 at 25 °C). Formula 1's `kw_total` is the
  2007 Guide's total-scale value (Dickson, Sabine & Christian 2007, ch. 5, eq. 62: Millero's constant less 0.015, a
  sea-water approximation that leaves pKw 14.001 in pure water); its docstring had named Millero as the source. Kw
  moved by −0.8 to +1.5 % in golden v3, formula 3's own CO₂ by at most +0.085 % there (pH 6.5 to 8.5); nearer the
  alkalinity floor more (the change is Kw's times the hydroxide's share of what is above the floor: 0.4 % at 40 °C, S 40,
  1 meq/L, pH 9). The basis the limits were set on keeps formula 1's Kw, so a judged CO₂ never falls below formula 1's.
  **Ω**: the calcite and aragonite saturation takes the calcium (mg/L) and the carbonate (of a per-litre alkalinity) per
  litre, and Mucci's Ksp is per kg², so formula 3 takes the Ksp per litre (`Equilibria::ksp_per_litre`: times the square
  of `seawater_density`, the one-atmosphere EOS-80 of Millero & Poisson 1981, check values of UNESCO 1983), one
  definition for the small chart's index and the chart's Ω = 1 line. Ω had been ρ² too high: it fell by 4.1 to 5.4 % at
  S 35 and under 0.8 % at S 5. **A water that cannot be**: a pH whose hydroxide and borate alone are at least the
  alkalinity (its DIC, CO₂ and carbonate would be 0 or negative; 40 °C, S 40, 0.5 meq/L, pH 9 gave a DIC of −0.017
  mmol/L) is refused by the core at every door (`ChemError::ImpossibleWater`, in Python `native.ImpossibleWaterError`, a
  ValueError): the analysis (the water and the target), the equilibria's `dic`, `co2_judged`, `co2` and `carbonate`,
  the chart, the small charts, the safe zone, a judged step and the simulator's start. One rule,
  `Equilibria::possible`, which `why_impossible` asks too, so the reason the calculator's form, a unit's chart and a
  replay frame say and the core's refusal are one decision; the trail (`sensors:trail`) lists such an hour under
  `impossible` and draws no point. The chart's own geometry still follows a pH line below its floor (the safe zone's
  corners, the solver of a CO₂ border): those are not waters. Tests: `chemcore/core/tests/kw.rs`, `omega.rs`,
  `impossible.rs`; `farm/tests/test_saturation.py`, `test_impossible_water.py`, `sensors/tests/test_impossible.py`.
- *Anchors* (`chemcore/golden/anchors.json`): the constants and a carbonate chain at three waters, worked out at 50
  digits with mpmath (`chemcore/scripts/anchors_mpmath.py`, mpmath pinned by hash in `anchors.lock`, run once, never
  by the server) from the formulas typed from the papers, each paper's check value asserted first. Today's Python
  agrees to 1e-12.
- *The source platform* (owner amendment B1): its engine, copied unchanged from aquaculture_platform 352aa2a8 into a
  scratchpad harness and run under Node by `farm/tests/deffeyes_reference/b1/driver.ts`, on the golden's inputs; its
  outputs in `chemcore/golden/b1/source.json.gz` with their provenance; the noise floors declared before the
  comparison (`floors.toml`). `chemcore/scripts/b1_compare.py` and `farm/tests/test_b1.py` compare every output and
  intermediate, the chart point by point, and fail on any disagreement that `chemcore/findings/b1-registry.json` does
  not cover. The seven findings, each with its inputs, both values, cause and literature verdict, are in
  `chemcore/findings/B1.md` for the owner, with the note on fresh water's missing ionic strength (I2). To run the
  source again: the steps in the driver's header, then `b1_compare.py inputs`, the driver, and the test.

**Moving a function.** Its Rust port is written to the Python it replaces (the same operations in the same order,
`libm` for every transcendental, `chemcore/core/src/num.rs` failing exactly where CPython's `math` raised), tested
against golden v1 by class and against the anchors (`farm/tests/test_native_chemistry.py`), then switched: the Python
module keeps its names as a door (`from .native import ...`) and loses its bodies in the same commit, and
`farm/tests/test_one_formula.py` checks that a switched module holds no formula. From then on golden v1 is held by
class (`chemcore/scripts/golden_parity.py`), not bit for bit. Two deliberate differences from the Python it replaced:
a tie (an alkalinity on the floor or one ulp beside it) may be decided apart by two libms: such cases are listed by
`farm/tests/test_native_analysis.py` (one flips in golden v1: 10 °C, S 0, pH 9, one ulp above Python's floor); where
Python ran out of the box's 1-2-5 steps with a bare StopIteration the core raises `ChartTooLargeError`; an input that is not a finite number is refused (`native.NonFiniteError`, a ValueError) where Python sometimes
returned NaN, and nothing is cached (a water's constants take about 1 µs). After a change to `chemcore/`, rebuild the
image and run `chemcore/scripts/gen_expected.sh`; the browser guard's list is regenerated with
`gen_guard_list.py`.

**Retired (S10, 2026-11-09).** Every function has moved: `farm/tests/test_one_formula.py` RetirementTests holds the
five doors (`chemistry.py`, `deffeyes.py`, `dosing.py`, `charts.py`, `calculation.py`) to computing nothing, in a
function or at a module's top, but a reviewed list of what is not chemistry, each with why: the SVG scene in pixels
(`deffeyes.render`, `charts.draw` and their helpers; S8, the scene in the core, is deferred by the owner), a dose shown
in g/m³ or kg, the simulator's change shown, an input's accepted range. A new formula anywhere in a door fails it, and
so does a name a door gives that nothing outside the tests calls (the dead doors went: `charts.nh3_plot`, `h2s_plot`,
`carbonate_plot`, `saturation_plot`, which the tests now read as `charts.plots(analysis)[key]`; deffeyes'
`ISOLINE_PHS`, `LABELLED_PHS`, `OMEGA_SALINITY`; chemistry's `AIR_CO2`, `KELVIN`, `SOLVER_PH`). Left in Python on
purpose, outside the doors: `farm/water/read.py` works out a reading's NH₃-N and NH₄-N as the TAN times the core's NH₃
share, and the other oxygen unit as 100 × mg/L ÷ the core's solubility (and back), in Decimal at the parameter's
decimals. They are definitions over the core's chemistry, not a model, and `wip/fix-monitoring` rewrites that code
(the oxygen basis); moving them into the core would change Decimal into float arithmetic before quantising, so it is
a step of its own after that branch lands. The plan's differential run of 20 000 fresh waters against the Python
formulas was not made: the formulas were deleted function by function at each switch (S4 to S7), each switch held to
golden v1 by class, which the suite runs on every change (`farm/tests/test_golden.py`); the uncommitted tier 2 of the
golden was never made, so there is nothing to replace with snapshot hashes.

**No chemistry in the browser** (B2) is a test: `core/test_no_chemistry_in_browser.py` reads the deny-list
`chemcore/guard-list.txt` (the core's public names and coefficients, generated by `chemcore/scripts/gen_guard_list.py`
and never stale) and fails if anything shipped (frontend/, static/, a template's script, the calculator's pages as
rendered) holds an entry, a `.wasm` or a source map. `core/test_lean_endpoints.py` works out from the code which views
compute on values from the request and holds them to a reviewed list of four (the calculator's three pages and a
unit's chart), each refusing a user without its permission.

| Step | State |
|---|---|
| S0 spike (measurements, go) | done |
| S1 plumbing: workspace, image, gates, `native.py`, `core.E001` | done |
| S2 golden reference, anchors, browser guard, lean endpoints | done |
| S3 three-way cross-validation with the source platform: seven findings | done; all decided for ours (owner, B5) |
| S4 the constants, the equilibria, the solver, the gases: `farm/water/chemistry.py` is a door to the core | done |
| S5 the analysis (judge, analyse, the alkalinity floor, the box): deffeyes.py's analysis is a door to the core | done |
| A replay page's box worked out once (its largest DIC and alkalinity), not every point for every figure | done |
| S6 the chart in its own units (box, isolines, regions, borders, safe zone, Omega, dosing clipped): deffeyes.py's geometry is a door to the core; the notes are codes, farm/water/messages.py says them | done |
| S7 the dosing, the small charts, the simulator's judging: dosing.py, charts.py and calculation.judge_step are doors to the core | done |
| S9 (part) a replay page shares one diagram among frames equal but for pH, alkalinity and oxygen (proved invariant on random waters), its point left out (each frame carries its own); the page is sent gzipped | done |
| S8 the SVG scene in the core | deferred (owner direction, 2026-11-09): the scene stays Python (`deffeyes.render`, `charts.draw`), drawing from the core's figures |
| S9 the rest: the readings read per frame (`replay_window`) | done (see the measured table below) |
| S9 the rest: one batch call for a page's analyses and figures | open |
| S9 the rest: a binary encoding of the figures | not needed now: a real 60 s page is 0.4 to 0.76 MB gzipped, under the 2 MB at which it would be built (the plan's 400 KB target is passed at 60 s) |
| S10 the retirement audit: no formula left in a door (a test holds it), the dead doors gone, the docs | done; two definitions over the core's values stay in `farm/water/read.py` until `wip/fix-monitoring` lands (see Retired) |
| I2 fresh-water ionic strength (golden v3 beside v1, the owner sees it before any switch) | switched (owner, 2026-11-09): formula 3 with I1 (A of the temperature), the band from 1 to 5 ‰, the conductivity at 25 °C and the hardness as water parameters; the comparison for the owner is `chemcore/findings/I2-comparison.md` |

**The replay, measured** (development database, read only, 2000-frame pages on three units with live demo readings at
about 1 Hz). Distinct (temperature, salinity, TAN), and so figures, per page: 140 to 215 at a 1 s step, 219 to 362 at
5 s, 927 to 1 158 at 60 s; a figure takes about 1 to 3 ms in the core (21 to 23 ms in Python before). The readings
query (`replay_rows`) was the bottleneck at long steps: below an hour it read and sorted every raw reading of the page's
span. Since `replay_window` (2026-11-09) it reads at a step over 5 s one indexed reading per frame and channel. Measured
the same way, old and new code back to back on the same data (the machine shared with other test runs, so the
spread is wide):

| Step | Whole page, before | Whole page, after | Readings query, before | Readings query, after |
|---|---|---|---|---|
| 1 s | 2.0 to 3.5 s | 2.2 to 2.9 s | 0.3 to 0.7 s | 0.26 to 0.6 s |
| 5 s | 2.1 to 3.1 s | 2.4 to 3.1 s | 0.58 to 0.91 s | 0.59 to 0.83 s |
| 60 s | 8.7 to 12.5 s | 2.4 to 3.8 s | 6.7 to 9.6 s | 0.55 to 1.06 s |

These are warm figures (the database's pages in memory): a cross review read cold windows at 2.5 to 5.7 s for
1 600 to 1 800 look-ups, about 40 µs a look-up once warm. (On 2026-11-08, on a busier machine, the old 60 s page had
taken 44 to 62 s.) What is left of a 60 s page is, besides
the readings, the figures (0.6 to 1.3 s), the bindings read per input (0.4 to 0.5 s) and the 2000 analyses (0.2 to
0.5 s): the next levers are the one batch call of S9 and fewer binding queries. On a synthetic page (2000 frames, 54
temperatures) the figures take 131 ms and the page is 746 KB of JSON, 169 KB gzipped. Real pages as the endpoint sends
them (2026-11-09, the same three units): at 1 s 1.9 to 2.6 MB of JSON, 124 to 147 KB gzipped; at 5 s 2.7 to 4.1 MB, 149
to 204 KB; at 60 s 9.6 to 12 MB, 396 to 764 KB.

## Languages

English is the source language of every text in the code and templates; Norwegian bokmål (`nb`) and
Turkish (`tr`) are translations kept in `locale/<language>/LC_MESSAGES/django.po`. A visitor gets the
language of the cookie set by the switch, otherwise of the browser, otherwise English; a signed-in
person's choice is also saved on their account (`Profile`) and the admin can set it on the user form,
so an invitation email arrives in the new person's language, and the page its link opens is shown in it
(`core.views.SetPasswordView`). Numbers and dates follow the language
(`60,3913`); a date is shown and typed the European way in every language (`02.11.2026`, `02.11.2026 13:05`, owner rule). The activity log is stored in English and shown translated.

GNU gettext is not needed: `manage.py update_catalogs` and `manage.py compile_catalogs` (Babel) do
what `makemessages` and `compilemessages` do; they skip the system checks, so they run without the
database (the other commands' checks ask the database for its version, which a generated column needs:
`makemigrations` without a database needs `--skip-checks`). How to add a string or a language, the glossary and the
translations that need a native speaker's review are in [`docs/i18n.md`](docs/i18n.md).

## Look and themes

The console follows the Suderra Platform design system in [`docs/design/system/`](docs/design/system/README.md) (the
brand book) and its hand-off ([`HANDOFF.md`](docs/design/system/HANDOFF.md)). So far the shell and four Production
pages are drawn in it: the Overview, Meal board, Production units and Water chemistry; the other pages run on its tokens
without a redesign yet, and are redesigned one page at a time.

- **Tokens.** `static/css/tokens.css` is the design system's `tokens.css` plus a short block of the app's own (the
  rail's overlays), loaded first. **`docs/design/system/tokens.json` is the one source**: `scripts/tokens.mjs` builds
  both CSS files from it (`npm run build:tokens`, part of `npm run build`; `npm run check:tokens`, CI and `npm test`
  fail when either is not what it builds), and `core.tests_design_shell.TokenSourceTests` fails when the served file is
  not the design system's with only the app's block after it, or when the app's block sets a name the design system
  sets. Tokens v2 (2026-11-21) adds, in all five themes, the status roles `note` and `stale` (no hue: a note is told by
  its square, stale by a hatch), the area hues `area-farm`, `-water`, `-feed`, `-stock` and `-neutral` (each with a
  tint and a rail variant), `shadow-raised` (elevation 1) and the type scale as `--fs-*` variables, chart text included (`--fs-chart-*`: a
  chart drawn in a viewBox divides them by its own scale, so its labels keep their size on screen: a pH plot at every card width, the Deffeyes chart from a 768 px window to 5120 px, and below that its text shrinks with the window, 6 px at 390 px, see docs/design/system/README.md, Type) and
  chart colours that alias the status and area roles (`--chart-crit`, `--chart-water`, ...);
  `core/tests_contrast.py` measures every text pair (4.5:1) and shape (3:1) in every theme and keeps each area hue 30°
  from the status hues.
- **Colour, two channels.** The area hues say where a page sits (`area` on its menu line in `config/navigation.py`,
  the nearest of entry, group, section and panel; `core.navigation.area_of`): its rail icon and the chip before its
  page title. The status colours say what is wrong, and only that. They never mix (docs/design/system/README.md,
  Principles; this replaces "grey by default").
- **Width.** The shell never caps the width (the old 1520 px cap left a third of a 2560 px window empty): every page's
  content reaches the window's right edge, up to a 3840 × 2160 wall TV and the owner's 5120 × 1440 desk monitor (the farms' wall screens are standard 16:9 TVs; 5120 × 1440 is a desktop width). A page says how it uses the room
  with `data-measure` on `<main>` (block `measure` of `app_base.html`): `fluid` (the default), `wall`, `form`
  (`crud/form.html`: the fields flow into columns, none wider than a field needs, the sections an outline beside them
  from 1280 px) and `prose` (text blocks at 70 ch in as many columns as fit, an aside beside them). The browser layout
  test holds the right edge at nine widths from 390 to 5120 px, 1920 and 3840 (the wall TVs) among them.
- **Components and the gate.** `static/css/ds.css` holds one rule set per pattern (button, field, filter bar, table,
  tabs, badge, card, page head) on tokens only; the older class names of each pattern (`button`, `data-table`,
  `badge-*`, ...) are drawn by the same rule, so every page took the look at once. `npm run check:ds`
  (`scripts/check-ds.mjs`; CI and `npm test`) fails on a colour outside `tokens.css`, a raw size in `ds.css`, and on
  more raw font sizes, radii, old class names or arbitrary Tailwind sizes than `docs/design/system/ds-ratchet.json`
  allows; the ratchet only goes down. `ds.css` is linked right after `base.css` and `ui.css`, before `app.css`, `components.css`, a page's sheets and `tw.css`
  (also by the printed water report and `500.html`): a rule of a later sheet for one element of a pattern wins by coming later, and
  the gate fails on a template that links `base.css` without `ds.css` in that place (review of slice 1a: loaded after them, the rail's
  collapse button, the report's Print button and tables and a chip's size lost their rules, and the printed report, which did not link
  `ds.css` at all, lost its tables, buttons and cards). `frontend/test/cascade.browser.test.ts` holds, in a real browser, what the gate
  cannot see. Details: docs/design/system/README.md, Width, Components, The gate. `static/css/tw.css` does not hold the tokens (it
  names the variables), so it is built from neither. No stylesheet writes a colour of its own: `core/tests_design_shell.py` fails on a
  hex, `rgb()` or `rgba()` outside `tokens.css`. The old variables (`--mist`, `--olive`, `--stripe` and the rest) are
  gone; every sheet reads the role tokens (`--surface-*`, `--text-1` to `-3`, `--line-*`, `--primary`, `--action`,
  `--ok`, `--warn`, `--crit` with their `-text` and `-tint`).
- **Known gaps of the design system (slice 1a).** Not done or not seen, in full in docs/design/system/README.md (Known gaps):
  the `form` measure is not the plan's field column with a context aside (a form without tabs spreads over the width, and
  has no aside); the gate does not see `em` or `%` font sizes, single-quoted classes or old classes in `.py` and `.ts`
  files, and its ratchet is one count per class name; the contrast test reads six-digit hex only and does not check chart
  series or text on zone fills (`--text-3` on `--zone-safe` is 4.24 to 4.26:1 in Polarnatt and Nordlys); `.sensor-chart`
  keeps `max-width: 960px`; the Deffeyes chart's text is 6 to 11 px below a 768 px window; a Big card's chart text is 11.2 to
  14 px, not wall legibility (the wall slice); Safari and iOS, screen readers and a real wall TV were not tested.
- **Parts.** `static/css/ui.css` is the design system's `components.css` (the `ui-*` classes) with the app's additions
  at its end; the shell's layout is `app.css`.
- **Tailwind.** A redesigned page may be drawn with Tailwind v4 utilities beside the `ui-*` parts
  ([`tailwind.md`](docs/design/system/tailwind.md), "In this app"): every class carries the `tw:` prefix
  (`tw:grid tw:xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]`, `tw:coarse:min-h-12` for the 48 px tank-side targets), and
  the theme of `frontend/tailwind.css` names only the role tokens, so a utility follows the person's theme. The build is
  utilities only (no preflight, no default theme, no cascade layer) into `static/css/tw.css`, committed and loaded last by
  `app_base.html`; it styles nothing but an element that carries a `tw:` class, so the pages not redesigned are exactly as
  they were (`core/tests_tailwind.py`). `npm run build` writes it (`npm run build:css` alone); `npm run check:css` (CI,
  before the build, and `npm test`) fails when it is not what the source and the templates build now. Nothing is loaded
  from a CDN and nothing runs in the browser. A page whose own sheet styles the same elements (Monitoring: a card's frame)
  loads that sheet in `app_base.html`'s block `page_styles`, BEFORE `tw.css`, so a utility wins over the sheet's rule for
  the same class. The theme also holds a fitted monitoring card's type scale, four sizes in em of the card's own unit
  (`tw:text-u-s`, `-m`, `-l`, `-xl`: 0.8, 1, 1.25, 2.4), and the variant `tw:wall:` for a wall screen (`data-wall`); a test
  holds the monitoring templates to those four sizes and to two weights (`monitoring/tests/test_small.py`).
- **Overview** (`/production/`, `templates/production_home.html`). The panel's landing page at the start of a shift, a
  dashboard (the owner's decision over the design system's earlier "no KPI tile row"): the day's figures as metric cards
  (`templates/_metric_card.html`) on one sheet, five to a row from 768 px and two on a phone: fish, biomass, stocked units
  (of all units), feed today and over 7 days, critical water points and water points with a warning (of all sampling
  points), tasks due today, overdue tasks, reports due (with the overdue ones as a chip). Each card is the figure large
  with its label, one sub-line and its source and time ("Stock records at 15:35"), the whole card a link; grey unless
  abnormal (the 4 px status edge, glyph and word). Below, Needs attention in compact rows (what else is not "nothing needs attention", each from the read of the page
that owns it, so the two cannot disagree: the stocked units with no water value inside the Water page's 30 days, the
sites with fish that are not set up for reports, for which nothing can be known to be due, and the notices to file at
once, which have no deadline and so are never "overdue"; the head's chips, the Reports card and the Reports due panel
say the same, and the company's home page too: `farm/tests/test_overview_truth.py`; the water points with a
  critical or warning value measured at them, the critical first, at most six, each value on one line with its origin and
  age, a small History button; overdue tasks; overdue reports and duties) and beside it, from 1024 px, the farm as cards
  (production departments, systems, equipment, tanks, ponds and cages; the systems by status and the units by kind) and
  the reports due. Every figure the page showed before its redesign is a card
  (`farm/tests/test_production_overview.py`, OldFiguresTests). Read once by the areas' own functions
  (`farm.water.views.overview` reads the water page's rows, so the two never disagree); each part only for a person
  whose role reads its area. The one primary action is Record water sample, for a person who may record one.
- **Themes.** Fjord (the default), Polarnatt, Nordlys (for the monitoring wall), Tang and Laks, picked in the user menu
  beside the language. The choice is a cookie (`theme`, kept a year, `core/theme.py`) that the server writes on
  `<html data-theme>`, so the first paint has it; never the system's colour scheme.
- **Fonts.** Atkinson Hyperlegible Next (text) and Bricolage Grotesque (h1, h2, the wordmark) are served from
  `static/fonts/` (SIL OFL 1.1, THIRD_PARTY.md): no page asks another server for anything, and the console reads the
  same offline on site.
- **Shell.** The dark rail (240 px; 72 px of icons when collapsed, the toggle and its rule unchanged) with the logo disc
  and the SU/DERRA wordmark and the panel switch under them; the top bar with the breadcrumb, the EN / TR / NB switch
  and the user menu; the page head (h1, a line of status chips, the page's primary action). Below 1024 px the rail is a
  sheet and a bottom bar holds Meals, Water, Units and Storage (those the person's role opens; the Company panel shows
  its first pages) and More, which opens the sheet; the console keeps the bar's height free at its end, so a page's last
  line is never under the bar (the browser layout test checks it at 390 and 1023 px).
- **Rail order.** Daily work first: the overview, Operations (with Feeding, Harvest, Health), Research, Reports,
  Communication, Team; Setup last and folded (`Section(collapsed=True)` in `config/navigation.py`), open on its own
  pages and elsewhere as the person left it (`frontend/collapse.ts`, kept in the browser). In the collapsed rail a
  link's name stands beside it on hover and on focus. The foot says the company (`COMPANY_NAME` in the environment)
  and the site of the department the person is placed in today, or the farm's site when it has one (`hr.read.rail_foot`,
  `RAIL_FOOT`); "Fish farm" when neither is known.
- **Tables** on the three pages are real tables in a `ui-table-wrap` that scrolls inside itself, with the first column
  and the row actions sticky; each value is a value face (figure, origin and age), a missing figure says why or "no
  data", a status is a chip with glyph and word. Words wrap inside their columns, column heads too (a figure column's
  head as well; its figures stay on one line), and the meal board fits a 1440 px window with at least 24 px to spare (the
  browser layout test checks it on `frontend/test/pages/meal.html` in the product's own typefaces, so Windows and Linux
  Chrome measure alike); a wider table scrolls in its frame, its sticky columns shaded so a column passing under them
  reads as going on. Dates stay dd.mm.yyyy in every language.

## Browser code

There is no hand-written JavaScript. The browser code is TypeScript in `frontend/` (strict mode),
compiled by `npm run build` into `static/js/`, which is not committed:

- `nav-boot.ts` sets the rail state before the first paint and owns the open/collapsed rule;
- `shell.ts` the rail toggle, the rail as a sheet below 1024 px (opened from the bottom bar's More) and the popup menus;
- `components.ts` the shared parts every tab uses through data attributes: the dialog
  (`data-modal`), inner tabs, upper-case inputs, row lists and check boxes that need another one
  (`data-requires`, the role matrix), GET forms that leave empty fields out of the address
  (`data-omit-empty`, the database viewer's filters), choices and rows that belong to another field's
  value (`data-depends-on`; a choice cleared because it no longer fits is a change too, so a chain such as
  site → location → batch fits itself all the way down), fields that render the form again with what was
  entered (`data-refresh`, sent once per change however many fields it cleared),
  link lists with one primary mark (`data-links`), a print button (`data-print`), and a link to a field
  in a hidden tab opens the tab;
- `auth.ts` the show/hide password button;
- `poll.ts` the parts of a page the server renders again while it is in view (`data-poll`: the open
  conversation, the list of conversations, a menu entry's number), a GET form whose results the server
  draws again as it is filled in (`data-live`: its `data-live-part`s are swapped, its fields' errors put
  under them, the address kept in step; the water calculator), a list that follows new rows
  (`data-scroll-end`) and a text box sent with Enter (`data-submit-on-enter`). It is THE one polling
  implementation, and `watch(element)` is what other scripts import. Nothing is asked before every module script
  of the page has run (DOMContentLoaded): an element watched earlier waits, a `poll:now` sent to it meanwhile kept, so
  a script that listens (announce.ts) never misses the first answer whatever the scripts' order. Every request has a 20 s timeout, each
  wait a few per cent shorter or longer by chance (screens never line up), a failure doubles the wait up to
  a minute, nothing is asked while the page is hidden, one shared listener serves every element and an
  element that left the page is let go. The element carries `data-poll-state` (`live`, `stale` after two
  failures in a row, `gone` after a 401, 403, 404 or a redirect to sign-in, with a bubbling `poll:gone`
  event), so the page's CSS can say so in its own words (the script has no text). An element the server
  draws with `data-poll-state="loading"` holds only a placeholder (the monitoring shell): it is asked for at
  once (its request may take 35 s), it turns live when its first answer with something to show is in place (a
  merged element's: an element with the key), and before that a failure, a 204 or a 200 with nothing to show makes
  it `unread` at once (no last picture to keep; such an answer's next address is not followed), and it is asked
  again within 10 s whatever its interval; after the first answer the page goes to the element its `#fragment`
  names, when the answer brought it; the event `poll:now`
  asks at once (`detail.url`: the address from now on); `data-poll-merge="<attr>"` replaces a keyed child
  only when its markup differs, inserts a new key where the answer has it and drops a child the answer
  lacks (focus stays on the same id; an unkeyed child in the answer replaces everything);
  `data-poll-skip-same` leaves an answer equal to the last alone. Messages' append mode and the
  calculator's live form are unchanged, and pinned by `core/test_frontend_contract.py`, which also checks
  that every hook a template uses is one the script documents and reads.
- `wall.ts` the monitoring wall of fitted cards: the screen under the band cut into columns and rows of equal cells by
  the one slot rule (`wall/slots.ts`, pure, the twin of `monitoring/cards/slots.py`; both run
  `monitoring/tests/slot_vectors.json`), pages when the cards do not fit at a unit that can be read (PageDown, PageUp, the
  band's buttons, "2 / 3"; it opens on the page of the worst card), laid out again after a poll or a resize. It sets
  custom properties and attributes on the grid through the CSSOM (`--cols`, `--rows`, `--mh`, `data-page`),
  never on a card. A wall of cards that flow is left alone.
- `windows.ts` movable, non-modal windows (the monitoring cards' Deffeyes chart) and the full-screen button
  of a wall: `<button data-window="<url>" data-window-title>` opens the fragment in a `section[role=dialog]`
  made from the server-rendered `#monitor-window-template` (templates/monitoring/_windows.html, in the
  person's language) inside `#monitor-windows`, a sibling of the polled grid so a refresh never touches a
  window and a window shows in full screen. The title bar drags it (pointer events), the arrow keys move it
  16 px and Shift+arrows resize it, it comes forward when touched or focused, Escape closes it and returns
  the focus to its button, the same address is focused, never opened twice, and a link marked
  `data-window-load` loads in the same window. The body is polled through poll.ts (every 60 s, skipping an
  identical answer, stopping when the window closes; a 403 or 404 closes it). Each window's place is kept
  per device in `localStorage` (fractions of the screen, in a try/catch: losing it centres the window); below
  640 px a window is a sheet at the bottom of the screen. It never uses `<dialog>.showModal`, which would
  make the page inert and stop the wall. All the styles of the module, the wall (`?wall=1` puts
  `data-wall` on `<html>` through the `html_attrs` block of `app_base.html`: no rail, no top bar, no width
  limit) and the notices CSS prints from `data-poll-state`, are in `static/css/monitor.css`.
- `date-input.ts` the shared date box (`input[data-date-input="day|moment"]`, `core.widgets.DayInput` and `MomentInput`, every
  form's date by default): what is typed is put `dd.mm.yyyy` and `dd.mm.yyyy HH:MM` when the box is left, in every language
  (owner rule; `6.11.2026 9:19` becomes `06.11.2026 09:19`), before a filter's autosubmit reads it; what is not a date stays as
  typed for the server to refuse (docs/i18n.md).
- `announce.ts` what the monitoring wall says aloud: after each merge of the grid poll.ts sends `poll:merged` (what it replaced,
  inserted and removed); a card whose `data-state` got worse (ok, note, no recent data, warning, critical) is said in one of two
  live regions beside the grid (`#monitor-announce`, never inside the polled grid): a critical one assertively, the others
  politely, the first in full ("T-01 is now Critical.") and the rest as a count, at most one announcement per region in 5 s with
  the latest held for after. A first load, a better state, a card coming into view or going say nothing; so does the
  shell's first fill when it succeeds, while a failed first answer, the grid's or the pane's, says once, in the
  polite region, that the cards cannot be read (the placeholder's own words), and the grid's cards that come after it
  say "Updated again." there. The sentences and the state words are the page's (`data-announce-*`, `data-state-*`).
- `designer.ts` the card designer of Reference data › Card templates (the Design tab, `templates/monitoring/widgets/_designer.html`):
  it edits the form's own layout textarea (without script the layout is edited as text); a palette (click or Enter adds), a
  canvas of the 12 columns under the card's fixed frame band (select; drag to move, the corner handle to resize, one history
  entry per gesture; the arrow keys move, Shift and the arrow keys resize, Delete removes and selects the next, on the
  focused widget: `grid/keyboard.ts`), an inspector (column, row, width, height counted from 1, the water value and point,
  the widget's options from its descriptors), the reading order as links, undo, redo and revert (Ctrl+Z, Ctrl+Y), the
  problems the server's validator finds (each links its widget, a refused widget is marked), and the preview: the server's
  card for a unit chosen from the live units, optionally shown in a forced state, refreshed 400 ms after a change (a newer
  request aborts the older); it replaces only the preview pane, so the focus on the canvas stays. A change is announced in a
  polite live region from the `data-announce-*` sentences. Its browser test (`frontend/test/designer.browser.test.ts`)
  runs Playwright on the machine's own Chrome or Edge with a stub preview server (keyboard, drag, palette, inspector, the
  focus through a preview, axe-core finding no serious violation); it is skipped where there is no such browser.
- `grid/` the card designer's grid library, our own (no grid package): `layout.ts` pure functions over an immutable
  layout (`catalogueOf` reads the server's widget catalogue, `parse`/`serialize` a stored layout, `check` the geometry the
  server's validator also checks, `clamp`, `compact`, `move`, `resize`, `add`, `remove`, `readingOrder`, `changes`,
  `cellFromPoint`, `keyToDelta`), `history.ts` undo and redo (a gesture is one entry, 100 kept, a new entry clears redo),
  `types.ts`. A gesture places the moved, grown or dropped widget first, pushes what it lands on straight down and then
  compacts (floats every widget up as far as it goes, in reading order, stable on ties); compaction exists only here, the
  server never moves a widget. Nothing changes its input and garbage is a typed answer, never a throw. Its tests
  (`*.test.ts`, `frontend/test/random.ts`) are examples, the geometry vectors shared with the server and seeded
  properties over 2,000 random layouts and gestures each (mulberry32; a failure prints the seed, `GRID_SEED=<n> npm test`
  replays it): no overlap, in bounds and sizes, ids kept, compaction idempotent and never downwards, undo exact, round trip.

Asset URLs carry the file's modification time (`{% asset %}`, core/templatetags/assets.py) and the
compiled modules are reached through an import map (`{% module_map %}`), so a browser never shows a
page with new markup and an old stylesheet or script from its cache. `manage.py check` warns when
the compiled code is missing.

The browser code has no text of its own: the templates render the texts it shows into data
attributes (`data-label-show`, `data-forbidden`, ...), already translated.

### Islands (React, built by Vite)

A page whose body needs more than data attributes (the pilot of the frontend redesign:
`F:\dev\balik-notes\frontend-redesign\CONSENSUS.md`, `live-arch\PLAN-SPEED-FRONTEND.md` B4) draws it as an **island**: a React
root inside the server-rendered page. Django keeps the view, the shell, auth, CSRF, permissions, the menu, the languages,
validation and every chemistry judgement; the island draws the finished values it is given.

- **Source.** `frontend/islands/<name>.tsx` is one island; it calls `mount('<name>', Component)`. The one component
  library is `frontend/islands/ui/` (import from `./ui/index.js`): Button, LinkButton, IconButton, Chip, Plate and
  Plates, Tile and Tiles, Table, Tabs and LinkTabs, TextField, SelectField, CheckboxGroup, FixedField, ServerForm, Notice,
  EmptyState, LoadingState, ErrorState, ChartFrame, Icon, and SeriesChart (uPlot, imported on its own from
  `./ui/SeriesChart.js`: an interactive series, gaps never bridged, colours from the chart roles). They draw the design system's classes (`static/css/ds.css`):
  a server-rendered page writes the same classes, so both look the same from one rule set. React Aria where a control
  needs behaviour (buttons, tabs); native `<select>`, `<dialog>` otherwise (no popover that would lock the scroll).
  Icons come from `templates/icons/` (`scripts/icons.mjs` builds `ui/icon-shapes.ts`; `npm test` fails when it is stale).
- **Build.** `npm run build` runs `vite build` (`vite.config.mjs`, `scripts/islands.mjs`) into `static/islands/` (not
  committed): hashed names, no source maps, no inlined assets, no module-preload polyfill. There is **no dev server and
  no hot reload**: its injected scripts and styles would break the Content-Security-Policy. With no island yet the
  build writes an empty manifest.
- **On a page.** `{% load assets %}{% island "units" props label=_("Loading the units…") %}` writes the root (with
  `label` as its loading line), the props as a JSON data block (`json_script`: never run), and once per page the island's
  module, its chunks as `modulepreload` and every stylesheet they bring (at any depth), read from the build's manifest,
  `static/islands/manifest.json` (no dot-folder, so `collectstatic` copies it). **In production** it must be beside the
  islands it names: `STATIC_ROOT/islands/manifest.json` after `collectstatic` (read first when it is there), else the
  build's own; `manage.py check --deploy` fails (core.E007) when it is missing or cannot be read, and the plain check
  warns (core.W001). `settings.ISLANDS_MANIFEST` points elsewhere (the tests use `core/testdata/islands-manifest.json`). An unknown island
  raises; a missing build is core.W001. Props carry finished, translated values only; a form posts back to Django
  (`ServerForm` with the CSRF token from the props), whose errors come back as props and land on the fields.
- **Rules** (`npm run check:ds`): an island writes no colour, no `style=` or style object, no markup string
  (`dangerouslySetInnerHTML`), no old class name and no arbitrary Tailwind size. React Aria's one injected style rule
  ships in `ds.css` and `mount` puts its marker element in the head, so the page stays at 0 CSP violations.
- **Licences** (`npm run check:licences`, CI and `npm test`): every installed npm package is MIT, Apache-2.0, ISC,
  BSD-2/3-Clause or 0BSD, or a reviewed exception in `scripts/licence-gate.mjs` (THIRD_PARTY.md).
- **Tests.** `frontend/islands/ui/ui.test.tsx` renders each component to markup; `frontend/test/islands.browser.test.ts`
  mounts the component gallery (`frontend/test/gallery/`, `npm run build:gallery`, never shipped) under the product's
  policy in all six themes: 0 CSP violations, no critical or serious axe finding, every text at 4.5:1, visible focus, the
  busy and invalid states, no sideways scroll at 390 px (`SHOTS=<folder>` writes screenshots).
  `frontend/test/page.browser.test.ts` loads a whole server-printed page of the new look (`frontend/test/pages/shell-next.html`,
  `manage.py layout_pages`: the shell, its scripts, the strip and an island) under the server's own policy and nonce;
  `frontend/test/classic.browser.test.ts` holds the classic look as it was. The browser tests read the policy from
  `config/settings.py` (`frontend/test/csp.ts`). `core/tests_islands.py`
  holds the tag and the build checks.
- **Real pages in a browser.** An island page's props are made in the TEST database, through its real view, by a Django
  test (`core/island_props.py`: `render_island` asks the view in the new look and the language given, `keep` writes the
  props to `.build/island-props/`, never committed: the repository is public, so nothing recorded from a real database
  is kept). `farm/tests/test_island_pages.py` makes those of Tank › Water and Sensors › Charts from THE test world
  (`core/test_world.py`, shared with `scripts/record_test_world.py`, the clock at its `MOMENT`: TT-01's probe with an
  outage and a pH silent for two hours, the channels' state as the ingest writes it, samples, limits, an alarm, a harvest,
  a treatment and a feeding, each part a function of its own);
  `npm run test:pages` (`frontend/test/*.pages.ts`) then mounts the built islands on them under the product's policy
  (CSP, axe, 4.5:1, no sideways scroll at 1440 and 390 px). CI runs it in the Django job right after the suite (a run
  with labels makes the props too) and keeps its screenshots as the artifact `island-pages-shots`; missing props fail
  it, never skip it.
- **Notices.** `npm run build` writes `static/islands/THIRD_PARTY_NOTICES.txt` beside the bundles: the licence text of every
  package they may ship (package-lock.json, not dev), served with them.

### The new look (`?ui=next`)

The design console of 2026-11-23 (`F:\dev\balik-notes\design-in`; docs/design/system/README.md, The new look) is
previewed on every page behind `?ui=next`: `core/ui.py` keeps it in a cookie (`ui`) until `?ui=classic`, and
`app_base.html` writes `data-ui="next"` on `<html>`. The same markup is drawn square and hairline-framed with Barlow
headings (the `look` block of tokens.json, ds.css and app.css under `[data-ui="next"]`), with the status strip in the
top bar, the trail "Panel › Group › Page" from the menu registry (`core.navigation.page_place`; a page outside the menu keeps
its own eyebrow) and the menu group over the page title. The classic look stays the default until the owner switches,
on Fjord when no theme is chosen; the new look opens on Industry (`core/theme.py`). The user menu has "Back to the classic
look".

The status strip: what needs a look, the people on site (`hr.read.muster`) and the company's clock, each only for who may
see it.
- **What needs a look** is `alarms.read.attention(now=None, site=None)`, with `attention_all()` (the farm and every site from
  one reading, for a page that shows both) and `attention_by_site()`: the open alarms and every
  stocked unit on the monitoring cards' own ladder, rungs 1 to 4 (`monitoring.read.water_rungs`, which `_ladder` calls
  too): critical, warning, blind (an old or missing temperature or oxygen, no point at all, live values not read),
  unjudged (no limit for the fish). The strip says every count, none hidden behind another ("1 open alarm · 3 units
  critical · 2 units with no recent data"), and "No open alarms" only when nothing is open and every stocked unit is OK
  or a note. A unit whose water cannot be read is read on its own, as the engine reads it, and counted ("1 unit cannot be
  read"); the others still are. A farm-wide alarm (on no site) counts on every site, marked `farm_wide`. The reading is
  the same for every viewer and kept 15 s (`settings.ATTENTION_CACHE_SECONDS`): a farm's open pages ask the database once
  in that time. One reader for the strip, an overview's open-alarms figure and a site's count.
- **Polled whole** (`core:ui_strip`, every 30 s): the clock and the muster count never stand still beside a live alarm
  count. The page draws it with "Reading the alarms…" (the reader looks at every unit's water, so the page never waits
  for it). It is asked for only while it is drawn (`data-poll-if-shown`: it is hidden under 1100 px), and is marked "Not
  updated: the alarms cannot be read" after ONE failed answer (`data-poll-stale-after="1"`), never an old "No open alarms"
  unmarked. A rise of its alarms is said in a live region beside it (`frontend/strip.ts`; a critical one assertively), never
  the item every 30 s (`frontend/test/strip.browser.test.ts`).

Pages drawn by an island in the new look (the classic page is unchanged behind `?ui=classic`):

- **Company › Overview** (`/`, `templates/home_next.html`, island `company`, `frontend/islands/pages/Company.tsx`): the
  design's board. `config/company.py` reads each block by its area's own function (stock from the ledger, water from the
  Water page's own rows, alarms, the office board and muster, reports due, unread messages, feed on hand and cover, the
  latest log and knowledge entries), split per site from the same rows; `config/company_props.py` words it in the
  request's language. A block is left out for a person who may not read its area. The water chip per site says the
  sampling points' worst judgement (critical, warning, OK, or "Not measured"). The Open alarms tile and each site's
  Open alarms are the status strip's one reader, the farm and its sites from one reading of the water
  (`alarms.read.attention_all`): the figure counts open alarms (a site's holds the farm-wide ones too, and says how many
  of them are for the whole farm); the line under it counts stocked units on the monitoring cards' ladder, in the strip's
  words ("2 units critical", "1 unit with no recent data", "1 unit with no limit", "1 unit cannot be read"), so a
  critical unit shows before its alarm is raised (one wording, `core.ui.attention_said`, the strip's and the Overview's). The Open alarms plate says "No alarm is open." only when nothing needs a look (`Attention.quiet`); else it says the units' line. A site's water chip says a value of a sampling point, never a count, and never "OK" while the site's units are flagged: then it says their line. A page load reads the shared, cached reading the strip reads. Held
  to the classic page
  by `core.pagesays` in three languages (`farm/tests/test_company_overview.py`); its island is checked in a browser in
  every theme and language for CSP, axe and contrast (`frontend/test/company.browser.test.ts`).
- **The create, edit and delete page of every tab on the shared `crud/form.html`** (`core.crud.FormView.page`, `DeleteView`; `templates/crud/form_next.html`,
  `confirm_delete_next.html`; islands `record-form` and `confirm-delete`, `frontend/islands/pages/RecordForm.tsx` and
  `ConfirmDelete.tsx`): the same view, form and address; the island draws `core.formpayload`'s form with the library's
  form components (Field.tsx and FormParts.tsx: text, number, date and moment boxes tidied by `frontend/date-input.ts`,
  selects that follow another field and keep their groups' headings and switched-off options, box groups, radios, a
  single box, files with the stored one, the role matrix, link lists, the handling acknowledgement), the required fields
  unmarked and the
  others marked "optional", the server's errors on their fields and the tab that holds them open, a submit busy until
  the answer, the History tab and the delete link; the delete confirmation says the delete plan in the old page's words.
  `core/formprops.py` decides which forms the island draws (`drawable`: the shared crud/form.html, no question asked
  before a save (`question_template`: the withdrawal guard), no context of the page's own besides the tab to open, and
  every widget kind drawn; an unknown widget or several hidden values in one field keep the classic page, never an
  error); a tab with a form template of its own, and a request for a dialog, keep the classic page. Row lists (formsets,
  `RowList`, `core.formpayload.formset_payload`) are built and tested but not drawn yet: every tab with row lists has a
  form template of its own. A delete the plan blocks keeps its button off (`ServerForm` switches on only what it
  switched off). Held: the props say
  what the classic page says (`core/tests_formprops.py`, three languages); every field of every tab's form, new, refused
  and editing a record, its row lists' rows and the handling acknowledgement, posts what the old page posts
  (`frontend/islands/pages/RecordForm.test.tsx` against `frontend/test/pages/form-oracle.json`); the tabs, focus, busy
  state, CSP and axe in a browser (`frontend/test/recordform.browser.test.ts`). A help built with links travels as its
  words and its links to the application's own pages (`segments`, never markup); a stored file links to its own
  permission-checked view (a widget's `current_url`); a link is the application's own only as a plain path
  (`core.formpayload.own_path`: no scheme, host, backslash or control character). Every drawn tab, new and editing a
  record of the test world, is held to its classic page (`core/tests_formprops.py`, EveryDrawableTabTests). The browser
  tests run on props recorded from the test world; the Python tests (`unsaid`) are what link those props to the real
  pages. In CI (CI=1 or CI=true) a missing browser fails the browser tests instead of skipping them.
- **Every tab's list page** (`core.crud.ListView`; `templates/crud/list_next.html`, island `list-page`,
  `frontend/islands/ui/ListPage.tsx`, built once for every list): the same view reads the same rows; `core/listprops.py`
  words them: the search and the filters as one GET form (the server reads the address and is the only source of what is
  listed; a view or tab in the address is kept), the link tabs of the list's views with their counts, notices, the table
  (a cell's text, its link, sub-lines, chips) with each row's actions (a link, or a small POST with the page's CSRF
  token), the empty state (no records yet, or none matching with the way back), the pager keeping the search and the
  filters. Every word is the classic page's msgid. A tab opts in with `Resource.list_rows` (its columns and rows, built
  with `core.listprops` helpers; `listprops.title` and `edit_delete` give the usual name link and Edit and Delete) and
  `list_filters` (selects and day boxes from the values `filter_list` returns); a tab without `list_rows` keeps its
  classic list in the new look. A row's title and its actions open the record's own page (the record form island), never
  the classic dialog. Drawn now: the HR lists (Team, Departments, Attendance, Leave requests, Shifts, Holidays, Leave
  types), under both mounts. Held: `hr/tests/test_list_next.py` (each list against its classic page on the test world in
  three languages; the search, the filters and the pager are the address's); `frontend/islands/ui/ui.test.tsx` (the
  markup); `frontend/test/listpage.browser.test.ts` (the GET form sends what the server reads; CSP and axe in every theme
  at 1440 and 390) and `listpages.browser.test.ts` (every recorded list in three languages at both widths).
- **The browser tests' fixtures come from the test world, never from the development database.**
  `scripts/record_test_world.sh` starts a throwaway database (its own server and network, no host port, data in memory),
  migrates it and runs `scripts/record_test_world.py`, which refuses any other database, makes the test world (fixture
  names "Test …", addresses @example.com; `core/test_world.py`, one function per part: `company_world`, `hr_world`) in a
  transaction it rolls back, and writes `form-oracle.json`, `company-props-<language>.json` and
  `list-props-<language>.json`. `core/tests_fixture_privacy.py` fails on any e-mail address under `frontend/test`,
  `frontend/islands` and `core/testdata` outside example.com and the `.example` domains.

## One format for every tab

`core/crud.py` turns a `Resource` (model, form, labels, list template) into list, create, edit and
delete pages. Every tab gets the same behaviour from it: a role needs view/add/change/delete on the
model for each page (the platform admin has all of them), every change is written to the activity
log in the same transaction, an outdated `version` is refused, models with soft delete are hidden
rather than erased, and forms and confirmations open in a dialog (`templates/modal_base.html`) or,
opened directly, as a page. The menu is data (`config/navigation.py`: panels, main headings, groups,
entries) and shows each entry only to people allowed to read it; an entry can carry a number (a `Badge`, the
unread messages) that the page polls. Production's menu has two main headings, as in the platform: **Setup** (the farm's structure under Facility structure, the
reference lists the production side picks from under Reference data, and the suppliers under
Purchasing) and **Operations** (the daily
production records; it appears with its first tab), then **Reports** (Regulatory reports) and **Communication** (Messages). The source calls the reference lists "Records";
the prototype does not, because Operations holds the daily records. The menu is the one place that says
where a page sits: the role matrix and the small heading above a tab's title follow it
(`core.navigation.place`). There are no built-in roles: the platform admin creates roles
and grants permissions.

### Row scope: which records a person may reach

The role matrix says which verbs a person has; **`Resource.scoped(request, objects)`** says which rows. It is
the one hook, and by default it returns every row. A tab whose rows depend on a relationship (the HR area:
the people of the department a person manages) overrides it once, and the core applies it to the list (before
its search and filters), to every lookup of a record (the edit, delete, read and row-list pages) and to the
lock a save takes. A record outside the scope does not exist for the person: it is a 404 on every verb,
whatever the address or the query, and nothing is written or logged. Nothing else decides who may see a
record, so a rule is never written a second time.

The matrix has one more column for the same purpose, **Everyone** (`all`): offered by the one area whose rows
are scoped (HR's Employees), it includes no other right (it widens rows; Read is ticked on its own), and the scope function reads it as
"no limit". A tab's `private_fields` name form fields that hold a person's own words (a leave reason, a
punch's note): the activity log says "Private text" for a filled one and never stores the words, so it shows
that the field was set, replaced or cleared, not what it says (a short keyed digest of the text is kept so that
a replacement is a change the log shows). Two more columns widen HR's rows for production, each offered by one area: **All
production** (Employees: every production person) and **Crew** (Shift schedule: one's production colleagues' shifts). A tab can
also be served a second time under another address and panel (`Resource.mounts`, `core.crud.Mount`: HR's pages under Production ›
Team); the request carries the mount (`mount_of`), `scoped` narrows the rows to it, and the links, redirects and heading stay in it.
A tab can also refuse a verb on a record it reaches (`Resource.allowed`: HR
refuses editing, voiding and planning one's own attendance and plan).

### The delete plan

Records are soft-deleted, so the database's own `on_delete` never runs. `core/softdelete.py` reads
each link's `on_delete` instead and applies it to live records: `CASCADE` deletes the records that
point at it too, `SET_NULL` keeps them but clears the link, `PROTECT` blocks the delete. A model
adds conditions that are not links by overriding `delete_blockers()`. One plan serves the
confirmation, which lists what will be affected and disables the button when something blocks, and
the delete itself, which writes an activity-log row for every record it touches. `DO_NOTHING` keeps the
records as they are, still pointing at the deleted one: history that does not hold a delete back (a
unit's feeding records, as its stock lines), shown again when it is restored. A tab never writes
down what a delete does to its neighbours: it is whatever its links say. Records linked through a
many-to-many link (the equipment serving a system) keep their link rows; the confirmation lists them,
and the link counts again once the record is restored. Records whose link is `DO_NOTHING` (a unit's or a
system's water samples) stay as they are: their manager hides them while the record is deleted, the
confirmation counts them, and they come back with it. The confirmation counts each kept record once, however
many of its links point at what is deleted, and says what becomes of them (the model's `kept_note`: a task
stays in the lists, showing its place as deleted). Records that point at it through `DO_NOTHING` but are
only a plan go with it all the same: their model says which (`AuditedModel.deleted_with`, a recurring task's
planned tasks nobody touched).

**Lock order** (`core.softdelete`, LOCK ORDER): every write takes its locks on the farm's structure in one order, the
fish first (batches, then units: the stock operations and the withdrawal guard's `lock_fish`) and then the place going
up (production departments, then sites: a unit's save, `Tank._lock_place`). A delete locks what it takes along the
deepest first and the record last (`lock_along`), a restore the same, so a department deleted while one of its units
is saved waits for the save instead of deadlocking (merge review, finding 1). A cycle no write can foresee is still
failed by the database, whole: a deadlock or a serialization failure on a write comes back as "Someone else saved at
the same moment: nothing was saved. Send it again." on the page it was sent from (`CrossedWritesMiddleware`), never a
server error.

**Restoring** (the admin's action, `core.softdelete.restore`): a delete stamps every record it deletes with one
moment, so a restore brings back the record and what that delete took along (a site's production departments,
systems and equipment, a draft experiment's design, a recurring task's planned tasks: F-029, F-067), parents first,
each checked like a new one, all of it or nothing, one activity-log row each. A record deleted on its own before
stays deleted, and a link the delete cleared (`SET_NULL`) stays cleared: what it pointed at is not kept (F-036). The
record is locked, so two restores take turns, and a code taken by a record committed meanwhile is refused with its
reason, not a server error (F-003). The records a delete takes along were read for the plan, not locked, so it
writes only their deletion's columns, counting the version up in the database (`AuditedModel.mark_deleted`,
`detach`): an edit saved meanwhile is kept and its editor's outdated version refused (F-065, F-079, F-190). The delete
locks the records it takes along and takes each only as it still is: one moved to another parent meanwhile stays
there with what hangs under it, one deleted on its own meanwhile keeps its own moment (cross review F2). Deletes
made before this stamped each record with its own moment: restoring one of those brings back the record alone.

### Shared form parts

What one tab needed and the next ones will too lives in `core/`:

- `TabbedForm` (`core/crud.py`): inner tabs, fields grouped under a heading (`Fieldset`), a word per
  tab (`tab_help`), fields chosen once (`fixed_after_creation`; the department form opens its site again for a department a
  deleted site left without one) and fields that change the form itself
  (`refresh_on`: the form is posted with a `_draft` marker and rendered again from the values entered so
  far, nothing validated or saved; the values travel in the request body, never in the address; the
  marker names the field that changed and the form comes back on that field's tab). A form can drop
  fields for one record (a pond has no diameter): the tabs show the fields it kept.
  A unique constraint among live records, on fields or on an expression (a species' scientific name
  in any case, `Lower(...)`), is checked on the form by the constraint itself, with its message on
  the field; a clash only the database catches (two people saving at once) comes back the same way, on a new record
  and on an edit (F-034). An edit or a row list locks its record to save it, and one deleted meanwhile is not found
  (404, F-009). Every new-record form carries a hidden key, stored with the record it created in one table for every
  kind of record (`entry_keys`, `core.models.EntryKey`, F-232): the same form sent twice (a double click, a retried
  request, two at once) creates one record and the second sending opens it. The write paths of their own (a stock
  operation, a feeding, a treatment, a sea-lice count, a storage operation, a water sample, an experiment's copy) and
  the dialogs that write their own way (feeding assignments, a sensor's Move) keep and read their key in the same table
  (`EntryKey.note` / `record_of`, cross review F7): one mechanism. A key that already stands for a record of another
  kind (tampering, a broken client) is refused with a reason on the form, never a server error (F7c).
- `Output` (`core/widgets.py`): a value the form shows but nobody types (a unit's volume), on a
  disabled field so a posted value is never read.
- `core/formpayload.py`: a form as the JSON a new page's island draws (`?ui=next`). It is what Django's own renderer is
  handed for the old page (the bound field's label, help, required, errors; the widget's formatted value, attributes with
  the server's bounds, options), projected to JSON, so the server stays the only validator and the island posts the same
  names to the same address. Every widget of the project has a `kind` the island draws; another widget class, or a value
  that is not plain JSON, is refused, never guessed. Help text built with `format_html` travels as markup, any other as
  text. `core/tests_formpayload.py` builds every tab's form, new and sent empty, draws each field with the old field
  template and holds the payload to it: the same controls posted with the same values, the same label, help and errors.
  A whole new page is held to its old one by `core/pagesays.py`: every run of text, link address and control name of the
  old page's `<main>` must be carried by the new page's payload (`unsaid` names what is not), the two pages read side
  by side in one test on one fixture.
- `core/query.py`: the numbers and years a page reads from its address (`?page=`, `?before=`, `?year=`), one rule for
  every page (F-006, F-176, F-120): a number in ASCII digits within its bounds, a year of the calendar `core.dates`
  reads; anything else is taken as not given and the page shows its default, as for a stale link, never a server error.
  Days, moments and periods are `core.dates`' (`read_day`, `read_moment`, `read_period`); `core/tests_query_pages.py`
  asks every page with malformed values of both.
- A tab's page heading is what the menu calls it (`Resource.title`, from the menu entry), so
  "Tanks, ponds & cages" lists units.
- `Resource.search`: what the list's search box does; by default the text in one of `search_fields`, a
  full-text search where a tab needs one (the library, `knowledge/search.py`).
- `Resource.detail_template`: a read page for one record (`<prefix>/<id>/view/`, `templates/crud/detail.html`)
  for everyone who may read the tab, with Edit and Delete for those who may; the edit form needs the change
  permission, so a reader would otherwise see only the list (a library document, a knowledge entry).
- Files: a form with a file field gets the uploaded files and posts as multipart, in the dialog too (a
  document's PDF). A file is never served from a public address: a view that checks the permission sends it.
- `Resource.page_size`: the list is paged on the server, after the search and the filters, and the
  page links keep both (`templates/crud/_pager.html`). Lists that nest records (systems, equipment)
  stay on one page.
- `CodedMixin.name_field`: a record shown as "Name (CODE)" whose name is in another field (a
  species' common name).
- After a create the new record opens for editing only for a person who may edit it; a person whose role creates and
  does not edit (a worker filing a leave request) lands on the record's own page when the tab has one, else on the
  list, never on a refusal (`CreateView.created`, `hr/tests/test_after_create.py`).
- `RowList` (`core/crud.py`): rows a record owns, edited as one list on a tab and saved together,
  replacing the stored rows, logged on the record (a site's contacts, a feeder's calibrations, a feed's
  suitability). A refused list shows the record's edit page again from the list's address; the record's own form
  posts to the record's own address whatever address the page came from (`FormView.page` gives `form_action`, never
  "this page's address"), so "Save" after a refused list saves the record (`farm/tests/test_row_list_refused.py`). A record's contact persons are one shape for every record that has them
  (`farm/models/contact.py`, `farm/forms/contact.py`, `farm/resources/contact.py`,
  `templates/farm/_contacts.html`): a site's, a supplier's. Rows on an inner tab of their own with a
  heading row (a feeder's calibrations, a feed's suitability) are one template,
  `templates/crud/_row_list.html` with `crud/_row.html`; a class per list (`calibration-row`,
  `suitability-row`) gives its heading and its rows the same columns.
- `ChoiceArrayField` (`core/fields.py`): several choices of one list stored as a PostgreSQL array
  (what a supplier supplies), a check box per choice in the form, stored once each in the order of the
  choices; the activity log keeps each as its msgid and the database viewer shows the array as
  PostgreSQL prints it (`{feed,transport}`).
- `DependentSelect` (`core/widgets.py`) and `LinkList` (`core/links.py`): a choice, or a list of
  check boxes with the details of each link, that belongs to another field's value. A choice that belongs
  to none of its values (a production department without a site: `None` in `belongs_to`) belongs to
  `core.widgets.NONE`, the value the source field offers as "Without a site" (the list filters' value for
  "without one" too), so it can be chosen like any other.
- `Schema` and `SchemaValuesField` (`core/schema.py`): fields described by data (a type's technical
  specifications), the form fields and the check of the stored values from one definition.
- `TreeMixin` (`core/models.py`): records nested under records of the same kind, without loops.
- `next_code(model, prefix)` (`core/codes.py`): the next generated code of a kind of record (a batch's
  `B-2026-001`, an experiment's `E-2026-001`): one more than the highest number under the prefix, deleted
  records counted, so a number is never given twice; an advisory lock keyed on the table makes two creators
  take turns, so call it inside the saving transaction.
- `check.require_acknowledged(assessment, seen, field)` (`farm/handling/check.py`): a save with warnings
  is refused until the person has ticked the box for exactly the warnings as they are now; the stock forms'
  box is `handling_ack`, another form (an experiment's start) names its own.

### Shared page parts

The layout rules every page relies on are in the style sheets, once, and checked by tests (`core/tests_templates.py`
reads the templates and the style sheets; `frontend/test/layout.browser.test.ts` lays the parts out in a real browser at
390, 1024 and 1440 px (and the content's right edge at nine widths up to 5120 px, a 3840 px TV among them), in the typefaces of
`static/css/fonts.css`, not the machine's fallback font; `frontend/test/cascade.browser.test.ts` holds the cascade of the sheets,
in the order the templates link them: a page's rule for one element of a pattern wins, the focus ring shows, a phone's tab strip
shows the current tab, the charts' text size):

- **No page scrolls sideways.** A word longer than the line (a content hash) breaks (`.content`); a grid track is never a
  bare `1fr` (that is at least as wide as its widest content) but `minmax(0, …fr)`; a filter's fields, view tabs and a
  notice's list wrap; a screen-reader label (`.sr-only`) is pinned to its containing block's left edge, so one in a wide
  table never widens the page.
- **Every table is in a `.table-wrap`**, the frame that scrolls a wide table inside itself and shows a shade at the edge
  the table goes on past (none at an edge it ends at), so a table's last columns and its row actions are never out of
  view unseen. `.table-wrap-bare` is the frame without its border, in a card. A cell of words (a title over its lines)
  keeps at least 10 rem, so a table wider than its frame does not squeeze it to a word a line; on a phone the first
  column's lines wrap so the next column shows beside it. A row's actions (`td.row-actions`) stand apart.
- **A form's buttons** (`.form-actions`): the others first, then at most one filled button, the primary (or a danger
  button), last, on one row, each as wide as its words. A tab saved on its own (a row list such as a medicine's
  withdrawal, the history) shows only its own buttons: the record form's buttons show with its own fields.
- **Error pages** (`templates/403.html`, `404.html`, `500.html`): a refused or a missing page says what happened and offers
  the way back to the overview, in the dialog's frame when the dialog asked for the page (a stale row opened in it), in the
  console's shell for a person signed in (the menu stays) and on the sign-in page's for a visitor (`core.navigation.page_base`);
  a broken page is a page of its own that needs neither the person nor the database.
- **One rule for a mass** (`farm/templatetags/feeding.py` `amount`, behind the feeding's kilograms and the store's kg
  items): under a kilogram to the gram (0.035 kg), from a kilogram at most two decimals (251.8 kg, 1,420 kg), digits grouped
  as the language writes them; three decimals after the separator would read as a thousands group. Masses are still
  recorded to the gram. **Things counted** (an item in units: doses, bottles) are shown as recorded, to their three
  decimals (`exact`): never rounded.

### Restoring

A deleted record stays in the database. In `/admin/` (platform admin) every farm record type lists its
records including deleted ones, and the "Restore" action brings them back: refused when a record it
points at is deleted too (bring that back first) or its code was taken meanwhile, and logged. What its
delete took along comes back with it (see the delete plan: restoring). The admin edits nothing, and users and roles
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
7. **The data map**: a tab's table comes from the code; run `manage.py data_map` and commit
   `docs/data-map.md` and `.json`. Whatever the tab's form leaves out of the model is said in `<app>/screens.py`
   (Data map); `core.test_datamap` fails otherwise.
8. **Translatable text**: names, labels, help texts, choices and messages written with
   `gettext_lazy` / `{% trans %}`, `manage.py update_catalogs`, and the Turkish and Norwegian
   translations (`docs/i18n.md`); `TabTranslationTests` and the catalog tests in `core/test_catalogs.py`
   fail otherwise.

### Line endings

Every text file is LF (`.gitattributes`), so tools on any system produce the same file.

## Email

Two mails go out, both about a person's account and both by one path (`core/accountmail.py`): the **invitation** a
new person gets when the platform admin creates their account (and each time the admin sends it again), and the
**password reset** ("Forgot your password?" on the sign-in page). Nothing else sends mail (the alarms' transports are
their own, see Alarms).

- **The link** is Django's one-time link (`PasswordResetTokenGenerator`; the page behind it is Django's
  `PasswordResetConfirmView`, served as `core.views.SetPasswordView`): no token is stored and no token scheme is
  written here. The project's generator (`accountmail.tokens`) adds one thing to what Django signs, the account's
  `is_active`. A link stops working when the password is set (so it works once), when the person signs in, when the
  account's address changes, when the account is deactivated (an opened page too), and after `ACCOUNT_LINK_HOURS`
  (24): a day is long enough to open a mail the next morning, and a person whose link has expired asks for a new one
  themselves or the admin sends the invitation again. Sending again does not end an earlier link that is still in
  time; setting the password ends them all. An account made active again within a link's lifetime has that link back.
  A link that no longer works says so ("The link was already used or has expired") and offers "Request a new link"
  and the sign-in page. Setting the password does not sign in. Between opening the link and saving the password the
  token is in the person's session row, and the link's address is in the access log of whatever stands in front of
  Django: Django's design; the secure-cookie settings are still on the open deploy list for it.
- **The link starts with `PUBLIC_BASE_URL`**, never with the Host header of the request that caused the mail.
- **The text** is plain text (`templates/mail/`), in English, Norwegian bokmål and Turkish: in the language saved on
  the recipient's account (the admin chooses it on the user form), otherwise the language of whoever caused the mail.
  The invitation says who created the account; both say the username (it is what signs in), how long the link lives
  and, the invitation, where to ask for a new one. The set-password page, and the reasons it refuses a password for,
  are shown in the same saved language once the link has proved who it is for.
- **A password set through a link is logged** (activity log, action "Password set": by the person, when, the address
  the link went to) and shows on the person's row on Users: "Password set 10.11.2026 14:05 through an emailed link",
  and, when the account's address has been changed since, "through the link sent to wrong@…, which is not this
  account's address now". An invitation that went to a mistyped address and was used before the address was put
  right is seen there. There is no "take the password back" action: the right person uses "Forgot your password?"
  (the owner's decision if more is wanted).

### A mail leaves after the request, never in it

`core.AccountMail` (table `account_mails`) is the **outbox**. What causes a mail writes its row as waiting, inside
its own transaction (creating a user writes the user, the log row "Invited" and the mail's row together); the request
is answered; once that transaction has committed, the row is handed to **one worker thread per server process**
(`accountmail.worker`), which talks to the mail server outside any transaction and any lock and then writes on the
row when the mail went out (`sent_at`) or why it did not (`error`). The shared tab layer has the hook for it
(`Resource.after_commit`, called after a save's transaction, before the page is answered). So:

- no request waits for a mail server, and "Forgot your password?" does the same work and takes the same time for
  every address: the form hands the address over and nothing else; whether it has an account, the hourly limit, the
  row and the send are the worker's (measured with a mail server taking 0.6 s a mail: answers of 2 to 5 ms for an
  address nobody has and for one with an account; 610 to 690 ms for the latter before);
- a person's row is never locked while a mail server is talked to (a reset under way does not hold up their sign-in);
- a save that fails sends nothing, and no mail is out for a user that does not exist.

**One mail gets `EMAIL_TIMEOUT` seconds in all** (30), not for each step: the SMTP library's timeout is per step of
the conversation (connect, greeting, sender, recipient, data, ...), so the worker cuts the conversation off itself at
that limit and the mail counts as not sent ("The mail server did not finish in time: the mail may have gone out all
the same"). Only the opening of the
connection can add its own timeout once more.

**What the admin sees.** The answer to creating a user or to "Send invitation" says that the invitation is being
sent and that the person's row says whether it went out; the row says "is being sent" (no second send meanwhile),
then "Invitation sent …" or "Invitation not sent" with the reason and "Send invitation again". The mail server's own
words are on that row and in the database viewer (`account_mails`: the address, who asked, when, the reason; no
token, nothing masked), which only the platform admin opens; the activity log, which a role can be given, gets the
platform's own line after the admin's "Invited": "Not sent" with the kind of failure only (the error's class, or the
platform's own sentence). The platform's own sentences are shown in the reader's language. The server's log has a
line for every mail that did not go out (the kind and the row's id), with time and level (`LOGGING`,
`core.accountmail`, to stderr).

**The worker.** Two lines wait for it, each with room for 200 jobs: the mails the platform admin causes
(invitations) and the requests anybody can send (the forgot-password form). It takes the admin's first, so requests
from outside can neither crowd an invitation out nor make it wait behind them. It keeps its database connection from
one job to the next while jobs wait and closes it when none does: 200 lookups of addresses nobody has are emptied
in 0.2 s (about 900 a second; 42 a second while it opened a connection for each). It tries the kept connection before
each job and opens a new one when the database has dropped it meanwhile, so the job after a database restart is not
lost. **A full line is never silent.**
An invitation that finds its line full is marked not sent ("Too many mails are waiting to be sent") and the admin is
told. A reset request that finds the requests' line full is dropped: the person is answered like every other, and
the server's log says so once a minute with how many were dropped since the last line and since the process started
(the count an operator reads; `accountmail.worker.dropped`).

**Whose a waiting mail is, and what happens at a restart.** The lines are in memory, so a waiting mail can be sent
only by the server process that queued it. Its row names that process (`owner`), and the process keeps saying that
it still has the mail (`alive_at`, renewed at every job its worker starts, **for the mails the worker holds**: the
ones handed to it and not yet done, never everything that carries the process's name). A mail is called not sent only
when that is known, and it is then **written down**, once, on the row and in the logs ("The sending was interrupted: the server
stopped, or the mail server never answered", stored like any other reason):

- by the process itself, when it stops in order with mails still queued (`atexit`: the mails under way get
  `EMAIL_TIMEOUT`, what is left is closed);
- for a process that was killed, by the next look at the row once its owner has been silent for three times
  `EMAIL_TIMEOUT`: before the users tab is drawn, before an invitation is sent again or a reset is counted, and when
  a worker starts (a restart);
- the same way for **a mail whose job was lost while its process lives on** (the database failed when the job
  started, or when the outcome was to be written after the mail server had answered): the worker no longer holds
  it, so nobody renews it, and the next look after three times `EMAIL_TIMEOUT` closes it as interrupted. Such a mail
  **may have gone out**: the row cannot say, since writing it down is what failed.

Never by the row's age: a mail behind a slow mail server or a long line is "being sent" for as long as its owner has
it, and sending it again is refused meanwhile. **A mail can go out twice in two cases, both to the same person at
the same address**, and in both the first row stays "interrupted" though the mail went: the mail under way of an
owner that was silent past the lease without having stopped (a hung process, a paused machine), when the admin sends
again and the first send then completes after all; and a mail whose outcome could not be written (above), sent again
by the admin. Neither can be closed without the mail server's help. A mail still waiting in a line cannot: a row
closed as interrupted is skipped by an owner that gets to it after all. Nothing sends a lost mail again by itself: the admin sends the
invitation again from the row, and a person asks for their reset again (a lost reset does not count against their
hour). Two server processes each have their own worker and their own rows; neither closes the other's while it lives.

**Forgot your password** answers every address the same way (the same page, the same work in the request). One
account is sent at most `PASSWORD_RESET_MAILS_PER_HOUR` (3) reset mails an hour: the mails that went out or are
waiting count for the hour, one that failed for five minutes (a mail server that was down keeps nobody out for the
hour); the account's row is locked while its mails are counted, so two server processes cannot both read "none
yet". An account held back is one warning in the server's log an hour. The admin's "Send invitation again" is not
limited (it is the admin's, and logged). An invited person who has not set a password yet can ask for a link here
too. **There is no limit per client**: the reverse proxy in front of the server must limit
`/accounts/password_reset/` (for nginx, `limit_req`), or one script can send three mails an hour to every account.
A reset is not in the activity log (anyone can ask for one); its row is in `account_mails`.

**Where the mail goes** is the environment's alone; no address, user or password is in the repository. They are
deployment settings, not the platform owner's (a farm does not change its mail server or its link lifetime on a
page):

| Variable | What | Default |
|---|---|---|
| `EMAIL_HOST` | the SMTP server | none: a development server prints the mail in its terminal |
| `EMAIL_PORT` | its port | the encryption's own: 587 (starttls), 465 (ssl), 25 (off) |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | the account to sign in to the SMTP server with (both or neither) | no sign-in |
| `EMAIL_TLS` | `starttls`, `ssl` or `off` | `starttls` |
| `EMAIL_TIMEOUT` | seconds one mail may take in all (1 or more) | 30 |
| `DEFAULT_FROM_EMAIL` | the sender address | none (a development server: `webmaster@localhost`) |
| `PUBLIC_BASE_URL` | the address people open the console at, scheme and host only (`https://farm.example.no`) | a development server: `http://127.0.0.1:8047` |
| `ACCOUNT_LINK_HOURS` | how long an invitation's or a reset's link works (1 or more) | 24 |
| `PASSWORD_RESET_MAILS_PER_HOUR` | reset mails one account is sent in an hour (1 or more) | 3 |

A development server (`DJANGO_DEBUG` on, the default) without `EMAIL_HOST` uses Django's console backend: the mail is
printed in the `runserver` terminal, link and all. **With `DJANGO_DEBUG=0` there is no console to fall back on**: the
mailer is SMTP whatever the environment holds, and the system check `core.checks.mail_is_configured` stops `runserver`,
`migrate` and `check` with an Error when something is missing:

- `core.E002`: no SMTP server (`EMAIL_HOST`);
- `core.E003`: no sender address (`DEFAULT_FROM_EMAIL`), or not an address;
- `core.E004`: `PUBLIC_BASE_URL` not set, not `https://host[:port]` alone (a user part before the host is refused
  too), or a host this server does not answer to (`DJANGO_ALLOWED_HOSTS`; with `*` there every host passes);
- `core.E005`: an SMTP user without a password (or the other way round), or a password with `EMAIL_TLS=off`;
- `core.E006`: `ATOMIC_REQUESTS` on a database (whatever the mail settings): a mail would be handed to the worker
  inside the request's transaction, before the save that causes it is committed.

A development server pointed at a real SMTP server is held to E003 to E005 too, and every server to E006. The deploy check
(`CHECKS=1 scripts/test.sh`) runs with an SMTP server, a sender and a public address in its production-like settings,
so Django's `mail.E001` (a development-only mail backend) is closed and no longer in the list of open deploy issues.

### Starting a production server

Nothing in the repository starts a production server yet (no image, no entry point, no WSGI server in
`requirements.txt`), and a WSGI server does not run Django's system checks by itself. Whatever starts it must run,
in this order and stopping at the first failure:

```
python manage.py check --deploy --fail-level ERROR   # exits 1 on core.E001 (chemistry core), farm.E001, core.E002 to E005 (mail)
python manage.py migrate                             # runs the same checks first
python manage.py compile_catalogs
<the WSGI server> config.wsgi:application
```

with `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, the database variables and the mail variables
above in the environment. Should the server be started without the checks all the same and without its mail
settings, no mail is lost silently: every send fails ("The public address of this server is not set", or the mailer's
own refusal of a missing host) and shows on the person's row as any failed send. One worker thread per server
process sends the mails, so a server run as several processes sends several at a time. Nothing in the code ends that
thread; should it end all the same, the next job starts a new one, and a job queued while the old one was still
ending (alive, so no new one was started for it) is handed on by the ending thread itself (`Worker.run`): before,
it waited until some later job happened to start a worker. Two conditions on whatever
runs the server:

- **It must run Python threads.** The worker is a thread: a server that runs none (uWSGI without `enable-threads`)
  would queue every mail and send none; the rows would be closed as interrupted and nothing would ever arrive.
- **It should end its processes in order.** A process that exits normally sends what is under way and closes the
  rest itself (`atexit`). gunicorn turns SIGTERM into such an exit; a bare `runserver --noreload` in a container does
  not (SIGTERM kills it, as SIGKILL kills anything): what was queued is then lost, and its rows are closed as
  interrupted at the next look (see "Whose a waiting mail is").

### Known and accepted

- **A person who has an account can still learn, slowly, whether another address has one.** The one worker takes the
  requests in turn, so their own reset mail is built later when the request before it had a mail to send, and a mail
  says when it was built (`Date`, `Message-ID`). It needs an account of one's own, costs one of that account's three
  mails an hour for each address tried, and stops working for an address once it is held back. An outsider learns
  nothing: the answer and its time are the same for every address.
- **A mail the mail server took but acknowledged after the limit** is recorded as not sent ("The mail server did not
  finish in time: the mail may have gone out all the same"); sending it again can put a second one in the inbox.
- **The time limit reaches into Django's SMTP backend** (its `connection` and `_partial_connection` attributes) to
  cut a conversation. A Django that renames them, or another mail backend, is held by the per-step timeout only;
  `core.tests_account_mail.SendTimeTests` fails then, which is the alarm.
- **An account made active again within a link's lifetime has that link back** (the token is stateless; putting a
  wrong address right ends the link for good).
- **No limit per client** on "Forgot your password?": the reverse proxy's (above).
- **A mail can reach the same person twice**, at the same address, in the two cases of "Whose a waiting mail is" (the
  mail under way of an owner silent past the lease that completes after all; a mail whose outcome could not be
  written), when the admin sends again. The first row stays "interrupted" though the mail went.
- **A stranger's address** an invitation was mis-sent to stays in `account_mails` and in the log, as the evidence
  of where a link went, until the stranger asks: it is then erased from both by `manage.py erase_stranger_address`,
  on the data-protection officer's instruction (`docs/erasure.md`, step 8).

## Pages

| Path | Page |
|---|---|
| `/` | Company overview (sign-in required) |
| `/production/` | Production overview |
| `/sites/` | Facility › Sites |
| `/production-departments/` | Production departments |
| `/systems/` | Facility › Systems |
| `/equipment/` | Facility › Equipment; `<id>/calibrations/` saves a feeder's calibrations |
| `/tanks/` | Facility › Tanks, ponds & cages |
| `/species/` | Reference data › Species |
| `/feeds/` | Reference data › Feeds; `<id>/suitability/` saves the species and fish weights a feed suits |
| `/suppliers/` | Purchasing › Suppliers; `<id>/contacts/` saves a supplier's contact persons |
| `/operations/units/` | Operations › Production units; `?unit=<id>` opens a unit's drawer |
| `/monitoring-boards/` | Setup › Facility structure › Monitoring boards: the named wall screens, each with its Units tab |
| `/card-templates/`, `/card-templates/<id>/copy/` (POST), `/card-templates/preview/` (POST JSON) | Setup › Reference data › Card templates: the designer, Copy, the designer's preview |
| `/card-template-rules/` | Setup › Reference data › Card template rules |
| `/operations/monitoring/` | Operations › Monitoring: a live card per unit, drawn with its card template (`?mode=simple|detailed` picks a built-in for a page without a board); `?wall=1`, `?site=`, `?department=`, `?system=`, `?kind=`, `?occupancy=stocked\|empty\|all`, `?mode=detailed`, `?flip=<id,id>`, `?units=<id,id>`, `?q=`. The page is the shell (its cards come with the grid's first poll); `?full=1` draws them in the page |
| `/operations/monitoring/cards/` | The grid's children for the same address; `&after=<token>` answers 204 while nothing changed, `X-Poll-Next` is the next address |
| `/operations/units/new-batch/` | A new batch (`?unit=<id>` chooses the unit) |
| `/operations/units/<id>/<operation>/` | An operation on a unit's fish: `mortality`, `weighing`, `transfer`, `grading`, `cull`, `harvest` |
| `/operations/units/void/<id>/` | Voids a stock operation |
| `/operations/units/<id>/feeding/` | Records a feeding of a unit (`?next=` goes back to the page it came from) |
| `/operations/feeding/board/` | Operations › Feeding › Meal board |
| `/operations/feeding/` | Operations › Feeding › Records: the feeding records; `?view=days` by unit and day |
| `/operations/feeding/new/` | Record feeding from the list: the units with fish |
| `/operations/units/<id>/feeding/?meal=next` | Record meal from the Meal board: the next meal filled in |
| `/operations/feeding/protocols/` | Operations › Feeding › Protocols; `<id>/table/` saves a protocol's feeding table, `<id>/duplicate/` copies it |
| `/operations/feeding/assignments/` | Operations › Feeding › Assignments |
| `/operations/feeding/void/<id>/` | Voids a feeding |
| `/sampling-points/` | Setup › Facility structure › Sampling points: the points of the units, loops and equipment; `?unit=<id>`, `?system=<id>` or `?equipment=<id>` one owner's, filters by site, owner and kind |
| `/operations/water/` | Operations › Water chemistry: the latest water per point; `?view=history` the samples, `?unit=<id>`, `?system=<id>` or `?equipment=<id>` an owner's history (every point of it), `?point=<id>` one point's; `from`/`to` choose the days (a day that is no day is the default 30 days, a day is held to the last century up to today so 9999-12-31 is today; a span longer than 366 days starts later and says so; the samples are paged in the database and only the shown page is judged, F-019, F-176) |
| `/operations/water/calculator/` | Water chemistry › Calculator: the Water Quality Management Chart, the small charts, the results and the dosing of the water in the address (a GET form); `?point=tank:<id>` or `system:<id>` puts that unit's or loop's values in |
| `/operations/water/calculator/results/` | The calculator's live parts for the values in the address (what the page's script asks for) |
| `/operations/water/calculator/report/` | The calculator's printed report for the values in the address |
| `/operations/water/units/<id>/chart/` | A unit's own Water Quality Management Chart from one of its points' latest readings (`?point=`), or what is missing; a fragment |
| `/operations/water/record/` | Record a water sample (`?unit=<id>`, `?system=<id>` or `?equipment=<id>` offers that owner's points with its middle one chosen; `?point=<id>` names one) |
| `/operations/water/round/` | A water round: the middle points of the units and loops of a site, production department or system (`include=` adds other kinds of point, or the equipment's) |
| `/operations/water/void/<id>/` | Voids a water sample |
| `/operations/harvests/` | Operations › Harvest › Harvested: every harvest, the book against the scale, totals per batch and site |
| `/operations/harvest-plan/` | Operations › Harvest › Harvest plan: planned harvests and transports; `?unit=<id>` one unit's |
| `/operations/production-plans/` | Operations › Harvest › Production plans: the target weight per batch in stock |
| `/operations/units/<id>/harvest/?plan=<id>` | A harvest (or `transfer/`, a transfer) recorded from its plan; `next=` goes back to the plan |
| `/slaughter-facilities/` | Harvest and logistics › Slaughter facilities |
| `/handling-rules/` | Reference data › Handling rules |
| `/medicines/` | Reference data › Medicines |
| `/operations/health/treatments/` | Operations › Treatments; `new/` records one (`?unit=<id>` ticks a unit), `<id>/last-day/` changes its last day, `<id>/void/` voids it |
| `/operations/health/events/` | Operations › Health events; `<id>/void/` voids one |
| `/operations/health/lice/` | Operations › Sea-lice counts; `new/` records one (`?unit=<id>` chooses the unit), `<id>/void/` voids it |
| `/water-limits/` | Reference data › Water limits |
| `/storage-locations/` | Company › Facility › Storage locations; `<id>/reorder/` saves a location's reorder levels |
| `/operations/storage/` | Operations › Storage; `?tab=stock`, `movements` or `counts` |
| `/operations/storage/receive/`, `issue/`, `write-off/`, `return/`, `transfer/` | Receive a delivery; a lot leaving a location (`?location=<id>&lot=<id>` chooses it) |
| `/operations/storage/count/` | Count a location (`?location=<id>` chooses it) |
| `/operations/storage/void/<id>/` | Voids an operation of the store |
| `/operations/storage/items/<id>/`, `/operations/storage/lots/<id>/` | An item's day-by-day book (`?site=<id>`), a lot's trace |
| `/operations/tasks/` | Operations › Tasks: `?view=open` or `completed`, the filters, `?task=<id>` opens a task's drawer |
| `/operations/tasks/new/`, `/operations/tasks/<id>/`, `<id>/delete/`, `<id>/checklist/` | A new task (`?place=unit:<id>` starts at a place), edit, delete, save its checklist |
| `/operations/tasks/<id>/start/`, `complete/`, `cancel/`, `reopen/`, `checklist/<line>/`, `notes/` | Start, complete, cancel, reopen a task, tick a line, add a note (`?next=` goes back to the page) |
| `/operations/tasks/recurring/` | Operations › Recurring tasks; `new/`, `<id>/`, `<id>/delete/`, `<id>/checklist/` |
| `/research/experiments/` | Research › Experiments; `?view=mine` or `templates`, `new/`, `<id>/` the form, `<id>/view/` the read page, `<id>/design/` saves the design, `<id>/places/` places or randomises the tanks, `<id>/start/` the Start dialog, `<id>/copy/` the copy dialog, `<id>/release/<placement>/` and `<id>/replace/<placement>/` release or replace a tank of a running experiment, `<id>/team/` saves the team, `<id>/delete/` |
| `/reports/` | Production › Reports › Regulatory reports: a tab for every kind (`?kind=`) with where it stands for each site, what is due, the filed reports whose records changed, the reports and notices; `site=`, `status=` filter, `new/?kind=&site=&period=2026-W45` (or `&facility=`, `&health_event=`, `&escape=`) starts one |
| `/reports/<id>/view/`, `<id>/`, `<id>/delete/` | A report's page (the figures as filed, or as the records give them now, and the differences), its form, discarding a draft; `<id>/treatments/`, `resistance/`, `sensitivity/`, `units/` save the answers of its kind |
| `/reports/<id>/submit/`, `correct/`, `export.<csv or json>`, `print/` | Records the filing (POST); starts a correction (POST); the exports; the printable page |
| `/messages/` | Communication › Messages: the person's conversations |
| `/messages/<id>/` | A conversation (`?before=<message>`: the messages before one); `post/` sends, `new/?after=<message>` is its poll |
| `/messages/new/`, `/messages/new-channel/` | New message (a direct conversation), New channel |
| `/messages/<id>/members/` | A channel's members; `add/`, `<participant>/remove/`, `<participant>/role/` change them |
| `/messages/<id>/leave/`, `/messages/<id>/messages/<message>/delete/` | Leave a channel; delete one's own message |
| `/messages/list/`, `/messages/unread/` | Fragments the page polls: the list of conversations, the menu's unread number |
| `/knowledge/library/` | Knowledge › Library (`?q=` searches, `topic`, `species`, `year` filter) |
| `/knowledge/library/<id>/view/` | A document's read page (`?q=` shows the pages where the words are) |
| `/knowledge/library/<id>/file/` | A document's PDF, to people who may read the library (`?download` as an attachment) |
| `/knowledge/library/<id>/text/` | The text read from a document's PDF, page by page |
| `/knowledge/entries/` | Knowledge › Knowledge entries; `<id>/view/` an entry's read page |
| `/knowledge/entries/new/?document=<id>` | A new entry whose source is that document |
| `/knowledge/entries/<id>/review/` | Marks an entry reviewed, or takes it back to draft (POST) |
| `/activity/` | Activity log |
| `/administration/platform-settings/` | Administration › Platform settings (the platform owner's rules) |
| `/alarms/` | Alarms › Alarms (`?state=all` lists the cleared ones too); `<id>/` an alarm's history, `<id>/acknowledge/` (POST) |
| `/alarms/recipients/` | Alarms › Alarm recipients (who is notified of which alarms) |
| `/alarms/severity-rules/`, `/alarms/deadbands/` | Alarms › Alarm severity rules and Alarm deadbands (the alarm rules, the user's reference data) |
| `/administration/opening-balances/` | Administration › Opening balances; `new/` registers one (the platform owner's right) |
| `/roles/` | Administration › Roles (platform admin) |
| `/users/` | Administration › Users (platform admin); `<id>/invite/` sends a person their invitation (again; POST) |
| `/database/` | Administration › Database: every table (platform admin) |
| `/database/<table>/` | One table: Data and Structure tabs; `export.csv` below it downloads the filtered rows |
| `/language/` | Language switch (POST; sets the cookie and the account's language) |
| `/accounts/login/` | Sign in |
| `/accounts/logout/` | Sign out (POST) |
| `/accounts/password_reset/` | Forgot password |
| `/accounts/reset/<uid>/<token>/` | The link of an invitation or a reset mail: set the password (once, while the link lives) |
| `/accounts/password_change/` | Change password |
| `/admin/` | Django admin: deleted farm records, and restoring them (platform admin) |

## Layout of the code

| Path | Contents |
|---|---|
| `config/` | Settings, URLs, the overview view |
| `core/` | TimescaleDB extension, audit log (model, append-only trigger, `audit.py` helpers, activity page), roles and users (`resources.py`, `forms.py`), tests |
| `core/language.py`, `core/catalogs.py`, `locale/`, `config/formats/`, `docs/i18n.md` | Languages: which one a request gets, the catalogs without GNU gettext, the English date look, the guide and glossary |
| `core/access.py`, `config/access.py` | Access areas: what a role can be given (the permission matrix) |
| `core/accountmail.py`, `templates/mail/`, `core/checks.py` | The account e-mails, one path: the invitation and the password reset, the outbox they are sent from after the request (`account_mails`, the worker thread, the whole-mail time limit), the link's token, the reset limit, a person's standing on the users tab; the check that stops a server that could not send them (Email) |
| `farm/` | Farm module, one module per tab under `models/`, `forms/`, `resources/`; tests |
| `core/widgets.py`, `core/links.py` | `DependentSelect`: a choice that belongs to another field's value (a production department to its site); `Output`: a value shown, not typed; `LinkList`: check boxes for a record's links, with their details |
| `core/fields.py` | Model fields the tabs share: `ChoiceArrayField`, several choices stored as an array |
| `core/people.py` | People as the pages name and offer them: a person's name, and the active users who hold a permission (tasks' assignees, an experiment's team) |
| `core/codes.py` | The next generated code of a kind of record (a batch's, an experiment's), under an advisory lock |
| `core/schema.py` | Fields described by a schema (a type's specifications): the form fields and the check of stored values |
| `farm/equipment_types.py` | The equipment type catalogue, written into the database by migrations |
| `alarms/` | Alarms: the append-only rows (`models.py`), what raises them (`sources.py`), who is notified (`routing.py`), the write path (`services.py`), the loop (`engine.py`, `manage.py run_alarms`), the transports (`transports.py`), the pages (`views.py`) |
| `core/platform.py` | The platform owner's settings as the code reads them: the correction window and second approval |
| `farm/models/stock.py`, `farm/stock/` | The stock ledger: batches, operations and their lines; the fold (`fold.py`), reading it (`read.py`), the one write path (`services.py`), the integrity check (`integrity.py`, `manage.py check_stock`), the Production units page and dialogs (`views.py`, `farm/forms/stock.py`, `farm/templatetags/stock.py`) |
| `farm/models/feeding.py`, `farm/feeding/` | The feeding records: the walk of the feed along the stock's timeline (`fold.py`), reading it for the pages, FCR and the feed rate (`read.py`), the one write path (`services.py`), the Meal board, Records and the dialogs (`views.py`, `farm/forms/feeding.py`, `farm/templatetags/feeding.py`); the farm's dates shared with the stock (`farm/stock/dates.py`) |
| `farm/models/feeding_protocol.py`, `farm/feeding/` | Feeding protocols and assignments: the ration on read (`ration.py`), the estimated weight kept along the walk (`projection.py`), the temperature a ration reads (`temperature.py`), the table's write path and Duplicate (`protocols.py`), the assignments' rows and write path that the dialog and an experiment's start share (`assignments.py`); the tabs (`farm/resources/feeding_protocol.py`, `farm/forms/feeding_protocol.py`) |
| `farm/models/health.py`, `farm/health/`, `farm/handling/` | Fish health: medicines, treatments, health events, lice counts; the disease catalogue (`diseases.py`), the statutory lice rules (`lice.py`), the withdrawal worked out on read (`withdrawal.py`), the lice weeks and the records' days (`read.py`), the one write path (`services.py`), the pages and dialogs (`views.py`, `farm/forms/health.py`, `farm/resources/medicine.py`, `farm/resources/health_event.py`, `farm/templatetags/health.py`); the withdrawal registry the harvest side reads (`farm/handling/withdrawal.py`) |
| `farm/models/water_point.py`, `farm/water/points.py`, `farm/forms/water_point.py`, `farm/resources/water_point.py` | Sampling points: the model with its kinds, flow roles and rules, the default points and the share report, the form and the tab |
| `farm/models/water.py`, `farm/water/` | Water chemistry: samples and limits; the parameters (`parameters.py`), the chemistry worked out from a sample or the calculator (`chemistry.py`), judging on read (`evaluate.py`), the one read API of the samples: the latest values, the history, a unit's water and where its temperature is read from (`read.py`), the one write path (`services.py`), the Water Quality Management Chart (`deffeyes.py`), the small charts (`charts.py`), the dosing (`dosing.py`), the calculator's one calculation and a point's values for it (`calculation.py`), the page, the calculator and the dialogs (`views.py`, `farm/forms/water.py`, `farm/templatetags/water.py`) |
| `chemcore/`, `farm/water/native.py`, `docker/testrunner.Dockerfile` | The water-chemistry core in Rust (server only): the chemistry crate, the PyO3 module, the gates (`chemcore/scripts/test.sh`), the handshake file `chemcore/EXPECTED`; the one door Django calls it through; the image that builds it |
| `farm/models/harvest.py`, `farm/harvest/` | Harvest: slaughter facilities, a harvest's record, production plans and plan items; the Harvested list and its totals (`read.py`, `views.py`), the drawer's harvest part; the plan pages (`farm/resources/harvest_plan.py`, `farm/forms/harvest.py`) |
| `farm/models/handling.py`, `farm/handling/` | The handling check: the withdrawal registry (`withdrawal.py`), fasting, the purging in degree-days, when feeding must stop and the fasts plans ask for (`fasting.py`, `start_of_fast`, `fasting_on`), the check, the earliest suitable harvest date and the acknowledgement (`check.py`); the handling rules tab (`farm/forms/handling.py`, `farm/resources/handling_rule.py`) |
| `farm/placements.py` | The placement registry: the chip an app puts beside a unit (the experiments', on Production units, its drawer and the meal board); fails open |
| `farm/water/degree_days.py` | The batch's daily mean water temperature and the degree-days it adds up to (a past day without a measurement at the species' assumed temperature, else 0 °C; a day ahead projected): the one definition the medicine withdrawal and the purging fast share |
| `inventory/` | The store (its own app): storage locations, items, lots and the ledger (`models.py`), the fold (`fold.py`), reading it for the pages (`read.py`), the one write path (`services.py`), the integrity check (`integrity.py`, `manage.py check_inventory`), the location tab (`resources.py`), the page and dialogs (`views.py`, `forms.py`, `templatetags/inventory.py`, `templates/inventory/`) |
| `reports/` | Regulatory reports (its own app): the models (`models.py`), the kinds (`kinds.py`) and periods (`periods.py`), each report's computation from the records (`compute/`), the filing and corrections (`services.py`), what is due (`due.py`), the exports (`exports.py`), the check (`integrity.py`) and the provider the health records read (`health.py`) |
| `messaging/` | Messages: models (`models.py`), the one write path (`services.py`), the reads (`read.py`), the event a push or an AI assistant listens to (`events.py`), the pages and fragments (`views.py`, `templates/messaging/`, `static/css/messages.css`) |
| `tasks/` | Tasks and recurring tasks: models (`models.py`), the place as a choice (`places.py`), the one write path and the planned tasks (`services.py`), overdue and the views on read (`read.py`), the tabs (`resources.py`, `forms.py`), the drawer's actions and the overview tiles (`views.py`), `manage.py generate_tasks`, `templates/tasks/`, `static/css/tasks.css` |
| `experiments/` | Experiments (its own app, reading the farm): the design, the placements and the team (`models.py`), the endpoints (`variables.py`), the tab, its design view and its team list (`resources.py`, `forms.py`), what is wrong with a design (`design.py`), the seeded deal (`allocation.py`), the reads that every figure goes through and the deviations (`read.py`), the check of every started experiment (`integrity.py`, `manage.py check_experiments`), the write path of the design and the places (`services.py`), the constraints and composite keys (`migrations/0001_initial.py`), the triggers that freeze a started design (`migrations/0002_design_frozen.py`), `templates/experiments/`, tests, `docs/experiments.md` |
| `hr/` | Human resources (Company › HR, its own app): people, departments, placements, shifts, leave and attendance (`models/`), the rules and the scope (`rules.py`, `scope.py`, `roles.py`), the write path (`services.py`), the reads (`read.py`), what the database cannot hold (`checks.py`, `manage.py check_hr`), the tabs (`resources/`, `forms/`), `templates/hr/`, tests (README, Human resources) |
| `monitoring/` | Operations › Monitoring: the one card read and its state ladder with its words (`read.py`), the band above the cards (`read.band`), the card templates' catalogue, validator, resolution, drawing and the wall's slot rule (`cards/`, `cards/slots.py`), boards and templates (`models.py`, `resources.py`, `forms.py`), the page, the fragment and the designer's preview (`views.py`), `templates/monitoring/`, `static/css/monitor.css`, `frontend/poll.ts`, `frontend/announce.ts`, `frontend/designer.ts`, `frontend/windows.ts`, `frontend/wall.ts`, tests (README, Monitoring) |
| `sensors/` | The Sensors panel: devices, channels and their bindings (`models/`, `bindings.py`), the live water source the farm reads through `farm/water/sources.py` (`provider.py`, `read.py`), alarms and quality (`alarms.py`, `quality.py`), the charts and the trail (`chart.py`, `trail.py`), `sensors/CONTRACT.md`, tests (README, Sensors) |
| `sensors-ingest/` | The ingest service (Rust): reads the broker's sensor messages and writes the readings (`CONTRACT-REQUESTS.md`, `BENCH.md`) |
| `core/rev.py`, `core/operations.py`, `core/migrations/0014_rev.py`, `farm/migrations/0050_rev_triggers.py`, `sensors/migrations/0014_rev_triggers.py` | Revisions (`core_rev`): the triggers that move a revision per (scope, key) whenever an input of the water's judgement changes, the `TrackRev` migration operation, the presence check (core.W005), `manage.py core_rev_repair` and `manage.py core_rev_rebuild` (README, Revisions) |
| `core/checks.py`, `core/ranges.py`, `core/text.py` | The system checks run at start (the built catalogs and assets); periods as PostgreSQL compares them, for exclusion constraints; lower case in the person's language |
| `knowledge/` | Knowledge: the library's documents and their pages, the knowledge entries (`models/`), reading a PDF's text (`extraction.py`), the full-text search (`search.py`), the reference in APA form (`citation.py`), the file, text and review views (`views.py`), the tabs (`forms/`, `resources/`, `templates/knowledge/`) |
| `farm/species_catalog.py` | The species catalogue: fills the blank fields of a known species; data in code, no rows |
| `core/datamap.py`, `<app>/screens.py`, `core/test_datamap.py`, `docs/data-map.md`, `docs/data-map.json` | The data map: every table's screens, read from the code and the declarations; `manage.py data_map [--check]` |
| `core/database.py`, `config/database.py` | The database viewer's tables (from the models), their structure (from the database), sections, descriptions and masked columns |
| `core/dbgrid.py`, `core/dbview.py`, `templates/core/database/` | The viewer's grid (search, filters, sort, cells, export) and its three pages |
| `core/softdelete.py` | The delete plan: what deleting a record does to the records that point at it |
| `core/crud.py`, `templates/crud/`, `templates/modal_base.html`, `frontend/components.ts` | One format for every tab: list, form, delete, dialog, permissions, audit |
| `core/navigation.py`, `config/navigation.py`, `core/middleware.py` | The menu as data: panels (workspaces) with main headings, groups and entries, filtered by permission; the panel in use is remembered; where a page sits (`place`) for the role matrix and page headings |
| `farm/resources/`, `templates/farm/` | Farm tabs declared on top of `core.crud`; their URLs come from the registry |
| `core/admin.py` | The admin for farm records: shows deleted ones, restores them (checked like a new one), edits nothing; reference data (equipment types) is shown read-only |
| `static/css/components.css` | Shared page components (buttons, cards, tabs, form grids, audit trail), on the tokens |
| `static/css/tokens.css`, `static/css/ui.css`, `static/css/fonts.css`, `static/fonts/` | The design system (Look and themes): every colour, size and font as a token, the `ui-*` parts, the two self-hosted typefaces |
| `core/theme.py` | The theme cookie and the context processor that writes it on `<html data-theme>` |
| `templates/auth_base.html`, `templates/registration/` | Sign-in and password pages |
| `templates/app_base.html`, `templates/icons/` | Console shell (rail, top bar, user menu, page head, bottom bar), Lucide icons |
| `static/css/base.css` | Reset and form controls shared by every page, on the tokens |
| `static/css/auth.css` | Sign-in layout |
| `static/css/app.css` | Console shell layout |
| `frontend/`, `tsconfig.json`, `package.json` | Browser code in TypeScript |
| `tsconfig.test.json`, `scripts/mark-esm.mjs` | The TypeScript unit tests' build (`npm test`) |
| `scripts/test.sh`, `scripts/testrunner/` | The whole suite in Docker, in parallel, on a database server of its own (Tests); `in-container.sh` the checks and the run inside the container, deprecations as errors; `prune.sh` removes the test runner's old image tags |
| `config/test_runner.py`, `config/tests.py` | The test runner: the parallel suite, fast password hashing, warnings as errors (Tests) |
| `core/testing.py` | The tests' clock: `FrozenClock` holds `timezone.now()` at a class's `NOW`, so a test dated on fixed days does not read the day it runs on (Tests) |
| `.github/workflows/ci.yml`, `.github/dependabot.yml`, `sensors-ingest/rust-toolchain.toml`, `scripts/testrunner/image.sh` | CI, dependency updates and the ingest's pinned toolchain (CI and dependency updates) |

### Management commands

Every `manage.py` command of the project, and what kind it is. The product's commands and the developer's tools live in
the same folders (each app's `management/commands/`, beside its tests and the scripts that call them by name); this
table tells them apart, and `core/tests_commands.py` holds it against the code: a command missing here, or listed
under the wrong kind, fails.

- **product**: part of running a farm's server (a scheduled job, a set-up step, an operator's check). Changes nothing
  it should not; safe on a farm's database.
- **build**: makes or checks files of the repository (catalogs, the data map, generated CSS, the layout test's pages);
  no farm's data is read or written. Run by a developer and by CI.
- **dev**: made-up or development-only data: a demonstration seeder, a benchmark, a repair of the development seed.
  Each is built on `core.management.devtool.DevCommand`: **with `DEBUG` off it refuses to run** unless `--force` is
  given too (`seed_hr_demo` never runs with `DEBUG` off: it makes accounts with a known password). A developer's
  machine and the scripts' throwaway databases run with `DEBUG` on (the default) and are not asked. **The guard judges
  the process, not the database**: a process started with `DEBUG` on and pointed at a farm's database is not stopped by
  it (each of these commands still has its own check: a confirmed database name, a flag, the seed's marker).

| Command | App | Kind | What it does | Who runs it |
|---|---|---|---|---|
| `run_alarms` | alarms | product | One pass of the alarms, or one every `--loop` seconds: opens, clears, notifies, escalates, sends | The deployment, as its loop (Alarms) |
| `check_sensors` | sensors | product | The sensor alarm rules once, or every `--loop` seconds | An operator; the deployment runs `run_alarms` instead, which checks these too |
| `generate_tasks` | tasks | product | Makes the planned tasks of every active recurring task | A cron job (the Tasks pages do the same before they read) |
| `sensors_housekeeping` | sensors | product | Deletes the dead letters last seen more than 90 days ago | A daily job |
| `sensor_broker_sync` | sensors | product | Writes the MQTT broker's passwd and acl files from the sensors configuration | An operator, after the sensors configuration changed (the broker reloads the files) |
| `sensors_ingest_role` | sensors | product | Lets the ingest's database role sign in with the password in a file, or stops it | An operator, at set-up |
| `hr_roles` | hr | product | Creates the Production manager and Production worker roles when missing | An operator, at set-up |
| `private_log_values` | core | product | The conversion of migration `core/0011` again: plain values under private labels in the activity log made private (`--dry-run`) | The database administrator (docs/erasure.md) |
| `erase_stranger_address` | core | product | Erases, on the data-protection officer's instruction, an address an invitation was mis-sent to: in `account_mails` and in the activity log's rows of the account (a dry run unless `--apply`; it checks only that no account has the address now) | The database administrator (docs/erasure.md, step 8) |
| `core_rev_rebuild` | core | product | Moves every revision of `core_rev` past every stored figure's stamp and sets the floor for keys seen later, so every stored figure is built again; names a missing or disabled revision trigger | The database administrator, after a restore, a load with the triggers off or a session in replica mode (Revisions) |
| `core_rev_repair` | core | product | Makes the missing, disabled or replica-only revision triggers (core.W005) again as their migrations made them, then rebuilds every revision; does nothing when none is missing | The database administrator, on core.W005 (Revisions) |
| `check_stock` | farm | product | Folds the stock ledger from its first line and reports every broken rule; changes nothing | An operator |
| `rederive_ph` | farm | product | Puts the stored samples' pH measured on the total, seawater or free scale on the NBS scale again by the application's formula, from what was measured, each change logged with its old value (`--dry-run` reads only; check farm.W001) | The database administrator, at a formula change after the backup (Water chemistry, formula 4) |
| `check_withdrawal` | farm | product | The withdrawals holding fish today, and harvests and live deliveries recorded inside one; changes nothing | An operator |
| `check_inventory` | inventory | product | Every rule of the store from scratch; changes nothing | An operator |
| `check_reports` | reports | product | Every report against its frozen content and its key; changes nothing | An operator |
| `check_experiments` | experiments | product | Every started experiment against the rules the database cannot hold; changes nothing | An operator |
| `check_hr` | hr | product | What disagrees in the HR records; changes nothing | An operator |
| `compile_catalogs` | core | build | Builds the `.mo` files from the `.po` files (Babel) | Landing, CI, the tests |
| `update_catalogs` | core | build | Updates `locale/*/django.po` from the code and the templates | A developer after changing text; CI checks it changed nothing |
| `data_map` | core | build | Writes `docs/data-map.md` and `.json` (`--check`) | A developer after changing models; CI |
| `layout_pages` | core | build | Writes `frontend/test/pages` from the real templates (`--check`) | A developer after changing those templates; the suite checks |
| `card_grid_css` | monitoring | build | Writes `static/css/card-grid.css` from the widget catalogue (`--check`) | A developer after changing the catalogue; the suite checks |
| `seed_hr_demo` | hr | dev | A small demonstration company in the HR area, with sign-ins of a known password | A developer, for a walk-through (never with `DEBUG` off) |
| `sensors_demo_setup` | sensors | dev | Makes (`--confirm`) or removes (`--remove`) the live demo's sensors for the tanks and systems a database has | A developer; `sensors-ingest/simulator/farm-check.sh` |
| `bench_sensors` | sensors | dev | Writes synthetic readings into a database named on the command line and prints storage and read figures | A developer, on a copy or a test database (Sensors, Measured figures) |
| `fix_seed_size_mix` | farm | dev | Separates the batches of very different sizes the development seed stocked together (Production, the development seed's mixed cages) | A developer, once per database restored from a dump older than it |

`fix_seed_size_mix` is a finished one-off on a database it has run on (run again it does nothing), and is kept: every
development dump taken before it holds the mixed cages, and a restore of one needs it again.

## Tests

The whole suite, as every agent and developer runs it (Git Bash, or any POSIX shell with Docker):

```
scripts/test.sh                          # the whole suite, 6 worker processes in parallel
scripts/test.sh farm.tests.test_stock    # only these labels; any `manage.py test` argument passes through
WORKERS=1 scripts/test.sh                # one process, without --parallel
```

`scripts/test.sh` starts a PostgreSQL server for the run alone (the development database's image,
`timescale/timescaledb:2.17.2-pg17`, in a container `balik-test-db-<run>` on a network of its own, no host port, its data in
memory), runs `manage.py compile_catalogs` and `manage.py test --noinput --parallel $WORKERS` in the test runner's
image, stage `tests` of `docker/testrunner.Dockerfile` (the hashed requirements, the water-chemistry core built from the
checkout and `tblib`; `scripts/testrunner/image.sh` defines it, its Dockerfile, stage, context and a tag hashed from
everything it is built from, and builds it when missing; CI builds it by the same script. Of `docker/` and `chemcore/`
the tag is hashed from the files git tracks, so what a run leaves in a tree, a `__pycache__` beside chemcore's scripts
or `chemcore/target/`, is not in the image's name, and a worktree that has run its tests asks for the same tag as a
clean checkout), and removes the
server and the network at the end (`KEEP_DB=1` keeps them): on every way out of the script, a pass, a failure, a step
that could not start, Ctrl-C, a TERM or HUP signal (the tests' container runs behind a `wait`, so a signal is answered at
once), with any anonymous volume of the containers (`docker rm -f -v`; the server's data is a tmpfs in the place of the
image's volume, so a run leaves no volume). Only a script killed outright (SIGKILL, its console closed) cleans nothing:
remove its `balik-test-db-<run>`, `balik-test-run-<run>` and network `balik-test-<run>` by name. **The old images are
`scripts/testrunner/prune.sh`'s**: every change to the requirements, `docker/` or `chemcore/` builds a new
`balik-testrunner-chemcore:req-<hash>` tag (some 400 MB), and nothing removed the old ones. The script removes every
`req-*` tag except the tag of its own tree (always) and of every live git worktree of the repository (each tree's own
`image.sh` says it), a tag whose image a container uses, and a tag made within the last 24 hours; it says what it
removed and what it kept and why, `--dry-run` removes nothing, and it touches no other image, no container, no volume
and no network. Where git cannot list the worktrees (a copy that is no checkout) it stops with a message and removes
nothing: it cannot know there which tags the worktrees ask for. So a run never touches the development database `balik`, its
server or its volume, never shares test databases, roles or the shared server's 100 connections with another run, and needs
no `DB_TEST_NAME`. There is no serial-only group: every test runs in the parallel run. Why the run is shaped so:

- **Its own server, with TimescaleDB's job scheduler off** (`timescaledb.max_background_workers=0`). Each worker gets a copy
  of the test database, and PostgreSQL copies a database only while nobody is connected to it; the scheduler keeps a
  connection open to every database with the extension, so on the development server the copy fails ("source database is
  being accessed by other users"). No test needs the scheduler: the tests of the jobs run them (`CALL run_job`), so no job
  runs behind a test's back either. `manage.py test --parallel` on a server running the scheduler stops before it makes
  anything and names this script (`config/test_runner.py`). Its data lives only as long as the run, so `fsync`,
  `synchronous_commit` and `full_page_writes` are off; `max_connections` is 200, one connection per worker and the few a
  test opens itself.
- **A worker's failure is reported, not the run stopped**: without `tblib` a failing test's traceback cannot be sent from its
  worker and the whole run ends at the first error.
- **The catalogs are built in one step** (`core.catalogs.compile`): each worker builds them (the language tests'
  `setUpModule`), and a worker loading a `.mo` file another one was rewriting read it half-written. The new file is written
  beside the old one and replaces it, and a file that would not change is left alone.
- **A request's language ends with the request** (`core.language.end_request_language` on `request_finished`): a test
  client's request left its language active in the thread, and tests after it in the same worker read Norwegian or Turkish.
- **A TransactionTestCase's tests are handed out one by one** (`config.test_runner.TestByTestParallelSuite`): they share
  nothing, and the migration tests take minutes each (each migrates the schema back and forth), so a class of them no
  longer keeps one worker busy long after the rest. They still come after every TestCase, as Django orders them, so no
  TestCase meets a database one of them has emptied.

**Measured** (2026-11-07 and 08, commit e8d5162, this development machine: 12 CPUs, 31 GB for Docker, other agents' suites running at the same
time, so the times move with the load; 2828 tests):

| How | Time |
|---|---|
| Before: `manage.py test` in Docker on the shared development server, one process (the agents' logs of 2026-11-06/07, about 2790 tests) | 5677 to 8685 s (1.6 to 2.4 h) |
| `WORKERS=1 scripts/test.sh` (own server, one process) | 4661 s (1.3 h; 2828 tests, 3 skipped) |
| `scripts/test.sh` with 4 workers, before the last two fixes above | 2362 s |
| `WORKERS=8 scripts/test.sh` | 1338 s |
| `scripts/test.sh` (6 workers), three runs in a row | 1118 s, 957 s, 768 s (2828 tests, 3 skipped, each) |

The parallel and the serial run pass the same tests (2828, 3 skipped by both: the two TypeScript tests, without Node in the
image, and the load check, which runs with `MONITOR_LOAD=1`). More workers than 8 did not help on this machine (12 workers: 2116 s under load): the test database and the workers
share the same CPUs, and half of all test time is the migration tests.

Without Docker the suite still runs on the development server, one process:

```
.venv\Scripts\python.exe manage.py test
```

Tests build the catalogs first and hash passwords quickly (`config/test_runner.py`); the TypeScript is
type-checked by a test when Node and `npm install` are there, and its unit tests run by another (`npm test`: `tsconfig.test.json`
builds `frontend/` with its `*.test.ts` and `frontend/test/` into `.build/test`, not committed, `scripts/mark-esm.mjs` marks it
as ES modules and `node --test` runs it; without Node the test is skipped, under `CI=1` it fails). The browser build
(`tsconfig.json`) leaves the tests out, and the no-UI-text rule reads every folder of `frontend/` but the tests. The
development-only tools and their licences are in [`THIRD_PARTY.md`](THIRD_PARTY.md); none of them is shipped to the browser. Run so, the tests need the database container running (they check the timescaledb extension too); set
`DB_TEST_NAME` to give a checkout its own test database when two such runs overlap.

**Warnings are errors.** In every test run a `DeprecationWarning`, a `PendingDeprecationWarning` (so every Django
`RemovedInDjango*Warning`) and Django's "received a naive datetime" `RuntimeWarning` fail the test that raised them, in every
worker (`config.test_runner.strict_warnings`; its tests are `config/tests.py`). They fail wherever they are raised, so a
warning a library attributes to its own frame while our call caused it fails too; a library's warning about its own
internals goes, with its reason, in `THIRD_PARTY_WARNINGS` beside it, where it is reported but does not fail (the list is
empty: the whole suite raises none). `scripts/test.sh` also runs every command with deprecations as errors from the first
import (`scripts/testrunner/in-container.sh`), which catches one raised while the models are imported, before the runner
starts; a plain `manage.py test` has the runner's filters only.

**A test does not read the day it runs on.** A test whose records are dated on fixed days holds the clock
(`core.testing.FrozenClock`, mixed in before the TestCase with `NOW`: `django.utils.timezone.now`, the one clock the code
reads, stands at that moment for the class's data and every test of it). Otherwise the rules that count from today (a
record dated at most the correction window back, nothing in the future, a freshness) fail the test by the calendar:
`sensors/tests/test_replay.py`, dated 10.10.2026 with a sample of the day before, failed from 10.11.2026 on (31 days).
The dates stay as written and the clock is held, rather than the dates moved with the run's day, wherever the data is
tied to its dates (seeded readings, whole hours, an address's `2026-10-10T00:05`). The database's own `now()` is not held,
nor a model field's `default=timezone.now` (it keeps the real function it was given). Where the records must be made
one after the other (the newest report, a history in order), `core.testing.StartedClock` starts the clock at `NOW` and
lets it run on. Held so since the sweep below: the reports' tests (`reports.tests.helpers.ReportTestCase`, dated in
October and November 2026: the deadline of a week's planned slaughter is expected from the day its plans' rows are
made, and failed from 12.11.2026 on; the overdue driftsplan of 2026 failed once a later year's is owed) and HR's leave
tests (a request of 01.06.2027 stands for "not begun yet"). **A date can also spell a value**, and no sweep by
clock looks for that: `monitoring.tests.test_pages` asserted that the oxygen value "8.10" was nowhere on a page that
also says when the fish were last weighed, 15 days back, and failed on 12.11.2026 for "28.10.2026" alone (it would
again on every day whose date 15 days back ends in 8.10). A test that asserts a number is absent from a whole page
uses a number no date can spell, and first shows that the page prints it for someone who may see it.

**Nor on how soon the database lets go of a connection.** PostgreSQL lists a connection (`pg_stat_activity`) until its
server process has ended, which follows the client's close in the server's own time (2 to 22 ms measured alone, up to
64 ms beside other runs), and it lists its own autovacuum workers beside the clients. The mail worker's test asked "as
many connections as before" of that list at once and failed in a whole suite under load (12.11.2026) and in 1 of 20
runs alone; the worker had closed its connection every time. A test that asks the database whether a connection is
gone asks for the clients' connections by their process id, those that were not there before, and waits for the
answer with a bound; what the code under test has done itself (closed its connection) it asks of that connection.

**Nor on how fast another thread is.** The mail worker's tests (`core/tests_account_mail_worker.py`) wait for a
thread, an event, a lock or the worker at rest. Each waits for that condition itself, up to one generous bound
(`WAIT`, 60 s), and fails saying what it waited for: `rested`, `reached`, `ended`, `until`. None sleeps a time that
"should be enough" and goes on (a second "until both are at the row", a join of 20 s whose outcome nobody read: the
whole suite of 13.11.2026 failed on that one, under load), and none measures seconds of the clock where it means
work: 200 lookups "in a moment" are measured against the same 200 done at once on the same machine, the mail's time
limit against how far the conversation with the test's mail server got. What must not happen is asked the other way
round, with a short time (`drain(0.5)` is false while a mail is at the mail server). The platform's own patience
with a mail server is set longer than any wait of a test there, so nothing is cut off behind a test's back.

**Nor the hour it runs at.** The server's day is UTC's, the company's is Oslo's (`COMPANY_TIME_ZONE`) and a site's is
its own. From 23:00 to 24:00 UTC in winter (from 22:00 in summer) Oslo is a day ahead of the server, and a test that
says "today" on one clock while the code reads another passes all day and fails there. Five did, in CI run 42921917659
(23:17 to 23:57 UTC on 10.11.2026). Four were the tests' own: the wall's session day asked of the server's clock
(`timezone.localdate()`) where the code reads the company's; the cleaner-fish cage's site left on the company's zone
beside fixtures that count on UTC; the overview's "Feed today", then read on the company's day, expected of a UTC
site's day; a plan dated the company's today for people placed on a UTC site. One was the product's: the Treatments list read
every treatment on the company's day (Operations › Health). What holds the class now:

- `core/tests_day_boundary.py` runs the classes that count days again with the clock held at each moment of
  `core.testing.BAD_HOURS` (23:30 UTC on a winter night, 22:30 UTC on a summer night, the second before and the second
  after Oslo's midnight, New Year's Eve at 23:30 UTC), in every run of the suite: `at_bad_hours(globals(), ...)` makes
  `<Class>At<Moment>` for each. A class that says "today" belongs in that list.
- `TEST_CLOCK=2026-11-10T23:30:00+00:00 scripts/test.sh <labels>` starts the whole run's clock at that moment and lets
  it run on (`core.testing.run_clock`, in every worker): the way to look for more, at any hour, day or year. The
  database's clock stays the real one, so in such a run the tests that compare the two clocks fail by design
  (`core.tests_testing`, the test that runs `makemigrations`, the account mails' lease); it is a search, not a way to
  run the suite. Run on 11.11.2026 over the 150 test modules that name a clock or a date (3,106 tests) with the clock
  started at `2027-12-31T23:30:00+00:00`: ten failures, three of them the tests above, six of the run's own making and
  one a data map that the branch's own test commits had left stale. **A sweep is run by hand**: nothing runs one on a
  schedule, and the reports' and leave tests stand at 11.11.2026 until someone moves them.
- **Decided since (the owner, 12.11.2026): everything is shown on the site's own day.** The overview's feed figures
  count each site on its own day (Feeding, the production overview), and the Treatments list reads the fish on the
  day of the site they are on (Health). The test that had pinned "Feed today" to `0.00 kg` in the hours when the
  company's day is ahead of the site's now expects the feed at every hour.
- In a test, today is asked of the clock the code under test reads: `farm.stock.dates.site_today(site)` or
  `local_today(unit)` for a site's records, `core.dates.company_today()` for what has no site; never
  `timezone.localdate()`, `date.today()` or `timezone.now().date()` (`core/tests_company_clock.py` refuses them in the
  code and, since this change, in the tests).

## CI and dependency updates

GitHub Actions (`.github/workflows/ci.yml`) runs five jobs in parallel, `permissions: contents: read`, every action pinned
to a full commit with its version beside it. No secret is used: the database passwords are throwaway values that live only
inside the job. When it runs (the owner's decision, 2026-11-08):

- **A pull request into `main`**: the fast jobs only, minutes each: `frontend`, `rust`, `chemcore`, `security` and `python` as the
  checks without the suite (`SUITE=0`). A newer push to the pull request cancels the older run.
- **The whole Python suite** (an hour or more on a hosted runner): on every push to `main`, nightly at 06:30 UTC (after
  06:00: until the golden-card fix G-03 lands, six subtests of `monitoring.tests.test_golden` fail before 06:00 UTC) and
  by hand (Actions, CI, Run workflow). These runs carry the other four jobs too and are never cancelled.

Artifacts: none on a passing run. The three jobs that build an image (`python`, `rust`, `chemcore`) keep the build's
record (`docker buildx history export`, for Docker Desktop's Builds view) only when that build failed, for 3 days, as
`build-record-<job>`; `docker/build-push-action`'s own upload of every build's record is off (`DOCKER_BUILD_RECORD_UPLOAD`),
as it filled the account's artifact storage. Neither step can fail a job or hide its failure (`continue-on-error`).

The python job is the same job on every event, only `SUITE` differs; its logic is in one place, `scripts/test.sh` and
`scripts/testrunner/in-container.sh`, which a developer runs the same way. The suite itself is not run on a pull request,
so run `scripts/test.sh` on the branch before asking for a merge.

| Job | What it runs | The same on a developer's machine |
|---|---|---|
| `python` | the browser build first (`npm ci`, `npm run build`: `check` fails on core.W001 without `static/js`), then `CHECKS=1 scripts/test.sh` (`SUITE=0` on a pull request) with 4 workers, in the test runner's image (`scripts/testrunner/image.sh`, built with its layers cached): `ruff check` (the linter, below); `compile_catalogs` (a fresh checkout has no `.mo`, and core.W002 would fail the check); `manage.py check --fail-level WARNING`; `check --deploy` with production-like settings (DEBUG off, a random key, a host, an SMTP server, a sender and an https public address: Email), where any issue but the four still open fails (`DEPLOY_OPEN` in `scripts/testrunner/in-container.sh`: the four HTTPS settings, until the production settings exist); `makemigrations --check`; `data_map --check`; `update_catalogs`, then `git diff --exit-code -- locale` (the catalogs were up to date); `compile_catalogs`; then, except on a pull request, the whole suite with warnings as errors | `CHECKS=1 SUITE=0 scripts/test.sh` (the checks only) or `CHECKS=1 scripts/test.sh`, then `git diff -- locale` |
| `frontend` | `npm ci`, `npm run check:css` (the committed `static/css/tw.css` is what `frontend/tailwind.css` and the templates build now), `npm run check:tokens` (the tokens' CSS is what `tokens.json` builds), `npm run check:ds` (the design-system gate and its ratchet), `npm run build` (tsc, `tsconfig.json`, then the Tailwind build), `npm test` (the TypeScript tests, the designer's and the layout's browser tests on the runner's Chrome) | the same four |
| `rust` | in `sensors-ingest/`, on the toolchain of `rust-toolchain.toml` (1.88.0, the release image's and the crate's `rust-version`): `cargo fmt --check`, `cargo clippy --locked --all-targets -- -D warnings`, `cargo test --locked --all-targets` against a TimescaleDB service migrated by Django (`manage.py migrate` in the test runner's image, the server's own packages) and a Mosquitto broker (`REQUIRE_DB=1`: the database and broker tests run, never skip), `cargo deny --locked check` (licences, bans, sources, RustSec advisories), `THIRD_PARTY` equal to what `Cargo.lock` says | `sensors-ingest/tests/run.sh` |
| `chemcore` | `chemcore/scripts/test.sh` in the `chemcore-tools` stage of `docker/testrunner.Dockerfile` (its layers cached): rustfmt, clippy, `cargo test`, libm the chemistry's only dependency, no WebAssembly, `cargo deny` with advisories, `chemcore/THIRD_PARTY`, `docker/requirements.lock` naming the pins of `requirements.txt`; the built module's handshake with `chemcore/EXPECTED` (core.E001) is the python job's `check`. | the same `docker run` as the script's header |
| `security` | `pip-audit --strict` on `requirements.txt` and the test runner's, and with `--require-hashes` on what the runner image installs (`docker/requirements.lock`) and the chemcore wheel's build tool (`docker/chemcore-build.lock`, maturin); the Python licence gate (`pip-licenses --allow-only`, the licences [`THIRD_PARTY.md`](THIRD_PARTY.md) allows: AGPL, SSPL, BUSL, non-commercial or any unreviewed licence fails); the banned components, MinIO and rodbus, whatever licence a client library carries (a Python or npm package, or an image a compose file or Dockerfile names; the crates are denied in `deny.toml`); `npm audit --omit=dev --audit-level=high` | see below |

The ingest's tests, bench and end-to-end runs make their configuration in SQL of their own (`sensors-ingest/tests/common/mod.rs`,
`bench/seed.sql`, `bench/multisource_setup.py`, `e2e/seed.sql`) on the schema Django migrates, so a migration breaks them
without touching `sensors-ingest/`: a NOT NULL column without a database default (a model's `default` is Python's) that
they do not give (`sensors_channel.fresh_heartbeats`, sensors 0010, kept the `rust` job red on `main` from its landing).
Two things hold it: `sensors.tests.test_contract.IngestSqlTests`, in the Python suite, reads every `INSERT INTO table
(columns)` under `sensors-ingest/` against the schema (a column the database does not fill left out, a column that is
gone), and a branch with a migration runs `sensors-ingest/tests/run.sh` before it lands (CLAUDE.md, How work lands).

**The linter** is ruff (MIT), pinned exactly in `scripts/testrunner/requirements.txt`, so it is in the image the tests
run in and never in a server's (the `runner` stage installs `docker/requirements.lock` only). It finds mistakes, not
taste (`ruff.toml`): pyflakes (`F`: an undefined name, an unused import or variable, a key written twice, a format
string with no field) and `E9` (what stops a file from being read); no formatter, no style rule, no import sorting, and
it changes no file. It runs first among the project checks, reading the files without importing them. An import that is
there for what importing it does (a registration, a re-export) says so on its line (`# noqa: F401  why`); an applied
migration is not edited for it (one is listed in `ruff.toml`). By hand, without the checks:
`docker run --rm -v "$PWD:/app" -w /app "$(sh scripts/testrunner/image.sh build)" ruff check --no-cache .`

The security job by hand (Docker, nothing installed on the machine):

```
docker run --rm -v "$PWD:/w:ro" -w /w python:3.12-slim sh -c '
  python -m venv /tools && /tools/bin/pip install -q pip-audit==2.10.1 pip-licenses==5.5.5 &&
  /tools/bin/pip-audit --strict -r requirements.txt -r scripts/testrunner/requirements.txt &&
  python -m venv /app && /app/bin/pip install -q -r requirements.txt -r scripts/testrunner/requirements.txt &&
  /tools/bin/pip-licenses --python /app/bin/python --from=mixed --allow-only="Apache-2.0;Apache-2.0 OR BSD-3-Clause;BSD-2-Clause;BSD-3-Clause;BSD License;LGPL-3.0-only;MIT;MIT-0;PSF-2.0"'
npm audit --omit=dev --audit-level=high
```

The workflow is checked with `actionlint` (the `rhysd/actionlint` image runs it with shellcheck:
`docker run --rm -v "$PWD:/repo:ro" -w /repo rhysd/actionlint:1.7.12`). The suite takes far longer on GitHub's runners than
here (4 workers on a small runner; the job allows 150 minutes, the checks alone 30), so `scripts/test.sh` stays the way to
run it while working.

**Dependency updates** come from Dependabot (`.github/dependabot.yml`): every Monday for pip (the requirements and the
test runner's), npm, cargo (`sensors-ingest` grouped, `chemcore` one pull request per crate, its pins exact: a libm move is a re-recorded golden), the GitHub actions and the Dockerfiles' images (`docker/`, `sensors-ingest/`); minor and patch releases
grouped into one pull request per ecosystem, each major in a pull request of its own, at most 5 open per ecosystem. Django's
feature releases (6.1 to 6.2) never come in the group, and a new Python or Rust (minor) is not proposed at all: they are
planned moves. Nor is a new major of `@types/node`: it follows the Node that runs the tests and CI (22, `NODE_VERSION`),
and the two move together. The TimescaleDB image is pinned by hand in `docker-compose.yml`, `scripts/test.sh`, the workflow and
`sensors-ingest/tests/run.sh`, and moves in all four together. Dependabot's security updates are a repository setting
(Settings, Code security), to be switched on by the owner. Dependabot does not regenerate `docker/requirements.lock`: a
pull request that moves a pin of `requirements.txt` fails the chemcore job (the lock must name the same pins) until the lock
is regenerated on its branch (README, chemcore, Upgrading).

**Upgrade policy:**

- **Security patches at once**: a pull request for a security fix (Dependabot's, or a RustSec, pip-audit or npm audit
  failure) is taken as soon as the whole CI is green on it.
- **Minor and patch releases monthly**: the grouped pull requests are merged once a month, each only with the whole suite
  green.
- **Majors on a planned branch**, after reading the release notes and the upgrade guide, with the deprecations they remove
  fixed first; Python and Rust toolchain moves likewise (the Rust one changes `rust-toolchain.toml`, the Dockerfile,
  `tests/run.sh` and the crate's `rust-version` together).
- **Django**: we are on 6.1, a non-LTS release (security fixes until about December 2027); the move to the 6.2 LTS (due
  April 2027, security fixes for three years) is planned as such a branch, once 6.2.1 is out, with the 6.1 deprecations
  already gone (they fail the suite).
- **Deprecation warnings are errors** (Tests, Warnings are errors), so a removal in the next release never surprises us: a
  deprecated call fails the suite the day the release that deprecates it lands in a pull request, long before the release
  that removes it.

**One adapter per library.** A library other than the framework is called from one module, so an upgrade or a replacement
touches one place and its tests: `pypdf` only in `knowledge/extraction.py` (reading a PDF's text), Babel only in
`core/catalogs.py` (the translation catalogs), `psycopg` directly (beyond Django's database backend) only in
`sensors/management/commands/sensors_ingest_role.py` (the ingest role's SQL, quoted by `psycopg.sql`); `cryptography` is
imported by nothing of ours (pypdf uses it for encrypted PDFs). Tests may import a library to build their inputs (a PDF, a
`.mo` file, a connection). In the ingest, the MQTT client (`rumqttc`) is only in `src/mqtt.rs` and the HTTP server (`axum`)
in `src/http.rs` and `src/supervisor.rs`, the time library (`time`, since chrono became unmaintained) only in `src/ts.rs`,
the one timestamp type (the bench example `examples/multisource.rs` formats its payload times with it too); its
database client is its core and is used where it writes (`src/db.rs`, `src/config.rs`, `src/env.rs`, `src/service.rs`).
