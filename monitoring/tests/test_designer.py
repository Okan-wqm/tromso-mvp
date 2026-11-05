"""The card designer's server side: the template form's Design tab hands the TypeScript everything it shows (the widget
catalogue, the units to preview on, the preview address, the sentences it announces) in the person's language, and the
preview draws the same card the wall would for one real unit, writing nothing; a forced state is possible there only."""
import json

from django.urls import reverse

from core.models import AuditLog, Profile

from ..cards import builtin
from ..models import CardTemplate
from .golden import Tree
from .test_template_pages import DESIGNER, LAYOUT, PagesCase

PREVIEW = reverse('monitoring:cardtemplate_preview')


def json_script(html, element_id):
    node = next(each for each in Tree(html).root.walk() if each.attrs.get('id') == element_id)
    return json.loads(node.text())


class DesignTabTests(PagesCase):
    def test_the_form_hands_the_designer_its_catalogue_units_address_and_sentences(self):
        html = self.client.get(reverse('monitoring:cardtemplate_create')).content.decode()
        catalogue = json_script(html, 'card-catalogue')
        self.assertEqual(catalogue['columns'], 12)
        self.assertIn('value', [widget['type'] for widget in catalogue['widgets']])
        units = json_script(html, 'card-units')
        self.assertIn({'value': str(self.t2.pk), 'label': 'T-02'}, units)
        root = next(node for node in Tree(html).root.walk() if 'data-designer' in node.attrs)
        self.assertEqual(root.attrs['data-preview-url'], PREVIEW)
        for key in ('data-announce-moved', 'data-announce-resized', 'data-announce-added', 'data-announce-removed',
                    'data-label-undo', 'data-label-redo', 'data-label-remove', 'data-label-x', 'data-label-y',
                    'data-label-w', 'data-label-h', 'data-label-binding', 'data-label-point'):
            with self.subTest(attribute=key):
                self.assertTrue(root.attrs.get(key), key)
        self.assertIn('js/designer.js', html)
        self.assertIn('name="layout"', html)                       # the JSON the designer fills is the form's own field

    def test_the_designer_speaks_the_persons_language(self):
        Profile.objects.update_or_create(user=self.designer, defaults={'language': 'nb'})
        html = self.client.get(reverse('monitoring:cardtemplate_create')).content.decode()
        root = next(node for node in Tree(html).root.walk() if 'data-designer' in node.attrs)
        self.assertNotEqual(root.attrs['data-label-undo'], 'Undo')
        self.assertNotEqual(json_script(html, 'card-catalogue')['widgets'][0]['label'], 'Value')


class PreviewTests(PagesCase):
    def preview(self, layout=LAYOUT, unit=None, **extra):
        return self.client.post(PREVIEW, json.dumps({'layout': layout, 'unit': str((unit or self.t2).pk), **extra}),
                                content_type='application/json')

    def test_the_preview_is_the_card_the_wall_draws_and_writes_nothing(self):
        before = (AuditLog.objects.count(), CardTemplate.all_objects.count())
        response = self.preview()
        self.assertEqual(response.status_code, 200)
        answer = response.json()
        self.assertEqual(answer['problems'], [])
        self.assertIn(f'data-key="card:{self.t2.pk}"', answer['html'])
        self.assertIn('data-preview', answer['html'])
        self.assertIn('w w-value', answer['html'])
        self.assertEqual((AuditLog.objects.count(), CardTemplate.all_objects.count()), before)

    def test_a_layout_with_errors_says_them_and_draws_nothing(self):
        answer = self.preview({'schema': 1, 'widgets': [{**LAYOUT['widgets'][0], 'x': 11}]}).json()
        self.assertEqual(answer['html'], '')
        self.assertEqual([(problem['severity'], problem['widget'], problem['code']) for problem in answer['problems']],
                         [('error', 'w1', 'bounds')])
        self.assertIn('Widget w1', answer['problems'][0]['message'])
        warned = self.preview({'schema': 1, 'widgets': [{'id': 'w1', 'type': 'tasks', 'x': 0, 'y': 0, 'w': 6, 'h': 2}]})
        self.assertTrue(warned.json()['html'])                     # a warning draws the card and says so
        self.assertEqual([problem['code'] for problem in warned.json()['problems']], ['no_oxygen'])

    def test_a_state_can_be_forced_here_only(self):
        answer = self.preview(state='critical').json()
        self.assertIn('monitor-critical', answer['html'])
        self.assertNotIn('monitor-critical', self.preview().json()['html'])

    def test_the_preview_needs_the_change_right_a_post_a_known_unit_and_a_small_body(self):
        self.assertEqual(self.client.get(PREVIEW).status_code, 405)
        self.assertEqual(self.preview(unit=self.t2, extra=1).status_code, 200)
        self.assertEqual(self.client.post(PREVIEW, '{"layout": ', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(PREVIEW, json.dumps({'layout': LAYOUT, 'unit': 'nope'}),
                                          content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(PREVIEW, json.dumps({'layout': LAYOUT, 'unit': str(self.t2.pk),
                                                               'pad': 'x' * 70000}),
                                          content_type='application/json').status_code, 413)
        self.as_person('looker', 'view_cardtemplate', 'view_stockoperation')
        self.assertEqual(self.preview().status_code, 403)

    def test_the_preview_shows_only_what_the_previewer_may_read(self):
        self.as_person('stock-designer', 'change_cardtemplate', 'view_stockoperation')
        html = self.preview(builtin.DETAILED_LAYOUT).json()['html']
        self.assertIn('Water: not shown to you', html)
