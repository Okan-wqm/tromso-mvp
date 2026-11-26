"""The new look's list (core/listprops.py, island `list-page`) of Operations › Health events (farm/resources/
health_event.py: `list_rows`, `list_filters`), worded as templates/farm/health_event_list.html words it (the same msgids)
from the rows and the context the one list view (core.crud.ListView) read for the classic page.

Safety: a listed disease suspected or confirmed and not yet notified raises "Notify Mattilsynet" as a critical notice
above the list, with each event and the way to file its notice (farm/health/notices.py); on its row "Notify at once" is
its Mattilsynet cell, in a critical chip. Whether Mattilsynet was told is the server's (`told`); not checked says "—"
as on the classic page, never "Notified"."""
from django.template.defaultfilters import truncatechars
from django.urls import reverse
from django.utils import formats
from django.utils.translation import gettext as _

from core import listprops as L
from core.templatetags.dates import site_clock

from .. import words
from ..templatetags.health import event_voidable, told_of
from ..templatetags.stock import fish

DASH = '—'


def event_filters(view, context):
    return [
        L.choice('site', str(words.SITE), context['chosen_site'],
                 [('', str(words.ALL_SITES)), *((site.pk, site.name) for site in context['sites'])]),
        L.choice('kind', str(words.KIND), context['chosen_kind'], [('', str(words.ALL_KINDS)), *context['kinds']]),
        L.choice('state', str(words.STATUS), context['chosen_state'], [('', str(words.OPEN_AND_CLOSED)), *context['states']]),
        L.check('voided', str(words.SHOW_VOIDED), context['show_voided']),
    ]


def _event(view, context, event):
    sub = []
    if event.diagnosis:
        disease = event.disease
        sub.append(f'{event.get_diagnosis_display()} · {event.get_confirmation_display()}'
                   + (f' ({disease.local_name})' if disease.local_name else '') + f' · {disease.listing_label}')
    if event.findings:
        sub.append(truncatechars(event.findings, 120))
    editable = context.get('can_change') and not event.is_deleted
    return L.cell(event.get_kind_display(), href=view.url('edit', event.pk) if editable else None, strong=True, sub=sub)


def _told(context, event):
    """Mattilsynet: notified (when), "Notify at once" (critical) while it is not and the notices were read, else "—"."""
    if not event.notifiable:
        return L.cell(DASH), None
    notified = told_of(context['told'], event)
    if notified:
        return L.cell(_('Notified %(moment)s') % {
            'moment': formats.date_format(site_clock(notified.at, event.site), 'DATETIME_FORMAT')}), None
    if context['told'] is not None and not event.is_deleted:
        return L.cell(chip=L.chip('critical', str(words.NOTIFY_AT_ONCE))), 'critical'
    return L.cell(DASH), None


def _closed(event):
    sub = [truncatechars(event.outcome, 80) if event.closed_on and event.outcome else '']
    if event.is_deleted:
        sub.append(_('voided by %(name)s: %(reason)s') % {
            'reason': event.void_reason, 'name': event.deleted_by.get_username() if event.deleted_by else 'system'})
    if event.closed_on:
        return L.cell(formats.date_format(event.closed_on, 'DATE_FORMAT'), sub=sub)
    return L.cell(chip=L.chip('accent', str(words.OPEN_2)), sub=sub)


def events(view, objects, context):
    """Health events: what was seen, found or advised, where, the signs, Mattilsynet, who examined, the deaths recorded
    under it and whether it is closed; Edit and Void (with its reason) for a person who may."""
    rows = []
    for event in objects:
        told, status = _told(context, event)
        actions = []
        if not event.is_deleted:
            if context.get('can_change'):
                actions.append(L.link(view.url('edit', event.pk), str(words.EDIT), 'pencil'))
            if context.get('can_void') and event_voidable(event):
                actions.append(L.link(reverse('farm:healthevent_void', args=[event.pk]), str(words.VOID), 'x', danger=True,
                                      labelled=True))
        units = [unit.code for unit in event.units.all()]
        examined = [event.vet.name if event.vet else '',
                    (event.lab.name + (f' · {event.lab_reference}' if event.lab_reference else '')) if event.lab else '']
        rows.append(L.row(event.pk, {
            'date': L.cell(formats.date_format(event.date, 'DATE_FORMAT'),
                           chips=[L.chip('neutral', str(words.VOIDED))] if event.is_deleted else ()),
            'event': _event(view, context, event),
            'where': L.cell(event.site.name, sub=[', '.join(units) if units else str(words.WHOLE_SITE)]),
            'signs': L.cell(', '.join(str(label) for label in event.sign_labels()) or DASH),
            'told': told,
            'examined': L.cell(event.examined_by or DASH, sub=examined),
            'deaths': L.cell(fish(event.deaths)),
            'closed': _closed(event),
        }, actions, status=status, voided=event.is_deleted))
    notices = []
    if context['to_notify']:
        notices.append(L.notice('notify', 'critical', f"{str(words.NOTIFY_MATTILSYNET)}: " + str(words.A_LISTED_DISEASE_IS_SUSPECTED_OR_CONFIRMED)))
        for event, url in context['to_notify']:
            # each event as the classic list names it, and the way to file its notice (or its form, to record the filing)
            href = url or (view.url('edit', event.pk) if context.get('can_change') else None)
            notices.append(L.notice(f'notify-{event.pk}', 'critical',
                                    f'{event} · {event.site.name} · {event.get_confirmation_display()}',
                                    link=(href, str(words.NOTIFY_MATTILSYNET)) if href else None))
    return {
        'columns': [L.column('date', str(words.DATE)), L.column('event', str(words.EVENT)), L.column('where', str(words.WHERE)),
                    L.column('signs', str(words.SIGNS)), L.column('told', str(words.MATTILSYNET)),
                    L.column('examined', str(words.EXAMINED_BY)), L.column('deaths', str(words.DEATHS), numeric=True),
                    L.column('closed', str(words.CLOSED))],
        'notices': notices,
        'rows': rows,
    }
