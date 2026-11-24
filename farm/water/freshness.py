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
    return {'hours': dict(WaterFreshness.objects.values_list('parameter', 'fresh_hours')),
            'tolerance': timedelta(seconds=PlatformSettings.get().clock_tolerance_seconds)}


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
