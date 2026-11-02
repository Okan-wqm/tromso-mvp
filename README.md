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
  and **Production** (overview, production departments, systems, equipment, tanks, ponds & cages,
  species, feeds, water limits, suppliers, and under Operations the production units with their fish, the
  feeding records and the water chemistry). Each has its own overview. A
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
- The hand-typed tank count is not carried over: it would drift from the real tanks. The list counts
  the units in each system instead (linked to the units list). The second status flag `isActive` is not
  carried over either.
- A system cannot be moved to another production department while units of another are in it.
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
batches) are on Operations › Production units. A table (unit, kind with its shape or type, production department
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
- Code and regulatory unit ID are unique among live units, as database constraints; a deleted unit can
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
- **Regulatory**: the official code (artskode), and the cleaner-fish type (lumpfish or wrasse).
- **Status and notes**: active, experimental, inactive or discontinued; notes. Active and
  experimental species are the ones a new batch can take (Production units).

The species catalogue (`farm/species_catalog.py`) knows the 13 species Norwegian farms grow or stock
(salmon, rainbow and brown trout, Arctic char, cod, halibut, turbot, seabass, seabream, lumpfish and
three wrasses). When a species is created under one of these scientific names, or renamed to one,
the fields left blank are filled in from it (local name in Norwegian, family, water environments
when none is ticked, cleaner-fish type, official code) and the message after saving lists them;
a typed value is never replaced, and an edit that keeps the name fills nothing, so every field can
be cleared. Official codes are filled in only for the nine grow-out species (FAO ASFIS, e.g. SAL);
the four cleaner-fish codes of the source are unverified and never filled in (SPC-32). A catalogue
species cannot be given an official code other than its verified one. No species rows are seeded
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
  starter, fry, grower, finisher, broodstock, medicated, other), pellet size in mm, buoyancy (floating,
  slow sinking, sinking, or not stated), status (active, inactive, discontinued).
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
conditions, where it is kept), purchase orders, feeding tables and curves (feeding rate and FCR per
temperature and fish weight) and the feeding records.

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
Reference data › Feeds), and like bought fish, a supplier that makes live feeds cannot be deleted. The
three links are each a `SupplierLink` (`farm/models/supplier.py`): one declaration per link holds the
category it takes (`limit_choices_to`, the model's validation and the form's list) and the words the
supplier's form says when the category must stay ticked; `Supplier.clean` checks every such link, so a
new link adds no code to the supplier.

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

**The drawer** (`?unit=`), beside the table: the unit's code, name, place, status and since when; for a
stocked unit its batches, "Stocked · N days", fish, average, biomass, bFCR and eFCR, survival, the density
bar against its max with the volume, a line per batch (fish, average and when it was weighed, biomass,
survival, deaths and culls, the feed of its stay and its bFCR, its share of the unit), its feeding (see
Feeding records) and the operations, **Record feeding** first; for an empty unit its volume, max density
and max biomass and "Stock this unit" with the unit chosen, or why it cannot be stocked; for every unit
its last 20 operations and 10 feedings, voided ones struck through with their reason, each with **Void**
while it may be voided.

