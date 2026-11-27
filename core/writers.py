"""One writer per record, held at run time (the review of wip/hr-one-path, N-2 c).

A model that declares `service_written = True` (core.models.AuditedModel) is written by its app's `services.py` only.
Rule S of core/tests_data_access.py reads the code for a second writer by name; a row held in a variable, a related
manager or a form's `save()` is not a name, so the model itself refuses them: its `save`, `delete` and its managers'
`update`, `delete`, `bulk_create` and `bulk_update` (core.models) ask `require`, which raises NotTheWriter unless the
write happens inside the writing context of the model's app. The whole suite drives every page and command, so it is
the witness that nothing but the service writes.

- **The service enters it.** `services.py` decorates each function that writes with `writer('<app label>')`
  (`writing` is the same as a context manager). Nothing else in the production code enters it: rule S reads every
  module for `writing(` and `writer(` and lists none outside a `services.py`.
- **A builder of rows as stored enters it with its reason**: the test world (core/test_world.py), which makes the rows
  the recorded fixtures and the development tools show, not through the pages.
- **A test's own fixture row passes**: a write made directly by a test module (its helpers included: a file under a
  `tests` folder, or named `test_*.py`, `tests_*.py` or `tests.py`) is the test laying out what the code under test
  then reads. Only the DIRECT caller counts: production code a test drives (a view, a command, crud, the delete plan)
  is held like in production.
- **A migration** works on historical models, which have neither the model's methods nor its managers: nothing to
  enter. A RunPython that imports the real model of such a table would have to enter `writing` with its reason.

Not held: a write through `Model._base_manager` (Django's own plain manager, which `save()` itself uses) or raw SQL;
rule S reads the code for the first by name, rule W for the second."""
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

import django

_entered = ContextVar('one_writer_entered', default=())
_DJANGO = str(Path(django.__file__).resolve().parent)
_OWN = (str(Path(__file__).resolve()), str(Path(__file__).resolve().parent / 'models.py'))


class NotTheWriter(RuntimeError):
    """A record its service alone writes was written from somewhere else: a programming error, never a person's."""


@contextmanager
def writing(app_label, reason):
    """Inside it, the models of `app_label` that declare `service_written` may be written. `reason`: who enters and
    why (a service's own function, or why a builder writes rows as stored)."""
    if not reason:
        raise ValueError('core.writers.writing needs its reason: who writes these rows and why.')
    token = _entered.set((*_entered.get(), app_label))
    try:
        yield
    finally:
        _entered.reset(token)


def writer(app_label):
    """Decorates a function of `<app_label>/services.py` that writes: its body runs in the app's writing context."""
    def decorate(function):
        @wraps(function)
        def inside(*args, **kwargs):
            with writing(app_label, function.__qualname__):
                return function(*args, **kwargs)
        return inside
    return decorate


def _test_module(filename):
    path = Path(filename)
    return 'tests' in path.parts or path.name == 'tests.py' or path.name.startswith(('test_', 'tests_'))


def _a_tests_own_row():
    """Whether the write's direct caller (the first frame outside Django and the model's own code) is a test module."""
    frame = sys._getframe(2)
    while frame is not None:
        filename = frame.f_code.co_filename
        if not filename.startswith(_DJANGO) and filename not in _OWN:
            return _test_module(filename)
        frame = frame.f_back
    return False


def require(model, what):
    """Refuses a write (`what`: save, update, ...) of a `service_written` model outside its app's writing context."""
    if not getattr(model, 'service_written', False) or model._meta.app_label in _entered.get() or _a_tests_own_row():
        return
    raise NotTheWriter(
        f'{model.__name__}.{what}: {model._meta.app_label}/services.py is the one writer of {model.__name__} '
        f'(service_written). Call the service; a tab hands its save to it (core.crud.Resource.service_writes).')
