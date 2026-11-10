"""A cleaner fish is not checked for mixed sizes unless the farm gives it a limit (owner decision, 2026-11-10: lumpfish and
wrasses are topped up with fish of other sizes). Migration 0034 gave every species the default 2; this empties the limit
of the species with a cleaner-fish type that still hold that default untouched, deleted ones too (0034 gave them the
default too), each change one row of the activity log (by 'system'). Untouched: the limit is 2 and no person's change of
it is in the log. A limit a person set stays, a 2 they chose too; salmon and every other production species are left alone.

Going back gives 2 back only where this took it and nobody chose since (read from the log), each logged."""
from decimal import Decimal

from django.db import migrations

from core.migrations._log import SYSTEM, entries, system_entry

DEFAULT = Decimal('2.00')                                  # what 0034 gave, and what the species form offers
LABEL = 'Max weight ratio of batches in one unit'           # how the log names the limit (the field's name)
EMPTIED = 'farm 0038: a cleaner fish is not checked for mixed sizes unless the farm gives it a limit (owner decision, ' \
          '2026-11-10); this species still held the default.'
GIVEN_BACK = 'farm 0038 reversed: the default this migration emptied is given back.'


def _ours(schema_editor):
    """({species id: whether the last word on its limit in the log is this migration's emptying}, the ids whose limit a
    person changed at some time). A new species' first value is not a change: the form offers the default."""
    ours, chosen = {}, set()
    for species_id, who, action, changes in entries(schema_editor, 'species'):
        if LABEL not in changes:
            continue
        note = (changes.get('Note') or [None, None])[1]
        if who == SYSTEM and note in (EMPTIED, GIVEN_BACK):
            ours[species_id] = note == EMPTIED
        else:
            ours[species_id] = False
            if action == 'update':
                chosen.add(species_id)
    return ours, chosen


def _label(species):
    return f'{species.common_name} ({species.code})'


def forward(apps, schema_editor):
    Species = apps.get_model('farm', 'Species')
    _state, chosen = _ours(schema_editor)
    changed = 0
    for species in Species._base_manager.exclude(cleaner_fish_type='').filter(max_weight_ratio=DEFAULT).order_by('code'):
        if str(species.pk) in chosen:
            continue
        Species._base_manager.filter(pk=species.pk).update(max_weight_ratio=None)
        system_entry(schema_editor, 'species', species.pk, _label(species),
                     {LABEL: [f'{DEFAULT:.2f}', None], 'Note': [None, EMPTIED]})
        changed += 1
    if changed:
        print(f'\n  farm 0038: {changed} cleaner species still at the default size limit now have no check (logged).')
    return changed


def backward(apps, schema_editor):
    Species = apps.get_model('farm', 'Species')
    ours, _chosen = _ours(schema_editor)
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
