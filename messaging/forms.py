"""The forms of Messages. They only read what was entered; every rule is the service's (messaging/services.py),
whose refusals come back on the field they concern (`refused`)."""
from django import forms
from django.utils.translation import gettext_lazy as _

from . import services
from .models import MAX_BODY, Participant, person_name


class PersonChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return person_name(obj)


class PeopleChoice(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return person_name(obj)


class ServiceForm(forms.Form):
    def refused(self, error):
        """Puts the service's reasons on the form: on their field, else above the form."""
        if hasattr(error, 'error_dict'):
            for field, errors in error.error_dict.items():
                self.add_error(field if field in self.fields else None, errors)
        else:
            self.add_error(None, error)


class MessageForm(ServiceForm):
    body = forms.CharField(label=_('Message'), max_length=MAX_BODY,
                           widget=forms.Textarea(attrs={'rows': 2, 'data-submit-on-enter': ''}))


class DirectForm(ServiceForm):
    person = PersonChoice(queryset=None, label=_('Person'), empty_label=_('Choose a person'))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['person'].queryset = services.contacts(user)


class ChannelForm(ServiceForm):
    name = forms.CharField(label=_('Channel name'), max_length=80)
    members = PeopleChoice(queryset=None, required=False, label=_('Members'), widget=forms.CheckboxSelectMultiple,
                           help_text=_('You are its owner. People who cannot use Messages are not listed.'))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['members'].queryset = services.contacts(user)


class AddMembersForm(ServiceForm):
    people = PeopleChoice(queryset=None, label=_('Add members'), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, conversation, **kwargs):
        super().__init__(*args, **kwargs)
        inside = conversation.participants.exclude(user=None).values('user')
        self.fields['people'].queryset = services.contacts().exclude(pk__in=inside)


class RoleForm(ServiceForm):
    role = forms.ChoiceField(choices=Participant.Role.choices)
