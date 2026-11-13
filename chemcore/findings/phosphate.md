# The optional phosphate (PO₄-P): what it does, how it was checked (2026-11-13)

The independent check of 2026-11-09 (`F:\dev\balik-notes\verify-science\VERIFY.md`, hypothesis 12a) ranked this first by
its effect on live fish: phosphate is part of the alkalinity a titration measures, the core did not know it, and in a
RAS (3 to 10 mg/L PO₄-P and more) the CO₂ after a base dose or a degassing came out 57 to 71 % too low. The owner approved
an optional input on 2026-11-10.

## What was built

- **An optional input, and nothing moves without it.** `Ions::phosphate_p_mg_l` (mg/L as P; None or 0: not given).
  Without it no phosphate constant is computed and no line of the chemistry takes another path: golden v1 and the
  three blocks of golden v3 recorded before keep their bytes (waters `72c3ed35…`, analyses `d08a9fae…`, scales
  `f46bdce5…`); `core/tests/phosphate.rs` holds None and 0 to the water as it was, every field and every pH line bit
  for bit. A fourth block, `phosphate`, records 180 waters with 1 and 10 mg/L. Formula 1 does not read it.
- **Its alkalinity, as the definition says.** Total alkalinity (Dickson 1981, as Dickson, Sabine & Christian (eds.)
  2007, *Guide to Best Practices for Ocean CO₂ Measurements*, ch. 2, section 4.2, give it; read) counts
  [HPO₄²⁻] + 2 [PO₄³⁻] − [H₃PO₄]. With PT = PO₄-P ÷ 30.973762 mg/mmol that is
  PT (K1 K2 h + 2 K1 K2 K3 − h³) / (h³ + K1 h² + K1 K2 h + K1 K2 K3) (the Guide's ch. 2, eq. 43 to 45), added to the
  intercept of every pH line (`Equilibria::isoline`, `phosphate_alkalinity`). So the DIC and the water's own CO₂ of a pH
  and an alkalinity are lower by it, the pH a DIC and an alkalinity give meets its buffer (`ph_at`: every dose, recipe
  and simulator step), and a pH and an alkalinity whose phosphate alone is that much alkalinity cannot be: refused by
  the one rule, with the phosphate in the reason.
- **The constants.** Millero (1995), a composite of Kester & Pytkowicz (1967), Dickson & Riley (1979) and Johansson &
  Wedborg (1979), read in the 2007 Guide, ch. 5, eq. 49, 52, 55, which prints them for the total scale with 0.015
  taken from each constant term (its footnote 5). The core holds Millero's own, on his seawater scale (the Guide's plus
  0.015: 115.540, 172.1033, −18.126), and converts them as its other constants: on the sea path over
  [H⁺]SWS / [H⁺]free; on the fresh path the S 0 values (pK 2.149, 7.200, 12.345 at 25 °C) with Davies activity
  coefficients (K1P° / γ₁², K2P° / γ₂, K3P° γ₂ / (γ₁ γ₃)); blended in the band from 1 to 5 ‰.
- **A judged CO₂ never falls because a phosphate was given.** Every CO₂ judgement (the value judged, its status and
  border, the safe zone, a simulator step, the chart's CO₂ curve) takes the largest of three: the limits' basis, the
  water's own value without the phosphate, and its own with it (`Equilibria::co2_judged`, `ph_where_co2`,
  `alkalinity_where_co2`). At a fish water's pH the first two are the larger, so the judged CO₂ of a measured water is
  the same number with and without the phosphate, to the last bit (over 700 possible waters in the test). The water's own CO₂ with
  the phosphate counted is said beside it. What changes for safety is the other side: after a dose the pH is now the
  phosphate-buffered one, and the judged CO₂ there is the larger value at that true pH.
- **The chart.** With a phosphate the judged and the own CO₂ are not in one ratio, so the chart's CO₂ curve is drawn as
  the judged border itself, row by row of the alkalinity (`geometry::co2_curve_judged`); without one the curve is
  drawn as before.
- **The NH₃ does not read it.**
- **Application.** A water parameter like the others (`phosphate_p_mg_l`, "Phosphate (mg/L PO₄ as P)", 0 to 100,
  two decimals): on the record form and a round, in the latest values and the history, a limit can be set on it per
  species (reference data), its freshness is reference data too (seeded 7 days), a sensor channel can measure it. The
  calculator has the field; a unit's chart, the replay and the hourly trail take the unit's fresh value. The words
  beside a result say it: "…; phosphate 10.00 mg/L as P counted in the alkalinity" and "CO₂ judged without the
  phosphate: … With the phosphate counted, the water's own CO₂ is … mg/L."

## The independent comparison (numbers only; no code copied)

