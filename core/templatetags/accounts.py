"""`{{ person|invitation }}`: where a person stands with their invitation, for their row on the users tab
(core.accountmail.standing)."""
from django import template

from .. import accountmail

register = template.Library()


@register.filter
def invitation(user):
    return accountmail.standing(user)
