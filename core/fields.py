"""Model fields the tabs share."""
from django import forms
from django.contrib.postgres.fields import ArrayField
from django.db import models


class ChoiceArrayField(ArrayField):
    """Several values of one list of choices, e.g. everything a supplier supplies: a PostgreSQL array of
    the base field's choices, shown in a form as a check box per choice. The values are stored once each,
    in the order of the choices, whatever wrote them. The model adds the database checks it needs (the
    values among the choices, at least one), and the activity log shows the labels (core.audit)."""

    def formfield(self, **kwargs):
        # ArrayField's own form field is a comma-separated text box; a list of choices is check boxes.
        defaults = {
            'form_class': forms.TypedMultipleChoiceField, 'choices': self.base_field.choices,
            'coerce': self.base_field.to_python, 'widget': forms.CheckboxSelectMultiple,
        }
        return models.Field.formfield(self, **{**defaults, **kwargs})

    def pre_save(self, model_instance, add):
        values = getattr(model_instance, self.attname)
        if values is not None:
            order = {value: index for index, value in enumerate(choice for choice, _ in self.base_field.flatchoices)}
            values = sorted(dict.fromkeys(values), key=lambda value: order.get(value, len(order)))
            setattr(model_instance, self.attname, values)
        return values
