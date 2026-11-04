"""The species catalogue: the species Norwegian fish farms grow or stock, with what is known about each.

When a species is saved under one of these scientific names, the fields left blank on its form are
filled in from here (farm.forms.species); a value that was typed is never replaced. The catalogue is
data in the code, not rows in the database: no species is ever created from it.

Official codes. Every species carries its FAO ASFIS 3-alpha code, which the Norwegian reports use as artskode:
Mattilsynet's reporting API asks for "kode i store bokstaver etter FAO-standarden" (its OpenAPI, read 2026-11-03),
and the codes were checked against the ASFIS list 2026.1 (docs/regulatory-reports.md, 3.4). The cleaner fish are
LUM (lumpfish), USB (ballan wrasse), YFM (corkwing), TBR (goldsinny) and ENX (rock cook); the source's map gave
the lumpfish USB and the wrasses BER, GRO and BNB, other species in ASFIS (SPC-32, REP-51). A blank code is
filled in from here, and a species of the catalogue whose code is verified cannot be given another one
(farm.models.Species.clean).

Names: the English common name, and the Norwegian name as the local name (the source's onboarding
seeder used Turkish names). Water: every water the species is farmed in. Salmon and trout grow up in
fresh water and are farmed on in sea water; Arctic char is farmed in fresh water, on land."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogueSpecies:
    scientific_name: str
    common_name: str              # English
    local_name: str               # Norwegian
    official_code: str
    official_code_verified: bool  # False: kept for reference, never filled in (none today)
    family: str
    freshwater: bool
    brackish: bool
    saltwater: bool
    cleaner_fish_type: str = ''   # Species.CleanerFishType


CATALOGUE = (
    # Grow-out species, FAO ASFIS 3-alpha codes.
    CatalogueSpecies('Salmo salar', 'Atlantic salmon', 'Laks', 'SAL', True, 'Salmonidae', True, False, True),
    CatalogueSpecies('Oncorhynchus mykiss', 'Rainbow trout', 'Regnbueørret', 'TRR', True, 'Salmonidae',
                     True, False, True),
    CatalogueSpecies('Salmo trutta', 'Brown trout', 'Ørret', 'TRS', True, 'Salmonidae', True, False, True),
    CatalogueSpecies('Salvelinus alpinus', 'Arctic char', 'Røye', 'ACH', True, 'Salmonidae', True, False, False),
    CatalogueSpecies('Gadus morhua', 'Atlantic cod', 'Torsk', 'COD', True, 'Gadidae', False, False, True),
    CatalogueSpecies('Hippoglossus hippoglossus', 'Atlantic halibut', 'Kveite', 'HAL', True, 'Pleuronectidae',
                     False, False, True),
    CatalogueSpecies('Scophthalmus maximus', 'Turbot', 'Piggvar', 'TUR', True, 'Scophthalmidae', False, False, True),
    CatalogueSpecies('Dicentrarchus labrax', 'European seabass', 'Havabbor', 'BSS', True, 'Moronidae',
                     False, True, True),
    CatalogueSpecies('Sparus aurata', 'Gilthead seabream', 'Dorade', 'SBG', True, 'Sparidae', False, True, True),
    # Cleaner fish, FAO ASFIS 3-alpha codes (the five Mattilsynet names: rognkjeks, berggylt, grønngylt, bergnebb,
    # gressgylt).
    CatalogueSpecies('Cyclopterus lumpus', 'Lumpfish', 'Rognkjeks', 'LUM', True, 'Cyclopteridae',
                     False, False, True, 'lumpfish'),
    CatalogueSpecies('Labrus bergylta', 'Ballan wrasse', 'Berggylt', 'USB', True, 'Labridae',
                     False, False, True, 'wrasse'),
    CatalogueSpecies('Symphodus melops', 'Corkwing wrasse', 'Grønngylt', 'YFM', True, 'Labridae',
                     False, False, True, 'wrasse'),
    CatalogueSpecies('Ctenolabrus rupestris', 'Goldsinny wrasse', 'Bergnebb', 'TBR', True, 'Labridae',
                     False, False, True, 'wrasse'),
    CatalogueSpecies('Centrolabrus exoletus', 'Rock cook', 'Gressgylt', 'ENX', True, 'Labridae',
                     False, False, True, 'wrasse'),
)


def find(scientific_name):
    """The catalogue's entry for a scientific name, whatever its case and spacing; None when it has none."""
    wanted = ' '.join((scientific_name or '').split()).lower()
    return next((entry for entry in CATALOGUE if entry.scientific_name.lower() == wanted), None)
