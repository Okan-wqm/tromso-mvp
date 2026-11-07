# A date typed into a page and shown in a date box, the European way in every language (owner rule): dd.mm.yyyy and
# dd.mm.yyyy HH:MM on the 24-hour clock (core.widgets.DayInput, MomentInput, core.dates.read_day; frontend/date-input.ts
# puts what is typed so). ISO is read too (Django adds it).
DATE_INPUT_FORMATS = ['%d.%m.%Y']
DATETIME_INPUT_FORMATS = ['%d.%m.%Y %H:%M']