**Operations**, each a dialog (in the shared dialog, or as a page) whose form is one call of the stock
service, with the server's reason on the field it concerns: a new batch (species, stage at input,
stocking date, fish arriving and their average weight, origin, supplier and its batch number, strain,
name, expected harvest, notes, and the units the fish go into, whose fish must add up to the fish
arriving); mortality (fish, cause, the weighed kilos if known); cull (fish, reason); a sampling
weigh-in (fish weighed and their weight together, or a measured average); transfer / split (to one or
several units, a reason); grading (per size class a unit, fish and measured average, and the average of
the fish that stay); harvest (fish and their weighed kilos; "this empties the unit of this batch"
records the fish the book still holds as an unaccounted loss). A unit holding two batches asks which one.
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
several batches of it), then writes and folds every batch involved from its first line, so a backdated
operation is accepted only if every later day stays right (no share ever below 0 fish, and every feeding
recorded in the unit still finds fish there on its day: "The feeding of 2 Nov in T-01 would have no fish:
void it first."); above a unit's max biomass it asks for an acknowledgement, stored on the operation. The unit's status follows its fish:
the first fish make a preparing or fallow unit active, the last fish out make an active one fallow and
a harvesting or quarantined one due for cleaning; a void that brings fish back makes the unit active.
Every operation, every void and every status change is in the activity log ("Voided", with the reason).

**Void** is the undo: the operation stops counting, the stock is folded again without it, and it is
refused when later operations need its fish (the message names them). A correction is a void and a new
entry. Voiding a stocking voids its batch; a batch number is never given twice. The admin shows voided
operations and batches but does not restore them (a restore would skip the checks).

**Who may do what:** the area Production units in the role matrix (Production · Operations): Read the
page, Create records an operation, Delete voids one. A unit with fish cannot be deleted, nor resized,
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
- Not ported: the cleaner-fish track (later, as batches of a cleaner-fish species), sensors and water
  temperature, harvest plans, lot numbers, buyers and prices, the
  medicine-withdrawal block on harvest (**it must come back with the health module before real
  harvests**), batch documents and costs, count adjustments as a dialog (their lines and checks exist).

### Operations › Feeding records (`/operations/feeding/`)

Table `feeding_records`: feed given to one unit on one day, the farm's daily feeding record. A record is
the unit, the day, the feed (an active feed of Reference data › Feeds) and the kilos given, to the gram,
and optionally the time, the number of meals, the feeder and notes; several a day are fine (meals, a feed
change mid-day). **No batch is stored**: the batches a record fed are the batches the stock ledger has in
the unit that day, the feed split between them by their book biomass at the start of the day (at its
end when the unit was empty that morning, the day it was stocked). A backdated stock operation therefore
never leaves a stored batch wrong, and nothing is written back into the stock: feed never changes a count
or a gram of the book (only measured weights enter it).

**Recording.** "Record feeding", the first and primary button of a stocked unit's drawer on Production
units, or **Record feeding** on the list (it lists the units with fish). The dialog has the date (the
farm's today), the feed (the active feeds; those whose suitability rows suit the fish's species and
average weight first, the others under "Other active feeds": choosing one of those is allowed and
noticed), the kilos (`0.035` for 35 g), meals, time, feeder (a feeder of the unit's site) and notes. A
unit with two batches says how the feed is split ("Split by the book biomass at the start of 2 Nov:
B-2026-001 71 %, B-2026-004 29 %"). The rules, in one write path (`farm/feeding/services.py`), each with
the server's reason on its field:

- the date as for the stock: the farm's today at the latest, at most `STOCK_BACKDATE_DAYS` (31) back;
- the unit must hold fish at the start or the end of that day (from the stock ledger); and the other way
  round, a stock operation (a backdated harvest or transfer, the void of the stocking that brought the
  fish) is refused while a recorded feeding would be left without fish, naming it;
- a new record takes an active feed; a record keeps its feed whatever the feed's status becomes;
- above `FEEDING_ACK_PERCENT` (10 %) of the unit's book biomass in a day, the person is asked to confirm,
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
- In the drawer: fed today (kilos, meals), the last 7 days' kilos and the **feed rate** (SFR, % of the
  biomass a day = 100 × feed / the sum of the book biomass of the days with fish; the book does not grow
  between weighings, so it reads high as the last weighing ages, and the drawer says how old it is), the
  feed in use, each batch's window ("1 Oct – 15 Oct, 168 kg fed, 196 kg grown") and its last 10 records.
- The production overview: feed today and over the last 7 days on the whole farm.

**Who may do what:** the area Feeding records in the role matrix (Production · Operations): Read the list
and the feeding part of a unit's drawer, Create records a feeding, Delete voids one. A feed or a feeder
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
- Not ported: planned amounts and variance, waste, cost and currency, method, environment, behaviour,
  duration, verified-by, the meal board, day plans, protocols and feeding tables, feed stock (lots,
  deductions), the feeder's shots and calibrations (the feeder is recorded, the kilos are typed), a
  daily feeding sheet for all units of a department, the batch page's FCR, SGR and alerts.

### Operations › Water chemistry (`/operations/water/`) and Reference data › Water limits (`/water-limits/`)

The water samples people take, in a unit or in a system's loop (at the sump), and the limits the owner
sets per species. Tables `water_measurements` (a TimescaleDB hypertable) and `water_limits`.

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
parameter, empty when not measured, at least one value (a database check). The point is a unit or a
system, exactly one (a database check). The time is on the clock of the point's site, never in the
future and at most 31 days back (`STOCK_BACKDATE_DAYS`, `farm/stock/dates.py`), the rule of every daily
record; the source is a meter or kit, or a laboratory; the person is the one signed in. A form sent twice
records once (its key, stored with the time). Samples are never edited: **Void** (with a reason, logged as
"Voided" like a stock operation) and a new entry correct one; a voided sample stays in the history, struck
through. The only writer is `farm/water/services.py`.

**The hypertable.** `water_measurements` is a TimescaleDB hypertable on `measured_at` (90-day chunks),
made by one `RunSQL` in migration `farm/0014_water`, which depends on `core/0001_timescaledb` (the
migration that runs `CREATE EXTENSION IF NOT EXISTS timescaledb`). Its primary key in the database is
`(id, measured_at)`, as a hypertable's must be, while Django's model keeps `id`, so `makemigrations
--check` stays clean (a test runs it). The rules that follow are in the model's docstring: every unique
constraint includes `measured_at`, no foreign key points at the table, compression is left for later.

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
  water it equals Emerson et al. (1975) within 0.002 pK. It needs the pH and the temperature of the same
  sample; the salinity is the sample's, else the point's latest within 30 days before it, else 0 where
  every unit is in fresh water; otherwise the page says what is missing. NH₄-N = TAN − NH₃-N is shown.
- **Oxygen saturation**: Benson & Krause (1984) as in Standard Methods 4500-O, corrected for the
  barometric pressure of the site's altitude (sea-level pressure, said so, when the site has none). From
  mg/L the % is worked out, from % the mg/L; when both are entered and differ by more than 10 %, both are
  kept and flagged.

**The page** has two views: **Latest** (every unit and every loop with a sample in the last 30 days, its
status and the latest value of each parameter, coloured by status, its time and age on hover; a filter by
site) and **History** (the samples, newest first, 50 a page, filtered by site, unit or loop, dates, and
"only warnings and criticals"; each value coloured as judged now, worked-out values in italics; Void
while the sample is in the window). **Record sample** opens the dialog (date and time on the site's
clock, source, the twelve values in four groups, notes; from a unit's history the unit is fixed and each
field's help shows its species' limits). **Round** is the morning round: a site and optionally a
production department or a system, the columns to fill (temperature and oxygen by default), one row per
unit that is not inactive and per loop, one time and one source; empty rows are skipped, a value out of
range is shown in its cell and nothing is recorded until every cell is right (at most 200 rows).

**Who may do what**: the area Water chemistry (Production · Operations): Read the page, Create records
a sample or a round, Delete voids one; the area Water limits (Production · Setup · Reference data) with
read, create, edit and delete.

**Deleting**: a unit or a system keeps its samples, out of sight while it is deleted (the link is
`DO_NOTHING`; the confirmation counts them) and back when it is restored, as its stock lines are; a
species takes its water limits with it, each listed and logged. The admin shows voided samples but does
not restore them.

**The MVP alerts nobody.** A critical value is shown on the page (and, with Production units, on the
unit), never sent: there is no email, SMS or push, no acknowledgement and no escalation. Someone has to
look.

Differences from the source (details in the bug document, WQ-01 to WQ-29):

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
- Not ported: sensors and their reading sources (points, positions, channels), charts and daily means,
  notifications, the Deffeyes calculator and dosing, H₂S, hardness and the other lab parameters,
  detection limits ("< 0.02"), attachments, limits per life stage or site, a sampling plan per unit,
  and a site's intake water. The feeding tab is to read the latest water temperature from here and keep
  no copy of its own (WQ-02).

## Roles and users

There are no built-in roles. The platform admin (a Django superuser) can open everything and is the
only one who manages roles and users; everyone else gets exactly what their roles allow.

- **Access areas** (`config/access.py`, read by `core/access.py`): the parts of the console a role
  can be given, one line each, with the actions each offers: Sites, Production departments,
  Systems, Equipment, Tanks, ponds & cages, Species, Feeds, Water limits and Suppliers (read, create,
  edit, delete), Production units (read the page, create = record an operation, delete = void one),
  Feeding records (read, create = record a feeding, delete = void one), Water chemistry (read the page
  and a unit's water, create = record a sample or a round, delete = void one) and Activity log (read).
  A new tab appears in the matrix by
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
headings, as in the platform: **Setup** (the farm's structure under Facility structure, the
reference lists the production side picks from under Reference data, and the suppliers under
Purchasing) and **Operations** (the daily
production records; it appears with its first tab). The source calls the reference lists "Records";
the prototype does not, because Operations holds the daily records. The menu is the one place that says
where a page sits: the role matrix and the small heading above a tab's title follow it
(`core.navigation.place`). There are no built-in roles: the platform admin creates roles
and grants permissions.

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
confirmation counts them, and they come back with it.

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
  the field.
- `Output` (`core/widgets.py`): a value the form shows but nobody types (a unit's volume), on a
  disabled field so a posted value is never read.
- A tab's page heading is what the menu calls it (`Resource.title`, from the menu entry), so
  "Tanks, ponds & cages" lists units.
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
| `/tanks/` | Facility › Tanks, ponds & cages |
| `/species/` | Reference data › Species |
| `/feeds/` | Reference data › Feeds; `<id>/suitability/` saves the species and fish weights a feed suits |
| `/suppliers/` | Purchasing › Suppliers; `<id>/contacts/` saves a supplier's contact persons |
| `/operations/units/` | Operations › Production units; `?unit=<id>` opens a unit's drawer |
| `/operations/units/new-batch/` | A new batch (`?unit=<id>` chooses the unit) |
| `/operations/units/<id>/<operation>/` | An operation on a unit's fish: `mortality`, `weighing`, `transfer`, `grading`, `cull`, `harvest` |
| `/operations/units/void/<id>/` | Voids a stock operation |
| `/operations/units/<id>/feeding/` | Records a feeding of a unit (`?next=` goes back to the page it came from) |
| `/operations/feeding/` | Operations › Feeding records |
| `/operations/feeding/new/` | Record feeding from the list: the units with fish |
| `/operations/feeding/void/<id>/` | Voids a feeding |
| `/operations/water/` | Operations › Water chemistry: the latest water per unit and loop; `?view=history` the samples, `?unit=<id>` or `?system=<id>` one point's history |
| `/operations/water/record/` | Record a water sample (`?unit=<id>` or `?system=<id>` chooses the point) |
| `/operations/water/round/` | A water round: the units and loops of a site, production department or system |
| `/operations/water/void/<id>/` | Voids a water sample |
| `/water-limits/` | Reference data › Water limits |
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
| `core/schema.py` | Fields described by a schema (a type's specifications): the form fields and the check of stored values |
| `farm/equipment_types.py` | The equipment type catalogue, written into the database by migrations |
| `farm/models/stock.py`, `farm/stock/` | The stock ledger: batches, operations and their lines; the fold (`fold.py`), reading it (`read.py`), the one write path (`services.py`), the integrity check (`integrity.py`, `manage.py check_stock`), the Production units page and dialogs (`views.py`, `farm/forms/stock.py`, `farm/templatetags/stock.py`) |
| `farm/models/feeding.py`, `farm/feeding/` | The feeding records: the walk of the feed along the stock's timeline (`fold.py`), reading it for the pages, FCR and the feed rate (`read.py`), the one write path (`services.py`), the list and the dialogs (`views.py`, `farm/forms/feeding.py`, `farm/templatetags/feeding.py`); the farm's dates shared with the stock (`farm/stock/dates.py`) |
| `farm/models/water.py`, `farm/water/` | Water chemistry: samples and limits; the parameters (`parameters.py`), the values worked out from a sample (`chemistry.py`), judging on read (`evaluate.py`), the latest values and the history (`read.py`), the one write path (`services.py`), the page and dialogs (`views.py`, `farm/forms/water.py`, `farm/templatetags/water.py`) |
| `farm/species_catalog.py` | The species catalogue: fills the blank fields of a known species; data in code, no rows |
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
