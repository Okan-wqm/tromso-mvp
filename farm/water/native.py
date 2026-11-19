"""The one door to the water-chemistry core, chemcore (Rust, built into the runner's image: README, chemcore).
Only this module imports it (farm/tests/test_native.py checks the whole checkout); the chemistry modules call
through here. There is no fallback: without the module this import fails, and so does the server's start.

`expected()` reads chemcore/EXPECTED, which chemcore/scripts/gen_expected.sh writes from the built module and
which is committed with the source; the start check core.E001 (core/checks.py) refuses a build that differs."""
from pathlib import Path

import chemcore

if not hasattr(chemcore, 'core_hash'):
    # The checkout's chemcore/ directory imports as an empty namespace package when the wheel is missing.
    raise ImportError('The water-chemistry core (chemcore) is not installed: only its source directory was found '
                      f'({list(getattr(chemcore, "__path__", []))}). Build the image (docker/testrunner.Dockerfile).')

EXPECTED = Path(__file__).resolve().parent.parent.parent / 'chemcore' / 'EXPECTED'
FIELDS = ('version', 'formula_version', 'core_hash')


def version():
    return chemcore.version()


def formula_version():
    return chemcore.formula_version()


FORMULA_VERSION = chemcore.formula_version()          # the formula every value of the application is worked out by
FORMULAS = tuple(chemcore.FORMULAS)                   # the formulas the core can still work out (1, 3, 4)


def core_hash():
    return chemcore.core_hash()


def expected():
    """{field: value} of chemcore/EXPECTED; ValueError when a line is not "name value" or a field is missing."""
    found = {}
    for number, line in enumerate(EXPECTED.read_text(encoding='utf-8').splitlines(), start=1):
        if not line.strip() or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) != 2 or parts[0] not in FIELDS:
            raise ValueError(f'line {number}: not "name value" with a name of {", ".join(FIELDS)}')
        found[parts[0]] = parts[1]
    missing = [field for field in FIELDS if field not in found]
    if missing:
        raise ValueError(f'missing {", ".join(missing)}')
    return found


def handshake_problems():
    """What differs between the installed core and chemcore/EXPECTED, as sentences; [] when they agree."""
    try:
        wanted = expected()
    except (OSError, ValueError) as error:
        return [f'chemcore/EXPECTED cannot be read: {error}']
    installed = {'version': version(), 'formula_version': str(formula_version()), 'core_hash': core_hash()}
    return [f'{field}: installed {installed[field]}, expected {wanted[field]}'
            for field in FIELDS if installed[field] != wanted[field]]


# ---- the chemistry (chemcore/core/src/chemistry.rs), under the names farm/water/chemistry.py gives them ----------
NonFiniteError = chemcore.NonFiniteError
# A water that cannot be (its alkalinity at or below the floor of its pH, or a DIC below 0): formula 3 refuses it at every
# door, never a negative concentration; a ValueError. The pages say the reason first (deffeyes.why_impossible, the same rule).
ImpossibleWaterError = chemcore.ImpossibleWaterError
# A pH on a seawater scale (total, seawater, free) for a water that is not sea water of 5 permil or more: never
# converted on an assumption; a ValueError. The forms and the write path say the reason first (Equilibria.takes_ph_scale).
SeawaterScaleError = chemcore.SeawaterScaleError
# The scales a pH may be given on, the default (NBS: the pH itself) first (chemcore/core/src/scale.rs); a pH on another
# is put on the NBS scale by Equilibria.ph_nbs before anything is worked out from it.
PH_SCALES = tuple(chemcore.PH_SCALES)
Equilibria = chemcore.Equilibria
KELVIN = chemcore.KELVIN
MG_CACO3_PER_MEQ = chemcore.MG_CACO3_PER_MEQ
MG_CO2_PER_MMOL = chemcore.MG_CO2_PER_MMOL
MG_CALCIUM_PER_MOL = chemcore.MG_CALCIUM_PER_MOL
H2S_PER_S = chemcore.H2S_PER_S
MG_P_PER_MMOL = chemcore.MG_P_PER_MMOL    # PO₄-P, mg/L as P, per mmol/L of phosphate (P 30.973762)
SOLVER_PH = chemcore.SOLVER_PH
AIR_CO2 = chemcore.AIR_CO2
equilibria = chemcore.equilibria
solve = chemcore.solve
ks = chemcore.ks
kf = chemcore.kf
ionic_strength = chemcore.ionic_strength
total_sulfate = chemcore.total_sulfate
total_fluoride = chemcore.total_fluoride
total_boron = chemcore.total_boron
free_to_sws = chemcore.free_to_sws
free_to_total = chemcore.free_to_total
activity_coefficient_h = chemcore.activity_coefficient_h
sws_to_nbs = chemcore.sws_to_nbs
ph_free = chemcore.ph_free
k1_sws = chemcore.k1_sws
k2_sws = chemcore.k2_sws
kw_total = chemcore.kw_total            # formula 1's: the 2007 Guide's total-scale value (Millero's constant less 0.015)
kw_sws = chemcore.kw_sws                # formula 3's: Millero (1995) on his seawater scale; at S 0 pure water's
kw_free = chemcore.kw_free              # ... over [H+]SWS / [H+]free, as formula 3's Equilibria hold it
kb_total = chemcore.kb_total
k_nh4_sws = chemcore.k_nh4_sws          # formula 3's K_NH4 (Yao & Millero 1995)
pk_nh4 = chemcore.pk_nh4
# Formula 4's K_NH4, the best estimate fresh to sea: Clegg & Whitfield (1995) eq. 18 (total scale, molal) and its pure-water
# pK; on the free scale per kg of solution as the core holds its constants.
k_nh4_cw95 = chemcore.k_nh4_cw95
pk_nh4_cw95_total = chemcore.pk_nh4_cw95_total
pk_nh4_cw95_pure = chemcore.pk_nh4_cw95_pure
k_h2s_total = chemcore.k_h2s_total
# Phosphoric acid (Millero 1995, seawater scale; pure water's at S 0): only a water with a phosphate given reads them.
k1p_sws = chemcore.k1p_sws
k2p_sws = chemcore.k2p_sws
k3p_sws = chemcore.k3p_sws
ksp_calcite = chemcore.ksp_calcite
ksp_aragonite = chemcore.ksp_aragonite
nh3_fraction = chemcore.nh3_fraction
pressure_atm = chemcore.pressure_atm
vapour_pressure_atm = chemcore.vapour_pressure_atm
oxygen_solubility = chemcore.oxygen_solubility
k0_co2 = chemcore.k0_co2
co2_from_air = chemcore.co2_from_air
seawater_density = chemcore.seawater_density      # EOS-80 at one atmosphere, kg/L: formula 3's Ω takes the Ksp per litre

