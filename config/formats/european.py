# Owner rule: a date is shown and typed the European way in every language, dd.mm.yyyy, a date and time dd.mm.yyyy HH:MM on
# the 24-hour clock, a day and month dd.mm. (core/tests_templates.py, core/tests_date_inputs.py). One place: each language's
# formats module takes these; a month's name stays the language's (YEAR_MONTH_FORMAT: "October 2026"). ISO is read too
# (Django adds it to the input formats).
DATE_FORMAT = 'd.m.Y'
DATETIME_FORMAT = 'd.m.Y H:i'
TIME_FORMAT = 'H:i'
MONTH_DAY_FORMAT = 'd.m.'
SHORT_DATE_FORMAT = 'd.m.Y'
SHORT_DATETIME_FORMAT = 'd.m.Y H:i'
DATE_INPUT_FORMATS = ['%d.%m.%Y']
DATETIME_INPUT_FORMATS = ['%d.%m.%Y %H:%M']
