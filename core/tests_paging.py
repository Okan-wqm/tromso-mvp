"""Keyset paging (core.paging): a list that grows for ever (a ledger, the activity log, water samples) is read a page at
a time after the last row shown, never counted and never offset, so its cost does not grow with its history. Every tab
says how its list grows (`Resource.growth`): 'reference' lists stay small and keep page numbers, 'ledger' lists page
by key."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from .crud import Resource
from .models import AuditLog
from .paging import DEFAULT_SIZE, MAX_SIZE, Keyset


class ParseTests(SimpleTestCase):
    def keyset(self, **query):
        return Keyset.parse(RequestFactory().get('/', query), order=('-created_at', '-id'), model=AuditLog)

    def test_the_size_is_clamped_and_a_bad_one_is_the_default(self):
        self.assertEqual(self.keyset().size, DEFAULT_SIZE)
        self.assertEqual((DEFAULT_SIZE, MAX_SIZE), (50, 200))
        self.assertEqual(self.keyset(size='500').size, MAX_SIZE)
        self.assertEqual(self.keyset(size='0').size, 1)
        self.assertEqual(self.keyset(size='x').size, DEFAULT_SIZE)

    def test_a_broken_cursor_is_the_first_page_and_says_so(self):
        for cursor in ('%%%', 'eyJ4Ijoi', 'WyJub3QtYS1kYXRlIiwiMSJd'):
            keyset = self.keyset(after=cursor)
            self.assertEqual((keyset.after, keyset.invalid), (None, True))

    def test_an_order_on_a_column_that_may_be_null_is_refused(self):
        from farm.models import StockMovement
        with self.assertRaises(ValueError):
            Keyset(order=('avg_weight_g', 'id'), model=StockMovement)

    def test_the_order_must_end_with_a_unique_column(self):
        with self.assertRaises(ValueError):
            Keyset(order=('-created_at',), model=AuditLog)


class PageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('pager', 'p@example.com', 'x')
        now = timezone.now()
        # 7 rows, three of them at the same instant (the tie is broken by the id)
        times = [now - timedelta(minutes=minutes) for minutes in (1, 2, 2, 2, 3, 4, 5)]
        for number, at in enumerate(times):
            row = AuditLog.objects.create(user=self.user, user_name='p', action='create', entity_type='x',
                                          entity_id=str(number), entity_label=str(number))
            AuditLog.objects.filter(pk=row.pk).update(created_at=at)

    def walk(self, size):
        seen, after = [], None
        while True:
            query = {'size': str(size)} | ({'after': after} if after else {})
            keyset = Keyset.parse(RequestFactory().get('/', query), order=('-created_at', '-id'), model=AuditLog)
            with self.assertNumQueries(1):                       # size + 1 rows; no COUNT(*)
                rows, after = keyset.page(AuditLog.objects.all())
            self.assertLessEqual(len(rows), size)
            seen.extend(rows)
            if after is None:
                return seen

    def test_the_pages_hold_every_row_once_in_order(self):
        expected = list(AuditLog.objects.order_by('-created_at', '-id'))
        for size in (1, 2, 3, 7, 50):
            with self.subTest(size=size):
                self.assertEqual(self.walk(size), expected)

    def test_the_last_page_has_no_next_cursor(self):
        keyset = Keyset.parse(RequestFactory().get('/', {'size': '7'}), order=('-created_at', '-id'), model=AuditLog)
        rows, after = keyset.page(AuditLog.objects.all())
        self.assertEqual((len(rows), after), (7, None))

    def test_a_row_added_at_the_top_while_paging_neither_repeats_nor_skips_a_row(self):
        first = Keyset.parse(RequestFactory().get('/', {'size': '3'}), order=('-created_at', '-id'), model=AuditLog)
        rows, after = first.page(AuditLog.objects.all())
        AuditLog.objects.create(user=self.user, user_name='p', action='create', entity_type='x', entity_id='new',
                                entity_label='new')
        rest = Keyset.parse(RequestFactory().get('/', {'size': '50', 'after': after}), order=('-created_at', '-id'),
                            model=AuditLog)
        more, _after = rest.page(AuditLog.objects.all())
        self.assertEqual(rows + more, list(AuditLog.objects.exclude(entity_id='new').order_by('-created_at', '-id')))


class GrowthTests(SimpleTestCase):
    def test_every_tab_says_how_its_list_grows(self):
        unclassified = [resource.__name__ for resource in Resource.registry
                        if getattr(resource, 'growth', None) not in ('reference', 'ledger')]
        self.assertEqual(unclassified, [], 'Declare growth = "reference" or "ledger" beside page_size (core.crud)')