# ---- the analysis of a water (chemcore/core/src/analysis.rs) ---------------------------------------------------
ChartTooLargeError = chemcore.ChartTooLargeError
PH_RANGE = chemcore.PH_RANGE
ALERT_PH = chemcore.ALERT_PH
AXIS = chemcore.AXIS
judge = chemcore.judge
analyse = chemcore.analyse
alkalinity_floor = chemcore.alkalinity_floor
why_impossible = chemcore.why_impossible
box_of = chemcore.box_of

# ---- the chart in its own units (chemcore/core/src/geometry.rs) ------------------------------------------------
geometry = chemcore.geometry
safe_zone = chemcore.safe_zone
safe_zone_gaps = chemcore.safe_zone_gaps

clip_polyline = chemcore.clip_polyline

# ---- dosing (chemcore/core/src/dosing.rs) -------------------------------------------------------------------------
reagents = chemcore.reagents
at_target = chemcore.at_target
split = chemcore.split
recipes = chemcore.recipes
visual = chemcore.visual
simulate = chemcore.simulate

# ---- the four small charts (chemcore/core/src/plots.rs) ----------------------------------------------------------
plots = chemcore.plots
judge_step = chemcore.judge_step
bands = chemcore.bands
saturation_index = chemcore.saturation_index

# ---- formula 3, the application's (chemcore/core/src/fresh.rs; chemcore/findings/I2-comparison.md): fresh water's own
# ionic strength, the Debye-Hückel A of the temperature, the band from 1 to 5 permil. Every chemistry of a water starts
# from `water_equilibria` (the formula of FORMULA_VERSION by default); `equilibria` is formula 1, golden v1's, kept so a
# value shown before can be worked out again exactly, never called by the application.
FRESH_UP_TO = chemcore.FRESH_UP_TO
SEA_FROM = chemcore.SEA_FROM
sea_weight = chemcore.sea_weight
DAVIES_MAX = chemcore.DAVIES_MAX
IONIC_PER_MICROSIEMENS = chemcore.IONIC_PER_MICROSIEMENS              # Russell 1976: natural (bicarbonate) waters
IONIC_PER_MICROSIEMENS_NACL = chemcore.IONIC_PER_MICROSIEMENS_NACL    # NaCl: a salt-added water (cross review F4)
fresh_ionic_strength = chemcore.fresh_ionic_strength
practical_salinity = chemcore.practical_salinity          # PSS-78 at 25 °C (cross review F5)
davies_log_gamma = chemcore.davies_log_gamma
dielectric_constant = chemcore.dielectric_constant
water_density = chemcore.water_density
debye_huckel_a = chemcore.debye_huckel_a
equilibria_v3 = chemcore.equilibria_v3

# ---- formula 4, the application's (chemcore/core/src/formula4.rs): formula 3 with the NBS step of Millero (1986) in salt
# water, Clegg & Whitfield's K_NH4 and Rule S: from 5 permil the judged NH3 and CO2 are the best estimate at the pH plus and
# minus PH_UNCERTAINTY (0.03, US EPA 1989), up to 1 permil formula 3's ideal water, blended between.
PH_UNCERTAINTY = chemcore.PH_UNCERTAINTY
equilibria_v4 = chemcore.equilibria_v4
ph_offset_v4 = chemcore.ph_offset_v4
nbs_minus_total_25 = chemcore.nbs_minus_total_25
water_equilibria = chemcore.water_equilibria
