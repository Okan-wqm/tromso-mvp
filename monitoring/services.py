"""Monitoring's writes besides its tabs (core.crud): the copy of a card template. Rules live here, never in a view (the
data-layering audit, L-1): who may (core.access.require), the one-time key of the button that asked (core.models.
EntryKey: a double click makes one copy), a name of its own taken even when another copy takes one at the same moment,
the copy logged as a new record."""
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from core import access, audit
from core.models import EntryKey, violated_constraint

from .models import CardTemplate

ADD = 'monitoring.add_cardtemplate'
NAME_TAKEN = 'uq_monitor_card_templates_name_live'
# How many names a copy tries when other copies take them at the same moment: each try reads the names again.
NAME_TRIES = 5


def copy_name(source):
    """'<name> (copy)', or '(copy 2)', '(copy 3)' … while the name is taken by a live template (any case)."""
    base = source.shown_name
    names = {name.lower() for name in CardTemplate.objects.values_list('name', flat=True)}
    candidate, number = _('%(name)s (copy)') % {'name': base}, 2
    while candidate.lower() in names:
        candidate = _('%(name)s (copy %(number)d)') % {'name': base, 'number': number}
        number += 1
    return candidate


def copy_template(user, source, key=None):
    """A copy of `source` (the way to change a built-in): its description, layout, measure and flip target, a name of
    its own, logged as a new record. `key`: the one-time key the button was sent with; the same key again returns the
    copy it made. Returns the copy."""
    from .resources import CardTemplateResource as resource
    access.require(user, ADD)
    for attempt in range(NAME_TRIES):
        if key is not None:
            made = EntryKey.record_of(key, CardTemplate)
            if made is not None:
                return made
        try:
            with transaction.atomic():
                copy = CardTemplate.objects.create(
                    name=copy_name(source), description=source.description, layout=source.layout,
                    schema_version=source.schema_version, expanded=source.expanded, measure_w=source.measure_w,
                    measure_h=source.measure_h, created_by=user, updated_by=user)
                if key is not None:
                    EntryKey.note(key, copy)
                audit.record_create(user, copy, resource.recorded(copy), entity_type=resource.entity_type())
            return copy
        except IntegrityError as error:
            # The same key sent at once (its row waited for the other's commit: the loop's top returns that copy), or
            # the name taken by another copy meanwhile (read the names again). Anything else is a fault.
            if key is not None and EntryKey.record_of(key, CardTemplate) is not None:
                continue
            clash = violated_constraint(CardTemplate, error)
            if clash is None or clash.name != NAME_TAKEN or attempt == NAME_TRIES - 1:
                raise
    return EntryKey.record_of(key, CardTemplate)
