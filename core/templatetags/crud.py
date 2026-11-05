from django import template

from core.crud import mount_of, mounted_name

register = template.Library()


@register.filter
def mounted(url_name, request):
    """The route `url_name` under the mount the page came by (core.crud.Mount): a link or form on a page served twice stays
    in the place it was opened from. `{% url 'hr:leaverequest_approve'|mounted:request pk %}`."""
    return mounted_name(url_name, mount_of(request))
