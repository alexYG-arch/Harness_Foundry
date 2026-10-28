"""Exercise unchanged public behavior against the new, separate package versions.

These reuse independent fixture assertions, not historical PASS results.
Host-review records are synthetic; they do not accept a browser/search task.
"""
import json
from pathlib import Path
from unittest.mock import patch
from tests import test_capability_data as data
from tests import test_capability_doc as doc
from tests import test_capability_host_review as review
from tests import test_capability_python_environment as python
from tests import test_target_dashboard as dashboard

PACKAGES = Path(__file__).resolve().parents[1] / 'examples/capability-adapters/packages'


class DataV2Tests(data.CapabilityDataTests):
    def setUp(self):
        self.enterContext(patch.object(data, 'PACKAGE', PACKAGES/'data-summary/2'))
        super().setUp()

    def test_manifest_keeps_checker_private_and_package_has_no_expected_answer(self):
        manifest=json.loads((self.package/'capability.json').read_text())
        self.assertEqual((manifest['name'],manifest['version'],manifest['usage']),('data-summary','2','both'))
        self.assertEqual(manifest['verification_files'],['check_summary.py'])
        self.assertNotIn('check_summary.py',manifest['materials'])
        self.assertNotIn('check_summary.py',[entry['path'] for entry in manifest['tools']])
        self.assertFalse(list(self.package.glob('*expected*')))
        self.assertNotIn('harness_foundry',(self.package/'summarize_csv.py').read_text())


class DocV2Tests(doc.CapabilityDocTests):
    def setUp(self):
        self.enterContext(patch.object(doc, 'PACKAGE', PACKAGES/'doc-export/2'))
        super().setUp()


class HostReviewV2Tests(review.CapabilityHostReviewTests):
    def setUp(self):
        self.enterContext(patch.object(review, 'PACKAGE', PACKAGES/'host-review/2'))
        super().setUp()


class PythonV2Tests(python.CapabilityPythonEnvironmentTests):
    def setUp(self):
        package = PACKAGES/'python-environment/2'
        self.enterContext(patch.object(python, 'PACKAGE', package))
        self.enterContext(patch.object(python, 'TOOL', python.load('feature_python', package/'python_environment.py')))
        self.enterContext(patch.object(python, 'CHECK', python.load('feature_python_check', package/'check_python.py')))
        super().setUp()


class DashboardV5Tests(dashboard.TargetDashboardTests):
    def setUp(self):
        package = PACKAGES/'local-dashboard/5'
        self.enterContext(patch.object(dashboard, 'PACKAGE', package))
        self.enterContext(patch.object(dashboard, 'TARGET', python.load('feature_dashboard', package/'target.py')))
        super().setUp()
