"""The disease catalogue a health event's diagnosis is chosen from, with what Norwegian law says about each.

Data in the code, like the species catalogue (farm/species_catalog.py): a diagnosis is stored as its code and
the database checks it is one of these. Which diseases are listed, and so must be notified, was read on
2026-11-03 in:

- dyrehelseforskriften (FOR-2022-04-06-631) § 6, the national list: category F, bacterial kidney disease,
  Gyrodactylus salaris, furunculosis, pancreas disease, systemic Flavobacterium psychrophilum infection
  (rainbow trout), francisellosis, crayfish plague and Lepeophtheirus salmonis (sea lice); category G,
  viral nervous necrosis and piscirickettsiosis;
- the EU list it takes over in § 5 (Commission Implementing Regulation (EU) 2018/1882, annex, as amended):
  epizootic haematopoietic necrosis (category A), viral haemorrhagic septicaemia, infectious
  haematopoietic necrosis and HPR-deleted infectious salmon anaemia (categories C, D and E);
- § 7: on reason to suspect, or on finding, a listed disease, the person in charge notifies Mattilsynet at
  once (umiddelbart). Sea lice are the exception: they are reported every week with the lice counts
  (lakselusforskriften § 10), so they raise no notification banner here.

ILA (infectious salmon anaemia) is endemic in Norway and listed (HLT-11: the source called it exotic).
Diseases that are not listed (HSMI, CMS, IPN, AGD, winter ulcer and others) need no notification as such;
§ 7 second paragraph still asks for a vet's assessment of unusual mortality of unclear cause, and for a
notification when the cause stays unclear. Pasteurellosis was proposed for the national list in 2025; it is
not listed here until the regulation lists it. Crayfish plague is left out: the farm keeps no crayfish.

A vet or fish-health biologist should read this list before it is relied on, and it is to be read against
Lovdata again when the regulation changes."""
from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _

# Where a disease is listed.
EU_A = 'eu_a'
EU_C = 'eu_c'
NATIONAL_F = 'national_f'
NATIONAL_G = 'national_g'
NOT_LISTED = ''

LISTINGS = {
    EU_A: _('EU-listed, category A'),
    EU_C: _('EU-listed, categories C, D and E'),
    NATIONAL_F: _('Norwegian list, category F'),
    NATIONAL_G: _('Norwegian list, category G'),
    NOT_LISTED: _('Not listed'),
}


@dataclass(frozen=True)
class Disease:
    code: str
    name: str             # English, translated when shown
    local_name: str       # the Norwegian name, as vets and Mattilsynet write it
    agent: str            # the pathogen
    listing: str
    notifiable: bool      # notify Mattilsynet at once on suspicion (dyrehelseforskriften § 7)

    @property
    def listing_label(self):
        return LISTINGS[self.listing]


CATALOGUE = (
    # EU-listed (dyrehelseforskriften § 5).
    Disease('isa', _('Infectious salmon anaemia (ISA)'), 'ILA', 'HPR-deleted ISA virus', EU_C, True),
    Disease('vhs', _('Viral haemorrhagic septicaemia (VHS)'), 'VHS', 'VHS virus', EU_C, True),
    Disease('ihn', _('Infectious haematopoietic necrosis (IHN)'), 'IHN', 'IHN virus', EU_C, True),
    Disease('ehn', _('Epizootic haematopoietic necrosis (EHN)'), 'EHN', 'EHN virus', EU_A, True),
    # The national list (§ 6).
    Disease('pd', _('Pancreas disease (PD)'), 'Pankreassykdom', 'Salmonid alphavirus', NATIONAL_F, True),
    Disease('bkd', _('Bacterial kidney disease (BKD)'), 'Bakteriell nyresyke', 'Renibacterium salmoninarum',
            NATIONAL_F, True),
    Disease('furunculosis', _('Furunculosis'), 'Furunkulose', 'Aeromonas salmonicida subsp. salmonicida',
            NATIONAL_F, True),
    Disease('gyrodactylosis', _('Gyrodactylus salaris infection'), 'Gyrodactylose', 'Gyrodactylus salaris',
            NATIONAL_F, True),
    Disease('flavobacteriosis', _('Systemic Flavobacterium psychrophilum infection (rainbow trout)'),
            'Systemisk infeksjon med Flavobacterium psychrophilum', 'Flavobacterium psychrophilum', NATIONAL_F, True),
    Disease('francisellosis', _('Francisellosis'), 'Francisellose', 'Francisella sp.', NATIONAL_F, True),
    Disease('sea_lice', _('Sea lice'), 'Lakselus', 'Lepeophtheirus salmonis', NATIONAL_F, False),
    Disease('vnn', _('Viral nervous necrosis (VNN/VER)'), 'Viral nervøs nekrose', 'Betanodavirus', NATIONAL_G,
            True),
    Disease('piscirickettsiosis', _('Piscirickettsiosis'), 'Piscirickettsiose', 'Piscirickettsia salmonis',
            NATIONAL_G, True),
    # Not listed.
    Disease('hsmi', _('Heart and skeletal muscle inflammation (HSMI)'), 'HSMB', 'Piscine orthoreovirus (PRV-1)',
            NOT_LISTED, False),
    Disease('cms', _('Cardiomyopathy syndrome (CMS)'), 'Kardiomyopatisyndrom', 'Piscine myocarditis virus',
            NOT_LISTED, False),
    Disease('ipn', _('Infectious pancreatic necrosis (IPN)'), 'IPN', 'IPN virus', NOT_LISTED, False),
    Disease('agd', _('Amoebic gill disease (AGD)'), 'Amøbegjellesykdom', 'Paramoeba perurans', NOT_LISTED, False),
    Disease('winter_ulcer', _('Winter ulcer'), 'Vintersår', 'Moritella viscosa', NOT_LISTED, False),
    Disease('yersiniosis', _('Yersiniosis'), 'Yersiniose', 'Yersinia ruckeri', NOT_LISTED, False),
    Disease('pasteurellosis', _('Pasteurellosis'), 'Pasteurellose', 'Pasteurella sp.', NOT_LISTED, False),
    Disease('tenacibaculosis', _('Tenacibaculosis'), 'Tenacibaculose', 'Tenacibaculum spp.', NOT_LISTED, False),
    Disease('gill_disease', _('Gill disease'), 'Gjellesykdom', '', NOT_LISTED, False),
    Disease('saprolegniosis', _('Saprolegniosis'), 'Saprolegniose', 'Saprolegnia spp.', NOT_LISTED, False),
    Disease('other', _('Other diagnosis'), '', '', NOT_LISTED, False),
)

BY_CODE = {disease.code: disease for disease in CATALOGUE}
CHOICES = [(disease.code, disease.name) for disease in CATALOGUE]
NOTIFIABLE = tuple(disease.code for disease in CATALOGUE if disease.notifiable)


def get(code):
    """The catalogue's disease with this code; None for a blank or unknown one."""
    return BY_CODE.get(code)
