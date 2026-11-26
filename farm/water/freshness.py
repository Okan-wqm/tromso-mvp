"""The staleness rules the water is read by, the user's reference data (alarm plan §7c, cross review F10), never the
code's:
- per parameter, how long a value says something about the water now (farm.WaterFreshness, `hours`): an older one is
  shown stale, never OK, and never clears an alarm;
- how far ahead of the server's clock a value may be stamped and still count as fresh (the platform settings' clock
  tolerance, `tolerance`): one moment for two clocks. A value further ahead, up to the ingest contract's hour
  (evaluate.MAX_AHEAD), still decides its unit's status and its alarm is never delayed (alarms/sources.py seen_at).
A live value's freshness is its channel's (sensors.Channel `fresh_s`: its heartbeat times its own `fresh_heartbeats`).
A worked-out value (NH₃-N, NH₄-N: a parameter with declared `inputs`) is never fresher than its oldest input
(`derived_until`): it stops being fresh when the first value it was worked out from does, never later than its own row.

The rows are read once and kept in the process until one of them is saved (a signal, farm/apps.py), a request starts
(Django's request_started) or the alarm loop starts a pass (alarms/engine.py): a change takes effect on the next page and
the next pass, and a page asks the database once, not once per value. A parameter whose row is missing (a restore) gets
it made again from SEEDS, as the platform settings' row is (core.models.PlatformSettings.get): the values in force are
the rows; SEEDS are the defaults the migration wrote (farm 0037). When the rows cannot be read at all (the database
is not there, a code path that may not query it), the defaults stand in for that call only, said once in the log, and
the rows are asked again the next time."""
import logging
import threading
from datetime import timedelta

logger = logging.getLogger(__name__)

# How long a freshness may be, in hours: at least an hour, at most a year. The refusal of nonsense, never a value in force.
FRESH_HOURS_BOUNDS = (1, 8760)
# The defaults a missing row is made again with (farm 0037 and 0042 seeded the same): the owner's, as they stood in the code.
SEEDS = {'temperature_c': 24, 'oxygen_mg_l': 24, 'oxygen_saturation_pct': 24, 'ph': 72, 'alkalinity_mg_l': 336,
         'co2_mg_l': 72, 'tan_mg_l': 168, 'nitrite_n_mg_l': 168, 'nitrate_n_mg_l': 336, 'tgp_pct': 168,
         'salinity_ppt': 168, 'turbidity_ntu': 168, 'nh3_n_mg_l': 168, 'nh4_n_mg_l': 168,
         # formula 3's ionic-strength inputs (farm 0042): the conductivity at 25 °C 7 days, the hardness 14
         'conductivity_25_us_cm': 168, 'hardness_mg_l': 336,
         # the optional phosphate (farm 0044): 7 days, as the TAN and the other nutrients
         'phosphate_p_mg_l': 168}

_held = {}
_lock = threading.Lock()


def forget(*args, **kwargs):
    """Drops the rows held: the next use reads them again (a row saved, a request started, an alarm pass started)."""
    _held.pop('rules', None)


def _load():
    from core.models import PlatformSettings
    from farm.models import WaterFreshness
    hours = dict(WaterFreshness.objects.values_list('parameter', 'fresh_hours'))
    missing = [code for code in SEEDS if code not in hours]
    if missing:
        WaterFreshness.objects.bulk_create([WaterFreshness(parameter=code, fresh_hours=SEEDS[code]) for code in missing],
                                           ignore_conflicts=True)
        hours = dict(WaterFreshness.objects.values_list('parameter', 'fresh_hours'))
    return {'hours': hours, 'tolerance': timedelta(seconds=PlatformSettings.get().clock_tolerance_seconds)}


def _defaults():
    from core.models import PlatformSettings
    return {'hours': dict(SEEDS), 'tolerance': timedelta(
        seconds=PlatformSettings._meta.get_field('clock_tolerance_seconds').default)}


def _rules():
    held = _held.get('rules')
    if held is None:
        with _lock:
            held = _held.get('rules')
            if held is None:
                try:
                    held = _held['rules'] = _load()
                    _held.pop('warned', None)
                except Exception:
                    if 'warned' not in _held:
                        _held['warned'] = True
                        logger.warning('The water freshness rows could not be read; their defaults stand in.',
                                       exc_info=True)
                    return _defaults()
    return held


def hours(code):
    """How many hours a value of the parameter says something about the water now."""
    return _rules()['hours'][code]


def fresh_for(code):
    return timedelta(hours=hours(code))


def tolerance():
    """How far ahead of the server's clock a value may be stamped and still count as fresh."""
    return _rules()['tolerance']


def fresh_until(code, at, seconds=None):
    """The moment a measured value of `code` taken at `at` stops being fresh: a live value `seconds` after it (its
    channel's heartbeats times its fresh heartbeats), else the parameter's hours after it."""
    return at + (timedelta(seconds=seconds) if seconds is not None else fresh_for(code))


def derived_until(code, at, inputs):
    """The moment a worked-out value of `code` (one with declared `inputs`, farm/water/parameters.py) worked out at `at`
    stops being fresh: a worked-out value is never fresher than its oldest input (the coordinator's decision of
    2026-11-26), so the earliest moment any of its inputs stops being fresh, and never later than its own row's hours.
    `inputs`: {input code: the moment that input stops being fresh (`fresh_until`), or None where no measured value of
    it entered (the salinity 0 assumed in fresh water; an input missing, so nothing was worked out)}, for exactly the
    inputs the parameter declares: one left out or one not declared is refused (ValueError), never silently skipped."""
    from .parameters import get
    declared = get(code).inputs
    if not declared:
        raise ValueError(f'{code} is not a worked-out parameter: it declares no inputs')
    if set(inputs) != set(declared):
        raise ValueError(f'{code} is worked out from {sorted(declared)}, not {sorted(inputs)}')
    return min([fresh_until(code, at), *(end for end in inputs.values() if end is not None)])


# The coordinator's decision of 2026-11-26: how far, in °C, the place's live temperature may be from the temperature a
# worked-out value was worked out with and still confirm it. THE one constant of the rule below.
TEMPERATURE_BAND = 1.0


def temperature_until(own_end, confirmed_until):
    """The end of a worked-out value's temperature input (a sample's, or the place's sensor's at the sample's time) where
    the place has live temperature: it stays fresh while the place has a fresh live temperature within TEMPERATURE_BAND
    of the temperature used, and ends the moment that live temperature moves further or goes stale (`confirmed_until`,
    sources.steady_until from the input's own time: at that time already where the live temperature then was further
    off). Where the place had no fresh live temperature at that time (`confirmed_until` None) its own end stands
    (`own_end`, `fresh_until`). The live temperature says what the water is now, so it can end the input before its own
    hours, as well as keep it fresh after them."""
    return own_end if confirmed_until is None else confirmed_until
