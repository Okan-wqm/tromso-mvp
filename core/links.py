"""A record's links to records of another table, edited in its form as a list of check boxes: the
systems a piece of equipment serves. Each link is a row of a through model that can carry more than
its two ends: which link is the primary one, and details such as a role. The field offers a box per
record that can be linked, a radio button for the primary link and the detail inputs beside each
box, and cleans them into unsaved rows of the through model; the form saves them with the record.

Which records are offered can depend on another field of the form, like DependentSelect: each row
carries `data-group`, the values of that field it fits (frontend/components.ts, data-depends-on).
The browser only guides; the field and the through model's own rules decide."""
from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .widgets import group_of


class LinkListWidget(forms.Widget):
    template_name = 'core/widgets/link_list.html'
    use_fieldset = True

    def __init__(self, attrs=None):
        super().__init__(attrs)
        self.records, self.details, self.detail_names = [], None, ()
        self.primary, self.depends_on, self.belongs_to, self.empty_text = False, '', {}, ''

    def value_from_datadict(self, data, files, name):
        """[{'pk', 'primary', <detail>: raw value}] for the ticked boxes, in the order posted."""
        primary = data.get(f'{name}-primary')
        ticked = data.getlist(name) if hasattr(data, 'getlist') else data.get(name, [])
        return [{'pk': pk, 'primary': pk == primary,
                 **{detail: data.get(f'{name}-{pk}-{detail}') for detail in self.detail_names}}
                for pk in dict.fromkeys(ticked)]

    def value_omitted_from_data(self, data, files, name):
        # Like check boxes: no box ticked is a value, not a missing one.
        return False

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        linked = {str(link['pk']): link for link in value or []}
        rows = []
        for index, record in enumerate(self.records):
            pk = str(record.pk)
            link = linked.get(pk)
            initial = {detail: link[detail] for detail in self.detail_names if link and link.get(detail) is not None}
            rows.append({
                'pk': pk, 'label': str(record), 'group': group_of(self.belongs_to, pk),
                'id': f'{context["widget"]["attrs"].get("id", name)}_{index}',
                'checked': link is not None, 'primary': bool(link and link['primary']),
                'details': self.details(prefix=f'{name}-{pk}', initial=initial) if self.details else None,
            })
        columns = [self.details.base_fields[detail].label for detail in self.detail_names] if self.details else []
        context['widget'].update(rows=rows, columns=columns, primary=self.primary, depends_on=self.depends_on,
                                 empty_text=self.empty_text)
        return context


class LinkList(forms.Field):
    """The links to records of `queryset`, as rows of `through` whose link to them is `target`;
    `details` are through-model fields edited beside each box, and `primary` names the flag that marks
    one link as the primary one. The cleaned value is the list of unsaved through rows (without the
    owner, which the form sets when it saves)."""

    widget = LinkListWidget
    default_error_messages = {
        'required': _('Choose at least one.'),
        'invalid_choice': _('Choose among the ones offered.'),
        'primary': _('Mark which one is the primary one.'),
    }

    def __init__(self, *, through, target, details=(), primary='', **kwargs):
        self.through, self.target, self.primary = through, target, primary
        self.detail_names = tuple(details)
        self.details_form = forms.modelform_factory(through, fields=list(details)) if details else None
        self.queryset = through._meta.get_field(target).related_model._default_manager.none()
        super().__init__(**kwargs)
        self.widget.details, self.widget.detail_names, self.widget.primary = (
            self.details_form, self.detail_names, bool(primary))

    def offer(self, queryset, depends_on='', belongs_to=None, empty_text=''):
        """The records that can be linked; with `depends_on`, `belongs_to` maps a record's pk to the
        values of that field it fits, and `empty_text` says why nothing is offered."""
        self.queryset = queryset
        self.widget.records, self.widget.depends_on = queryset, depends_on
        self.widget.belongs_to, self.widget.empty_text = belongs_to or {}, empty_text

    def clean(self, value):
        links = value or []
        if not links:
            if self.required:
                raise ValidationError(self.error_messages['required'], code='required')
            return []
        offered = {str(record.pk): record for record in self.queryset}
        if any(str(link['pk']) not in offered for link in links):
            raise ValidationError(self.error_messages['invalid_choice'], code='invalid_choice')
        rows, errors = [], []
        for link in links:
            record = offered[str(link['pk'])]
            row = self.through(**{self.target: record})
            if self.details_form:
                details = self.details_form({name: link.get(name) for name in self.detail_names})
                if details.is_valid():
                    for name in self.detail_names:
                        setattr(row, name, details.cleaned_data[name])
                for name, messages in details.errors.items():
                    errors += [ValidationError('%(record)s · %(field)s: %(error)s', params={
                        'record': record, 'field': details.fields[name].label if name in details.fields else '',
                        'error': message}) for message in messages]
            if self.primary:
                setattr(row, self.primary, len(links) == 1 or link['primary'])
            rows.append(row)
        if self.primary and sum(bool(getattr(row, self.primary)) for row in rows) != 1:
            errors.append(ValidationError(self.error_messages['primary'], code='primary'))
        if errors:
            raise ValidationError(errors)
        return rows
