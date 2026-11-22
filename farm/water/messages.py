"""The words of the water-chemistry core's codes (owner amendment B2: the core is language-free; the browser receives
finished words). One table: code -> the msgid the chart always used, so the EN, TR and NB catalogues carry over
unchanged. farm/tests/test_native_geometry.py checks that every code the core gives has its words here."""
from decimal import ROUND_HALF_UP, Decimal

from django.utils.formats import number_format
from django.utils.translation import gettext_lazy as _

from . import native, parameters

NOTES = {
    'co2.no_limit': _('CO₂: no limit given.'),
    # With a phosphate the judged CO₂ curve is drawn in the water's own DIC, which near an alkalinity of 0 falls before
    # it rises (chemcore/core/src/geometry.rs co2_curve_judged, bends_back; the independent review of 2026-11-16, R9).
    'co2.bends_back': _('CO₂: near an alkalinity of 0 the curve bends back. With the phosphate given the water’s own '
                        'DIC falls before it rises there (a pH under about 4.7, where the phosphate holds negative '
                        'alkalinity); no fish water is in that corner.'),
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


def refused(error):
    """A refusal of the core (the ValueError or arithmetic error a call of farm/water/native.py raised) as the sentence
    a page says in the place of the value, the chart or the result: the core's own reason, in its words. The one
    wording of it: a sample's NH₃ (read._ammonia) and the gate of every chart and calculation (deffeyes.unworkable)."""
    return _('Cannot be worked out: %(why)s.') % {'why': error}


# A judged NH₃ the core refuses to work out, judged on the safe-side basis alone (read.Context._ammonia_on_basis; the
# re-check of 2026-11-18, RC-3): the sentence beside the refusal, and the few visible words beside the number.
ON_BASIS = _('Judged on the safe-side basis alone, which needs no conductivity: the judged value is at least this; the '
             'best estimate is not known.')
BASIS_ONLY = _('at least: the safe-side basis')


def unevaluated(reading):
    """What a page and an alarm say of a value the limits would judge that the core refused to work out
    (read.Reading.refused, its reason): the one wording of it (the verification of 2026-11-18, V-A)."""
    return _('%(label)s cannot be evaluated: %(why)s.') % {'label': reading.parameter.label, 'why': reading.refused}


# The scales a pH may be measured on besides NBS, as a sentence says them (the core's codes, chemcore/core/src/scale.rs).
PH_SCALES = {
    'total': _('total scale'),
    'sws': _('seawater scale (SWS)'),
    'free': _('free scale'),
}
PH_NOT_SEA = _('A pH on this scale is taken for sea water of 5 ‰ or more only (not fresh water with salt added): give '
               'the pH a meter calibrated with NBS/NIST buffers reads.')
PH_NEEDED = _('Needed with a pH on another scale than NBS: the conversion takes the temperature and the salinity of the '
              'same sample.')
# The calculator: another scale chosen on the unchanged pH a unit or a loop gave it (farm/forms/water.py
# CalculatorForm.unchanged_loaded; the independent review of 2026-11-16, R2).
PH_LOADED = _('pH %(ph)s is the value loaded from %(point)s: it is on the NBS scale already (a stored pH always is) and '
              'is not converted again. Leave the scale at NBS, or type the pH as it was measured with its scale.')


def ph_measured_words(value, scale):
    """'measured 7.95 on the total scale': a pH measured on another scale than NBS, as the few visible words beside the
    NBS number (a typed sample's, `ph_measured_short`, and a sensor's)."""
    return _('measured %(value)s on the %(scale)s') % {'value': number_format(value, 2), 'scale': PH_SCALES[scale]}


def ph_measured_short(sample):
    """What a sample's pH was measured as, when on another scale than NBS, as the few visible words beside the NBS
    number ('' for an NBS pH); `ph_measured` is the whole sentence."""
    if not sample.ph_scale:
        return ''
    return ph_measured_words(sample.ph_as_measured, sample.ph_scale)


# A sensor's pH on another scale than NBS (owner decision 1 of 2026-11-17; the water-chemistry audit of 2026-11-19, F1;
# farm/water/read.py Context.sensor_ph): put on the NBS scale where the water is read, or why not, in the words a page
# says after "pH (NBS scale) cannot be evaluated:" (`unevaluated`).
PH_SENSOR_REFUSED = {
    'unconverted': _('a pH on the %(scale)s is not put on the NBS scale here'),
    'stale': _('a pH on the %(scale)s is put on the NBS scale only while it is fresh, and it is no longer fresh'),
    'temperature': _('a pH on the %(scale)s is put on the NBS scale with a temperature of its moment, a sensor’s or a '
                     'sample’s, and none is fresh then'),
    'salinity': _('a pH on the %(scale)s is put on the NBS scale with the salinity of the same moment, and none was '
                  'measured here in the days before'),
    'not_sea': _('a pH on the %(scale)s is taken for sea water of 5 ‰ or more only (not fresh water with salt added); '
                 'set the channel’s pH scale to NBS if the probe is calibrated with NBS/NIST buffers'),
    # The core refused the water itself (read.OnNbs; the review of the water-chemistry audit, C5): its own reason.
    'core': _('a pH on the %(scale)s is put on the NBS scale by the chemistry core, which cannot work this water out: '
              '%(why)s'),
}


def ph_sensor_refused(why, scale, error=''):
    """Why a sensor's pH on `scale` was not put on the NBS scale (PH_SENSOR_REFUSED's key `why`; `error`, the core's own
    reason where it refused the water: 'core')."""
    return PH_SENSOR_REFUSED[why] % {'scale': PH_SCALES[scale], 'why': error}


def ph_scale_changed(moment):
    """Why a sensor's pH measured before its channel's pH scale was changed (at `moment`, on the site's clock) is used
    nowhere: the scale it was measured on is not known any more."""
    return _('measured before the channel’s pH scale was changed (%(time)s): the scale it was measured on is not '
             'known') % {'time': moment.strftime('%d.%m.%Y %H:%M')}


def unevaluated_ph(why):
    """Why a moment of a replay or a trail has no diagram: its sensor pH could not be put on the NBS scale."""
    return _('No diagram: the sensor’s pH cannot be put on the NBS scale (%(why)s).') % {'why': why}


def ph_not_converted(why):
    """The note of a sensor's pH that was not put on the NBS scale (`why`: ph_sensor_refused or ph_scale_changed)."""
    return _('Not shown: %(why)s.') % {'why': why}


def nh3_ph_not_converted(why):
    """The note of an NH₃ not worked out because the sensor's pH could not be put on the NBS scale."""
    return _('Not worked out: the sensor’s pH cannot be used (%(why)s).') % {'why': why}


def ph_sensor_converted(ph):
    """What a sensor's pH put on the NBS scale says beside it (read.SensorPh, converted), and where its temperature came
    from when not a fresh sensor's (`temperature_from`: a sample's, as the oxygen's basis says it)."""
    said = _('Measured %(value)s on the %(scale)s by the sensor; put on the NBS scale by formula %(formula)d with '
             '%(temperature)s °C and %(salinity)s ‰ of the same moment.') % {
        'value': number_format(ph.as_measured, 2), 'scale': PH_SCALES[ph.scale], 'formula': ph.formula,
        'temperature': number_format(ph.temperature, 1), 'salinity': number_format(ph.salinity, 1)}
    if not ph.temperature_from:
        return said
    source = _('The temperature is %(source)s.') % {'source': ph.temperature_from}
    return f'{said} {source}'


def ph_stored(sample):
    """A converted pH where its stored value is given on (the calculator's values from a unit): "measured 7.95 on the
    total scale, stored as 8.08 NBS"; '' for an NBS pH."""
    if not sample.ph_scale:
        return ''
    return _('%(measured)s, stored as %(nbs)s NBS') % {'measured': ph_measured_short(sample),
                                                       'nbs': number_format(sample.ph, 2)}


# The calculator: another unit chosen on the unchanged phosphate a unit or a loop gave it (as PH_LOADED).
PHOSPHATE_LOADED = _('Phosphate %(value)s is the value loaded from %(point)s: it is as P already (a stored phosphate '
                     'always is) and is not converted again. Leave the unit at P, or type the phosphate as it was '
                     'reported with its unit.')
# The calculator: another scale or unit on a value that a unit or a loop may have given, where the address does not
# carry what was loaded (an old or hand-made link) and the unit offers another value now: it is not taken for typed
# (CalculatorForm.loaded_unsaid; the verification of 2026-11-18, V-B).
LOADED_UNSAID = _('%(value)s may be the value stored for %(point)s, already converted: this address does not say it '
                  'was typed. Leave the scale or the unit as loaded, or choose %(point)s again under “Values from” and '
                  'type the value as it was measured.')


def _rounded(value, decimals):
    """A Decimal as the language writes it, ROUNDED to `decimals` (number_format alone cuts a Decimal's further digits
    off: 5.0062 would read 5.00 and 15.3499 15.34)."""
    return number_format(value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP), decimals)


