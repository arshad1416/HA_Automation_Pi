"""Ensure climate checks import quietly and discovery executes real assertions."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'verification/test_climate_tou_guards.py'


def import_guards():
    spec = importlib.util.spec_from_file_location('climate_guards_import_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClimateDiscoveryTests(unittest.TestCase):
    def test_import_neither_reads_configuration_nor_exits_or_prints(self):
        output = io.StringIO()
        with patch('builtins.open', side_effect=AssertionError('configuration read during import')):
            with contextlib.redirect_stdout(output):
                import_guards()
        self.assertEqual(output.getvalue(), '')

    def test_discovery_executes_climate_assertions(self):
        module = import_guards()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ('automations/10_climate_comfort.yaml', 'automations/01_main.yaml',
                        'automations/06_enhancements.yaml'):
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                text = (ROOT / rel).read_text()
                if rel.endswith('01_main.yaml'):
                    self.assertIn('id: tariff_change', text)
                    text = text.replace('id: tariff_change', 'id: intentionally_missing_tariff_change')
                target.write_text(text)
            module.ROOT = root
            suite = unittest.defaultTestLoader.loadTestsFromModule(module)
            result = unittest.TestResult()
            suite.run(result)
            self.assertGreater(result.testsRun, 0)
            self.assertEqual(len(result.errors), 0)
            self.assertEqual(len(result.failures), 1)
            self.assertIn('tariff_change trigger missing', result.failures[0][1])


if __name__ == '__main__':
    unittest.main()
