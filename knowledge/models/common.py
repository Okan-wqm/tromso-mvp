"""What the library and the knowledge entries share: the topics, the languages, and how their text is made
searchable."""
from django.contrib.postgres.search import SearchVector
from django.db import models
from django.utils.translation import gettext_lazy as _

# Every stored text is analysed with PostgreSQL's `simple` configuration: lower case, every word kept as written,
# no stemming, whatever the language. The library holds English, Norwegian and Turkish texts, often several in
# one document (a Norwegian report with an English abstract), so no one language's stemmer suits a stored text;
# the stemming is done on the query side instead, in every language (knowledge.search).
SEARCH_CONFIG = 'simple'


class Topic(models.TextChoices):
    """What a piece of knowledge is about. An AI agent that watches one part of the farm (the water, the
    purchasing) will read the entries of its topics."""
    WATER_QUALITY = 'water_quality', _('Water quality')
    FEEDING = 'feeding', _('Feeding')
    HEALTH = 'health', _('Health')
    GROWTH = 'growth', _('Growth')
    WELFARE = 'welfare', _('Welfare')
    HARVEST = 'harvest', _('Harvest')
    PROCUREMENT = 'procurement', _('Procurement and logistics')
    EQUIPMENT = 'equipment', _('Equipment')
    REGULATION = 'regulation', _('Regulation')
    OTHER = 'other', _('Other')


class Language(models.TextChoices):
    """The language a document is written in (ISO 639-1)."""
    ENGLISH = 'en', _('English')
    NORWEGIAN = 'no', _('Norwegian')
    TURKISH = 'tr', _('Turkish')
    SWEDISH = 'sv', _('Swedish')
    DANISH = 'da', _('Danish')
    ICELANDIC = 'is', _('Icelandic')
    GERMAN = 'de', _('German')
    FRENCH = 'fr', _('French')
    SPANISH = 'es', _('Spanish')
    OTHER = 'other', _('Other language')


def search_vector(*weighted):
    """The search vector of a row: each (field, weight) analysed with SEARCH_CONFIG and weighted (A counts most,
    D least), for a GeneratedField, so the database keeps it in step with the text whatever writes the row."""
    vectors = [SearchVector(name, config=SEARCH_CONFIG, weight=weight) for name, weight in weighted]
    combined = vectors[0]
    for vector in vectors[1:]:
        combined = combined + vector
    return combined


def topic_labels(values):
    """The labels of a record's topics, in the order of the topics."""
    return [Topic(value).label for value in values or []]
