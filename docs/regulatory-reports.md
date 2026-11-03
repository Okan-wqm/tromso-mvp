# Regulatory reports: what the authorities ask, where each number comes from, and the design

Phase 1 of porting the platform's regulatory reports (`apps/farm-service/src/regulatory/`, the farm module's
`pages/reports/`) into the prototype. This is the map the code will be built from: every report the farm
owes, every field of it with the place it comes from here, what is missing, what was found wrong in the
source and on our side, and the design. No app code is written in this phase.

**The owner's brief.** Reports are made from the site and its production units, automatically or
semi-automatically: the cleaner-fish report's mortality, and the cage each count belongs to, come from the
units. Most of what the reports ask is already recorded (stock, mortality, feed, moves, harvest). **Sending is
not automatic**: people file the reports themselves (Altinn, Mattilsynet's forms, e-mail, telephone), then
record here that, when and with which receipt they did. What was filed is frozen; if the records behind it
change afterwards, the page says the filed report no longer matches and a correction is needed. Reports that
fall due are listed per site and period with their deadlines without anyone creating them. Event reports
(escape, disease, welfare) are started by a person and prefilled with what is known.

**What was read.**
- Source: `aquaculture_platform`, branch `snowball-test`, commit `352aa2a8` (2026-10-29). Backend paths are
  relative to `apps/farm-service/src/regulatory/` unless they start with another folder; UI paths to
  `web/modules/farm-module/src/pages/reports/`.
- Ours: `wip/reports` at `2104a3a`; the health records from `wip/health` (`scratchpad/wt-health`, in progress,
  marked **(health)**: they land before this work is built, and their line numbers may still move).
- The regulations, read on lovdata.no on 2026-11-03: lakselusforskriften (FOR-2012-12-05-1140),
  akvakulturdriftsforskriften (FOR-2008-06-17-822, last amended FOR-2025-10-10-2019), dyrehelseforskriften
  (FOR-2022-04-06-631) as cited by the health records (`farm/health/diseases.py`, health). Mattilsynet's and
  Fiskeridirektoratet's pages where cited.

**How reliable each statement is.** ✔ = re-read by the lead at the cited lines (or, for an official source, read
by the lead). **E1** to **E4** = found by one of the four checking experts at the cited place: E1 Norwegian
regulatory reporting (official pages), E2 the source's report code, E3 production data against our ledger, E4 our
architecture; the lead re-read those also marked ✔.
**Unverified** = not confirmed from an official page or a test. The source's own field lists for the
Mattilsynet API are a transcription it never compared with Mattilsynet's swagger (`"x-verified": false` on
line 6 of each of `schemas/official/*.schema.json` ✔); where this document gives an API field name from them, it
says "(source schema, unverified)".

## Contents

