//! The values of a water against its limits (farm/water/deffeyes.py `analyse`, `judge`, the borders, the alkalinity
//! floor, the chart's box), ported literally from golden v1's Python: DIC and CO₂ from the alkalinity and the pH, NH₃-N
//! from the TAN, H₂S from the total sulfide, each limit as a pH border with its margin and status (the source's rule:
//! past the border critical, within 0.2 pH a warning), the oxygen saturation at a pressure.
use crate::chemistry::{self as c, Equilibria};
use crate::num::{ChemError, R, div, finite};

/// The chart's pH domain (the source's): a border inside it is shown as a number.
pub const PH_RANGE: (f64, f64) = (4.0, 12.5);
/// A border nearer than this (pH) is a warning.
pub const ALERT_PH: f64 = 0.2;
/// The axes' ends at least: 6 mmol/L DIC and 6 meq/L alkalinity.
pub const AXIS: f64 = 6.0;

/// The status of a value (farm/water/evaluate.py `Status`, the five the chemistry gives).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    Critical,
    Warning,
    Ok,
    NoLimit,
    NotMeasured,
}

impl Status {
    /// The stable code (evaluate.Status's value).
    pub fn code(self) -> &'static str {
        match self {
            Status::Critical => "critical",
            Status::Warning => "warning",
            Status::Ok => "ok",
            Status::NoLimit => "no_limit",
            Status::NotMeasured => "not_measured",
        }
    }

    pub fn from_code(code: &str) -> Option<Status> {
        [
            Status::Critical,
            Status::Warning,
            Status::Ok,
            Status::NoLimit,
            Status::NotMeasured,
        ]
        .into_iter()
        .find(|status| status.code() == code)
    }
}

/// A limit as a pH: toxic above it (NH₃) or below it (CO₂, H₂S); `ph` None when the limit cannot be reached; `margin`
/// how far the water's pH is from it on the safe side (negative: past it).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Border {
    pub ph: Option<f64>,
    pub toxic_above: bool,
    pub margin: Option<f64>,
    pub status: Status,
}

impl Border {
    /// The border is a pH of the chart's range (4 to 12.5): shown as a number.
    pub fn on_chart(&self) -> bool {
        self.ph.is_some_and(|ph| PH_RANGE.0 <= ph && ph <= PH_RANGE.1)
    }

    /// The limit is passed at every pH of the chart's range.
    pub fn everywhere(&self) -> bool {
        match self.ph {
            None => false,
            Some(ph) => {
                if self.toxic_above {
                    ph < PH_RANGE.0
                } else {
                    ph > PH_RANGE.1
                }
            }
        }
    }

    /// The limit is not reached at any pH of the chart's range.
    pub fn off_chart(&self) -> bool {
        self.ph.is_some() && !self.on_chart() && !self.everywhere()
    }
}

/// The border and the status: critical past it, a warning within ALERT_PH of it, ok short of it or when it cannot be
/// reached. `missing`: the status when there is nothing to judge (no value or no limit).
pub fn judge(ph: f64, border: Option<f64>, toxic_above: bool, missing: Option<Status>) -> Border {
    if let Some(status) = missing {
        return Border {
            ph: None,
            toxic_above,
            margin: None,
            status,
        };
    }
    let Some(border) = border else {
        return Border {
            ph: None,
            toxic_above,
            margin: None,
            status: Status::Ok,
        };
    };
    let margin = if toxic_above { border - ph } else { ph - border };
    let status = if margin <= 0.0 {
        Status::Critical
    } else if margin <= ALERT_PH {
        Status::Warning
    } else {
        Status::Ok
    };
    Border {
        ph: Some(border),
        toxic_above,
        margin: Some(margin),
        status,
    }
}

/// What a sample holds: units and bases in the names; total sulfide as S.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Water {
    pub temperature_c: f64,
    pub salinity_ppt: f64,
    pub ph: f64,
    pub alkalinity_mg_l: f64,
    pub tan_mg_l: Option<f64>,
    pub total_sulfide_ug_l: Option<f64>,
    pub calcium_mg_l: Option<f64>,
    pub oxygen_mg_l: Option<f64>,
}

