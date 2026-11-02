from django import forms


def group_of(values):
    """`data-group`: the value of the other field a choice belongs to, or several, space-separated
    (a parent pump belongs to every production department of its site)."""
    if values is None:
        return ''
    if isinstance(values, (list, tuple, set)):
        return ' '.join(sorted(str(value) for value in values))
    return str(values)


class DependentSelect(forms.Select):
    """A select whose options belong to the value of another field of the form: a production
    department belongs to a site, a parent system to a site. Each option carries `data-group`, the
    value (or values) of the other field it belongs to; the browser shows only the options of the
    chosen value (frontend/components.ts, `data-depends-on`). The server checks the same rule when it
    validates, so the browser only keeps the choice honest while editing."""

    def __init__(self, depends_on, belongs_to, attrs=None):
        super().__init__({**(attrs or {}), 'data-depends-on': depends_on})
        self.belongs_to = belongs_to   # {option value: value of the other field, or a list of them}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        group = group_of(self.belongs_to.get(str(value)))
        if group:
            option['attrs']['data-group'] = group
        return option

    @classmethod
    def apply(cls, field, depends_on, belongs_to):
        """Makes a model choice field depend on another field, keeping its queryset, choices and attributes."""
        field.widget = cls(depends_on, belongs_to, attrs=field.widget.attrs)
        field.widget.is_required = field.required
        field.widget.choices = field.choices