PyCO2SYS 1.8.3.4 with `total_phosphate`, the same free pH given (opt_pH_scale 3), opt_k_carbonic 13, opt_k_bisulfate 1,
opt_k_fluoride 1, opt_total_borate 1. Grid: S 0, 5, 15, 35 by 5, 10, 15, 25 °C by alkalinity 1, 2, 4 meq/L by pH (NBS)
6.5, 7.0, 7.5, 8.0 by PO₄-P 1, 3, 10, 30 mg/L: 768 waters, 763 of them possible (571 at S 5 to 35, 192 at S 0). Fresh
water is compared with every activity 1 (nothing measured but the phosphate): the libraries know no activity
coefficients. Scripts and outputs: `F:\dev\balik-notes\chem-v3\verify\` (`phosphate_ours.py`, `phosphate_pyco2.py`,
`phosphate_seacarb.R`, `out/phosphate_*`). Core `53a4a691f35e65c5`.

| Quantity | S 5 to 35 (571 waters): median, largest difference, where | S 0 (192 waters): largest |
|---|---|---|
| K1P, K2P, K3P on the free scale | ≤ 3.2e-15; 3.1e-14 (K2P, 15 °C, S 15) | 2.8e-14 |
| The phosphate's alkalinity | 2.2e-16; 1.9e-14 (15 °C, S 5) | 2.4e-14 |
| DIC and CO₂ of an alkalinity and a pH | 7.0e-6; 1.4e-3 (25 °C, S 35, 1 meq/L, pH 7.5, 30 mg/L) | 8.3e-14 |
| pH after 0.5 meq/L of base at the same DIC | −5.2e-5 to −2.9e-6 pH | ±2.5e-11 pH |
| CO₂ after that base | 3.3e-5; 1.4e-4 (15 °C, S 35) | 7.8e-11 |
| pH after 0.3 mmol/L of DIC stripped | −1.0e-4 to −3.2e-6 pH | ±2.5e-11 pH |
| CO₂ after that stripping | 3.7e-5; 2.3e-4 (25 °C, S 35) | 7.9e-11 |

seacarb 3.4.2, the three constants on 12 cells (S 5, 15, 35 by four temperatures): its seawater-scale values times
`kconv(kf = "dg")`'s factor are within 4.6e-7 of ours (its fluoride total, as the check of 2026-11-09 found); its own
free-scale values (default kf, Perez & Fraga) are 3.5e-3 away, the difference of that KF, not of the phosphoric fits.

Reading it: in sea water the constants and the phosphate's alkalinity agree to the last digits; the 7e-6 median and
1.4e-3 largest difference of the DIC and CO₂ are the differences the check of 2026-11-09 already measured without any
phosphate (the per-litre bookkeeping with per-kg constants, largest next to the alkalinity floor, which 30 mg/L of
phosphate brings close at 1 meq/L). In fresh water with every activity 1 everything agrees to 1e-10 or better.

What leaving the phosphate out did, on the same grid against PyCO2SYS: the CO₂ of an alkalinity and a pH too high by
a median of 7.6 % in sea water and 3.7 % in fresh water (the safe side; without bound where the phosphate is nearly
all of the alkalinity); after a base dose or a stripping the CO₂ too low, by up to 100 % (the unsafe side).

## Design choices and why (the conservative one each time)

| Point | Choice | Why |
|---|---|---|
| What judges CO₂ when a phosphate is given | The largest of the limits' basis, the own value without the phosphate and the own value with it | A mistyped phosphate (PO₄ entered as P is 3.07 times too much), a total-P reading, or an alkalinity kit that did not count the phosphate would otherwise lower a judged CO₂. The limits' basis (Standard Methods 4500-CO₂ D: all the alkalinity carbonate's) counts none either. The true value is shown beside it. |
| Fresh-water constants | The S 0 values with Davies coefficients, as K1, K2 and the others | One rule for every constant of the fresh path. |
| Ionic strength | The phosphate is not added to it | A conductivity already counts it; 10 mg/L as P is about 0.0005 mol/L. |
| Range | 0 to 100 mg/L as P, two decimals | A RAS holds 3 to 10 and more; the range is the typing-slip guard of every parameter, not a limit. |
| Limits and freshness | Reference data (a limit per species can be set; freshness seeded 7 days) | A farm sets these. |
| Formula version | Still 3 | No result of a water without a phosphate moves; a result with one says the phosphate. |

## Weak points

- Millero (1995) and the three papers behind its phosphate fits were not read; the equations are the 2007 Guide's with
  its 0.015 put back, confirmed by two libraries' numbers.
- That the alkalinity a farm measures counts the phosphate as Dickson's definition does (a titration to about pH 4.5
  does) is assumed; a kit that does not would make the own CO₂ with phosphate too low. The judged CO₂ is unaffected.
- The fresh path with Davies coefficients (a real fresh water, ionic strength above 0) has no independent reference:
  only the ideal water was compared. K3P's coefficient takes a trivalent ion's Davies γ, at the edge of what Davies
  is used for; PO₄³⁻ is under 0.1 % of the phosphate below pH 9.
- Silicate, ammonia and sulfide alkalinity are still not counted (small below pH 8.5; silicate matters in some ground
  waters).
- The chart's judged CO₂ curve bends back near an alkalinity of 0 (a pH under 4.7), where no fish water is; it is
  drawn as it is.
- The phosphate lowers the DIC shown and the recipes' amounts; nothing compares a recipe with a jar test.
