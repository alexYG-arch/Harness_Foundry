import json
from pathlib import Path
import tempfile
from unittest import TestCase

from harness_foundry_factory.artifact_descriptors import diagnose_candidate_hash_projections


class CandidateHashDiagnosticTests(TestCase):
    def test_real_document_projection_inventory_is_nonblocking_not_cost_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "validation").mkdir()
            content = json.dumps({"entries": [{"input_ref": "candidate://input", "input_sha256": "a" * 64}] * 2})
            (root / "validation/CASE_EXECUTION_MANIFEST.json").write_text(content)
            report = diagnose_candidate_hash_projections(root)
            self.assertFalse(report["blocking"])
            self.assertEqual(report["projection_count"], 2)
            self.assertEqual(report["unique_referenced_objects"], 1)
            self.assertEqual(report["redundant_digest_computations"], "NOT_MEASURED")
            self.assertEqual(report["diagnostic_cost"]["bytes_read"], len(content.encode()))
            self.assertEqual(report["diagnostic_cost"]["digest_computations"], 0)

    def test_missing_optional_diagnostic_input_does_not_change_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(diagnose_candidate_hash_projections(directory)["blocking"])
