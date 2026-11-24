"""The words of the tasks panels of their own, one source for both looks: the classic templates read them through the
template tag `task_words` (templatetags/task_words.py) and the new look's panels (core/formpanels.py, Resource.next_panels)
from here. Each is the msgid the template said itself."""
from django.utils.functional import lazy
from django.utils.translation import gettext_lazy as _

THE_CHECKLIST_HAS_BEEN_STARTED_ITS = _('The checklist has been started: its lines can no longer be changed. Add a note instead.')

# For a template: {name in lower case: the words}, said as the template's trans tag said them (a msgid's per cent signs are
# doubled, as a template's msgid has them: core.formpanels.said).
_said = lazy(lambda text: str(text).replace('%%', '%'), str)
WORDS = {name.lower(): _said(value) for name, value in dict(globals()).items() if name.isupper() and name != 'WORDS'}
