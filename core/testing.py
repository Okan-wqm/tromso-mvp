"""The tests' clock. A test whose records are dated on fixed days must not read the day it runs on: the rules that count
from today (a record dated at most the correction window back, nothing in the future, a value's freshness) would fail
it, or pass it, by the calendar. `FrozenClock` holds the clock the code reads at one moment for a test class's whole
life, its class data included. That clock is `django.utils.timezone.now`: the code's days and moments come from it
(core.dates, farm.stock.dates; core/tests_company_clock.py refuses `date.today()` and the like). Not held: the
database's own clock (`now()` in SQL), and a model field's `default=timezone.now`, which keeps the real function it was
given when the model was read (core.AccountMail.alive_at, messaging's created_at): a row made without a value for it
carries the real moment.

Nor must a test read the hour it runs at. The server's day (UTC) and the company's (settings.COMPANY_TIME_ZONE, Oslo)
differ for an hour or two before every UTC midnight, and a site on a third zone differs for longer: a test that says
"today" on one clock while the code reads another passes all day and fails in those hours. `BAD_HOURS` are moments
inside them; core/tests_day_boundary.py runs the tests that count days again at each (`at_bad_hours`), and
`TEST_CLOCK` starts a whole run's clock at any moment (`run_clock`: scripts/test.sh passes it on), to look for more."""
import os
from datetime import datetime, timezone as dt_timezone
from unittest import mock

from core.modules import is_test_module  # noqa: F401  a re-export: production imports core.modules, never this module

CLOCK = 'django.utils.timezone.now'


# Moments at which the UTC day is not the company's (Europe/Oslo unless the environment names another). The first is
# the middle of the CI run that found the class (run 42921917659, 23:17 to 23:57 UTC on 10.11.2026).
BAD_HOURS = {
    'WinterNight': datetime(2026, 11, 10, 23, 30, tzinfo=dt_timezone.utc),      # 00:30 on the 11th in Oslo (UTC+1)
    'SummerNight': datetime(2026, 7, 10, 22, 30, tzinfo=dt_timezone.utc),       # 00:30 on the 11th in Oslo (UTC+2)
    'JustBeforeOslosMidnight': datetime(2026, 11, 10, 22, 59, 59, tzinfo=dt_timezone.utc),   # the same day on both
    'JustAfterOslosMidnight': datetime(2026, 11, 10, 23, 0, 0, tzinfo=dt_timezone.utc),      # Oslo is a day ahead
    'NewYearsEve': datetime(2026, 12, 31, 23, 30, tzinfo=dt_timezone.utc),      # 2027 in Oslo, 2026 on the server
}


class FrozenClock:
    """Mixed in before the TestCase: `timezone.now()` is NOW (an aware datetime) while the class's data is made
    (setUpTestData) and in every test of it, and the real clock again afterwards, also when the set-up fails."""
    NOW = None
    RUNS_ON = False             # StartedClock: the clock starts at NOW and runs on

    @classmethod
    def setUpClass(cls):
        if cls.NOW is None or cls.NOW.tzinfo is None:
            raise TypeError(f'{cls.__name__}.NOW is the moment its clock stands at: an aware datetime.')
        if cls.RUNS_ON:
            began = datetime.now(dt_timezone.utc)
            clock = mock.patch(CLOCK, side_effect=lambda: cls.NOW + (datetime.now(dt_timezone.utc) - began))
        else:
            clock = mock.patch(CLOCK, return_value=cls.NOW)
        clock.start()
        cls.addClassCleanup(clock.stop)
        super().setUpClass()


class StartedClock(FrozenClock):
    """As FrozenClock, but the clock starts at NOW when the class's data is made and runs on from there: for tests
    whose records must be made one after the other (the newest by `created_at`, a history in order), which a clock
    that stands gives the same moment. The day and the year are NOW's all the same (a class runs for seconds)."""
    RUNS_ON = True


def at_bad_hours(namespace, *cases, moments=BAD_HOURS):
    """Puts into `namespace` (a test module's globals()) one class per test class of `cases` and moment of `moments`:
    the same tests with the clock held at that moment (`<Case>At<Moment>`). The cases are given as attributes of their
    modules (`test_pages.WallTests`): a class imported by name would be collected a second time where it is imported."""
    for case in cases:
        for name, moment in moments.items():
            held = type(f'{case.__name__}At{name}', (FrozenClock, case), {
                'NOW': moment, '__module__': namespace['__name__'],
                '__doc__': f'{case.__module__}.{case.__name__} with the clock held at {moment.isoformat()}.'})
            namespace[held.__name__] = held


def run_clock(text=None):
    """The clock of a whole run started at the moment `text` (ISO, with its offset: 2026-11-10T23:30:00+00:00) and
    running on from there, or None without one (TEST_CLOCK in the environment unless given): started by the test runner
    before any test or class data (config/test_runner.py), in every worker. A class's FrozenClock still holds its own.
    The database's clock stays the real one, so a test that compares the two fails in such a run: it is a way to look
    for tests that read the hour, the day or the year they run in, not a way to run the suite. What fails by the run's
    own making, and says nothing of the code: the tests of this module (they compare with the real clock), a test that
    runs makemigrations (the clock is a mock where a migration names `timezone.now`), and the account mails' lease,
    whose rows carry the real moment from their field's default (the module's docstring) while the sweep reads the
    run's."""
    text = os.environ.get('TEST_CLOCK', '') if text is None else text
    if not text:
        return None
    start = datetime.fromisoformat(text)
    if start.tzinfo is None:
        raise ValueError(f'TEST_CLOCK {text!r} is the moment the run\'s clock starts at: give its offset (+00:00).')
    began = datetime.now(dt_timezone.utc)
    clock = mock.patch(CLOCK, side_effect=lambda: start + (datetime.now(dt_timezone.utc) - began))
    clock.start()
    return clock


def platform_settings_data(**overrides):
    """What the Platform settings form posts for the row as stored, with `overrides`: every field the form has (a new
    setting is taken along without touching the tests that post it), a ticked box as 'on' and an unticked one left out,
    as a browser sends them, and the row's version."""
    from core.forms import PlatformSettingsForm
    from core.models import PlatformSettings
    row = PlatformSettings.get()
    data = {'version': row.version}
    for name, field in PlatformSettingsForm.base_fields.items():
        if name == 'version' or not hasattr(row, name):
            continue
        data[name] = getattr(row, name)
    data.update(overrides)
    for name, value in list(data.items()):
        if isinstance(value, bool):
            if value:
                data[name] = 'on'
            else:
                del data[name]
    return data


def delete_confirmed(client, url, data=None, **extra):
    """Posts a tab's delete as its confirmation page does: with the version the confirmation shows of the record as it
    is now (core.crud.DeleteView refuses a delete without it, and one of a record changed since). When the
    confirmation does not open (a record the person may not reach, a route that is no tab's), the post goes as it is,
    so the refusal the test expects is the view's own. `data` and `extra` are the post's."""
    data = dict(data or {})
    if 'version' not in data:
        page = client.get(url, **extra)
        version = None
        if page.status_code == 200 and page.context is not None:
            try:
                version = page.context['version']
            except KeyError:
                try:
                    version = page.context['props'].get('version')
                except KeyError:
                    version = None
        if version is not None:
            data['version'] = version
    return client.post(url, data, **extra)