def phosphate_range(as_p):
    """Why a phosphate is refused once it is put on P: the range is the phosphorus's whatever unit it was typed in."""
    parameter = parameters.get(parameters.PHOSPHATE)
    return _('As P this is %(value)s mg/L: a phosphate is between %(low)s and %(high)s mg/L as P (up to %(most)s as '
             'PO₄). Check the value and its unit.') % {
        'value': _rounded(as_p, 2), 'low': parameter.low, 'high': parameter.high,
        'most': _rounded(parameters.PO4_HIGH, 2)}


def phosphate_measured_short(sample):
    """What a sample's phosphate was entered as, when not as P, as the few visible words beside the stored P ('' for a
    phosphate entered as P); `phosphate_measured` is the whole sentence."""
    if not sample.phosphate_unit:
        return ''
    return _('entered as %(value)s mg/L PO₄') % {'value': number_format(sample.phosphate_as_measured, 2)}


def phosphate_measured(sample):
    """What a sample's phosphate was entered as, when not as P, in words ('' for a phosphate entered as P): said beside
    the P wherever it is shown (a reading's provenance)."""
    if not sample.phosphate_unit:
        return ''
    return _('Entered as %(value)s mg/L as PO₄; stored as phosphorus (PO₄-P), divided by %(factor)s (the molar masses '
             'of PO₄ and P).') % {'value': number_format(sample.phosphate_as_measured, 2),
                                  'factor': _rounded(parameters.PO4_PER_P, 3)}


