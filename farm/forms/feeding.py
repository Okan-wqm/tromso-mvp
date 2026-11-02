"""The feeding dialog: one call of the feeding service (farm/feeding/services.py), as the stock's operation
dialogs are of theirs (farm/forms/stock.py: the token, the farm's today, the service's reasons on their
fields, the acknowledgement offered once asked for)."""
import uuid

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS
from django.utils.translation import gettext_lazy as _

from ..feeding import services
from ..models import Equipment, Feed, FeedingRecord
from ..models.feeding import feeders_for
from ..stock.dates import local_today
from ..templatetags.feeding import amount
from .stock import DATE, DECIMAL, NOTES, Acknowledged, ServiceErrors


def feed_label(feed):
    """A feed in the list: its name, code and pellet: Smolt 3 (SM-3) · 3 mm."""
    if feed.pellet_size_mm is None:
        return str(feed)
    return _('%(feed)s · %(size)s mm') % {'feed': feed, 'size': amount(feed.pellet_size_mm)}


def suits(feed, species, weight_g):
    """Whether the feed's suitability rows say it suits fish of this species and average weight."""
    return any(row.species_id == species.pk and row.suits(weight_g) for row in feed.suitability.all())


class FeedChoice(forms.ModelChoiceField):
    def label_from_instance(self, feed):
        return feed_label(feed)


class FeedingForm(Acknowledged, ServiceErrors, forms.ModelForm):
    """Feed given to the unit: the day (the farm's today), the feed (active feeds, those that suit the
    unit's fish first), the kilos to the gram, and optionally the meals, the time, the feeder (one of
    the unit's site) and notes."""

    token = forms.UUIDField(widget=forms.HiddenInput)
    feed = FeedChoice(label=_('Feed'), queryset=Feed.objects.none())
    feeder = forms.ModelChoiceField(label=_('Feeder'), queryset=Equipment.objects.none(), required=False,
                                    help_text=_('Optional: the feeder that gave it, on the unit’s site.'))
    high_rate_ack = forms.BooleanField(
        label=_('Feed above the usual rate'), required=False,
        help_text=_('Tick it only when the amount is right, e.g. for fry that are fed more.'))

    ack_field = 'high_rate_ack'
    service_fields = {'unit': NON_FIELD_ERRORS}

    class Meta:
        model = FeedingRecord
        fields = ['date', 'feed', 'amount_kg', 'meals', 'time', 'feeder', 'notes', 'high_rate_ack']
        widgets = {'date': DATE, 'time': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
                   'amount_kg': forms.TextInput(attrs=DECIMAL), 'notes': NOTES}
        localized_fields = ['amount_kg']
        help_texts = {
            'amount_kg': _('As given, to the gram (0.035 for 35 g).'),
            'meals': _('Optional: how many meals it was given in.'),
            'time': _('Optional: the time of the feeding, or of its first meal.'),
        }

    def __init__(self, *args, unit, stock=None, **kwargs):
        super().__init__(*args, instance=FeedingRecord(unit=unit), **kwargs)
        self.unit = unit
        self.initial['date'] = local_today(unit)      # a new record: its own empty date would win over the field's
        self.fields['token'].initial = uuid.uuid4()
        self.fields['feed'].queryset = Feed.objects.filter(status=Feed.Status.ACTIVE).prefetch_related('suitability')
        self.fields['feed'].choices = self._feed_choices(stock)
        self.fields['feeder'].queryset = feeders_for(unit).order_by('name')

    def _feed_choices(self, stock):
        """The active feeds; when the unit holds fish, those that suit their species and average weight
        first, the others under "Other active feeds" (a choice among them is allowed: the page says so)."""
        feeds = list(self.fields['feed'].queryset)
        self.suiting = set()
        if stock is not None:
            species = stock.batches[0].species
            self.suiting = {feed.pk for feed in feeds if suits(feed, species, stock.avg_weight_g)}
        choices = [('', '---------')]
        if not self.suiting:
            return choices + [(feed.pk, feed_label(feed)) for feed in feeds]
        groups = [(_('Suitable for these fish'), [feed for feed in feeds if feed.pk in self.suiting]),
                  (_('Other active feeds'), [feed for feed in feeds if feed.pk not in self.suiting])]
        return choices + [(group, [(feed.pk, feed_label(feed)) for feed in members]) for group, members in groups
                          if members]

    def save(self, user):
        data = self.cleaned_data
        return services.record_feeding(
            user, unit=self.unit, day=data['date'], feed=data['feed'], amount_kg=data['amount_kg'],
            time=data['time'], meals=data['meals'], feeder=data['feeder'], notes=data['notes'],
            ack=data['high_rate_ack'], token=data['token'])
