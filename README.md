# Fish farm prototype

A small Django prototype of the farm module of Suderra's aquaculture platform: Django 6.1 on
PostgreSQL 17 with TimescaleDB 2.17 (Docker). The farm module's tabs are ported one at a time.

What works today:

- Sign in, sign out, forgot password (reset link by email), change password. All of it is Django's
  built-in auth: PBKDF2 password hashing, signed one-time reset tokens, the standard password
  validators, CSRF protection and sign-out by POST only.
- An activity log (`/activity/`): who created, changed or deleted which record, when, with the old
  and new value of every changed field. Rows are written in the same transaction as the change and a
  database trigger refuses to update or delete them. Each record's form has a History tab. An entry where
  someone went on past a handling warning is marked critical.
- Every page needs a signed-in user (`LoginRequiredMiddleware`) unless its view opts out.
- Roles (`/roles/`) and users (`/users/`), managed by the platform admin only (see Roles and users).
- A database viewer (`/database/`): every table as a spreadsheet-style grid, for the platform admin
  (see Database viewer).
- Three panels, switched from the top left: **Company** (overview, Facility › Sites and Storage locations,
  Knowledge, Administration, and HR) and **Production** (overview, production departments, systems, equipment, tanks,
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
- Deleting a site leaves its production departments without a site (see Production departments); the other dependants
  join the delete plan as their tabs arrive. Its health events stay with it, out of sight, and come back with it.
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
  its parts. Deleting a site leaves its production departments without a site (as before), so their
  equipment stays with them, without systems: the source deleted that equipment with the site.
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
source's status machine, in one place (`TRANSITIONS`); a new unit holds no fish, so it starts as
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
- The code is unique among live units. The regulatory unit ID is the locality's own number (merd 1 on two sites
  is two units): unique among the live units of a site, held by the database per production department and by the
  form across the site. A unit with stock records stays on its site, and so does a production department whose
  units have some, since moved, their past figures would be reported for another locality. A deleted unit can
  be restored from the admin.
- Deleting a site leaves its production departments, with their units, without a site (as for
  equipment); the source deactivated their tanks.
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
different. The filters and the open unit are in the address, so a view can be linked and the back
button works; a row is one link. Two empty states: no units at all (with a link to Setup) and no match
(with "Clear filters"). The column chooser and sorting come next.
For people who may read the water (see Water chemistry), the table also has **Temp. (°C)** and **O₂ (mg/L)**
after survival, each the latest value of the unit's middle sampling point coloured by its status, stale ones grey
(time and age on hover), a status dot by the unit's code (its worst fresh status), and the count line says how many units
shown are critical ("14 units · 3.2 t · 2 critical"); the production overview has a tile "Units with a
critical water value".

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
Dates default to the farm's today (the site's time zone), never in the future, at most 31 days back
(`STOCK_BACKDATE_DAYS`). A form sent twice records once (the form's key, stored on the operation).

**The ledger.** A batch holds its identity and origin, no count. An operation (`StockOperation`) is what
a person did, with its date; its lines (`StockMovement`) say how many fish of which batch came into (+)
or left (−) which unit, or were weighed there (0). Every figure on the page is computed from the live
lines: a unit's fish is their sum, its biomass a date-ordered fold (`farm/stock/fold.py`): fish leave at
their batch's average in that unit on that day, a weighing sets the biomass from that day, the last fish
out take whatever the book holds, moved fish arrive with exactly the grams that left, a grading weighs
the whole lot. Only measured weights enter the book. Nothing is stored that can drift.

**One write path** (`farm/stock/services.py`, `_commit`): it locks the batches and the units, checks the
date, the units' status (a unit takes fish while active, preparing or fallow), the species (one per unit,
several batches of it; on a sea site cleaner fish may join the production species, see Cleaner fish below), then
writes and folds every batch involved from its first line, so a backdated
operation is accepted only if every later day stays right (no share ever below 0 fish, and every feeding
recorded in the unit still finds fish there on its day: "The feeding of 2 Nov in T-01 would have no fish:
void it first."); above a unit's max biomass it asks for an acknowledgement, stored on the operation. The unit's status follows its fish:
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
operations made of their lines, stocking dates, unit statuses, species, feedings without fish) and the
tests run it.

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

