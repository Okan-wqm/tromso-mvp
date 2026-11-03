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
- The regulations, read on lovdata.no on 2026-11-03 (section 1 lists them), and Mattilsynet's public reporting
  API, Altinn's form pages and the authorities' guidance, where cited.

**How reliable each statement is.** ✔ = re-read by the lead at the cited lines (or, for an official source, read
by the lead). **E1** to **E4** = found by one of the four checking experts at the cited place: E1 Norwegian
regulatory reporting (official pages), E2 the source's report code, E3 production data against our ledger, E4 our
architecture; the lead re-read those also marked ✔.
**Unverified** = not confirmed from an official page or a test. The source's own field lists for the
Mattilsynet API are a transcription it never compared with Mattilsynet's API (`"x-verified": false` on line 6 of
each of `schemas/official/*.schema.json` ✔); this document takes the fields from Mattilsynet's published OpenAPI
instead (section 1).

## Contents

1. [The reports](#1-the-reports)
2. [Where each field comes from here](#2-where-each-field-comes-from-here)
3. [Cleaner fish](#3-cleaner-fish)
4. [Bugs found](#4-bugs-found)
5. [Design](#5-design)
6. [Decisions](#6-decisions)

## 1. The reports

The official sources, read 2026-11-03:
- **Mattilsynet's reporting API**, whose OpenAPI is public: `https://innrapportering-api.fisk.mattilsynet.io/q/openapi?format=json`
  (production, version `de3580a`; dev identical) (E1; the lead read the saved copy ✔). The source's notes say every
  API mirrors its Altinn form (`docs/integrations/mattilsynet-reporting-api.md:18` ✔); Mattilsynet's API page: "Dersom det ikke er mulig ...
  kan dere rapportere manuelt via Altinn for alle skjemaene"
  (`mattilsynet.no/om-mattilsynet/api/maskinell-innrapportering-via-api-innen-akvakultur-omradet`, E1). So the
  API's field list **is** the Altinn form's content, and this document takes field names, types and
  definitions from it, never from the source's transcription.
- The regulations on lovdata.no: lakselusforskriften (FOR-2012-12-05-1140, last amended FOR-2023-12-14-2087),
  akvakulturdriftsforskriften (FOR-2008-06-17-822, last amended FOR-2026-01-25-85; § 44 last by
  FOR-2025-10-10-2019), restkontrollforskriften (FOR-2000-01-27-65), dyrehelseforskriften (FOR-2022-04-06-631) ✔.
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
| Escape | Fiskeridirektoratet | akvakulturdriftsforskriften § 38 ✔ | the permit holder, and suppliers under the Aquaculture Act (who must also tell the permit holder, § 38 second paragraph ✔), on knowledge **or suspicion** of an escape from own or others' units, installations or transport units (Altinn: "Innehavere, leverandører som omfattes av akvakulturloven", E1) | event | "straks" (§ 38 ✔) | Altinn "Rømt oppdrettsfisk eller avvik" (links to the form on fiskeridir.no), "skal meldes med én gang" (E1) |
| Disease | Mattilsynet | dyrehelseforskriften § 7 (E1; quoted in `farm/health/diseases.py:21-23`, health) | on reason to suspect, or a finding of, a listed disease (except sea lice); raised mortality still unexplained after the vet's reassessment within 14 days | event | "umiddelbart" (listed disease); "så snart som praktisk mulig" (unexplained mortality after the reassessment) | Altinn "Varsel om velferdshendelse og listeført sykdom på oppdrettsfisk" (E1) |
| Welfare | Mattilsynet | akvakulturdriftsforskriften § 14 ✔ | "forhold som har medført alvorlige velferdsmessige konsekvenser for fisken, herunder om sykdom, skade eller svikt" | event | "umiddelbart" (§ 14 ✔) | the same Altinn form for events on a site; e-mail to varsling.akvakultur@mattilsynet.no for transport and slaughterhouse events (Mattilsynet, reviewed 30.03.2026, E1) |

Not in this work, listed so nobody looks for them (the first needs a decision, D-13): matfisk and stamfisk sites on
land or in fresh water file no monthly biomass report but notify Fiskeridirektoratet when a site is taken into use
or emptied and, in continuous operation, give their yearly stock by 7 January (§ 44a ✔); a site with a
forurensningsloven § 11 permit may get other requirements from the Statsforvalter than § 44 first paragraph a–h
(§ 3a, FOR-2026-01-25-85, E1); the
notices for kultiveringsfisk (§ 58 third and fourth paragraphs ✔); the broodstock year report (§ 45,
15 July ✔); recapture start and end (§ 39 third paragraph ✔); samdrift notices (§ 49 ✔); the two-year
operating plan due 1 October (§ 40; Mattilsynet's driftsplan API, E1); Mattilsynet's automated lice-count API
(by agreement only, E1).

### 1.2 Sea lice, weekly

§ 10 ✔ asks for each week: a. sea temperature; b. treatment against lice; c. the active substances and the amounts
used; d. results of sensitivity tests; e. suspicion of resistance; f. the number of lice of the adult female,
mobile and attached stages. How the numbers are made (✔ lovdata; quoted in `farm/health/lice.py:1-19`, health):
- temperature at **3 m depth**, measured at least weekly (§ 6);
- counting every 7 days at 4 °C or above, every 14 below (§ 6); not required when all fish of the site are to be
  slaughtered within 14 days of the due count (§ 6); a cage to be emptied that week must still be counted if 7 days
  have passed since its last count (Mattilsynet complaint decision 20.02.2026, E1);
- at least 20 fish per cage (the text says "minst 20 tilfeldige fisk fra alle merdene"; per cage is the reading
  point 6's mean per cage gives) in weeks 14–21 (Nord-Trøndelag and south) or 19–26 (Nordland, Troms, Finnmark), 10
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
| `lusetelling {voksneHunnlus, bevegeligeLus, fastsittendeLus}` | **no** (nullable) | numbers ≥ 0 | the site's average lice per fish per stage (the API says only "Antall voksne hunnlus"; per fish is Vedlegg 1 point 6 and the guidance, E1). A week in which no count fell due is filed without it; there is no "not counted" reason field (E1) |
| `ikkeMedikamentelleBehandlinger[]` | no | `type` TERMISK_BEHANDLING, MEKANISK_BEHANDLING, FERSKVANNSBEHANDLING, ANNEN_BEHANDLING; `gjennomførtFørTelling` bool; `heleLokaliteten` bool; `antallMerder`; `beskrivelse` (ANNEN only) | non-medicinal treatments of the week |
| `medikamentelleBehandlinger[]` | no | `type` FORBEHANDLING, BADEBEHANDLING, ANNEN_BEHANDLING (with `beskrivelse`); the same flags; `virkestoff {type, styrke {verdi, enhet}, mengde {verdi, enhet}}` with type AZAMETHIPHOS, CYPERMETHRIN, DELTAMETHRIN, IMIDAKLOPRID, HYDROGENPEROKSID, DIFLUBENZURON, EMAMECTIN_BENZOAT, TEFLUBENZURON, ANNET_VIRKESTOFF (with `annetVirkestoff`); strength mg/g, mg/mL, g/kg, mg/kg, %; amount g, kg, t, L | medicinal treatments; a treatment spanning two weeks is reported in both; fresh or warm water is never a medicine: "Vatn er ikkje eit legemiddel ... skal rapporterast som vassbehandling" (guidance, E1) |
| `kombinasjonsbehandlinger[]` | no | lists of the two kinds above | treatments given together |
| `resistensMistanker[]` | no | `resistens` (the eight substances, FERSKVANNSBEHANDLING, ANNEN_RESISTENS) with `annenResistens`; `årsak` BIOESSAY, NEDSATT_BEHANDLINGSEFFEKT, SITUASJONEN_I_OMRÅDET, ANNEN_ÅRSAK with `annenÅrsak` | § 10 e |
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
the site)** and `produksjonsenheter[]` (at least one; "Vi trenger kun produksjonsenhetene som hadde rensefisk i
løpet av måneden"),
each with `merdId` ("skal stemme overens med driftsjournalen") and `arter[]` (at least one, one per species and origin: "antall fisk av valgt art og opprinnelse"):

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
Broodstock of salmon, trout and rainbow trout: spring or autumn stocking, and, where a broodstock permit is
co-located, "hvilken tillatelse opplysningene refererer seg til". One joint report under samdrift. The
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
| `godkjenningsnummer` | `[a-zA-Z\d]{1,6}` ✔ | `SlaughterFacility.approval_number`, `^[A-Z0-9]{1,6}$`, stored in capitals (`farm/models/harvest.py:26-29`, `:63-64`, `:114-116` ✔) | exists; consistent with the API's pattern (which also accepts lower case; we store capitals) |
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
(`farm/stock/fold.py:13-14` ✔); the feeding projection estimates growth (`project`, `farm/feeding/read.py:147-158` ✔).
Its inputs are fixed once older than the backdating window (a protocol's table, species and FCR once assigned,
`farm/models/feeding_protocol.py:75-77` ✔; an assignment starts at most 31 days back,
`farm/forms/feeding_protocol.py:248-255` ✔; water samples likewise, `farm/water/services.py:47-53`), but it adds no
growth on blind days (no protocol, no FCR, `farm/feeding/projection.py:14-15` ✔) and follows master data (a unit's
system, a system's parent) (E3, who retracted an earlier claim that it was not reproducible). On a sea site,
weighings between sea transfer and harvest are rare (E3's field practice, unverified), so the book can stay at an
old weight for months and understate the § 44 d biomass. § 42 b asks for "biomasse og grunnlaget for
beregningen": which figure is filed is decision D-7, and the basis (the last weighing, or the feed and FCR since
it) is filed with it either way. Within a day, operations are folded in the order they were entered, not by the
clock (`farm/stock/fold.py:94-97`, `farm/stock/read.py:33-35` ✔): a weighing entered after a same-day transfer
gives the transfer's destination other kilos than one entered before it (E3 ran it); counts are not affected.

### 2.2 Sea lice

| Field | Here | Status |
|---|---|---|
| week | ISO week on the site's clock (`farm/health/read.py:52-54`, health) | ok |
| `sjøtemperatur` | `WaterMeasurement.temperature_c` (`farm/models/water.py:107` ✔) of the site's units or systems in the week | **gap**: samples have no depth (`farm/models/water.py:77-119` ✔, grep `depth`: none, E3); § 6 asks for 3 m. Proposed `WaterMeasurement.depth_m` (Decimal 5,2, null) and the rule "the week's mean of the site's samples taken at 3 m"; without one the report names the missing sample and links to Water chemistry to record it (OUR-13), it does not take a typed temperature |
| `lusetelling` (3 stages) | `lice_weeks()` → `LiceWeek.average(stage)`: the latest count of each unit counted in the week, mean of the units' averages (`farm/health/read.py:57-126`, health) | ok, the health read is reused as it is; the report also compares the cages counted with the cages holding salmonids that week and names a cage that was due a count and has none (5.2; "Snitt fra telling i alle merder", Vedlegg 1 ✔) |
| `ikkeMedikamentelle[].type` | `Treatment.method` thermal / mechanical / freshwater / other (`farm/models/health.py:208-219`, health), `reason = sea_lice` | ok (1:1) |
| `medikamentelle[].type` | `Treatment.method` in_feed → FORBEHANDLING, bath and dip → BADEBEHANDLING, injection → ANNEN_BEHANDLING | mapping unverified (E3) |
| `virkestoff.type` / `styrke` / `mengde` | `Medicine.lice_report_code` (official values, `farm/models/health.py:72-84`, `:123`), `strength_value`+`strength_unit` (`:125-127`), `Treatment.amount_value`+`amount_unit` (`:279-281`) (health) | ok; the amount is optional, and a lice treatment may use a medicine with no substance code (OUR-10, belongs to health) |
| `gjennomførtFørTelling` | derived from `Treatment.start_date`/`end_date` against each treated unit's count date that week | **same-day ambiguous** (no times on either): a person's answer per treatment, stored on the report (`TreatmentAnswer`, 5.3), offered the value the dates suggest |
| `heleLokaliteten`, `antallMerder` | `Treatment.units` against the units holding salmonids on the treatment's first day in the week (`stock_on`); `antallMerder` given only when not the whole site | derived |
| `kombinasjonsbehandlinger` | none (one medicine per treatment, `farm/models/health.py:271`, health) | **person enters** on the report: which of the week's treatments were given together |
| `resistensMistanker`, `følsomhetsundersøkelser` | none (`EventKind` has no such kind, `farm/models/health.py:367-371`, health) | **person enters** on the report (child rows); the source of truth for sensitivity tests could later be a lab result of the health records |

### 2.3 Smolt

| Field | Here | Status |
|---|---|---|
| `karId` | `Tank.regulatory_unit_id`, else `Tank.code` | ok (OUR-07) |
| `artskode` | the unit's batches' `Species.official_code` (one species per unit, `farm/stock/services.py:283-286` ✔) | ok; blank code → the report cannot be marked ready |
| `beholdningVedMånedsslutt` | fold at the month's last day, count | exact for a unit holding fish at the month's end |
| `snittvektGram` | fold at the month's last day, grams / count (book) | rule D-7; the API wants it above 0 (`exclusiveMinimum`, ✔ copy) |
| a unit emptied in the month | the count and average just before the operation that emptied it (the fold's `before` hook at that operation, `farm/stock/fold.py:133-142` ✔), since the fold has no average at 0 fish (`:83-85` ✔) and the API wants every unit that held smolt in the month | whether its `beholdningVedMånedsslutt` is that count or 0 ("eller når produksjonsenheten ble tømt") is decision D-8 (E3) |
| `antallSelvdød` | −Σ lines(MORTALITY, month) count_delta | ok |
| `antallAvlivet` | −Σ lines(CULL, month) | ok |
| `antallFlyttetEksternt` | −Σ lines(TRANSFER_OUT, month) whose paired TRANSFER_IN is on another site (same operation, same `pair`, `farm/models/stock.py:294` ✔) | **gap**: no operation delivers fish out of the company (a sale of smolt); HARVEST needs a slaughter facility (OUR-04, E3) |
| which units | every unit of the site with a line in the month or fish at its start, holding "startfôringsyngel eller eldre fisk" (§ 58) | the rule for "start-feeding or older" is D-8 |

### 2.4 Cleaner fish (once cleaner fish can share a cage, section 3)

| Field | Here | Status |
|---|---|---|
| `merdId` | `Tank.regulatory_unit_id`, else code | ok |
| `artskode` | `Species.official_code` of the cleaner batches (`cleaner_fish_type` set, `farm/models/species.py:103-105` ✔) | ok once the catalogue carries the ASFIS codes (3.4, OUR-19) |
| `opprinnelse` | one row per unit, species and origin; both origins of a species in a unit may be folded into VILLFANGET_OG_OPPDRETTET (optional in the API, "kan man bruke") | **gap**: `purchased` says how, not wild or farmed (`farm/models/stock.py:40-43` ✔), and the API has no "unknown" (1.4); proposed: a provenance farmed / wild-caught on the batch, required for a cleaner-fish species (E3) |
| `beholdningVedForrigeMånedsslutt` | fold at the day before the month, count | exact |
| `utsett.antallNy` | Σ lines(INPUT, month) | ok |
| `utsett.antallFlyttetInn` | Σ lines(TRANSFER_IN, month): from any other unit, of this site or another (the API: "fra en annen produksjonsenhet") | ok |
| `uttak.antallSelvdød` | −Σ lines(MORTALITY, month), every cause | ok |
| `uttak.antallAvlivetSykdom` … `SkalIkkeBrukes` | −Σ lines(CULL, month) by reason | **gap**: `CullReason` (`farm/models/stock.py:87-94` ✔) has `sick` only; proposed: the cull of a cleaner fish takes the official six causes (OUR-08) |
| `uttak.antallFlyttetUt` | −Σ lines(TRANSFER_OUT, month) | ok |
| `uttak.antallKanIkkeGjøresRedeFor` | −Σ lines(ADJUSTMENT, month) with reason `unaccounted_loss` (a harvest that empties a unit writes it, `farm/stock/services.py:594-596` ✔) | partial: escape and count corrections need a rule (D-9) |
| balance | opening + utsett − uttak = closing (fold at the month's last day) | **checked on read**. A harvest of a cleaner-fish batch is refused by the stock (their end of cycle is a cull "skal ikke brukes"); the month's count adjustments are netted per unit, species and origin: a net loss is "kan ikke gjøres rede for", a net gain (a true upward recount) is shown with its explanation as a warning that still lets the person file (D-9), never a block: after 31 days it could not be voided (`farm/stock/services.py:450-458` ✔) and the month would be unfileable (E3) |
| `tørrforKg` / `våtforKg` (the site's totals for the month, integer kg) | `fed()` of the site's cleaner batches, by the feed's form | **gap**: a feeding cannot name its fish (split by biomass, `farm/feeding/fold.py:184-191` ✔) and a feed has no dry/wet form (`farm/models/feed.py:47-56` ✔); proposals in 3.2 |

### 2.5 Monthly biomass (§ 44)

| § 44 item | Here | Status |
|---|---|---|
| fallow date | the day the site's last production fish left (fold); cleaner fish may stay through fallowing (§ 40 fifth paragraph ✔) | derivable |
| a. unit number | `Tank.regulatory_unit_id` | ok (OUR-07) |
| b. stocking: species, number, year class | lines(INPUT) and arrivals from other sites in the month | **year class missing** (OUR-16); proposed `Batch.year_class`, with no default for batches stocked as eggs, larvae or fry (a batch keeps its identity through moves, `farm/stock/services.py:534-549` ✔, so a default from the input date would carry the egg year into the sea); the definition and the spring/autumn rule are D-14 |
| c. stock: species, number, year class | fold at the month's end, per unit and batch | year class as above |
| d. biomass | fold at the month's end, kg (book) | rule D-7 |
| e. harvest: species, number, slaughter weight, condition | lines(HARVEST): count, `measured_weight_kg` (round weight, `farm/models/stock.py:291-293` ✔) | **slaughter weight and condition missing**: round kilos only; the slaughter result is not ported (`farm/models/harvest.py:148-149` ✔; Harvest owner decisions) (OUR-18) |
| f. live fish out, destination site | lines(TRANSFER_OUT) whose pair is on another site; the destination site's lokalitetsnummer | ok within the company; **out of the company missing** (OUR-04) |
| g. losses: mortality and other causes, number, quantity | lines(MORTALITY, CULL, ADJUSTMENT) by reason, an upward correction as a negative counting error; kg from `measured_weight_kg` when weighed, else the grams the fold took out | the cause list of Fiskeridirektoratet's statistics is Dødfisk, Utkast fra slakteri, Rømming, Annet, Tellefeil (E1); the mapping (mortality and culls → Dødfisk, escape → Rømming, count corrections → Tellefeil, unaccounted loss → Annet; Utkast from the slaughter result, not our culls) is D-15, unverified |
| h. feed kg and feed type | `fed()` per unit and feed; `Feed.feed_type` (`farm/models/feed.py:47-56` ✔) | ok; whether "fôrtype" means this list is unverified |
| i. volume the fish can move in | `Tank.water_volume_m3` else `volume_m3` (`UnitStock.volume_m3`, `farm/stock/read.py:142-145` ✔) | ok |
| j. reduced-capacity production | none | **person enters** (rare; a unit flag later) |
| third paragraph (feed trade names, medicines, impregnated nets) | not in force (§ 70, E1) | not reported; `Feed.name` and the treatments (health) give them when it is |

### 2.6 Slaughter

| Field | Here | Status |
|---|---|---|
| planned kg per locality, species and weekday | `HandlingPlanItem` (kind harvest) live and not cancelled: `date.isoweekday()`, `unit` → site, `batch.species`, `planned_kg` (`farm/models/harvest.py:248-286` ✔) | `planned_kg` is round weight and may be empty (OUR-09); the plan's date is the day the fish leave the unit, the API's weekday the slaughter day ("planlagt slaktet på mandag", ✔ copy): they differ when fish wait in a wellboat or the slaughterhouse's pens, so the report shows the days for the person to confirm, or the plan gets a slaughter date (D-3) |
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
`tank_batches` row (`cleanerFishDetails`, `batch/entities/tank-batch.entity.ts:78-92`, `:208-225`, E2), created and
moved by five commands of their own (create, deploy, mortality, removal, transfer) with operation types
`cleaner_deployment`, `cleaner_mortality`, `cleaner_removal`, `cleaner_transfer_in/out`
(`batch/entities/tank-operation.enums.ts:39-43`, E2). A second stock beside the salmon's, with its own bugs
(REP-46 to REP-49) and no month-end reconstruction (`batch/services/stock-reconstruction.service.ts:30-34`, E2).
Deaths and removals are told apart, but a removal's reason is free text inside its notes: nothing says whether a
removed fish was put down, nor which of the regulator's causes, so the nine uttak causes **cannot be derived from the
source's records** (E2). The source does record farmed or wild origin, on the batch (`batch/entities/batch.entity.ts:156-166`)
and per cage entry (`batch/entities/tank-batch.entity.ts:87`), and its assembler maps it (`regulatory/assembly/assemblers/rensefisk.assembler.ts:141-146` ✔);
the UI sends "unknown" anyway (REP-29). Feed is recorded per batch with the tank optional and no dry/wet field
(`feeding/entities/feeding-record.entity.ts:123-138`, `:185-206`); the feeding code has no cleaner-fish logic, and the
protocol seeder creates no cleaner-fish protocol (`feed/services/feeding-protocol-seeder.service.ts:23-30`) (E2). And,
suspected, the cleaner-fish commands and the report may not even read the same container table (REP-56).

### 3.2 Here

The README already says the cleaner-fish track comes "later, as batches of a cleaner-fish species"
(README.md, Operations › Production units, "Not ported") ✔, and a species can be marked a cleaner fish
(`Species.cleaner_fish_type`, `farm/models/species.py:47-51`, `:103-105` ✔). That is the right shape: one ledger,
the same operations (stocking, mortality, cull, transfer, harvest), the same fold, so the cleaner-fish report's
counts are the ledger's per unit, exactly as the owner asks. What blocks it:

1. **One species per unit** (owner decision Q1): the stock refuses a second species in a unit
   (`farm/stock/services.py:13-14`, `:283-286`, `:332-336` ✔). Lumpfish and wrasse live in the salmon's cage;
   § 47 fourth paragraph forbids only fish of different *holders* in one unit ✔. Proposed: a unit holds one
   species, except that on a sea site cleaner-fish batches may join the unit's production species (decision D-1;
   a hatchery tank still holds one species, since the smolt report has one `artskode` per `karId`, E3).
2. **Feed split**: each feeding is split between every batch in the unit by biomass
   (`farm/feeding/fold.py:184-191`, `_present` `:237-239` ✔): salmon feed would be booked to lumpfish and
   lumpfish blocks to salmon (OUR-02). Proposed: the feeding record names its target (production fish or
   cleaner fish), defaulted from the feed's suitable species (`FeedSuitability`, `farm/models/feed.py:246-272` ✔)
   and stored on the record; the walk splits each record among its target's batches, and a feeding with no
   batch of its target at the start or the end of its day is refused as today's feedings without fish are
   (`farm/feeding/fold.py:176-179`). Suitability alone cannot do it: an unsuitable feed is a notice today, not a
   refusal (`farm/feeding/views.py:341-347`, `farm/forms/feeding.py:72-86`), a feed may suit both, and a
   lumpfish feed on a day with only salmon would divide by zero at `farm/feeding/fold.py:187` (E3). Decision D-1.
   With a dry/wet form on the feed (`Feed.form`), the report's `tørrforKg`/`våtforKg` are reads.
3. **Unit figures** (density, capacity, survival, average, ration, FCR) sum every share
   (`farm/stock/read.py:126-182` ✔; `farm/feeding/projection.py:184-188`, E3), and so do the capacity check when fish
   arrive (`farm/stock/services.py:287-290`, `:308-322` ✔), the feed-rate acknowledgement
   (`farm/feeding/services.py:58`) and, in the health records, the lice count's "has fish" (`farm/health/services.py:79-80`,
   health), which must count salmonids only (E3); five places take the unit's first
   batch as "the" species (`farm/forms/feeding.py:78-79`, `farm/feeding/views.py:346`,
   `farm/handling/check.py:166`, `templates/farm/production_units.html:95`, `templates/farm/_unit_drawer.html:14`,
   E3). Proposed: the unit's production figures read the production shares; the cleaner fish get their own line
   in the drawer and the page's announced cleaner-fish tab (README, Production units ✔). Cleaner fish are outside § 47
   and § 44 c–d (§ 3 h ✔) and not counted in a unit's number of fish (E1); whether they count in its density is D-2.
4. **Cull reasons**: the cull reason list gains the six official "avlivet" causes (checked by the database,
   `_reason_rule`, `farm/models/stock.py:252-256` ✔); the stock service lets a cleaner-fish batch's cull take only
   those six and a production batch's only the others (a database check cannot see the batch's species, which is
   on the batch, E3).
5. **Origin**: a provenance, farmed or wild-caught, required for a cleaner-fish species (the API has no
   "unknown", 1.4), beside how the fish were acquired; a wild-caught batch bought
   from a fisherman may then name its supplier (today refused, `chk_batches_supplier`,
   `farm/models/stock.py:184-190` ✔, OUR-11).

These are changes to the stock and feeding code, not to the reports; each is a step of its own with its own
tests, decided in section 6.

### 3.3 What the report then is

Per unit with cleaner fish at the month's start or a cleaner-fish line in the month, per cleaner species: the
fold's count the day before the month, the month's lines by kind and reason, the fold's count at the month's
end, and the balance between them (D-9); the site's dry and wet feed of the month. Nothing is typed but the
contact person: every field of the API comes from the records.

### 3.4 The cleaner-fish species codes

The source's schema accepts USB, BER, GRO, BNB (`schemas/official/rensefisk-v1.schema.json:67` ✔) and its UI
maps USB to lumpfish (rognkjeks) (`CleanerFishReportTab.tsx:95-108`, E2). Our catalogue keeps these codes marked
unverified and notes that in FAO ASFIS USB is the ballan wrasse (`farm/species_catalog.py:7-13` ✔).
Mattilsynet's API asks for "kode i store bokstaver etter FAO-standarden" (`[A-Z]{3}`) ✔. Against the FAO ASFIS
list 2026.1 (E1): **LUM** *Cyclopterus lumpus* (lumpfish, rognkjeks); **USB** *Labrus bergylta* (ballan wrasse,
berggylt); **YFM** *Symphodus melops* (corkwing, grønngylt); **TBR** *Ctenolabrus rupestris* (goldsinny, bergnebb);
ENX *Centrolabrus exoletus* (rock cook, gressgylt). The source's BER, GRO and BNB are other species in ASFIS
(*Brachypterois serrulata*, "groundfishes nei", a sharkminnow) and its USB is the wrong fish: every cleaner-fish
code the source sends is wrong (REP-51), and so are ours (OUR-19), which are kept unverified and never filled in.
The Norwegian name to Latin name pairs are the usual ones; no official page lists them (E1, unverified).

## 4. Bugs found

The source's bugs (**REP-01** to **REP-62**) are in `docs/aquaculture-platform-bugs.md`, section "Regulatory reports",
with the other tabs'; the Harvest section holds HRV-02, -03, -04, -08, -13 and -14 and the Health section HLT-09, HLT-11
and HLT-22, which this document refers to and does not repeat. What is wrong on our side (**OUR-01** to **OUR-25**) is
here, with what was done about each.

### 4.1 Our side

**Status after Phase 2.** Fixed as the last column says: OUR-01 to OUR-08, OUR-11 (a bought batch says it is wild-caught),
OUR-12 (nine digits; the mod-11 check is not made, its rule is unverified), OUR-13 (the water module's depth points, read
through `farm/water/read.py`), OUR-16, OUR-17, OUR-19 to OUR-25; OUR-03 gave an escape its dialog, a count correction up or
down still has none. Not fixed, and why: OUR-09 (a planned harvest may still have no kilos: the planned-slaughter report names
it as a problem and cannot be filed), OUR-10 and OUR-14 (the health module's: the lice report names the treatment it cannot
report and reads the week with `stock_on`), OUR-15 (a company time zone: out of the reports' scope, they run on Oslo's
calendar), OUR-18 (the slaughter result: D-3 builds the planned slaughter only).


| ID | Sev. | Where | What is wrong | Fix (Phase 2 unless said) |
|---|---|---|---|---|
| OUR-01 | High | `farm/stock/services.py:13-14`, `:283-286` ✔ | One species per unit: cleaner fish cannot be in the salmon's cage, so the cleaner-fish report cannot say which cage they are in. | Production species only (D-1). |
| OUR-02 | High (once OUR-01 is lifted) | `farm/feeding/fold.py:184-191` ✔ | A feeding is split among every batch in the unit by biomass. | Split among the batches of the species the feed suits (3.2). |
| OUR-03 | High | `farm/stock/services.py:41` ✔; `farm/models/stock.py:46-48` ✔ | Count adjustments, escape among them, have no dialog: an escape cannot be booked, a recount cannot correct the stock (E3). | An escape record with its adjustment (5.3); the adjustment dialog. |
| OUR-04 | High | `farm/models/stock.py:46-56` ✔; `farm/models/harvest.py:154-155` ✔ | No operation delivers live fish out of the company (smolt sold or delivered to a customer's site): a hatchery cannot book its deliveries (E3). | A delivery operation (removal with a destination: customer, its site's lokalitetsnummer). Decision D-10. |
| OUR-05 | High | `farm/stock/services.py:450-458` ✔; `farm/stock/dates.py:66-73` ✔; `config/settings.py:202` ✔ | Records may be dated or voided up to 31 days back, so a filed month changes silently when recomputed (E3 ran it: voiding a 20 Oct weighing moved a 31 Oct biomass from 97 to 48.5 kg). Nothing records a filed report. | The reports' frozen content and "no longer matches" (5.4). |
| OUR-06 | Medium-High | `farm/models/tank.py:535-546` ✔; `farm/models/production_department.py:43-47` ✔; `core/softdelete.py:7` | A unit with stock lines, holding fish now or not, may be moved to a production department on another site (only its size is protected), and deleting a site detaches its departments (SET_NULL): past figures per locality move with the unit or lose their site (E3, E4). Same class as HRV-13. | A unit with stock lines keeps its site; a site whose units have stock lines is closed, not deleted (`delete_blockers`). |
| OUR-07 | Medium | `farm/models/tank.py:400-404` ✔ | `regulatory_unit_id` is unique across the company, but unit numbers are per locality ("merd 1" on two sites) (E3). | Unique per site. A database constraint cannot follow the department to its site (E3, E4): the unique constraint becomes per production department (what the database can hold), and the per-site rule is checked in `clean()` under a lock on the site and by `check_stock`. |
| OUR-08 | Medium | `farm/models/stock.py:87-94`, `:109-113`, `:249` ✔ | The cull reasons cannot fill the rensefisk causes; an "escape" adjustment may be positive (E3). | 3.2 point 4; an escape is negative. |
| OUR-09 | Medium | `farm/models/harvest.py:267-270` ✔ | A planned harvest may have neither fish nor kilos (E3). | Kilos required for a planned harvest (the planned-slaughter report needs them). |
| OUR-10 | Medium | `farm/health/services.py:96-116` (health) | A lice treatment may use a medicine with no lice substance code, and its amount is optional (E3). | Reported to the health work; the report blocks "ready" and names the treatment meanwhile. |
| OUR-11 | Medium | `farm/models/stock.py:184-190` ✔ | Wild-caught fish bought from a fisherman cannot name the supplier (E3). | 3.2 point 5. |
| OUR-12 | Medium | `farm/models/site.py:48` ✔; `farm/forms/site.py:42-43` ✔ | "Organisation number override" of a company number that exists nowhere; 20 free characters though the placeholder says 9 digits. | `Site.organisation_number`: by default the permit holder's, 9 digits with the mod-11 check (E3 proposes; the check rule unverified), required to file. The API's number is "selskapet som eier fisken" ✔: contract production for a customer will later need an owner on the batch (E3, unverified practice). |
| OUR-13 | Medium | `farm/models/water.py:77-119` ✔ | Water samples have no depth; the lice report's temperature is at 3 m (§ 6 ✔). | `depth_m` on the sample. |
| OUR-14 | Low | `farm/health/read.py:65` (health) | The lice week's "N of M units counted" uses the units holding fish now, not that week (E3). | Reported to the health work; the report uses `stock_on`. |
| OUR-15 | Low | `config/settings.py:145` ✔; `farm/models/site.py:69-70`, `:138-141` ✔ | A site without a time zone runs on UTC (company default `TIME_ZONE='UTC'`), so its day and ISO week edges are UTC's. | A company time zone setting; out of the reports' scope, noted. |
| OUR-16 | Medium | `farm/models/stock.py:134-171` ✔ | No year class (årsklasse) on a batch; § 44 b, c and § 42 ask for it. | `Batch.year_class` (D-14). |
| OUR-17 | Low | `farm/models/feed.py:47-56` ✔ | No dry/wet form on a feed (rensefisk). | `Feed.form`. |
| OUR-18 | Gap | `farm/models/harvest.py:148-149` ✔ | No slaughter result (gutted kg per quality class, slaughter condition): § 44 e and the executed-slaughter report. | `SlaughterResult` 1:1 with the harvest record (Harvest's plan). |
| OUR-19 | Low | `farm/species_catalog.py:49-57` ✔ | The catalogue's cleaner-fish codes are the source's wrong ones (USB for lumpfish, BER, GRO, BNB); they are marked unverified and never filled in, so nothing filed carries them yet. | LUM, USB, YFM, TBR, verified against ASFIS 2026.1 (3.4). |
| OUR-20 | Medium | `core/crud.py:330-333` ✔; `templates/crud/form.html:8`, `detail.html:7`, `confirm_delete.html:6`, `list.html:8` ✔ | The heading above a tab's title is the menu group's label; a tab in an unlabelled menu group shows " · Title" and an empty heading (E4; latent today; the Regulatory reports entry will sit in an unlabelled group under the Reports heading). | One helper on `navigation.Place` that every page uses. |
| OUR-21 | Medium | `core/audit.py:91` ✔ | The activity log stores a record's name as `str(instance)` in the language of the person's request, though the log is English at rest (`core/audit.py:1-7`); E4 printed a water limit's name in nb and tr. | Build the default name inside `source_language()`. |
| OUR-22 | Medium | `core/crud.py:278-292`, `:630-642` | A row-list save locks nothing and checks no version, unlike the edit view (`:554-562`): a row-list save racing another save (for a report: its submission) keeps rows the frozen content does not have (E4). | Lock the parent (`select_for_update`), post the parent's version with the row list and refuse a stale one, bump the parent's version on save (E4: the row-list templates post none today). |
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
   which treatments were combined, a resistance suspicion, an event's narrative) is typed on the report, in typed
   columns or rows, never JSON (the house rule, README.md:287-288, :360, :913 ✔; E4).
3. **A missing fact is recorded where it belongs.** A temperature at 3 m is a water sample with its depth, a
   cleaner fish's cull cause is the cull's reason, a year class is the batch's: the report links to the place to
   record it and names what is missing; it does not take the value itself. One exception for now: a sensitivity
   test's result is a health fact with no health record yet, so it is a row of the lice report until the health
   records have lab results (then it moves there and the report reads it).
4. **Nothing is sent.** No Altinn, Maskinporten or Mattilsynet API calls, no e-mails to authorities, no
   scheduler, retries or outbox (the source's whole submission pipeline is not ported). A person files and records
   that they did.
5. **What was filed is frozen and checked.** Recording a submission stores the content as filed; the page
   recomputes and says when the records no longer give the same content (OUR-05: records may change up to 31 days
   back, some without a window).
6. **Due reports are computed on read**, from the sites, their fish and the calendar, never created by a job
   (REP-14, REP-15).

### 5.2 What is due

Which reports a site owes depends on what it produces, not on where it is (E1): settefisk is "rogn og fisk som
produseres med sikte på overføring til andre lokaliteter eller annen type produksjon" (§ 4 nr. 27 ✔) and is
governed by chapter 5 (§ 58), matfisk and stamfisk by chapter 4 (§ 44 at sea, § 44a on land or in fresh water)
(§ 3 a, b ✔). So a site gets a **production form** (a new `Site` column: matfisk, settefisk, stamfisk; empty =
not set up, decision D-13) beside its type, and a **reports-from date** (D-6).

`reports/due.py` lists, per kind, the (site or facility, period) pairs owed between the site's reports-from date
and the last closed period, minus the periods that have a **submitted** report; a started draft stays on its due
row with its deadline and overdue mark (E4). A site that owes reports by its form and fish but has no
reports-from date is listed as "not set up for reports" rather than hidden (E4).

| Kind | Owed for | Applies when | Deadline |
|---|---|---|---|
| Sea lice | site, ISO week | a sea site (`Site.type = sea_cage`) held fish of salmon, trout or rainbow trout (`official_code` SAL, TRS, TRR; D-11) at any time in the week | Tuesday of the next week, end of the day ("i løpet av tirsdag") |
| Smolt | site, month | a settefisk site (cleaner-fish hatcheries included, § 3 i ✔) held fish of start-feeding stage or older at any time in the month (D-8) | the 7th of the next month |
| Cleaner fish | site, month | a matfisk sea site held cleaner fish (a species with `cleaner_fish_type`) at any time in the month | the 7th of the next month |
| Monthly biomass | site, month | a matfisk or stamfisk sea site held production fish (not cleaner fish: they may stay through fallowing, § 40 fifth paragraph ✔) at any time in the month | the 7th of the next month |
| Planned slaughter | slaughter facility, ISO week | live planned harvests (`HandlingPlanItem` kind harvest, not cancelled) to the facility in the week (D-3) | the earlier of Thursday 24:00 of the week before and the day the fish start fasting for it (restkontrollforskriften § 9a ✔; the fast's start is `fast_of(item)`, `farm/handling/fasting.py:12-14`, `:119-122` ✔); a slaughter agreed later: at once; corrections until Tuesday 09:00 of the slaughter week (E1) |
| Escape | an escape record | every escape record with no live notice | at once ("straks") |
| Disease | a health event | a health event with a listed diagnosis, suspected or confirmed, with no live notice; and a mortality event whose cause is still unexplained 14 days after the first assessment (dyrehelseforskriften § 7, E1) | at once ("umiddelbart"); the second case "så snart som praktisk mulig" |
| Welfare | started by a person | — | at once ("umiddelbart") |

The window's eligibility is read from summed live `count_delta`: one query per kind for each site's net count of
the relevant fish before the window and its daily deltas and arrival days inside it, then a walk over the periods
in Python (the number of queries is E4's estimate, unverified). The last closed period, today and every deadline
are in Europe/Oslo, whatever the site's clock (the company default is UTC, OUR-15); overdue is "today in Oslo is
after the deadline". ISO weeks use the ISO week-numbering year: 28 December 2026 to 3 January 2027 is 2026-W53
(which year Mattilsynet expects at that edge is unverified; a test pins it).

Sea lice in particular (Vedlegg 1 ✔, § 6 ✔, E1): the week's figure is the mean over the cages counted, so the
report compares the cages counted with the cages holding fish and does not mark itself ready while a cage that was
due a count has none ("Snitt fra telling i alle merder"); a cage needs no count that week when its last count is
younger than 7 days (14 below 4 °C), when all fish of the site are to be slaughtered within 14 days, or for
broodstock below 4 °C; a week in which no count fell due is filed with the temperature and no counts, and the page
says why (the filing itself has no reason field).

### 5.3 Models (a new app `reports`, like `inventory`; it reads `farm`, `farm` never imports it)

**`Report(AuditedModel)`**, table `regulatory_reports`, a `core.crud` Resource (E4):
- `kind`: sea_lice, smolt, cleaner_fish, biomass, slaughter_planned, escape, disease, welfare (and, only if
  D-3 says so, slaughter_executed);
- `site` (PROTECT) — empty only for slaughter; for an event, taken from the event when the report is started;
- `facility` (`SlaughterFacility`, PROTECT) — slaughter only; a check: exactly the one the kind needs (precedent
  `farm/models/harvest.py:297-301` ✔);
- `period_start` (Monday of the ISO week, or the 1st of the month; the end is derived, never stored), empty for
  events, with checks that it is a Monday / the 1st;
- `health_event` (PROTECT; disease required, welfare optional), `escape` (PROTECT; escape required): a check per
  kind;
- `contact_name`, `contact_email`, `contact_phone` (required to submit; the name and e-mail are prefilled from the
  person, who has no phone on record, E4);
- for the event kinds, the narrative as **columns of the report** (what happened, when it was found, cause, fish
  dead / injured / involved, the situation now, measures taken), kept empty for other kinds by checks and left off
  their form (precedent `knowledge/models/entry.py:105-120`, `core/crud.py:92-93`, E4), so they are on the one
  edit form, logged and tested like every field. They hold **what was told**: prefilled once from the event when
  the report is started, then the person's text;
- `corrects` (self, PROTECT, related name `corrections`): a correction is a new report of the same key that
  replaces a submitted one;
- `submitted_at` (when the person says they filed), `submitted_by` (who recorded it, PROTECT), `channel` (Altinn
  form, API from another system, e-mail, telephone, other; checked against its values) and `reference` (the
  receipt or case number): `submitted_at`, `submitted_by` and `channel` all set or all empty; `reference` required
  unless the channel is telephone or other (a notice phoned in at once has no receipt, E4);
- the status is derived, never stored: **draft** (no submission), **submitted**, **superseded** (a submitted
  correction replaces it), and, read on demand, **needs correction** (5.4).

Constraints and rules:
- one live original per (kind, site, facility, period_start) where `period_start` is set
  (`condition=Q(is_deleted=False, corrects__isnull=True, period_start__isnull=False)`, `nulls_distinct=False`
  since site or facility is empty; precedent `core/crud.py:142-143`), one per (kind, health_event) where the event
  is set, one per escape where it is set; one live correction per report (E4);
- the key (`kind`, `site`, `facility`, `period_start`, `health_event`, `escape`, `corrects`) is fixed after
  creation (`fixed_after_creation`, `core/crud.py:106-109`, plus `clean()` against the stored row);
- a correction points at a submitted report with the same key, and an event report's site is its event's: checked
  by the service that creates them and by `manage.py check_reports` (precedent `check_stock`,
  `farm/stock/integrity.py`), which the tests run;
- a submitted report is never deleted (a check on `is_deleted` with `submitted_at`, plus `delete_blockers()`),
  and its row cannot change: a BEFORE UPDATE OR DELETE trigger compares the row without the user columns (which
  Django may set to NULL) once `submitted_at` is set (E4's generic `to_jsonb(NEW) - …`; precedent the audit log's
  append-only trigger, `core/migrations/0003_audit_log_append_only.py`), and `clean()` refuses it with a readable
  message, because the edit view saves unconditionally (`core/crud.py:563-569`, E4).

**`ReportSnapshot`** (one-to-one with the report, PROTECT, append-only by trigger): `format_version`, `content`
(JSON), `content_sha256` (64 hex), `sources_fingerprint` (64 hex: a hash of what the report's source queries return:
the id, version and deleted flag of every row they match — every ledger line of the batches read dated up to the
period's end (through its operation, since lines have no version of their own), the period's feedings, samples,
health and plan rows, and the master rows read: site, units, species, medicines — recomputed by re-running the
queries, with no fold; so a void, a backdated entry with a new id, and a unit moved to another site all change it,
E3, E4). The content is what was told to the authority: the figures as filed (keyed by
record ids, with the codes, not translated labels; decimals as strings), the person's fields, the identity
(organisation number, lokalitetsnummer, unit numbers, species codes) as they were, and per figure its provenance
(the function, its arguments and the ids of the records it read). JSON here is a frozen document read only to
compare and to re-export, never as an input (the audit log's `changes` is the precedent, `core/models.py:172-175`;
E4). The hash also goes into the submission's activity-log entry, which is append-only, so the frozen content
cannot be swapped unseen.

**Person-entered rows** (RowLists; each with `created_by` and an English `describe()` for the log; `applies_to()`
refuses them once the report is submitted, and a trigger on each table refuses INSERT, UPDATE and DELETE while
its report's `submitted_at` is set, E4):
- sea lice: `TreatmentAnswer` (report, treatment PROTECT, `done_before_count` Boolean, `combination` group
  number; unique per report and treatment) for the week's lice treatments; `ResistanceSuspicion` (substance from
  the API's `resistens` list, cause from its `årsak` list, the other-text fields); `SensitivityTest` (date,
  laboratory, substance, result);
- biomass: `UnitAnswer` (report, unit PROTECT, reduced-capacity production; unique per report and unit) — the one
  § 44 item no record holds.

**Outside the app** (each its own step, with the owner's decision where marked): `Site.organisation_number`
(OUR-12), `Site.production_form` (D-13), `Site.reports_from` (D-6), unit numbers unique per site (OUR-07), a unit
with stock keeps its site (OUR-06), `WaterMeasurement.depth_m` (OUR-13), `Batch.year_class` (OUR-16), `Feed.form`
dry / wet (OUR-17), the cleaner-fish track (section 3, D-1, D-2), an **escape record** in the stock (`farm`): the
escape with its time found, cause, suspected or confirmed, health status, recapture, and the count-adjustment lines
that take the fish out of the units (OUR-03; the stock stays the only writer of fish), a delivery operation
(OUR-04, D-10), the slaughter result (OUR-18, D-3).

### 5.4 Submitting, freezing, "no longer matches", corrections

- **Ready** is computed: every required field has a value, every unit balances, the lice coverage holds, the
  identity is complete (organisation number, lokalitetsnummer, unit numbers, species codes); the page lists what is
  missing and links to where it is recorded.
- **Record as submitted** (Edit permission): the person gives when, how and the reference; in one transaction
  `reports/services.py` locks the report, checks its version, computes the content, stores the snapshot and the
  submission fields, and logs it.
- **No longer matches**: the report's page recomputes and compares with the snapshot, figure by figure keyed by
  record ids, and shows the differences ("unit M3: died 140 → 152, the mortality of 28 Oct was voided on 2 Nov").
  A change of identity (a unit's number, the lokalitetsnummer, a species code renamed since) is shown apart as
  "identity changed since filing"; whether that needs a correction is the person's call (E4). A difference of
  format (a newer `format_version`) is told apart from a change of records. The list marks a report when its
  `sources_fingerprint` no longer matches, re-read only for reports whose period is inside the backdating window
  or whose sources have no window (health events, treatments, harvest plans; E4).
- **Correction**: "Start a correction" creates a report with `corrects` set; it is filled and submitted like any
  other; the original shows "superseded by". Mattilsynet's guidance for lice is to send the whole week again (E1),
  which is exactly a correction's content.

### 5.5 Exports (per kind, from the snapshot once submitted, else live and marked "not submitted")

- **Print**: a page in the order of the authority's form, the official Norwegian field names beside the
  person's language, the identity on top; print CSS, the print button in TypeScript (`frontend/`).
- **CSV**: section, official field, value. Free text goes through the database viewer's formula guard, made one
  function both use (`formula_safe(text)`, out of `Grid.export_text`, `core/dbgrid.py:32`, `:258-265`, E4);
  numbers are written as numbers, so a sea temperature of −0.4 °C stays a number.
- **JSON in the shape of Mattilsynet's API** for the lice, smolt, cleaner-fish and planned-slaughter reports, for a
  person or another system that files through the API. A copy of the relevant schemas of the OpenAPI read
  2026-11-03 (NLOD licence, E1) is kept with the tests, and every export is validated against it with `jsonschema`
  (a new pinned dependency) or a hand-written validator of the subset used (decided in Phase 2 by what the subset
  needs). The OpenAPI lists `unknownProperties` as required on several objects, a Java artefact (E1): the export
  leaves it out and the test copy drops it from `required`, saying so (whether Mattilsynet's server wants `{}` is
  unverified).
- The biomass report: print and CSV only (Fiskeridirektoratet's current form is unverified, 1.5).

### 5.6 Menu and pages

A fourth heading in Production: **Reports**, after Operations and before Communication, with one entry
**Regulatory reports** in an unlabelled group (`/reports/`, icon `file-text`). Not under Operations: Operations
holds the daily records (`config/navigation.py:71-74` ✔), and a report is neither a daily record nor structure,
which is why Communication got a heading of its own (`config/navigation.py:95-97` ✔); the source also keeps
Reports apart (E4). The texts that count the headings change with it (README.md:1628-1631, `config/navigation.py:10-13`,
the headings test `core/tests_workspaces.py:150-155` and the area map `:187-213`, E4).

`Report` is a `core.crud` Resource (url prefix `reports`): the list page is the Reports page (what is due and
overdue first, per site, kind and period with the deadline; then the notices to file; then the filed reports;
filters by site, kind and status), its due rows put in by `filter_list` (`core/crud.py:390-392`, `:485`); "Start"
on a due row opens the new-report form with `?kind=&site=&period=` as initial values; the detail page shows the
frozen or live figures, the differences and the export links; submit, correct and the exports are function views
under `/reports/<id>/…` (E4).

### 5.7 Roles

One area **Regulatory reports** (`reports.Report`) with the four actions: Read (the page, a report, its
exports), Create (start a due report, a notice, a correction), Edit (fill in a draft and **record it as
submitted**: a state change under Edit, as "Edit also reviews an entry" for knowledge, `config/access.py:21-22`
✔), Delete (discard a draft). Whether submitting needs a permission of its own is D-5 (a fifth matrix column,
E4).

### 5.8 Activity log

Started (created), edited (changed; the row lists as one change of the report), submitted (changed, built in the
source language: status, submitted at, by, channel, reference, content hash), correction started (created,
"Corrects …"), draft discarded (deleted through the delete plan). All under the report's entity type so its History
tab shows them; severity normal (critical is for going past a fish or food-safety warning,
`core/models.py:135-140` ✔).

### 5.9 Delete plan

A draft is soft-deleted (the delete plan) and can be restored in the admin; a restore re-checks the constraints,
so it is refused while another live original exists. A submitted report is never deleted, not even softly
(`delete_blockers()`: "It was submitted: start a correction instead", the check, the trigger). Its site,
facility, health event and escape are PROTECT: a site with filed reports is closed, not deleted (which also keeps
its departments from losing their site, OUR-06). A void of a record a report read is not stopped by anything
(voids are not deletes, `farm/stock/services.py:444-465`, E4): it is exactly what "no longer matches" shows.
Snapshots are read-only in the admin.

### 5.10 Tests (the house rule: every form field a column, with create, read, edit and delete through the pages against stored rows; README.md:43-44, :1722-1723, E4)

- A draft of each kind created, read, edited and discarded through the pages, each row list against its stored
  rows; the per-kind checks (fields of other kinds stay empty).
- Submit: the stored columns, the snapshot row with its hashes, the log entry carrying the content hash.
- Refusals: editing or deleting a submitted report through the form and directly in the database (the triggers);
  a row list of a submitted report (404, and the trigger); the user columns may still become NULL.
- Corrections: one live correction; only of a submitted report; the original shows superseded.
- The due list per kind (eligibility by production form, type, species and fish; the window; "not set up";
  overdue in Oslo; the ISO week 53 edge; a started draft stays listed) and "no longer matches" after a void, after a
  backdated entry and after a unit moved site.
- Every compute function against hand-folded figures (opening + in − out = closing per unit), the lice coverage
  and no-count rules, the planned-slaughter deadline with a fast starting before Thursday.
- Exports: the CSV guard on text and not on numbers; the JSON equal to the snapshot and valid against the
  official schemas.
- Permissions per action (`as_role`, as `farm/tests/test_harvest.py:738-770`); the heading and the area in the
  tests that list them; languages; the database viewer; the delete plan; restoring a draft, refused while another
  live original exists; `check_reports` clean after every test that writes.

### 5.11 Also

- **Languages**: the page in en, tr, nb; the authority's field names in the exports stay Norwegian as the authority
  writes them (text no person reads in their language is not translated, `docs/i18n.md`, E4); the glossary in
  `docs/i18n.md` gets the report terms.
- **Database viewer**: a section for the app (`config/database.py`), the app in the viewer test's list.
- **README**: a section "Production › Reports › Regulatory reports (`/reports/`)", the area in "Roles and users",
  the app in "Database viewer", "Layout of the code" and "Pages", the headings text (5.6). **Bug document**: a
  section "Regulatory reports" with REP-01 to REP-62 and the owner decisions.
- **Not ported**: the submission pipeline (Maskinporten, the API client, retries, the outbox, the e-mails, the
  scheduler and its advisory locks, auto-submit), the source's per-tab wizards, the threshold tables
  (`utils/thresholds.ts`, REP-33, REP-41; the health records hold the lice limit and the disease lists).

### 5.12 Order of work for Phase 2

0. Start once the health work is on main: the reports read its lice counts, treatments and health events, and
   every new farm migration comes after its `0018_health` (two 0018 leaves would conflict, E4).
1. Shared fixes the reports stand on: OUR-12, OUR-07, OUR-06, OUR-19, OUR-20, OUR-21, OUR-22, OUR-23, OUR-24,
   OUR-25, the one formula guard (5.5); the new Site fields `production_form` and `reports_from` on the Sites
   form, with their CRUD tests, README Sites section and translations.
2. The reads of 2.1 (`stock_on`, `movements`, `fed`), with their tests against the fold.
3. The app: models, due list, the compute functions (sea lice, smolt, biomass, planned slaughter, disease and
   welfare notices), submit, freeze, compare, correct, exports, page, roles, log, delete plan, admin, viewer,
   translations, README, bug document. The escape kind and the report's `escape` link come in a later migration of
   the app, with step 4.
4. With the owner's decisions: the cleaner-fish track and its report (D-1, D-2), the escape record (OUR-03), year
   class and depth (OUR-16, OUR-13), the delivery operation (D-10), the slaughter result (D-3), the § 44a notices
   (D-13).

### 5.13 As built (Phase 2)

What was built follows 5.1 to 5.12. Where it does not, or where a choice the design left open was made, here:

- **The reports** are `reports/`: `Report` (a draft until filed, then frozen with its `ReportSnapshot`, a database trigger
  on the report, its content and its answers), the computations of `reports/compute/` (sea lice, smolt, cleaner fish,
  monthly biomass, planned slaughter, a land site's yearly stock, a site taken into use or emptied, disease, welfare and
  escape notices), the filing and corrections of `reports/services.py`, the due list of `reports/due.py`, the exports of
  `reports/exports.py` (print, CSV, and the API's JSON validated in the tests against the OpenAPI subset kept with them)
  and `manage.py check_reports`.
- **The stock** gained two operations with their records, written by the one stock service: an **escape** (a count
  adjustment of the reason escape, with its cause, whether only suspected, the time found, the health status and the fish
  recaptured; one unit and one batch for each, since an operation belongs to one batch: an escape from several cages is
  recorded for each) and a **delivery** of live fish out of the company (who received them, the receiving site's number; the
  transport check runs). Cleaner fish share the salmon's cage on a sea site, are not in the unit's figures, are fed and culled
  by their own rules and are not harvested.
- **The health event's "Mattilsynet notified at" is gone** (D-4): the notice's filing is that fact, the health records read it
  through the registry of `farm/health/notices.py`, and reports migrations 0004 and 0005 turned the times already recorded
  into filed notices by whoever recorded them (and stop, naming the events, where no person is known). A notice given by
  telephone is recorded though its figures are not all ready, the missing ones kept in its log entry.
- **The sea temperature** is the mean of the week's samples at the site's depth points of 3 m, read through the water
  module's read API (OUR-13, the coordinator's sampling points); without one the report names the sample to take.
- **The answers no record holds** are rows of the report: a lice treatment's "given before the count" and "given together" (the
  records have dates, no times: a treatment that ended on the day of a count must be answered), resistance suspicions,
  sensitivity tests (with the other substance) and the biomass report's units of reduced capacity.
- **Not built:** the executed slaughter report and the slaughter result (D-3, OUR-18); the disease notice for a mortality
  left unexplained 14 days (5.2); the § 44a "continuous operation" refinements beyond the yearly stock and the two site
  notices; the mod-11 check of an organisation number; a dialog for a count correction.

## 6. Decisions

Decided 2026-11-03: the lead's recommendation, checked by the four experts, accepted (the owner may still
override one; the change is then recorded here). Taken as recommended unless the last column says otherwise.

| # | Question | Decision and why |
|---|---|---|
| D-1 | Cleaner fish share the salmon's cage: lift "one species per unit" (owner decision Q1) for cleaner-fish species, and let a feeding name its target (production or cleaner fish)? | **Yes**: a unit holds one species, except that on a sea site cleaner-fish batches may join its production species; a feeding record names its target and is split among that target's batches (3.2). Without it the cleaner-fish report cannot say which cage its fish are in (the owner's own example). § 47 forbids only fish of different holders in one unit ✔. |
| D-2 | Do cleaner fish count in a unit's density, capacity, feed rate and the site's biomass? | **No** for the unit's production figures and the biomass report: § 3 h applies to the use of cleaner fish only § 44 first paragraph a, b, f, g, h, not § 47 (biomass) nor § 44 c–d ✔; NFD's 2017 hearing note proposed "Rensefisk skal ikke inngå i beregningen av pålydende maksimalt tillatt biomasse" (a proposal, E1); and they are not counted in the unit's number of fish (Altinn, E1). Whether they count in a unit's density (§ 25) is unverified. They get their own line and the announced cleaner-fish tab. |
| D-3 | Slaughter reports: the farmer must notify a planned slaughter (restkontrollforskriften § 9a ✔), but the Altinn forms are filed by slaughterhouses (E1), and the executed report is the slaughterhouse's gutted kilos per quality class. Which does the farm file? | **Planned**: built, per slaughter facility and week, from the harvest plan, for the farm to file or hand to the slaughterhouse. **Executed**: not now (only if the farm runs its own slaughterhouse; then with the slaughter result, OUR-18). |
| D-4 | "Mattilsynet notified" for a disease: the health records keep `authority_notified_at` on the health event (health); a disease notice here records the same fact. Which is the one place? | **The notice** (when, how, reference, frozen content) for all three notices alike; the health event reads it through a provider, as the withdrawal registry does (`farm/handling/withdrawal.py:3-38`): with no provider registered it is "not checked", as `withdrawal.blocks` returns None; health's `needs_notification` and its "to notify" list are rewritten on it, and its own column goes. Done after the health work is on main, coordinated with its code. |
| D-5 | May whoever fills in a report also record it as submitted, or is submitting a permission of its own? | **Edit covers it** (no change to the role matrix). A separate permission adds a fifth column to every area (E4); worth it only if preparers and filers are different people. |
| D-6 | From when are a site's reports listed as due? | **A date per site** ("Reports from"): periods before it were filed elsewhere and must not show as overdue; a site that owes reports by its production form and fish but has no date is listed as "not set up for reports", never hidden (E4). |
| D-7 | Month-end biomass between weighings: the book (last measured average) or the feeding projection? | The **book** when the unit was weighed recently; else the **projection** when it has no blind days since the last measured point; else the book marked stale. The basis is filed either way (the last weighing, or the feed and FCR since it), as § 42 b asks. The book alone would understate a sea site's biomass for months where weighings are rare (E3). |
| D-8 | Which units of a settefisk site are in the smolt report, and what does a unit emptied in the month report? | Every unit holding fish of start-feeding stage or older (§ 58 ✔): batches stocked as eggs or larvae enter once they reach start-feeding, which needs a rule (a weight or an age, kept as data, then read from the fold); until a rule is set, every unit holding fish. A unit emptied in the month reports the count and average from just before it was emptied (the API wants an average above 0); whether its month-end stock is that count or 0 is **unverified**, to be confirmed with Mattilsynet. |
| D-9 | Count adjustments in the cleaner-fish report? | The month's adjustments are netted per unit, species and origin: a net loss (escape, unaccounted loss, a downward recount) is "kan ikke gjøres rede for" (the API's definition includes escaped fish, E1); a net gain is shown with its explanation and the person files with a warning (a negative value if Mattilsynet accepts one, unverified, or the form by hand with a remark): never unfileable (E3). |
| D-10 | Fish delivered alive out of the company (smolt sold): a new stock operation? | **Yes**, a live delivery out of the company with its destination (a customer, its site's lokalitetsnummer); it is the smolt report's "flyttet eksternt" and § 44 f. |
| D-11 | Which species make a site owe the lice report? | An explicit code set: **SAL, TRS, TRR** (salmon, trout, rainbow trout), Mattilsynet's own "Laks, Ørret, Regnbueørret" in its API (E1); the family Salmonidae is too wide (char, whitefish), and Arctic char in the sea is unverified. |
| D-12 | Fiskeridirektoratet's monthly biomass form: its current channel and fields are unverified (the old Altinn page answers 404; an API from Q2 2026 is reported only by the trade press). | Built as § 44 reads (print and CSV), marked on the page and the export "confirm the form with Fiskeridirektoratet". |
| D-13 | A site's production form (settefisk, matfisk, stamfisk), which decides its reports (5.2): and the § 44a notices of matfisk and stamfisk sites on land or in fresh water (taken into use, emptied, yearly stock by 7 January), build them? | The production form is needed (a land grow-out site is not a hatchery, E1, E3). The § 44a notices: **yes** (the MVP goes to a university that may run a land site), as a yearly report and two event notices. |
| D-14 | What is a batch's year class (årsklasse): the hatch year, or the year it went to sea, and how do spring and autumn stockings (§ 44 second paragraph) show? | Entered per batch, **no default**; the definition (hatch year or sea year) and the spring/autumn rule are **unverified**, noted on the field. |
| D-15 | How our loss reasons map to Fiskeridirektoratet's causes (Dødfisk, Utkast fra slakteri, Rømming, Annet, Tellefeil) | Mortality and culls → Dødfisk; escape → Rømming; count corrections → Tellefeil; unaccounted loss → Annet; Utkast from the slaughter result only. As proposed, **unverified** until the form is confirmed (D-12). |
