from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core.crud import RowList


class ContactList(RowList):
    """A record's contact persons, saved as a whole list on its Contact tab (a site's, a supplier's).
    A tab sets `formset` (farm.forms.contact.contact_formset)."""

    key, tab, label = 'contacts', 'contact', _('Contacts')
    saved = ngettext_lazy('%(count)d contact saved.', '%(count)d contacts saved.', 'count')

    @classmethod
    def describe(cls, contact):
        """e.g. "Kari (Manager, kari@x.no, primary)"; the word "primary" is stored in English."""
        details = [value for value in (contact.role, contact.email, contact.phone) if value]
        if contact.is_primary:
            details.append(gettext('primary'))
        return f'{contact.name} ({", ".join(details)})' if details else contact.name
