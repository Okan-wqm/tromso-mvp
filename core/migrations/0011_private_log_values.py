"""The personal data already in the activity log is made private (owner decision F-059 / F-061 / F-179 / F-050,
2026-11-10). From this migration on the code logs a contact's e-mail and phone and people's free text as private
values (core.audit.private: the enumerated "Private text" with a short keyed digest); the rows written before held them
in plain text, in a log nobody can erase from. This converts those values: what it does, value by value, is written in
core/migrations/_private.py, which `manage.py private_log_values` runs too (with `--dry-run` it writes nothing and says
what would be converted and which contact lists cannot be taken apart: run it on a copy before this migration runs on
real data).

Only what was decided private is hidden: a contact keeps its name, its role and whether it was the primary one, and
the row still says who was added or taken off.

**There is no way back.** The words are not kept anywhere, which is the point; the only way back is a backup taken
before this ran. So going back over this migration is refused once it has converted a row (as alarms/0010 refuses);
on a database where it converted nothing, going back is free."""
from django.db import migrations

from . import _private


def convert(apps, schema_editor):
    counts = _private.convert(schema_editor)
    if counts['rows']:
        print(f'\n  core 0011: {counts["rows"]} activity-log row(s) converted:')
        print('\n'.join(_private.report([], {**counts, 'whole_ids': []})))
        if counts['whole_ids']:
            print(f'  made private whole (also in the log\'s row): {", ".join(counts["whole_ids"])}')
    return counts


def no_way_back(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        times = _private.converted(cursor)
    if times:
        raise RuntimeError(
            'core 0011 cannot be reversed: it made the personal data in the activity log private, and the words are '
            'kept nowhere (that is what was decided). Restore a backup taken before it instead.')


class Migration(migrations.Migration):
    dependencies = [('core', '0010_clock_tolerance')]

    operations = [migrations.RunPython(convert, no_way_back)]