A live card per tank, pond or cage, simple or detailed, in one grid that doubles as a wall screen for a control room, with a
unit's Deffeyes chart in a movable window. The app `monitoring` is composition only: it stores nothing but (later) shared
wall boards, derives no figure and writes nothing, a poll included. Every number on a card comes from the module that owns
it, through a read that answers for many units at once (the table is `monitoring/read.py`'s docstring):

| Card figure | Owner |
|---|---|
| fish, average g, biomass, volume, density, capacity, over capacity, since, deaths, culls, survival, last weighed, batches | `UnitStock` (farm/stock/read.py), `stock_of` |
| ration, fed today, remaining, next meal, why there is no ration (a fast too), weigh soon or now | `feeding.read.figures(details, ration=True)`: one walk of the projected weight for all the cards, then `meal_lines` and `drift`, which the meal board prints too |
| bFCR, eFCR, last fed, feed rate, feed in use | `UnitFeeding`, `Week` |
| water per parameter with age and status | `water.read.points_water`: one `latest()`, the middle point of a simple card, every active point of a detailed one |
| medicine withdrawal | the registry's one bulk answer (`harvest.views.withdrawals`), with the stock right, as Production units |
| open health events (every card), treatments and the latest sea-lice count (detailed) | `health.read.open_events`, `recent_treatments`, `latest_counts` |
| open, overdue and due-today tasks (detailed) | `tasks.read.per_unit` |
| the Deffeyes chart | `water.calculation.chart_of` through `farm:water_unit_chart` (see Water chemistry) |

**The page** has a toolbar (a GET form that works without script: site, department, system, kind, fish (stocked by default,
empty, all), the all-cards mode, a text search, a unit picker, Wall and Full screen) and the grid: a head ("2 of 3 units
shown", "computed at" a time, so a frozen screen is visibly old), a strip naming each critical, warning or no-recent-data
card, and one article per unit in the farm's one order (site, department, code), so a card never moves when its state does.
Each card has its Simple or Detailed link (the page with that card flipped; with script the grid refetches), its state word
and shape, the withdrawal with its date, and a Deffeyes chart button that opens the window. A **section the person may not read
is not read at all** (no query) and the card says so ("Water: not shown to you" and "State from: Fish"); one right for each
section (`monitoring.read.sections_for`, the one place that spells a permission). Detailed never widens access.

**The state** is one ladder (`state_of`, the thresholds are the owners', none invented here): critical (a water reading judged
critical); warning (a warning reading, over capacity, an estimate that says weigh now); **no recent data** (a stocked unit whose
temperature or oxygen is missing or older than its 24 hours, or with no middle point: the water's own status ranks OK above
stale, so a fresh pH would hide a three-day-old oxygen; never OK, never red, the age is printed; not worked out when the water
is hidden); note (a withdrawal in force, weigh soon, a ration that cannot be worked out with its reason, an open health event);
ok; empty. Word, shape and reasons, never colour alone.

**Polling.** The grid is `data-poll` with `data-poll-merge="data-key"` (every 15 s, `settings.MONITOR_POLL_SECONDS`). The
fragment `cards/?...&after=<token>` computes the **change token** first (`core.audit.revision()`: the newest audit entry and
how many lie in the five minutes up to it, two indexed queries, read before any data; the minute, the language, what the person
may read, the board and the canonical address), answers **204** with the same `X-Poll-Next` while it is equal, else 200 with the
cards and the next address; the minute re-draws the figures that run on the clock at most once a minute. A writer that does not
write its audit entry would leave a card up to a minute old: the token test enumerates the writers. The fragment is rendered
without a request, so the shell's context (the menu, the unread count) is never worked out for a poll.

**The wall.** `?wall=1` puts `data-wall` on `<html>` (no rail, no top bar, no width limit, larger figures), and the page and its
polls keep the session alive once a day (the default session is two weeks and a wall must not sign itself out); the grid prints a
large notice from `data-poll-state` when the server cannot be reached or the person is signed out.

**Boards** (Setup › Facility structure › Monitoring boards, `/monitoring-boards/`): the only thing the app stores. A board is a
named, shared wall screen: a name (unique among the live boards in any case), a description, how its cards are drawn by
default (simple or detailed), how often its screens ask (10 to 600 seconds, empty: the system's 15), and its **Units** tab, one
card per unit with its own mode (empty: the board's), saved as a whole list with the board's version (a list based on an outdated
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
to roles without feeding rights; the chart's temperature is the unit's own point's, never the loop's, and the chart refuses and
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
"4 8 12 16", and changing them renders the grid again with what was entered (`data-refresh`, nothing saved); the
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
`STOCK_BACKDATE_DAYS` back. Before its first day a row may change or be deleted; from then on only its last day
(yesterday at the earliest) and notes change, and it is ended, not deleted: the days it fed keep their protocol.
The list groups the rows of one dialog, filters by site, unit, batch, protocol and in force / starting later /
ended, and counts the fish each row feeds today after the more specific rows.

**The ration** of a batch in a unit on a day (`farm/feeding/ration.py`): the protocol by the rule above; the band
by the fish's **estimated** average (owner decision Q7); the **temperature** of the unit, else of its system's loop,
then of the systems that system is nested in (`farm/feeding/temperature.py`, the water samples' series of
`farm/water/read.py`): the unit's own fresh value wins, else the nearest loop's fresh value, else the newest stale
one, marked stale; fresh is the temperature parameter's 24 h, and nothing within `TEMPERATURE_USABLE_DAYS` (7,
owner decision Q5) gives no ration; the moment is now for today and the end of the day for a past day. The SFR is
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
next meal; a unit without a ration says why in the row. **Record meal** opens the existing feeding dialog with today,
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

- the date as for the stock: the farm's today at the latest, at most `STOCK_BACKDATE_DAYS` (31) back;
- the unit must hold fish of the target at the start or the end of that day (from the stock ledger; the
  reason is on the target when the unit holds the other kind); and the other way round, a stock operation (a backdated harvest or transfer, the void of the stocking that brought the
  fish) is refused while a recorded feeding would be left without fish, naming it;
- a new record takes an active feed; a record keeps its feed whatever the feed's status becomes;
- above `FEEDING_ACK_PERCENT` (10 %) of the book biomass of the target's fish in a day, the person is asked to confirm,
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
- The production overview: feed today and over the last 7 days on the whole farm.

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
  FDR-37); who recorded is the person signed in (FDR-11); amounts to the gram (FDR-35, FDR-40).
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
NO₂⁻ ÷ 3.29, NO₃⁻ ÷ 4.43, NH₄⁺ ÷ 1.29). Each has a plausible range, which catches a typing slip and is a
database check (the ranges are argued in the bug document), its precision and how long a value is fresh:

| Column | Label | Decimals | Plausible | Fresh |
|---|---|---|---|---|
| `temperature_c` | Temperature (°C) | 1 | −3 … 40 | 24 h |
| `oxygen_mg_l` | Dissolved oxygen (mg/L O₂) | 2 | 0 … 50 | 24 h |
| `oxygen_saturation_pct` | Oxygen saturation (% of air saturation) | 1 | 0 … 400 | 24 h |
| `ph` | pH (NBS scale) | 2 | 2 … 12 | 72 h |
| `alkalinity_mg_l` | Alkalinity (mg/L as CaCO₃) | 0 | 0 … 1000 | 14 days |
| `co2_mg_l` | Carbon dioxide (mg/L free CO₂) | 1 | 0 … 200 | 72 h |
| `tan_mg_l` | Total ammonia nitrogen (mg/L TAN as N) | 3 | 0 … 100 | 7 days |
| `nitrite_n_mg_l` | Nitrite (mg/L NO₂ as N) | 3 | 0 … 100 | 7 days |
| `nitrate_n_mg_l` | Nitrate (mg/L NO₃ as N) | 1 | 0 … 1000 | 14 days |
| `tgp_pct` | Total gas pressure (% of barometric pressure) | 1 | 50 … 200 | 7 days |
| `salinity_ppt` | Salinity (‰, g/kg) | 1 | 0 … 50 | 7 days |
| `turbidity_ntu` | Turbidity (NTU) | 1 | 0 … 4000 | 7 days |

**A sample** is one row: what a person measured at one point at one moment, a typed column per
parameter, empty when not measured, at least one value (a database check). The point is one sampling point
(`point`, a required foreign key; the table has no unit or system column: the unit, loop or equipment is the
point's owner, so the two cannot disagree). The time is on the clock of the point's site, never in the
future and at most 31 days back (`STOCK_BACKDATE_DAYS`, `farm/stock/dates.py`), the rule of every daily
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
  fish shows its values with "no limit"** (owner decision 1).
- **A past sample is judged against the limits as they are now** (owner decision 2): a changed limit
  re-judges the history at once; the limits of the time are not kept. The page says so.
- The latest value of each parameter is per parameter, not per sample: a later sample without DO never
  hides a critical DO. A value older than its freshness is "stale" with its age, never ok. A unit's
  status is the worst of its fresh values; stale when nothing is fresh.

**Worked out from a sample**, never stored (`farm/water/chemistry.py`, each pinned by a test against
published values):
- **NH₃-N** = TAN × K / (K + [H⁺]), with K the ammonium constant of Millero (1995) on the seawater scale,
  converted to the free scale, and the pH (NBS) converted too, ported from the source's engine; in fresh
  water it equals Emerson et al. (1975) within 0.002 pK up to 30 °C and 0.003 up to 40 °C. It needs the pH and the temperature of the same
  sample; the salinity is the sample's, else its point's latest within 30 days before it, else its owner's middle
  point's, else 0 where every unit it concerns is in fresh water; otherwise the page says what is missing. NH₄-N = TAN − NH₃-N is shown.
- **Oxygen saturation**: Benson & Krause (1984) as in Standard Methods 4500-O, corrected for the
  barometric pressure of the site's altitude (sea-level pressure, said so, when the site has none). From
  mg/L the % is worked out, from % the mg/L; when both are entered and differ by more than 10 %, both are
  kept and flagged.

**The page** has three tabs: **Latest** (one row per point: the middle point of every unit (a unit without one
has a row that says so) and every other point, of a loop, a unit or a piece of equipment, that has a sample in the
last 30 days; its status and the latest value of each parameter, coloured by status, its time and age on hover;
a filter by site), **History** (the samples, newest first, 50 a page, filtered by site, by unit, loop or
equipment and then by one of its points, dates, and "only warnings and criticals"; each value says which point
it was taken at, coloured as judged now, worked-out values in italics; Void while the sample is in the window)
and **Calculator** (below). **Record sample** opens the dialog (a sampling point chosen from the points grouped
by what owns them, "T-01 › Middle"; date and time on the site's clock, source, the twelve values in four
groups, notes). Opened from a unit, a loop or a piece of equipment (`?unit=`, `?system=`, `?equipment=`) it
offers that owner's active points with its middle point chosen, so a routine sample takes no more fields than
before, and when the owner has only one point it is fixed; each field's help shows the limits of the fish
there. `?point=<id>` names one point. **Round** is the morning round: a site and optionally a production
department or a system, the columns to fill (temperature and oxygen by default), one row per unit's middle
point (a unit that is not inactive) and per loop, and, when asked ("Also list": inlets, outlets, side outlets,
bottom drains, depth points, the points of equipment), the other points of them, one time and one source; empty
rows are skipped, a value out of range is shown in its cell and nothing is recorded until every cell is right
(at most 200 rows).

**A unit's water** is the latest samples at its middle point, and only there (`read.middle_points`, the one
definition; `read.unit_water`): what Production units, its drawer, the overview tile, the status dot and the
calculator show of it. An inlet's or an outlet's sample is the stream's, not the fish's: it is judged for the same
fish and shown, but it never moves the unit's status. Nothing of a unit's DO, pH or nitrogen is taken from its
loop (the source passes on only what is the same all round a loop, and so does this). Its **temperature** is the
one value that may come from a loop: the ration (`farm/feeding/temperature.py`) reads the unit's middle point, else
the loop point of its system and of the systems that system is nested in, and the withdrawal's daily mean
(`farm/health/withdrawal.py`) the unit's, else its own system's loop (a day without one counts at the species'
assumed temperature, else as 0 °C, and says so: the safe side). Both ask `read.water_sources`, the one place that says where a unit's temperature is read from,
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
  given, from 5 to 44 ‰ (Mucci's range); the water (a star) and the target (a cross); the dosing layer (one
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
  source calls them Millero 2010, WQ-39); Kw of Millero (1995); KB of Dickson (1990)
  with Uppström's (1974) boron; the ammonium constant of Millero (1995); KH₂S of Millero, Plese &
  Fernandez (1988); the Ksp of Mucci (1983); the CO₂ solubility of Weiss (1974); each converted to the free
  scale, the pH (NBS) too, as the source does. DIC = (alkalinity − [OH⁻] + [H⁺] − [B(OH)₄⁻]) / (α1 + 2 α2),
  CO₂ = DIC α0; NH₃-N = TAN K / (K + [H⁺]); H₂S = total sulfide × 34.08 / 32.07 × [H⁺] / (K + [H⁺]). A pH
  and an alkalinity that cannot go together (the hydroxide alone above the alkalinity) are refused.
- **Two conventions inherited from the source**, kept for consistency and stated here: the ionic strength
  comes from the salinity, so at 0 ‰ the pH needs no activity correction while fresh water's own ions
  would give it one; entering 0 instead of 0.3 ‰ gives 7 to 13 % more CO₂ and 5 to 9 % more NH₃ at 5 to
  25 °C and pH 6.5 to 8.5, the safe side. And a pH (NBS) is put on the seawater scale with a Davies-type
  activity coefficient, not CO2SYS's apparent coefficient of Takahashi et al. (1982): at 35 ‰ the two
  differ by −0.07 pH at 0 °C, −0.058 at 5 °C, about 0 at 25 °C and +0.05 at 40 °C; at 5 °C the chart
  shows about 12 % less NH₃ and 16 % more CO₂ than CO2SYS would.
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
"assumed". The temperature is the point's own, never the loop's. TAN, oxygen and the site's altitude are drawn
when there; no total sulfide or calcium is measured, so there is no H₂S or Ω layer, and a limit the fish do not
have is said, not drawn. Each reading shows its age, status and point; the chart's SVG ids carry the point
(`uid`), so several windows on one page never clash. The endpoint needs only the right to read water samples.
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
as its stock lines are: points are not deleted with their owner because restoring a record brings back only that
record, so points deleted with it would never return. A species takes its water limits with it, each listed and
logged. The admin shows voided samples but does not restore them.

**The MVP alerts nobody.** A critical value is shown on the page, on the unit in Production units (its
columns, dot, count line and drawer) and as a tile of the production overview, never sent: there is no
email, SMS or push, no acknowledgement and no escalation. Someone has to look.

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
  notifications, H₂S as a sample parameter, hardness and the other lab
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
missing delivery, dated on or before the day (within the backdating window). Units without a site feed
from no store.

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
`STOCK_BACKDATE_DAYS` back), live locations, arrivals into active locations only, a live supplier that
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
  expired lots fed; per site and item the stock on hand, the feed of the last 7 days and the **days of
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
  3 Nov 2026, 02:52, 48.0 h and 36 degree-days before 6 Nov 2026: the harvest rule asks for 72 h and 60 degree-days." The last feeding is of the fish themselves, wherever they were
  fed: the feeding walk's split says which batches a record fed, so fish moved in yesterday bring their last
  meal in the old unit with them (`farm.feeding.read.last_fed_at`). A record without a time counts from the end
  of its day and a feeding on the day gives 0 h, so **the fast is never overstated** (and the degree-days of several
  batches in a unit are the fewest). The rule is the species'
  own, else the one for every species; a grading takes the longer of the grading and the transport rule. No
  rule, or no feeding in the 31 days before (longer than any rule), is said, not warned.
- *Medicine withdrawal* (**a harvest only**: the fish go to food, to the slaughter facility the harvest names; a
  medicine withdrawal is a meat withdrawal, so it means nothing when live fish are moved or graded, where the
  fast and the live-transfer facts are what matter, and a treatment during a withdrawal harms nobody): every block
  a registered provider gives for the batch whose end is after the day, or unknown (unknown is a warning, never
  clear). The health records register their provider in `farm/apps.py` (`farm/handling/withdrawal.py`:
  `register(provider)`, `blocks(unit, day)`, `WithdrawalBlock(batch, until, approximate, reason, source)`; see
  Operations › Health). With no provider registered the harvest dialog would say "Medicine withdrawal not
  checked" and warn nothing.
  It reads "Not suitable for harvest — medicine withdrawal of B-2026-001 until 14 Dec 2026". The informational
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
  decides**: "Earliest suitable harvest date: 17 Nov 2026. Medicine withdrawal decides: until 17 Nov 2026." or "Earliest
  suitable harvest date: 15 Nov 2026. Purging decides: feeding must stop by 11 Nov 2026." (a tie goes to the
  withdrawal; an unknown withdrawal end is "not known"). It is worked out from the parts above on read, nothing is
  stored; a plan dated before it is marked, and a harvest before it is a warning on the parts' terms, acknowledged and
  logged as critical as before, never a block. A transfer and a grading do not say it.
