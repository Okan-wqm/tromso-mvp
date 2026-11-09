//! Dosing: the reagents that move a water on the chart, the recipes of two of them from the water to a target, the
//! chart's dosing layer and the simulator (farm/water/dosing.py at golden v1, from the source's reagents.ts with its
//! defects corrected: WQ-40 a pair split by Cramer's rule, WQ-41 nothing clamped, WQ-45 stripping flagged below the
//! air's CO₂). Molar masses from the IUPAC standard atomic weights of 2007 (B1-04).
use alloc::vec;
use alloc::vec::Vec;

use crate::chemistry::{self as c, Equilibria};
use crate::num::{ChemError, div};

/// Standard atomic weights (IUPAC 2007), g/mol.
const H: f64 = 1.00794;
const C: f64 = 12.0107;
const O: f64 = 15.9994;
const NA: f64 = 22.98976928;
const CA: f64 = 40.078;
const CL: f64 = 35.453;

/// A dose under this many grams is left out of a recipe (the source's).
pub const LEFT_OUT_G: f64 = 0.001;
/// Closer than this (mmol/L and meq/L) the water is at its target (the source's).
pub const AT_TARGET: f64 = 0.001;
/// At most this many recipes.
pub const MAX_RECIPES: usize = 6;
/// The source's direction lines: 8 mmol/L along DIC (or meq/L along alkalinity).
pub const LINE_LENGTH: f64 = 8.0;

/// A reagent: the DIC (mmol) and alkalinity (meq) one mmol of it adds.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Reagent {
    pub key: &'static str,
    pub molar_mass: f64,
    pub dic: f64,
    pub alkalinity: f64,
}

fn mass(atoms: &[(f64, f64)]) -> f64 {
    // CPython 3.12's sum() of floats, which dosing.py's molar_mass used: Neumaier's compensated summation from 0
    // (Objects/bltinmodule.c), so NaOH is 39.997109280000004 g/mol as golden v1 recorded, not the naive 39.99710928.
    let (mut total, mut compensation) = (0.0_f64, 0.0_f64);
    for &(weight, count) in atoms {
        let term = weight * count;
        let next = total + term;
        if libm::fabs(total) >= libm::fabs(term) {
            compensation += (total - next) + term;
        } else {
            compensation += (term - next) + total;
        }
        total = next;
    }
    if compensation != 0.0 && compensation.is_finite() {
        total + compensation
    } else {
        total
    }
}

/// The source's reagents, in its order, which is also the order of practicality recipes are ranked by.
pub fn reagents() -> [Reagent; 9] {
    [
        Reagent {
            key: "nahco3",
            molar_mass: mass(&[(NA, 1.0), (H, 1.0), (C, 1.0), (O, 3.0)]),
            dic: 1.0,
            alkalinity: 1.0,
        },
        Reagent {
            key: "na2co3",
            molar_mass: mass(&[(NA, 2.0), (C, 1.0), (O, 3.0)]),
            dic: 1.0,
            alkalinity: 2.0,
        },
        Reagent {
            key: "naoh",
            molar_mass: mass(&[(NA, 1.0), (O, 1.0), (H, 1.0)]),
            dic: 0.0,
            alkalinity: 1.0,
        },
        Reagent {
            key: "caco3",
            molar_mass: mass(&[(CA, 1.0), (C, 1.0), (O, 3.0)]),
            dic: 1.0,
            alkalinity: 2.0,
        },
        Reagent {
            key: "caoh2",
            molar_mass: mass(&[(CA, 1.0), (O, 2.0), (H, 2.0)]),
            dic: 0.0,
            alkalinity: 2.0,
        },
        Reagent {
            key: "cao",
            molar_mass: mass(&[(CA, 1.0), (O, 1.0)]),
            dic: 0.0,
            alkalinity: 2.0,
        },
        Reagent {
            key: "co2",
            molar_mass: mass(&[(C, 1.0), (O, 2.0)]),
            dic: 1.0,
            alkalinity: 0.0,
        },
        Reagent {
            key: "degas",
            molar_mass: mass(&[(C, 1.0), (O, 2.0)]),
            dic: -1.0,
            alkalinity: 0.0,
        },
        Reagent {
            key: "hcl",
            molar_mass: mass(&[(H, 1.0), (CL, 1.0)]),
            dic: 0.0,
            alkalinity: -1.0,
        },
    ]
}

