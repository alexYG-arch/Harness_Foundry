"""Local process protocol fixture. This is NOT Codex or target build evidence."""

from pathlib import Path
import sys


if "--help" in sys.argv:
    print("TEST FIXTURE ONLY: exec --sandbox --skip-git-repo-check")
    raise SystemExit(0)
if "--fixture-fail" in sys.argv:
    print("TEST FIXTURE ONLY: requested process failure", file=sys.stderr)
    raise SystemExit(23)

root = Path.cwd()
(root / "src/fixture_package").mkdir(parents=True)
(root / "tests").mkdir()
(root / "pyproject.toml").write_text('[project]\nname="process-fixture-only"\nversion="0.0.0"\n')
(root / "src/fixture_package/__init__.py").write_text('"""Not a generated Harness."""\n')
(root / "tests/test_process_fixture.py").write_text(
    "import unittest\n"
    "class ProcessFixtureTest(unittest.TestCase):\n"
    "    def test_observed_test_process(self):\n"
    "        self.assertEqual(2 + 2, 4)\n"
)
print("TEST FIXTURE ONLY: materialized a structural test package, not Codex output")
