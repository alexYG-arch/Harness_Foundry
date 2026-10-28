"""Exercise unchanged public behavior against the new, separate package versions.

These reuse independent fixture assertions, not historical PASS results.
Host-review records are synthetic; they do not accept a browser/search task.
"""
import json
import sys
import tempfile
import unittest
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

    def test_loopback_start_does_not_depend_on_hostname_lookup(self):
        self.make_config()
        before = self.all_bytes()
        with patch('socket.getfqdn', side_effect=AssertionError('loopback must not need DNS')):
            observer = self.host.observer_from_config(self.config)
            try:
                observer.start()
                self.assertEqual(self.request(observer)['business']['items'][0]['state'], 'PASS')
            finally:
                observer.stop()
        self.assertEqual(before, self.all_bytes())


class NativeDependencyV2Tests(unittest.TestCase):
    def observe(self, package, extra_header=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            owner, arm, intel = [root/name for name in ('universal binary', 'arm.dylib', 'intel.dylib')]
            for item in (owner, arm, intel): item.write_text('fixture native bytes')
            helper = python.load('feature_native_deps', package/'native_dependencies.py')
            runtime = helper._runtime()
            def query(argv, cwd, report_dir, **kwargs):
                report = Path(report_dir); report.mkdir()
                item = Path(argv[-1]); lines = [str(item)+':']
                if item == owner:
                    lines = [str(item)+' (architecture arm64):', '\t'+str(arm)+' (compatibility version 1.0.0, current version 1.0.0)',
                             (extra_header if extra_header is not None else str(item)+' (architecture x86_64):'),
                             '\t'+str(intel)+' (compatibility version 1.0.0, current version 1.0.0)']
                lines.append('\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)')
                (report/'stdout.txt').write_text('\n'.join(lines)+'\n')
                return {'status':'FINISHED','returncode':0}
            with patch.object(runtime, 'run_capture', side_effect=query) as run:
                result = helper.discover_dependencies([str(owner), str(owner)], tool=sys.executable,
                    report_dir=root/'reports', environment={}, runtime=runtime)
            return result, run.call_count

    def test_universal_headers_keep_both_architecture_dependencies_once(self):
        for package in (PACKAGES/'python-environment/2', PACKAGES/'qt-cmake/3'):
            with self.subTest(package=package.name):
                result, calls = self.observe(package)
                self.assertEqual(result['status'], 'OBSERVED', result['issues'])
                self.assertEqual(len(result['files']), 3)
                self.assertEqual(calls, 3)

    def test_unrelated_headers_and_unknown_lines_remain_errors(self):
        for package in (PACKAGES/'python-environment/2', PACKAGES/'qt-cmake/3'):
            for line in ('/another/library (architecture arm64):', 'unrecognized diagnostic text'):
                with self.subTest(package=package.name, line=line):
                    result, _ = self.observe(package, line)
                    self.assertEqual(result['status'], 'ERROR')
                    self.assertFalse(result['complete'])
                    self.assertTrue(result['operations'])
