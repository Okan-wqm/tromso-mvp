"""The words of the farm panels of their own, one source for both looks: the classic templates read them through the
template tag `farm_words` (templatetags/farm_words.py) and the new look's panels (core/formpanels.py, Resource.next_panels)
from here. Each is the msgid the template said itself."""
from django.utils.functional import lazy
from django.utils.translation import gettext_lazy as _, pgettext_lazy

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

# The words of Operations › Feeding, Harvest and Health (farm/feeding/pages.py and lists.py, farm/harvest/…, farm/health/…
# and the classic list pages they mirror): each the msgid its classic template said.
THE_RATION_IS_THE_ESTIMATED_BIOMASS_TIMES = _('The ration is the estimated biomass times the SFR of the '
                                              'protocol’s band at the unit’s temperature, read between the '
                                              'table’s columns. The estimated weight is the last measured one '
                                              'plus the feed given since, divided by the expected FCR (feed '
                                              'above a day’s ration is not counted as growth); after each meal '
                                              'the next one is worked out again. Over- and underfeeding are not '
                                              'flagged yet: compare the fed and remaining amounts.')
NO_DATA = _('no data')
RECORDS = _('Records')
NO_UNIT_HELD_FISH_ON_THESE_DAYS = _('No unit held fish on these days.')
CLEANER_FISH_NO_FEEDING_TABLE_OF_THEIR = _('Cleaner fish: no feeding table of their own.')
MEALS_DONE = _('meals done')
UNIT = _('Unit')
NEXT_MEAL = _('Next meal')
TODAY = _('Today')
FED_TODAY = _('Fed today')
RATION = _('Ration')
BATCH = _('Batch')
AVG_WEIGHT = _('Avg. weight')
WATER = _('Water')
PROTOCOL = _('Protocol')
PRODUCTION_DEPARTMENT = _('Production department')
OVER_AND_UNDERFEEDING_ARE_NOT_FLAGGED_YET = _('Over- and underfeeding are not flagged yet.')
NO_UNIT_WITH_FISH_MATCHES_THESE_FILTERS = _('No unit with fish matches these filters.')
NO_UNIT_HOLDS_FISH = _('No unit holds fish')
THE_BOARD_LISTS_THE_UNITS_WITH_FISH = _('The board lists the units with fish, from Production units.')
MEAL_BOARD_SCROLLS_SIDEWAYS = _('Meal board, scrolls sideways')
RECORD_FEEDING = _('Record feeding')
DATE = _('Date')
BATCHES_FED = _('Batches fed')
FEED_GIVEN = _('Feed given')
MEALS = _('Meals')
FEEDER = _('Feeder')
RECORDED_BY = _('Recorded by')
NOTES = _('Notes')
SITE = _('Site')
FROM = _('From')
TO = _('To')
SHOW_VOIDED = _('Show voided')
NO_FEEDING_MATCHES_THESE_FILTERS = _('No feeding matches these filters.')
NO_FEEDING_RECORDED_YET = _('No feeding recorded yet')
FEED_GIVEN_TO_A_UNIT_IS_RECORDED = _('Feed given to a unit is recorded from its drawer on Production units, or '
                                     'with Record feeding.')
BATCHES = _('Batches')
CALCULATED = _('Calculated')
GIVEN = _('Given')
DEVIATION = _('Deviation')
THE_CALCULATED_RATION_OF_A_DAY_COUNTS = _('The calculated ration of a day counts each recorded meal at the '
                                          'ration it had when it was given (the estimated weight then), and the '
                                          'meals still to come at the estimate now; a record that does not say '
                                          'its meals counts as one. The deviation is the feed given less the '
                                          'calculated ration. It is worked out again from the records, the stock '
                                          'and the water samples as they are now.')
