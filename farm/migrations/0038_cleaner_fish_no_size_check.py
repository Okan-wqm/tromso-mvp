"""A cleaner fish is not checked for mixed sizes unless the farm gives it a limit (owner decision, 2026-11-10: lumpfish and
wrasses are topped up with fish of other sizes). Migration 0034 gave every species the default 2; this empties the limit
of the species with a cleaner-fish type that still hold that default untouched, deleted ones too (0034 gave them the
default too), each change one row of the activity log (by 'system'). Untouched: the limit is 2 and no person's word
about it is in the log. A limit a person set stays, a 2 they changed it to too; a 2 that came with the species' own
creation through the form cannot be told from a typed one, so that species is left as it is and named in the migration's
output (review R11); salmon and every other production species are left alone.

Going back gives 2 back only where this took it and nobody chose since (read from the log), each logged."""
from decimal import Decimal

from django.db import migrations

from core.migrations._log import SYSTEM, entries, system_entry

DEFAULT = Decimal('2.00')                                  # what 0034 gave, and what the species form offers
LABEL = 'Max weight ratio of batches in one unit'           # how the log names the limit (the field's name)
EMPTIED = 'farm 0038: a cleaner fish is not checked for mixed sizes unless the farm gives it a limit (owner decision, ' \
          '2026-11-10); this species still held the default.'
GIVEN_BACK = 'farm 0038 reversed: the default this migration emptied is given back.'


def _read(connection):
    """({species id: whether the last word on its limit in the log is this migration's emptying}, the ids whose limit
    a person changed at some time, the ids whose limit a person gave when they made the species)."""
    ours, changed, given = {}, set(), set()

    class Editor:                                  # what core/migrations/_log reads through
        pass
    Editor.connection = connection
    for species_id, who, action, changes in entries(Editor, 'species'):
        if LABEL not in changes:
            continue
        note = (changes.get('Note') or [None, None])[1]
        if who == SYSTEM and note in (EMPTIED, GIVEN_BACK):
            ours[species_id] = note == EMPTIED
            continue
        ours[species_id] = False
        (changed if action == 'update' else given).add(species_id)
    return ours, changed, given


def _label(species):
    return f'{species.common_name} ({species.code})'


def sort(apps, connection):
    """(the cleaner species whose 2 is the untouched default of 0034, those whose 2 cannot be known to be untouched).
    Untouched: the limit is 2 and no person's word about it is in the log. A 2 a person changed it to is theirs and
    not listed at all. A 2 that came with the species' own creation through the form cannot be told from a typed one
    (review R11): it is left as it is and reported."""
    Species = apps.get_model('farm', 'Species')
    _ours, changed, given = _read(connection)
    at_default = Species._base_manager.exclude(cleaner_fish_type='').filter(max_weight_ratio=DEFAULT).order_by('code')
    untouched = [species for species in at_default if str(species.pk) not in changed | given]
    unknown = [species for species in at_default if str(species.pk) in given - changed]
    return untouched, unknown


def forward(apps, schema_editor):
    Species = apps.get_model('farm', 'Species')
    untouched, unknown = sort(apps, schema_editor.connection)
    for species in untouched:
        Species._base_manager.filter(pk=species.pk).update(max_weight_ratio=None)
        system_entry(schema_editor, 'species', species.pk, _label(species),
                     {LABEL: [f'{DEFAULT:.2f}', None], 'Note': [None, EMPTIED]})
    if untouched:
        print(f'\n  farm 0038: {len(untouched)} cleaner species still at the default size limit now have no check '
              f'(logged).')
    if unknown:
        print(f'\n  farm 0038: left as they are, their limit of 2 was given when they were made and may have been '
              f'typed: {", ".join(_label(species) for species in unknown)}. Empty it in Setup › Species if it was not.')
    return len(untouched)


def backward(apps, schema_editor):
    Species = apps.get_model('farm', 'Species')
    ours, _changed, _given = _read(schema_editor.connection)
    changed = 0
    for species in Species._base_manager.filter(max_weight_ratio__isnull=True).order_by('code'):
        if not ours.get(str(species.pk)):
            continue
        Species._base_manager.filter(pk=species.pk).update(max_weight_ratio=DEFAULT)
        system_entry(schema_editor, 'species', species.pk, _label(species),
                     {LABEL: [None, f'{DEFAULT:.2f}'], 'Note': [None, GIVEN_BACK]})
        changed += 1
    return changed


class Migration(migrations.Migration):
    dependencies = [
        ('farm', '0037_water_freshness'),
        ('core', '0007_audit_severity'),
    ]

    operations = [migrations.RunPython(forward, backward)]
