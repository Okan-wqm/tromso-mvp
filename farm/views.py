from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from core import audit
from core.crud import UpdateView, done
from core.models import AuditLog

from .forms import SiteContactFormSet
from .models import SiteContact
from .resources import SiteResource


def _contacts_summary(site):
    """The contact list as one line for the audit log, e.g. "Kari (Manager, kari@x.no, primary); Ola"."""
    def describe(contact):
        details = [value for value in (contact.role, contact.email, contact.phone) if value]
        if contact.is_primary:
            details.append('primary')
        return f'{contact.name} ({", ".join(details)})' if details else contact.name
    return '; '.join(describe(contact) for contact in site.contacts.all()) or None


def site_contacts(request, pk):
    """Saves a site's whole contact list at once, replacing the stored rows (as the source does).
    Editing contacts is part of editing the site, so it needs the site's change permission."""
    if not request.user.has_perm(SiteResource.perm('change')):
        raise PermissionDenied
    site = get_object_or_404(SiteResource.queryset(), pk=pk)
    edit_url = reverse(SiteResource.url_name('edit'), args=[pk])
    if request.method != 'POST':
        return redirect(edit_url)
    contacts = SiteContactFormSet(request.POST, instance=site, prefix='contacts')
    if not contacts.is_valid():
        page = UpdateView.as_page(SiteResource, request)
        return page.page(SiteResource.form(request, instance=site), site, contacts=contacts, open_tab='contact')
    rows = contacts.kept_rows()
    with transaction.atomic():
        before = _contacts_summary(site)
        site.contacts.all().delete()
        SiteContact.objects.bulk_create([
            SiteContact(site=site, created_by=request.user,
                        **{key: row[key] for key in ('name', 'role', 'email', 'phone', 'is_primary')})
            for row in rows
        ])
        after = _contacts_summary(site)
        if before != after:
            audit.record(request.user, AuditLog.Action.UPDATE, site, {'Contacts': [before, after]})
    messages.success(request, f'Contacts saved ({len(rows)}).')
    return done(request, edit_url, stay=True)
