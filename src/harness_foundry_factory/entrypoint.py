"""One production build route; historical creation commands are retired."""

import json
import sys


# Source-engineering diagnostics only. None advances a historical Program.
DIAGNOSTIC_COMMANDS = frozenset({"verify-spec", "validate-core", "project-core-evidence", "self-check-diagnostic"})

RETIRED_COMMANDS = frozenset({
    "chat-turn", "status", "readback", "requirement-readback", "architecture-readback",
    "compile", "advance-authoring-until-gate", "advance-until-gate", "checkpoint", "resume",
    "explain-stop", "prepare-runtime-authorization", "approve-runtime-authorization",
    "revoke-runtime-authorization", "prepare-execution-handoff", "validate-candidate",
    "verify-run", "package-local",
})


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    command = arguments[0] if arguments else None
    if command in RETIRED_COMMANDS:
        print(json.dumps({"status": "ERROR", "error": {"code": "LEGACY_WORKFLOW_RETIRED",
            "message": "Historical creation, generation and execution are retired. Use the reviewed generic Build route; use read-history for stored records."},
            "writes_performed": False, "execution_started": False, "legacy_fallback_available": False}))
        return 2
    if command in DIAGNOSTIC_COMMANDS:
        from .cli import _baseline_main
        return _baseline_main(arguments)
    from .build_cli import main as run
    return run(arguments)