- *Production units*: a "Withdrawal" badge on a unit with a withdrawal in force today, and the drawer's
  **Harvest and handling** part: the check of a harvest today and the unit's open plans with their fasts.

**The activity log** has a severity: normal, or critical for an operation someone went on with past a handling
warning (`AuditLog.severity`, a database check, a partial index); critical entries have a red edge and a
Critical badge, and the log filters by severity. Nobody is alerted yet: the later alarms read these entries.

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
entered by the farm and checked by its vet. A medicine a treatment used cannot be deleted, nor its manufacturer
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
medicated feed is not checked: it is the feeding itself. Every unit must hold fish on the first day; the other
way round, a stock operation that would leave a treatment (or a lice count) without fish on its day is refused,
naming it, and `check_stock` reports one. **No
batch is stored**: the batches treated are the ones the stock ledger has in its units from its first to its last
day. The list filters by site, unit, batch, method, medicine, dates, "under withdrawal today" and
"vaccinations", shows every batch a treatment reached with the withdrawal it puts on it, and offers **Last day**
(the course ended earlier or goes on: Edit, logged with the old and new day) and **Void** (with a reason, the
farm's window; it lifts the withdrawal). Nothing else is edited: a correction is a void and a new record.

**The medicine withdrawal** is worked out on read, never stored (`farm/health/withdrawal.py`), so a void, a
corrected temperature or a backdated transfer changes it at once:

- it **follows the fish**: every live treatment with a medicine whose treated batches include the batch holds
  it, wherever it is now; if only some of its units were treated, the whole batch is held;
- **per species**: the medicine's row for the batch's species, else its row for every species, else the end is
  unknown (see Medicines); the margin is applied to both values;
- **days**: day 1 is the day after the last treatment day, the first day the fish may be harvested is the last
  day + the days + 1;
- **degree-days**: the batch's daily mean water temperature is added up from the day after the last day until
  it reaches the row's degree-days, the next day is the first harvest day. A unit's daily mean is the mean
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

A withdrawal holds the batch from the treatment's first day (or the medicated feeding's day) to the day before
the first harvest day; a day before the treatment is not held.

