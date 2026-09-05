import json
from pathlib import Path
import tempfile
from unittest import TestCase

from harness_foundry_factory.contract_references import pointer_values, resolve_candidate_operand


class ContractReferenceTests(TestCase):
    def test_missing_member_is_not_silently_dropped(self):
        with self.assertRaises(KeyError):
            pointer_values({"cases": [{"result_ref": "a"}, {}]}, "/cases/*/result_ref")
        self.assertEqual(pointer_values({"cases": []}, "/cases/*/result_ref"), [])

    def test_candidate_alias_and_standard_uri_resolve_same_fragment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cases.json").write_text(json.dumps({"cases": [{"result_ref": "a"}]}))
            for prefix in ("candidate://", "harness-resource://candidate/"):
                self.assertEqual(resolve_candidate_operand(root, prefix + "cases.json#/cases/*/result_ref"), ["a"])
                with self.assertRaises(KeyError):
                    resolve_candidate_operand(root, prefix + "cases.json#/acceptance_case_invocations/*/result_ref")
