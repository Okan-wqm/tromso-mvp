from datetime import datetime, time

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required, permission_required
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import render
from django.utils import timezone, translation
from django.utils.translation import gettext
from django.views import i18n

from .dates import company_zone, read_day
from . import accountmail, audit
from .language import account_language, is_supported, save_account_language
from .models import AuditLog


class SetPasswordView(auth_views.PasswordResetConfirmView):
    """Django's page behind the link of an account e-mail (core.accountmail), shown in the language saved on the
    account the link is for: the admin chose it with the invitation, and the mail was written in it. Only a link
    that works says whose it is; one that does not follows the browser like every page before sign-in.

    The link is checked with the account e-mails' own token (accountmail.tokens: Django's, with `is_active` in it). A
    password set here is written to the activity log in the same transaction: by the person, with the address the
    link went to. A link works only while the account's address is the one it was sent to, so that address is the
    account's at this moment; should it be put right later, the log and the users row still name it."""
    token_generator = accountmail.tokens

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            audit.record(self.user, AuditLog.Action.PASSWORD, self.user,
                         {accountmail.LINK_SENT_TO_LABEL: [None, self.user.email]},
                         entity_type=audit.entity_type_of(type(self.user)))
        return response

    def get_context_data(self, **kwargs):
        language = account_language(self.user) if self.validlink else None
        if language:
            translation.activate(language)
            self.request.LANGUAGE_CODE = language
        return super().get_context_data(**kwargs)


@login_not_required
def set_language(request):
    """Django's language switch (it sets the language cookie), which also saves the choice on the
    signed-in person's account. Open to everyone: the sign-in pages have it too."""
    response = i18n.set_language(request)
    chosen = response.cookies.get(settings.LANGUAGE_COOKIE_NAME)
    if chosen and is_supported(chosen.value) and request.user.is_authenticated:
        save_account_language(request.user, chosen.value)
    return response


def _day(request, value, end=False):
    """The start (or the end) of the day typed in a filter, in the language's format or ISO (core.dates.read_day)."""
    day = read_day(value, request)
    if day is None:
        return None
    return timezone.make_aware(datetime.combine(day, time.max if end else time.min), company_zone())


@permission_required('core.view_auditlog', raise_exception=True)
def activity_log(request):
    """Every recorded change, newest first, filterable by person, record type, action and dates."""
    readable = audit.readable(request.user)
    entries = readable
    filters = {key: request.GET.get(key, '').strip()
               for key in ('q', 'user', 'type', 'action', 'severity', 'from', 'to')}
    if filters['q']:
        entries = entries.filter(entity_label__icontains=filters['q'])
    if filters['user']:
        entries = entries.filter(user_name=filters['user'])
    if filters['type']:
        entries = entries.filter(entity_type=filters['type'])
    if filters['action']:
        entries = entries.filter(action=filters['action'])
    if filters['severity'] in AuditLog.Severity.values:
        entries = entries.filter(severity=filters['severity'])
    else:
        filters['severity'] = ''
    if start := _day(request, filters['from']):
        entries = entries.filter(created_at__gte=start)
    if end := _day(request, filters['to'], end=True):
        entries = entries.filter(created_at__lte=end)

    page = Paginator(entries, 50).get_page(request.GET.get('page'))
    query = request.GET.copy()
    query.pop('page', None)
    return render(request, 'core/activity_log.html', {
        'page': page,
        'filters': filters,
        'query': query.urlencode(),
        'users': readable.order_by('user_name').values_list('user_name', flat=True).distinct(),
        'types': [(name, gettext(name)) for name in
                  readable.order_by('entity_type').values_list('entity_type', flat=True).distinct()],
        'actions': AuditLog.Action.choices,
        'severities': AuditLog.Severity.choices,
    })
