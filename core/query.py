"""What a page reads from its address (`?page=2`, `?before=…`, `?year=2026`): one rule for the numbers and the years
of every query parameter (F-006, F-176, F-120). A value that is not well formed, or lies outside what a page can show,
is taken as not given (None), so the page shows its default as it does for a stale link, and never fails: digits
Python's `str.isdigit()` takes but `int()` does not (², ٣), a number past the database's bigint, a year outside the
calendar. Days, moments and periods are core.dates' (`read_day`, `read_moment`, `read_period`, cross review F8), whose
calendar the years here keep."""
import re

from . import dates

LARGEST = 2 ** 63 - 1      # a bigint, the widest whole number a query compares with

_DIGITS = re.compile(r'[0-9]{1,19}')


def number(value, *, least=0, most=LARGEST):
    """The whole number written in ASCII digits, from `least` to `most`; None for anything else (a sign, a space,
    another script's digits, an exponent)."""
    if not isinstance(value, str) or not _DIGITS.fullmatch(value):
        return None
    found = int(value)
    return found if least <= found <= most else None


def year(value):
    """A year of the calendar core.dates reads."""
    return number(value, least=dates.FIRST.year, most=dates.LAST.year)
