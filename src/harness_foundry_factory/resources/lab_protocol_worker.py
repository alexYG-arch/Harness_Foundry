#!/usr/bin/env python3
"""Run only as the approved offline worker, never import targets in the controller."""

import argparse
from contextlib import redirect_stdout, redirect_stderr
import importlib
import io
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
checks = importlib.import_module("harness_foundry_runtime.lab_protocol_checks")
contract_checks = importlib.import_module("harness_foundry_runtime.lab_protocol_contract_checks")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--schema-file", type=Path, required=True)
    args = parser.parse_args()
    scope = "LAB_PROTOCOL_PRIMITIVES_AND_FROZEN_DECLARATIONS"
    result = {"status": "INCONCLUSIVE", "evidence_scope": scope, "cases": [],
              "workpack_accepted": False, "execution_authorized": False,
              "implementation_module": "external_lab.protocol"}
    try:
        root = args.project_root.resolve(strict=True)
        expected = root / "external_lab/protocol.py"
        if not expected.is_file() or expected.resolve() != expected:
            raise ValueError("selected project's external_lab/protocol.py is absent or linked")
        interface = json.loads(args.schema_file.read_bytes())
        # These inputs belong to the same fixed Candidate as --schema-file;
        # neither the project nor its report chooses a replacement registry.
        candidate = args.schema_file.parent.parent
        registry = json.loads((candidate / "validation/ORACLE_EVALUATOR_REGISTRY.json").read_bytes())
        catalog = json.loads((candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json").read_bytes())["target"].get("artifact_schema_catalog", {})
        sys.path.insert(0, str(root))
        # Incidental project prints are not the worker result protocol.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            api = importlib.import_module("external_lab.protocol")
            if Path(api.__file__).resolve() != expected:
                raise ValueError("imported implementation is not the selected project")
            primitive = checks.verify_protocol_primitives(api, interface["job_request_schema"])
            frozen = contract_checks.verify_frozen_protocol_contract(api, interface, registry, catalog)
            statuses = {primitive["status"], frozen["status"]}
            result.update(cases=primitive["cases"], frozen_contract_checks=frozen,
                          status="FAIL" if "FAIL" in statuses else "INCONCLUSIVE" if "INCONCLUSIVE" in statuses else "PASS")
    except Exception as exc:
        result["status"] = "INCONCLUSIVE"
        result["diagnostic"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
