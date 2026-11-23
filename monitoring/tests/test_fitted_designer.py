"""Phase 1D: a FITTED template in the designer. The validator knows a template's measure: a widget with no fitted look
on a fitted card is an error that names it (review R7: such a card was cut on a wall without a word), as is a layout of
more rows than a fitted card shares its height in; a widget whose place is too low or too narrow for what it prints is
a warning; a widget made for a fitted card on a card that flows is a warning too. The form refuses the measure with
the validator's sentence, and the preview draws the card fitted, at its measure, with the same problems."""
import json

from django.test import SimpleTestCase
from django.urls import reverse

from ..cards import builtin, catalogue, validate
from ..forms import CardTemplateForm
from ..models import CardTemplate
from .golden import Tree
from .test_template_pages import PagesCase

PREVIEW = reverse('monitoring:cardtemplate_preview')


def found(layout, measure=None):
    return [(problem.severity, problem.widget, problem.code) for problem in validate.validate(layout, measure)]


class ValidatorTests(SimpleTestCase):
    def test_the_fitted_built_ins_are_clean_at_their_measures(self):
        self.assertEqual(found(builtin.SMALL_LAYOUT, builtin.SMALL_MEASURE), [])
        self.assertEqual(found(builtin.BIG_LAYOUT, builtin.BIG_MEASURE), [])

    def test_a_widget_with_no_fitted_look_is_an_error_on_a_fitted_card_and_names_itself(self):
        problems = validate.validate(builtin.SIMPLE_LAYOUT, (31, 20))
        self.assertEqual([(each.severity, each.widget, each.code) for each in problems],
                         [('error', 'w1', 'fit_look'), ('error', 'w2', 'fit_look'), ('error', 'w3', 'fit_look'),
                          ('error', 'w5', 'fit_look')])
        self.assertEqual(problems[1].message, 'Widget w2: Fish has no fitted look and would be cut on a fitted card. '
                                              'Remove it, or leave the card’s width and height empty.')
        # the same layout on a card that flows is what it always was
        self.assertEqual(found(builtin.SIMPLE_LAYOUT), [])

    def test_the_looks_are_the_catalogues(self):
        fitted = {spec.type for spec in catalogue.WIDGETS.values() if catalogue.FIT in spec.looks}
        self.assertEqual(fitted, {'value', 'water_table', 'ph_window', 'chart', 'dosing', 'points', 'stock'})
        only = {spec.type for spec in catalogue.WIDGETS.values() if spec.looks == (catalogue.FIT,)}
        self.assertEqual(only, {'chart', 'dosing', 'points', 'stock'})
        for spec in catalogue.WIDGETS.values():
            self.assertEqual(catalogue.FIT in spec.looks, spec.fit_units is not None, spec.type)

    def test_more_rows_than_a_fitted_card_has_is_an_error(self):
        layout = {'schema': 1, 'widgets': [
            {'id': f'w{index}', 'type': 'value', 'x': 0, 'y': 4 * index, 'w': 6, 'h': 4, 'bind': {'parameter': 'oxygen_mg_l'}}
            for index in range(7)]}
        self.assertIn(('error', '', 'fit_rows'), found(layout, (31, 64)))
        self.assertNotIn(('error', '', 'fit_rows'), found(layout))

    def test_a_place_too_low_or_too_narrow_for_what_it_prints_is_a_warning(self):
        low = {'schema': 1, 'widgets': [
            {'id': 'w1', 'type': 'value', 'x': 0, 'y': 0, 'w': 6, 'h': 2, 'bind': {'parameter': 'oxygen_mg_l'}},
            {'id': 'w2', 'type': 'ph_window', 'x': 0, 'y': 2, 'w': 12, 'h': 3}]}
        self.assertEqual(found(low, (31, 10)), [('warning', 'w1', 'fit_low')])
        self.assertEqual(found(low, (31, 16)), [])
        narrow = {'schema': 1, 'widgets': [
            {'id': 'w1', 'type': 'value', 'x': 0, 'y': 0, 'w': 2, 'h': 4, 'bind': {'parameter': 'oxygen_mg_l'}}]}
        self.assertEqual(found(narrow, (20, 12)), [('warning', 'w1', 'fit_narrow')])
        self.assertEqual(found(narrow, (48, 12)), [])

    def test_a_widget_made_for_a_fitted_card_warns_on_a_card_that_flows(self):
        layout = {'schema': 1, 'widgets': [
            {'id': 'w1', 'type': 'value', 'x': 0, 'y': 0, 'w': 6, 'h': 2, 'bind': {'parameter': 'oxygen_mg_l'}},
            {'id': 'w2', 'type': 'chart', 'x': 0, 'y': 2, 'w': 12, 'h': 8}]}
        self.assertEqual(found(layout), [('warning', 'w2', 'needs_fit')])
        self.assertNotIn(('warning', 'w2', 'needs_fit'), found(layout, (48, 40)))


