"""The data-layer gate of the medicine withdrawal (cross-review 2 of F-195/F-196, closed further by cross-review 3): the
facts a withdrawal is worked out from refuse a change made anywhere but inside the withdrawal guard
(farm.health.withdrawal.guarded), which asks the person about what the change does to the withdrawals first.

REGISTRY names the inputs: a model whose every write counts (None), or the fields of a model whose other fields do not
(a feed's type, a species' assumed water temperature, a unit's loop, a sampling point's active flag, kind and owner); a
new row of such a model, and a write of its other fields, is free. A treatment's units count from either side of the
link and through the link table itself (registered as a model of its own). A field is the field whichever name says it:
`unit` and its column `unit_id` alike.

CONDITIONAL names the fields whose change counts only for some rows, each with the rule that says which: a system, a
unit or a species deleted or restored while a withdrawal holds fish it reaches (its loop's samples, the fish in it, the
species' assumed temperature), a sampling point deleted or restored with water samples on it. The rule is given the row
as stored and returns the reason the change counts, or nothing. A queryset update or bulk update of such a field is not
seen row by row: it counts.

`install()` (the farm app's ready()) holds the rule for every way a row is written through the ORM: a model's save and
delete (pre_save, pre_delete; `loaddata` too: a fixture is a write like any other, loaded inside `opened()` when it is
meant to), a treatment's units (m2m_changed, from either side), and a queryset's update, delete, bulk create and bulk
update, for any manager or related manager. A refused write raises UnguardedWithdrawalWrite, a ValidationError, so every
form, the admin and the services say it as they say any refusal; nothing is written.

`opened(reason)` lets writes through: the guard opens it around the write it checks; a test fixture, a command or a data
correction that is meant to write behind the guard says so, with its reason (the explicit allowlist). Migrations work on
historical models, which the gate does not know. Raw SQL is not seen."""
import contextvars
from contextlib import contextmanager

from django.core.exceptions import ValidationError
from django.db.models import QuerySet, signals

_open = contextvars.ContextVar('withdrawal_gate', default=None)

REGISTRY = {}          # model -> None (every write) or the tuple of fields whose change counts
CONDITIONAL = {}       # model -> {field: rule(stored row) -> the reason its change counts, or None}


class UnguardedWithdrawalWrite(ValidationError):
    """A withdrawal input was changed outside the withdrawal guard."""


@contextmanager
def opened(reason):
    """Writes to the withdrawal inputs inside the block are let through: the guard's (it asks first), or a fixture's,
    a command's or a correction's that says why."""
    token = _open.set(reason)
    try:
        yield
    finally:
        _open.reset(token)


def is_open():
    return _open.get() is not None


def _refuse(model, what):
    if not is_open():
        raise UnguardedWithdrawalWrite(
            f'{model.__name__}: {what} outside the withdrawal guard (farm.health.withdrawal.guarded). A write that '
            f'changes what a medicine withdrawal is worked out from goes through it, so that what it does to the '
            f'withdrawals is asked first.')


def _field(model, name):
    """The model field a name says: `unit` and its column `unit_id` are the same field."""
    name = name.split('__')[0]
    for field in model._meta.concrete_fields:
        if name in (field.name, field.attname):
            return field
    return model._meta.get_field(name)


def _changed_fields(instance, fields):
    """The fields among `fields` of a stored row that this save changes (none for a row not stored yet)."""
    model = type(instance)
    attnames = {name: _field(model, name).attname for name in fields}
    stored = model._base_manager.filter(pk=instance.pk).values(*attnames.values()).first()
    if stored is None:
        return []
    return [name for name in fields if stored[attnames[name]] != getattr(instance, attnames[name])]


