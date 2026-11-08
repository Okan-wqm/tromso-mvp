"""The words of the water-chemistry core's codes (owner amendment B2: the core is language-free; the browser receives
finished words). One table: code -> the msgid the chart always used, so the EN, TR and NB catalogues carry over
unchanged. farm/tests/test_native_geometry.py checks that every code the core gives has its words here."""
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
