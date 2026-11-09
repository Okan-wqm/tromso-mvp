"""The Rust core's four small charts (chemcore/core/src/plots.rs, through farm/water/native.py) against golden v1: for
40 waters, each chart's pH and value ranges, unit, curves, bands, verticals, horizontals and dots, or that it cannot
be drawn, within the classes of chemcore/tolerances.toml; the pH axis widened to the water and its ends on half units,
the grid STEP apart, the bands cut to the axis."""
import gzip
import importlib.util
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from ..water import native

ROOT = Path(settings.BASE_DIR)
V1 = ROOT / 'chemcore' / 'golden' / 'v1'


class PlotsParityTests(SimpleTestCase):
    def test_every_small_chart_of_golden_v1_within_its_class(self):
        spec = importlib.util.spec_from_file_location('golden_parity', ROOT / 'chemcore' / 'scripts' / 'golden_parity.py')
        parity = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(parity)
        with gzip.open(V1 / 'plots.jsonl.gz', 'rt', encoding='utf-8') as stream:
            records = [json.loads(line) for line in stream]
        found, drawn = [], 0
        for record in records:
            ours = native.plots(record['water'], record['limits'])
            self.assertEqual(set(ours), {'nh3', 'h2s', 'carbonate', 'saturation'})
            found += parity.compare(record['plots'], json.loads(json.dumps(ours)))
            drawn += sum(plot is not None for plot in ours.values())
        self.assertEqual(len(records), 40)
        self.assertGreater(drawn, 100)
        self.assertEqual(found[:5], [])
