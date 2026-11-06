# A date typed into a page (core.widgets.DayInput, MomentInput, core.dates.read_day), day first as the language writes it:
# the first format is how an input shows it; ISO is read too (Django adds it). The other formats are Django's own.
DATE_INPUT_FORMATS = ['%d.%m.%Y', '%d.%m.%y']
DATETIME_INPUT_FORMATS = ['%d.%m.%Y %H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M']