/// The values not to pass: NH₃-N mg/L as N, CO₂ mg/L, H₂S µg/L as H₂S; the alkalinity band, mg/L as CaCO₃.
#[derive(Clone, Copy, Debug, PartialEq, Default)]
pub struct Limits {
    pub nh3_n_mg_l: Option<f64>,
    pub co2_mg_l: Option<f64>,
    pub h2s_ug_l: Option<f64>,
    pub alkalinity_low_mg_l: Option<f64>,
    pub alkalinity_high_mg_l: Option<f64>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Target {
    pub ph: f64,
    pub alkalinity_mg_l: f64,
}

/// The values of a water, worked out: per litre, alkalinity in meq/L, DIC in mmol/L.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Analysis {
    pub equilibria: Equilibria,
    pub alkalinity_meq: f64,
    pub dic: f64,
    pub co2_mg_l: f64,
    pub co2: Border,
    pub target_alkalinity_meq: Option<f64>,
    pub target_dic: Option<f64>,
    pub target_co2_mg_l: Option<f64>,
    pub nh3_n_mg_l: Option<f64>,
    pub nh3: Border,
    /// The TAN that gives the NH₃-N limit at this pH.
    pub safe_tan_mg_l: Option<f64>,
    /// NH₃ as a share of TAN at the border, limit ÷ TAN, %.
    pub nh3_share_at_border_pct: Option<f64>,
    /// As H₂S.
    pub h2s_ug_l: Option<f64>,
    pub h2s: Border,
    /// As S: the total sulfide that gives the H₂S limit at this pH.
    pub safe_total_sulfide_ug_l: Option<f64>,
    pub oxygen_solubility_mg_l: f64,
    pub oxygen_saturation_pct: Option<f64>,
    pub pressure_atm: f64,
    /// NH₃ as a share of TAN at the water's pH, %.
    pub nh3_share_pct: f64,
    /// H₂S as a share of the total sulfide at the water's pH, %.
    pub h2s_share_pct: f64,
}

fn finite_option(value: Option<f64>) -> Result<Option<f64>, ChemError> {
    value.map(finite).transpose()
}

/// The values of a water against the limits at a pressure (atm). Every input must be finite.
pub fn analyse(water: &Water, limits: &Limits, target: Option<&Target>, pressure: f64) -> Result<Analysis, ChemError> {
    for value in [water.ph, water.alkalinity_mg_l, pressure] {
        finite(value)?;
    }
    for value in [
        water.tan_mg_l,
        water.total_sulfide_ug_l,
        water.calcium_mg_l,
        water.oxygen_mg_l,
        limits.nh3_n_mg_l,
        limits.co2_mg_l,
        limits.h2s_ug_l,
        limits.alkalinity_low_mg_l,
        limits.alkalinity_high_mg_l,
    ] {
        finite_option(value)?;
    }
    if let Some(target) = target {
        finite(target.ph)?;
        finite(target.alkalinity_mg_l)?;
    }
    let eq = c::equilibria(water.temperature_c, water.salinity_ppt)?;
    let ph = water.ph;
    let alkalinity = div(water.alkalinity_mg_l, c::MG_CACO3_PER_MEQ)?;
    let dic = eq.dic(alkalinity, ph)?;
    let co2_limit = limits
        .co2_mg_l
        .map(|limit| div(limit, c::MG_CO2_PER_MMOL))
        .transpose()?;
    let co2 = judge(
        ph,
        match co2_limit {
            None => None,
            Some(limit) => eq.ph_where_co2(alkalinity, limit)?,
        },
        false,
        if co2_limit.is_none() {
            Some(Status::NoLimit)
        } else {
            None
        },
    );

    let (mut target_alkalinity, mut target_dic, mut target_co2) = (None, None, None);
    if let Some(target) = target {
        let alkalinity = div(target.alkalinity_mg_l, c::MG_CACO3_PER_MEQ)?;
        let dic = eq.dic(alkalinity, target.ph)?;
        target_alkalinity = Some(alkalinity);
        target_dic = Some(dic);
        target_co2 = Some(eq.co2(dic, target.ph)? * c::MG_CO2_PER_MMOL);
    }

    let (tan, nh3_limit) = (water.tan_mg_l, limits.nh3_n_mg_l);
    let nh3_share = eq.nh3_share(ph)?;
    let nh3 = judge(
        ph,
        match (tan, nh3_limit) {
            (Some(tan), Some(limit)) => eq.ph_where_nh3(tan, limit)?,
            _ => None,
        },
        true,
        if tan.is_none() {
            Some(Status::NotMeasured)
        } else if nh3_limit.is_none() {
            Some(Status::NoLimit)
        } else {
            None
        },
    );

    let (sulfide, h2s_limit) = (water.total_sulfide_ug_l, limits.h2s_ug_l);
    let h2s_share = eq.h2s_share(ph)?;
    let total_h2s = sulfide.map(|sulfide| sulfide * c::H2S_PER_S);
    let h2s = judge(
        ph,
        match (total_h2s, h2s_limit) {
            (Some(total), Some(limit)) => eq.ph_where_h2s(total, limit)?,
            _ => None,
        },
        false,
        if sulfide.is_none() {
            Some(Status::NotMeasured)
        } else if h2s_limit.is_none() {
            Some(Status::NoLimit)
        } else {
            None
        },
    );

    let solubility = c::oxygen_solubility(water.temperature_c, water.salinity_ppt, pressure)?;
    let analysis = Analysis {
        equilibria: eq,
        alkalinity_meq: alkalinity,
        dic,
        co2_mg_l: eq.co2(dic, ph)? * c::MG_CO2_PER_MMOL,
        co2,
        target_alkalinity_meq: target_alkalinity,
        target_dic,
        target_co2_mg_l: target_co2,
        nh3_n_mg_l: tan.map(|tan| tan * nh3_share),
        nh3,
        safe_tan_mg_l: nh3_limit.map(|limit| div(limit, nh3_share)).transpose()?,
        nh3_share_at_border_pct: match (nh3.ph, nh3_limit, tan) {
            (Some(_), Some(limit), Some(tan)) => Some(div(100.0 * limit, tan)?),
            _ => None,
        },
        h2s_ug_l: total_h2s.map(|total| total * h2s_share),
        h2s,
        safe_total_sulfide_ug_l: h2s_limit
            .map(|limit| div(div(limit, h2s_share)?, c::H2S_PER_S))
            .transpose()?,
        oxygen_solubility_mg_l: solubility,
        oxygen_saturation_pct: water
            .oxygen_mg_l
            .map(|oxygen| div(100.0 * oxygen, solubility))
            .transpose()?,
        pressure_atm: pressure,
        nh3_share_pct: 100.0 * eq.nh3_share(water.ph)?,
        h2s_share_pct: 100.0 * eq.h2s_share(water.ph)?,
    };
    Ok(analysis)
}