def phosphate_used(equilibria):
    """The sentence beside every recipe and simulator step worked out with a phosphate: which phosphate, as P and as
    PO₄ (the two numbers a kit may show: a reader sees at once whether the right one went in), and that a wrong one
    changes the dose; '' for a water without one (the independent review of 2026-11-16, R3)."""
    if not equilibria.phosphate > 0:
        return ''
    as_p = Decimal(repr(equilibria.phosphate * 1000 * native.MG_P_PER_MMOL))
    return _('Worked out with phosphate %(p)s mg/L as P (%(po4)s as PO₄): a wrong phosphate changes this dose.') % {
        'p': _rounded(as_p, 2), 'po4': _rounded(parameters.phosphate_as_po4(as_p), 2)}


def ph_measured(sample):
    """What a sample's pH was measured as, when on another scale than NBS, in words ('' for an NBS pH): said beside the
    NBS pH wherever it is shown (a reading's provenance)."""
    if not sample.ph_scale:
        return ''
    return _('Measured %(value)s on the %(scale)s; put on the NBS scale by formula %(formula)d with the sample’s '
             '%(temperature)s °C and %(salinity)s ‰.') % {
        'value': number_format(sample.ph_as_measured, 2), 'scale': PH_SCALES[sample.ph_scale],
        'formula': sample.ph_converted_formula, 'temperature': number_format(sample.temperature_c, 1),
        'salinity': number_format(sample.salinity_ppt, 1)}


# Where a water's ionic strength came from (the core's codes, chemcore/core/src/chemistry.rs Source).
STRENGTH_SOURCES = {
    'conductivity': _('from the conductivity at 25 °C'),
    'hardness': _('at least that of the hardness and the alkalinity'),
    'salinity': _('from the salinity'),
    'alkalinity': _('at least that of the alkalinity'),
    'seawater': _('of sea water of this salinity'),
    'none': _('none measured, taken as 0 (the safe side)'),
}