Where it shows: the health records give it to the shared handling check through the registry of
`farm/handling/withdrawal.py` (`blocks(unit, day)`: a block per batch and cause, `until` the first day the fish
may be harvested; the provider is registered in `farm/apps.py`). From there Production units marks the unit's
row **Withdrawal** and the drawer's Harvest and handling section says **"Not suitable for harvest — medicine
withdrawal of B-2026-001 until 14 Dec 2026."** ("about" when projected, "its end unknown") with why, to everyone
who sees the page; the harvest dialog warns, never blocks (owner decision), and keeps the acknowledgement (the
transfer and grading dialogs are not asked for a withdrawal: live fish are not eaten). The Treatments list shows each batch's end as "until 13 Dec 2026 (harvest from 14 Dec 2026)".

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
  smaller sample is pointed out; how many of the units with fish were counted is shown.

Over the limit is a warning on the page; nobody is alerted yet, and the weekly report to Mattilsynet is not
built (§ 10).

**The unit's drawer** on Production units has a **Health** section: the withdrawal of each batch with why, the
open health events that concern the unit, its treatments of the last 90 days, its latest lice count, and Record
treatment, Record sea-lice count and Record health event with the unit chosen.

**Who may do what**: the areas Medicines (Production · Setup · Reference data: read, create, edit, delete),
Treatments (read, create, edit = change the last day, delete = void), Health events (read, create, edit, delete =
void) and Sea-lice counts (read, create, delete = void), the last three under Production · Operations · Health.
The admin shows voided treatments, events and counts and does not restore them. `manage.py check_withdrawal`
works out every unit's withdrawal from scratch and lists the fish held, with the end and why.

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
- **notes**: anyone who can read Tasks adds one in the drawer; a note is never edited or removed and is in
  the activity log with its text (task notes are part of the work record; Messages are not, see below).

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
notes are part of the farm's record that a supervisor, the next shift or an auditor reads.

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
  with the reason), the experiment it was copied from, notes and the key of the form that made it.
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
  comes back without its design (only the record itself returns). A copy of a deleted experiment keeps pointing at it.
  A protocol a level names, a tank or a department a placement names, and a site or species an experiment names cannot
  be deleted while it does.

