"""The words of the water-chemistry core's codes (owner amendment B2: the core is language-free; the browser receives
finished words). One table: code -> the msgid the chart always used, so the EN, TR and NB catalogues carry over
unchanged. farm/tests/test_native_geometry.py checks that every code the core gives has its words here."""
from django.utils.formats import number_format
from django.utils.translation import gettext_lazy as _

NOTES = {
    'co2.no_limit': _('CO₂: no limit given.'),
    'safe.no_band': _('Safe zone: not drawn without the alkalinity band.'),
    'safe.empty_band': _('Safe zone: not drawn, the alkalinity band is empty (its high end is not above its low end).'),
    'safe.no_tan': _('Safe zone: not drawn without the TAN.'),
    'safe.no_nh3_limit': _('Safe zone: not drawn without the NH₃ limit.'),
    'safe.no_co2_limit': _('Safe zone: not drawn without the CO₂ limit.'),
    'safe.no_h2s_limit': _('Safe zone: not drawn without the H₂S limit, a total sulfide being given.'),
    'safe.h2s_not_assessed': _('Safe zone: H₂S not assessed, no total sulfide given.'),
    'safe.no_safe_ph': _('Safe zone: no pH in the alkalinity band is inside every limit.'),
    'omega.out_of_range': _('Ω: needs the calcium and a salinity of 5 to 44 ‰, the range of Mucci (1983).'),
    'nh3.no_tan': _('NH₃: give the TAN.'),
    'nh3.no_limit': _('NH₃: no limit given.'),
    'nh3.not_reached': _('NH₃: the limit is not reached anywhere on this chart.'),
    'nh3.cannot_reach': _('NH₃: the TAN cannot give the limit at any pH (the limit is not below the TAN).'),
    'h2s.no_sulfide': _('H₂S: give the total sulfide.'),
    'h2s.no_limit': _('H₂S: no limit given.'),
    'h2s.not_reached': _('H₂S: the limit is not reached anywhere on this chart.'),
    'h2s.cannot_reach': _('H₂S: the total sulfide cannot give the limit at any pH.'),
}


def note(code):
    """The words of a note's code (lazy: said in the language active when shown). KeyError for an unknown code."""
    return NOTES[code]


DOSING_NOTES = {
    'dosing.cannot_reach': _('Dosing path: these two reagents cannot reach the target.'),
    'dosing.tick_one_or_two': _('Dosing path: tick one reagent to draw its line, or two to draw their path to the target.'),
}


def dosing_note(code):
    """The words of the dosing layer's note ('' when it has none). KeyError for an unknown code."""
    return '' if code is None else DOSING_NOTES[code]


# Where a water's ionic strength came from (the core's codes, chemcore/core/src/chemistry.rs Source).
STRENGTH_SOURCES = {
    'conductivity': _('from the conductivity at 25 °C'),
    'hardness': _('at least that of the hardness and the alkalinity'),
    'salinity': _('from the salinity'),
    'alkalinity': _('at least that of the alkalinity'),
    'seawater': _('of sea water of this salinity'),
    'none': _('none measured, taken as 0 (the safe side)'),
}


def provenance(equilibria):
    """What a value worked out from a water's equilibria was worked out by, in words: the formula version, the ionic
    strength and where it came from, and the share of the seawater constants (1 to 5 ‰). Every worked-out value shown
    says it (chemcore/findings/I2-comparison.md); KeyError for an unknown source code."""
    said = _('Formula %(formula)d: ionic strength %(strength)s, %(source)s') % {
        'formula': equilibria.formula, 'strength': number_format(equilibria.ionic_strength, 4),
        'source': STRENGTH_SOURCES[equilibria.strength_source]}
    if 0 < equilibria.sea_weight < 1:
        said = _('%(said)s; %(share)d %% seawater constants') % {'said': said, 'share': round(100 * equilibria.sea_weight)}
        if equilibria.water_origin == '':
            # Cross review F3: the band takes sea water's ions; a fresh water salted with NaCl would read low CO2.
            said = _('%(said)s (assumes sea water’s ion composition; salt-added fresh water may read low CO₂: say the '
                     'unit’s water origin)') % {'said': said}
    if equilibria.water_origin == 'salt_added':
        said = (_('%(said)s; salt-added fresh water, its ions taken as NaCl') if equilibria.sea_weight == 0
                else _('%(said)s; salt-added fresh water past the Davies range, worked out as sea water')) % {'said': said}
    return f'{said}.'


# What judged a water's NH3 or CO2 against its limits (cross review F1; chemcore/core/src/chemistry.rs Basis): the
# larger of the basis the limits were set on and the activity-corrected value.
JUDGED = {
    ('nh3', 'limits'): _('NH₃ judged on the basis its limits were set on (to 1 ‰ the ideal water, every activity 1, as '
                         'Emerson et al. 1975; from 5 ‰ formula 1’s seawater constants), the larger; activity-corrected '
                         '%(value)s mg/L.'),
    ('nh3', 'corrected'): _('NH₃ judged on its activity-corrected value, the larger here.'),
    ('co2', 'limits'): _('CO₂ judged on the basis its limits were set on (to 1 ‰ the ideal water, every activity 1, as '
                         'Standard Methods 4500-CO₂ D; from 5 ‰ formula 1’s seawater constants), the larger; '
                         'activity-corrected %(value)s mg/L.'),
    ('co2', 'corrected'): _('CO₂ judged on its activity-corrected value, the larger here.'),
}
JUDGED_DECIMALS = {'nh3': 4, 'co2': 2}


def judged(kind, basis, corrected, equilibria):
    """Which value judged a water's NH3 ('nh3') or CO2 ('co2'), with the activity-corrected value beside it, in words;
    '' for formula 1 (its own value is the limits' basis), for the ideal water (an ionic strength of 0 in fresh water:
    the two are one) or without a value. KeyError for an unknown kind or basis."""
    words = JUDGED[kind, basis]
    ideal = equilibria.ionic_strength == 0 and equilibria.sea_weight == 0
    if equilibria.formula == 1 or ideal or corrected is None:
        return ''
    return str(words % {'value': number_format(corrected, JUDGED_DECIMALS[kind])} if basis == 'limits' else words)
