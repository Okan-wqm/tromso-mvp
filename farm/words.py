"""The words of the farm panels of their own, one source for both looks: the classic templates read them through the
template tag `farm_words` (templatetags/farm_words.py) and the new look's panels (core/formpanels.py, Resource.next_panels)
from here. Each is the msgid the template said itself."""
from django.utils.functional import lazy
from django.utils.translation import gettext_lazy as _

FEEDING_TABLE = _('Feeding table')
THE_FEEDING_TABLE_CAN_BE_FILLED = _('The feeding table can be filled in once the protocol is created.')
THE_PROTOCOL_IS_ASSIGNED_SO_ITS = _('The protocol is assigned, so its table is fixed: the rations of the days it fed are read from '
      'it. To change it, duplicate the protocol, change the copy and assign it from a date.')
WEIGHT_BAND = _('Weight band')
FEED = _('Feed')
MEALS_A_DAY = _('Meals a day')
EXPECTED_FCR = _('Expected FCR')
ONE_ROW_PER_WEIGHT_BAND_FROM = _('One row per weight band, from its lower weight up to, not including, its upper one; the bands '
      'meet without gaps and only the last may have no upper weight. Fish outside the bands, or in '
      'water outside the first and last temperature column, get no ration. In each cell the SFR, the %% '
      'of the body weight fed a day; 0 means no feeding at that temperature. An empty FCR is the '
      'protocol’s. The table is saved as a whole.')
FROM_G = _('From (g)')
UP_TO_G = _('Up to (g)')
REMOVE = _('Remove')
NO_BAND_YET_USE_ADD_BAND = _('No band yet. Use “Add band” to add a row.')
GIVE_THE_TEMPERATURE_COLUMNS_FIRST_THE = _('Give the temperature columns first: the grid follows them.')
ADD_BAND = _('Add band')
SAVE_TABLE = _('Save table')
DUPLICATE = _('Duplicate')
A_DRAFT_COPY_WITH_THIS_TABLE = _('A draft copy with this table, to change and assign from a date.')
MEDICINE_WITHDRAWAL = _('Medicine withdrawal')
GO_ON_DESPITE_THESE_WARNINGS = _('Go on despite these warnings')
FISH_UNDER_A_MEDICINE_WITHDRAWAL_MUST = _('Fish under a medicine withdrawal must not go to food. Going on is stored with what is shown here '
      'and logged as critical.')
A_PROTOCOL_GIVES_PER_WEIGHT_BAND = _('A protocol gives, per weight band of the fish, the feed, the meals a day and the '
                                     'specific feeding rate (SFR, %% of the body weight a day) at each temperature column, '
                                     'with the FCR it expects. A ration is worked out from it on read: the fish, their '
                                     'estimated weight and the unit’s temperature (Meal board).')

# For a template: {name in lower case: the words}, said as the template's trans tag said them (a msgid's per cent signs are
# doubled, as a template's msgid has them: core.formpanels.said).
_said = lazy(lambda text: str(text).replace('%%', '%'), str)
WORDS = {name.lower(): _said(value) for name, value in dict(globals()).items() if name.isupper() and name != 'WORDS'}


def sfr_at(temperature):
    """A feeding table's SFR column (`temperature` as it is said, e.g. 8 °C)."""
    from django.utils.translation import gettext
    return gettext('SFR at %(temperature)s') % {'temperature': temperature}
