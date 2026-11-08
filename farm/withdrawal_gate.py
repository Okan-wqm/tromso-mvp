"""The data-layer gate of the medicine withdrawal (cross-review 2 of F-195/F-196): the facts a withdrawal is worked out
from refuse a change made anywhere but inside the withdrawal guard (farm.health.withdrawal.guarded), which asks the
person about what the change does to the withdrawals first.

REGISTRY names the inputs: a model whose every write counts (None), or the fields of a model whose other fields do not
(a feed's type, a species' assumed water temperature, a sampling point's active flag, kind and owner); a new row of such
a model, and a write of its other fields, is free. `install()` (the farm app's ready()) holds the rule for every way a
row is written through the ORM: a model's save and delete (pre_save, pre_delete), a treatment's units (m2m_changed), and
a queryset's update, delete, bulk create and bulk update, for any manager or related manager. A refused write raises
UnguardedWithdrawalWrite and nothing is written.

`opened(reason)` lets writes through: the guard opens it around the write it checks; a test fixture, a command or a data
correction that is meant to write behind the guard says so, with its reason (the explicit allowlist). Migrations work on
historical models, which the gate does not know. Raw SQL is not seen."""
import contextvars
from contextlib import contextmanager

from django.db.models import QuerySet, signals

_open = contextvars.ContextVar('withdrawal_gate', default=None)

REGISTRY = {}          # model -> None (every write) or the tuple of fields whose change counts


class UnguardedWithdrawalWrite(Exception):
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


def _changed_fields(instance, fields):
    """The registered fields of a stored row that this save changes."""
    model = type(instance)
    stored = model._base_manager.filter(pk=instance.pk).values(*[model._meta.get_field(name).attname
                                                                  for name in fields]).first()
    if stored is None:
        return []
    return [name for name in fields if stored[model._meta.get_field(name).attname]
            != getattr(instance, model._meta.get_field(name).attname)]


def _pre_save(sender, instance, raw=False, **kwargs):
    if sender not in REGISTRY or raw:
        return
    fields = REGISTRY[sender]
    if fields is None:
        _refuse(sender, 'a row written')
    elif not instance._state.adding and _changed_fields(instance, fields):
        _refuse(sender, f'{", ".join(fields)} changed')


def _pre_delete(sender, instance, **kwargs):
    if sender in REGISTRY and REGISTRY[sender] is None:
        _refuse(sender, 'a row deleted')


def _m2m_changed(sender, instance, action, **kwargs):
    if action in ('pre_add', 'pre_remove', 'pre_clear') and type(instance) in REGISTRY \
            and REGISTRY[type(instance)] is None:
        _refuse(type(instance), f'its {sender._meta.model_name} changed')


# Who recorded or changed a row and when: not what a withdrawal is worked out from. A person removed from the system has
# these set to NULL (SET_NULL) by a queryset update, which the gate lets through.
BOOKKEEPING = {'created_by', 'updated_by', 'deleted_by', 'created_by_id', 'updated_by_id', 'deleted_by_id',
               'created_at', 'updated_at'}


def _counts(queryset, names):
    fields = REGISTRY.get(queryset.model, ())
    named = {name.split('__')[0] for name in names}
    if fields is None:
        return not named <= BOOKKEEPING
    return bool(set(fields) & named)


_original = {}


def _wrap(name, check):
    original = getattr(QuerySet, name)
    _original[name] = original

    def method(self, *args, **kwargs):
        if self.model in REGISTRY and check(self, args, kwargs):
            _refuse(self.model, f'a queryset {name}')
        return original(self, *args, **kwargs)

    method.__name__, method.__doc__ = name, original.__doc__
    setattr(QuerySet, name, method)


def install(models):
    """Registers the inputs ({model: None or fields}) and holds the rule (called once, from the farm app's ready())."""
    REGISTRY.update(models)
    if _original:
        return
    signals.pre_save.connect(_pre_save, dispatch_uid='withdrawal_gate_pre_save')
    signals.pre_delete.connect(_pre_delete, dispatch_uid='withdrawal_gate_pre_delete')
    signals.m2m_changed.connect(_m2m_changed, dispatch_uid='withdrawal_gate_m2m')
    _wrap('update', lambda queryset, args, kwargs: _counts(queryset, kwargs))
    _wrap('delete', lambda queryset, args, kwargs: REGISTRY[queryset.model] is None)
    _wrap('bulk_create', lambda queryset, args, kwargs: REGISTRY[queryset.model] is None)
    _wrap('bulk_update', lambda queryset, args, kwargs: _counts(queryset, args[1] if len(args) > 1
                                                                 else kwargs.get('fields', ())))
