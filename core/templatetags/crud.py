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