**Who may do what**: the area Experiments (Production · Research): Read the list and the read pages, Create makes and copies an
experiment, Edit changes it, saves its design, its places and its team, and starts it, Delete removes a draft. The recommended roles are data in Roles (no built-in roles): a researcher all four, a
student Read, Create and Edit, a technician and an advisor Read. Rights per experiment (a student edits only the
experiments they are in the team of) come with the permissions plan, which reads the team. The admin lists experiments,
deleted ones too, and restores an experiment (not its parts).

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
what was filed: a correction is needed", figure by figure; a correction is a new report of the same key that replaces it.

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
"Filed 2 days after its deadline" and a notice, filed at once, is never late. **Said, not assumed:** the biomass report asks in what
condition the harvested fish are weighed (round or gutted weight) and is not ready with a harvest until it is said; a cleaner-fish
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
the content hash and a link to the print page (the exact values to type, field by field in the authority's names); every export
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
  recorded; a cage with no production fish left on that day needs none), the sea temperature (the mean of the week's samples at the site's depth points of
  3 m, from Water chemistry), the week's lice treatments with substance, strength and amount from their records (the amount is
  the product's: Mattilsynet's § 10 c asks for the active substance's, so the report says to confirm which it wants).
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
Times are on the company's clock (`settings.TIME_ZONE`), as in the activity log.

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
  remain. Channel names are unique among live channels, whatever their case.
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
  topic each, on a site, optionally the instrument of a piece of equipment; offline after three intervals without a
  message), Channels (what a value measures, from the quantity catalogue `sensors/quantities.py`; where it is in the
  message; the unit conversion; how it is stored: every value, or a value that moves past the deadband and at least once
  per heartbeat; fresh for three heartbeats; a range outside which a value is stored but flagged and used nowhere;
  maintenance and retired states; calibrations as a list on the site's clock, applied by the ingest at the device time,
  never rewriting stored values), Bindings (where a channel's values belong over time: a sampling point or a system for a
  water value, a piece of equipment or a system for a process value; one primary and one backup per place and quantity;
  a move ends one binding and starts the next, so a sensor's earlier values stay with the tank they were taken in).
- **Operations**: Charts (a place and a quantity over a preset or chosen time, drawn by the server; the CSV is exactly
  the drawn buckets), Live values (every channel listened to, its last value, its age, fresh or stale, where it is bound),
  Dead letters (what the ingest could not store, counted, the payload shown escaped as text and hex; resolved by a
  person, logged), Alarm rules and Alarm events (**shown, not sent**: nobody is notified until a delivery path exists, and
  the pages say so).
- **Administration**: Credentials (a publisher's sign-in at the broker; the secret is made on the server, shown once
  when made or replaced, stored only as Mosquitto's `$7$` PBKDF2-SHA512 hash, masked in the database viewer and never in
  the activity log).
- **Overview**: the ingest alive or down (a heartbeat within 90 s), devices online, channels without a fresh value, dead
  letters of the last day, open alarms; each tile for the right that may read it.

### The water's latest value (owner rule A1)

Per unit and parameter, each on its own, in one place (`farm/water/read.py` `latest`, the sensors reach it through the
registry `farm/water/sources.py`, registered by `SensorsConfig.ready()`; the farm never imports the sensors): a fresh
value of a sensor on the unit's own point (primary, then backup); else, for the middle point, a fresh value of a sensor
on the unit's system; else a fresh manual or lab sample; else the newest of all, shown stale. A channel in maintenance
or retired is skipped. Sensor values enter as the parameter's Decimal at its decimals and are judged by the same water
limits. Derived values follow their base value's source (a sensor TAN gives NH₃ only with fresh sensor pH and
temperature, at the oldest input's time; a manual TAN only with its own sample's). Every latest value on the water page,
the monitoring cards and the Deffeyes window says where it comes from and how old it is ("unit sensor #12 · 12 s ago",
"system sensor #3 · 40 s ago", "manual · 2 days"); when the sensors cannot be read, the pages say the values come from
the samples only. The ration's temperature takes a fresh sensor value at its moment too.

A unit's or a system's Deffeyes can be drawn as it was at a past moment (`?at=` on the window's address, the site's
clock): the samples taken up to then and each channel's value then, from the bindings that held then. The hourly trail of
a unit's point on the diagram is `sensors:trail` (JSON, from the hour rollup). The monitoring card's own buttons for
these, for a place's charts (`sensors:target_charts`) and for binding a channel from a card (`sensors:binding_create`
with `?channel=&target=`) are left to the card-template designer.

### Storage

- `sensors_reading`: a hypertable in 7-day chunks, compressed after 14 days (per channel, newest first), dropped after
  730 days; primary key (channel, time) so a redelivered message is stored once; a row carries how many messages it stands
  for and, for more than one, their sum, lowest and highest, so every mean is exact (a sum of sums over a sum of counts,
  never a mean of means). Quality is one bitset (`sensors/quality.py`): bad rows (out of range, device bad, maintenance,
  simulated) are stored as evidence and left out of everything drawn or judged.
- Two continuous aggregates over clean rows: per minute, and per hour built on the minutes. Charts take the bucketed raw
  rows below a minute, the minute rollup up to an hour, the hour rollup above, and the site's local days from the hours
  (a day the clocks go back has 25 hours). The rollups refresh every minute and every hour over the last 35 and 75 days;
  a daily job takes in later readings back to the contract's late limit (728 days). The refresh never reaches back into
  dropped raw data: TimescaleDB 2.17 invalidates a dropped region and a refresh there would empty the rollups.
- The database viewer counts a hypertable by the database's estimate and leaves the readings out (billions of rows).
- Licences: compression, continuous aggregates and their policies are TimescaleDB's TSL features of the community build
  (free for an application that owns its schema, as this one; a test asserts `timescaledb.license = 'timescale'`). No new
  Python package; the credential hash is the standard library's `hashlib`.

### Running it

- `manage.py sensors_ingest_role --password-file FILE` lets the ingest's database role (NOLOGIN after the migration) sign
  in; `--disable` closes it.
- `manage.py sensor_broker_sync --passwd PATH --acl PATH [--extra OPS_LINES] [--check]` writes Mosquitto's files from the
  credentials and devices (atomic replace), then `docker compose kill -s HUP mosquitto` makes the broker read them.
- `manage.py check_sensors [--loop 60]` checks the alarm rules; `manage.py sensors_housekeeping` (daily) deletes dead
  letters older than 90 days.
