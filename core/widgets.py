from datetime import datetime

from django import forms
from django.utils import formats

# The value of a choice that means "without one": a production department without a site, in a list's
# filter (core.crud.filter_by) and as the value a DependentSelect's source can take, so the choices that
# belong to no value of it (belongs_to None) can be offered too.
NONE = 'none'


def group_of(belongs_to, value):
    """`data-group` of the choice `value`: the value of the other field it belongs to, or several,
    space-separated (a parent pump belongs to every production department of its site); NONE when it
    belongs to none (a production department without a site, `belongs_to` maps it to None); '' (no group,
    never offered) when it belongs to nothing at all (an empty list) or is not in `belongs_to` (the empty
    choice, always offered)."""
    key = str(value)
    if key not in belongs_to:
        return ''
    values = belongs_to[key]
    if values is None:
        return NONE
    if isinstance(values, (list, tuple, set)):
        return ' '.join(sorted(str(item) for item in values))
    return str(values)


class DependentSelect(forms.Select):
    """A select whose options belong to the value of another field of the form: a production
    department belongs to a site, a parent system to a site. Each option carries `data-group`, the
    value (or values) of the other field it belongs to; the browser shows only the options of the
    chosen value (frontend/components.ts, `data-depends-on`). An option that belongs to no value of the
    other field (`belongs_to` maps it to None: a production department without a site) is shown when the
    other field is set to NONE, which a source offers as a choice of its own ("Without a site"), so such
    an option can be chosen like any other. The server checks the same rule when it validates, so the
    browser only keeps the choice honest while editing."""

    def __init__(self, depends_on, belongs_to, attrs=None):
        super().__init__({**(attrs or {}), 'data-depends-on': depends_on})
        self.belongs_to = belongs_to   # {option value: value of the other field, a list of them, or None}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        group = group_of(self.belongs_to, value)
        if group:
            option['attrs']['data-group'] = group
        return option

    @classmethod
    def apply(cls, field, depends_on, belongs_to):
        """Makes a choice field depend on another field, keeping its queryset, choices and attributes."""
        field.widget = cls(depends_on, belongs_to, attrs=field.widget.attrs)
        field.widget.is_required = field.required
        field.widget.choices = field.choices


class Output(forms.Widget):
    """A value the form shows but nobody types, worked out from the record: a tank's volume, the date
    its status changed. It renders as an <output> element (a dash when there is no value), so it reads
    as a result, not as a field that is switched off. Put it on a disabled field: Django then never reads
    a posted value for it."""

    template_name = 'core/widgets/output.html'

    def value_omitted_from_data(self, data, files, name):
        return True


# ---- a date and a moment, in the person's language ------------------------------------------------------------------
# A browser's own date box says a date in the browser's language, not the page's (11/06/2026 09:19 AM beside 6 Nov 2026),
# so a date is a text box in the language's own input format (config/formats/<language>/formats.py, ISO read too), the
# example of the format as its placeholder. Every form takes these (core/tests_date_inputs.py).
EXAMPLE = datetime(2026, 10, 26, 7, 30)


class DayInput(forms.DateInput):
    input_type = 'text'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget']['attrs'].setdefault('placeholder', formats.localize_input(EXAMPLE.date()))
        context['widget']['attrs'].setdefault('autocomplete', 'off')
        return context


class MomentInput(forms.DateTimeInput):
    input_type = 'text'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget']['attrs'].setdefault('placeholder', formats.localize_input(EXAMPLE))
        context['widget']['attrs'].setdefault('autocomplete', 'off')
        return context
