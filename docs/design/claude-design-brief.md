# Suderra: design brief for Claude Design

## 0. The owner's goal

**"The world's best management-program dashboard."** Every screen below is judged against that sentence: a fish farm's whole day (fish, feed, water, health, people, research, the authorities) in one calm, legible console that a newcomer reads at a glance and an operator trusts with wet hands at the tank side.

This brief was refreshed on 5 Nov 2026 against main `c295bb3` plus Production › Team (`fd49eed`), and on 6 Nov 2026 against main `b24de24` with the **Sensors panel live** (29 simulated devices, 232 channels, a reading a second from a Node-RED field simulator), running on a seeded demonstration company, **Nordhav Akva** (fictional: 40 people, 6 office and 7 production departments, two sites Bergen Hatchery BH-01 and Tromsø Grow-out TG-02, 23 units, three trials, 131 tasks, 12 conversations, filed reports). Screenshots: `ekran-goruntuleri/` (section 16 has the index; old ones are in `_eski/`).

## 1. Product, users and the bar

Suderra is fish-farm management software, now an MVP. Operators record feeding, mortality, water samples and storage at the tank side on tablets, with wet hands and glare. Managers, fish-health vets and researchers work at desktops; HR and team leads plan people; the quality manager files reports to Mattilsynet and Fiskeridirektoratet. Investors will decide within minutes whether it is world-class.

The owner's bar: "ultra professional, readable, organised, harmonious colour and spacing, the best system in the world." Our tests: a newcomer finds the five numbers that matter at a glance; nothing clips or hides; one image is remembered. Keep the sage-grey canvas and the login's trout-skin artwork; replace today's crimson-for-everything palette and clipped tables (section 17 lists where the shots show clipping today).

## 2. Design principles

