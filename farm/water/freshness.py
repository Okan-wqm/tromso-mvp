"""The staleness rules the water is read by, the user's reference data (alarm plan §7c, cross review F10), never the
code's:
- per parameter, how long a value says something about the water now (farm.WaterFreshness, `hours`): an older one is
  shown stale, never OK, and never clears an alarm;
- how far ahead of the server's clock a value may be stamped and still count as fresh (the platform settings' clock
  tolerance, `tolerance`): one moment for two clocks. A value further ahead, up to the ingest contract's hour
  (evaluate.MAX_AHEAD), still decides its unit's status and its alarm is never delayed (alarms/sources.py seen_at).
A live value's freshness is its channel's (sensors.Channel `fresh_s`: its heartbeat times its own `fresh_heartbeats`).

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
# The defaults a missing row is made again with (farm 0037 and 0040 seeded the same): the owner's, as they stood in the code.
SEEDS = {'temperature_c': 24, 'oxygen_mg_l': 24, 'oxygen_saturation_pct': 24, 'ph': 72, 'alkalinity_mg_l': 336,
         'co2_mg_l': 72, 'tan_mg_l': 168, 'nitrite_n_mg_l': 168, 'nitrate_n_mg_l': 336, 'tgp_pct': 168,
         'salinity_ppt': 168, 'turbidity_ntu': 168, 'nh3_n_mg_l': 168, 'nh4_n_mg_l': 168,
         # formula 3's ionic-strength inputs (farm 0040): the conductivity at 25 °C 7 days, the hardness 14
         'conductivity_25_us_cm': 168, 'hardness_mg_l': 336}

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