NO_UNIT_HELD_FISH_ON_THESE_DAYS_2 = _('No unit held fish on these days with these filters.')
SFR = _('SFR')
CLEANER_FISH = _('Cleaner fish')
STALE = _('stale')
SYSTEM = _('System')
CLEAR_FILTERS = _('Clear filters')
ABOVE_THE_USUAL_FEED_RATE_ACCEPTED = _('Above the usual feed rate, accepted')
FASTING = _('Fasting')
RECORD_MEAL = _('Record meal')
RECORD_WATER_SAMPLE = _('Record water sample')
ALL_PRODUCTION_DEPARTMENTS = _('All production departments')
HOW_RATIONS_ARE_WORKED_OUT = _('How rations are worked out')
VOID = _('Void')
ALL_SITES = _('All sites')
ALL_UNITS = _('All units')
ALL_BATCHES = _('All batches')
ALL_FEEDS = _('All feeds')
ALL_SYSTEMS = _('All systems')
NO_FISH_AT_THE_END_OF_THE = _('No fish at the end of the day')
VOIDED = _('Voided')
STATUS = _('Status')
WEIGHT_BANDS = _('Weight bands')
TEMPERATURES = _('Temperatures')
IN_FORCE_TODAY = _('In force today')
WHEN = _('When')
WHEREVER_IT_IS = _('wherever it is')
WHATEVER_IS_IN_IT = _('whatever is in it')
ENDED = _('ended')
OPEN = _('open')
APPLIES_TO = _('Applies to')
UNTIL = _('Until')
FEEDS_NOW = _('Feeds now')
A_PROTOCOL_IS_ASSIGNED_TO_UNITS_IT = _('A protocol is assigned to units (it feeds whatever is in them), to a '
                                       'whole batch (it follows the batch into every unit it is moved to) or to '
                                       'a batch in chosen units. For a batch in a unit the most specific row in '
                                       'force applies: batch in unit, then unit, then whole batch. A row may be '
                                       'changed or deleted before its first day; afterwards it is ended by its '
                                       'last day.')
ALL_SPECIES = _('All species')
ALL_STATUSES = _('All statuses')
STARTS_LATER = _('starts later')
EDIT = _('Edit')
DELETE = _('Delete')
ALL_PROTOCOLS = _('All protocols')
ANY_TIME = _('Any time')
NO_TABLE_YET = _('No table yet')
DELETED = _('Deleted')
NO_FISH = _('no fish')
HARVEST = _('Harvest')
HARVESTS = _('Harvests')
FISH = _('Fish')
ROUND_WEIGHT = _('Round weight')
BOOK = _('Book')
DIFFERENCE = _('Difference')
SLAUGHTER_FACILITY = _('Slaughter facility')
NO_HARVEST_MATCHES_THESE_FILTERS = _('No harvest matches these filters.')
NO_HARVEST_RECORDED_YET = _('No harvest recorded yet')
A_HARVEST_IS_RECORDED_FROM_ITS_UNIT = _('A harvest is recorded from its unit’s drawer on Production units, or '
                                        'from its plan.')
HANDLING_WARNING_ACKNOWLEDGED = _('Handling warning acknowledged')
UNACCOUNTED_LOSS = _('Unaccounted loss')
TRANSPORT = _('Transport')
ALL_SLAUGHTER_FACILITIES = _('All slaughter facilities')
NONE = _('None')
PLAN = _('Plan')
MEDICINE_WITHDRAWAL_NOT_CHECKED = _('Medicine withdrawal not checked')
PLAN_TRANSPORT = _('Plan transport')
NOT_CHECKED = _('Not checked')
AS_STOCKED = _('as stocked')
PLANNED = _('Planned')
ACTUAL = _('Actual')
BEFORE_HANDLING = _('Before handling')
A_PLAN_IS_DONE_WHEN_THE_HARVEST = _('A plan is done when the harvest or transfer recorded from it counts; '
                                    'voiding that operation plans it again. The fast a plan asks of its unit '
                                    'starts at the start of its day less the handling rule’s hours.')
TARGET_WEIGHT = _('Target weight')
ESTIMATED_NOW_TARGET_REACHED = _('Estimated now · target reached')
EXPECTED_HARVEST = _('Expected harvest')
LAST_FED = _('Last fed')
THE_TARGET_WEIGHT_EACH_BATCH_IS_GROWN = _('The target weight each batch is grown to for harvest. The estimated '
                                          'weight now is the feeding protocols’ estimate; the day it reaches the '
                                          'target walks it forward on the ration of each day, at the unit’s '
                                          'latest temperature held, with no growth on a fasting day. The '
                                          'expected harvest is the date given when the batch was stocked.')
