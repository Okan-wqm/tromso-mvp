"""Periods as PostgreSQL compares them, for exclusion constraints ("no two rows of one thing overlap in time"):
`DateRange(first, last, '[]')` is the days a row covers, an empty last day is open; `InstantRange(in, out, '[)')`
is the stretch of time between two instants, an empty end runs to infinity."""
from django.contrib.postgres.fields import DateTimeRangeField, DateRangeField
from django.db.models import Func


class DateRange(Func):
    """daterange(lower, upper, bounds): the days an assignment covers; an empty upper end is open."""
    function = 'daterange'
    output_field = DateRangeField()


class InstantRange(Func):
    """tstzrange(lower, upper, bounds): the time between two instants (a punch in and out); an empty upper end is
    open."""
    function = 'tstzrange'
    output_field = DateTimeRangeField()
