from django import template

from core import access

register = template.Library()


@register.filter
def access_summary(permissions):
    """What a role's permissions allow, e.g. 'Sites: read, create; Activity log: read'."""
    return access.summary(permissions)