class FormTests(PagesCase):
    def posted(self, **fields):
        return {'name': 'Fitted copy', 'description': '', 'expanded': '', 'layout': json.dumps(builtin.SIMPLE_LAYOUT),
                'measure_w': '', 'measure_h': '', **fields}

    def test_a_template_with_no_fitted_look_cannot_be_given_a_measure_and_the_form_says_why(self):
        """Review R7."""
        form = CardTemplateForm(data=self.posted(measure_w='31', measure_h='20'))
        self.assertFalse(form.is_valid())
        (said,) = form.errors['measure_w']
        self.assertTrue(said.startswith('This layout cannot be a fitted card: '), said)
        for name in ('Experiments', 'Fish', 'Feeding', 'Deffeyes chart'):
            self.assertIn(name, said)
        self.assertIn('leave the width and the height empty', said)
        # through the page: nothing is stored
        response = self.client.post(reverse('monitoring:cardtemplate_create'), self.posted(measure_w='31', measure_h='20'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CardTemplate.objects.filter(name='Fitted copy').exists())
        # without the measure the same layout is a card that flows, as ever; and a layout of fitted looks takes one
        self.assertTrue(CardTemplateForm(data=self.posted()).is_valid())
        fitted = CardTemplateForm(data=self.posted(layout=json.dumps(builtin.SMALL_LAYOUT), measure_w='31', measure_h='12'))
        self.assertTrue(fitted.is_valid(), fitted.errors)


class PreviewTests(PagesCase):
    def ask(self, **asked):
        return self.client.post(PREVIEW, json.dumps({'unit': str(self.t2.pk), **asked}), content_type='application/json')

    def test_the_preview_draws_a_fitted_template_fitted_at_its_measure(self):
        answer = self.ask(layout=builtin.SMALL_LAYOUT, measure=[31, 12]).json()
        self.assertEqual(answer['problems'], [])
        (card,) = [node for node in Tree(answer['html']).root.walk() if node.tag == 'article']
        self.assertTrue({'is-fit', 'mw-31', 'mh-12'} <= set(card.classes))
        self.assertIn('data-preview', card.attrs)
        self.assertFalse([node for node in card.walk() if 'data-dock' in node.attrs])    # a preview opens nothing
        # another measure is another card; no measure is the card that flows
        self.assertIn('mw-40 mh-16', self.ask(layout=builtin.SMALL_LAYOUT, measure=[40, 16]).json()['html'])
        self.assertNotIn('is-fit', self.ask(layout=builtin.SMALL_LAYOUT).json()['html'])
        self.assertNotIn('is-fit', self.ask(layout=builtin.SMALL_LAYOUT, measure=None).json()['html'])

    def test_the_preview_says_the_fitted_problems_and_draws_nothing_on_an_error(self):
        answer = self.ask(layout=builtin.SIMPLE_LAYOUT, measure=[31, 20]).json()
        self.assertEqual(answer['html'], '')
        self.assertEqual({(each['severity'], each['code']) for each in answer['problems']}, {('error', 'fit_look')})
        low = {'schema': 1, 'widgets': [
            {'id': 'w1', 'type': 'value', 'x': 0, 'y': 0, 'w': 6, 'h': 2, 'bind': {'parameter': 'oxygen_mg_l'}},
            {'id': 'w2', 'type': 'ph_window', 'x': 0, 'y': 2, 'w': 12, 'h': 3}]}
        answer = self.ask(layout=low, measure=[31, 10]).json()
        self.assertEqual([(each['severity'], each['widget'], each['code']) for each in answer['problems']],
                         [('warning', 'w1', 'fit_low')])
        self.assertIn('is-fit', answer['html'])                      # a warning never stops the drawing

    def test_a_measure_that_is_no_measure_is_refused(self):
        for measure in ([5, 12], [31, 900], [31], 'wide', [31.5, 12]):
            with self.subTest(measure=measure):
                self.assertEqual(self.ask(layout=builtin.SMALL_LAYOUT, measure=measure).status_code, 400)