HARVESTS_AND_TRANSPORTS = _('Harvests and transports')
EDIT_OR_CANCEL = _('Edit or cancel')
SET_TARGET = _('Set target')
PLAN_HARVEST = _('Plan harvest')
RECORD_HARVEST = _('Record harvest')
RECORD_TRANSFER = _('Record transfer')
TARGET_REACHED = _('target reached')
NO_LONGER_IN_STOCK = _('No longer in stock')
NO_FISH_FOUND_IN_THESE_UNITS_ON = _('No fish found in these units on these days')
DAYS = _('Days')
UNITS = _('Units')
TREATMENT = _('Treatment')
DOSE_AMOUNT = _('Dose · amount')
BATCHES_AND_WITHDRAWAL = _('Batches and withdrawal')
PRESCRIPTION = _('Prescription')
WHAT_WAS_GIVEN = _('What was given')
PER_BATCH = _('Per batch')
ADD_UNIT = _('Add unit')
CHOOSE_THE_UNIT_THAT_WAS_FED = _('Choose the unit that was fed.')
NO_UNIT_HOLDS_FISH_A_FEEDING_NEEDS = _('No unit holds fish: a feeding needs fish in its unit.')
SPECIES_SINGULAR = pgettext_lazy('singular', 'Species')
PER_SITE = _('Per site')
DOSE_AND_AMOUNT = _('Dose and amount')
METHOD = _('Method')
MEDICINE = _('Medicine')
SHOW = _('Show')
NO_TREATMENT_MATCHES_THESE_FILTERS = _('No treatment matches these filters.')
NO_TREATMENT_RECORDED_YET = _('No treatment recorded yet')
A_BATH_A_MEDICATED_FEED_AN_INJECTION = _('A bath, a medicated feed, an injection or a vaccination, or a '
                                         'treatment without a medicine, is recorded here or from a unit’s drawer '
                                         'on Production units.')
WEEKLY_AVERAGES = _('Weekly averages')
FISH_EXAMINED = _('Fish examined')
ADULT_FEMALES = _('Adult females')
MOBILE = _('Mobile')
ATTACHED = _('Attached')
NO_COUNT_MATCHES_THESE_FILTERS = _('No count matches these filters.')
NO_SEA_LICE_COUNT_RECORDED_YET = _('No sea-lice count recorded yet')
LICE_ARE_COUNTED_AT_LEAST_EVERY_7 = _('Lice are counted at least every 7 days at 4 °C or above, every 14 days '
                                      'below (lakselusforskriften § 6).')
RUNNING = _('Running')
OVER_THE_LIMIT = _('Over the limit')
ALL_METHODS = _('All methods')
ALL_MEDICINES = _('All medicines')
ALL_TREATMENTS = _('All treatments')
UNDER_WITHDRAWAL_TODAY = _('Under withdrawal today')
VACCINATIONS = _('Vaccinations')
RECORD_TREATMENT = _('Record treatment')
WEEK = _('Week')
ADULT_FEMALES_PER_FISH = _('Adult females per fish')
LIMIT = _('Limit')
MOBILE_PER_FISH = _('Mobile per fish')
ATTACHED_PER_FISH = _('Attached per fish')
UNITS_COUNTED = _('Units counted')
RECORD_SEA_LICE_COUNT = _('Record sea-lice count')
LAST_DAY = _('Last day')
UNRESOLVED_OLD_COURSES = _('Unresolved old courses')
AREA_NOT_SET_THE_STRICTER_LIMIT_APPLIES = _('Area not set: the stricter limit applies (Facility › Sites)')
A_SITE_AVERAGES_THE_AVERAGES_OF_ITS = _('A site averages the averages of its units counted that week, every unit '
                                        'weighing the same, and must stay below the limit: 0.5 adult female lice '
                                        'per fish, 0.2 in the spring weeks (lakselusforskriften § 8 and Vedlegg '
                                        '1). The latest count of each unit in the week counts.')
SHARED_A_UNIT = _('shared a unit')
KIND = _('Kind')
OPEN_2 = _('Open')
EVENT = _('Event')
WHERE = _('Where')
SIGNS = _('Signs')
MATTILSYNET = _('Mattilsynet')
EXAMINED_BY = _('Examined by')
DEATHS = _('Deaths')
CLOSED = _('Closed')
ALL_KINDS = _('All kinds')
OPEN_AND_CLOSED = _('Open and closed')
A_LISTED_DISEASE_IS_SUSPECTED_OR_CONFIRMED = _('A listed disease is suspected or confirmed and Mattilsynet has '
                                               'not been notified: notify at once (dyrehelseforskriften § 7), '
                                               'then record the filing of the notice.')
NOTIFY_AT_ONCE = _('Notify at once')
NOTIFY_MATTILSYNET = _('Notify Mattilsynet')
WHOLE_SITE = _('Whole site')

# For a template: {name in lower case: the words}, said as the template's trans tag said them (a msgid's per cent signs are
# doubled, as a template's msgid has them: core.formpanels.said).
_said = lazy(lambda text: str(text).replace('%%', '%'), str)
WORDS = {name.lower(): _said(value) for name, value in dict(globals()).items() if name.isupper() and name != 'WORDS'}


def sfr_at(temperature):
    """A feeding table's SFR column (`temperature` as it is said, e.g. 8 °C)."""
    from django.utils.translation import gettext
    return gettext('SFR at %(temperature)s') % {'temperature': temperature}
