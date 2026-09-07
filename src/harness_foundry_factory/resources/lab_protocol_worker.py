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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--schema-file", type=Path, required=True)
    args = parser.parse_args()
    result = {"status": "INCONCLUSIVE", "evidence_scope": "LAB_PROTOCOL_PRIMITIVES_ONLY", "cases": [],
              "workpack_accepted": False, "execution_authorized": False,
              "implementation_module": "external_lab.protocol"}
    try:
        root = args.project_root.resolve(strict=True)
        expected = root / "external_lab/protocol.py"
        if not expected.is_file() or expected.resolve() != expected:
            raise ValueError("selected project's external_lab/protocol.py is absent or linked")
        schema = json.loads(args.schema_file.read_bytes())["job_request_schema"]
        sys.path.insert(0, str(root))
        # Incidental project prints are not the worker result protocol.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            api = importlib.import_module("external_lab.protocol")
            if Path(api.__file__).resolve() != expected:
                raise ValueError("imported implementation is not the selected project")
            result.update(checks.verify_protocol_primitives(api, schema))
    except Exception as exc:
        result["diagnostic"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
