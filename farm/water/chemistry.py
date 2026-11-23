"""The water's chemistry, worked out on read and never stored: the un-ionised ammonia of a TAN reading and the oxygen
saturation of a dissolved-oxygen reading (farm/water/read.py), and the carbonate and sulfide systems the Deffeyes chart
is drawn from (farm/water/deffeyes.py).

The formulas live in the Rust core only (chemcore/core/src/chemistry.rs: each with its paper and validity range;
README, Water-chemistry core), reached through farm/water/native.py. This module keeps the names the rest of the code
has always used, so no caller changed; it holds no formula (farm/tests/test_one_formula.py). The core was held to the
Python formulas it replaced: golden v1 (chemcore/golden/v1) within each quantity's class, the 50-digit anchors, and
the source platform's engine (chemcore/findings/B1.md).

What it gives, in short (the core's documentation has the sources): the constants of a water on the free pH scale
by the application's formula (`water_equilibria`, formula 3: the water's own ionic strength from its conductivity at
25 °C, hardness, alkalinity or salinity, Davies activities with the A of its temperature, the seawater constants from
5 ‰ and a blend from 1 ‰; FORMULA_VERSION; each Equilibria says its formula and ionic strength) and formula 1's
(`equilibria`, golden v1's, never the application's), from the constants K1, K2 of Millero et al. 2006; Kw of
Millero 1995; KB of Dickson 1990; KNH4 of Millero 1995; KH2S of Millero, Plese & Fernandez 1988; Ksp of Mucci 1983,
with its carbonate system on the Deffeyes chart (`Equilibria`:
fractions, isoline, DIC, CO2, the borders of a limit), the solver (`solve`), the oxygen solubility of Benson & Krause
1984 at a pressure (`oxygen_solubility`, `pressure_atm`, `vapour_pressure_atm`) and the CO2 of a water in equilibrium
with the air (`k0_co2`, `co2_from_air`, Weiss 1974). An input that is not a finite number, or one where the mathematics
fails, raises (ValueError, ZeroDivisionError, OverflowError; native.NonFiniteError for a non-finite one); a pH and an
alkalinity no water has (the alkalinity at or below the floor of the pH), or a DIC below 0, raises ImpossibleWaterError
(a ValueError; formula 3), never a concentration below 0. Kw is Millero's (1995) on his seawater scale (formula 1: the
2007 Guide's total-scale value, `kw_total`)."""
from .native import (  # noqa: F401  the names the code has always used
    FORMULA_VERSION, H2S_PER_S, MG_CACO3_PER_MEQ, MG_CALCIUM_PER_MOL, MG_CO2_PER_MMOL, Equilibria, ImpossibleWaterError,
    water_equilibria,
    co2_from_air, equilibria, k0_co2, k1_sws, k2_sws, k_h2s_total, k_nh4_sws, kb_total, ksp_aragonite, ksp_calcite,
    kw_total, nh3_fraction, oxygen_solubility, ph_free, pk_nh4, pressure_atm, solve, vapour_pressure_atm)
from .native import activity_coefficient_h as _activity_coefficient_h  # noqa: F401
from .native import free_to_sws as _free_to_sws  # noqa: F401
from .native import free_to_total as _free_to_total  # noqa: F401
from .native import ionic_strength as _ionic_strength  # noqa: F401
from .native import kf as _kf  # noqa: F401
from .native import ks as _ks  # noqa: F401
from .native import sws_to_nbs as _sws_to_nbs  # noqa: F401
from .native import total_boron as _total_boron  # noqa: F401
from .native import total_fluoride as _total_fluoride  # noqa: F401
from .native import total_sulfate as _total_sulfate  # noqa: F401
