"""The words of the experiments panels of their own, one source for both looks: the classic templates read them through the
template tag `experiment_words` (templatetags/experiments_words.py) and the new look's panels (core/formpanels.py, Resource.next_panels)
from here. Each is the msgid the template said itself."""
from django.utils.functional import lazy
from django.utils.translation import gettext_lazy as _

DESIGN = _('Design')
PLACES = _('Places')
THE_EXPERIMENT_HAS_STARTED_SO_ITS = _('The experiment has started, so its design is fixed: it was registered before the first day and '
      'what is judged is what was planned. To change it, copy the experiment and change the copy.')
START_THE_EXPERIMENT = _('Start the experiment')
A_FACTOR_IS_WHAT_THE_GROUPS = _('A factor is what the groups differ in: the diet, whose levels are feeding protocols (how the '
      'farm applies it), or another factor such as a temperature, whose levels are labels. Each group '
      'has one level of each factor and its replicates, the tanks of which are placed on the Places '
      'tab. The design is saved as a whole.')
FACTORS = _('Factors')
FACTOR = _('Factor')
KIND = _('Kind')
UNIT_OF_ITS_LEVELS = _('Unit of its levels')
REMOVE = _('Remove')
ADD_FACTOR = _('Add factor')
GROUPS = _('Groups')
GROUP = _('Group')
ROLE = _('Role')
REPLICATES = _('Replicates')
NO_GROUP_YET_USE_ADD_GROUP = _('No group yet. Use “Add group” to add a row.')
NAME_A_FACTOR_FIRST_THE_GROUPS = _('Name a factor first: the groups follow its columns.')
ADD_GROUP = _('Add group')
SAVE_DESIGN = _('Save design')
THE_EXPERIMENT_HAS_STARTED_ITS_TANKS = _('The experiment has started: its tanks and days are fixed. A tank that has to leave, or be '
      'replaced, is released from its page.')
SET_DAY_0_ON_THE_DETAILS = _('Set day 0 on the Details tab first: a tank is booked for days.')
NO_REPLICATE_YET_DESIGN_THE_GROUPS = _('No replicate yet: design the groups on the Design tab first.')
RANDOMISE = _('Randomise')
CHOOSE_AS_MANY_TANKS_OR_SYSTEMS = _('Choose as many tanks or systems as there are replicates and a seed: they are dealt to the '
      'replicates by a fixed method, so the deal can be repeated and checked. The seed is kept with the '
      'placements.')
BY_HAND = _('By hand')
REPLICATE = _('Replicate')
TANKS = _('Tanks')
ADD_THE_TANKS_OF_A_SYSTEM = _('Add the tanks of a system')
FROM = _('From')
UNTIL = _('Until')
SAVE_PLACES = _('Save places')
TO_FIX_BEFORE_IT_CAN_START = _('To fix before it can start')
TO_READ_BEFORE_IT_STARTS = _('To read before it starts')
COPY_AS_A_NEW_EXPERIMENT = _('Copy as a new experiment')
SAVE_AS_A_TEMPLATE = _('Save as a template')
TANK = _('Tank')
NO_TANK_IS_PLACED = _('No tank is placed.')
CONTROL = _('Control')
NO_GROUP = _('No group.')

# For a template: {name in lower case: the words}, said as the template's trans tag said them (a msgid's per cent signs are
# doubled, as a template's msgid has them: core.formpanels.said).
_said = lazy(lambda text: str(text).replace('%%', '%'), str)
WORDS = {name.lower(): _said(value) for name, value in dict(globals()).items() if name.isupper() and name != 'WORDS'}


def booked_for(span, error_df):
    """The Places tab's sentence of the days the tanks are booked for and the error degrees of freedom left."""
    from django.utils import formats
    from django.utils.translation import gettext
    return gettext('The tanks are booked for the days of the experiment, %(first)s to %(last)s, unless a row gives days '
                   'of its own. The error degrees of freedom the design leaves are %(error_df)s.') % {
        'first': formats.date_format(span[0], 'DATE_FORMAT'), 'last': formats.date_format(span[1], 'DATE_FORMAT'),
        'error_df': formats.localize(error_df)}
