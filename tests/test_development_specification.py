"""Pinned historical source input; no external sibling or retired public route."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.constants import (
    default_spec_lock_path, default_spec_root, historical_spec_lock_path,
)
from harness_foundry_factory.spec_lock import (
    DEVELOPMENT_LOCK_KIND, DEVELOPMENT_ROOT_BINDING, SPEC_ROOT_BINDING,
    SpecLockError, build_spec_lock, load_spec_lock, verify_spec_lock,
)


ROOT = Path(__file__).resolve().parents[1]


class DevelopmentSpecificationTests(unittest.TestCase):
    def test_source_dependency_is_exact_historical_content(self):
        historical = load_spec_lock(historical_spec_lock_path())
        development = load_spec_lock()
        self.assertEqual(development['files'], historical['files'])
        self.assertEqual(development['content_sha256'], historical['content_sha256'])
        self.assertEqual(development['file_count'], 101)
        self.assertEqual(development['historical_lock_sha256'], hashlib.sha256(historical_spec_lock_path().read_bytes()).hexdigest())
        self.assertEqual(historical['spec_root_binding'], SPEC_ROOT_BINDING)
        self.assertEqual(development['lock_kind'], DEVELOPMENT_LOCK_KIND)
        self.assertEqual(development['spec_root_binding'], DEVELOPMENT_ROOT_BINDING)
        self.assertEqual(build_spec_lock(), development)

    def test_relocated_clean_source_verifies_without_a_sibling(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / 'clean source 汉'
            shutil.copytree(ROOT / 'src', copy / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            shutil.copytree(ROOT / 'spec_lock', copy / 'spec_lock')
            relative = default_spec_root().relative_to(ROOT)
            shutil.copytree(default_spec_root(), copy / relative)
            code = (
                'import json,sys;sys.path.insert(0,sys.argv[1]);'
                'from harness_foundry_factory.constants import default_spec_root;'
                'from harness_foundry_factory.spec_lock import load_spec_lock,verify_spec_lock;'
                'r=verify_spec_lock(load_spec_lock());print(json.dumps(r));'
                'raise SystemExit(0 if r["status"]=="PASS" else 1)'
            )
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(copy / 'src')],
                                    cwd=copy, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report['checked_files'], 101)
            self.assertTrue(Path(report['spec_root']).is_relative_to(copy.resolve()))
            self.assertFalse((copy.parent / 'Harness_Foundry_v2_8_Start_Package').exists())

    def test_historical_lock_still_verifies_only_its_physical_binding(self):
        historical = load_spec_lock(historical_spec_lock_path())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'Harness_Foundry_v2_8_Start_Package'
            shutil.copytree(default_spec_root(), root)
            with patch('harness_foundry_factory.spec_lock.historical_spec_root', return_value=root):
                self.assertEqual(verify_spec_lock(historical)['status'], 'PASS')
                self.assertEqual(build_spec_lock(root), historical)
                wrong = verify_spec_lock(historical, default_spec_root())
                self.assertEqual(wrong['findings'][0]['code'], 'SPEC_PATH_MISMATCH')

    def test_historical_symlink_remains_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'Harness_Foundry_v2_8_Start_Package'
            root.symlink_to(default_spec_root(), target_is_directory=True)
            with patch('harness_foundry_factory.spec_lock.historical_spec_root', return_value=root):
                with self.assertRaises(SpecLockError):
                    build_spec_lock(root)
                self.assertEqual(verify_spec_lock(load_spec_lock(historical_spec_lock_path()))['status'], 'FAIL')

    def test_missing_changed_and_extra_files_do_not_fall_back_to_sibling(self):
        for mutation in ('missing', 'changed', 'added'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'Harness_Foundry_v2_8_Start_Package'
                shutil.copytree(default_spec_root(), root)
                if mutation == 'missing':
                    (root / 'README.md').unlink()
                elif mutation == 'changed':
                    (root / 'README.md').write_text('changed historical document')
                else:
                    (root / 'unexpected.txt').write_text('not declared')
                with patch('harness_foundry_factory.spec_lock.default_spec_root', return_value=root):
                    report = verify_spec_lock(load_spec_lock())
                    self.assertEqual(report['status'], 'FAIL')
                    self.assertIn('SPEC_FILES_' + {'missing':'MISSING','changed':'CHANGED','added':'ADDED'}[mutation],
                                  [item['code'] for item in report['findings']])
                    with self.assertRaises(SpecLockError):
                        build_spec_lock()

    def test_development_location_is_explicit_not_arbitrary_override(self):
        report = verify_spec_lock(load_spec_lock(), Path('/not-the-declared-source'))
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['findings'][0]['code'], 'SPEC_PATH_MISMATCH')

    def test_historical_lock_digest_and_development_binding_are_checked(self):
        for field in ('historical_lock_ref', 'historical_lock_sha256', 'spec_root_relative'):
            with self.subTest(field=field):
                changed = deepcopy(load_spec_lock())
                changed[field] = 'wrong'
                report = verify_spec_lock(changed)
                self.assertEqual(report['status'], 'FAIL')

    def test_generic_runtime_inventory_has_no_specification_dependency(self):
        path = ROOT / 'devtools/package_generic_release.py'
        spec = importlib.util.spec_from_file_location('spec_dependency_generic_inventory', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        files = module.collect_files(ROOT)
        names = set(files)
        self.assertFalse(any(name.startswith(('spec_lock/', 'devtools/specifications/')) for name in names))
        self.assertNotIn('src/harness_foundry_factory/spec_lock.py', names)
        self.assertNotIn('src/harness_foundry_factory/constants.py', names)


if __name__ == '__main__':
    unittest.main()
