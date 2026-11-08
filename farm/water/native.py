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
Equilibria = chemcore.Equilibria
KELVIN = chemcore.KELVIN
MG_CACO3_PER_MEQ = chemcore.MG_CACO3_PER_MEQ
MG_CO2_PER_MMOL = chemcore.MG_CO2_PER_MMOL
MG_CALCIUM_PER_MOL = chemcore.MG_CALCIUM_PER_MOL
H2S_PER_S = chemcore.H2S_PER_S
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
kw_total = chemcore.kw_total
kb_total = chemcore.kb_total
k_nh4_sws = chemcore.k_nh4_sws
pk_nh4 = chemcore.pk_nh4
k_h2s_total = chemcore.k_h2s_total
ksp_calcite = chemcore.ksp_calcite
ksp_aragonite = chemcore.ksp_aragonite
nh3_fraction = chemcore.nh3_fraction
pressure_atm = chemcore.pressure_atm
vapour_pressure_atm = chemcore.vapour_pressure_atm
oxygen_solubility = chemcore.oxygen_solubility
k0_co2 = chemcore.k0_co2
co2_from_air = chemcore.co2_from_air

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