- `manage.py bench_sensors --confirm-database NAME` writes synthetic readings into a database named on the command line
  (never a farm's) and prints the storage and read figures.

### Measured figures (bench_sensors on the local container)

- A channel stored at every 1 s message: the minute rollup holds 1.7 % of the raw rows.
- A channel stored once a minute (a deadband channel with a 60 s heartbeat, the common case): the minute rollup holds as
  many rows as the raw table (100 %). **This fails the plan's 40 % gate**: the owner decides whether the hour rollup is
  built from the raw readings instead of the minutes (one migration).
- 20 channels × 30 days at one row a minute: a chart of one channel over the whole span in about 0.3 s (real-time
  aggregation, nothing refreshed yet), the latest values of 20 channels in about 40 ms.

## Human resources (Company › HR: `/hr/`)

The company's people, where they work and, as the pages arrive, their time. It is one piece of the Company
panel, not a module of its own: the same roles, delete plans, activity log, database viewer and languages. It is
built by reading the source platform's HR service and listing what was wrong with it
([docs/aquaculture-platform-bugs.md](docs/aquaculture-platform-bugs.md), "Human resources"). The rules it holds:

- **One source for departments.** Every production department is an HR department by itself: the Departments page
  reads the farm's own rows (`hr.read.departments`), so a production department created, renamed or deleted under
  Production is there at once with no HR write and no copy. Only the white-collar departments (Finance, administration,
  management) are HR's own rows (`hr.OfficeDepartment`, table `office_departments`); they nest under one another for the
  organisation chart.
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

One list over two kinds, production departments (never edited here: their name links to the farm's own form for
whoever may change them) and office departments (created, edited and deleted here). A table with kind, status, site
and manager, search by name or code, and filters for kind and status. An office department has a name, a code (unique
among live ones, capital letters, digits, hyphens and underscores), a parent (the chart), a site (the clock of its
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
(the days a leave request is charged for) and the punch window and the absent-after minutes (Today). The figures are
labelled defaults on the page, **not the law**: none of the statutory figures is verified, so none is a database
constraint (a rest of 60 minutes can be stored); the settings may only be set stricter than the statute, and the owner
confirms them. Sanity checks only: ranges and the enumerations.

**Shifts** (`/hr/settings/shifts/`, no menu line, reached from the settings page; Shifts is its own matrix area): a name,
a code (capital letters, digits, hyphens, underscores; unique among live shifts, free again after a delete), the start
and end on the wall clock of the site (an end at or before the start is the next day), a break (0-240, shorter than the
shift: a database check on the two time columns), a grace (0-120), a tone 1-8 (a CSS class: no colour value is stored,
HR-27) and a status. **Holidays** (`/hr/settings/holidays/`): a day, a name and a site or every site, one per day for
every site and one per site (`nulls_distinct=False`); typed in by HR, never seeded, because the country's days are the
owner's data. A site with holidays is not deleted.

### Time & shifts › Shift schedule (`/hr/schedule/`)

A week of the viewer's people as a table: a row per person (their department under the name), a cell per day, the planned
hours at the end. A cell shows the shift (its code in its tone), "Off" for planned off, the holiday of the person's site, and
a "!" with the finding when a rule is broken; it opens the plan of that person and day in a dialog (a plus on an empty cell
when the viewer may create). The week is the ISO week (Monday first, no setting); `?week=` takes any date of it, `?department=`
and the search narrow the people and never widen them, and the list says "n of m" with its own paging. Everything on the page is
worked out on the server (`hr.read.week`: one query each for the page's people, their plan a fortnight either side, their
placements and the holidays, whatever the number of people), and a person who moved is shown to each manager on their days
only (`hr.scope.visible_days`).

**One roster table** (`hr.ShiftAssignment`, `shift_assignments`, shown as "plan" in the log): a person and the day a shift
starts (a night shift ends on the next day), the shift or none (planned off, which is not the same as no plan), a note (private:
masked in the log and the viewer). One row per person and day among live rows; a cleared cell is a soft delete. Leave and
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

**Leave types** (`/hr/settings/leave-types/`, no menu line, reached from Scheduling settings): a name, a code, the days a
year (empty: no limit) and whether a request needs approval; owner data, none seeded. **A request** (`hr.LeaveRequest`,
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
pending request is cancelled by the person or a decider at any time, an approved one only while its first day has not started on
the site's clock; the decisions are `hr.services.decide_leave` and `cancel_leave` (POST routes, a dialog for the rejection
note), each in one transaction with its audit row, and every refusal leaves rows and log unchanged.

**Privacy.** A lead sees the person, the type and the days; the reason is the person's own words, shown to them and to the holders
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
record is a fact and the plan an intent: a person who is there but not planned is listed as present, "not planned". People planned off,
with nothing planned or on a day off are not listed (the source counted every unrecorded person absent, HR-12); pending leave is not
leave. Today shows the figures (planned, here, late, not in yet, absent, on leave) and the people; the board is a fragment the page
polls (`data-poll`, 30 seconds) and the server draws every number and every time, on the clock of each person's site. The person's own
**Clock in** and **Clock out** buttons need Read on Attendance and an employee row of their own, and are refused while a stretch is open
or none is.

**The Attendance page** lists the stretches of the viewer's team over the last fortnight or the days asked for, times on the site's clock,
with **Mark present** (Create: a person of the team, the times, the reason), a correction (Edit, logged with what it was before) and a
void (Delete). The page's heading is Attendance though it shares its permission with Today (the role matrix places the area under
HR dashboard, where its Read page first sits).

### HR dashboard › Organization chart (`/hr/organization/`) and Time & shifts › Team overview (`/hr/overview/`)

**Team overview** is the Shift schedule's week as numbers (`hr.read.overview`, built from the same cells and the same scope, so the two pages
cannot disagree): per person the days working, planned off and on leave, the planned hours and how many minutes they stand above or below the
standard week (a setting; a week over it is marked), and per day how many work, are off or are away. It has the week, department and search
filters and the "n of m" paging of the schedule, needs Read on the Shift schedule, and runs in a fixed number of queries.

**Organization chart** is the company as nested lists, drawn by the server (no script, no layout algorithm; the browser's print makes a
printed page of it): the sites with their production departments, then the office departments under their parents, each box with its manager
and the people in it, direct and in all below, counted among the people the viewer may reach (a lead's chart counts their own team). A
production department created, renamed or deleted under Production is in the chart at once, from the same rows.

**Rules the review of the branch added.** A record of a person belongs to the manager of the department the person was placed in
on the record's own day (`hr.scope.by_day`: a plan, a punch, a leave request), so a person who moved leaves their old records with
the old manager on every verb; the week names the department and the clock of the first day the viewer reaches, and its findings
are worked out from the days the viewer reaches only. A lead does not plan or write their own attendance (Everyone may). The
Manager of a production department and the account of an employee are chosen by those who administer HR (`hr.change_officedepartment`
or Everyone), because they decide whose rows and whose private words a person reaches. A pending request carries no decider and a
hand-entered note has words, as database checks; a decision note over 500 characters is an error on the page.

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
- **Tests** (`hr/tests/`): per model the create, read, edit, delete and restore round trips against stored rows with a test that
  names every column; the constraints through `IntegrityError` on raw rows, including both triggers, the open punch and the
  exclusions; the team scope by function and by URL for every actor (404 on every verb outside it, nothing written or logged, every
  route needs a row in the matrix or the suite fails); the boundary (no pay, bank, tax or identity column, form field, template word
  or import, and every free-text column named and masked); derived state at a fixed `now` for sites ahead of and behind UTC and the
  7 and 9 hour nights; the rules as pure functions; the services' refusals leaving rows and log unchanged; query budgets (the same
  number of queries for few and many people) on the Team list, Departments, the week, the overview, the chart, the board and the leave
  list; and the migrations back to nothing and forward again.

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
  also reviews an entry), Employees (read, create, edit, and Everyone), Departments (the office departments: read, create, edit, delete), Shift schedule, Attendance (read = Today & attendance and the Attendance page, create = enter presence by hand, edit = correct, delete = void), Leave requests (read, create, edit = also approves, rejects and cancels), Leave types, Shifts and Holidays (read, create, edit, delete; on the schedule Edit changes a plan and Delete clears a cell) and Scheduling settings (read, edit) and Activity log (read).
  A new tab appears in the matrix by
  adding its line there. The matrix groups the areas where the menu puts their pages (e.g.
  `Production · Setup · Facility structure`); the grouping is not written a second time. Roles and
  users are not areas, so no role can grant them.