- **One job per colour.** Red means critical only. Blue marks what you can follow or select. Olive-black is structure and the single commit button per view. Rose is the brand and never touches data.
- (Amended 2026-11-21 by the owner's "colourful, clear, organised": colour now runs in two channels that never mix, area hues for where you are in the chrome and status colours for what is wrong; the rule below still holds for values and cards. See docs/design/system/README.md, Principles.) **Grey by default, colour only for the abnormal** (ISA-101, the high-performance HMI rule). A normal value is ink on white; only a warning, critical or stale value earns a tint. This applies everywhere, the monitoring cards most of all.
- **Status is shape, word and fill weight; colour comes third.** It survives greyscale, colour blindness and glare.
- **Five numbers never wrap, clip or hide:** unit, decision figure, status, next action, age.
- **Every value says where it came from and how old it is** (Sensor, Manual, Lab; "2 d ago"); "no data" is a word, never a dash or 0.
- **Quiet by default.** OK is a small check, empty is dashed, only problems take colour. Boldness goes into one object, the Deffeyes plate.
- **Safety stays visible.** Limits come from their real bounds; "Nobody is alerted" is stated. Warnings never block; an acknowledged one is logged as critical, visibly.
- **Say why when something is absent.** "Hatchery is not a sea site", "12.3 °C is outside this table (8.0–12.0 °C)", "Water: not shown to you". Never an empty cell with no reason.
- **Tank side first, boardroom second.** Big touch targets, three taps to record the next meal, legible on a projector and on a wall screen.

## 3. Identity

**Source:** the rainbow trout already painted on our login: olive-black back, silver flank, white belly, one rose lateral band. Back becomes ink and rail, silver the canvas, belly the sheet. Rose survives only in the wordmark, a 4 px stripe atop the rail and the login artwork. **The one memorable element is the Deffeyes plate** (section 5): the only place with large coloured areas and hatching.

### Colour

Day is the default and what investors see. Night is a second theme set by cookie, never by the OS. Ratios are computed (WCAG 2.x), Day / Night.

| Role | Day | Night | Contrast |
|---|---|---|---|
| Canvas | #EEF1EA | #131A15 | sheet on canvas 1.14 / 1.11, so frame the sheet with the hairline |
| Sheet (one per page); sunken (table head, wells, hover) | #FFFFFF; #E4E9DD | #1B241E; #232E27 | |
| Rail; text on rail | #1F2A1C; #E4EADC | #0E140F; #B7C2AE | 12.16 / 10.08 |
| Hairline; control border | #C6CEBA; #7C8873 | #33403A; #6C7A63 | hairline 1.62 / 1.47; border 3.02 / 3.09 on sunken, the worst case |
| Text 1, 2, 3 | #1F2A1C, #3E4A38, #5A6553 | #E6ECE0, #B7C2AE, #8E9A86 | on sheet 14.93, 9.37, 6.14 / 13.23, 8.61, 5.40; Text 3 on sunken 4.97 / 4.77 |
| Primary button; hover | #1F2A1C; #33422F | #E6ECE0; #F4F8EF | white on it 14.93 / 10.71; Night text #131A15 14.70 / 16.45 |
| Action (link, selection, focus); tint | #1D4E89; #E3EBF5 | #86B6EE; #1E2D44 | 8.39 / 7.54 on sheet; on tint 6.98 / 6.56 |
| Brand rose on rail | #E27C95 | #E27C95 | 5.37 / 6.71; login band artwork #B8455F |
| OK mark; text on tint | #1E7A57; #17654A on #E1F1EA | #4CC19A; #6FD3AE on #163A2D | 5.28 / 7.14; 6.00 / 6.92 |
| Warning mark; text on tint | #B77900; #7A5410 on #FBF0D9 | #F2C14E; #F0C36E on #3A2C10 | 3.65 / 9.50; 5.98 / 8.23 |
| Critical solid; text on tint | #A52A17; same on #FBE5E0 | #FF6A50; #FF9A85 on #3E1A14 | white on solid 7.13, Night #2A0C06 6.44; 5.91 / 7.49 |
| Series 1 to 5 | #3F8FD0, #1F2A1C, #8E3F7A, #6B7A2E, #3D3F9E | #8CC4F4, #E6ECE0, #D08BBE, #B5C45C, #7C86F0 | 3.47 or more / 4.95 or more; worst colour-vision ΔE 26 / 16 |
| Plate: safe zone, toxic zone, isoline | #DDEFE5, #F6E0DA, #5B6B7E | #163A2D, #3E1A14, #8FA6BF | isoline 5.46 / 6.36; hatch #A52A17 / #FF6A50 on toxic 5.64 / 5.45 |
| Shift tones 1 to 8 (roster chips only) | eight pale tints with ink text, chosen by the designer | same | text 4.5:1 on each tint; a tone is a CSS class, never a stored colour |

Warning against critical under deuteranopia: ΔE 23.5 Day, 19.8 Night. Focus ring: 2 px white inside, 2 px #1F2A1C outside (13.09); on the rail a white ring (14.93); Night outer #E6ECE0 (14.70). The app's own warning amber for text is #7A5410 (4.5:1 on white, pinned by a test); a warning dot or border must reach 3:1.

### Type

Two distinct families, self-hosted as woff2 (see open question 2: the app still uses Bricolage for everything).
- **Atkinson Hyperlegible Next**, 400 to 700, for everything read or entered: its 0, O, 1 and l differ, which matters for codes like HA-K01 on a glared tablet. Tabular figures on globally. It lacks µ, ₂, ₃ and ‰: use subscript markup (CO<sub>2</sub>) and let µ fall back.
- **Bricolage Grotesque** 600 only for h1, h2, wordmark and empty-state titles, 22 px and up; never for a measured value.

Scale (px): 12 chart ticks and captions only; 13 column heads and sub-lines (14 on coarse pointers); 15 body and cells (16 on coarse); 18/600 for the one figure per row people act on; 22 h2 and dialog titles; 28 h1 and the "Next meal" readout. Line height 1.45, headings 1.2; prose 68 characters; text left-aligned, figures right-aligned. Sentence case; no `text-transform` (Turkish İ and ı break), no all-caps, no monospace.

Space, 4 px base: 4, 8, 12, 16, 24, 32, 48, 72. Radius by role: 4 chips, 6 controls, 10 objects (sheet, dialog, drawer, tile, plate, card, window). Depth: flat, one overlay shadow `0 8px 24px rgb(15 22 12 / .22)` for menu, drawer, dialog and movable window. Icons: lucide-style inline SVG, 20 px in the rail at stroke 1.75, 16 px inline at stroke 2; a status glyph never appears without a word.

## 4. Components (prefix `ui-`; state in `data-status` and `data-state`)

**Buttons.** Height 40; on coarse pointers 48, primary 56. Primary is filled ink, one per view; row buttons are outlined. Red fill only in a destructive confirm, never beside edit. One name per action from label to confirmation: "Record meal", "Meal recorded". A tab that saves on its own (a medicine's Withdrawal) has its own one primary; the page's primary hides while that tab is open.

**Fields.** Label above (15/600), help below (13, Text 3), unit as an inside suffix, height 40/48. Error: red glyph and a sentence saying what to do ("Enter a pH from 0 to 14"), 2 px red border, linked by `aria-describedby`. A fixed value is read-only text with a lock and the reason, never a greyed select. **Tabbed forms:** a red dot on a tab with an error, a sticky Save and Cancel bar; overflowing tabs scroll with an edge fade, never clipping a label.

**Tables.** Row 40 (one line), 52 (two), 56 coarse. Head 13/600 Text 2 on sunken, sentence case, wraps to two lines, never `nowrap`; `nowrap` only on atoms (codes, figures, units). Numbers tabular and right-aligned, unit in the head ("Biomass (kg)"), non-breaking space before the unit; missing is "–", never 0; one precision per column (never "251.804 kg" beside "1,420 kg"). Priority: P1 always, P2 from a 640 px container, P3 from 960, P4 only in the drawer; tables over four columns become cards below 640 px, keeping table roles. A table that must scroll says so: `tabindex=0`, label, edge fade, sticky first column, and the row actions sticky at the right so Edit and Delete never scroll out of sight. Voided rows: values struck through, a "Voided" chip, the reason legible, excluded from totals. Unmeasured or empty rows fold into one group ("Not measured (8)"). Row actions are separate buttons with gaps, or one "More" menu, never words run together.

**Status chips** (24 px high, 13/600, glyph 16), a ladder of fill weight:
- OK: check-circle in the OK mark colour, no container; the word shows in summaries, screen-reader text elsewhere.
- Warning: tint fill, triangle, word "Warning".
- Critical: solid red fill, octagon, white word "Critical"; the row gets a 4 px red edge.
- Hold: outline chip in Text 2, hourglass or crossed utensils, with the date: "Withdrawal to 24 Nov", "Fasting until 06:00"; never red, never the triangle.
- Acknowledged hold: shield-alert, solid red: "Critical, acknowledged by Kari Nordmann, 2 Nov 14:05".
- Not measured: dashed outline and word. Stale ("No recent data"): clock and "3 d ago", never italics, never red.
- People states (HR): Upcoming, Not in yet, Present, Late, Absent, Done, On leave, Not planned: outline chips; only Absent and Late take the warning tint.
- Report states: Draft, Filed (with the time and receipt), Overdue (critical tint), Done (duty outside the system), Open (authority question).

A non-OK value shows glyph and number together: triangle 6.50, octagon 15.6. If over half the rows are critical, show a summary strip instead of edges. Counts are chips ("23 units"); rail badges are 20 px pills, red only for a critical count.

**Tabs and toggles.** Tab: 15/600, 3 px blue underline, 44 px target, with its count when it has one (section 13). Segmented toggles (Floor/Table, 7d/30d/90d, All/Tanks/Ponds/Cages): pressed is blue tint, 2 px blue border and a check. **Filter bar:** one row, search first; "Show voided" applies instantly; no duplicate "All". **Drawer:** 480 px from the right (560 when it holds a table), non-modal, table visible, focus moves to its heading, Esc closes and focus returns. **Dialog:** header, scrolling body, sticky footer with Cancel left of the primary; full-screen on phones; focus on the first invalid field, else the first; Esc or backdrop on a dirty form asks first; a failure keeps entries and carries Close. **Flash:** inline banner with glyph and word; success clears after 8 s, warning and error stay. **Empty:** dashed outline, purpose, the one action as a button inside. **Loading:** skeleton rows. **Error:** what happened, what to do, Retry. **Pager:** "Showing 51 to 100 of 1,204", Previous and Next at 44 px.

## 5. Data visualisation

Server-drawn SVG with CSS hooks, coloured by classes that read tokens. A quiet sea chart: pale tints, thin contours, direct labels with a white halo, no legends.

**One gauge grammar, `ui-gauge`.** Outlined track (3:1), a fill that is the value (neutral until a limit is crossed, then the status colour), an ink tick for the limit, the number beside it. Horizontal for storage cover, density ("7.4 kg/m³, 12 %") and sea lice (0.30 against a 0.5 limit); in a table it is 96 px wide, number first. The vertical "Level" (a tank profile) exists only on tiles 96 px tall or more: capacity runs to 120 % with the tick at 100 %, so overstock shows. No other chart goes in a table. The monitoring **limit bar** is the same grammar with four bounds (critical low, warning low, warning high, critical high), bands told apart by dash pattern as well as tone.

**Time series.** Small multiples: oxygen, pH, CO<sub>2</sub>, temperature, TAN with NH<sub>3</sub>-N; 104 px each, expandable to 240; shared time axis; one ink line. Draw every limit from its real bounds, up to four per parameter, coloured by the status it triggers: warning dashed amber, critical solid red 2 px, labelled at the line end ("Critical 15.0"). Source by marker: sensor a continuous line with a min-max envelope, manual a 6 px filled circle, lab an 8 px diamond; an out-of-range marker gets a 2 px status ring in a tinted band. A gap stays a gap, never zero. Series colours only overlay one parameter across units.

**The Deffeyes plate.** Alkalinity (meq/L, horizontal) against dissolved inorganic carbon (DIC, meq/L, vertical), range 0 to 6, zoomed by default to 0 to 3 with a "Full range" toggle. pH isolines in one slate hue, labelled. The two toxic regions (CO<sub>2</sub>, NH<sub>3</sub>) are hatched in critical colours with direct labels; the safe zone is a solid tint with a 2 px OK border, the strongest shape. The water is an ink dot with a white ring (14 px); the target is a blue cross. Tick text at least 11 rendered px: phone, drawer and the movable window get their own narrow 360 by 480 drawing. Today the chart is titled "Water Quality Management Chart" and keeps the source platform's rainbow isolines and orange fill (open question 3).

## 6. Screens of the first brief (still valid; updated)

**Prototype story data.** For the prototypes keep this story: Bergen Hatchery, Hatchery hall A; HA-K01 Smolt tank 1, batch B-2026-001, 15,850 fish, 66.2 g, 1,050 kg, 21.0 kg/m³ (limit 40); HA-K01 feeding: SFR 1.36 %, ration 14.28 kg, 4 meals planned, 1 done (3.70 kg fed), 10.58 kg left, next meal 3.53 kg of Sea Grow 9 mm, FCR 1.03; HA-K01 water sampled 16 h ago: CO<sub>2</sub> 16.9 mg/L (warning above 10.0, critical above 15.0); HA-K02 O<sub>2</sub> 6.50 mg/L (warning below 7.00); Sea Grow 9 mm 1,420 kg, 21,300 NOK, 57 days of cover; withdrawal to 17 Nov 2026; HA-K03 fasting until 06:00; today 3 Nov 2026. **The shots show the seeded company instead** (5 Nov 2026, Nordhav Akva): the same units with other figures, quoted in each section below. Both are fine as long as each prototype is internally consistent.

**App shell.** Dark olive-black rail with the rose stripe, wordmark and a Company/Production switch (today a dropdown "Suderra Production" at the top of the rail); a 56 px top bar with the EN/TR/NB switch and user menu (today the language switch sits in the user menu); the page sits on one sheet. Rail 240 from a 1280 px viewport; 72 (icons, label on focus) from 1024 to 1279 on fine pointers; otherwise a 56 px bottom bar (Meals, Water, Units, Storage, More) with the full menu as a sheet, hidden on full-page forms. The rail now has **sections and groups** (section 16 lists them): Company: Facility, Knowledge, Administration, then HR (HR dashboard; Time & shifts). Production: Setup (Facility structure, Reference data, Harvest and logistics, Purchasing), Operations (with Feeding, Harvest, Health), Research, Reports, Communication, Team (Time & attendance, People). Daily work first; Setup collapsed and remembered; the menu shows only the entries a person's role opens. Page head: eyebrow (section, page), h1 28, one status line of chips, the single primary action at right.

**Production overview** (`production-overview-home`). Today: a KPI tile row (19 stocked units, 311,665 fish, 137.9 t biomass, 848 kg feed today, 7.4 t feed last 7 days, 0 units with a critical water value, 1 task due today, 3 overdue, then 6 departments, 6 systems, 29 equipment, 23 tanks) and a placeholder "The production figures will appear here." Design target, superseded by the owner (Nov 2026: the overview is a dashboard of metric cards, docs/design/system/README.md, Do and do not): no KPI tiles. h2 "Today at Bergen Hatchery", then three sentences with figures at 18/600 ("19 of 23 units are stocked with 311,665 fish." "1 water point is critical and 6 are warnings." "3 units are on withdrawal."), then Needs attention, one row each (octagon HA-K02 side outlet "CO<sub>2</sub> 15.6 mg/L, limit 15.0, sampled 2 d ago" with Record water sample; clock HA-K03 "No recent data, 2 days old"; hourglass HA-K01 "Withdrawal to 24 Nov"), then the floor: units by department as 120 by 148 px tiles with the Level, code, fish count, density; empty units fold into "4 empty units". Add a small "Team today" line (22 planned, 4 here, 1 absent, 1 on leave) and "Reports: 1 overdue" linking to their pages.

**Company overview** (`company-overview-home`). Today: "2 Sites" tile, an Upcoming reports block ("Planned slaughter, Fjord Seafood Processing (N1234), Week 45 of 2026, 29 Oct 2026, Overdue" in red; "Disease, Tromsø Grow-out (TG-02), at once"; "Planned slaughter, week 47, 12 Nov 2026") and "Welcome, admin. The company's figures will appear here." Design it as the company's front page: sites with their state in one sentence each, reports due, people today (office), unread messages.

**Meal board, the daily heart** (`production-feeding-meal-board`). Filters: site, department, system. One muted line: "Over- and underfeeding are not flagged yet." The ration arithmetic folds into "How rations are worked out". One row per batch line. Columns (910 px): Unit 160 (code 15/600, department below, a trial chip "E-2026-002, EPA+DHA 1.0 %, low density, R1" when the tank is in a trial); Next meal 150 (3.53 kg at 28/600, "Sea Grow 9 mm"); Today 210 (four pips: done filled with a check, next ringed and labelled "Next", later dashed; "3.70 of 14.28 kg, 10.58 left"); Fish now, P3, 160 (15,830 fish, 66.2 g est., 1,048 kg); Water 100 ("12.3 °C", "loop RAS-1, 2 d ago", Stale clock); Record meal 130, outlined. One warning mark per row: HA-K02 "Estimate incomplete: 1 feeding day without an expected FCR". Protocol, SFR, FCR live in the drawer. **The "why no ration" state** is in every shot: "12.3 °C is outside this table (8.0–12.0 °C)", ration "0 kg", next "–": design it as a hold row (the why sentence where the next meal would be, Record meal still offered), not as zeros. Phone: a card per unit, "Next meal 3.53 kg" at 28, a 56 px full-width Record meal (today the phone shows the Unit column only, section 17).

**Record meal dialog** (`production-feeding-record-meal-dialog`). Today: "Record feeding, HA-K01, Smolt tank 1, 15,830 fish, 1,045 kg now"; Date, Feed (empty select, "The feeds that suit the species and average weight of these fish come first"), Feed given (kg), Meals, Time, Feeder, Notes; Cancel, Record feeding. Design target: amount prefilled from the next meal, feed prefilled with its stock ("Sea Grow 9 mm, 1,420 kg on hand"), time now; during fasting or withdrawal the acknowledge row of section 13.

**Production units** (`production-operations-units`, drawer `production-operations-unit-drawer`). Filter chips All sites / Bergen Hatchery / Tromsø Grow-out; All / Tanks / Ponds / Cages; All / Stocked / Empty; status. "23 units, 137.9 t". Table: Unit (code, state dot, Withdrawal chip, department and site), Batch (B-2026-001, Laks), Fish 15,830, Avg. weight 66.0 g, Biomass 1,045 kg, Density and capacity with gauge "7.4 kg/m³, 12 %", bFCR 1.24, Survival 99.2 %, Temp. 9.5, O<sub>2</sub> 9.30, Last fed 3 Nov 2026. Empty units: "Empty, ready to stock", "Empty, Maintenance". **Drawer HA-K01:** "Smolt tank 1, Hatchery hall A, Bergen Hatchery", Active since 2 Nov 2026, "B-2026-001, Laks, stocked 13 days"; metrics Fish 15,830, Avg. weight 66.0 g, Biomass 1,045 kg, bFCR 1.24, eFCR 1.28, Survival 99.2 %; density bar "7.4 kg/m³, 12 %, 140.7 m³, max 60 kg/m³, 8,445 kg"; Batches table (batch, fish, weight, biomass, survival, year class, farmed or wild-caught, Batch details); Feeding; Water by point with limits; actions Record meal, Record mortality, Weighing, Transfer / split, Grading, Record cull, Deliver fish, Harvest, Stock another batch. The drawer needs 560 px or a P1/P2-only batch table (today it squeezes into one-word lines). **Dialogs from the drawer:** Harvest (`production-operations-harvest-dialog`: Date, Fish harvested, Round weight (kg), "This empties the unit of this batch", Slaughter facility, Transport, Wellboat or vehicle, Notes, a Before handling box with last fed and the handling rule), Transfer / split (`production-operations-transfer-dialog`: Date, Reason "Density management", To units rows with Fish, Add unit, Before handling "Last fed 3 Nov 2026, 02:52; 45.1 h before 5 Nov 2026. The transport rule for Atlantic salmon asks for 24 h."), Batch details (`production-operations-batch-details`: year class, farmed or wild-caught).

**Water chemistry** (`production-operations-water-*`). Tabs Latest, History, Calculator; primary Record sample, secondary Round. *Latest:* on 5 Nov (manual samples only) "40 sampling points, 1 critical, 6 warnings"; since 6 Nov most values come from sensors with their origin and age (section 12.7: "40 sampling points, 4 warnings"); the safety sentence "Nobody is alerted: critical values are shown here, not sent." One row per **sampling point** (not per unit): "HA-K02 Side outlet, Hatchery hall A, Bergen Hatchery", Status, Temp. (°C), O<sub>2</sub> (mg/L), O<sub>2</sub> (%), pH, Alkalinity, CO<sub>2</sub>, TAN, NH<sub>3</sub>-N, NO<sub>2</sub>-N, NO<sub>3</sub>-N, TGP, Salinity, Turbidity, History. Real rows: HA-K02 side outlet Critical, 9.6 °C, 6.00 mg/L, 52.8 %, pH 7.33, CO<sub>2</sub> 15.6; HA-K03 middle Stale 12.0 °C; HA-K04 Not measured; HA-R01 "No limit" (no fish). Fourteen value columns cannot fit: P1 status, temperature, O<sub>2</sub>, CO<sub>2</sub>, pH; the rest in the drawer or a "More values" toggle. *History:* filter by site, unit, system or equipment and point; rows with Measured at, point, Source ("Meter or test kit, morning check before the first meal"), values; *point history* (`water-point`, "History of BIO-1, Loop"). *Record sample:* Sampling point, Measured at, Source, then grouped fields (Temperature and oxygen; Acid-base and CO<sub>2</sub>; Nitrogen; Gas and other) each with its help line. *Round* (`water-round`): choose a site, tick parameters and point kinds (Inlet, Depth point, Outlet, Side outlet, Bottom drain, Points of equipment), "Show the points": one form for a walk round many points.

**Calculator** (`production-operations-water-calculator`). Values from "Entered here" or a unit; tabs Water, System, Target, Limits, Reagents, Simulator; inputs temperature 12, pH 7.00, salinity 1, alkalinity 90, TAN 0.5, total sulfide 2; Defaults, Print report. Results: Un-ionised ammonia against pH, H<sub>2</sub>S and HS<sup>-</sup> against pH, CO<sub>2</sub>/HCO<sub>3</sub><sup>-</sup>/CO<sub>3</sub><sup>2-</sup> against pH, Calcite and aragonite saturation, the Water Quality Management Chart (Deffeyes) with "Show on the chart" toggles (pH isolines, safe zone, NH<sub>3</sub> toxic, CO<sub>2</sub> toxic, target, simulator path), then Ammonia, Hydrogen sulfide, Worked out from the values, Dosing recipes ("NaHCO<sub>3</sub> + NaOH ... per m³"). From 1280 px two columns: fields left, a sticky plate right at 600 px or more, redrawn live after a 300 ms pause; the small charts become a strip of three under it. On phones the plate comes first.

**Storage** (`production-operations-storage-*`). Tabs Overview, Stock, Movements, Counts; actions Receive delivery (primary), Transfer, Issue, Write off, Return to supplier, Count a location. *Overview:* On hand per site (Site, Item, On hand, Fed last 7 days, Days of cover): Tromsø Grow-out Sea Grow 9 mm 63,089.3 kg, 6,843.8 kg, 64.5 days; Bergen Hatchery Smolt Grow 3 mm 251.804 kg, 449.696 kg, 3.9 days; Low stock line ("Smolt Grow 3 mm in SI-02 (Bergen Hatchery): 251.804 kg, below the reorder level of 1,000 kg"); Value on hand (Bergen Hatchery 45,120.11 NOK; Tromsø Grow-out 1,153,573.92 NOK). *Stock:* per location and lot (FS-01 Feed store 1, Sea Grow 9 mm, lot L-471, expires 1 Mar 2027, 920 kg, last movement 3 Nov 2026, 13,800.00 NOK, row actions Transfer, Issue, Write off, Return). *Movements:* append-only ledger (Delivery, Transfer, Issue "Samples and analyses", Write-off "Damaged", Count, Return to supplier) with Void. *Counts:* a count per location with Book, Counted, Difference. *Item page* (`storage-item`: "Sea Grow 9 mm (SEA-9)", the day-by-day book per site) and *lot page* (`storage-lot`: "Trial diet EPA+DHA 2.0 % 3 mm (TD-EPA20), lot FF-26-441", expires 20 Apr 2027, Movements, "Feeding drawn from it (estimated)"). *Receive delivery* form: supplier, date, supplier's document number, lines (feed, lot, expiry, location, quantity, cost per kg, currency), Add line.

**Tabbed form, equipment** (`production-setup-equipment-edit`). "Ammonia sensor biofilterx (SNS-NH3-1)": tabs General (name, code, category Sensors, type Ammonia sensor, status Operational), Location, Details, Technical specifications, History.

**Messages** (`production-communication-*`). Conversation list (New message, New channel; Kari Nordmann direct; channels Tromsø site, Bergen Hatchery, Management team; Nils Berg) and thread ("Kari Nordmann: Hi, could Jakob Fossum get an account so he can clock in himself? He uses the sign-in sheet now."). On touch, Enter adds a line; Send sends.

**Knowledge library and entries.** Library: documents with year, topics, species, file ("PDF, 1 page, text found"), entries count; item page with Reference ("Fivelstad, S., & Olsen, A. B. (2003). Carbon dioxide and nephrocalcinosis in Atlantic salmon smolt. Aquaculture, 221(1-4), 83-97."), abstract, topics, DOI, file (Open the PDF, Download), "Read the text, page by page", "Knowledge taken from it". Entries: statement, topics, species, source, status Reviewed or Draft ("In Atlantic salmon under 50 g, free CO<sub>2</sub> above 15 mg/L leads to nephrocalcinosis."); entry page with Review ("Back to draft", "Review it again").

**Roles, users, activity log, database.** Roles: list with users and a long "Allows" sentence (make it a compact matrix summary, "17 areas, 4 with delete"); role form: a permission matrix by area (grouped Company, Facility; Production, Setup ...) with Read, Create, Edit, Delete plus the special columns Crew, All production, Everyone. Users: username, name, email, roles, status, last sign-in; user form with Language (Browser default, English, Türkçe, Norsk bokmål) and role checkboxes. Activity log: filters (record, person, record type, action, severity, dates); entries "Changed, Task, Clean and disinfect settling pond TG-D01, by bjorn.eriksen, 5 Nov 2026 09:05" with field changes (a checklist shown "☐ Drain the pond; ☐ Remove the sludge"); an acknowledged warning shows the shield and "Critical". Database: every table with its plain-language description, rows, deleted; table view with Data and Structure tabs, search every column, Export CSV.

**Login** (`account-login`). Left 600 px: the trout-skin artwork, wordmark top left, "Farm console for tanks, water quality and stock records." bottom left. Right: h1 "Sign in", username, password with Show, an ink primary button, "Forgot your password?". On phones the artwork becomes a 96 px band.

## 7. Responsive behaviour and acceptance

The shell answers to the viewport; everything inside the page answers to its container at 640 and 960 px. Never put `container-type` on the element containing the fixed drawer. Test at 320, 360, 390, 768, 820, 1024, 1280, 1440, and on a 1920 wall screen for Monitoring. Scriptable criteria:

1. Text 4.5:1; control borders and chart marks 3:1 on every neighbouring surface, both themes.
2. Double focus ring at 3:1 on rail, canvas and sheet; focus never hides under the top bar.
3. Targets 48 px on coarse, 24 px anywhere; delete never beside edit.
4. Greyscale and deuteranope renders still separate OK, warning and critical.
5. No horizontal page scroll at any test width or at 400 % zoom (today 23 phone pages overflow, section 17).
6. At 360 px each table's unit, decision figure, status and action show without scrolling.
7. Next planned meal recorded in three taps, no typing, on 390 by 844 when no warning applies.
8. A critical water value or active hold shows on the first screen after sign-in.
9. A plus 50 % pseudo-locale passes 5 and 6; axe-core finds no serious issue; no information rests on a `title` tooltip.
10. At 1440 no table cuts a column or its row actions (today about a dozen do, section 17).

## 8. Languages

English, Turkish, Norwegian Bokmål, all three real and complete (the `tr/` and `nb/` shots are the live catalogs, not mock-ups). Labels grow by a 90th percentile of 1.5 (Withdrawal becomes Tilbakeholdelse; Shift schedule becomes Vardiya çizelgesi), so design for plus 50 %: heads wrap, buttons size by padding, chips grow, tabs scroll. Numbers: 1,234.5 English; 1.234,5 Turkish; 1 234,5 Norwegian (non-breaking space). Dates: "3 Nov 2026, 19:21", "3 Kas 2026 19:21", "3. nov. 2026 19:21"; 24-hour (today English shows "9:04 p.m." on Monitoring and "10/26/2026" on the experiment overview: use the one date style everywhere); Monday first; print the parsed date beside each date picker ("Tue 3 Nov 2026"). A moment shows the site's clock, naming the zone when it differs from the viewer's. Authority terms stay in Norwegian with an English gloss ("Lokalitetsnummer", "driftsplan", "velferdspermisjon").

## 9. Motion

Four things move: drawer, dialog and movable window open in 180 ms; recording a meal fills the next pip in 200 ms and crossfades the figure; the plate's water dot glides to its new place in 200 ms when an input changes; a monitoring card that changes state on a poll crossfades its frame (never moves). The Deffeyes replay (section 15) animates frames at the user's chosen speed. Nothing else; `prefers-reduced-motion` turns it all off (the replay then steps).

## 10. Do and do not

Do: make the next meal the largest figure on the board. Keep the cards in one fixed order on the wall. Say why when a figure is missing.
Do not: use red for brand, link or button; put rose on data; colour a normal value; join strings with middle dots in data cells; use all-caps labels, arrows on buttons, numbered markers, eyebrows over every block or monospace; hide safety sentences in a popover; put a KPI tile row or identical card grid on the overview; shrink a wide chart for phones; let a table scroll silently or cut its actions.

## 11. Hand-off

Return: (1) a token file with named custom properties in Day and Night (`--surface-*`, `--line-hair`, `--line-control`, `--text-1` to `-3`, `--primary`, `--action`, `--brand-rose`, `--focus-inner`, `--focus-outer`, `--ok`, `--warn`, `--crit` each with `-text` and `-tint`, `--chart-s1` to `s5`, `--chart-iso`, `--zone-safe`, `--zone-toxic`, `--tone-1` to `-8`, `--space-1` to `8`, `--radius-*`, `--shadow-overlay`, `--font-text`, `--font-display`) and a computed contrast table; no colour literal elsewhere. (2) CSS for `ui-btn`, `ui-field`, `ui-form`, `ui-tabs`, `ui-toolbar`, `ui-table`, `ui-chip`, `ui-gauge`, `ui-dialog`, `ui-drawer`, `ui-menu`, `ui-message`, `ui-empty`, `ui-pager`, `ui-entry`, `ui-chart`, plus the section 13 parts `ui-cardgrid`, `ui-card`, `ui-value`, `ui-window`, `ui-roster`, `ui-orgtree`, `ui-ack`, `ui-why`; `data-status` is ok, warning, critical, hold or neutral; `data-state` is stale, nodata, voided, acknowledged, hidden or preview. (3) High-fidelity Day prototypes: meal board, units with drawer, water latest, calculator, **monitoring (grid and wall) with the Deffeyes window, Today & attendance, Shift schedule** at 1440, 1024 and 390; Sensors overview, live values and a chart, the Move dialog, card template designer, experiment overview, reports list and a report page, leave approve dialog, org chart, the rest at 1440 and 390; Night proofs of meal board, monitoring wall, water history and calculator; plus 50 % Turkish and Norwegian frames of meal board, water latest, monitoring and shift schedule.

Stack: server-rendered Django templates, plain CSS custom properties, no framework, TypeScript for behaviour (grid editor, roster paint, movable windows, polling), inline SVG icons, server-drawn charts. Browser floor Safari 16, Chrome 105, Firefox 110. Every table is a real `<table>`.

## 12. New and changed screens

Each block: what it shows, who uses it, real example data from the shots, and its states. "Permission-hidden" means the page or block is not offered: a menu entry is absent, a section says "not shown to you", a 404 for a record outside a person's reach.

### 12.1 HR: the office people (Company › HR) and Production › Team

The HR pages exist twice over **one set of records**: Company › HR for the office people (6 office departments), Production › Team for the people placed in a production department (7). Same components, same layouts; the panel decides who is listed. No pay, bank or identity number anywhere, by design.

**Today & attendance** (`company-hr-today`, `production-team-today`). Who: team leads at the start of a shift; each person to clock in and out. Shows count tiles (Planned today, Here now, Late, Not in yet, Absent, On leave) and a table Employee (department under the name), Shift (code chip and times), In, Out, State; Mark present (primary). Production example: 22 planned, 4 here now, 0 late, 0 not in yet, 1 absent (Viktor Andersson, DAY 07:00–15:00), 1 on leave (Mohammed Al-Sayed, "Not planned"); Erik Holm EVE 15:00–23:00, in 14:52, Present; Magnus Berg NIGHT 23:00–07:00, Upcoming; Kari Nordmann DAY, 06:50–15:09, Done. Company: 15 planned (OFFICE 08:00–16:00), all Done, Jonas Eide on leave. The board refreshes every 30 s. States: normal; warning (Late, Absent take the warning tint); a forgotten clock-out (an open stretch from yesterday, e.g. Nora Haugen) shows "In since 4 Nov 07:03"; empty ("Nobody is expected today", `durumlar/state-empty-production-team-today`); permission-hidden (a worker sees only themselves and their own Clock in / Clock out). Design notes: the tiles must add up (22 planned but tiles 4+0+0+1+1: add Done and Upcoming, or make the tiles a single stacked bar "13 done, 4 here, 3 upcoming, 1 absent, 1 on leave"); own Clock in / Clock out as a 56 px button for a person who has a roster today.

**Team list and person** (`company-hr-team`, `production-team-people`, `company-hr-person`, `production-team-person`, new forms `*-team-new`, `production-team-people-new`). Who: HR, heads of department. Table: Employee (name, number E-2001), Type (Staff, Technician, Student, Researcher, Contractor ...), Department, Title, Joined, Status ("Working here", "Left 14 Aug 2026", "Not placed"). Examples: Kari Nordmann E-2001, Hatchery hall A, Hatchery Manager, joined 1 Apr 2015; Hedda Lie E-1014, Student, Summer Intern, 15 Jun–14 Aug 2026. Person page: number, type, account, joined, left; Placements table (Hatchery hall A (HAT-A), Shift Leader, 1 Sep 2026, Open; Quarantine unit, Biosecurity Technician, 12 Feb 2018 to 31 Aug 2026). New employee form: tabs Person, Employment, Placement; account optional ("No account": a student needs no login). States: empty ("No employees yet"), a person outside the viewer's team is a 404.

**Departments** (`company-hr-departments`). Office departments in tree order: Management (MGMT, Ingrid Solheim, 1), Finance & Administration (FIN, in Management, Henrik Aasen, 3), People & HR (Camilla Strand, 2), Quality & Compliance (Elin Vik, 3), Research & Development (Lars Moen, 4), Sales & Logistics (Tromsø Grow-out, Per Johansen, 3). Production departments are managed under Production › Setup (`production-setup-departments`: Feed store FEED-1, Grow-out cages north GRO-N 24,000, Hatchery hall A HAT-A 1,500, Quarantine unit QUA-1 200, Research hall RES-1 600, Technical & maintenance MNT-1, each with its manager).

**Organization chart** (`company-hr-org-chart`, `production-team-org-chart`). Who: everyone with Read on employees; printable. Nested boxes, server-drawn. Company: "39 people you may see in the company", Management (Office, Ingrid Solheim, 1 person, 16 in all) with five departments below, and one computed **Production** box (23 people) linking to Production's chart. Production: sites as boxes (Bergen Hatchery, Site, 11 people: Hatchery hall A, Kari Nordmann, 5; Quarantine unit, Hanne Rønning, 2; Research hall, Lars Moen, 2; Technical & maintenance, Ole Kristiansen, 2. Tromsø Grow-out, 12: Feed store, Bjørn Eriksen, 1; Grow-out cages north, Bjørn Eriksen, 11). Design it as a real tree (connector lines, manager avatar initials, counts as chips), still printable on one A4 landscape.

**Shift schedule** (`company-hr-schedule`, `production-team-schedule`, plan dialog `production-team-schedule-new`). Who: leads plan the week; workers read their own week and their crew. The weekly roster of section 13: week "2 Nov 2026 – 8 Nov 2026" with Previous and Next week, Print; paint bar (Paint: DAY, OFFICE, WKND, EVE, NIGHT, Off, Clear; Clear selection; Apply to the selected days); search and department filter; "23 of 23 people"; rows like Magnus Berg: Off, NIGHT, NIGHT, NIGHT, NIGHT, Off, Off, 30 h; Tuva Aune with WKND on Saturday and Sunday. Below: "Crew this week" (a worker's view of their department's shifts). States: rule findings as "!" in the cell (rest too short, more than 6 days in a row, over the week, work on a holiday); On leave and holidays in their cells; empty ("No plans yet", `durumlar/state-empty-production-team-schedule-p390`); permission-hidden (a worker gets no paint bar and no plus). Phone: one person per card with seven day pills, or the viewer's own week first.

**Team overview** (`company-hr-team-overview`, `production-team-overview`). The schedule's week as numbers: per person Working days, Off, On leave, Planned (h), Against the standard week (min) (Jonas Eide: 0 working, 7 on leave, -2250; Mohammed Al-Sayed: 2 working, 3 on leave, 15 h, -1350); "Each day" totals (Working 18 / 19 / 19 / 22 / 22 / 3 / 3). Show minutes as hours ("-37.5 h"), mark a week over the standard with the warning chip.

**Attendance** (`company-hr-attendance`, `production-team-attendance`, form `*-attendance-new`). Stretches of the last weeks: Employee, Clock in, Clock out, How ("Clocked in by the person", "Entered by hand"), edit and void. Example: Nils Berg 5 Nov 2026 15:03, still "In". The form: employee, clock in, clock out (empty while the person is in), Note with "Why the time was entered or corrected" (required when entered by hand).

**Leave requests** (`company-hr-leave`, `company-hr-leave-pending`, `company-hr-leave-request`, `production-team-leave`, form `*-leave-new`, approve dialog `production-team-leave-approve-dialog`). Who: everyone files their own; leads decide. Tabs with counts: Pending 2, Approved 8, Rejected 1, All 12 (Production). Rows: Kristoffer Pedersen, Annual leave (ferie), 23–27 Nov 2026, charged 5, Pending, with Approve, Reject, Cancel icons; Sindre Olsen 21–31 Dec 2026, 8 days. Request page: Jonas Eide, Parental leave, 7 Sep–18 Dec 2026, charged 75, Approved, decided by Ingrid Solheim 5 Jun 2026, "Congratulations!". **Approve dialog**: "Approve the request of Kristoffer Pedersen, 23 Nov 2026 to 27 Nov 2026?", the shifts it hits ("The person has no planned shifts in these days." or a list to cover), Note ("Seen by the person; it is not written to the log"), Cancel and Approve. States: privacy (the leave type and reason are shown only to the person, a decider and HR; a lead sees "Leave" and the days), nobody decides their own leave (no buttons on one's own row), empty (`durumlar/state-empty-production-team-leave`).

**Scheduling settings, Shifts, Holidays** (`company-hr-settings-*`). The one row of limits with the warning "These are defaults the company can change, not the law: confirm them with your agreements": standard week 2250 min, minimum rest 660 min, most working days in a row 6, rule mode Warn, working weekdays Monday to Friday, punch window 120 min, absent after 30 min; shifts DAY 07:00–15:00 (break 30, grace 5), OFFICE 08:00–16:00 (15), WKND 08:00–18:00 (10), EVE 15:00–23:00 (5), NIGHT 23:00–07:00 next day (10), each with its tone; holidays (1 Jan 2026 New Year's Day, Every site ... 26 Dec 2027 Boxing Day). Show minutes as hours and minutes everywhere ("37 h 30 min").

### 12.2 Research › Experiments

Who: the research director and researchers (Lars Moen leads, Marta Kowalska, Lukas Becker, Nora Haugen), auditors.

**List** (`production-research-experiments`). Views Experiments, Mine, Templates; filters status, site, species; one line "A trial of one species on one site...". Rows: E-2026-002 "EPA+DHA level and stocking density in post-smolt", Running, Bergen Hatchery, Atlantic salmon, day 0 26 Oct 2026, 56 days, 6 groups, 12 replicates; E-2026-003 "Photoperiod before sea transfer and smolt quality", Draft, 11 Jan 2027, 84 days, 2 groups, 6; E-2026-001 Draft, 0 groups.

**Overview, Data, Team** (`production-research-experiment-overview`, `-data`, `-team`). Head: Running chip, "Day 10 of 56", the facts (number, site, species, starts on, duration, primary endpoint Biomass gain), Hypothesis ("Post-smolt fed 2.0 or 3.0 % EPA+DHA gain more biomass and convert feed better than those fed 1.0 %, and the effect holds at the higher stocking density."), Notes, Copy as a new experiment, Save as a template. *Overview:* per group (EPA+DHA 1.0 %, low density, Control group) its replicates R1, R2 with tank (RT-01), days, batch B-2026-003, fish now 100, biomass 7.14 kg, survival 100.0 %, bFCR, eFCR; then an amber list of record notes ("100 fish were moved from HA-R01 to RT-01 on 2026-10-26, and HA-R01 is not a tank of the experiment"). *Data:* per replicate the tank's farm records over its days: feeding records 11, feed given 0.868 kg, links to Feeding records, Treatments, Sea-lice counts, Water chemistry, Production units, and Release. *Team:* Thomas Brekke (Advisor), Lars Moen (Lead), Marta Kowalska (Researcher), Lukas Becker (Student), Nora Haugen (Technician). States: running (design frozen: fields read-only with "Copy it to change the design"), draft, closed, template; notes as warnings, never blocking.

**Design and Places** (`production-research-experiment-design`, `-places`; form tabs Details, Design, Places, Team, History). Design: two grids saved as a whole. Factors (Photoperiod, Other factor, unit "hours of light"; Add factor); Groups (Continuous light, Control group, 24:0 LD, 24.0000, 3 replicates; Winter signal, Test group, 12:12 LD, 12.0000, 3; Add group, Save design). "To fix before it can start": "The tanks are not allocated: randomise them or place them by hand.", "Continuous light (24:0) R1 has no tank." ... Places: Randomise (Pool: a multi-select of tanks HA-K01 Smolt tank 1 ... RT-03 Trial tank 3; Seed 389004873; "The same pool and seed always give the same placements") or By hand (per replicate: tanks, Add the tanks of a system, From, Until; Reason for placing by hand). States: errors block Start (red box), warnings are acknowledged at Start.

**Start dialog** (`production-research-experiment-start`; blocked state in `durumlar/state-blocked-production-research-experiment-start`). "Start E-2026-003?" with "Starting fixes the design for ever ...", the "To fix" list, Cancel and a disabled Start. With warnings only: the acknowledge row of section 13.

### 12.3 Reports (Production › Reports)

Who: the quality manager (Elin Vik) and the site managers; the authorities are Mattilsynet, Fiskeridirektoratet and Statsforvalteren. The system sends nothing: a person files in Altinn or the authority's API and records here when, how and the receipt.

**Regulatory reports list** (`production-reports-list`, a kind tab `production-reports-list-sea-lice`). Tabs with counts in two groups: All reports 3; Urgent: Welfare event, Disease 1, Escape, Site taken into use, Site emptied; Scheduled: Sea lice, Monthly biomass, Smolt, Cleaner fish, Planned slaughter 2, Yearly stock of a land site. Filters: site, status. Blocks in order: "Outside this system" (a link to the duties page); **"The records no longer give what was filed"** (red: "Smolt, Bergen Hatchery (BH-01), October 2026"); **"Reports and notices due"** (amber): "Planned slaughter, Fjord Seafood Processing (N1234), Week 45 of 2026, 29 Oct 2026, Overdue, Start, Close without filing"; "Disease, Tromsø Grow-out (TG-02), Pancreas disease (PD), 2026-10-20, at once, Start"; then the table Report, For, Deadline, Status (Filed chips carry the time and receipt "3 Nov 2026, AR-44-2026-7002"). A kind tab adds **"Where it stands"**, the why-not lines: "Bergen Hatchery: Not due. Bergen Hatchery is not a sea site."; "Tromsø Grow-out: Up to date. Every period since 2026-10-01 with fish is filed." States: overdue (critical tint), due, draft, filed in time, filed late, records changed, closed without filing (with the reason), not set up ("site not set up: no production form", with the link to fix it).

**A report** (`production-reports-report-draft`, `-report-filed`, `-report-filed-records-changed`, `-report-print`). Head facts: Report ("Sea lice, Mattilsynet (lakselusforskriften § 10)"), Site, For ("Week 45 of 2026"), Deadline (10 Nov 2026), Where to file it ("Altinn: Ukentlig rapportering av lakselus, or Mattilsynet's reporting API"), Status. Draft: "As the records give it now" (the figures), what keeps it from being ready, Print, CSV, JSON; **"Record that it was filed"**: the content hash, Filed at (Oslo time), Filed through (Altinn form, API, telephone), Receipt or reference, Id returned by the API, Record as filed. Filed: "Filed 3 Nov 2026, 09:05 through Altinn form, recorded by elin.vik, AR-44-2026-7002, in time", "The records still give what was filed.", Start a correction. Records changed: an amber block naming each figure that changed (design it as a before/after table per unit, "HA-K01 average weight 71.50 g to 73.00 g"; today it prints raw keys, section 17). Print: field and value in the authority's own names (lokalitetsnummer 23456, rapporteringsår 2026, uke 41, sjøtemperatur 9.6, voksneHunnlus 0.325, bevegeligeLus 0.6, fastsittendeLus 1.475), Back to the report, Print; A4 portrait.

**Duties outside this system** (`production-reports-duties`). "The annual duties of each site" (Tromsø Grow-out, Operating plan (driftsplan), 2026, deadline 1 Oct 2026, Done 24 Sep 2026, with Undo; Lice coordination plan (lakselusforskriften § 4), Done) and "All the duties": Duty, Deadline, Channel, When it binds (by production form), Source with "read it" links, Not verified. The long legal text needs a two-level layout: a short row and an expandable "When it binds".

**Questions for the authority** (`production-reports-authority-questions`, form `-authority-question-edit`). Rows Q1 to Q12: the question ("In virkestoff.mengde, is the amount the amount of the product or of the active substance?"), asked of (Mattilsynet, Fiskeridirektoratet, Statsforvalteren), the report rule it affects ("Sea-lice report: the amount of an active substance (R03)"), status Open, asked, answer. The form adds asked by, asked on, answer, answered on. An open question shows on the report it affects as "Unverified: Q1".

### 12.4 Monitoring with card templates

Who: operators on the floor, the control room on a wall screen, managers. **Rules (ISA-101):** grey by default, colour only for the abnormal; position constancy (cards in the farm's one order, site, department, code; a card never moves when its state changes); redundancy (word plus shape plus fill weight); origin and age on every value; precision from the parameter.

**The page** (`production-operations-monitoring`, `-monitoring-detailed`, `-monitoring-board`, `-monitoring-wall`). Toolbar: Board, Site, Production department, System, Kind, Fish (Stocked, Empty, All), Cards (Simple, Detailed), Search, Choose units, Wall, Full screen. Head: "7 of 23 units shown, computed at 21:04" and a strip naming each non-OK card ("HA-K01 Warning, Carbon dioxide (mg/L free CO<sub>2</sub>): Warning"; "HA-K03 No recent data, Temperature (°C): no recent data, 2 days old"). **The card frame** (always there, not data): unit code and link, state word and shape at right (Warning ◆, No recent data clock), name and department ("Smolt tank 1, Hatchery hall A"), the withdrawal chip ("Withdrawal, 24 Nov 2026"), the reasons as bullets, the flip link (Simple / Detailed), "State from: Fish, Feeding, Water, Health", "Template: Detailed, the rule for this type of system". **Widgets** below: fish (Fish 15,830, Avg. weight 66.0 g, Biomass 1,045 kg, bFCR 1.24, eFCR 1.28, Survival 99.2 %), density bar ("7.4 kg/m³, 12 %, 140.7 m³, max 60 kg/m³"), losses (170 dead, 0 culled), feeding (Ration –, Fed today 0 kg, 0 meals, Next meal –, why line "12.3 °C is outside this table"), feed rate 1.24 %, last fed 3 Nov 2026, feed in use Smolt Grow 3 mm, water per point (Middle: Temp. 9.5 °C, pH 7.41, Alkalinity 90, CO<sub>2</sub> 12.4, TAN 0.780, NH<sub>3</sub>-N 0.0032, each "Meter or test kit, 2 d ago"; then Bottom drain, Inlet, Side outlet), treatments in the last 90 days, tasks (Open 0, Overdue 0, Due today 0), the Deffeyes chart button. **Three templates are built in:** Simple, Detailed, Operator view (oxygen and temperature large and first, then O<sub>2</sub> %, pH and TAN). **Boards** are named wall screens with their own template and card width: "Bergen Hatchery – hall A and raceways" (Detailed, 7 cards, every 60 s), "Research hall – trial tanks" (Operator view, 12 cards, 120 s), "Tromsø – cage line north" (Detailed, 4, 300 s), "System A". **Wall** (`?wall=1`): no rail or top bar, larger figures, "Leave the wall", a large notice when the server cannot be reached; it refreshes every 15 s and keeps a minute-old picture visibly dated. States per card: Critical, Warning, No recent data (temperature or oxygen older than 24 h or missing: never OK, never red, age printed), Note (withdrawal, weigh soon, open health event), OK, Empty, Maintenance (unit status), Template error (dashed line "this card is shown as Detailed"), section hidden ("Water: not shown to you", the Deffeyes button left out), optional source failed ("no data"). Design notes: a value cell holds the figure on one line and origin and age on a second short line ("Meter, 2 d"); today the origin text wraps word by word in three-column cells (section 17). Give compact, automatic and comfortable widths (17, 21, 28 rem) a designed look each.

**Deffeyes window** (`production-operations-monitoring-deffeyes-window`). A movable window over the grid: ink title bar "Deffeyes chart, HA-K01", close; body "HA-K01, Middle, Atlantic salmon" and the chart (alkalinity against DIC, pH isolines, the water point as a star). Several windows side by side, place remembered per board. Planned: the replay player (section 15).

**Card templates** (`production-reference-card-templates`), **designer** (`production-reference-card-template-designer` new, `production-reference-card-template-operator-view` a built-in, read-only). List: Template, Rules, Boards, Cards, with "Built in" chips (Detailed 2 rules, 3 boards; Operator view 1, 1; Simple 2 rules, 0 boards, 4 cards) and Copy. The form: General (name, description, the template its flip link shows) and Design. **Design tab:** a palette of widgets (Value, Value against its limits, Water, Fish, Feeding, Health, Tasks, Experiments, Deffeyes chart), Undo, Redo, Revert, Grid lines; the canvas: a 12-column grid under a fixed band "The card's frame: the unit, its state and why, the withdrawal. Always shown."; a side panel "Select a widget to change it" (its options: size, bound parameter and point, field set); Reading order (the widgets as an ordered list, y then x); a live **preview** ("Preview on HA-K01", "Show as: Its own state / OK / Warning / Critical / No recent data", "Width: Card / Compact / Comfortable") drawing the real card ("Template: New template, the layout being designed"; "The preview shows only what you may read yourself"); "The layout as text" disclosure; Cancel, Create card template. Validation: errors name the widget ("w3 overlaps w1"), warnings never block ("No oxygen anywhere on this card"). Keyboard: arrows move, Shift+arrows resize, every gesture one undo step.

**Card template rules** (`production-reference-card-template-rules`, edit `-rule-edit`). The ladder in its order: Research RAS loop (RES-RAS) → Operator view; RAS (recirculating) → Detailed; Lumpfish (LUMP) → Simple; Cage → Detailed; Every unit → Simple (last, cannot be deleted). Form: Template, then exactly one of Unit, System, System type, Species, Unit kind, with the rule sentence "The most specific rule wins: a unit's own, then its system's, its system type's, its species', its kind's; a board's card and default come before and after the rules."

### 12.5 Setup and reference pages that changed

**Sampling points** (`production-setup-sampling-points`, edit `-sampling-point-edit`). Where in the water a sample is taken, owned by a unit, a system loop or a piece of equipment. Table: Owner (BIO-1 Biofilter loop, System), Sampling point (Loop), Kind and role (Middle, Within; Inlet, Stream in; Outlet, Stream out; Side outlet; Bottom drain), Flow (m³/h) (FLT-DRM-1 drum filter inlet 30; HA-K01 side outlet 10.80), Share of the outflow (%) (side outlet 90, bottom drain 10), Depth (m), Status, History link (to the water history of that point). A unit has one active middle point, the one that stands for its water.

**Monitoring boards** (`production-setup-monitoring-boards`, edit `-monitoring-board-edit`): name, description ("The control-room screen of the hatchery every tank of hall A, the raceways and the quarantine tank"), cards drawn with (template), card width (Automatic), refresh every (seconds, 10 to 600), Units tab (one row per unit with its own template).

**Medicines, withdrawal per species** (`production-reference-medicines`, `-medicine-edit`, `-medicine-withdrawal`). List: Medicine (Alphamax vet., MTnr 09-6993, prescription only), Kind (Sea-lice medicine), Active substance (Deltamethrin), Strength (10 mg/mL), **Withdrawal** as lines per species ("Aquaflor vet.: Other species 150 degree-days; Atlantic salmon 150 degree-days + 20 % safety margin = 180 degree-days"; "Alphamax vet.: 5 degree-days"; a vaccine "0 degree-days or 0 days, whichever ends later"), Manufacturer (Havet Fiskehelse). Withdrawal tab: rows Species (All species or one), Withdrawal (degree-days), Withdrawal (days), Safety margin (%), Note, Remove; Add species; the rule sentence "Give both when the SPC gives both: the later end wins." On units it surfaces as the hold chip "Withdrawal, 24 Nov 2026".

**Handling rules: fasting and purging** (`production-reference-handling-rules`, edit `-handling-rule-edit`). Rows: Grading, every species, 1 day (24 h); Harvest, every species, 3 days (72 h); **Harvest, Atlantic salmon, 5 days (120 h) and 40 degree-days purging** ("Purging: five days without feed, in clean water, and at least 40 degree-days"); Transport, 1 day; Treatment, 1 day; each with its source ("Starting value: check it with your veterinarian. BIM (2024) ..."). Form: Handling, Species, Fasting before it (number and unit), Purging before it (degree-days), Source of the value. They feed the "Before handling" box of the harvest, transfer and grading dialogs, and an override is the acknowledge row (section 13).

**Water limits** (`production-reference-water-limits`). Per species and water type: Parameter, Critical below, Warning below, Warning above, Critical above, Source (Atlantic salmon: Carbon dioxide —, —, 10.0, 15.0; Dissolved oxygen 6.00, 7.00; pH 6.00, 6.50, 8.00, 8.50; Temperature 2.0, 4.0, 16.0, 18.0. Sea Bass: Temperature 18.0, 19.0, 23.0, 25.0). Design it as a range strip per row (the four bounds on one scale), not four columns.

**Species, feeds, systems, tanks, equipment, suppliers, slaughter facilities, storage locations, sites.** Unchanged in purpose; more data now (Lumpfish as a cleaner fish, 29 equipment, 23 units, 8 suppliers, Fjord Seafood Processing with approval number N1234). All these lists are wide: they need the P1 to P4 column priority and sticky row actions (section 17, item 1).

### 12.6 Operations pages that changed

**Tasks** (`production-operations-tasks`, `-task-detail`, `-tasks-recurring`). Tabs Today 4, Open 59, Completed, Recurring tasks; filters site, place, person, priority, category, due dates; "3 overdue tasks". Rows: "Feed barge silo levels and feed order", Feeding, Medium, recurring; Feed store, Tromsø Grow-out; 2 Nov 2026 10:00, Overdue; Arne Moe; Open; checklist 0/3. Task form: tabs General, Where, When and who, Checklist, History. Recurring: "Daily mortality collection and recording, cages", every day at 10:00 from 19 Oct 2026, Grow-out cages north, Sindre Olsen, Ida Bakke, Nils Berg, next 5 Nov 2026, Active.

**Feeding records, protocols, assignments** (`production-feeding-*`). Records: Feeding records and By unit and day; rows date, unit, batches fed, feed, feed given, meals, feeder ("Demand feeder RAS"); "999 records, 132.5 t". By unit and day: Calculated, Given, Deviation ("-0.043 kg, -23.1 %"), with the why lines ("12.3 °C is outside this table (8.0–12.0 °C)", "No protocol is assigned to these fish"). Protocols: "R&D diet trial – EPA+DHA 1.0 %", Atlantic salmon, Active, weight bands "from 0 g, TD-EPA10, 3 mm", temperatures "8.0 °C – 12.0 °C, 2 columns", expected FCR 1.00, in force today 4. Assignments: protocol, applies to (Unit, Whole batch), unit, batch, from, until, fish now.

**Harvest** (`production-harvest-*`). Harvested: "2 harvests, 138.8 t round weight, 138.5 t in the book"; per row Date, Unit, Batch, Fish 30,000, Round weight 125,700 kg, Avg. weight 4,190 g, Book 126,000 kg, Difference -300 kg (-0.2 %); Per batch, Per site. Harvest plan: rows Date 16 Nov 2026, Harvest, TG-M01, B-2026-004, 5,581 fish, 24,624 kg, to Fjord Seafood Processing, Planned, and the Before handling text. Production plans: Unit, Batch, Fish, Avg. weight, Target weight ("Set target"), Estimated now, Expected harvest date.

**Health** (`production-health-*`). Events: a red "Notify Mattilsynet" banner ("A listed disease is suspected or confirmed and Mattilsynet has not been notified: notify at once (dyrehelseforskriften § 7)", Pancreas disease (PD), 2026-10-20, Tromsø Grow-out, Suspected); rows Observation 5 Nov 2026 (Bergen Hatchery, Reduced appetite, Pale gills, deaths 6, closed), Vet or fish-health visit 20 Oct 2026 (PD suspected, Notify at once, 827 deaths, Open), Increased mortality 17 Sep 2026. Event form: tabs Event, Diagnosis, Examination, Closing, History; units as checkboxes; signs as checkboxes. Treatments: date, units, treatment (Aquaflor vet., in feed, florfenicol), dose and amount (10 mg/kg biomass per day, 2 kg), batches and withdrawal ("B-2026-001 until about 23 Nov 2026"), prescription, recorded by, Last day, Void. Sea-lice counts: "Weekly averages" (Week 45, Tromsø Grow-out, adult females per fish 0.13, limit 0.50, mobile 0.63, attached 1.48, "2 of 2 units with fish now") and counts per cage with Void.

### 12.7 Sensors (the third panel, `/sensors/`)

Who: the technical manager and maintenance (Ole Kristiansen's department) set it up; operators and managers read Live values and Charts; HR and office staff never see it. Live today with the demo simulator: 1 connection, 1 payload format, 29 devices, 232 channels, a reading per channel every second since 6 Nov 2026 09:19. The panel's promise in one line: **every value says which sensor, how old, fresh or stale, and where it belongs.** Alarms are shown, not sent, and the pages say so.

**Menu.** Overview; Setup: Connections, Payload formats, Devices, Channels, Bindings; Operations: Charts, Live values, Dead letters, Alarm rules, Alarm events; Administration: Credentials. Panel switch: Company, Production, Sensors.

**Overview** (`sensors-overview-home`). Tiles, each for the right that may read it: Ingest "Alive" (a heartbeat within 90 s), "0 QoS 0 messages dropped on a full queue", "0 Messages the database refused", "29 / 29 Devices online", "0 Channels without a fresh value", "0 Open alarms", "0 Dead letters, last 24 hours", then counts 1 Connections, 29 Devices, 232 Channels, 1 Payload formats, each a link. States: Alive; Down (ingest silent for more than 90 s: critical, with the time of its last heartbeat); devices partly offline ("27 / 29", warning); stale channels (warning count links to Live values filtered); open alarms (critical count); dead letters (warning count). This is a candidate for the ISA-101 treatment: grey tiles, colour only on a non-zero problem count.

**Connections** (`sensors-setup-connections`, edit `-connection-edit`). "Demo simulator broker, mosquitto:1883, client id demo-simulator-ingest, 29 devices, Active". Form tabs General (name, Active: "An inactive connection is not listened to; its devices send to no one"), Connection (host, port, user name, secret file, client id, keep-alive in seconds), History.

**Payload formats** (`sensors-setup-payload-formats`, edit `-payload-format-edit`). "Demo simulator (JSON object): One object, a value per channel at its own path; time /ts, milliseconds since 1970; 29 devices". Tabs General, Time and sequence, Shape, History. Planned on the Shape tab: a "Test with a payload" box that decodes a pasted message (not on the page today).

**Devices** (`sensors-setup-devices`, edit `-device-edit`, tabs `-device-channels`, `-device-credential`). Rows: "Simulated probes BIO-1, SIM-BIO-1, Node-RED farm flow", topic demo/sim-bio-1, Demo simulator broker, Bergen Hatchery, 8 channels, Active. Tabs: General (connection, code, name, site, equipment, manufacturer Node-RED, model "farm flow", note, Active, **Simulated**: "A simulator or test device: its values are stored marked simulated and used nowhere"), Payload (format, topic), Credential (demo-simulator: "The broker credential this device publishes with; one gateway may serve many devices"), Channels (channel, quantity, value path "/oxygen_mg_l", heartbeat 300 s, state), History. States: active, inactive, simulated (mark it everywhere its values appear, e.g. a "Simulated" chip), offline (no message for longer than its expected interval).

**Channels** (`sensors-setup-channels`, edit `-channel-edit`, tabs `-channel-storing`, `-channel-calibration`). Rows: "OXYGEN-MG-L, Dissolved oxygen (mg/L O₂), #186, SIM-BIO-1, Every value, at least every 300 s, Active"; "NITRATE-N-MG-L ... Moves of 0.5000, at least every 900 s". Tabs: Source (device, code, name, value path, item name, note), Quantity and unit, Address, **Storing** (Store every value, or a value that moves past the deadband; deadband; heartbeat 300 s; range 0.0 to 50.0: "A value outside the range is stored, marked and used nowhere"; state Active, Maintenance, Retired; "Channel number 186. A value is fresh for three heartbeats: 900 seconds."), **Calibration** ("Value = gain × raw value + offset, from the moment given on the site's clock"; rows From, Gain, Offset, Calibrated by, Note; "No calibrations: values are stored as the device sends them"), History. States: active, maintenance (values stored, marked, not used for water), retired, out of range, stale.

**Bindings** (`sensors-setup-bindings`, one channel's history `-bindings-of-channel`, edit `-binding-edit`, the **Move dialog** `-binding-move-dialog`). Where a channel's values belong over time. Rows: "OXYGEN-MG-L, SIM-HA-K01 #2, bound to HA-K01 › Middle (Made by manage.py sensors_demo_setup.), Primary, from 6 Nov 2026 08:02, until now". The Move dialog ("New channel binding"): Channel, Bound to ("A water value goes to a sampling point or a system; a process value (flow, level, power ...) to a piece of equipment or a system"), Role (Primary, Backup), From (on the site's clock: "its binding until now ends then"), Note ("e.g. moved to the new tank after the grading"). The edit form only ends a binding (Until, Note); a move is always a new binding, so earlier values stay with the tank they were taken in. Design the per-channel history as a timeline (one bar per place over time).

**Charts** (`sensors-operations-charts-empty`, a tank `-chart-tank`, a system `-chart-system`). Form: Place (units and systems, e.g. "Smolt tank 1 (HA-K01)", "Biofilter loop (BIO-1)"), Quantity, Time (From and to, 6h, 24h, 7d, 30d, 90d, 1y, 2y), From, To, Draw. The chart: title "Smolt tank 1 (HA-K01), Dissolved oxygen (mg/L O₂), stored values, 15 s each", the line with its min-max envelope, axis 9.98 to 10.43 from 6 Nov 2026 09:19 to 10:30; "Download the drawn values (CSV)". Apply the section 5 time-series grammar: limits from the water limits, gaps stay gaps, the tier named ("15 s each", "hourly means"). States: empty (no place chosen), no data in range ("No stored values from ... to ..."), gaps, simulated values marked.

**Live values** (`sensors-operations-live`). "A value is fresh for three heartbeats of its channel. A stale value is not used for a unit's water: the next source counts (its system's sensor, then the latest sample)." Columns: Channel (NITRATE-N-MG-L, SIM-BIO-1 #189), Quantity, Value (45.600), Measured (6 Nov 2026, 09:42, "0 minutes ago"), State (Fresh, Stale, Out of range, Maintenance), Bound to (Biofilter loop (BIO-1)). 232 rows: needs grouping by device or place, a "Stale only" filter and a sticky head.

**Dead letters** (`sensors-operations-dead-letters`). Filters reason, show (open ones); "A message the ingest could not store is kept here with how often it came. Beyond 1000 new ones per connection and hour the rest are counted on one row. Readings are never refused for the dead letters' sake. Kept 90 days."; empty "No dead letters." A row shows reason, count, first and last seen, the payload as escaped text and hex (never rendered), Resolve.

**Alarm rules** (`sensors-operations-alarm-rules`, form `-alarm-rule-new`) and **Alarm events** (`sensors-operations-alarm-events`). The banner on both: "Alarms are shown on the Sensors pages, not sent: nobody is notified yet." / "Nobody is notified: an alarm is shown here and on the Sensors overview until a way to send it exists. It is not an alarm until someone sees it." Rule form: Channel, or Every channel of a quantity; When (No fresh value, Device offline, Above, Below, Changes faster than); Threshold (in the quantity's unit; for a rate, the change over the time below); For (seconds); Hysteresis; Severity (Warning, Critical); Active. Empty states: "No alarm rules yet. A rule says when a channel needs a look ..." with Add alarm rule; "No alarm events." Event rows (when they exist): severity, channel, place, raised at, value, cleared at, acknowledged (section 15 has the acknowledgement pages that are being built).

**Credentials** (`sensors-admin-credentials`, edit `-credential-edit`). "demo-simulator, secret made 6 Nov 2026 08:03, 29 devices, Enabled"; form: User name, Enabled ("A disabled credential cannot sign in once the broker's files are written again"), **Replace the secret** ("makes a new one, shown once; the old one stops working once the broker's files are written again"). The once-shown secret is a dialog with copy and a clear "You will not see it again".

**Values with origin and age on the farm screens** (re-shot: `production-operations-water-latest`, `-monitoring`, `-monitoring-detailed`, `-monitoring-wall`, `-monitoring-board`, `-monitoring-deffeyes-window`, `-unit-drawer`, `-units`, `production-feeding-meal-board`, `production-overview-home`). Per unit and parameter, independently: a fresh sensor on the unit's own point (primary, then backup); else a fresh sensor on its system; else a fresh manual or lab sample; else the newest value, shown stale. Each value says which: water latest HA-K01 Middle "13.7, unit sensor #1, 0 s ago", "10.37 O₂, unit sensor #2", "42.4 NO₃-N, system sensor #221"; HA-K02 side outlet "9.6, manual, 3 days ago"; monitoring cards "13.6, unit sensor #17, just now", "13.9 CO₂, Meter or test kit, 3 d ago"; meal board water "13.6 °C, unit, 0 min ago". The water page now reads "40 sampling points, 4 warnings" (four CO₂ warnings: HA-K01, HA-K03, HA-R01, TG-M02). Design: origin as a short tag (Unit sensor, System sensor, Manual, Lab) with the channel number on hover-free disclosure, age as a band; never the full sentence inside a table cell (today it is glued to the figure, section 17).

### 12.8 Role-limited views (`ekran-goruntuleri/roller/`)

Shot as two seeded people with dev-only sign-ins: **Kari Nordmann, Production manager** (Hatchery hall A) and **Ida Bakke, Production worker** (Grow-out cages north). File names start `role-production-manager-` and `role-production-worker-`.

- **Production manager menu:** Production: Overview; Setup (all of Facility structure and Reference data, Slaughter facilities, Suppliers); Operations, Feeding, Harvest, Health; Reports (Regulatory reports, Questions for the authority); Communication; **Team › Time & attendance: Today & attendance, Shift schedule, Leave requests (badge 2 pending to decide), Attendance, Team overview**; no Research, no Team › People. Company: Overview, Facility, Knowledge, Administration › Activity log only.
- **Production worker menu:** the same Production setup and operations reading, no Reports, no Research; Team › Time & attendance: Today & attendance, Shift schedule, Leave requests, Attendance (no Team overview). Company: Overview, Facility, Knowledge.
- **What each sees:** the manager's Today lists the production team (22 planned on 6 Nov), the schedule with the paint bar, leave with Approve and Reject; the worker's Today lists only herself (1 planned, NIGHT 23:00–07:00, Upcoming), her own week plus **Crew this week** (names, shift codes and times of her department, nothing else), her own leave ("No leave requests yet" with Add), her own attendance.
- **Permission-denied state:** both get **403** on Team list and Organization chart (`...-team-people-forbidden-*`, `...-team-org-chart-forbidden-*`). Today that page is a bare "403 Forbidden" with no app shell (section 17): design the denied page (shell kept, "You do not have access to Team list. Ask an HR administrator.", a way back).

## 13. Shared components added since the first brief

Each is already built and used on more than one screen; design it once, as a `ui-` part.

- **Card grid (`ui-cardgrid`, `ui-card`).** The monitoring cards and the designer's canvas: a 12-column grid inside each card; every widget has x, y, width, height in cells (`--x --y --w --h`), rows at least 1.75 rem and growing with content. Below 30 rem of card width the widgets stack in one column in reading order (y, then x). Board card widths: compact 17 rem, automatic 21, comfortable 28 (plus 15 % on a wall).
- **Card frame vs widgets.** The frame is not data and no template can remove it (unit, state word, shape and reasons, withdrawal, unit status, "State from", "Template: ... because ...", flip link). Widgets are the data. A frame's left edge carries the state: solid 4 px for critical and warning, dashed for no recent data, dotted for empty, none for OK.
- **Value face (`ui-value`).** One way a single value is said: label with unit, figure at the parameter's precision, status in words, origin (Sensor, Manual, Lab, "Meter or test kit") and age in bands ("just now", "40 s ago", "12 min ago", "3 h ago", "2 d ago"), "old" past the parameter's freshness, "no data". Two lines at most.
- **Limit bar.** Value against the four bounds of its limit, SVG `role="img"` named by the same sentence; bands told apart by dash pattern and tone; "No limit set" when there is none.
- **Movable window (`ui-window`).** Ink title bar with the subject, close, drag by the bar, resize from the corner, keyboard move (Alt+arrows), several side by side, place remembered per board on each device; on phones it becomes a full-screen sheet.
- **Weekly roster (`ui-roster`).** A row per person (department under the name), seven day cells Monday first, planned hours at the end. Cell states: shift code in its tone, Off, holiday name, On leave (type hidden from leads), "!" with the finding, empty with a plus for a planner. Arrow keys move; the paint bar plans many cells at once, all or none; a cell opens the plan dialog. Crew variant: only name, shift code and times of the worker's own department.
- **Org tree (`ui-orgtree`).** Nested boxes with kind (Site, Production, Office), manager and "n people" (direct and in all below); a computed box (Company's Production box) is marked and links to its own chart; prints on one page.
- **Tabs with counts.** Reports (All reports 3, Disease 1, Planned slaughter 2), Leave (Pending 2, Approved 8, Rejected 1, All 12), Tasks (Today 4, Open 59), Production units (Production 19). Zero is shown; groups have quiet labels ("Urgent", "Scheduled"); an urgent count with work due takes the warning tint.
- **Acknowledge row with critical warning (`ui-ack`).** Record meal during fasting, harvest or transfer before the handling rule's fasting or purging is done or during a withdrawal, Start experiment with warnings: an amber box saying what is wrong and "Recording now is allowed and is logged as critical", a 56 px checkbox row, the button renamed "Record anyway and log as critical"; the acknowledgement is stored (the situation: withdrawal end, hours fasted against the rule's) and shown in the activity log with the shield. A blocking error is a red box "To fix before it can start" with a disabled primary.
- **Why line (`ui-why`).** One plain sentence where a figure or duty is absent; Text 2, never italic, never a tooltip.
- **Before handling box.** In harvest, transfer and grading dialogs: last fed, hours fasted, the rule that applies and its source; turns amber with the ack row when the rule is not met.
- **Poll state.** A polled page (monitoring 15 s, Today 30 s) shows "computed at 21:04" and a banner when the server cannot be reached or the person is signed out.

## 14. Owner design questions still open (with our recommendation)

1. **Brand crimson to ink.** Every shot still uses crimson (#B8455F family) for the primary button, active rail item, active tab, eyebrow and links. Recommendation: do it. Ink #1F2A1C for the one primary per view, blue #1D4E89 for links, selection and the active tab, crimson only in the wordmark, the rail stripe and the login artwork. Reason: "red means critical only"; today "Approve" and a critical chip are the same family, and an operator reads every page as alarmed.
2. **Font.** Today Bricolage Grotesque everywhere, figures and codes included. Recommendation: Atkinson Hyperlegible Next for everything read or entered (tabular figures, dotted zero: HA-K01 never reads HA-KO1), Bricolage 600 only for h1, h2, the wordmark and empty-state titles at 22 px and up; both self-hosted; µ, ₂, ₃, ‰ fall back per glyph.
3. **Deffeyes colours.** The chart keeps the source platform's 12 colours (rainbow pH isolines, orange toxic fill), pinned by a parity test. Recommendation: restyle to the plate of section 5 (slate isolines, hatched critical zones, a safe zone with an OK border, ink water dot, blue target) as a deliberate, owner-approved change with the test updated; until then design the plate, ship parity.
4. **Sea-lice "close to the limit".** Today a count is over or under (0.5 adult females per fish, 0.2 in the spring weeks). Recommendation: a warning band from 80 % of the limit (0.40; 0.16 in spring), shown as Warning on the lice list, the cards and the report; the owner confirms the 80 %.
5. **Acknowledgement reason.** Today an acknowledgement stores the situation (withdrawal end, hours fasted against the rule) and who and when, not why. Recommendation: one short reason when an acknowledgement becomes a critical log entry (a pick list "Vet approved", "Emergency", "Recorded late" plus free text of at least 10 characters), shown beside "Critical, acknowledged by ..." in the log and on the record.

## 15. Coming next (being built now: design them, expect no shots)

- **Deffeyes replay player** (plan A6 to A8), inside the movable window. Range presets (last 24 h, 5 days, 30 days) and custom from-to; step (1 min, 5 min, 15 min, 1 h, 1 day); play, pause, scrub, step, speed 1x, 2x, 3x, 5x, 10x. The whole diagram moves: every frame redraws isolines, zones and labels from the water at that moment (temperature, salinity), not only the dot. A frame with missing inputs shows "missing" and why, never an interpolated point. Frames load in pages of up to 2,000 (5 days at 1 min is 7,200 frames): show the loaded part on the scrubber, the time and the inputs with their origin under the chart. Several windows, one per unit or system.
- **"Bind sensor" on a monitoring card and in the Deffeyes window.** For a person with the Binding right: from a value with no sensor (or a stale one), open the Move dialog of section 12.7 prefilled with the place and the quantity; after saving, the value reads "unit sensor #n, just now". The window shows which channel feeds each input.
- **Portable sensor "Move device".** A portable probe carried from tank to tank: one action ends all its channels' bindings at a moment and starts them at the new place (device, new place, from, note), with a confirmation listing each channel that moves; earlier values stay with the tank they were taken in.
- **Alarm notifications and acknowledgement pages.** Today alarms are shown, not sent. Coming: who is notified, by which channel and when; an Acknowledge action on an alarm event (who, when, a note; acknowledged until it clears); an open-alarms page with Critical first; the overview tile counting unacknowledged alarms. Keep the honest "nobody is notified" banner until delivery is real, then name who was notified.
- **Platform-owner settings.** One settings page for the platform owner (company identity, languages offered, number and date formats, retention periods, the sensors ingest's limits), in sections, each with a line saying who may change it.

## 16. Screen inventory and screenshot index

Files: `ekran-goruntuleri/en/` every screen at three sizes; `tr/` and `nb/` the main screens; `durumlar/` deliberate states (empty, blocked) taken before the demo company existed; `roller/` the role-limited views (section 12.8); `_eski/` the 58 shots of the first brief (all outdated, kept for comparison). Name: `<panel>-<section>-<page>-<viewport>-<lang>.png`, viewport `d1440` (1440 by 900), `t1024` (1024 by 768), `p390` (390 by 844); pages are full height (cut at 2,600 px), dialogs, drawer and window are the first screen. Counts: 161 screens (134 of 5 Nov plus 27 Sensors pages); EN 483 shots (161 per viewport; the 10 farm screens that now show sensor values were re-shot on 6 Nov under their old names); TR 84 and NB 84 (28 main screens by 3 sizes: the 19 of 5 Nov, 6 of them re-shot on 6 Nov with sensor values, plus 8 Sensors pages and the Deffeyes window); 66 role shots (11 screens by 3 sizes for each of two roles, 12 of them the 403 state); 6 state shots. Shots were taken as the platform admin unless the file starts with `role-`.

**Live menu.** Company: Overview; Facility: Sites, Storage locations; Knowledge: Library, Knowledge entries; Administration: Activity log, Roles, Users, Database; HR › HR dashboard: Today & attendance, Team list, Departments, Organization chart; HR › Time & shifts: Shift schedule, Team overview, Attendance, Leave requests, Scheduling settings (Shifts, Holidays, Leave types from there). Production: Overview; Setup › Facility structure: Production departments, Systems, Equipment, Tanks, ponds & cages, Monitoring boards, Sampling points; Setup › Reference data: Species, Feeds, Water limits, Medicines, Handling rules, Card templates, Card template rules; Setup › Harvest and logistics: Slaughter facilities; Setup › Purchasing: Suppliers; Operations: Production units, Monitoring, Water chemistry, Storage, Tasks, Recurring tasks; Feeding: Meal board, Records, Protocols, Assignments; Harvest: Harvested, Harvest plan, Production plans; Health: Treatments, Health events, Sea-lice counts; Research: Experiments; Reports: Regulatory reports, Questions for the authority (and Duties outside this system); Communication: Messages; Team › Time & attendance: Today & attendance, Shift schedule, Leave requests, Attendance, Team overview; Team › People: Team list, Organization chart. Sensors: Overview; Setup: Connections, Payload formats, Devices, Channels, Bindings; Operations: Charts, Live values, Dead letters, Alarm rules, Alarm events; Administration: Credentials. Account: Change password, Sign out.

| Screen (file base) | Address | Languages |
|---|---|---|
| account-login | /accounts/login/ | EN |
| company-overview-home | / | EN TR NB |
| company-facility-sites | /sites/ | EN |
| company-facility-site-edit | /sites/<id>/ | EN |
| company-facility-storage-locations | /storage-locations/ | EN |
| company-knowledge-library | /knowledge/library/ | EN |
| company-knowledge-library-item | /knowledge/library/<id>/view/ | EN |
| company-knowledge-entries | /knowledge/entries/ | EN |
| company-knowledge-entry-view | /knowledge/entries/<id>/view/ | EN |
| company-admin-activity-log | /activity/ | EN |
| company-admin-roles | /roles/ | EN |
| company-admin-role-edit | /roles/5/ | EN |
| company-admin-users | /users/ | EN |
| company-admin-user-edit | /users/4/ | EN |
| company-admin-database | /database/ | EN |
| company-admin-database-table | /database/tanks/ | EN |
| company-account-password-change | /accounts/password_change/ | EN |
| company-hr-today | /hr/ | EN TR NB |
| company-hr-team | /hr/team/ | EN |
| company-hr-team-new | /hr/team/new/ | EN |
| company-hr-departments | /hr/departments/ | EN |
| company-hr-org-chart | /hr/organization/ | EN |
| company-hr-schedule | /hr/schedule/ | EN TR NB |
| company-hr-team-overview | /hr/overview/ | EN |
| company-hr-attendance | /hr/time/attendance/ | EN |
| company-hr-attendance-new | /hr/time/attendance/new/ | EN |
| company-hr-leave | /hr/leave/ | EN |
| company-hr-leave-pending | /hr/leave/?tab=pending | EN |
| company-hr-leave-request | /hr/leave/<id>/view/ | EN |
| company-hr-person | /hr/team/<id>/view/ | EN |
| company-hr-leave-new | /hr/leave/new/ | EN |
| company-hr-settings-scheduling | /hr/settings/scheduling/ | EN |
| company-hr-settings-scheduling-edit | /hr/settings/scheduling/<id>/ | EN |
| company-hr-settings-shifts | /hr/settings/shifts/ | EN |
| company-hr-settings-holidays | /hr/settings/holidays/ | EN |
| production-overview-home | /production/ | EN TR NB |
| production-setup-departments | /production-departments/ | EN |
| production-setup-systems | /systems/ | EN |
| production-setup-system-edit | /systems/<id>/ | EN |
| production-setup-equipment | /equipment/ | EN |
| production-setup-equipment-edit | /equipment/<id>/ | EN |
| production-setup-tanks | /tanks/ | EN |
| production-setup-tank-edit | /tanks/<id>/ | EN |
| production-setup-monitoring-boards | /monitoring-boards/ | EN |
| production-setup-monitoring-board-edit | /monitoring-boards/<id>/ | EN |
| production-setup-sampling-points | /sampling-points/ | EN |
| production-setup-sampling-point-edit | /sampling-points/<id>/ | EN |
| production-reference-species | /species/ | EN |
| production-reference-species-edit | /species/<id>/ | EN |
| production-reference-feeds | /feeds/ | EN |
| production-reference-water-limits | /water-limits/ | EN |
| production-reference-medicines | /medicines/ | EN |
| production-reference-medicine-edit | /medicines/<id>/ | EN |
| production-reference-medicine-withdrawal | /medicines/<id>/ (after a click: Withdrawal) | EN |
| production-reference-handling-rules | /handling-rules/ | EN |
| production-reference-handling-rule-edit | /handling-rules/<id>/ | EN |
| production-reference-card-templates | /card-templates/ | EN |
| production-reference-card-template-designer | /card-templates/new/ (after a click: button[data-tab="design"]) | EN TR NB |
| production-reference-card-template-operator-view | /card-templates/<id>/ (after a click: button[data-tab="design"]) | EN TR NB |
| production-reference-card-template-rules | /card-template-rules/ | EN |
| production-reference-card-template-rule-edit | /card-template-rules/<id>/ | EN |
| production-logistics-slaughter-facilities | /slaughter-facilities/ | EN |
| production-purchasing-suppliers | /suppliers/ | EN |
| production-operations-units | /operations/units/ | EN TR NB |
| production-operations-unit-drawer | /operations/units/?unit=<id> | EN TR NB |
| production-operations-harvest-dialog | /operations/units/?unit=<id> (after a click: a[href*="/harvest/"]) | EN |
| production-operations-transfer-dialog | /operations/units/?unit=<id> (after a click: a[href*="/transfer/"]) | EN |
| production-operations-batch-details | /operations/units/?unit=<id> (after a click: a[href*="/batch/"]) | EN |
| production-operations-monitoring | /operations/monitoring/ | EN TR NB |
| production-operations-monitoring-deffeyes-window | /operations/monitoring/ (after a click: Deffeyes) | EN TR NB |
| production-operations-monitoring-wall | /operations/monitoring/?wall=1 | EN |
| production-operations-monitoring-board | /operations/monitoring/?board=<id> | EN |
| production-operations-monitoring-detailed | /operations/monitoring/?mode=detailed | EN |
| production-operations-water-latest | /operations/water/ | EN TR NB |
| production-operations-water-history | /operations/water/?view=history | EN |
| production-operations-water-point | /operations/water/?point=<id> | EN |
| production-operations-water-record | /operations/water/record/ | EN |
| production-operations-water-round | /operations/water/round/ | EN |
| production-operations-water-calculator | /operations/water/calculator/ | EN TR NB |
| production-operations-storage-overview | /operations/storage/ | EN TR NB |
| production-operations-storage-stock | /operations/storage/?tab=stock | EN |
| production-operations-storage-movements | /operations/storage/?tab=movements | EN |
| production-operations-storage-counts | /operations/storage/?tab=counts | EN |
| production-operations-storage-lot | /operations/storage/lots/<id>/ | EN |
| production-operations-storage-receive | /operations/storage/receive/ | EN |
| production-operations-storage-item | /operations/storage/items/<id>/?site=<id> | EN |
| production-operations-tasks | /operations/tasks/ | EN |
| production-operations-task-detail | /operations/tasks/<id>/ | EN |
| production-operations-tasks-recurring | /operations/tasks/recurring/ | EN |
| production-feeding-meal-board | /operations/feeding/board/ | EN TR NB |
| production-feeding-record-meal-dialog | /operations/feeding/board/ (after a click: a[href*="/feeding/?meal=next"]) | EN |
| production-feeding-records | /operations/feeding/ | EN |
| production-feeding-records-days | /operations/feeding/?view=days | EN |
| production-feeding-protocols | /operations/feeding/protocols/ | EN |
| production-feeding-protocol-edit | /operations/feeding/protocols/<id>/ | EN |
| production-feeding-assignments | /operations/feeding/assignments/ | EN |
| production-harvest-harvested | /operations/harvests/ | EN |
| production-harvest-plan | /operations/harvest-plan/ | EN |
| production-harvest-production-plans | /operations/production-plans/ | EN |
| production-health-treatments | /operations/health/treatments/ | EN |
| production-health-events | /operations/health/events/ | EN |
| production-health-event-edit | /operations/health/events/<id>/ | EN |
| production-health-lice | /operations/health/lice/ | EN |
| production-research-experiments | /research/experiments/ | EN |
| production-research-experiment-overview | /research/experiments/<id>/view/?tab=overview | EN TR NB |
| production-research-experiment-data | /research/experiments/<id>/view/?tab=data | EN |
| production-research-experiment-team | /research/experiments/<id>/view/?tab=team | EN |
| production-research-experiment-design | /research/experiments/<id>/ (after a click: button[data-tab="design"]) | EN |
| production-research-experiment-places | /research/experiments/<id>/ (after a click: Places) | EN |
| production-research-experiment-start | /research/experiments/<id>/start/ | EN |
| production-reports-list | /reports/ | EN TR NB |
| production-reports-list-sea-lice | /reports/?kind=sea_lice | EN |
| production-reports-duties | /reports/duties/ | EN |
| production-reports-report-draft | /reports/<id>/view/ | EN |
| production-reports-report-filed-records-changed | /reports/<id>/view/ | EN |
| production-reports-report-filed | /reports/<id>/view/ | EN |
| production-reports-report-print | /reports/<id>/print/ | EN |
| production-reports-authority-questions | /authority-questions/ | EN |
| production-reports-authority-question-edit | /authority-questions/<id>/ | EN |
| production-team-today | /production/team/ | EN TR NB |
| production-team-schedule | /production/team/schedule/ | EN TR NB |
| production-team-schedule-new | /production/team/schedule/new/ | EN |
| production-team-leave | /production/team/leave/ | EN |
| production-team-leave-approve-dialog | /production/team/leave/?tab=pending (after a click: a[href*="/approve/"]) | EN TR NB |
| production-team-leave-new | /production/team/leave/new/ | EN |
| production-team-attendance | /production/team/attendance/ | EN |
| production-team-attendance-new | /production/team/attendance/new/ | EN |
| production-team-overview | /production/team/overview/ | EN |
| production-team-people | /production/team/people/ | EN |
| production-team-people-new | /production/team/people/new/ | EN |
| production-team-person | /production/team/people/<id>/view/ | EN |
| production-team-org-chart | /production/team/organization/ | EN |
| production-communication-messages | /messages/ | EN TR NB |
| production-communication-thread | /messages/<id>/ | EN |
| sensors-overview-home | /sensors/ | EN TR NB |
| sensors-setup-connections | /sensors/connections/ | EN |
| sensors-setup-connection-edit | /sensors/connections/<id>/ | EN |
| sensors-setup-payload-formats | /sensors/payload-formats/ | EN |
| sensors-setup-payload-format-edit | /sensors/payload-formats/<id>/ | EN |
| sensors-setup-devices | /sensors/devices/ | EN TR NB |
| sensors-setup-device-edit | /sensors/devices/<id>/ | EN |
| sensors-setup-device-channels | /sensors/devices/<id>/ (after a click: button[data-tab="channels"]) | EN |
| sensors-setup-device-credential | /sensors/devices/<id>/ (after a click: button[data-tab="credential"]) | EN |
| sensors-setup-channels | /sensors/channels/ | EN |
| sensors-setup-channel-edit | /sensors/channels/<id>/ | EN TR NB |
| sensors-setup-channel-storing | /sensors/channels/<id>/ (after a click: button[data-tab="reduction"]) | EN |
| sensors-setup-channel-calibration | /sensors/channels/<id>/ (after a click: button[data-tab="calibration"]) | EN |
| sensors-setup-bindings | /sensors/bindings/ | EN TR NB |
| sensors-setup-bindings-of-channel | /sensors/bindings/?channel=<id> | EN |
| sensors-setup-binding-edit | /sensors/bindings/<id>/ | EN |
| sensors-setup-binding-move-dialog | /sensors/bindings/ (after a click: a[href="/sensors/bindings/new/"]) | EN TR NB |
| sensors-operations-charts-empty | /sensors/charts/ | EN |
| sensors-operations-chart-tank | /sensors/charts/?target=unit:<id>&quantity=oxygen_mg_l&range=&start=2026-11-06T09:19&end=2026-11-06T10:30 | EN TR NB |
| sensors-operations-chart-system | /sensors/charts/?target=system:<id>&quantity=temperature_c&range=&start=2026-11-06T09:19&end=2026-11-06T10:30 | EN TR NB |
| sensors-operations-live | /sensors/live/ | EN TR NB |
| sensors-operations-dead-letters | /sensors/dead-letters/ | EN |
| sensors-operations-alarm-rules | /sensors/alarm-rules/ | EN |
| sensors-operations-alarm-rule-new | /sensors/alarm-rules/new/ | EN |
| sensors-operations-alarm-events | /sensors/alarm-events/ | EN |
| sensors-admin-credentials | /sensors/credentials/ | EN |
| sensors-admin-credential-edit | /sensors/credentials/<id>/ | EN |
| role-production-manager-production-overview-home, role-production-worker-production-overview-home | /production/ | EN (roller/) |
| role-production-manager-company-overview-home, role-production-worker-company-overview-home | / | EN (roller/) |
| role-production-manager-production-team-today, role-production-worker-production-team-today | /production/team/ | EN (roller/) |
| role-production-manager-production-team-schedule, role-production-worker-production-team-schedule | /production/team/schedule/ | EN (roller/) |
| role-production-manager-production-team-leave, role-production-worker-production-team-leave | /production/team/leave/ | EN (roller/) |
| role-production-manager-production-team-attendance, role-production-worker-production-team-attendance | /production/team/attendance/ | EN (roller/) |
| role-production-manager-production-team-overview, role-production-worker-production-team-overview | /production/team/overview/ | EN (roller/) |
| role-production-manager-production-team-people, role-production-worker-production-team-people (named -forbidden-) | /production/team/people/ | EN (roller/) |
| role-production-manager-production-team-org-chart, role-production-worker-production-team-org-chart (named -forbidden-) | /production/team/organization/ | EN (roller/) |
| role-production-manager-production-feeding-meal-board, role-production-worker-production-feeding-meal-board | /operations/feeding/board/ | EN (roller/) |
| role-production-manager-production-operations-monitoring, role-production-worker-production-operations-monitoring | /operations/monitoring/ | EN (roller/) |

**The first brief's shots** (all 58 outdated: the rail lacked Monitoring boards, Sampling points, Card templates, Research, Reports, Team and HR, and the data was a small test farm):

| Old file (`_eski/`) | Status | Replaced by |
|---|---|---|
| d1440-activity.png | outdated | en/company-admin-activity-log-d1440-en.png |
| d1440-database.png | outdated | en/company-admin-database-d1440-en.png |
| d1440-equipment-new.png | outdated | en/production-setup-equipment-edit-d1440-en.png |
| d1440-equipment.png | outdated | en/production-setup-equipment-d1440-en.png |
| d1440-feeds.png | outdated | en/production-reference-feeds-d1440-en.png |
| d1440-handling-rules.png | outdated | en/production-reference-handling-rules-d1440-en.png |
| d1440-home.png | outdated | en/company-overview-home-d1440-en.png |
| d1440-knowledge-entries.png | outdated | en/company-knowledge-entries-d1440-en.png |
| d1440-knowledge-library.png | outdated | en/company-knowledge-library-d1440-en.png |
| d1440-login.png | outdated | en/account-login-d1440-en.png |
| d1440-medicines.png | outdated | en/production-reference-medicines-d1440-en.png |
| d1440-messages.png | outdated | en/production-communication-messages-d1440-en.png |
| d1440-operations-feeding-assignments.png | outdated | en/production-feeding-assignments-d1440-en.png |
| d1440-operations-feeding-board.png | outdated | en/production-feeding-meal-board-d1440-en.png |
| d1440-operations-feeding-protocols-abcbb7df-3f7f-4853-a3d3-602d3f9af168.png | outdated | en/production-feeding-protocol-edit-d1440-en.png |
| d1440-operations-feeding-protocols.png | outdated | en/production-feeding-protocols-d1440-en.png |
| d1440-operations-feeding.png | outdated | en/production-feeding-records-d1440-en.png |
| d1440-operations-harvest-plan.png | outdated | en/production-harvest-plan-d1440-en.png |
| d1440-operations-harvests.png | outdated | en/production-harvest-harvested-d1440-en.png |
| d1440-operations-health-events.png | outdated | en/production-health-events-d1440-en.png |
| d1440-operations-health-lice.png | outdated | en/production-health-lice-d1440-en.png |
| d1440-operations-health-treatments.png | outdated | en/production-health-treatments-d1440-en.png |
| d1440-operations-production-plans.png | outdated | en/production-harvest-production-plans-d1440-en.png |
| d1440-operations-storage-receive.png | outdated | en/production-operations-storage-receive-d1440-en.png |
| d1440-operations-storage-tab-stock.png | outdated | en/production-operations-storage-stock-d1440-en.png |
| d1440-operations-storage.png | outdated | en/production-operations-storage-overview-d1440-en.png |
| d1440-operations-units.png | outdated | en/production-operations-units-d1440-en.png |
| d1440-operations-water-calculator.png | outdated | en/production-operations-water-calculator-d1440-en.png |
| d1440-operations-water-record.png | outdated | en/production-operations-water-record-d1440-en.png |
| d1440-operations-water-view-history.png | outdated | en/production-operations-water-history-d1440-en.png |
| d1440-operations-water.png | outdated | en/production-operations-water-latest-d1440-en.png |
| d1440-production-departments.png | outdated | en/production-setup-departments-d1440-en.png |
| d1440-production.png | outdated | en/production-overview-home-d1440-en.png |
| d1440-roles.png | outdated | en/company-admin-roles-d1440-en.png |
| d1440-sites-new.png | outdated | en/company-facility-site-edit-d1440-en.png |
| d1440-sites.png | outdated | en/company-facility-sites-d1440-en.png |
| d1440-slaughter-facilities.png | outdated | en/production-logistics-slaughter-facilities-d1440-en.png |
| d1440-species.png | outdated | en/production-reference-species-d1440-en.png |
| d1440-storage-locations.png | outdated | en/company-facility-storage-locations-d1440-en.png |
| d1440-suppliers.png | outdated | en/production-purchasing-suppliers-d1440-en.png |
| d1440-systems.png | outdated | en/production-setup-systems-d1440-en.png |
| d1440-tanks-b01e3d15-6ba2-4831-9eb2-98c48b3b229d.png | outdated | en/production-setup-tank-edit-d1440-en.png |
| d1440-users.png | outdated | en/company-admin-users-d1440-en.png |
| d1440-water-limits.png | outdated | en/production-reference-water-limits-d1440-en.png |
| p390-messages.png | outdated | en/production-communication-messages-p390-en.png |
| p390-operations-feeding-board.png | outdated | en/production-feeding-meal-board-p390-en.png |
| p390-operations-storage.png | outdated | en/production-operations-storage-overview-p390-en.png |
| p390-operations-units.png | outdated | en/production-operations-units-p390-en.png |
| p390-operations-water-calculator.png | outdated | en/production-operations-water-calculator-p390-en.png |
| p390-operations-water.png | outdated | en/production-operations-water-latest-p390-en.png |
| p390-production.png | outdated | en/production-overview-home-p390-en.png |
| p390-sites.png | outdated | en/company-facility-sites-p390-en.png |
| t820-equipment.png | outdated | en/production-setup-equipment-t1024-en.png |
| t820-operations-feeding-board.png | outdated | en/production-feeding-meal-board-t1024-en.png |
| t820-operations-storage.png | outdated | en/production-operations-storage-overview-t1024-en.png |
| t820-operations-units.png | outdated | en/production-operations-units-t1024-en.png |
| t820-operations-water.png | outdated | en/production-operations-water-latest-t1024-en.png |
| t820-production.png | outdated | en/production-overview-home-t1024-en.png |

## 17. What the shots show is broken today (design must solve these)

1. **Wide tables cut their right-hand columns at 1440 with no scroll cue,** often with the row actions: meal board (Protocol, Today, Next meal and Record meal out of view), production units (Density onwards), water latest and history (CO<sub>2</sub> onwards), equipment (Edit and Delete are in the page but not visible), feeds (Delete), harvest plan and harvested (last column), health events (Closed), experiment data (Release) and places (Until), duties (Not verified). Solution: column priority, cards under 640 px, sticky first column and sticky actions, a visible scroll affordance.
2. **On a 390 phone most tables show only their first column** (meal board: unit names only, no Record meal; production units; water latest; Today & attendance; storage), and 23 pages scroll sideways as a whole (role edit 630 px, report draft 694, feeding records 548, harvested 548, treatments 548, card designer 451, leave list and approve dialog 444, tasks 458, water limits 422, storage tabs 409, equipment and tanks 410, health events 395, ...).
3. **The unit drawer's batch table** collapses to one word per line at 1440.
4. **Storage stock row actions run together** as "TransferIssueWrite offReturn".
5. **Mixed precision:** "251.804 kg" next to "1,420 kg" reads as 251 tonnes (storage overview, low stock).
6. **Monitoring card value cells** wrap origin and age word by word ("Meter / or test / kit, 2 d / ago").
7. **Shift schedule against Team overview:** days of approved leave show "Off" on the schedule (Jonas Eide on `/hr/schedule/`, Mohammed Al-Sayed on `/production/team/schedule/`) while the overview counts them On leave.
8. **Today tiles do not add up** (22 planned; Here now 4, Absent 1, On leave 1; no Done or Upcoming).
9. **A filed report whose records changed** lists raw keys ("/units/f62e32a3-.../avg_weight_g → 7150") instead of named figures.
10. **A sea-lice report page** lists notice fields (Happened on, What happened, Fish dead, all "–") under "As the records give it now", not the lice figures the print page has.
11. **Dates and times in two styles:** "10/26/2026 – 12/21/2026" on the experiment overview, "9:04 p.m." on monitoring, "26 Oct 2026" elsewhere.
12. **Overview against water page:** Production overview says "0 Units with a critical water value" while Water chemistry has 1 critical point (HA-K02 side outlet, CO<sub>2</sub> 15.6).
13. **Both overviews are placeholders** ("The production figures will appear here.", "Welcome, admin. The company's figures will appear here.").
14. **Two primaries on one tab** (medicine Withdrawal: Save medicine and Save withdrawal).
15. **Approve dialog footer**: Cancel alone on a row above a full-width Approve.
16. **"Crew this week: Nobody else is placed in your department this week."** shown to the admin, who has no department.
17. **A value and its origin run together** on Water chemistry ("13.7unit sensor #1 · 0 s ago": the origin sits inline with no space), and the longer cells push the table further off the right edge.
18. **Monitoring cards with sensor values** wrap origin and age to five lines per value ("13.6 / unit / sensor / #17 · / just now").
19. **Norwegian Monitoring overflows at 1440** (the page is 1,448 px wide; on the phone too): the toolbar's longer labels do not wrap.
20. **Live values mix precisions** in one column ("13", "11.800", "45.600", "101"): use each quantity's decimals.
21. **A forbidden page is a bare "403 Forbidden"** with no shell, menu or way back (Team list and Organization chart for a Production manager or worker).
22. **Date-time fields show the browser's US format** ("11/06/2026 09:19 AM") on Charts, the Move dialog and the forms, beside "6 Nov 2026, 09:19" in the page.
23. **A side-outlet sample changed status overnight:** HA-K02 side outlet CO₂ 15.6 (manual, 3 days old) was Critical on 5 Nov and shows "No limit" on 6 Nov; the page does not say why.
24. **The Production worker opens Team overview by its address** although the menu hides it, and the page then shows only her own row without saying why.
25. **The Channels list overflows on the phone** (394 px).

## Rejected alternatives

- Crimson as primary: reads as an alarm in a product whose alarms are the point.
- A blue filled primary: the SaaS default; ink is the trout's back and ties the button to the rail.
- One rose limit line per chart: cannot show two-level limits (oxygen 7.00 and 6.00).
- Violet for holds: a fifth hue that merges with the plum and indigo series colours.
- KPI tile row, teal ocean look, waves: the default dashboard and the water cliché.
- Safety sentences behind an "i" popover: an operator who assumes an alert exists is the failure case.
- Colouring normal values green on the monitoring wall: breaks "grey by default"; the eye must find the one abnormal card among 23.
- The browser `<meter>` for limits: the browser picks its own colours and has three cut points where a limit has four.