# The plausibility warnings of a water's inputs (cross review F5; chemcore/core/src/fresh.rs plausibility): said beside
# the value, never a refusal. 'nh3_past_guard' is the K_NH4 panel's (2026-11-10, row 3), its words formula 4's: the
# numbers are the core's NH3_GUARD_MAX_TEMP_C and NH3_GUARD_MAX_SALINITY, the range formula 4 was checked over (its
# margin holds past it: chemcore/core/tests/formula4.rs), which farm/tests/test_plausibility.py holds them to.
WARNINGS = {
    'conductivity_salinity': _('Check the conductivity and the salinity: they disagree beyond what any water from NaCl '
                               'brine to a hard fresh water allows (one of them mistyped, uncompensated, or from '
                               'another point?).'),
    'conductivity_above_ions': _('Check the conductivity: it gives over 30 times the ions the hardness and the '
                                 'alkalinity account for (salt added, or mS/cm typed as µS/cm?).'),
    'conductivity_below_ions': _('Check the conductivity: it gives fewer ions than the hardness and the alkalinity need '
                                 '(not compensated to 25 °C, or in the wrong unit?); theirs is used.'),
    'seawater_conductivity': _('Check the salinity: the conductivity is that of sea water of 5 ‰ or more (PSS-78) on '
                               'a water without a salinity; give the salinity, or the unit’s water origin.'),
    'nh3_past_guard': _('NH₃ and CO₂: above 30 °C or a salinity of 35 ‰ the water is outside the range the formula '
                        'was checked over (0 to 30 °C, up to 35 ‰): the judged values keep their margin over the best '
                        'estimate, but the best estimate itself was not checked there. Keep a margin to the limit.'),
    # The water-chemistry audit of 2026-11-19, F10 (chemcore/core/src/fresh.rs FITTED_FROM_TEMP_C).
    'below_fitted_temp': _('Below 0 °C: the chemistry’s constants are fitted from 0 °C or above, so these values are '
                           'extrapolated. The judged NH₃ and CO₂ stay on the safe side there (they read high, not low).'),
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
    if equilibria.phosphate > 0:
        said = _('%(said)s; phosphate %(phosphate)s mg/L as P counted in the alkalinity') % {
            'said': said, 'phosphate': number_format(equilibria.phosphate * 1000 * native.MG_P_PER_MMOL, 2)}
    if equilibria.water_origin == 'salt_added':
        said = (_('%(said)s; salt-added fresh water, its ions taken as NaCl') if equilibria.sea_weight == 0
                else _('%(said)s; salt-added fresh water past the Davies range, worked out as sea water')) % {'said': said}
    return ' '.join([f'{said}.', *(str(WARNINGS[code]) for code in equilibria.warnings)])


# What judged a water's NH3 or CO2 against its limits (chemcore/core/src/chemistry.rs Basis): formula 4's Rule S (the
# water-chemistry audit of 2026-11-19 and the owner's decision; chemcore/core/src/formula4.rs): the safe side, the larger
# of it and the best estimate. Up to 1 ‰ the ideal water as formula 3 had it; from 5 ‰ the best estimate at the pH + 0.03
# (NH3) or − 0.03 (CO2), native.PH_UNCERTAINTY (farm/tests/test_formula_v4.py holds the words to it); blended between.
# The CO₂'s margin is 10^0.03 − 1 (7.2 %) only while the alkalinity is all bicarbonate: the lower pH also takes borate
# and hydroxide out of the alkalinity, so the carbonate's share grows; worked out by the core from 5 ‰ (S 5 to 40, 0 to
# 30 °C): +7.2 % to +9.8 % up to pH 8.2 and to +14.4 % at pH 9 with 50 mg/L, far more where the alkalinity is near its
# floor (farm/tests/test_formula_v4.py WordsTests holds the words to these numbers).
JUDGED = {
    ('nh3', 'limits'): _('NH₃ judged on the safe side (to 1 ‰ the ideal water, every activity 1, as Emerson et al. 1975; '
                         'from 5 ‰ the best estimate at the pH + 0.03, the uncertainty of a pH reading (US EPA 1989), '
                         'about 7 %% above it; blended between; salt-added water: the ideal throughout), the larger of it '
                         'and the best estimate; best estimate %(value)s mg/L.'),
    ('nh3', 'corrected'): _('NH₃ judged on its best estimate, the larger here.'),
    ('co2', 'limits'): _('CO₂ judged on the safe side (to 1 ‰ the ideal water, every activity 1, as Standard Methods '
                         '4500-CO₂ D; from 5 ‰ the best estimate at the pH − 0.03, the uncertainty of a pH reading (US EPA '
                         '1989), at least 7 %% above it and more at a high pH with a low alkalinity (up to about 10 %% at '
                         'pH 8.2 and 14 %% at pH 9 with 50 mg/L as CaCO₃); blended between; salt-added water: the ideal '
                         'throughout), the larger of it and the best estimate; best estimate %(value)s mg/L.'),
    ('co2', 'corrected'): _('CO₂ judged on its best estimate, the larger here.'),
}
JUDGED_DECIMALS = {'nh3': 4, 'co2': 2}
# With a phosphate given (chemcore/core/src/chemistry.rs Equilibria::co2_judged): the judged CO₂ is the water's without
# it, the water's own with it is said beside it.
JUDGED_WITHOUT_PHOSPHATE = _('CO₂ judged without the phosphate: the larger of the safe side and the best estimate, '
                             'neither counting the phosphate’s alkalinity (Standard Methods '
                             '4500-CO₂ D takes all the alkalinity as carbonate’s), so it is never below what it was '
                             'before the phosphate was given. With the phosphate counted, the water’s own CO₂ is '
                             '%(value)s mg/L.')


# What the best estimate of an NH₃ with seawater constants rests on (formula 4; chemcore/core/src/formula4.rs): the NBS
# pH taken by Millero's (1986) measured step and the ammonium constant of Clegg & Whitfield (1995). Formula 3's own
# conversion read up to 16 % below the references in cold sea water (the audit of 2026-11-19, F6); formula 4 replaced it.
BEST_SEA = _('In salt water the best estimate takes the NBS pH by Millero’s (1986) measured step and the ammonium '
             'constant of Clegg & Whitfield (1995).')
# An NH₃ worked out from a pH measured on the total, seawater or free scale (the audit of 2026-11-19, F11; a typed
# sample's or a sensor's): put on the NBS scale by the same step and judged as every salt-water NH₃ is (`JUDGED`).
JUDGED_ON_NBS = _('The pH was measured on the %(scale)s and put on the NBS scale by Millero’s (1986) step: the NH₃ is '
                  'judged at that pH + 0.03, the uncertainty of a pH reading, about 7 %% above its best estimate.')


def judged(kind, basis, corrected, equilibria):
    """Which value judged a water's NH3 ('nh3') or CO2 ('co2'), with the best estimate beside it, in words; '' for formula
    1 (its own value is the limits' basis), for the ideal water (an ionic strength of 0 in fresh water: the two are one,
    within 0.5 %) or without a value. An NH₃ of a water with seawater constants says what its best estimate rests on
    (`BEST_SEA`). KeyError for an unknown kind or basis."""
    if kind == 'co2' and equilibria.formula != 1 and equilibria.phosphate > 0 and corrected is not None:
        return str(JUDGED_WITHOUT_PHOSPHATE % {'value': number_format(corrected, JUDGED_DECIMALS[kind])})
    words = JUDGED[kind, basis]
    ideal = equilibria.ionic_strength == 0 and equilibria.sea_weight == 0
    if equilibria.formula == 1 or ideal or corrected is None:
        return ''
    said = str(words % {'value': number_format(corrected, JUDGED_DECIMALS[kind])} if basis == 'limits' else words)
    if kind == 'nh3' and equilibria.sea_weight > 0:
        said = f'{said} {BEST_SEA}'
    return said


def judged_on_nbs(scale):
    """What an NH₃ worked out from a pH measured on another scale than NBS says beside it (`JUDGED_ON_NBS`)."""
    return str(JUDGED_ON_NBS % {'scale': PH_SCALES[scale]})


def ionic_strength_unit(equilibria):
    """The unit of a water's ionic strength as a page says it (the audit of 2026-11-19, F8): per kg of water where it
    is the salinity's (DOE 1994, molal: sea water, and a fresh water given only its salinity), per litre where it is
    the fresh path's estimate from the conductivity, the hardness or the alkalinity (taken as per kg)."""
    return 'mol/kg H₂O' if equilibria.strength_source in ('salinity', 'seawater') else 'mol/L'


def last_own(reading):
    """What the page, the card and the alarm say of a unit's own last value that keeps its status while a value of its
    system stands in (read.last_own; decision of 2026-11-19 on the verification's F3-9): "last own value 0.8924
    critical on 02.11.2026 10:00, no recent data: measure this unit"."""
    from ..models.water_point import local_time
    from .evaluate import Status
    return _('last own value %(value)s %(status)s on %(time)s, no recent data: measure this unit') % {
        'value': number_format(reading.value, reading.parameter.decimals),
        'status': str(Status(reading.judged).label).lower(),
        'time': local_time(reading.at, reading.point).strftime('%d.%m.%Y %H:%M')}
