"""Which language a request is shown in. Django's LocaleMiddleware negotiates it (cookie, then the
browser's Accept-Language, then LANGUAGE_CODE); a signed-in person who has saved a language on their
account gets that one instead, on every device. The language switcher (core.views.set_language) sets
the cookie and saves the account; the sign-in pages have no person yet, so they use the cookie alone."""
from django.conf import settings
from django.utils import translation
from django.utils.deprecation import MiddlewareMixin

from .models import Profile


def is_supported(language):
    return language in dict(settings.LANGUAGES)


def account_language(user):
    """The language saved on the person's account, or None while they have not chosen one."""
    profile = getattr(user, 'profile', None)
    return profile.language if profile and is_supported(profile.language) else None


def save_account_language(user, language):
    user.profile, _ = Profile.objects.update_or_create(user=user, defaults={'language': language})


class AccountLanguageMiddleware(MiddlewareMixin):
    """Goes after LocaleMiddleware and AuthenticationMiddleware."""

    def process_request(self, request):
        language = account_language(request.user) if request.user.is_authenticated else None
        if language:
            translation.activate(language)
            request.LANGUAGE_CODE = language
