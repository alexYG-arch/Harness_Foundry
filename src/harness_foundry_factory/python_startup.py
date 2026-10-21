"""Explain the existing Python minimum before importing the runtime.

Keep this bootstrap readable by older Python interpreters. It diagnoses only;
it never selects another interpreter, changes PATH or starts another process.
"""

import json
from pathlib import Path
import shlex
import sys


MINIMUM_PYTHON = (3, 11)


def require_supported_python(argv=None, *, launcher=None, module=None):
    if sys.version_info[:2] >= MINIMUM_PYTHON:
        return
    arguments = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[2]
    # Keep the venv invocation path, not its resolved binary target. This is a
    # suggested command only; the named environment is not run or repaired.
    candidate = root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    suggested = str(candidate) if candidate.is_file() else "<configured-python-3.11-or-newer>"
    if launcher is None and module is None:
        script = root / "tools/hffactory.py"
        if script.is_file():
            launcher = str(script)
        else:
            module = "harness_foundry_factory.build_cli"
    invocation = ["-m", module] if module else [str(launcher)]
    retry = [suggested, "-B", *invocation, *arguments]
    version = ".".join(str(value) for value in sys.version_info[:3])
    message = "Foundry requires Python >=3.11; current interpreter is {} ({})".format(sys.executable, version)
    result = {"schema_version": "1.0", "status": "ERROR", "error": {
        "code": "UNSUPPORTED_PYTHON_VERSION", "message": message,
        "details": {"python_executable": sys.executable, "python_version": version,
                    "requires_python": ">=3.11", "suggested_argv": retry,
                    "suggested_interpreter_verified": False}},
        "writes_performed": False, "execution_started": False}
    if "--json" in arguments:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(message + "\nRun with your declared Python >=3.11 interpreter; for example:\n"
              + shlex.join(retry) + "\nThe suggested interpreter has not been executed or verified.", file=sys.stderr)
    raise SystemExit(2)
