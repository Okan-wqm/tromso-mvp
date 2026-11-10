from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core import audit
from core.crud import RowList


class ContactList(RowList):
    """A record's contact persons, saved as a whole list on its Contact tab (a site's, a supplier's).
    A tab sets `formset` (farm.forms.contact.contact_formset)."""

    key, tab, label = 'contacts', 'contact', _('Contacts')
    saved = ngettext_lazy('%(count)d contact saved.', '%(count)d contacts saved.', 'count')

    @classmethod
    def describe(cls, contact):
        """e.g. "Kari (Manager, email #1a2b3c4d, primary)"; the words are stored in English. The log names the contact
        (name, role) and keeps the e-mail and the phone private: each is said by the log's keyed digest
        (core.audit.digest), so a changed address is a change the log shows and two contacts with one address read as
        equal, and the address itself is never written into the log, which nobody can erase from (owner decision
        F-059, 2026-11-10; docs/erasure.md)."""
        details = [contact.role] if contact.role else []
        details += [f'{word} #{audit.digest(value)}' for word, value in (('email', contact.email), ('phone', contact.phone))
                    if value]
        if contact.is_primary:
            details.append(gettext('primary'))
        return f'{contact.name} ({", ".join(details)})' if details else contact.name
