"""Pure real-package handoffs; fixture SDK/tools do not claim native usability."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / 'examples/capability-adapters'
PACKAGES = ADAPTERS / 'packages'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


QT = load(PACKAGES / 'qt-cmake/2/qt_environment.py', 'integration_qt')
PYTHON = load(PACKAGES / 'python-environment/1/python_environment.py', 'integration_python')
UPGRADE = load(ADAPTERS / 'upgrade.py', 'integration_upgrade')
PREPARE = UPGRADE._prepare


class StackEnvironmentIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='stack handoff 中文 ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.sources = self.root / 'project sources'
        self.sources.mkdir()
        (self.sources / 'brief.md').write_bytes(b'# Retained project\r\nUse custom units.\r\n')
        self.sdk = self.sdk_fixture('SDK old')
        self.cmake = self.root / 'fixture-cmake'
        self.cmake.write_text('#!/bin/sh\nexit 99\n')
        self.cmake.chmod(0o755)
        self.ctest = self.root / 'fixture-ctest'
        self.ctest.write_bytes(self.cmake.read_bytes())
        self.ctest.chmod(0o755)
        self.tools = {'qt-python':sys.executable,'cmake':str(self.cmake),'ctest':str(self.ctest)}
        project_modules = self.project / 'src'
        project_modules.mkdir()
        self.py_profile = PYTHON.bind(sys.executable, [str(project_modules)])
        self.py_path = self.root / 'python-profile.json'
        self.py_path.write_text(json.dumps(self.py_profile))
        self.qt_profile = QT.discover(self.tools, [str(self.sdk)])['profile']
        self.qt_path = self.root / 'qt-profile.json'
        self.qt_path.write_text(json.dumps(self.qt_profile))
        self.base = {'source_manifest':[{'source_id':'BRIEF','path':'brief.md'}],
            'request':{'requirement_ir':{'sources':[{'source_id':'BRIEF','path_or_uri':'brief.md','loaded_completely':True}],
                         'atoms':[{'atom_id':'UNITS','text_or_lossless_paraphrase':'Use custom units'}]},
                       'plan':{'workpacks':[{'workpack_id':'MAKE','goal':'Preserve custom units',
                                            'inputs':[{'kind':'SOURCE','id':'BRIEF'}]}]}},
            'scope':{'workspace_root':str(self.project),'task_write_roots':{'MAKE':['output']},
                     'executables':{'python':sys.executable},'source_read_roots':[],
                     'max_attempts':7,'max_task_attempts':4},
            'preparation':{'next':'Return to the original host','verifier_inputs':[]}}
        self.bindings = {'python':{'path':sys.executable,'observed_version':'.'.join(map(str,sys.version_info[:3]))},
            'qt-python':{'path':sys.executable,'observed_version':'.'.join(map(str,sys.version_info[:3]))},
            'project-python':{'path':sys.executable,'observed_version':'.'.join(map(str,sys.version_info[:3]))},
            'cmake':{'path':str(self.cmake),'observed_version':'3.31.12'},
            'ctest':{'path':str(self.ctest),'observed_version':'3.31.12'},'qt-sdk':{'path':str(self.sdk)}}

    def sdk_fixture(self, name):
        sdk = self.root / name
        config = sdk / 'lib/cmake/Qt6/Qt6Config.cmake'
        config.parent.mkdir(parents=True)
        config.write_text('# Pure fixture, not a usable SDK\n')
        core = sdk / 'lib/QtCore.framework/Versions/A/QtCore'
        core.parent.mkdir(parents=True)
        core.write_bytes(name.encode())
        return sdk

    def config(self, qt_version):
        selections = [{'directory':str(PACKAGES / 'python-environment/1'),'version':'1',
                       'workpack_ids':['MAKE'],'environment_profile':str(self.py_path)}]
        if qt_version is not None:
            qt = {'directory':str(PACKAGES / 'qt-cmake' / qt_version),'version':qt_version,'workpack_ids':['MAKE']}
            if qt_version == '2': qt['environment_profile'] = str(self.qt_path)
            selections.insert(0, qt)
        return {'project_root':str(self.project),'source_root':str(self.sources),
                'base_materials':deepcopy(self.base),'selections':selections,'environment_bindings':deepcopy(self.bindings)}

    def test_selected_real_package_upgrade_retains_other_stack_project_and_budget(self):
        config = self.config('1')
        del config['environment_bindings']['cmake']['observed_version']
        old = PREPARE.write_materials(config, self.root / 'old-materials')
        self.assertEqual(old['preparation']['readiness'], 'INCOMPLETE')
        before = deepcopy(old)
        old_files = {str(p):p.read_bytes() for p in (self.root / 'old-materials').rglob('*') if p.is_file()}
        with patch('subprocess.Popen', side_effect=AssertionError('material upgrade cannot execute')):
            new, files, transition = UPGRADE.build_upgrade(old, self.config('2'), self.root / 'next-materials')
            removed, _, removal = UPGRADE.build_upgrade(new, self.config(None), self.root / 'remove-qt-materials')
        self.assertEqual(old, before)
        self.assertTrue(all(Path(path).read_bytes() == raw for path, raw in old_files.items()))
        self.assertEqual(new['preparation']['readiness'], 'READY')
        changes = {row['name']:row['changes'] for row in transition['packages']}
        self.assertIn('VERSION_CHANGED', changes['qt-cmake'])
        self.assertEqual(changes['python-environment'], ['UNCHANGED'])
        for value in (new, removed):
            self.assertEqual(value['request']['requirement_ir']['atoms'], self.base['request']['requirement_ir']['atoms'])
            self.assertEqual(value['request']['plan']['workpacks'][0]['goal'], 'Preserve custom units')
            self.assertEqual(value['scope']['max_attempts'], 7)
            self.assertEqual(value['scope']['max_task_attempts'], 4)
            self.assertEqual(value['tool_bindings']['python-environment'], old['tool_bindings']['python-environment'])
            python_binding = next(row for row in value['preparation']['stack_profiles'] if row['package'] == 'python-environment')
            old_python = next(row for row in old['preparation']['stack_profiles'] if row['package'] == 'python-environment')
            self.assertEqual(python_binding['sha256'], old_python['sha256'])
        self.assertEqual(files['sources/brief.md'], (self.sources / 'brief.md').read_bytes())
        self.assertTrue(transition['previous_diagnostics'])
        for report in (transition, removal):
            for key in ('commands_executed','target_modified','acceptance_granted','authority_inherited','budget_modified'):
                self.assertFalse(report[key])
        self.assertEqual({r['name']:r['changes'] for r in removal['packages']}['qt-cmake'], ['REMOVED'])

    def test_sdk_alias_retarget_keeps_pinned_old_profile_until_new_discovery(self):
        alias = self.root / 'selected SDK'
        alias.symlink_to(self.sdk, target_is_directory=True)
        old = QT.discover(self.tools, [str(alias)])['profile']
        profile_path = self.root / 'old-pinned.json'
        profile_path.write_text(json.dumps(old))
        original = profile_path.read_bytes()
        next_sdk = self.sdk_fixture('SDK new')
        alias.unlink()
        alias.symlink_to(next_sdk, target_is_directory=True)
        with patch('subprocess.Popen', side_effect=AssertionError('discovery cannot execute')):
            loaded = QT.load_profile(profile_path)
            new = QT.discover(self.tools, [str(alias)])['profile']
        self.assertEqual(loaded['extensions']['qt']['sdk'], str(self.sdk))
        self.assertEqual(new['extensions']['qt']['sdk'], str(next_sdk))
        self.assertEqual(loaded['extensions']['qt']['sdk_requested'], [str(alias)])
        self.assertIn('Qt6_DIR:PATH=' + str(self.sdk / 'lib/cmake/Qt6'), QT.configure_definitions(loaded, []))
        self.assertIn('Qt6_DIR:PATH=' + str(next_sdk / 'lib/cmake/Qt6'), QT.configure_definitions(new, []))
        self.assertNotEqual(QT.runtime.profile_digest(loaded), QT.runtime.profile_digest(new))
        self.assertEqual(profile_path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