/// The reagent of a key.
pub fn by_key(key: &str) -> Option<Reagent> {
    reagents().into_iter().find(|reagent| reagent.key == key)
}

fn index_of(reagent: &Reagent) -> usize {
    reagents()
        .iter()
        .position(|each| each.key == reagent.key)
        .unwrap_or(usize::MAX)
}

impl Reagent {
    /// Its direction on the chart, from 0 to 2π (the source's `radians`): atan2 taken modulo 2π as Python's `%`.
    pub fn angle(&self) -> f64 {
        let turn = 2.0 * core::f64::consts::PI;
        let angle = libm::atan2(self.alkalinity, self.dic);
        let rest = libm::fmod(angle, turn);
        if rest != 0.0 && (rest < 0.0) != (turn < 0.0) {
            rest + turn
        } else {
            rest
        }
    }

    /// Its direction scaled to one unit along DIC, or along alkalinity when it leaves the DIC alone.
    pub fn unit_move(&self) -> Result<(f64, f64), ChemError> {
        let scale = if self.dic != 0.0 {
            libm::fabs(self.dic)
        } else {
            libm::fabs(self.alkalinity)
        };
        Ok((div(self.dic, scale)?, div(self.alkalinity, scale)?))
    }
}

/// How much of each of two reagents takes a water from `start` to `end`: (lower, a, higher, b), a and b in mmol/L,
/// `lower` the reagent of the smaller angle; None when the move is not a sum of their directions with amounts ≥ 0.
pub fn split(
    start: (f64, f64),
    end: (f64, f64),
    first: Reagent,
    second: Reagent,
) -> Option<(Reagent, f64, Reagent, f64)> {
    // sorted() is stable: equal angles keep the order given
    let (lower, higher) = if second.angle() < first.angle() {
        (second, first)
    } else {
        (first, second)
    };
    let (across, up) = (end.0 - start.0, end.1 - start.1);
    if libm::fabs(across) < 1e-6 && libm::fabs(up) < 1e-6 {
        return None;
    }
    let determinant = lower.dic * higher.alkalinity - lower.alkalinity * higher.dic;
    if libm::fabs(determinant) < 1e-12 {
        return None;
    }
    let a = (across * higher.alkalinity - up * higher.dic) / determinant;
    let b = (lower.dic * up - lower.alkalinity * across) / determinant;
    if a < -1e-9 || b < -1e-9 {
        return None;
    }
    Some((
        lower,
        if a >= 0.0 { a } else { 0.0 },
        higher,
        if b >= 0.0 { b } else { 0.0 },
    ))
}

/// One reagent of a recipe.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Dose {
    pub reagent: Reagent,
    /// mmol of reagent per litre
    pub concentration: f64,
    /// in the volume; None without a volume
    pub grams: Option<f64>,
    pub delta_dic: f64,
    pub delta_alkalinity: f64,
}

fn dose(reagent: Reagent, concentration: f64, volume: Option<f64>) -> Dose {
    Dose {
        reagent,
        concentration,
        grams: volume.map(|volume| concentration * reagent.molar_mass * volume),
        delta_dic: concentration * reagent.dic,
        delta_alkalinity: concentration * reagent.alkalinity,
    }
}

/// A recipe of one or two doses.
#[derive(Clone, Debug, PartialEq)]
pub struct Recipe {
    pub doses: Vec<Dose>,
    /// (DIC, alkalinity) after the first reagent
    pub waypoint: (f64, f64),
    /// a stripping step would take the CO₂ below the air's whichever dose goes first
    pub below_air: bool,
}

impl Recipe {
    /// One reagent adds alkalinity and the other takes it away: an overshoot and a correction.
    pub fn counter_productive(&self) -> bool {
        self.doses.iter().any(|dose| dose.delta_alkalinity > 1e-9)
            && self.doses.iter().any(|dose| dose.delta_alkalinity < -1e-9)
    }

    pub fn priority(&self) -> usize {
        self.doses.iter().map(|dose| index_of(&dose.reagent)).sum()
    }
}

/// The air's CO₂ a water cannot be stripped below: the equilibria of the water and the air's CO₂ (mg/L).
#[derive(Clone, Copy, Debug)]
pub struct Air<'a> {
    pub equilibria: &'a Equilibria,
    pub co2_mg_l: f64,
}

