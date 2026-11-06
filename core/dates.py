"""A date typed into a page, in the person's language (config/formats/<language>/formats.py `DATE_INPUT_FORMATS`, ISO too):
the one reading of a list's date filter (?from=, ?to=, ?week=), as the forms' DayInput reads a field. A browser's own date
box says a date in the browser's language, not the page's, so no page has one (core/tests_date_inputs.py)."""
from datetime import datetime

from django.utils import formats


def read_day(text):
    """The date in `text` as the language writes it, or ISO (2026-10-26); None when it is empty or not a date."""
    text = (text or '').strip()
    if not text:
        return None
    for shape in formats.get_format('DATE_INPUT_FORMATS'):
        try:
            return datetime.strptime(text, shape).date()
        except ValueError:
            continue
    return None


def show_day(day):
    """A date as an input shows it: the language's first input format (26 Oct 2026, 26.10.2026)."""
    return formats.localize_input(day) if day else ''
