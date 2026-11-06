"""What a page reads from its address (`?from=2026-11-06&page=2`): one rule for every query parameter (F-006, F-176,
F-120). A value that is not well formed, or lies outside what a page can show, is taken as not given (None), so the
page shows its default as it does for a stale link, and never fails: a misspelt or impossible date (2026-13-45), digits
Python's `str.isdigit()` takes but `int()` does not (², ٣), a number past the database's bigint, a date at the end of
the calendar a page then adds days to."""
import re
from datetime import date

# The days a page shows: wide enough for any farm record, narrow enough that a page may add or take a few years.
FIRST_DAY, LAST_DAY = date(1900, 1, 1), date(2999, 12, 31)
LARGEST = 2 ** 63 - 1      # a bigint, the widest whole number a query compares with

_DAY = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
_DIGITS = re.compile(r'[0-9]{1,19}')


def day(value):
    """The date written YYYY-MM-DD (as a date input and every link of the pages write it), between FIRST_DAY and
    LAST_DAY; None for anything else."""
    if not isinstance(value, str) or not _DAY.fullmatch(value):
        return None
    try:
        found = date.fromisoformat(value)
    except ValueError:
        return None
    return found if FIRST_DAY <= found <= LAST_DAY else None


def number(value, *, least=0, most=LARGEST):
    """The whole number written in ASCII digits, from `least` to `most`; None for anything else (a sign, a space,
    another script's digits, an exponent)."""
    if not isinstance(value, str) or not _DIGITS.fullmatch(value):
        return None
    found = int(value)
    return found if least <= found <= most else None


def year(value):
    """A year of the calendar the pages show."""
    return number(value, least=FIRST_DAY.year, most=LAST_DAY.year)
