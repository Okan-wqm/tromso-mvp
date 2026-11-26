"""The recheck of 2a2c8451 (REVIEW4.md), each held by a test that fails without its fix:

- F-A (probe SZ2): a message is never longer than its transport's payload limit (`max_bytes`: a push payload about
  4,000 bytes, an SMS 160). `outbox.text` builds to it: the open alarms first, the names that fit, "and K more",
  how many are open now, "see the alarm list"; a word or a number is never cut in half. 200 criticals of one kind
  through a push service that refuses over 4,000 characters are all told, none left;
- the critical follow-up time is at most 8 s, so a user cannot break the owner's 10 s from a value to its message;
- a second critical within the follow-up time waits for the follow-up message: it is not sent on its own at once, and
  it is told within the follow-up time (the surviving mutant: the hold removed)."""
import re

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.test import override_settings

from .. import outbox, services
from ..models import DeliveryAttempt, Notification, OutboxEntry, SeverityPolicy
from .doubles import RecordingTransport
from .test_review_fixes import Case

RECORDING = {'push': 'alarms.tests.doubles.RecordingTransport'}
SMS = {'push': 'alarms.tests.doubles.SmsTransport'}


class SizeCase(Case):
    def setUp(self):
        super().setUp()
        RecordingTransport.floods.clear()
        self.addCleanup(RecordingTransport.floods.clear)

    def units(self, count, seconds=0, words=''):
        """`count` critical oxygen alarms of the alarm system's one kind, each naming its unit, opened `seconds` after
        self.now, their notifications to the operator queued then."""
        at = self.at(seconds=seconds)
        made = []
        for number in range(count):
            alarm = services.open_alarm(
                source='system', parameter='sensors_failed', severity='critical', at=at, site=self.bergen, farm_wide=True,
                summary=f'T-{seconds:03d}{number:03d} · Middle: Dissolved oxygen 3.1 mg/L (critical){words}')
            made += services.queue_many([Notification(alarm=alarm, recipient=self.operator, channel='push', level=0,
                                                      queued_at=at)])
        return made

    def rounds(self, start, end):
        for second in range(start, end + 1):
            outbox.send_due(self.at(seconds=second))

    def assert_told_within(self, limit, made):
        texts = [sent.text for sent in RecordingTransport.sent]
        self.assertTrue(texts)
        for text in texts:
            self.assertLessEqual(len(text.encode('utf-8')), limit, text)
        for row in made:                                         # every one sent (in a message), none left untold
            self.assertTrue(DeliveryAttempt.objects.filter(notification=row, outcome='sent').exists(), row.pk)
        self.assertFalse(OutboxEntry.objects.exists())
        self.assertFalse(DeliveryAttempt.objects.filter(outcome__in=['failed', 'grouped']).exists())
        return texts


# ---- F-A ----------------------------------------------------------------------------------------------------------------
class PushLimitTests(SizeCase):
    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_200_criticals_of_one_kind_are_all_told_within_the_push_limit(self):            # probe SZ2
        made = self.units(200, words=', last own value 2 h ago, measure this unit')
        self.rounds(0, 30)
        texts = self.assert_told_within(4000, made)
        follow_up = next(text for text in texts if 'more critical alarms of one kind' in text)
        self.assertTrue(follow_up.startswith('199 more critical alarms of one kind since'), follow_up)
        self.assertIn('199 open now', follow_up)
        self.assertIn('see the alarm list', follow_up)
        named = [row for row in made[1:] if row.alarm.summary in follow_up]
        self.assertTrue(named)
        more = re.search(r'and (\d+) more', follow_up)
        self.assertIsNotNone(more, follow_up)
        self.assertEqual(len(named) + int(more.group(1)), 199)          # each named in full, or counted

    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_the_open_ones_are_named_before_the_cleared_ones(self):
        cleared = self.units(100, words=', last own value 2 h ago, measure this unit')
        for row in cleared:
            services.clear(row.alarm, self.at(seconds=1), 'restored')
        still_open = self.units(100, seconds=2, words=', last own value 2 h ago, measure this unit')
        self.rounds(2, 30)
        texts = self.assert_told_within(4000, cleared + still_open)
        follow_up = next(text for text in texts if 'more critical alarms of one kind' in text)
        self.assertIn('99 open now', follow_up)                          # the first open one went on its own
        self.assertFalse(any(row.alarm.summary in follow_up for row in cleared))
        self.assertTrue(any(row.alarm.summary in follow_up for row in still_open))


class SmsLimitTests(SizeCase):
    @override_settings(ALARM_TRANSPORTS=SMS)
    def test_a_follow_up_fits_an_sms(self):
        made = self.units(6, words=', last own value 2 h ago, measure this unit')
        self.rounds(0, 10)
        texts = self.assert_told_within(160, made)
        self.assertEqual(len(texts), 2)                                 # the first, then one follow-up for five
        self.assertIn('5 open now', texts[1])
        self.assertIn('see the alarm list', texts[1])

    @override_settings(ALARM_TRANSPORTS=SMS)
    def test_a_long_alarm_is_cut_between_words_never_inside_one(self):
        words = ' '.join(f'reading{number} 12.{number}5' for number in range(40))
        (row,) = self.units(1, words=f', {words}')
        self.rounds(0, 1)
        (text,) = self.assert_told_within(160, [row])
        self.assertTrue(text.endswith('…'), text)
        full = outbox.text(row)
        kept = text[:-1]
        self.assertTrue(full.startswith(kept), (kept, full))
        self.assertIn(full[len(kept)], ' ;,:', (kept, full[len(kept):]))     # the cut falls between two words


# ---- the follow-up bound and the hold ---------------------------------------------------------------------------------
class FollowUpTests(SizeCase):
    def test_the_critical_follow_up_is_at_most_8_seconds(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            SeverityPolicy.objects.filter(severity='critical').update(follow_up_seconds=9)
        row = SeverityPolicy.objects.get(severity='critical')
        row.follow_up_seconds = 9
        with self.assertRaises(ValidationError):
            row.full_clean()
        row.follow_up_seconds = 8
        row.full_clean()

    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_a_second_critical_within_the_follow_up_waits_for_it_and_is_told_in_time(self):
        (first,) = self.units(1)
        outbox.send_due(self.at(seconds=0))
        self.assertEqual([sent.pk for sent in RecordingTransport.sent], [first.pk])
        (second,) = self.units(1, seconds=1)
        held = outbox.send_due(self.at(seconds=1))
        self.assertEqual((held.held, held.sent), (1, 0))                # not sent on its own at once
        (third,) = self.units(1, seconds=2)
        for tick in range(2, 5):
            outbox.send_due(self.at(seconds=tick))
            self.assertEqual(len(RecordingTransport.sent), 1, tick)
        outbox.send_due(self.at(seconds=5))                              # the follow-up time (5 s) after the first
        self.assertEqual(len(RecordingTransport.sent), 2)
        text = RecordingTransport.sent[1].text
        self.assertIn(second.alarm.summary, text)
        self.assertIn(third.alarm.summary, text)
