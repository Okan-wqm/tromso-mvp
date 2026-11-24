"""The words of the knowledge panels of their own, one source for both looks: the classic templates read them through the
template tag `knowledge_words` (templatetags/knowledge_words.py) and the new look's panels (core/formpanels.py, Resource.next_panels)
from here. Each is the msgid the template said itself."""
from django.utils.functional import lazy
from django.utils.translation import gettext_lazy as _

REVIEW = _('Review')
NOT_REVIEWED_YET_AI_AGENTS_WILL = _('Not reviewed yet. AI agents will act on reviewed entries only.')
BACK_TO_DRAFT = _('Back to draft')
REVIEW_IT_AGAIN = _('Review it again')
MARK_AS_REVIEWED = _('Mark as reviewed')
REVIEWING_SAYS_THE_STATEMENT_AND_ITS = _('Reviewing says the statement and its source are right: it is recorded in your name, now. Editing '
      'the statement, topics, species or source of a reviewed entry makes it a draft again.')

# For a template: {name in lower case: the words}, said as the template's trans tag said them (a msgid's per cent signs are
# doubled, as a template's msgid has them: core.formpanels.said).
_said = lazy(lambda text: str(text).replace('%%', '%'), str)
WORDS = {name.lower(): _said(value) for name, value in dict(globals()).items() if name.isupper() and name != 'WORDS'}


def reviewed_by(entry):
    """Who reviewed an entry and when, on the company's clock."""
    from django.utils import formats
    from django.utils.translation import gettext

    from core.templatetags.dates import company_clock
    return gettext('by %(who)s, %(when)s') % {
        'who': entry.reviewed_by, 'when': formats.date_format(company_clock(entry.reviewed_at), 'DATETIME_FORMAT')}
