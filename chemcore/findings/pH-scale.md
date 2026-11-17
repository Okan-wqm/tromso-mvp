# The scale of a pH: the selector, its conversion and its check (2026-11-12)

The K_NH4 panel (2026-11-10, decision row 6) found the largest single hazard of the ammonia chemistry not in a constant
but in the pH: every pH the application takes is on the NBS scale, and a seawater pH is often measured on another (a
sensor or an indicator calibrated with TRIS reads on the total scale). The panel decided the label and proposed "an
optional scale field (NBS default; total; SWS; free) converted with the core's own factors"; the owner decided on
2026-11-11 that it is built.

## What was built

- **One scale everywhere.** Every pH stored, shown, judged and worked out from stays on the NBS scale. The scale is
  chosen where a pH is typed: Record water sample, a water round (one scale for the round's pHs), the calculator. A pH
  on another scale is put on the NBS scale by the core at that door, before anything reads it, so no page, limit,
  alarm, chart or report can hold two scales.
- **NBS is the default and changes nothing.** `scale::ph_nbs(eq, ph, PhScale::Nbs)` is the pH itself, bit for bit
  (`core/tests/scale.rs`: 324 waters of both formulas); no function a caller had takes a new argument; golden v1 and
  the two blocks of golden v3 recorded before keep their bytes (waters `72c3ed35…eb555`, analyses `d08a9fae…2074d`). A
  third block, `scales`, records the conversions (24 sea waters, five pHs, four scales).
- **The conversion** (`chemcore/core/src/scale.rs`):
  pH free = pH total + log₁₀(1 + ST/KS); pH free = pH SWS + log₁₀(1 + ST/KS + FT/KF); pH NBS = pH free − offset,
  the offset the water's own (formula 3's free − NBS). Source of the first: Dickson, Sabine & Christian (eds.) 2007,
  *Guide to Best Practices for Ocean CO₂ Measurements*, ch. 2, eq. 15, and SOP 6a, eq. 1, read. The seawater scale
  (hydrogen fluoride counted too) is named in the Guide's ch. 5, footnote 5; its defining papers (Dickson & Riley 1979;
  Zeebe & Wolf-Gladrow 2001, ch. 1.3) were not read here. ST, FT, KS, KF are the core's as always (Morris & Riley
  1966; Riley 1965; Dickson 1990; Dickson & Riley 1979).
- **Sea water only.** A scale other than NBS is taken from 5 ‰ where the water's constants are the sea path's alone
  (`scale::converts`): KS holds from S 5, TRIS buffers are made for S 20 to 40, and below 5 ‰ or in fresh water salted
  with NaCl the offset depends on the ions measured. Elsewhere it is refused with the reason (the forms, the write path,
  and the core itself: `ChemError::SeawaterScale`, Python `SeawaterScaleError`), never converted on an assumption.
  Fresh water with salt added is refused at EVERY salinity, by its origin: past the Davies limit (about 28.4 ‰ as NaCl)
  the core works its constants out by the sea path, which does not give it sea water's sulfate and fluoride (the
  independent review of 2026-11-16, R4: until then S 29, 30 and 35 salt-added were converted, 12 °C, S 30, total 8.00
  to 8.1372).
- **The sample's own temperature and salinity.** A sample or a round's row converts with the temperature and salinity
  typed in the same sample; without them it is refused, nothing is looked up.
- **What was measured is kept.** `water_measurements.ph` holds the NBS pH at the column's two decimals;
  `ph_scale`, `ph_as_measured` and `ph_converted_formula` hold the scale, the value as measured and the formula
  version, a database check holding them together (`chk_water_measurements_ph_scale`). The reading says it wherever a
  value's title is shown: "Measured 7.95 on the total scale; put on the NBS scale by formula 3 with the sample's 12.0 °C
  and 34.0 ‰." The activity log holds all three. The calculator converts without rounding and says "pH 7.95 on the
  total scale is 8.08 on the NBS scale"; its target pH and pH limits are NBS; values taken from a unit are NBS.
- **Sensors are not converted.** The ingest stores what a device sends, and the conversion needs the temperature and
  salinity of the same moment. A pH channel is NBS, and the channel form says that a total-scale sensor is not
  converted and what that costs.

## The independent comparison (numbers only; no code copied)

