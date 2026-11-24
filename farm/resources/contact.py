from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core import audit
from core.crud import RowList


class ContactList(RowList):
    """A record's contact persons, saved as a whole list on its Contact tab (a site's, a supplier's).
    A tab sets `formset` (farm.forms.contact.contact_formset)."""

    key, tab, label = 'contacts', 'contact', _('Contacts')
    saved = ngettext_lazy('%(count)d contact saved.', '%(count)d contacts saved.', 'count')
    # Its panel on the Contact tab, in farm/_contacts.html's words (a record adds its help and pending sentence).
    title, legend = _('Contacts'), _('Contact')
    empty_text = _('No contacts yet. Use “Add contact” to add a row.')
    add_label, save_label = _('Add contact'), _('Save contacts')
    headed, on_record_tab = False, True
    field_labels = {'is_primary': _('Primary')}
    # The fields of a contact the log keeps private, in the order it says them, each under its field's name.
    PRIVATE = ('email', 'phone')

    @classmethod
    def describe(cls, contact):
        """e.g. "Kari (Manager, primary)": who the contact is, in plain text; the word "primary" is stored in English."""
        details = [contact.role] if contact.role else []
        if contact.is_primary:
            details.append(gettext('primary'))
        return f'{contact.name} ({", ".join(details)})' if details else contact.name

    @classmethod
    def parts(cls, contact):
        """A contact as the log keeps it: who it is (`describe`), then the e-mail and the phone when given, each as a
        private value that says which it is (core.audit.private: the page shows "Email: Private text"). The address
        and the number are never written into the log, which nobody can erase from; their digests are stored so that
        a change is a change, and shown on no page (owner decision F-059, review R2; docs/erasure.md)."""
        return [cls.describe(contact), *(
            audit.private(getattr(contact, name), contact._meta.get_field(name).verbose_name)
            for name in cls.PRIVATE if getattr(contact, name))]

    @classmethod
    def summary(cls, obj):
        """The list as the log keeps it: one list of parts per contact, None for no contacts."""
        return [cls.parts(contact) for contact in cls.rows(obj)] or None
