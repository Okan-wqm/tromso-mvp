from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from core import audit
from core.models import AuditLog

from .forms import SiteContactFormSet, SiteForm
from .models import Site, SiteContact

STALE_MESSAGE = ('Someone else changed this site while you were editing it. '
                 'The form now shows their version; make your changes again.')

# The audit log tracks every field the site form edits, under the form's labels.
SITE_AUDIT_FIELDS = SiteForm.Meta.fields
SITE_AUDIT_LABELS = SiteForm.Meta.labels


def _contacts_summary(site):
    """The contact list as one line for the audit log, e.g. "Kari (Manager, kari@x.no, primary); Ola"."""
    def describe(contact):
        details = [value for value in (contact.role, contact.email, contact.phone) if value]
        if contact.is_primary:
            details.append('primary')
        return f'{contact.name} ({", ".join(details)})' if details else contact.name
    return '; '.join(describe(contact) for contact in site.contacts.all()) or None


def site_list(request):
    query = request.GET.get('q', '').strip()
    sites = Site.objects.all()
    if query:
        sites = sites.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(region__icontains=query))
    return render(request, 'farm/site_list.html', {'sites': sites, 'query': query})


def site_create(request):
    form = SiteForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            site = form.save(commit=False)
            site.created_by = site.updated_by = request.user
            site.save()
            audit.record_create(request.user, site, SITE_AUDIT_FIELDS, SITE_AUDIT_LABELS)
        messages.success(request, f'Site “{site.name}” created. You can add its contacts now.')
        return redirect('farm:site_edit', pk=site.pk)
    return render(request, 'farm/site_form.html', {'form': form, 'site': None})


def _edit_page(request, site, form, contacts, **extra):
    history = AuditLog.objects.filter(entity_type=Site._meta.verbose_name, entity_id=str(site.pk))[:20]
    return render(request, 'farm/site_form.html', {
        'form': form, 'site': site, 'contacts': contacts, 'history': history, **extra,
    })


def site_edit(request, pk):
    site = get_object_or_404(Site, pk=pk)
    form = SiteForm(request.POST or None, instance=site)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            current = Site.objects.select_for_update().get(pk=pk)
            if form.cleaned_data.get('version') != current.version:
                messages.error(request, STALE_MESSAGE)
                return redirect('farm:site_edit', pk=pk)
            before = audit.snapshot(current, SITE_AUDIT_FIELDS, SITE_AUDIT_LABELS)
            site = form.save(commit=False)
            site.version = current.version + 1
            site.updated_by = request.user
            site.save()
            audit.record_update(request.user, site, before, SITE_AUDIT_FIELDS, SITE_AUDIT_LABELS)
        messages.success(request, f'Site “{site.name}” saved.')
        return redirect('farm:site_list')
    return _edit_page(request, site, form, SiteContactFormSet(instance=site, prefix='contacts'))


def site_contacts(request, pk):
    """Saves the whole contact list at once, replacing the stored rows (as the source does)."""
    site = get_object_or_404(Site, pk=pk)
    if request.method != 'POST':
        return redirect('farm:site_edit', pk=pk)
    contacts = SiteContactFormSet(request.POST, instance=site, prefix='contacts')
    if contacts.is_valid():
        rows = contacts.kept_rows()
        with transaction.atomic():
            before = _contacts_summary(site)
            site.contacts.all().delete()
            SiteContact.objects.bulk_create([
                SiteContact(
                    site=site, created_by=request.user,
                    **{key: row[key] for key in ('name', 'role', 'email', 'phone', 'is_primary')},
                )
                for row in rows
            ])
            after = _contacts_summary(site)
            if before != after:
                audit.record(request.user, AuditLog.Action.UPDATE, site, {'Contacts': [before, after]})
        messages.success(request, f'Contacts saved ({len(rows)}).')
        return redirect('farm:site_edit', pk=pk)
    return _edit_page(request, site, SiteForm(instance=site), contacts, open_tab='contact')


def site_delete(request, pk):
    site = get_object_or_404(Site, pk=pk)
    if request.method == 'POST':
        with transaction.atomic():
            site.soft_delete(request.user)
            audit.record_delete(request.user, site)
        messages.success(request, f'Site “{site.name}” deleted.')
        return redirect('farm:site_list')
    return render(request, 'farm/site_confirm_delete.html', {'site': site})
