from django import template

from core.crud import mount_of, mounted_name

register = template.Library()


@register.filter
def mounted(url_name, request):
    """The route `url_name` under the mount the page came by (core.crud.Mount): a link or form on a page served twice stays
    in the place it was opened from. `{% url 'hr:leaverequest_approve'|mounted:request pk %}`."""
    return mounted_name(url_name, mount_of(request))


@register.simple_tag
def entry_key():
    """A fresh one-time key (core.crud.ENTRY_KEY, core.models.EntryKey) for a form that creates a record outside a crud
    dialog, such as a Copy button: the same form sent twice, by a double click or a retried request, creates one record.
    `<form ...>{% entry_key %}...`."""
    import uuid

    from django.utils.html import format_html

    from core.crud import ENTRY_KEY
    return format_html('<input type="hidden" name="{}" value="{}">', ENTRY_KEY, uuid.uuid4())


# A field's help longer than this is a reference note (a scale, a conversion, a source: "As a pH meter or kit calibrated
# with NBS/NIST buffers reads it, …"), shown as a tooltip where a page asks for it; shorter, it is a hint and stays under
# the field ("At most 20 characters"). README › Frontend: field notes.
NOTE_LONGER_THAN = 80


@register.filter
def is_noted(field, notes):
    """Whether `field`'s help is drawn as a note (a tooltip on its field, an ⓘ button beside its label) rather than as text
    under it: only where the page asks for notes (`notes`, registration/_field.html: the calculator in the new look), only
    for a single control, and only for a help longer than NOTE_LONGER_THAN characters."""
    return bool(notes) and not field.use_fieldset and field.widget_type != 'checkbox' and \
        len(str(field.help_text or '')) > NOTE_LONGER_THAN
