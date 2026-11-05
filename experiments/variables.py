"""The variables an experiment is judged on (Research › Experiments). Today only what the farm's own reads give:
the feed conversion ratios, survival and biomass gain; weight and growth rates join with the growth-indicator
area, and each addition is one entry here and in the database check of `Experiment.primary_endpoint` (a
migration), so a stored endpoint is always one the reads can answer."""
from django.db import models
from django.utils.translation import gettext_lazy as _


class Endpoint(models.TextChoices):
    BFCR = 'bfcr', _('Biological FCR')
    EFCR = 'efcr', _('Economic FCR')
    SURVIVAL = 'survival', _('Survival')
    BIOMASS_GAIN = 'biomass_gain', _('Biomass gain')


ENDPOINTS = Endpoint.choices
