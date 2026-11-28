from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.crud import BoundedModelForm, RowFormSet


class ContactForm(BoundedModelForm):
    """One row of a contact list (farm.models.contact.Contact); `contact_formset` gives it its model."""

    class Meta:
        fields = ['name', 'role', 'email', 'phone', 'is_primary']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('Name')}),
            'role': forms.TextInput(attrs={'placeholder': _('Role')}),
            'email': forms.EmailInput(attrs={'placeholder': _('Email')}),
            'phone': forms.TextInput(attrs={'placeholder': _('Phone'), 'type': 'tel'}),
            'is_primary': forms.CheckboxInput(attrs={'data-primary': ''}),
        }

    def validate_constraints(self):
        # The one-primary rule spans the whole list, which is saved as a full replace; the formset
        # checks it and the database constraint backs it up. Checking each row against the stored
        # rows would reject moving the primary flag from one contact to another.
        pass


class ContactFormSet(RowFormSet):
    def clean(self):
        super().clean()
        primaries = sum(
            1 for form in self.forms
            if form.cleaned_data.get('is_primary') and not form.cleaned_data.get('DELETE')
        )
        if primaries > 1:
            raise ValidationError(_('Only one contact can be the primary contact; %(count)d are marked.'),
                                  params={'count': primaries})


def contact_formset(parent_model, model):
    """The contact list of a record: a site's, a supplier's."""
    return forms.inlineformset_factory(parent_model, model, form=ContactForm, formset=ContactFormSet, extra=0,
                                       can_delete=True)
