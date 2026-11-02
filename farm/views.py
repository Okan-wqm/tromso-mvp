from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import SiteContactFormSet, SiteForm
from .models import Site, SiteContact

STALE_MESSAGE = ('Someone else changed this site while you were editing it. '
                 'The form now shows their version; make your changes again.')


def site_list(request):
    query = request.GET.get('q', '').strip()
    sites = Site.objects.all()
    if query:
        sites = sites.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(region__icontains=query))
    return render(request, 'farm/site_list.html', {'sites': sites, 'query': query})


def site_create(request):
    form = SiteForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        site = form.save(commit=False)
        site.created_by = site.updated_by = request.user
        site.save()
        messages.success(request, f'Site “{site.name}” created. You can add its contacts now.')
        return redirect('farm:site_edit', pk=site.pk)
    return render(request, 'farm/site_form.html', {'form': form, 'site': None})


def site_edit(request, pk):
    site = get_object_or_404(Site, pk=pk)
    form = SiteForm(request.POST or None, instance=site)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            current = Site.objects.select_for_update().get(pk=pk)
            if form.cleaned_data.get('version') != current.version:
                messages.error(request, STALE_MESSAGE)
                return redirect('farm:site_edit', pk=pk)
            site = form.save(commit=False)
            site.version = current.version + 1
            site.updated_by = request.user
            site.save()
        messages.success(request, f'Site “{site.name}” saved.')
        return redirect('farm:site_list')
    contacts = SiteContactFormSet(instance=site, prefix='contacts')
    return render(request, 'farm/site_form.html', {'form': form, 'site': site, 'contacts': contacts})


def site_contacts(request, pk):
    """Saves the whole contact list at once, replacing the stored rows (as the source does)."""
    site = get_object_or_404(Site, pk=pk)
    if request.method != 'POST':
        return redirect('farm:site_edit', pk=pk)
    contacts = SiteContactFormSet(request.POST, instance=site, prefix='contacts')
    if contacts.is_valid():
        rows = contacts.kept_rows()
        with transaction.atomic():
            site.contacts.all().delete()
            SiteContact.objects.bulk_create([
                SiteContact(
                    site=site, created_by=request.user,
                    **{key: row[key] for key in ('name', 'role', 'email', 'phone', 'is_primary')},
                )
                for row in rows
            ])
        messages.success(request, f'Contacts saved ({len(rows)}).')
        return redirect('farm:site_edit', pk=pk)
    form = SiteForm(instance=site)
    return render(request, 'farm/site_form.html', {
        'form': form, 'site': site, 'contacts': contacts, 'open_tab': 'contact',
    })


def site_delete(request, pk):
    site = get_object_or_404(Site, pk=pk)
    if request.method == 'POST':
        site.soft_delete(request.user)
        messages.success(request, f'Site “{site.name}” deleted.')
        return redirect('farm:site_list')
    return render(request, 'farm/site_confirm_delete.html', {'site': site})
