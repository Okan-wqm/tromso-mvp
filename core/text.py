"""Lower case in the person's language. Python's str.lower() follows no language: the Turkish dotted capital İ becomes
"i̇" (an i with a combining dot above) and the dotless capital I an i with a dot, so a translated word put in the middle
of a sentence reads wrong in Turkish (F-160). `lower` is the one way the app lowers a translated word."""
from django.utils import translation

# The languages whose capital I and İ lower to ı and i (Turkish, and Azerbaijani which writes them alike).
DOTTED = {'tr', 'az'}


def lower(text, language=None):
    """`text` in lower case as `language` (default: the active one) writes it."""
    text = str(text)
    language = (language or translation.get_language() or '').split('-')[0]
    if language in DOTTED:
        text = text.replace('İ', 'i').replace('I', 'ı')
    return text.lower()
