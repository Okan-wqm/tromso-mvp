"""Keyset paging: a list that grows for ever (a ledger, the activity log, water samples) is read a page after the last
row shown (`?after=<cursor>`), `size` + 1 rows to know whether there is more, never counted (no COUNT(*)) and never
offset, so a page costs the same after ten years. The order is a tuple of model fields ending with a unique one (the
tie-break), none of them nullable. The cursor is the last row's order values, base64url JSON; a broken one gives the
first page and says so (`invalid`), never an error page.

Size: 50 by default, at most 200, set once here. A bound cuts a list, never the input of a printed figure."""
import base64
import binascii
import json

from django.core.exceptions import ValidationError
from django.db.models import Q

DEFAULT_SIZE, MAX_SIZE = 50, 200


def _size(text):
    try:
        size = int(text)
    except (TypeError, ValueError):
        return DEFAULT_SIZE
    return max(1, min(MAX_SIZE, size))


class Keyset:
    def __init__(self, order, model, size=DEFAULT_SIZE, after=None, invalid=False):
        self.fields = []
        for name in order:
            descending = name.startswith('-')
            field = model._meta.get_field(name.lstrip('-'))
            if field.null:
                raise ValueError(f'Keyset order on {field.name}, which may be empty: a row would fall out of the pages.')
            self.fields.append((field, descending))
        last = self.fields[-1][0] if self.fields else None
        if last is None or not (last.primary_key or last.unique):
            raise ValueError('A keyset order ends with a unique field (the tie-break).')
        self.order = tuple(order)
        self.size, self.after, self.invalid = size, after, invalid

    @classmethod
    def parse(cls, request, order, model, size_param='size', after_param='after'):
        keyset = cls(order, model, size=_size(request.GET.get(size_param)))
        text = request.GET.get(after_param)
        if text:
            try:
                keyset.after = keyset.decode(text)
            except (ValueError, TypeError, ValidationError, binascii.Error, UnicodeDecodeError):
                keyset.invalid = True
        return keyset

    def decode(self, text):
        values = json.loads(base64.urlsafe_b64decode(text + '=' * (-len(text) % 4)).decode())
        if not isinstance(values, list) or len(values) != len(self.fields):
            raise ValueError('cursor shape')
        return [field.to_python(value) for (field, _descending), value in zip(self.fields, values)]

    def encode(self, row):
        values = [field.value_to_string(row) for field, _descending in self.fields]
        return base64.urlsafe_b64encode(json.dumps(values).encode()).decode().rstrip('=')

    def page(self, queryset):
        """(rows, next cursor or None): the page after the cursor, in the keyset's order."""
        queryset = queryset.order_by(*self.order)
        if self.after is not None:
            later = Q()
            for index, (field, descending) in enumerate(self.fields):
                step = Q(**{f'{field.name}__{"lt" if descending else "gt"}': self.after[index]})
                for (earlier, _d), value in zip(self.fields[:index], self.after[:index]):
                    step &= Q(**{earlier.name: value})
                later |= step
            queryset = queryset.filter(later)
        rows = list(queryset[:self.size + 1])
        if len(rows) > self.size:
            return rows[:self.size], self.encode(rows[self.size - 1])
        return rows, None