1. [The reports](#1-the-reports)
2. [Where each field comes from here](#2-where-each-field-comes-from-here)
3. [Cleaner fish](#3-cleaner-fish)
4. [Bugs found](#4-bugs-found)
5. [Design](#5-design)
6. [Decisions for the owner](#6-decisions-for-the-owner)

## 1. The reports

The official sources, read 2026-11-03:
- **Mattilsynet's reporting API**, whose OpenAPI is public: `https://innrapportering-api.fisk.mattilsynet.io/q/openapi?format=json`
  (production, version `de3580a`; dev identical) (E1; the lead read the saved copy ✔). The source's notes say every
  API mirrors its Altinn form (`docs/integrations/mattilsynet-reporting-api.md:18` ✔); Mattilsynet's API page: "Dersom det ikke er mulig ...
  kan dere rapportere manuelt via Altinn for alle skjemaene"
  (`mattilsynet.no/om-mattilsynet/api/maskinell-innrapportering-via-api-innen-akvakultur-omradet`, E1). So the
  API's field list **is** the Altinn form's content, and this document takes field names, types and
  definitions from it, never from the source's transcription.
- The regulations on lovdata.no: lakselusforskriften (FOR-2012-12-05-1140), akvakulturdriftsforskriften
  (FOR-2008-06-17-822), restkontrollforskriften (FOR-2000-01-27-65), dyrehelseforskriften (FOR-2022-04-06-631) ✔.
- The Altinn form pages (`info.altinn.no/skjemaoversikt/...`) and Mattilsynet's and Fiskeridirektoratet's
  guidance pages, as cited (E1).

### 1.1 Overview

| Report | Authority | Legal basis | Who files, for what | Period | Deadline | Channel (people file, section 5) |
|---|---|---|---|---|---|---|
| Sea lice | Mattilsynet | lakselusforskriften § 10; counting § 6, Vedlegg 1 ✔ | every site with salmonids in the sea (§ 2: "akvakulturanlegg med laksefisk i sjø" ✔) | ISO week | "senest i løpet av tirsdag i nærmeste påfølgende uke" (§ 10 ✔) | Altinn "Ukentlig rapportering av lakselus", or the API (E1) |
| Smolt (settefisk) | Mattilsynet | akvakulturdriftsforskriften § 58 ✔ | a hatchery, "for hver produksjonsenhet som er i drift med startfôringsyngel eller eldre fisk" | calendar month | "den 7. i påfølgende måned" (§ 58 ✔) | Altinn "Månedsrapport settefisk" (role Daglig leder), or the API (E1) |
| Cleaner fish (rensefisk) | Mattilsynet (copy to Fiskeridirektoratet) | akvakulturdriftsforskriften § 44 first paragraph a, b, f, g, h, applied to cleaner fish by § 3 first paragraph h (Altinn page, E1) | "Innehavere av akvakulturtillatelser som bruker rensefisk for lusebekjempelse på matfisklokalitet" (E1) | calendar month, from January 2026 (before: in Fiskeridirektoratet's biomass report, E1) | "Månedlig, med frist til den 7. i påfølgende måned" (Altinn, E1; the API: "senest 7 dager etter måneden" ✔) | Altinn "Månedlig rapportering for bruk av rensefisk", or the API (E1) |
| Monthly biomass | Fiskeridirektoratet | akvakulturdriftsforskriften § 44 ✔ | "akvakulturanlegg i sjø med fisk": every production unit in operation; one joint report under samdrift | calendar month | "den 7. i påfølgende måned" (§ 44 ✔) | Altinn, "enten via et rapporteringsskjema i Altinn eller direkte fra fagsystemene" (Fiskeridirektoratet's statistics page, E1); the old Altinn page ("FD-0001") now answers 404 and a move to API-only from Q2 2026 is reported only by the trade press: **current channel unverified** |
| Planned slaughter | Mattilsynet | restkontrollforskriften § 9a ✔: "Oppdretter plikter å underrette Mattilsynet om slakting ... senest når fisken er satt til sulting" | the **farmer** (§ 9a); the Altinn form says "Slakterier/pakkerier av oppdrettsfisk skal levere skjema" (E1), i.e. the slaughterhouse files under its approval number, per slaughter week, listing the farmers' localities | ISO week of the slaughter | "torsdag kl. 24.00 i uken før slakting skal skje" ✔; correctable until Tuesday 09:00 of the slaughter week (Mattilsynet guidance, E1) | Altinn "Planlagt slakting av oppdrettsfisk", or the API |
| Executed slaughter | Mattilsynet | not cited on the Altinn page (E1, unverified) | the slaughterhouse (Altinn, E1): kg **gutted** per quality class per locality | ISO week | "Alle slakteuker som avsluttes i en kalendermåned, skal være rapportert senest den 7. i påfølgende måned" (E1) | Altinn "Gjennomført slakting av oppdrettsfisk", or the API |
| Escape | Fiskeridirektoratet | akvakulturdriftsforskriften § 38 ✔ | anyone who knows of an escape **or suspects one**, from own or others' units or transport | event | "straks" (§ 38 ✔) | Altinn "Rømt oppdrettsfisk eller avvik" (links to the form on fiskeridir.no), "skal meldes med én gang" (E1) |
| Disease | Mattilsynet | dyrehelseforskriften § 7 (E1; quoted in `farm/health/diseases.py:21-23`, health) | on reason to suspect, or a finding of, a listed disease (except sea lice); unclear raised mortality after the vet's assessment "så snart som praktisk mulig" | event | "umiddelbart" | Altinn "Varsel om velferdshendelse og listeført sykdom på oppdrettsfisk" (E1) |
| Welfare | Mattilsynet | akvakulturdriftsforskriften § 14 ✔ | "forhold som har medført alvorlige velferdsmessige konsekvenser for fisken, herunder om sykdom, skade eller svikt" | event | "umiddelbart" (§ 14 ✔) | the same Altinn form for events on a site; e-mail to varsling.akvakultur@mattilsynet.no for transport and slaughterhouse events (Mattilsynet, reviewed 30.03.2026, E1) |

Not in this work, listed so nobody looks for them: land and freshwater sites file no monthly biomass report but
notify when a site is taken into use or emptied and give their yearly stock by 7 January (§ 44a ✔); the
hatchery's yearly stock in continuous operation (§ 58 fourth paragraph ✔); the broodstock year report (§ 45,
15 July ✔); recapture start and end (§ 39 third paragraph ✔); samdrift notices (§ 49 ✔); the two-year
operating plan due 1 October (§ 40; Mattilsynet's driftsplan API, E1); Mattilsynet's automated lice-count API
(by agreement only, E1).

### 1.2 Sea lice, weekly

§ 10 ✔ asks for each week: a. sea temperature; b. treatment against lice; c. the active substances and the amounts
used; d. results of sensitivity tests; e. suspicion of resistance; f. the number of lice of the adult female,
mobile and attached stages. How the numbers are made (✔ lovdata; quoted in `farm/health/lice.py:1-19`, health):
- temperature at **3 m depth**, measured at least weekly (§ 6);
- counting every 7 days at 4 °C or above, every 14 below (§ 6); not required when all fish of the site are to be
  slaughtered within 14 days of the due count (§ 6); a cage emptied during the week is still counted (Mattilsynet
  complaint decision 20.02.2026, E1);
- at least 20 fish per cage in weeks 14–21 (Nord-Trøndelag and south) or 19–26 (Nordland, Troms, Finnmark), 10
  otherwise (Vedlegg 1 points 2–3);
- **the site's average per stage is the mean of the cages' averages**: "legge sammen gjennomsnittene fra hver merd
  delt på antall merder" (Vedlegg 1 point 6);
- limit, shown not filed: fewer than 0.2 adult females per fish in weeks 16–21 (south) / 21–26 (north), 0.5
  otherwise (§ 8).

API `POST /api/lakselus/v1/lakselus`, `LakselusrapporteringDto` (✔ copy):

| Field | Required | Type and unit | Definition |
|---|---|---|---|
| `rapporteringsår`, `rapporteringsuke` | yes | integers | the ISO week |
| `organisasjonsnummer`, `lokalitetsnummer`, `kontaktperson {navn, epost, telefonnummer}` | yes | 9 digits; integer | |
| `sjøtemperatur` | **yes** | number, °C | § 6: at 3 m depth (the API has no depth field) |
| `lusetelling {voksneHunnlus, bevegeligeLus, fastsittendeLus}` | **no** (nullable) | numbers ≥ 0, lice per fish | the site's average per stage. A week without a count is filed without it; there is no "not counted" reason field (E1) |
| `ikkeMedikamentelleBehandlinger[]` | no | `type` TERMISK_BEHANDLING, MEKANISK_BEHANDLING, FERSKVANNSBEHANDLING, ANNEN_BEHANDLING; `gjennomførtFørTelling` bool; `heleLokaliteten` bool; `antallMerder`; `beskrivelse` (ANNEN only) | non-medicinal treatments of the week |
| `medikamentelleBehandlinger[]` | no | `type` FORBEHANDLING, BADEBEHANDLING, ANNEN_BEHANDLING; the same flags; `virkestoff {type, styrke {verdi, enhet}, mengde {verdi, enhet}}` with type AZAMETHIPHOS, CYPERMETHRIN, DELTAMETHRIN, IMIDAKLOPRID, HYDROGENPEROKSID, DIFLUBENZURON, EMAMECTIN_BENZOAT, TEFLUBENZURON, ANNET_VIRKESTOFF; strength mg/g, mg/mL, g/kg, mg/kg, %; amount g, kg, t, L | medicinal treatments; a treatment spanning two weeks is reported in both (guidance, E1) |
| `kombinasjonsbehandlinger[]` | no | lists of the two kinds above | treatments given together |
| `resistensMistanker[]` | no | `resistens`; `årsak` BIOESSAY, NEDSATT_BEHANDLINGSEFFEKT, SITUASJONEN_I_OMRÅDET, ANNEN_ÅRSAK | § 10 e |
| `følsomhetsundersøkelser[]` | no | `utførtDato`, `laboratorium`, `resistens`, `testresultat` FØLSOM, NEDSATT_FØLSOMHET, RESISTENS | § 10 d |

A correction replaces the whole week: "melde inn heile skjemaet for den relevante veka på nytt" (Mattilsynet's
guidance, E1). Unverified: whether a fallow or empty site files weekly.

### 1.3 Smolt (settefisk), monthly

§ 58 ✔: "for hver produksjonsenhet som er i drift med startfôringsyngel eller eldre fisk: antall fisk, snittvekt og
dødelighet". API `POST /api/settefisk/v1/settefisk` (✔ copy): the identity as above, `rapporteringsmåned`,
`rapporteringsår`, and `produksjonsenheter[]` (at least one; "kun produksjonsenhetene som hadde settefisk i løpet
av måneden"), each:

| Field | Type and unit | Definition (the API's) |
|---|---|---|
| `karId` | text | "Kar-ID skal stemme overens med driftsjournalen" |
| `artskode` | `[A-Z]{3}`, FAO ASFIS | species |
| `snittvektGram` | number > 0, g | average weight in the unit |
| `beholdningVedMånedsslutt` | integer | fish at the month's end, "eller når produksjonsenheten ble tømt" |
| `antallAvlivet` | integer | "avlivet og/eller destruert" in the month |
| `antallSelvdød` | integer | died in the month |
| `antallFlyttetEksternt` | integer | live fish moved **out of the site** in the month; "Intern flytting mellom kar skal ikke rapporteres" |

`organisasjonsnummer` here and in the cleaner-fish report is "selskapet som eier fisken" (✔ copy).

### 1.4 Cleaner fish (rensefisk), monthly

API `POST /api/rensefisk/v1/rensefisk`, `RensefiskrapporteringDto` (✔ copy). Report level: the identity,
`rapporteringsmåned`, `rapporteringsår`, **`tørrforKg` and `våtforKg` (required, integer kg, the month's totals for
the site)** and `produksjonsenheter[]` (at least one: the units "rensefisken er satt ut i eller tatt ut av"),
each with `merdId` ("skal stemme overens med driftsjournalen") and `arter[]` (at least one):

| Field | Type | Definition (the API's, shortened) |
|---|---|---|
| `artskode` | `[A-Z]{3}`, FAO ASFIS | the cleaner species |
| `opprinnelse` | VILLFANGET, OPPDRETTET, VILLFANGET_OG_OPPDRETTET | wild-caught, farmed, or both in the unit. **There is no "unknown"** |
| `beholdningVedForrigeMånedsslutt` | integer | fish of the species and origin in the unit at the end of the month before |
| `utsett.antallNy` | integer | new fish stocked into the unit |
| `utsett.antallFlyttetInn` | integer | moved in from another unit |
| `uttak.antallAvlivetSykdom` | integer | weakened fish culled for signs of disease |
| `uttak.antallAvlivetSkader` | integer | weakened fish culled for wounds or injuries not from disease |
| `uttak.antallAvlivetAvmagret` | integer | weakened fish culled for a lower condition factor than at stocking |
| `uttak.antallAvlivetForeståendeHåndteringAvLaksen` | integer | **healthy** fish culled because of an upcoming handling of the salmon (delousing, grading …) |
| `uttak.antallAvlivetForeståendeUgunstigLevemiljø` | integer | **healthy** fish culled because of an upcoming unfavourable environment (season, wind, current, harmful organisms) |
| `uttak.antallAvlivetSkalIkkeBrukes` | integer | **healthy** fish culled because they are not to be used further (end of the salmon cycle, grown too big) |
| `uttak.antallSelvdød` | integer | dead fish taken out in the month |
| `uttak.antallFlyttetUt` | integer | live fish moved to be kept in another unit |
| `uttak.antallKanIkkeGjøresRedeFor` | integer | fish that cannot be accounted for: escaped, disappeared, unexplained |

The source's schema has fields the API does not (`samdriftOrganisasjonsnumre`, `produksjonssyklusStart`), an
origin the API does not (`UKJENT`), and optional feed the API requires (REP-50).

### 1.5 Monthly biomass to Fiskeridirektoratet

§ 44 ✔, from a site in the sea with fish, monthly: the date the site was left fallow; and **for each production
unit in operation**: a. the unit's number tied to the permit holder; b. stocking: species, number of fish and
**year class** (årsklasse); c. stock: species, number and year class; d. biomass; e. harvest: species, number,
**slaughter weight and slaughter condition**; f. live fish taken out: species, number and quantity, and the site
they were moved to; g. losses: mortality and other causes, species, number, quantity; h. feed used in kg and the
feed type; i. the volume the fish can move in; j. whether the unit is used for reduced-capacity production.
Broodstock of salmon, trout and rainbow trout: spring or autumn stocking. One joint report under samdrift. The
third paragraph (feed trade names, medicines, impregnated nets) is not in force: § 70 says it takes effect when
the two ministries decide (E1).

Fiskeridirektoratet's statistics page: "månedlig på merdnivå; en rapport per lokalitet, per selskap"; the loss
causes in its statistics are Dødfisk, Utkast fra slakteri, Rømming, Annet, Tellefeil (E1). The form's exact
fields are **unverified** (no public form or API found, E1). The daily journal of § 42 ✔ holds the same facts per
unit (stock with year class, biomass and its basis, losses, feed kg and type), so the report is the month's read
of what the records here already are.

### 1.6 Slaughter, planned and executed

Planned, `POST /api/slakt/v1/planlagt` (✔ copy): `uke` (1–53), `år`, `organisasjonsnummer` (`\d{9}`, "selskapet
som rapporter planlagt slakt"), `godkjenningsnummer` (`[a-zA-Z\d]{1,6}`, "Godkjenningsnummer til slakteriet"),
`planlagteLokaliteter[]` ("bare lokalitetene som har planlagt slakt"): `organisasjonsnummer` and
`lokalitetsnummer` of the farmer whose fish are planned, `ukeplanPerArt[]` {`artskode`, `mandagKg` …
`søndagKg`, integer kg}. Weight basis of the planned kilos: **unverified**.

Executed, `POST /api/slakt/v1/utfort` (✔ copy): `slakteuke`, `slakteår`, the reporter's `organisasjonsnummer`,
`godkjenningsnummer`, `utførteLokaliteter[]` {farmer's `organisasjonsnummer`, `lokalitetsnummer`, `arter[]` {`art`,
`superiorKg`, `ordinærKg`, `produksjonsfiskKg`, `utkastKg`: integer, "Antall kg (sløyd vekt)"}}: **gutted weight**
per quality class, which only the slaughterhouse knows.

So: the duty to notify a planned slaughter is the farmer's (§ 9a), the form is filed per slaughterhouse and week,
and the executed report is the slaughterhouse's own result (decision D-3).

### 1.7 Escape

§ 38 ✔: "Det skal straks meldes fra til Fiskeridirektoratet dersom det er kjennskap til at fisk rømmer, eller når
mistanke om rømming foreligger, uavhengig av om fisken har rømt fra egne eller andres produksjonsenheter eller
installasjoner eller fra transportenheter. Meldingen skal sendes inn på den måten tilsynsmyndigheten bestemmer."
Every escape and every suspicion, whatever the number. The journal holds (§ 41 c, sea ✔; § 57 b, hatcheries ✔):
cause, time, species, number escaped, their average weight (size), health status, and that and when it was
reported to Fiskeridirektoratet; recapture catches (§ 41 d, § 57 h ✔). Recapture is a duty within 500 m, and its
start and end are reported (§ 39 ✔). The notice form's own fields are **unverified** (rendered by script, E1).

### 1.8 Disease and welfare notices

- Disease (dyrehelseforskriften § 7, E1): "Ved grunn til mistanke om forekomst eller ved påvisning av en
  listeført sykdom ... unntatt lakselus, skal driftsansvarlige ... umiddelbart melde fra til Mattilsynet". The
  health records carry the catalogue (EU A, C–E; national F, G) and the fact "Mattilsynet notified at" on the
  health event (`HealthEvent.authority_notified_at`, `farm/models/health.py:421`; `needs_notification`, health).
  "All informasjon fra analyselaboratorium skal videreformidles" (Altinn page, E1).
- Welfare (§ 14 ✔): immediate, also "ved gradvis negativ påvirkning" (Altinn, E1). For transport and
  slaughterhouse events Mattilsynet asks by e-mail for: site number and name, the company, transport unit and
  slaughterhouse, cause, when it happened or was found, number and species dead or injured, total fish involved,
  the situation now, a contact person (E1). The Altinn form's fields are behind log-in: **unverified**.

### 1.9 Identity

| Key | Official rule | Here | Status |
|---|---|---|---|
| `organisasjonsnummer` | "nøyaktig 9 sifre"; in the smolt and cleaner-fish reports, of "selskapet som eier fisken" ✔ | only `Site.organisation_number_override`, `CharField(20)`, unchecked (`farm/models/site.py:48` ✔); no company number anywhere (grep ✔) | **missing**, OUR-12 |
| `lokalitetsnummer` | integer 10000–99999, "Må finnes i Akvakulturregisteret" ✔ | `Site.lokalitetsnummer`, same range, unique among live sites (`farm/models/site.py:43-47`, `:102-111` ✔) | exists |
| `karId` / `merdId`; § 44 a unit number | free text that "skal stemme overens med driftsjournalen" ✔ | `Tank.regulatory_unit_id`, unique **company-wide** (`farm/models/tank.py:339`, `:400-404` ✔) | exists; must be unique per site, not company (OUR-07) |
| `artskode` | `[A-Z]{3}`, "store bokstaver etter FAO-standarden" (ASFIS) ✔ | `Species.official_code`, `^[A-Z]{3}$` (`farm/models/species.py:15`, `:92-95` ✔) | exists; the cleaner-fish codes in our catalogue are wrong (3.4) |
| `godkjenningsnummer` | `[a-zA-Z\d]{1,6}` ✔ | `SlaughterFacility.approval_number`, `^[A-Z0-9]{1,6}$`, stored in capitals (`farm/models/harvest.py:26-29`, `:63-64`, `:114-116` ✔) | exists; the official rule confirms the format (the code's "not verified" note can go) |
| `kontaktperson {navn, epost, telefonnummer}` | required on every report ✔ | the person filing; `Site.contact_email`/`contact_phone`, `SiteContact` (`farm/models/site.py:79-81`, `:144-162` ✔) | entered on the report, prefilled from the person |
| `klientReferanse` | unique per submission ✔ | — | only for API filing; the export carries the report's id |

## 2. Where each field comes from here

Notation. *Lines(K, P)*: the stock ledger's lines (`StockMovement`, `farm/models/stock.py:273-333` ✔) of kind K
whose operation is live and dated in the period P. *The fold at D*: the stock as it was at the end of day D,
by folding the live lines dated up to D (`farm/stock/fold.py:133-177` ✔; `share_on`, `farm/stock/read.py:52-55` ✔
does this for one unit and batch). A unit's site is its production department's (`farm/stock/dates.py:27-28` ✔).
Every figure is read on demand from these; a report never keeps a second copy of a count.

### 2.1 Reads to add (shared, in `farm/stock/read.py` and `farm/feeding/read.py`, not in the reports code)

| Read | What | Why |
|---|---|---|
| `stock_on(units, day)` | {unit: UnitStock} at the end of `day`: the fold of every batch ever in the units, cut at `day` | only "now" exists (`unit_counts`, `stock_of`, `farm/stock/read.py:58-62`, `:196-218` ✔, E3); every monthly report needs the month's end and start |
| `movements(units, first, last)` | the live lines of the units dated in the period, with their reason, pair and the grams they moved (`moved_grams`, `farm/stock/read.py:44-49` ✔) | in/out per unit and batch; a move's other end (same site or not) from its pair |
| `fed(units, first, last)` | kg per unit, batch and feed in the period, from the feeding walk's split (`split_of`, `farm/feeding/read.py:166-172` ✔) | biomass report (h), cleaner-fish feed |

Biomass between weighings: the fold keeps the last measured average until the next weighing
(`farm/stock/fold.py:13-14` ✔); the feeding projection estimates growth (`project`, `farm/feeding/read.py:147-158` ✔)
but reads today's protocols and temperatures, so it is not reproducible for a past day (E3). § 42 b asks for
"biomasse og grunnlaget for beregningen": the report gives the **book** biomass (measured weights) and states
the date of each unit's last weighing as its basis; the projection is shown beside it, not filed (decision D-7).

### 2.2 Sea lice

| Field | Here | Status |
|---|---|---|
| week | ISO week on the site's clock (`farm/health/read.py:52-54`, health) | ok |
| `sjøtemperatur` | `WaterMeasurement.temperature_c` (`farm/models/water.py:107` ✔) of the site's units or systems in the week | **gap**: samples have no depth (`farm/models/water.py:77-119` ✔, grep `depth`: none, E3); § 6 asks for 3 m. Proposed `WaterMeasurement.depth_m` (Decimal 5,2, null) and the rule "the week's mean of the site's samples taken at 3 m"; without one the person enters it (OUR-13) |
| `lusetelling` (3 stages) | `lice_weeks()` → `LiceWeek.average(stage)`: the latest count of each unit counted in the week, mean of the units' averages (`farm/health/read.py:57-126`, health) | ok, the health read is reused as it is |
| `ikkeMedikamentelle[].type` | `Treatment.method` thermal / mechanical / freshwater / other (`farm/models/health.py:208-219`, health), `reason = sea_lice` | ok (1:1) |
| `medikamentelle[].type` | `Treatment.method` in_feed → FORBEHANDLING, bath and dip → BADEBEHANDLING, injection → ANNEN_BEHANDLING | mapping unverified (E3) |
| `virkestoff.type` / `styrke` / `mengde` | `Medicine.lice_report_code` (official values, `farm/models/health.py:72-84`, `:123`), `strength_value`+`strength_unit` (`:125-127`), `Treatment.amount_value`+`amount_unit` (`:279-281`) (health) | ok; the amount is optional, and a lice treatment may use a medicine with no substance code (OUR-10, belongs to health) |
| `gjennomførtFørTelling` | derived from `Treatment.start_date`/`end_date` against each treated unit's count date that week | **same-day ambiguous** (no times on either): shown derived, the person confirms (stored on the report) |
| `heleLokaliteten`, `antallMerder` | `Treatment.units` against the units holding fish that day (`stock_on`) | derived |
| `kombinasjonsbehandlinger` | none (one medicine per treatment, `farm/models/health.py:271`, health) | **person enters** on the report: which of the week's treatments were given together |
| `resistensMistanker`, `følsomhetsundersøkelser` | none (`EventKind` has no such kind, `farm/models/health.py:367-371`, health) | **person enters** on the report (child rows); the source of truth for sensitivity tests could later be a lab result of the health records |

### 2.3 Smolt

| Field | Here | Status |
|---|---|---|
| `karId` | `Tank.regulatory_unit_id`, else `Tank.code` | ok (OUR-07) |
| `artskode` | the unit's batches' `Species.official_code` (one species per unit, `farm/stock/services.py:283-286` ✔) | ok; blank code → the report cannot be marked ready |
| `beholdningVedMånedsslutt` | fold at the month's last day, count; for a unit emptied in the month, the count before it was emptied ("eller når produksjonsenheten ble tømt"; reading unverified) | exact |
| `snittvektGram` | fold at the month's last day, grams / count (book) | rule D-7 |
| `antallSelvdød` | −Σ lines(MORTALITY, month) count_delta | ok |
| `antallAvlivet` | −Σ lines(CULL, month) | ok |
| `antallFlyttetEksternt` | −Σ lines(TRANSFER_OUT, month) whose paired TRANSFER_IN is on another site (same operation, same `pair`, `farm/models/stock.py:294` ✔) | **gap**: no operation delivers fish out of the company (a sale of smolt); HARVEST needs a slaughter facility (OUR-04, E3) |
| which units | every unit of the site with a line in the month or fish at its start, holding "startfôringsyngel eller eldre fisk" (§ 58) | eggs and yolk-sac larvae are left out by `Batch.input_stage` plus age; the exact rule is a decision (D-8) |

### 2.4 Cleaner fish (once cleaner fish can share a cage, section 3)

| Field | Here | Status |
|---|---|---|
| `merdId` | `Tank.regulatory_unit_id`, else code | ok |
| `artskode` | `Species.official_code` of the cleaner batches (`cleaner_fish_type` set, `farm/models/species.py:103-105` ✔) | codes unverified (3.4) |
| `opprinnelse` | folded per unit and species over its batches' `Batch.origin`: wild-caught, farmed, or both | **gap**: `purchased` says how, not wild or farmed (`farm/models/stock.py:40-43` ✔), and the API has no "unknown" (1.4); proposed: a provenance farmed / wild-caught on the batch, required for a cleaner-fish species (E3) |
| `beholdningVedForrigeMånedsslutt` | fold at the day before the month, count | exact |
| `utsett.antallNy` | Σ lines(INPUT, month) | ok |
| `utsett.antallFlyttetInn` | Σ lines(TRANSFER_IN, month): from any other unit, of this site or another (the API: "fra en annen produksjonsenhet") | ok |
| `uttak.antallSelvdød` | −Σ lines(MORTALITY, month), every cause | ok |
| `uttak.antallAvlivetSykdom` … `SkalIkkeBrukes` | −Σ lines(CULL, month) by reason | **gap**: `CullReason` (`farm/models/stock.py:87-94` ✔) has `sick` only; proposed: the cull of a cleaner fish takes the official six causes (OUR-08) |
| `uttak.antallFlyttetUt` | −Σ lines(TRANSFER_OUT, month) | ok |
| `uttak.antallKanIkkeGjøresRedeFor` | −Σ lines(ADJUSTMENT, month) with reason `unaccounted_loss` (a harvest that empties a unit writes it, `farm/stock/services.py:594-596` ✔) | partial: escape and count corrections need a rule (D-9) |
| balance | opening + utsett − uttak = closing (fold at the month's last day) | **checked on read**; a unit that does not balance (a harvest of cleaner fish, an upward correction) blocks "ready" and says why |
| `tørrforKg` / `våtforKg` (the site's totals for the month, integer kg) | `fed()` of the site's cleaner batches, by the feed's form | **gap**: a feeding cannot name its fish (split by biomass, `farm/feeding/fold.py:184-191` ✔) and a feed has no dry/wet form (`farm/models/feed.py:47-56` ✔); proposals in 3.2 |

### 2.5 Monthly biomass (§ 44)

| § 44 item | Here | Status |
|---|---|---|
| fallow date | the day the site's last fish left (fold) | derivable |
| a. unit number | `Tank.regulatory_unit_id` | ok (OUR-07) |
| b. stocking: species, number, year class | lines(INPUT) and arrivals from other sites in the month | **year class missing** (OUR-16); proposed `Batch.year_class` (a year, entered at stocking, default the input date's year) |
| c. stock: species, number, year class | fold at the month's end, per unit and batch | year class as above |
| d. biomass | fold at the month's end, kg (book) | rule D-7 |
| e. harvest: species, number, slaughter weight, condition | lines(HARVEST): count, `measured_weight_kg` (round weight, `farm/models/stock.py:291-293` ✔) | **slaughter weight and condition missing**: round kilos only; the slaughter result is not ported (`farm/models/harvest.py:148-149` ✔; Harvest owner decisions) (OUR-18) |
| f. live fish out, destination site | lines(TRANSFER_OUT) whose pair is on another site; the destination site's lokalitetsnummer | ok within the company; **out of the company missing** (OUR-04) |
| g. losses: mortality and other causes, number, quantity | lines(MORTALITY, CULL, ADJUSTMENT<0) by reason; kg from `measured_weight_kg` when weighed, else the grams the fold took out | ok; the authority's cause list unverified |
| h. feed kg and feed type | `fed()` per unit and feed; `Feed.feed_type` (`farm/models/feed.py:47-56` ✔) | ok; whether "fôrtype" means this list is unverified |
| i. volume the fish can move in | `Tank.water_volume_m3` else `volume_m3` (`UnitStock.volume_m3`, `farm/stock/read.py:142-145` ✔) | ok |
| j. reduced-capacity production | none | **person enters** (rare; a unit flag later) |
| third paragraph (feed trade names, medicines, impregnated nets) | not in force (§ 70, E1) | not reported; `Feed.name` and the treatments (health) give them when it is |

### 2.6 Slaughter

| Field | Here | Status |
|---|---|---|
| planned kg per locality, species and weekday | `HandlingPlanItem` (kind harvest) live and not cancelled: `date.isoweekday()`, `unit` → site, `batch.species`, `planned_kg` (`farm/models/harvest.py:248-286` ✔) | `planned_kg` is round weight and may be empty (OUR-09) |
| executed kg per quality class | none | **missing**: the slaughter result (gutted kg per class) attaches to `HarvestRecord` later (`farm/models/harvest.py:148-149` ✔) |
| `godkjenningsnummer` | `HarvestRecord.facility.approval_number`, `HandlingPlanItem.facility` (`farm/models/harvest.py:154-155`, `:271-272` ✔) | ok, per harvest (the source used one default facility, HRV-08) |

### 2.7 Events

| Event | Here | Status |
|---|---|---|
| Escape | the count would be an ADJUSTMENT line with reason `escape` (`farm/models/stock.py:109-113` ✔), but count adjustments have no dialog (`farm/stock/services.py:41` ✔, OUR-03); species, unit, average weight from the unit's stock (`stock_on`) | **missing**: cause, time found, suspected or confirmed, health status, recapture. Proposed: an escape record of the stock (see 5.3) |
| Disease | `HealthEvent` with a listed diagnosis: site, units, date, diagnosis, confirmation, `authority_notified_at` (`farm/models/health.py:393-443`, health) | ok; the deaths under it from `with_deaths` (`farm/health/read.py:42-48`, health) |
| Welfare | `HealthEvent` of kind mortality with its deaths (health); equipment failures have no record | the report holds what the person writes; prefilled from the health event when started from one |

## 3. Cleaner fish

### 3.1 In the source

A cleaner-fish group is its own batch (`batchType = CLEANER_FISH`, `batch/entities/batch.entity.ts:143-149`,
`batch/entities/batch.types.ts:106`, E2) whose fish sit in the salmon's cage as a JSON list on the cage's single
`tank_batches` row (`cleanerFishDetails`, `batch/entities/tank-batch.entity.ts:78-92`, `:208-225`, E2), moved by
five commands of their own (deploy, mortality, removal, transfer, create) with operation types
`cleaner_deployment`, `cleaner_mortality`, `cleaner_removal`, `cleaner_transfer_in/out`
(`batch/entities/tank-operation.enums.ts:39-43`, E2). A second stock beside the salmon's, with its own bugs
(REP-46 to REP-49) and no month-end reconstruction (`batch/services/stock-reconstruction.service.ts:30-34`, E2).
No record says whether a removed fish was culled or died, nor why in the regulator's terms: the nine uttak causes
**cannot be derived from the source's records** (E2).

### 3.2 Here

The README already says the cleaner-fish track comes "later, as batches of a cleaner-fish species"
(README.md, Operations › Production units, "Not ported") ✔, and a species can be marked a cleaner fish
(`Species.cleaner_fish_type`, `farm/models/species.py:47-51`, `:103-105` ✔). That is the right shape: one ledger,
the same operations (stocking, mortality, cull, transfer, harvest), the same fold, so the cleaner-fish report's
counts are the ledger's per unit, exactly as the owner asks. What blocks it:

1. **One species per unit** (owner decision Q1): the stock refuses a second species in a unit
   (`farm/stock/services.py:13-14`, `:283-286`, `:332-336` ✔). Lumpfish and wrasse live in the salmon's cage;
   § 47 fourth paragraph forbids only fish of different *holders* in one unit ✔. Proposed: the rule counts
   production species only; any number of cleaner-fish batches may share a unit (decision D-1).
2. **Feed split**: each feeding is split between every batch in the unit by biomass
   (`farm/feeding/fold.py:184-191`, `_present` `:237-239` ✔): salmon feed would be booked to lumpfish and
   lumpfish blocks to salmon (OUR-02). Proposed: a feed says whom it is for (the feed's suitable species,
   `FeedSuitability`, `farm/models/feed.py:246-272` ✔, already lists species per feed); a feeding is split
   among the batches of the species it suits, and a feed suited to none of the unit's batches is refused.
   With a dry/wet form on the feed (`Feed.form`), the report's `tørrforKg`/`våtforKg` are reads.
3. **Unit figures** (density, capacity, survival, average, ration, FCR) sum every share
   (`farm/stock/read.py:126-182` ✔; `farm/feeding/projection.py:184-188`, E3); five places take the unit's first
   batch as "the" species (`farm/forms/feeding.py:78-79`, `farm/feeding/views.py:346`,
   `farm/handling/check.py:166`, `templates/farm/production_units.html:95`, `templates/farm/_unit_drawer.html:14`,
   E3). Proposed: the unit's production figures read the production shares; the cleaner fish get their own line
   in the drawer and the page's announced cleaner-fish tab (README, Production units ✔). Whether cleaner-fish
   biomass counts toward the unit's density and the site's MTB is a decision (D-2; unverified in law).
4. **Cull reasons**: the cull of a cleaner fish takes the six official "avlivet" causes (a second reason list
   for cleaner-fish species, checked by the database like `_reason_rule`, `farm/models/stock.py:252-256` ✔).
5. **Origin**: farmed / wild-caught / unknown beside how the fish were acquired; a wild-caught batch bought
   from a fisherman may then name its supplier (today refused, `chk_batches_supplier`,
   `farm/models/stock.py:184-190` ✔, OUR-11).

These are changes to the stock and feeding code, not to the reports; each is a step of its own with its own
tests and the owner's decision first (section 6).

### 3.3 What the report then is

Per unit with cleaner fish at the month's start or a cleaner-fish line in the month, per cleaner species: the
fold's count the day before the month, the month's lines by kind and reason, the fold's count at the month's
end, and the balance between them; the site's dry and wet feed of the month. Nothing is typed but the
contact person: every field of the API comes from the records.

### 3.4 The cleaner-fish species codes

The source's schema accepts USB, BER, GRO, BNB (`schemas/official/rensefisk-v1.schema.json:67` ✔) and its UI
maps USB to lumpfish (rognkjeks) (`CleanerFishReportTab.tsx:95-108`, E2). Our catalogue keeps these codes marked
unverified and notes that in FAO ASFIS USB is the ballan wrasse (`farm/species_catalog.py:7-13` ✔).
Mattilsynet's API asks for "kode i store bokstaver etter FAO-standarden" (`[A-Z]{3}`) ✔. Against the FAO ASFIS
list 2026.1 (E1): **LUM** *Cyclopterus lumpus* (lumpfish, rognkjeks); **USB** *Labrus bergylta* (ballan wrasse,
berggylt); **YFM** *Symphodus melops* (corkwing, grønngylt); **TBR** *Ctenolabrus rupestris* (goldsinny, bergnebb);
ENX *Centrolabrus exoletus* (rock cook, grasgylt). The source's BER, GRO and BNB are other species in ASFIS
(*Brachypterois serrulata*, "groundfishes nei", a sharkminnow) and its USB is the wrong fish: every cleaner-fish
code the source sends is wrong (REP-51), and so are ours (OUR-19), which are kept unverified and never filled in.
The Norwegian name to Latin name pairs are the usual ones; no official page lists them (E1, unverified).

## 4. Bugs found

IDs: **REP-** in the source (to go into `docs/aquaculture-platform-bugs.md` as a new section "Regulatory
reports" in Phase 2), **OUR-** on our side. Bugs already recorded under Harvest (HRV-02, -03, -04, -08, -13,
-14) and Health (HLT-09, HLT-11, HLT-22, in `wip/health`) are referenced, not repeated.

### 4.1 Source backend: assemblers, scheduler, drafts, biomass

Paths relative to `apps/farm-service/src/regulatory/`.

| ID | Sev. | Where | What is wrong | Here |
|---|---|---|---|---|
| REP-01 | High | `assembly/assemblers/rensefisk.assembler.ts:123-135` ✔, `:207-227` ✔ | **The cleaner-fish opening stock is reconstructed from today's composition**: `beholdningVedForrigeMånedsslutt` = the current `tank_batches.cleanerFishDetails` quantity minus this month's inflows plus this month's outflows. Any movement after the month's end (a refresh, a late assembly, the review days before the 7th) shifts the number; `Math.max(0, …)` at `:132` hides the negative results this produces. | The fold of the ledger lines dated up to the day before the month starts gives the opening stock, per unit and batch, whatever day the report is read. |
| REP-02 | High | `rensefisk.assembler.ts:213-225` ✔ | **A cage whose cleaner fish are gone is left out**: the units come only from the current composition, so a cage whose cleaner fish all died, were removed or moved during the month (or since) is not reported, with its mortality. | The units are every unit with a live line of a cleaner-fish batch in the month or stock at its start. |
| REP-03 | High | `rensefisk.assembler.ts:60-70` ✔, `:115-119` ✔, `:149` ✔, `:162-169` ✔ | **The six "avlivet" causes and "kan ikke gjøres rede for" are always 0, stamped RECORDS** (the unit's provenance is `fromRecords('/produksjonsenheter')`); `cleaner_removal` enters the opening-stock arithmetic but no uttak bucket, so a unit does not balance (opening + utsett − uttak ≠ closing). Only a non-blocking note says so. | The cause of a cleaner-fish cull is recorded on the cull (the official list); a unit's figures are checked to balance before the report can be marked ready. |
| REP-04 | Medium | `rensefisk.assembler.ts:121` ✔, `:156` ✔, `:165` ✔, `:171` ✔ vs `:174-177` ✔; `services/regulatory-report-draft.service.ts:195-212` ✔ | **The JSON pointers address the wrong cage**: `unitIndex` counts composition rows (one per batch), but `produksjonsenheter` is grouped per tank; with two batches or species in a cage, `/produksjonsenheter/{i}` points at another cage, and an operator override saved against it lands there. | No pointer overrides; a person's input is a typed row keyed by unit and species. |
| REP-05 | Medium | `rensefisk.assembler.ts:139-150` ✔ | One `arter` entry per batch: two batches of a species in one cage give two entries with the same `artskode`; `VILLFANGET_OG_OPPDRETTET` is never produced, though two such batches are exactly that case. | One row per unit and species; the origin is folded over its batches. |
| REP-06 | Medium | `rensefisk.assembler.ts:189-195` ✔ | `tørrforKg`/`våtforKg` are never filled; the note offers the whole site's feed (the salmon's included) as context. | Feed of cleaner-fish feeds, from the feeding records of their units (see section 3). |
| REP-07 | High | `assembly/assemblers/settefisk.assembler.ts:151-169` ✔ | **The smolt report's month-end stock is today's**: `beholdningVedMånedsslutt` and `snittvektGram` come from the live `tank_batches`; and `WHERE tb."totalQuantity" > 0` (`:168`) drops every tank emptied since, with its month's deaths, culls and moves (`:165-167`). | The fold at the month's last day; every unit with lines in the month is listed. |
| REP-08 | Medium | `settefisk.assembler.ts:64` ✔, `:71-73` ✔ | A unit with no weight is reported as 0 g, stamped RECORDS (the biomass assembler fixed the same thing, `biomass.assembler.ts:143-164`; this one not). | No weight, no number: the field is missing and the report cannot be marked ready. |
| REP-09 | Medium | `settefisk.assembler.ts:162-164` ✔ | The species is the tank's primary batch's: a tank with two batches of different species is reported as one species (the source's audit lists it as FARM-MEDIUM-010, open). | One species per unit is a database-checked rule of the stock here (cleaner fish aside, section 3). |
| REP-10 | High | `assembly/assemblers/lakselus.assembler.ts:196-212` ✔, `:330-337` ✔ | **The site's lice average is a pooled mean weighted by fish examined**, and every count of the week enters (a cage counted twice counts twice). Lakselusforskriften Vedlegg 1 point 6: the site's average is the mean of the cages' averages. = HLT-22 (Health, wip/health). | The health records' `lice_weeks` (the latest count of each unit in the week, the mean of the units' averages); the report reads it, never recomputes it. |
| REP-11 | Medium | `lakselus.assembler.ts:241-242` ✔ | `gjennomførtFørTelling` is "applied on or before the latest count of the whole site", by the UTC date of `appliedAt`: a treatment of cage A after A's count but before B's later count is "before counting"; a same-day treatment is always "before". | Shown as derived from the dates, with both dates, for the person to confirm; stored as the person's answer. |
| REP-12 | High | `assembly/assemblers/slakt.assembler.ts:287-310` ✔ | Executed slaughter counts cancelled harvests (no status filter; the biomass section has one, `biomass.assembler.ts:326`). = HRV-02; with HRV-03 (fabricated quality class), HRV-04 (round weight as gutted), HRV-08 (one default facility), HRV-13 (plan site through the current tank), HRV-14 (planned kilos typed, default 0). | Harvest is the voidable stock operation; every read joins the live operation (Harvest section). |
| REP-13 | Medium | `slakt.assembler.ts:50-70` ✔, `:186-192` ✔ | A harvest whose quality class is none of the four adds nothing to `arter` (the `switch` has no default) but counts in `totalKgPerArt`: kilos vanish from the filed figures silently. | A unit or species that does not balance blocks "ready". |
| REP-14 | High | `services/report-scheduler.service.ts:191-209` ✔ | **Every report type is assembled for every site with a lokalitetsnummer**: weekly lice for land-based smolt sites, monthly smolt for sea sites, cleaner fish where there are none, slaughter per site instead of per slaughterhouse; each such draft stays blocking and raises deadline reminders (`:279-324`) until someone dismisses it. | Which reports a site owes is decided per period from the site's type and its fish in that period (section 5). |
| REP-15 | Medium | `report-scheduler.service.ts:104-126` ✔, `:216-269` ✔ | Drafts exist only if the cron ran at the rollover; a missed run (downtime, a failed tenant) leaves a period with no draft, so nothing is due and no reminder fires. | The due list is computed on read from the periods themselves; nothing has to have run. |
| REP-16 | High | `services/regulatory-report-draft.service.ts:158-179` ✔, `:186-222` ✔ | **Operator overrides survive a re-assembly by JSON pointer**: after a refresh that adds or removes a unit, a stored override for `/produksjonsenheter/2/...` applies to whatever unit is now third. | As REP-04. |
| REP-17 | Low | `regulatory-report-draft.service.ts:283-287` ✔ | An APPROVED draft stays APPROVED after a refresh that makes it invalid (`schemaValid` false). | No approval state; "ready" is computed. |
| REP-18 | High | `assembly/biomass.assembler.ts:88-89` ✔, `:119-141` ✔; `assembly/period.util.ts:62-66` ✔ | **For the month just closed, today's live stock is stamped as the month-end stock (RECORDS)**: "fresh" means the period ended in the current or previous calendar month, so on 31 October the 30 September figure is the stock of 31 October. The point-in-time replay exists but is only used for older months. | One rule: the fold at the period's last day, for every period. |
| REP-19 | Medium | `biomass.assembler.ts:284-298` ✔ | A stocking is a batch whose batch-level `stockedAt` is in the month and that touched the site, reported with the batch's `initialQuantity`: a batch split between two sites is reported whole at both; a batch moved in from another site is not a stocking (and its original stocking date may fall in the month at the wrong site). | Stockings and moves in are the input and transfer-in lines into the site's units in the month, with their own counts. |
| REP-20 | Medium | `services/biomass-report.service.ts:54-128` ✔; `entities/biomass-report.entity.ts:156-161` ✔ | The biomass report stores the payload the client sends (`buildPayload(input)`); nothing re-reads the records, so a hand-typed number is filed as the farm's. The refusal message offers "a correction flow" (`:76-80`) that does not exist, and the unique `(tenant, site, month, year)` forbids a second row: a submitted month cannot be corrected in the system. `submittedAt` is the moment of confirmation, not of filing (`:191`). | The content is computed from the records; a correction is a new report linked to the one it corrects; the person states when it was filed. |
| REP-21 | Medium | `services/biomass-altinn-export.service.ts:294` ✔, `:318` ✔, `:397` ✔ | The export names the site by its internal UUID (file name and rows), not the lokalitetsnummer and organisation number the authority knows it by; it is per species for the whole site only. | The export carries the official identity and the authority's granularity (section 1). |
| REP-22 | Medium | `assembly/assemblers/escape.assembler.ts:166-190` ✔, `:180` ✔, `:108` ✔ | Only the latest open, unreported incident can be assembled (earlier ones cannot), and the species is `COALESCE(officialCode, code)` checked against `^[A-Z]{3}$`: a three-letter internal code is filed as the official artskode (the source's own FARM-MEDIUM-213, open). | The person starts the report from the escape; the official code only (`Species.official_code`, never `code`). |
| REP-23 | Medium | `assembly/assemblers/welfare.assembler.ts:247-249` ✔, `:309-321` ✔, `:375-398` ✔; `assembly/assemblers/disease.assembler.ts:177-216` ✔ | The welfare notice takes the site's latest routine welfare assessment, whatever its date, and derives the notice's severity from its worst score; the disease notice takes the latest open outbreak. The event being notified is never chosen by a person. | An event report is started by a person from the event it is about. |
| REP-24 | Medium | `services/regulatory-varsling.service.ts:1-23` ✔; `apps/notification-service/src/notification/services/email.service.ts:110-120` ✔ | The three event notices are e-mailed by the system (to `varsling.akva@mattilsynet.no`, escape also to `postmottak@fiskeridir.no`) and the row is QUEUED, shown as submitted with the outbox event id as "receipt" (the source's COMPLIANCE-MEDIUM-004, open). | Nothing is sent by the system; the person notifies and records how, when and the reference. |
| REP-25 | Medium | `schemas/official/*.schema.json` line 6 (`"x-verified": false`) ✔; `docs/integrations/mattilsynet-reporting-api.md:184-195` ✔ | The five wire schemas are transcribed from the source's own notes and never compared with Mattilsynet's swagger. | Field lists here cite the official pages (section 1); where only the source's transcription exists it says so. |
| REP-50 | High | `schemas/official/rensefisk-v1.schema.json:25-31` ✔, `:70` ✔ vs the API's `RensefiskrapporteringDto`, `RensefiskOpprinnelse` ✔ | **The cleaner-fish wire shape is not Mattilsynet's**: it sends `samdriftOrganisasjonsnumre` and `produksjonssyklusStart`, which the API does not have; accepts origin `UKJENT`, which the API does not (and the UI always sends it, REP-29); makes the feed optional where the API requires `tørrforKg` and `våtforKg`; and types kilos as decimals where the API has integers (also the slaughter kilos, `slakt-utfort-v1.schema.json:64-67` ✔). | The fields and types of the official OpenAPI (section 1). |
| REP-51 | High | `species/data/official-species-codes.ts:35-38` ✔; `schemas/official/rensefisk-v1.schema.json:67` ✔ | **Every cleaner-fish species code is wrong**: lumpfish is sent as USB (ASFIS: ballan wrasse), ballan wrasse as BER, corkwing as GRO, goldsinny as BNB (none of them cleaner fish in ASFIS). | ASFIS codes LUM, USB, YFM, TBR (3.4). |
| REP-52 | High | `schemas/official/lakselus-v1.schema.json:17` ✔; `assembly/assemblers/lakselus.assembler.ts:150-160` ✔ | **A week without a lice count cannot be filed**: the source requires `lusetelling` and blocks the draft when there is no count, while the API leaves it out (nullable, not required) and § 6 asks for a count only every 14 days below 4 °C. | A week is filed with the temperature and no counts when there were none; the page says why (below 4 °C, no fish, slaughter within 14 days). |
| REP-53 | Low | `services/report-deadlines.ts:74-78` ✔ | Executed slaughter is dated by the month of the week's Thursday; the rule is "slakteuker som avsluttes i en kalendermåned" (the week's Sunday): a week ending on 1 November is due 7 December, not 7 November. | Not ported (the slaughterhouse's report, D-3). |
| REP-54 | Medium | `apps/notification-service/src/notification/services/email.service.ts:110-120` ✔ | The welfare and disease notices go to `varsling.akva@mattilsynet.no`, an address no current Mattilsynet page gives; notices from a site go through the Altinn form, e-mail only for transport and slaughterhouse events, to `varsling.akvakultur@mattilsynet.no` (E1). With REP-24. | People file; the page names the right channel per kind. |

### 4.2 Source UI (`pages/reports/`, E2; ✔ where the lead re-read)

| ID | Sev. | Where | What is wrong |
|---|---|---|---|
| REP-26 | Critical | `ReportsPage.tsx:441-448` ✔; `tabs/EscapeReportTab.tsx:177`, `:244` ✔; `WelfareEventTab.tsx:348`; `DiseaseOutbreakTab.tsx:272`; `utils/regulatoryIdentity.ts:72` | **None of the three event notices can be filed from the Reports page**: the tabs are mounted without a site, fall back to `'site-001'`, and the identity lookup then fails "missing a locality number"; the tests mount the tabs with that id and hide it (`tabs/__tests__/immediateReportSubmit.spec.tsx:38`, `:179-193`). |
| REP-27 | High | `tabs/CleanerFishReportTab.tsx:1380-1402` ✔ | **Each species' losses are copied into every cage holding it**: N cages report N times the losses. |
| REP-28 | High | `CleanerFishReportTab.tsx:1296`; `SeaLiceReportTab.tsx:1416`; `SlaughterReportTab.tsx:1538`; `SmoltReportTab.tsx:1000` | No tab filters the tanks by site (the hook can, `hooks/useTanks.ts:133`): the stock of every site is filed under one lokalitetsnummer. |
| REP-29 | Medium | `CleanerFishReportTab.tsx:324`, `:326`, `:1382-1399` ✔ | Origin always `UKJENT`, moved-in always 0, "skal ikke brukes" has no input, the opening stock defaults to 0 and the closing stock is today's; the mortality loaded from the tanks is never sent; deployments, origin and capture place are dropped. |
| REP-30 | High | `tabs/SeaLiceReportTab.tsx:167-174` ✔ | **The week is not the ISO week** (`ceil((dayOfYear+1)/7)` with the calendar year) and cannot be changed: 2026-03-30 is filed as week 13 (ISO 14); 1 January 2027 as 2027-W1 (ISO 2026-W53) (E2 ran it in Node, Europe/Oslo). |
| REP-31 | High | `SeaLiceReportTab.tsx:108`, `:112-113`, `:1558`, `:1567`; `dto/regulatory-inputs.dto.ts:74-85`, `:400-402` | The sensitivity-test substance is sent as the UI's value (`AZAMETIFOS`, `EMAMEKTIN_BENZOAT`, `ANNET`), which the backend enum rejects: the whole report fails for 3 of 6 choices; an unanswered result is sent as "sensitive". |
| REP-32 | High | `SeaLiceReportTab.tsx:1534`, `:1540`, `:1547-1548` | Every medicinal treatment is sent as a bath (in-feed emamectin included); the amount's unit is always grams whatever was chosen; the strength is never sent; a resistance suspicion is always "other substance / reduced effect". (= HLT-09 in part.) |
| REP-33 | Medium | `SeaLiceReportTab.tsx:134-165`, `:666-681`; `utils/thresholds.ts:26-48` | The lice "alert / treatment / critical" levels 0.5 / 1.0 / 2.0 have no legal basis and no spring limit; § 8 says fewer than 0.2 in weeks 16–21 (south) / 21–26 (north), 0.5 otherwise ✔. |
| REP-34 | High | `tabs/SlaughterReportTab.tsx:1562-1581` | The slaughter tab resolves no identity (no `buildRegulatoryIdentity`): `lokalitetsnummer` is 0 unless typed (the source's FARM-HIGH-128, fixed elsewhere, not here). |
| REP-35 | Medium | `SlaughterReportTab.tsx:303-306`, `:222-223`, `:1591-1597` | The week is clamped to 1–52 (2026 has a week 53), the ISO week is paired with the calendar year, and only the first plan entry per day and species is sent. |
| REP-36 | High | `tabs/SmoltReportTab.tsx:39-44` vs `species/data/official-species-codes.ts:26-28` | Trout and char codes ORR / ORB / ROY in the smolt tab, TRR / TRS / ACH in the backend; both pass the form's `^[A-Z]{2,5}$`. |
| REP-37 | High | `SmoltReportTab.tsx:66-73`, `:294-308`, `:587-595`, `:634-638`, `:711` | "Load from system" throws away the server's culled, died and moved-out numbers; mortality rows are matched by unit id but shown by position, so a changed or added unit is filed with 0 losses. |
| REP-38 | Medium | `tabs/BiomassReportTab.tsx:182-187`, `:1840`, `:1404-1410` | Typed species *names* are sent as species codes; cause codes are rewritten to display labels and sent back; "estimated FCR" is feed / standing biomass. |
| REP-39 | Medium | `components/modals/EscapeReportModal.tsx:307-309`, `:321`, `:338`; `WelfareEventModal.tsx:244-246`, `:281`; `DiseaseOutbreakModal.tsx:289-291`, `:309`; `tabs/WelfareEventTab.tsx:274-294`; `DiseaseOutbreakTab.tsx:196-216` | The event forms require fields they never send (preventive measures, mortality count, immediate actions, lab results, recapture) and stamp the detection time as "now" with no input. |
| REP-40 | Medium | `EscapeReportModal.tsx:467-470`, `:409`; `utils/thresholds.ts:19` | The escape notice addresses Mattilsynet and says Fiskeridirektoratet must be told only above 1,000 fish; § 38 ✔: every escape and every suspicion, to Fiskeridirektoratet, at once. |
| REP-41 | Medium | `utils/thresholds.ts:141-202` | The disease lists are wrong: ILA "not present in Norway" (it is endemic and listed), carp diseases SVC and KHV, and CMS, HSMI, AGD as notifiable (= HLT-11; the health catalogue has the lists from dyrehelseforskriften §§ 5–6). |
| REP-42 | Medium | `utils/thresholds.ts:374-389`; `ReportsPage.tsx:260-279` | The next deadline adds 7 days on the due day itself (the "due soon" banner never shows on the day) and is computed in the browser's time zone. |
| REP-43 | High | `components/wizard/ReportWizard.tsx:129`, `:146-147` | After submit the wizard always resets and clears the error: a refused or failed report shows nothing and jumps to step 1 (all five wizard tabs). |
| REP-44 | Medium | `components/ReportSettingsModal.tsx:27-50`, `:232`; `hooks/useRegulatory.ts:397`, `:514` | The settings hold no organisation number (it is on the company page) while the error points to them; a save invalidates a cache key the tabs do not read. |
| REP-45 | Medium | `components/ReportsDueSection.tsx:136`, `:166-171`, `:190` | The due list does not show the site: with several sites a person can approve the wrong one; dismiss has no confirmation. |

### 4.3 Source cleaner-fish stock (`batch/`, E2)

| ID | Sev. | Where | What is wrong |
|---|---|---|---|
| REP-46 | High | `batch/handlers/deploy-cleaner-fish.handler.ts:194` ✔; `record-cleaner-mortality.handler.ts:84-90` ✔, `:193`; `remove-cleaner-fish.handler.ts:141-143` | **Cleaner-fish mortality is checked against the batch's undeployed pool**: deploying takes the fish out of `currentQuantity`, and a death is then refused once the batch is fully deployed ("cannot exceed the current count (0)"), or, while some fish are undeployed, subtracted from fish that were never in the cage. The spec's fixture never deploys. |
| REP-47 | Low | `record-cleaner-mortality.handler.ts:204-213`, `:221`, `:242` | Predation and cannibalism become UNKNOWN on the mortality record while the operation keeps them. |
| REP-48 | Medium | `transfer-cleaner-fish.handler.ts:162-177` | A cleaner-fish transfer checks no capacity (`isOverCapacity: false` hard-coded); deploy does. |
| REP-49 | High | `remove-cleaner-fish.handler.ts:147-149`, `:172`; `resolvers/cleaner-fish.resolver.ts:245-248`, `:610` | A removal's reason is any string, kept only inside `notes`; nothing says culled or died, nor which of the regulator's causes: the rensefisk losses cannot come from the records. |

### 4.4 Our side

| ID | Sev. | Where | What is wrong | Fix (Phase 2 unless said) |
|---|---|---|---|---|
| OUR-01 | High | `farm/stock/services.py:13-14`, `:283-286` ✔ | One species per unit: cleaner fish cannot be in the salmon's cage, so the cleaner-fish report cannot say which cage they are in. | Production species only (D-1). |
| OUR-02 | High (once OUR-01 is lifted) | `farm/feeding/fold.py:184-191` ✔ | A feeding is split among every batch in the unit by biomass. | Split among the batches of the species the feed suits (3.2). |
| OUR-03 | High | `farm/stock/services.py:41` ✔; `farm/models/stock.py:46-48` ✔ | Count adjustments, escape among them, have no dialog: an escape cannot be booked, a recount cannot correct the stock (E3). | An escape record with its adjustment (5.3); the adjustment dialog. |
| OUR-04 | High | `farm/models/stock.py:46-56` ✔; `farm/models/harvest.py:154-155` ✔ | No operation delivers live fish out of the company (smolt sold or delivered to a customer's site): a hatchery cannot book its deliveries (E3). | A delivery operation (removal with a destination: customer, its site's lokalitetsnummer). Decision D-10. |
| OUR-05 | High | `farm/stock/services.py:450-458` ✔; `farm/stock/dates.py:66-73` ✔; `config/settings.py:202` ✔ | Records may be dated or voided up to 31 days back, so a filed month changes silently when recomputed (E3 ran it: voiding a 20 Oct weighing moved a 31 Oct biomass from 97 to 48.5 kg). Nothing records a filed report. | The reports' frozen content and "no longer matches" (5.4). |
| OUR-06 | Medium-High | `farm/models/tank.py:535-546` ✔ | A unit holding fish may be moved to a production department on another site (only its size is protected): past figures per locality move with it (E3). Same class as HRV-13. | A unit with stock lines keeps its site (the check beside the size check). |
| OUR-07 | Medium | `farm/models/tank.py:400-404` ✔ | `regulatory_unit_id` is unique across the company, but unit numbers are per locality ("merd 1" on two sites) (E3). | Unique per site (the department's site), a migration. |
| OUR-08 | Medium | `farm/models/stock.py:87-94`, `:109-113`, `:249` ✔ | The cull reasons cannot fill the rensefisk causes; an "escape" adjustment may be positive (E3). | 3.2 point 4; an escape is negative. |
| OUR-09 | Medium | `farm/models/harvest.py:267-270` ✔ | A planned harvest may have neither fish nor kilos (E3). | Kilos required for a planned harvest (the planned-slaughter report needs them). |
| OUR-10 | Medium | `farm/health/services.py:96-116` (health) | A lice treatment may use a medicine with no lice substance code, and its amount is optional (E3). | Reported to the health work; the report blocks "ready" and names the treatment meanwhile. |
| OUR-11 | Medium | `farm/models/stock.py:184-190` ✔ | Wild-caught fish bought from a fisherman cannot name the supplier (E3). | 3.2 point 5. |
| OUR-12 | Medium | `farm/models/site.py:48` ✔; `farm/forms/site.py:42-43` ✔ | "Organisation number override" of a company number that exists nowhere; 20 free characters though the placeholder says 9 digits. | `Site.organisation_number`: the permit holder's, 9 digits with the mod-11 check (E3 proposes; the check rule unverified), required to file. |
| OUR-13 | Medium | `farm/models/water.py:77-119` ✔ | Water samples have no depth; the lice report's temperature is at 3 m (§ 6 ✔). | `depth_m` on the sample. |
| OUR-14 | Low | `farm/health/read.py:65` (health) | The lice week's "N of M units counted" uses the units holding fish now, not that week (E3). | Reported to the health work; the report uses `stock_on`. |
| OUR-15 | Low | `config/settings.py:145` ✔; `farm/models/site.py:69-70`, `:138-141` ✔ | A site without a time zone runs on UTC (company default `TIME_ZONE='UTC'`), so its day and ISO week edges are UTC's. | A company time zone setting; out of the reports' scope, noted. |
| OUR-16 | Medium | `farm/models/stock.py:134-171` ✔ | No year class (årsklasse) on a batch; § 44 b, c and § 42 ask for it. | `Batch.year_class`. |
| OUR-17 | Low | `farm/models/feed.py:47-56` ✔ | No dry/wet form on a feed (rensefisk). | `Feed.form`. |
| OUR-18 | Gap | `farm/models/harvest.py:148-149` ✔ | No slaughter result (gutted kg per quality class, slaughter condition): § 44 e and the executed-slaughter report. | `SlaughterResult` 1:1 with the harvest record (Harvest's plan). |
| OUR-19 | Low | `farm/species_catalog.py:49-57` ✔ | The catalogue's cleaner-fish codes are the source's wrong ones (USB for lumpfish, BER, GRO, BNB); they are marked unverified and never filled in, so nothing filed carries them yet. | LUM, USB, YFM, TBR, verified against ASFIS 2026.1 (3.4). |
| OUR-20 | Medium | `core/crud.py:330-333` ✔; `templates/crud/form.html:8`, `detail.html:7`, `confirm_delete.html:6`, `list.html:8` ✔ | The heading above a tab's title is the menu group's label; a tab in a group without a label (the Reports heading will have one) shows " · Title" and an empty heading (E4; latent today). | One helper on `navigation.Place` that every page uses. |
| OUR-21 | Medium | `core/audit.py:91` ✔ | The activity log stores a record's name as `str(instance)` in the language of the person's request, though the log is English at rest (`core/audit.py:1-7`); E4 printed a water limit's name in nb and tr. | Build the default name inside `source_language()`. |
| OUR-22 | Medium | `core/crud.py:278-292`, `:630-642` | A row-list save locks nothing and checks no version, unlike the edit view (`:554-562`): a row-list save racing another save (for a report: its submission) keeps rows the frozen content does not have (E4). | Lock the parent and check its version. |
| OUR-23 | Low | `core/crud.py:525-533` | Two requests creating the same record past a conditional unique constraint end in a 500 (IntegrityError not caught) (E4). | Catch it and show the constraint's message. |
| OUR-24 | Low | `farm/models/harvest.py:1` ✔; `README.md:1248` ✔ | Both still place slaughter facilities in "Setup › Reference data"; the menu has them in "Setup › Harvest and logistics" (`config/navigation.py:62-65` ✔). | Text fix. |
| OUR-25 | Low | `core/test_database.py:117`; `config/database.py:8-15` ✔; `farm/tests/test_restore.py:63-67` | A new app can be left out of the database viewer and the admin restore with no test failing (E4). | A test that every app with audited models is in both. |

## 5. Design

### 5.1 Principles

1. **A report is a read of the records, not a copy.** Every figure is computed by one function per kind from
   the ledger, the feeding walk, the health records and the harvest records, with the reads of 2.1; the page,
   the export, the frozen content and the "still matches?" check all call the same function. Nothing in the
   reports code recomputes a stock figure its own way (the source's assemblers each had their own SQL and got
   the period end wrong in four of them, REP-01, REP-07, REP-18, REP-19).
2. **A figure is computed or entered, never both.** There are no overrides of a computed number (the source's
   JSON-pointer overrides, REP-04, REP-16). A wrong number is corrected at its record (a void and a new entry,
   as everywhere here), and the report shows the corrected figure. What no record can hold (the contact person,
   which treatments were combined, a resistance suspicion, a sensitivity test, an event's narrative) is typed on
   the report, in typed columns or rows, never JSON (README "One format for every tab"; E4).
3. **A missing fact is recorded where it belongs.** A temperature at 3 m is a water sample with its depth, a
   cleaner fish's cull cause is the cull's reason, a year class is the batch's: the report links to the place to
   record it and names what is missing; it does not take the value itself.
4. **Nothing is sent.** No Altinn, Maskinporten or Mattilsynet API calls, no e-mails to authorities, no
   scheduler, retries or outbox (the source's whole submission pipeline is not ported). A person files and records
   that they did.
5. **What was filed is frozen and checked.** Recording a submission stores the content as filed; the page
   recomputes and says when the records no longer give the same content (OUR-05: records may change up to 31 days
   back).
6. **Due reports are computed on read**, from the sites, their fish and the calendar, never created by a job
   (REP-14, REP-15).

### 5.2 What is due

`reports/due.py` lists, per kind, the (site or facility, period) pairs owed, between a site's **reports-from
date** (a new `Site` column, empty = this site's reports are not listed; decision D-6) and the last closed period,
minus the reports already started:

| Kind | Owed for | Applies when | Deadline (Europe/Oslo calendar) |
|---|---|---|---|
| Sea lice | site, ISO week | a sea site (`Site.type = sea_cage`) held fish of a salmonid species at any time in the week | Tuesday of the next week |
| Smolt | site, month | a site that is not a sea site held fish of start-feeding stage or older at any time in the month (D-8) | the 7th of the next month |
| Cleaner fish | site, month | a sea site held cleaner fish (a species with `cleaner_fish_type`) at any time in the month | the 7th of the next month |
| Monthly biomass | site, month | a sea site held fish at any time in the month | the 7th of the next month |
| Planned slaughter | slaughter facility, ISO week | live planned harvests (`HandlingPlanItem` kind harvest, not cancelled) to the facility in the week (D-3) | Thursday of the week before |
| Escape, disease, welfare | an event | started by a person; the page lists events with no notice yet: escapes, and health events whose diagnosis is notifiable (`needs_notification`, health) | at once ("straks", "umiddelbart") |

"Held fish in the period" is the fish at the period's start plus any arrival line in it, from summed live
`count_delta` (2–3 queries per kind, E4; no fold needed); "salmonid" needs a typed rule (the species' family is
free text, `farm/models/species.py:101` ✔, E4): the catalogue's family Salmonidae, checked on the species form
(D-11). Deadlines are dates in Europe/Oslo, whatever the site's clock (the company default is UTC, OUR-15);
overdue is "today in Oslo is after the deadline".

### 5.3 Models (a new app `reports`, like `inventory`; it reads `farm`, `farm` never imports it)

**`Report(AuditedModel)`**, table `regulatory_reports`:
- `kind`: sea_lice, smolt, cleaner_fish, biomass, slaughter_planned, escape, disease, welfare (and, only if
  D-3 says so, slaughter_executed);
- `site` (PROTECT; empty only for slaughter) or `facility` (`SlaughterFacility`, PROTECT; slaughter only) — a
  check: exactly the one the kind needs (precedent `farm/models/harvest.py:297-301` ✔);
- `period_start` (Monday of the ISO week, or the 1st of the month; the end is derived, never stored), empty for
  events; checks that it is a Monday / the 1st;
- for events: `health_event` (PROTECT, disease and welfare), `escape` (PROTECT, see below);
- `contact_name`, `contact_email`, `contact_phone` (required to submit; prefilled from the person);
- `corrects` (self, PROTECT, related name `corrections`): a correction is a new report of the same key that
  replaces a submitted one;
- `submitted_at` (when the person says they filed), `submitted_by` (who recorded it, PROTECT),
  `channel` (Altinn form, Mattilsynet API from another system, e-mail, telephone, other), `reference` (the
  receipt or case number): all set or all empty (precedent `knowledge/models/entry.py:122-127`, E4);
- the status is derived, never stored: **draft** (no submission), **submitted**, **superseded** (a submitted
  correction replaces it), and, read on demand, **needs correction** (the records no longer give its content).

Constraints: one live original per (kind, site, facility, period) and per (kind, event)
(`nulls_distinct=False`, E4); one live correction per report; a submitted report is never deleted (a check on
`is_deleted` with `submitted_at`, plus `delete_blockers()`); changes to a submitted row are refused by a trigger
(the audit log's append-only trigger, `core/migrations/0003_audit_log_append_only.py`, is the precedent; E4's
generic `to_jsonb(NEW) - …` comparison) and by `clean()` with a readable message, because the edit view saves
unconditionally (`core/crud.py:563-569`, E4).

**`ReportSnapshot`** (one-to-one with the report, PROTECT, append-only by trigger): `format_version`, `content`
(JSON), `content_sha256`. The content is what was told to the authority: the figures as filed (codes, not
translated labels; decimals as strings), the person's fields, the identity (organisation number, lokalitetsnummer,
unit numbers, species codes) as they were, and per figure its provenance (the function, its arguments and the ids
of the records it read). JSON here is a frozen document read only to compare and to re-export, never as an input
(the audit log's `changes` is the precedent, `core/models.py:172-175`; E4). The hash also goes into the
submission's activity-log entry, which is append-only, so the frozen content cannot be swapped unseen.

**Person-entered rows** (RowLists, refused once the report is submitted through `applies_to()`; E4):
- sea lice: `TreatmentAnswer` (report, treatment, `before_count`, `combination` group number) for the week's
  treatments; `ResistanceSuspicion` (substance, cause, other text); `SensitivityTest` (date, laboratory,
  substance, result);
- biomass: `UnitAnswer` (report, unit, reduced-capacity production) — the one § 44 item no record holds;
- events: the narrative fields on an `EventNotice` (one-to-one): what happened, when it was found, cause, fish
  dead / injured / involved, the situation now, measures taken; prefilled from the event.

**Outside the app** (each its own step, with the owner's decision where marked): `Site.organisation_number`
(OUR-12), `Site.reports_from` (D-6), `Tank.regulatory_unit_id` unique per site (OUR-07), a unit with stock keeps
its site (OUR-06), `WaterMeasurement.depth_m` (OUR-13), `Batch.year_class` (OUR-16), `Feed.form` dry / wet
(OUR-17), the cleaner-fish track (section 3, D-1, D-2), an **escape record** in the stock (`farm`): the escape
with its time found, cause, suspected or confirmed, health status, recapture, and the count-adjustment
lines that take the fish out of the units (OUR-03; the stock stays the only writer of fish), a delivery
operation (OUR-04, D-10), the slaughter result (OUR-18, D-3).

### 5.4 Submitting, freezing, "no longer matches", corrections

- **Ready** is computed: every required field has a value, every unit balances, the identity is complete
  (organisation number, lokalitetsnummer, unit numbers, species codes); the page lists what is missing and links
  to where it is recorded.
- **Record as submitted** (Edit permission): the person gives when, how and the reference; in one transaction
  `reports/services.py` locks the report, checks its version, computes the content, stores the snapshot and the
  submission fields, and logs it.
- **No longer matches**: the report's page recomputes and compares with the snapshot by codes and ids, field by
  field, and shows the differences ("unit M3: died 140 → 152, the mortality of 28 Oct was voided on 2 Nov"). A
  difference of the format (a newer `format_version`) is told apart from a change of records. Lists show a mark
  for reports whose period is still inside the backdating window or whose sources have no window (health events,
  harvest plans), with a fingerprint of the source rows (ids, versions, deleted flags) stored with the snapshot so
  the list does not refold everything (E4).
- **Correction**: "Start a correction" creates a report with `corrects` set; it is filled and submitted like any
  other; the original shows "superseded by". Mattilsynet's guidance for lice is to send the whole week again (E1),
  which is exactly a correction's content.

### 5.5 Exports (per kind, from the snapshot once submitted, else live and marked "not submitted")

- **Print**: a page in the order of the authority's form, the official Norwegian field names beside the
  person's language, the identity on top; print CSS, the print button in TypeScript (`frontend/`).
- **CSV**: section, official field, value; through the database viewer's formula guard (`FORMULA_STARTS`,
  `core/dbgrid.py:32`, E4), not a copy of it.
- **JSON in the shape of Mattilsynet's API** for the lice, smolt, cleaner-fish and planned-slaughter reports,
  for a person or another system that files through the API. Its fields follow the OpenAPI read 2026-11-03; a
  copy of the relevant schemas (NLOD licence, E1) is kept with the tests, and every export is validated against it
  in the tests, so a change of ours that breaks the shape fails a test.
- The biomass report: print and CSV only (Fiskeridirektoratet's current form is unverified, 1.5).

### 5.6 Menu

A fourth heading in Production: **Reports**, after Operations and before Communication, with one entry
**Regulatory reports** (`/reports/`, icon `file-text`). Not under Operations: Operations holds the daily
records (`config/navigation.py:71-74` ✔), and a report is neither a daily record nor structure, which is why
Communication got a heading of its own (`config/navigation.py:95-97` ✔); the source also keeps Reports apart
(E4). The page: what is due and overdue first (per site, kind and period, with the deadline), then the notices to
file, then the filed reports, filters by site, kind and status (draft, submitted, needs correction).

### 5.7 Roles

One area **Regulatory reports** (`reports.Report`) with the four actions: Read (the page, a report, its
exports), Create (start a due report, a notice, a correction), Edit (fill in a draft and **record it as
submitted**: a state change under Edit, as "Edit also reviews an entry" for knowledge, `config/access.py:21-22`
✔), Delete (discard a draft). Whether submitting needs a permission of its own is D-5 (a fifth matrix column,
E4).

### 5.8 Activity log

Started (created), edited (changed), submitted (changed, built in the source language: status, submitted at, by,
channel, reference, content hash), correction started (created, "Corrects …"), draft discarded (deleted through
the delete plan). All under the report's entity type so its History tab shows them; severity normal (critical is
for going past a fish or food-safety warning, `core/models.py:133-140` ✔).

### 5.9 Delete plan

A draft is soft-deleted (the delete plan) and can be restored in the admin; a restore re-checks the constraints,
so it is refused while another live original exists. A submitted report is never deleted, not even softly
(`delete_blockers()`: "It was submitted: start a correction instead", the check, the trigger). Its site,
facility, health event and escape are PROTECT: a site with filed reports is closed, not deleted. A void of a
record a report read is not stopped by anything (voids are not deletes, `farm/stock/services.py:444-465`, E4):
it is exactly what "no longer matches" shows. Snapshots are read-only in the admin.

### 5.10 Also

- **Languages**: the page in en, tr, nb; the authority's field names in the exports stay Norwegian as the authority
  writes them (text no person reads in their language is not translated, `docs/i18n.md`, E4).
- **Database viewer**: a section for the app (`config/database.py`), the app in the viewer test's list.
- **README**: a section "Production › Reports › Regulatory reports (`/reports/`)", the area in "Roles and users",
  the app in "Database viewer", the page in "Pages". **Bug document**: a section "Regulatory reports" with REP-01
  to REP-54 and the owner decisions.
- **Not ported**: the submission pipeline (Maskinporten, the API client, retries, the outbox, the e-mails, the
  scheduler and its advisory locks, auto-submit), the source's per-tab wizards, the threshold tables
  (`utils/thresholds.ts`, REP-33, REP-41; the health records hold the lice limit and the disease lists).

### 5.11 Order of work for Phase 2

1. Shared fixes the reports stand on: OUR-12, OUR-07, OUR-06, OUR-19, OUR-20, OUR-21, OUR-22, OUR-23, OUR-24.
2. The reads of 2.1 (`stock_on`, `movements`, `fed`), with their tests against the fold.
3. The app: models, due list, the compute functions (sea lice and the notices once health is on main; smolt,
   biomass, planned slaughter), submit, freeze, compare, correct, exports, page, roles, log, delete plan, admin,
   viewer, translations, README, bug document.
4. With the owner's decisions: the cleaner-fish track and its report (D-1, D-2), the escape record (OUR-03), year
   class and depth (OUR-16, OUR-13), the delivery operation (D-10), the slaughter result (D-3).

## 6. Decisions for the owner

Each with the recommendation; nothing that depends on one is built before it is taken.

| # | Question | Recommendation and why |
|---|---|---|
| D-1 | Cleaner fish share the salmon's cage: lift "one species per unit" (owner decision Q1) for cleaner-fish species? | **Yes**: a unit holds one production species and any number of cleaner-fish batches. Without it the cleaner-fish report cannot say which cage its fish are in (the owner's own example). § 47 forbids only fish of different holders in one unit ✔. |
| D-2 | Do cleaner fish count in a unit's density, capacity, feed rate and the site's biomass? | **No** for the unit's production figures and the biomass report: cleaner fish are not counted in MTB (NFD's 2017 hearing note, adopted 2018: "Rensefisk skal ikke inngå i beregningen av pålydende maksimalt tillatt biomasse", E1) nor in the unit's fish count (Altinn, E1). They get their own line and the announced cleaner-fish tab. |
| D-3 | Slaughter reports: the farmer must notify a planned slaughter (restkontrollforskriften § 9a ✔), but the Altinn forms are filed by slaughterhouses (E1), and the executed report is the slaughterhouse's gutted kilos per quality class. Which does the farm file? | **Planned**: build it, per slaughter facility and week, from the harvest plan, for the farm to file or hand to the slaughterhouse. **Executed**: not built unless the farm runs its own slaughterhouse; then with the slaughter result (OUR-18). |
| D-4 | "Mattilsynet notified" for a disease: the health records keep `authority_notified_at` on the health event (health); a disease notice here records the same fact. Which is the one place? | **The notice** (when, how, reference, frozen content) for all three notices alike; the health event reads it through a provider, as the withdrawal registry does (`farm/handling/withdrawal.py`), and its own column goes. To be agreed with the health work once it is on main. |
| D-5 | May whoever fills in a report also record it as submitted, or is submitting a permission of its own? | **Edit covers it** for the MVP (no change to the role matrix). A separate permission adds a fifth column to every area (E4); worth it only if preparers and filers are different people. |
| D-6 | From when are a site's reports listed as due? | **A date per site** ("Reports from", empty = not listed): periods before it were filed elsewhere and must not show as overdue. |
| D-7 | Month-end biomass between weighings: the book (last measured average) or the feeding projection? | **The book**, with each unit's last weighing date as the basis § 42 b asks for; the projection is shown beside it. The projection reads today's protocols and temperatures, so a past month's figure would change with them (E3). |
| D-8 | Which units of a hatchery are in the smolt report? | Every unit holding fish of start-feeding stage or older (§ 58 ✔): batches stocked as eggs or larvae enter once they reach start-feeding, which needs a rule (a weight or an age) or a stage line in the ledger. Until then: every unit holding fish, the person removes none. |
| D-9 | Count adjustments in the cleaner-fish report: an escape and a downward recount go to "kan ikke gjøres rede for" (the API's definition includes escaped fish, E1)? | **Yes** for losses (escape, unaccounted loss, a downward correction); an upward correction has no column and blocks "ready" with an explanation. |
| D-10 | Fish delivered alive out of the company (smolt sold): a new stock operation? | **Yes**, a delivery with a destination (a customer, its site's lokalitetsnummer); it is the smolt report's "flyttet eksternt" and § 44 f. |
| D-11 | "Salmonid" for the lice report: from the species' family? | The catalogue's family **Salmonidae**, the family field checked on the species form for species the catalogue knows; the family is free text today. |
| D-12 | Fiskeridirektoratet's monthly biomass form: its current channel and fields are unverified (the old Altinn page answers 404; an API from Q2 2026 is reported only by the trade press). | Build the report as § 44 reads (print and CSV) and confirm the form with Fiskeridirektoratet before relying on it. |