impl Air<'_> {
    /// Whether a water's CO₂ is below the air's (or no pH gives the water).
    pub fn below(&self, dic: f64, alkalinity: f64) -> Result<bool, ChemError> {
        Ok(match self.equilibria.ph_at(dic, alkalinity)? {
            None => true,
            Some(ph) => self.equilibria.co2(dic, ph)? * c::MG_CO2_PER_MMOL < self.co2_mg_l,
        })
    }
}

/// The water is at its target: closer than AT_TARGET in DIC and in alkalinity.
pub fn at_target(start: (f64, f64), end: (f64, f64)) -> bool {
    libm::fabs(end.0 - start.0) < AT_TARGET && libm::fabs(end.1 - start.1) < AT_TARGET
}

/// The recipe of two reagents from `start` to `end` (volume in m³; None gives the doses per litre only).
pub fn recipe(
    start: (f64, f64),
    end: (f64, f64),
    first: Reagent,
    second: Reagent,
    volume: Option<f64>,
    air: Option<&Air<'_>>,
) -> Result<Option<Recipe>, ChemError> {
    let Some((lower, a, higher, b)) = split(start, end, first, second) else {
        return Ok(None);
    };
    let waypoint = (start.0 + a * lower.dic, start.1 + a * lower.alkalinity);
    let weight = volume.unwrap_or(1.0);
    let doses: Vec<Dose> = [(lower, a), (higher, b)]
        .into_iter()
        .filter(|(reagent, amount)| amount * reagent.molar_mass * weight > LEFT_OUT_G)
        .map(|(reagent, amount)| dose(reagent, amount, volume))
        .collect();
    if doses.is_empty() {
        return Ok(None);
    }
    let below_air = match air {
        Some(air) if doses.iter().any(|dose| dose.reagent.key == "degas") => {
            let stripped = if lower.key == "degas" { a } else { b };
            air.below(start.0 - stripped, start.1)? && air.below(end.0, end.1)?
        }
        _ => false,
    };
    Ok(Some(Recipe {
        doses,
        waypoint,
        below_air,
    }))
}

/// The recipes from the water to the target with the chosen reagents, practical ones first, at most MAX_RECIPES.
pub fn recipes(
    start: (f64, f64),
    end: (f64, f64),
    chosen: &[&str],
    volume: Option<f64>,
    air: Option<&Air<'_>>,
) -> Result<Vec<Recipe>, ChemError> {
    if at_target(start, end) {
        return Ok(Vec::new());
    }
    let picked: Vec<Reagent> = reagents()
        .into_iter()
        .filter(|reagent| chosen.contains(&reagent.key))
        .collect();
    let mut found: Vec<Recipe> = Vec::new();
    let mut seen: Vec<Vec<&'static str>> = Vec::new();
    for (index, &first) in picked.iter().enumerate() {
        for &second in picked.iter().skip(index + 1) {
            let Some(made) = recipe(start, end, first, second, volume, air)? else {
                continue;
            };
            let mut same: Vec<&'static str> = made.doses.iter().map(|dose| dose.reagent.key).collect();
            same.sort_unstable();
            if seen.contains(&same) {
                continue;
            }
            seen.push(same);
            found.push(made);
        }
    }
    let productive: Vec<Recipe> = found
        .iter()
        .filter(|made| !made.counter_productive())
        .cloned()
        .collect();
    let mut ranked = if productive.is_empty() { found } else { productive };
    ranked.sort_by_key(Recipe::priority);
    ranked.truncate(MAX_RECIPES);
    Ok(ranked)
}

/// The chart's dosing layer: one reagent, its line; two, both lines, the wedge and, when they reach the target, the
/// path through the waypoint. `note` a code when there is a word to say.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Visual {
    pub lines: Vec<(&'static str, Vec<(f64, f64)>)>,
    pub wedge: Vec<(f64, f64)>,
    pub path: Vec<(f64, f64)>,
    pub waypoint: Option<(f64, f64)>,
    pub note: Option<&'static str>,
}

/// A reagent's direction line from a water, LINE_LENGTH long.
pub fn direction_line(start: (f64, f64), reagent: &Reagent) -> Result<Vec<(f64, f64)>, ChemError> {
    let (across, up) = reagent.unit_move()?;
    Ok(vec![
        start,
        (start.0 + LINE_LENGTH * across, start.1 + LINE_LENGTH * up),
    ])
}