/// The alkalinity (mg/L as CaCO₃) a water of this pH has at least: hydroxide and borate are alkalinity too, so at a
/// high pH the alkalinity has a floor below which the DIC would be negative (WQ-38).
pub fn alkalinity_floor(temperature_c: f64, salinity_ppt: f64, ph: f64) -> R {
    finite(ph)?;
    Ok(c::equilibria(temperature_c, salinity_ppt)?.isoline(ph)?.1 * c::MG_CACO3_PER_MEQ)
}

/// The floor when a water of this pH and alkalinity cannot be (its alkalinity at or below the floor), else None.
pub fn why_impossible(
    temperature_c: f64,
    salinity_ppt: f64,
    ph: f64,
    alkalinity_mg_l: f64,
) -> Result<Option<f64>, ChemError> {
    finite(alkalinity_mg_l)?;
    let floor = alkalinity_floor(temperature_c, salinity_ppt, ph)?;
    Ok(if alkalinity_mg_l > floor { None } else { Some(floor) })
}

/// The axes' ends and their tick steps.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ChartBox {
    pub dic: f64,
    pub alkalinity: f64,
    pub dic_step: f64,
    pub alkalinity_step: f64,
}

/// The end of an axis and its step: AXIS when the values fit in it with 10 % to spare, else the next multiple of a
/// 1-2-5 step that keeps at most 12 ticks. Beyond 12 steps of 5e7 (the Python ran out of steps with StopIteration):
/// ChartTooLarge.
pub fn axis(needed: f64) -> Result<(f64, f64), AxisError> {
    let needed = needed * 1.1;
    if needed <= AXIS {
        return Ok((AXIS, 1.0));
    }
    let mut power = 1.0;
    for _ in 0..8 {
        for base in [1.0, 2.0, 5.0] {
            let step = base * power;
            if needed / step <= 12.0 {
                return Ok((libm::ceil(needed / step) * step, step));
            }
        }
        power *= 10.0;
    }
    Err(AxisError::ChartTooLarge)
}

/// Why there is no box.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AxisError {
    /// The values need more than 12 ticks of 5e7 (an alkalinity of thousands of mol/L).
    ChartTooLarge,
}

/// The box that holds the water (DIC, alkalinity in meq/L), the target, the alkalinity band's high end (mg/L) and the
/// `extra` points (DIC, alkalinity), with 10 % to spare.
pub fn box_of(
    dic: f64,
    alkalinity_meq: f64,
    target: Option<(f64, f64)>,
    alkalinity_high_mg_l: Option<f64>,
    extra: &[(f64, f64)],
) -> Result<ChartBox, AxisError> {
    let (target_dic, target_alkalinity) = target.unwrap_or((0.0, 0.0));
    let largest = |values: &mut dyn Iterator<Item = f64>| {
        values.fold(f64::NEG_INFINITY, |most, value| if value > most { value } else { most })
    };
    let dic = largest(&mut [dic, target_dic].into_iter().chain(extra.iter().map(|point| point.0)));
    let high = alkalinity_high_mg_l.map(|high| high / c::MG_CACO3_PER_MEQ);
    let alkalinity = largest(
        &mut [alkalinity_meq, target_alkalinity]
            .into_iter()
            .chain(extra.iter().map(|point| point.1))
            .chain(high),
    );
    let (dic, dic_step) = axis(dic)?;
    let (alkalinity, alkalinity_step) = axis(alkalinity)?;
    Ok(ChartBox {
        dic,
        alkalinity,
        dic_step,
        alkalinity_step,
    })
}