- **Roles** (`/roles/`, Django `Group`): a table with each role's users and what it allows; the
  dialog has the name and a permission matrix (areas by group, columns Read / Create / Edit /
  Delete, and Everyone where an area offers it: see Row scope). Create, Edit, Delete and Everyone include Read: the form adds it and the browser ticks it. Saving
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
(`farm`, `inventory`, `knowledge`, `messaging`, `reports`, `tasks`, `core`, `auth`), so a tab that is ported later appears with no new code, in the section its
app belongs to. The tables of other apps (sessions, the Django admin's log) are not shown at all.
Everything the query string names is checked against the table's real columns and the rows come
through the ORM.

**Sensitive data.** `config/database.py` lists the masked columns (`auth_user.password`, and
`messages.body`: what people write to each other, see Messages). A masked
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
defaults match the local container in `docker-compose.yml`. Uploaded files (the library's PDFs) go to
`MEDIA_ROOT`: `DJANGO_MEDIA_ROOT`, by default `media/` in the checkout (ignored by git); keep it outside the
checkout anywhere but a developer's machine, and back it up with the database.

## Languages

English is the source language of every text in the code and templates; Norwegian bokmål (`nb`) and
Turkish (`tr`) are translations kept in `locale/<language>/LC_MESSAGES/django.po`. A visitor gets the
language of the cookie set by the switch, otherwise of the browser, otherwise English; a signed-in
person's choice is also saved on their account (`Profile`) and the admin can set it on the user form,
so an invitation email arrives in the new person's language. Numbers and dates follow the language
(`60,3913`, `2. november 2026`). The activity log is stored in English and shown translated.

GNU gettext is not needed: `manage.py update_catalogs` and `manage.py compile_catalogs` (Babel) do
what `makemessages` and `compilemessages` do; they skip the system checks, so they run without the
database (the other commands' checks ask the database for its version, which a generated column needs:
`makemigrations` without a database needs `--skip-checks`). How to add a string or a language, the glossary and the
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
  implementation, and `watch(element)` is what other scripts import. Every request has a 20 s timeout, each
  wait a few per cent shorter or longer by chance (screens never line up), a failure doubles the wait up to
  a minute, nothing is asked while the page is hidden, one shared listener serves every element and an
  element that left the page is let go. The element carries `data-poll-state` (`live`, `stale` after two
  failures in a row, `gone` after a 401, 403, 404 or a redirect to sign-in, with a bubbling `poll:gone`
  event), so the page's CSS can say so in its own words (the script has no text); the event `poll:now`
  asks at once (`detail.url`: the address from now on); `data-poll-merge="<attr>"` replaces a keyed child
  only when its markup differs, inserts a new key where the answer has it and drops a child the answer
  lacks (focus stays on the same id; an unkeyed child in the answer replaces everything);
  `data-poll-skip-same` leaves an answer equal to the last alone. Messages' append mode and the
  calculator's live form are unchanged, and pinned by `core/test_frontend_contract.py`, which also checks
  that every hook a template uses is one the script documents and reads.
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
are scoped (HR's Employees), it implies Read like Create, Edit and Delete, and the scope function reads it as
"no limit". A tab's `private_fields` name form fields that hold a person's own words (a leave reason, a
punch's note): the activity log says "Private text" for a filled one and never stores the words, so it shows
that the field was set, replaced or cleared, not what it says (a short keyed digest of the text is kept so that
a replacement is a change the log shows). A tab can also refuse a verb on a record it reaches (`Resource.allowed`: HR
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

### Shared form parts

What one tab needed and the next ones will too lives in `core/`:

- `TabbedForm` (`core/crud.py`): inner tabs, fields grouped under a heading (`Fieldset`), a word per
  tab (`tab_help`), fields chosen once (`fixed_after_creation`) and fields that change the form itself
  (`refresh_on`: the form is posted with a `_draft` marker and rendered again from the values entered so
  far, nothing validated or saved; the values travel in the request body, never in the address; the
  marker names the field that changed and the form comes back on that field's tab). A form can drop
  fields for one record (a pond has no diameter): the tabs show the fields it kept.
  A unique constraint among live records, on fields or on an expression (a species' scientific name
  in any case, `Lower(...)`), is checked on the form by the constraint itself, with its message on
  the field. A model with an `entry_key` field gets a hidden key on its new-record form, stored with the
  record: the same form sent twice (a double click, a retried request, two at once) creates one record and
  the second sending opens it (`core.crud.ENTRY_KEY`, a task, a recurring task).
- `Output` (`core/widgets.py`): a value the form shows but nobody types (a unit's volume), on a
  disabled field so a posted value is never read.
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
- `RowList` (`core/crud.py`): rows a record owns, edited as one list on a tab and saved together,
  replacing the stored rows, logged on the record (a site's contacts, a feeder's calibrations, a feed's
  suitability). A record's contact persons are one shape for every record that has them
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
| `/tanks/` | Facility › Tanks, ponds & cages |
| `/species/` | Reference data › Species |
| `/feeds/` | Reference data › Feeds; `<id>/suitability/` saves the species and fish weights a feed suits |
| `/suppliers/` | Purchasing › Suppliers; `<id>/contacts/` saves a supplier's contact persons |
| `/operations/units/` | Operations › Production units; `?unit=<id>` opens a unit's drawer |
| `/operations/monitoring/` | Operations › Monitoring: a live card per unit, simple or detailed; `?wall=1`, `?site=`, `?department=`, `?system=`, `?kind=`, `?occupancy=stocked\|empty\|all`, `?mode=detailed`, `?flip=<id,id>`, `?units=<id,id>`, `?q=` |
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
| `/operations/water/` | Operations › Water chemistry: the latest water per point; `?view=history` the samples, `?unit=<id>`, `?system=<id>` or `?equipment=<id>` an owner's history (every point of it), `?point=<id>` one point's |
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
| `core/widgets.py`, `core/links.py` | `DependentSelect`: a choice that belongs to another field's value (a production department to its site); `Output`: a value shown, not typed; `LinkList`: check boxes for a record's links, with their details |
| `core/fields.py` | Model fields the tabs share: `ChoiceArrayField`, several choices stored as an array |
| `core/people.py` | People as the pages name and offer them: a person's name, and the active users who hold a permission (tasks' assignees, an experiment's team) |
| `core/codes.py` | The next generated code of a kind of record (a batch's, an experiment's), under an advisory lock |
| `core/schema.py` | Fields described by a schema (a type's specifications): the form fields and the check of stored values |
| `farm/equipment_types.py` | The equipment type catalogue, written into the database by migrations |
| `farm/models/stock.py`, `farm/stock/` | The stock ledger: batches, operations and their lines; the fold (`fold.py`), reading it (`read.py`), the one write path (`services.py`), the integrity check (`integrity.py`, `manage.py check_stock`), the Production units page and dialogs (`views.py`, `farm/forms/stock.py`, `farm/templatetags/stock.py`) |
| `farm/models/feeding.py`, `farm/feeding/` | The feeding records: the walk of the feed along the stock's timeline (`fold.py`), reading it for the pages, FCR and the feed rate (`read.py`), the one write path (`services.py`), the Meal board, Records and the dialogs (`views.py`, `farm/forms/feeding.py`, `farm/templatetags/feeding.py`); the farm's dates shared with the stock (`farm/stock/dates.py`) |
| `farm/models/feeding_protocol.py`, `farm/feeding/` | Feeding protocols and assignments: the ration on read (`ration.py`), the estimated weight kept along the walk (`projection.py`), the temperature a ration reads (`temperature.py`), the table's write path and Duplicate (`protocols.py`), the assignments' rows and write path that the dialog and an experiment's start share (`assignments.py`); the tabs (`farm/resources/feeding_protocol.py`, `farm/forms/feeding_protocol.py`) |
| `farm/models/health.py`, `farm/health/`, `farm/handling/` | Fish health: medicines, treatments, health events, lice counts; the disease catalogue (`diseases.py`), the statutory lice rules (`lice.py`), the withdrawal worked out on read (`withdrawal.py`), the lice weeks and the records' days (`read.py`), the one write path (`services.py`), the pages and dialogs (`views.py`, `farm/forms/health.py`, `farm/resources/medicine.py`, `farm/resources/health_event.py`, `farm/templatetags/health.py`); the withdrawal registry the harvest side reads (`farm/handling/withdrawal.py`) |
| `farm/models/water_point.py`, `farm/water/points.py`, `farm/forms/water_point.py`, `farm/resources/water_point.py` | Sampling points: the model with its kinds, flow roles and rules, the default points and the share report, the form and the tab |
| `farm/models/water.py`, `farm/water/` | Water chemistry: samples and limits; the parameters (`parameters.py`), the chemistry worked out from a sample or the calculator (`chemistry.py`), judging on read (`evaluate.py`), the one read API of the samples: the latest values, the history, a unit's water and where its temperature is read from (`read.py`), the one write path (`services.py`), the Water Quality Management Chart (`deffeyes.py`), the small charts (`charts.py`), the dosing (`dosing.py`), the calculator's one calculation and a point's values for it (`calculation.py`), the page, the calculator and the dialogs (`views.py`, `farm/forms/water.py`, `farm/templatetags/water.py`) |
| `farm/models/harvest.py`, `farm/harvest/` | Harvest: slaughter facilities, a harvest's record, production plans and plan items; the Harvested list and its totals (`read.py`, `views.py`), the drawer's harvest part; the plan pages (`farm/resources/harvest_plan.py`, `farm/forms/harvest.py`) |
| `farm/models/handling.py`, `farm/handling/` | The handling check: the withdrawal registry (`withdrawal.py`), fasting, the purging in degree-days, when feeding must stop and the fasts plans ask for (`fasting.py`, `start_of_fast`, `fasting_on`), the check, the earliest suitable harvest date and the acknowledgement (`check.py`); the handling rules tab (`farm/forms/handling.py`, `farm/resources/handling_rule.py`) |
| `farm/placements.py` | The placement registry: the chip an app puts beside a unit (the experiments', on Production units, its drawer and the meal board); fails open |
| `farm/water/degree_days.py` | The batch's daily mean water temperature and the degree-days it adds up to (a past day without a measurement at the species' assumed temperature, else 0 °C; a day ahead projected): the one definition the medicine withdrawal and the purging fast share |
| `inventory/` | The store (its own app): storage locations, items, lots and the ledger (`models.py`), the fold (`fold.py`), reading it for the pages (`read.py`), the one write path (`services.py`), the integrity check (`integrity.py`, `manage.py check_inventory`), the location tab (`resources.py`), the page and dialogs (`views.py`, `forms.py`, `templatetags/inventory.py`, `templates/inventory/`) |
| `reports/` | Regulatory reports (its own app): the models (`models.py`), the kinds (`kinds.py`) and periods (`periods.py`), each report's computation from the records (`compute/`), the filing and corrections (`services.py`), what is due (`due.py`), the exports (`exports.py`), the check (`integrity.py`) and the provider the health records read (`health.py`) |
| `messaging/` | Messages: models (`models.py`), the one write path (`services.py`), the reads (`read.py`), the event a push or an AI assistant listens to (`events.py`), the pages and fragments (`views.py`, `templates/messaging/`, `static/css/messages.css`) |
| `tasks/` | Tasks and recurring tasks: models (`models.py`), the place as a choice (`places.py`), the one write path and the planned tasks (`services.py`), overdue and the views on read (`read.py`), the tabs (`resources.py`, `forms.py`), the drawer's actions and the overview tiles (`views.py`), `manage.py generate_tasks`, `templates/tasks/`, `static/css/tasks.css` |
| `experiments/` | Experiments (its own app, reading the farm): the design, the placements and the team (`models.py`), the endpoints (`variables.py`), the tab, its design view and its team list (`resources.py`, `forms.py`), what is wrong with a design (`design.py`), the seeded deal (`allocation.py`), the reads that every figure goes through and the deviations (`read.py`), the check of every started experiment (`integrity.py`, `manage.py check_experiments`), the write path of the design and the places (`services.py`), the constraints and composite keys (`migrations/0001_initial.py`), the triggers that freeze a started design (`migrations/0002_design_frozen.py`), `templates/experiments/`, tests, `docs/experiments.md` |
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