def _pre_save(sender, instance, raw=False, **kwargs):
    if is_open():
        return
    stored = raw or not instance._state.adding      # a fixture's row is new to the ORM, maybe not to the table
    if sender in REGISTRY:
        fields = REGISTRY[sender]
        if fields is None:
            _refuse(sender, 'a row written')
        elif stored and _changed_fields(instance, fields):
            _refuse(sender, f'{", ".join(fields)} changed')
    rules = CONDITIONAL.get(sender)
    if rules and stored:
        for name in _changed_fields(instance, list(rules)):
            reason = rules[name](sender._base_manager.get(pk=instance.pk))
            if reason:
                _refuse(sender, f'{name} changed ({reason})')


def _whole(model):
    return model in REGISTRY and REGISTRY[model] is None


def _pre_delete(sender, instance, **kwargs):
    if _whole(sender):
        _refuse(sender, 'a row deleted')


def _m2m_changed(sender, instance, action, model=None, **kwargs):
    """A link between two records changed from either side: the link table (`sender`), the record's own model or the
    other side's (`model`)."""
    if action in ('pre_add', 'pre_remove', 'pre_clear') and any(map(_whole, (sender, type(instance), model))):
        _refuse(type(instance), f'its {sender._meta.model_name} changed')


# Who recorded or changed a row and when: not what a withdrawal is worked out from. A person removed from the system has
# these set to NULL (SET_NULL) by a queryset update, which the gate lets through.
BOOKKEEPING = {'created_by', 'updated_by', 'deleted_by', 'created_at', 'updated_at'}


def _counts(queryset, names):
    """Whether a queryset update or bulk update of the fields `names` changes an input: of a whole input anything but
    its bookkeeping, else a registered or a conditional field."""
    model = queryset.model
    named = {_field(model, name).name for name in names}
    fields = REGISTRY.get(model, ())
    if fields is None:
        return not named <= BOOKKEEPING
    counted = {_field(model, name).name for name in fields} | set(CONDITIONAL.get(model, ()))
    return bool(counted & named)


_original = {}


def _wrap(name, check):
    original = getattr(QuerySet, name)
    _original[name] = original

    def method(self, *args, **kwargs):
        if (self.model in REGISTRY or self.model in CONDITIONAL) and check(self, args, kwargs):
            _refuse(self.model, f'a queryset {name}')
        return original(self, *args, **kwargs)

    method.__name__, method.__doc__ = name, original.__doc__
    setattr(QuerySet, name, method)


def _hold_link_table(model):
    """Django sends no pre_save or pre_delete for a link table it made itself (a many-to-many's): its row's own save and
    delete say it to the gate instead."""
    if getattr(model, '_withdrawal_gate_held', False):
        return
    save_base, delete = model.save_base, model.delete

    def held_save_base(self, *args, **kwargs):
        _pre_save(type(self), self, raw=kwargs.get('raw', False))
        return save_base(self, *args, **kwargs)

    def held_delete(self, *args, **kwargs):
        _pre_delete(type(self), self)
        return delete(self, *args, **kwargs)

    model.save_base, model.delete, model._withdrawal_gate_held = held_save_base, held_delete, True


def install(models, conditional=None):
    """Registers the inputs ({model: None or fields}; `conditional`: {model: {field: rule}}) and holds the rule (called
    once, from the farm app's ready())."""
    REGISTRY.update(models)
    CONDITIONAL.update(conditional or {})
    for model in models:
        if model._meta.auto_created:
            _hold_link_table(model)
    if _original:
        return
    signals.pre_save.connect(_pre_save, dispatch_uid='withdrawal_gate_pre_save')
    signals.pre_delete.connect(_pre_delete, dispatch_uid='withdrawal_gate_pre_delete')
    signals.m2m_changed.connect(_m2m_changed, dispatch_uid='withdrawal_gate_m2m')
    _wrap('update', lambda queryset, args, kwargs: _counts(queryset, kwargs))
    _wrap('delete', lambda queryset, args, kwargs: _whole(queryset.model))
    _wrap('bulk_create', lambda queryset, args, kwargs: _whole(queryset.model))
    _wrap('bulk_update', lambda queryset, args, kwargs: _counts(queryset, args[1] if len(args) > 1
                                                                 else kwargs.get('fields', ())))
