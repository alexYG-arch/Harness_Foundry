"""Host snapshot operations only; these records are not actual business review."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'examples/harness-composition-upgrade/integration/prepare_host_evidence.py'
SPEC = importlib.util.spec_from_file_location('r3_host_evidence', PATH)
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


class HostEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out, self.fixture, self.evidence = [self.root / x for x in ('product', 'fixture', 'observations')]
        for folder in (self.out, self.fixture, self.evidence):
            folder.mkdir()
        self.manifest = {'id': 'prd_design', 'outputs': ['prd.md'],
                         'v2_additional_outputs': ['state-transitions.json'],
                         'workflows': {'v1': 'v1.md', 'v2': 'v2.md'}}
        (self.fixture / 'manifest.json').write_text(json.dumps(self.manifest))
        (self.fixture / 'v1.md').write_text('original workflow')
        (self.fixture / 'v2.md').write_text('updated workflow')
        (self.out / 'prd.md').write_bytes(b'actual product bytes\n')
        (self.evidence / 'readback.txt').write_text('synthetic test observation')
        self.review = {'reviewer': 'test fixture', 'observations': [
            {'id': 'render-mobile-desktop', 'result': 'UNKNOWN',
             'reason': 'not run in this source test', 'evidence_refs': ['readback.txt']}]}

    def prepare(self, destination=None, version='v1'):
        return HELPER.prepare('prd-design', version, self.out, self.fixture,
                              self.evidence, self.review, destination or self.root / 'snapshot')

    def test_copies_actual_bytes_and_preserves_incomplete_observation(self):
        result = self.prepare()
        self.assertEqual(result['observations'][0]['result'], 'UNKNOWN')
        self.assertEqual(result['observations'][0]['evidence_refs'], ['evidence/readback.txt'])
        self.assertEqual((self.root / 'snapshot/reviewed-output/prd.md').read_bytes(),
                         (self.out / 'prd.md').read_bytes())
        self.assertEqual((self.root / 'snapshot/workflow.md').read_text(), 'original workflow')
        self.assertNotIn('accepted', result)
        self.assertNotIn('status', result)

    def test_v2_requires_new_output_and_preserves_previous_evidence(self):
        self.prepare()
        with self.assertRaises(ValueError):
            self.prepare(self.root / 'next', 'v2')
        self.assertFalse((self.root / 'next').exists())
        (self.out / 'state-transitions.json').write_text('{}')
        self.prepare(self.root / 'next', 'v2')
        self.assertEqual((self.root / 'next/workflow.md').read_text(), 'updated workflow')
        self.assertEqual((self.root / 'snapshot/workflow.md').read_text(), 'original workflow')
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_no_write_into_product_or_fixture(self):
        for parent in (self.out, self.fixture):
            with self.subTest(parent=parent), self.assertRaises(ValueError):
                self.prepare(parent / 'new-snapshot')
            self.assertFalse((parent / 'new-snapshot').exists())

    def test_missing_reference_does_not_create_snapshot(self):
        self.review['observations'][0]['evidence_refs'] = ['missing.png']
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.root / 'snapshot').exists())

    def test_no_default_pass_or_invented_observations(self):
        self.review['observations'] = []
        result = self.prepare()
        self.assertEqual(result['observations'], [])

    def test_named_evidence_does_not_follow_symlinks_or_parent_paths(self):
        (self.evidence / 'alias.txt').symlink_to(self.evidence / 'readback.txt')
        for reference in ('alias.txt', '../product/prd.md'):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                self.review['observations'][0]['evidence_refs'] = [reference]
                self.prepare()


if __name__ == '__main__':
    unittest.main()
