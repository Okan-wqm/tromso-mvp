# The English date look the console had before it had languages (day, short month, 24-hour clock), and every format a
# page uses (core/tests_templates.py DateFormatTests): Django's English short formats (10/26/2026, 9:04 p.m.) would be a
# second style. Turkish and Norwegian use Django's own formats for their language, already on the 24-hour clock.
DATE_FORMAT = 'j M Y'
DATETIME_FORMAT = 'j M Y, H:i'
TIME_FORMAT = 'H:i'
MONTH_DAY_FORMAT = 'j M'