Grid: 0 to 40 °C every 5 °C by S 5 to 40 every 5 (72 cells), a pH of 8 given on the total scale (the conversion does
not depend on the pH). Scripts and outputs: `F:\dev\balik-notes\chem-v3\verify\` (`scale_ours.py`, `scale_pyco2.py`,
`scale_seacarb.R`, `out/scale_*.csv`). Core `c545a1cb87d1c7b0`.

| Converted value | Reference | Largest difference | Where |
|---|---|---|---|
| free pH of a total-scale pH | PyCO2SYS 1.8.3.4 (opt_k_bisulfate 1, opt_k_fluoride 1) | 8.9e-15 pH | 30 °C, S 40 |
| seawater-scale pH of a total-scale pH | PyCO2SYS 1.8.3.4 | 1.8e-15 pH | 40 °C, S 35 |
| free pH of a total-scale pH | seacarb 3.4.2 (`kconv`, ks = "d") | 1.8e-15 pH | 0 °C, S 25 |
| seawater-scale pH of a total-scale pH | seacarb 3.4.2, kf = "dg" (Dickson & Riley, the core's) | 2.4e-7 pH | 40 °C, S 40 |
| the same | seacarb 3.4.2, its default kf (Perez & Fraga inside 9–33 °C, S 10–40) | 2.0e-3 pH | 10 °C, S 40 |
| NBS pH of a total-scale pH | PyCO2SYS 1.8.3.4 (its fH: Takahashi et al. 1982) | −0.069 to +0.055 pH | 40 °C, S 5; 0 °C, S 40 |
| the same, within 0–30 °C and S 5–35 | PyCO2SYS 1.8.3.4 | −0.058 to +0.048 pH | 30 °C, S 5; 0 °C, S 35 |

Reading it:

- The published definitions (total, seawater, free) are reproduced to the last digits. The 2.4e-7 against seacarb is
  its fluoride total (atomic weight 18.9984 against the core's 18.998, as the check of 2026-11-09 found); the 2.0e-3 is
  another KF, not ours.
- The last two rows are **not** a property of the selector: they are the core's NBS conversion itself, an in-house
  Davies-type activity coefficient (README, the ionic strength and the NBS pH; the check of 2026-11-09, claim 7: ±0.08
  pH against Takahashi's fH from S 5, which is itself wrong at S ≤ 5). Every NBS pH a meter reads carries the same.
- That uncertainty does not reach what the water's own constants work out from a converted pH: the free [H⁺] they take,
  10^−(pH NBS + offset), is the given pH's own by the published definition, the offset cancelling (tested to 1e-12). So
  a total-scale pH said as total gives a more certain activity-corrected NH₃ and CO₂ than an NBS reading. It does reach
  the limits' basis, which takes the NBS pH as measured; the judged value is the larger of the two, as always.

## The hazard it closes, by the core's own factors

Over 5 to 35 ‰ and 0 to 30 °C a total-scale pH is 0.104 to 0.141 below the NBS pH of the same water (seawater scale
0.106 to 0.150; free 0.011 to 0.102). A total-scale pH of 8 typed as NBS makes the judged NH₃ 20.3 to 26.9 % too low
(`F:\dev\balik-notes\chem-v3\measure\item4-plus.out`; the panel's 5 to 28 % is the same by its two measures).

## Design choices and why (the conservative one each time)

| Point the panel left open | Choice | Why |
|---|---|---|
| Where the scale lives | At the door: converted when written, the NBS pH stored, what was measured kept beside it | Every reader (latest values, limits, alarms, charts, monitoring cards, reports, exports) reads one column on one scale; a per-value scale would have every reader convert, and one that forgot would mix scales silently. The price: a stored value that was worked out; so the scale, the measured value and the formula version are stored with it and a database check holds them together. |
| Which waters | Sea water of 5 ‰ or more, the sea path's constants alone, never salt-added water (at any salinity) | The seawater scales are defined in sea water; below 5 ‰ and in NaCl-salted water the conversion would rest on the ions measured and on KS outside its range. Refused with the reason. |
| What the conversion takes | The same sample's temperature and salinity | A looked-up value could be another water's; a missing one is asked for. |
| Precision | The pH column's two decimals (half-even), so up to ±0.005 pH of rounding (about 1.2 % of NH₃); the calculator does not round | The column's precision and its checks were not widened for this. |
| Sensors | Not converted; said on the channel form | The ingest cannot convert (no temperature and salinity of the same moment), and a conversion on read would put a second scale into every reader of live values. A TRIS-calibrated sensor is exactly the case the selector is for: open, for the owner. |
| The limits' basis | Unchanged: it takes the converted NBS pH as it takes a measured one | The judged value stays the larger of the basis and the corrected value. |

## Weak points

- The seawater scale's defining source was not read first-hand; it is confirmed by two libraries' numbers only.
- The NBS leg is the in-house conversion (above); the farms' real probes' NBS − free offsets are not measured.
- A converted pH is rounded to two decimals when stored.
- Sensors on another scale are not converted.
- A sample's pH typed on another scale in fresh or brackish water (below 5 ‰) is refused, not converted: a free-scale
  pH there would need the water's ions.
- Samples stored before a later formula changes the NBS conversion keep the NBS pH of the formula named in
  `ph_converted_formula`; they are not converted again by themselves.