/// The dosing layer for the chosen reagents (keys, in the order chosen); `end` None without a target.
pub fn visual(start: (f64, f64), end: Option<(f64, f64)>, chosen: &[&str]) -> Result<Visual, ChemError> {
    let picked: Vec<Reagent> = chosen.iter().filter_map(|key| by_key(key)).collect();
    let mut shown = Visual::default();
    match picked.as_slice() {
        [one] => shown.lines = vec![(one.key, direction_line(start, one)?)],
        [first, second] => {
            let first_line = direction_line(start, first)?;
            let second_line = direction_line(start, second)?;
            shown.wedge = vec![
                start,
                first_line.get(1).copied().unwrap_or(start),
                second_line.get(1).copied().unwrap_or(start),
            ];
            shown.lines = vec![(first.key, first_line), (second.key, second_line)];
            match end.and_then(|end| split(start, end, *first, *second).map(|found| (end, found))) {
                Some((end, (lower, a, _higher, _b))) => {
                    let waypoint = (start.0 + a * lower.dic, start.1 + a * lower.alkalinity);
                    shown.waypoint = Some(waypoint);
                    shown.path = vec![start, waypoint, end];
                }
                None => {
                    if end.is_some() {
                        shown.note = Some("dosing.cannot_reach");
                    }
                }
            }
        }
        _ => shown.note = Some("dosing.tick_one_or_two"),
    }
    Ok(shown)
}

/// The water after a dose (the first step: before any); `ph` None: no water has this DIC and alkalinity.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Step {
    pub reagent: Option<&'static str>,
    pub grams: f64,
    pub dic: f64,
    pub alkalinity: f64,
    pub ph: Option<f64>,
    pub co2_mg_l: Option<f64>,
    pub below_air: bool,
}

/// The water after each amount (grams by reagent key) added in turn to `volume` m³, in the reagents' order, from
/// `start` at `ph`; a stripping step that takes the CO₂ below `air_co2_mg_l` is flagged; [] without an amount.
pub fn simulate(
    eq: &Equilibria,
    start: (f64, f64),
    ph: f64,
    amounts: &[(&str, f64)],
    volume: f64,
    air_co2_mg_l: Option<f64>,
) -> Result<Vec<Step>, ChemError> {
    let doses: Vec<(Reagent, f64)> = reagents()
        .into_iter()
        .filter_map(|reagent| {
            amounts
                .iter()
                .find(|(key, _grams)| *key == reagent.key)
                .map(|&(_key, grams)| (reagent, grams))
        })
        .filter(|&(_reagent, grams)| grams != 0.0)
        .collect();
    if doses.is_empty() {
        return Ok(Vec::new());
    }
    let (mut dic, mut alkalinity) = start;
    let mut steps = vec![Step {
        reagent: None,
        grams: 0.0,
        dic,
        alkalinity,
        ph: Some(ph),
        co2_mg_l: Some(eq.co2_judged(alkalinity, ph, eq.co2(dic, ph)?)?.0 * c::MG_CO2_PER_MMOL),
        below_air: false,
    }];
    for (reagent, grams) in doses {
        let concentration = div(div(grams, reagent.molar_mass)?, volume)?;
        dic += concentration * reagent.dic;
        alkalinity += concentration * reagent.alkalinity;
        let Some(reached) = eq.ph_at(dic, alkalinity)? else {
            steps.push(Step {
                reagent: Some(reagent.key),
                grams,
                dic,
                alkalinity,
                ph: None,
                co2_mg_l: None,
                below_air: false,
            });
            break;
        };
        // The air's CO₂ is a true concentration (Weiss 1974): stripping is held to it by the water's own CO₂; the step shows
        // the judged CO₂ (Equilibria::co2_judged, cross review F1).
        let own = eq.co2(dic, reached)?;
        let co2 = eq.co2_judged(alkalinity, reached, own)?.0 * c::MG_CO2_PER_MMOL;
        let below = reagent.key == "degas" && air_co2_mg_l.is_some_and(|air| own * c::MG_CO2_PER_MMOL < air);
        steps.push(Step {
            reagent: Some(reagent.key),
            grams,
            dic,
            alkalinity,
            ph: Some(reached),
            co2_mg_l: Some(co2),
            below_air: below,
        });
    }
    Ok(steps)
}
