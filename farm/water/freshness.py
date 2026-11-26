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
the next pass, and a page asks the database once, not once per value.

Reading them is a read and nothing else (the data-layering audit, M-1): the values in force are the rows, seeded by the
migrations (farm 0037, 0042, 0044: one per water parameter) and kept by the database (farm 0051: a row is changed,
never deleted). There is no default in the code to stand in for them. A parameter without its row cannot be said fresh
or stale, so `hours` refuses it (Missing): the page fails and the alarm pass's water step fails, and a failed step is
itself a critical alarm (alarms/sources.py supervise), never a value judged by a rule the farm did not set. When the
rows cannot be read at all, the database's error goes to the caller the same way."""
import threading
from datetime import timedelta

# How long a freshness may be, in hours: at least an hour, at most a year. The refusal of nonsense, never a value in force.
FRESH_HOURS_BOUNDS = (1, 8760)

_held = {}
_lock = threading.Lock()


class Missing(LookupError):
    """A water parameter has no freshness row: its values can be judged neither fresh nor stale."""

    def __init__(self, code):
        super().__init__(f'The water parameter {code!r} has no freshness row (Setup › Reference data › Water freshness): '
                         f'its values cannot be judged fresh or stale. The rows are seeded by the migrations and never '
                         f'deleted; restore the database from its backup.')
        self.code = code


def forget(*args, **kwargs):
    """Drops the rows held: the next use reads them again (a row saved, a request started, an alarm pass started)."""
    _held.pop('rules', None)


def _load():
    from core.models import PlatformSettings
    from farm.models import WaterFreshness
    platform = PlatformSettings.get()
    return {'hours': dict(WaterFreshness.objects.values_list('parameter', 'fresh_hours')),
            'tolerance': timedelta(seconds=platform.clock_tolerance_seconds),
            'band': float(platform.temperature_band_c)}


def _rules():
    held = _held.get('rules')
    if held is None:
        with _lock:
            held = _held.get('rules')
            if held is None:
                held = _held['rules'] = _load()
    return held


def hours(code):
    """How many hours a value of the parameter says something about the water now (Missing without its row)."""
    try:
        return _rules()['hours'][code]
    except KeyError:
        raise Missing(code) from None


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


def temperature_band():
    """How far, in °C, the place's live temperature may be from the temperature a worked-out value was worked out with
    and still keep it fresh: the platform owner's setting (core.models.PlatformSettings.temperature_band_c, 1.0 until
    set; the coordinator's decisions of 2026-11-26), read with the rows above and dropped with them."""
    return _rules()['band']


def temperature_until(own_end, confirmed_until):
    """The end of a worked-out value's temperature input (a sample's, or the place's sensor's at the sample's time) where
    the place has live temperature: it stays fresh while the place has a fresh live temperature within the band
    (`temperature_band`) of the temperature used, and ends the moment that live temperature moves further or goes stale
    (`confirmed_until`,
    sources.steady_until from the input's own time: at that time already where the live temperature then was further
    off). Where the place had no fresh live temperature at that time (`confirmed_until` None) its own end stands
    (`own_end`, `fresh_until`). The live temperature says what the water is now, so it can end the input before its own
    hours, as well as keep it fresh after them."""
    return own_end if confirmed_until is None else confirmed_until
